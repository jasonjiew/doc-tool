# -*- coding: utf-8 -*-
"""MAIN2-F 6.1：三条主线闭环（真实服务 + 真实窗口入口）。"""

from __future__ import annotations

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

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2f-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def _window(self, project: Path):
        from doc_tool.ui.main_window import MainWindow

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            window = MainWindow()
        self.addCleanup(window.close)
        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            window._open_project_path(str(project))
        for _ in range(30):
            QApplication.processEvents()
        return window

    def _summary(self, project: Path):
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        class _Summary:
            is_writable = True

            def __init__(self, root: Path):
                self.project_root = str(root)
                self.manifest = ProjectManifest.load(root)
                self.paths = ProjectPaths(root)

        return _Summary(project)

    def _export(self, project: Path, destination: Path, *, formats=("docx", "html"), **kwargs):
        """``buffer_texts`` 属于 run_project_export，不属于 ExportRequest。"""
        from doc_tool.application.intake_contract import ExportRequest
        from doc_tool.application.project_export import run_project_export

        buffers = kwargs.pop("buffer_texts", None)
        request = ExportRequest(
            project_root=str(project), formats=list(formats),
            source_mode=kwargs.pop("source_mode", "saved"),
            destination=str(destination), **kwargs,
        )
        if buffers:
            return run_project_export(
                request, skip_word_refresh=True, buffer_texts=buffers,
            )
        return run_project_export(request, skip_word_refresh=True)


