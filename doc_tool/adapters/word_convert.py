# -*- coding: utf-8 -*-
"""Word 互转适配器：DOCX/DOC → PDF、PDF → DOCX、HTML → DOCX/PDF、RTF/ODT 导入，
全部由本机 Word 完成。

两条设计约束都来自真机实测，改动前请先复现：

1. **不用 ``scripts/refresh_fields.py`` 的子进程 worker 模式**。那里的命令是
   ``[sys.executable, __file__, "--worker"]``，冻结态下 ``sys.executable`` 是
   ``DocTool.exe`` 本身，重新拉起会进 GUI 而不是脚本入口。这里改成后台线程执行
   COM，超时后按 PID 终止本次专用 Word 进程树（``DispatchEx`` 保证是我们自己的
   Word，绝不影响用户已打开的会话）。
2. **不能用解析字节的方式校验 PDF 产物**。亿赛通 DocGuard 环境下 Word 写出的
   PDF 密文落盘，非信任进程（本应用、python、pdftotext）读到的都是密文，
   ``pypdf`` 必然报 ``invalid pdf header``。因此 PDF 侧只校验「存在且非零字节」，
   DOCX 侧仍沿用 Word 只读复打开验证。

真机探针结论（scripts/probes/probe_group_a.py，2026-08 实测）：

- RTF、ODT 都能被 Word 静默打开并 ``SaveAs2`` 成 DOCX（wdFormatXMLDocument=12）；
  MHT 三种规范变体全部被本机 Word 拒绝打开（com_error「命令失败」），因此
  MHT 方向不提供。
- ``ExportAsFixedFormat`` 的页范围导出走 ``Range=wdExportFromTo(3) + From/To``
  关键字参数，HTML 与 DOCX 源均实测通过。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

MODE_DOCX_TO_PDF = "docx_to_pdf"
MODE_PDF_TO_DOCX = "pdf_to_docx"
MODE_HTML_TO_DOCX = "html_to_docx"
MODE_HTML_TO_PDF = "html_to_pdf"
MODE_IMPORT_TO_DOCX = "import_to_docx"
MODE_IMPORT_TO_PDF = "import_to_pdf"
CONVERT_MODES = (
    MODE_DOCX_TO_PDF,
    MODE_PDF_TO_DOCX,
    MODE_HTML_TO_DOCX,
    MODE_HTML_TO_PDF,
    MODE_IMPORT_TO_DOCX,
    MODE_IMPORT_TO_PDF,
)
# 产出 PDF 的模式（ExportAsFixedFormat），支持页范围。
PDF_EXPORT_MODES = (MODE_DOCX_TO_PDF, MODE_HTML_TO_PDF, MODE_IMPORT_TO_PDF)

REASON_OK = "ok"
REASON_TIMEOUT = "timeout"
REASON_WORD_UNAVAILABLE = "word_unavailable"
REASON_CONVERT_FAILED = "convert_failed"
REASON_OUTPUT_MISSING = "output_missing"
CONVERT_REASONS = (
    REASON_OK,
    REASON_TIMEOUT,
    REASON_WORD_UNAVAILABLE,
    REASON_CONVERT_FAILED,
    REASON_OUTPUT_MISSING,
)

# Word 常量：wdExportFormatPDF / wdFormatXMLDocument / wdStatisticPages /
# wdPaperA4 / wdPortrait / wdExportFromTo。页边距一律按点数设置（72pt = 2.54cm）。
_WD_EXPORT_PDF = 17
_WD_EXPORT_FROM_TO = 3
_WD_FORMAT_DOCX = 12
_WD_STATISTIC_PAGES = 2
_WD_PAPER_A4 = 7
_WD_PORTRAIT = 0
_MARGIN_TOP_PT = 72.0
_MARGIN_BOTTOM_PT = 72.0
_MARGIN_SIDE_PT = 85.05

# 各方向的默认单文件超时（秒）。量级差别来自实测（同一 21 页模板）：
# DOCX→PDF 导出约 6 秒；PDF→Word 预热后 7.5 秒、Word 首次冷启动重排引擎要 84 秒；
# HTML→Word 与导出同量级。默认值按最坏情况留量。
DOCX_TO_PDF_TIMEOUT_SECONDS = 300
PDF_TO_DOCX_TIMEOUT_SECONDS = 900
HTML_TO_DOCX_TIMEOUT_SECONDS = 300
HTML_TO_PDF_TIMEOUT_SECONDS = 300
IMPORT_TO_DOCX_TIMEOUT_SECONDS = 300
IMPORT_TO_PDF_TIMEOUT_SECONDS = 300
_DEFAULT_TIMEOUTS = {
    MODE_DOCX_TO_PDF: DOCX_TO_PDF_TIMEOUT_SECONDS,
    MODE_PDF_TO_DOCX: PDF_TO_DOCX_TIMEOUT_SECONDS,
    MODE_HTML_TO_DOCX: HTML_TO_DOCX_TIMEOUT_SECONDS,
    MODE_HTML_TO_PDF: HTML_TO_PDF_TIMEOUT_SECONDS,
    MODE_IMPORT_TO_DOCX: IMPORT_TO_DOCX_TIMEOUT_SECONDS,
    MODE_IMPORT_TO_PDF: IMPORT_TO_PDF_TIMEOUT_SECONDS,
}
DEFAULT_TIMEOUT_SECONDS = DOCX_TO_PDF_TIMEOUT_SECONDS


def default_timeout_seconds(mode: str) -> int:
    """该方向的建议默认超时（秒）。"""
    return _DEFAULT_TIMEOUTS.get(mode, DOCX_TO_PDF_TIMEOUT_SECONDS)


@dataclass
class WordConversionOutcome:
    """一次互转的结果。``detail`` 面向用户，不含堆栈。

    ``error_code`` 仅在失败且原因键映射不出更精确的错误码时由适配器给出
    （如页范围越界 → E6008）；批量层优先采用它，否则按 ``reason`` 映射。
    """

    mode: str
    source: str
    target: str
    ok: bool = False
    reason: str = REASON_CONVERT_FAILED
    detail: str = ""
    elapsed_seconds: float = 0.0
    pages: int = 0
    error_code: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "source": self.source,
            "target": self.target,
            "ok": self.ok,
            "reason": self.reason,
            "detail": self.detail,
            "elapsedSeconds": round(self.elapsed_seconds, 2),
            "pages": self.pages,
            "errorCode": self.error_code,
        }


class _WordHandle:
    """在工作线程与应用线程之间传递本次 Word 进程 PID，供超时后清理。"""

    def __init__(self) -> None:
        self._pid: Optional[int] = None
        self._lock = threading.Lock()

    def attach(self, word, pids_before: Optional[set] = None) -> None:
        pid = _word_pid(word, pids_before)
        with self._lock:
            self._pid = pid

    def detach(self) -> None:
        with self._lock:
            self._pid = None

    def kill(self) -> None:
        with self._lock:
            pid = self._pid
            self._pid = None
        _kill_process_tree(pid)


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
        import subprocess

        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except Exception:
        # 清理失败不遮蔽原始结果：挂起的工作线程会在 Word 消失后自行抛错退出。
        pass


def _outcome(
    mode: str,
    source: Path,
    target: Path,
    ok: bool,
    reason: str,
    detail: str = "",
    pages: int = 0,
    elapsed_seconds: float = 0.0,
    error_code: Optional[str] = None,
) -> WordConversionOutcome:
    return WordConversionOutcome(
        mode=mode,
        source=str(source),
        target=str(target),
        ok=ok,
        reason=reason,
        detail=detail,
        pages=pages,
        elapsed_seconds=elapsed_seconds,
        error_code=error_code,
    )


def _open_word_document(word, path: Path, mode: str):
    """按方向打开源文件。入参组合都经真机探针验证。

    - DOCX→PDF 走与 refresh_fields 同套只读入参：互转绝不改动源文档；
    - HTML/RTF/ODT 导入与 HTML→PDF 需要可写打开：排版收口、页边距或另存
      都发生在打开后的文档对象上；
    - PDF 侧必须关掉格式转换确认框，否则无头 Word 会永久等待用户应答。
    """
    if mode == MODE_DOCX_TO_PDF:
        return word.Documents.Open(
            FileName=os.path.abspath(str(path)),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            Revert=False,
            Visible=False,
            OpenAndRepair=False,
            NoEncodingDialog=True,
        )
    if mode in (MODE_HTML_TO_DOCX, MODE_HTML_TO_PDF, MODE_IMPORT_TO_DOCX, MODE_IMPORT_TO_PDF):
        # 需要可写打开：导入后还要设纸张页边距、按需插入目录或另存新文件。
        return word.Documents.Open(
            FileName=os.path.abspath(str(path)),
            ConfirmConversions=False,
            ReadOnly=False,
            AddToRecentFiles=False,
            Visible=False,
        )
    # PDF 侧必须关掉格式转换确认框，否则无头 Word 会永久等待用户应答。
    return word.Documents.Open(
        FileName=os.path.abspath(str(path)),
        ConfirmConversions=False,
        ReadOnly=True,
        AddToRecentFiles=False,
        Visible=False,
    )


def _page_count(document) -> int:
    try:
        return int(document.ComputeStatistics(_WD_STATISTIC_PAGES))
    except Exception:
        return 0


def _export_pdf(document, target: Path, page_range: Optional[Tuple[int, int]]) -> Optional[str]:
    """ExportAsFixedFormat，支持可选页范围。返回错误说明，正常返回空串。

    页范围走 ``Range=wdExportFromTo + From/To`` 关键字（真机探针实测可用）。
    上界超出文档页数时按页数收口；下界超页才报错。
    """
    if page_range is None:
        document.ExportAsFixedFormat(str(target), _WD_EXPORT_PDF)
        return ""
    pages = _page_count(document)
    from_page, to_page = page_range
    if pages and from_page > pages:
        return "页范围 {0}-{1} 超出文档页数（共 {2} 页）".format(from_page, to_page, pages)
    if pages and to_page > pages:
        to_page = pages
    document.ExportAsFixedFormat(
        str(target), _WD_EXPORT_PDF,
        Range=_WD_EXPORT_FROM_TO, From=from_page, To=to_page,
    )
    return ""


def _embed_linked_pictures(document) -> str:
    """把 HTML 导入产生的「链接图片」转为内嵌，返回给用户看的说明。

    实测 Word 从 HTML 导入 ``<img>`` 时默认只建外部链接（``word/media`` 是空的），
    产物发给别人就丢图；必须 ``SavePictureWithDocument = True`` 再 ``BreakLink``
    才真正进包。逆序遍历：BreakLink 会改动 InlineShapes 集合。
    """
    try:
        total = int(document.InlineShapes.Count)
    except Exception:
        return ""
    if total <= 0:
        return ""
    embedded = 0
    failed = 0
    for index in range(total, 0, -1):
        try:
            link = document.InlineShapes.Item(index).LinkFormat
        except Exception:
            continue
        if link is None:
            continue
        try:
            link.SavePictureWithDocument = True
            link.BreakLink()
            embedded += 1
        except Exception:
            failed += 1
    note = "图片已内嵌 {0} 张".format(embedded) if embedded else ""
    if failed:
        note += "{0}未能内嵌 {1} 张（换机可能丢图）".format("，" if note else "", failed)
    return note


def _apply_word_layout(document, with_toc: bool) -> str:
    """HTML 导入后的排版收口：图片内嵌、纸张与页边距、（可选）自动目录。

    CSS 的 ``@page`` 在 Word 的 HTML 导入器里不可靠，纸张与页边距一律在这里显式
    设置；目录用内置标题样式（1~3 级）生成，插入后立即刷新域，避免出现
    「错误!未定义书签」。
    """
    notes: List[str] = []
    pictures = _embed_linked_pictures(document)
    if pictures:
        notes.append(pictures)
    try:
        setup = document.PageSetup
        setup.PaperSize = _WD_PAPER_A4
        setup.Orientation = _WD_PORTRAIT
        setup.TopMargin = _MARGIN_TOP_PT
        setup.BottomMargin = _MARGIN_BOTTOM_PT
        setup.LeftMargin = _MARGIN_SIDE_PT
        setup.RightMargin = _MARGIN_SIDE_PT
    except Exception as exc:
        notes.append("页面设置未生效（{0}）".format(_classify_failure(exc)))
    if with_toc:
        try:
            document.TablesOfContents.Add(
                document.Range(0, 0),
                UseHeadingStyles=True,
                UpperHeadingLevel=1,
                LowerHeadingLevel=3,
            )
            document.Repaginate()
            document.Fields.Update()
            notes.append("已插入 1~3 级目录")
        except Exception as exc:
            notes.append("目录插入失败：{0!r}".format(exc))
    return "；".join(notes)


def _verify_docx_output(word, target: Path) -> Tuple[str, int]:
    """产物 DOCX 的存在性 + Word 只读复打开校验。

    返回 ``(失败说明, 段落数)``；说明为空串表示校验通过。
    """
    missing = _missing_output(target)
    if missing:
        return (missing, 0)
    reopened = _open_word_document(word, target, MODE_DOCX_TO_PDF)
    try:
        paragraphs = int(reopened.Paragraphs.Count)
    except Exception:
        paragraphs = 0
    reopened.Close(SaveChanges=False)
    if paragraphs <= 0:
        return ("Word 复打开后文档不含任何段落", 0)
    return ("", paragraphs)


def _run_session(
    source: Path,
    target: Path,
    mode: str,
    handle: _WordHandle,
    with_toc: bool = False,
    page_range: Optional[Tuple[int, int]] = None,
) -> WordConversionOutcome:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        return _outcome(
            mode, source, target, False, REASON_WORD_UNAVAILABLE,
            "未安装 pywin32，无法调用 Word：{0}".format(exc),
        )

    word = None
    opened = None
    try:
        pythoncom.CoInitialize()
        try:
            pids_before = _get_winword_pids()
            word = win32com.client.DispatchEx("Word.Application")
            handle.attach(word, pids_before)
            word.Visible = False
            word.DisplayAlerts = 0  # wdAlertsNone
            try:
                word.AutomationSecurity = 3  # 绝不执行文档宏
            except Exception:
                pass
            parent = os.path.dirname(os.path.abspath(str(target)))
            if parent:
                os.makedirs(parent, exist_ok=True)

            opened = _open_word_document(word, source, mode)
            if handle._pid is None:
                handle.attach(word)

            if mode in PDF_EXPORT_MODES:
                # 页数是廉价的（实测 1.2 秒），给用户一个体量读数；DOCX 源
                # 额外 Repaginate 保证导出前分页一致。
                pages = _page_count(opened)
                try:
                    opened.Repaginate()
                except Exception:
                    pass
                notes = ""
                if mode == MODE_HTML_TO_PDF:
                    # HTML 的 CSS @page 在 Word 导入器里不可靠：A4 与页边距
                    # 在这里显式设置（与 HTML→Word 同一套收口）。
                    notes = _apply_word_layout(opened, with_toc)
                problem = _export_pdf(opened, target, page_range)
                opened.Close(SaveChanges=False)
                opened = None
                if problem:
                    return _outcome(
                        mode, source, target, False, REASON_CONVERT_FAILED, problem,
                        pages=pages, error_code="E6008",
                    )
                missing = _missing_output(target)
                if missing:
                    return _outcome(mode, source, target, False, REASON_OUTPUT_MISSING, missing)
                detail = "源文档 {0} 页，PDF 已生成".format(pages) if pages else "PDF 已生成"
                if page_range is not None:
                    detail += "（第 {0}-{1} 页）".format(page_range[0], page_range[1])
                if notes:
                    detail += "；{0}".format(notes)
                return _outcome(
                    mode, source, target, True, REASON_OK, detail, pages=pages
                )

            if mode == MODE_IMPORT_TO_DOCX:
                # RTF/ODT 导入：原样另存为 DOCX，不做排版改动。
                opened.SaveAs2(str(target), FileFormat=_WD_FORMAT_DOCX)
                opened.Close(SaveChanges=False)
                opened = None
                problem, paragraphs = _verify_docx_output(word, target)
                if problem:
                    return _outcome(mode, source, target, False, REASON_OUTPUT_MISSING, problem)
                return _outcome(
                    mode, source, target, True, REASON_OK,
                    "导入 Word 完成，{0} 段".format(paragraphs),
                )

            # HTML → Word：排版收口（图片内嵌、纸张页边距、可选目录）→ 另存 → 复打开校验。
            notes = _apply_word_layout(opened, with_toc)
            opened.SaveAs2(str(target), FileFormat=_WD_FORMAT_DOCX)
            opened.Close(SaveChanges=False)
            opened = None
            problem, paragraphs = _verify_docx_output(word, target)
            if problem:
                return _outcome(mode, source, target, False, REASON_OUTPUT_MISSING, problem)
            detail = "HTML → Word {0} 段".format(paragraphs)
            if notes:
                detail += "；{0}".format(notes)
            return _outcome(mode, source, target, True, REASON_OK, detail)
        finally:
            if opened is not None:
                try:
                    opened.Close(SaveChanges=False)
                except Exception:
                    pass
            if word is not None:
                # 先 Quit、失败才按 PID 杀进程树；不能先 detach——pid 一旦
                # 清空，Quit 失败分支的 kill 就拿不到目标，Word 进程会泄漏。
                try:
                    word.Quit(SaveChanges=False)
                except Exception:
                    handle.kill()
                handle.detach()
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    except Exception as exc:
        reason = _classify_failure(exc)
        return _outcome(mode, source, target, False, reason, repr(exc)[:300])


def _missing_output(target: Path) -> str:
    """返回产物缺失/不可用的说明，正常时返回空串。"""
    if not os.path.isfile(str(target)):
        return "Word 未生成输出文件：{0}".format(Path(target).name)
    try:
        if os.path.getsize(str(target)) <= 0:
            return "Word 生成的输出文件为空：{0}".format(Path(target).name)
    except OSError as exc:
        return "无法确认输出文件状态：{0}".format(exc)
    return ""


def _classify_failure(exc: BaseException) -> str:
    text = str(exc)
    lower = text.lower()
    if (
        "pywin32" in lower
        or "win32com" in lower
        or "word.application" in lower
        or "没有注册类" in text
        or "拒绝访问" in text
    ):
        return REASON_WORD_UNAVAILABLE
    return REASON_CONVERT_FAILED


def convert_document(
    source: Path,
    target: Path,
    mode: str,
    timeout_seconds: Optional[float] = None,
    with_toc: bool = False,
    page_range: Optional[Tuple[int, int]] = None,
) -> WordConversionOutcome:
    """把 ``source`` 转成 ``target``。方向由 ``mode`` 指定。

    始终在独立线程里跑一次 Word COM：COM 调用不可中断，超时只能终止本次专用
    Word 进程，让挂起的调用抛错自行结束（daemon 线程随之退出）。
    ``page_range`` 仅对 PDF 导出模式生效，形如 ``(起始页, 结束页)``（1 起）。
    """
    if mode not in CONVERT_MODES:
        raise ValueError("未知转换方向: {0}".format(mode))
    if timeout_seconds is None:
        timeout_seconds = float(default_timeout_seconds(mode))
    source = Path(source)
    target = Path(target)
    if not source.is_file():
        return _outcome(mode, source, target, False, REASON_CONVERT_FAILED, "源文件不存在")

    handle = _WordHandle()
    box: list = []

    def _worker() -> None:
        box.append(_run_session(source, target, mode, handle, with_toc, page_range))

    started = time.monotonic()
    thread = threading.Thread(target=_worker, name="doc-tool-word-convert", daemon=True)
    thread.start()
    thread.join(max(1.0, float(timeout_seconds)))
    elapsed = time.monotonic() - started

    if thread.is_alive():
        handle.kill()
        thread.join(15)
        if thread.is_alive():
            return _outcome(
                mode, source, target, False, REASON_TIMEOUT,
                "Word 进程未响应，已终止，但转换线程仍在回收中",
                elapsed_seconds=elapsed,
            )
        return _outcome(
            mode, source, target, False, REASON_TIMEOUT,
            "Word 转换超过 {0} 秒，已终止本次专用进程".format(int(timeout_seconds)),
            elapsed_seconds=elapsed,
        )
    outcome = box[0] if box else _outcome(
        mode, source, target, False, REASON_CONVERT_FAILED, "Word 转换线程未返回结果"
    )
    outcome.elapsed_seconds = elapsed
    return outcome
