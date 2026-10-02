# -*- coding: utf-8 -*-
"""CORE-E/F 测试：有效快照、同源多格式出稿、同轮补格式与源码包。

对应验收 C-4/C-5/C-6/C-8 的自动部分与易用性 U-4/U-5/U-6/U-8。
Word 实机相关断言在本机有 Word 时执行，否则记录为待验收（测试内部按可用性分支）。
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.effective_snapshot import (  # noqa: E402
    capture_snapshot, count_unsaved, discover_chapters, mark_source_updated,
    snapshot_cache_key,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF, FORMAT_SOURCE_ZIP,
    SCOPE_CHAPTERS, SCOPE_CURRENT_CHAPTER, SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED, STATUS_PENDING_CONVERT, STATUS_PENDING_REFRESH, STATUS_READY,
    ExportRequest, ExportScope, sha256_file,
)
from doc_tool.application.project_export import (  # noqa: E402
    INDEX_NAME, read_export_index, report_docx_path, retry_export_formats,
    run_project_export,
)
from doc_tool.application.source_package import build_source_package  # noqa: E402


def _project_tree_state(root: Path) -> dict:
    """记录项目内 content/assets/template 的文件哈希（用于验证未被改写）。"""
    state = {}
    for folder in ("content", "assets", "template"):
        base = Path(root) / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                state[path.relative_to(root).as_posix()] = sha256_file(path)
    return state


class _SharedProjectMixin:
    """真实导入夹具较慢：每个测试类只建一次，测试内复制使用。"""

    _shared_root: Path = None
    _shared_project: Path = None

    @classmethod
    def _ensure_shared(cls):
        if cls._shared_project is None or not Path(cls._shared_project).is_dir():
            cls._shared_root = fixtures.scratch_dir("shared")
            cls._shared_project = fixtures.two_chapter_project(cls._shared_root / "proj")

    def _new_project(self, name: str = "proj") -> Path:
        self._ensure_shared()
        target = self.work / name
        shutil.copytree(str(self._shared_project), str(target))
        return target

    def _chapter_rel(self, preferred: str) -> str:
        """返回项目内实际存在的章节相对路径（夹具内容随导入结果变化）。"""
        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        return preferred if preferred in rels else rels[0]


class SnapshotTests(_SharedProjectMixin, unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("snap")
        self.project = self._new_project()

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_buffer_edit_is_captured_without_touching_disk(self):
        content = self.project / "content" / "general"
        before = _project_tree_state(self.project)
        target = self._chapter_rel("第1章 引言/1.1 目的.md")
        disk_before = (content / target).read_text(encoding="utf-8")
        buffers = {target: disk_before + "\n未保存修改。\n"}
        self.assertEqual(count_unsaved(content, buffers), [target])
        snapshot = capture_snapshot(
            self.project, source_mode=SOURCE_MODE_CURRENT_BUFFER, buffer_texts=buffers,
        )
        self.assertEqual(snapshot.unsavedChapters, [target])
        self.assertIn("1 章未保存修改", snapshot.source_description())
        # 快照工作目录里是编辑后的内容；源项目磁盘内容不变
        snapshot_text = (Path(snapshot.workDir) / "content" / target).read_text(encoding="utf-8")
        self.assertIn("未保存修改", snapshot_text)
        self.assertEqual(_project_tree_state(self.project), before)
        self.assertEqual((content / target).read_text(encoding="utf-8"), disk_before)

    def test_snapshot_assets_use_manifest_resource_root(self):
        from doc_tool.domain.manifest import ProjectManifest
        manifest = ProjectManifest.load(self.project)
        image = self.project / manifest.relative_asset_root() / "images" / "review.png"
        fixtures.tiny_png(image)
        rel = self._chapter_rel("第1章 引言/1.1 目的.md")
        chapter = self.project / manifest.relative_content_root() / rel
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n![图](images/review.png)\n", encoding="utf-8")
        table = self.project / manifest.relative_table_root() / "review.xml"
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text('<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>', encoding="utf-8")
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n<!-- TABLE:1:review.xml -->\n", encoding="utf-8")
        snapshot = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED)
        self.assertEqual(snapshot.missingResources, [])
        copied = Path(snapshot.workDir) / "assets/images/review.png"
        self.assertEqual(copied.read_bytes(), image.read_bytes())
        self.assertEqual(snapshot.assetHashes["images/review.png"], sha256_file(copied))
        self.assertEqual((Path(snapshot.workDir) / "assets/tables/review.xml").read_bytes(), table.read_bytes())
        from doc_tool.application.snapshot_views import build_snapshot_views
        views = build_snapshot_views(snapshot, self.work / "preview")
        self.assertTrue(views.ok, views.warnings)
        self.assertFalse(any("图片缺失" in item.get("message", "") for item in views.previewWarnings))

    def test_snapshot_rejects_work_directory_over_source_project(self):
        before = _project_tree_state(self.project)
        with self.assertRaises(ValueError):
            capture_snapshot(self.project, work_root=self.project)
        self.assertEqual(_project_tree_state(self.project), before)

    def test_saved_mode_ignores_buffer_edits(self):
        target = self._chapter_rel("第1章 引言/1.1 目的.md")
        buffers = {target: "只存在于缓冲。\n"}
        snapshot = capture_snapshot(
            self.project, source_mode=SOURCE_MODE_SAVED, buffer_texts=buffers,
        )
        self.assertEqual(snapshot.unsavedChapters, [])
        written = (Path(snapshot.workDir) / "content" / target).read_text(encoding="utf-8")
        self.assertNotIn("只存在于缓冲", written)
        self.assertEqual(written, (self.project / "content" / "general" / target).read_text(encoding="utf-8"))
        self.assertIn("已保存版本", snapshot.source_description())

    def test_scope_selects_chapters_in_project_order(self):
        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        self.assertGreaterEqual(len(rels), 2, rels)
        first, second = rels[0], rels[1]
        scope = ExportScope(kind=SCOPE_CHAPTERS, chapters=[second, first])
        snapshot = capture_snapshot(self.project, scope=scope, source_mode=SOURCE_MODE_SAVED)
        self.assertEqual(snapshot.orderedChapters, [first, second])
        files = [rel for rel, _path in discover_chapters(Path(snapshot.workDir) / "content")]
        self.assertEqual(sorted(files), sorted(snapshot.orderedChapters))
        current = capture_snapshot(
            self.project,
            scope=ExportScope(kind=SCOPE_CURRENT_CHAPTER, current=second),
            source_mode=SOURCE_MODE_SAVED,
        )
        self.assertEqual(current.orderedChapters, [second])
        self.assertEqual(len(current.omittedChapters), len(rels) - 1)

    def test_cache_key_tracks_content_and_scope(self):
        base = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED)
        again = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED)
        self.assertEqual(base.cacheKey, again.cacheKey)
        target = self._chapter_rel("第1章 引言/1.1 目的.md")
        edited = capture_snapshot(
            self.project, source_mode=SOURCE_MODE_CURRENT_BUFFER,
            buffer_texts={target: "改了。\n"},
        )
        self.assertNotEqual(base.cacheKey, edited.cacheKey)
        self.assertEqual(edited.cacheKey, snapshot_cache_key(edited))

    def test_source_updated_detection(self):
        snapshot = capture_snapshot(self.project, source_mode=SOURCE_MODE_SAVED)
        self.assertFalse(mark_source_updated(snapshot))
        target = self._chapter_rel("第1章 引言/1.1 目的.md")
        chapter = self.project / "content" / "general" / target
        chapter.write_text("磁盘后来改了。\n", encoding="utf-8")
        self.assertTrue(mark_source_updated(snapshot))


class ExportTests(_SharedProjectMixin, unittest.TestCase):
    """多格式出稿；默认诊断构建（不依赖 Word 刷新）以保证可重复。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("export")
        self.project = self._new_project()
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _request(self, **kwargs):
        payload = dict(
            project_root=str(self.project),
            formats=[FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF, FORMAT_SOURCE_ZIP],
            source_mode=SOURCE_MODE_CURRENT_BUFFER,
            destination=str(self.out),
        )
        payload.update(kwargs)
        return ExportRequest(**payload)

    def test_multi_format_partial_success_keeps_usable_results(self):
        target = self._chapter_rel("第1章 引言/1.1 目的.md")
        buffers = {target: "导出前未保存的修改。\n"}
        before = _project_tree_state(self.project)
        report = run_project_export(
            self._request(), buffer_texts=buffers, skip_word_refresh=True,
        )
        docx = report.result_for(FORMAT_DOCX)
        html = report.result_for(FORMAT_HTML)
        pdf = report.result_for(FORMAT_PDF)
        package = report.result_for(FORMAT_SOURCE_ZIP)
        self.assertEqual(docx.status, STATUS_PENDING_REFRESH)
        self.assertTrue(docx.usable and Path(docx.path).is_file())
        self.assertEqual(html.status, STATUS_READY)
        self.assertTrue(Path(html.path).is_file())
        # 有 Word 时 PDF 由本轮 DOCX 转换成功；无 Word 时明确待转换
        self.assertIn(pdf.status, (STATUS_READY, STATUS_PENDING_CONVERT))
        if pdf.status == STATUS_READY:
            self.assertTrue(Path(pdf.path).is_file())
        else:
            self.assertIn("待转换", pdf.message)
        self.assertTrue(Path(package.path).is_file())
        self.assertEqual(report.unsavedChapters, [target])
        # 源项目正文/资源/底模未被改写
        self.assertEqual(_project_tree_state(self.project), before)
        # 索引：同轮 captureId、范围与来源可查
        index = self.out / INDEX_NAME
        self.assertTrue(index.is_file())
        data = json.loads(index.read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["captureId"], report.captureId)
        self.assertEqual(data["sourceMode"], SOURCE_MODE_CURRENT_BUFFER)
        reloaded = read_export_index(self.out)
        self.assertEqual(reloaded.captureId, report.captureId)
        self.assertEqual(
            sorted(item.format for item in reloaded.results),
            sorted([FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF, FORMAT_SOURCE_ZIP]),
        )

    def test_retry_only_failed_format_reuses_original_round(self):
        report = run_project_export(self._request(), skip_word_refresh=True)
        docx_before = report.result_for(FORMAT_DOCX).path
        # 源正文后来改了：补 PDF 仍必须用原轮快照，不混入新正文
        chapter = self.project / "content" / "general" / self._chapter_rel("第1章 引言/1.1 目的.md")
        chapter.write_text("后来大改。\n", encoding="utf-8")
        retried = retry_export_formats(
            report, [FORMAT_PDF], skip_word_refresh=True,
        )
        self.assertEqual(retried.captureId, report.captureId)
        self.assertEqual(retried.result_for(FORMAT_DOCX).path, docx_before)
        self.assertEqual(retried.result_for(FORMAT_PDF).attempts >= 1, True)
        self.assertEqual(
            Path(retried.snapshotWorkDir), Path(report.snapshotWorkDir),
        )

    def test_same_name_uses_new_safe_name_instead_of_overwriting(self):
        first = run_project_export(self._request(), skip_word_refresh=True)
        second = run_project_export(self._request(), skip_word_refresh=True)
        self.assertNotEqual(
            first.result_for(FORMAT_DOCX).path, second.result_for(FORMAT_DOCX).path,
        )
        self.assertTrue(Path(first.result_for(FORMAT_DOCX).path).is_file())
        self.assertTrue(Path(second.result_for(FORMAT_DOCX).path).is_file())

    def test_invalid_destination_falls_back_and_keeps_settings(self):
        report = run_project_export(
            self._request(destination="Z:/definitely-missing/dir"),
            skip_word_refresh=True,
        )
        self.assertTrue(Path(report.destination).is_dir())
        self.assertTrue(any("已改用" in item for item in report.warnings), report.warnings)
        self.assertEqual(report.result_for(FORMAT_DOCX).status, STATUS_PENDING_REFRESH)

    def test_cancel_keeps_completed_formats(self):
        from doc_tool.domain.cancellation import CancellationToken

        token = CancellationToken()
        calls = {"count": 0}

        def progress(fmt, detail):
            calls["count"] += 1
            if calls["count"] >= 2:
                token.request_cancel()

        report = run_project_export(
            self._request(formats=[FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF]),
            skip_word_refresh=True, cancel_token=token, progress=progress,
        )
        self.assertTrue(report.usable_results())
        self.assertTrue(any(
            item.status == "cancelled" for item in report.results
        ), [item.status for item in report.results])

    def test_scope_and_summary_report_actual_range(self):
        target = self._chapter_rel("第2章 设计/2.1 架构.md")
        report = run_project_export(
            self._request(
                scope=ExportScope(kind=SCOPE_CURRENT_CHAPTER, current=target),
                formats=[FORMAT_HTML],
            ),
            skip_word_refresh=True,
        )
        lines = "\n".join(report.summary_lines())
        self.assertIn("当前章", lines)
        self.assertIn("输出位置", lines)

    def test_source_package_is_portable_and_excludes_user_data(self):
        target = self.work / "pkg" / "项目源码包.zip"
        outcome = build_source_package(self.project, target, include_original=False)
        self.assertTrue(outcome.ok, outcome.message)
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            self.assertIn("project.yml", names)
            self.assertTrue(any(name.startswith("content/") for name in names))
            self.assertTrue(any(name.startswith("template/") for name in names))
            self.assertNotIn("original/source.docx", names)
            self.assertFalse(any(".git" in name for name in names))
            self.assertFalse(any("__pycache__" in name for name in names))
            manifest = json.loads(archive.read("source-package.json").decode("utf-8"))
        self.assertTrue(manifest["selfContained"])
        # 搬到另一目录后可再次打开（清单相对路径可解析）
        moved = self.work / "moved"
        moved.mkdir()
        with zipfile.ZipFile(target) as archive:
            archive.extractall(moved)
        from doc_tool.domain.manifest import ProjectManifest

        manifest_obj = ProjectManifest.load(moved)
        self.assertEqual(manifest_obj.documentType, "general")
        self.assertTrue((moved / "project.yml").is_file())
        self.assertTrue(list((moved / "content").rglob("*.md")))

    def test_source_package_reports_missing_resource(self):
        chapter = self.project / "content" / "general" / self._chapter_rel("第1章 引言/1.1 目的.md")
        chapter.write_text("正文。\n\n![缺图](images/none.png)\n", encoding="utf-8")
        target = self.work / "pkg2.zip"
        outcome = build_source_package(self.project, target)
        self.assertTrue(outcome.ok)
        self.assertIn("images/none.png", outcome.missing)
        with zipfile.ZipFile(target) as archive:
            manifest = json.loads(archive.read("source-package.json").decode("utf-8"))
        self.assertFalse(manifest["selfContained"])

    def test_source_package_keeps_assets_and_parent_body_when_moved(self):
        from doc_tool.domain.manifest import ProjectManifest
        manifest = ProjectManifest.load(self.project)
        image = self.project / manifest.relative_asset_root() / "images" / "review.png"
        fixtures.tiny_png(image)
        rel = self._chapter_rel("第1章 引言/1.1 目的.md")
        chapter = self.project / manifest.relative_content_root() / rel
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n![图](images/review.png)\n", encoding="utf-8")
        index = chapter.parent / "_index.md"
        index.write_text("父章节的正文。\n", encoding="utf-8")
        table = self.project / manifest.relative_table_root() / "review.xml"
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text('<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>', encoding="utf-8")
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n<!-- TABLE:1:review.xml -->\n", encoding="utf-8")
        outcome = build_source_package(self.project, self.work / "with-assets.zip")
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.missing, [])
        with zipfile.ZipFile(outcome.path) as archive:
            self.assertEqual(archive.read("assets/images/review.png"), image.read_bytes())
            self.assertEqual(archive.read("assets/tables/review.xml"), table.read_bytes())
            self.assertEqual(archive.read("content/" + (Path(rel).parent / "_index.md").as_posix()), index.read_bytes())


