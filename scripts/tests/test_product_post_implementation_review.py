# -*- coding: utf-8 -*-
"""独立复核：真实按钮、表格事务、冻结身份、草稿退出和样例隔离。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.tests import core_fixtures as fixtures
from doc_tool.application.content import table_grid as grid
from doc_tool.application import pack_authoring as authoring
from doc_tool.application.standard_pack import validate_pack_dir


class TableDataReviewTests(unittest.TestCase):
    def test_tsv_keeps_trailing_empty_and_whitespace_rows(self):
        parsed = grid.parse_clipboard_text("名称\t值\nA\t1\n\t\n  \t \n")
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.rows, [["名称", "值"], ["A", "1"], ["", ""], ["  ", " "]])

    def test_tsv_entire_empty_selection_keeps_dimensions(self):
        parsed = grid.parse_clipboard_text("\t\t\r\n\t\t\r\n")
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.rows, [["", "", ""], ["", "", ""]])

    def test_ambiguous_fragment_does_not_pick_by_distance(self):
        fragment = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        result = grid.locate_fragment(fragment + "\n\n" + fragment, fragment, near_line=1)
        self.assertFalse(result.ok, "距离不能证明原片段身份")

    def test_grid_multiline_serializes_as_supported_break(self):
        model = grid.model_from_matrix([["列1", "列2"], ["第一行\n第二行", "值"]])
        parsed = grid.parse_table(model.serialize())
        self.assertTrue(parsed.ok, parsed.error)
        self.assertEqual(parsed.model.rows, [["第一行<br>第二行", "值"]])


class PackFilesReviewTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("post-review-pack")
        self.draft = authoring.create_draft(self.work / "draft", pack_id="review", version="1.0", document_kind="general")
        self.draft.template = ""
        self.draft.variables = {"name": "first"}
        skeleton = self.draft.root / "skeleton" / "review.md"
        skeleton.parent.mkdir(parents=True)
        skeleton.write_text("# 样例\n\n验证内容。\n", encoding="utf-8")
        self.draft.skeleton = ["skeleton/review.md"]

    def tearDown(self):
        assert self.work.resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
        fixtures.cleanup(self.work)

    def test_clear_resource_does_not_leave_old_terms_in_pack(self):
        self.draft.terms = [{"canonical": "旧术语"}]
        authoring.freeze_draft(self.draft)
        self.draft.terms = []
        frozen = authoring.freeze_draft(self.draft)
        validated = validate_pack_dir(frozen["packDir"])
        self.assertTrue(validated.ok, validated.errors)
        terms_file = Path(frozen["packDir"]) / "terms.yml"
        if terms_file.exists():
            import yaml
            self.assertEqual(yaml.safe_load(terms_file.read_text(encoding="utf-8"))["terms"], [])
        self.assertNotIn("旧术语", "\n".join(p.read_text(encoding="utf-8") for p in Path(frozen["packDir"]).glob("*.yml")))

    def test_metadata_changes_are_not_reused_as_old_pack(self):
        first = authoring.freeze_draft(self.draft)
        self.draft.document_kind = "design"
        self.draft.description = "new description"
        second = authoring.freeze_draft(self.draft)
        self.assertNotEqual(first["packDir"], second["packDir"])
        pack = validate_pack_dir(second["packDir"]).pack
        self.assertEqual(pack.document_kind, "design")
        self.assertEqual(pack.description, "new description")

    def test_optional_template_empty_value_roundtrips_without_false_staleness(self):
        self.draft.sample = {"draftDigest": authoring.draft_digest(self.draft)}
        self.draft.save()
        loaded = authoring.PackDraft.load(self.draft.root)
        self.assertEqual(loaded.template, "")
        self.assertFalse(authoring.sample_is_stale(loaded))

    def test_copy_pack_keeps_unknown_metadata_and_declared_resources(self):
        import yaml
        from doc_tool.application.standard_pack import sha256_file
        first = authoring.freeze_draft(self.draft)
        base = Path(first["packDir"])
        extra = base / "declarations" / "future.yml"
        extra.parent.mkdir()
        extra.write_text("future: retained\n", encoding="utf-8")
        payload = yaml.safe_load((base / "pack.yml").read_text(encoding="utf-8"))
        payload["futureMetadata"] = {"owner": "engineering", "nested": [1, 2]}
        payload["files"]["declarations/future.yml"] = sha256_file(extra)
        (base / "pack.yml").write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
        copied = authoring.draft_from_pack(base, self.work / "copied")
        refrozen = authoring.freeze_draft(copied)
        new_base = Path(refrozen["packDir"])
        new_payload = yaml.safe_load((new_base / "pack.yml").read_text(encoding="utf-8"))
        self.assertEqual(new_payload["futureMetadata"], payload["futureMetadata"])
        self.assertEqual((new_base / "declarations/future.yml").read_bytes(), extra.read_bytes())

    def test_same_second_freezes_keep_each_previous_artifact(self):
        with patch("doc_tool.application.pack_authoring.time.strftime", return_value="20261003010101"):
            first = authoring.freeze_draft(self.draft)
            self.draft.variables["name"] = "second"
            second = authoring.freeze_draft(self.draft)
            before = (Path(second["packDir"]) / "variables.yml").read_bytes()
            self.draft.variables["name"] = "third"
            third = authoring.freeze_draft(self.draft)
        self.assertEqual(len({first["packDir"], second["packDir"], third["packDir"]}), 3)
        self.assertEqual((Path(second["packDir"]) / "variables.yml").read_bytes(), before)

    def test_export_exclusions_keep_zip_consumable_and_existing_zip_unchanged(self):
        import yaml
        from doc_tool.application.standard_pack import extract_pack_zip, sha256_file
        frozen = authoring.freeze_draft(self.draft)
        base = Path(frozen["packDir"])
        secret = base / "credentials.json"
        secret.write_text('{"token":"private"}', encoding="utf-8")
        payload = yaml.safe_load((base / "pack.yml").read_text(encoding="utf-8"))
        payload["files"]["credentials.json"] = sha256_file(secret)
        (base / "pack.yml").write_text(yaml.safe_dump(payload), encoding="utf-8")
        output = self.work / "zip"
        output.mkdir()
        first = authoring.export_zip(base, output)
        first_bytes = Path(first["path"]).read_bytes()
        loaded = extract_pack_zip(first["path"], self.work / "extracted")
        self.assertTrue(loaded.ok, loaded.errors)
        self.assertNotIn("credentials.json", loaded.pack.entries)
        second = authoring.export_zip(base, output)
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(Path(first["path"]).read_bytes(), first_bytes)

    def test_latest_sample_preserves_previous_project_and_artifacts(self):
        first = authoring.run_sample(self.draft, sample_root=self.work / "sample")
        self.assertTrue(first["htmlPath"])
        old_project = Path(first["projectRoot"])
        old_html = Path(first["htmlPath"])
        old_manifest = (old_project / "project.yml").read_bytes()
        old_content = old_html.read_bytes()
        self.draft.variables["name"] = "latest"
        second = authoring.run_sample(self.draft, sample_root=self.work / "sample")
        self.assertNotEqual(first["projectRoot"], second["projectRoot"])
        self.assertNotEqual(first["htmlPath"], second["htmlPath"])
        self.assertTrue(old_project.is_dir())
        self.assertEqual((old_project / "project.yml").read_bytes(), old_manifest)
        self.assertEqual(old_html.read_bytes(), old_content)
        self.assertEqual(authoring.PackDraft.load(self.draft.root).sample["captureId"], second["captureId"])

    def test_retry_sample_uses_original_capture_after_draft_changes(self):
        first = authoring.run_sample(self.draft, sample_root=self.work / "sample")
        old_html = Path(first["htmlPath"]).read_bytes()
        self.draft.variables["name"] = "changed after sample"
        retried = authoring.retry_sample_word(self.draft, skip_word_refresh=True)
        self.assertEqual(retried["captureId"], first["captureId"])
        self.assertEqual(retried["roundId"], first["roundId"])
        self.assertEqual(retried["draftDigest"], first["draftDigest"])
        self.assertEqual(Path(retried["htmlPath"]).read_bytes(), old_html)
        self.assertTrue(authoring.sample_is_stale(self.draft))

    def test_missing_sample_record_does_not_capture_latest_source(self):
        self.draft.sample = {"captureId": "original", "htmlPath": "old.html"}
        with patch("doc_tool.application.project_export.run_project_export") as export:
            result = authoring.retry_sample_word(self.draft)
        export.assert_not_called()
        self.assertEqual(result["captureId"], "original")
        self.assertEqual(result["htmlPath"], "old.html")
        self.assertIn("生成最新", result["message"])

    def test_same_freeze_identity_cannot_reuse_corrupted_artifact(self):
        first = authoring.freeze_draft(self.draft)
        target = Path(first["packDir"]) / "variables.yml"
        target.write_text("name: corrupted\n", encoding="utf-8")
        second = authoring.freeze_draft(self.draft)
        self.assertFalse(second["reused"], "坏 hash 的既有产物不能冒充同摘要")
        self.assertNotEqual(first["packDir"], second["packDir"])


class GuiReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("post-review-ui")
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.processEvents()
        assert self.work.resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
        fixtures.cleanup(self.work)

    def grid_dialog(self):
        from doc_tool.ui.content.table_grid_dialog import TableGridDialog
        dialog = TableGridDialog(grid.model_from_matrix([["A", "B", "C"], ["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]], alignments=["left", "center", "right"]))
        self.widgets.append(dialog)
        return dialog

    def test_insert_delete_column_preserves_alignment_identity(self):
        dialog = self.grid_dialog()
        dialog.table.setCurrentCell(1, 0)
        dialog._insert_column(after=True)
        self.assertEqual(dialog.result_model().alignments, ["left", "default", "center", "right"])
        dialog.table.setCurrentCell(1, 1)
        dialog._remove_columns()
        self.assertEqual(dialog.result_model().alignments, ["left", "center", "right"])

    def test_column_move_is_one_undo_transaction(self):
        dialog = self.grid_dialog()
        original = dialog.markdown_text()
        dialog.table.setCurrentCell(1, 1)
        dialog._move_column(-1)
        moved = dialog.markdown_text()
        self.assertNotEqual(moved, original)
        dialog.undo_grid()
        self.assertEqual(dialog.markdown_text(), original)
        dialog.redo_grid()
        self.assertEqual(dialog.markdown_text(), moved)

    def test_row_move_is_one_undo_transaction(self):
        dialog = self.grid_dialog()
        original = dialog.markdown_text()
        dialog.table.setCurrentCell(2, 0)
        dialog._move_row(-1)
        self.assertNotEqual(dialog.markdown_text(), original)
        dialog.undo_grid()
        self.assertEqual(dialog.markdown_text(), original)
        self.assertFalse(dialog._undo_stack, "内部 setItem 信号不能制造多次撤销")

    def test_selected_rows_move_together_without_reversing_order(self):
        from PySide6.QtWidgets import QTableWidgetSelectionRange
        dialog = self.grid_dialog()
        dialog.table.setRangeSelected(QTableWidgetSelectionRange(1, 0, 2, 2), True)
        dialog._move_row(1)
        self.assertEqual(dialog._matrix(), [["A", "B", "C"], ["7", "8", "9"], ["1", "2", "3"], ["4", "5", "6"]])

    def test_real_table_grid_and_paste_buttons_pass_no_click_boolean(self):
        from PySide6.QtWidgets import QDialog
        from doc_tool.ui.content.editor_panel import EditorPanel
        from doc_tool.ui.content.table_grid_dialog import TableGridDialog, TablePasteDialog
        class Writer:
            def resolve(self, rel_path):
                return ROOT / rel_path
        panel = EditorPanel(Writer())
        self.widgets.append(panel)
        source = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        panel.load("a.md", source)
        with patch.object(TableGridDialog, "exec", return_value=QDialog.DialogCode.Rejected) as opened:
            next(b for name, b in panel._md_actions if name == "表格网格").click()
        self.assertEqual(opened.call_count, 1, "真实按钮必须打开正确模型")
        self.app.clipboard().setText("列1\t列2\n内容\t值")
        captured = []
        def paste_preview(dialog):
            captured.append(dialog._result)
            return QDialog.DialogCode.Rejected
        with patch.object(TablePasteDialog, "exec", paste_preview):
            next(b for name, b in panel._md_actions if name == "粘贴为表格").click()
        self.assertTrue(captured[0].ok)
        self.assertEqual(captured[0].rows[1], ["内容", "值"])

    def pack_dialog(self):
        from doc_tool.ui.standard_pack_dialog import StandardPackDialog
        dialog = StandardPackDialog(draft_dir=str(self.work / "draft"))
        self.widgets.append(dialog)
        dialog.pack_id_edit.setText("ui-review")
        dialog.version_edit.setText("1.0")
        return dialog

    def editor_panel(self, source):
        from doc_tool.ui.content.editor_panel import EditorPanel
        class Writer:
            def resolve(self, rel_path):
                return ROOT / rel_path
        panel = EditorPanel(Writer())
        panel.load("review.md", source)
        self.widgets.append(panel)
        return panel

    def test_anchored_grid_does_not_modify_another_identical_table(self):
        from PySide6.QtGui import QTextCursor
        fragment = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        panel = self.editor_panel(fragment + "\n\n" + fragment)
        anchor = panel._capture_table_fragment(fragment, 1)
        edit = QTextCursor(panel._editor.document())
        edit.setPosition(panel._editor.document().findBlockByNumber(2).position() + 2)
        edit.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
        edit.insertText("9")
        before = panel._editor.toPlainText()
        ok, reason = panel._replace_table_fragment(fragment, "replacement", source_cursor=anchor, source_identity="review.md")
        self.assertFalse(ok, reason)
        self.assertEqual(panel._editor.toPlainText(), before)

    def test_anchored_grid_tracks_external_edit_and_undo_restores_table_only(self):
        from PySide6.QtGui import QTextCursor
        fragment = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        panel = self.editor_panel("前言\n\n" + fragment + "\n\n" + fragment)
        anchor = panel._capture_table_fragment(fragment, 3)
        edit = QTextCursor(panel._editor.document())
        edit.setPosition(0)
        edit.insertText("额外的前言\n")
        before = panel._editor.toPlainText()
        replacement = fragment.replace("| 1 |", "| 001 |")
        ok, reason = panel._replace_table_fragment(fragment, replacement, source_cursor=anchor, source_identity="review.md")
        self.assertTrue(ok, reason)
        self.assertEqual(panel._editor.toPlainText().count("001"), 1)
        panel._editor.undo()
        self.assertEqual(panel._editor.toPlainText(), before)

    def test_grid_rejects_file_switch(self):
        fragment = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        panel = self.editor_panel(fragment)
        anchor = panel._capture_table_fragment(fragment, 1)
        panel.load("another.md", fragment)
        ok, reason = panel._replace_table_fragment(fragment, "replacement", source_cursor=anchor, source_identity="review.md")
        self.assertFalse(ok, reason)
        self.assertEqual(panel._editor.toPlainText(), fragment)

    def test_replacing_emoji_table_keeps_no_partial_source(self):
        fragment = "| a | b |\n| --- | --- |\n| 😀 | 😀😀 |"
        panel = self.editor_panel(fragment + "\n后记")
        replacement = fragment.replace("😀", "新")
        ok, reason = panel._replace_table_fragment(fragment, replacement)
        self.assertTrue(ok, reason)
        self.assertEqual(panel._editor.toPlainText(), replacement + "\n后记")

    def test_cancelled_grid_draft_reopens_and_applies(self):
        from PySide6.QtWidgets import QDialog, QTableWidgetItem
        from doc_tool.ui.content.table_grid_dialog import TableGridDialog
        fragment = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        panel = self.editor_panel(fragment)
        def cancel_after_edit(dialog):
            dialog.table.setItem(1, 0, QTableWidgetItem("待应用"))
            return QDialog.DialogCode.Rejected
        with patch.object(TableGridDialog, "exec", cancel_after_edit):
            self.assertFalse(panel.open_table_grid())
        self.assertEqual(panel._editor.toPlainText(), fragment)
        with patch.object(TableGridDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.assertTrue(panel.open_table_grid())
        self.assertIn("待应用", panel._editor.toPlainText())
        panel._editor.undo()
        self.assertEqual(panel._editor.toPlainText(), fragment)

    def test_normal_close_button_saves_edits(self):
        dialog = self.pack_dialog()
        dialog.description_edit.setPlainText("关闭之前的改动")
        dialog.accept()
        loaded = authoring.PackDraft.load(self.work / "draft")
        self.assertEqual(loaded.description, "关闭之前的改动")

    def test_invalid_input_is_restored_after_save_and_reopen(self):
        dialog = self.pack_dialog()
        dialog.rules_edit.setPlainText("{未完成的规则")
        dialog._on_save_draft()
        loaded_dialog = self.pack_dialog()
        self.assertEqual(loaded_dialog.rules_edit.toPlainText(), "{未完成的规则")

    def test_export_uses_current_form_after_previous_freeze(self):
        import zipfile
        import yaml
        dialog = self.pack_dialog()
        dialog._add_variable_row("product", "first")
        dialog._on_freeze()
        dialog.description_edit.setPlainText("当前表单")
        output = self.work / "output"
        output.mkdir()
        with patch("doc_tool.ui.standard_pack_dialog.QFileDialog.getExistingDirectory", return_value=str(output)):
            dialog._on_export_zip()
        archives = list(output.glob("*.zip"))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            payload = yaml.safe_load(archive.read("pack.yml"))
        self.assertEqual(payload["description"], "当前表单")

    def test_sample_work_does_not_block_gui_and_busy_form_is_stable(self):
        dialog = self.pack_dialog()
        started = threading.Event()
        release = threading.Event()
        threads = []
        main_thread = threading.get_ident()
        def slow_sample(draft, **kwargs):
            threads.append(threading.get_ident())
            started.set()
            release.wait(0.35)
            return {"message": "complete"}
        try:
            with patch("doc_tool.ui.standard_pack_dialog.authoring.run_sample", slow_sample):
                start = time.monotonic()
                dialog.sample_btn.click()
                elapsed = time.monotonic() - start
                self.assertTrue(started.wait(1))
                self.assertLess(elapsed, 0.15, "耗时后端必须移出 GUI 线程")
                self.assertNotEqual(threads[0], main_thread)
                self.assertFalse(dialog.sample_btn.isEnabled())
                self.assertFalse(dialog.pack_id_edit.isEnabled())
                release.set()
                deadline = time.monotonic() + 3
                while not dialog.sample_btn.isEnabled() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.assertTrue(dialog.sample_btn.isEnabled())
                self.assertTrue(dialog.pack_id_edit.isEnabled())
        finally:
            release.set()

    def test_toolbar_really_fits_and_labels_do_not_overlap_after_resize(self):
        from PySide6.QtCore import QPoint
        from doc_tool.ui.styles import apply_theme
        apply_theme(self.app, dark=False)
        panel = self.editor_panel("# 文档\n\n正文")
        for width in (1600, 1024, 1280, 1024):
            panel.resize(width, 640)
            panel.show()
            for _ in range(4):
                self.app.processEvents()
            self.assertEqual(panel.width(), width)
            self.assertLess(panel._md_toolbar.geometry().right(), panel._file_label.geometry().left())
            for button in (panel._heading_btn, panel._overflow_btn, panel._preview_btn, panel._save_btn):
                if button.isVisible():
                    point = button.mapTo(panel, QPoint(0, 0))
                    self.assertGreaterEqual(point.x(), 0)
                    self.assertLessEqual(point.x() + button.width(), width)
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())
            for name, button in panel._md_actions:
                self.assertTrue(button.isVisible() or any(n == name for n, _a, _b in panel.overflow_items()), name)

    def test_pack_small_window_keeps_readable_editors_and_dark_scroll_background(self):
        from doc_tool.ui.styles import apply_theme
        apply_theme(self.app, dark=True)
        dialog = self.pack_dialog()
        dialog.resize(1024, 640)
        dialog.show()
        dialog.tabs.setCurrentIndex(1)
        for _ in range(4):
            self.app.processEvents()
        scroll = dialog.tabs.widget(1)
        self.assertGreater(dialog.terms_edit.height(), 80)
        self.assertGreater(dialog.rules_edit.height(), 80)
        scroll.ensureWidgetVisible(dialog.rules_edit)
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        color = scroll.widget().grab().toImage().pixelColor(1, 1)
        self.assertLess(max(color.red(), color.green(), color.blue()), 100)
        apply_theme(self.app, dark=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
