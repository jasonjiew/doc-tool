# -*- coding: utf-8 -*-
"""UI2-E 成果与高级面板（5.1～5.4）：窄面板、历史身份与局部恢复。

覆盖验收 U2-7/U2-8 的可自动部分：

- 成果面板在 340px 下竖排且所有主动作可见可点（不靠 400+ minimumWidth）；
- 补原轮前核对 roundId/captureId：目录索引被新轮覆盖时不提交错轮；
- 辅助/批量面板在窄宽度下动作分行，且取消保留输入、有效成员可继续。
"""

from __future__ import annotations

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
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.application.content.unsaved import UnsavedChoice  # noqa: E402
from doc_tool.application.project_export import (  # noqa: E402
    ExportReport,
    read_export_index,
    write_export_index,
)
from doc_tool.ui.export_results_view import ExportResultsView  # noqa: E402
from doc_tool.ui.export_rounds import (  # noqa: E402
    ExportRoundView,
    RoundFormatView,
    load_round_from_index,
)
from doc_tool.ui.flow_row import FlowRow  # noqa: E402


def _round_view(round_id: str, capture_id: str, **over):
    data = dict(
        round_id=round_id,
        capture_id=capture_id,
        project_root="X:/proj",
        source_mode="current-buffer",
        scope_text="所选 2 章",
        destination="X:/proj/output",
        formats=[
            RoundFormatView(format="docx", status="pending-refresh", usable=True),
            RoundFormatView(format="html", status="ready", usable=True),
            RoundFormatView(format="pdf", status="pending-convert", message="no tool"),
        ],
    )
    data.update(over)
    return ExportRoundView(**data)


class NarrowPanelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_results_view_is_operable_at_340(self):
        view = ExportResultsView()
        view.render([_round_view("r-1", "c-1")])
        view.resize(340, 700)
        view.show()
        for _ in range(12):
            self._app.processEvents()
            time.sleep(0.01)
        self.assertEqual(view.width(), 340)
        self.assertLessEqual(view.minimumSizeHint().width(), 340)
        self.assertTrue(view._actions_row.is_stacked(), "340px 下动作必须竖排")
        for button in (
            view._retry_btn,
            view._regenerate_btn,
            view._settings_btn,
            view._destination_btn,
        ):
            self.assertTrue(button.isVisible(), button.text())
            self.assertGreaterEqual(
                button.width(), button.sizeHint().width(),
                "窄面板不得压缩动作文字：{0}".format(button.text()),
            )
            self.assertLessEqual(button.geometry().right(), view.width())
        view.close()

    def test_results_view_expands_at_420_and_700(self):
        view = ExportResultsView()
        view.render([_round_view("r-1", "c-1")])
        view.show()
        for width in (420, 700):
            view.resize(width, 700)
            for _ in range(8):
                self._app.processEvents()
                time.sleep(0.01)
            self.assertEqual(view.width(), width)
            self.assertFalse(
                view._actions_row.is_stacked(),
                "{0}px 下动作应自然横排".format(width),
            )
        view.close()

    def test_flow_row_flips_direction_without_rebuilding_children(self):
        row = FlowRow(stack_below=300)
        from PySide6.QtWidgets import QPushButton

        first = row.add(QPushButton("A", row))
        second = row.add(QPushButton("B", row))
        row.apply_width(200)
        self.assertTrue(row.is_stacked())
        self.assertIs(row._laid_out[0], first)
        self.assertIs(row._laid_out[1], second)
        row.apply_width(500)
        self.assertFalse(row.is_stacked())

    def test_pending_refresh_word_remains_openable_and_partial_failure_kept(self):
        source = Path(__file__).resolve()
        view = ExportResultsView()
        view.render([
            _round_view(
                "r-2",
                "c-2",
                formats=[
                    RoundFormatView(
                        format="docx", status="pending-refresh", path=str(source),
                        usable=True,
                    ),
                    RoundFormatView(format="pdf", status="failed", message="转换器缺失"),
                ],
            )
        ])
        current = view.current_round()
        docx = [item for item in current.formats if item.format == "docx"][0]
        pdf = [item for item in current.formats if item.format == "pdf"][0]
        self.assertTrue(docx.can_open, "待刷新 Word 仍必须可打开")
        self.assertFalse(pdf.usable)
        self.assertIn("失败", pdf.describe())
        self.assertTrue(current.has_retryable)
        view.close()


