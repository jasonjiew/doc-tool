# -*- coding: utf-8 -*-
"""性能、内存与字体指标测量（Task 9.4：REQ-MD-03、REQ-MD-07、REQ-MD-08）。"""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doc_tool.domain.preview_types import PreviewSnapshot
from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser


def get_memory_mb() -> float:
    try:
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def main():
    mem_before_mb = get_memory_mb()

    t0 = time.perf_counter()
    app = QApplication.instance() or QApplication(sys.argv)
    browser = WebPreviewBrowser()

    if not browser._page_ready:
        loop = QEventLoop()
        browser.loadFinished.connect(lambda ok: loop.quit())
        QTimer.singleShot(6000, loop.quit)
        loop.exec()

    t_startup = (time.perf_counter() - t0) * 1000

    # 首次渲染耗时测量
    md_sample = (
        "# 性能验证测试文档\n\n"
        "本段落测试中文字体回退（微软雅黑、苹方、中易黑体）混排下的排版渲染性能。\n\n"
        "| 列 1 | 列 2 | 状态 |\n"
        "| :--- | :---: | ---: |\n"
        "| 数据行 A | 居中说明 | 正常 |\n"
        "| 数据行 B | 居中说明 | 警告 |\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "  Start[启动引擎] --> Proc[渲染正文与矢量图] --> End[完成展示]\n"
        "```\n"
    )

    snap1 = PreviewSnapshot("sess-perf", "chap-perf", 1, "h1")
    t1 = time.perf_counter()
    browser.set_markdown(md_sample, snapshot=snap1)

    loop_render = QEventLoop()
    QTimer.singleShot(500, loop_render.quit)
    loop_render.exec()
    t_first_render = (time.perf_counter() - t1) * 1000

    # 连续更新耗时测量
    md_updated = md_sample + "\n追加编辑内容，触发去抖与增量连续更新。"
    snap2 = PreviewSnapshot("sess-perf", "chap-perf", 2, "h2")
    t2 = time.perf_counter()
    browser.set_markdown(md_updated, snapshot=snap2)

    loop_update = QEventLoop()
    QTimer.singleShot(300, loop_update.quit)
    loop_update.exec()
    t_update = (time.perf_counter() - t2) * 1000

    mem_after_mb = get_memory_mb()

    # 静态资源包体统计
    res_dir = REPO_ROOT / "doc_tool" / "resources" / "web_preview"
    html_sz = (res_dir / "preview.html").stat().st_size / 1024
    mdit_sz = (res_dir / "markdown-it.min.js").stat().st_size / 1024
    total_asset_kb = html_sz + mdit_sz

    metrics = {
        "startup_ms": round(t_startup, 1),
        "first_render_ms": round(t_first_render, 1),
        "update_ms": round(t_update, 1),
        "mem_start_mb": round(mem_before_mb, 1),
        "mem_end_mb": round(mem_after_mb, 1),
        "mem_delta_mb": round(mem_after_mb - mem_before_mb, 1),
        "html_template_kb": round(html_sz, 1),
        "markdown_it_kb": round(mdit_sz, 1),
        "total_web_assets_kb": round(total_asset_kb, 1),
    }

    out_file = HERE / "perf_metrics.json"
    out_file.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Metrics saved to {out_file}: {metrics}")

    browser.cleanup()


if __name__ == "__main__":
    main()
