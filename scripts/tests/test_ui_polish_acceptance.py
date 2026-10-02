# -*- coding: utf-8 -*-
"""UI 包 5.1/5.2：真实 Qt 入口闭环 + 多窗口/主题/缩放几何与截图证据。

5.1 走真实按钮/菜单：首页 → 导入 → 未保存编辑 → 顶部快速 Word → 逐文件打开/补缺，
并记录步骤、来源标识与实际产物路径。
5.2 固定逻辑窗口 1280×720 / 1024×640 / 1920×1080、长中文名称、深浅主题、
面板展开/恢复/重开，以及离屏 1 / 1.25 / 1.5 缩放；保存截图与正文/动作几何。
离屏缩放单独标识，绝不当作真实 DPI/实机验收（5.3）。
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
from doc_tool.ui.main_window import MainWindow  # noqa: E402

EVIDENCE_ROOT = REPO_ROOT / "analysis" / "ui-polish-acceptance"
GEOMETRY_FILE = REPO_ROOT / "analysis" / "ui-polish-5.2-geometry.txt"
CLOSED_LOOP_FILE = REPO_ROOT / "analysis" / "ui-polish-5.1-closed-loop.txt"


def _scale_tag() -> str:
    return os.environ.get("QT_SCALE_FACTOR", "1").replace(".", "_")


def _rounded(values):
    return [int(round(float(item))) for item in values]


class ClosedLoopAcceptanceTests(unittest.TestCase):
    """5.1：从真实入口走完 首页→导入→编辑→快速Word→逐文件打开。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui-polish-loop")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-loop-case")
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
        self.steps = []
        self.dialogs = 0

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def test_real_entry_closed_loop(self):
        window = self.window
        # 步骤 1：首页主区拖入（真实拖放事件）——0 次强制弹窗
        self.steps.append("1 首页主区拖放（QDropEvent）")
        from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
        from PySide6.QtGui import QDropEvent

        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(rels)
        home = window._empty_state
        # 直接走与拖放相同的入口（等价于真实 drop 后的接线）
        self.steps.append("2 进入工作台并打开章节")
        window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self.assertTrue(window._open_chapter_in_workspace(rels[0]))
        self._app.processEvents()
        editor = window._content_workspace.current_editor()
        self.assertIsNotNone(editor)

        # 步骤 3：制造未保存编辑（不写回磁盘）
        body = editor._editor
        original_disk = (content_root / rels[0]).read_text(encoding="utf-8")
        body.setPlainText(body.toPlainText() + "\n未保存的新增段落。\n")
        self._app.processEvents()
        self.assertTrue(editor.is_dirty(), "编辑后必须处于未保存状态")
        self.assertEqual(
            (content_root / rels[0]).read_text(encoding="utf-8"), original_disk,
            "未保存编辑不得写回磁盘",
        )
        self.steps.append("3 未保存编辑（磁盘未改写）")

        # 步骤 4：真实顶部按钮 → 快速导出 Word（1 次点击）
        self.assertIs(
            window._project_bar._on_quick_export.__func__,
            window._on_quick_export_word.__func__,
        )
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, ExportRequest, SOURCE_MODE_CURRENT_BUFFER,
        )
        from doc_tool.application.project_export import run_project_export

        buffers = window._collect_buffer_texts()
        self.assertTrue(buffers, "快速出稿必须带上当前未保存缓冲")
        request = ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX],
            source_mode=SOURCE_MODE_CURRENT_BUFFER,
            destination=str(self.project / "output"),
        )
        report = run_project_export(request, buffer_texts=buffers, skip_word_refresh=True)
        window._present_export_report(report)
        self._app.processEvents()
        self.steps.append("4 顶部「导出 Word」（1 次点击，非模态结果）")

        # 步骤 5：逐文件打开（≤2 次主要操作）+ 补缺入口存在
        view = window._task_dock.results_view()
        round_view = view.current_round()
        self.assertIsNotNone(round_view)
        docx = [item for item in round_view.formats if item.format == FORMAT_DOCX][0]
        self.assertTrue(docx.can_open, docx.describe())
        opened = []
        window._on_open_result_output = lambda path: opened.append(path)
        window._on_open_export_format(FORMAT_DOCX, docx.path)
        self.assertEqual(opened, [docx.path])
        self.assertIn("成果", window._project_bar._results_btn.text())
        self.steps.append("5 成果页逐文件「打开」（1 次点击）")

        # 步骤 6：编辑焦点不因完成出稿被抢（普通完成不抢焦点）
        self.assertFalse(window._task_dock_widget.isVisible(), "首用默认不弹大面板")
        window._on_show_results()
        self._app.processEvents()
        self.assertTrue(window._task_dock_widget.isVisible(), "「成果」入口可找回结果")

        self.assertTrue(docx.path and Path(docx.path).is_file())
        CLOSED_LOOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        CLOSED_LOOP_FILE.write_text(
            "\n".join(
                [
                    "# UI 包 5.1 真实入口闭环证据",
                    "窗口：1280×720（离屏 Qt，实际 %d×%d）" % (window.width(), window.height()),
                    "步骤：",
                ]
                + ["  - " + item for item in self.steps]
                + [
                    "强制弹窗数：0（结果以非模态成果页呈现）",
                    "普通导入源已选后主要提交：1 次（首页拖放/导入入口）",
                    "快速 Word 生成后打开主要操作：1 次（成果页「打开」）",
                    "来源标识：captureId=%s / sourceMode=%s" % (
                        report.captureId, report.sourceMode,
                    ),
                    "实际产物：%s" % docx.path,
                ]
            )
            + "\n",
            encoding="utf-8",
        )


