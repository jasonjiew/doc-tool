# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.lint import ContentLinter
from doc_tool.application.content.quality_rules import QualityRule, QualityRulesConfig, default_rules
from doc_tool.application.content.traceability import (
    TraceItem,
    TraceabilityService,
    build_matrix,
    render_matrix_markdown,
)
from doc_tool.application.content.baselines import (
    BaselineStore,
    CheckpointStore,
    pre_publish_checks,
)
from doc_tool.application.content.writer import ContentWriter
from doc_tool.application.content.history import BuildHistoryStore, diff_docx_text
from doc_tool.application.export.pdf_html import (
    VisualDiffService,
    export_html,
    export_pdf,
    pixel_diff_regions,
)
from doc_tool.application.review.review_store import (
    ReviewPackageBuilder,
    ReviewStore,
    approval_gate,
)
from doc_tool.application.content.reimport import ReimportService, compare_chapters, file_sha256
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.content_index import FileReference, REF_LINK
from doc_tool.domain.manifest import ProjectManifest, increment_version


class QualityRulesTests(unittest.TestCase):
    def _index(self, root: Path):
        (root / "1.1 范围.md").write_text("# 范围\n文档编号: RQ-1\n手机号 13800138000\nTODO gxpc\n", encoding="utf-8")
        (root / "1.2 重复.md").write_text("# 1.1 重复\n", encoding="utf-8")
        return ContentIndexService(root).build()

    def test_config_roundtrip_corrupt_fallback_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            store = QualityRulesConfig(state, "requirement")
            rules = [QualityRule("todo_residual", False, "error", {"x": 1})]
            store.save(rules)
            loaded = store.load()[0]
            self.assertFalse(loaded.enabled)
            self.assertEqual(loaded.params, {"x": 1})
            store.file.write_text("{bad", encoding="utf-8")
            self.assertTrue(any(r.rule_id == "required_section" for r in store.load()))
            readonly = QualityRulesConfig(state, "design", writable=False)
            with self.assertRaises(PermissionError):
                readonly.save(default_rules("design"))

    def test_configured_rules_and_legacy_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "requirement"
            root.mkdir(parents=True)
            index = self._index(root)
            state = Path(tmp) / ".state"
            config = QualityRulesConfig(state, "requirement")
            config.save([
                QualityRule("todo_residual", True, "error"),
                QualityRule("term_case", True, "info"),
                QualityRule("required_section", True, "error", {"titles": ["范围", "总体描述"]}),
                QualityRule("field_completeness", True, "warning", {"fields": {"编号": {"regex": r"文档编号:\s*RQ-\d+", "count": 2}}}),
                QualityRule("numbering_uniqueness", True, "error"),
                QualityRule("sensitive_info", True, "warning", {"patterns": [{"name": "手机", "regex": r"1[3-9]\d{9}"}]}),
            ])
            issues = ContentLinter(index, config).check_all(["GXPC"])
            by_rule = {issue.rule_id for issue in issues}
            self.assertTrue({"todo_residual", "term_case", "required_section", "field_completeness", "numbering_uniqueness", "sensitive_info"}.issubset(by_rule))
            self.assertTrue(all(issue.severity in ("error", "warning", "info") for issue in issues))

    def test_disabled_rule_is_not_executed_and_positive_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "design"
            root.mkdir(parents=True)
            (root / "1.1 x.md").write_text("# 功能描述\n# 核心逻辑\nTODO\n", encoding="utf-8")
            config = QualityRulesConfig(Path(tmp) / ".state", "design")
            config.save([
                QualityRule("required_section", True, "error", {"titles": ["功能描述", "核心逻辑"]}),
                QualityRule("todo_residual", False, "error"),
            ])
            issues = ContentLinter(ContentIndexService(root).build(), config).check_all([])
            self.assertEqual(issues, [])

    def test_numbering_uniqueness_same_file_duplicate_and_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "requirement"
            root.mkdir(parents=True)
            (root / "1.1 概述.md").write_text("# 3.1 概述\n# 3.1 详情\n", encoding="utf-8")
            (root / "a.md").write_text("# 范围\n", encoding="utf-8")
            (root / "b.md").write_text("# 范围\n", encoding="utf-8")
            config = QualityRulesConfig(Path(tmp) / ".state", "requirement")
            config.save([QualityRule("numbering_uniqueness", True, "error")])
            issues = ContentLinter(ContentIndexService(root).build(), config).check_all([])
            numbers = [issue for issue in issues if "章节编号重复" in issue.message]
            anchors = [issue for issue in issues if "标题锚点重复" in issue.message]
            self.assertTrue(any("3.1" in issue.message for issue in numbers), "同文件重复编号未检出")
            self.assertTrue(anchors, "跨文件重复标题锚点未检出")

    def test_numbering_uniqueness_own_title_not_self_reported(self):
        # 文件名章节号（3.1 概述.md -> 3.1）与其首个同号 H1 是同一逻辑位置：
        # H1 不在首行时若各自计数，会自我误报「章节编号重复」。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "requirement"
            root.mkdir(parents=True)
            (root / "3.1 概述.md").write_text("\n\n# 3.1 概述\n正文\n", encoding="utf-8")
            config = QualityRulesConfig(Path(tmp) / ".state", "requirement")
            config.save([QualityRule("numbering_uniqueness", True, "error")])
            issues = ContentLinter(ContentIndexService(root).build(), config).check_all([])
            numbers = [issue for issue in issues if "章节编号重复" in issue.message]
            self.assertEqual(numbers, [], "文件自身标题被误报为编号重复")
            # 同文件后续同号标题仍是真实重复，不得因合并而漏检。
            (root / "3.1 概述.md").write_text("# 3.1 概述\n# 3.1 功能\n", encoding="utf-8")
            issues = ContentLinter(ContentIndexService(root).build(), config).check_all([])
            numbers = [issue for issue in issues if "章节编号重复" in issue.message]
            self.assertTrue(numbers, "合并后同文件真实重复被漏检")

    def test_interface_table_structure_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "requirement"
            root.mkdir(parents=True)
            (root / "1.1 接口.md").write_text("# 1.1 接口\n接口说明但没有表格。\n", encoding="utf-8")
            (root / "1.2 接口.md").write_text("# 1.2 接口\n| 名称 | 说明 |\n| --- | --- |\n| A | B |\n", encoding="utf-8")
            (root / "1.3 复合.md").write_text("# 1.3 接口\n| 名称 | 说明 |\n| --- | --- |\n| A | B |\n## 1.3.1 子接口\n说明无表\n", encoding="utf-8")
            config = QualityRulesConfig(Path(tmp) / ".state", "requirement")
            config.save([QualityRule("interface_table_structure", True, "warning")])
            issues = [issue for issue in ContentLinter(ContentIndexService(root).build(), config).check_all([])
                      if issue.rule_id == "interface_table_structure"]
            self.assertEqual(len(issues), 2)
            self.assertEqual({issue.rel_path for issue in issues}, {"1.1 接口.md", "1.3 复合.md"})

    def test_field_completeness_bad_count_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content" / "requirement"
            root.mkdir(parents=True)
            (root / "1.1 概述.md").write_text("# 范围\n", encoding="utf-8")
            config = QualityRulesConfig(Path(tmp) / ".state", "requirement")
            config.save([
                QualityRule("field_completeness", True, "warning", {"fields": {"编号": {"regex": "RQ-\\d+", "count": "oops"}}}),
            ])
            issues = ContentLinter(ContentIndexService(root).build(), config).check_all([])
            self.assertTrue(any(issue.rule_id == "field_completeness" for issue in issues))

    def test_heading_format_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "content"
            root.mkdir(parents=True)
            (root / "1.1 格式.md").write_text(
                "#1.1 无空格标题\n正文\n##\n```python\n#不是标题\n```\n",
                encoding="utf-8",
            )
            config = QualityRulesConfig(Path(tmp) / ".state", "general")
            config.save([QualityRule("heading_format", True, "warning")])
            issues = [issue for issue in ContentLinter(ContentIndexService(root).build(), config).check_all([])
                      if issue.rule_id == "heading_format"]
            self.assertEqual(len(issues), 2)
            self.assertIn("缺少空格", issues[0].message)
            self.assertEqual(issues[0].line_no, 1)
            self.assertIn("标题文本为空", issues[1].message)
            self.assertEqual(issues[1].line_no, 3)


