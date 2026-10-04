# -*- coding: utf-8 -*-
"""42-B：正确的增量计算（依赖摘要、缓存一致性、同大小同时间修改）。"""

from __future__ import annotations

import os
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


def _issues(issues):
    return sorted(
        (getattr(i, "rel_path", ""), getattr(i, "line_no", 0), getattr(i, "rule_id", "") or getattr(i, "rule", ""))
        for i in issues
    )


class DigestCacheTests(unittest.TestCase):
    """内容摘要缓存必须仍然发现“同大小、同 mtime”的真实改写。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-digest-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(incremental.reset_digest_cache)

    def test_same_size_same_mtime_change_is_detected(self):
        target = self.work / "a.md"
        target.write_text("hello", encoding="utf-8")
        before = incremental.content_digest(target)
        again = incremental.content_digest(target)
        self.assertEqual(before, again, "未变内容应复用同一真实摘要")
        stat = target.stat()
        target.write_text("world", encoding="utf-8")
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(target.stat().st_size, stat.st_size, "测试前提：大小相同")
        self.assertEqual(target.stat().st_mtime_ns, stat.st_mtime_ns, "测试前提：mtime 相同")
        after = incremental.content_digest(target)
        self.assertNotEqual(before, after, "同大小/同时间改写必须被发现")

    def test_uncached_digest_matches_cached_digest(self):
        target = self.work / "b.md"
        target.write_text("内容甲" * 20, encoding="utf-8")
        cached = incremental.content_digest(target)
        fresh = incremental.content_digest(target, use_stat_cache=False)
        self.assertEqual(cached, fresh, "缓存摘要必须等于真实读取摘要")

    def test_stat_fingerprint_matches_read(self):
        target = self.work / "c.md"
        target.write_text("x" * 10, encoding="utf-8")
        fingerprint = incremental.file_stat_fingerprint(target)
        self.assertIsNotNone(fingerprint)
        self.assertEqual(fingerprint[0], str(target))
        self.assertEqual(fingerprint[1], 10)


class IndexDependencyTests(unittest.TestCase):
    """索引构建在缓存复用下仍与完整扫描逐项一致。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-dep-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(incremental.reset_digest_cache)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.content / "1 概述.md").write_text("# 概述\n\n正文。\n", encoding="utf-8")
        (self.content / "2 设计.md").write_text("# 设计\n\nTODO: 待办\n", encoding="utf-8")

    def test_rebuild_with_cache_matches_full_scan(self):
        first = ContentIndexService(self.content).build()
        second = ContentIndexService(self.content).build()
        self.assertEqual(sorted(first.lines), sorted(second.lines))
        for rel in first.lines:
            self.assertEqual(first.lines[rel], second.lines[rel], rel)

    def test_changed_chapter_is_reparsed_others_reused(self):
        ContentIndexService(self.content).build()
        target = self.content / "1 概述.md"
        target.write_text("# 概述\n\n改动后的正文。\n", encoding="utf-8")
        service = ContentIndexService(self.content)
        index = service.build()
        self.assertIn("改动后的正文。", "\n".join(index.lines["1 概述.md"]))
        stats = service.stats()
        self.assertGreaterEqual(int(stats.get("parseCount", 0)), 1, "变更章必须重新解析")


class LintResultCacheTests(unittest.TestCase):
    """检查结果复用必须与完整重算逐项一致，且规则变化即失效。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-lintcache-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(lint_module.reset_lint_result_cache)
        self.addCleanup(incremental.reset_digest_cache)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.work / ".state").mkdir(exist_ok=True)
        (self.content / "1 概述.md").write_text("# 概述\n\nTODO: 待办\n", encoding="utf-8")
        (self.content / "2 设计.md").write_text("# 设计\n\n正文。\n", encoding="utf-8")
        self.config = QualityRulesConfig(self.work / ".state", "general")

    def _index(self):
        return ContentIndexService(self.content).build()

    def test_cached_result_equals_uncached_full_check(self):
        index = self._index()
        cached = ContentLinter(index, self.config).check_all([])
        again = ContentLinter(index, self.config).check_all([])
        uncached = ContentLinter(index, self.config, use_result_cache=False).check_all([])
        self.assertEqual(_issues(cached), _issues(uncached))
        self.assertEqual(_issues(again), _issues(uncached))

    def test_content_change_invalidates_result(self):
        index = self._index()
        before = _issues(ContentLinter(index, self.config).check_all([]))
        self.assertEqual(
            [item[0] for item in before], ["1 概述.md"],
            "初始只有第一章有 TODO：{0}".format(before),
        )
        # 第二章新增一处 TODO：问题集合必须真的变化（键包含正文状态）。
        (self.content / "2 设计.md").write_text(
            "# 设计\n\nTODO: 新增待办\n", encoding="utf-8"
        )
        after_index = self._index()
        after = _issues(ContentLinter(after_index, self.config).check_all([]))
        self.assertNotEqual(before, after, "正文变化后不得复用旧结果")
        self.assertEqual(
            sorted(item[0] for item in after), ["1 概述.md", "2 设计.md"]
        )
        self.assertEqual(
            after, _issues(ContentLinter(after_index, self.config, use_result_cache=False).check_all([]))
        )

    def test_rule_parameter_change_invalidates_result(self):
        index = self._index()
        base = _issues(ContentLinter(index, self.config).check_all([]))
        self.assertTrue(base, "初始应有 TODO 问题")
        # 经真实配置写入关闭 todo 规则，再用新配置建检查器：不得复用旧键结果。
        self.config.load()
        rules = {rule.rule_id: rule for rule in self.config.rule_map().values()}
        self.assertIn("todo_residual", rules, "默认规则应包含 todo_residual")
        rules["todo_residual"].enabled = False
        self.config.save(rules=list(rules.values()))
        reloaded = QualityRulesConfig(self.work / ".state", "general")
        changed = _issues(ContentLinter(index, reloaded).check_all([]))
        self.assertFalse(
            [item for item in changed if item[2] == "todo_residual"],
            "关闭规则后不得再报该规则问题：{0}".format(changed),
        )
        self.assertEqual(
            changed,
            _issues(ContentLinter(index, reloaded, use_result_cache=False).check_all([])),
        )
        # 缓存仍应可用：重复调用结果一致
        self.assertEqual(
            changed, _issues(ContentLinter(index, reloaded).check_all([]))
        )

    def test_dependency_digest_covers_paths_lines_and_digests(self):
        index = self._index()
        digest = lint_module.index_dependency_digest(index)
        self.assertIn("1 概述.md", str(digest))
        self.assertIn(lint_module.LINT_PARSER_VERSION, digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
