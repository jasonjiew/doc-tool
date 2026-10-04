# -*- coding: utf-8 -*-
"""Refresh TOC/fields in a dedicated Microsoft Word process.

The public process supervises a worker with a configured timeout.  The worker
uses DispatchEx so an automation failure never quits an existing user-owned
Word session.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from typing import Optional, Sequence, Tuple

from docx_common import AutomationError, discover_document_types, load_config


def _get_winword_pids() -> set:
    """获取系统当前所有 WINWORD.EXE 进程的 PID 集合。"""
    if os.name != "nt":
        return set()
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1 or h_snap == 0xFFFFFFFF:
            return set()
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        pids = set()
        try:
            if kernel32.Process32First(h_snap, ctypes.byref(pe)):
                while True:
                    if pe.szExeFile.lower() == b"winword.exe":
                        pids.add(int(pe.th32ProcessID))
                    if not kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                        break
        finally:
            kernel32.CloseHandle(h_snap)
        return pids
    except Exception:
        return set()


def _word_pid(word, pids_before: Optional[set] = None) -> Optional[int]:
    """精准获取 Word 进程的 PID。
    
    Word.Application 对象没有 .Hwnd 属性；通过启动前后差集与 ActiveWindow 提取 PID。
    """
    if pids_before is not None:
        try:
            pids_after = _get_winword_pids()
            diff = pids_after - pids_before
            if diff:
                return next(iter(diff))
        except Exception:
            pass
    try:
        import win32process

        if hasattr(word, "ActiveWindow") and word.ActiveWindow is not None:
            return int(win32process.GetWindowThreadProcessId(int(word.ActiveWindow.Hwnd))[1])
    except Exception:
        pass
    try:
        import win32process

        hwnd = getattr(word, "Hwnd", None)
        if hwnd:
            return int(win32process.GetWindowThreadProcessId(int(hwnd))[1])
    except Exception:
        pass
    return None


def _kill_process_tree(pid: Optional[int]) -> None:
    if not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except Exception:
        # 清理失败不遮蔽原始结果：任务仍在停止预算内返回。
        pass


# 刷新失败原因键：worker 经 stderr 输出 [REASON] 标记，supervise 透传给管线
# 映射稳定错误码（E3002 超时 / E3003 保存失败 / E3001 其余）。
REASON_OK = "ok"
REASON_TIMEOUT = "timeout"
REASON_WORD_UNAVAILABLE = "word_unavailable"
REASON_SAVE_FAILED = "save_failed"
REASON_REFRESH_FAILED = "refresh_failed"

_REASON_MARKER = "[REASON] "
_REASON_KEYS = (
    REASON_OK,
    REASON_TIMEOUT,
    REASON_WORD_UNAVAILABLE,
    REASON_SAVE_FAILED,
    REASON_REFRESH_FAILED,
)

# --- V4.0 40-B：阶段事实（跨进程用 stderr 标记传递，不引入第二套业务） ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from doc_tool.domain.word_operations import (  # noqa: E402
    STAGE_ENTER,
    STAGE_LABELS,
    STAGE_OPEN,
    STAGE_PENDING,
    STAGE_PROCESS,
    STAGE_QUIT,
    STAGE_SAVE,
    STAGE_START,
    WordOperationReport,
    budgets_for_timeout,
    ownership_from_pid_diff,
    parse_stage_markers,
    stage_marker,
    stop_and_cleanup,
)


def _publish_report(report) -> None:
    """把真实阶段事实写入 ``LAST_REPORT``（只增不改的旁路事实）。"""
    try:
        LAST_REPORT.clear()
        LAST_REPORT.update(report.to_dict())
    except Exception:  # noqa: BLE001 - 事实记录失败不影响刷新结果
        pass


def _report_stage(stage: str, detail: str = "") -> None:
    """向监督进程报告真实阶段（stderr 标记；失败不影响刷新本身）。"""
    try:
        print(stage_marker(stage, detail), file=sys.stderr, flush=True)
    except Exception:
        pass


def _classify_failure(exc: BaseException) -> str:
    """把 worker 失败原因分类为稳定键。"""
    text = str(exc)
    lower = text.lower()
    if "保存" in text or "save" in lower:
        return REASON_SAVE_FAILED
    if (
        "pywin32" in lower
        or "win32com" in lower
        or "word.application" in lower
        or "没有注册类" in text
        or "拒绝访问" in text
    ):
        return REASON_WORD_UNAVAILABLE
    return REASON_REFRESH_FAILED


def _scan_reason(err_bytes: bytes) -> str:
    """从 worker stderr 提取 [REASON] 标记；缺失时按一般刷新失败处理。"""
    for line in err_bytes.splitlines():
        stripped = line.decode("utf-8", errors="replace").strip()
        if stripped.startswith(_REASON_MARKER):
            key = stripped[len(_REASON_MARKER):].strip()
            if key in _REASON_KEYS:
                return key
    return REASON_REFRESH_FAILED


def _open_document(word, path: str, read_only: bool):
    return word.Documents.Open(
        FileName=os.path.abspath(path),
        ConfirmConversions=False,
        ReadOnly=read_only,
        AddToRecentFiles=False,
        Revert=False,
        Visible=False,
        OpenAndRepair=False,
        NoEncodingDialog=True,
    )


def _update_all_story_fields(document) -> None:
    # Word defines 17 story types.  Not every document contains every type.
    for story_type in range(1, 18):
        try:
            story = document.StoryRanges(story_type)
        except Exception:
            continue
        while story is not None:
            try:
                story.Fields.Update()
            except Exception:
                pass
            try:
                story = story.NextStoryRange
            except Exception:
                break


def refresh_worker(
    document: Optional[str] = None,
    output_path: Optional[str] = None,
    pid_holder: Optional[dict] = None,
) -> int:
    try:
        import win32com.client
    except ImportError as exc:
        print("[FAIL] 未安装 pywin32，无法刷新 Word 域: {0}".format(exc), file=sys.stderr, flush=True)
        print("{0}{1}".format(_REASON_MARKER, REASON_WORD_UNAVAILABLE), file=sys.stderr, flush=True)
        return 1

    if output_path is None:
        if document is None:
            print("[FAIL] 刷新工作进程缺少输出路径", file=sys.stderr, flush=True)
            return 1
        config = load_config(document)
        output_path = config["paths"]["output"]
    output = os.path.abspath(output_path)
    if not os.path.isfile(output):
        print("[FAIL] 待刷新文档不存在: {0}".format(output), file=sys.stderr, flush=True)
        print("{0}{1}".format(_REASON_MARKER, REASON_REFRESH_FAILED), file=sys.stderr, flush=True)
        return 1
    # 显示标签：项目上下文无 doc_type 时用文件名替代，避免消息出现 None。
    if document is None:
        document = os.path.basename(output)

    word = None
    opened = None
    word_pid = None
    try:
        _report_stage(STAGE_ENTER, "等待可用的 Word 会话")
        pids_before = _get_winword_pids()
        _report_stage(STAGE_START, "启动专用 Word 实例")
        word = win32com.client.DispatchEx("Word.Application")
        word_pid = _word_pid(word, pids_before)
        if pid_holder is not None and word_pid:
            pid_holder["pid"] = word_pid
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        # msoAutomationSecurityForceDisable: never execute document macros.
        try:
            word.AutomationSecurity = 3
        except Exception:
            pass

        print("[{0}] Word 打开并刷新: {1}".format(document, output), flush=True)
        _report_stage(STAGE_OPEN, "打开待刷新文档")
        opened = _open_document(word, output, read_only=False)
        if not word_pid:
            word_pid = _word_pid(word)
            if pid_holder is not None and word_pid:
                pid_holder["pid"] = word_pid
        _report_stage(STAGE_PROCESS, "更新域与目录")
        _update_all_story_fields(opened)
        for index in range(1, int(opened.TablesOfContents.Count) + 1):
            opened.TablesOfContents(index).Update()
        try:
            opened.Repaginate()
        except Exception:
            pass
        _update_all_story_fields(opened)
        _report_stage(STAGE_SAVE, "保存刷新结果")
        opened.Save()
        opened.Close(SaveChanges=False)
        opened = None

        # A clean read-only reopen catches Word's repair dialog/corrupt-package
        # cases before the command reports success.
        opened = _open_document(word, output, read_only=True)
        if not bool(opened.ReadOnly):
            raise AutomationError("只读复打开验证失败")
        opened.Close(SaveChanges=False)
        opened = None
        print("[{0}] TOC、NUMPAGES 与全部 story 域刷新完成".format(document), flush=True)
        return 0
    except Exception as exc:
        print("[{0}] [FAIL] Word 刷新失败: {1!r}".format(document, exc), file=sys.stderr, flush=True)
        print("{0}{1}".format(_REASON_MARKER, _classify_failure(exc)), file=sys.stderr, flush=True)
        return 1
    finally:
        if opened is not None:
            try:
                opened.Close(SaveChanges=False)
            except Exception:
                pass
        if word is not None:
            _report_stage(STAGE_QUIT, "退出 Word")
            try:
                word.Quit(SaveChanges=False)
            except Exception:
                _kill_process_tree(word_pid)


#: 最近一次监督的真实阶段/归属/清理事实（供界面诊断读取，不参与业务判断）。
#: 历史调用方仍只拿 ``(是否成功, 原因键)``，此处是只增不改的旁路事实。
LAST_REPORT: dict = {}


def _bounded_supervise_in_thread(
    document: Optional[str],
    output_path: str,
    timeout: int,
    label: str,
) -> Tuple[bool, str, Optional[WordOperationReport]]:
    """在工作线程内**有界**监督 Word 刷新，并登记真实阶段/归属/清理事实。

    用于 PyInstaller 冻结环境（此时 sys.executable 是 DocTool.exe，无法作为
    Python 脚本执行器直接拉起 refresh_fields.py）或限制子进程时的安全执行。

    与旧实现的差别只有“事实更完整”：阶段来自 worker 的真实标记，超时后按
    停止预算确认终止；归属不可证明时只留残留事实，绝不按进程名清理用户 Word。
    """
    import contextlib
    import io
    import threading

    report = WordOperationReport(
        operation="word-refresh", source=document or "", target=output_path,
        budgets=budgets_for_timeout(timeout),
    )
    res = {"code": 1}
    holder = {"pid": None, "pidsBefore": None}
    stderr_buf = io.StringIO()
    stream_lock = threading.Lock()

    def _consume(text: str) -> None:
        for stage_name, detail in parse_stage_markers(text):
            with stream_lock:
                report.stage(stage_name, detail, outcome=STAGE_PENDING)

    def _worker() -> None:
        try:
            try:
                import pythoncom

                pythoncom.CoInitialize()
            except Exception:
                pass
            with contextlib.redirect_stderr(_TeeStream(stderr_buf, _consume)):
                res["code"] = refresh_worker(
                    document=document,
                    output_path=output_path,
                    pid_holder=holder,
                )
        except Exception as exc:
            stderr_buf.write("[{0}] [FAIL] Word 刷新失败: {1!r}\n".format(label, exc))
            stderr_buf.write("{0}{1}\n".format(_REASON_MARKER, _classify_failure(exc)))
            res["code"] = 1
        finally:
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:
                pass

    thread = threading.Thread(
        target=_worker, name="doc-tool-word-refresh-thread", daemon=True
    )
    started = time.monotonic()
    thread.start()
    thread.join(float(timeout))

    if thread.is_alive():
        stage = report.currentStage or STAGE_PROCESS
        report.note_timeout(
            stage,
            "阶段「{0}」超过预算 {1} 秒，已按停止预算处理".format(
                STAGE_LABELS.get(stage, stage), timeout
            ),
        )
        pid = holder.get("pid")
        report.set_ownership(
            ownership_from_pid_diff(pid, holder.get("pidsBefore") or [])
        )
        stop = stop_and_cleanup(
            report,
            kill=(lambda: _kill_process_tree(pid)) if pid else None,
            is_alive=thread.is_alive,
        )
        thread.join(max(0.0, float(report.budgets.cleanup)))
        if thread.is_alive():
            report.note_residual("刷新线程在停止预算内仍在回收中")
        print(
            "[{0}] [FAIL] Word 刷新超过 {1} 秒，{2}".format(label, timeout, stop.summary_line()),
            file=sys.stderr,
            flush=True,
        )
        elapsed = time.monotonic() - started
        if report.stage_fact(stage) is not None:
            report.stage_fact(stage).elapsedSeconds = elapsed
        return (False, REASON_TIMEOUT, report)

    err_text = stderr_buf.getvalue()
    _consume(err_text)
    if err_text:
        sys.stderr.write(err_text)
        sys.stderr.flush()

    if res["code"] == 0:
        return (True, REASON_OK, report)
    reason = _scan_reason(err_text.encode("utf-8", errors="replace"))
    if not report.stages:
        report.stage(
            STAGE_START if reason == REASON_WORD_UNAVAILABLE else STAGE_PROCESS,
            "刷新未完成（{0}）".format(reason), outcome="failed",
        )
    return (False, reason, report)


class _TeeStream:
    """把 stderr 同时写入缓冲与阶段解析器（不改变字符内容）。"""

    def __init__(self, buffer, consumer) -> None:
        self._buffer = buffer
        self._consumer = consumer

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer.write(text)
        if "[DOC-TOOL-STAGE]" in text:
            self._consumer(text)
        return len(text)

    def flush(self) -> None:
        return None


def _supervise_in_thread(
    document: Optional[str],
    output_path: str,
    timeout: int,
    label: str,
) -> Tuple[bool, str]:
    """兼容入口：仍返回 ``(是否成功, 原因键)``，真实事实写入 ``LAST_REPORT``。"""
    ok, reason, report = _bounded_supervise_in_thread(document, output_path, timeout, label)
    LAST_REPORT.clear()
    if report is not None:
        LAST_REPORT.update(report.to_dict())
    return (ok, reason)


def supervise(
    document: Optional[str] = None,
    output_path: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Supervise the Word refresh worker with a timeout.

    Project context callers pass ``output_path`` and ``timeout`` directly;
    legacy callers pass ``document`` and the config is loaded from disk.

    Returns:
        ``(是否成功, 原因键)``：``ok / timeout / word_unavailable /
        save_failed / refresh_failed``，供管线映射稳定错误码——旧实现只返回
        bool，超时/保存失败被上层一律当作「Word 不可用」（E3001）误报。
    """
    if output_path is None or timeout is None:
        if document is None:
            raise AutomationError("必须提供 document 或 output_path 参数")
        config = load_config(document)
        if output_path is None:
            output_path = config["paths"]["output"]
        if timeout is None:
            timeout = int(config.get("refresh", {}).get("timeoutSeconds", 900))
    label = document or os.path.basename(output_path)

    # 在 PyInstaller 冻结环境下，sys.executable 是 DocTool.exe 而非 python 解释器；
    # 重新拉起会导致重复启动图形主窗口或命令行参数不识别。
    # 此时切换为线程监督模式，同样具备超时看门狗与专用 Word 进程清理保护。
    is_frozen = bool(getattr(sys, "frozen", False)) or (
        os.path.basename(sys.executable).lower()
        not in ("python.exe", "pythonw.exe", "python3.exe", "python")
    )
    if is_frozen:
        return _supervise_in_thread(
            document=document,
            output_path=output_path,
            timeout=timeout,
            label=label,
        )

    command = [
        sys.executable,
        os.path.abspath(__file__),
        "--worker",
        "--output",
        os.path.abspath(output_path),
    ]
    # 捕获 worker stderr：失败细节与 [REASON] 标记经父进程 stderr 透出，
    # 保持原命令行可见性的同时让管线拿到稳定原因键。阶段标记同路回传，
    # 由后台读取线程实时解析，超时后仍能说明“卡在哪一步”。
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    report = WordOperationReport(
        operation="word-refresh", source=document or "", target=output_path,
        budgets=budgets_for_timeout(timeout),
    )
    chunks: list = []

    def _reader() -> None:
        try:
            for raw in iter(process.stderr.readline, b""):
                text = raw.decode("utf-8", errors="replace")
                chunks.append(text)
                for stage_name, detail in parse_stage_markers(text):
                    report.stage(stage_name, detail, outcome=STAGE_PENDING)
        except Exception:  # noqa: BLE001 - 读取失败不改变刷新结果
            return

    reader = threading.Thread(target=_reader, name="doc-tool-word-refresh-stages", daemon=True)
    reader.start()
    try:
        # 只用后台读线程排空 stderr：communicate() 会再抢一个读者，
        # 两个读者互相截断输出，阶段标记与 [REASON] 都会丢失。
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stage = report.currentStage or STAGE_PROCESS
        report.note_timeout(
            stage,
            "阶段「{0}」超过预算 {1} 秒，已按停止预算处理".format(
                STAGE_LABELS.get(stage, stage), timeout
            ),
        )
        # worker 进程是本次专用进程：按进程归属清理（不涉及用户 Word 会话）。
        report.set_ownership(ownership_from_pid_diff(process.pid, []))
        stop = stop_and_cleanup(
            report,
            kill=lambda: _kill_process_tree(process.pid),
            is_alive=lambda: process.poll() is None,
        )
        try:
            process.wait(timeout=max(1.0, float(report.budgets.cleanup)))
        except Exception:
            pass
        reader.join(1.0)
        _publish_report(report)
        print(
            "[{0}] [FAIL] Word 刷新超过 {1} 秒，{2}".format(label, timeout, stop.summary_line()),
            file=sys.stderr,
            flush=True,
        )
        return (False, REASON_TIMEOUT)
    reader.join(2.0)
    text = "".join(chunks)
    if process.returncode == 0:
        _publish_report(report)
        return (True, REASON_OK)
    if text:
        sys.stderr.write(text)
        sys.stderr.flush()
    reason = _scan_reason(text.encode("utf-8", errors="replace"))
    if not report.stages:
        report.stage(
            STAGE_START if reason == REASON_WORD_UNAVAILABLE else STAGE_PROCESS,
            "刷新未完成（{0}）".format(reason), outcome="failed",
        )
    _publish_report(report)
    return (False, reason)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="使用独立 Word 进程刷新 TOC、NUMPAGES 和域")
    # 与 build_docx/run_pipeline 一致，从 config/ 动态枚举文档类型。
    available = discover_document_types()
    choices = tuple(available) + ("all",)
    parser.add_argument("document", choices=choices, nargs="?", default="all")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    parser.add_argument(
        "--skip-word-refresh",
        action="store_true",
        help="显式跳过 Word 刷新（仅限无 Word 的诊断环境；日常生成入口不使用）",
    )
    args = parser.parse_args(argv)
    if args.worker:
        if args.output:
            return refresh_worker(output_path=args.output)
        if args.document != "all":
            return refresh_worker(document=args.document)
        parser.error("--worker 需要 --output 或文档参数")
    if args.skip_word_refresh:
        print("[SKIP] 已按显式参数跳过 Word 实机刷新；不能视为正式验收通过。")
        return 0
    targets = tuple(available) if args.document == "all" else (args.document,)
    ok = True
    for target in targets:
        ok_refresh, _reason = supervise(target)
        if not ok_refresh:
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
