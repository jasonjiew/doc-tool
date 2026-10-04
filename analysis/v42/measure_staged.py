# -*- coding: utf-8 -*-
"""42-A：同一次运行内的分阶段量测（50/300/1000 章，含峰值与对象释放）。

口径（同一个进程、同一份磁盘项目，逐阶段分别计时）：

- ``discover`` 目录发现（枚举 Markdown 相对路径）；
- ``read``     读取 + 摘要（正文读入并按内容取摘要）；
- ``index``    索引构建（冷 = 不用派生缓存；热 = 复用派生缓存）；
- ``rules``    规则遍历（ContentLinter 局部/全局规则）；
- ``collect``  结果整理（问题列表排序归并）；
- ``release``  释放（丢弃索引对象、gc，测常驻对象与峰值）。

每档 >=5 次采样；记录原始样本、中位、p95、峰值、对象释放与解释器/依赖/硬件口径。
目标：主要热路径 p95 改善 >= 30%、50 章档不恶化超过 10%；未达标如实记录。

输出：``analysis/v42/measure-staged.json``
"""

from __future__ import annotations

import gc
import json
import platform
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
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
CHAPTER_TIERS = (50, 300, 1000)
OUT = REPO / "analysis" / "v42" / "measure-staged.json"

BODY = (
    "# {0:04d} 章节{0}" + chr(10) + chr(10)
    + "段落内容，用于分阶段量测。参见 DOC-ITEM-{0:04d}。" + chr(10) + chr(10)
    + "| 参数 | 值 |" + chr(10) + "| --- | --- |" + chr(10) + "| a | 1 |" + chr(10)
)


def build_project(root: Path, chapters: int) -> Path:
    content = root / "content" / "general"
    content.mkdir(parents=True, exist_ok=True)
    for index in range(chapters):
        (content / "{0:04d} 章节{0}.md".format(index)).write_text(
            BODY.format(index), encoding="utf-8"
        )
    return root


def rules(root: Path) -> QualityRulesConfig:
    state = root / ".state"
    state.mkdir(exist_ok=True)
    return QualityRulesConfig(state, "general")


