# -*- coding: utf-8 -*-
"""回归测试：基线核对（baseline-check）、声明文件比对与确认对象失效判定。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_tool.application.baseline_check import check_baselines, check_project_baseline
from doc_tool.application.content.baselines import BaselineStore
from doc_tool.application.review.review_store import ReviewStore
from doc_tool.domain.manifest import ProjectManifest


class DevFlowBaselineCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj = self.root / "doc_project"
        self.proj.mkdir()

        self.manifest_file = self.proj / "project.yml"
        self.manifest_file.write_text(
            "schemaVersion: 1\n"
            "projectId: proj-base-01\n"
            "documentNo: KF-2090-1-001\n"
            "documentName: 康尚健康云软件需求说明书\n"
            "documentVersion: '3.8'\n"
            "paths:\n"
            "  contentRoot: content/requirement\n",
            encoding="utf-8",
        )
        self.content_dir = self.proj / "content" / "requirement"
        self.content_dir.mkdir(parents=True)

        self.rev_file = self.content_dir / "_revision_record.md"
        self.rev_file.write_text(
            "# 修订记录\n\n"
            "| 版本 | 修订内容 | 日期 | 修订人 |\n"
            "|------|----------|------|--------|\n"
            "| V3.7 | 历史功能 | 2026-05-01 | 张三 |\n"
            "| V3.8 | 最新需求 | 2026-07-20 | 李四 |\n",
            encoding="utf-8",
        )

        self.ch1 = self.content_dir / "01_req.md"
        self.ch1.write_text("# 1. 需求\n\n正文。\n", encoding="utf-8")

        # 外部声明文件（模拟 README.md）
        self.readme = self.root / "README.md"
        self.readme.write_text(
            "# 文档清单\n\n"
            "| 文档编号 | 文档名称 | 当前版本 | 目录 |\n"
            "|---|---|---|---|\n"
            "| KF-2090-1-001 | 康尚健康云软件需求说明书 | 3.10 | `requirements/` |\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_conflict_detection_with_declared_file(self):
        # 项目本身 manifest 为 3.8，修订记录为 3.8；但 README 声明为 3.10
        res = check_baselines(self.proj, declare_files=[self.readme])
        self.assertTrue(res["conflict"])
        self.assertEqual(res["status"], "conflict")
        self.assertEqual(res["exitCode"], 1)

        p0 = res["projects"][0]
        self.assertEqual(p0["manifestVersion"], "3.8")
        self.assertEqual(p0["revisionRecordVersion"], "3.8")
        self.assertEqual(len(p0["declaredVersions"]), 1)
        self.assertEqual(p0["declaredVersions"][0]["declaredVersion"], "3.10")
        self.assertTrue(any("3.10" in iss and "冲突" in iss for iss in p0["issues"]))

    def test_conflict_between_manifest_and_revision_record(self):
        # 修订记录改为 V3.9，而 manifest 仍是 3.8
        self.rev_file.write_text(
            "| 版本 | 修订内容 | 日期 | 修订人 |\n"
            "|------|----------|------|--------|\n"
            "| V3.9 | 漂移记录 | 2026-08-01 | 王五 |\n",
            encoding="utf-8",
        )
        res = check_baselines(self.proj)
        self.assertTrue(res["conflict"])
        self.assertEqual(res["status"], "conflict")
        p0 = res["projects"][0]
        self.assertTrue(any("3.8" in iss and "3.9" in iss for iss in p0["issues"]))

    def test_baseline_check_signoff_staleness_and_unverified(self):
        # 写入未绑定的历史签审和已绑定的当前签审
        state_dir = self.proj / ".state"
        r_store = ReviewStore(state_dir)
        r_store.append_signoff("张工", "架构师", "旧版确认")  # 无 content_hash

        res1 = check_project_baseline(self.proj)
        self.assertEqual(res1["signoffs"][0]["status"], "unverified")
        self.assertTrue(any("未满足" in iss and "缺少内容指纹绑定" in iss for iss in res1["issues"]))
        self.assertEqual(res1["status"], "incomplete")

        # 绑定正确内容哈希
        cur_hash = res1["currentContentHash"]
        r_store.append_signoff("李工", "测试经理", "基线确认", content_hash=cur_hash)

        # 篡改正文内容，原确认应变为 stale
        self.ch1.write_text("# 1. 需求\n\n正文已改动！\n", encoding="utf-8")
        res2 = check_project_baseline(self.proj)
        stale_signoffs = [s for s in res2["signoffs"] if s["status"] == "stale"]
        self.assertEqual(len(stale_signoffs), 1)
        self.assertEqual(stale_signoffs[0]["author"], "李工")
        self.assertTrue(any("已失效" in iss and "内容已发生变更" in iss for iss in res2["issues"]))

    def test_baseline_check_tool_metadata(self):
        res = check_baselines(self.proj)
        self.assertIn("tool", res)
        self.assertEqual(res["tool"]["appVersion"], "3.0.0")
        self.assertIn("commit", res["tool"])

    def test_frozen_baseline_verification_and_corruption(self):
        # 匹配状态下，冻结基线
        manifest = ProjectManifest.load(self.proj)
        state_dir = self.proj / ".state"
        b_store = BaselineStore(state_dir)
        b_store.freeze(manifest, self.content_dir)

        # 核对冻结存在且完好
        res = check_project_baseline(self.proj)
        self.assertTrue(res["frozenBaseline"]["exists"])
        self.assertEqual(len(res["frozenBaseline"]["corrupted"]), 0)

        # 模拟冻结快照被意外篡改
        snap_file = state_dir / "baselines" / "3.8" / "content" / "01_req.md"
        snap_file.write_text("篡改快照！", encoding="utf-8")

        res_corrupt = check_project_baseline(self.proj)
        self.assertTrue(res_corrupt["frozenBaseline"]["exists"])
        self.assertGreater(len(res_corrupt["frozenBaseline"]["corrupted"]), 0)
        self.assertIn("不匹配", res_corrupt["frozenBaseline"]["corrupted"][0])


if __name__ == "__main__":
    unittest.main()
