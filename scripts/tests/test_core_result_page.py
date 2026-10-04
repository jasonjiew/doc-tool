# -*- coding: utf-8 -*-
"""CORE-C 3.3 测试：导入结果页、分组归并、就地替换图片与界面动作接线。"""

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
from doc_tool.application.import_record import (  # noqa: E402
    HANDLING_EDITABLE, HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER,
    ImportRecord, read_import_record, write_import_record,
)
from doc_tool.application.intake_contract import PreservationFinding  # noqa: E402
from doc_tool.application.intake_entries import run_intake  # noqa: E402
from doc_tool.application.intake_result_page import (  # noqa: E402
    ACTION_LOCATE, ACTION_REPLACE_IMAGE, ACTION_VIEW_ORIGINAL,
    build_result_page, replace_placeholder_image, resolve_chapter_rel_path,
)


class ResultPageServiceTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("result-page")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _missing_image_project(self) -> Path:
        out = self.work / "out"
        out.mkdir(parents=True, exist_ok=True)
        image = fixtures.tiny_png(self.work / "a.png")
        source = fixtures.image_docx(self.work / "缺图.docx", image)
        fixtures.drop_media_parts(source)
        outcome = run_intake(source, parent_dir=out)
        self.assertTrue(outcome.ok, outcome.errors)
        return Path(outcome.project_root)

    def test_page_groups_gaps_and_limits_actions(self):
        project = self._missing_image_project()
        record = read_import_record(project)
        record.findings = [
            PreservationFinding("image", HANDLING_PLACEHOLDER, target_chapter="图示",
                                detail="缺图", action="定位此处 → 选择替代图片"),
            PreservationFinding("formula", HANDLING_ORIGINAL_ONLY, target_chapter="图示", detail="公式"),
            PreservationFinding("textbox", HANDLING_ORIGINAL_ONLY, target_chapter="图示", detail="文本框"),
            PreservationFinding("footnote", HANDLING_ORIGINAL_ONLY, target_chapter="图示", detail="脚注"),
            PreservationFinding("comment", HANDLING_EDITABLE, editable=True, severity="info", detail="批注"),
        ]
        write_import_record(project, record)
        page = build_result_page(project)
        self.assertTrue(page.hasRecord)
        self.assertLessEqual(len(page.actions), 3)
        self.assertEqual(page.toFix, 4)
        self.assertEqual(page.autoHandled, 1)
        self.assertTrue(page.groups, page.groups)
        self.assertEqual(len(page.details), 5)
        kinds = {item.kind for item in page.actions}
        self.assertIn(ACTION_REPLACE_IMAGE, kinds)
        self.assertIn(ACTION_VIEW_ORIGINAL, kinds)
        self.assertTrue(page.needsAttention)
        self.assertTrue(page.summary)
        self.assertIn("原件已保留", " ".join(page.summary))

    def test_locate_action_resolves_real_chapter_path(self):
        project = self._missing_image_project()
        page = build_result_page(project)
        action = page.actions[0]
        self.assertTrue(action.relPath, action)
        content_root = project / "content" / "general"
        self.assertTrue((content_root / action.relPath).is_file())
        self.assertEqual(
            resolve_chapter_rel_path(project, "图示"), action.relPath,
        )
        self.assertEqual(resolve_chapter_rel_path(project, "不存在的章节"), "")

    def test_replace_placeholder_image_updates_body_and_ledger(self):
        project = self._missing_image_project()
        page = build_result_page(project)
        action = next(item for item in page.actions if item.kind == ACTION_REPLACE_IMAGE)
        replacement = fixtures.tiny_png(self.work / "new.png")
        outcome = replace_placeholder_image(
            project, action.relPath, replacement, line=action.line,
        )
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue((project / "assets" / "general" / outcome.imageRelPath).is_file())
        body = (project / "content" / "general" / action.relPath).read_text(encoding="utf-8")
        self.assertIn("images/", body)
        self.assertNotIn("[[待完善", body)
        after = build_result_page(project)
        self.assertEqual(after.toFix, 0)
        self.assertEqual(after.autoHandled, 1)

    def test_replace_image_errors_are_reported_without_touching_body(self):
        project = self._missing_image_project()
        page = build_result_page(project)
        action = next(item for item in page.actions if item.kind == ACTION_REPLACE_IMAGE)
        body_path = project / "content" / "general" / action.relPath
        before = body_path.read_text(encoding="utf-8")
        missing = replace_placeholder_image(project, action.relPath, self.work / "nope.png")
        self.assertFalse(missing.ok)
        self.assertIn("不存在", missing.message)
        escape = replace_placeholder_image(project, "../outside.md", self.work / "a.png")
        self.assertFalse(escape.ok)
        self.assertEqual(body_path.read_text(encoding="utf-8"), before)
        no_placeholder = replace_placeholder_image(project, "_revision_record.md", self.work / "a.png")
        self.assertFalse(no_placeholder.ok)


