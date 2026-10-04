# -*- coding: utf-8 -*-
"""V4.0 40-E：导出目录探测的失败原因必须可读（冻结产物定位用）。"""

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

from doc_tool.application.intake_contract import resolve_export_directory  # noqa: E402


class _UnwritablePath:
    """只代理需要的方法：mkdir 成功但写入被拒（模拟只读/受限目录）。"""

    def __init__(self, base: Path):
        self._base = base

    def __fspath__(self):
        return str(self._base)

    def __str__(self):
        return str(self._base)

    def __truediv__(self, other):
        return self._base / other


class ExportDirectoryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v40-dir-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_all_candidates_fail_reports_each_reason(self):
        """全部候选失败时，错误信息必须带上每个候选的真实原因。"""
        # ``nul`` 设备下的路径在 Windows 上必然无法创建，且与权限无关。
        bad_candidate = Path("C:\\nul\\..\\nul\\x")
        with self.assertRaises(OSError) as ctx:
            resolve_export_directory(bad_candidate, [Path("C:\\nul\\..\\nul\\y")])
        message = str(ctx.exception)
        self.assertIn("没有可写的导出目录", message)
        self.assertIn("已尝试", message, "必须列出已尝试的候选")
        self.assertIn("nul", message, "必须带上失败候选的真实路径")
        self.assertIn("Error", message, "必须带上真实异常类型")

    def test_first_writable_candidate_is_used_without_note(self):
        target = self.work / "ok-out"
        resolved, note = resolve_export_directory(target, [self.work / "fallback"])
        self.assertEqual(resolved, target)
        self.assertIsNone(note, "首选可用时不得声称已回退")
        self.assertTrue(target.is_dir())

    def test_fallback_note_names_the_real_directory(self):
        blocked = self.work / "blocker-file"
        blocked.write_text("x", encoding="utf-8")
        fallback = self.work / "fallback-dir"
        resolved, note = resolve_export_directory(blocked, [fallback])
        self.assertEqual(resolved, fallback)
        self.assertIsNotNone(note)
        self.assertIn(str(fallback), note, "回退说明必须写明真实目录")


if __name__ == "__main__":
    unittest.main(verbosity=2)