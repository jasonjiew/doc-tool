# -*- coding: utf-8 -*-
"""Bounded synthetic main-flow measurements; no model, Word, or real documents.

Run from the repository: python -B scripts/benchmark_mainflow_intelligence.py
    --sizes 50 300 1000 --output analysis/<owned-run>/scale.json

Absolute observations only: this is not a before/after productivity claim, native
GUI acceptance, RSS measurement, or a benchmark of real enterprise documents.
All corpus/cache writes are in a newly owned temporary directory under tmp/;
the report path is explicit. No user configuration or project source is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from doc_tool.application.assist.models import SOURCE_KIND_PROJECT
from doc_tool.application.assist.search_local import EvidenceSource, LocalEvidenceSearch
from doc_tool.application.intake_contract import HANDLING_PLACEHOLDER
from doc_tool.application.intake_result_page import summarize_followups
from doc_tool.application.mainflow_advice import MainflowFacts, QualityFacts, derive_advice


def tree_hashes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def signature(outcome) -> list:
    return [(h.rel_path, h.line_no, h.content_hash, h.rank_score, h.rank_reasons)
            for h in outcome.hits]


def timed(function):
    start = time.perf_counter()
    value = function()
    return value, round(time.perf_counter() - start, 6)


def measure_case(work: Path, chapters: int, lines: int, limit: int) -> dict:
    case = work / str(chapters)
    corpus, cache = case / "corpus", case / "cache"
    corpus.mkdir(parents=True)
    for number in range(1, chapters + 1):
        heading = "# 接口" if number == chapters else "# 合成章节 {0}".format(number)
        body = ["接口正文 {0}-{1}；仅用于合成检索规模量测。".format(number, row)
                for row in range(1, lines + 1)]
        (corpus / "{0:04d}.md".format(number)).write_text(
            heading + "\n" + "\n".join(body) + "\n", encoding="utf-8")
    before = tree_hashes(corpus)
    source = EvidenceSource(source_id="synthetic", kind=SOURCE_KIND_PROJECT,
                            label="合成数据", root=str(corpus))

    def new_search():
        return LocalEvidenceSearch([source], cache_dir=cache, cache_enabled=True)

    search = new_search()
    cold, cold_seconds = timed(lambda: search.search("接口", limit=limit))
    warm, warm_seconds = timed(lambda: search.search("接口", limit=limit))
    disk_search = new_search()
    disk, disk_seconds = timed(lambda: disk_search.search("接口", limit=limit))
    expected = chapters * lines + 1
    for result in (cold, warm, disk):
        assert result.ok and not result.cancelled, result.error
        assert not result.skipped, result.skipped
        assert result.total == expected, (result.total, expected)
        assert result.file_count == chapters, (result.file_count, chapters)
        assert len(result.hits) == min(limit, expected)
        assert result.hits[0].rel_path == "{0:04d}.md".format(chapters)
        assert result.hits[0].line_no == 1
        assert "标题精确匹配" in result.hits[0].rank_reasons
    assert signature(cold) == signature(warm) == signature(disk)

    # Incremental Python allocation during one warm query, not process RSS and
    # not total resident index/corpus memory. Tracing is outside primary timing.
    tracemalloc.start()
    try:
        traced = search.search("接口", limit=limit)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert signature(traced) == signature(cold)
    cancelled = search.search("接口", limit=limit,
                              cancel_token=SimpleNamespace(is_cancelled=True))
    assert cancelled.cancelled and cancelled.total == 0 and not cancelled.hits
    assert tree_hashes(corpus) == before, "Search changed synthetic source files"
    return {
        "chapters": chapters, "bodyLinesPerChapter": lines,
        "sourceBytes": sum(p.stat().st_size for p in corpus.iterdir()),
        "matchingLines": expected, "retainedHits": len(cold.hits), "limit": limit,
        "coldSeconds": cold_seconds, "warmMemorySeconds": warm_seconds,
        "warmDiskCacheSeconds": disk_seconds,
        "warmSearchPeakPythonAllocationBytes": peak_bytes,
        "coldCacheStatus": cold.cache_status, "diskCacheStatus": disk.cache_status,
        "highestRankedPath": cold.hits[0].rel_path,
        "rankReasons": list(cold.hits[0].rank_reasons),
        "resultsIdentical": True, "sourceHashesUnchanged": True,
        "preCancelledReturnsNoHits": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[50, 300, 1000])
    parser.add_argument("--lines", type=int, default=50)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (not args.sizes or any(n < 1 or n > 2000 for n in args.sizes)
            or not 1 <= args.lines <= 200 or not 1 <= args.limit <= 1000):
        parser.error("Bounded corpus: 1..2000 chapters, 1..200 lines, 1..1000 hits")
    scratch = ROOT / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mainflow-scale-", dir=scratch) as name:
        cases = [measure_case(Path(name), size, args.lines, args.limit) for size in args.sizes]
    facts = MainflowFacts(quality=QualityFacts())

    def advice_loop():
        for _ in range(10_000):
            assert derive_advice(facts).primary.action == "check-current"

    _, advice_seconds = timed(advice_loop)
    rows = [{"feature": "image", "handling": HANDLING_PLACEHOLDER}] * 50_000
    groups, groups_seconds = timed(lambda: summarize_followups(rows))
    assert sum(row["count"] for row in groups) == len(rows)
    report = {
        "schemaVersion": 1, "sourceType": "synthetic-only",
        "python": platform.python_version(), "platform": platform.platform(),
        "cases": cases, "advice10000CallsSeconds": advice_seconds,
        "followup50000RowsSeconds": groups_seconds,
        "followupCount": len(rows), "followupCountsComplete": True,
        "realModelCalls": 0, "realWordInvocations": 0,
        "notes": [
            "Primary timings exclude corpus creation and allocation tracing.",
            "Cache is confined to the owned temporary directory, not user configuration.",
            "Absolute samples, not before/after, productivity, RSS, or native GUI acceptance.",
            "All match lines are counted; only top-K hits are retained for display.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
