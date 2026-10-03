# -*- coding: utf-8 -*-
"""MAIN-D 4.4：检查/预览热路径实测（增量索引 vs 完整扫描，各 >=5 次采样）。

对照口径：
- cold  ：不用派生缓存（等价于完整扫描），每次真实解析全部章节。
- hot   ：复用同一份派生缓存（等价于日常「检查/预览」热路径）。
- corrupt：故意破坏缓存文件后重建，验证缓存损坏可重建且结果与完整扫描一致。
- incremental-change：只改一章后刷新，验证只重解析变更章节。

输出：analysis/main-d/measure-check-hotpath.json
"""
from __future__ import annotations

import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for candidate in (str(REPO), str(REPO / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content import incremental_index as incremental  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.lint import ContentLinter  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402

SAMPLES = 5
OUT = REPO / "analysis" / "main-d" / "measure-check-hotpath.json"


def build_project(root: Path, chapters: int = 120) -> Path:
    content = root / "content" / "general"
    content.mkdir(parents=True, exist_ok=True)
    body = (
        "# {0:03d} 章节{0}" + chr(10) + chr(10)
        + "段落内容，用于检查热路径测量。" + chr(10) + chr(10)
        + "| 参数 | 值 |" + chr(10) + "| --- | --- |" + chr(10) + "| a | 1 |" + chr(10)
    )
    for index in range(chapters):
        (content / "{0:03d} 章节{0}.md".format(index)).write_text(
            body.format(index), encoding="utf-8"
        )
    return root


def rules(root: Path):
    state = root / ".state"
    state.mkdir(exist_ok=True)
    return QualityRulesConfig(state, "general")


def timed(fn, samples: int = SAMPLES):
    durations = []
    result = None
    for _ in range(samples):
        start = time.perf_counter()
        result = fn()
        durations.append((time.perf_counter() - start) * 1000.0)
    return durations, result


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="main-d-perf-"))
    try:
        project = build_project(tmp / "项目", chapters=120)
        content = project / "content" / "general"
        fingerprint = incremental.config_fingerprint(project)
        config = rules(project)

        def service(cache=None):
            return ContentIndexService(
                content, cache=cache, config_fingerprint=fingerprint,
            )

        # --- cold：无缓存完整扫描 ---
        def cold():
            index = service().build(save_cache=False)
            return ContentLinter(index, config).check_all([])

        cold_ms, cold_issues = timed(cold)

        # --- 仅索引构建（不含检查遍历），用于区分解析复用与检查开销 ---
        def cold_index_only():
            return service().build(save_cache=False)

        cold_index_ms, _ = timed(cold_index_only)

        # --- hot：复用派生缓存 ---
        cache = incremental.ChapterCache.for_content_root(content)
        warm = service(cache)
        warm_index = warm.build()
        baseline_issues = ContentLinter(warm_index, config).check_all([])

        def hot():
            index = service(cache).build()
            return ContentLinter(index, config).check_all([])

        hot_ms, hot_issues = timed(hot)

        def hot_index_only():
            return service(cache).build()

        hot_index_ms, _ = timed(hot_index_only)

        # --- incremental-change：改一章后增量刷新 ---
        target = sorted(content.glob("*.md"))[0]

        def change_and_refresh():
            target.write_text(
                target.read_text(encoding="utf-8") + chr(10) + "新增一行。" + chr(10),
                encoding="utf-8",
            )
            svc = service(cache)
            index = svc.build()
            return svc.stats()

        change_ms = []
        last_stats = None
        for _ in range(SAMPLES):
            start = time.perf_counter()
            last_stats = change_and_refresh()
            change_ms.append((time.perf_counter() - start) * 1000.0)

        # --- corrupt：缓存损坏后重建 ---
        cache_file = incremental.ChapterCache.for_content_root(content).path
        corrupted = False
        if cache_file.exists():
            cache_file.write_text("{ not json", encoding="utf-8")
            corrupted = True

        def corrupt_rebuild():
            index = service(incremental.ChapterCache.for_content_root(content)).build()
            return ContentLinter(index, config).check_all([])

        corrupt_ms, corrupt_issues = timed(corrupt_rebuild)

        payload = {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "chapters": 120,
            "samples": SAMPLES,
            "coldFullScanMs": cold_ms,
            "hotIncrementalMs": hot_ms,
            "coldIndexOnlyMs": cold_index_ms,
            "hotIndexOnlyMs": hot_index_ms,
            "singleChapterChangeMs": change_ms,
            "corruptedCacheRebuildMs": corrupt_ms,
            "summary": {
                "coldMedianMs": round(statistics.median(cold_ms), 2),
                "hotMedianMs": round(statistics.median(hot_ms), 2),
                "changeMedianMs": round(statistics.median(change_ms), 2),
                "corruptMedianMs": round(statistics.median(corrupt_ms), 2),
                "speedupHotVsCold": round(
                    statistics.median(cold_ms) / max(statistics.median(hot_ms), 0.001), 2
                ),
                "coldIndexOnlyMedianMs": round(statistics.median(cold_index_ms), 2),
                "hotIndexOnlyMedianMs": round(statistics.median(hot_index_ms), 2),
                "speedupIndexOnly": round(
                    statistics.median(cold_index_ms)
                    / max(statistics.median(hot_index_ms), 0.001),
                    2,
                ),
            },
            "assertions": {
                "issueCountCold": len(cold_issues),
                "issueCountHot": len(hot_issues),
                "issueCountCorrupt": len(corrupt_issues),
                "issueCountBaseline": len(baseline_issues),
                "sameIssuesHotAsBaseline": [
                    (i.rel_path, i.line_no, i.rule) for i in hot_issues
                ] == [(i.rel_path, i.line_no, i.rule) for i in baseline_issues],
                "sameIssuesCorruptAsCold": [
                    (i.rel_path, i.line_no, i.rule) for i in corrupt_issues
                ] == [(i.rel_path, i.line_no, i.rule) for i in cold_issues],
                "cacheCorrupted": corrupted,
                "lastRefreshStats": last_stats,
            },
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
        print(json.dumps(payload["assertions"], ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())