# -*- coding: utf-8 -*-
"""审查回归：真实正文摘要、空缓冲复制、跨目录引用与移动失败回滚。"""
from __future__ import annotations

import os
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.refactor import copy_chapter
from doc_tool.application.content.writer import ContentWriter, WriteResult
from doc_tool.application.content.batch_chapter_ops import (
    BATCH_MOVE, apply_batch_plan, plan_batch_chapters,
)


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review-20261004-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = self.root / "content" / "general"
        self.content.mkdir(parents=True)
        self.writer = ContentWriter(self.content, self.root / ".state")

    def write(self, path, text):
        target = self.content / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def index(self):
        self.service = ContentIndexService(self.content)
        index = self.service.build()
        ReferenceScanner(index).scan_all()
        return index

    def test_same_stat_edit_refreshes_existing_index(self):
        self.write("1 a.md", "# A\nTODO: old\n")
        index = self.index()
        target = self.content / "1 a.md"
        stat = target.stat()
        self.write("1 a.md", "# A\nTODO: new\n")
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.service.refresh(index)
        self.assertIn("TODO: new", index.lines["1 a.md"])

    def test_empty_live_buffer_does_not_restore_saved_body(self):
        self.write("1 a.md", "# A\nOLD BODY\n")
        result = copy_chapter(self.index(), "1 a.md", self.writer,
                              title="Copy", source_text="")
        self.assertTrue(result.ok, result.message)
        self.assertNotIn("OLD BODY", (self.content / result.target).read_text(encoding="utf-8"))

    def test_export_probe_preserves_existing_user_file(self):
        from doc_tool.application.intake_contract import resolve_export_directory
        original = self.root / ".doctool-write-probe"
        original.write_bytes(b"user data")
        resolved, _note = resolve_export_directory(self.root, [])
        self.assertEqual(resolved, self.root)
        self.assertEqual(original.read_bytes(), b"user data")
        self.assertEqual(list(self.root.glob(".doctool-write-probe-*")), [])

    def test_legacy_partial_version_is_not_comparable(self):
        from doc_tool.application.delivery.revision_compare import VersionOption
        manifest = self.root / "baseline.json"
        manifest.write_text("{}", encoding="utf-8")
        option = VersionOption(path=str(manifest), legacyPartial=True)
        self.assertFalse(option.comparable)
        self.assertIn("不可比较", option.label())

    def test_word_refresh_has_one_stderr_reader(self):
        from doc_tool.adapters.kernel import ensure_kernel_importable
        ensure_kernel_importable()
        import refresh_fields
        from doc_tool.domain.word_operations import stage_marker
        process = Mock()
        process.stderr = io.BytesIO((stage_marker("open", "opening") +
                                    "\n[REASON] save_failed\n").encode("utf-8"))
        process.returncode = 1
        with patch.object(refresh_fields.subprocess, "Popen", return_value=process), patch.object(sys, "executable", "python.exe"), patch.object(sys, "frozen", False, create=True):
            ok, reason = refresh_fields.supervise(output_path=str(self.root / "a.docx"), timeout=2)
        self.assertFalse(ok)
        self.assertEqual(reason, refresh_fields.REASON_SAVE_FAILED)
        process.wait.assert_called_once_with(timeout=2)
        process.communicate.assert_not_called()
        self.assertEqual(refresh_fields.LAST_REPORT["currentStage"], "open")

    def test_ambiguous_word_pid_difference_is_not_used(self):
        from doc_tool.adapters import word_convert
        with patch.object(word_convert, "_get_winword_pids", return_value={10, 20, 30}):
            self.assertIsNone(word_convert._word_pid(object(), {10}))

    def move_fixture(self):
        self.write("one/1.1 a.md", "# 1.1 A\n[B](1.2 b.md#b)\n")
        self.write("one/1.2 b.md", "# B\n[A](1.1 a.md)\n")
        self.write("two/2.1 c.md", "# C\n[A](../one/1.1 a.md)\n")
        index = self.index()
        plan = plan_batch_chapters(index, ["one/1.1 a.md"], BATCH_MOVE,
                                   dest_dir="two", content_root=self.content)
        return index, plan

    def test_cross_directory_move_preserves_incoming_and_outgoing_links(self):
        index, plan = self.move_fixture()
        result = apply_batch_plan(plan, index, self.writer,
                                  refresh_index=self.service.refresh)
        self.assertTrue(all(item.ok for item in result), plan.result_text())
        self.assertIn("[B](../one/1.2 b.md#b)", (self.content / plan.items[0].target).read_text(encoding="utf-8"))
        self.assertIn("[A](../two/1.1 a.md)", (self.content / "one/1.2 b.md").read_text(encoding="utf-8"))
        self.assertIn("[A](1.1 a.md)", (self.content / "two/2.1 c.md").read_text(encoding="utf-8"))
        ReferenceScanner(index).scan_all()
        self.assertFalse(any(ref.dangling for refs in index.references.values()
                             for ref in refs if ref.kind == "link"))

    def test_failed_move_restores_sources_and_reference_text(self):
        index, plan = self.move_fixture()
        before = {p.relative_to(self.content).as_posix(): p.read_bytes()
                  for p in self.content.rglob("*.md")}
        rename = self.writer.rename
        def fail_target(old, new, **kwargs):
            if new == plan.items[0].target:
                return WriteResult(new, None, False, error="injected failure")
            return rename(old, new, **kwargs)
        with patch.object(self.writer, "rename", side_effect=fail_target):
            results = apply_batch_plan(plan, index, self.writer,
                                       refresh_index=self.service.refresh)
        self.assertFalse(results[0].ok)
        after = {p.relative_to(self.content).as_posix(): p.read_bytes()
                 for p in self.content.rglob("*.md")}
        self.assertEqual(before, after)
        self.assertFalse(list(self.content.rglob(".doc-tool-*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
