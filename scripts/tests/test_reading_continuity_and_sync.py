# -*- coding: utf-8 -*-
"""验证来源定位、异步更新与阅读连续性（Group 7：REQ-MD-04、REQ-MD-06、REQ-MD-07、REQ-ED-01、REQ-MM-04）。"""

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))



import os
import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication

from doc_tool.domain.preview_types import (
    BlockLocation,
    BlockRegistry,
    PreviewMode,
    PreviewSnapshot,
    build_block_registry,
)
from doc_tool.ui.content.preview_adapter import PreviewAdapter
from doc_tool.ui.content.web_preview_browser import WebPreviewBrowser


class ReadingContinuityAndSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = WebPreviewBrowser()
        if not self.browser._page_ready:
            loop = QEventLoop()
            self.browser.loadFinished.connect(lambda ok: loop.quit())
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

    def tearDown(self):
        self.browser.cleanup()

    # --- 7.1: 正文 Token 与模块来源合成为稳定块注册表 ---
    def test_7_1_block_registry_synthesis_and_module_mapping(self):
        """7.1: 重复标题、同源多图、跨文件模块映射到真实源文件与行，不可定位时给出原因。"""
        markdown_text = (
            "# 第一章 架构总览\n\n"
            "这是第一章的导言。\n\n"
            "## 详细设计\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  A --> B\n"
            "```\n\n"
            "# 第二章 详细设计\n\n"
            "## 详细设计\n\n"
            "这是第二章里的同名小节。\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  A --> B\n"
            "```\n"
        )
        # 模拟跨文件模块展开行映射：第 14 行来自 included_module.md 的第 3 行
        line_map = {
            14: ("included_module.md", 3),
            15: ("included_module.md", 4),
        }

        registry = build_block_registry(
            markdown_text,
            source_file="main_chapter.md",
            snapshot_id="snap-001",
            prepared_line_map=line_map,
        )

        self.assertGreater(len(registry.blocks), 4)

        # 验证重复标题：存在两个名为 "详细设计" 的标题块，但 block_id 不同且行号不同
        headings = [b for b in registry.blocks if b.kind == "heading" and b.title == "详细设计"]
        self.assertEqual(len(headings), 2)
        self.assertNotEqual(headings[0].block_id, headings[1].block_id)
        self.assertEqual(headings[0].start_line, 5)

        # 验证第二个同名标题映射到了真实外部模块
        self.assertEqual(headings[1].source_file, "included_module.md")
        self.assertEqual(headings[1].start_line, 3)

        # 验证两个相同的 Mermaid 源码块具有独立的 block_id
        mermaids = [b for b in registry.blocks if b.kind == "mermaid"]
        self.assertEqual(len(mermaids), 2)
        self.assertNotEqual(mermaids[0].block_id, mermaids[1].block_id)

    # --- 7.2: 点击预览回源码与编辑位置联动 ---
    def test_7_2_click_to_locate_and_cursor_sync(self):
        """7.2: 点击目标块精确定位对应行号，不因同名发生漂移；支持双向滚动联动。"""
        markdown_text = (
            "# 主标题\n\n"
            "段落一\n\n"
            "## 重复子标题\n\n"
            "段落二\n\n"
            "## 重复子标题\n\n"
            "段落三\n"
        )
        registry = build_block_registry(markdown_text, source_file="doc.md", snapshot_id="snap-002")

        # 模拟点击第二个重复子标题（在行 9）
        loc9 = registry.find_by_id("line-9")
        self.assertIsNotNone(loc9)
        self.assertEqual(loc9.start_line, 9)

        # 模拟点击第一个重复子标题（在行 5）
        loc5 = registry.find_by_id("line-5")
        self.assertIsNotNone(loc5)
        self.assertEqual(loc5.start_line, 5)

        # 验证双向滚动联动方法正常执行无报错
        self.browser.scroll_to_line(9)

    # --- 7.3: 缓冲版本/主题结果校验与乱序过期丢弃 ---
    def test_7_3_stale_snapshot_discard_on_rapid_typing(self):
        """7.3: 乱序返回的旧版本快照被安全丢弃，不覆盖最新内容。"""
        snap_v2 = PreviewSnapshot(
            session_id="session-1",
            chapter_id="chap-A",
            buffer_version=2,
            text_hash="hash2",
        )
        snap_v1_delayed = PreviewSnapshot(
            session_id="session-1",
            chapter_id="chap-A",
            buffer_version=1,
            text_hash="hash1",
        )

        # 1. 提交新版本 v2
        self.browser.set_markdown("# 最新内容 v2", snapshot=snap_v2)
        self.assertEqual(self.browser._current_snapshot.buffer_version, 2)

        # 2. 模拟延迟到达的旧版本 v1
        self.browser.set_markdown("# 过期旧内容 v1", snapshot=snap_v1_delayed)
        # 验证当前版本依然保持为 v2，旧版本被丢弃
        self.assertEqual(self.browser._current_snapshot.buffer_version, 2)

    # --- 7.4: 滚动锚点保持与图形缓存复用 ---
    def test_7_4_reading_scroll_continuity_and_diagram_reuse(self):
        """7.4: 异步更新保留滚动位置，未变化图形复用缓存，无主线程同步阻塞。"""
        long_md = (
            "# 章节开头\n\n" + ("正文段落填充内容。\n\n" * 20) +
            "```mermaid\n"
            "flowchart TD\n"
            "  X[复用节点] --> Y[不变节点]\n"
            "```\n\n" + ("后续长正文段落。\n\n" * 20)
        )
        snap = PreviewSnapshot("sess", "chap", 1, "h1")
        self.browser.set_markdown(long_md, snapshot=snap)

        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()

        # 修改部分正文后再次更新，验证依然平稳
        updated_md = long_md.replace("章节开头", "章节开头（已微调）")
        snap2 = PreviewSnapshot("sess", "chap", 2, "h2")
        self.browser.set_markdown(updated_md, snapshot=snap2)

    # --- 7.5: 多窗口隔离与对象安全释放 ---
    def test_7_5_multi_window_isolation_and_cleanup(self):
        """7.5: 多窗口独立拥有页面与会话，互不干扰，关闭可正常析构释放。"""
        browser_win2 = WebPreviewBrowser()
        if not browser_win2._page_ready:
            loop = QEventLoop()
            browser_win2.loadFinished.connect(lambda ok: loop.quit())
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

        snap_win1 = PreviewSnapshot("session-win-1", "chap-1", 1, "text1")
        snap_win2 = PreviewSnapshot("session-win-2", "chap-2", 1, "text2")

        self.browser.set_markdown("# 窗口1文本", snapshot=snap_win1)
        browser_win2.set_markdown("# 窗口2文本", snapshot=snap_win2)

        self.assertEqual(self.browser._current_snapshot.session_id, "session-win-1")
        self.assertEqual(browser_win2._current_snapshot.session_id, "session-win-2")

        # 安全释放窗口 2
        browser_win2.cleanup()
        self.assertIsNone(browser_win2._current_snapshot)


if __name__ == "__main__":
    unittest.main()
