# -*- coding: utf-8 -*-
"""CORE-A 契约与入口测试（任务 1.2/1.3/1.4）。

覆盖：策略适配、默认目标、章节范围决定、缺口归并、出稿契约归一化、
入口路由（真实服务名）以及 ``run_intake`` 对标准/无标题/坏包/Markdown
夹具的真实建项调用。夹具目录放在仓库内 ``tmp/core-scratch``，不依赖系统
临时目录的可写性。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF, HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER,
    POLICY_NORMAL, POLICY_STRICT, SCOPE_CHAPTERS, SCOPE_PROJECT,
    SEVERITY_WARNING, SOURCE_MODE_CURRENT_BUFFER, SOURCE_MODE_SAVED,
    ExportRequest, ExportScope, HeadingDecision, IntakePlan, IntakePolicy,
    PreservationFinding, SectionCandidate, default_document_name, fresh_output_path,
    normalize_formats, placeholder_text, resolve_export_directory, sanitize_name_part,
    unique_directory,
)
from doc_tool.application.intake_entries import (  # noqa: E402
    ACTION_CREATE, ACTION_PENDING_CONVERT, ACTION_REIMPORT, ACTION_UNSUPPORTED,
    KIND_DOC, KIND_DOCX, KIND_MARKDOWN, KIND_PACK, SERVICE_MARKDOWN,
    detect_intake_kind, plan_target, route_for, run_intake,
)


class PolicyTests(unittest.TestCase):
    def test_normal_policy_never_blocks_and_adapts_legacy_flags(self):
        policy = IntakePolicy.normal()
        self.assertEqual(policy.to_legacy_flags(), {
            "allow_missing_headings": True,
            "ignore_roundtrip_block": True,
            "require_exact_roundtrip": False,
        })
        blocked, reason = policy.should_block([
            PreservationFinding("formula", HANDLING_ORIGINAL_ONLY, severity=SEVERITY_WARNING)
        ])
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_strict_policy_blocks_on_warning_and_drops_missing_heading_allowance(self):
        policy = IntakePolicy.strict()
        self.assertFalse(policy.allow_missing_headings)
        self.assertTrue(policy.to_legacy_flags()["require_exact_roundtrip"])
        blocked, reason = policy.should_block([
            PreservationFinding("formula", HANDLING_ORIGINAL_ONLY, severity=SEVERITY_WARNING)
        ])
        self.assertTrue(blocked)
        self.assertIn("严格模式", reason)

    def test_legacy_flags_round_trip(self):
        policy = IntakePolicy.from_legacy_flags(
            ignore_roundtrip_block=False, require_exact_roundtrip=True, allow_missing_headings=True,
        )
        self.assertEqual(policy.mode, POLICY_STRICT)
        normal = IntakePolicy.from_legacy_flags(
            ignore_roundtrip_block=True, require_exact_roundtrip=False, allow_missing_headings=True,
        )
        self.assertEqual(normal.mode, POLICY_NORMAL)

    def test_unknown_mode_falls_back_to_normal(self):
        self.assertEqual(IntakePolicy(mode="whatever").mode, POLICY_NORMAL)


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("target")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_name_from_file_when_no_trusted_metadata(self):
        source = fixtures.standard_docx(self.work / "设备说明.docx")
        target = plan_target(source, parent_dir=self.work / "out")
        self.assertEqual(target.document_name, "设备说明")
        self.assertEqual(target.name_source, "文件名")
        self.assertTrue(target.directory.endswith("设备说明"))

    def test_name_prefers_trusted_metadata_and_sanitizes(self):
        source = fixtures.standard_docx(self.work / "raw.docx")
        target = plan_target(source, parent_dir=self.work / "out", trusted_name='A/B:C*?')
        self.assertEqual(target.document_name, "A_B_C__")
        self.assertEqual(target.name_source, "可信元数据")

    def test_same_name_gets_suffix_and_no_overwrite(self):
        (self.work / "out" / "同名").mkdir(parents=True)
        target = plan_target(self.work / "同名.docx", parent_dir=self.work / "out", trusted_name="同名")
        self.assertTrue(target.directory.endswith("同名-2"))
        self.assertNotEqual(Path(target.directory).name, "同名")

    def test_sanitize_and_default_name_helpers(self):
        self.assertEqual(sanitize_name_part("  名<称>  "), "名_称_")
        self.assertEqual(default_document_name(Path("x/无名.docx")), "无名")
        self.assertEqual(default_document_name(Path("x/a.docx"), "   "), "a")


class PlanTests(unittest.TestCase):
    def _plan(self):
        plan = IntakePlan(
            source="a.docx", sourceKind=KIND_DOCX,
            sections=[
                SectionCandidate("c1", "第1章", level=1, order=0),
                SectionCandidate("c1-1", "1.1", level=2, parent_id="c1", order=1),
                SectionCandidate("c2", "第2章", level=1, order=2),
            ],
        )
        return plan

    def test_selection_keeps_source_order_and_ancestors(self):
        plan = self._plan()
        added = plan.apply_selection(["c1-1"])
        self.assertEqual(added, ["c1"])
        self.assertEqual([s.chapter_id for s in plan.selected_sections()], ["c1", "c1-1"])
        self.assertFalse(plan.scope_is_full())
        by_id = {s.chapter_id: s for s in plan.sections}
        self.assertTrue(by_id["c1"].required_by_selection)
        # 再选两章：仍按源文档顺序（不按点击顺序）返回
        plan.apply_selection(["c2", "c1-1"])
        self.assertEqual([s.chapter_id for s in plan.selected_sections()], ["c1", "c1-1", "c2"])
        self.assertTrue(plan.scope_is_full())

    def test_actionable_findings_limited_to_three_and_counted(self):
        plan = self._plan()
        plan.preservationFindings = [
            PreservationFinding("image", HANDLING_PLACEHOLDER, target_chapter="第1章", action="选择替代图片"),
            PreservationFinding("formula", HANDLING_ORIGINAL_ONLY, target_chapter="第1章", action="查看原件"),
            PreservationFinding("textbox", HANDLING_ORIGINAL_ONLY, target_chapter="第2章"),
            PreservationFinding("footnote", HANDLING_ORIGINAL_ONLY, target_chapter="第2章"),
            PreservationFinding("comment", HANDLING_ORIGINAL_ONLY, target_chapter="第2章"),
        ]
        actions = plan.actionable_findings()
        self.assertEqual(len(actions), 3)
        self.assertEqual(plan.to_fix_count(), 5)
        lines = plan.summary_lines()
        self.assertTrue(any("5 处内容待完善" in line for line in lines))
        self.assertTrue(any(line.startswith("其余 2 项见详情") for line in lines))

    def test_summary_reports_scope_and_strict_block(self):
        plan = self._plan()
        plan.apply_selection(["c2"])
        plan.strictBlocked = True
        plan.strictReason = "命中阈值"
        text = "\n".join(plan.summary_lines())
        self.assertIn("部分范围", text)
        self.assertIn("严格模式未通过", text)

    def test_plan_round_trips_through_dict(self):
        plan = self._plan()
        plan.headingDecisions.append(HeadingDecision("第1章", level=1, style_id="Heading1"))
        plan.policy = IntakePolicy.strict()
        plan.target.document_name = "示例"
        restored = IntakePlan.from_dict(plan.to_dict())
        self.assertEqual(restored.policy.mode, POLICY_STRICT)
        self.assertEqual([s.chapter_id for s in restored.sections], ["c1", "c1-1", "c2"])
        self.assertEqual(restored.headingDecisions[0].style_id, "Heading1")
        self.assertEqual(restored.target.document_name, "示例")


class ExportContractTests(unittest.TestCase):
    def test_format_aliases_and_dedup(self):
        self.assertEqual(normalize_formats(["Word", "docx", "PDF", "zip"]), [FORMAT_DOCX, FORMAT_PDF, "source-zip"])
        self.assertEqual(normalize_formats([]), [])

    def test_request_defaults_and_source_mode_fallback(self):
        request = ExportRequest(formats=["word"], source_mode="bogus")
        self.assertEqual(request.formats, [FORMAT_DOCX])
        self.assertEqual(request.source_mode, SOURCE_MODE_SAVED)
        request2 = ExportRequest(source_mode=SOURCE_MODE_CURRENT_BUFFER)
        self.assertEqual(request2.source_mode, SOURCE_MODE_CURRENT_BUFFER)

    def test_scope_normalizes_and_describes(self):
        scope = ExportScope(kind=SCOPE_CHAPTERS, chapters=["第2章", "第1章"])
        self.assertEqual(scope.describe(), "所选 2 章：第2章、第1章")
        self.assertFalse(scope.is_full)
        self.assertEqual(ExportScope(kind="nope").kind, SCOPE_PROJECT)
        self.assertEqual(ExportScope.from_dict(scope.to_dict()).chapters, ["第2章", "第1章"])
        self.assertEqual(ExportScope(kind=SCOPE_PROJECT, chapters=["x"]).chapters, [])

    def test_placeholder_text_is_visible_and_source_tagged(self):
        text = placeholder_text("formula", "original/source.docx")
        self.assertIn("公式", text)
        self.assertIn("original/source.docx", text)

    def test_export_directory_falls_back_and_reports(self):
        work = fixtures.scratch_dir("export-dir")
        try:
            chosen, note = resolve_export_directory(work / "ok", [work / "backup"])
            self.assertEqual(note, None)
            chosen2, note2 = resolve_export_directory(work / "missing" / "nul" if False else Path("Z:/nope"), [work / "backup"])
            self.assertIsNotNone(note2)
            self.assertTrue(Path(chosen2).is_dir())
        finally:
            fixtures.cleanup(work)

    def test_fresh_output_path_avoids_existing_name(self):
        work = fixtures.scratch_dir("fresh")
        try:
            target = work / "out.docx"
            target.write_text("x", encoding="utf-8")
            fresh = fresh_output_path(target)
            self.assertEqual(fresh.name, "out-2.docx")
            self.assertNotEqual(fresh, target)
        finally:
            fixtures.cleanup(work)

    def test_unique_directory_suffix(self):
        work = fixtures.scratch_dir("uniq")
        try:
            (work / "同名").mkdir()
            self.assertEqual(unique_directory(work, "同名").name, "同名-2")
        finally:
            fixtures.cleanup(work)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("route")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_detect_kinds(self):
        docx = fixtures.standard_docx(self.work / "a.docx")
        md = self.work / "a.md"
        md.write_text("# t\n", encoding="utf-8")
        pack = self.work / "pack"
        pack.mkdir()
        (pack / "project.yml").write_text("documentType: general\n", encoding="utf-8")
        broken = fixtures.broken_docx(self.work / "b.docx")
        self.assertEqual(detect_intake_kind(docx), KIND_DOCX)
        self.assertEqual(detect_intake_kind(md), KIND_MARKDOWN)
        self.assertEqual(detect_intake_kind(pack), KIND_PACK)
        self.assertEqual(detect_intake_kind(broken), KIND_DOCX)
        self.assertEqual(detect_intake_kind(self.work / "x.unknown"), "unknown")

    def test_routes_use_real_services(self):
        docx = fixtures.standard_docx(self.work / "a.docx")
        route = route_for(docx)
        self.assertEqual(route.action, ACTION_CREATE)
        self.assertEqual(route.service, "import_first_time")
        self.assertTrue(route.available)
        md = self.work / "a.md"
        md.write_text("# t\n", encoding="utf-8")
        self.assertEqual(route_for(md).service, SERVICE_MARKDOWN)
        pack = self.work / "pack"
        (pack / "quality").mkdir(parents=True, exist_ok=True)
        (pack / "project.yml").write_text("documentType: general\n", encoding="utf-8")
        self.assertEqual(route_for(pack).service, "create_project_from_pack")
        # 已打开项目接收外部 Word -> 差异重导入，不新建项目
        opened = route_for(docx, project_open=True)
        self.assertEqual(opened.action, ACTION_REIMPORT)
        self.assertEqual(opened.service, "ReimportService.reimport")

    def test_doc_without_word_is_pending_convert(self):
        doc = self.work / "old.doc"
        doc.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
        route = route_for(doc, word_available=False)
        self.assertEqual(route.kind, KIND_DOC)
        self.assertEqual(route.action, ACTION_PENDING_CONVERT)
        self.assertFalse(route.available)
        self.assertIn("Word", route.suggested_action)

    def test_unknown_input_is_unsupported(self):
        route = route_for(self.work / "x.zip")
        self.assertEqual(route.action, ACTION_UNSUPPORTED)
        outcome = run_intake(self.work / "x.zip", parent_dir=self.work / "out")
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.errors)


class RunIntakeTests(unittest.TestCase):
    """真实调用建项服务：标准/坏包/Markdown/待转换。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("run")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_broken_package_fails_without_creating_project(self):
        broken = fixtures.broken_docx(self.work / "坏包.docx")
        outcome = run_intake(broken, parent_dir=self.out)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.errors)
        self.assertIsNone(outcome.project_root)
        # 失败只写诊断日志，不建立任何项目目录
        self.assertEqual(
            [item for item in self.out.iterdir() if item.is_dir()], []
        )
        self.assertFalse((self.out / "project.yml").exists())

    def test_markdown_multi_file_creates_single_project_in_order(self):
        first = self.work / "1 概述.md"
        first.write_text("# 概述\n\n正文一。\n", encoding="utf-8")
        second = self.work / "2 设计.md"
        second.write_text("# 设计\n\n正文二。\n", encoding="utf-8")
        outcome = run_intake(
            first, parent_dir=self.out,
            markdown_sources=[first, second],
            target_name="Markdown 项目",
        )
        self.assertTrue(outcome.ok, outcome.errors)
        root = Path(outcome.project_root)
        self.assertTrue((root / "project.yml").is_file())
        manifest_text = (root / "project.yml").read_text(encoding="utf-8")
        self.assertIn("1 概述.md", manifest_text)
        self.assertLess(manifest_text.index("1 概述.md"), manifest_text.index("2 设计.md"))

    def test_doc_without_word_reports_pending_and_keeps_input(self):
        doc = self.work / "旧格式.doc"
        doc.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
        before = doc.read_bytes()
        outcome = run_intake(doc, parent_dir=self.out, word_available=False)
        self.assertFalse(outcome.ok)
        self.assertEqual(len(outcome.pending), 1)
        self.assertTrue(doc.is_file())
        self.assertEqual(doc.read_bytes(), before)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_standard_docx_creates_editable_project(self):
        source = fixtures.standard_docx(self.work / "标准文档.docx")
        outcome = run_intake(source, parent_dir=self.out, document_no="")
        self.assertTrue(outcome.ok, outcome.errors or outcome.summary_lines())
        root = Path(outcome.project_root)
        self.assertTrue((root / "project.yml").is_file())
        self.assertTrue((root / "original" / "source.docx").is_file())
        chapter_dirs = sorted(p.name for p in (root / "content").rglob("*") if p.is_dir())
        chapter_files = sorted(p.name for p in (root / "content").rglob("*.md"))
        self.assertTrue(any("第1章 引言" == name for name in chapter_dirs), chapter_dirs)
        self.assertTrue(any("第2章 设计" == name for name in chapter_dirs), chapter_dirs)
        self.assertTrue(any(name.endswith("目的.md") for name in chapter_files), chapter_files)
        self.assertIsNotNone(outcome.plan)
        self.assertIn("已生成可编辑项目", outcome.summary_lines()[0])
        # 编号可空：默认目标不带编号也能建项
        self.assertEqual(outcome.plan.target.document_no, "")

    def test_reimport_route_refuses_first_time_build(self):
        source = fixtures.standard_docx(self.work / "外部修改.docx")
        outcome = run_intake(source, parent_dir=self.out, project_root=self.work)
        self.assertFalse(outcome.ok)
        self.assertTrue(any("重新导入" in item for item in outcome.errors))
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)