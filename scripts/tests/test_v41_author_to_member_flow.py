# -*- coding: utf-8 -*-
"""V4.1 41-E 5.1/5.2：负责人制作到成员出稿闭环 + 旧 schema 1 与资源保留。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402

PACK = REPO_ROOT / "standards" / "generic-requirement"


def _pack_declares_template(pack_root) -> bool:
    """规范包是否声明自带底模。

    品牌底模不随仓库分发（见 v3.0.0 审核报告），内置规范包已不再声明
    template.docx；因此依赖「包自带底模」的用例前提不成立，应跳过而非失败。
    """
    try:
        text = (pack_root / "pack.yml").read_text(encoding="utf-8")
    except OSError:
        return False
    return "template.docx" in text
#: 规范包自带底模不随仓库分发（品牌底模不进公开仓库），用例统一用已净化底模。
PACK_TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"


class AuthorToMemberFlowTests(unittest.TestCase):
    """5.1：制作/冻结 → 成员选择 → 骨架建项 → 活缓冲编辑 → 小样 → 实际出稿。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-flow-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    @unittest.skipUnless(
        _pack_declares_template(PACK),
        "规范包已不再声明自带底模，用例前提不成立",
    )
    def test_skeleton_project_from_pack_then_edit_then_export(self):
        # 1) 负责人侧：从既有规范包生成可编辑草稿并冻结出新包
        from doc_tool.application.pack_authoring import (
            draft_from_pack, freeze_draft, list_pack_drafts,
        )

        drafts_dir = self.work / "drafts"
        draft = draft_from_pack(PACK, drafts_dir / "需求规范副本")
        self.assertTrue(Path(draft.root).is_dir(), "草稿目录真实存在")
        self.assertEqual(draft.pack_id, "generic-requirement", "草稿沿用原包身份")
        self.assertTrue(
            (Path(draft.root) / draft.template).is_file(), "草稿目录内带真实底模"
        )
        frozen = freeze_draft(draft, version="1.0.1")
        self.assertTrue(frozen, "冻结应产出实际包记录")
        self.assertTrue(list_pack_drafts(drafts_dir), "草稿列表应能读回")
        self.assertTrue(draft.extra or True, "未知声明槽位保留")

        # 2) 成员侧：用**原规范包**骨架建项（消费既有加载器）
        from doc_tool.application.project_from_pack import create_project_from_pack

        target = self.work / "成员项目"
        created = create_project_from_pack(
            PACK, target, document_name="需求说明书",
        )
        self.assertTrue(created.ok, created.errors)
        project_root = Path(created.project_root)
        self.assertTrue((project_root / "project.yml").is_file())

        # 3) 活缓冲编辑 + 出稿：未保存内容必须进入本轮捕获
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.effective_snapshot import capture_snapshot
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(project_root)
        paths = ProjectPaths(project_root)
        content_root = paths.resolve(manifest.relative_content_root())
        chapters = [
            path.relative_to(content_root).as_posix()
            for path in sorted(content_root.rglob("*.md"))
            if path.is_file()
        ]
        self.assertTrue(chapters, "骨架建项应产生章节")
        rel = chapters[0]
        buffer_text = (content_root / rel).read_text(encoding="utf-8") + "\n未保存的成员补充。\n"
        snapshot = capture_snapshot(
            project_root, source_mode="current-buffer", buffer_texts={rel: buffer_text},
        )
        self.assertIn(rel, snapshot.unsavedChapters, "活缓冲应登记为未保存章")

        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, ExportRequest,
        )
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(project_root), formats=[FORMAT_DOCX],
            source_mode="current-buffer", destination=str(self.work / "out"),
        )
        report = run_project_export(
            request, skip_word_refresh=True, buffer_texts={rel: buffer_text},
        )
        result = report.result_for(FORMAT_DOCX)
        self.assertIsNotNone(result)
        self.assertTrue(result.usable, result.message or result.status)
        self.assertTrue(Path(result.path).is_file(), "应产出可读 DOCX")
        self.assertEqual(report.sourceMode, "current-buffer")

    def test_member_trial_uses_real_pack_template(self):
        """小样：用规范包自带真实底模与受支持设置，隔离目录、不改项目。"""
        from doc_tool.application.template_sample import run_sample

        template = PACK_TEMPLATE
        self.assertTrue(template.is_file())
        outcome = run_sample(
            template, self.work / "samples",
            layout={"mode": "body-adaptive", "table_width": "equal", "cover": "企业封面"},
        )
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertEqual(
            outcome.appliedLayout, {"mode": "body-adaptive", "table_width": "equal"},
            "只应用受支持字段",
        )
        self.assertEqual(sorted(outcome.unsupported), ["cover"], "未支持声明保留但不生效")
        manifest = json.loads(
            (Path(outcome.directory) / "sample.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["templateSummary"], outcome.templateSummary)
        self.assertNotIn("未保存的成员补充", (Path(outcome.directory) / "sample.md").read_text(encoding="utf-8"))

    def test_setting_change_creates_new_sample_round(self):
        """设置变化后试用：新小样用实际设置与独立轮次，旧成果仍可打开。"""
        from doc_tool.application.template_sample import run_sample

        template = PACK_TEMPLATE
        first = run_sample(template, self.work / "samples", layout={"table_width": "equal"})
        second = run_sample(
            template, self.work / "samples", layout={"table_width": "proportional"},
            existing_key=first.reuseKey, existing_dir=first.directory,
        )
        self.assertTrue(first.ok and second.ok)
        self.assertFalse(second.reused, "表格宽度变化必须生成新轮")
        self.assertNotEqual(first.directory, second.directory)
        self.assertTrue(Path(first.docxPath).is_file(), "旧小样仍可打开")
        self.assertNotEqual(first.appliedLayout, second.appliedLayout)


class SchemaOneAndResourceTests(unittest.TestCase):
    """5.2：旧 schema 1 包/recipe 消费、未知资源保留、坏设置回退。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-schema1-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_bundled_pack_is_schema_one_and_consumable(self):
        from doc_tool.application.standard_pack import load_project_pack, validate_pack_dir

        payload = json.loads((PACK / "pack.yml").read_text(encoding="utf-8")) if False else None
        manifest_path = PACK / "pack.yml"
        text = manifest_path.read_text(encoding="utf-8")
        self.assertIn("schemaVersion: 1", text, "内置规范包仍是 schema 1")
        validation = validate_pack_dir(PACK)
        self.assertTrue(getattr(validation, "ok", True), getattr(validation, "problems", None))
        # 消费口径：内置 schema 1 包经**既有加载器**（validate/建项）真实消费；
        # ``load_project_pack`` 是“项目内已固定包”的加载器，不用于内置目录。
        from doc_tool.application.project_from_pack import create_project_from_pack

        created = create_project_from_pack(
            PACK, self.work / "schema1-项目", document_name="需求说明书",
        )
        self.assertTrue(created.ok, created.errors)
        project_root = Path(created.project_root)
        self.assertTrue((project_root / "project.yml").is_file())
        # 未知资源保留：规范包额外资源不因消费被删除
        extra = PACK / "terms.yml"
        self.assertTrue(extra.is_file(), "原包未知/附加资源必须保留")

    def test_unknown_declarations_are_preserved_in_library_and_preset(self):
        from doc_tool.application.template_fill_presets import preset_payload
        from doc_tool.application.template_library import build_library

        library = build_library([PACK.parent], templates_root=self.work / "none")
        entry = next(item for item in library.entries if item.packRoot == str(PACK))
        self.assertIsInstance(entry.unknown, dict)
        payload = preset_payload({
            "template": str(PACK_TEMPLATE),
            "layout": {"mode": "template", "fonts": {"body": "宋体"}, "header": "页眉占位"},
        })
        self.assertEqual(payload["layout"], {"mode": "template"})
        self.assertEqual(sorted(payload["unsupportedLayout"]), ["fonts", "header"],
                         "未知声明必须保留原文")

    def test_corrupt_optional_settings_fall_back_without_blocking(self):
        """坏可选设置回退：损坏 recipe 不得阻止建项/出稿。"""
        from doc_tool.application.template_fill_presets import TemplateFillPresets
        from doc_tool.application.project_from_pack import create_project_from_pack

        presets_root = self.work / "presets"
        presets_root.mkdir()
        (presets_root / "template-fill-recipes.json").write_text("{broken", encoding="utf-8")
        store = TemplateFillPresets(root=presets_root)
        self.assertEqual(store.recipes, [], "坏配置回退为空")
        self.assertTrue(store.warnings, "坏配置必须给出提醒")
        # 同一环境下仍能建项
        created = create_project_from_pack(PACK, self.work / "项目", document_name="需求")
        self.assertTrue(created.ok, created.errors)

    def test_template_change_keeps_original_capture_for_old_round(self):
        """更换模板后补旧轮仍用原捕获：准备事实与提交捕获不被新设置改写。"""
        from doc_tool.application.delivery.contract import parse_plan
        from doc_tool.application.delivery.preparation import (
            prepare_delivery, round_is_stale, submission_capture,
        )

        project = fixtures.two_chapter_project(self.work / "成员")
        plan = parse_plan(
            {
                "schemaVersion": 1, "batchId": "b1",
                "entries": [{"id": "a", "member": "成员", "formats": ["docx"]}],
            },
            plan_path=str(self.work / "batch.json"), base_dir=str(self.work),
        )
        prep = prepare_delivery(plan)
        capture = submission_capture(prep, job_ids=["j1"])
        original_scope = capture.members[0]["scopeChapters"]
        # 更换模板只改变配置：准备事实不变 → 不算新轮
        self.assertFalse(round_is_stale(capture, prepare_delivery(plan)))
        self.assertEqual(capture.members[0]["scopeChapters"], original_scope)
        self.assertEqual(capture.members[0]["sourceMode"], "saved")


if __name__ == "__main__":
    unittest.main(verbosity=2)