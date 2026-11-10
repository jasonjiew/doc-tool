# -*- coding: utf-8 -*-
"""WPS 接管 Word.Application 时不得进入 Word 刷新（防 900 秒挂起）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.adapters import kernel  # noqa: E402
from doc_tool.application import project_export  # noqa: E402


class WpsWordRefreshGuardTests(unittest.TestCase):
    def test_export_word_available_is_false_under_wps(self) -> None:
        with mock.patch(
            "doc_tool.application.word_check.is_wps_replacing_word",
            return_value=True,
        ), mock.patch(
            "doc_tool.application.word_check.check_word_available"
        ) as probe:
            self.assertFalse(project_export._word_available())
        probe.assert_not_called()

    def test_refresh_with_project_short_circuits_under_wps(self) -> None:
        with mock.patch(
            "doc_tool.application.word_check.is_wps_replacing_word",
            return_value=True,
        ):
            ok, reason = kernel.refresh_with_project(None, None)
        self.assertFalse(ok)
        self.assertEqual(reason, "word_unavailable")

    def test_refresh_with_project_proceeds_without_wps(self) -> None:
        with mock.patch(
            "doc_tool.application.word_check.is_wps_replacing_word",
            return_value=False,
        ), mock.patch.object(kernel, "ensure_kernel_importable"), mock.patch.object(
            kernel, "config_from_project", side_effect=RuntimeError("reached")
        ):
            with self.assertRaises(RuntimeError):
                kernel.refresh_with_project(None, None)


if __name__ == "__main__":
    unittest.main()
