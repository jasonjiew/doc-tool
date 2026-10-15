# -*- coding: utf-8 -*-
"""回归测试：研发流程免安装 CLI 契约、能力自省、条目查询与复核状态。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_tool.application.capabilities import get_capabilities_report
from doc_tool.application.content.impact import ReviewRecordStore
from doc_tool.application.item_query import generate_stable_trace_plan, list_items, review_status, show_item
from doc_tool.application.review.review_store import ReviewStore
from doc_tool.cli import main


class DevFlowCliContractsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # 构造合成文档项目，提供完整合规清单字段
        self.manifest = self.root / "project.yml"
        self.manifest.write_text(
            "schemaVersion: 1\n"
            "projectId: proj-test-01\n"
            "documentNo: TEST-001\n"
            "documentName: 自动化测试项目\n"
            "documentVersion: '1.0'\n"
            "paths:\n"
            "  contentRoot: content\n",
            encoding="utf-8",
        )
        self.content_dir = self.root / "content"
        self.content_dir.mkdir(parents=True)

        self.ch1 = self.content_dir / "01_intro.md"
        self.ch1.write_text(
            "# 1. 引言\n\n系统概述段落。\n\n"
            "<!-- DOC-ITEM: projectId=proj-test-01 kind=requirement id=00000000-0000-0000-0000-000000000001 alias=REQ-01 -->\n"
            "这是需求 1 的原子正文。\n\n"
            "<!-- DOC-ITEM: projectId=proj-test-01 kind=requirement id=00000000-0000-0000-0000-000000000002 alias=REQ-02 -->\n"
            "这是需求 2 的原子正文。\n",
            encoding="utf-8",
        )

        self.ch2 = self.content_dir / "02_detail.md"
        self.ch2.write_text(
            "# 2. 详细说明\n\n"
            "```markdown\n<!-- DOC-ITEM: projectId=proj-test-01 kind=requirement id=99999999-9999-9999-9999-999999999999 -->\n```\n\n"
            "<!-- DOC-ITEM: projectId=proj-test-01 kind=design id=00000000-0000-0000-0000-000000000003 alias=DES-01 -->\n"
            "这是设计 1 的正文内容，包含图片：\n![架构图](assets/arch.png)\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_capabilities_schema_and_purity(self):
        report = get_capabilities_report()
        self.assertEqual(report["schemaVersion"], 1)
        self.assertEqual(report["command"], "capabilities")
        self.assertIn("tool", report)
        self.assertIn("appVersion", report["tool"])
        self.assertIn("commit", report["tool"])
        self.assertIn("frozen", report["tool"])
        self.assertFalse(report["environment"]["pythonRequired"])

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with patch("sys.stdout", out_buf), patch("sys.stderr", err_buf):
            code = main(["capabilities", "--format", "json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out_buf.getvalue())
        self.assertEqual(parsed["command"], "capabilities")

    def test_item_list_pagination_and_filter(self):
        res = list_items(self.root)
        self.assertEqual(res["total"], 3)
        self.assertEqual(res["totalPages"], 1)
        self.assertEqual(len(res["items"]), 3)

        res_ch1 = list_items(self.root, chapter="01_intro.md")
        self.assertEqual(res_ch1["total"], 2)

        res_q = list_items(self.root, query="DES-01")
        self.assertEqual(res_q["total"], 1)
        self.assertEqual(res_q["items"][0]["itemId"], "00000000-0000-0000-0000-000000000003")

        res_page = list_items(self.root, page=2, page_size=2)
        self.assertEqual(res_page["page"], 2)
        self.assertEqual(len(res_page["items"]), 1)

    def test_item_show_lookup_by_alias(self):
        # 支持以 alias 查询条目
        res_alias = show_item(self.root, "REQ-01")
        self.assertTrue(res_alias["found"])
        self.assertEqual(res_alias["item"]["alias"], "REQ-01")

        # 支持以 projectId/alias 查询条目
        res_scoped = show_item(self.root, "proj-test-01/REQ-02")
        self.assertTrue(res_scoped["found"])
        self.assertEqual(res_scoped["item"]["alias"], "REQ-02")

    def test_trace_plan_ignores_code_fences(self):
        fence_file = self.content_dir / "04_code.md"
        fence_file.write_text(
            "# 4. 代码演示\n\n"
            "```python\n"
            "# 1.1 这里的代码注释不应该被提取为旧编号条目\n"
            "def foo(): pass\n"
            "```\n\n"
            "1.1 真实的旧编号条目\n",
            encoding="utf-8",
        )
        plan = generate_stable_trace_plan(self.root)
        legacy_lines = [c["lineNo"] for c in plan["confident"]]
        # 真实条目行号必须在代码块之后
        self.assertTrue(any(l > 6 for l in legacy_lines))
        # 代码块内的第 4 行不应出现在计划中
        self.assertNotIn(4, legacy_lines)

    def test_all_reports_include_tool_metadata(self):
        r_list = list_items(self.root)
        self.assertIn("tool", r_list)
        self.assertEqual(r_list["tool"]["name"], "doc-tool")

        r_show = show_item(self.root, "REQ-01")
        self.assertIn("tool", r_show)

        r_rev = review_status(self.root)
        self.assertIn("tool", r_rev)

        r_plan = generate_stable_trace_plan(self.root)
        self.assertIn("tool", r_plan)

    def test_item_show(self):
        res = show_item(self.root, "00000000-0000-0000-0000-000000000003")
        self.assertTrue(res["found"])
        self.assertEqual(res["item"]["alias"], "DES-01")
        self.assertIn("assets/arch.png", res["item"]["resources"])

        res_none = show_item(self.root, "non-existent-uuid")
        self.assertFalse(res_none["found"])

    def test_stable_trace_plan(self):
        legacy_file = self.content_dir / "03_legacy.md"
        legacy_file.write_text(
            "# 3. 旧编号模块\n\n1.1 首个功能需求\n\n1.2 第二个功能需求\n",
            encoding="utf-8",
        )

        plan1 = generate_stable_trace_plan(self.root)
        plan2 = generate_stable_trace_plan(self.root)

        self.assertEqual(plan1["planId"], plan2["planId"])
        self.assertEqual(len(plan1["confident"]), 2)
        self.assertEqual(plan1["confident"][0]["proposedId"], plan2["confident"][0]["proposedId"])
        self.assertEqual(plan1["confident"][1]["proposedId"], plan2["confident"][1]["proposedId"])

        self.assertNotIn("DOC-ITEM", legacy_file.read_text(encoding="utf-8"))

    def test_review_status_unverified_and_stale(self):
        state_dir = self.root / ".state"
        r_store = ReviewStore(state_dir)

        r_store.append_signoff("张工", "架构师", "旧版架构签审")
        st1 = review_status(self.root)
        self.assertEqual(len(st1["signoffs"]), 1)
        self.assertEqual(st1["signoffs"][0]["status"], "unverified")
        self.assertIn("缺少内容指纹绑定", st1["signoffs"][0]["staleReason"])

        cur_hash = st1["currentContentHash"]
        r_store.append_signoff("李工", "测试经理", "新签审", content_hash=cur_hash)
        st2 = review_status(self.root)
        self.assertEqual(st2["signoffs"][1]["status"], "valid")

        self.ch1.write_text("正文被篡改！", encoding="utf-8")
        st3 = review_status(self.root)
        self.assertEqual(st3["signoffs"][1]["status"], "stale")
        self.assertIn("内容已发生变更", st3["signoffs"][1]["staleReason"])

    def test_table_business_ids_fallback_in_item_list_show_and_trace_plan(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p_root = Path(tmp_dir)
            (p_root / "project.yml").write_text(
                "schemaVersion: 1\nprojectId: proj-table-01\ndocumentNo: REQ-001\n"
                "documentName: 需求规格\ndocumentVersion: '1.0'\npaths:\n  contentRoot: content\n",
                encoding="utf-8",
            )
            c_dir = p_root / "content"
            c_dir.mkdir(parents=True)
            (c_dir / "3.1.1 模块A.md").write_text(
                "#### 需求编号与说明\n\n"
                "| 需求编号 | 模块名称 | 需求描述 |\n"
                "| --- | --- | --- |\n"
                "| REQ-00101 | 列表 | 支持列表查询 |\n"
                "| Function-100101 | 导出 | 支持报表导出 |\n"
                "| Design-300101 | 接口 | 接口设计说明 |\n",
                encoding="utf-8",
            )
            listed = list_items(p_root)
            self.assertEqual(listed["total"], 3)
            aliases = {it["alias"] for it in listed["items"]}
            self.assertEqual(aliases, {"REQ-00101", "Function-100101", "Design-300101"})

            shown = show_item(p_root, "REQ-00101")
            self.assertTrue(shown["found"])
            self.assertEqual(shown["item"]["alias"], "REQ-00101")
            self.assertEqual(shown["item"]["kind"], "requirement")

            plan = generate_stable_trace_plan(p_root)
            self.assertEqual(plan["confidentCount"], 3)
            legacy_nos = {c["legacyNo"] for c in plan["confident"]}
            self.assertEqual(legacy_nos, {"REQ-00101", "Function-100101", "Design-300101"})


if __name__ == "__main__":
    unittest.main()
