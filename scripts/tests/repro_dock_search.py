# -*- coding: utf-8 -*-
"""Headless reproduction for the two reported UI bugs:
  A. SearchPanel: results not visible after a search.
  B. Left (chapter tree) / bottom (panels) docks cannot be reopened after close.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "site-packages"))
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QTreeWidgetItem, QVBoxLayout, QWidget

from doc_tool.application.content.search import SearchOptions, SearchResult, SearchService
from doc_tool.ui.content.search_panel import SearchPanel


def check_layout_integrity() -> None:
    """Verify Qt behavior when two QVBoxLayout(self) are created on one widget."""
    print("\n=== check_layout_integrity ===")
    w = QWidget()
    lay1 = QVBoxLayout(w)
    b1 = w  # placeholder
    lay1.addWidget(QWidget())
    lay2 = QVBoxLayout(w)  # second layout install attempt
    lay2.addWidget(QWidget())
    installed = w.layout()
    print("installed layout is lay1:", installed is lay1)
    print("installed layout is lay2:", installed is lay2)
    print("lay2.isLayoutItem... parentWidget:", lay2.parentWidget() is w)


def run_search_panel() -> int:
    """SearchPanel with a fake service; render results and check tree visibility."""
    print("\n=== run_search_panel ===")

    class FakeIndex:
        def __init__(self):
            self.files = {"a.md": type("E", (), {"document_type": "general"})()}
            self.lines = {"a.md": ["hello world line", "nothing here"]}

        def all_files(self):
            return list(self.files)

    class FakeService:
        def __init__(self):
            self.index = FakeIndex()

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

    # Drive a search like a user would.
    panel._query_entry.setText("hello")
    panel.search_now()
    # Wait for the background TaskRunner to finish.
    import time
    for _ in range(200):
        panel._runner.poll()
        app.processEvents()
        if not panel._runner.is_running:
            break
        time.sleep(0.01)
    app.processEvents()

    tree = panel._tree
    top_count = tree.topLevelItemCount()
    print("tree topLevelItemCount:", top_count)
    summary = panel._summary_label.text()
    print("summary label:", summary)
    print("tree visible:", tree.isVisible())
    print("tree geometry:", tree.geometry())
    print("tree height() in panel:", tree.height(), "panel:", panel.height())

    if top_count == 0:
        print("BUG A reproduced: search results tree is empty (or never rendered)")
        return 1
    # Check the tree actually occupies vertical space inside the panel.
    # If it is orphaned from the installed layout, height will be tiny/0.
    if tree.height() < 50:
        print("BUG A reproduced: results tree height=%d (layout not managing it)" % tree.height())
        return 2
    print("A OK: results rendered and visible")
    return 0


def run_dock_reopen() -> int:
    """Build the real MainWindow, close the left/bottom docks, try to reopen."""
    print("\n=== run_dock_reopen ===")
    from doc_tool.ui.main_window import MainWindow

    win = MainWindow()
    # Simulate a project being opened so content docks are created.
    # We need a real project summary; build a minimal fake to drive show_project.
    from doc_tool.application.content.index import ContentIndexService

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

    win.show_project(FakeSummary())
    app.processEvents()
    # wait for content index build
    import time
    for _ in range(400):
        win._content_workspace._runner.poll()
        app.processEvents()
        if win._content_workspace.is_index_ready():
            break
        time.sleep(0.02)

    tree_dock = win.findChild(type(win._tree_dock), "chapterTreeDock")
    panels_dock = win.findChild(type(win._panels_dock), "panelsDock")
    print("tree_dock found:", tree_dock is not None)
    print("panels_dock found:", panels_dock is not None)
    if tree_dock is None or panels_dock is None:
        return 3

    # Close both docks (as a user clicking the X in the dock title bar).
    tree_dock.close()
    panels_dock.close()
    app.processEvents()
    print("after close -> tree visible:", tree_dock.isVisible(), "panels visible:", panels_dock.isVisible())

    # Now: does ANY mechanism reopen them? Ctrl+F (search) should at least re-show the bottom panels dock.
    win._on_content_search()
    app.processEvents()
    print("after Ctrl+F -> tree visible:", tree_dock.isVisible(), "panels visible:", panels_dock.isVisible())
    print("panels dock has feature Closable:", bool(panels_dock.features() & panels_dock.DockWidgetFeature.DockWidgetClosable))

    if not panels_dock.isVisible():
        print("BUG B reproduced: panels dock cannot be reopened")
        return 4
    print("B OK: docks reopenable")
    return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    check_layout_integrity()
    a = run_search_panel()
    b = run_dock_reopen()
    print("\nEXIT:", max(a, b))
    sys.exit(max(a, b))