class ResultPageUiTests(unittest.TestCase):
    """界面：结果页按钮映射到真实动作；替换动作复用资源修复服务。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("result-ui")
        out = self.work / "out"
        out.mkdir(parents=True, exist_ok=True)
        image = fixtures.tiny_png(self.work / "a.png")
        source = fixtures.image_docx(self.work / "缺图.docx", image)
        fixtures.drop_media_parts(source)
        outcome = run_intake(source, parent_dir=out)
        self.assertTrue(outcome.ok, outcome.errors)
        self.project = Path(outcome.project_root)
        record = read_import_record(self.project)
        self.assertTrue(record and record.findings)

        from doc_tool.application.project_service import load_recent_projects
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch(
            "doc_tool.application.project_service.load_recent_projects",
            return_value=[],
        )
        self._recent.start()
        self.window = MainWindow()
        self._infos = []
        self._patches = [
            patch("doc_tool.ui.main_window.QMessageBox.information",
                  side_effect=lambda *a, **k: self._infos.append(a)),
            patch("doc_tool.ui.main_window.QMessageBox.warning", lambda *a, **k: None),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._recent.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def test_action_buttons_call_real_services(self):
        """结果窗口的替换动作复用既有资源修复服务（真实服务调用）。"""
        clicked_actions = []

        def _fake_replace(project_root, rel_path, source, line=None):
            clicked_actions.append((rel_path, str(source)))

            class _Outcome:
                ok = True

                def summary_line(self):
                    return "已替换"

            return _Outcome()

        with patch(
            "doc_tool.ui.main_window.QFileDialog.getOpenFileName",
            return_value=(str(self.work / "a.png"), ""),
        ), patch(
            "doc_tool.application.intake_result_page.replace_placeholder_image", _fake_replace
        ):
            self.window._show_intake_result_page(str(self.project))
            window = self.window._intake_result_window
            self.assertIsNotNone(window, "结果窗口应已打开")
            self.assertFalse(window.isModal())
            # 选中第一条占位事实（替换动作仅对占位项可用）
            target_row = None
            for row in range(window._table.rowCount()):
                if window._rows_cache[row].get("handling") == "placeholder":
                    target_row = row
                    break
            self.assertIsNotNone(target_row, "缺图项目应至少有一条占位事实")
            window._table.selectRow(target_row)
            self.assertTrue(window._replace_btn.isEnabled())
            window._on_replace_image()
        self.assertTrue(clicked_actions, "结果窗口动作应调用替换图片服务")

    def test_details_view_shows_full_facts(self):
        """完整处理事实在同一个非模态窗口里可查（不再截断到 40 项）。"""
        page = build_result_page(self.project)
        self.window._show_intake_result_page(str(self.project))
        window = self.window._intake_result_window
        self.assertIsNotNone(window)
        self.assertEqual(len(window._rows), len(page.details))
        self.assertIn("共 {0} 项处理事实".format(len(page.details)), window._counts.text())
        self.assertGreater(window._table.rowCount(), 0)

    def test_view_original_action_opens_retained_file(self):
        from doc_tool.application.intake_result_page import ResultAction

        opened = []
        self.window._on_open_result_output = lambda path: opened.append(path)
        action = ResultAction(kind=ACTION_VIEW_ORIGINAL, label="查看原件",
                              retainedPath="original/source.docx")
        self.window._run_intake_action(str(self.project), action)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].endswith("source.docx"))
        self.assertTrue(Path(opened[0]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)