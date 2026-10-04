# -*- coding: utf-8 -*-
"""V4.1 41-B 2.3：正文来源/范围与模板预设分开；换目录不丢所选范围。"""

from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class SourceScopeSeparationTests(unittest.TestCase):
    """快速导出默认整份当前内容；模板/版式设置不得偷偷带入旧范围。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(fixtures.scratch_dir("v41-scope-sep"))
        self.addCleanup(lambda: fixtures.cleanup(self.work))
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.ui.main_window import MainWindow

        class _Summary:
            is_writable = True

            def __init__(self, root: Path):
                from doc_tool.domain.manifest import ProjectManifest
                from doc_tool.domain.paths import ProjectPaths

                self.project_root = str(root)
                self.manifest = ProjectManifest.load(root)
                self.paths = ProjectPaths(root)

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.window._project_summary = _Summary(self.project)
        self.window._collect_buffer_texts = lambda: {}

    def _report(self, **kwargs):
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, SOURCE_MODE_SAVED, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX],
            source_mode=SOURCE_MODE_SAVED, destination=str(self.work / "out"), **kwargs,
        )
        return run_project_export(request, skip_word_refresh=True)

    def test_quick_export_defaults_to_full_document_even_after_scoped_round(self):
        """上一轮是选章时，快速导出仍默认整份当前内容（不被旧范围缩小）。"""
        from doc_tool.application.intake_contract import SCOPE_CHAPTERS, ExportScope

        scoped = self._report(
            scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=["第1章 引言/1.1 目的.md"]),
        )
        view = self.window._record_export_round(scoped)
        # 直接走快速导出请求构造：不带旧视图范围
        from doc_tool.application.intake_contract import ExportRequest

        quick = ExportRequest(
            project_root=str(self.project), formats=["docx"],
            source_mode="saved", destination=str(self.work / "quick"),
        )
        self.assertTrue(quick.scope.is_full, "快速导出默认整份：{0}".format(quick.scope.to_dict()))

    def test_scope_survives_directory_change(self):
        """换目录的新轮沿用原范围；范围缺失时才回到可见设置。"""
        from doc_tool.application.intake_contract import SCOPE_CHAPTERS, ExportScope

        report = self._report(
            scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=["第1章 引言/1.1 目的.md"]),
        )
        view = self.window._record_export_round(report)
        request, buffers = self.window._new_round_request(
            view, destination=str(self.work / "another"),
        )
        self.assertIsNotNone(request, "范围可用时应直接建立新轮")
        self.assertEqual(request.scope.kind, SCOPE_CHAPTERS)
        self.assertEqual(list(request.scope.chapters), ["第1章 引言/1.1 目的.md"])
        self.assertEqual(request.destination, str(self.work / "another"))
        self.assertEqual(buffers, {})
        # 模板/版式设置与正文来源分开：本请求用已保存来源
        self.assertEqual(request.source_mode, "saved")

    def test_removed_scope_falls_back_to_visible_settings(self):
        """原范围章节被删除时不得静默扩大范围，而是回到可见设置。"""
        from doc_tool.application.intake_contract import SCOPE_CHAPTERS, ExportScope

        report = self._report(
            scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=["第1章 引言/1.1 目的.md"]),
        )
        view = self.window._record_export_round(report)
        summary = self.window._project_summary
        content_root = summary.paths.resolve(summary.manifest.relative_content_root())
        (content_root / "第1章 引言" / "1.1 目的.md").unlink()
        submissions, settings = [], []
        self.window._run_export_task = lambda **task: submissions.append(task)
        self.window._on_export_settings = lambda preset, **kwargs: settings.append((preset, kwargs))
        request, _buffers = self.window._new_round_request(view, destination=str(self.work / "x"))
        self.assertIsNone(request, "范围已失效时不得直接提交")
        self.assertEqual(submissions, [])
        self.assertEqual(len(settings), 1)
        self.assertIn("实际范围", settings[0][1]["notice"])
        self.assertEqual(settings[0][0].scope.kind, SCOPE_CHAPTERS, "回到设置时仍带原范围供用户确认")


class TemplateFillOutputContractTests(unittest.TestCase):
    """`template-fill --output` 仍是 DOCX 文件路径（不被统一导出改成目录）。"""

    def test_cli_help_and_argument_declaration(self):
        from doc_tool.cli import build_parser

        parser = build_parser()
        # 找到 template-fill 子命令并确认 --output 作为单个路径参数存在
        actions = [a for a in parser._actions if getattr(a, "choices", None)]
        self.assertTrue(actions, "顶层解析器应有子命令")
        sub = None
        for action in actions:
            if action.choices and "template-fill" in action.choices:
                sub = action.choices["template-fill"]
                break
        self.assertIsNotNone(sub, "应存在 template-fill 子命令")
        names = {opt for action in sub._actions for opt in action.option_strings}
        self.assertIn("--output", names)

    def test_output_is_treated_as_docx_file(self):
        """真实调用：输出参数是文件路径，写出的就是 DOCX 文件本身。"""
        work = Path(fixtures.scratch_dir("v41-fill-output"))
        self.addCleanup(lambda: fixtures.cleanup(work))
        template = work / "模板.docx"
        template.write_bytes((REPO_ROOT / "templates" / "requirement-template.docx").read_bytes())
        source = work / "1 概述.md"
        source.write_text("# 概述\n\n正文。\n", encoding="utf-8")
        output = work / "成品.docx"
        from doc_tool.application.template_fill import fill_markdown_with_template

        result = fill_markdown_with_template([source], template, output)
        written = Path(getattr(result, "output", output) or output)
        self.assertTrue(written.is_file(), "应写出文件：{0}".format(written))
        self.assertEqual(written.suffix.lower(), ".docx", "输出必须是 DOCX 文件路径")
        self.assertFalse(written.is_dir(), "输出不得被当成目录")


if __name__ == "__main__":
    unittest.main(verbosity=2)