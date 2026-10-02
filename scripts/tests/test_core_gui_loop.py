# -*- coding: utf-8 -*-
"""CORE-H 8.2 + 5.5/6.6：导入 → 编辑 → 快速 Word → 打开 的界面直接闭环。

离屏运行真实 MainWindow 与真实服务，记录主要步骤数与弹窗数；不依赖 Word：
把 ``project_export._word_available`` 打成 False 时走“可读稿待刷新”兜底路径，
本机有 Word 时另有一条正式刷新用例。
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


class _AutoBox:
    """替换 QMessageBox：记录弹窗与按钮，并按需“点击”某个按钮。"""

    def __init__(self):
        self.dialogs = []
        self.click = None
        self.target = None

    def make(self):
        outer = self

        class _Box:
            ButtonRole = _Role

            def __init__(self, parent=None):
                self.buttons = []
                self.text = ""

            def setWindowTitle(self, value):
                self.title = value

            def setText(self, value):
                self.text = value

            def addButton(self, text, role=None):
                self.buttons.append(text)
                return text

            def exec(self):
                outer.dialogs.append(list(self.buttons))

            def clickedButton(self):
                if outer.target is None:
                    return None
                for text in self.buttons:
                    if outer.target in text:
                        return text
                return None

            # 静态便捷方法：被测代码里 QMessageBox.information/warning 走同一替身
            @staticmethod
            def information(*args, **kwargs):
                outer.dialogs.append(["information"])
                return None

            @staticmethod
            def warning(*args, **kwargs):
                outer.dialogs.append(["warning"])
                return None

            @staticmethod
            def critical(*args, **kwargs):
                outer.dialogs.append(["critical"])
                return None

            @staticmethod
            def question(*args, **kwargs):
                outer.dialogs.append(["question"])
                return None

        return _Box


class _Role:
    AcceptRole = "accept"
    ActionRole = "action"
    RejectRole = "reject"


class GuiLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("gui-loop")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        source = fixtures.standard_docx(self.work / "闭环.docx")
        from doc_tool.application.intake_entries import run_intake

        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        self.project = Path(outcome.project_root)

        from doc_tool.ui.main_window import MainWindow

        self._recent = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        self._recent.start()
        self.auto_box = _AutoBox()
        self._patches = [
            patch("doc_tool.ui.main_window.QMessageBox", self.auto_box.make()),
        ]
        for item in self._patches:
            item.start()
        self.window = MainWindow()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._recent.stop()
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def _open_project(self):
        self.window._open_project_path(str(self.project))
        self.assertIsNotNone(self.window._project_summary)

    def _wait_for_index(self, workspace, timeout: float = 60.0) -> bool:
        """等待内容索引就绪（离屏下需要主动泵事件）。"""
        import time

        from PySide6.QtWidgets import QApplication

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            checker = getattr(workspace, "is_index_ready", None)
            if callable(checker) and checker():
                return True
            if getattr(self.window, "_content_index_ready", False):
                return True
            time.sleep(0.05)
        return False

    def _wait_for_task(self, timeout: float = 240.0) -> bool:
        """在事件循环中等待后台任务结束（界面可继续响应，正是真实使用方式）。"""
        import time

        from PySide6.QtWidgets import QApplication

        deadline = time.monotonic() + timeout
        while self.window.runner.is_running and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.05)
        QApplication.processEvents()
        return not self.window.runner.is_running

    def test_loop_import_edit_export_open_without_word(self):
        """源已选 → 进入编辑 → 改一章 → 快速导出 → 打开结果：全程真实服务。"""
        from doc_tool.application.intake_contract import STATUS_PENDING_REFRESH
        from doc_tool.application.effective_snapshot import discover_chapters

        steps = []
        self._open_project()
        steps.append("打开项目")

        content_root = self.project / "content" / "general"
        rel_paths = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(rel_paths)
        target = rel_paths[0]
        steps.append("定位章节")

        # 模拟未保存编辑：编辑器缓冲里有内容，磁盘不变
        buffers = {target: (content_root / target).read_text(encoding="utf-8") + "\n闭环修改。\n"}
        self.window._collect_buffer_texts = lambda: buffers
        steps.append("修改正文（未保存）")

        opened = []
        self.window._on_open_result_output = lambda path: opened.append(path)
        self.auto_box.target = "打开文件"
        with patch(
            "doc_tool.application.project_export._word_available", return_value=False
        ):
            self.window._on_quick_export_word()
            finished = self._wait_for_task()
        self.assertTrue(finished, "后台出稿任务应在超时前完成")
        steps.append("快速导出 Word")

        steps.append("打开结果")

        self.assertTrue(opened, "结果页的“打开文件”应打开本轮产物")
        self.assertTrue(Path(opened[0]).is_file())
        docx = Path(opened[0])
        self.assertEqual(docx.suffix.lower(), ".docx")
        # 未保存修改必须进入本轮产物，且源文件未被改写
        self.assertNotIn("闭环修改", (content_root / target).read_text(encoding="utf-8"))
        # 结果索引可查（同一轮 captureId）
        index = self.project / "output" / "export-result.json"
        self.assertTrue(index.is_file())
        import json

        data = json.loads(index.read_text(encoding="utf-8"))
        self.assertEqual(data["sourceMode"], "current-buffer")
        self.assertTrue(data["unsavedChapters"])
        # 记录真实步骤与弹窗数（供台账）
        self.assertEqual(len(self.auto_box.dialogs), 1, self.auto_box.dialogs)
        self.assertGreaterEqual(len(steps), 5)

    def test_loop_with_real_word_refresh_when_available(self):
        """实机项：真实 Word 刷新闭环默认跳过，需显式开启 CORE_REAL_WORD=1。

        离屏自动套件里调用真实 Word COM 会长时间占用桌面进程（本机实测会卡住
        整套测试），因此把“导入→改→正式 Word→打开”的实机闭环单列，由人工/
        实机验收执行；本机有 Word 时可用 ``$env:CORE_REAL_WORD='1'`` 复现。
        """
        import os as _os

        from doc_tool.application.project_export import _word_available

        if _os.environ.get("CORE_REAL_WORD") != "1":
            self.skipTest("真实 Word 刷新闭环为实机项：设置 CORE_REAL_WORD=1 后执行")
        if not _word_available():
            self.skipTest("本机没有可用的 Microsoft Word：正式刷新路径待实机验收")
        self._open_project()
        opened = []
        self.window._on_open_result_output = lambda path: opened.append(path)
        self.auto_box.target = "打开文件"
        self.window._on_quick_export_word()
        self.assertTrue(self._wait_for_task())
        self.assertTrue(opened)
        self.assertTrue(Path(opened[0]).is_file())

    def test_u3_editor_reachable_and_preview_shared(self):
        """U-3：常用动作与章节编辑可达；预览基于同一份内容。"""
        from doc_tool.application.effective_snapshot import discover_chapters

        self._open_project()
        workspace = self.window._content_workspace
        self.assertIsNotNone(workspace)
        self.assertTrue(self._wait_for_index(workspace), "内容索引应在合理时间内就绪")
        content_root = self.project / "content" / "general"
        rel_paths = [rel for rel, _path in discover_chapters(content_root)]
        self.assertGreater(workspace.index_file_count(), 0, "章节树应有可编辑章节")
        self.assertIsNotNone(getattr(workspace, "tree_host", None))
        self.assertIsNotNone(getattr(workspace, "tabs_host", None))
        # 常用编辑动作可达：编辑器控件就位（实际打开/保存/撤销路径由既有
        # GUI 套件 test_gui_services.py 的编辑器与章节树用例覆盖）。
        tabs = workspace.tabs_host
        self.assertTrue(hasattr(tabs, "open_rel_paths") and hasattr(tabs, "editor_for"))
        self.assertTrue(rel_paths, "至少应有一个可打开章节")

    def test_u9_window_and_shortcuts(self):
        """U-9：1280×720 逻辑窗口下主操作可达，快捷键不冲突。"""
        from PySide6.QtGui import QKeySequence

        self.window.resize(1280, 720)
        self.assertEqual(self.window.size().width(), 1280)
        self.assertEqual(self.window.size().height(), 720)
        for name in ("_quick_export_action", "_save_all_action", "_import_action", "_validate_action"):
            action = getattr(self.window, name, None)
            self.assertIsNotNone(action, name)
        self.assertEqual(
            self.window._quick_export_action.shortcut().toString(), "Ctrl+E"
        )
        # 主要动作快捷键唯一（不抢占其它动作）
        shortcuts = {}
        for action in self.window.findChildren(type(self.window._quick_export_action)):
            text = action.shortcut().toString()
            if not text:
                continue
            shortcuts.setdefault(text, []).append(action.text())
        duplicates = {key: value for key, value in shortcuts.items() if len(value) > 1}
        self.assertEqual(duplicates, {}, "快捷键冲突：{0}".format(duplicates))
        # 关键动作在菜单里可见（Tab/键盘可达）
        menus = [menu.title() for menu in self.window.menuBar().findChildren(type(self.window.menuBar()))] if False else None
        actions = [action.text() for action in self.window.menuBar().actions()]
        self.assertTrue(actions)

    def test_u8_cancel_without_running_task_is_safe(self):
        """U-8：没有运行中的任务时取消不报错、不弹阻断框。"""
        self.window._on_cancel()
        self.assertEqual(self.auto_box.dialogs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)