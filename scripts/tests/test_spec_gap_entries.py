# -*- coding: utf-8 -*-
"""规范缺口补测：CORE R9 重新定位；V3.3 建议导出入口。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class RelocateRecentProjectTests(unittest.TestCase):
    """CORE R9：失效的最近记录必须能“重新定位”（不是只能移除）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("core-relocate")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _recent_entry(self, path: Path):
        from doc_tool.application.project_service import RecentEntry

        manifest = __import__("doc_tool.domain.manifest", fromlist=["ProjectManifest"]).ProjectManifest.load(self.project)
        return RecentEntry(
            path=str(path), name=path.name, document_name=manifest.documentName,
            document_no=manifest.documentNo, document_type=manifest.documentType, last_opened="",
        )

    def test_invalid_entry_offers_relocate_button(self):
        from doc_tool.ui.empty_state import EmptyState

        calls = []
        page = EmptyState(on_relocate_recent=lambda old, new: calls.append((old, new)))
        missing = self.work / "已移动的项目"
        page.set_recent_projects([self._recent_entry(missing)])
        buttons = page.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
        relocate = [b for b in buttons if b.property("recentAction") == "relocate"]
        self.assertTrue(relocate, "失效条目应有重新定位按钮")
        self.assertTrue(relocate[0].isEnabled(), "重新定位按钮必须可用（此前定位被禁用）")

        with patch(
            "PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(self.project)
        ):
            relocate[0].click()
        self.assertEqual(calls, [(str(missing), str(self.project))])
        page.deleteLater()

    def test_non_project_directory_is_rejected(self):
        from doc_tool.ui.empty_state import EmptyState

        calls = []
        page = EmptyState(on_relocate_recent=lambda old, new: calls.append((old, new)))
        missing = self.work / "已移动的项目"
        page.set_recent_projects([self._recent_entry(missing)])
        buttons = page.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
        relocate = [b for b in buttons if b.property("recentAction") == "relocate"][0]
        not_a_project = self.work / "随便一个目录"
        not_a_project.mkdir(parents=True, exist_ok=True)
        with patch(
            "PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(not_a_project)
        ), patch("PySide6.QtWidgets.QMessageBox.information") as info:
            relocate.click()
        self.assertEqual(calls, [], "非项目目录不得改列表")
        self.assertTrue(info.called, "应提示所选目录不是项目")
        page.deleteLater()

    def test_window_updates_recent_store_on_relocate(self):
        from doc_tool.application.project_service import load_recent_projects, remove_recent_project
        from doc_tool.ui.main_window import MainWindow

        moved = self.work / "原来的位置"
        moved.mkdir(parents=True, exist_ok=True)
        # 先把“旧路径”真的写进最近列表，否则“旧路径已移除”是空断言（复核指出）
        from doc_tool.application.project_service import add_recent_project
        from doc_tool.domain.manifest import ProjectManifest

        add_recent_project(str(moved), ProjectManifest.load(self.project))
        self.assertTrue(
            any(str(entry.path) == str(moved) for entry in load_recent_projects()),
            "测试前置：旧路径已在最近列表",
        )
        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            window = MainWindow()
        try:
            window._on_relocate_recent(str(moved), str(self.project))
            entries = [entry.path for entry in load_recent_projects()]
            self.assertTrue(
                any(Path(item).resolve() == self.project.resolve() for item in entries),
                entries,
            )
            self.assertFalse(
                any(Path(item).resolve() == moved.resolve() for item in entries),
                "旧路径应从最近列表移除",
            )
        finally:
            window.close()
            remove_recent_project(str(self.project))


class SuggestionExportEntryTests(unittest.TestCase):
    """V3.3：建议导出必须有生产入口（此前 export_suggestions 零调用方）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v33-export-entry")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_panel_exports_suggestions_to_chosen_file(self):
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        assistant = build_assistant(self.project)
        panel = AssistPanel(assistant, project_root=self.project)
        panel.load_all_suggestions()
        text = panel.suggestions_export_text()
        self.assertTrue(text.strip(), "应有可导出的建议文本")

        target = self.work / "建议清单.md"
        with patch(
            "PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(target), "")
        ):
            written = panel.export_suggestions_to_file()
        self.assertEqual(written, str(target))
        self.assertTrue(target.is_file())
        self.assertIn("建议", target.read_text(encoding="utf-8"))

    def test_read_only_project_can_still_export(self):
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        assistant = build_assistant(self.project, read_only=True)
        panel = AssistPanel(assistant, project_root=self.project)
        panel.load_all_suggestions()
        target = self.work / "只读建议.md"
        with patch(
            "PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(target), "")
        ):
            written = panel.export_suggestions_to_file()
        self.assertEqual(written, str(target))
        self.assertTrue(target.is_file(), "只读项目也要能导出建议供审阅")


if __name__ == "__main__":
    unittest.main(verbosity=2)