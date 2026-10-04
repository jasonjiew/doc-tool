# -*- coding: utf-8 -*-
"""MAIN2-B：外部 Word 修订隔离预览、选择接收与脏项保留。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.content.reimport import ReimportService  # noqa: E402
from doc_tool.application.content.reimport_preview import (  # noqa: E402
    apply_session, cancel_session, open_preview, toggle_selection,
)


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class ServicePreviewTests(unittest.TestCase):
    """服务层：隔离预览不写正文、脏项不参与、应用只处理合法项。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2b-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.manifest = ProjectManifest.load(self.project)
        self.paths = ProjectPaths(self.project)
        self.service = ReimportService(self.manifest, self.paths)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())

    def _incoming(self, mapping) -> Path:
        incoming = self.work / "incoming"
        for rel, text in mapping.items():
            _write(incoming, rel, text)
        return incoming

    def test_preview_reports_added_modified_deleted_without_writing(self):
        before = {
            rel: (self.content_root / rel).read_text(encoding="utf-8")
            for rel in self._current_rel_paths()
        }
        incoming = self._incoming({
            "第1章 引言/1.1 目的.md": "# 目的\n\n新源正文。\n",
            "第2章 新增/2.1 新节.md": "# 新节\n\n新增内容。\n",
        })
        session = open_preview(
            self._changes_for(incoming), service=self.service,
            source_path=str(incoming), baseline_available=False,
        )
        statuses = {item.rel_path: item.change for item in session.entries}
        self.assertIn("第1章 引言/1.1 目的.md", statuses)
        # 预览不写正式正文
        after = {
            rel: (self.content_root / rel).read_text(encoding="utf-8")
            for rel in self._current_rel_paths()
        }
        self.assertEqual(before, after)

    def _current_rel_paths(self):
        from doc_tool.application.effective_snapshot import discover_chapters

        return [rel for rel, _path in discover_chapters(self.content_root)]

    def _changes_for(self, incoming: Path):
        from doc_tool.application.content.reimport import compare_chapters

        return compare_chapters(self.content_root, incoming, self.service._base_hashes())


class PreviewWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _session(self, dirty=(), conflicts=()):
        changes = []
        from doc_tool.application.content.reimport import ChapterChange

        for rel in ("1 概述.md", "2 设计.md", "3 测试.md"):
            conflicts_here = rel in conflicts
            changes.append(ChapterChange(rel, "modified", conflicts_here, not conflicts_here))
        return open_preview(
            changes, service=None, source_path="new.docx", baseline_available=True,
            dirty_paths=list(dirty),
            local_contents={item.rel_path: "本地内容" for item in changes},
            incoming_contents={item.rel_path: "新源内容" for item in changes},
        )

    def _window(self, session):
        from doc_tool.ui.reimport_preview_window import ReimportPreviewWindow

        class _Host:
            def __init__(self):
                self.applied = []
                self.status = []

            def _apply_reimport_session(self, sess, source):
                self.applied.append((sess, source))
                return True

            def _save_reimport_incoming_copy(self, source):
                return "copied"

            def _save_chapters_then_refresh(self, source, paths, window=None):
                self.status.append(list(paths))
                return True

            def _show_status_message(self, message):
                self.status.append(message)

        host = _Host()
        window = ReimportPreviewWindow(session, host=host, source_path="new.docx")
        self.addCleanup(window.close)
        return window, host

    def test_conflict_and_dirty_rows_are_preselected_out(self):
        session = self._session(dirty=("2 设计.md",), conflicts=("3 测试.md",))
        window, _host = self._window(session)
        checked = window.selected_paths()
        self.assertEqual(checked, ["1 概述.md"])
        # 冲突/脏项显示保留原因，且不可勾选
        reasons = [window._table.item(row, 2).text() for row in range(window._table.rowCount())]
        self.assertTrue(any("未保存" in item for item in reasons))
        self.assertTrue(
            any(("双方" in item) or ("冲突" in item) or ("人工确认" in item) for item in reasons),
            "冲突项必须给出保留原因：{0}".format(reasons),
        )

    def test_diff_is_shown_for_selected_row(self):
        session = self._session()
        window, _host = self._window(session)
        window._table.selectRow(0)
        self.assertIn("新源内容", window._diff.toPlainText())
        self.assertIn("本地内容", window._diff.toPlainText())

    def test_cancel_writes_nothing(self):
        session = self._session()
        window, host = self._window(session)
        window._on_cancel()
        self.assertTrue(session.closed)
        self.assertEqual(host.applied, [])
        self.assertFalse(any(item.selected for item in session.entries))

    def test_toggle_blocked_item_is_refused(self):
        session = self._session(dirty=("2 设计.md",))
        blocked = [item for item in session.entries if item.dirty][0]
        self.assertFalse(toggle_selection(session, blocked.rel_path, True))
        self.assertFalse(blocked.selected)

    def test_apply_passes_only_applicable(self):
        session = self._session(dirty=("2 设计.md",), conflicts=("3 测试.md",))
        window, host = self._window(session)
        window._on_apply()
        self.assertEqual(len(host.applied), 1)
        applied_session, source = host.applied[0]
        self.assertEqual(source, "new.docx")
        applicable = [item.rel_path for item in applied_session.entries if item.applicable]
        self.assertEqual(applicable, ["1 概述.md"])


class MainWindowReimportEntryTests(unittest.TestCase):
    """真实入口：菜单/按钮走差异预览；预览失败只提示，不写正文。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2b-entry-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.ui.main_window import MainWindow

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            self.window = MainWindow()
        self.addCleanup(self.window.close)

        class _Summary:
            is_writable = True

            def __init__(self, root: Path):
                from doc_tool.domain.manifest import ProjectManifest
                from doc_tool.domain.paths import ProjectPaths

                self.project_root = str(root)
                self.manifest = ProjectManifest.load(root)
                self.paths = ProjectPaths(root)

        self.window._project_summary = _Summary(self.project)

    def test_menu_action_exists(self):
        self.assertTrue(hasattr(self.window, "_reimport_action"))
        self.assertIn("重新导入", self.window._reimport_action.text())

    def test_entry_opens_preview_window_and_writes_nothing(self):
        content_root = self.window._project_summary.paths.resolve(
            self.window._project_summary.manifest.relative_content_root()
        )
        before = {
            path.relative_to(content_root).as_posix(): path.read_text(encoding="utf-8")
            for path in content_root.rglob("*.md")
        }
        incoming = self.work / "updated.docx"
        incoming.write_bytes(b"PK\x03\x04not-a-real-docx")
        self.window._reimport_into_current(incoming)
        # 差异计算在后台（MAIN2-B 2.1）：泵事件等待结束，期间 UI 不阻塞。
        import time

        from PySide6.QtWidgets import QApplication

        deadline = time.monotonic() + 60
        while self.window.runner.is_running and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        QApplication.processEvents()
        after = {
            path.relative_to(content_root).as_posix(): path.read_text(encoding="utf-8")
            for path in content_root.rglob("*.md")
        }
        self.assertEqual(before, after, "预览阶段不得写正式正文")
        # 无法解析的新源必须明确提示（就地状态），且不打开选择窗口、不改项目。
        message = " ".join([
            self.window._status_label.text(),
            self.window.statusBar().currentMessage() if self.window.statusBar() else "",
        ])
        self.assertIn("差异预览未生成", message)
        self.assertIsNone(getattr(self.window, "_reimport_window", None))


if __name__ == "__main__":
    unittest.main(verbosity=2)