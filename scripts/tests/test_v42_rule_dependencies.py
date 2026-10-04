# -*- coding: utf-8 -*-
"""42-B 2.3/2.4：规则依赖分类、完整核对回退与活缓冲/代次隔离。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content import incremental_index as incremental  # noqa: E402
from doc_tool.application.content import lint as lint_module  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.lint import ContentLinter  # noqa: E402
from doc_tool.application.content.quality_rules import QualityRulesConfig  # noqa: E402


class RuleDependencyTests(unittest.TestCase):
    """2.3：跨章/未知依赖必须退完整核对，不按“本章变化”复用。"""

    def test_known_local_rules_do_not_force_full_recheck(self):
        self.assertEqual(lint_module.rule_dependency("todo_residual"), "local")
        self.assertFalse(lint_module.requires_full_recheck(["todo_residual", "mermaid_syntax"]))

    def test_cross_chapter_rules_force_full_recheck(self):
        for rule_id in ("duplicate_title", "term_case", "numbering_uniqueness", "required_section"):
            self.assertEqual(lint_module.rule_dependency(rule_id), "cross-chapter", rule_id)
            self.assertTrue(lint_module.requires_full_recheck([rule_id]), rule_id)

    def test_unknown_rule_falls_back_to_full_recheck(self):
        self.assertEqual(lint_module.rule_dependency("brand_new_rule"), "unknown")
        self.assertTrue(
            lint_module.requires_full_recheck(["todo_residual", "brand_new_rule"]),
            "未知依赖规则必须退完整核对",
        )

    def test_default_rule_set_requires_full_recheck(self):
        """默认规则含重复标题/术语，因此默认口径就是整份核对（安全侧）。"""
        from doc_tool.application.content.quality_rules import default_rules

        config_rules = [rule.rule_id for rule in default_rules("general")]
        self.assertTrue(
            lint_module.requires_full_recheck(config_rules),
            "默认规则集合应要求完整核对：{0}".format(config_rules),
        )

    def test_cross_chapter_change_invalidates_duplicate_title_result(self):
        """跨章规则：即使只改一章，重复标题结果也必须按新正文重算。"""
        work = Path(tempfile.mkdtemp(prefix="v42-cross-"))
        self.addCleanup(shutil.rmtree, work, True)
        self.addCleanup(lint_module.reset_lint_result_cache)
        self.addCleanup(incremental.reset_digest_cache)
        content = work / "content" / "general"
        content.mkdir(parents=True)
        (work / ".state").mkdir(exist_ok=True)
        (content / "1 a.md").write_text("# 同名标题\n\n正文。\n", encoding="utf-8")
        (content / "2 b.md").write_text("# 其它标题\n\n正文。\n", encoding="utf-8")
        config = QualityRulesConfig(work / ".state", "general")

        def issues():
            index = ContentIndexService(content).build()
            return sorted(
                (getattr(i, "rel_path", ""), getattr(i, "line_no", 0),
                 getattr(i, "rule_id", "") or getattr(i, "rule", ""))
                for i in ContentLinter(index, config).check_all([])
            )

        before = issues()
        (content / "2 b.md").write_text("# 同名标题\n\n正文。\n", encoding="utf-8")
        after = issues()
        self.assertNotEqual(before, after, "跨章重复标题必须按新正文重算")
        self.assertTrue(
            any(item[2] == "duplicate_title" for item in after),
            "改后应出现重复标题问题：{0}".format(after),
        )
        # 与完整重算逐项一致
        index = ContentIndexService(content).build()
        uncached = sorted(
            (getattr(i, "rel_path", ""), getattr(i, "line_no", 0),
             getattr(i, "rule_id", "") or getattr(i, "rule", ""))
            for i in ContentLinter(index, config, use_result_cache=False).check_all([])
        )
        self.assertEqual(after, uncached)


class CacheLifecycleTests(unittest.TestCase):
    """2.4：坏缓存/容量不足回直接计算；活缓冲只存内存。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-life-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(lint_module.reset_lint_result_cache)
        self.addCleanup(incremental.reset_digest_cache)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.work / ".state").mkdir(exist_ok=True)
        (self.content / "1 a.md").write_text("# A\n\nTODO: x\n", encoding="utf-8")

    def test_reset_clears_caches(self):
        incremental.content_digest(self.content / "1 a.md")
        self.assertTrue(incremental._DIGEST_CACHE)
        incremental.reset_digest_cache()
        self.assertFalse(incremental._DIGEST_CACHE)

        config = QualityRulesConfig(self.work / ".state", "general")
        index = ContentIndexService(self.content).build()
        ContentLinter(index, config).check_all([])
        self.assertTrue(lint_module._LINT_RESULT_CACHE)
        lint_module.reset_lint_result_cache()
        self.assertFalse(lint_module._LINT_RESULT_CACHE)

    def test_capacity_overflow_falls_back_to_recompute(self):
        config = QualityRulesConfig(self.work / ".state", "general")
        original = lint_module._LINT_RESULT_CACHE_MAX
        lint_module._LINT_RESULT_CACHE_MAX = 1
        try:
            for round_no in range(3):
                (self.content / "1 a.md").write_text(
                    "# A\n\nTODO: x {0}\n".format(round_no), encoding="utf-8"
                )
                index = ContentIndexService(self.content).build()
                cached = sorted(
                    (i.rel_path, i.line_no, getattr(i, "rule_id", "") or i.rule)
                    for i in ContentLinter(index, config).check_all([])
                )
                uncached = sorted(
                    (i.rel_path, i.line_no, getattr(i, "rule_id", "") or i.rule)
                    for i in ContentLinter(index, config, use_result_cache=False).check_all([])
                )
                self.assertEqual(cached, uncached, "容量不足时必须回直接计算且结果一致")
            self.assertLessEqual(len(lint_module._LINT_RESULT_CACHE), 1)
        finally:
            lint_module._LINT_RESULT_CACHE_MAX = original

    def test_buffer_override_digest_is_memory_only(self):
        """活缓冲派生只影响内存摘要，不写盘、不污染磁盘内容。"""
        ContentIndexService(self.content).build()
        target = self.content / "1 a.md"
        disk_before = target.read_text(encoding="utf-8")
        service = ContentIndexService(
            self.content, override_texts={"1 a.md": "# A\n\nTODO: 缓冲里的内容\n"},
        )
        index = service.build()
        self.assertIn("TODO: 缓冲里的内容", "\n".join(index.lines["1 a.md"]))
        self.assertEqual(target.read_text(encoding="utf-8"), disk_before, "不得改写磁盘正文")
        self.assertTrue(service.stats().get("captureFiles"), "缓冲文本应登记为捕获内容")


if __name__ == "__main__":
    unittest.main(verbosity=2)