# -*- coding: utf-8 -*-
"""V3.6 大文档增量索引与视图回归（36-A～36-E）。

覆盖缓存命中/失效（同大小修改、新增/删除/移动、配置变化、解析器版本）、
损坏与关闭缓存的直接读取兜底、写入失败、容量清理、捕获隔离、索引一致性
以及与无缓存直接扫描的结果对照；性能目标以同机基准脚本的实测记录为准。
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.content import incremental_index as incremental  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.search import SearchOptions, SearchService  # noqa: E402

EVIDENCE_DIR = ROOT / "analysis" / "product-v36-large-document-performance"


def _cleanup(path):
    assert Path(path).resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(path)


def _write_evidence(name: str, payload: dict) -> None:
    if os.environ.get("PRODUCT_V36_EVIDENCE") != "1":
        return
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _project(root: Path, chapters: int = 6) -> Path:
    from scripts.tests.fixture_factory import create_project

    project = Path(root)
    create_project(project, document_type="requirement")
    content = project / "content" / "requirement"
    for index in range(chapters):
        chapter_dir = content / "{0:03d} 章节{0}".format(index)
        chapter_dir.mkdir(parents=True, exist_ok=True)
        (chapter_dir / "_index.md").write_text("# {0:03d} 章节{0}\n".format(index), encoding="utf-8")
        (chapter_dir / "{0:03d}.1 小节.md".format(index)).write_text(
            "## {0:03d}.1 小节\n\n段落内容。\n\n| 参数 | 值 |\n| --- | --- |\n| a | 1 |\n".format(index),
            encoding="utf-8",
        )
    return project


class CacheBehaviourTests(unittest.TestCase):
    """36-B：缓存键、失效与兜底。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-cache")
        self.project = _project(self.work / "项目")
        self.content = self.project / "content" / "requirement"
        self.fingerprint = incremental.config_fingerprint(self.project)

    def tearDown(self):
        _cleanup(self.work)

    def _service(self, *, cache: bool = True, **kwargs):
        chapter_cache = (
            incremental.ChapterCache.for_content_root(self.content) if cache else None
        )
        return ContentIndexService(
            self.content, cache=chapter_cache,
            config_fingerprint=self.fingerprint, **kwargs,
        )

    def test_first_build_parses_and_second_build_reuses_cache(self):
        service = self._service()
        index = service.build()
        files = len(index.files)
        self.assertGreater(files, 0)
        self.assertEqual(service.stats()["parseCount"], files)
        cache_path = incremental.default_cache_path(self.content)
        self.assertTrue(cache_path.is_file(), "启用缓存时应写入派生缓存文件")

        second = self._service()
        rebuilt = second.build()
        stats = second.stats()
        self.assertEqual(stats["parseCount"], 0, "内容未变化时不得重复解析")
        self.assertEqual(stats["reuseCount"], files)
        self.assertEqual(set(rebuilt.files), set(index.files))
        self.assertEqual(rebuilt.lines, index.lines)
        self.assertEqual(
            {key: [(item.line_no, item.level, item.text) for item in value] for key, value in rebuilt.headings.items()},
            {key: [(item.line_no, item.level, item.text) for item in value] for key, value in index.headings.items()},
        )

    def test_same_size_content_change_invalidates_by_digest(self):
        service = self._service()
        index = service.build()
        target = self.content / "001 章节1" / "001.1 小节.md"
        text = target.read_text(encoding="utf-8")
        changed = text.replace("段落内容。", "段落内容！")
        self.assertEqual(len(changed.encode("utf-8")), len(text.encode("utf-8")), "样例必须保持同字节数")
        before_size = target.stat().st_size
        target.write_text(changed, encoding="utf-8")
        os.utime(target, None)
        self.assertEqual(target.stat().st_size, before_size)
        rel = "001 章节1/001.1 小节.md"
        service.refresh(index)
        self.assertIn("段落内容！", "\n".join(index.lines[rel]))
        direct = ContentIndexService(self.content).build()
        self.assertEqual(index.lines[rel], direct.lines[rel], "缓存结果必须与直接解析一致")

    def test_add_delete_and_move_are_handled(self):
        service = self._service()
        index = service.build()
        new_file = self.content / "新增章" / "新增.md"
        new_file.parent.mkdir(parents=True, exist_ok=True)
        new_file.write_text("## 新增章\n\n新内容。\n", encoding="utf-8")
        service.refresh(index)
        self.assertIn("新增章/新增.md", index.files)

        moved_dir = self.content / "移动章"
        moved_dir.mkdir(parents=True, exist_ok=True)
        moved = moved_dir / "新增.md"
        new_file.replace(moved)
        service.refresh(index)
        self.assertNotIn("新增章/新增.md", index.files)
        self.assertIn("移动章/新增.md", index.files)

        moved.unlink()
        service.refresh(index)
        self.assertNotIn("移动章/新增.md", index.files)
        cache = service._cache
        self.assertNotIn("移动章/新增.md", cache.entries, "缓存条目必须随文件删除同步清理")

    def test_config_change_invalidates_cache(self):
        service = self._service()
        service.build()
        variants = self.project / "variants.yml"
        variants.write_text("schemaVersion: 1\nvariants:\n  - variantId: v1\n    name: 变体\n", encoding="utf-8")
        changed_fp = incremental.config_fingerprint(self.project)
        self.assertNotEqual(changed_fp, self.fingerprint, "配置指纹必须反映变体声明变化")
        other = ContentIndexService(
            self.content,
            cache=incremental.ChapterCache.for_content_root(self.content),
            config_fingerprint=changed_fp,
        )
        other.build()
        self.assertGreater(other.stats()["parseCount"], 0, "配置变化后必须重新解析")

    def test_parser_version_change_invalidates_cache(self):
        service = self._service()
        service.build()
        other = ContentIndexService(
            self.content,
            cache=incremental.ChapterCache(
                incremental.default_cache_path(self.content), parser_version="content-index/999",
            ),
            config_fingerprint=self.fingerprint,
        )
        other.build()
        self.assertGreater(other.stats()["parseCount"], 0, "解析器版本变化必须使旧缓存失效")

    def test_corrupted_cache_falls_back_to_source(self):
        service = self._service()
        original = service.build()
        cache_path = incremental.default_cache_path(self.content)
        cache_path.write_bytes(b'{"cacheSchemaVersion": 1, "entries": {"a":')  # 截断
        other = self._service()
        rebuilt = other.build()
        self.assertGreater(other.stats()["parseCount"], 0)
        self.assertEqual(set(rebuilt.files), set(original.files))
        self.assertTrue(other._cache.warnings, "损坏缓存应给出可诊断信息")
        self.assertTrue(cache_path.is_file(), "损坏缓存应能被重建")
        _write_evidence("cache-corruption.json", {
            "rebuilt": True,
            "warnings": other._cache.warnings,
            "files": len(rebuilt.files),
        })

    def test_cache_disabled_matches_direct_scan_and_writes_nothing(self):
        service = self._service(cache=False)
        index = service.build()
        files = len(index.files)
        self.assertEqual(service.stats()["parseCount"], files)
        self.assertFalse(incremental.default_cache_path(self.content).exists(), "关闭缓存不得写文件")
        direct = ContentIndexService(self.content).build()
        self.assertEqual(index.lines, direct.lines)

    def test_cache_write_failure_keeps_results(self):
        # 情况一：目标是目录（占位）→ 明确失败且不误写。
        cache_path = incremental.default_cache_path(self.content)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir()
        service = self._service()
        index = service.build()
        self.assertTrue(index.files)
        self.assertTrue(any("写入失败" in item for item in service._cache.warnings))

        # 情况二：父路径不是目录 → 写入抛错但索引结果保持正确。
        blocker = self.work / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        broken = ContentIndexService(
            self.content,
            cache=incremental.ChapterCache(blocker / "cache.json"),
            config_fingerprint=self.fingerprint,
        )
        rebuilt = broken.build()
        self.assertEqual(set(rebuilt.files), set(index.files))
        self.assertTrue(any("写入失败" in item for item in broken._cache.warnings))

    def test_capacity_prune_keeps_recent_entries(self):
        cache = incremental.ChapterCache(
            incremental.default_cache_path(self.content), max_entries=3,
        )
        for index in range(6):
            cache.put("f{0}.md".format(index), incremental.CachedChapter(digest="d{0}".format(index)))
            time.sleep(0.001)
        self.assertEqual(cache.prune(), 3)
        self.assertEqual(len(cache.entries), 3)

    def test_capture_index_isolates_unsaved_buffer_from_disk_cache(self):
        capture = incremental.CaptureIndex(capture_id="cap-1")
        buffer_text = "## 未保存章节\n\n缓冲内容。\n"
        digest = capture.put("001 章节1/001.1 小节.md", buffer_text)
        self.assertEqual(capture.digest_for("001 章节1/001.1 小节.md"), digest)
        self.assertNotEqual(
            digest,
            incremental.content_digest(self.content / "001 章节1" / "001.1 小节.md"),
            "缓冲摘要必须与磁盘旧内容区分",
        )
        self.assertEqual(capture.to_dict()["captureId"], "cap-1")


