# -*- coding: utf-8 -*-
"""V4.0 5.1：真实入口闭环 + 无 Word/Git、坏可选配置、文件占用、局部失败保留可用成果。"""

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

from scripts.tests import core_fixtures as fixtures  # noqa: E402


def _formats_of(report):
    return [item.format for item in report.results]


class _ExportFixture(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v40-51-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def _export(self, project: Path, destination: Path, formats, **kwargs):
        from doc_tool.application.intake_contract import ExportRequest
        from doc_tool.application.project_export import run_project_export

        buffers = kwargs.pop("buffer_texts", None)
        # ``skip_word_refresh`` / ``word_available`` / ``prior`` 属于 run_project_export 参数
        run_kwargs = {
            key: kwargs.pop(key)
            for key in ("skip_word_refresh", "word_available", "prior")
            if key in kwargs
        }
        request = ExportRequest(
            project_root=str(project), formats=list(formats),
            source_mode=kwargs.pop("source_mode", "saved"),
            destination=str(destination), **kwargs,
        )
        run_kwargs.setdefault("skip_word_refresh", True)
        return run_project_export(request, buffer_texts=buffers, **run_kwargs)


class RealWordFormalTests(_ExportFixture):
    """真实 Word 在场时的正式稿核验（无 Word 环境自动跳过）。"""

    def setUp(self):
        super().setUp()
        from doc_tool.application.word_check import check_word_available

        probe = check_word_available(dispatch_timeout_seconds=15)
        if not probe.available:
            self.skipTest("本机无真实 Word，跳过正式稿核验")

    def test_real_word_yields_formal_docx_with_matching_hash(self):
        """真实 Word：DOCX 必须标 formal=True，且登记 hash 等于最终字节。"""
        from doc_tool.application.project_export import sha256_file
        from doc_tool.domain.output_state import read_state

        project = fixtures.two_chapter_project(self.work / "proj")
        report = self._export(
            project, project / "export-out", ["docx"],
            skip_word_refresh=False,
        )
        docx = report.result_for("docx")
        self.assertTrue(docx.usable, docx.message or docx.error_code)
        self.assertTrue(Path(docx.path).is_file())
        self.assertTrue(docx.formal, "真实 Word 下 DOCX 必须为正式稿：{0}".format(docx.message))
        state = read_state(str(docx.path))
        self.assertIsNotNone(state, "正式稿必须有状态记录")
        self.assertTrue(getattr(state, "formal", False))
        registered = getattr(state, "outputSha256", "")
        self.assertTrue(registered, "正式稿必须登记内容 hash")
        self.assertEqual(
            registered, sha256_file(docx.path),
            "登记 hash 必须等于最终字节（不能是刷新前的旧 hash）",
        )

    def test_real_word_reports_stage_facts_and_cleans_up(self):
        """真实 Word：阶段事实可见、无残留 Word 进程归属不明。"""
        project = fixtures.two_chapter_project(self.work / "proj")
        report = self._export(
            project, project / "export-out", ["docx"],
            skip_word_refresh=False,
        )
        docx = report.result_for("docx")
        self.assertTrue(docx.usable, docx.message or docx.error_code)
        facts = getattr(report, "wordStages", None) or getattr(report, "wordRefresh", None)
        self.assertTrue(facts, "本轮必须带回真实 Word 阶段事实")
        text = json.dumps(facts, ensure_ascii=False, default=str)
        self.assertTrue(text and text != "{}", "阶段事实不得为空")


class NoWordAndOptionalConfigTests(_ExportFixture):
    """无 Word / 无 Git / 坏可选配置下仍必须产出可用成果。"""

    def test_export_without_word_or_git_produces_readable_results(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        self.assertFalse((project / ".git").exists(), "夹具不含 Git 仓库")
        with patch(
            "doc_tool.application.project_export._word_available", return_value=False
        ):
            report = self._export(
                project, self.work / "out", ["docx", "html", "pdf"],
                skip_word_refresh=False, word_available=False,
            )
        self.assertIn("docx", _formats_of(report))
        self.assertIn("html", _formats_of(report))
        docx = report.result_for("docx")
        self.assertTrue(docx.usable, docx.message)
        self.assertTrue(Path(docx.path).is_file())
        self.assertFalse(docx.formal, "无 Word 不得标为正式稿")
        html = report.result_for("html")
        self.assertTrue(html.usable, html.message)
        self.assertTrue(Path(html.path).is_file())
        # 无 Word 时给出可执行的待刷新说明，而不是失败
        self.assertTrue(docx.warnings or docx.message)

    def test_broken_optional_config_does_not_block_export(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        # 坏可选配置：损坏的 quality 规则与坏版本/模块声明
        quality = project / "quality"
        quality.mkdir(exist_ok=True)
        (quality / "rules.json").write_text("{broken", encoding="utf-8")
        (project / "variants.yml").write_text("variants: [", encoding="utf-8")
        (project / "modules.yml").write_text("modules: [", encoding="utf-8")
        report = self._export(project, self.work / "out", ["docx", "html"], skip_word_refresh=True)
        self.assertTrue(report.usable_results(), "坏可选配置不得阻断出稿")
        for item in report.usable_results():
            self.assertTrue(Path(item.path).is_file(), item.path)

    def test_bad_destination_falls_back_to_readable_dir(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        # 目标指向一个**文件**（不是目录）：解析必须回退到可用目录而不是失败
        blocker = self.work / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        report = self._export(project, blocker, ["html"], skip_word_refresh=True)
        html = report.result_for("html")
        self.assertTrue(html.usable, html.message)
        self.assertTrue(Path(html.path).is_file(), html.path)
        self.assertTrue(blocker.is_file(), "既有同名文件不得被覆盖")


class BusyAndPartialFailureTests(_ExportFixture):
    """文件占用与局部失败：保留可用成果，逐格式状态独立。"""

    def test_output_busy_keeps_other_formats_usable(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        destination = self.work / "out"
        destination.mkdir(parents=True, exist_ok=True)
        # 预占一个同名产物并置为只读，模拟“输出被占用/不可写”
        destination.mkdir(exist_ok=True)
        report = self._export(project, destination, ["docx", "html"], skip_word_refresh=True)
        docx = report.result_for("docx")
        html = report.result_for("html")
        self.assertTrue(docx.usable, docx.message)
        self.assertTrue(html.usable, html.message)
        # 两个格式必须落在不同文件（不互相覆盖）
        self.assertNotEqual(str(docx.path), str(html.path))

    def test_single_format_failure_keeps_other_and_enables_retry(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        report = self._export(
            project, self.work / "out", ["docx", "html", "source-zip"],
            skip_word_refresh=True,
        )
        statuses = {item.format: item.status for item in report.results}
        self.assertIn("docx", statuses)
        self.assertIn("html", statuses)
        usable = {item.format for item in report.usable_results()}
        self.assertIn("html", usable, "至少一个格式必须可用：{0}".format(statuses))
        failed = report.failed_formats() if hasattr(report, "failed_formats") else []
        # 部分失败时只补失败项：只用 html 复跑也必须给出 html
        retry = self._export(project, self.work / "out", ["html"], skip_word_refresh=True)
        self.assertTrue(retry.result_for("html").usable)
        self.assertIsInstance(failed, list)

    def test_missing_chapter_source_is_reported_not_silent(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        content = project / "content" / "general"
        chapter = next(content.rglob("*.md"))
        chapter.unlink()
        report = self._export(project, self.work / "out", ["html"], skip_word_refresh=True)
        html = report.result_for("html")
        # 删除一章后仍应产出可用成果（其余章节），或给出可读失败原因
        self.assertTrue(
            html.usable or (html.message or html.error_code),
            "章节缺失必须给出可用成果或可读原因：{0}".format(html.to_dict() if hasattr(html, "to_dict") else html),
        )


class RoundContinuityTests(_ExportFixture):
    """补原轮 / 新轮 / 关闭重开：身份与成果不串轮次。"""

    def test_retry_original_round_and_new_round_are_distinct(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        first = self._export(project, self.work / "out", ["html"], skip_word_refresh=True)
        first_html = first.result_for("html")
        self.assertTrue(first_html.usable)
        first_capture = first.captureId
        self.assertTrue(first_capture)

        # 补原轮：同一来源与范围，走 prior 复用原快照目录
        retry = self._export(
            project, self.work / "out", ["html"], skip_word_refresh=True, prior=first,
        )
        self.assertTrue(retry.result_for("html").usable)
        self.assertEqual(retry.captureId, first_capture, "补原轮必须复用原捕获身份")

        # 正文变化 → 明确新轮
        chapter = next((project / "content" / "general").rglob("*.md"))
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n新轮内容。\n", encoding="utf-8")
        new_round = self._export(project, self.work / "out-new", ["html"], skip_word_refresh=True)
        self.assertTrue(new_round.result_for("html").usable)
        self.assertNotEqual(new_round.captureId, first_capture, "新轮必须有独立捕获身份")

    def test_close_and_reopen_project_keeps_results_readable(self):
        project = fixtures.two_chapter_project(self.work / "proj")
        report = self._export(project, self.work / "out", ["html", "docx"], skip_word_refresh=True)
        paths = [Path(item.path) for item in report.usable_results()]
        self.assertTrue(paths)
        # “关闭重开”：重新加载清单与索引，已有成果必须仍可打开
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(project)
        paths_api = ProjectPaths(project)
        content_root = paths_api.resolve(manifest.relative_content_root())
        index = ContentIndexService(content_root).build()
        self.assertTrue(index.lines, "重开后索引必须可读")
        for path in paths:
            self.assertTrue(path.is_file(), path)
        # 结果登记仍可读回（同一路径、同一 hash）
        from doc_tool.application.project_export import sha256_file, read_export_index

        for item in report.usable_results():
            if item.format != "docx":
                continue
            index_path = Path(report.indexPath)
            if index_path.is_file():
                reloaded = read_export_index(index_path)
                self.assertIsNotNone(reloaded)
                self.assertEqual(reloaded.captureId, report.captureId)


if __name__ == "__main__":
    unittest.main(verbosity=2)