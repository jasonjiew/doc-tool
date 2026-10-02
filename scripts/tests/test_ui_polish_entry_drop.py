# -*- coding: utf-8 -*-
"""UI 包 1.1：首页主区拖放与导入按钮共用同一建项路由。

真实 Qt 控件 + 真实拖放事件（``QDropEvent``）验证落点语义：
- 左侧「项目出稿」区拖入 => ``on_drop_intake``（与「新建项目…」同一 handler）；
- 互转卡拖入 => ``on_drop_convert``（文档互转语义保留）；
- 事件没有坐标（旧桩事件）时退回互转语义，不改变既有调用方行为。

来源保护断言：失败/不支持来源仍走原 warn/原路由，源文件与缓冲不被改写。
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
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.ui.empty_state import (  # noqa: E402
    DROP_ZONE_CONVERT,
    DROP_ZONE_INTAKE,
    EmptyState,
)
from doc_tool.ui.main_window import MainWindow  # noqa: E402


def _drop_event(mime: QMimeData, local_point: QPointF) -> QDropEvent:
    return QDropEvent(
        local_point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class _PositionlessEvent:
    """无坐标的旧式桩事件：判定必须安全退回互转语义。"""

    def __init__(self, mime: QMimeData) -> None:
        self.accepted = False
        self._mime = mime

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:
        self.accepted = True


class HomeDropRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _home(self, **callbacks) -> EmptyState:
        home = EmptyState(**callbacks)
        home.resize(1200, 800)
        home.show()
        self._app.processEvents()
        self.addCleanup(home.close)
        self.addCleanup(lambda: (home.deleteLater(), self._app.processEvents()))
        return home

    @staticmethod
    def _mime(name: str = "dropped.docx") -> QMimeData:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(Path("C:/x") / name))])
        return mime

    def _centre_point(self, home: EmptyState, widget) -> QPointF:
        centre_global = widget.mapToGlobal(widget.rect().center())
        return QPointF(home.mapFromGlobal(centre_global))

    def test_intake_area_drop_uses_intake_route(self):
        seen = {"intake": [], "convert": []}
        home = self._home(
            on_drop_intake=lambda paths: seen["intake"].append(list(paths)),
            on_drop_convert=lambda paths: seen["convert"].append(list(paths)),
        )
        # mime 必须绑定到局部变量：Qt 不持有 Python 侧 QMimeData 的强引用，
        # 临时对象被回收后事件的 mimeData() 会退化为裸 QObject。
        mime = self._mime()
        event = _drop_event(mime, self._centre_point(home, home._intake_card))
        self.assertEqual(home.drop_zone_for(event), DROP_ZONE_INTAKE)
        home.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual([[p.name for p in group] for group in seen["intake"]], [["dropped.docx"]])
        self.assertEqual(seen["convert"], [])

    def test_convert_card_drop_uses_convert_route(self):
        seen = {"intake": [], "convert": []}
        home = self._home(
            on_drop_intake=lambda paths: seen["intake"].append(list(paths)),
            on_drop_convert=lambda paths: seen["convert"].append(list(paths)),
        )
        mime = self._mime()
        event = _drop_event(mime, self._centre_point(home, home._convert_card))
        self.assertEqual(home.drop_zone_for(event), DROP_ZONE_CONVERT)
        home.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual([[p.name for p in group] for group in seen["convert"]], [["dropped.docx"]])
        self.assertEqual(seen["intake"], [])

    def test_positionless_event_keeps_legacy_convert_route(self):
        seen = {"intake": [], "convert": []}
        home = self._home(
            on_drop_intake=lambda paths: seen["intake"].append(list(paths)),
            on_drop_convert=lambda paths: seen["convert"].append(list(paths)),
        )
        mime = self._mime()
        event = _PositionlessEvent(mime)
        self.assertEqual(home.drop_zone_for(event), DROP_ZONE_CONVERT)
        home.dropEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(len(seen["convert"]), 1)
        self.assertEqual(seen["intake"], [])

    def test_drop_without_urls_is_ignored(self):
        seen = []
        home = self._home(
            on_drop_intake=lambda paths: seen.append(list(paths)),
            on_drop_convert=lambda paths: seen.append(list(paths)),
        )
        empty = QMimeData()
        event = _drop_event(empty, self._centre_point(home, home._intake_card))
        home.dropEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(seen, [])

    def test_intake_route_and_import_button_share_one_handler(self):
        """主区拖放接线必须就是「新建项目…」按钮使用的同一 handler。"""
        window = MainWindow()
        self.addCleanup(window.close)
        home = window._empty_state
        # 绑定方法每次访问都是新对象，比较底层函数与宿主对象。
        self.assertIs(home._on_drop_intake.__func__, window._on_import_document.__func__)
        self.assertIs(home._on_drop_intake.__self__, window)
        self.assertIs(home._on_new_project.__func__, window._on_import_document.__func__)
        self.assertIs(home._on_drop_convert.__func__, window._on_convert_documents.__func__)


class MainWindowIntakeDropTests(unittest.TestCase):
    """真实 MainWindow：主区拖入 DOCX/Markdown 走既有建项服务。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-drop")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        self._patches = [
            patch("doc_tool.application.project_service.load_recent_projects", return_value=[]),
            patch("doc_tool.application.project_service.add_recent_project", return_value=None),
            patch("doc_tool.ui.main_window.QMessageBox.information", side_effect=lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.warning", side_effect=lambda *a, **k: None),
            # 离屏下任何模态收尾框都会永久阻塞：统一替换 exec。
            patch.object(QMessageBox, "exec", lambda self: None),
            patch.object(QMessageBox, "warning", lambda *a, **k: None),
        ]
        for item in self._patches:
            item.start()
        self.window = MainWindow()
        self.window.resize(1280, 720)
        self.window.show()
        self._app.processEvents()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _opened(self):
        opened = {"path": [], "window": [], "convert": []}
        self.window._open_project_path = lambda path: opened["path"].append(path)
        self.window._open_project_in_new_window = lambda path: opened["window"].append(path)
        self.window._on_convert_documents = (
            lambda paths=None, *a, **k: opened["convert"].append(paths)
        )
        home = self.window._empty_state
        # EmptyState 用 ``__init__`` 时传入的绑定方法，后续改窗口属性不会再影响
        # 已接线控件；这里同步替换两个拖放回调，保证路由记录真实生效。
        home._on_drop_intake = self.window._on_import_document
        home._on_drop_convert = self.window._on_convert_documents
        return opened

    def _drop_on(self, widget, paths):
        home = self.window._empty_state
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        centre = QPointF(home.mapFromGlobal(widget.mapToGlobal(widget.rect().center())))
        event = _drop_event(mime, centre)
        home.dropEvent(event)
        self._app.processEvents()
        return event

    def test_main_area_drop_of_markdown_builds_one_project(self):
        first = self.work / "1 概述.md"
        first.write_text("# 概述\n\n正文。\n", encoding="utf-8")
        second = self.work / "2 设计.md"
        second.write_text("# 设计\n\n正文。\n", encoding="utf-8")
        opened = self._opened()
        home = self.window._empty_state
        with patch(
            "doc_tool.application.intake_entries.default_project_parent",
            return_value=self.out,
        ):
            event = self._drop_on(home._intake_card, [first, second])
        self.assertEqual(home.drop_zone_for(event), DROP_ZONE_INTAKE)
        self.assertEqual(opened["convert"], [], "主区拖放不得进入互转")
        self.assertEqual(len(opened["path"]), 1, opened)
        project = Path(opened["path"][0])
        self.assertTrue((project / "project.yml").is_file())
        manifest_text = (project / "project.yml").read_text(encoding="utf-8")
        self.assertLess(manifest_text.index("1 概述.md"), manifest_text.index("2 设计.md"))

    def test_main_area_drop_of_docx_opens_import_wizard_once(self):
        docx = fixtures.standard_docx(self.work / "标准.docx")
        opened = self._opened()
        seen = {}

        class _FakeWizard:
            def __init__(self, parent=None, initial_file=None):
                seen["initial_file"] = initial_file

            def run(self):
                seen["ran"] = True
                return None

        home = self.window._empty_state
        with patch("doc_tool.ui.wizard.ImportWizard", _FakeWizard):
            event = self._drop_on(home._intake_card, [docx])
        self.assertEqual(home.drop_zone_for(event), DROP_ZONE_INTAKE)
        self.assertEqual(opened["convert"], [], "主区拖放不得进入互转")
        self.assertEqual(seen.get("initial_file"), str(docx))
        self.assertTrue(seen.get("ran"))

    def test_convert_card_drop_of_docx_enters_convert(self):
        docx = self.work / "外部.docx"
        docx.write_bytes(b"PK")
        opened = self._opened()
        home = self.window._empty_state
        event = self._drop_on(home._convert_card, [docx])
        self.assertEqual(home.drop_zone_for(event), DROP_ZONE_CONVERT)
        self.assertEqual(opened["convert"], [[docx]])
        self.assertEqual(opened["path"], [])

    def test_unsupported_source_on_intake_keeps_file_untouched(self):
        bogus = self.work / "x.zip"
        bogus.write_bytes(b"PK")
        before = bogus.read_bytes()
        warned = []
        home = self.window._empty_state
        with patch(
            "doc_tool.ui.main_window.QMessageBox.warning",
            side_effect=lambda *a, **k: warned.append(a),
        ):
            self._drop_on(home._intake_card, [bogus])
        self.assertEqual(len(warned), 1)
        self.assertEqual(bogus.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class IntakeCommandGroupTests(unittest.TestCase):
    """UI 包 1.4：重复命令分组合并为单一可发现入口，且真实可用性一致。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-commands")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        self._patches = [
            patch("doc_tool.application.project_service.load_recent_projects", return_value=[]),
            patch("doc_tool.application.project_service.add_recent_project", return_value=None),
            patch.object(QMessageBox, "exec", lambda self: None),
            patch.object(QMessageBox, "warning", lambda *a, **k: None),
            patch.object(QMessageBox, "information", lambda *a, **k: None),
        ]
        for item in self._patches:
            item.start()
        self.window = MainWindow()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _file_menu_labels(self):
        menu = None
        for action in self.window.menuBar().actions():
            try:
                if action.text() == "文件":
                    menu = action.menu()
                    break
            except RuntimeError:  # noqa: PERF203 - 菜单项被回收时跳过
                continue
        self.assertIsNotNone(menu)
        labels = []
        for action in menu.actions():
            try:
                if action.isSeparator():
                    continue
                labels.append(action.text())
            except RuntimeError:  # noqa: PERF203 - 已删除的 Python 包装对象
                continue
        return labels

    def test_file_menu_has_one_intake_entry(self):
        labels = self._file_menu_labels()
        self.assertIn(self.window._import_action.text(), labels)
        self.assertEqual(self.window._import_action.shortcut().toString(), "Ctrl+N")
        # 旧「新建项目（导入向导）」重复入口已合并，不再单独出现。
        self.assertNotIn("新建项目（导入向导）…", labels)
        self.assertEqual(
            [label for label in labels if "导入" in label],
            [self.window._import_action.text()],
            "导入类入口只保留一个：{0}".format(labels),
        )

    def test_palette_import_entry_uses_the_same_handler(self):
        seen = []
        self.window._on_import_document = lambda paths=None: seen.append(paths)
        captured = {}
        from doc_tool.ui.command_palette import CommandPaletteDialog

        def _capture(self):
            captured["dialog"] = self

        with patch.object(
            self.window, "_registry_palette_items", return_value=[]
        ), patch.object(CommandPaletteDialog, "exec", _capture):
            self.window.open_command_palette()
        dialog = captured.get("dialog")
        self.assertIsNotNone(dialog, "命令面板应已创建")
        titles = [item.title for item in dialog._all_items]
        self.assertIn("导入 / 新建项目（Word / Markdown）…", titles)
        self.assertNotIn("接管现有 Word 建项…", titles, "重复的接管 Word 入口应已合并")
        target = [item for item in dialog._all_items if item.title.startswith("导入 / 新建项目")][0]
        target.callback()
        self.assertEqual(seen, [None])
        dialog.close()

    def test_mixed_sources_route_by_real_kind_without_touching_files(self):
        docx = fixtures.standard_docx(self.work / "标准.docx")
        markdown = self.work / "01 概述.md"
        markdown.write_text("# 概述\n\n正文。\n", encoding="utf-8")
        bogus = self.work / "x.zip"
        bogus.write_bytes(b"PK")
        before = {p: p.read_bytes() for p in (docx, markdown, bogus)}

        opened = []
        self.window._open_project_path = lambda path: opened.append(path)
        self.window._open_project_in_new_window = lambda path: None
        seen = {}

        class _FakeWizard:
            def __init__(self, parent=None, initial_file=None):
                seen["docx"] = initial_file

            def run(self):
                return None

        warnings = []
        with patch("doc_tool.ui.wizard.ImportWizard", _FakeWizard), patch(
            "doc_tool.application.intake_entries.default_project_parent",
            return_value=self.out,
        ), patch(
            "doc_tool.ui.main_window.QMessageBox.warning",
            side_effect=lambda *a, **k: warnings.append(a),
        ):
            self.window._on_import_document([docx, markdown, bogus])

        self.assertEqual(len(opened), 1, "Markdown 应组成一份项目并打开")
        self.assertTrue((Path(opened[0]) / "project.yml").is_file())
        self.assertEqual(seen.get("docx"), str(docx), "DOCX 逐份进入导入向导")
        self.assertEqual(len(warnings), 1, "不支持格式只警告一次且不进入任何服务")
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, "入口调整不得改写源文件：{0}".format(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)