class IndexConsistencyTests(unittest.TestCase):
    """36-B/36-E：缓存开/关结果对照与重复刷新解析次数。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-consistency")
        self.project = _project(self.work / "项目", chapters=8)
        self.content = self.project / "content" / "requirement"

    def tearDown(self):
        _cleanup(self.work)

    def test_repeat_refresh_parses_nothing_and_matches_direct_scan(self):
        cache = incremental.ChapterCache.for_content_root(self.content)
        service = ContentIndexService(
            self.content, cache=cache,
            config_fingerprint=incremental.config_fingerprint(self.project),
        )
        index = service.build()
        parsed_after_build = service.stats()["parseCount"]
        service.refresh(index)
        self.assertEqual(
            service.stats()["parseCount"], parsed_after_build,
            "内容未变化时重复刷新不得再解析任何文件",
        )
        direct = ContentIndexService(self.content).build()
        self.assertEqual(set(index.files), set(direct.files))
        for rel_path in index.files:
            self.assertEqual(index.lines[rel_path], direct.lines[rel_path])
            self.assertEqual(
                [(item.line_no, item.level, item.text, item.anchor_id) for item in index.headings[rel_path]],
                [(item.line_no, item.level, item.text, item.anchor_id) for item in direct.headings[rel_path]],
            )

    def test_search_results_match_between_cache_and_direct(self):
        cache = incremental.ChapterCache.for_content_root(self.content)
        service = ContentIndexService(
            self.content, cache=cache,
            config_fingerprint=incremental.config_fingerprint(self.project),
        )
        first = service.build()
        service.build()  # 第二次命中缓存
        cached_result = SearchService(first).search(SearchOptions(query="段落内容", limit=100), None)
        direct_index = ContentIndexService(self.content).build()
        direct_result = SearchService(direct_index).search(SearchOptions(query="段落内容", limit=100), None)
        self.assertEqual(cached_result.total, direct_result.total)
        self.assertGreater(cached_result.total, 0)
        self.assertEqual(
            [(hit.rel_path, hit.line_no) for hit in cached_result.hits],
            [(hit.rel_path, hit.line_no) for hit in direct_result.hits],
        )

    def test_workspace_index_service_uses_project_cache(self):
        from doc_tool.ui.content.workspace import _index_service_for

        state_dir = self.project / ".state"
        service = _index_service_for(self.content, state_dir=state_dir)
        index = service.build()
        self.assertTrue(index.files)
        cache_path = self.project / ".state" / "cache" / incremental.CACHE_NAME
        self.assertTrue(cache_path.is_file(), "应用内索引服务应写入项目级派生缓存")
        reopened = _index_service_for(self.content, state_dir=state_dir)
        rebuilt = reopened.build()
        self.assertEqual(reopened.stats()["parseCount"], 0, "重开项目应命中派生缓存")
        self.assertEqual(set(rebuilt.files), set(index.files))

    def test_stats_expose_counts_without_content(self):
        cache = incremental.ChapterCache.for_content_root(self.content)
        service = ContentIndexService(
            self.content, cache=cache,
            config_fingerprint=incremental.config_fingerprint(self.project),
        )
        service.build()
        stats = service.stats()
        self.assertIn("parseCount", stats)
        self.assertIn("reuseCount", stats)
        self.assertIn("cache", stats)
        blob = json.dumps(stats, ensure_ascii=False)
        self.assertNotIn("段落内容", blob, "观测数据不得包含正文")


class CaptureScopeTests(unittest.TestCase):
    """36-C 3.1：捕获作用域索引——缓冲用内存真实摘要，缓存按 captureId 隔离。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-capture")
        self.project = _project(self.work / "项目", chapters=4)
        self.content = self.project / "content" / "requirement"
        self.rel = "001 章节1/001.1 小节.md"

    def tearDown(self):
        _cleanup(self.work)

    def test_buffered_chapter_uses_memory_text_not_disk_or_cache(self):
        from doc_tool.application.content import incremental_index as ii

        disk = (self.content / self.rel).read_text(encoding="utf-8")
        buffer_text = "### 001.1 小节（未保存）\n\n只存在于缓冲的新内容。\n"
        service = ii.capture_index_service(
            self.content, capture_id="cap-1", override_texts={self.rel: buffer_text},
            project_root=self.project,
        )
        index = service.build()
        self.assertIn("只存在于缓冲的新内容。", "\n".join(index.lines[self.rel]))
        self.assertNotIn("段落内容", "\n".join(index.lines[self.rel]), "不得读到磁盘旧内容")
        stats = service.stats()
        self.assertEqual(stats["captureId"], "cap-1")
        self.assertEqual(stats["captureFiles"], 1)
        cache_file = incremental.default_cache_path(self.content)
        if cache_file.is_file():
            blob = cache_file.read_text(encoding="utf-8")
            self.assertNotIn("只存在于缓冲的新内容。", blob, "缓冲内容不得写入持久缓存")
        self.assertIn("只存在于缓冲的新内容。", buffer_text)
        self.assertNotEqual(buffer_text, disk)

    def test_cache_entries_do_not_cross_captures(self):
        from doc_tool.application.content import incremental_index as ii

        first = ii.capture_index_service(self.content, capture_id="cap-1", project_root=self.project)
        first.build()
        second = ii.capture_index_service(self.content, capture_id="cap-2", project_root=self.project)
        second.build()
        self.assertGreater(
            second.stats()["parseCount"], 0,
            "不同 captureId 之间不得复用缓存条目",
        )

    def test_core_snapshot_records_capture_digests(self):
        from doc_tool.application.effective_snapshot import capture_snapshot
        from doc_tool.application.intake_contract import (
            SOURCE_MODE_CURRENT_BUFFER, ExportScope,
        )

        buffer_text = "### 001.1 小节\n\n捕获时的缓冲内容。\n"
        snapshot = capture_snapshot(
            self.project, scope=ExportScope(), source_mode=SOURCE_MODE_CURRENT_BUFFER,
            buffer_texts={self.rel: buffer_text}, work_root=self.work / "snap",
        )
        self.assertTrue(snapshot.captureId)
        self.assertIn(self.rel, snapshot.captureIndex)
        self.assertEqual(
            snapshot.captureIndex[self.rel], incremental.text_digest(buffer_text),
            "捕获应记录本轮真实内容摘要",
        )
        disk_digest = incremental.content_digest(self.content / self.rel)
        self.assertNotEqual(snapshot.captureIndex[self.rel], disk_digest)
        self.assertIn(self.rel, snapshot.unsavedChapters)


