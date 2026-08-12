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
from typing import Optional, Sequence

from docx_common import AutomationError, discover_document_types, load_config


def _word_pid(word) -> Optional[int]:
    try:
        import win32process

        return int(win32process.GetWindowThreadProcessId(int(word.Hwnd))[1])
    except Exception:
        return None


def _kill_process_tree(pid: Optional[int]) -> None:
    if not pid:
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


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
    document: Optional[str] = None, output_path: Optional[str] = None
) -> int:
    try:
        import win32com.client
    except ImportError as exc:
        print("[FAIL] 未安装 pywin32，无法刷新 Word 域: {0}".format(exc), file=sys.stderr, flush=True)
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
        return 1
    # 显示标签：项目上下文无 doc_type 时用文件名替代，避免消息出现 None。
    if document is None:
        document = os.path.basename(output)

    word = None
    opened = None
    word_pid = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word_pid = _word_pid(word)
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        # msoAutomationSecurityForceDisable: never execute document macros.
        try:
            word.AutomationSecurity = 3
        except Exception:
            pass

        print("[{0}] Word 打开并刷新: {1}".format(document, output), flush=True)
        opened = _open_document(word, output, read_only=False)
        _update_all_story_fields(opened)
        for index in range(1, int(opened.TablesOfContents.Count) + 1):
            opened.TablesOfContents(index).Update()
        try:
            opened.Repaginate()
        except Exception:
            pass
        _update_all_story_fields(opened)
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
        return 1
    finally:
        if opened is not None:
            try:
                opened.Close(SaveChanges=False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit(SaveChanges=False)
            except Exception:
                _kill_process_tree(word_pid)


def supervise(
    document: Optional[str] = None,
    output_path: Optional[str] = None,
    timeout: Optional[int] = None,
) -> bool:
    """Supervise the Word refresh worker with a timeout.

    Project context callers pass ``output_path`` and ``timeout`` directly;
    legacy callers pass ``document`` and the config is loaded from disk.
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
    command = [
        sys.executable,
        os.path.abspath(__file__),
        "--worker",
        "--output",
        os.path.abspath(output_path),
    ]
    process = subprocess.Popen(command)
    try:
        return process.wait(timeout=timeout) == 0
    except subprocess.TimeoutExpired:
        print(
            "[{0}] [FAIL] Word 刷新超过 {1} 秒，已终止本次专用进程".format(label, timeout),
            file=sys.stderr,
            flush=True,
        )
        _kill_process_tree(process.pid)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return False


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
        if not supervise(target):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
