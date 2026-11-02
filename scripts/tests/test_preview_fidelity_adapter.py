# -*- coding: utf-8 -*-
"""预览适配边界、运行生命周期与通信安全测试（REQ-ED-01、REQ-MD-05、REQ-MD-06、REQ-MD-07、REQ-MD-08）。

验证 Task 2.1～2.4 需求：
- 2.1: 纯配置与结果对象无 GUI 可用；统一适配边界；正文编辑/撤销状态不受影响
- 2.2: 按需导入、页面就绪队列只发最新、模式切换不写文件/不污染撤销
- 2.3: QWebChannel 白名单校验、拒绝未知动作/伪造路径、块注册表解析
- 2.4: 运行组件缺失/加载失败/崩溃退出安全降级，编辑缓冲保留，无无限重启
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from doc_tool.domain.preview_types import (
    BlockLocation,
    BlockRegistry,
    DiagramIdentity,
    PreviewMode,
    PreviewSnapshot,
)
from doc_tool.ui.content.editor_panel import EditorPanel, _PreviewBrowser
from doc_tool.ui.content.preview_adapter import PreviewAdapter
from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


class DummyWriter:
    def resolve(self, path):
        return Path(path)


class PreviewAdapterFidelityLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_2_1_domain_types_no_gui_runnable(self):
        """2.1 验收：纯配置、块注册表与快照对象可在无 GUI 进程使用。"""
        reg = BlockRegistry(snapshot_id="snap-1", source_file="doc.md")
        b1 = BlockLocation("blk-1", "doc.md", 1, 3, "heading", title="一级标题")
        b2 = BlockLocation("blk-2", "doc.md", 5, 10, "mermaid")
        reg.add_block(b1)
        reg.add_block(b2)

        self.assertEqual(reg.find_by_id("blk-1"), b1)
        self.assertEqual(reg.find_by_heading("一级标题"), b1)
        self.assertEqual(reg.find_by_line(2), b1)
        self.assertEqual(reg.find_by_line(7), b2)
        self.assertIsNone(reg.find_by_line(4))

        snap = PreviewSnapshot("s-1", "ch-1", 1, "hash-a", "light")
        self.assertTrue(snap.is_current("s-1", "ch-1", 1))
        self.assertFalse(snap.is_current("s-1", "ch-1", 2))

        diag = DiagramIdentity(
            block_id="blk-2",
            source_file="doc.md",
            start_line=5,
            source_hash="h1",
            engine_version="11.16.1",
            config_hash="c1",
            backend="official-webengine",
            is_fidelity=True,
        )
        self.assertTrue(diag.is_fidelity)
        self.assertEqual(diag.engine_version, "11.16.1")

    def test_2_2_mode_switch_preserves_editor_buffer_and_undo(self):
        """2.2 验收：切换预览模式不修改正文、不触发保存、不污染撤销历史。"""
        panel = EditorPanel(DummyWriter(), writable=True)
        initial_text = "# 标题\n\n测试正文内容。"
        panel._editor.setPlainText(initial_text)

        # 记录初始状态
        undo_available_before = panel._editor.document().isUndoAvailable()
        dirty_before = panel.is_dirty()
        text_before = panel._editor.toPlainText()

        # 切换到轻量模式
        panel._preview.set_mode(PreviewMode.LIGHTWEIGHT)
        self.assertEqual(panel._preview.mode(), PreviewMode.LIGHTWEIGHT)
        self.assertEqual(panel._editor.toPlainText(), text_before)
        self.assertEqual(panel.is_dirty(), dirty_before)
        self.assertEqual(panel._editor.document().isUndoAvailable(), undo_available_before)

        # 切换回高保真模式
        if panel._preview.is_fidelity_available():
            panel._preview.set_mode(PreviewMode.FIDELITY)
            self.assertEqual(panel._preview.mode(), PreviewMode.FIDELITY)
            self.assertEqual(panel._editor.toPlainText(), text_before)
            self.assertEqual(panel.is_dirty(), dirty_before)
            self.assertEqual(panel._editor.document().isUndoAvailable(), undo_available_before)

    def test_2_2_ready_queue_keeps_only_latest_submission(self):
        """2.2 验收：页面未就绪时连续提交只分发最新内容，中间过期内容被丢弃。"""
        browser = WebPreviewBrowser()
        browser._page_ready = False  # 模拟页面尚未就绪

        # 连续快速提交三次更新
        browser.set_markdown("旧内容 1")
        browser.set_markdown("旧内容 2")
        browser.set_markdown("最新内容 3")

        # 检查未就绪队列只保留最新内容
        self.assertIsNotNone(browser._pending_update)
        text, base_url, snap = browser._pending_update
        self.assertEqual(text, "最新内容 3")

    def test_2_3_structured_bridge_whitelist_and_path_safety(self):
        """2.3 验收：结构化桥梁校验动作白名单，拒绝伪造路径与越界操作。"""
        browser = WebPreviewBrowser()
        reg = BlockRegistry("s1", "ch.md")
        loc = BlockLocation("legal-block", "ch.md", 15, 20, "mermaid")
        reg.add_block(loc)
        browser._block_registry = reg

        received_anchors = []
        browser.anchorClicked.connect(lambda url: received_anchors.append(url.toString()))

        # 1. 合法 anchor: line-15
        browser._bridge.reportAnchorClick("line-15")
        self.assertEqual(len(received_anchors), 1)
        self.assertEqual(received_anchors[0], "line-15")

        # 2. 伪造/注入路径攻击: line-../../etc/passwd 或任意执行
        browser._bridge.reportAnchorClick("line-../../etc/passwd")
        # 应该被拒绝，不触发非法 anchor
        self.assertEqual(len(received_anchors), 1)

        # 3. 动作白名单验证
        actions_received = []
        browser.mermaidEditRequested.connect(lambda s: actions_received.append(("edit", s)))
        
        # 合法动作
        browser._bridge.reportMermaidAction("edit", "graph TD; A-->B", "{}")
        self.assertEqual(len(actions_received), 1)
        self.assertEqual(actions_received[0], ("edit", "graph TD; A-->B"))

        # 非法未知动作
        browser._bridge.reportMermaidAction("execute_shell_command", "calc.exe", "{}")
        # 必须被白名单拦截
        self.assertEqual(len(actions_received), 1)

    def test_2_4_render_process_crashed_graceful_fallback(self):
        """2.4 验收：渲染进程异常退出时自动安全降级至轻量模式，显示原因，编辑缓冲不受损。"""
        adapter = PreviewAdapter()
        adapter.update_content("# 正在编辑的重要章节\n\n正文文字不能丢失。")
        self.assertEqual(adapter._current_text, "# 正在编辑的重要章节\n\n正文文字不能丢失。")

        # 模拟高保真浏览器发生崩溃
        adapter._on_fidelity_crashed("CrashedTerminationStatus (exit code -1073741819)")

        # 验证自动回退至轻量模式
        self.assertEqual(adapter.mode(), PreviewMode.LIGHTWEIGHT)
        self.assertIn("崩溃", adapter._lbl_status.text())
        # 验证编辑正文完整保留
        self.assertEqual(adapter._current_text, "# 正在编辑的重要章节\n\n正文文字不能丢失。")
        self.assertGreater(adapter._crash_count, 0)


if __name__ == "__main__":
    unittest.main()