class ModuleFingerprintTests(unittest.TestCase):
    """36-C 3.2：装配指纹只失效真正依赖该模块的章节。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-module-fp")
        self.project = _project(self.work / "项目", chapters=3)
        self.content = self.project / "content" / "requirement"
        from doc_tool.application.content import module_refs
        from doc_tool.application.content.modules import Module, install_module

        self.module_refs = module_refs
        module = Module(
            moduleId="m-arch", version="1.0.0", title="架构模块",
            body="# 架构\n\n模块正文。\n",
        )
        self.published = install_module(self.project, module)
        self.referencing = "001 章节1/001.1 小节.md"
        self.plain = "002 章节2/002.1 小节.md"
        chapter = self.content / self.referencing
        chapter.write_text(
            chapter.read_text(encoding="utf-8")
            + "\n" + module_refs.canonical_directive("m-arch", "1.0.0", "s1") + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        _cleanup(self.work)

    def _chapter_texts(self):
        texts = {}
        for path in sorted(self.content.rglob("*.md")):
            texts[path.relative_to(self.content).as_posix()] = path.read_text(encoding="utf-8")
        return texts

    def _service(self, fingerprints):
        return incremental.capture_index_service(
            self.content, capture_id="cap-module", project_root=self.project,
            per_file_fingerprint=fingerprints,
        )

    def test_only_referencing_chapter_is_invalidated_by_module_change(self):
        texts = self._chapter_texts()
        before = incremental.chapter_assembly_fingerprints(self.project, texts)
        self.assertTrue(before.get(self.referencing), "引用模块的章节必须有装配指纹")
        self.assertEqual(before.get(self.plain), "", "未引用模块的章节指纹为空")

        first = self._service(before)
        index = first.build()
        self.assertEqual(first.stats()["parseCount"], len(index.files))

        # 同一装配下重建：不重复解析
        same = self._service(before)
        same.build()
        self.assertEqual(same.stats()["parseCount"], 0)

        # 模块内容变化：只有引用它的章节指纹变化
        body = Path(self.published.bodyPath)
        body.write_text(body.read_text(encoding="utf-8") + "\n新增模块内容。\n", encoding="utf-8")
        after = incremental.chapter_assembly_fingerprints(self.project, texts)
        self.assertNotEqual(after[self.referencing], before[self.referencing])
        self.assertEqual(after[self.plain], before[self.plain])

        changed = self._service(after)
        rebuilt = changed.build()
        self.assertEqual(
            changed.stats()["parseCount"], 1,
            "模块变化只应重新解析依赖该模块的章节（实际 {0}）".format(changed.stats()["parseCount"]),
        )
        self.assertEqual(set(rebuilt.files), set(index.files))
        self.assertEqual(rebuilt.lines[self.plain], index.lines[self.plain])

    def test_capture_index_helper_carries_capture_identity(self):
        texts = self._chapter_texts()
        fingerprints = incremental.chapter_assembly_fingerprints(self.project, texts)
        service = self._service(fingerprints)
        service.build()
        stats = service.stats()
        self.assertEqual(stats["captureId"], "cap-module")
        self.assertIn("cache", stats)


class ProgressiveChapterTests(unittest.TestCase):
    """36-D 4.2/4.4：章节首屏与问题分页、扫描进度与内存释放。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-first-screen")
        self.project = _project(self.work / "项目", chapters=12)
        self.content = self.project / "content" / "requirement"

    def tearDown(self):
        _cleanup(self.work)

    def test_index_build_reports_progress_counts(self):
        events = []
        service = ContentIndexService(self.content)
        index = service.build(on_progress=lambda scanned, total: events.append((scanned, total)), progress_every=3)
        total = len(index.files)
        self.assertTrue(events)
        self.assertEqual(events[-1], (total, total), "最后一次进度必须是完整总数")
        self.assertEqual([item[0] for item in events], sorted(item[0] for item in events))

    def test_build_content_context_forwards_progress_events(self):
        from doc_tool.ui.content.workspace import build_content_context

        seen = []

        class _Events:
            def __init__(self, collector):
                self._collector = collector

            def __call__(self, event):
                self._collector.append(event)

        index = build_content_context(
            self.content, state_dir=self.project / ".state",
            on_event=_Events(seen),
        )
        self.assertTrue(index.files)
        self.assertTrue(seen, "构建上下文应把解析进度推给界面")
        self.assertEqual(seen[-1].metrics["totalFiles"], len(index.files))
        self.assertIn("已解析", seen[-1].detail)

    def test_workspace_renders_first_screen_before_index_finishes(self):
        from doc_tool.ui.content.workspace import ContentWorkspace

        messages = []
        workspace = ContentWorkspace(
            self.content, state_dir=self.project / ".state",
            on_status=lambda text: messages.append(str(text)),
        )
        try:
            self.assertTrue(
                any("已显示前" in text for text in messages),
                "索引完成前应先渲染章节首屏：{0}".format(messages[:3]),
            )
            self.assertGreaterEqual(workspace._first_screen_count, 1)
        finally:
            workspace.shutdown()
            workspace.deleteLater()
            self.app.processEvents()

    def test_issue_list_is_paged_and_not_truncated(self):
        from doc_tool.application.content.lint import LintIssue
        from doc_tool.ui.content.lint_panel import ISSUE_PAGE_SIZE, LintPanel

        class _Linter:
            def check_all(self, _terms):
                return [
                    LintIssue(
                        rule="markdown_structure", rel_path="a.md", line_no=index + 1,
                        message="问题{0}".format(index), severity="warning",
                    )
                    for index in range(ISSUE_PAGE_SIZE * 2 + 5)
                ]

        class _Terms:
            def load(self):
                return []

            def save(self, _terms):
                return ""

        panel = LintPanel(_Linter(), _Terms())
        try:
            panel.resize(900, 520)
            panel.show()
            total = ISSUE_PAGE_SIZE * 2 + 5
            panel.run_check()
            self.app.processEvents()
            self.assertEqual(panel._tree.topLevelItemCount(), ISSUE_PAGE_SIZE)
            self.assertTrue(panel._more_btn.isVisible())
            self.assertIn("已显示前 {0}".format(ISSUE_PAGE_SIZE), panel._status_label.text())
            self.assertIn("共 {0}".format(total), panel._status_label.text())
            panel._more_btn.click()
            self.app.processEvents()
            self.assertEqual(panel._tree.topLevelItemCount(), ISSUE_PAGE_SIZE * 2)
            panel._more_btn.click()
            self.app.processEvents()
            self.assertEqual(panel._tree.topLevelItemCount(), total, "显示更多后必须完整展示")
            self.assertFalse(panel._more_btn.isVisible())
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_releasing_index_frees_traced_memory(self):
        import gc
        import tracemalloc

        gc.collect()
        tracemalloc.start()
        baseline, _peak0 = tracemalloc.get_traced_memory()
        service = ContentIndexService(self.content)
        index = service.build()
        _current, peak = tracemalloc.get_traced_memory()
        self.assertTrue(index.files)
        service = None
        index = None
        gc.collect()
        retained, _peak1 = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        grown = max(1.0, (peak - baseline) / 1024.0)
        kept = max(0.0, (retained - baseline) / 1024.0)
        self.assertLess(
            kept, grown * 0.5,
            "释放索引后应回收大部分派生内存（峰值 {0:.1f}KB，残留 {1:.1f}KB）".format(grown, kept),
        )


