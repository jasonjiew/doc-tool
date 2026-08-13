# -*- coding: utf-8 -*-
"""Full-path reproduction: ContentWorkspace over real content/ -> click tree file -> preview."""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "site-packages"))
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication

from doc_tool.ui.content.workspace import ContentWorkspace


def main() -> int:
    app = QApplication(sys.argv)
    tmp = Path(tempfile.mkdtemp(prefix="repro-full-"))
    ws = ContentWorkspace(
        REPO / "content",
        state_dir=tmp / "state",
        assets_root=REPO / "assets",
        writable=False,
    )

    # Wait for background index build (TaskRunner polled via timer).
    import time
    for _ in range(400):
        ws._runner.poll()
        app.processEvents()
        if ws.is_index_ready():
            break
        time.sleep(0.02)
    print("index ready:", ws.is_index_ready(), "files:", ws.index_file_count())
    if not ws.is_index_ready():
        print("RESULT: index not ready")
        return 2

    items = ws._tree._items
    files = [it for it in items if it.is_file]
    print("tree file nodes:", len(files))
    if not files:
        print("RESULT: no file nodes in tree")
        return 3

    target = files[0]
    print("target file:", target.rel_path)

    # Simulate real click via QTreeView selection -> currentChanged.
    idx = ws._tree._index_for(target.rel_path)
    ws._tree._tree.setCurrentIndex(idx)
    ws._tree._tree.selectionModel().setCurrentIndex(
        idx, ws._tree._tree.selectionModel().SelectionFlag.ClearAndSelect
    )
    app.processEvents()

    editor = ws.tabs_host.current_editor()
    print("editor opened:", editor is not None)
    if editor is None:
        print("RESULT: NO EDITOR OPENED (bug)")
        return 4
    print("editor rel:", editor.current_rel_path())
    pv = editor._preview.toPlainText()
    print("preview length:", len(pv))
    print("preview head:", repr(pv[:150]))
    if not pv.strip():
        print("RESULT: PREVIEW EMPTY (bug reproduced)")
        return 1
    print("RESULT: preview OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
