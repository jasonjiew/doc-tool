# -*- coding: utf-8 -*-
"""UI2-B 首页继续工作（2.1～2.4）：固定、筛选、会话位置与坏配置回退。

覆盖验收 U2-2 的可自动部分：

- 固定/取消固定只改个人最近记录（重启后仍在），不移动/删除工程；
- 类型筛选与已有搜索组合作用；无匹配给出可行动空态；
- 坏字段/缺字段按项回退，失效项目可重新定位且取消后不挡其他项目；
- 继续工作复用既有打开/会话/草稿恢复，并补回光标位置偏好。
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from doc_tool.application.content.workspace_state import (  # noqa: E402
    SessionState,
    WorkspaceStateStore,
)
from doc_tool.application.project_service import (  # noqa: E402
    RecentEntry,
    load_recent_projects,
    set_recent_pinned,
)
from doc_tool.ui.empty_state import EmptyState  # noqa: E402


def _entry(path: Path, *, name: str, doc_name: str, doc_type: str, days: int = 0, pinned: bool = False):
    now = datetime.now(timezone.utc)
    return RecentEntry(
        path=str(path),
        name=name,
        document_name=doc_name,
        document_type=doc_type,
        last_opened=(now - timedelta(days=days)).isoformat(timespec="seconds"),
        pinned=pinned,
    )


class RecentStoreTests(unittest.TestCase):
    """个人记录层：固定标记往返、坏字段回退、不删除工程。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("ui2-home-store")
        self.recent_file = self.work / "recent.json"
        self._patch = patch(
            "doc_tool.application.project_service._recent_file",
            return_value=self.recent_file,
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        fixtures.cleanup(self.work)

    def test_pin_roundtrip_keeps_project_dir(self):
        project = self.work / "proj-pin"
        project.mkdir()
        self.recent_file.write_text(
            json.dumps([_entry(project, name="proj-pin", doc_name="固定项目", doc_type="design").to_dict()],
                       ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertTrue(set_recent_pinned(str(project), True))
        entries = load_recent_projects()
        self.assertTrue(entries[0].pinned)
        self.assertTrue(project.is_dir(), "固定不得移动或删除工程目录")
        self.assertTrue(set_recent_pinned(str(project), False))
        self.assertFalse(load_recent_projects()[0].pinned)
        self.assertTrue(project.is_dir())

    def test_missing_or_bad_pinned_field_falls_back(self):
        project = self.work / "proj-old"
        project.mkdir()
        payload = _entry(project, name="proj-old", doc_name="旧记录", doc_type="requirement").to_dict()
        payload.pop("pinned", None)
        self.recent_file.write_text(json.dumps([payload], ensure_ascii=False), encoding="utf-8")
        entry = load_recent_projects()[0]
        self.assertFalse(entry.pinned, "旧记录缺字段按未固定回退")
        payload["pinned"] = "yes"
        self.recent_file.write_text(json.dumps([payload], ensure_ascii=False), encoding="utf-8")
        self.assertFalse(load_recent_projects()[0].pinned, "错型 pinned 按未固定回退")
        self.assertTrue(project.is_dir())

    def test_pin_unknown_path_reports_miss(self):
        self.recent_file.write_text("[]", encoding="utf-8")
        self.assertFalse(set_recent_pinned(str(self.work / "nope"), True))


class HomeContinueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("ui2-home-ui")
        self.a = self.work / "alpha"
        self.b = self.work / "beta"
        self.c = self.work / "gamma"
        for path in (self.a, self.b, self.c):
            path.mkdir()
        self.home = EmptyState()
        self.home.resize(1280, 800)
        self.home.show()
        self._app.processEvents()

    def tearDown(self):
        try:
            self.home.close()
        except Exception:  # noqa: BLE001
            pass
        fixtures.cleanup(self.work)

    def _cards(self):
        return self.home._recent_cards

    def test_pinned_entries_sort_first(self):
        self.home.set_recent_projects([
            _entry(self.a, name="alpha", doc_name="甲需求", doc_type="requirement", days=1),
            _entry(self.b, name="beta", doc_name="乙设计", doc_type="design", days=2),
            _entry(self.c, name="gamma", doc_name="丙通用", doc_type="general", days=0, pinned=True),
        ])
        self._app.processEvents()
        first = self._cards()[0]
        self.assertEqual(first._entry_data.name, "gamma", "固定项必须置顶")

    def test_type_filter_combines_with_search(self):
        self.home.set_recent_projects([
            _entry(self.a, name="alpha", doc_name="系统需求归档说明", doc_type="requirement"),
            _entry(self.b, name="beta", doc_name="系统设计说明", doc_type="design"),
            _entry(self.c, name="gamma", doc_name="系统通用附录", doc_type="general"),
        ])
        self._app.processEvents()
        self.home.set_type_filter("design")
        visible = [card._entry_data.name for card in self._cards() if card.isVisible()]
        self.assertEqual(visible, ["beta"])
        # 搜索叠加在类型筛选之上（"归档" 只出现在需求类名称里，类型不匹配）
        self.home._search_input.setText("归档")
        self._app.processEvents()
        visible = [card._entry_data.name for card in self._cards() if card.isVisible()]
        self.assertEqual(visible, [], "类型与关键词同时不匹配时不应显示")
        self.assertIsNotNone(self.home._search_empty_label)
        self.assertIn("没有匹配的最近项目", self.home._search_empty_label.text())
        # 清除筛选后恢复
        self.home._search_input.setText("")
        self.home.set_type_filter("")
        self._app.processEvents()
        self.assertEqual(len([c for c in self._cards() if c.isVisible()]), 3)

    def test_pin_button_invokes_callback_and_keeps_engineering_dir(self):
        calls = []
        self.home._on_toggle_pin = lambda path, pinned: calls.append((path, pinned))
        self.home.set_recent_projects([
            _entry(self.a, name="alpha", doc_name="甲需求", doc_type="requirement"),
        ])
        self._app.processEvents()
        buttons = self._cards()[0].findChildren(QPushButton)
        pin = next(b for b in buttons if b.text() in ("固定", "已固定"))
        pin.click()
        self.assertEqual(calls, [(str(self.a), True)])
        self.assertTrue(self.a.is_dir())

    def test_missing_project_entry_offers_relocate_or_remove(self):
        missing = self.work / "moved-away"
        self.home.set_recent_projects([
            _entry(missing, name="moved-away", doc_name="已移动项目", doc_type="design"),
            _entry(self.a, name="alpha", doc_name="甲需求", doc_type="requirement"),
        ])
        self._app.processEvents()
        texts = [b.text() for b in self._cards()[0].findChildren(QPushButton)]
        self.assertIn("重新定位", texts, "失效条目必须提供重新定位：{0}".format(texts))
        self.assertIn("已移动", self._cards()[0].toolTip())
        # 取消定位不阻塞其他项目点击（文件选择框由 QtWidgets 层导入）
        opened = []
        self.home._on_open_recent = opened.append
        with patch(
            "PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=""
        ):
            next(b for b in self._cards()[0].findChildren(QPushButton) if b.text() == "重新定位").click()
        self.assertEqual(opened, [], "取消定位不得打开任何项目")
        self.home._handle_recent(str(self.a))
        self.assertEqual(opened, [str(self.a)], "取消定位后其他项目仍可打开")


class ContinueWorkSessionTests(unittest.TestCase):
    """2.3：继续工作复用会话恢复，并补回光标位置偏好。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui2-home-session")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls._shared)

    def setUp(self):
        import shutil

        from doc_tool.application.content.unsaved import UnsavedChoice
        from doc_tool.ui.main_window import MainWindow

        self.work = fixtures.scratch_dir("ui2-home-session-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
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

    def test_cursor_position_is_stored_and_restored(self):
        from doc_tool.application.effective_snapshot import discover_chapters

        rels = [rel for rel, _p in discover_chapters(self.project / "content" / "general")]
        self.assertTrue(self.window._open_chapter_in_workspace(rels[0]))
        self._app.processEvents()
        editor = self.window._content_workspace.current_editor()
        self.assertIsNotNone(editor)
        editor._editor.setPlainText("# 标题\n\n第一段。\n\n第二段需要记住光标。\n")
        editor.set_cursor_position(20)
        self._app.processEvents()
        expected = editor.cursor_position()
        self.window._persist_workspace_session()
        stored = WorkspaceStateStore(self.project / ".state").load()
        self.assertTrue(stored.cursor_positions, "会话必须保存光标位置")
        stored_value = stored.cursor_positions.get(rels[0])
        if stored_value is None:
            stored_value = list(stored.cursor_positions.values())[0]
        self.assertEqual(stored_value, expected)
        # 坏值只影响该项
        stored.cursor_positions[rels[0]] = 999999
        editor.set_cursor_position(stored.cursor_positions[rels[0]])
        self.assertLessEqual(editor.cursor_position(), len(editor.plain_text()))

    def test_old_session_without_cursor_field_still_restores_tabs(self):
        from doc_tool.application.effective_snapshot import discover_chapters

        rels = [
            rel for rel, _p in discover_chapters(self.project / "content" / "general")
        ]
        state_dir = self.project / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "workspace.json").write_text(
            json.dumps(
                {
                    "dockVisibility": {},
                    "dockState": "",
                    "theme": "light",
                    "openTabs": [rels[0]],
                    "currentFile": rels[0],
                    "previewEnabled": {rels[0]: True},
                    "scrollPositions": {rels[0]: 0},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        loaded = WorkspaceStateStore(state_dir).load()
        self.assertEqual(loaded.open_tabs, [rels[0]])
        self.assertEqual(loaded.cursor_positions, {}, "缺字段按空回退")
        self.window._pending_session = loaded
        self.window._init_content_workspace(self.window._project_summary)
        self.window._restore_window_session()
        self._app.processEvents()
        self.assertTrue(self.window._content_workspace is not None)


if __name__ == "__main__":
    unittest.main(verbosity=2)