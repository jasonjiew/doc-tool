# -*- coding: utf-8 -*-
"""主页面及项目级界面体验优化测试集。

覆盖验证：
1. Docs-as-Code 3 步流水线引导条与 Ctrl+K 命令入口。
2. 文档转换与 PDF 工具箱卡片上的格式/工具直达胶囊（.docx, .pdf, .md, .html, 合并, 拆分, 水印, 加密, 解密, 压缩, 页码）。
3. 最近项目路径失效告警、定位、复制路径、列表条目移除。
4. 最近项目实时检索过滤。
5. ProjectBar 上的关闭项目按钮生命周期（显示/隐藏/重置/点击）。
6. MainWindow.close_project 闭环（未保存检查、会话保存、dock 卸载、重置回到 EmptyState 视图）。
7. 小屏幕响应式滚动容器（QScrollArea#homeScrollArea）包裹与无损展示。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
)

from doc_tool.application.project_service import RecentEntry
from doc_tool.ui.workbench_state import ActionState, WorkbenchState, WorkView
from doc_tool.ui.empty_state import EmptyState, _ClickablePill
from doc_tool.ui.main_window import MainWindow
from doc_tool.ui.project_bar import ProjectBar


class HomeExperienceIterationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pipeline_banner_rendering_and_command_button(self):
        """测试 Docs-as-Code 3 步流水线横幅与 Ctrl+K 全局快捷键入口。"""
        cmd_triggered = []
        home = EmptyState(on_command_palette=lambda: cmd_triggered.append(True))
        home.resize(1120, 720)

        banner = home.findChild(QFrame, "pipelineBanner")
        self.assertIsNotNone(banner)

        labels = [c.text() for c in banner.findChildren(QLabel)]
        self.assertIn("①", labels)
        self.assertIn("导入拆解", labels)
        self.assertIn("Word 智能分章", labels)
        self.assertIn("②", labels)
        self.assertIn("协同撰写", labels)
        self.assertIn("Markdown 审查", labels)
        self.assertIn("③", labels)
        self.assertIn("规范出稿", labels)
        self.assertIn("自动化合规 DOCX", labels)

        cmd_btns = [b for b in banner.findChildren(QPushButton) if "Ctrl+K" in b.text()]
        self.assertEqual(len(cmd_btns), 1)
        cmd_btns[0].click()
        self.assertEqual(cmd_triggered, [True])

    def test_interactive_chips_on_convert_card(self):
        """测试文档转换卡片胶囊可直接携带目标格式触发转换。"""
        chosen_formats = []
        home = EmptyState(on_convert=lambda fmt=None: chosen_formats.append(fmt))
        home.resize(1120, 720)

        pills = [c for c in home._convert_card.findChildren(_ClickablePill)]
        pill_map = {p.text(): p for p in pills}

        self.assertIn(".docx", pill_map)
        self.assertIn(".pdf", pill_map)
        self.assertIn(".md", pill_map)
        self.assertIn(".html", pill_map)

        pill_map[".docx"].clicked.emit()
        self.assertEqual(chosen_formats, ["docx"])

        pill_map[".md"].clicked.emit()
        self.assertEqual(chosen_formats, ["docx", "md"])

    def test_interactive_chips_on_pdf_toolbox_card(self):
        """测试 PDF 工具箱卡片胶囊可直接直达指定工具。"""
        chosen_tools = []
        home = EmptyState(on_pdf_toolbox=lambda tid=None: chosen_tools.append(tid))
        home.resize(1120, 720)

        pills = [c for c in home._pdf_card.findChildren(_ClickablePill)]
        pill_map = {p.text(): p for p in pills}

        for name in ("合并", "拆分", "水印", "加密", "解密", "压缩", "页码"):
            self.assertIn(name, pill_map)

        pill_map["水印"].clicked.emit()
        self.assertEqual(chosen_tools, ["watermark"])

        pill_map["合并"].clicked.emit()
        self.assertEqual(chosen_tools, ["watermark", "merge"])

    def test_recent_projects_actions_and_invalidation(self):
        """测试最近项目定位、复制路径、移除与失效目录标记。"""
        removed = []
        home = EmptyState(on_remove_recent=removed.append)

        valid_dir = self.tmp_path / "valid_proj"
        valid_dir.mkdir()
        missing_dir = self.tmp_path / "missing_proj"

        now = datetime.now(timezone.utc)
        entries = [
            RecentEntry(
                path=str(valid_dir),
                name="valid_proj",
                document_name="系统需求规格",
                document_type="requirement",
                last_opened=now.isoformat(),
            ),
            RecentEntry(
                path=str(missing_dir),
                name="missing_proj",
                document_name="已失效归档",
                document_type="design",
                last_opened=(now - timedelta(days=5)).isoformat(),
            ),
        ]
        home.set_recent_projects(entries)
        self.assertEqual(len(home._recent_cards), 2)

        card0_pills = [p.text() for p in home._recent_cards[0].findChildren(QLabel) if p.property("pill")]
        card1_pills = [p.text() for p in home._recent_cards[1].findChildren(QLabel) if p.property("pill")]
        self.assertNotIn("路径失效", card0_pills)
        self.assertIn("路径失效", card1_pills)

        btns_card0 = home._recent_cards[0].findChildren(QPushButton)
        copy_btn = next((b for b in btns_card0 if b.text() == "📋"), None)
        self.assertIsNotNone(copy_btn)
        clipboard = QGuiApplication.clipboard()
        written: list = []
        original_set_text = clipboard.setText
        clipboard.setText = lambda text, mode=None: written.append(text)
        try:
            copy_btn.click()
        finally:
            clipboard.setText = original_set_text
        self.assertEqual(written, [str(valid_dir)])

        remove_btn = next((b for b in btns_card0 if b.text() == "✕"), None)
        self.assertIsNotNone(remove_btn)
        remove_btn.click()
        self.assertEqual(removed, [str(valid_dir)])

    def test_recent_projects_filter_search(self):
        """测试当条目达到 3 条时展示快速过滤搜索框并支持实时检索。"""
        home = EmptyState()
        now = datetime.now(timezone.utc)
        entries = [
            RecentEntry(path="D:/arch", name="arch", document_name="系统总体架构设计", last_opened=now.isoformat()),
            RecentEntry(path="D:/req", name="req", document_name="用户需求说明书", last_opened=now.isoformat()),
            RecentEntry(path="D:/api", name="api", document_name="外部接口协议规范", last_opened=now.isoformat()),
        ]
        home.set_recent_projects(entries)
        self.assertFalse(home._search_input.isHidden())
        self.assertEqual(len(home._recent_cards), 3)

        home._search_input.setText("架构")
        self.assertFalse(home._recent_cards[0].isHidden())
        self.assertTrue(home._recent_cards[1].isHidden())
        self.assertTrue(home._recent_cards[2].isHidden())

        home._search_input.clear()
        self.assertFalse(home._recent_cards[0].isHidden())
        self.assertFalse(home._recent_cards[1].isHidden())
        self.assertFalse(home._recent_cards[2].isHidden())

    def test_project_bar_close_button_lifecycle(self):
        """测试 ProjectBar 上的关闭项目按钮显隐与点击回调。"""
        closed = []
        bar = ProjectBar(on_close_project=lambda: closed.append(True))
        self.assertTrue(bar._close_btn.isHidden())

        summary = type("FakeSummary", (), {"manifest": None, "project_root": Path("D:/proj")})()
        state = WorkbenchState(
            view=WorkView.IDLE,
            actions={"validate": ActionState(True, ""), "diag_build": ActionState(True, ""), "merge": ActionState(True, "")},
            readiness_text="就绪",
        )
        bar.render(summary, state)
        self.assertFalse(bar._close_btn.isHidden())

        bar._close_btn.click()
        self.assertEqual(closed, [True])

        bar.reset()
        self.assertTrue(bar._close_btn.isHidden())

    def test_main_window_close_project_lifecycle(self):
        """测试 MainWindow.close_project 闭环回到 EmptyState 视图。"""
        window = MainWindow()
        self.addCleanup(window.close)
        window._init_content_workspace = lambda s: None

        self.assertEqual(window._stack.currentWidget(), window._empty_state)
        self.assertIsNone(window.project)

        summary = type("FakeSummary", (), {
            "manifest": type("Manifest", (), {
                "documentName": "测试文档",
                "documentType": "general",
                "documentVersion": "1.0",
                "documentNo": "NO-1",
                "sourceSha256": "abc",
                "lastSuccessfulBuildVersion": "",
            })(),
            "project_root": self.tmp_path / "mock_proj",
            "is_writable": True,
            "lock_info": None,
        })()
        (self.tmp_path / "mock_proj").mkdir()
        window.show_project(summary)

        self.assertEqual(window._stack.currentWidget(), window._ide_page)
        self.assertFalse(window._project_bar._close_btn.isHidden())

        success = window.close_project()
        self.assertTrue(success)
        self.assertIsNone(window.project)
        self.assertEqual(window._stack.currentWidget(), window._empty_state)
        self.assertTrue(window._project_bar._close_btn.isHidden())

    def test_responsive_scroll_container_wrapping(self):
        """测试首页任务页被 QScrollArea 容器完整包裹，防止小屏截断。"""
        home = EmptyState()
        scroll_area = home.findChild(QScrollArea, "homeScrollArea")
        self.assertIsNotNone(scroll_area)
        self.assertEqual(scroll_area.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)


    def test_pipeline_step1_click_triggers_new_project(self):
        """测试流水线向导条 Step 1 可直接点击触发新建项目向导。"""
        new_triggered = []
        home = EmptyState(on_new_project=lambda: new_triggered.append(True))
        banner = home.findChild(QFrame, "pipelineBanner")
        self.assertIsNotNone(banner)

        step1_card = banner.findChild(QFrame, "pipelineStep1Card")
        self.assertIsNotNone(step1_card)
        step1_card.clicked.emit()
        self.assertEqual(new_triggered, [True])

    def test_clickable_cards_and_pills_keyboard_accessibility(self):
        """测试卡片与胶囊支持键盘聚焦与 Enter/Space 激活。"""
        chosen_formats = []
        home = EmptyState(on_convert=lambda fmt=None: chosen_formats.append(fmt))
        
        card = home._convert_card
        self.assertEqual(card.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        
        # 键盘回车激活胶囊
        pills = [c for c in home._convert_card.findChildren(_ClickablePill)]
        docx_pill = next(p for p in pills if p.text() == ".docx")
        self.assertEqual(docx_pill.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        
        key_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        docx_pill.keyPressEvent(key_event)
        self.assertEqual(chosen_formats, ["docx"])

    def test_recent_projects_empty_state_box_and_quick_action(self):
        """测试无最近项目时渲染 recentEmptyBox 并提供快速导入按钮。"""
        new_triggered = []
        home = EmptyState(on_new_project=lambda: new_triggered.append(True))
        home.set_recent_projects([])

        empty_box = home._recent_frame.findChild(QFrame, "recentEmptyBox")
        self.assertIsNotNone(empty_box)
        self.assertIsNotNone(home._empty_label)
        self.assertIn("新建项目", home._empty_label.text())

        start_btn = next((b for b in empty_box.findChildren(QPushButton) if "导入首个文档" in b.text()), None)
        self.assertIsNotNone(start_btn)
        start_btn.click()
        self.assertEqual(new_triggered, [True])

    def test_recent_projects_search_empty_feedback_and_full_history(self):
        """测试最近项目搜索无结果时呈现空态提示，且支持搜索全量历史条目。"""
        home = EmptyState()
        now = datetime.now(timezone.utc)
        # 创建 8 个条目（超出前 5 条）
        entries = [
            RecentEntry(path=f"D:/proj_{i}", name=f"proj_{i}", document_name=f"项目文档_{i}", last_opened=now.isoformat())
            for i in range(8)
        ]
        home.set_recent_projects(entries)

        # 默认只显示前 5 个
        self.assertEqual(len(home._recent_cards), 8)
        self.assertFalse(home._recent_cards[0].isHidden())
        self.assertFalse(home._recent_cards[4].isHidden())
        self.assertTrue(home._recent_cards[5].isHidden())
        self.assertTrue(home._recent_cards[7].isHidden())

        # 搜索第 7 个项目（proj_7）
        home._search_input.setText("proj_7")
        self.assertFalse(home._recent_cards[7].isHidden())
        self.assertTrue(home._recent_cards[0].isHidden())

        # 搜索不存在的项目
        home._search_input.setText("not_exist_xyz")
        self.assertTrue(all(c.isHidden() for c in home._recent_cards))
        self.assertIsNotNone(home._search_empty_label)
        self.assertFalse(home._search_empty_label.isHidden())
        self.assertIn("not_exist_xyz", home._search_empty_label.text())

        # 清除搜索框后恢复
        home._search_input.clear()
        self.assertFalse(home._recent_cards[0].isHidden())
        self.assertTrue(home._recent_cards[7].isHidden())
        self.assertTrue(home._search_empty_label.isHidden())

    def test_recent_projects_invalid_path_locate_disabled(self):
        """测试失效路径的定位按钮自动禁用，防范假点击。"""
        missing_dir = self.tmp_path / "missing_target"
        entries = [
            RecentEntry(path=str(missing_dir), name="missing", document_name="已失效项目"),
        ]
        home = EmptyState()
        home.set_recent_projects(entries)

        btns = home._recent_cards[0].findChildren(QPushButton)
        locate_btn = next(b for b in btns if b.text() == "📁")
        self.assertFalse(locate_btn.isEnabled())
        self.assertIn("无法", locate_btn.toolTip())

    def test_close_project_blocked_when_runner_is_running(self):
        """测试当任务正在运行中时，MainWindow.close_project 拒绝关闭并保护工作区。"""
        window = MainWindow()
        self.addCleanup(window.close)
        window._init_content_workspace = lambda s: None

        summary = type("FakeSummary", (), {
            "manifest": type("Manifest", (), {
            "documentName": "测试",
            "documentType": "general",
            "documentVersion": "1.0",
            "documentNo": "NO-1",
            "sourceSha256": "abc",
            "lastSuccessfulBuildVersion": "",
        })(),
            "project_root": self.tmp_path / "busy_proj",
            "is_writable": True,
            "lock_info": None,
        })()
        (self.tmp_path / "busy_proj").mkdir()
        window.show_project(summary)
        self.assertIsNotNone(window.project)

        # 模拟后台任务运行中
        orig_is_running = window.runner._is_running
        window.runner._is_running = True
        from unittest.mock import patch
        try:
            with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                success = window.close_project()
                self.assertFalse(success)
                self.assertIsNotNone(window.project)
                mock_warn.assert_called_once()
        finally:
            window.runner._is_running = orig_is_running

    def test_close_action_menu_state(self):
        """测试文件菜单中关闭项目动作的启用与禁用状态。"""
        window = MainWindow()
        self.addCleanup(window.close)
        window._init_content_workspace = lambda s: None

        # 无项目时动作禁用
        self.assertFalse(window._close_action.isEnabled())

        # 打开项目后动作启用
        summary = type("FakeSummary", (), {
            "manifest": type("Manifest", (), {
            "documentName": "测试",
            "documentType": "general",
            "documentVersion": "1.0",
            "documentNo": "NO-1",
            "sourceSha256": "abc",
            "lastSuccessfulBuildVersion": "",
        })(),
            "project_root": self.tmp_path / "p_action",
            "is_writable": True,
            "lock_info": None,
        })()
        (self.tmp_path / "p_action").mkdir()
        window.show_project(summary)
        self.assertTrue(window._close_action.isEnabled())

    def test_project_bar_close_btn_disabled_when_running(self):
        """测试任务运行状态下 ProjectBar 关闭项目按钮处于禁用状态。"""
        bar = ProjectBar()
        summary = type("FakeSummary", (), {"manifest": None, "project_root": Path("D:/proj")})()
        
        from doc_tool.ui.workbench_state import ActionState, WorkView, WorkbenchState
        state_idle = WorkbenchState(view=WorkView.IDLE, actions={}, readiness_text="就绪")
        bar.render(summary, state_idle)
        self.assertTrue(bar._close_btn.isEnabled())

        state_running = WorkbenchState(view=WorkView.RUNNING, actions={}, readiness_text="运行中")
        bar.render(summary, state_running)
        self.assertFalse(bar._close_btn.isEnabled())
        self.assertIn("任务正在执行中", bar._close_btn.toolTip())

    def test_responsive_layout_reflow(self):
        """测试在小分辨率下自动折叠为单栏布局防截断，大分辨率为双栏。"""
        home = EmptyState()
        home.show()
        home.resize(640, 600)
        QApplication.processEvents()
        self.assertEqual(home._body_layout.direction(), QBoxLayout.Direction.TopToBottom)

        home.resize(1024, 768)
        QApplication.processEvents()
        self.assertEqual(home._body_layout.direction(), QBoxLayout.Direction.LeftToRight)


    def test_recent_project_remove_button_visibility_and_callback(self):
        """测试最近项目条目中的删除按钮(✕)样式正常、文本可见且点击能触发移除回调。"""
        from doc_tool.ui.styles import build_qss
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(build_qss("light"))
        removed = []
        home = EmptyState(on_remove_recent=lambda p: removed.append(p))
        entry = RecentEntry(path="D:/test_proj_to_remove", name="test_proj", document_name="待移除项目")
        home.set_recent_projects([entry])
        home.show()
        home.resize(800, 600)
        QApplication.processEvents()

        card = home._recent_cards[0]
        remove_btn = card.findChild(QPushButton, "recentRemoveBtn")
        self.assertIsNotNone(remove_btn)
        self.assertEqual(remove_btn.text(), "✕")
        self.assertEqual(remove_btn.property("recentAction"), "remove")
        self.assertFalse(remove_btn.isHidden())

        # 校验绘制像素在中心字形区包含前景文字像素（防范 QSS padding 截断导致中心为空白背景）
        btn_pix = remove_btn.grab()
        img = btn_pix.toImage()
        w, h = remove_btn.width(), remove_btn.height()
        center_colors = {
            img.pixelColor(x, y).name()
            for x in range(w // 4, 3 * w // 4)
            for y in range(h // 4, 3 * h // 4)
        }
        self.assertGreaterEqual(len(center_colors), 2)

        # 触发点击
        remove_btn.click()
        self.assertEqual(removed, ["D:/test_proj_to_remove"])
        home.close()

    def test_remove_recent_project_normalization(self):
        """测试 remove_recent_project 对斜杠形态与路径大小写规范化匹配。"""
        from doc_tool.application.project_service import (
            _save_recent_projects,
            load_recent_projects,
            remove_recent_project,
        )
        fake_entries = [
            RecentEntry(path="D:/Slash/Project_A", name="proj_a", document_name="文档A"),
            RecentEntry(path="D:\\Backslash\\Project_B", name="proj_b", document_name="文档B"),
        ]
        _save_recent_projects(fake_entries)
        try:
            # 用反斜杠移除斜杠条目
            remove_recent_project("D:\\Slash\\Project_A")
            remaining = [e.path for e in load_recent_projects()]
            self.assertNotIn("D:/Slash/Project_A", remaining)

            # 用正斜杠移除反斜杠条目
            remove_recent_project("D:/Backslash/Project_B")
            remaining = [e.path for e in load_recent_projects()]
            self.assertEqual(remaining, [])
        finally:
            _save_recent_projects([])

if __name__ == "__main__":
    unittest.main()
