# -*- coding: utf-8 -*-
"""V2.8 8.2：重导入预览会话（服务层）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.reimport import ChapterChange  # noqa: E402
from doc_tool.application.content.reimport_preview import (  # noqa: E402
    apply_session,
    cancel_session,
    open_preview,
    toggle_selection,
)

NL = chr(10)


def _changes():
    return [
        ChapterChange("1 概述.md", "added", False, True),
        ChapterChange("2 设计.md", "modified", False, True),
        ChapterChange("3 冲突.md", "modified", True, False),
        ChapterChange("4 未变.md", "unchanged", False, True),
    ]


class OpenPreviewTests(unittest.TestCase):
    def test_session_lists_items_with_counts(self):
        session = open_preview(_changes(), source_path="new.docx", baseline_available=True)
        counts = session.counts()
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["applicable"], 2)
        self.assertEqual(counts["conflict"], 1)
        self.assertIn("重导入预览", session.markdown_text())
        self.assertTrue(session.warnings)

    def test_dirty_items_excluded_from_application(self):
        session = open_preview(
            _changes(),
            source_path="new.docx",
            baseline_available=True,
            dirty_paths=["2 设计.md"],
        )
        entry = {item.rel_path: item for item in session.entries}["2 设计.md"]
        self.assertTrue(entry.dirty)
        self.assertFalse(entry.applicable)
        self.assertIn("未保存", entry.blocked_reason)
        self.assertEqual({item.rel_path for item in session.applicable}, {"1 概述.md"})

    def test_diff_generated_when_contents_given(self):
        session = open_preview(
            _changes(),
            source_path="new.docx",
            baseline_available=True,
            local_contents={"2 设计.md": "line1" + NL + "old"},
            incoming_contents={"2 设计.md": "line1" + NL + "new"},
        )
        entry = {item.rel_path: item for item in session.entries}["2 设计.md"]
        self.assertTrue(entry.diff_lines)
        joined = NL.join(entry.diff_lines)
        self.assertIn("-old", joined)
        self.assertIn("+new", joined)

    def test_diff_missing_contents_does_not_break(self):
        session = open_preview(_changes(), source_path="new.docx", baseline_available=True)
        entry = {item.rel_path: item for item in session.entries}["2 设计.md"]
        self.assertFalse(entry.diff_lines)
        self.assertTrue(entry.applicable)

    def test_toggle_blocked_items_refused(self):
        session = open_preview(
            _changes(), source_path="new.docx", baseline_available=True, dirty_paths=["1 概述.md"]
        )
        self.assertFalse(toggle_selection(session, "1 概述.md", True))
        self.assertFalse(toggle_selection(session, "3 冲突.md", True))
        self.assertFalse(toggle_selection(session, "missing.md", True))
        self.assertTrue(toggle_selection(session, "2 设计.md", False))
        # 取消后可重新选中（不是被阻项）
        self.assertTrue(toggle_selection(session, "2 设计.md", True))

    def test_cancel_writes_nothing(self):
        session = open_preview(_changes(), source_path="new.docx", baseline_available=True)
        service = mock.Mock()
        cancel_session(session)
        outcome = apply_session(session, service, "new.docx")
        self.assertFalse(outcome["success"])
        self.assertIn("取消", outcome["message"])
        service.reimport.assert_not_called()
        self.assertTrue(session.closed)
        self.assertFalse([item for item in session.entries if item.selected])


class ApplySessionTests(unittest.TestCase):
    def test_apply_passes_only_applicable(self):
        session = open_preview(
            _changes(), source_path="new.docx", baseline_available=True, dirty_paths=["2 设计.md"]
        )
        service = mock.Mock()
        service.reimport.return_value = mock.Mock(success=True, message="")
        outcome = apply_session(session, service, "new.docx")
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["applied"], ["1 概述.md"])
        self.assertIn("3 冲突.md", outcome["blocked"])
        self.assertIn("2 设计.md", outcome["blocked"])
        choices = service.reimport.call_args.kwargs["choices"]
        self.assertTrue(choices["1 概述.md"])
        self.assertFalse(choices["3 冲突.md"])

    def test_apply_failure_rolls_back(self):
        session = open_preview(_changes(), source_path="new.docx", baseline_available=True)
        service = mock.Mock()
        service.reimport.side_effect = RuntimeError("写入失败")
        outcome = apply_session(session, service, "new.docx")
        self.assertFalse(outcome["success"])
        self.assertTrue(outcome["rolledBack"])

    def test_apply_with_no_selection_is_noop(self):
        session = open_preview(_changes(), source_path="new.docx", baseline_available=True)
        for item in session.entries:
            toggle_selection(session, item.rel_path, False)
        service = mock.Mock()
        outcome = apply_session(session, service, "new.docx")
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["applied"], [])
        service.reimport.assert_not_called()

    def test_dirty_paths_normalized_for_windows_separators(self):
        session = open_preview(
            _changes(),
            source_path="new.docx",
            baseline_available=True,
            dirty_paths=["2 设计.md".replace("/", "\\")],
        )
        entry = {item.rel_path: item for item in session.entries}["2 设计.md"]
        self.assertTrue(entry.dirty, "反斜杠路径也应识别为脏内容")


if __name__ == "__main__":
    unittest.main()