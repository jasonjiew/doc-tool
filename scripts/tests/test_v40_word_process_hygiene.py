# -*- coding: utf-8 -*-
"""V4.0 40-D：Word 探测不得在系统里留下孤儿 Word 进程。"""

from __future__ import annotations

import os
import sys
import unittest

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application import word_check  # noqa: E402


@unittest.skipUnless(os.name == "nt", "仅在 Windows 上检查 Word 进程")
class WordProbeProcessHygieneTests(unittest.TestCase):
    """探测前后 Word 进程集合必须一致：只允许清理本应用启动的进程。"""

    def test_probe_does_not_leak_word_processes(self):
        before = word_check._get_winword_pids()
        # 连续 3 次探测：无论成功与否，都不得留下新增 Word 进程。
        results = [bool(word_check.check_word_available().available) for _ in range(3)]
        after = word_check._get_winword_pids()
        leaked = sorted(after - before)
        self.assertEqual(
            leaked, [],
            "探测后出现新增 Word 进程（本次探测结果 {0}）：{1}".format(results, leaked),
        )

    def test_user_word_process_is_never_touched(self):
        """用户已打开的 Word（探测前就在的 PID）必须原样保留。"""
        before = word_check._get_winword_pids()
        if not before:
            self.skipTest("当前没有已打开的 Word，跳过保留性检查")
        word_check.check_word_available()
        after = word_check._get_winword_pids()
        missing = sorted(before - after)
        self.assertEqual(
            missing, [],
            "探测把用户已打开的 Word 也关掉了：{0}".format(missing),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)