class SnapshotViewTests(_SharedProjectMixin, unittest.TestCase):
    """CORE-E 5.3：预览与检查基于同一份有效快照。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("views")
        self.project = self._new_project()

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_preview_uses_same_snapshot_content_as_export(self):
        from doc_tool.application.snapshot_views import build_snapshot_views

        target = self._chapter_rel("第1章 引言/1.1 目的.md")
        buffers = {target: "预览与出稿共用的内容。\n"}
        snapshot = capture_snapshot(
            self.project, source_mode=SOURCE_MODE_CURRENT_BUFFER, buffer_texts=buffers,
        )
        views = build_snapshot_views(snapshot, self.work / "views-out")
        self.assertTrue(views.ok, views.warnings)
        self.assertEqual(views.captureId, snapshot.captureId)
        preview = Path(views.previewIndex).read_text(encoding="utf-8", errors="replace")
        self.assertIn("预览与出稿共用的内容", preview)
        # 快照本身未被预览改写
        self.assertEqual(
            (Path(snapshot.workDir) / "content" / target).read_text(encoding="utf-8"),
            buffers[target],
        )
        self.assertTrue(views.summary_lines())


class ReadonlyAndActionTests(_SharedProjectMixin, unittest.TestCase):
    """C-6/U-7：只读项目外部出稿，项目内无新增写入；结果给直接动作。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("readonly")
        self.project = self._new_project()

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_readonly_project_exports_to_external_dir_without_writing_inside(self):
        import yaml

        from doc_tool.domain.manifest import ProjectManifest

        manifest_file = self.project / "project.yml"
        payload = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
        payload["schemaVersion"] = int(manifest_file.read_text(encoding="utf-8").count("") or 0) and payload["schemaVersion"]
        payload["schemaVersion"] = 92  # 高于当前应用可写版本 -> 只读
        manifest_file.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        self.assertFalse(ProjectManifest.load(self.project).is_writable())
        before = sorted(p.relative_to(self.project).as_posix() for p in self.project.rglob("*"))
        external = self.work / "交付目录"
        report = run_project_export(
            ExportRequest(
                project_root=str(self.project), formats=[FORMAT_DOCX, FORMAT_HTML],
                destination=str(external),
            ),
            skip_word_refresh=True,
        )
        self.assertTrue(report.usable_results())
        self.assertTrue(Path(report.destination).is_dir())
        after = sorted(p.relative_to(self.project).as_posix() for p in self.project.rglob("*"))
        self.assertEqual(before, after)
        self.assertTrue(report.readonlyProject)

    def test_action_items_are_direct_and_limited(self):
        from doc_tool.application.import_record import (
            ImportRecord, HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER,
        )
        from doc_tool.application.intake_contract import PreservationFinding

        record = ImportRecord(findings=[
            PreservationFinding("image", HANDLING_PLACEHOLDER, target_chapter="第1章"),
            PreservationFinding("formula", HANDLING_ORIGINAL_ONLY, target_chapter="第1章"),
            PreservationFinding("textbox", HANDLING_ORIGINAL_ONLY, target_chapter="第2章"),
            PreservationFinding("footnote", HANDLING_ORIGINAL_ONLY, target_chapter="第2章"),
        ])
        actions = record.result_actions()
        self.assertEqual(len(actions), 3)
        kinds = {item["kind"] for item in actions}
        self.assertIn("replace-image", kinds)
        self.assertIn("view-original", kinds)
        for item in actions:
            self.assertTrue(item["action"])
            self.assertTrue(item["label"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
