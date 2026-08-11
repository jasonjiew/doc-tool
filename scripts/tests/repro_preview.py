# -*- coding: utf-8 -*-
"""Headless reproduction for: 点击左侧 md 文件，右侧预览未按 markdown 渲染。

Simulates the exact click -> open -> preview path with PySide6 offscreen.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "site-packages"))
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication

from doc_tool.application.content.tree import build_tree
from doc_tool.application.content.writer import ContentWriter
from doc_tool.ui.content.tabs_host import TabsHost
from doc_tool.ui.content.tree_panel import ChapterTree

MD_SAMPLE = """# 第一章 概述

## 1.1 项目背景

这里是段落文本。

| 字段 | 说明 |
| ---- | ---- |
| A | 值一 |
| B | 值二 |

![图例](assets/foo.png)

正文结尾。
"""


def main() -> int:
    app = QApplication(sys.argv)

    tmp = Path(tempfile.mkdtemp(prefix="repro-preview-"))
    content_root = tmp / "content"
    content_root.mkdir(parents=True)
    state_dir = tmp / "state"
    state_dir.mkdir(parents=True)
    rel = "requirement/第1章/1.1-概述.md"
    f = content_root / rel
    f.parent.mkdir(parents=True)
    f.write_text(MD_SAMPLE, encoding="utf-8")

    writer = ContentWriter(content_root, state_dir)
    tabs = TabsHost(writer)
    opened = {}

    def on_open(rp: str) -> None:
        path = writer.resolve(rp)
        text = path.read_text(encoding="utf-8")
        tabs.open_file(rp, text)
        opened["last"] = rp

    tree = ChapterTree(on_open=on_open)
    items = build_tree([rel])
    tree.set_items(items)

    print("=== tree items ===")
    for it in items:
        print("  id=%r parent=%r file=%s text=%r" % (
            it.node_id, it.parent_id, it.is_file, it.text))

    # Simulate a user click: selecting the file node in the QTreeView.
    ok = tree.select_file(rel)
    print("select_file ->", ok)

    # Also drive currentChanged like a real click would.
    idx = tree._index_for(rel)
    tree._tree.setCurrentIndex(idx)
    tree._tree.selectionModel().setCurrentIndex(
        idx, tree._tree.selectionModel().SelectionFlag.ClearAndSelect
    )
    print("currentChanged path -> opened:", opened.get("last"))

    # Check the editor + preview state.
    editor = tabs.current_editor()
    if editor is None:
        print("RESULT: no editor opened")
        return 2
    print("editor rel:", editor.current_rel_path())
    print("editor has text:", bool(editor._editor.toPlainText()))
    print("preview length:", len(editor._preview.toPlainText()))
    print("preview text preview:")
    print(repr(editor._preview.toPlainText()[:200]))
    if not editor._preview.toPlainText().strip():
        print("RESULT: PREVIEW EMPTY (bug reproduced?)")
        return 1
    print("RESULT: preview has content")
    return 0


if __name__ == "__main__":
    sys.exit(main())
