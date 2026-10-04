# -*- coding: utf-8 -*-
"""V4.3 43-E 5.1：三个合成成员走完整交付闭环（真实入口、真实文件）。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class ThreeMemberClosedLoopTests(unittest.TestCase):
    """准备 → 提交后编辑 → 部分失败 → 补原轮 → 新轮 → 两版比较 → 修订说明 → 离线包 → 副本恢复。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-e-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.members = {}
        for name in ("Alpha", "Beta", "Gamma"):
            self.members[name] = fixtures.two_chapter_project(self.work / name)

    def _plan(self, *, entries=None, batch_id="batch-e"):
        from doc_tool.application.delivery.contract import parse_plan

        payload = {
            "schemaVersion": 1, "batchId": batch_id,
            "defaults": {"formats": ["docx", "html"]},
            "entries": entries or [
                {"id": name.lower(), "member": name, "formats": ["docx", "html"]}
                for name in self.members
            ],
        }
        return parse_plan(
            payload, plan_path=str(self.work / "batch.json"), base_dir=str(self.work),
        )

    def test_prepare_submit_export_compare_package_recover(self):
        from doc_tool.application.delivery.preparation import (
            prepare_delivery, round_is_stale, submission_capture,
        )
        from doc_tool.application.intake_contract import ExportRequest
        from doc_tool.application.project_export import run_project_export

        # 1) 准备 + 提交捕获
        prep = prepare_delivery(self._plan())
        self.assertEqual(prep.completeness, "full")
        self.assertEqual([row.member for row in prep.executableRows], ["Alpha", "Beta", "Gamma"])
        capture = submission_capture(prep, job_ids=["j-a", "j-b", "j-g"])
        self.assertEqual(capture.memberCount, 3)

        # 2) 逐成员真实出稿（一成员刻意只出 HTML → 部分失败场景）
        reports = {}
        for row in prep.executableRows:
            formats = ["html"] if row.member == "Beta" else list(row.formats)
            request = ExportRequest(
                project_root=row.projectRoot, formats=formats,
                source_mode="saved", destination=str(self.work / "out" / row.member),
            )
            reports[row.member] = run_project_export(request, skip_word_refresh=True)
        self.assertIn("docx", [item.format for item in reports["Alpha"].results])
        self.assertEqual([item.format for item in reports["Beta"].results], ["html"],
                         "Beta 只出 HTML，用于部分失败场景")
        alpha_docx = reports["Alpha"].result_for("docx")
        self.assertTrue(alpha_docx.usable, alpha_docx.message)
        self.assertTrue(Path(alpha_docx.path).is_file())

        # 3) 提交后编辑只影响下一轮
        changed = prepare_delivery(self._plan(), current_buffer_members=["Beta"])
        self.assertTrue(round_is_stale(capture, changed), "提交后编辑应属于下一轮")
        self.assertEqual([item["sourceMode"] for item in capture.members],
                         ["saved", "saved", "saved"])

        # 4) 补原轮：从原报告身份恢复，补 Beta 的 docx
        beta_retry = run_project_export(
            ExportRequest(
                project_root=str(self.members["Beta"]), formats=["docx"],
                source_mode="saved", destination=str(self.work / "out" / "Beta"),
            ),
            skip_word_refresh=True,
        )
        self.assertTrue(beta_retry.result_for("docx").usable)
        self.assertTrue(Path(beta_retry.result_for("docx").path).is_file())

        # 5) 新轮：正文变化后明确新轮，且捕获身份不同
        target = self.members["Alpha"] / "content" / "general" / "第1章 引言" / "1.1 目的.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n新增一段。\n", encoding="utf-8")
        new_round = run_project_export(
            ExportRequest(
                project_root=str(self.members["Alpha"]), formats=["html"],
                source_mode="saved", destination=str(self.work / "out-new" / "Alpha"),
            ),
            skip_word_refresh=True,
        )
        self.assertNotEqual(new_round.captureId, reports["Alpha"].captureId,
                            "新轮必须有独立捕获身份")

        # 5b) 两版比较 + 修订说明（用真实基线，非按显示名）
        from doc_tool.application.collection import build_manifest, register_manifest
        from doc_tool.application.delivery.revision_compare import (
            build_revision_note, compare_versions, list_versions,
        )

        versions = []
        for version, extra in (("v1", ""), ("v2", "\n第二版新增内容。\n")):
            root = self.work / ("比较工程-" + version)
            shutil.copytree(self.members["Alpha"], root)
            item = root / "content" / "general" / "第1章 引言" / "1.1 目的.md"
            item.write_text(item.read_text(encoding="utf-8") + extra, encoding="utf-8")
            manifest = build_manifest(root, version=version, label="同类集合")
            path, error = register_manifest(root, manifest)
            self.assertEqual(error, "")
            versions.append(list_versions(root)[0])
        comparison = compare_versions(
            versions[0].identity, versions[1].identity, options=versions,
        )
        self.assertTrue(comparison.known, comparison.reason)
        self.assertNotEqual(versions[0].identity, versions[1].identity,
                            "同名集合必须按真实身份区分")
        changed = {
            item["relativePath"]
            for items in comparison.groups.values() for item in items
        }
        self.assertIn("content/general/第1章 引言/1.1 目的.md", changed,
                      "正文章节变化必须出现在两版差异里")
        note = build_revision_note(comparison)
        self.assertIn("1.1 目的.md", note.text)
        note.update("手工修订说明：本次更新了目的章节。")
        self.assertTrue(note.edited)
        self.assertIn("1.1 目的.md", note.prefilled)

        # 6) 离线 HTML 可打开且不依赖源目录
        html_path = Path(reports["Alpha"].result_for("html").path)
        self.assertTrue(html_path.is_file())
        self.assertIn("docs-as-code".lower() if False else "<html", html_path.read_text(encoding="utf-8")[:2000].lower())

        # 7) 离线包 + 用途判定
        from doc_tool.application.delivery.handover import (
            PURPOSE_READABLE, build_handover_package, inspect_package,
        )

        package = build_handover_package(
            reports["Alpha"], destination=self.work / "成果包.zip",
        )
        self.assertTrue(package.ok, package.warnings)
        self.assertEqual(package.facts.purpose, PURPOSE_READABLE)
        self.assertTrue(package.facts.offlineEntry)
        moved = self.work / "移走的包.zip"
        shutil.move(package.path, moved)
        moved_facts = inspect_package(moved)
        self.assertTrue(moved_facts.offlineEntry, "移走后仍能读到包内离线入口")
        with zipfile.ZipFile(moved) as archive:
            self.assertTrue(all(not name.startswith("/") for name in archive.namelist()))

        # 8) 副本恢复：原工程与成果保持
        from doc_tool.application.collection import build_manifest, register_manifest
        from doc_tool.application.delivery.handover import recover_to_new_copy

        manifest = build_manifest(self.members["Gamma"], version="v1", label="集合")
        manifest_path, error = register_manifest(self.members["Gamma"], manifest)
        self.assertEqual(error, "")
        before = {
            path.relative_to(self.members["Gamma"]).as_posix(): path.read_bytes()
            for path in self.members["Gamma"].rglob("*") if path.is_file()
        }
        recovery = recover_to_new_copy(
            self.members["Gamma"], manifest_path, self.work / "副本",
        )
        self.assertTrue(recovery.ok, recovery.message)
        after = {
            path.relative_to(self.members["Gamma"]).as_posix(): path.read_bytes()
            for path in self.members["Gamma"].rglob("*") if path.is_file()
        }
        self.assertEqual(before, after, "恢复不得改动原工程")
        self.assertTrue([p for p in Path(recovery.destination).rglob("*") if p.is_file()])

    def test_member_missing_keeps_others_and_marks_partial(self):
        from doc_tool.application.delivery.preparation import prepare_delivery

        prep = prepare_delivery(self._plan(entries=[
            {"id": "a", "member": "Alpha", "formats": ["docx"]},
            {"id": "b", "member": "Beta", "formats": ["docx"]},
            {"id": "ghost", "member": "不存在的成员", "formats": ["docx"]},
        ]))
        self.assertEqual(prep.completeness, "partial")
        self.assertEqual([row.member for row in prep.executableRows], ["Alpha", "Beta"])
        self.assertFalse(prep.isCompleteSet)
        text = "\n".join(prep.summary_lines())
        self.assertIn("不得冒充完整基线", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)