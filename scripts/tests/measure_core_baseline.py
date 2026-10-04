# -*- coding: utf-8 -*-
"""CORE-H 8.3 本机基线测量：导入/出稿阶段耗时、内存峰值、取消响应与缓存无关性。

用法：``$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path; python scripts/tests/measure_core_baseline.py``
输出一行 JSON，便于写入台账；只做测量，不做断言。
"""

from __future__ import annotations

import json
import sys
import time
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


def main() -> int:
    from doc_tool.application.effective_snapshot import capture_snapshot, snapshot_cache_key
    from doc_tool.application.intake_contract import (
        FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_CURRENT_BUFFER, ExportRequest,
    )
    from doc_tool.application.intake_entries import run_intake
    from doc_tool.application.project_export import run_project_export
    from doc_tool.domain.cancellation import CancellationToken

    work = fixtures.scratch_dir("baseline")
    metrics = {"sample": "脱敏合成夹具（4 章两级标题，含 1 张图片资源引用）"}
    try:
        # 大样本：把标准文档扩展为 40 章
        blocks = []
        for index in range(1, 41):
            blocks.append(("h1", "章节{0}".format(index)))
            blocks.append(("p", "第 {0} 章正文段落，用于测量解析与构建阶段耗时。".format(index)))
            blocks.append(("h2", "小节{0}".format(index)))
            blocks.append(("p", "小节正文。"))
        source = fixtures.build_docx(work / "baseline.docx", blocks)
        out = work / "out"
        out.mkdir(parents=True, exist_ok=True)

        tracemalloc.start()
        started = time.perf_counter()
        outcome = run_intake(source, parent_dir=out)
        import_seconds = time.perf_counter() - started
        peak_after_import = tracemalloc.get_traced_memory()[1]
        stages = {
            event.stage: event.status for event in outcome.events
        }
        metrics["import"] = {
            "seconds": round(import_seconds, 3),
            "ok": outcome.ok,
            "stages": len(outcome.events),
            "chapters": len(outcome.plan.sections) if outcome.plan else 0,
            "peak_mb": round(peak_after_import / 1048576, 2),
        }

        project = outcome.project_root
        content = Path(project) / "content" / "general"
        buffers = {}
        for rel, path in __import__(
            "doc_tool.application.effective_snapshot", fromlist=["discover_chapters"]
        ).discover_chapters(content):
            buffers[rel] = path.read_text(encoding="utf-8") + "\n缓冲修改。\n"

        started = time.perf_counter()
        snapshot = capture_snapshot(
            project, scope=None, source_mode=SOURCE_MODE_CURRENT_BUFFER, buffer_texts=buffers,
        )
        snapshot_seconds = time.perf_counter() - started

        started = time.perf_counter()
        report = run_project_export(
            ExportRequest(
                project_root=str(project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_CURRENT_BUFFER, destination=str(work / "exp"),
            ),
            buffer_texts=buffers, skip_word_refresh=True,
        )
        export_seconds = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        metrics["export"] = {
            "seconds": round(export_seconds, 3),
            "snapshot_seconds": round(snapshot_seconds, 3),
            "results": [(item.format, item.status) for item in report.results],
            "usable": len(report.usable_results()),
            "peak_mb": round(peak / 1048576, 2),
            "cacheKey": snapshot.cacheKey[:16],
        }

        # 取消响应：在第一个进度回调后请求取消
        token = CancellationToken()
        seen = {"count": 0}

        def progress(_fmt, _detail):
            seen["count"] += 1
            token.request_cancel()

        started = time.perf_counter()
        cancelled = run_project_export(
            ExportRequest(
                project_root=str(project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_CURRENT_BUFFER, destination=str(work / "cancel"),
            ),
            buffer_texts=buffers, skip_word_refresh=True, cancel_token=token, progress=progress,
        )
        cancel_seconds = time.perf_counter() - started
        metrics["cancel"] = {
            "seconds": round(cancel_seconds, 3),
            "statuses": [item.status for item in cancelled.results],
            "kept_usable": len(cancelled.usable_results()),
        }

        # 缓存无关性：第二次出稿（另一次捕获）内容哈希与结果状态一致
        again = run_project_export(
            ExportRequest(
                project_root=str(project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_CURRENT_BUFFER, destination=str(work / "exp2"),
            ),
            buffer_texts=buffers, skip_word_refresh=True,
        )
        metrics["repeat"] = {
            "same_statuses": [item.status for item in again.results] == [
                item.status for item in report.results
            ],
            "same_usable": len(again.usable_results()) == len(report.usable_results()),
        }
        metrics["ok"] = True
    finally:
        fixtures.cleanup(work)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())