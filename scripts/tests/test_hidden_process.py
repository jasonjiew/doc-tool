# -*- coding: utf-8 -*-
"""GUI 子进程静默：打开项目时不再连续弹出黑色控制台窗口。"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.domain import hidden_process as hp  # noqa: E402


class WithNoWindowTests(unittest.TestCase):
    def test_explicit_creationflags_win(self) -> None:
        merged = hp.with_no_window({"creationflags": 0x1234})
        self.assertEqual(merged["creationflags"], 0x1234)

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_default_is_create_no_window(self) -> None:
        merged = hp.with_no_window({"timeout": 5})
        self.assertEqual(merged["creationflags"], hp.CREATE_NO_WINDOW)
        self.assertEqual(merged["timeout"], 5)


@unittest.skipUnless(os.name == "nt", "Windows only")
class InstallTests(unittest.TestCase):
    def tearDown(self) -> None:
        hp.uninstall_no_window_defaults()

    def test_install_is_idempotent_and_reversible(self) -> None:
        before = subprocess.Popen
        self.assertTrue(hp.install_windows_no_window_defaults())
        self.assertIsNot(subprocess.Popen, before)
        self.assertFalse(hp.install_windows_no_window_defaults())
        hp.uninstall_no_window_defaults()
        self.assertIs(subprocess.Popen, before)

    def test_wrapped_popen_still_runs(self) -> None:
        hp.install_windows_no_window_defaults()
        completed = subprocess.run(
            [sys.executable, "-c", "print('ok')"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
