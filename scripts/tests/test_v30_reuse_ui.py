# -*- coding: utf-8 -*-
"""V3.0 6.1/6.2 测试：模块库/引用解析/展开副本入口（离屏）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

FENCE = chr(96) * 3


class ReuseDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("reuse-dialog")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        from doc_tool.application.content import reuse_commands as reuse
        from doc_tool.application.effective_snapshot import discover_chapters

        content = cls.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content)]
        cls.reference_chapter = rels[0]
        context = reuse.load_context(cls.project)
        result = reuse.extract_chapter_module(context, rels[1], module_id="m-arch", version="1.0.0")
        assert result.get("ok"), result
        first = content / rels[0]
        first.write_text(
            first.read_text(encoding="utf-8") + "\n{0}doc-module id=m-arch version=1.0.0 slot=s1\n{0}\n".format(FENCE),
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _dialog(self):
        from doc_tool.ui.reuse_dialog import ReuseDialog

        return ReuseDialog(self.project)

    def test_module_list_and_preview(self):
        dialog = self._dialog()
        self.assertGreaterEqual(dialog.module_list.count(), 1)
        dialog.module_list.setCurrentRow(0)
        text = dialog.preview.toPlainText()
        self.assertIn("模块：", text)
        self.assertIn("架构正文", text)
        dialog.deleteLater()

    def test_search_filters_modules(self):
        dialog = self._dialog()
        dialog.search_input.setText("不存在的模块名")
        self.assertEqual(dialog.module_list.count(), 0)
        dialog.search_input.setText("m-arch")
        self.assertGreaterEqual(dialog.module_list.count(), 1)
        dialog.deleteLater()

    def test_resolve_report_lists_chapter_and_source(self):
        dialog = self._dialog()
        dialog.refresh_report()
        report = dialog.preview.toPlainText()
        self.assertTrue(report.strip())
        self.assertIn("第1章", report)
        self.assertTrue("m-arch" in report or "来源" in report or "模块" in report)
        dialog.deleteLater()

    def test_export_expanded_copy_into_chosen_directory(self):
        from doc_tool.application.content import reuse_commands as reuse

        target = self.work / "expanded"
        target.mkdir(parents=True, exist_ok=True)
        dialog = self._dialog()
        infos = []
        with patch(
            "doc_tool.ui.reuse_dialog.QFileDialog.getExistingDirectory",
            return_value=str(target),
        ), patch(
            "doc_tool.ui.reuse_dialog.QMessageBox.information",
            side_effect=lambda *a, **k: infos.append(a),
        ):
            dialog.export_expanded_copy()
        self.assertTrue(infos, "导出成功应给出结果提示")
        copied = [
            path for path in target.rglob("*.md")
            if "展开副本说明" not in path.read_text(encoding="utf-8", errors="replace")
        ]
        self.assertTrue(copied, "展开副本应包含普通 Markdown 章节")
        body = "".join(path.read_text(encoding="utf-8") for path in copied)
        self.assertNotIn("doc-module", body, "展开副本章节不得保留模块引用标记")
        self.assertIn("架构正文", body)
        self.assertIn("目的正文", body)
        dialog.deleteLater()


class ReuseEntryTests(unittest.TestCase):
    """主窗口入口存在且调用真实对话框（离屏）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        self._recent.start()
        self.window = MainWindow()

    def tearDown(self):
        self._recent.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass

    def test_action_exists_and_requires_project(self):
        self.assertTrue(hasattr(self.window, "_reuse_action"))
        self.assertIn("模块库", self.window._reuse_action.text())
        messages = []
        self.window._show_status_message = lambda message: messages.append(str(message))
        self.window._on_reuse_dialog()
        self.assertTrue(any("项目" in item for item in messages), messages)

    def test_handler_opens_dialog_when_project_open(self):
        from doc_tool.ui import reuse_dialog as module

        opened = []

        class _FakeDialog:
            # UI 包 4.2 后入口还会传缓冲/插入回调；测试关心的是真实项目路径。
            def __init__(self, project_root, parent=None, **kwargs):
                opened.append(str(project_root))

            def exec(self):
                return 0

            def deleteLater(self):
                return None

        class _Summary:
            project_root = "X:/proj"

        self.window._project_summary = _Summary()
        with patch.object(module, "ReuseDialog", _FakeDialog):
            self.window._on_reuse_dialog()
        self.assertEqual(opened, ["X:/proj"])


if __name__ == "__main__":
    unittest.main(verbosity=2)