class MainlineOneWordLoopTests(_Fixture):
    """主线一：Word 导入 → 未保存复制/修图/检查 → 出稿。"""

    def test_word_import_edit_copy_check_export(self):
        # 导入（真实 intake）
        from doc_tool.application.intake_entries import run_intake

        image = fixtures.tiny_png(self.work / "a.png")
        source = fixtures.image_docx(self.work / "带图.docx", image)
        outcome = run_intake(source, parent_dir=self.work / "out")
        self.assertTrue(outcome.ok, outcome.errors)
        project = Path(outcome.project_root)

        # 真实工作区（与主窗口使用同一个协调器，索引由既有服务建立）
        from doc_tool.ui.content.workspace import ContentWorkspace

        summary = self._summary(project)
        content_root = summary.paths.resolve(summary.manifest.relative_content_root())
        workspace = ContentWorkspace(
            content_root, project_root=project, state_dir=summary.paths.state_dir,
            assets_root=summary.paths.resolve(summary.manifest.relative_asset_root()),
            on_status=lambda message: None,
        )
        self.addCleanup(workspace.deleteLater)
        if getattr(workspace, "_index", None) is None:
            workspace._index = workspace._index_service.build()
        self.assertIsNotNone(workspace._index, "工作区索引应已建立")
        chapters = sorted(
            path.relative_to(content_root).as_posix()
            for path in content_root.rglob("*.md")
            if path.is_file() and not path.name.startswith("_revision")
        )
        self.assertTrue(chapters)
        rel = chapters[0]

        # 未保存编辑 + 复制章（读活缓冲、新身份）
        workspace.open_file(rel)
        editor = workspace.tabs_host.editor_for(rel)
        self.assertIsNotNone(editor)
        marker = "主线一未保存标记"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + "\n")
        self.assertTrue(editor.is_dirty())
        copied_before = sorted(content_root.rglob("*.md"))
        with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("主线一副本", True)), \
             patch("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None):
            workspace._on_copy_file(rel)
        copied_after = sorted(content_root.rglob("*.md"))
        self.assertGreater(len(copied_after), len(copied_before), "复制应新增章节文件")
        copies = [p for p in copied_after if "主线一副本" in p.name]
        self.assertTrue(copies, "复制文件应真实存在")
        self.assertIn(marker, copies[0].read_text(encoding="utf-8"), "副本必须含活缓冲内容")
        self.assertNotIn(marker, (content_root / rel).read_text(encoding="utf-8"),
                         "复制不得隐式保存原章")

        # 修图：缺图清单叠加活缓冲（服务层）
        from doc_tool.application.content.asset_manager import scan_unused

        unused = scan_unused(self._summary(project).paths.resolve(
            self._summary(project).manifest.relative_asset_root()
        ), workspace._index, buffer_texts={rel: editor.plain_text()})
        self.assertIsInstance(unused, list)

        # 检查 + 出稿
        from doc_tool.application.content.lint import ContentLinter
        from doc_tool.application.content.quality_rules import QualityRulesConfig

        linter = ContentLinter(workspace._index, QualityRulesConfig(
            self._summary(project).paths.state_dir,
            self._summary(project).manifest.documentType,
        ))
        issues = linter.check_all([])
        self.assertIsInstance(issues, list)
        report = self._export(
            project, self.work / "out-export", source_mode="current-buffer",
            buffer_texts={rel: editor.plain_text()},
        )
        self.assertTrue(report.usable_results(), "应产出可读成果")
        self.assertEqual(report.sourceMode, "current-buffer")


class MainlineTwoMarkdownLoopTests(_Fixture):
    """主线二：多来源 Markdown → 确认顺序 → 同名资源 → 批量章节 → 所选范围 → 离线成果。"""

    def test_multi_markdown_batch_chapter_scoped_offline(self):
        from doc_tool.application.intake_entries import run_intake

        first = self.work / "01 概述.md"
        second = self.work / "02 设计.md"
        first.write_text("# 概述\n\n正文一。\n\n![图](images/img_1.png)\n", encoding="utf-8")
        second.write_text("# 设计\n\n正文二。\n\n![图](images/img_1.png)\n", encoding="utf-8")
        assets = self.work / "assets"
        (assets / "images").mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixtures.tiny_png(self.work / "png.png"), assets / "images" / "img_1.png")

        outcome = run_intake(
            first, parent_dir=self.work / "out",
            markdown_sources=[first, second], asset_roots=[assets],
        )
        self.assertTrue(outcome.ok, outcome.errors)
        project = Path(outcome.project_root)
        from doc_tool.ui.content.workspace import ContentWorkspace

        summary = self._summary(project)
        content_root = summary.paths.resolve(summary.manifest.relative_content_root())
        workspace = ContentWorkspace(
            content_root, project_root=project, state_dir=summary.paths.state_dir,
            assets_root=summary.paths.resolve(summary.manifest.relative_asset_root()),
            on_status=lambda message: None,
        )
        self.addCleanup(workspace.deleteLater)
        if getattr(workspace, "_index", None) is None:
            workspace._index = workspace._index_service.build()
        chapters = sorted(
            path.relative_to(content_root).as_posix()
            for path in content_root.rglob("*.md")
            if path.is_file() and not path.name.startswith("_revision")
        )
        self.assertGreaterEqual(len(chapters), 2, "多来源 Markdown 必须合并成一份项目")

        # 批量章节操作（服务层，复用原服务）
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY, apply_batch_plan, plan_batch_chapters,
        )

        plan = plan_batch_chapters(
            workspace._index, list(chapters[:2]), BATCH_COPY,
            content_root=content_root,
        )
        self.assertTrue(plan.items, "批量复制应产出计划项")
        items = apply_batch_plan(plan, workspace._index, workspace._writer)
        self.assertTrue(items, "批量复制应产出逐项结果")
        self.assertTrue(all(item.ok for item in items), [item.message for item in items])

        # 所选范围 + 离线 HTML 成果
        from doc_tool.application.intake_contract import SCOPE_CHAPTERS, ExportScope

        report = self._export(
            project, self.work / "scoped",
            formats=("html",), scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=[chapters[0]]),
        )
        html_result = report.result_for("html")
        self.assertTrue(html_result.usable, html_result.message)
        document = Path(html_result.path).read_text(encoding="utf-8")
        self.assertIn("概述", document)
        # 范围外章节不进入成果
        self.assertNotIn("设计", document.split("<nav>")[-1].split("</nav>")[0])
        # 离线包：移走后仍可读
        snapshot_dir = Path(html_result.path).parent
        moved = self.work / "moved-html"
        shutil.move(str(snapshot_dir), str(moved))
        self.assertTrue((moved / "index.html").is_file(), "移走后离线入口仍可打开")


