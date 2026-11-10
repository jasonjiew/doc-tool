# -*- coding: utf-8 -*-
"""Word 刷新卡在启动阶段（DispatchEx）时的 PID 兜底。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import refresh_fields  # noqa: E402


@unittest.skipUnless(os.name == "nt", "WINWORD 进程探测仅在 Windows 上可用")
class WordPidFallbackTests(unittest.TestCase):
    def test_single_new_invisible_process_is_attributed(self) -> None:
        with mock.patch.object(
            refresh_fields, "_get_winword_pids", return_value={101, 102, 103}
        ), mock.patch.object(
            refresh_fields, "_has_visible_top_level_window", return_value=False
        ):
            self.assertEqual(refresh_fields._fallback_pid_from_diff([101, 102]), 103)

    def test_visible_new_process_is_never_killed(self) -> None:
        """用户在这段时间自己打开的 Word 有可见窗口，不能按差集杀。"""
        with mock.patch.object(
            refresh_fields, "_get_winword_pids", return_value={101, 102, 103}
        ), mock.patch.object(
            refresh_fields, "_has_visible_top_level_window", return_value=True
        ):
            self.assertIsNone(refresh_fields._fallback_pid_from_diff([101, 102]))

    def test_unknown_window_state_does_not_kill(self) -> None:
        with mock.patch.object(
            refresh_fields, "_get_winword_pids", return_value={101, 102, 103}
        ), mock.patch.object(
            refresh_fields, "_has_visible_top_level_window", return_value=None
        ):
            self.assertIsNone(refresh_fields._fallback_pid_from_diff([101, 102]))

    def test_multiple_new_processes_are_not_guessed(self) -> None:
        with mock.patch.object(
            refresh_fields, "_get_winword_pids", return_value={101, 102, 103, 104}
        ):
            self.assertIsNone(refresh_fields._fallback_pid_from_diff([101, 102]))

    def test_no_new_process_returns_none(self) -> None:
        with mock.patch.object(
            refresh_fields, "_get_winword_pids", return_value={101, 102}
        ):
            self.assertIsNone(refresh_fields._fallback_pid_from_diff([101, 102]))

    def test_probe_failure_is_tolerated(self) -> None:
        with mock.patch.object(
            refresh_fields, "_get_winword_pids", side_effect=OSError("no snapshot")
        ):
            self.assertIsNone(refresh_fields._fallback_pid_from_diff([1]))


if __name__ == "__main__":
    unittest.main()