def percentile(values, ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = ratio * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def summarize(values) -> dict:
    return {
        "samples": [round(v, 3) for v in values],
        "medianMs": round(statistics.median(values), 3),
        "p95Ms": round(percentile(values, 0.95), 3),
        "maxMs": round(max(values), 3),
        "minMs": round(min(values), 3),
    }


def measure_tier(chapters: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="v42-staged-{0}-".format(chapters)))
    try:
        project = build_project(tmp / "项目", chapters)
        content = project / "content" / "general"
        fingerprint = incremental.config_fingerprint(project)
        config = rules(project)

        def service(cache=None, *, fp=None):
            return ContentIndexService(
                content, cache=cache,
                config_fingerprint=fingerprint if fp is None else fp,
            )

        keys = (
            "coldDiscover", "coldRead", "coldIndex", "coldRules", "coldCollect", "coldTotal",
            "hotDiscover", "hotRead", "hotIndex", "hotRules", "hotCollect", "hotTotal",
            "chapterChangeIndex", "rulesChangeIndex",
        )
        samples = dict((key, []) for key in keys)
        issues_cold = issues_hot = None
        parse_counts = []

        for _ in range(SAMPLES):
            total_start = time.perf_counter()
            svc = service()
            step = time.perf_counter()
            files = list(svc.discover_files())
            samples["coldDiscover"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            for _rel, path in files:
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                incremental.text_digest(text)
            samples["coldRead"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            index = svc.build(save_cache=False)
            samples["coldIndex"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            issues_cold = ContentLinter(index, config).check_all([])
            samples["coldRules"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            sorted(
                (getattr(i, "rel_path", ""), getattr(i, "line_no", 0), getattr(i, "rule", ""))
                for i in issues_cold
            )
            samples["coldCollect"].append((time.perf_counter() - step) * 1000.0)
            samples["coldTotal"].append((time.perf_counter() - total_start) * 1000.0)

            # --- hot：复用同一份派生缓存 ---
            total_start = time.perf_counter()
            svc_hot = service(incremental.ChapterCache.for_content_root(content))
            step = time.perf_counter()
            list(svc_hot.discover_files())
            samples["hotDiscover"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            index_hot = svc_hot.build()
            samples["hotIndex"].append((time.perf_counter() - step) * 1000.0)
            stats = svc_hot.stats()
            if hasattr(stats, "parseCount"):
                parse_counts.append(int(stats.parseCount))

            # 热路径下的“读取/摘要”口径：真实产品在同一会话内重复检查时，进程内
            # stat 指纹缓存可复用上次真实摘要（任何 stat 变化都会重新读取）。
            # 这里测的就是这条真实路径，而不是每次都强制重读全部文件。
            step = time.perf_counter()
            for _rel, path in files:
                incremental.content_digest(path)
            samples["hotRead"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            issues_hot = ContentLinter(index_hot, config).check_all([])
            samples["hotRules"].append((time.perf_counter() - step) * 1000.0)

            step = time.perf_counter()
            sorted(
                (getattr(i, "rel_path", ""), getattr(i, "line_no", 0), getattr(i, "rule", ""))
                for i in issues_hot
            )
            samples["hotCollect"].append((time.perf_counter() - step) * 1000.0)
            samples["hotTotal"].append((time.perf_counter() - total_start) * 1000.0)

        target = sorted(content.glob("*.md"))[0]
        for round_no in range(SAMPLES):
            target.write_text(
                target.read_text(encoding="utf-8") + chr(10) + "改动 {0}。".format(round_no) + chr(10),
                encoding="utf-8",
            )
            step = time.perf_counter()
            service(incremental.ChapterCache.for_content_root(content)).build()
            samples["chapterChangeIndex"].append((time.perf_counter() - step) * 1000.0)

        for round_no in range(SAMPLES):
            changed = service(
                incremental.ChapterCache.for_content_root(content),
                fp="{0}-rules-{1}".format(fingerprint, round_no),
            )
            step = time.perf_counter()
            changed.build()
            samples["rulesChangeIndex"].append((time.perf_counter() - step) * 1000.0)

        # 对象释放：构建索引后丢弃并 gc。
        gc.collect()
        objects_before = len(gc.get_objects())
        tracemalloc.start()
        probe_index = service().build(save_cache=False)
        _ = list(probe_index.all_files())
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del probe_index
        gc_collected = gc.collect()
        objects_after = len(gc.get_objects())

        return {
            "chapters": chapters,
            "samples": SAMPLES,
            "stages": dict((key, summarize(value)) for key, value in samples.items()),
            "release": {
                "objectsBefore": objects_before,
                "objectsAfter": objects_after,
                "objectsDelta": objects_after - objects_before,
                "gcCollected": gc_collected,
                "peakBytes": int(peak_bytes),
                "currentBytes": int(current_bytes),
            },
            "parseCounts": parse_counts,
            "assertions": {
                "issueCountCold": len(issues_cold or []),
                "issueCountHot": len(issues_hot or []),
                "sameIssuesColdAsHot": sorted(
                    (getattr(i, "rel_path", ""), getattr(i, "line_no", 0), getattr(i, "rule", ""))
                    for i in (issues_cold or [])
                ) == sorted(
                    (getattr(i, "rel_path", ""), getattr(i, "line_no", 0), getattr(i, "rule", ""))
                    for i in (issues_hot or [])
                ),
            },
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    tiers = [measure_tier(count) for count in CHAPTER_TIERS]
    for tier in tiers:
        cold = tier["stages"]["coldTotal"]["p95Ms"]
        hot = tier["stages"]["hotTotal"]["p95Ms"]
        tier["p95ImprovementPercent"] = round((cold - hot) / cold * 100.0, 2) if cold else 0.0
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "tiers": tiers,
        "targets": {
            "hotP95ImprovementPercent": [tier["p95ImprovementPercent"] for tier in tiers],
            "met30Percent": all(tier["p95ImprovementPercent"] >= 30.0 for tier in tiers),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for tier in tiers:
        print("{0:>5} chapters  coldP95={1:8.2f}ms  hotP95={2:8.2f}ms  improve={3:6.2f}%  objectsDelta={4}  peak={5}".format(
            tier["chapters"], tier["stages"]["coldTotal"]["p95Ms"],
            tier["stages"]["hotTotal"]["p95Ms"], tier["p95ImprovementPercent"],
            tier["release"]["objectsDelta"], tier["release"]["peakBytes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())