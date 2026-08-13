# -*- coding: utf-8 -*-
"""Run on real display, open a file, and save screenshots of the editor panel."""

import os
import sys
import tempfile
from pathlib import Path

# NOTE: intentionally NOT offscreen so we exercise the real Qt platform plugin.
os.environ.pop("QT_QPA_PLATFORM", None)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "site-packages"))
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication

from doc_tool.ui.content.workspace import ContentWorkspace

OUT = REPO / "scripts" / "tests" / "shots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    app = QApplication(sys.argv)
    tmp = Path(tempfile.mkdtemp(prefix="repro-shot-"))
    ws = ContentWorkspace(
        REPO / "content",
        state_dir=tmp / "state",
        assets_root=REPO / "assets",
        writable=False,
    )
    ws.resize(1200, 700)
    ws.show()

    import time
    for _ in range(400):
        ws._runner.poll()
        app.processEvents()
        if ws.is_index_ready():
            break
        time.sleep(0.02)
    print("index ready:", ws.is_index_ready(), "files:", ws.index_file_count())

    files = [it for it in ws._tree._items if it.is_file]
    if not files:
        print("no files")
        return 1
    target = files[0]
    idx = ws._tree._index_for(target.rel_path)
    ws._tree._tree.setCurrentIndex(idx)
    ws._tree._tree.selectionModel().setCurrentIndex(
        idx, ws._tree._tree.selectionModel().SelectionFlag.ClearAndSelect
    )
    app.processEvents()

    editor = ws.tabs_host.current_editor()
    print("editor opened:", editor is not None, "rel:", editor and editor.current_rel_path())
    app.processEvents()

    # Wait for debounced preview refresh if any.
    time.sleep(0.6)
    app.processEvents()

    ws.grab().save(str(OUT / "workspace.png"))
    if editor is not None:
        editor.grab().save(str(OUT / "editor.png"))
        editor._editor.grab().save(str(OUT / "editor-left.png"))
        editor._preview.grab().save(str(OUT / "editor-right.png"))
    print("shots saved to", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
