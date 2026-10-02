# -*- coding: utf-8 -*-
"""CORE E8：高 DPI（缩放因子模拟）布局回归。

说明：本机没有可切换的物理 125%/150% 显示器，这里用 Qt 的 `QT_SCALE_FACTOR`
在离屏模式下**模拟**缩放，验证布局不变式（控件非零尺寸、都在窗口内、首页不出现横向溢出）。
物理缩放仍列为待验收项；本用例把模拟部分固定下来，避免以后回归。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROBE = REPO_ROOT / "scripts" / "tests" / "hidpi_probe.py"
SCALE_FACTORS = ("1", "1.25", "1.5")


def _run_probe(factor: str, size: str = "1280x720") -> dict:
    env = dict(os.environ)
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "QT_SCALE_FACTOR": factor,
        "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", "")))),
        "PYTHONUTF8": "1",
    })
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--size", size, "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600, env=env,
    )
    start = proc.stdout.find("{")
    if start < 0:
        raise AssertionError("探针未输出 JSON（exit={0}）：{1}".format(proc.returncode, proc.stderr[-300:]))
    return json.loads(proc.stdout[start:])


class HighDpiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measurements = {}

    def test_layout_invariants_hold_at_each_scale_factor(self):
        for factor in SCALE_FACTORS:
            with self.subTest(scale=factor):
                data = _run_probe(factor)
                HighDpiLayoutTests.measurements[factor] = data
                self.assertEqual(data["logicalSize"], {"width": 1280, "height": 720})
                expected_dpr = float(factor)
                self.assertAlmostEqual(data["devicePixelRatio"], expected_dpr, places=2)
                self.assertEqual(
                    data["physicalSize"]["width"], int(round(1280 * expected_dpr)),
                )
                self.assertEqual(data["issues"], [], data)
                self.assertTrue(data["ok"])
                names = {item["name"] for item in data["widgets"]}
                self.assertIn("menuBar", names)
                self.assertIn("home", names)
                for item in data["widgets"]:
                    self.assertGreater(item["width"], 0, item)
                    self.assertGreater(item["height"], 0, item)
                    self.assertTrue(item["insideWindow"], item)
                self.assertFalse(
                    data["scroll"]["horizontalScrollBarVisible"],
                    "缩放后首页不应出现横向溢出",
                )

    def test_measurements_are_recorded_for_the_ledger(self):
        """把实测数据打到输出，便于台账引用（避免只有断言没有数字）。"""
        for factor in SCALE_FACTORS:
            data = self.measurements.get(factor) or _run_probe(factor)
            print("HIDPI_JSON:" + json.dumps({
                "scale": factor,
                "devicePixelRatio": data["devicePixelRatio"],
                "logical": data["logicalSize"],
                "physical": data["physicalSize"],
                "widgets": len(data["widgets"]),
                "issues": data["issues"],
            }, ensure_ascii=False))
            self.assertTrue(data["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
