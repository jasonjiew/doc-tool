# -*- coding: utf-8 -*-
"""文档互转模块优化专项测试：格式智能推荐、行级定制、错误指引、重试与交互体验。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from doc_tool.application.convert import (
    DIRECTIONS,
    KIND_DOCX_TO_MARKDOWN,
    KIND_DOCX_TO_PDF,
    KIND_XLSX_TO_CSV,
    TARGET_CSV,
    TARGET_DOCX,
    TARGET_HTML,
    TARGET_MARKDOWN,
    TARGET_PDF,
    available_targets_for,
    build_plan,
    convert_paths,
    default_target_for,
    error_resolution_guide,
    format_file_size,
    validate_source_signature,
)
from doc_tool.domain.errors import UnsupportedConversionError
from doc_tool.ui.convert_dialog import ConvertDialog, _DropZone, _RowActionWidget


def _ensure_qapp():
    if QApplication.instance() is None:
        QApplication([])


class ConvertApplicationHelpersTests(unittest.TestCase):
    """测试 convert.py 新增的应用层工具函数。"""

    def test_available_targets_for_various_extensions(self):
        # docx: pdf, md, html
        docx_targets = [t[0] for t in available_targets_for("sample.docx")]
        self.assertIn(TARGET_PDF, docx_targets)
        self.assertIn(TARGET_MARKDOWN, docx_targets)
        self.assertIn(TARGET_HTML, docx_targets)

        # old .doc: only pdf
        doc_targets = [t[0] for t in available_targets_for("sample.doc")]
        self.assertEqual(doc_targets, [TARGET_PDF])

        # pdf: docx
        pdf_targets = [t[0] for t in available_targets_for("sample.pdf")]
        self.assertIn(TARGET_DOCX, pdf_targets)

        # xlsx: csv, html, pdf
        xlsx_targets = [t[0] for t in available_targets_for("sample.xlsx")]
        self.assertIn(TARGET_CSV, xlsx_targets)
        self.assertIn(TARGET_HTML, xlsx_targets)
        self.assertIn(TARGET_PDF, xlsx_targets)

        # csv: xlsx, pdf
        csv_targets = [t[0] for t in available_targets_for("sample.csv")]
        self.assertIn("xlsx", csv_targets)
        self.assertIn(TARGET_PDF, csv_targets)

        # unknown extension
        self.assertEqual(available_targets_for("sample.unknown"), [])

    def test_default_target_for(self):
        self.assertEqual(default_target_for("a.docx"), TARGET_PDF)
        self.assertEqual(default_target_for("a.doc"), TARGET_PDF)
        self.assertEqual(default_target_for("a.pdf"), TARGET_DOCX)
        self.assertEqual(default_target_for("a.md"), TARGET_DOCX)
        self.assertEqual(default_target_for("a.xlsx"), TARGET_CSV)
        self.assertEqual(default_target_for("a.csv"), "xlsx")
        self.assertEqual(default_target_for("a.txt"), TARGET_PDF)
        self.assertEqual(default_target_for("a.rtf"), TARGET_PDF)
        self.assertEqual(default_target_for("a.odt"), TARGET_PDF)

    def test_format_file_size(self):
        self.assertEqual(format_file_size(0), "0 B")
        self.assertEqual(format_file_size(512), "512 B")
        self.assertEqual(format_file_size(1024), "1.0 KB")
        self.assertEqual(format_file_size(1536), "1.5 KB")
        self.assertEqual(format_file_size(1024 * 1024), "1.0 MB")
        self.assertEqual(format_file_size(1024 * 1024 * 1024 * 2), "2.00 GB")

    def test_error_resolution_guide(self):
        for code in ("E6001", "E6002", "E6003", "E6004", "E6005", "E6006", "E6007", "E6008"):
            desc, guide = error_resolution_guide(code)
            self.assertTrue(desc, f"desc for {code} should not be empty")
            self.assertTrue(guide, f"guide for {code} should not be empty")
            self.assertIsInstance(desc, str)
            self.assertIsInstance(guide, str)

        # Specific keyword checks
        _, g_word = error_resolution_guide("E6001")
        self.assertIn("Word", g_word)

        _, g_target = error_resolution_guide("E6002")
        self.assertIn("覆盖", g_target)

        _, g_enc = error_resolution_guide("E6007")
        self.assertIn("UTF-8", g_enc)

        # Fallback
        desc_fallback, guide_fallback = error_resolution_guide("E9999", "未知错误详情")
        self.assertEqual(desc_fallback, "未知错误详情")
        self.assertIn("检查源文件", guide_fallback)

    def test_convert_paths_with_dict_target_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f_xlsx = root / "table.xlsx"
            f_csv = root / "data.csv"

            import openpyxl
            wb = openpyxl.Workbook()
            wb.active.append(["A", "B"])
            wb.active.append(["1", "2"])
            wb.save(str(f_xlsx))

            f_csv.write_text("H1,H2\nV1,V2\n", encoding="utf-8")

            # Batch convert with per-file target format dict
            targets = {f_xlsx: "csv", f_csv: "xlsx"}
            res = convert_paths([f_xlsx, f_csv], target_format=targets)
            self.assertTrue(res.success, res.summary())
            self.assertEqual(len(res.records), 2)
            self.assertTrue((root / "table.csv").is_file())
            self.assertTrue((root / "data.xlsx").is_file())



    def test_validate_source_signature_detects_empty_and_disguised_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # 0 字节空文件
            empty_docx = root / "empty.docx"
            empty_docx.write_bytes(b"")
            valid, msg = validate_source_signature(empty_docx)
            self.assertFalse(valid)
            self.assertIn("0 字节", msg)

            # 伪装的 Windows PE 可执行文件
            fake_exe = root / "invoice.docx"
            fake_exe.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)
            valid, msg = validate_source_signature(fake_exe)
            self.assertFalse(valid)
            self.assertIn("MZ", msg)

            # 伪装的 PNG 图片
            fake_img = root / "contract.pdf"
            fake_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            valid, msg = validate_source_signature(fake_img)
            self.assertFalse(valid)
            self.assertIn("图片", msg)

            # 大于 64 字节却无 PK 头的 DOCX
            fake_docx = root / "corrupted.docx"
            fake_docx.write_bytes(b"A" * 128)
            valid, msg = validate_source_signature(fake_docx)
            self.assertFalse(valid)
            self.assertIn("PK", msg)

            # 大于 64 字节却无 %PDF- 头的 PDF
            fake_pdf = root / "corrupted.pdf"
            fake_pdf.write_bytes(b"B" * 128)
            valid, msg = validate_source_signature(fake_pdf)
            self.assertFalse(valid)
            self.assertIn("%PDF-", msg)

            # 合法的 DOCX (带 PK 头)
            ok_docx = root / "ok.docx"
            ok_docx.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
            valid, _ = validate_source_signature(ok_docx)
            self.assertTrue(valid)

            # 合法的 PDF (带 %PDF- 头)
            ok_pdf = root / "ok.pdf"
            ok_pdf.write_bytes(b"%PDF-1.4\n" + b"\x00" * 100)
            valid, _ = validate_source_signature(ok_pdf)
            self.assertTrue(valid)

    def test_build_plan_validates_signature_and_output_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty_file = root / "test.docx"
            empty_file.write_bytes(b"")
            with self.assertRaises(UnsupportedConversionError):
                build_plan(empty_file, validate_signature=True)

            # output_dir 是已有文件
            ok_file = root / "valid.docx"
            ok_file.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
            target_as_file = root / "existing_file.txt"
            target_as_file.write_text("not a dir", encoding="utf-8")
            with self.assertRaises(UnsupportedConversionError):
                build_plan(ok_file, output_dir=target_as_file)

    def test_error_resolution_guide_exact_mappings(self):
        desc, _ = error_resolution_guide("E6001")
        self.assertEqual(desc, "格式或方向不支持")

        desc, _ = error_resolution_guide("E6002")
        self.assertEqual(desc, "目标文件已存在")

        desc, _ = error_resolution_guide("E6003")
        self.assertEqual(desc, "Word 转换失败")

        desc, _ = error_resolution_guide("E6004")
        self.assertEqual(desc, "转换超时")

        desc, _ = error_resolution_guide("E6005")
        self.assertEqual(desc, "产物文件未找到")

        desc, _ = error_resolution_guide("E3001")
        self.assertEqual(desc, "未检测到 Microsoft Word")

        desc, _ = error_resolution_guide(None, "WinError 0x800706be rpc failed")
        self.assertEqual(desc, "Word COM 服务崩溃")


class ConvertDialogUXTests(unittest.TestCase):
    """测试 ConvertDialog 界面、行级交互、空态/紧凑态、操作按钮及重试。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "doc1.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 30)
        (self.root / "sheet.xlsx").write_bytes(b"PK\x03\x04" + b"\x00" * 30)
        (self.root / "readme.md").write_text("# 标题\n\n正文", encoding="utf-8")

    def tearDown(self):
        for dlg in getattr(self, "_dialogs", []):
            try:
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass
        self._dialogs = []
        app = QApplication.instance()
        if app:
            app.processEvents()
        self._tmp.cleanup()

    def _dialog(self):
        dlg = ConvertDialog()
        if not hasattr(self, "_dialogs"):
            self._dialogs = []
        self._dialogs.append(dlg)
        dlg.show()
        return dlg

    def test_drop_zone_empty_and_compact_transition(self):
        dlg = self._dialog()
        # 初始空列表：大欢迎卡片模式，安全徽标未隐藏
        self.assertFalse(dlg._drop_zone._security_badge.isHidden())
        self.assertEqual(dlg._table.rowCount(), 0)

        # 添加文件后：切换为紧凑条形模式
        dlg._append([str(self.root / "doc1.docx")])
        self.assertTrue(dlg._drop_zone._security_badge.isHidden())
        self.assertIn("追加", dlg._drop_zone._title.text())
        self.assertEqual(dlg._table.rowCount(), 1)

        # 清空后：恢复大欢迎卡片模式
        dlg._on_clear()
        self.assertFalse(dlg._drop_zone._security_badge.isHidden())
        self.assertIn("点击选择", dlg._drop_zone._title.text())
        dlg.close()

    def test_per_row_combo_creation_and_customization(self):
        dlg = self._dialog()
        dlg._append([str(self.root / "doc1.docx"), str(self.root / "sheet.xlsx")])
        self.assertEqual(dlg._table.rowCount(), 2)

        # 检查行级下拉框存在
        combo0 = dlg._row_combos.get(str(self.root / "doc1.docx"))
        combo1 = dlg._row_combos.get(str(self.root / "sheet.xlsx"))
        self.assertIsNotNone(combo0)
        self.assertIsNotNone(combo1)

        # 检查 docx 行的可用目标选项
        docx_data = [combo0.itemData(i) for i in range(combo0.count())]
        self.assertIn(TARGET_PDF, docx_data)
        self.assertIn(TARGET_MARKDOWN, docx_data)
        self.assertIn(TARGET_HTML, docx_data)

        # 检查 xlsx 行的可用目标选项
        xlsx_data = [combo1.itemData(i) for i in range(combo1.count())]
        self.assertIn(TARGET_CSV, xlsx_data)
        self.assertIn(TARGET_PDF, xlsx_data)
        self.assertNotIn(TARGET_DOCX, xlsx_data)

        # 改变第 0 行的目标格式为 Markdown
        md_idx = combo0.findData(TARGET_MARKDOWN)
        self.assertGreaterEqual(md_idx, 0)
        combo0.setCurrentIndex(md_idx)

        # 验证表格文本和方向同步更新
        self.assertEqual(dlg._table.item(0, 1).text(), "Word → Markdown")

        # 改变第 1 行的目标格式为 CSV
        csv_idx = combo1.findData(TARGET_CSV)
        self.assertGreaterEqual(csv_idx, 0)
        combo1.setCurrentIndex(csv_idx)
        self.assertEqual(dlg._table.item(1, 1).text(), "Excel → CSV")
        dlg.close()

    def test_row_action_widget_lifecycle(self):
        widget = _RowActionWidget(self.root / "doc1.docx")
        widget.show()
        self.assertFalse(widget._remove_btn.isHidden())
        self.assertTrue(widget._open_btn.isHidden())
        self.assertTrue(widget._folder_btn.isHidden())
        self.assertTrue(widget._retry_btn.isHidden())

        # 转换成功状态
        out_file = self.root / "doc1.pdf"
        widget.set_status_succeeded(out_file)
        self.assertTrue(widget._remove_btn.isHidden())
        self.assertFalse(widget._open_btn.isHidden())
        self.assertFalse(widget._folder_btn.isHidden())
        self.assertTrue(widget._retry_btn.isHidden())

        # 转换失败状态
        widget.set_status_failed()
        self.assertFalse(widget._remove_btn.isHidden())
        self.assertTrue(widget._open_btn.isHidden())
        self.assertTrue(widget._folder_btn.isHidden())
        self.assertFalse(widget._retry_btn.isHidden())

        # 运行中禁用
        widget.set_running(True)
        self.assertFalse(widget.isEnabled())
        widget.set_running(False)
        self.assertTrue(widget.isEnabled())
        widget.close()

    def test_single_row_remove_button(self):
        dlg = self._dialog()
        dlg._append([str(self.root / "doc1.docx"), str(self.root / "sheet.xlsx")])
        self.assertEqual(dlg._table.rowCount(), 2)

        # 点击第 0 行的移除按钮
        dlg._on_remove_single_row(self.root / "doc1.docx")
        self.assertEqual(dlg._table.rowCount(), 1)
        self.assertEqual(dlg._sources, [self.root / "sheet.xlsx"])
        dlg.close()

    def test_retry_failed_mechanism(self):
        class _FakeRecord:
            def __init__(self, source, ok, err=""):
                self.source = Path(source)
                self.target = Path("out.pdf")
                self.ok = ok
                self.error_code = err
                self.detail = "失败详情"
                self.note = ""
                self.status = "ok" if ok else "failed"
                self.elapsed_seconds = 1.0

        class _FakeResult:
            def __init__(self, records):
                self.records = records
                self.success = all(r.ok for r in records)
                self.failed = sum(1 for r in records if not r.ok)

            def summary(self):
                return f"完成：成功 {len(self.records)-self.failed}，失败 {self.failed}"

        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        f2 = self.root / "sheet.xlsx"
        dlg._append([str(f1), str(f2)])

        # 初始时重试失败按钮隐藏
        self.assertTrue(dlg._retry_failed_button.isHidden())

        # 模拟运行完成：1 成功，1 失败
        r1 = _FakeRecord(f1, True)
        r2 = _FakeRecord(f2, False, "E6006")
        dlg._on_done(_FakeResult([r1, r2]))

        # 重试按钮应变为可见并包含计数
        self.assertFalse(dlg._retry_failed_button.isHidden())
        self.assertIn("1", dlg._retry_failed_button.text())

        # 单独重试 f2：必须保持完整 _sources 列表不被截断，且传递 targets_to_run 参数
        with patch.object(dlg, "_on_run") as mock_run:
            dlg._on_retry_single(f2)
            self.assertEqual(dlg._sources, [f1, f2], "单独重试必须保留完整源列表，不得撕裂表格行索引")
            mock_run.assert_called_once_with(targets_to_run=[f2])

        # 批量重试失败项：同样保留全部源文件，仅针对失败项派发重跑
        with patch.object(dlg, "_on_run") as mock_run:
            dlg._on_retry_failed()
            self.assertEqual(dlg._sources, [f1, f2], "重试失败项必须保留完整源列表，不得撕裂表格行索引")
            mock_run.assert_called_once_with(targets_to_run=[f2])
        dlg.close()

    def test_anti_double_click_debounce(self):
        dlg = self._dialog()
        dlg._append([str(self.root / "doc1.docx")])
        dlg._last_run_time = time.monotonic()  # 刚触发过

        with patch.object(dlg._runner, "start") as mock_start:
            dlg._on_run()
            mock_start.assert_not_called()
        dlg.close()

    def test_error_diagnosis_logged_on_failure(self):
        class _FakeRecord:
            source = Path("fail.txt")
            target = Path("")
            ok = False
            error_code = "E6007"
            detail = "编码无法识别"
            note = ""
            status = "failed"
            reason = "encoding_failed"
            elapsed_seconds = 0.2

        dlg = self._dialog()
        dlg._append([str(self.root / "doc1.docx")])
        dlg._log_record(_FakeRecord())
        log_text = dlg._details.toPlainText()
        self.assertIn("E6007", log_text)
        self.assertIn("解决指引", log_text)
        self.assertIn("UTF-8", log_text)
        dlg.close()

    def test_key_press_esc_cancels_when_running(self):
        dlg = self._dialog()
        with patch.object(type(dlg._runner), "is_running", new_callable=PropertyMock) as mock_running:
            mock_running.return_value = True
            with patch.object(dlg, "_on_cancel") as mock_cancel:
                event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
                dlg.keyPressEvent(event)
                mock_cancel.assert_called_once()
        dlg.close()


    def test_retry_single_preserves_other_rows_status(self):
        """验证重试单个文件时，其他已成功的行不会被错误标记为排队中。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        f2 = self.root / "sheet.xlsx"
        dlg._append([str(f1), str(f2)])

        # 模拟 f1 成功
        dlg._on_progress(1, 2, SimpleNamespace(
            source=f1, target=Path("doc1.pdf"), ok=True,
            status="成功", elapsed_seconds=0.5, detail="", error_code=None, note=""
        ))
        self.assertIn("成功", dlg._table.item(0, 3).text())

        # 对 f2 发起重跑，f1 的状态必须保持为成功
        with patch.object(dlg._runner, "start") as mock_start:
            mock_start.return_value = True
            dlg._on_retry_single(f2)
            self.assertIn("成功", dlg._table.item(0, 3).text(), "重跑 f2 时已完成的 f1 状态绝不能变回排队中")
            self.assertIn("排队中", dlg._table.item(1, 3).text())
        dlg.close()

    def test_running_state_freezes_controls_and_prevents_removal(self):
        """验证运行中冻结配置控件，且禁止通过快捷键或移除按钮撕裂运行队列。"""
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])
        dlg._set_controls_enabled(False)
        self.assertFalse(dlg._add_files_btn.isEnabled())
        self.assertFalse(dlg._remove_btn.isEnabled())
        self.assertFalse(dlg._clear_btn.isEnabled())
        self.assertFalse(dlg._format_combo.isEnabled())

        # 运行中调用移除操作应直接被守卫拦截
        with patch.object(type(dlg._runner), "is_running", new_callable=PropertyMock) as mock_running:
            mock_running.return_value = True
            dlg._table.selectAll()
            dlg._on_remove_selected()
            self.assertEqual(dlg._table.rowCount(), 1, "运行中禁止移除行造成索引错乱")
            self.assertEqual(dlg._sources, [f1])
        dlg.close()

    def test_drag_move_event_accepted_for_windows_compatibility(self):
        """验证 dragMoveEvent 被正确处理与接受，避免 Windows 资源管理器悬停时判定为禁止拖入。"""
        from PySide6.QtCore import QMimeData, QPoint, QUrl
        from PySide6.QtGui import QDragMoveEvent

        dlg = self._dialog()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.root / "doc1.docx"))])
        move_ev = QDragMoveEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dlg.dragMoveEvent(move_ev)
        self.assertTrue(move_ev.isAccepted(), "Windows OLE 悬停时必须接受 dragMoveEvent")
        dlg.close()

    def test_row_target_change_resets_status_and_predicted_target(self):
        """验证在某行修改目标格式后，自动刷新预估产物路径，并将行状态重置为待转换。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])

        # 先模拟一次成功
        dlg._on_progress(1, 1, SimpleNamespace(
            source=f1, target=Path("doc1.pdf"), ok=True,
            status="成功", elapsed_seconds=0.3, detail="", error_code=None, note=""
        ))
        self.assertIn("成功", dlg._table.item(0, 3).text())

        # 用户在行级修改目标为 Markdown
        combo = dlg._row_combos[str(f1)]
        idx = combo.findData("md")
        combo.setCurrentIndex(idx)

        # 状态应重置为「待转换」，且预估产物更新为 .md
        self.assertEqual(dlg._table.item(0, 3).text(), "待转换")
        self.assertIn(".md", dlg._table.item(0, 2).text())
        self.assertEqual(dlg._run_button.text(), "开始转换")
        dlg.close()

    def test_cancel_task_marks_remaining_rows_cancelled(self):
        """验证任务取消后，排队中但未跑完的条目会被准确标记为「已取消」而非卡在「排队中」。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        f2 = self.root / "sheet.xlsx"
        dlg._append([str(f1), str(f2)])
        dlg._current_run_sources = [f1, f2]
        dlg._set_item(0, 3, "排队中")
        dlg._set_item(1, 3, "排队中")

        # 模拟仅 f1 跑完（触发 progress 回调）即发生取消
        r1 = SimpleNamespace(
            source=f1, target=Path("doc1.pdf"), ok=True,
            status="成功", elapsed_seconds=0.4, detail="", error_code=None, note=""
        )
        dlg._on_progress(1, 2, r1)
        fake_result = SimpleNamespace(
            success=False, failed=0, cancelled=True, records=[r1],
            summary=lambda: "已取消转换"
        )
        dlg._on_done(fake_result)

        self.assertIn("成功", dlg._table.item(0, 3).text())
        self.assertEqual(dlg._table.item(1, 3).text(), "已取消", "被取消的条目必须明确标记为已取消")
        self.assertIn("已取消", dlg._status.text())
        dlg.close()

    def test_semantic_colors_applied_to_status_items(self):
        """验证状态列文本根据状态正确配置 SEMANTIC_COLORS 语义前景色。"""
        from doc_tool.ui.styles import SEMANTIC_COLORS
        from PySide6.QtGui import QColor
        dlg = self._dialog()
        dlg._append([str(self.root / "doc1.docx")])
        dlg._set_item(0, 3, "成功", tone="success")
        item = dlg._table.item(0, 3)
        self.assertEqual(item.foreground().color().name(), QColor(SEMANTIC_COLORS["success"]).name())
        dlg.close()



    def test_rebuild_rows_cleans_last_records_and_updates_retry_button(self):
        """验证删除行后，已删除条目从 _last_records 清理，重试按钮随之隐藏。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        f2 = self.root / "sheet.xlsx"
        dlg._append([str(f1), str(f2)])

        # 模拟 f1 成功，f2 失败
        r1 = SimpleNamespace(source=f1, target=Path("doc1.pdf"), ok=True, error_code=None)
        r2 = SimpleNamespace(source=f2, target=Path("sheet.csv"), ok=False, error_code="E6006")
        dlg._last_records = [r1, r2]
        dlg._retry_failed_button.setText("重试失败项 (1)")
        dlg._retry_failed_button.setVisible(True)

        # 用户移除失败的 f2 行
        dlg._on_remove_single_row(f2)
        self.assertEqual(len(dlg._last_records), 1)
        self.assertEqual(dlg._last_records[0].source, f1)
        self.assertTrue(dlg._retry_failed_button.isHidden(), "移除失败条目后重试失败项按钮必须隐藏")
        dlg.close()

    def test_row_target_change_updates_retry_button_count(self):
        """验证单行修改目标格式后，重试按钮计数同步刷新。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])

        r1 = SimpleNamespace(source=f1, target=Path("doc1.pdf"), ok=False, error_code="E6003")
        dlg._last_records = [r1]
        dlg._retry_failed_button.setText("重试失败项 (1)")
        dlg._retry_failed_button.setVisible(True)

        # 修改 f1 的目标格式
        combo = dlg._row_combos[str(f1)]
        combo.setCurrentIndex(combo.findData("md"))
        self.assertTrue(dlg._retry_failed_button.isHidden(), "格式重设为待转换后无失败条目，重试按钮应隐藏")
        dlg.close()

    def test_on_done_recovers_when_result_is_none(self):
        """验证当后台任务发生意外崩溃/看门狗超时（result is None）时，UI 优雅恢复并标红失败。"""
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])
        dlg._current_run_sources = [f1]
        dlg._set_item(0, 3, "排队中")

        dlg._on_done(None)
        self.assertIn("异常终止", dlg._status.text())
        self.assertIn("异常终止", dlg._table.item(0, 3).text())
        self.assertFalse(dlg._retry_failed_button.isHidden(), "崩溃后必须允许用户重试")
        self.assertTrue(dlg._run_button.isEnabled())
        dlg.close()

    def test_output_dir_changed_updates_predicted_tooltip(self):
        """验证修改输出路径文本框时，待转换行的预估输出路径动态联动。"""
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])

        dlg._output_edit.setText("D:\\my_custom_output_folder")
        tip = dlg._table.item(0, 2).toolTip()
        self.assertIn("my_custom_output_folder", tip)
        dlg.close()

    def test_key_press_delete_removes_selected_rows(self):
        """验证按 Delete 键可快捷删除选中的行。"""
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        f2 = self.root / "sheet.xlsx"
        dlg._append([str(f1), str(f2)])
        dlg._table.selectRow(0)

        del_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(del_event)
        self.assertEqual(dlg._table.rowCount(), 1)
        self.assertEqual(dlg._sources, [f2])
        dlg.close()

    def test_batch_summary_merges_counts_across_retry_rounds(self):
        """验证跨重试轮次后，状态栏摘要统计呈现完整批次的真实成功/失败总数。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        f2 = self.root / "sheet.xlsx"
        dlg._append([str(f1), str(f2)])

        # 第 1 轮：f1 成功，f2 失败
        r1 = SimpleNamespace(source=f1, target=Path("doc1.pdf"), ok=True, error_code=None, status="成功", elapsed_seconds=0.2, detail="", note="")
        r2_fail = SimpleNamespace(source=f2, target=Path("sheet.csv"), ok=False, error_code="E6006", status="失败", elapsed_seconds=0.2, detail="表格错误", note="", failed=True)
        dlg._last_records = [r1, r2_fail]

        # 第 2 轮重试 f2 成功
        r2_ok = SimpleNamespace(source=f2, target=Path("sheet.csv"), ok=True, error_code=None, status="成功", elapsed_seconds=0.3, detail="", note="")
        res_retry = SimpleNamespace(records=[r2_ok], cancelled=False, success=True, failed=0, summary=lambda: "成功 1 个，失败 0 个。")
        dlg._on_done(res_retry)

        self.assertIn("成功 2 个，失败 0 个", dlg._status.text(), "全量汇总必须合并历史轮次（2个成功），绝不能退化为仅重跑子集的数字")
        dlg.close()


    def test_validate_source_signature_catches_small_fake_files(self):
        """验证小于 64 字节的伪装小文件或含 NUL 字符的损坏文本文件会被准确拦截。"""
        from doc_tool.application.convert import validate_source_signature

        # 1. 只有 11 字节但缺少 PK 头的假 docx
        fake_docx = self.root / "small_fake.docx"
        fake_docx.write_bytes(b"hello world")
        valid, msg = validate_source_signature(fake_docx)
        self.assertFalse(valid)
        self.assertIn("ZIP", msg)

        # 2. 只有 15 字节且缺少 %PDF- 头的假 pdf
        fake_pdf = self.root / "small_fake.pdf"
        fake_pdf.write_bytes(b"not a valid pdf")
        valid, msg = validate_source_signature(fake_pdf)
        self.assertFalse(valid)
        self.assertIn("%PDF-", msg)

        # 3. 含有二进制 NUL 空字符的伪装/损坏 txt
        corrupt_txt = self.root / "corrupt.txt"
        corrupt_txt.write_bytes(b"hello\x00world binary content")
        valid, msg = validate_source_signature(corrupt_txt)
        self.assertFalse(valid)
        self.assertIn("NUL", msg)

        # 4. 正常 UTF-8 文本
        normal_txt = self.root / "normal.txt"
        normal_txt.write_text("合法的纯文本内容", encoding="utf-8")
        valid, msg = validate_source_signature(normal_txt)
        self.assertTrue(valid)

    def test_global_format_change_resets_completed_rows_and_predicted_targets(self):
        """验证全局切换目标格式时，已完成行的状态和预估产物自动重置为新格式的「待转换」。"""
        from types import SimpleNamespace
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])

        # 模拟转换完成为 PDF
        rec = SimpleNamespace(
            source=f1,
            target=self.root / "doc1.pdf",
            ok=True,
            error_code=None,
            status="成功",
            elapsed_seconds=0.3,
            detail="",
            note="",
        )
        dlg._on_progress(1, 1, rec)
        dlg._on_done(SimpleNamespace(records=[rec], cancelled=False, success=True, failed=0, summary=lambda: "成功 1 个"))

        self.assertIn("成功", dlg._table.item(0, 3).text())
        self.assertEqual(dlg._run_button.text(), "重新转换全部")

        # 切换全局格式为 Markdown
        idx_md = dlg._format_combo.findData("md")
        self.assertGreaterEqual(idx_md, 0)
        dlg._format_combo.setCurrentIndex(idx_md)

        # 校验：行下拉框切为 md，预估产物为 doc1.md，状态重置为待转换，按钮重置为开始转换
        combo = dlg._row_combos[str(f1)]
        self.assertEqual(combo.currentData(), "md")
        self.assertIn("doc1.md", dlg._table.item(0, 2).text())
        self.assertEqual(dlg._table.item(0, 3).text(), "待转换")
        self.assertEqual(dlg._run_button.text(), "开始转换")
        dlg.close()

    def test_global_format_change_unsupported_row_keeps_format_and_sets_tooltip(self):
        """验证当某源不支持全局目标格式时（如 .doc 不支持 md），保留原有效方向并不遮挡控件。"""
        dlg = self._dialog()
        # 伪造一个合法的 OLE2 复合头 .doc 文件
        doc_file = self.root / "old.doc"
        doc_file.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 600)
        dlg._append([str(doc_file)])

        # 切换全局为 md
        idx_md = dlg._format_combo.findData("md")
        self.assertGreaterEqual(idx_md, 0)
        dlg._format_combo.setCurrentIndex(idx_md)

        combo = dlg._row_combos[str(doc_file)]
        self.assertEqual(combo.currentData(), "pdf")
        self.assertIn("不支持转为", combo.toolTip())
        dlg.close()

    def test_on_clear_disables_open_output_button(self):
        """验证清空列表后，打开输出文件夹按钮同步禁用。"""
        dlg = self._dialog()
        f1 = self.root / "doc1.docx"
        dlg._append([str(f1)])
        dlg._open_output_button.setEnabled(True)

        dlg._on_clear()
        self.assertFalse(dlg._open_output_button.isEnabled())
        dlg.close()

    def test_row_action_open_file_and_folder_when_missing_shows_warning(self):
        """验证当产物被外部删除或未生成时，点击打开产物或文件夹弹出警告而非静默无响应。"""
        from unittest.mock import patch
        from doc_tool.ui.convert_dialog import _RowActionWidget

        widget = _RowActionWidget(self.root / "dummy.docx")
        widget.set_target(self.root / "non_existent_file.pdf")

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            widget._on_open_file()
            self.assertTrue(mock_warn.called)
            self.assertIn("无法打开产物", mock_warn.call_args[0][1])

        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            widget.set_target(Path("Z:/non_existent_drive/invalid.pdf"))
            widget._on_open_folder()
            self.assertTrue(mock_warn.called)
            self.assertIn("无法打开文件夹", mock_warn.call_args[0][1])

    def test_error_resolution_guide_long_path_winerror_206(self):
        """验证 Windows 超长路径（WinError 206）异常能被智能诊断。"""
        from doc_tool.application.convert import error_resolution_guide
        title, guide = error_resolution_guide(None, "OSError: [WinError 206] The filename or extension is too long")
        self.assertEqual(title, "路径或文件名超长")
        self.assertIn("260", guide)

    def test_main_window_convert_and_pdf_toolbox_accepts_path_and_tuple(self):
        """测试 MainWindow._on_convert_documents 与 _on_pdf_toolbox 对单个 Path 及 tuple 格式的健壮接收。"""
        from unittest.mock import patch
        from doc_tool.ui.main_window import MainWindow

        captured_convert = []
        captured_pdf = []

        class _MockConvertDialog:
            def __init__(self, parent=None, busy_check=None):
                pass
            def _ingest_paths(self, paths):
                captured_convert.extend(paths)
            def exec(self):
                pass
            def deleteLater(self):
                pass

        class _MockPdfDialog:
            def __init__(self, parent=None, busy_check=None):
                pass
            def _ingest_paths(self, paths):
                captured_pdf.extend(paths)
            def select_tool(self, tool_id):
                pass
            def exec(self):
                pass
            def deleteLater(self):
                pass

        win = MainWindow()
        self.addCleanup(win.close)

        f1 = self.root / "doc1.docx"
        f2 = self.root / "doc2.docx"

        with patch("doc_tool.ui.convert_dialog.ConvertDialog", _MockConvertDialog):
            # 单个 Path
            win._on_convert_documents(f1)
            self.assertEqual(captured_convert, [f1])
            captured_convert.clear()

            # tuple of Paths
            win._on_convert_documents((f1, f2))
            self.assertEqual(captured_convert, [f1, f2])

        with patch("doc_tool.ui.pdf_toolbox_dialog.PdfToolboxDialog", _MockPdfDialog):
            # 单个 Path
            win._on_pdf_toolbox(f1)
            self.assertEqual(captured_pdf, [f1])
            captured_pdf.clear()

            # tuple of Paths
            win._on_pdf_toolbox((f1, f2))
            self.assertEqual(captured_pdf, [f1, f2])

if __name__ == "__main__":
    unittest.main()
