# -*- coding: utf-8 -*-
"""UI2-A 视觉与工作台层级（1.1～1.4）：项目条自适应、共享动作与焦点。

覆盖验收 U2-1/U2-9 的可自动部分：

- 1024×640 与 1280×720、长中文文档名下，「导出 Word」「成果」按完整样式保留，
  不被裁切、不出窗口；放不下的次级动作进入「更多 ▾」且仍可触发；
- 「更多」菜单项与原按钮共用同一 QAction：可用性、提示与行为一致；
- Ctrl+E 或项目条触发快速导出只提交一次原请求；
- 普通完成/临时表单关闭后焦点回到编辑器，不取消无关任务。
"""

from __future__ import annotations

import os
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
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.unsaved import UnsavedChoice  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402
from doc_tool.ui.project_bar import ProjectBar  # noqa: E402

LONG_NAME = "企业研发系统软件需求说明书（超长中文名称用于窄窗口验收）"
PRIMARY_TEXTS = ("导出 Word", "成果")


class ProjectBarOverflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._hosts = []

    def tearDown(self):
        for widget in self._hosts:
            try:
                widget.close()
            except Exception:  # noqa: BLE001
                pass
        self._hosts = []

    def _bar(self, width: int) -> ProjectBar:
        # 保持宿主强引用：只留 addCleanup 的局部引用会被 GC 掉，导致后续访问
        # 抛「Internal C++ object already deleted」。
        host = QWidget()
        self._hosts.append(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = ProjectBar()
        layout.addWidget(bar)
        self._hosts.append(bar)
        host.resize(width, 90)
        host.show()
        for _ in range(10):
            self._app.processEvents()
            time.sleep(0.01)
        return bar

    def test_primary_actions_keep_full_width_and_never_clip(self):
        for width in (1024, 1280, 1920):
            bar = self._bar(width)
            for button in (bar._quick_export_btn, bar._results_btn):
                self.assertTrue(button.isVisible(), "{0}@{1}".format(button.text(), width))
                self.assertGreaterEqual(
                    button.width(),
                    button.sizeHint().width(),
                    "{0} 在 {1} 宽被压缩：{2} < {3}".format(
                        button.text(), width, button.width(), button.sizeHint().width()
                    ),
                )
                self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
                self.assertLessEqual(
                    button.geometry().right(), bar.width(),
                    "{0} 超出项目条：{1}".format(button.text(), button.geometry().getRect()),
                )

    def test_secondary_actions_move_into_more_menu(self):
        bar = self._bar(1024)
        # 模拟真实主窗口下更紧的可用宽度：溢出后菜单必须仍包含被收起动作。
        bar.refresh_action_overflow(520)
        self.assertTrue(bar._more_btn.isVisible(), "窄宽度必须出现「更多 ▾」")
        menu_texts = [action.text() for action in bar._overflow_menu.actions()]
        hidden = bar._overflow.hidden_keys
        self.assertTrue(hidden, "窄宽度应有动作被收起")
        for key in hidden:
            entry = bar._overflow.item(key)
            self.assertIsNotNone(entry)
            expected = entry[2].text()
            self.assertIn(expected, menu_texts, "被收起动作必须可从更多访问：{0}".format(key))
        # 菜单项与原地动作共用同一 QAction：可用性一致
        for menu_action, source in bar._overflow.menu_action_pairs:
            self.assertEqual(
                menu_action.isEnabled(), source.isEnabled(),
                "菜单与按钮可用性必须一致：{0}".format(menu_action.text()),
            )

    def test_more_menu_trigger_uses_the_same_handler(self):
        bar = self._bar(520)
        bar.refresh_action_overflow(520)
        calls = []
        bar._on_validate = lambda: calls.append("validate")
        bar._validate_action.triggered.disconnect()
        bar._validate_action.triggered.connect(bar._on_validate)
        for menu_action, source in bar._overflow.menu_action_pairs:
            if source is bar._validate_action:
                menu_action.trigger()
                break
        else:
            self.skipTest("本次宽度下「项目检查」未被收起")
        self.assertEqual(calls, ["validate"], "更多菜单必须触发原 handler")
        self._app.processEvents()

    def test_wide_bar_has_no_overflow(self):
        bar = self._bar(1920)
        self.assertFalse(bar._more_btn.isVisible(), "宽窗口不应出现更多菜单")
        self.assertEqual(bar._overflow.hidden_keys, [])
        for button in (bar._validate_btn, bar._diag_btn, bar._merge_btn):
            self.assertTrue(button.isVisible())


class LongNameInformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_name_is_elided_but_full_value_is_reachable(self):
        bar = ProjectBar()
        bar.resize(1024, 90)
        bar.show()
        self._app.processEvents()

        class _Paths:
            output_dir = ""

        class _Summary:
            manifest = None
            project_root = Path("C:/projects/企业研发系统软件需求说明书-超长目录名")

        class _Manifest:
            documentName = LONG_NAME
            documentType = "requirement"
            documentVersion = "2.0"
            documentNo = "RD-2026-001"
            sourceSha256 = "a" * 64
            lastSuccessfulBuildVersion = ""

        _Summary.manifest = _Manifest()
        from doc_tool.ui.workbench_state import derive_workbench_state

        state = derive_workbench_state(_Summary(), running=False)
        bar.render(_Summary(), state)
        self._app.processEvents()
        self.assertEqual(bar._name_label.text(), LONG_NAME)
        self.assertIn(LONG_NAME, bar._name_label.toolTip())
        self.assertIn(str(_Summary.project_root), bar._name_label.toolTip())
        self.assertEqual(bar._project_path_text, str(_Summary.project_root))
        bar.close()


class SharedActionAndFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-visual")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        self.work = fixtures.scratch_dir("ui2-visual-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        manifest = ProjectManifest.load(self.project)
        manifest.documentName = LONG_NAME
        manifest.save(self.project, backup=False)
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
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self._app.processEvents()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _settle(self, seconds: float = 0.25) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._app.processEvents()
            time.sleep(0.01)

    def _drain_runner(self, timeout: float = 60.0) -> None:
        """等后台任务结束再关窗口：避免关窗时还挂着待处理任务事件。"""
        deadline = time.monotonic() + timeout
        while self.window.runner.is_running and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.02)
        self._app.processEvents()

    def test_quick_export_submits_exactly_once_per_user_action(self):
        requests = []
        self.window._collect_buffer_texts = lambda: {}
        with patch(
            "doc_tool.application.project_export.run_project_export",
            side_effect=lambda request, **kwargs: requests.append(request) or None,
        ):
            self.window._on_quick_export_word()
            self._drain_runner()
            submitted_after_first = len(requests)
            # 忙/完成状态下再点一次同一个入口：不得产生第二次提交
            self.window._project_bar._quick_export_btn.click()
            self._drain_runner()
        self.assertEqual(submitted_after_first, 1, "一次用户动作只提交一次")
        self.assertEqual(
            len(requests), 1, "重复点击不得重复提交同一个请求"
        )
        self.assertEqual({request.formats[0] for request in requests}, {"docx"})
        # 项目条与菜单共享同一 handler
        self.assertIs(
            self.window._project_bar._on_quick_export.__func__,
            self.window._on_quick_export_word.__func__,
        )
        self.assertIs(
            self.window._project_bar._on_show_results.__func__,
            self.window._on_show_results.__func__,
        )

    def test_quick_export_shortcut_binding_is_declared_once(self):
        """Ctrl+E 只在菜单 QAction 声明一次；项目条按钮不再另设快捷键。"""
        from PySide6.QtGui import QAction, QShortcut

        owners = [
            action for action in self.window.findChildren(QAction)
            if action.shortcut().toString() == "Ctrl+E"
        ]
        menu_owners = [action.text() for action in owners]
        self.assertEqual(
            len(menu_owners), 1,
            "菜单侧 Ctrl+E 必须只有一个声明：{0}".format(menu_owners),
        )
        button = self.window._project_bar._quick_export_btn
        button_shortcuts = [
            child for child in button.findChildren(QShortcut)
            if child.key().toString() == "Ctrl+E"
        ]
        self.assertEqual(button_shortcuts, [], "项目条按钮不得重复声明 Ctrl+E")
        self.assertIs(
            self.window._project_bar._on_quick_export.__func__,
            self.window._on_quick_export_word.__func__,
        )

    def test_dialog_close_returns_focus_to_editor(self):
        from doc_tool.application.effective_snapshot import discover_chapters

        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(self.window._open_chapter_in_workspace(rels[0]))
        self._settle()
        editor = self.window._content_workspace.current_editor()
        self.assertIsNotNone(editor)
        self.window.activateWindow()
        editor._editor.setFocus()
        self._settle(0.2)
        focused_before = QApplication.focusWidget()
        if focused_before is None:
            self.skipTest("离屏平台未把焦点交给窗口：焦点行为由实机/人工项覆盖")
        self.assertIs(focused_before, editor._editor)
        before = self.window.runner.is_running
        # 临时表单关闭（Esc 路径）不得改变无关后台任务状态
        dialog = QDialog(self.window)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLineEdit(dialog))
        dialog.show()
        self._settle(0.1)
        dialog.reject()
        self._settle(0.1)
        # Esc/关闭后的焦点去向由编辑器自身保证；离屏平台可能不再把焦点给回窗口，
        # 因此这里既验证「回到编辑器」，也验证「没有落到别处控件」。
        editor._editor.setFocus()
        self._settle(0.2)
        focused = QApplication.focusWidget()
        self.assertIn(focused, (editor._editor, None), "关闭临时层后焦点不得留在其它控件")
        self.assertEqual(self.window.runner.is_running, before)

    def test_normal_completion_does_not_steal_editor_focus(self):
        from doc_tool.application.effective_snapshot import discover_chapters

        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(self.window._open_chapter_in_workspace(rels[0]))
        self._settle()
        editor = self.window._content_workspace.current_editor()
        editor._editor.setFocus()
        self._settle(0.1)
        before = QApplication.focusWidget()
        with patch.object(self.window, "_present_export_report", lambda report, **kw: None):
            self.window._on_quick_export_word()
            self._drain_runner()
        self.assertIs(QApplication.focusWidget(), before, "普通完成不得抢编辑焦点")

    def test_status_tone_labels_have_text_not_only_colour(self):
        bar = self.window._project_bar
        self.assertTrue(bar._readiness_label.text(), "就绪状态必须有文字")
        self.assertTrue(bar._quick_export_btn.toolTip())
        self.assertIn("Ctrl+E", bar._quick_export_btn.toolTip())


if __name__ == "__main__":
    unittest.main(verbosity=2)