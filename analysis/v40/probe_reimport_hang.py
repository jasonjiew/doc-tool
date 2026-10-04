# -*- coding: utf-8 -*-
"""带步进日志的挂起定位：逐行跟踪 _reimport_into_current 的真实调用顺序。"""
from __future__ import annotations

import faulthandler
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
for candidate in (str(REPO), str(REPO / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

faulthandler.dump_traceback_later(30, exit=False)
print("STEP 0 start", flush=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from scripts.tests import core_fixtures as fixtures  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="probe-reimport-"))
proj = fixtures.two_chapter_project(work / "proj")
print("STEP 1 fixture ready", proj, flush=True)

from doc_tool.ui.main_window import MainWindow  # noqa: E402

with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
    window = MainWindow()
print("STEP 2 window ready", flush=True)

from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402


class _FakeSummary:
    is_writable = True

    def __init__(self, root):
        self.project_root = str(root)
        self.manifest = ProjectManifest.load(root)
        self.paths = ProjectPaths(root)


window._project_summary = _FakeSummary(proj)
docx = fixtures.standard_docx(work / "外部修改.docx")
print("STEP 3 docx ready", flush=True)

orig = window._reimport_into_current


def traced(source, **kwargs):
    print("STEP 4 entering _reimport_into_current", source, flush=True)
    result = orig(source, **kwargs)
    print("STEP 5 returned from _reimport_into_current", flush=True)
    return result


window._reimport_into_current = traced
print("STEP 6 calling _on_import_document", flush=True)
window._on_import_document([docx])
print("STEP 7 _on_import_document returned; runner running =", window.runner.is_running, flush=True)
threading.Thread(target=lambda: None).start()
print("STEP 8 done", flush=True)