# -*- coding: utf-8 -*-
"""工作台安全与恢复（计划 1）自动测试。

覆盖 tasks 组 1/6：
- 1.5 AutoSaveStore 读写/覆盖/清除/越界拒绝、collect_unsaved 只收脏标签、
      决策函数三态映射、SessionState 序列化/缺省/损坏回退
- 6.1 离屏（决策注入）：退出三选、切项目三选、删除放弃/取消、重命名先保存/放弃/取消
- 6.2 草稿生命周期：编辑去抖写入、保存后清除、只读不写、草稿不影响索引
- 6.3 崩溃恢复：预置草稿→打开项目提示恢复/忽略，恢复后为脏状态且正式文件未变
- 6.4 会话恢复：写入会话→重开→标签/当前文件/滚动/预览恢复；缺失文件跳过；损坏 JSON 回退
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VENDOR = Path(REPO_ROOT) / ".vendor" / "site-packages"


def _ensure_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_project(files: dict) -> Path:
    """构建 project_root/content/... 假项目，返回 content_root。"""
    project_root = Path(tempfile.mkdtemp(prefix="doc-tool-safety-"))
    content_root = project_root / "content"
    for rel, text in files.items():
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return content_root


def _drafts_dir(state_dir) -> Path:
    from doc_tool.application.content.autosave import AUTOSAVE_DIR_NAME

    return Path(state_dir) / AUTOSAVE_DIR_NAME


# --- 1.5 纯逻辑 ---


class AutoSaveStoreTests(unittest.TestCase):
    """AutoSaveStore 读写/覆盖/清除/越界拒绝。"""

    def setUp(self):
        self.project_root = Path(tempfile.mkdtemp(prefix="doc-tool-draft-"))
        self.state_dir = self.project_root / ".state"
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)

    def _store(self):
        from doc_tool.application.content.autosave import AutoSaveStore

        return AutoSaveStore(self.state_dir)

    def test_write_read_roundtrip(self):
        store = self._store()
        store.write("requirement/第1章/1.1 目的.md", "草稿内容\n")
        self.assertEqual(
            store.read("requirement/第1章/1.1 目的.md"), "草稿内容\n"
        )
        self.assertTrue(store.has("requirement/第1章/1.1 目的.md"))

    def test_write_creates_mirror_path(self):
        store = self._store()
        store.write("a/b/c.md", "x")
        draft = _drafts_dir(self.state_dir) / "a" / "b" / "c.md"
        self.assertEqual(draft.read_text(encoding="utf-8"), "x")

    def test_overwrite_keeps_only_latest(self):
        store = self._store()
        store.write("f.md", "第一版")
        store.write("f.md", "第二版")
        self.assertEqual(store.read("f.md"), "第二版")
        self.assertEqual(store.list_drafts(), ["f.md"])

    def test_clear_removes_single(self):
        store = self._store()
        store.write("a.md", "1")
        store.write("b.md", "2")
        store.clear("a.md")
        self.assertEqual(store.list_drafts(), ["b.md"])
        self.assertIsNone(store.read("a.md"))

    def test_clear_all_empties(self):
        store = self._store()
        store.write("a.md", "1")
        store.write("b/c.md", "2")
        store.clear_all()
        self.assertEqual(store.list_drafts(), [])

    def test_clear_missing_is_silent(self):
        store = self._store()
        store.clear("不存在.md")  # 不应抛异常
        self.assertEqual(store.list_drafts(), [])

    def test_list_drafts_sorted(self):
        store = self._store()
        store.write("b.md", "1")
        store.write("a.md", "2")
        self.assertEqual(store.list_drafts(), ["a.md", "b.md"])

    def test_escape_path_write_rejected(self):
        from doc_tool.application.content.writer import PathOutsideContentError

        store = self._store()
        with self.assertRaises(PathOutsideContentError):
            store.write("../../evil.md", "x")
        # 越界草稿未被写入
        self.assertFalse((self.state_dir / ".." / "evil.md").exists())

    def test_escape_path_read_and_clear_safe(self):
        store = self._store()
        self.assertIsNone(store.read("../../evil.md"))
        store.clear("../../evil.md")  # 不抛异常、无副作用


class CollectUnsavedTests(unittest.TestCase):
    """collect_unsaved 只收脏标签。"""

    def _editor(self, rel_path, dirty):
        class _Editor:
            pass

        ed = _Editor()
        ed._rel = rel_path
        ed._dirty = dirty
        ed.current_rel_path = lambda: ed._rel
        ed.is_dirty = lambda: ed._dirty
        return ed

    def test_only_dirty_collected(self):
        from doc_tool.application.content.unsaved import collect_unsaved

        editors = [
            self._editor("a.md", True),
            self._editor("b.md", False),
            self._editor("c.md", True),
        ]
        self.assertEqual(collect_unsaved(editors), ["a.md", "c.md"])

    def test_no_dirty_returns_empty(self):
        from doc_tool.application.content.unsaved import collect_unsaved

        editors = [self._editor("a.md", False)]
        self.assertEqual(collect_unsaved(editors), [])

    def test_none_rel_path_skipped(self):
        from doc_tool.application.content.unsaved import collect_unsaved

        editors = [self._editor(None, True)]
        self.assertEqual(collect_unsaved(editors), [])


class UnsavedDecisionTests(unittest.TestCase):
    """决策函数（可注入）三态映射。"""

    def test_choice_values_stable(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        self.assertEqual(UnsavedChoice.SAVE, "save")
        self.assertEqual(UnsavedChoice.DISCARD, "discard")
        self.assertEqual(UnsavedChoice.CANCEL, "cancel")

    def test_resolver_injectable(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        calls = []
        resolver = lambda rels, ctx: (calls.append((rels, ctx)) or UnsavedChoice.SAVE)
        self.assertEqual(resolver(["a.md"], "exit"), UnsavedChoice.SAVE)
        self.assertEqual(calls, [(["a.md"], "exit")])


class SessionStateTests(unittest.TestCase):
    """SessionState 序列化/缺省/损坏回退/empty。"""

    def test_roundtrip_preserves_all_fields(self):
        from doc_tool.application.content.workspace_state import SessionState

        session = SessionState(
            dock_visibility={"treeDock": True, "panelsDock": False},
            dock_state="base64state",
            theme="dark",
            open_tabs=["a.md", "b.md"],
            current_file="b.md",
            preview_enabled={"a.md": True, "b.md": False},
            scroll_positions={"a.md": 42, "b.md": 7},
        )
        restored = SessionState.from_dict(session.to_dict())
        self.assertEqual(restored, session)

    def test_defaults_on_missing_fields(self):
        from doc_tool.application.content.workspace_state import SessionState

        restored = SessionState.from_dict({"openTabs": ["a.md"]})
        self.assertEqual(restored.open_tabs, ["a.md"])
        self.assertIsNone(restored.current_file)
        self.assertEqual(restored.theme, "light")
        self.assertEqual(restored.dock_visibility, {})

    def test_non_dict_falls_back_to_default(self):
        from doc_tool.application.content.workspace_state import SessionState

        self.assertEqual(SessionState.from_dict(None), SessionState())
        self.assertEqual(SessionState.from_dict("junk"), SessionState())

    def test_wrong_types_are_sanitized(self):
        from doc_tool.application.content.workspace_state import SessionState

        restored = SessionState.from_dict(
            {
                "openTabs": ["a.md", 3, None],
                "currentFile": 42,
                "scrollPositions": {"a.md": "x", "b.md": 7},
                "previewEnabled": {"a.md": "yes", "b.md": True},
            }
        )
        self.assertEqual(restored.open_tabs, ["a.md"])
        self.assertIsNone(restored.current_file)
        self.assertEqual(restored.scroll_positions, {"b.md": 7})
        self.assertEqual(restored.preview_enabled, {"b.md": True})

    def test_empty_when_no_tabs(self):
        from doc_tool.application.content.workspace_state import SessionState

        self.assertTrue(SessionState().empty)
        self.assertFalse(
            SessionState(open_tabs=["a.md"]).empty
        )
        self.assertFalse(SessionState(current_file="a.md").empty)

    def test_theme_or_dock_layout_alone_keeps_session_non_empty(self):
        # 用户自定义的主题/Dock 显隐/排列是持久化状态：即使没有任何打开标签，
        # 保存时也不能被当空会话丢弃（否则切到深色主题再关标签就永久丢失）。
        from doc_tool.application.content.workspace_state import SessionState

        self.assertFalse(SessionState(theme="dark").empty)
        self.assertFalse(SessionState(dock_visibility={"treeDock": False}).empty)
        self.assertFalse(SessionState(dock_state="base64").empty)


class WorkspaceStateStoreTests(unittest.TestCase):
    """WorkspaceStateStore 原子读写/缺省/损坏回退/无空文件。"""

    def setUp(self):
        self.project_root = Path(tempfile.mkdtemp(prefix="doc-tool-session-"))
        self.state_dir = self.project_root / ".state"
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)

    def _store(self):
        from doc_tool.application.content.workspace_state import WorkspaceStateStore

        return WorkspaceStateStore(self.state_dir)

    def test_save_load_roundtrip(self):
        from doc_tool.application.content.workspace_state import SessionState

        store = self._store()
        store.save(
            SessionState(
                theme="dark",
                open_tabs=["a.md"],
                current_file="a.md",
                scroll_positions={"a.md": 12},
            )
        )
        loaded = store.load()
        self.assertEqual(loaded.theme, "dark")
        self.assertEqual(loaded.open_tabs, ["a.md"])
        self.assertEqual(loaded.scroll_positions, {"a.md": 12})

    def test_missing_returns_default(self):
        store = self._store()
        self.assertTrue(store.load().empty)

    def test_corrupt_json_falls_back(self):
        store = self._store()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "workspace.json").write_text("{ 损坏", encoding="utf-8")
        self.assertTrue(store.load().empty)

    def test_empty_session_writes_no_file(self):
        from doc_tool.application.content.workspace_state import SessionState

        store = self._store()
        store.save(SessionState())
        self.assertFalse(store.file.exists())

    def test_empty_session_removes_stale_file(self):
        from doc_tool.application.content.workspace_state import SessionState

        store = self._store()
        store.save(SessionState(open_tabs=["a.md"], current_file="a.md"))
        self.assertTrue(store.file.exists())
        store.save(SessionState())  # 空会话 → 清理陈旧文件
        self.assertFalse(store.file.exists())


# --- 6.2 草稿生命周期（离屏） ---


class DraftLifecycleTests(unittest.TestCase):
    """编辑去抖写入、保存清除、只读不写、草稿不入索引。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self.project_root = Path(tempfile.mkdtemp(prefix="doc-tool-draft-ui-"))
        self.content_root = self.project_root / "content"
        self.rel = "requirement/第1章 引言/1.1 目的.md"
        path = self.content_root / self.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 1.1 目的\n原文\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)

    def _panel(self, writable=True, autosave=None):
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.editor_panel import EditorPanel

        writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        if autosave is None:
            from doc_tool.application.content.autosave import AutoSaveStore

            autosave = AutoSaveStore(self.project_root / ".state")
        return writer, EditorPanel(writer=writer, writable=writable, autosave=autosave)

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_edit_arms_draft_timer_and_write_persists(self):
        from doc_tool.application.content.autosave import AutoSaveStore

        store = AutoSaveStore(self.project_root / ".state")
        _writer, panel = self._panel(autosave=store)
        panel.load(self.rel, self._read(self.rel))
        panel._editor.setPlainText("# 1.1 目的\n被改内容\n")
        # 编辑后去抖定时器已武装（未触发前不落盘）
        self.assertTrue(panel._draft_timer.isActive())
        # 手动触发去抖回调 → 草稿写入且覆盖最近一份
        panel._write_draft()
        self.assertEqual(
            store.read(self.rel), "# 1.1 目的\n被改内容\n"
        )
        self.assertEqual(store.list_drafts(), [self.rel])
        panel.close()

    def test_save_clears_draft(self):
        from doc_tool.application.content.autosave import AutoSaveStore

        store = AutoSaveStore(self.project_root / ".state")
        writer, panel = self._panel(autosave=store)
        panel.load(self.rel, self._read(self.rel))
        panel._editor.setPlainText("# 1.1 目的\n被改内容\n")
        panel._write_draft()
        self.assertTrue(store.has(self.rel))
        self.assertTrue(panel.save())
        self.assertFalse(store.has(self.rel))
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n被改内容\n")
        panel.close()

    def test_readonly_no_draft(self):
        from doc_tool.application.content.autosave import AutoSaveStore

        store = AutoSaveStore(self.project_root / ".state")
        _writer, panel = self._panel(writable=False, autosave=store)
        panel.load(self.rel, self._read(self.rel))
        panel._editor.setPlainText("# 1.1 目的\n只读改写\n")
        panel._write_draft()
        self.assertEqual(store.list_drafts(), [])
        panel.close()

    def test_draft_timer_stopped_when_readonly(self):
        from doc_tool.application.content.autosave import AutoSaveStore

        store = AutoSaveStore(self.project_root / ".state")
        _writer, panel = self._panel(autosave=store)
        panel.load(self.rel, self._read(self.rel))
        panel._editor.setPlainText("x")
        self.assertTrue(panel._draft_timer.isActive())
        panel.set_writable(False)
        self.assertFalse(panel._draft_timer.isActive())
        panel.close()

    def test_drafts_outside_content_root_not_indexed(self):
        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.application.content.index import ContentIndexService

        store = AutoSaveStore(self.project_root / ".state")
        # 草稿镜像的路径在 contentRoot 中并不存在
        ghost_rel = "requirement/草稿专用/从未存在的文件.md"
        store.write(ghost_rel, "草稿内容")
        indexed = [
            rel for rel, _ in ContentIndexService(self.content_root).discover_files()
        ]
        # 草稿目录位于 contentRoot 之外 → 索引天然不收
        self.assertNotIn(ghost_rel, indexed)
        self.assertFalse(any(".state" in rel for rel in indexed))

    def test_draft_loaded_tab_is_dirty_and_not_saved(self):
        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.tabs_host import TabsHost

        store = AutoSaveStore(self.project_root / ".state")
        writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        tabs = TabsHost(writer, autosave=store)
        tabs.open_draft(self.rel, "# 1.1 目的\n恢复草稿\n")
        editor = tabs.current_editor()
        self.assertTrue(editor.is_dirty())
        self.assertIn("恢复自草稿", editor._dirty_label.text())
        # 正式文件未被写入
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原文\n")
        tabs.close_all()
        tabs.close()

    def test_save_all_skips_readonly_editors(self):
        """只读项目恢复出的脏草稿标签不应让 save_all 失败并中止退出。"""
        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.tabs_host import TabsHost

        store = AutoSaveStore(self.project_root / ".state")
        writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        tabs = TabsHost(writer, autosave=store, writable=False)
        tabs.open_file(self.rel, self._read(self.rel))
        editor = tabs.current_editor()
        editor._editor.setPlainText("只读下的程序化编辑")
        self.assertTrue(editor.is_dirty())
        self.assertFalse(editor.is_writable())
        failed = tabs.save_all()
        self.assertEqual(failed, [])  # 只读编辑器跳过，不报失败
        tabs.close_all()
        tabs.close()

    def test_close_dirty_tab_clears_draft(self):
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.tabs_host import TabsHost

        store = AutoSaveStore(self.project_root / ".state")
        writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        tabs = TabsHost(writer, autosave=store)
        tabs.open_file(self.rel, self._read(self.rel))
        editor = tabs.current_editor()
        editor._editor.setPlainText("# 1.1 目的\n被改\n")
        editor._write_draft()
        self.assertTrue(store.has(self.rel))
        # 拒绝 → 标签保留、草稿保留
        with mock.patch.object(
            QMessageBox, "question",
            return_value=QMessageBox.StandardButton.No,
        ):
            tabs._close_tab(0)
        self.assertEqual(tabs._tabs.count(), 1)
        self.assertTrue(store.has(self.rel))
        # 确认关闭 → 草稿被清除（显式放弃未保存编辑）
        with mock.patch.object(
            QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            tabs._close_tab(0)
        self.assertEqual(tabs._tabs.count(), 0)
        self.assertFalse(store.has(self.rel))
        tabs.close()


# --- 6.3 崩溃恢复（离屏） ---


class CrashRecoveryTests(unittest.TestCase):
    """预置草稿 → 恢复/忽略；恢复后脏状态且正式文件未变。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self.content_root = _make_project(
            {
                "requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\n原始正文\n",
                "requirement/第1章 引言/1.2 范围.md": "# 1.2 范围\n",
            }
        )
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)
        self.rel = "requirement/第1章 引言/1.1 目的.md"

    def _workspace(self, restore_choice):
        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.ui.content.workspace import ContentWorkspace

        store = AutoSaveStore(self.project_root / ".state")
        ws = ContentWorkspace(
            self.content_root,
            state_dir=self.project_root / ".state",
            restore_drafts_choice=restore_choice,
        )
        ws.shutdown()  # 停掉后台索引线程与轮询定时器，避免跨测试污染 Qt 状态
        return ws, store

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_restore_loads_drafts_as_dirty_and_keeps_formal_unchanged(self):
        ws, store = self._workspace(restore_choice=lambda rels: True)
        store.write(self.rel, "# 1.1 目的\n崩溃前草稿\n")
        ws._restore_drafts_and_session()
        editor = ws.tabs_host.editor_for(self.rel)
        self.assertIsNotNone(editor)
        self.assertTrue(editor.is_dirty())
        self.assertEqual(
            ws.tabs_host.editor_for(self.rel)._editor.toPlainText(),
            "# 1.1 目的\n崩溃前草稿\n",
        )
        # 正式 Markdown 未被覆盖
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原始正文\n")
        # 草稿在保存前保留在磁盘（供后续处理）
        self.assertTrue(store.has(self.rel))
        ws.shutdown()

    def test_ignore_leaves_drafts_and_formal_untouched(self):
        ws, store = self._workspace(restore_choice=lambda rels: False)
        store.write(self.rel, "# 1.1 目的\n草稿\n")
        ws._restore_drafts_and_session()
        self.assertIsNone(ws.tabs_host.editor_for(self.rel))
        self.assertTrue(store.has(self.rel))  # 忽略 → 草稿保留
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原始正文\n")
        ws.shutdown()


# --- 6.4 会话恢复（离屏） ---


class SessionRestoreTests(unittest.TestCase):
    """写入会话 → 重开 → 标签/当前文件/滚动/预览恢复；缺失跳过；损坏回退。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self.content_root = _make_project(
            {
                "requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\n" + "正文\n" * 40,
                "requirement/第1章 引言/1.2 范围.md": "# 1.2 范围\n" + "范围\n" * 40,
            }
        )
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)
        self.rel_a = "requirement/第1章 引言/1.1 目的.md"
        self.rel_b = "requirement/第1章 引言/1.2 范围.md"

    def _workspace(self, restore_choice=None):
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            self.content_root,
            state_dir=self.project_root / ".state",
            restore_drafts_choice=restore_choice,
        )
        ws.shutdown()  # 停掉后台索引线程与轮询定时器
        return ws

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_restore_tabs_current_scroll_preview(self):
        from doc_tool.application.content.workspace_state import SessionState

        ws1 = self._workspace()
        ws1.tabs_host.open_file(self.rel_a, self._read(self.rel_a))
        ws1.tabs_host.open_file(self.rel_b, self._read(self.rel_b))
        ws1.tabs_host.activate(self.rel_b)
        editor_a = ws1.tabs_host.editor_for(self.rel_a)
        editor_a._editor.verticalScrollBar().setValue(10)
        editor_a.set_preview_enabled(False)
        scroll_a = editor_a.scroll_position()
        session = ws1.collect_session_state(
            theme="dark", dock_visibility={"treeDock": True}, dock_state=""
        )
        ws1.session_store().save(session)
        self.assertEqual(session.open_tabs, [self.rel_a, self.rel_b])
        ws1.shutdown()

        ws2 = self._workspace()
        ws2._restore_drafts_and_session()
        self.assertEqual(ws2.tabs_host.open_rel_paths(), [self.rel_a, self.rel_b])
        self.assertEqual(ws2.tabs_host.current_rel_path(), self.rel_b)
        self.assertFalse(
            ws2.tabs_host.editor_for(self.rel_a).preview_enabled()
        )
        self.assertEqual(
            ws2.tabs_host.editor_for(self.rel_a).scroll_position(), scroll_a
        )
        ws2.shutdown()

    def test_missing_file_skipped_without_blocking(self):
        from doc_tool.application.content.workspace_state import SessionState

        ws1 = self._workspace()
        ws1.tabs_host.open_file(self.rel_a, self._read(self.rel_a))
        session = SessionState(
            open_tabs=[self.rel_a, "requirement/不存在.md"],
            current_file="requirement/不存在.md",
        )
        ws1.session_store().save(session)
        ws1.shutdown()

        ws2 = self._workspace()
        ws2._restore_drafts_and_session()
        # 缺失文件跳过，其余标签仍恢复；当前文件缺失 → 不激活
        self.assertEqual(ws2.tabs_host.open_rel_paths(), [self.rel_a])
        self.assertNotEqual(ws2.tabs_host.current_rel_path(), "requirement/不存在.md")
        ws2.shutdown()

    def test_corrupt_json_falls_back_to_default(self):
        state_dir = self.project_root / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "workspace.json").write_text("{ 损坏", encoding="utf-8")
        ws = self._workspace()
        ws._restore_drafts_and_session()
        self.assertEqual(ws.tabs_host.open_rel_paths(), [])
        ws.shutdown()

    def test_session_dirty_tab_restored_from_draft(self):
        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.application.content.workspace_state import SessionState

        store = AutoSaveStore(self.project_root / ".state")
        store.write(self.rel_a, "# 1.1 目的\n未保存草稿内容\n")
        ws1 = self._workspace()
        ws1.session_store().save(
            SessionState(open_tabs=[self.rel_a], current_file=self.rel_a)
        )
        ws1.shutdown()

        # 草稿恢复始终经显式确认：会话恢复只载入正式内容，草稿走「恢复/忽略」。
        ws2 = self._workspace(restore_choice=lambda rels: True)
        ws2._restore_drafts_and_session()
        editor = ws2.tabs_host.editor_for(self.rel_a)
        self.assertIsNotNone(editor)
        self.assertTrue(editor.is_dirty())
        self.assertEqual(
            editor._editor.toPlainText(), "# 1.1 目的\n未保存草稿内容\n"
        )
        # 正式文件未被覆盖
        self.assertEqual(self._read(self.rel_a), "# 1.1 目的\n" + "正文\n" * 40)
        ws2.shutdown()

    def test_session_ignored_draft_not_resurrected_on_reopen(self):
        """回归：会话恢复不得静默用旧草稿替换正式视图（修复已忽略草稿复活）。

        用户崩溃后「忽略」某草稿，随后会话记录了该文件；重开时会话标签应从
        正式内容恢复为干净状态，草稿仍走显式确认，绝不自动以草稿覆盖正式视图。
        """
        from doc_tool.application.content.autosave import AutoSaveStore
        from doc_tool.application.content.workspace_state import SessionState

        store = AutoSaveStore(self.project_root / ".state")
        store.write(self.rel_a, "# 1.1 目的\n已忽略的旧草稿\n")
        ws1 = self._workspace()
        ws1.session_store().save(
            SessionState(open_tabs=[self.rel_a], current_file=self.rel_a)
        )
        ws1.shutdown()

        # 用户再次「忽略」：会话标签展示正式内容且不脏，草稿保留在磁盘。
        ws2 = self._workspace(restore_choice=lambda rels: False)
        ws2._restore_drafts_and_session()
        editor = ws2.tabs_host.editor_for(self.rel_a)
        self.assertIsNotNone(editor)
        self.assertFalse(editor.is_dirty())
        self.assertEqual(
            editor._editor.toPlainText(), "# 1.1 目的\n" + "正文\n" * 40
        )
        self.assertTrue(store.has(self.rel_a))
        ws2.shutdown()