class RoundIdentityTests(unittest.TestCase):
    """5.2：旧轮报告必须双 ID 核对，索引被覆盖不得冒充旧轮。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("ui2-round-identity")
        self.output = self.work / "output"
        self.output.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_index_reload_matches_only_its_own_round(self):
        old_report = ExportReport(
            roundId="r-old-1", captureId="cap-old-1", projectRoot=str(self.work),
            destination=str(self.output),
        )
        write_export_index(old_report, self.output)
        loaded = read_export_index(self.output)
        self.assertEqual(loaded.roundId, "r-old-1")
        view = load_round_from_index(self.output)
        self.assertEqual(view.round_id, "r-old-1")
        self.assertEqual(view.capture_id, "cap-old-1")

    def test_identity_helper_rejects_other_round(self):
        from doc_tool.ui.main_window import MainWindow

        view = _round_view("r-old-1", "cap-old-1")
        same = ExportReport(roundId="r-old-1", captureId="cap-old-1")
        other_round = ExportReport(roundId="r-new-2", captureId="cap-old-1")
        other_capture = ExportReport(roundId="r-old-1", captureId="cap-other")
        self.assertTrue(MainWindow._round_identity_matches(view, same))
        self.assertFalse(
            MainWindow._round_identity_matches(view, other_round),
            "同目录索引被新轮覆盖时不得冒充旧轮",
        )
        self.assertFalse(
            MainWindow._round_identity_matches(view, other_capture),
            "捕获不匹配时不得补原轮",
        )
        # 历史引用只保存 roundId 时不因缺 captureId 误判失配
        partial = _round_view("r-old-1", "")
        self.assertTrue(MainWindow._round_identity_matches(partial, same))

    def test_index_overwritten_by_new_round_is_detected(self):
        old_report = ExportReport(
            roundId="r-old-1", captureId="cap-old-1", projectRoot=str(self.work),
            destination=str(self.output),
        )
        write_export_index(old_report, self.output)
        view = load_round_from_index(self.output)
        new_report = ExportReport(
            roundId="r-new-9", captureId="cap-new-9", projectRoot=str(self.work),
            destination=str(self.output),
        )
        write_export_index(new_report, self.output)
        reloaded = read_export_index(self.output)
        self.assertEqual(reloaded.roundId, "r-new-9")
        from doc_tool.ui.main_window import MainWindow

        self.assertFalse(
            MainWindow._round_identity_matches(view, reloaded),
            "被覆盖后的索引必须判为失配，UI 应转新轮设置",
        )


class AdvancedPanelContextTests(unittest.TestCase):
    """5.3/5.4：窄宽度下辅助与批量表单仍可操作，且取消保留输入。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("ui2-panels")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        cls.bad = cls.work / "bad-member"
        cls.bad.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_assist_panel_operable_at_340(self):
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        panel = AssistPanel(build_assistant(str(self.project)), project_root=self.project)
        panel.resize(340, 640)
        panel.show()
        for _ in range(10):
            self._app.processEvents()
            time.sleep(0.01)
        self.assertEqual(panel.width(), 340)
        self.assertLessEqual(panel.minimumSizeHint().width(), 340)
        for widget in (
            panel._search_button,
            panel._include_buffer,
            panel._add_scope_button,
            panel._cite_button,
        ):
            self.assertTrue(widget.isVisible())
        labels = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        self.assertEqual(labels, ["资料", "建议"])
        panel.close()

    def test_batch_form_partial_invalid_members_and_cancel_keeps_input(self):
        from doc_tool.ui.delivery_form_dialog import DeliveryFormDialog

        dialog = DeliveryFormDialog(
            initial_members=[str(self.project), str(self.bad)],
            default_dir=str(self.work),
        )
        dialog._name_entry.setText("UI2 批次")
        plan = dialog.validated_plan()
        self.assertTrue(plan.executable_entries(), "有效成员必须可执行")
        self.assertEqual(len(plan.invalid_entries()), 1, "失效成员只影响它自己")
        self.assertIn("project.yml", dialog._validation_label.text())
        # 移除失效成员后仍可提交，且输入保留
        for row in range(dialog._member_list.count()):
            item = dialog._member_list.item(row)
            if str(item.data(256)) == str(self.bad):
                dialog._member_list.setCurrentRow(row)
                break
        dialog._remove_selected()
        self.assertEqual(dialog._name_entry.text(), "UI2 批次", "修正时不得清空输入")
        self.assertTrue(dialog.validated_plan().executable_entries())
        dialog.reject()
        self.assertEqual(dialog._name_entry.text(), "UI2 批次", "取消后保留输入")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)