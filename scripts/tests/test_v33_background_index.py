# -*- coding: utf-8 -*-
"""V3.3 1.3/1.4 补测：后台分批建索引、来源去重、大范围检索不阻塞。

审计发现（第十四轮）：索引构建全同步、无后台分批；没有“来源去重”用例，
`..._does_not_block` 用例也未断言任何阻塞行为。本用例把这两点做实并给出可复现数据。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

TERM = "PACS"


def _project_with_sources(work: Path, chapters: int = 3) -> Path:
    """建一个含 N 个章节的项目，并额外把同一目录注册成“模块根”来源（制造重复来源）。"""
    project = fixtures.two_chapter_project(work / "proj")
    content = project / "content" / "general"
    template = next(path for path in sorted(content.rglob("*.md")) if path.name != "_index.md")
    for index in range(chapters):
        target_dir = content / "第9章 大量内容"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "9.{0} 段落.md".format(index + 1)).write_text(
            "# 段落 {0}\n\n本节讨论 {1} 接口与离线出稿。\n".format(index + 1, TERM),
            encoding="utf-8",
        )
    return project


class BackgroundIndexTests(unittest.TestCase):
    """1.3：索引在后台分批构建，检索本身不阻塞。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v33-bg-index")
        self.project = _project_with_sources(self.work, chapters=3)
        self.cache = self.work / "assist-cache"

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_build_index_task_reports_batches_and_writes_cache(self):
        from doc_tool.application.assist.worker import build_index_task

        events = []
        result = build_index_task(
            self.project, cache_dir=self.cache, on_event=events.append, batch_size=1,
        )
        self.assertTrue(result.get("ok"), result)
        self.assertGreater(result.get("documents", 0), 0)
        self.assertTrue(Path(str(result.get("path"))).is_file(), result)
        self.assertTrue(events, "应上报阶段事件")
        self.assertGreaterEqual(result.get("batches", 0), 1, "应按批次处理")

    def test_panel_searches_immediately_then_indexes_in_background(self):
        from PySide6.QtWidgets import QApplication

        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        QApplication.instance() or QApplication([])
        assistant = build_assistant(self.project, cache_dir=self.cache)
        panel = AssistPanel(assistant, project_root=self.project)

        started = time.perf_counter()
        outcome = panel.search(TERM)
        elapsed = time.perf_counter() - started
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.hits, "无索引也应能检索可读文本")
        self.assertLess(elapsed, 5.0, "首次检索不应因建索引而长时间阻塞：{0:.3f}s".format(elapsed))
        self.assertTrue(panel.has_background_index(), "应启动后台索引")

        panel.wait_background_index(timeout=120)
        result = panel.background_index_result()
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("ok"), result)
        # 索引建好后再次检索应命中缓存
        again = panel.search(TERM)
        self.assertTrue(again.hits)
        self.assertNotEqual(again.cache_status, "missing", again.cache_status)

    def test_background_index_task_supports_cancel(self):
        from doc_tool.application.assist.worker import build_index_task

        class _Cancelled:
            is_cancelled = True

            def check_cancel(self):
                raise RuntimeError("cancelled")

        result = build_index_task(self.project, cache_dir=self.cache, cancel_token=_Cancelled())
        self.assertIn("cancelled", result)
        self.assertTrue(result["cancelled"] or not result.get("documents"), result)


class SourceDedupTests(unittest.TestCase):
    """1.4：同一文件出现在多个来源时按来源去重。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v33-dedup")
        self.project = _project_with_sources(self.work, chapters=2)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_duplicate_sources_are_deduped(self):
        from doc_tool.application.assist.search_local import EvidenceSource, LocalEvidenceSearch

        content = self.project / "content" / "general"
        sources = [
            EvidenceSource.from_project(self.project),
            EvidenceSource.from_module(content),
        ]
        service = LocalEvidenceSearch(sources, cache_dir=self.work / "cache")
        outcome = service.search(TERM)
        self.assertTrue(outcome.hits)
        keys = [
            (hit.source_kind, hit.rel_path, hit.line_no, hit.content_hash) for hit in outcome.hits
        ]
        self.assertEqual(len(keys), len(set(keys)), "命中不应出现重复位置")
        self.assertGreaterEqual(outcome.deduped, 1, "同一内容出现在两个来源时应记录去重数")
        self.assertTrue(
            any("去重" in note for note in outcome.notes), outcome.notes,
        )

    def test_large_scope_search_stays_bounded_without_index(self):
        from doc_tool.application.assist.search_local import LocalEvidenceSearch, EvidenceSource

        large = _project_with_sources(self.work / "large", chapters=120)
        service = LocalEvidenceSearch(
            [EvidenceSource.from_project(large)], cache_dir=self.work / "large-cache",
        )
        started = time.perf_counter()
        outcome = service.search(TERM)
        elapsed = time.perf_counter() - started
        self.assertTrue(outcome.hits)
        self.assertLess(elapsed, 15.0, "120 章无索引检索应保持有界：{0:.3f}s".format(elapsed))
        # 数据留档：实测耗时供台账引用
        payload = {"chapters": 120, "seconds": round(elapsed, 3), "hits": len(outcome.hits)}
        print("LARGE_SEARCH_JSON:" + json.dumps(payload, ensure_ascii=False))
        self.assertGreater(len(outcome.hits), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)