# --- 6.1 未保存保护（离屏，决策注入） ---


def _build_index(content_root):
    from doc_tool.application.content.index import ContentIndexService

    return ContentIndexService(content_root).build()


class UnsavedProtectionTests(unittest.TestCase):
    """退出三选 / 切项目三选 / 删除放弃·取消 / 重命名先保存·放弃·取消。"""

    @classmethod
    def setUpClass(cls):
        _ensure_qapp()

    def setUp(self):
        self.content_root = _make_project(
            {
                "requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\n原始正文\n",
                "requirement/第1章 引言/1.2 范围.md": "# 1.2 范围\n",
            }
        )
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.project_root, ignore_errors=True)
        self.rel = "requirement/第1章 引言/1.1 目的.md"

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def _workspace(self, unsaved_resolver=None):
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            self.content_root,
            state_dir=self.project_root / ".state",
            unsaved_resolver=unsaved_resolver,
        )
        ws.shutdown()  # 停掉后台索引线程与轮询定时器，避免跨测试污染 Qt 状态
        ws._index = _build_index(self.content_root)
        return ws

    def _open_dirty(self, ws, text="被改内容"):
        ws.open_file(self.rel)  # workspace 从磁盘读取
        editor = ws.tabs_host.editor_for(self.rel)
        editor._editor.setPlainText(text)
        return editor

    def _choice(self, value):
        from doc_tool.application.content.unsaved import UnsavedChoice

        return lambda rels, ctx: value

    def _window_with(self, ws):
        from doc_tool.ui.main_window import MainWindow

        window = MainWindow()
        window._content_workspace = ws
        return window

    # --- 退出 ---

    def test_exit_save_all_then_close(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace()
        self._open_dirty(ws, "# 1.1 目的\n退出保存的新内容\n")
        window = self._window_with(ws)
        window._unsaved_resolver = self._choice(UnsavedChoice.SAVE)
        self.assertTrue(window._confirm_close_with_unsaved())
        # 全部脏标签已保存
        self.assertEqual(
            self._read(self.rel), "# 1.1 目的\n退出保存的新内容\n"
        )
        self.assertFalse(ws.tabs_host.editor_for(self.rel).is_dirty())
        window._content_workspace = None  # 避免 closeEvent 再弹确认
        window.close()

    def test_exit_discard_clears_draft_and_closes(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace()
        self._open_dirty(ws, "被放弃的内容")
        ws._autosave.write(self.rel, "草稿")
        window = self._window_with(ws)
        window._unsaved_resolver = self._choice(UnsavedChoice.DISCARD)
        self.assertTrue(window._confirm_close_with_unsaved())
        # 正式文件不被写入；明确放弃 → 草稿被清除
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原始正文\n")
        self.assertFalse(ws._autosave.has(self.rel))
        window._content_workspace = None
        window.close()

    def test_exit_cancel_aborts_close(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace()
        self._open_dirty(ws)
        window = self._window_with(ws)
        window._unsaved_resolver = self._choice(UnsavedChoice.CANCEL)
        self.assertFalse(window._confirm_close_with_unsaved())
        # 全部未保存编辑保留
        self.assertTrue(ws.tabs_host.editor_for(self.rel).is_dirty())
        window._content_workspace = None
        window.close()

    def test_exit_no_dirty_no_dialog(self):
        ws = self._workspace()
        ws.open_file(self.rel)
        window = self._window_with(ws)
        calls = []
        window._unsaved_resolver = lambda rels, ctx: calls.append(ctx) or True
        self.assertTrue(window._confirm_close_with_unsaved())
        self.assertEqual(calls, [])  # 无脏标签 → 不弹确认
        window._content_workspace = None
        window.close()

    # --- 切项目 ---

    def test_switch_save_then_proceed(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace()
        self._open_dirty(ws, "# 1.1 目的\n切换前保存\n")
        window = self._window_with(ws)
        window._unsaved_resolver = self._choice(UnsavedChoice.SAVE)
        self.assertTrue(window._confirm_switch_project())
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n切换前保存\n")
        window._content_workspace = None
        window.close()

    def test_switch_cancel_aborts(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace()
        self._open_dirty(ws)
        window = self._window_with(ws)
        window._unsaved_resolver = self._choice(UnsavedChoice.CANCEL)
        self.assertFalse(window._confirm_switch_project())
        self.assertTrue(ws.tabs_host.editor_for(self.rel).is_dirty())
        window._content_workspace = None
        window.close()

    def test_switch_discard_drops_edits_and_clears_draft(self):
        """切换项目选「不保存」：不写盘、清除草稿、停止草稿定时器后放行。"""
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace()
        editor = self._open_dirty(ws, "# 1.1 目的\n切换前未保存\n")
        ws._autosave.write(self.rel, "# 1.1 目的\n切换前未保存\n")
        self.assertTrue(editor._draft_timer.isActive())  # 编辑已武装草稿定时器
        window = self._window_with(ws)
        window._unsaved_resolver = self._choice(UnsavedChoice.DISCARD)
        self.assertTrue(window._confirm_switch_project())
        # 放弃：正式文件不变、草稿被清除、定时器停止（不会在慢关闭时重写草稿）
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原始正文\n")
        self.assertFalse(ws._autosave.has(self.rel))
        self.assertFalse(editor._draft_timer.isActive())
        window._content_workspace = None
        window.close()

    # --- 删除 ---

    def test_delete_dirty_discard_moves_to_trash_and_clears_draft(self):
        from doc_tool.application.content.unsaved import UnsavedChoice
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        ws = self._workspace(
            unsaved_resolver=self._choice(UnsavedChoice.DISCARD)
        )
        self._open_dirty(ws)
        ws._autosave.write(self.rel, "草稿")
        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ), mock.patch.object(QMessageBox, "warning"):
            ws._on_delete_file(self.rel)
        # 文件入回收站，草稿被清除
        self.assertFalse((self.content_root / self.rel).exists())
        self.assertFalse(ws._autosave.has(self.rel))
        ws.shutdown()

    def test_delete_dirty_cancel_keeps_file_and_edits(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace(
            unsaved_resolver=self._choice(UnsavedChoice.CANCEL)
        )
        self._open_dirty(ws)
        ws._on_delete_file(self.rel)
        self.assertTrue((self.content_root / self.rel).exists())
        self.assertTrue(ws.tabs_host.editor_for(self.rel).is_dirty())
        ws.shutdown()

    # --- 重命名 ---

    def test_rename_dirty_save_first(self):
        from doc_tool.application.content.unsaved import UnsavedChoice
        from unittest import mock

        from PySide6.QtWidgets import QInputDialog

        ws = self._workspace(
            unsaved_resolver=self._choice(UnsavedChoice.SAVE)
        )
        self._open_dirty(ws, "# 1.1 目的\n重命名前保存的内容\n")
        ws._autosave.write(self.rel, "草稿")
        # 输入同名校名 → 保存后短路返回，不改名
        with mock.patch.object(
            QInputDialog, "getText",
            return_value=("1.1 目的.md", True),
        ):
            ws._on_rename_file(self.rel)
        # 当前编辑已保存到原路径，草稿清除
        self.assertEqual(
            self._read(self.rel), "# 1.1 目的\n重命名前保存的内容\n"
        )
        self.assertFalse(ws._autosave.has(self.rel))
        ws.shutdown()

    def test_rename_dirty_discard_proceeds_without_save(self):
        from doc_tool.application.content.unsaved import UnsavedChoice
        from unittest import mock

        from PySide6.QtWidgets import QInputDialog

        ws = self._workspace(
            unsaved_resolver=self._choice(UnsavedChoice.DISCARD)
        )
        self._open_dirty(ws, "放弃的内容")
        # 输入框取消 → 重命名流程中止；DISCARD 未保存任何内容
        with mock.patch.object(
            QInputDialog, "getText", return_value=("", False)
        ):
            ws._on_rename_file(self.rel)
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原始正文\n")
        ws.shutdown()

    def test_rename_dirty_cancel_aborts(self):
        from doc_tool.application.content.unsaved import UnsavedChoice

        ws = self._workspace(
            unsaved_resolver=self._choice(UnsavedChoice.CANCEL)
        )
        self._open_dirty(ws, "不丢的编辑")
        ws._on_rename_file(self.rel)
        self.assertEqual(self._read(self.rel), "# 1.1 目的\n原始正文\n")
        self.assertTrue(ws.tabs_host.editor_for(self.rel).is_dirty())
        ws.shutdown()

    def test_rename_dirty_discard_clears_old_path_draft(self):
        """重命名成功后清除旧路径草稿（防「废弃草稿复活改名文件」）。"""
        from doc_tool.application.content.unsaved import UnsavedChoice
        from unittest import mock

        from PySide6.QtWidgets import QInputDialog, QMessageBox

        ws = self._workspace(
            unsaved_resolver=self._choice(UnsavedChoice.DISCARD)
        )
        self._open_dirty(ws, "放弃的编辑")
        ws._autosave.write(self.rel, "旧路径草稿")
        with mock.patch.object(
            QInputDialog, "getText", return_value=("1.1 目的2.md", True)
        ), mock.patch.object(QMessageBox, "warning"):
            ws._on_rename_file(self.rel)
        # 文件已改名，旧路径草稿被清除，新路径无草稿
        self.assertFalse((self.content_root / self.rel).exists())
        self.assertTrue(
            (self.content_root / "requirement/第1章 引言/1.1 目的2.md").exists()
        )
        self.assertFalse(ws._autosave.has(self.rel))
        self.assertFalse(ws._autosave.has("requirement/第1章 引言/1.1 目的2.md"))
        ws.shutdown()


# === 人工验收清单（工作台安全与恢复，任务 7.1/7.2） ===
# 以下操作需要在 Windows 桌面环境中手动执行，无法自动化：
#
# 1. 退出三选：打开文件编辑（置脏）后关闭应用
#    - 保存 → 全部脏标签落盘（生成 .md.bak）后退出
#    - 不保存 → 不写任何文件直接退出；重开项目不再提示该草稿
#    - 取消 → 中止退出，编辑保留
#    - 无脏标签 → 直接退出，不弹确认
# 2. 切项目三选：编辑后通过 文件→打开项目 打开另一个项目
#    - 保存 / 不保存 / 取消 行为同上；取消后旧项目与编辑保持不变
# 3. 删除脏文件：树中删除含未保存编辑的文件 → 「放弃 / 取消」
#    - 取消 → 文件与编辑保留；放弃 → 文件入回收站、草稿清除
# 4. 重命名脏文件 → 「先保存 / 放弃 / 取消」
#    - 先保存 → 保存到原路径再改名并联动引用；取消 → 中止
# 5. 保存全部：文件→保存全部 / Ctrl+Shift+S → 全部脏标签落盘并清除 ●
# 6. 只读项目：编辑被禁用，不产生草稿；删除/重命名写操作不可用
# 7. 草稿恢复：编辑后不保存直接退出（草稿已写），重开项目
#    - 提示「恢复 / 忽略」→ 恢复后标签带「● 恢复自草稿」，显式保存才落盘
# 8. 会话保存→重开恢复：调整 Dock 布局/开关主题/打开若干标签并滚动
#    - 退出后重开 → 布局/主题/标签/当前文件/滚动位置恢复；缺失文件跳过
# 9. 会话脏标签衔接：关闭时某标签未保存（有草稿）→ 重开经草稿以脏状态载入
# 10. 菜单项可用性：无项目/只读/索引未就绪时「保存全部」禁用，项目打开后可点


if __name__ == "__main__":
    unittest.main()
