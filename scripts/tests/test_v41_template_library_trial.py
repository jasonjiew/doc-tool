# -*- coding: utf-8 -*-
"""V4.1 41-D 4.2：列表详情提供试用小样、使用此模板与最近成果。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from PySide6.QtWidgets import QApplication  # noqa: E402

from doc_tool.ui.template_library_dialog import TemplateLibraryDialog  # noqa: E402

TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"
PACK_YML = (
    "schemaVersion: 1\n"
    "packId: {pack_id}\n"
    "version: 1.0.0\n"
    "documentKind: requirement\n"
    "description: 试用测试包\n"
)


class _Host:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.status = []
        self.opened = []
        self.drafts = []

    def tl_state_dir(self):
        return self.root / ".state"

    def tl_project_root(self):
        return str(self.root / "proj")

    def tl_project_writable(self):
        return True

    def tl_project_chapters(self):
        return []

    def tl_open_path(self, path):
        self.opened.append(str(path))

    def tl_status(self, message):
        self.status.append(str(message))

    def tl_open_pack_draft(self, path):
        self.drafts.append(str(path))


class TrialSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-trial-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.standards = self.work / "standards"
        pack = self.standards / "generic-requirement"
        (pack / "skeleton").mkdir(parents=True, exist_ok=True)
        (pack / "skeleton" / "1 引言.md").write_text("# 引言\n", encoding="utf-8")
        (pack / "pack.yml").write_text(
            PACK_YML.format(pack_id="generic-requirement"), encoding="utf-8"
        )
        shutil.copy2(TEMPLATE, pack / "template.docx")
        self.templates = self.work / "templates"
        self.templates.mkdir(parents=True, exist_ok=True)
        self.host = _Host(self.work)
        self.dialog = TemplateLibraryDialog(
            self.host, roots=[self.standards], templates_root=self.templates,
            state_dir=self.work / ".state", project_root=str(self.work / "proj"),
        )
        self.addCleanup(self.dialog.close)
        self.dialog.reload()
        QApplication.processEvents()

    def _reload(self):
        self.dialog.reload()
        QApplication.processEvents()

    def _select_export_entry(self):
        """选中带 template.docx 的项目出稿条目（试用依赖真实底模）。"""
        self.dialog.use_combo.setCurrentIndex(
            self.dialog.use_combo.findData("export")
        )
        QApplication.processEvents()
        entries = self.dialog.filtered_entries()
        self.assertTrue(entries, "应存在项目出稿条目")
        self.dialog.entry_list.setCurrentRow(0)
        QApplication.processEvents()
        return self.dialog.selected_entry()

    def test_sample_button_enabled_only_with_real_template(self):
        entry = self._select_export_entry()
        self.assertIsNotNone(entry)
        self.assertTrue(self.dialog.sample_btn.isEnabled(), "有底模时试用可用")
        # 换一个没有可解析底模的条目时必须禁用试用（避免生成无底模的小样）
        self.dialog.use_combo.setCurrentIndex(self.dialog.use_combo.findData("skeleton"))
        QApplication.processEvents()
        if self.dialog.filtered_entries():
            self.dialog.entry_list.setCurrentRow(0)
            QApplication.processEvents()
            skeleton = self.dialog.selected_entry()
            expected = bool(skeleton is not None and self.dialog._template_path_for(skeleton))
            self.assertEqual(
                self.dialog.sample_btn.isEnabled(), expected,
                "试用可用性必须与「是否真有可解析底模」一致：{0}".format(
                    getattr(skeleton, "source", "")
                ),
            )

    def test_trial_creates_isolated_sample_without_touching_project(self):
        entry = self._select_export_entry()
        before = sorted(
            path.relative_to(self.standards).as_posix()
            for path in self.standards.rglob("*") if path.is_file()
        )
        self.dialog._on_try_sample()
        QApplication.processEvents()
        outcome = self.dialog._last_sample
        self.assertIsNotNone(outcome, "试用应产生真实结果")
        self.assertTrue(outcome.ok, outcome.warnings)
        sample_dir = Path(outcome.directory)
        self.assertTrue(sample_dir.is_dir())
        # 隔离目录：位于项目 .state/template-samples 下，不写业务目录
        self.assertIn("template-samples", sample_dir.as_posix())
        manifest = json.loads((sample_dir / "sample.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["sampleIsGeneric"], "默认小样不得带业务正文")
        self.assertFalse(manifest["businessTextIncluded"])
        # 规范包与项目正文未被改动
        after = sorted(
            path.relative_to(self.standards).as_posix()
            for path in self.standards.rglob("*") if path.is_file()
        )
        self.assertEqual(before, after, "试用不得改动规范包")
        self.assertTrue(self.host.opened, "试用应给出可打开的小样路径")
        self.assertIn(str(outcome.docxPath), self.host.opened)

    def test_recent_results_lists_real_paths_and_reuse(self):
        self._select_export_entry()
        self.assertFalse(self.dialog.recent_btn.isEnabled(), "未试用前没有最近成果")
        self.dialog._on_try_sample()
        QApplication.processEvents()
        self.assertTrue(self.dialog.recent_btn.isEnabled(), "试用后应可查看最近成果")
        first_dir = self.dialog._last_sample.directory
        # 同设置再试用一次：复用同一小样目录（不重复生成）
        self.dialog._on_try_sample()
        QApplication.processEvents()
        self.assertTrue(self.dialog._last_sample.reused, "同模板/映射/版式应复用既有小样")
        self.assertEqual(self.dialog._last_sample.directory, first_dir)
        self.dialog._on_show_recent()
        QApplication.processEvents()
        text = "\n".join(self.dialog._notes)
        self.assertIn("最近成果", text)
        self.assertIn(first_dir, text)

    def test_trial_failure_reports_and_keeps_project(self):
        entry = self._select_export_entry()
        # 底模被删：试用必须给出可读原因且不改项目
        Path(entry.templatePath).unlink()
        self._reload()
        self.dialog.use_combo.setCurrentIndex(self.dialog.use_combo.findData("export"))
        QApplication.processEvents()
        if self.dialog.filtered_entries():
            self.dialog.entry_list.setCurrentRow(0)
            QApplication.processEvents()
        self.dialog._on_try_sample()
        QApplication.processEvents()
        self.assertFalse(self.dialog.recent_btn.isEnabled(), "失败不得产生最近成果")
        self.assertTrue(
            ("未生成" in self.dialog.status_text())
            or ("没有可用的底模文件" in self.dialog.status_text()),
            "失败必须给出可读原因：{0}".format(self.dialog.status_text()),
        )

    def test_primary_action_still_the_direct_export_path(self):
        """「使用此模板」仍是既有出稿流程，不要求先做规范制作。"""
        entry = self._select_export_entry()
        self.assertTrue(self.dialog.primary_btn.isEnabled())
        opened = {}
        with patch(
            "doc_tool.ui.template_library_dialog.TemplateFillDialog",
            side_effect=lambda **kwargs: opened.update(kwargs) or _StubDialog(),
        ):
            self.dialog._on_primary()
        self.assertTrue(opened, "主动作应打开既有底模出稿流程")
        self.assertTrue(str(opened.get("template", "")).endswith(".docx"))


class _StubDialog:
    def exec(self):
        return 0


if __name__ == "__main__":
    unittest.main(verbosity=2)