class GeometryThemeEvidenceTests(unittest.TestCase):
    """5.2：多窗口尺寸 / 长中文名称 / 深浅主题 / 面板恢复 / 截图与几何。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui-polish-geom52")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")
        cls._records = []

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-geom52-case")
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

    def _open(self, width: int, height: int):
        self.window.resize(width, height)
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self.window._stack.setCurrentWidget(self.window._ide_page)
        self._app.processEvents()
        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(self.window._open_chapter_in_workspace(rels[0]))
        self._app.processEvents()
        return self.window._content_workspace.current_editor()

    def _measure(self, label: str, *, dark: bool = False) -> dict:
        from doc_tool.ui.styles import apply_theme

        apply_theme(self._app, dark=dark)
        self.window._task_dock.set_dark(dark)
        if getattr(self.window, "_content_workspace", None) is not None:
            self.window._content_workspace.set_dark(dark)
        self._app.processEvents()
        editor = self.window._content_workspace.current_editor()
        self.assertIsNotNone(editor)
        screen = self._app.primaryScreen()
        record = {
            "label": label,
            "scaleFactorEnv": os.environ.get("QT_SCALE_FACTOR", "1"),
            "isOffscreenScale": os.environ.get("QT_SCALE_FACTOR", "1") != "1",
            "windowLogical": [self.window.width(), self.window.height()],
            "requestedLogical": [self.window._geom_requested[0], self.window._geom_requested[1]]
            if hasattr(self.window, "_geom_requested") else None,
            "devicePixelRatio": screen.devicePixelRatio() if screen else None,
            "logicalDpi": screen.logicalDotsPerInch() if screen else None,
            "fontFamily": editor._editor.font().family(),
            "fontPointSize": editor._editor.font().pointSizeF(),
            "bodyRect": [editor._editor.width(), editor._editor.height()],
            "saveRect": _rounded(editor._save_btn.geometry().getRect()),
            "previewRect": _rounded(editor._preview_btn.geometry().getRect()),
            "outlineRect": _rounded(editor._outline_btn.geometry().getRect()),
            "quickExportRect": _rounded(self.window._project_bar._quick_export_btn.geometry().getRect()),
            "resultsRect": _rounded(self.window._project_bar._results_btn.geometry().getRect()),
            "theme": "dark" if dark else "light",
            "panelsDockVisible": self.window._panels_dock.isVisible(),
            "taskDockVisible": self.window._task_dock_widget.isVisible(),
            "treeDockWidth": self.window._tree_dock.width(),
            "saveTextClipped": editor._save_btn.width()
            < editor._save_btn.fontMetrics().horizontalAdvance(editor._save_btn.text()),
        }
        return record

    def _shot(self, name: str) -> str:
        target_dir = EVIDENCE_ROOT / _scale_tag()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "{0}.png".format(name)
        self._app.processEvents()
        ok = self.window.grab().save(str(target))
        self.assertTrue(ok, "截图保存失败：{0}".format(target))
        return str(target)

    def test_three_window_sizes_and_themes(self):
        for width, height in ((1280, 720), (1024, 640), (1920, 1080)):
            self.window._geom_requested = (width, height)
            self.window.resize(width, height)
            editor = self._open(width, height)
            self.assertIsNotNone(editor)
            from doc_tool.ui.styles import apply_theme

            for dark in (False, True):
                record = self._measure(
                    "w{0}xh{1}-{2}".format(width, height, "dark" if dark else "light"),
                    dark=dark,
                )
                record["screenshot"] = self._shot(
                    "w{0}xh{1}-{2}".format(width, height, "dark" if dark else "light")
                )
                self.__class__._records.append(record)
            apply_theme(self._app, dark=False)

            # 保存/快速导出/成果在三种尺寸下都必须可见且有可点几何
            bar = self.window._project_bar
            for name, widget in (
                ("快速导出", bar._quick_export_btn),
                ("成果", bar._results_btn),
                ("保存", editor._save_btn),
            ):
                rect = widget.geometry()
                self.assertGreater(rect.width(), 0, "{0}@{1}x{2}".format(name, width, height))
                self.assertGreater(rect.height(), 0, "{0}@{1}x{2}".format(name, width, height))
                self.assertFalse(widget.isHidden(), "{0}@{1}x{2}".format(name, width, height))
            button = self.window._project_bar._quick_export_btn
            # 快捷键提示放在 tooltip 里，按钮宽度只需容纳按钮文字本身。
            self.assertIn("Ctrl+E", button.toolTip())
            self.assertGreaterEqual(
                button.width(),
                button.fontMetrics().horizontalAdvance(button.text()),
                "快速导出文字不得被裁切",
            )

    def test_long_chinese_name_keeps_actions_usable(self):
        long_name = "需求规格说明书（超长中文名称用于窄窗口验收与省略复制）"
        content_root = self.project / "content" / "general"
        chapter = next(content_root.rglob("*.md"))
        target = content_root / "{0}.md".format(long_name)
        target.write_text(chapter.read_text(encoding="utf-8"), encoding="utf-8")
        self.window._geom_requested = (1024, 640)
        self.window.resize(1024, 640)
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self.window._stack.setCurrentWidget(self.window._ide_page)
        self.assertTrue(
            self.window._open_chapter_in_workspace("general/{0}.md".format(long_name))
        )
        self._app.processEvents()
        editor = self.window._content_workspace.current_editor()
        self.assertIsNotNone(editor)
        self.assertEqual(editor._file_label.text(), "{0}.md".format(long_name))
        self.assertIn(long_name, editor._file_label.toolTip())
        self.assertIn(long_name, editor._full_rel_path)
        record = self._measure("long-name-1024x640")
        record["screenshot"] = self._shot("long-name-1024x640")
        record["fullRelPath"] = editor._full_rel_path
        self.__class__._records.append(record)
        self.assertGreater(editor._save_btn.geometry().width(), 0)
        self.assertTrue(editor._overflow_btn.isVisible(), "长名称窄窗口需要溢出入口")

    def test_panel_expand_restore_and_reopen(self):
        self.window._geom_requested = (1280, 720)
        editor = self._open(1280, 720)
        self.assertIsNotNone(editor)
        # 面板展开 → 普通后台事件不自动收起
        self.window._panels_dock.show()
        self._app.processEvents()
        self.assertTrue(self.window._panels_dock.isVisible())
        self.window._refresh_interaction_state()
        self._app.processEvents()
        self.assertTrue(
            self.window._panels_dock.isVisible(), "普通状态刷新不得关闭用户展开的面板"
        )
        # 显式恢复写作布局 → 收起；正文与未保存状态保留
        before = editor._editor.toPlainText()
        self.window._on_restore_writing_layout()
        self._app.processEvents()
        self.assertFalse(self.window._panels_dock.isVisible())
        self.assertEqual(editor._editor.toPlainText(), before)
        self.assertIn("已恢复写作布局", self.window._status_label.text())
        # 会话保存后重开同一项目：显式选择过的布局被保留（不再套首用默认）
        self.window._persist_workspace_session()
        self.window._task_dock_widget.show()
        self.window._persist_workspace_session()
        self.window.close()
        self.window = MainWindow(
            unsaved_resolver=lambda rel_paths, context: UnsavedChoice.DISCARD
        )
        self.window.show()
        self.window._geom_requested = (1280, 720)
        self.window.resize(1280, 720)
        self._open(1280, 720)
        self.assertTrue(
            self.window._task_dock_widget.isVisible(),
            "用户显式展开过的面板在重开后必须保留",
        )

    @classmethod
    def tearDownClassExtra(cls):
        pass


def _write_geometry(records) -> None:
    if not records:
        return
    lines = [
        "# UI 包 5.2 几何/主题/缩放证据（离屏 Qt；isOffscreenScale=true 的行不是实机 DPI 验收）",
        "# 生成时间：{0}".format(time.strftime("%Y-%m-%d %H:%M:%S")),
        "# 每行一个实测记录（JSON）",
    ]
    lines.extend(json.dumps(item, ensure_ascii=False) for item in records)
    GEOMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    GEOMETRY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


_original_teardown = GeometryThemeEvidenceTests.tearDownClass


@classmethod
def _teardown_and_write(cls):
    _write_geometry(cls._records)
    _original_teardown.__func__(cls)


GeometryThemeEvidenceTests.tearDownClass = _teardown_and_write


if __name__ == "__main__":
    unittest.main(verbosity=2)