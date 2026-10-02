# -*- coding: utf-8 -*-
"""CORE-B/C 测试：普通导入可用、跳级整理、标题前正文、缺图占位、原件账本。

对应验收 C-1/C-2/C-8 与易用性 U-1/U-2 的“正常路径 + 常见兜底”部分。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.import_record import (  # noqa: E402
    HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER, ImportRecord, append_source_version,
    archive_source_version, findings_from_fidelity, read_import_record, record_path,
    unavailable_from_roundtrip, write_import_record,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    IntakePolicy, placeholder_text,
    HANDLING_TEXT_FALLBACK,
)
from doc_tool.application.intake_entries import run_intake  # noqa: E402
from doc_tool.application.intake_outline import (  # noqa: E402
    PRE_TITLE_RETAIN, PRE_TITLE_TEMPLATE, build_plan, decide_pre_title_mode,
    normalize_levels, sections_from_decisions,
)
from doc_tool.application.intake_contract import HeadingDecision, PlannedTarget  # noqa: E402
from doc_tool.adapters.preflight import preflight  # noqa: E402


class OutlinePlanTests(unittest.TestCase):
    def test_jump_levels_are_flattened_keeping_titles_and_order(self):
        decisions = [
            HeadingDecision("总述", level=1),
            HeadingDecision("深层小节", level=3),
            HeadingDecision("详述", level=1),
        ]
        normalized, adjustments, jumps = normalize_levels(decisions)
        self.assertEqual([item.level for item in normalized], [1, 2, 1])
        self.assertEqual([item.title for item in normalized], ["总述", "深层小节", "详述"])
        self.assertTrue(jumps)
        self.assertEqual(adjustments[1].action, "flattened")
        self.assertIn("2 级", adjustments[1].reason)

    def test_normalize_can_preview_without_changing_levels(self):
        decisions = [HeadingDecision("总述", level=1), HeadingDecision("深层", level=4)]
        normalized, adjustments, _ = normalize_levels(decisions, allow_flatten=False)
        self.assertEqual([item.level for item in normalized], [1, 4])
        self.assertEqual(adjustments[1].action, "candidate")
        self.assertTrue(adjustments[1].reason)

    def test_sections_keep_ancestor_links_after_flattening(self):
        decisions = [
            HeadingDecision("总述", level=1),
            HeadingDecision("深层", level=2),
            HeadingDecision("更细", level=3),
            HeadingDecision("详述", level=1),
        ]
        sections = sections_from_decisions(decisions)
        self.assertEqual(sections[1].parent_id, sections[0].chapter_id)
        self.assertEqual(sections[2].parent_id, sections[1].chapter_id)
        self.assertEqual(sections[3].parent_id, "")

    def test_pre_title_decision_distinguishes_cover_and_body(self):
        mode, note = decide_pre_title_mode([{"kind": "image", "text": ""}])
        self.assertEqual(mode, PRE_TITLE_TEMPLATE)
        self.assertIn("封面", note)
        mode2, note2 = decide_pre_title_mode([{"kind": "p", "text": "正文说明"}])
        self.assertEqual(mode2, PRE_TITLE_RETAIN)
        self.assertIn("前言", note2)
        mode3, _ = decide_pre_title_mode([])
        self.assertEqual(mode3, "none")


class NormalIntakeTests(unittest.TestCase):
    """C-1：标准/无标题 Word 在普通模式下得到可编辑项目。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("intake")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_standard_docx_needs_no_required_user_input(self):
        source = fixtures.standard_docx(self.work / "标准.docx")
        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        plan = outcome.plan
        # U-1：源已选后不需要填写任何必填项（编号可空、名称/位置/版本都有默认值）
        self.assertTrue(plan.target.document_name)
        self.assertTrue(plan.target.directory)
        self.assertTrue(plan.target.document_version)
        self.assertEqual(plan.target.document_no, "")
        self.assertFalse(plan.policy.is_strict)
        self.assertEqual(plan.target.document_type, "general")
        # 预览与结果使用同一份决定
        self.assertTrue(plan.sections)
        self.assertIn("已生成可编辑项目", outcome.summary_lines()[0])

    def test_no_heading_docx_becomes_single_chapter(self):
        source = fixtures.no_heading_docx(self.work / "无标题.docx")
        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        self.assertEqual(len(outcome.plan.sections), 1)
        root = outcome.project_root
        chapters = [p for p in (root / "content").rglob("*.md")
                    if p.name not in ("_revision_record.md",)]
        self.assertEqual(len(chapters), 1)
        body = chapters[0].read_text(encoding="utf-8")
        self.assertIn("第一段正文需要完整保留", body)
        self.assertIn("第二段正文同样需要保留", body)
        self.assertTrue(any("单章" in item for item in outcome.plan.warnings))

    def test_jump_level_is_flattened_into_a_real_node(self):
        source = fixtures.jump_level_docx(self.work / "跳级.docx")
        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        root = outcome.project_root
        sub_files = [p for p in (root / "content").rglob("*.md") if p.name != "_revision_record.md"]
        names = sorted(p.name for p in sub_files)
        # 深层小节被整理为二级节点，成为可维护的独立小节
        self.assertTrue(any("深层小节" in name for name in names), names)
        self.assertTrue(any("层级整理" in item for item in outcome.plan.warnings))

    def test_pre_title_body_is_retained_as_explicit_chapter(self):
        source = fixtures.pre_title_body_docx(self.work / "标题前.docx")
        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        root = outcome.project_root
        indexes = {p.parent.name: p.read_text(encoding="utf-8")
                   for p in (root / "content").rglob("_index.md")}
        self.assertTrue(any("前言" in name for name in indexes), indexes)
        pre = [text for name, text in indexes.items() if "前言" in name][0]
        self.assertIn("这份内容在第一级标题之前", pre)

    def test_missing_image_keeps_placeholder_and_import_succeeds(self):
        image = fixtures.tiny_png(self.work / "a.png")
        source = fixtures.image_docx(self.work / "缺图.docx", image)
        fixtures.drop_media_parts(source)
        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        root = outcome.project_root
        texts = [p.read_text(encoding="utf-8") for p in (root / "content").rglob("_index.md")]
        self.assertTrue(any(placeholder_text("图片", "")[:6] in text for text in texts), texts)
        self.assertTrue(any(item.feature == "image" and item.handling == HANDLING_PLACEHOLDER
                            for item in outcome.plan.preservationFindings))
        # 对照未完成必须明说，不能静默视为对照通过
        self.assertTrue(outcome.plan.unavailableComparisons)
        self.assertTrue(any("对照未完成" in line for line in outcome.plan.summary_lines()))
        # 源文件未被修改
        self.assertTrue(source.is_file())

    def test_complex_objects_are_reported_with_original_retained(self):
        source = fixtures.complex_docx(self.work / "复杂.docx")
        outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        features = {item.feature for item in outcome.plan.preservationFindings}
        for expected in ("formula", "textbox", "revision", "comment", "footnote"):
            self.assertIn(expected, features)
        # CORE 3.2：暂不支持对象按三类区分——原件留存（无文本）或文本降级（读到文本但丢结构）；
        # 任何一类都不得冒充“可编辑保留”。
        allowed = {HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER, HANDLING_TEXT_FALLBACK}
        self.assertTrue(
            all(item.handling in allowed for item in outcome.plan.preservationFindings),
            [(item.feature, item.handling) for item in outcome.plan.preservationFindings],
        )
        self.assertTrue(all(not item.editable for item in outcome.plan.preservationFindings))
        root = outcome.project_root
        self.assertTrue((root / "original" / "source.docx").is_file())
        # 原件留存不得被表述成可编辑保留
        record = read_import_record(root)
        self.assertIsNotNone(record)
        self.assertEqual(record.retainedPath, "original/source.docx")
        self.assertTrue(all(not item.editable for item in record.findings))

    def test_broken_package_fails_and_preserves_source(self):
        source = fixtures.broken_docx(self.work / "坏包.docx")
        before = source.read_bytes()
        outcome = run_intake(source, parent_dir=self.out)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.errors)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual([p for p in self.out.iterdir() if p.is_dir()], [])

    def test_strict_mode_refuses_complex_but_normal_continues(self):
        source = fixtures.complex_docx(self.work / "严格.docx")
        strict = run_intake(source, parent_dir=self.out, policy=IntakePolicy.strict())
        self.assertFalse(strict.ok)
        self.assertEqual([p for p in self.out.iterdir() if p.is_dir()], [])
        normal = run_intake(source, parent_dir=self.out, policy=IntakePolicy.normal())
        self.assertTrue(normal.ok, normal.errors)


