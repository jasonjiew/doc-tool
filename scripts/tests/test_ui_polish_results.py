# -*- coding: utf-8 -*-
"""UI 包 3.1～3.4：非模态逐文件成果、原轮补缺/新轮/换目录与取消保留。

真实 Qt 控件 + 真实 ExportReport/索引验证：
- 普通完成不弹阻塞模态：成果进入右侧「成果」页，用户可继续编辑（焦点不被抢）；
- 逐格式状态/路径/打开与失效提示；关闭后仍能从「成果」入口与索引找回；
- 补这次成果用旧捕获（captureId 不变、不读新缓冲）；
- 按当前修改重新生成建立新 current-buffer 轮（新 captureId）；
- 换目录建立新轮且旧轮保留；忙时不覆盖当前任务；迟到结果归原项目。
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
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_PDF,
    FormatResult,
    STATUS_FAILED,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
)
from doc_tool.ui.export_rounds import (  # noqa: E402
    ExportRoundView,
    RoundFormatView,
    RoundStore,
)


def _result(fmt: str, status: str, path: str = "", usable: bool = False, message: str = ""):
    return FormatResult(
        format=fmt, status=status, path=path, usable=usable, message=message
    )


class RoundViewTests(unittest.TestCase):
    """纯模型：逐格式状态、失效判定与按项目保留轮次。"""

    def _round(self, round_id: str, project: str = "P1", **over):
        data = dict(
            round_id=round_id,
            project_root=project,
            source_mode="current-buffer",
            scope_text="整份文档（2 章）",
            formats=[
                RoundFormatView(format=FORMAT_DOCX, status=STATUS_READY, path="", usable=True),
                RoundFormatView(
                    format=FORMAT_PDF, status=STATUS_FAILED, usable=False, message="未安装转换器"
                ),
            ],
        )
        data.update(over)
        return ExportRoundView(**data)

    def test_partial_success_keeps_each_format_state(self):
        view = self._round("R1")
        self.assertEqual(len(view.usable_formats), 1)
        self.assertEqual([item.format for item in view.failed_formats], [FORMAT_PDF])
        self.assertTrue(view.has_retryable, "PDF 失败时应有补缺入口")
        self.assertIn("Word", view.formats[0].describe())

    def test_missing_path_is_marked_stale_not_openable(self):
        item = RoundFormatView(
            format=FORMAT_DOCX, status=STATUS_READY, path="Z:/not/here/a.docx", usable=True
        )
        self.assertFalse(item.can_open)
        self.assertTrue(item.is_stale)
        self.assertIn("已失效", item.describe())

    def test_pending_refresh_is_retryable_but_usable(self):
        view = self._round(
            "R2",
            formats=[
                RoundFormatView(
                    format=FORMAT_DOCX, status=STATUS_PENDING_REFRESH,
                    path="", usable=True,
                )
            ],
        )
        self.assertTrue(view.has_retryable, "待刷新阶段应可之后补该阶段")

    def test_round_store_keeps_history_per_project(self):
        store = RoundStore(limit=2)
        store.record(self._round("R1", "P1"))
        store.record(self._round("R2", "P1"))
        store.record(self._round("R3", "P1"))
        self.assertEqual(
            [item.round_id for item in store.for_project("P1")], ["R2", "R3"],
            "只保留最近 N 轮且旧轮不被覆盖成最新",
        )
        store.record(self._round("X1", "P2"))
        self.assertEqual([item.round_id for item in store.for_project("P2")], ["X1"])
        self.assertEqual(
            [item.round_id for item in store.for_project("P1")], ["R2", "R3"],
            "另一项目的结果不得混入本项目",
        )
        self.assertEqual(store.latest("P1").round_id, "R3")
        self.assertEqual(store.find("P1", "R2").round_id, "R2")

    def test_late_result_from_other_project_does_not_override_selection(self):
        store = RoundStore()
        store.record(self._round("NEW", "P1"))
        store.record(self._round("OLD", "P1"))
        self.assertEqual(store.latest("P1").round_id, "OLD", "迟到结果归自己的轮次")
        store.record(self._round("OTHER", "P2"))
        self.assertEqual(store.latest("P1").round_id, "OLD", "不覆盖当前项目视图")


class MainWindowResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui-polish-results")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        self.work = fixtures.scratch_dir("ui-polish-results-case")
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
        from doc_tool.application.content.unsaved import UnsavedChoice

        from doc_tool.ui.main_window import MainWindow

        self.window = MainWindow(
            unsaved_resolver=lambda rel_paths, context: UnsavedChoice.DISCARD
        )
        self.window.resize(1280, 720)
        self.window.show()
        self._open_project()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _open_project(self):
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self._app.processEvents()

    def _run_export(self, **kwargs):
        from doc_tool.application.intake_contract import ExportRequest
        from doc_tool.application.project_export import run_project_export

        # 默认走项目自有 output/ 目录：这样「重开项目从索引恢复」走真实路径。
        request = ExportRequest(
            project_root=str(self.project),
            formats=kwargs.pop("formats", [FORMAT_DOCX]),
            destination=str(self.project / kwargs.pop("destination", "output")),
            source_mode=kwargs.pop("source_mode", "saved"),
            **kwargs,
        )
        return run_project_export(request, skip_word_refresh=True)

    def test_completion_is_nonmodal_and_results_stay_reachable(self):
        report = self._run_export()
        editor_focus_before = self._app.focusWidget()
        self.window._present_export_report(report)
        self._app.processEvents()
        # 成果进入非模态页；普通完成不得弹阻塞模态框，也不夺走编辑焦点。
        self.assertEqual(
            self.window._task_dock._stack.currentWidget().__class__.__name__,
            "ExportResultsView",
        )
        view = self.window._task_dock.results_view()
        self.assertIsNotNone(view.current_round())
        self.assertIn("轮", view.current_round().summary_line())
        # 关闭成果面板后仍可从「成果」入口找回
        self.window._task_dock_widget.hide()
        self.window._on_show_results()
        self._app.processEvents()
        self.assertTrue(self.window._task_dock_widget.isVisible())
        self.assertIsNotNone(view.current_round())
        del editor_focus_before

    def test_last_round_is_restored_from_existing_index(self):
        report = self._run_export()
        self.window._record_export_round(report)
        round_id = report.roundId
        # 模拟重开项目：内存轮次清空后应能从既有 export-result.json 恢复
        self.window._export_rounds.clear()
        self.window._load_last_export_round(force=True)
        restored = self.window._export_rounds.latest(str(self.project))
        self.assertIsNotNone(restored, "必须沿用既有报告索引恢复最近一轮")
        self.assertEqual(restored.round_id, round_id)
        index = Path(report.destination) / "export-result.json"
        self.assertTrue(index.is_file())
        payload = json.loads(index.read_text(encoding="utf-8"))
        self.assertEqual(payload["roundId"], round_id)

    def test_retry_keeps_original_capture_and_ignores_new_buffer(self):
        report = self._run_export()
        view = self.window._record_export_round(report)
        captured = {}

        def _fake_retry(prior, formats, **kwargs):
            captured["prior"] = prior
            captured["formats"] = list(formats)
            captured["kwargs"] = kwargs
            return prior

        self.window._collect_buffer_texts = lambda: {"新.md": "不该被补缺读到"}
        self.window._on_export_task_done = lambda result: captured.setdefault("done", result)
        with patch(
            "doc_tool.application.project_export.retry_export_formats", _fake_retry
        ):
            self.window._on_retry_export_round(view)
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
        self.assertIn("prior", captured, "补缺必须真实调用原轮补刷新服务")
        self.assertEqual(captured["prior"].captureId, report.captureId)
        self.assertNotIn(
            "buffer_texts", captured["kwargs"],
            "补缺不得把当前编辑器缓冲混入原轮",
        )

    def test_regenerate_creates_new_current_buffer_round(self):
        first = self._run_export()
        view = self.window._record_export_round(first)
        captured = {}

        def _fake_run(request, **kwargs):
            captured["request"] = request
            captured["buffers"] = kwargs.get("buffer_texts")
            return first

        self.window._collect_buffer_texts = lambda: {"01-a.md": "改过的正文"}
        with patch(
            "doc_tool.application.project_export.run_project_export", _fake_run
        ):
            self.window._on_regenerate_round(view)
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
        request = captured["request"]
        self.assertEqual(request.source_mode, "current-buffer")
        self.assertEqual(captured["buffers"], {"01-a.md": "改过的正文"})
        self.assertTrue(request.scope.is_full, "新轮默认整份范围")
        # 旧轮仍在成果列表里（新轮不会覆盖历史）
        rounds = self.window._export_rounds.for_project(str(self.project))
        self.assertGreaterEqual(len(rounds), 1)
        self.assertEqual(rounds[0].capture_id, first.captureId)

    def test_change_destination_cancel_keeps_results(self):
        report = self._run_export()
        view = self.window._record_export_round(report)
        with patch(
            "doc_tool.ui.main_window.QFileDialog.getExistingDirectory", return_value=""
        ):
            self.window._on_change_export_destination(view)
        self.assertIn("已取消换目录", self.window._status_label.text())
        self.assertEqual(
            self.window._export_rounds.latest(str(self.project)).round_id, report.roundId
        )

    def test_change_destination_starts_new_round_in_new_directory(self):
        report = self._run_export()
        view = self.window._record_export_round(report)
        new_dir = str(self.work / "another")
        captured = {}

        def _fake_run(request, **kwargs):
            captured["request"] = request
            return report

        with patch(
            "doc_tool.ui.main_window.QFileDialog.getExistingDirectory", return_value=new_dir
        ), patch("doc_tool.application.project_export.run_project_export", _fake_run):
            self.window._on_change_export_destination(view)
            deadline = time.monotonic() + 30
            while self.window.runner.is_running and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
        self.assertEqual(captured["request"].destination, new_dir)
        self.assertEqual(
            self.window._export_rounds.latest(str(self.project)).round_id,
            report.roundId,
            "换目录前旧成果仍保留在成果列表",
        )

    def test_busy_runner_does_not_start_second_export(self):
        report = self._run_export()
        view = self.window._record_export_round(report)
        started = []
        self.window.runner._is_running = True
        try:
            with patch(
                "doc_tool.application.project_export.run_project_export",
                lambda request, **kw: started.append(request),
            ):
                self.window._on_regenerate_round(view)
        finally:
            self.window.runner._is_running = False
        self.assertEqual(started, [], "忙时不得重复启动出稿")
        self.assertIn("已有任务正在运行", self.window._status_label.text())

    def test_invalid_path_is_not_opened_and_gives_next_step(self):
        report = self._run_export()
        view = self.window._record_export_round(report)
        opened = []
        self.window._on_open_result_output = lambda path: opened.append(path)
        messages = []
        self.window._show_status_message = lambda message: messages.append(str(message))
        self.window._on_open_export_format(FORMAT_DOCX, str(self.work / "gone.docx"))
        self.assertEqual(opened, [], "失效路径不得误开另一轮文件")
        self.assertTrue(
            any("失效" in item for item in messages),
            "失效路径必须给出重新定位/重新生成的下一步：{0}".format(messages),
        )

    def test_project_switch_clears_other_project_results(self):
        report = self._run_export()
        self.window._record_export_round(report)
        self.window._task_dock.clear_result()
        self.assertEqual(self.window._task_dock.results_view().current_round(), None)
        # 另一项目的迟到结果只登记到自己名下
        from doc_tool.ui.export_rounds import ExportRoundView

        other = ExportRoundView(
            round_id="OTHER", project_root="Z:/other",
            formats=[RoundFormatView(format=FORMAT_HTML, status=STATUS_READY, usable=True)],
        )
        self.window._export_rounds.record(other)
        self.assertEqual(
            self.window._export_rounds.latest(str(self.project)).round_id, report.roundId,
            "其它项目结果不得覆盖本项目",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)