class TraceabilityTests(unittest.TestCase):
    def test_parse_items_including_unnumbered_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            requirement = content / "requirement"
            design = content / "design"
            requirement.mkdir(parents=True)
            design.mkdir(parents=True)
            (requirement / "1.1 req.md").write_text(
                "# REQ-1 \u9700\u6c42\n\u8be5\u9700\u6c42\u9700\u8981\u8ffd\u8e2a\u3002\n# \u65e0\u7f16\u53f7\u9700\u6c42\n",
                encoding="utf-8",
            )
            (design / "2.1 design.md").write_text(
                "# DES-1 \u8bbe\u8ba1\n\u5bf9\u5e94 REQ-1\n## IF-1 \u63a5\u53e3\n\u5bf9\u5e94 DES-1\n## AC-1 \u9a8c\u6536\n\u5bf9\u5e94 DES-1\n",
                encoding="utf-8",
            )
            index = ContentIndexService(content).build()
            service = TraceabilityService(index, Path(tmp) / ".state")
            items = service.parse_items()
            self.assertTrue(any(item.item_id == "" for item in items))
            matrix = service.rebuild()
            self.assertEqual(matrix.requirement_coverage, 100.0)
            self.assertEqual(matrix.design_coverage, 100.0)
            self.assertTrue(service.file.is_file())
            self.assertIn("REQ-1", render_matrix_markdown(matrix))

    def test_matrix_reports_unmapped_items(self):
        requirement = TraceItem("REQ-1", "requirement", "r", "r.md", 1)
        design = TraceItem("DES-1", "design", "d", "d.md", 1)
        matrix = build_matrix([requirement, design])
        self.assertEqual(matrix.requirement_coverage, 0.0)
        self.assertEqual(matrix.design_coverage, 0.0)
        self.assertEqual(matrix.unmapped_requirements, [requirement])
        self.assertEqual(matrix.unmapped_designs, [design])

    def test_deleted_section_impact_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp)
            (content / "source.md").write_text("# source\n", encoding="utf-8")
            (content / "target.md").write_text("# target\n", encoding="utf-8")
            index = ContentIndexService(content).build()
            index.references["source.md"] = [
                FileReference(
                    kind=REF_LINK,
                    source="source.md",
                    source_line=2,
                    source_text="[target](target.md)",
                    target="target.md",
                    target_rel_path="target.md",
                )
            ]
            del index.files["target.md"]
            impact = TraceabilityService(index).impact_analysis(["target.md"])
            self.assertEqual(impact[0]["source"], "source.md")
            self.assertTrue(impact[0]["dangling"])

    def test_heading_number_preferred_over_body_rq(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            requirement = content / "requirement"
            requirement.mkdir(parents=True)
            (requirement / "1.1 需求.md").write_text("# 1.1 需求概述\n关联 RQ-102\n", encoding="utf-8")
            index = ContentIndexService(content).build()
            items = TraceabilityService(index, Path(tmp) / ".state").parse_items()
            self.assertEqual(items[0].item_id, "1.1")
            self.assertIn("RQ-102", items[0].references)

    def test_number_reference_with_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            design = content / "design"
            design.mkdir(parents=True)
            (design / "2.1 设计.md").write_text("# 2.1 设计\n见需求 3.2\n", encoding="utf-8")
            index = ContentIndexService(content).build()
            items = TraceabilityService(index, Path(tmp) / ".state").parse_items()
            self.assertIn("3.2", items[0].references)

    def test_dangling_reference_reported_in_fresh_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            requirement = content / "requirement"
            design = content / "design"
            requirement.mkdir(parents=True)
            design.mkdir(parents=True)
            (requirement / "1.2 需求详情.md").write_text("# 1.2 需求详情\n", encoding="utf-8")
            (design / "2.2 设计.md").write_text("# 2.2 设计\n见 1.2 的需求\n", encoding="utf-8")
            index = ContentIndexService(content).build()
            # 删除需求章节后重建索引（fresh index）：引用变为悬空 target_rel_path=None
            (requirement / "1.2 需求详情.md").unlink()
            index = ContentIndexService(content).build()
            from doc_tool.application.content.references import ReferenceScanner
            ReferenceScanner(index).scan_all()
            impact = TraceabilityService(index).impact_analysis(["requirement/1.2 需求详情.md"])
            self.assertTrue(any(item["dangling"] for item in impact))


class SettingsAndBaselineTests(unittest.TestCase):
    def _manifest(self):
        return ProjectManifest(
            documentType="requirement",
            documentNo="GX-1",
            documentName="test",
            documentVersion="1.0.1",
            sourceSha256="abc",
            paths={
                "sourceDocx": "original/source.docx",
                "templateDocx": "template/template.docx",
                "contentRoot": "content/requirement",
            },
            publishNotes="notes",
        )

    def test_manifest_publish_notes_and_increment_version(self):
        manifest = ProjectManifest.from_dict(self._manifest().to_dict())
        self.assertEqual(manifest.publishNotes, "notes")
        self.assertEqual(increment_version("1.0.1", "patch"), "1.0.2")
        self.assertEqual(increment_version("1.0.1", "minor"), "1.1.0")
        self.assertEqual(increment_version("1.0.1", "major"), "2.0.0")
        with self.assertRaises(ValueError):
            increment_version("v1", "patch")

    def test_checkpoint_duplicate_and_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content"
            content.mkdir()
            (content / "a.md").write_text("old", encoding="utf-8")
            manifest_path = root / "project.yml"
            manifest_path.write_text("schemaVersion: 1", encoding="utf-8")
            report = root / "validation.md"
            report.write_text("PASS", encoding="utf-8")
            store = CheckpointStore(root / ".state")
            checkpoint = store.create("release", manifest_path, content, report)
            self.assertTrue((checkpoint / "content" / "a.md").is_file())
            self.assertTrue((checkpoint / "validation.md").is_file())
            with self.assertRaises(FileExistsError):
                store.create("release", manifest_path, content, report)

    def test_freeze_restore_cancel_and_change_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content"
            content.mkdir()
            target = content / "a.md"
            target.write_text("baseline", encoding="utf-8")
            baseline = BaselineStore(root / ".state")
            baseline.freeze(self._manifest(), content)
            target.write_text("changed", encoding="utf-8")
            writer = ContentWriter(content, root / ".state")
            self.assertEqual(baseline.restore("1.0.1", writer, confirmed=False), [])
            self.assertEqual(target.read_text(encoding="utf-8"), "changed")
            self.assertEqual(baseline.restore("1.0.1", writer, confirmed=True), ["a.md"])
            self.assertEqual(target.read_text(encoding="utf-8"), "baseline")
            writer.manifest.load()
            self.assertFalse(writer.manifest.empty)

    def test_pre_publish_check_branches(self):
        checks = pre_publish_checks(
            quality_errors=0,
            unresolved_reviews=0,
            current_version="2.0.0",
            baseline_version="1.9.0",
            pending_changes=0,
        )
        self.assertTrue(all(item.passed for item in checks))
        failed = pre_publish_checks(
            quality_errors=1,
            unresolved_reviews=2,
            current_version="1.0.0",
            baseline_version="2.0.0",
            pending_changes=3,
        )
        self.assertFalse(any(item.passed for item in failed))


class BuildHistoryTests(unittest.TestCase):
    def _archive(self, root: Path, store: BuildHistoryStore, version: str, text: str, *, diagnostic=False):
        content = root / "content"
        content.mkdir(exist_ok=True)
        (content / "a.md").write_text(text, encoding="utf-8")
        template = root / "template.docx"
        template.write_bytes(b"template")
        assets = root / "assets"
        assets.mkdir(exist_ok=True)
        output = root / (version + ".docx")
        output.write_bytes(("output-" + version).encode())
        manifest = ProjectManifest(
            documentType="general", documentNo="", documentName="x",
            documentVersion=version, sourceSha256="",
        )
        return store.archive(manifest, content, template, assets, output, diagnostic=diagnostic)

    def test_archive_list_diff_restore_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = BuildHistoryStore(root / ".state")
            first = self._archive(root, store, "1.0.0", "old")
            first_id = first.stem
            (root / "content" / "b.md").write_text("new file", encoding="utf-8")
            second = self._archive(root, store, "1.1.0", "new", diagnostic=True)
            second_id = second.stem
            entries = store.list_entries()
            self.assertTrue(entries[0].diagnostic)
            diff = store.diff(first_id, second_id)
            self.assertEqual(diff["modified"], ["a.md"])
            self.assertEqual(diff["added"], ["b.md"])
            self.assertIn("-old", store.text_diff(first_id, second_id, "a.md"))
            writer = ContentWriter(root / "content", root / ".state")
            self.assertEqual(store.restore(first_id, writer, confirmed=False), [])
            changed = store.restore(first_id, writer, confirmed=True)
            self.assertIn("a.md", changed)
            self.assertEqual((root / "content" / "a.md").read_text(encoding="utf-8"), "old")
            self.assertFalse((root / "content" / "b.md").exists())

    def test_restore_refuses_when_snapshot_missing_and_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = BuildHistoryStore(root / ".state")
            first = self._archive(root, store, "1.0.0", "old")
            first_id = first.stem
            shutil.rmtree(root / ".state" / "history" / first_id)
            writer = ContentWriter(root / "content", root / ".state")
            with self.assertRaises(FileNotFoundError):
                store.restore(first_id, writer, confirmed=True)
            # 快照缺失时不得把当前文件当作「基线外文件」删除
            self.assertTrue((root / "content" / "a.md").exists())

    def test_docx_text_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def make(name, text):
                path = root / name
                xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                       '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
                with zipfile.ZipFile(path, "w") as package:
                    package.writestr("word/document.xml", xml)
                return path
            diff = diff_docx_text(make("old.docx", "old"), make("new.docx", "new"))
            self.assertIn("-old", diff)
            self.assertIn("+new", diff)


class ReviewExportTests(unittest.TestCase):
    def test_html_and_non_word_pdf_export(self):
        try:
            import reportlab  # noqa: F401
            import pypdf
        except ImportError:
            self.skipTest("reportlab/pypdf optional review-export dependencies are unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            chapters = [("1.1 chapter", "# title\nbody")]
            html = export_html(chapters, output, "1.0.0")
            self.assertIn("章节导航", html.read_text(encoding="utf-8"))
            self.assertIn('id="chapter-1"', html.read_text(encoding="utf-8"))
            pdf = export_pdf(chapters, output, "1.0.0")
            self.assertGreater(pdf.stat().st_size, 100)
            self.assertIn("Word", "".join(page.extract_text() or "" for page in pypdf.PdfReader(pdf).pages))

    def test_visual_diff_region_location_viewed_and_no_baseline(self):
        from PIL import Image
        old = Image.new("RGB", (20, 20), "white")
        new = old.copy()
        new.putpixel((7, 8), (0, 0, 0))
        regions = pixel_diff_regions(old, new, rel_path="a.md")
        self.assertEqual(regions[0].box, (7, 8, 8, 9))
        self.assertEqual(regions[0].mark_viewed(), ("a.md", 1))
        self.assertTrue(regions[0].viewed)
        service = VisualDiffService()
        self.assertEqual(service.compare([old], [new], old_snapshot_hash="same", new_snapshot_hash="same"), [])
        with self.assertRaisesRegex(ValueError, "无对比基线"):
            service.compare([old], [new], old_snapshot_hash="", new_snapshot_hash="new")


class ReviewWorkflowTests(unittest.TestCase):
    def test_comments_status_association_signoff_and_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ReviewStore(root / ".state")
            comment = store.add_comment("fix it", "alice", "old.md", 3)
            self.assertEqual(store.unresolved_count, 1)
            store.set_resolved(comment.comment_id, True)
            self.assertTrue(store.comments()[0].resolved_at)
            store.set_resolved(comment.comment_id, False)
            store.mark_association_changes(["new.md"], {"old.md": "new.md"})
            self.assertTrue(store.comments()[0].association_changed)
            self.assertEqual(store.comments()[0].rel_path, "new.md")
            store.append_signoff("bob", "reviewer")
            gate = approval_gate(store.comments(), store.signoffs(), required_roles=["reviewer"])
            self.assertFalse(gate.allowed)
            skipped = approval_gate(store.comments(), store.signoffs(), required_roles=["owner"], skip=True)
            self.assertTrue(skipped.allowed)
            self.assertIn("跳过审批", skipped.history_note)
            store.set_resolved(comment.comment_id, True)
            self.assertTrue(approval_gate(store.comments(), store.signoffs(), required_roles=["reviewer"]).allowed)
            package = ReviewPackageBuilder(root / "output").build(store, {"a": "hash"}, {"modified": ["a.md"]}, "1.0")
            self.assertTrue(package.is_dir())
            self.assertTrue((package / "comments.json").is_file())
            self.assertTrue((package / "signoffs.json").is_file())
            self.assertTrue(store.delete_comment(comment.comment_id))

    def test_signoff_storage_has_no_mutation_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ReviewStore(Path(tmp))
            store.append_signoff("alice", "owner")
            self.assertEqual(len(store.signoffs()), 1)
            self.assertFalse(hasattr(store, "delete_signoff"))
            self.assertFalse(hasattr(store, "update_signoff"))


class ReimportTests(unittest.TestCase):
    def _project(self, root: Path):
        paths = ProjectPaths(root)
        paths.ensure_directories("general")
        paths.source_docx.write_bytes(b"source-old")
        manifest = ProjectManifest(
            documentType="general", documentNo="", documentName="x",
            documentVersion="1.0", sourceSha256=file_sha256(paths.source_docx),
            paths={
                "sourceDocx": "original/source.docx",
                "templateDocx": "template/template.docx",
                "contentRoot": "content/general",
                "assetRoot": "assets/general",
            },
        )
        manifest.save(root)
        return manifest, paths

    def test_source_change_consistent_changed_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, paths = self._project(Path(tmp))
            service = ReimportService(manifest, paths)
            self.assertFalse(service.source_changed())
            paths.source_docx.write_bytes(b"changed")
            self.assertTrue(service.source_changed())
            paths.source_docx.unlink()
            self.assertTrue(service.source_changed())

    def test_compare_conflict_default_keep_choose_new_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, paths = self._project(root)
            content = paths.content_dir("general")
            (content / "a.md").write_text("local", encoding="utf-8")
            base_hash = {"a.md": "not-current"}
            (paths.state_dir / "reimport_base.json").write_text(
                __import__("json").dumps({"files": base_hash}), encoding="utf-8"
            )
            new_source = root / "new.docx"
            new_source.write_bytes(b"source-new")
            def extractor(_source, incoming):
                (incoming / "a.md").write_text("incoming", encoding="utf-8")
                (incoming / "b.md").write_text("added", encoding="utf-8")
            service = ReimportService(manifest, paths)
            result = service.reimport(new_source, extractor=extractor)
            self.assertTrue(result.success, result.message)
            self.assertIn("a.md", result.conflicts)
            self.assertEqual((content / "a.md").read_text(encoding="utf-8"), "local")
            self.assertTrue((content / "b.md").is_file())
            self.assertEqual(service.rollback_last(), [])
            self.assertFalse((content / "b.md").exists())
            result = service.reimport(new_source, choices={"a.md": True}, extractor=extractor)
            self.assertTrue(result.success, result.message)
            self.assertEqual((content / "a.md").read_text(encoding="utf-8"), "incoming")

    def test_preflight_failure_returns_stable_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, paths = self._project(Path(tmp))
            bad = Path(tmp) / "bad.docx"
            bad.write_bytes(b"bad")
            result = ReimportService(manifest, paths).reimport(bad)
            self.assertFalse(result.success)
            self.assertRegex(result.error_code, r"^E\d{4}$")

    def test_compare_source_unchanged_keeps_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current"
            incoming = root / "incoming"
            current.mkdir()
            incoming.mkdir()
            (current / "a.md").write_text("local edit", encoding="utf-8")
            (incoming / "a.md").write_text("base", encoding="utf-8")
            base = {"a.md": hashlib.sha1(b"base").hexdigest()}
            changes = compare_chapters(current, incoming, base)
            self.assertEqual(changes[0].status, "modified")
            self.assertFalse(changes[0].conflict)
            self.assertFalse(changes[0].use_new)  # 源未变 → 保留本地，不覆盖

    def test_compare_local_deleted_is_conflict_keep_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current"
            incoming = root / "incoming"
            current.mkdir()
            incoming.mkdir()
            (incoming / "a.md").write_text("new", encoding="utf-8")
            base = {"a.md": hashlib.sha1(b"old").hexdigest()}
            changes = compare_chapters(current, incoming, base)
            self.assertEqual(changes[0].status, "added")
            self.assertTrue(changes[0].conflict)   # 基线有、本地删 → 冲突
            self.assertFalse(changes[0].use_new)   # 默认保留删除

    def test_rollback_last_restores_pre_reimport_content_of_edited_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, paths = self._project(root)
            content = paths.content_dir("general")
            (content / "a.md").write_text("v1", encoding="utf-8")
            # 本会话先编辑 a.md → 改动清单已有 edit 条目
            writer = ContentWriter(content, paths.state_dir)
            writer.write_text("a.md", "v2")
            (paths.state_dir / "reimport_base.json").write_text(
                json.dumps({"files": {"a.md": hashlib.sha1(b"v1").hexdigest()}}), encoding="utf-8")
            new_source = root / "new.docx"
            new_source.write_bytes(b"source-new")

            def extractor(_source, incoming):
                (incoming / "a.md").write_text("v3", encoding="utf-8")

            service = ReimportService(manifest, paths)
            result = service.reimport(new_source, choices={"a.md": True}, extractor=extractor)
            self.assertTrue(result.success, result.message)
            self.assertEqual((content / "a.md").read_text(encoding="utf-8"), "v3")
            self.assertEqual(service.rollback_last(), [])
            # 回滚必须恢复 a.md 到「重导入前」内容 v2（而非漏回滚停留在 v3）
            self.assertEqual((content / "a.md").read_text(encoding="utf-8"), "v2")

    def test_base_hashes_falls_back_to_content_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, paths = self._project(Path(tmp))
            content = paths.content_dir("general")
            (content / "a.md").write_text("seed", encoding="utf-8")
            from doc_tool.application.content.snapshot import ContentSnapshot
            snapshot = ContentSnapshot(paths.state_dir)
            snapshot.take(content, ["a.md"])
            snapshot.save()
            base = ReimportService(manifest, paths)._base_hashes()
            self.assertEqual(base["a.md"], hashlib.sha1(b"seed").hexdigest())

    def test_first_import_seeds_reimport_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ProjectPaths(root)
            paths.ensure_directories("requirement")
            (paths.content_dir("requirement") / "1.1 范围.md").write_text("# 范围\n", encoding="utf-8")
            from doc_tool.application.import_project import _seed_reimport_base
            _seed_reimport_base(paths, "requirement")
            payload = json.loads((paths.state_dir / "reimport_base.json").read_text(encoding="utf-8"))
            on_disk = (paths.content_dir("requirement") / "1.1 范围.md").read_bytes()
            self.assertEqual(payload["files"]["1.1 范围.md"], hashlib.sha1(on_disk).hexdigest())


class OffscreenTraceabilityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 is unavailable")
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_dialog_validates_and_readonly_disables_save(self):
        from PySide6.QtWidgets import QDialogButtonBox
        from doc_tool.ui.settings_dialog import SettingsDialog
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = ProjectManifest(
                documentType="general", documentNo="", documentName="x",
                documentVersion="1.0", sourceSha256="",
                paths={"templateDocx": "template/template.docx"},
            )
            dialog = SettingsDialog(manifest, root, writable=False)
            self.assertFalse(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).isEnabled())
            dialog.document_name.setText("")
            with self.assertRaises(Exception):
                dialog.validated_manifest()

    def test_lint_issue_result_structure_for_panel(self):
        from doc_tool.application.content.lint import LintIssue
        issue = LintIssue("todo_residual", "a.md", 2, "TODO", "todo_residual", "error")
        self.assertEqual(issue.rule_id, "todo_residual")
        self.assertEqual(issue.severity, "error")


if __name__ == "__main__":
    unittest.main()
