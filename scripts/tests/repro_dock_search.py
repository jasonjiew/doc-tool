# -*- coding: utf-8 -*-
"""Headless regression checks for the two reported UI bugs:
  A. SearchPanel results tree invisible (double-QVBoxLayout(self) defect).
  B. Left (chapter tree) / bottom (panels) docks cannot be reopened after close.

Runs offscreen. Exits 0 when both behaviors are fixed, non-zero otherwise.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "site-packages"))
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from doc_tool.application.content.search import SearchResult
from doc_tool.ui.content.search_panel import SearchPanel

APP = QApplication(sys.argv)


def _poll_until(cond, *, timeout_ms=4000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def check_search_panel_layout() -> int:
    """SearchPanel must manage the results tree via its single installed layout."""
    print("\n=== check_search_panel_layout ===")
    w = QWidget()
    lay1 = QVBoxLayout(w)
    lay1.addWidget(QWidget())
    lay2 = QVBoxLayout(w)
    lay2.addWidget(QWidget())
    ok_layout = w.layout() is lay1 and lay2.parentWidget() is None
    print("second layout NOT installed:", ok_layout)
    if not ok_layout:
        print("BUG A (layout) reproduced: second layout got installed")
        return 1

    class FakeIndex:
        def __init__(self):
            self.files = {"a.md": type("E", (), {"document_type": "general"})()}
            self.lines = {"a.md": ["hello world line", "nothing here"]}

        def all_files(self):
            return list(self.files)

    class FakeService:
        def search(self, options, cancel_token=None):
            return SearchResult(
                query=options.query,
                total=2,
                hits=[
                    type("H", (), {"rel_path": "a.md", "line_no": 1, "text": "hello world line"}),
                    type("H", (), {"rel_path": "a.md", "line_no": 2, "text": "nothing here"}),
                ],
                file_count=1,
            )

    panel = SearchPanel(FakeService())
    panel.resize(600, 400)
    panel.show()
    panel._query_entry.setText("hello")
    panel.search_now()
    ok = _poll_until(lambda: not panel._runner.is_running)
    APP.processEvents()
    tree = panel._tree
    print("search finished:", ok, "| topLevelItems:", tree.topLevelItemCount(),
          "| tree height:", tree.height(), "| panel height:", panel.height())
    if tree.topLevelItemCount() == 0:
        print("BUG A (results) reproduced: results tree empty")
        return 2
    if tree.height() < 200:
        print("BUG A (results) reproduced: results tree height=%d (layout not managing it)" % tree.height())
        return 3
    print("A OK: results rendered and tree fills the panel")
    return 0


def check_dock_reopen() -> int:
    """Closing the tree/panels docks must be recoverable via 视图 menu / content ops."""
    print("\n=== check_dock_reopen ===")
    from doc_tool.ui.main_window import MainWindow

    tmp = Path(tempfile.mkdtemp(prefix="repro-dock-"))
    content_root = tmp / "content"
    content_root.mkdir(parents=True)
    (content_root / "a.md").write_text("# Title\n\nhello\n", encoding="utf-8")

    class FakeManifest:
        documentType = "general"
        documentName = "测试文档"
        documentNo = "TEST-001"

        def relative_content_root(self):
            return "content"

    class FakePaths:
        def __init__(self, root):
            self.root = root
            self.project_root = root
            self.state_dir = tmp / "state"
            self.state_dir.mkdir(parents=True)
            self.assets_root = tmp / "assets"
            self.assets_root.mkdir(parents=True)
            self.logs_dir = tmp / "logs"
            self.logs_dir.mkdir(parents=True)
            self.output_dir = tmp / "output"
            self.content_root = tmp / "content"

        def resolve(self, rel):
            return tmp / rel

    class FakeSummary:
        def __init__(self):
            self.manifest = FakeManifest()
            self.paths = FakePaths(tmp)
            self.project_root = tmp
            self.is_writable = True
            self.lock_info = None

    from unittest.mock import patch

    win = MainWindow()
    win.show()
    with patch("doc_tool.application.project_service.add_recent_project"):
        win.show_project(FakeSummary())
    APP.processEvents()
    ok = _poll_until(lambda: win._content_index_ready)
    print("content index ready:", ok)

    tree_dock = win.findChild(type(win._tree_dock), "chapterTreeDock")
    panels_dock = win.findChild(type(win._panels_dock), "panelsDock")
    if tree_dock is None or panels_dock is None:
        print("BUG B reproduced: content docks missing after project open")
        return 4
    if not win._task_dock_widget.isVisible():
        print("BUG B reproduced: task dock hidden after project open")
        return 8

    # 视图 menu must expose a toggle action for each dock.
    toggle_labels = [a.text() for a in win._view_menu.actions()]
    print("视图 menu entries:", toggle_labels)
    for expected in ("章节树", "工具面板", "任务 / 结果"):
        if expected not in toggle_labels:
            print("BUG B reproduced: 视图 menu missing toggle for %r" % expected)
            return 5

    # Close both docks, then Ctrl+F must re-show the panels dock.
    tree_dock.close()
    panels_dock.close()
    APP.processEvents()
    win._on_content_search()
    APP.processEvents()
    print("after close+Ctrl+F -> tree visible:", tree_dock.isVisible(),
          "| panels visible:", panels_dock.isVisible())
    if not panels_dock.isVisible():
        print("BUG B reproduced: panels dock still hidden after Ctrl+F")
        return 6

    # Close again; the 视图 menu toggle must re-show it too.
    panels_dock.close()
    APP.processEvents()
    panels_action = next(a for a in win._view_menu.actions() if a.text() == "工具面板")
    panels_action.trigger()
    APP.processEvents()
    print("after 视图->工具面板 -> panels visible:", panels_dock.isVisible())
    if not panels_dock.isVisible():
        print("BUG B reproduced: 视图 menu toggle did not re-show panels dock")
        return 7

    print("B OK: docks reopenable via Ctrl+F and 视图 menu")
    win.close()
    return 0


def main() -> int:
    a = check_search_panel_layout()
    b = check_dock_reopen()
    print("\nEXIT:", max(a, b))
    return max(a, b)


if __name__ == "__main__":
    sys.exit(main())
