# -*- coding: utf-8 -*-
"""最小复现：RdWorkspaceDialog 是否导致同进程后续 setStyleSheet 崩溃。"""
import os, shutil, sys, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from PySide6.QtWidgets import QApplication
from scripts.tests import core_fixtures as fixtures

MODE = sys.argv[1] if len(sys.argv) > 1 else "dialog"

app = QApplication.instance() or QApplication([])
work = Path(tempfile.mkdtemp(prefix="repro-"))
ws_root = work / "ws"; ws_root.mkdir(parents=True)
members = {}
for name in ("Alpha", "Beta", "Gamma"):
    members[name] = fixtures.two_chapter_project(ws_root / name)

if MODE in ("dialog", "dialog_hold"):
    from doc_tool.application import workspace as ws_mod
    ws = ws_mod.create_workspace(ws_root, name="三成员")
    for name, root in members.items():
        ws_mod.add_project(ws, root, role="requirement")
    ws.save()
    from doc_tool.ui.rd_workspace import RdWorkspaceDialog
    dlg = RdWorkspaceDialog(None, root=str(ws_root))
    dlg.show()
    QApplication.processEvents()
    print("members:", len(dlg._members))
    dlg.close()
    if MODE == "dialog_hold":
        print("holding reference")
    else:
        dlg.deleteLater()
        QApplication.processEvents()
        del dlg
elif MODE == "files":
    print("only created project files")

import gc
gc.collect()
QApplication.processEvents()
from doc_tool.ui.styles import apply_theme
apply_theme(app, dark=True)
apply_theme(app, dark=False)
print("theme applied OK, mode:", MODE)