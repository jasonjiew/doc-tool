import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from doc_tool.application.content.reimport import ChapterChange
from doc_tool.application.content.reimport_preview import open_preview
changes = [ChapterChange("1 概述.md", "modified", False, True),
           ChapterChange("2 设计.md", "modified", False, True),
           ChapterChange("3 测试.md", "modified", True, False)]
s = open_preview(changes, service=None, source_path="new.docx", baseline_available=True,
                 dirty_paths=["2 设计.md"])
for e in s.entries:
    print(repr(e.rel_path), e.change, "conflict", e.conflict, "dirty", e.dirty,
          "selected", e.selected, "reason", repr(e.blocked_reason))