class SameRoundConsistencyTests(unittest.TestCase):
    """36-C 3.4 / 36-E 5.2：同轮预览/检查/出稿内容一致，取消保留已完成结果。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-round")
        self.project = _project(self.work / "项目", chapters=4)
        self.content = self.project / "content" / "requirement"

    def tearDown(self):
        _cleanup(self.work)

    def test_cached_index_does_not_change_preview_check_or_export_content(self):
        from doc_tool.application.check import run_check
        from doc_tool.application.content.preview import render_markdown_html
        from doc_tool.application.intake_contract import (
            FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        chapter = self.content / "001 章节1" / "001.1 小节.md"
        text = chapter.read_text(encoding="utf-8")
        cache = incremental.ChapterCache.for_content_root(self.content)
        service = ContentIndexService(
            self.content, cache=cache,
            config_fingerprint=incremental.config_fingerprint(self.project),
        )
        service.build()
        service.build()  # 命中缓存
        check_cached = run_check(self.project)
        report_cached = run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "out-cached"),
            ),
            skip_word_refresh=True,
        )
        html_cached = Path(report_cached.result_for(FORMAT_HTML).path).read_text(encoding="utf-8")
        preview_cached = render_markdown_html(text)

        # 无缓存直接读取作为对照
        incremental.ChapterCache.for_content_root(self.content).clear()
        direct = ContentIndexService(self.content).build()
        self.assertTrue(direct.files)
        check_direct = run_check(self.project)
        report_direct = run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "out-direct"),
            ),
            skip_word_refresh=True,
        )
        html_direct = Path(report_direct.result_for(FORMAT_HTML).path).read_text(encoding="utf-8")
        preview_direct = render_markdown_html(text)
        self.assertEqual(check_cached.status, check_direct.status)
        self.assertEqual(len(check_cached.issues), len(check_direct.issues))
        self.assertEqual(html_cached, html_direct, "缓存命中不得改变同轮出稿内容")
        self.assertEqual(preview_cached, preview_direct)
        self.assertFalse(report_cached.result_for(FORMAT_HTML).formal, "可读 HTML 不等于正式成功")

    def test_cancelled_build_keeps_partial_and_can_retry(self):
        from doc_tool.domain.cancellation import CancellationToken

        token = CancellationToken()
        service = ContentIndexService(self.content)
        calls = {"count": 0}

        original = service._index_file

        def counting(index, rel_path, file_path, **kwargs):
            calls["count"] += 1
            if calls["count"] >= 2:
                token.cancel()
            return original(index, rel_path, file_path, **kwargs)

        service._index_file = counting
        with self.assertRaises(Exception):
            service.build(token)
        self.assertGreaterEqual(calls["count"], 2, "取消应在文件边界生效")
        retried = ContentIndexService(self.content).build()
        self.assertEqual(len(retried.files), len(service.discover_files()), "重试应得到完整索引")


class ProgressiveViewTests(unittest.TestCase):
    """36-D 4.1～4.3：后台渐进扫描、请求代次、取消保留已找到结果。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("v36-views")
        self.project = _project(self.work / "项目", chapters=40)
        self.content = self.project / "content" / "requirement"

    def tearDown(self):
        _cleanup(self.work)

    def _index(self):
        return ContentIndexService(self.content).build()

    def test_progressive_search_reports_progress_and_matches_plain_search(self):
        from doc_tool.application.content.search import SearchProgress

        index = self._index()
        service = SearchService(index)
        events = []
        options = SearchOptions(query="段落内容", limit=1000)
        result = service.search_progressive(
            options, on_event=events.append, batch_files=5,
            generation=3, project_id="proj-1", capture_id="cap-9",
        )
        plain = service.search(options)
        self.assertEqual(result.total, plain.total, "渐进扫描结果必须与普通搜索一致")
        self.assertEqual(result.generation, 3)
        self.assertEqual(result.project_id, "proj-1")
        self.assertEqual(result.capture_id, "cap-9")
        self.assertFalse(result.partial)
        self.assertEqual(result.scanned_files, result.total_files)
        self.assertTrue(events, "扫描过程中必须报告进度")
        self.assertIsInstance(events[0], SearchProgress)
        self.assertLessEqual(events[0].metrics["found"], result.total, "扫描中只报告已找到数量")
        self.assertTrue(events[-1].metrics["complete"])

    def test_cancelled_search_is_partial_and_keeps_found_hits(self):
        from doc_tool.domain.cancellation import CancellationToken

        index = self._index()
        token = CancellationToken()
        calls = {"count": 0}
        original = SearchService.search_progressive

        seen = {}

        def progress(_stage, status, detail, metrics):
            calls["count"] += 1
            if metrics.get("scanned", 0) >= 5:
                token.request_cancel()

        class _Progress:
            def __init__(self, metrics):
                self.metrics = metrics

        result = SearchService(index).search_progressive(
            SearchOptions(query="段落内容", limit=1000), cancel_token=token,
            on_event=lambda ev: progress(None, None, None, ev.metrics), batch_files=1,
        )
        self.assertTrue(result.partial, "取消后必须标记部分结果")
        self.assertLess(result.scanned_files, result.total_files)
        self.assertGreaterEqual(result.total, 0)
        self.assertTrue(all(hit.rel_path for hit in result.hits), "已找到的命中必须保留")

    def test_search_panel_shows_progress_and_preserves_partial_results(self):
        import time

        from doc_tool.ui.content.search_panel import SearchPanel

        index = self._index()
        contexts = []
        panel = SearchPanel(
            SearchService(index),
            show_type_filter=False,
            context_provider=lambda: contexts.append(1) or {
                "projectId": "proj-1", "captureId": "cap-1",
            },
        )
        try:
            panel.resize(900, 520)
            panel.show()
            panel._query_entry.setText("段落内容")
            panel.search_now()
            deadline = time.monotonic() + 20
            while panel._runner.is_running and time.monotonic() < deadline:
                panel._poll()
                self.app.processEvents()
                time.sleep(0.005)
            panel._poll()
            self.app.processEvents()
            self.assertTrue(contexts, "启动搜索必须取用当前 projectId/captureId")
            self.assertGreater(panel._tree.topLevelItemCount(), 0)
            self.assertIn("共", panel._summary_label.text())
            self.assertFalse(panel._cancel_btn.isVisible(), "完成后取消按钮应收起")
            self.assertEqual(panel._generation, 1)
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_stale_generation_result_is_ignored_by_panel(self):
        from doc_tool.application.content.search import SearchResult
        from doc_tool.ui.content.search_panel import SearchPanel

        panel = SearchPanel(SearchService(self._index()), show_type_filter=False)
        try:
            panel._generation = 5
            before = panel._tree.topLevelItemCount()
            stale = SearchResult(
                query="x", total=1,
                hits=[type("H", (), {"rel_path": "a.md", "line_no": 1, "text": "旧结果"})()],
                file_count=1, generation=4,
            )
            panel._invalidate_inflight = False
            panel._on_search_done(stale)
            self.assertEqual(panel._tree.topLevelItemCount(), before, "旧代次结果不得更新界面")
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()


