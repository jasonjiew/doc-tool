# -*- coding: utf-8 -*-
"""CORE-A 1.3 入口测试：首页/文件菜单入口必须真实调用对应服务。

离屏运行 Qt，仅验证“入口调了哪条服务、结果怎么打开”，不重复验证服务内部
（服务本身由 ``test_core_intake_contract`` 覆盖）。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402


class _FakeSummary:
    is_writable = True
    project_root = ""
    manifest = None
    paths = None


class _FakeReimportService:
    calls = []

    def __init__(self, manifest, paths):
        self.manifest = manifest
        self.paths = paths

    def reimport(self, path):
        _FakeReimportService.calls.append(Path(path))

        class _Result:
            success = True
            changes = []
            conflicts = []
            message = ""
            error_code = ""

        return _Result()


class EntryWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("entries-ui")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        self._recent_patch = patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        )
        self._recent_patch.start()
        self._add_recent_patch = patch(
            "doc_tool.application.project_service.add_recent_project", return_value=None
        )
        self._add_recent_patch.start()
        _FakeReimportService.calls = []
        # 离屏环境下模态对话框会永久阻塞，统一替换为记录器
        self._info_patch = patch(
            "doc_tool.ui.main_window.QMessageBox.information",
            side_effect=lambda *a, **k: None,
        )
        self._info_patch.start()
        self.window = MainWindow()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        self._info_patch.stop()
        self._add_recent_patch.stop()
        self._recent_patch.stop()
        fixtures.cleanup(self.work)

    def _record_openers(self):
        opened = {"path": [], "window": []}
        self.window._open_project_path = lambda path: opened["path"].append(path)
        self.window._open_project_in_new_window = lambda path: opened["window"].append(path)
        return opened

    def test_home_new_project_button_uses_import_entry(self):
        self.assertEqual(
            self.window._empty_state._on_new_project, self.window._on_import_document
        )

    def test_markdown_import_creates_project_and_opens_it(self):
        first = self.work / "1 概述.md"
        first.write_text("# 概述\n\n正文。\n", encoding="utf-8")
        second = self.work / "2 设计.md"
        second.write_text("# 设计\n\n正文。\n", encoding="utf-8")
        opened = self._record_openers()
        with patch(
            "doc_tool.application.intake_entries.default_project_parent",
            return_value=self.out,
        ):
            self.window._on_import_document([first, second])
        self.assertEqual(len(opened["path"]), 1, opened)
        project = Path(opened["path"][0])
        self.assertTrue((project / "project.yml").is_file())
        manifest_text = (project / "project.yml").read_text(encoding="utf-8")
        self.assertLess(manifest_text.index("1 概述.md"), manifest_text.index("2 设计.md"))

    def test_docx_import_goes_to_wizard_with_selected_file(self):
        docx = fixtures.standard_docx(self.work / "标准.docx")
        seen = {}

        class _FakeWizard:
            def __init__(self, parent=None, initial_file=None):
                seen["initial_file"] = initial_file

            def run(self):
                seen["ran"] = True
                return None

        with patch("doc_tool.ui.wizard.ImportWizard", _FakeWizard):
            self.window._on_import_document([docx])
        self.assertEqual(seen.get("initial_file"), str(docx))
        self.assertTrue(seen.get("ran"))

    def test_open_project_docx_routes_to_reimport_not_new_project(self):
        docx = fixtures.standard_docx(self.work / "外部修改.docx")
        self.window._project_summary = _FakeSummary()
        with patch(
            "doc_tool.application.content.reimport.ReimportService", _FakeReimportService
        ):
            self.window._on_import_document([docx])
        self.assertEqual(_FakeReimportService.calls, [docx])

    def test_unsupported_input_warns_without_service_call(self):
        bogus = self.work / "x.zip"
        bogus.write_bytes(b"PK")
        warned = []
        with patch(
            "doc_tool.ui.main_window.QMessageBox.warning",
            side_effect=lambda *a, **k: warned.append(a),
        ):
            self.window._on_import_document([bogus])
        self.assertEqual(len(warned), 1)

    def test_pack_entry_calls_real_pack_service(self):
        pack = self.work / "pack"
        pack.mkdir()
        recorded = {}

        class _Result:
            ok = True
            project_root = self.work / "pack-project"
            errors = []
            warnings = []

        def _fake_create(pack_source, project_root, **kwargs):
            recorded["pack_source"] = str(pack_source)
            recorded["target"] = str(project_root)
            return _Result()

        opened = self._record_openers()
        with patch(
            "doc_tool.ui.main_window.QFileDialog.getExistingDirectory",
            return_value=str(pack),
        ), patch(
            "doc_tool.application.intake_entries.default_project_parent",
            return_value=self.out,
        ), patch(
            "doc_tool.application.project_from_pack.create_project_from_pack",
            _fake_create,
        ):
            self.window._on_create_from_pack()
        self.assertEqual(recorded.get("pack_source"), str(pack))
        self.assertTrue(str(recorded.get("target", "")).startswith(str(self.out)))
        self.assertEqual(len(opened["path"]), 1)

    def test_markdown_entry_uses_selected_files_in_order(self):
        first = self.work / "甲.md"
        first.write_text("# 甲\n", encoding="utf-8")
        second = self.work / "乙.md"
        second.write_text("# 乙\n", encoding="utf-8")
        opened = self._record_openers()
        with patch(
            "doc_tool.ui.main_window.QFileDialog.getOpenFileNames",
            return_value=([str(first), str(second)], ""),
        ), patch(
            "doc_tool.application.intake_entries.default_project_parent",
            return_value=self.out,
        ):
            self.window._on_create_from_markdown()
        self.assertEqual(len(opened["path"]), 1)
        manifest_text = (Path(opened["path"][0]) / "project.yml").read_text(encoding="utf-8")
        self.assertLess(manifest_text.index("甲.md"), manifest_text.index("乙.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)