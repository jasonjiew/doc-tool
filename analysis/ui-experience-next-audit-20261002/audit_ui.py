"""Render current Qt widgets in an isolated offscreen audit (UI2 evidence).

Usage::

    python analysis/ui-experience-next-audit-20261002/audit_ui.py [OUT_DIR]

``OUT_DIR`` defaults to this script's directory (the UI2 "before" baseline).
Pass another directory to record the "after" state without touching the
baseline::

    python analysis/ui-experience-next-audit-20261002/audit_ui.py \
        analysis/ui-experience-next-after-20261002

Never touches user projects: a synthetic project, an isolated ``Path.home`` and
explicitly registered Chinese fonts only. The audit is structural evidence, not
a real Windows/DPI/IME/Word acceptance run.
"""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
OUT = OUT if OUT.is_absolute() else (ROOT / OUT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
for item in (ROOT, ROOT / ".vendor/site-packages", ROOT / "analysis/review-test-deps"):
    sys.path.insert(0, str(item))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox, QToolButton
from doc_tool.ui.main_window import MainWindow
from doc_tool.ui.styles import apply_theme
from doc_tool.ui.wizard import ImportWizard
from doc_tool.ui.reuse_dialog import ReuseDialog
from doc_tool.ui.assist_panel import AssistPanel
from scripts.tests.fixture_factory import create_project
from scripts.tests.core_fixtures import standard_docx

OUT.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
font_files = ["msyh.ttc", "msyhbd.ttc", "consola.ttf", "seguiemj.ttf"]
loaded_fonts = []
for font_file in font_files:
    font_path = Path("C:/Windows/Fonts") / font_file
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        loaded_fonts.extend(QFontDatabase.applicationFontFamilies(font_id))
apply_theme(app, dark=False)
metrics = {"date": "2026-10-02", "platform": "Qt offscreen", "scale": 1,
           "fonts": loaded_fonts,
           "limitations": ["synthetic project", "no live desktop", "explicit offscreen font registration", "no real DPI/IME/Word trial"], "views": []}


def pump(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def capture(widget, name, width, height):
    widget.resize(width, height)
    widget.show()
    pump()
    screenshot = OUT / (name + ".png")
    if not widget.grab().save(str(screenshot)):
        raise RuntimeError("Cannot save " + str(screenshot))
    row = {"name": name, "requested": [width, height], "actual": [widget.width(), widget.height()],
           "minimumHint": [widget.minimumSizeHint().width(), widget.minimumSizeHint().height()],
           "screenshot": screenshot.name, "buttons": []}
    for button in widget.findChildren(QPushButton):
        if not button.isVisibleTo(widget):
            continue
        point = button.mapTo(widget, QPoint(0, 0))
        row["buttons"].append({"text": button.text(), "enabled": button.isEnabled(),
            "bounds": [point.x(), point.y(), button.width(), button.height()],
            "minimumWidthHint": button.minimumSizeHint().width(),
            "compressed": button.width() < button.minimumSizeHint().width(),
            "insideWindow": widget.rect().contains(point) and widget.rect().contains(
                point + QPoint(button.width() - 1, button.height() - 1))})
    # 「更多 ▾」等自适应入口是 QToolButton：单独记录，避免只检查 QPushButton 时漏掉。
    row["toolButtons"] = []
    for button in widget.findChildren(QToolButton):
        if not button.isVisibleTo(widget) or not button.text():
            continue
        point = button.mapTo(widget, QPoint(0, 0))
        row["toolButtons"].append({"text": button.text(), "enabled": button.isEnabled(),
            "bounds": [point.x(), point.y(), button.width(), button.height()],
            "minimumWidthHint": button.minimumSizeHint().width(),
            "compressed": button.width() < button.minimumSizeHint().width(),
            "insideWindow": widget.rect().contains(point) and widget.rect().contains(
                point + QPoint(button.width() - 1, button.height() - 1))})
    workspace = getattr(widget, "_content_workspace", None)
    editor = workspace.current_editor() if workspace is not None else None
    if editor is not None:
        text_editor = editor._editor
        point = text_editor.mapTo(widget, QPoint(0, 0))
        row["editorBounds"] = [point.x(), point.y(), text_editor.width(), text_editor.height()]
    metrics["views"].append(row)
    print(name, row["requested"], row["actual"], flush=True)


isolated_home = OUT / "isolated-user"
isolated_home.mkdir(exist_ok=True)
with patch("pathlib.Path.home", return_value=isolated_home), \
     patch.object(MainWindow, "_restore_geometry", lambda self: self.resize(1280, 720)):
    project = create_project(OUT / "sample-project", "general")
    source = standard_docx(OUT / "sample-import.docx")
    from doc_tool.domain.manifest import ProjectManifest
    manifest = ProjectManifest.load(project)
    manifest.documentName = "企业研发系统软件需求说明书"
    manifest.save(project, backup=False)
    chapter = project / "content/general/第1章 引言/1.1 目的.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# 目的\n\n说明文档维护与正式交付的范围。\n\n## 用户场景\n\n- 导入已有文档\n- 修改接口说明\n- 导出 Word 并打开\n\n| 参数 | 类型 | 说明 |\n| --- | --- | --- |\n| deviceId | String | 设备编号 |\n", encoding="utf-8")

    window = MainWindow()
    capture(window, "home-1280", 1280, 720)
    window._open_project_path(str(project))
    pump(2)
    if window._content_workspace is None:
        raise RuntimeError("Content workspace not initialized")
    workspace = window._content_workspace
    workspace.open_file("general/第1章 引言/1.1 目的.md")
    pump(1)
    capture(window, "editor-1280", 1280, 720)
    capture(window, "editor-1024", 1024, 640)
    capture(window, "editor-1920", 1920, 1080)
    window.resize(1280, 720)

    wizard = ImportWizard()
    wizard._source_page._on_file_selected(str(source))
    pump(2)
    capture(wizard, "import-source", 760, 560)
    wizard.hide()

    reuse = ReuseDialog(project)
    capture(reuse, "reuse-empty", 980, 620)
    reuse.hide()
    assist = AssistPanel(project_root=project)
    capture(assist, "assist-empty", 340, 640)
    assist.hide()

    from doc_tool.ui.export_results_view import ExportResultsView
    from doc_tool.ui.export_rounds import ExportRoundView, RoundFormatView
    from doc_tool.ui.delivery_form_dialog import DeliveryFormDialog
    html_path = OUT / "readable-result.html"
    html_path.write_text("<h1>审计样例</h1>", encoding="utf-8")
    result = ExportRoundView(
        round_id="audit-20261002-000001", capture_id="audit-capture", created_at="2026-10-02T00:00:00Z",
        project_root=str(project), source_mode="current-buffer", scope_text="所选 2 章",
        destination=str(OUT / "企业研发文档交付成果目录"),
        formats=[RoundFormatView(format="docx", status="pending-refresh", path=str(source), usable=True),
                 RoundFormatView(format="html", status="ready", path=str(html_path), usable=True),
                 RoundFormatView(format="pdf", status="pending-convert", message="没有可用的转换工具")],
        warnings=["Word 可以打开阅读，目录与页码待刷新。"], unsaved_chapters=[str(chapter)],
    )
    results = ExportResultsView()
    results.render([result])
    capture(results, "results-340", 340, 560)
    capture(results, "results-420", 420, 560)
    capture(results, "results-700", 700, 560)
    results.hide()
    batch = DeliveryFormDialog(initial_members=[str(project)], default_dir=str(OUT))
    capture(batch, "delivery-form", 800, 560)
    batch.hide()
    apply_theme(app, dark=True)
    capture(window, "editor-dark-1280", 1280, 720)
    window.hide()

(OUT / "widget-audit.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
print("Audit views:", len(metrics["views"]), flush=True)
os._exit(0)