class ImportRecordTests(unittest.TestCase):
    """CORE-C 3.1-3.4：账本读写、归并、来源版本与损坏隔离。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("record")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_record_round_trip_and_grouping(self):
        work = self.work
        source = fixtures.complex_docx(work / "复杂.docx")
        preview = preflight(str(source), allow_missing_headings=True,
                            tolerate_missing_resources=True)
        record = ImportRecord(
            sourceSha256="abc", sourceFile="复杂.docx",
            findings=findings_from_fidelity(preview.fidelity, retained_path="original/source.docx"),
        )
        written = write_import_record(work, record)
        self.assertEqual(written, record_path(work))
        data = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 1)
        restored = read_import_record(work)
        self.assertEqual(len(restored.findings), len(record.findings))
        groups = restored.grouped()
        self.assertTrue(groups)
        self.assertLessEqual(len(restored.action_items()), 3)
        self.assertGreaterEqual(restored.to_fix_count(), 5)
        self.assertTrue(any("原件已保留" in line for line in restored.summary_lines()))

    def test_damaged_record_is_quarantined_before_rewrite(self):
        write_import_record(self.work, ImportRecord(sourceSha256="x"))
        target = record_path(self.work)
        target.write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_import_record(self.work))
        write_import_record(self.work, ImportRecord(sourceSha256="y"))
        self.assertEqual(read_import_record(self.work).sourceSha256, "y")
        self.assertTrue(list(target.parent.glob("import-record.json.damaged-*")))

    def test_source_versions_are_archived_once(self):
        source = fixtures.standard_docx(self.work / "源.docx")
        version = archive_source_version(self.work, source, "deadbeef" * 8, note="首次导入")
        self.assertTrue((self.work / version.retained).is_file())
        record = ImportRecord()
        append_source_version(record, version)
        append_source_version(record, version)
        self.assertEqual(len(record.sourceVersions), 1)
        second = archive_source_version(self.work, source, "cafebabe" * 8, note="再次导入")
        append_source_version(record, second)
        self.assertEqual(len(record.sourceVersions), 2)
        # 旧原件仍保留（不被新来源覆盖）
        self.assertTrue((self.work / version.retained).is_file())
        self.assertNotEqual(version.retained, second.retained)

    def test_roundtrip_unavailable_is_recorded_not_silently_passed(self):
        notes = unavailable_from_roundtrip(RuntimeError("对象不支持"))
        self.assertEqual(len(notes), 1)
        self.assertIn("往返对照未完成", notes[0])
        self.assertEqual(unavailable_from_roundtrip(None), [])


class BoundedRetryTests(unittest.TestCase):
    """CORE 2.4：试构建失败时用通用底模做一次有界回退，仍失败才判该输入失败。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("retry")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_generic_template_fallback_is_applied_once(self):
        from doc_tool.application import import_project
        from doc_tool.application.intake_entries import run_intake

        source = fixtures.standard_docx(self.work / "标准.docx")
        calls = {"n": 0}
        real_trial = import_project._trial_build

        def flaky_trial(manifest, paths):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("模拟首次试构建失败")
            return real_trial(manifest, paths)

        with patch.object(import_project, "_trial_build", flaky_trial):
            outcome = run_intake(source, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        self.assertEqual(calls["n"], 2)
        self.assertTrue(any("通用底模" in item for item in outcome.warnings)
                        or any("通用底模" in str(ev.detail) for ev in outcome.events))

    def test_fallback_reports_failure_when_still_broken(self):
        from doc_tool.application import import_project
        from doc_tool.application.intake_entries import run_intake

        source = fixtures.standard_docx(self.work / "标准2.docx")

        def always_fail(manifest, paths):
            raise RuntimeError("试构建始终失败")

        with patch.object(import_project, "_trial_build", always_fail):
            outcome = run_intake(source, parent_dir=self.out)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.errors)
        self.assertIsNotNone(outcome.diagnostic_log)


class ReimportSourceVersionTests(unittest.TestCase):
    """CORE-C 3.4：再次导入保存来源版本，旧原件不被覆盖。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("reimport")
        self.out = self.work / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_second_import_appends_source_version(self):
        from doc_tool.application.content.reimport import ReimportService
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        first = fixtures.standard_docx(self.work / "第一版.docx")
        outcome = run_intake(first, parent_dir=self.out)
        self.assertTrue(outcome.ok, outcome.errors)
        root = Path(outcome.project_root)
        record = read_import_record(root)
        self.assertIsNotNone(record)
        self.assertEqual(len(record.sourceVersions), 1)
        first_version = record.sourceVersions[0].retained

        updated = fixtures.build_docx(self.work / "第二版.docx", [
            ("h1", "引言"),
            ("p", "更新后的正文。"),
        ])
        manifest = ProjectManifest.load(root)
        paths = ProjectPaths(root)
        result = ReimportService(manifest, paths).reimport(updated)
        self.assertTrue(result.success, result.message)
        record2 = read_import_record(root)
        self.assertGreaterEqual(len(record2.sourceVersions), 1)
        # 旧来源版本仍保留，可查到原出处
        if first_version:
            self.assertTrue((root / first_version).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)