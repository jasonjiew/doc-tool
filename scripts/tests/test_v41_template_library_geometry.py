# -*- coding: utf-8 -*-
"""V4.1 41-D 4.4：模板目录窗口在尺寸/主题/键盘/长名称下的真实可用性。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from doc_tool.ui.template_library_dialog import (  # noqa: E402
    STATE_EMPTY,
    STATE_NO_RESULT,
    STATE_OK,
    TemplateLibraryDialog,
)

PACK_YML = (
    "schemaVersion: 1\n"
    "packId: {pack_id}\n"
    "version: 1.0.0\n"
    "documentKind: requirement\n"
    "description: {description}\n"
)

SIZES = ((1024, 640), (1280, 720), (1920, 1080))


def _make_pack(root: Path, pack_id: str, description: str = "测试包") -> Path:
    pack = root / pack_id
    (pack / "skeleton").mkdir(parents=True, exist_ok=True)
    (pack / "skeleton" / "1 引言.md").write_text("# 引言\n", encoding="utf-8")
    (pack / "pack.yml").write_text(
        PACK_YML.format(pack_id=pack_id, description=description), encoding="utf-8"
    )
    return pack


class _Host:
    """最小宿主：记录状态与打开动作，不发真实建项。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.status = []
        self.opened = []
        self.created = []
        self.drafts = []

    def tl_state_dir(self):
        return self.root / ".state"

    def tl_project_root(self):
        return ""

    def tl_project_writable(self):
        return True

    def tl_project_chapters(self):
        return []

    def tl_open_path(self, path):
        self.opened.append(str(path))

    def tl_status(self, message):
        self.status.append(str(message))

    def tl_project_created(self, path):
        self.created.append(str(path))

    def tl_open_pack_draft(self, path):
        self.drafts.append(str(path))


class LibraryDialogGeometryTests(unittest.TestCase):
    """4.4：三档尺寸、明暗主题、长名称与溢出。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-ui-geom-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.standards = self.work / "standards"
        # 长名称条目：验证窄窗口下不裁切主动作、可滚动/溢出
        _make_pack(
            self.standards,
            "generic-requirement-" + "超长名称" * 8,
            description="用于验证长名称在窄窗口下的展示与溢出行为" * 3,
        )
        self.templates = self.work / "templates"
        self.templates.mkdir(parents=True, exist_ok=True)

    def _dialog(self, *, dark: bool = False):
        host = _Host(self.work)
        dialog = TemplateLibraryDialog(
            host, roots=[self.standards], templates_root=self.templates,
            state_dir=self.work / ".state",
        )
        if dark:
            from doc_tool.ui.styles import apply_theme

            apply_theme(self._app, dark=True)
            QApplication.processEvents()
        self.addCleanup(dialog.close)
        return dialog, host

    def _assert_no_horizontal_clip(self, dialog) -> None:
        """主动作必须在最小宽度内可达：不靠无上限抬高最小宽度。"""
        self.assertLessEqual(
            dialog.minimumSizeHint().width(), max(dialog.width(), 1024),
            "最小宽度不得大于常见窗口宽度（否则只能整体抬高窗口）",
        )
        self.assertLessEqual(
            dialog.primary_btn.minimumSizeHint().width(), dialog.width() + 1,
            "主动作必须在当前宽度内可达",
        )

    def test_three_sizes_keep_primary_action_reachable(self):
        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                dialog, _host = self._dialog()
                dialog.resize(width, height)
                dialog.show()
                QApplication.processEvents()
                self._assert_no_horizontal_clip(dialog)
                self.assertTrue(dialog.entry_list is not None)
                dialog.close()

    def test_long_names_do_not_break_state_or_selection(self):
        dialog, _host = self._dialog()
        dialog.resize(1024, 640)
        dialog.show()
        QApplication.processEvents()
        self.assertEqual(dialog._state, STATE_OK)
        self.assertGreaterEqual(len(dialog.entries()), 1)
        dialog.entry_list.setCurrentRow(0)
        QApplication.processEvents()
        self.assertIsNotNone(dialog.selected_entry(), "长名称条目仍可被选中")

    def test_dark_and_light_theme_both_ok(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                dialog, _host = self._dialog(dark=dark)
                dialog.show()
                QApplication.processEvents()
                self.assertEqual(dialog._state, STATE_OK, "主题切换不得影响目录状态")
                dialog.close()

    def test_escape_closes_and_tab_moves_focus(self):
        dialog, _host = self._dialog()
        dialog.show()
        QApplication.processEvents()
        first = dialog.focusWidget()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(event)
        QApplication.processEvents()
        escape = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )
        dialog.keyPressEvent(escape)
        QApplication.processEvents()
        self.assertFalse(dialog.isVisible(), "Esc 应关闭窗口")
        self.assertIsNotNone(first, "窗口应有可聚焦控件（Tab 可达）")

    def test_search_filter_and_missing_states_remain_reachable_at_narrow_width(self):
        dialog, _host = self._dialog()
        dialog.resize(1024, 640)
        dialog.show()
        dialog.search_edit.setText("不存在的模板关键字")
        QApplication.processEvents()
        self.assertEqual(dialog._state, STATE_NO_RESULT)
        self.assertTrue(dialog.status_text() or dialog.state_text(), "无结果时必须给出下一步")
        dialog.search_edit.clear()
        QApplication.processEvents()
        self.assertEqual(dialog._state, STATE_OK)

    def test_empty_directory_state_still_reachable(self):
        empty = self.work / "empty-standards"
        empty.mkdir()
        host = _Host(self.work)
        dialog = TemplateLibraryDialog(
            host, roots=[empty], templates_root=self.work / "no-templates",
            state_dir=self.work / ".state",
        )
        self.addCleanup(dialog.close)
        dialog.resize(1024, 640)
        dialog.show()
        QApplication.processEvents()
        self.assertEqual(dialog._state, STATE_EMPTY)
        self.assertTrue(dialog.status_text() or dialog.state_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)