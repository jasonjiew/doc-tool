# -*- coding: utf-8 -*-
"""UI 包 2.2：首用写作布局、旧会话优先与「恢复写作布局」。

全部用真实 Qt 控件与真实几何（离屏）验证：
- 无会话时按首用默认：工具面板与空闲任务 Dock 收起，1280×720 下正文控件
  至少 560×320（记录实际矩形，不用「非零尺寸」代替）；
- 已有有效 SessionState（含 Dock 显隐）时用户偏好优先，不被默认覆盖；
- 「恢复写作布局」只重设显隐/尺寸：正文、未保存缓冲、标签、滚动、预览与主题不变；
- 会话文件损坏时安全回退首用默认且不抛异常。
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

from doc_tool.application.content.workspace_state import (  # noqa: E402
    SessionState,
    WorkspaceStateStore,
)
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402
from doc_tool.ui.writing_layout import (  # noqa: E402
    DOCK_PANELS,
    DOCK_TASK,
    DOCK_TREE,
    default_writing_layout,
    should_apply_default_layout,
)


class WritingLayoutDefaultsTests(unittest.TestCase):
    """纯判定：默认布局取值与旧会话优先规则。"""

    def test_default_layout_collapses_idle_docks(self):
        layout = default_writing_layout()
        self.assertTrue(layout.docks[DOCK_TREE].visible)
        self.assertFalse(layout.docks[DOCK_PANELS].visible)
        self.assertFalse(layout.docks[DOCK_TASK].visible)
        self.assertEqual(
            layout.docks[DOCK_TREE].maximum_width, 240, "章节树默认收窄，给正文让出空间"
        )

    def test_should_apply_default_only_without_preference(self):
        self.assertTrue(should_apply_default_layout(None))
        self.assertTrue(should_apply_default_layout(SessionState()))
        with_layout = SessionState(dock_visibility={DOCK_PANELS: True, DOCK_TASK: True})
        self.assertFalse(should_apply_default_layout(with_layout))
        chosen = SessionState(layout_chosen=True)
        self.assertFalse(should_apply_default_layout(chosen))

    def test_session_roundtrip_keeps_layout_choice(self):
        state = SessionState(
            dock_visibility={DOCK_PANELS: False},
            open_tabs=["01-a.md"],
            current_file="01-a.md",
            scroll_positions={"01-a.md": 7},
            preview_enabled={"01-a.md": True},
            layout_chosen=True,
        )
        restored = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertTrue(restored.layout_chosen)
        self.assertTrue(restored.has_layout_preference)
        self.assertFalse(restored.empty)
        # 「恢复写作布局」只改显隐/尺寸：会话里的标签/滚动/预览原样保留。
        restored.dock_visibility = default_writing_layout().visibility
        self.assertEqual(restored.scroll_positions, {"01-a.md": 7})
        self.assertEqual(restored.preview_enabled, {"01-a.md": True})
        self.assertEqual(restored.open_tabs, ["01-a.md"])


class WritingLayoutWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui-polish-layout")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-layout-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        # 历史会话残留：默认布局用例必须在“无会话偏好”前提下运行。
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
        from doc_tool.application.content.unsaved import UnsavedChoice

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

    def _open_project_and_wait(self):
        self.window._open_project_path(str(self.project))
        self.assertIsNotNone(self.window._project_summary)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self.window._stack.setCurrentWidget(self.window._ide_page)
        self._app.processEvents()

    def _open_first_chapter(self):
        content_root = self.project / "content" / "general"
        rel_paths = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(rel_paths, "夹具项目应至少有一章")
        self.assertTrue(self.window._open_chapter_in_workspace(rel_paths[0]))
        self._app.processEvents()
        return self.window._content_workspace.current_editor()

    def test_first_use_default_layout_gives_body_space(self):
        self._open_project_and_wait()
        self.assertFalse(
            self.window._panels_dock.isVisible(), "首用默认应收起底部工具面板"
        )
        self.assertFalse(
            self.window._task_dock_widget.isVisible(), "空闲任务/结果 Dock 首用默认收起"
        )
        self.assertTrue(self.window._tree_dock.isVisible(), "章节树保留但收窄")
        self.assertLessEqual(self.window._tree_dock.maximumWidth(), 240)

        editor = self._open_first_chapter()
        if editor is None:
            self.skipTest("离屏环境下编辑器未就绪：由 test_gui_services 覆盖打开路径")
        body = editor._editor
        geometry = (body.width(), body.height())
        self.assertGreaterEqual(
            body.width(), 560, "1280×720 默认单栏正文宽度不足：{0}×{1}".format(*geometry)
        )
        self.assertGreaterEqual(
            body.height(), 320, "1280×720 默认单栏正文高度不足：{0}×{1}".format(*geometry)
        )

    def test_valid_old_session_wins_over_default(self):
        summary_paths_state = self.project / ".state"
        summary_paths_state.mkdir(parents=True, exist_ok=True)
        WorkspaceStateStore(summary_paths_state).save(
            SessionState(
                dock_visibility={DOCK_TREE: True, DOCK_TASK: True, DOCK_PANELS: True},
                layout_chosen=True,
            )
        )
        self._open_project_and_wait()
        self.assertTrue(
            self.window._panels_dock.isVisible(), "有效旧会话要求显示工具面板时必须恢复"
        )
        self.assertTrue(self.window._task_dock_widget.isVisible())
        self.assertTrue(self.window._tree_dock.isVisible())

    def test_corrupt_session_falls_back_to_default(self):
        state_dir = self.project / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "workspace.json").write_text("{not json", encoding="utf-8")
        self._open_project_and_wait()
        self.assertFalse(self.window._panels_dock.isVisible())
        self.assertTrue(self.window._tree_dock.isVisible())

    def test_restore_layout_only_touches_layout(self):
        self._open_project_and_wait()
        editor = self._open_first_chapter()
        if editor is None:
            self.skipTest("离屏环境下编辑器未就绪：由 test_gui_services 覆盖打开路径")
        body = editor._editor
        body.setPlainText(body.toPlainText() + "\n追加一行未保存内容。\n")
        self._app.processEvents()
        rel = self.window._content_workspace.tabs_host.current_rel_path()
        # 离屏窗口没有真实视口高度，滚动位置在部分平台上无法真正落位；
        # 只断言恢复动作不去改写该值（不做「设置成功」的假设）。
        scroll_before = editor.scroll_position()
        editor.set_preview_enabled(True)
        self._app.processEvents()

        before_text = body.toPlainText()
        before_dirty = editor.is_dirty()
        before_rel = rel
        before_theme = self.window._dark

        # 先人为打乱布局，确认恢复动作真的改变了布局。
        self.window._panels_dock.show()
        self.window._task_dock_widget.show()
        self._app.processEvents()

        self.window._on_restore_writing_layout()
        self._app.processEvents()

        self.assertFalse(self.window._panels_dock.isVisible())
        self.assertFalse(self.window._task_dock_widget.isVisible())
        self.assertTrue(self.window._tree_dock.isVisible())

        self.assertEqual(body.toPlainText(), before_text, "恢复布局不得改动正文")
        self.assertEqual(editor.is_dirty(), before_dirty, "恢复布局不得清除未保存状态")
        self.assertEqual(
            self.window._content_workspace.tabs_host.current_rel_path(), before_rel,
            "恢复布局不得切换标签",
        )
        self.assertEqual(
            editor.scroll_position(), scroll_before, "恢复布局不得改变滚动位置"
        )
        self.assertTrue(editor.preview_enabled(), "恢复布局不得切换预览开关")
        self.assertEqual(self.window._dark, before_theme, "恢复布局不得改变主题")
        self.assertTrue(hasattr(self.window, "_restore_layout_action"))
        titles = [action.text() for action in self.window._view_menu.actions()]
        self.assertIn("恢复写作布局", titles)
        self.assertIn("已恢复写作布局", self.window._status_label.text())

    def test_restored_layout_is_persisted_for_next_open(self):
        self._open_project_and_wait()
        self.window._on_restore_writing_layout()
        self.window._persist_workspace_session()
        stored = WorkspaceStateStore(self.project / ".state").load()
        self.assertTrue(stored.layout_chosen)
        self.assertEqual(stored.dock_visibility.get(DOCK_PANELS), False)
        self.assertEqual(stored.dock_visibility.get(DOCK_TASK), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)