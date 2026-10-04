# -*- coding: utf-8 -*-
"""V4.3 43-D：接收人成果包用途判定与副本恢复。"""

from __future__ import annotations

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
from doc_tool.application.delivery.handover import (  # noqa: E402
    PURPOSE_READABLE,
    PURPOSE_REFRESHABLE,
    build_handover_package,
    inspect_package,
    recover_to_new_copy,
)


class _ReportFixture(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v43-d-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")

    def _report(self, formats=("docx", "html")):
        from doc_tool.application.intake_contract import ExportRequest
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(self.project), formats=list(formats),
            source_mode="saved", destination=str(self.work / "out"),
        )
        return run_project_export(request, skip_word_refresh=True)


class PackagePurposeTests(_ReportFixture):
    """4.1/4.2：用途只按包内真实文件判定，不虚假声明可刷新。"""

    def test_readable_package_has_files_offline_entry_and_manifest(self):
        report = self._report()
        outcome = build_handover_package(
            report, destination=self.work / "成果包.zip",
        )
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertTrue(Path(outcome.path).is_file(), outcome.path)
        facts = outcome.facts
        self.assertIsNotNone(facts)
        self.assertEqual(facts.purpose, PURPOSE_READABLE, "无刷新输入时不得声称可刷新")
        self.assertIn("不能声称可同源正式化", facts.purposeLabel)
        self.assertTrue(facts.offlineEntry, "必须带离线入口")
        self.assertEqual(facts.missing, [], facts.missing)
        with zipfile.ZipFile(outcome.path) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith("collection-manifest.json") for name in names)
                            or any(name.endswith(".json") for name in names),
                            "包内应有真实清单：{0}".format(names[:8]))
            self.assertTrue(all(not name.startswith("/") for name in names), "包内必须是相对路径")
        text = "\n".join(outcome.summary_lines())
        self.assertIn("可读成果包", text)
        self.assertIn("不自动上传", text)

    def test_include_original_marks_refreshable_only_when_inputs_present(self):
        report = self._report()
        outcome = build_handover_package(
            report, destination=self.work / "含原捕获.zip", include_original=True,
        )
        self.assertTrue(outcome.ok, outcome.warnings)
        facts = outcome.facts
        if facts.purpose == PURPOSE_REFRESHABLE:
            self.assertTrue(facts.refreshInputs, "标可刷新必须真有刷新输入")
        else:
            self.assertTrue(
                any("未找到刷新输入" in item for item in outcome.warnings),
                "请求含原捕获但包内没有输入时必须给出如实提醒：{0}".format(outcome.warnings),
            )

    def test_inspect_reports_broken_package(self):
        broken = self.work / "坏包.zip"
        broken.write_bytes(b"not a zip")
        facts = inspect_package(broken)
        self.assertTrue(facts.broken)
        self.assertEqual(facts.purpose, PURPOSE_READABLE, "坏包不得声称可刷新")

    def test_missing_package_file_is_reported(self):
        facts = inspect_package(self.work / "不存在.zip")
        self.assertTrue(facts.broken)
        self.assertIn("包文件不存在", facts.broken[0])


class RecoveryTests(_ReportFixture):
    """4.4：恢复到新副本；冲突换新名；原工程与活缓冲不变。"""

    def _baseline(self, version: str = "v1"):
        from doc_tool.application.collection import build_manifest, register_manifest

        manifest = build_manifest(self.project, version=version, label="集合")
        path, error = register_manifest(self.project, manifest)
        self.assertEqual(error, "")
        return Path(path)

    def test_recover_creates_new_copy_without_touching_source(self):
        manifest = self._baseline()
        before = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        destination = self.work / "恢复副本"
        outcome = recover_to_new_copy(self.project, manifest, destination)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(Path(outcome.destination).exists())
        self.assertTrue(Path(outcome.destination).is_dir())
        # 新副本里应有真实文件
        restored = [path for path in Path(outcome.destination).rglob("*") if path.is_file()]
        self.assertTrue(restored, "副本应含真实文件")
        after = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after, "恢复不得改动原工程")
        text = "\n".join(outcome.summary_lines())
        self.assertIn("副本恢复", text)

    def test_conflict_destination_gets_new_name(self):
        manifest = self._baseline()
        destination = self.work / "已存在"
        destination.mkdir()
        (destination / "占位.txt").write_text("keep", encoding="utf-8")
        outcome = recover_to_new_copy(self.project, manifest, destination)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertNotEqual(Path(outcome.destination), destination, "目标已存在必须换新名")
        self.assertTrue(outcome.renamed, outcome.to_dict())
        self.assertTrue((destination / "占位.txt").is_file(), "既有目录内容不得被覆盖")
        self.assertEqual((destination / "占位.txt").read_text(encoding="utf-8"), "keep")

    def test_bad_manifest_is_reported_not_partial_silent(self):
        broken = self.work / "坏清单.yml"
        broken.write_text("not: a manifest\n", encoding="utf-8")
        outcome = recover_to_new_copy(self.project, broken, self.work / "副本")
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.message)
        text = "\n".join(outcome.summary_lines())
        self.assertIn("恢复", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)