class BenchmarkHarnessTests(unittest.TestCase):
    """36-A/36-E：基准脚本可在小样例上复现并产出计数。"""

    def test_benchmark_script_produces_report_with_counts(self):
        work = fixtures.scratch_dir("v36-bench-smoke")
        try:
            import importlib.util

            script = ROOT / "scripts" / "perf" / "v36_benchmark.py"
            spec = importlib.util.spec_from_file_location("v36_benchmark", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            info = module.build_sample(work / "sample-5", 5)
            measured = module.measure_project(Path(info["projectRoot"]), sizes_info=info, samples=1)
            self.assertEqual(measured["input"]["chapters"], 5)
            self.assertGreater(measured["counts"]["files"], 0)
            self.assertIn("parseCount", measured["operations"]["incremental"])
            self.assertIn("index_warm_repeat", measured["phases"])
            self.assertIn("index_full_refresh", measured["phases"])
            _write_evidence("benchmark-harness.json", {
                "chapters": measured["input"]["chapters"],
                "files": measured["counts"]["files"],
                "incrementalParseCount": measured["operations"]["incremental"]["parseCount"],
                "fullRefreshParseCount": measured["operations"]["fullRefresh"]["parseCount"],
                "medianIncremental": measured["phases"]["index_warm_repeat"]["median"],
                "medianFullRefresh": measured["phases"]["index_full_refresh"]["median"],
            })
        finally:
            _cleanup(work)


if __name__ == "__main__":
    unittest.main(verbosity=2)
