# -*- coding: utf-8 -*-
"""V3.6 大文档性能基准（36-A）。

观察脚本，不是测试：建立 50/300/1,000 章节的确定样例，记录机器/输入身份，
对打开、索引、预览、检索、检查与出稿源阶段分别做冷/热多次测量并输出 JSON。
日志只记录计数、摘要与耗时，不写正文内容。

用法：
    python scripts/perf/v36_benchmark.py --out analysis/.../baseline.json [--sizes 50,300,1000]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

DEFAULT_SIZES = (50, 300, 1000)
SAMPLES = 5
ITEM_ID_TEMPLATE = "6f1f5c4e-0d1a-5b2c-9f31-0000000{0:05d}"


def build_sample(root: Path, chapters: int) -> dict:
    """确定性样例：每章含标题、段落、普通表格、条目标记与图片引用。"""
    from scripts.tests.fixture_factory import create_project

    project = Path(root)
    create_project(project, document_type="requirement")
    content = project / "content" / "requirement"
    per_chapter = 12
    for index in range(chapters):
        chapter_dir = content / "{0:04d} 章节{0}".format(index)
        chapter_dir.mkdir(parents=True, exist_ok=True)
        (chapter_dir / "_index.md").write_text(
            "# {0:04d} 章节{0}\n\n本章说明。\n".format(index), encoding="utf-8",
        )
        lines = ["## {0:04d}.1 小节".format(index), "", "段落说明文字。" * 4, ""]
        lines.append("| 参数 | 说明 |")
        lines.append("| --- | --- |")
        for row in range(4):
            lines.append("| p{0} | 说明{0} |".format(row))
        lines.append("")
        for item in range(per_chapter):
            lines.append(
                "条目 {0}：系统应支持离线出稿。<!-- DOC-ITEM: projectId=bench kind=requirement "
                "id={1} alias=条目{2} -->".format(item, ITEM_ID_TEMPLATE.format(index * per_chapter + item), item)
            )
            lines.append("")
        (chapter_dir / "{0:04d}.1 小节.md".format(index)).write_text("\n".join(lines), encoding="utf-8")
    total_bytes = sum(path.stat().st_size for path in content.rglob("*.md"))
    return {
        "chapters": chapters,
        "items": chapters * per_chapter,
        "contentBytes": total_bytes,
        "projectRoot": str(project),
    }


def _timed(func, *, repeats: int = 1):
    started = time.perf_counter()
    result = None
    for _ in range(repeats):
        result = func()
    return (time.perf_counter() - started) / max(1, repeats), result


def _stats(values):
    ordered = sorted(values)
    if not ordered:
        return {}
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return {
        "min": round(ordered[0], 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(ordered[index], 4),
        "max": round(ordered[-1], 4),
        "samples": len(ordered),
    }


def _legacy_full_refresh(service, index) -> None:
    """优化前的刷新路径：全部文件失效后重建（用于同机对照）。"""
    for rel_path in index.all_files():
        index.invalidate(rel_path)
    service.refresh_dirty(index)


def measure_project(project: Path, *, sizes_info: dict, samples: int = SAMPLES) -> dict:
    """对一个样例执行冷/热阶段测量。"""
    from doc_tool.application.check import run_check
    from doc_tool.application.content.index import ContentIndexService
    from doc_tool.application.content.preview import render_markdown_html
    from doc_tool.application.content.search import SearchOptions, SearchService
    from doc_tool.application.intake_contract import (
        FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
    )
    from doc_tool.application.project_export import run_project_export
    from doc_tool.domain.manifest import ProjectManifest

    manifest = ProjectManifest.load(project)
    content_root = project / manifest.relative_content_root()
    largest = max(content_root.rglob("*.md"), key=lambda path: path.stat().st_size)
    largest_text = largest.read_text(encoding="utf-8")

    phases = {name: [] for name in (
        "manifest_open", "index_cold", "index_warm_repeat", "index_full_refresh",
        "search_first_page", "search_total", "preview_one_chapter", "check",
        "export_html_source",
    )}
    counts = {"files": 0, "projects": 1}
    operations = {"incremental": {}, "fullRefresh": {}, "coldWithCache": {}}
    for _ in range(samples):
        duration, _ = _timed(lambda: ProjectManifest.load(project))
        phases["manifest_open"].append(duration)

        duration, index = _timed(lambda: ContentIndexService(content_root).build())
        phases["index_cold"].append(duration)
        counts["files"] = len(index.files)

        service = ContentIndexService(content_root)
        fresh = service.build()
        duration, _ = _timed(lambda: service.refresh(fresh))
        phases["index_warm_repeat"].append(duration)
        operations["incremental"] = service.stats()
        # 对照：优化前的“全部失效后重建”路径（同机同输入）
        duration, _ = _timed(lambda: _legacy_full_refresh(service, fresh))
        phases["index_full_refresh"].append(duration)
        operations["fullRefresh"] = service.stats()

        index_for_search = service.build()
        search = SearchService(index_for_search)
        duration, result = _timed(
            lambda: search.search(SearchOptions(query="离线出稿", limit=20), None)
        )
        phases["search_first_page"].append(duration)
        duration, full = _timed(
            lambda: search.search(SearchOptions(query="离线出稿", limit=100000), None)
        )
        phases["search_total"].append(duration)
        counts["searchHits"] = full.total

        duration, _html = _timed(lambda: render_markdown_html(largest_text))
        phases["preview_one_chapter"].append(duration)

        duration, report = _timed(lambda: run_check(project))
        phases["check"].append(duration)
        counts["checkIssues"] = len(report.issues)

        duration, export = _timed(
            lambda: run_project_export(
                ExportRequest(
                    project_root=str(project), formats=[FORMAT_HTML],
                    source_mode=SOURCE_MODE_SAVED, destination=str(project / "output"),
                ),
                skip_word_refresh=True,
            )
        )
        phases["export_html_source"].append(duration)

    # --- V3.6 36-D 4.4：大列表/预览内存与对象释放 ---
    import gc

    gc.collect()
    tracemalloc.start()
    baseline, _peak = tracemalloc.get_traced_memory()
    index_for_memory = ContentIndexService(content_root).build()
    _current, index_peak = tracemalloc.get_traced_memory()
    index_for_memory = None
    gc.collect()
    retained, _peak2 = tracemalloc.get_traced_memory()
    # 预览在索引释放后单独测量：先重置峰值，避免与索引峰值混在一起。
    preview_peak = retained
    try:
        tracemalloc.reset_peak()
        render_markdown_html(largest_text)
        _current2, preview_peak = tracemalloc.get_traced_memory()
    except Exception:  # noqa: BLE001 - 预览失败只影响该项观测
        preview_peak = retained
    tracemalloc.stop()
    grown = max(1.0, (index_peak - baseline) / (1024 * 1024))
    kept = max(0.0, (retained - baseline) / (1024 * 1024))
    memory = {
        "baselineMB": round(baseline / (1024 * 1024), 3),
        "indexPeakMB": round(grown, 3),
        "previewPeakMB": round(max(0.0, (preview_peak - retained) / (1024 * 1024)), 3),
        "retainedAfterReleaseMB": round(kept, 3),
        "releasedRatio": round(1.0 - min(1.0, kept / grown), 4),
    }

    return {
        "input": {
            **sizes_info,
            "largestChapterBytes": largest.stat().st_size,
            "contentSha256": hashlib.sha256(
                "".join(sorted(path.name + str(path.stat().st_size) for path in content_root.rglob("*.md"))).encode("utf-8")
            ).hexdigest()[:16],
        },
        "counts": counts,
        "operations": operations,
        "phases": {name: _stats(values) for name, values in phases.items()},
        "memory": memory,
        "peakTracedMemoryMB": memory["indexPeakMB"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "analysis" / "product-v36-large-document-performance" / "baseline.json"))
    parser.add_argument("--work", default="")
    parser.add_argument("--sizes", default=",".join(str(item) for item in DEFAULT_SIZES))
    parser.add_argument("--samples", type=int, default=SAMPLES)
    args = parser.parse_args()

    from scripts.tests import core_fixtures as fixtures

    work = Path(args.work) if args.work else fixtures.scratch_dir("v36-bench")
    report = {
        "kind": "v36-benchmark",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpuCount": os.cpu_count(),
            "machine": platform.machine(),
        },
        "samplesPerPhase": args.samples,
        "projects": [],
    }
    for size in [int(item) for item in str(args.sizes).split(",") if item.strip()]:
        info = build_sample(work / "sample-{0}".format(size), size)
        measured = measure_project(Path(info["projectRoot"]), sizes_info=info, samples=args.samples)
        report["projects"].append(measured)
        print("[bench] {0} 章节：索引冷 {1}s / 重复刷新 {2}s / 检索全量 {3}s".format(
            size,
            measured["phases"]["index_cold"]["median"],
            measured["phases"]["index_warm_repeat"]["median"],
            measured["phases"]["search_total"]["median"],
        ), flush=True)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[bench] 已写入 {0}".format(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
