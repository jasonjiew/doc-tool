# -*- coding: utf-8 -*-
"""V4.2 42-E 5.1：对照冷/热/无缓存、同大小同时间修改、规则/模块变化与缓存坏。"""

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
        (getattr(i, "rel_path", ""), getattr(i, "line_no", 0),
         getattr(i, "rule_id", "") or getattr(i, "rule", "") or getattr(i, "source", ""))
        for i in issues
    )


class ColdHotNoCacheTests(unittest.TestCase):
    """冷/热/无缓存三条路径的问题集合必须逐项一致。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v42-e-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.addCleanup(lint_module.reset_lint_result_cache)
        self.addCleanup(incremental.reset_digest_cache)
        self.content = self.work / "content" / "general"
        self.content.mkdir(parents=True)
        (self.work / ".state").mkdir(exist_ok=True)
        (self.content / "1 a.md").write_text("# A\n\nTODO: 待办\n", encoding="utf-8")
        (self.content / "2 b.md").write_text("# B\n\nTODO: 待办\n", encoding="utf-8")
        (self.work / "project.yml").write_text("schemaVersion: 2\n", encoding="utf-8")
        self.config = QualityRulesConfig(self.work / ".state", "general")

    def _result(self, *, cache=None, use_result_cache=True):
        service = ContentIndexService(self.content, cache=cache)
        index = service.build()
        issues = ContentLinter(
            index, self.config, use_result_cache=use_result_cache
        ).check_all([])
        return _issues(issues), index, service

    def test_cold_hot_nocache_agree(self):
        cold, cold_index, _ = self._result()
        cache = incremental.ChapterCache.for_content_root(self.content)
        self._result(cache=cache)  # 预热
        hot, hot_index, hot_service = self._result(cache=cache)
        nocache, _, _ = self._result(use_result_cache=False)
        self.assertEqual(cold, hot, "冷/热问题集合必须一致")
        self.assertEqual(cold, nocache, "无缓存结果必须与冷路径一致")
        self.assertEqual(
            sorted(cold_index.lines), sorted(hot_index.lines),
        )
        self.assertGreaterEqual(int(hot_service.stats().get("reuseCount", 0)), 1,
                                "热路径必须真实复用了派生缓存")

    def test_same_size_same_mtime_change_detected(self):
        self._result()
        target = self.content / "2 b.md"
        stat = target.stat()
        # 与原文**等长**改写（同为 2 个汉字），保证大小一致后再复原 mtime
        target.write_text("# B\n\nTODO: 新增\n", encoding="utf-8")
        self.assertEqual(target.stat().st_size, 21, "测试前提：等长")
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(target.stat().st_size, stat.st_size, "测试前提：大小相同")
        self.assertEqual(target.stat().st_mtime_ns, stat.st_mtime_ns, "测试前提：mtime 相同")
        issues, _index, _service = self._result()
        self.assertIn("TODO: 新增", _index.lines["2 b.md"])
        self.assertTrue(
            any(item[0] == "2 b.md" for item in issues),
            "同大小/同时间修改必须被发现：{0}".format(issues),
        )

    def test_rules_and_module_change_invalidate_fingerprint(self):
        first = incremental.config_fingerprint(self.work)
        (self.work / "modules.yml").write_text("modules: []\n", encoding="utf-8")
        second = incremental.config_fingerprint(self.work)
        self.assertNotEqual(first, second, "模块声明变化必须改变配置指纹")
        (self.work / "quality").mkdir(exist_ok=True)
        (self.work / "quality" / "rules.json").write_text("{}", encoding="utf-8")
        third = incremental.config_fingerprint(self.work)
        self.assertNotEqual(second, third, "规则文件变化必须改变配置指纹")

    def test_corrupt_cache_rebuild_matches_full_scan(self):
        cache = incremental.ChapterCache.for_content_root(self.content)
        full, _index, _service = self._result(cache=cache)
        cache_file = cache.path
        self.assertTrue(cache_file.exists(), cache_file)
        cache_file.write_text("{ not json", encoding="utf-8")
        rebuilt, _a, _b = self._result(cache=incremental.ChapterCache.for_content_root(self.content))
        self.assertEqual(full, rebuilt, "坏缓存重建结果必须与完整扫描一致")

    def test_cancel_and_project_switch_do_not_leak_results(self):
        """取消/切项目后不得把旧结果串入新工作集。"""
        other = self.work / "content2" / "general"
        other.mkdir(parents=True)
        (other / "9 other.md").write_text("# Other\n\n正文。\n", encoding="utf-8")
        first = ContentIndexService(self.content).build()
        second = ContentIndexService(other).build()
        self.assertNotEqual(sorted(first.lines), sorted(second.lines),
                            "不同项目的工作集必须彼此独立")
        self.assertNotIn("9 other.md", first.lines)
        self.assertNotIn("1 a.md", second.lines)


if __name__ == "__main__":
    unittest.main(verbosity=2)