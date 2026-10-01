# -*- coding: utf-8 -*-
"""V2.8 28-B：章节顺序与变量解析（2.1、2.3、2.4、2.5）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.chapter_order import (  # noqa: E402
    UNDEFINED_TEMPLATE,
    is_resource_path,
    resolve_chapter_order,
    resolve_variables,
)

NL = chr(10)


class ChapterOrderTests(unittest.TestCase):
    def test_v1_without_declaration_keeps_scan_order(self):
        discovered = ["2 设计.md", "1 概述.md"]
        order = resolve_chapter_order(discovered)
        self.assertEqual(order.ordered, discovered)
        self.assertFalse(order.changed)

    def test_declared_order_wins_and_unlisted_appended(self):
        discovered = ["1 概述.md", "2 设计.md", "3 验证.md"]
        order = resolve_chapter_order(discovered, ["2 设计.md", "1 概述.md"])
        self.assertEqual(order.ordered, ["2 设计.md", "1 概述.md", "3 验证.md"])
        self.assertEqual(order.unlisted, ["3 验证.md"])
        self.assertTrue(order.warnings)

    def test_missing_declaration_reported_not_fatal(self):
        order = resolve_chapter_order(["1 概述.md"], ["9 不存在.md", "1 概述.md"])
        self.assertEqual(order.ordered, ["1 概述.md"])
        self.assertEqual(order.missing, ["9 不存在.md"])
        self.assertTrue(any("未找到" in item for item in order.warnings))

    def test_duplicate_declaration_deduplicated(self):
        order = resolve_chapter_order(
            ["1 概述.md"], ["1 概述.md", "1 概述"]
        )
        self.assertEqual(order.ordered, ["1 概述.md"])
        self.assertTrue(any("去重" in item for item in order.warnings))

    def test_extension_and_subdir_tolerant_matching(self):
        order = resolve_chapter_order(
            ["1 概述/1.1 目的.md"], ["1.1 目的.md"]
        )
        self.assertEqual(order.ordered, ["1 概述/1.1 目的.md"])
        self.assertFalse(order.missing)


class VariableResolutionTests(unittest.TestCase):
    def test_defined_variable_substituted(self):
        result = resolve_variables("产品：{{productName}}", {"productName": "示例"})
        self.assertEqual(result.text, "产品：示例")
        self.assertEqual(result.undefined, [])

    def test_undefined_uses_readable_placeholder_and_warns(self):
        result = resolve_variables("版本：{{docVersion}}")
        self.assertEqual(result.text, "版本：" + UNDEFINED_TEMPLATE.format("docVersion"))
        self.assertIn("docVersion", result.undefined)
        self.assertTrue(result.warnings)

    def test_declared_default_used_before_placeholder(self):
        result = resolve_variables("{{team}}", {}, {"team": "平台组"})
        self.assertEqual(result.text, "平台组")
        self.assertNotIn("team", result.undefined)

    def test_code_fence_content_never_substituted(self):
        text = NL.join(
            [
                "## 1.1 示例",
                "",
                "{{productName}}",
                "",
                "```python",
                "print('{{productName}}')",
                "```",
                "",
                "~~~text",
                "{{productName}}",
                "~~~",
                "",
            ]
        )
        result = resolve_variables(text, {"productName": "X"})
        lines = result.text.splitlines()
        self.assertEqual(lines[2], "X")
        # 代码围栏（``` 与 ~~~）内容不参与替换
        self.assertEqual(lines[5], "print('{{productName}}')")
        self.assertEqual(lines[9], "{{productName}}")
        self.assertEqual(lines.count("{{productName}}"), 1)

    def test_value_not_recursively_expanded(self):
        result = resolve_variables("{{a}}", {"a": "{{b}}", "b": "B"})
        self.assertEqual(result.text, "{{b}}")

    def test_resource_paths_are_recognized(self):
        self.assertTrue(is_resource_path("assets/img/fig-1.png"))
        self.assertTrue(is_resource_path("fig-1.PNG"))
        self.assertFalse(is_resource_path("普通文本"))

    def test_multiline_and_repeated_occurrences_all_replaced(self):
        result = resolve_variables("{{a}}-{{a}}" + NL + "{{a}}", {"a": "1"})
        self.assertEqual(result.text, "1-1" + NL + "1")


if __name__ == "__main__":
    unittest.main()