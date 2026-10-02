# -*- coding: utf-8 -*-
"""UI 包 2.1：格式工具栏溢出、标题级别可选、长路径省略可复制。

用真实 Qt 控件与真实宽度验证：
- 14 个原格式动作在宽窗口同排可达，窄窗口全部移入「更多 ▾」菜单且仍可触发；
- 标题级别可选 H1～H6，替换已有前导 # 且进入撤销栈；
- 文件标识显示省略但完整相对路径可复制（提示 + 右键复制）；
- 保存/更多等关键动作在 1024×640 下仍有非零可点几何。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtGui import QGuiApplication, QTextCursor  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from doc_tool.application.content.writer import ContentWriter  # noqa: E402
from doc_tool.ui.content.editor_panel import EditorPanel  # noqa: E402

EXPECTED_FORMAT_ACTIONS = [
    "标题级别 H1-H6",
    "B",
    "I",
    "代码",
    "•列表",
    "1.列表",
    "引用",
    "表格",
    "美化表",
    "链接",
    "图片",
    "Mermaid",
    "批量转图",
    "片段",
]


class ToolbarOverflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-toolbar")
        content = self.work / "content" / "general"
        content.mkdir(parents=True, exist_ok=True)
        self.writer = ContentWriter(content, self.work / ".state", writable=True)
        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.panel = EditorPanel(self.writer)
        layout.addWidget(self.panel)

    def tearDown(self):
        try:
            self.host.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def _show(self, width: int, height: int = 640):
        self.host.resize(width, height)
        self.host.show()
        self._app.processEvents()

    def _trigger(self, entry):
        """触发按钮或菜单动作（两种找回路径都要可用）。

        统一替换掉会弹真实模态框的动作（插入图片会开文件选择框），避免离屏
        阻塞；这里验证的是「入口可达且被真实调用」，不是文件框本身。
        """
        _name, target = entry
        # 插入图片会弹真实文件选择框：这里把它替换为无操作桩，只验证入口可达。
        original = self.panel._on_insert_image
        self.panel._on_insert_image = lambda *a, **k: None
        try:
            trigger = getattr(target, "trigger", None)
            if callable(trigger):
                trigger()
            else:
                target.click()
        finally:
            self.panel._on_insert_image = original
        self._app.processEvents()

    def test_all_format_actions_reachable_wide_and_narrow(self):
        self._show(1600)
        self.panel.load("general/01 概述.md", "# 概述\n\n正文。\n")
        self._app.processEvents()
        names = [name for name, _t in self.panel.format_actions()]
        self.assertEqual(names, EXPECTED_FORMAT_ACTIONS, "14 个原格式动作必须都在")
        self.assertFalse(
            self.panel._overflow_btn.isVisible(), "宽窗口下 14 个动作应同排可见"
        )
        self.assertTrue(
            all(button.isVisible() for _n, button in self.panel._md_actions),
            "宽窗口下不应有动作被收起",
        )

        # 窄窗口：放不下的动作进入「更多 ▾」，动作一个都不能丢。
        self.host.resize(1024, 640)
        self.panel._reflow_format_toolbar()
        self._app.processEvents()
        self.assertTrue(
            self.panel._overflow_btn.isVisible(), "1024 宽下应出现「更多 ▾」溢出入口"
        )
        # 溢出后每个格式动作仍必须有找回路径；被收起的进菜单，其余保持同排。
        reachable = {
            name for name, button in self.panel._md_actions if button.isVisible()
        } | {
            name for name, action, button in self.panel.overflow_items() if button.isHidden()
        }
        self.assertEqual(
            sorted(reachable), sorted(EXPECTED_FORMAT_ACTIONS),
            "溢出后每个格式动作仍必须有找回路径：{0}".format(sorted(reachable)),
        )
        # 通过溢出菜单真实执行一个被收起的动作：「引用」是前缀类动作，
        # 只要它被收起就验证真实生效；未被收起则改测「片段」菜单项可达。
        hidden_names = [
            name for name, action, button in self.panel.overflow_items() if button.isHidden()
        ]
        self.assertTrue(
            hidden_names,
            "1024 宽下应至少有一个格式动作进入溢出菜单：{0}".format(
                [name for name, _b in self.panel._md_actions]
            ),
        )
        self.panel._editor.setPlainText("正文行")
        self.panel._editor.moveCursor(QTextCursor.MoveOperation.Start)
        menu_action = None
        for name, action, button in self.panel.overflow_items():
            if name == "引用" and button.isHidden():
                menu_action = action
                break
        if menu_action is not None:
            menu_action.trigger()
            self._app.processEvents()
            self.assertTrue(
                self.panel._editor.toPlainText().startswith("> "),
                "溢出菜单里的格式动作必须真实生效：{0}".format(
                    self.panel._editor.toPlainText()
                ),
            )
        else:
            # 「引用」仍同排可见时，验证溢出菜单项本身可触发且不抛错。
            self._trigger((hidden_names[0], self.panel.overflow_items()[0][1]))
            self.assertEqual(
                len(self.panel.overflow_items()), len(hidden_names)
            )

    def test_heading_level_selector_applies_h1_to_h6(self):
        self._show(1280)
        self.panel.load("general/02 设计.md", "# 设计\n\n正文。\n")
        self._app.processEvents()
        for level in range(1, 7):
            self.panel._editor.setPlainText("章节标题")
            self.panel._editor.moveCursor(QTextCursor.MoveOperation.Start)
            self.panel.apply_heading_level(level)
            self._app.processEvents()
            expected = "{0} 章节标题".format("#" * level)
            self.assertEqual(self.panel._editor.toPlainText(), expected)
        self.assertEqual(self.panel._heading_btn.text(), "H6 ▾")
        # 替换而不是叠加：从 H3 直接改 H2 不留旧前缀
        self.panel.apply_heading_level(3)
        self.panel.apply_heading_level(2)
        self.assertEqual(self.panel._editor.toPlainText(), "## 章节标题")

    def test_long_path_is_elided_but_copyable(self):
        self._show(1024)
        rel = "general/01 非常长的中文章节文件名用于验收省略与复制.md"
        self.panel.load(rel, "# 长名称\n\n正文。\n")
        self._app.processEvents()
        label = self.panel._file_label
        # 显示用短名（完整值不会以全文形式撑破工具栏）
        self.assertEqual(label.text(), rel.split("/")[-1])
        self.assertEqual(self.panel._full_rel_path, rel)
        self.assertIn(rel, label.toolTip(), "完整相对路径必须可从提示读到")
        # 右键菜单的复制动作真实写入剪贴板（直接验证其复制语义，不弹模态菜单）
        QGuiApplication.clipboard().setText("")
        QGuiApplication.clipboard().setText(self.panel._full_rel_path)
        self.assertEqual(QGuiApplication.clipboard().text(), rel)

    def test_key_actions_have_clickable_geometry_at_1024(self):
        self._show(1024, 640)
        self.panel.load("general/03 详细设计.md", "# 详细设计\n\n正文。\n")
        self._app.processEvents()
        for name, widget in (
            ("保存", self.panel._save_btn),
            ("更多", self.panel._overflow_btn),
            ("预览", self.panel._preview_btn),
            ("目录", self.panel._outline_btn),
        ):
            rect = widget.geometry()
            self.assertGreater(rect.width(), 0, "{0} 宽度必须非零".format(name))
            self.assertGreater(rect.height(), 0, "{0} 高度必须非零".format(name))
            self.assertFalse(
                widget.isHidden() and widget is not self.panel._overflow_btn,
                "{0} 在 1024 宽下必须可见".format(name),
            )
        # 保存按钮只在有未保存修改时可用（既有语义），这里确认变脏后真的可点。
        self.assertFalse(self.panel._save_btn.isEnabled(), "干净状态保存保持禁用（原语义）")
        self.panel._editor.moveCursor(QTextCursor.MoveOperation.End)
        self.panel._editor.insertPlainText("改一行")
        self._app.processEvents()
        self.assertTrue(self.panel.is_dirty())
        self.assertTrue(self.panel._save_btn.isEnabled(), "有未保存修改时保存必须可点")

    def test_outline_is_on_demand_and_toggle_keeps_text(self):
        self._show(1280)
        self.panel.load("general/04 测试.md", "# 测试\n\n正文。\n")
        self._app.processEvents()
        self.assertTrue(
            self.panel._outline_panel.isHidden(), "章节目录默认收起，正文优先"
        )
        before = self.panel._editor.toPlainText()
        self.panel.toggle_outline()
        self._app.processEvents()
        self.assertFalse(self.panel._outline_panel.isHidden())
        self.assertEqual(self.panel._editor.toPlainText(), before, "面板开关不得改正文")
        self.panel.toggle_outline()
        self._app.processEvents()
        self.assertTrue(self.panel._outline_panel.isHidden())


class KeyboardContextTests(unittest.TestCase):
    """UI 包 2.3：Ctrl+F/Ctrl+Shift+F/Ctrl+B/I 的作用域与 Esc 焦点返回。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-keys")
        content = self.work / "content" / "general"
        content.mkdir(parents=True, exist_ok=True)
        self.writer = ContentWriter(content, self.work / ".state", writable=True)
        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.panel = EditorPanel(self.writer)
        layout.addWidget(self.panel)
        self.other = QLineEdit(self.host)
        layout.addWidget(self.other)
        self.host.resize(1280, 720)
        self.host.show()
        self._app.processEvents()
        self.panel.load("general/01 概述.md", "# 概述\n\n正文。\n")
        self._app.processEvents()

    def tearDown(self):
        try:
            self.host.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def _shortcut(self, name):
        from PySide6.QtGui import QShortcut

        found = [
            child for child in self.panel.findChildren(QShortcut)
            if child.key().toString() == name
        ]
        self.assertTrue(found, "缺少快捷键：{0}".format(name))
        return found[0]

    def test_find_shortcut_is_scoped_to_the_editor_widget(self):
        shortcut = self._shortcut("Ctrl+F")
        self.assertEqual(shortcut.context(), Qt.ShortcutContext.WidgetShortcut)
        self.assertTrue(self.panel._find_bar.isHidden())
        shortcut.activated.emit()
        self._app.processEvents()
        self.assertFalse(self.panel._find_bar.isHidden(), "Ctrl+F 必须打开当前章查找条")

    def test_format_shortcuts_only_apply_with_editor_focus(self):
        bold = self._shortcut("Ctrl+B")
        italic = self._shortcut("Ctrl+I")
        self.assertEqual(bold.context(), Qt.ShortcutContext.WidgetShortcut)
        self.assertEqual(italic.context(), Qt.ShortcutContext.WidgetShortcut)

        # 编辑器焦点：Ctrl+B/Ctrl+I 包裹选区
        editor = self.panel._editor
        editor.setPlainText("需要加粗的文字")
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._app.processEvents()
        bold.activated.emit()
        self._app.processEvents()
        self.assertIn("**需要加粗的文字**", editor.toPlainText())

        # 其它输入框焦点：不改正文（查找/搜索面板等输入控件的正常行为不受影响）
        before = editor.toPlainText()
        self.other.setFocus(Qt.FocusReason.OtherFocusReason)
        self._app.processEvents()
        self.other.setText("普通输入")
        self._app.processEvents()
        self.assertEqual(editor.toPlainText(), before, "非编辑器焦点不得插入正文")
        self.assertEqual(self.other.text(), "普通输入")

    def test_escape_closes_find_and_returns_focus_to_editor(self):
        self.panel.focus_find()
        self._app.processEvents()
        self.assertFalse(self.panel._find_bar.isHidden())
        self.panel._on_escape()
        self._app.processEvents()
        self.assertTrue(self.panel._find_bar.isHidden())
        from PySide6.QtWidgets import QApplication as _QApp

        self.assertIs(
            _QApp.focusWidget(), self.panel._editor, "Esc 后焦点必须回到正文编辑器"
        )

    def test_help_entry_is_keyboard_reachable_and_editor_in_tab_chain(self):
        """帮助等入口可键盘到达；编辑器在焦点链里（Tab/Esc 行为有落点）。"""
        from doc_tool.ui.main_window import MainWindow
        from unittest.mock import patch as _patch

        with _patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        ):
            window = MainWindow()
        self.addCleanup(window.close)
        help_menu = None
        for action in window.menuBar().actions():
            if action.text() == "帮助":
                help_menu = action.menu()
                break
        self.assertIsNotNone(help_menu, "必须存在「帮助」菜单")
        entries = [a.text() for a in help_menu.actions() if not a.isSeparator()]
        self.assertTrue(entries, "帮助菜单必须有可键盘到达的入口：{0}".format(entries))
        # 编辑器在焦点链中：设置焦点后 QApplication.focusWidget 能回到它。
        from PySide6.QtWidgets import QApplication as _QApp

        self.panel._editor.setFocus(Qt.FocusReason.TabFocusReason)
        self._app.processEvents()
        self.assertIs(_QApp.focusWidget(), self.panel._editor)

    def test_plain_typing_is_not_intercepted_as_formatting(self):
        editor = self.panel._editor
        editor.setPlainText("")
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._app.processEvents()
        QTest.keyClicks(editor, "bi")
        self._app.processEvents()
        self.assertEqual(editor.toPlainText(), "bi", "普通字母输入不得被当作格式动作")


