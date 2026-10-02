# -*- coding: utf-8 -*-
"""复核补测：CORE 3.2 按对象判降级 + 标题前对象；V3.2 逐项进度进入任务面板。"""

from __future__ import annotations

import os
import sys
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


def _docx_with_mixed_objects(path: Path, *, pre_title: bool = False) -> Path:
    """段落里同时有文字与脚注引用（不可降级）+ 公式（可降级）；可选标题前的无文本文本框。"""
    fixtures.build_docx(path, [("h1", "第1章 引言"), ("h2", "1.1 目的"), ("p", "正文段落。")])
    import shutil
    import tempfile

    work = Path(tempfile.mkdtemp(prefix="doc-tool-mixed-"))
    try:
        with zipfile.ZipFile(path) as archive:
            data = {name: archive.read(name) for name in archive.namelist()}
        document = data["word/document.xml"].decode("utf-8")
        footnote_para = (
            '<w:p><w:r><w:t>带脚注的正文</w:t></w:r>'
            '<w:r><w:footnoteReference w:id="1"/></w:r></w:p>'
        )
        if pre_title:
            textbox = (
                '<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent/></v:textbox>'
                '</v:shape></w:pict></w:r></w:p>'
            )
            document = document.replace("<w:body>", "<w:body>" + textbox, 1)
        document = document.replace("</w:body>", footnote_para + "</w:body>")
        data["word/document.xml"] = document.encode("utf-8")
        target = work / path.name
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in data.items():
                archive.writestr(name, payload)
        shutil.copy2(target, path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return path


class UnsupportedClassificationTests(unittest.TestCase):
    """脚注/尾注/批注/OLE 不得因“同段有文字”被记成文本降级。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("core-unsup-class")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _intake(self, name: str, *, pre_title: bool = False):
        from doc_tool.application.intake_entries import run_intake

        source = _docx_with_mixed_objects(self.work / name, pre_title=pre_title)
        outcome = run_intake(source, parent_dir=self.work, target_name=name.replace(".docx", ""))
        self.assertTrue(outcome.ok, outcome.errors)
        return Path(outcome.project_root)

    def test_footnote_in_text_paragraph_is_placeholder_not_degraded(self):
        from doc_tool.application.import_record import read_import_record

        project = self._intake("脚注.docx")
        record = read_import_record(project)
        self.assertIsNotNone(record)
        footnotes = [item for item in record.findings if item.feature == "footnote"]
        self.assertTrue(footnotes, [item.feature for item in record.findings])
        self.assertTrue(
            all(item.handling == "placeholder" for item in footnotes),
            [(item.feature, item.handling) for item in footnotes],
        )
        self.assertTrue(all(not item.editable for item in footnotes))
        self.assertTrue(any(item.target_chapter for item in footnotes), "应带章节定位")
        content = project / "content" / "general"
        bodies = "".join(
            path.read_text(encoding="utf-8") for path in content.rglob("*.md")
            if path.name != "_revision_record.md"
        )
        self.assertIn("脚注", bodies, "正文应出现脚注占位")
        self.assertIn("待完善", bodies)

    def test_pre_title_textbox_with_retention_gets_fact_and_placeholder(self):
        """开启标题前正文保留时，标题前的无文本对象也要有事实 + 可见占位。"""
        from doc_tool.adapters.importer import extract_content

        source = _docx_with_mixed_objects(self.work / "标题前文本框.docx", pre_title=True)
        out = self.work / "retained"
        extraction = extract_content(
            source, out / "content" / "general",
            out / "assets" / "general" / "images", out / "assets" / "general" / "tables",
            "general", retain_pre_title_body=True,
        )
        entries = [item for item in extraction.unsupported_map if item["feature"] == "textbox"]
        self.assertTrue(entries, extraction.unsupported_map)
        self.assertEqual(entries[0]["handling"], "placeholder", entries[0])
        self.assertTrue(entries[0]["chapter"], "应归入前言章节")
        bodies = "".join(
            path.read_text(encoding="utf-8") for path in (out / "content" / "general").rglob("*.md")
        )
        self.assertIn("文本框", bodies)
        self.assertIn("待完善", bodies)

    def test_pre_title_object_still_lands_in_ledger_by_default(self):
        """默认不保留标题前正文时，对象仍进待完善清单（不静默丢失）。"""
        from doc_tool.application.import_record import read_import_record

        project = self._intake("默认丢前言.docx", pre_title=True)
        record = read_import_record(project)
        entries = [item for item in record.findings if item.feature == "textbox"]
        self.assertTrue(entries, "默认策略下也应有事实记录")
        self.assertTrue(all(not item.editable for item in entries), entries)


class DeliveryStageReachesPanelTests(unittest.TestCase):
    """V3.2 2.2：逐项阶段事件必须进入任务面板（此前只处理终态）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_stage_event_updates_stage_events_and_dock_log(self):
        from unittest.mock import patch

        from doc_tool.ui.main_window import MainWindow
        from doc_tool.ui.task_bridge import TaskEvent

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            window = MainWindow()
        try:
            window._stage_events = []
            window._on_task_event(TaskEvent(
                kind="stage", stage="delivery:started", status="running",
                detail="Alpha：开始生成 Word", metrics={"jobId": "j1"},
            ))
            self.assertTrue(window._stage_events, "阶段事件应被记录")
            entry = window._stage_events[-1]
            self.assertEqual(entry["stage"], "delivery:started")
            self.assertIn("Alpha", entry["detail"])
            # 逐项明细必须在界面可见（任务面板日志或状态栏）
            dock = getattr(window, "_task_dock", None)
            visible = window._status_label.text()
            for accessor in ("log_text",):
                getter = getattr(dock, accessor, None)
                if callable(getter):
                    try:
                        visible = getter() or visible
                    except Exception:  # noqa: BLE001
                        pass
            self.assertIn("Alpha", visible, visible)
            self.assertTrue(
                "delivery:started" in visible or "Alpha" in window._progress_recent_stage,
                (visible, window._progress_recent_stage),
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)