# -*- coding: utf-8 -*-
"""V4.1 41-C：真实底模的隔离小样（独立目录、复用失效、不覆盖项目）。"""

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

from doc_tool.application.template_sample import (  # noqa: E402
    GENERIC_SAMPLE,
    render_sample_markdown,
    reuse_key,
    run_sample,
    template_summary,
)

TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"


class GenericSampleContentTests(unittest.TestCase):
    def test_generic_sample_covers_supported_objects(self):
        text = render_sample_markdown()
        self.assertIn("#", text, "标题层级")
        self.assertIn("- ", text, "无序列表")
        self.assertIn("1. ", text, "有序列表")
        self.assertIn("| --- |", text, "长表")
        self.assertIn("![", text, "图片")
        self.assertIn("```", text, "代码")
        # 长表必须多行（验证跨页/多行场景）
        rows = [line for line in text.splitlines() if line.startswith("| 行 ")]
        self.assertGreaterEqual(len(rows), 20)

    def test_business_text_only_when_explicitly_passed(self):
        self.assertNotIn("业务正文片段", render_sample_markdown())
        with_business = render_sample_markdown(business_text="# 业务章节\n\n业务正文片段")
        self.assertIn("业务正文片段", with_business)
        self.assertIn("示例章节", with_business, "通用内容仍保留")


class ReuseKeyTests(unittest.TestCase):
    def test_key_changes_on_template_mapping_layout_or_sample(self):
        base = reuse_key(template_hash="h1", mapping={"A": 1}, layout={"mode": "template"}, sample_text="s")
        self.assertEqual(base, reuse_key(template_hash="h1", mapping={"A": 1}, layout={"mode": "template"}, sample_text="s"))
        self.assertNotEqual(base, reuse_key(template_hash="h2", mapping={"A": 1}, layout={"mode": "template"}, sample_text="s"))
        self.assertNotEqual(base, reuse_key(template_hash="h1", mapping={"A": 2}, layout={"mode": "template"}, sample_text="s"))
        self.assertNotEqual(base, reuse_key(template_hash="h1", mapping={"A": 1}, layout={"mode": "body-adaptive"}, sample_text="s"))
        self.assertNotEqual(base, reuse_key(template_hash="h1", mapping={"A": 1}, layout={"mode": "template"}, sample_text="s2"))


class RunSampleTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-sample-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.base = self.work / "samples"
        self.template = self.work / "底模.docx"
        shutil.copy2(TEMPLATE, self.template)

    def test_sample_is_generated_in_isolated_directory(self):
        outcome = run_sample(self.template, self.base)
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertTrue(Path(outcome.docxPath).is_file(), "应真实写出小样 DOCX")
        self.assertTrue(Path(outcome.directory).is_dir())
        self.assertTrue(str(Path(outcome.directory)).startswith(str(self.base)), "小样必须在隔离目录内")
        self.assertNotEqual(Path(outcome.directory), self.work, "不得写到项目目录")
        self.assertEqual(len(outcome.templateSummary), 64, "必须记录真实底模摘要")
        manifest = json.loads((Path(outcome.directory) / "sample.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["sampleIsGeneric"], "默认小样必须是通用内容")
        self.assertFalse(manifest["businessTextIncluded"])
        self.assertEqual(manifest["templateSummary"], outcome.templateSummary)

    def test_no_word_still_readable_and_marked_pending(self):
        """无 Word 环境：小样仍可生成，Word 分页/目录标待刷新。"""
        outcome = run_sample(self.template, self.base, refresh_fields=False)
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertTrue(outcome.wordPending, "未请求刷新时必须标待刷新")
        self.assertFalse(outcome.reused)
        text = "\n".join(outcome.summary_lines())
        self.assertIn("待刷新", text)
        self.assertIn("内容预览", text)

    def test_reuse_only_when_key_matches(self):
        first = run_sample(self.template, self.base, mapping={"Heading1": 1})
        second = run_sample(
            self.template, self.base, mapping={"Heading1": 1},
            existing_key=first.reuseKey, existing_dir=first.directory,
        )
        self.assertTrue(second.reused, "同模板/映射/版式可复用")
        self.assertEqual(second.directory, first.directory)
        # 换版式 → 必须新建新轮
        third = run_sample(
            self.template, self.base, mapping={"Heading1": 1}, layout={"mode": "body-adaptive"},
            existing_key=first.reuseKey, existing_dir=first.directory,
        )
        self.assertFalse(third.reused, "版式变化必须使复用失效")
        self.assertNotEqual(third.directory, first.directory)

    def test_template_content_change_invalidates_reuse(self):
        first = run_sample(self.template, self.base)
        self.template.write_bytes(self.template.read_bytes() + b"changed")
        second = run_sample(
            self.template, self.base,
            existing_key=first.reuseKey, existing_dir=first.directory,
        )
        self.assertFalse(second.reused, "底模内容变化必须使旧小样失效")
        self.assertNotEqual(second.templateSummary, first.templateSummary)

    def test_old_sample_survives_new_round(self):
        first = run_sample(self.template, self.base)
        second = run_sample(self.template, self.base, layout={"mode": "body-adaptive"})
        self.assertTrue(Path(first.docxPath).is_file(), "旧小样必须保留")
        self.assertTrue(Path(second.docxPath).is_file())
        self.assertNotEqual(first.directory, second.directory)

    def test_missing_template_is_reported_not_created(self):
        outcome = run_sample(self.work / "不存在.docx", self.base)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.warnings)
        self.assertFalse(self.base.exists(), "失败时不得创建小样目录")

    def test_unsupported_layout_kept_but_not_claimed(self):
        outcome = run_sample(
            self.template, self.base,
            layout={"mode": "template", "cover": "企业封面", "header": "页眉"},
        )
        self.assertTrue(outcome.ok, outcome.warnings)
        self.assertEqual(outcome.appliedLayout, {"mode": "template"})
        self.assertEqual(sorted(outcome.unsupported), ["cover", "header"])
        text = "\n".join(outcome.summary_lines())
        self.assertIn("未支持声明", text)

    def test_business_snippet_only_when_selected(self):
        generic = run_sample(self.template, self.base)
        manifest = json.loads((Path(generic.directory) / "sample.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["businessTextIncluded"])
        with_business = run_sample(
            self.template, self.base, business_text="# 业务\n\n业务片段内容\n",
        )
        manifest = json.loads((Path(with_business.directory) / "sample.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["businessTextIncluded"])
        self.assertFalse(manifest["sampleIsGeneric"])


if __name__ == "__main__":
    unittest.main(verbosity=2)