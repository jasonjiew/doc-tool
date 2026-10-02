# -*- coding: utf-8 -*-
"""验收操作清单（runbook）与 tasks.md 的同步校验。

未勾选的任务必须在 `docs/product-v3-acceptance-runbook.md` 里出现，环境类待验收项
（实机 Word / 冻结写入闭环 / 物理缩放 / mmdc）也必须有对应小节，避免“台账说待验收、
清单里找不到怎么验”。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUNBOOK = REPO_ROOT / "docs" / "product-v3-acceptance-runbook.md"
CHANGES = (
    "product-core-import-export",
    "product-v30-content-reuse",
    "product-v31-team-workflow",
    "product-v32-batch-delivery",
    "product-v33-authoring-assistance",
)
#: 环境类待验收项在清单里必须出现的关键词（问题类型 → 关键词）
ENVIRONMENT_KEYWORDS = {
    "实机 Word 正式化/换机": "V32_REAL_WORD",
    "冻结包写入类闭环": "env-check",
    "物理 125%/150% 缩放": "125%",
    "Mermaid 预览（mmdc）": "mmdc",
}


class AcceptanceRunbookTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RUNBOOK.is_file(), "缺少验收操作清单：" + str(RUNBOOK))
        self.text = RUNBOOK.read_text(encoding="utf-8")

    def _unticked(self):
        rows = {}
        for change in CHANGES:
            path = REPO_ROOT / "openspec" / "changes" / change / "tasks.md"
            text = path.read_text(encoding="utf-8")
            rows[change] = re.findall(r"- \[ \] (\d+\.\d+)", text)
        return rows

    def test_every_unticked_task_is_referenced(self):
        unticked = self._unticked()
        missing = []
        for change, ids in unticked.items():
            for task_id in ids:
                # 清单里以“任务编号 + change 版本”形式出现，例如 CORE 8.5 / V3.1 6.3 / V3.2 7.5
                label = {
                    "product-core-import-export": "CORE",
                    "product-v30-content-reuse": "V3.0",
                    "product-v31-team-workflow": "V3.1",
                    "product-v32-batch-delivery": "V3.2",
                    "product-v33-authoring-assistance": "V3.3",
                }[change]
                if "{0} {1}".format(label, task_id) not in self.text:
                    missing.append("{0} {1}".format(label, task_id))
        self.assertEqual(missing, [], "清单未覆盖的未勾选任务：{0}".format(missing))

    def test_environment_items_documented(self):
        for label, keyword in ENVIRONMENT_KEYWORDS.items():
            self.assertIn(keyword, self.text, "清单缺少环境项：{0}".format(label))

    def test_each_item_has_command_and_criteria(self):
        # 每个小节都要给命令与判据，避免只有描述没有可执行步骤
        self.assertGreaterEqual(self.text.count("**命令**"), 5)
        self.assertGreaterEqual(self.text.count("**判据**"), 5)
        self.assertIn("验收记录表", self.text)

    def test_runbook_is_listed_in_handoff(self):
        handoff = (REPO_ROOT / "docs" / "product-v3-handoff.md").read_text(encoding="utf-8")
        self.assertIn("product-v3-acceptance-runbook.md", handoff)


if __name__ == "__main__":
    unittest.main(verbosity=2)