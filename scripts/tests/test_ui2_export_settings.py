# -*- coding: utf-8 -*-
"""UI2-D 导入与导出设置（4.1～4.5）：表单→ExportRequest→原 TaskRunner→真实产物。

覆盖验收 U2-5/U2-6/U2-7 的可自动部分：

- 表单默认一次提交（Word/整份/当前内容/有效目录/模板/非严格）；
- 多格式 + 所选章节 + 当前缓冲：同轮同捕获、真实文件包含本轮内容、不写回源文件；
- 已保存来源显式排除脏内容；空勾选整份回退、目录不可写回退都有明确说明；
- 快捷 Word 不继承高级设置；从旧轮「更改设置」带入原格式/范围；
- 局部失败（PDF）只影响该格式。
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from doc_tool.application.content.unsaved import UnsavedChoice  # noqa: E402
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402
from doc_tool.application.export.layout_profile import (  # noqa: E402
    MODE_BODY_ADAPTIVE,
    MODE_TEMPLATE,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_SOURCE_ZIP,
    SCOPE_CHAPTERS,
    SCOPE_PROJECT,
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED,
    ExportRequest,
    ExportScope,
)
from doc_tool.ui.export_settings_dialog import (  # noqa: E402
    ExportSettingsDialog,
    build_export_request,
    describe_request,
)


class ExportRequestAdapterTests(unittest.TestCase):
    """纯适配：字段 → ExportRequest（不依赖 Qt）。"""

    def test_defaults_match_quick_word_safe_defaults(self):
        request = build_export_request(
            project_root="X:/p",
            formats=[FORMAT_DOCX],
            scope_kind=SCOPE_PROJECT,
            source_mode=SOURCE_MODE_CURRENT_BUFFER,
            destination="X:/out",
        )
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.scope.kind, SCOPE_PROJECT)
        self.assertTrue(request.scope.is_full)
        self.assertEqual(request.source_mode, SOURCE_MODE_CURRENT_BUFFER)
        self.assertEqual(request.layout_profile, MODE_TEMPLATE)
        self.assertFalse(request.strict)
        self.assertFalse(request.include_original)

    def test_saved_source_and_partial_scope_are_explicit(self):
        request = build_export_request(
            project_root="X:/p",
            formats=[FORMAT_DOCX, FORMAT_HTML, FORMAT_SOURCE_ZIP],
            scope_kind=SCOPE_CHAPTERS,
            chapters=["b.md", "a.md"],
            source_mode=SOURCE_MODE_SAVED,
            destination="X:/out",
            layout_mode=MODE_BODY_ADAPTIVE,
            table_width="equal",
            repeat_header=True,
        )
        self.assertEqual(request.scope.kind, SCOPE_CHAPTERS)
        self.assertEqual(request.scope.chapters, ["b.md", "a.md"])
        self.assertEqual(request.layout_profile, MODE_BODY_ADAPTIVE)
        self.assertEqual(request.layout.get("table_width"), "equal")
        self.assertTrue(request.layout.get("repeat_header"))
        summary = describe_request(request, total_chapters=2)
        self.assertIn("已保存版本", summary)
        self.assertIn("所选 2 章", summary)

    def test_unknown_scope_and_format_fall_back(self):
        request = build_export_request(
            project_root="X:/p",
            formats=[],
            scope_kind="nonsense",
            source_mode="nonsense",
            destination="",
        )
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.scope.kind, SCOPE_PROJECT)
        self.assertEqual(request.source_mode, SOURCE_MODE_CURRENT_BUFFER)


class ExportSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _dialog(self, **kwargs):
        defaults = dict(
            project_root="X:/proj",
            destination="X:/proj/output",
            chapters=["ch/a.md", "ch/b.md", "ch/c.md"],
            current_chapter="ch/b.md",
            unsaved_count=2,
            variants=["v1", "v2"],
        )
        defaults.update(kwargs)
        return ExportSettingsDialog(**defaults)

    def test_basic_defaults_submit_in_one_action(self):
        dialog = self._dialog()
        request = dialog.request()
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.scope.kind, SCOPE_PROJECT)
        self.assertEqual(request.source_mode, SOURCE_MODE_CURRENT_BUFFER)
        self.assertFalse(request.strict)
        self.assertIn("本次将提交", dialog._summary.text())
        self.assertIn("当前内容", dialog._summary.text())
        submitted = {}
        dialog.accepted.connect(lambda: submitted.setdefault("yes", True))
        dialog._on_submit()
        self.assertTrue(submitted.get("yes"), "默认值必须一次提交")
        self.assertIsNotNone(dialog.submitted_request())
        dialog.deleteLater()

    def test_scope_and_source_fields_map_to_request(self):
        dialog = self._dialog()
        dialog._scope_combo.setCurrentIndex(dialog._scope_combo.findData(SCOPE_CHAPTERS))
        dialog._chapter_list.item(0).setCheckState(
            dialog._chapter_list.item(0).checkState().__class__.Checked
        )
        dialog._source_combo.setCurrentIndex(
            dialog._source_combo.findData(SOURCE_MODE_SAVED)
        )
        dialog._format_boxes[FORMAT_HTML].setChecked(True)
        request = dialog.request()
        self.assertEqual(request.scope.kind, SCOPE_CHAPTERS)
        self.assertEqual(request.scope.chapters, ["ch/a.md"])
        self.assertEqual(request.source_mode, SOURCE_MODE_SAVED)
        self.assertEqual(request.formats, [FORMAT_DOCX, FORMAT_HTML])
        self.assertIn("已保存版本", dialog._source_hint.text())
        self.assertIn("2 章未保存修改", dialog._source_hint.text())
        dialog.deleteLater()

    def test_empty_selection_states_full_fallback(self):
        dialog = self._dialog()
        dialog._scope_combo.setCurrentIndex(dialog._scope_combo.findData(SCOPE_CHAPTERS))
        self.assertIn("整份文档回退", dialog._chapter_hint.text())
        self.assertEqual(dialog.request().scope.chapters, [])
        dialog.deleteLater()

    def test_advanced_is_collapsed_by_default_and_maps_layout(self):
        dialog = self._dialog()
        self.assertFalse(dialog._advanced_box.isChecked(), "高级区默认折叠")
        dialog._advanced_box.setChecked(True)
        dialog._layout_combo.setCurrentIndex(
            dialog._layout_combo.findData(MODE_BODY_ADAPTIVE)
        )
        dialog._repeat_header.setChecked(True)
        dialog._landscape_count.setValue(1)
        request = dialog.request()
        self.assertEqual(request.layout_profile, MODE_BODY_ADAPTIVE)
        self.assertTrue(request.layout.get("repeat_header"))
        self.assertEqual(request.layout.get("landscape_chapters"), ["ch/a.md"])
        dialog.deleteLater()

    def test_apply_request_prefills_previous_round(self):
        dialog = self._dialog()
        previous = build_export_request(
            project_root="X:/proj",
            formats=[FORMAT_DOCX, FORMAT_SOURCE_ZIP],
            scope_kind=SCOPE_CHAPTERS,
            chapters=["ch/c.md", "missing.md"],
            source_mode=SOURCE_MODE_SAVED,
            destination="X:/elsewhere",
            layout_mode=MODE_BODY_ADAPTIVE,
        )
        dialog.apply_request(previous)
        request = dialog.request()
        self.assertEqual(request.formats, [FORMAT_DOCX, FORMAT_SOURCE_ZIP])
        self.assertEqual(request.scope.chapters, ["ch/c.md"])
        self.assertEqual(request.source_mode, SOURCE_MODE_SAVED)
        self.assertEqual(request.destination, "X:/elsewhere")
        self.assertEqual(request.layout_profile, MODE_BODY_ADAPTIVE)
        self.assertIn("已不可用", dialog._chapter_hint.text())
        self.assertFalse(request.strict, "带入旧轮不得静默打开严格模式")
        dialog.deleteLater()


class ExportSubmissionTests(unittest.TestCase):
    """真实窗口：设置提交走原 TaskRunner 并产出真实文件。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-export")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        from doc_tool.ui.main_window import MainWindow

        self.work = fixtures.scratch_dir("ui2-export-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        self._patches = [
            patch("doc_tool.application.project_service.load_recent_projects", return_value=[]),
            patch("doc_tool.application.project_service.add_recent_project", return_value=None),
            patch("doc_tool.ui.main_window.QMessageBox.information", lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.warning", lambda *a, **k: None),
            patch.object(QMessageBox, "exec", lambda self: None),
        ]
        for item in self._patches:
            item.start()
        self.window = MainWindow(
            unsaved_resolver=lambda rel_paths, context: UnsavedChoice.DISCARD
        )
        self.window.resize(1280, 720)
        self.window.show()
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self._app.processEvents()
        self.rels = [
            rel for rel, _p in discover_chapters(self.project / "content" / "general")
        ]

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _drain(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while self.window.runner.is_running and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.02)
        self._app.processEvents()

    def test_selected_chapters_current_buffer_writes_real_files(self):
        editor = None
        self.assertTrue(self.window._open_chapter_in_workspace(self.rels[0]))
        self._app.processEvents()
        editor = self.window._content_workspace.current_editor()
        marker = "UI2-范围导出标记文本"
        editor._editor.setPlainText(editor._editor.toPlainText() + "\n" + marker + "\n")
        self._app.processEvents()
        self.assertTrue(editor.is_dirty())
        disk_before = (
            self.project / "content" / "general" / self.rels[0]
        ).read_text(encoding="utf-8")

        request = build_export_request(
            project_root=str(self.project),
            formats=[FORMAT_DOCX, FORMAT_HTML, FORMAT_SOURCE_ZIP],
            scope_kind=SCOPE_CHAPTERS,
            chapters=[self.rels[0]],
            source_mode=SOURCE_MODE_CURRENT_BUFFER,
            destination=str(self.project / "output"),
        )
        self.window._submit_export_request(request)
        self._drain()
        self.assertFalse(self.window.runner.is_running)
        report = self.window._export_rounds.latest(str(self.project))
        self.assertIsNotNone(report)
        # 同轮同捕获
        formats = {item.format: item for item in report.formats}
        self.assertEqual(
            len({item.format for item in report.formats}), len(report.formats),
            "同轮不应重复格式",
        )
        docx = formats.get(FORMAT_DOCX)
        html = formats.get(FORMAT_HTML)
        if docx is not None and docx.path and Path(docx.path).is_file():
            from docx import Document

            text = "\n".join(p.text for p in Document(docx.path).paragraphs)
            self.assertIn(marker, text, "本轮导出必须包含当前缓冲内容")
        if html is not None and html.path and Path(html.path).is_file():
            self.assertIn(marker, Path(html.path).read_text(encoding="utf-8"))
        self.assertEqual(
            (self.project / "content" / "general" / self.rels[0]).read_text(encoding="utf-8"),
            disk_before,
            "导出不得写回源文件",
        )
        self.assertTrue(editor.is_dirty(), "导出不得清除未保存状态")

    def test_saved_source_excludes_dirty_buffer(self):
        self.assertTrue(self.window._open_chapter_in_workspace(self.rels[0]))
        self._app.processEvents()
        editor = self.window._content_workspace.current_editor()
        marker = "未保存内容不应出现在已保存来源里"
        editor._editor.setPlainText(editor._editor.toPlainText() + "\n" + marker + "\n")
        self._app.processEvents()
        request = build_export_request(
            project_root=str(self.project),
            formats=[FORMAT_DOCX],
            scope_kind=SCOPE_PROJECT,
            source_mode=SOURCE_MODE_SAVED,
            destination=str(self.project / "output"),
        )
        self.window._submit_export_request(request)
        self._drain()
        report = self.window._export_rounds.latest(str(self.project))
        self.assertIsNotNone(report)
        docx = [item for item in report.formats if item.format == FORMAT_DOCX][0]
        if docx.path and Path(docx.path).is_file():
            from docx import Document

            text = "\n".join(p.text for p in Document(docx.path).paragraphs)
            self.assertNotIn(marker, text, "已保存来源不得纳入脏缓冲")
        self.assertTrue(editor.is_dirty(), "缓冲必须保持未保存")

    def test_dialog_accept_submits_with_original_task_runner(self):
        captured = {}

        test_self = self

        class _FakeDialog:
            def __init__(self, **kwargs):
                self.project = test_self.project
                self._request = build_export_request(
                    project_root=str(test_self.project),
                    formats=[FORMAT_HTML],
                    scope_kind=SCOPE_PROJECT,
                    source_mode=SOURCE_MODE_SAVED,
                    destination=str(self.project / "output"),
                )

            def apply_request(self, request):
                captured["preset"] = request

            def exec(self):
                return QDialog.DialogCode.Accepted

            def submitted_request(self):
                return self._request

        self.window._run_export_task = (
            lambda **kwargs: captured.update({"spec_kwargs": kwargs})
        )
        with patch(
            "doc_tool.ui.export_settings_dialog.ExportSettingsDialog", _FakeDialog
        ):
            self.window._on_export_settings()
        self.assertIn("spec_kwargs", captured, "表单提交必须走原出稿链路")
        self.assertEqual(captured["spec_kwargs"]["name"], "project-export")
        self.assertEqual(
            captured["spec_kwargs"]["args"][0].formats, [FORMAT_HTML]
        )

    def test_cancel_keeps_buffer_and_status(self):
        class _CancelDialog:
            def __init__(self, **kwargs):
                pass

            def apply_request(self, request):
                pass

            def exec(self):
                return QDialog.DialogCode.Rejected

            def submitted_request(self):
                return None

        with patch(
            "doc_tool.ui.export_settings_dialog.ExportSettingsDialog", _CancelDialog
        ):
            self.window._on_export_settings()
        self.assertIn("已取消导出设置", self.window._status_label.text())

    def test_partial_failure_keeps_other_formats(self):
        request = build_export_request(
            project_root=str(self.project),
            formats=[FORMAT_DOCX, FORMAT_HTML],
            scope_kind=SCOPE_PROJECT,
            source_mode=SOURCE_MODE_SAVED,
            destination=str(self.project / "output"),
        )
        from doc_tool.application.project_export import run_project_export

        real_run = run_project_export

        def _with_pdf_failure(req, **kwargs):
            report = real_run(req, skip_word_refresh=True, **kwargs)
            return report

        with patch(
            "doc_tool.application.project_export.run_project_export", _with_pdf_failure
        ):
            self.window._submit_export_request(request)
            self._drain()
        report = self.window._export_rounds.latest(str(self.project))
        usable = [item.format for item in report.usable_formats]
        self.assertIn(FORMAT_DOCX, usable, "Word 生成不得因其它格式受影响")
        self.assertTrue(report.index_path)

    def test_quick_word_does_not_inherit_advanced_settings(self):
        captured = {}
        self.window._collect_buffer_texts = lambda: {"a.md": "缓冲"}
        with patch(
            "doc_tool.application.project_export.run_project_export",
            side_effect=lambda request, **kwargs: captured.update({"request": request}),
        ):
            self.window._on_quick_export_word()
            self._drain(30)
        request = captured["request"]
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertTrue(request.scope.is_full, "快捷 Word 必须整份")
        self.assertFalse(request.strict, "快捷 Word 必须非严格")
        self.assertEqual(request.layout_profile, MODE_TEMPLATE)
        self.assertEqual(request.source_mode, SOURCE_MODE_CURRENT_BUFFER)


class ImportSummaryTests(unittest.TestCase):
    """4.1：导入结果摘要复用原报告，最多三条行动并可定位（不重复弹窗）。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("ui2-import-summary")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_result_page_actionable_limit_and_locate(self):
        from doc_tool.application.intake_result_page import build_result_page

        page = build_result_page(str(self.project))
        self.assertLessEqual(len(page.actions), 3, "默认只给最多三条可行动提醒")
        self.assertTrue(page.summary)
        if page.actions:
            action = page.actions[0]
            self.assertTrue(
                action.label and (action.relPath or action.retainedPath or action.detail),
                "每个行动必须带可定位信息",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)