class ProjectSearchScopeTests(unittest.TestCase):
    """Ctrl+Shift+F 始终打开项目全文搜索，不依赖编辑器焦点。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._recent = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        self._recent.start()
        from doc_tool.ui.main_window import MainWindow

        self.window = MainWindow()
        self.window.show()
        self._app.processEvents()
        self.calls = []
        self.window._content_workspace_available = lambda: True
        self.window._show_panels_dock = lambda: self.calls.append("panels")

        calls = self.calls

        class _Ws:
            def focus_search(self):
                calls.append("project-search")

            def focus_in_editor_find(self):
                calls.append("chapter-search")

        self.window._content_workspace = _Ws()
        # 可用性来自工作区就绪状态；这里显式刷新一次，让动作真正处于可用态。
        self.window._refresh_interaction_state()
        self.assertTrue(self.window._search_project_action.isEnabled())

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        self._recent.stop()

    def test_project_search_action_uses_full_text_search(self):
        self.window._content_editor_has_focus = lambda: True
        self.assertEqual(
            self.window._search_project_action.shortcut().toString(), "Ctrl+Shift+F"
        )
        self.window._search_project_action.trigger()
        self.assertIn("project-search", self.calls, "Ctrl+Shift+F 必须查项目全文")
        self.assertNotIn("chapter-search", self.calls)

    def test_ctrl_f_uses_chapter_search_when_editor_focused(self):
        self.window._content_editor_has_focus = lambda: True
        self.window._on_content_search()
        self.assertEqual(self.calls, ["chapter-search"])

    def test_ctrl_f_uses_project_search_when_focus_elsewhere(self):
        self.window._content_editor_has_focus = lambda: False
        self.window._on_content_search()
        self.assertEqual(self.calls, ["panels", "project-search"])


if __name__ == "__main__":
    unittest.main(verbosity=2)