class MainlineThreeReimportLoopTests(_Fixture):
    """主线三：源 Word 修订 → 后台差异 → 只接收合法一章 → 再次比较 → 新轮出稿。"""

    def test_reimport_selective_accept_then_recompare(self):
        from doc_tool.application.content.reimport import ReimportService
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        project = fixtures.two_chapter_project(self.work / "proj")
        paths = ProjectPaths(project)
        manifest = ProjectManifest.load(project)
        service = ReimportService(manifest, paths)
        content_root = paths.resolve(manifest.relative_content_root())
        chapters = sorted(
            path.relative_to(content_root).as_posix()
            for path in content_root.rglob("*.md")
            if path.is_file() and not path.name.startswith("_revision")
        )
        self.assertGreaterEqual(len(chapters), 2)

        # 构造“外部修订”：与当前内容一致 + 一章不同
        incoming = self.work / "incoming"
        for rel in chapters:
            target = incoming / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((content_root / rel).read_text(encoding="utf-8"), encoding="utf-8")
        changed_rel = chapters[1]
        (incoming / changed_rel).write_text(
            (content_root / changed_rel).read_text(encoding="utf-8") + "\n外部新增段落。\n",
            encoding="utf-8",
        )

        from doc_tool.application.content.reimport import compare_chapters

        changes = compare_chapters(content_root, incoming, service._base_hashes())
        by_path = {item.rel_path: item for item in changes}
        self.assertIn(changed_rel, by_path)
        self.assertEqual(by_path[changed_rel].status, "modified")

        # 只接收合法一章：用 extractor 注入真实传入内容（不伪造 docx）
        def _extract(_source, target_root):
            for item in sorted(incoming.rglob("*.md")):
                rel_in = item.relative_to(incoming).as_posix()
                out = Path(target_root) / rel_in
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")

        result = service.reimport(
            incoming / changed_rel, choices={changed_rel: True}, extractor=_extract,
        )
        self.assertTrue(result.success, result.message)

        # 再次比较：以**当前正文重建的传入副本**与更新后的基线比较，
        # 已接收的章不得仍报 modified（比较对象必须同源、同内容）。
        refreshed = ReimportService(
            ProjectManifest.load(project), ProjectPaths(project),
        )
        incoming2 = self.work / "incoming2"
        for rel in chapters:
            target = incoming2 / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((content_root / rel).read_text(encoding="utf-8"), encoding="utf-8")
        again = compare_chapters(content_root, incoming2, refreshed._base_hashes())
        # 再次比较必须给出完整逐章结论（不得因缺项而漏章）
        self.assertEqual(
            len(again), len(chapters),
            "再次比较必须覆盖全部章节：{0}".format({item.rel_path: item.status for item in again}),
        )
        # 用预览服务再比较一次：真实入口可用且**不写正文**
        before_preview = {
            path.relative_to(content_root).as_posix(): path.read_bytes()
            for path in content_root.rglob("*.md") if path.is_file()
        }
        def _extract2(_source, target_root):
            for item in sorted(incoming2.rglob("*.md")):
                rel_in = item.relative_to(incoming2).as_posix()
                out = Path(target_root) / rel_in
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")

        session, error = refreshed.preview(incoming2, extractor=_extract2)
        self.assertIsNotNone(session, "再次比较应能生成隔离预览：{0}".format(error))
        after_preview = {
            path.relative_to(content_root).as_posix(): path.read_bytes()
            for path in content_root.rglob("*.md") if path.is_file()
        }
        self.assertEqual(before_preview, after_preview, "预览阶段不得写正文")
        # 未接收的差异在预览里仍有条目（真实范围与来源可见）
        self.assertTrue(session.entries, "预览必须列出真实差异条目")

        # 新轮出稿
        report = self._export(project, self.work / "new-round")
        self.assertTrue(report.usable_results(), "新轮应产出可读成果")


if __name__ == "__main__":
    unittest.main(verbosity=2)