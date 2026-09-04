# -*- coding: utf-8 -*-
"""单元测试：全局命令面板与快速打开浮层。"""

import unittest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from doc_tool.ui.command_palette import CommandPaletteDialog, PaletteItem


class CommandPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_filter_and_activate_item(self):
        called = []

        items = [
            PaletteItem(title="新建项目…", category="文件", shortcut="Ctrl+N", callback=lambda: called.append("new")),
            PaletteItem(title="正式合并出稿", category="构建", shortcut="Ctrl+Shift+B", callback=lambda: called.append("build")),
            PaletteItem(title="美化表格", category="编辑", shortcut="Ctrl+Alt+T", callback=lambda: called.append("format_table")),
        ]

        dlg = CommandPaletteDialog(items, mode="command", dark=False)

        # 初始应展示 3 项，默认选中第 0 项
        self.assertEqual(dlg._list_widget.count(), 3)
        self.assertEqual(dlg._list_widget.currentRow(), 0)

        # 过滤 "合并" -> 应该只剩 1 项
        dlg._search_input.setText("合并")
        self.assertEqual(dlg._list_widget.count(), 1)
        self.assertEqual(dlg._filtered_items[0].title, "正式合并出稿")

        # 触发当前项
        dlg._trigger_current()
        self.assertEqual(called, ["build"])

    def test_keyboard_navigation(self):
        items = [
            PaletteItem(title="条目 1"),
            PaletteItem(title="条目 2"),
            PaletteItem(title="条目 3"),
        ]
        dlg = CommandPaletteDialog(items, mode="command", dark=True)

        self.assertEqual(dlg._list_widget.currentRow(), 0)

        # 模拟 Down 键
        down_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        dlg.eventFilter(dlg._search_input, down_event)
        self.assertEqual(dlg._list_widget.currentRow(), 1)

        # 模拟 Up 键
        up_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        dlg.eventFilter(dlg._search_input, up_event)
        self.assertEqual(dlg._list_widget.currentRow(), 0)

    def test_file_mode(self):
        activated_items = []
        items = [
            PaletteItem(title="1.1 概述", category="章节", description="content/req/01.md"),
            PaletteItem(title="1.2 架构", category="章节", description="content/design/02.md"),
        ]
        dlg = CommandPaletteDialog(items, mode="file")
        dlg.itemActivated.connect(lambda item: activated_items.append(item.title))

        dlg._search_input.setText("02.md")
        self.assertEqual(dlg._list_widget.count(), 1)
        dlg._trigger_current()
        self.assertEqual(activated_items, ["1.2 架构"])


if __name__ == "__main__":
    unittest.main()
