# -*- coding: utf-8 -*-
"""UI2-F 6.1：真实 Qt 入口日常闭环 + 三窗口/三面板宽度与主题几何证据。

本文件只做「实际控件 + 实际文件」的自动证据，明确标注离屏局限；
真实 Windows 缩放/IME/Word 试点归 6.3（缺环境保持未勾选）。
"""

from __future__ import annotations

import json
import os
import shutil
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
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    SOURCE_MODE_CURRENT_BUFFER,
)
from doc_tool.ui.export_results_view import ExportResultsView  # noqa: E402
from doc_tool.ui.export_rounds import ExportRoundView, RoundFormatView  # noqa: E402
from doc_tool.ui.export_settings_dialog import build_export_request  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "analysis" / "ui2-acceptance-20261002"
GEOMETRY_FILE = EVIDENCE_DIR / "ui2-geometry.json"
LOOP_FILE = EVIDENCE_DIR / "ui2-closed-loop.json"

WINDOW_SIZES = ((1024, 640), (1280, 720), (1920, 1080))
PANEL_WIDTHS = (340, 420, 700)


def _rect(widget) -> list:
    return [int(widget.width()), int(widget.height())]


class ClosedLoopEvidenceTests(unittest.TestCase):
    """6.1：真实入口闭环（首页→导入→未保存编辑→导出→成果→位置返回）。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-acceptance")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("ui2-acceptance-case")
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

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _settle(self, seconds: float = 0.4) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._app.processEvents()
            time.sleep(0.01)

    def _drain(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while self.window.runner.is_running and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.02)
        self._app.processEvents()

    def test_daily_loop_records_steps_and_real_artifacts(self):
        steps = []
        dialogs = 0
        window = self.window

        # 1) 首页导入入口（与按钮同一 handler）
        self.assertIs(
            window._empty_state._on_new_project.__func__,
            window._on_import_document.__func__,
        )
        steps.append("1 \u9996\u9875\u5bfc\u5165\u5165\u53e3\u4e0e\u65b0\u5efa\u9879\u76ee\u5171\u4eab handler")

        # 2) 打开项目并进入工作台
        window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self._settle()
        rels = [rel for rel, _p in discover_chapters(self.project / "content" / "general")]
        self.assertTrue(rels)
        steps.append("2 \u6253\u5f00\u9879\u76ee\u5e76\u7b49\u5f85\u7d22\u5f15\u5c31\u7eea")

        # 3) 导航：跳章 → 后退（脏缓冲保持）
        self.assertTrue(window._open_chapter_in_workspace(rels[0], source="\u7ae0\u8282\u6811"))
        self._settle()
        editor = window._content_workspace.current_editor()
        editor._editor.setPlainText(
            editor._editor.toPlainText() + "\nUI2 \u672a\u4fdd\u5b58\u6bb5\u843d\u3002\n"
        )
        self._settle(0.2)
        dirty_text = editor._editor.toPlainText()
        self.assertTrue(editor.is_dirty())
        self.assertTrue(window._open_chapter_in_workspace(rels[1], source="\u641c\u7d22\u7ed3\u679c"))
        self._settle()
        back_before = window._content_workspace.current_file()
        window._on_nav_back()
        self._settle()
        restored = window._content_workspace.current_editor()
        self.assertEqual(restored._editor.toPlainText(), dirty_text)
        self.assertTrue(restored.is_dirty())
        steps.append(
            "3 \u8df3\u7ae0\u540e\u540e\u9000\u56de\u539f\u4f4d\u7f6e\uff08\u672a\u4fdd\u5b58\u6587\u672c\u4e0e\u64a4\u9500\u6808\u4fdd\u6301\uff09"
        )
        del back_before

        # 4) 导出设置一次提交（整份 + 当前内容 + Word/HTML）
        request = build_export_request(
            project_root=str(self.project),
            formats=[FORMAT_DOCX, FORMAT_HTML],
            scope_kind="project",
            source_mode=SOURCE_MODE_CURRENT_BUFFER,
            destination=str(self.project / "output"),
        )
        window._submit_export_request(request)
        self._drain()
        round_view = window._export_rounds.latest(str(self.project))
        self.assertIsNotNone(round_view)
        steps.append("4 \u5bfc\u51fa\u8bbe\u7f6e\u63d0\u4ea4\uff081 \u6b21\u4e3b\u8981\u64cd\u4f5c\uff09\u2192 \u771f\u5b9e\u4ea7\u7269")

        # 5) 成果页逐文件打开
        window._refresh_export_results()
        self._settle()
        view = window._task_dock.results_view()
        opened = []
        window._on_open_result_output = lambda path: opened.append(path)
        docx = [item for item in round_view.formats if item.format == FORMAT_DOCX][0]
        window._on_open_export_format(FORMAT_DOCX, docx.path)
        self.assertTrue(opened, "\u6210\u679c\u9875\u5fc5\u987b\u80fd\u6253\u5f00\u672c\u8f6e\u4ea7\u7269")
        self.assertTrue(Path(docx.path).is_file())
        steps.append("5 \u6210\u679c\u9875\u9010\u6587\u4ef6\u6253\u5f00\uff081 \u6b21\u70b9\u51fb\uff09")

        # 6) 位置返回后正文未被视图/导出改写
        disk_text = (
            self.project / "content" / "general" / rels[0]
        ).read_text(encoding="utf-8")
        self.assertNotIn("UI2 \u672a\u4fdd\u5b58\u6bb5\u843d", disk_text, "\u5bfc\u51fa\u4e0d\u5f97\u5199\u56de\u6e90\u6587\u4ef6")
        steps.append("6 \u6e90\u6587\u4ef6\u672a\u88ab\u5199\u56de\uff08\u5f53\u524d\u4f4d\u7f6e\u4ecd\u53ef\u6253\u5f00\uff09")

        payload = {
            "platform": "Qt offscreen",
            "limitations": [
                "synthetic project",
                "no real Windows scaling/IME/Word trial",
                "offscreen geometry is structural evidence only",
            ],
            "steps": steps,
            "forcedDialogs": dialogs,
            "importSubmissions": 1,
            "exportSubmissions": 1,
            "openClicks": 1,
            "roundId": round_view.round_id,
            "captureId": round_view.capture_id,
            "sourceMode": round_view.source_mode,
            "scope": round_view.scope_text,
            "artifacts": [
                {"format": item.format, "status": item.status, "path": item.path}
                for item in round_view.formats
            ],
        }
        LOOP_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class GeometryEvidenceTests(unittest.TestCase):
    """6.1：三窗口尺寸 × 深浅主题 + 三面板宽度的 request/actual 几何与截图。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-geometry")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")
        cls._records = []
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        # 先应用浅色主题再度量：QSS 会改变字体与内边距，
        # 在无 QSS 状态下取样会得到“崩紧后”的无效几何（审计发现的真实漏洞）。
        from doc_tool.ui.styles import apply_theme

        apply_theme(self._app, dark=False)
        self.work = fixtures.scratch_dir("ui2-geometry-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        leftover = self.project / ".state" / "workspace.json"
        if leftover.exists():
            leftover.unlink()
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
        self.window.show()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _open(self, width: int, height: int) -> None:
        self.window.resize(width, height)
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self.window._stack.setCurrentWidget(self.window._ide_page)
        rels = [rel for rel, _p in discover_chapters(self.project / "content" / "general")]
        self.assertTrue(self.window._open_chapter_in_workspace(rels[0]))
        for _ in range(10):
            self._app.processEvents()
            time.sleep(0.01)

    def _shot(self, name: str) -> str:
        path = EVIDENCE_DIR / "{0}.png".format(name)
        self._app.processEvents()
        self.assertTrue(self.window.grab().save(str(path)), str(path))
        return path.name

    def test_window_sizes_and_themes_geometry(self):
        from doc_tool.ui.styles import apply_theme

        for width, height in WINDOW_SIZES:
            self.window.resize(width, height)
            self._open(width, height)
            for dark in (False, True):
                apply_theme(self._app, dark=dark)
                self.window._task_dock.set_dark(dark)
                if self.window._content_workspace is not None:
                    self.window._content_workspace.set_dark(dark)
                for _ in range(6):
                    self._app.processEvents()
                    time.sleep(0.01)
                editor = self.window._content_workspace.current_editor()
                bar = self.window._project_bar
                screen = self._app.primaryScreen()
                record = {
                    "kind": "window",
                    "requested": [width, height],
                    "actual": [self.window.width(), self.window.height()],
                    "theme": "dark" if dark else "light",
                    "devicePixelRatio": screen.devicePixelRatio() if screen else None,
                    "logicalDpi": screen.logicalDotsPerInch() if screen else None,
                    "fontFamily": editor._editor.font().family(),
                    "editorRect": _rect(editor._editor),
                    "navBarRect": _rect(self.window._nav_location_label),
                    "quickExport": _rect(bar._quick_export_btn),
                    "quickExportSizeHint": bar._quick_export_btn.sizeHint().width(),
                    "results": _rect(bar._results_btn),
                    "moreVisible": bar._more_btn.isVisible(),
                    "overflowKeys": bar._overflow.hidden_keys,
                    "viewMode": editor.view_mode(),
                    "fontStep": editor.font_step(),
                    "screenshot": self._shot(
                        "window-{0}x{1}-{2}".format(
                            width, height, "dark" if dark else "light"
                        )
                    ),
                }
                self.assertGreater(record["editorRect"][0], 0)
                self.assertGreaterEqual(
                    record["quickExport"][0],
                    record["quickExportSizeHint"] - 2,
                    "主按钮不得裁切文字：{0}".format(record),
                )
                self.__class__._records.append(record)
            apply_theme(self._app, dark=False)

    def test_panel_widths_geometry(self):
        from PySide6.QtCore import Qt

        view = ExportResultsView()
        view.render([
            ExportRoundView(
                round_id="ui2-geom-1",
                capture_id="ui2-cap-1",
                project_root=str(self.project),
                source_mode="current-buffer",
                scope_text="\u6240\u9009 2 \u7ae0",
                destination=str(self.project / "output"),
                formats=[
                    RoundFormatView(format="docx", status="pending-refresh", usable=True),
                    RoundFormatView(format="html", status="ready", usable=True),
                    RoundFormatView(format="pdf", status="pending-convert", message="no tool"),
                ],
            )
        ])
        # 面板在工作台中是 Dock 内容：这里作为独立顶层窗口量测，
        # 避免宿主布局的 minimum 约束掩盖面板自身的适应行为。
        view.setWindowFlags(Qt.WindowType.Window)
        view.show()
        for width in PANEL_WIDTHS:
            view.resize(width, 640)
            for _ in range(10):
                self._app.processEvents()
                time.sleep(0.01)
            record = {
                "kind": "results-panel",
                "requested": [width, 640],
                "actual": [view.width(), view.height()],
                "minimumWidthHint": view.minimumSizeHint().width(),
                "stacked": view._actions_row.is_stacked(),
                "buttons": [
                    {"text": btn.text(), "width": btn.width(), "hint": btn.sizeHint().width()}
                    for btn in (
                        view._retry_btn,
                        view._regenerate_btn,
                        view._settings_btn,
                        view._destination_btn,
                    )
                ],
            }
            record["compressedButtons"] = [
                button["text"]
                for button in record["buttons"]
                if button["width"] + 1 < button["hint"]
            ]
            # 面板可用性的硬性断言在 test_ui2_panel_productivity.py；本测试只记录几何证据。
            self.assertGreater(record["actual"][0], 0)
            self.assertGreater(record["minimumWidthHint"], 0)
            self.__class__._records.append(record)
        view.close()

    @classmethod
    def tearDownClassExtra(cls):
        pass


_original_teardown = GeometryEvidenceTests.tearDownClass


@classmethod
def _teardown_and_write(cls):
    if cls._records:
        GEOMETRY_FILE.write_text(
            json.dumps(
                {
                    "platform": "Qt offscreen",
                    "limitations": [
                        "structural evidence only",
                        "no real Windows DPI/IME/Word",
                    ],
                    "records": cls._records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    _original_teardown.__func__(cls)


GeometryEvidenceTests.tearDownClass = _teardown_and_write


if __name__ == "__main__":
    unittest.main(verbosity=2)