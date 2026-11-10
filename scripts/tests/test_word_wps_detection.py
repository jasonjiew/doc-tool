# -*- coding: utf-8 -*-
"""Word.Application 被 WPS 接管的识别（注册表 CLSID 比对）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application import word_check  # noqa: E402


class WpsDetectionTests(unittest.TestCase):
    def test_microsoft_word_clsid_is_not_wps(self) -> None:
        self.assertFalse(word_check.is_wps_replacing_word(word_check.MS_WORD_CLSID))
        self.assertFalse(
            word_check.is_wps_replacing_word(word_check.MS_WORD_CLSID.lower())
        )

    def test_other_clsid_is_treated_as_wps(self) -> None:
        self.assertTrue(
            word_check.is_wps_replacing_word("{DB6D5A2B-1111-2222-3333-444455556666}")
        )

    def test_unknown_clsid_is_not_wps(self) -> None:
        self.assertFalse(word_check.is_wps_replacing_word(None))
        self.assertFalse(word_check.is_wps_replacing_word(""))

    def test_registry_probe_does_not_raise(self) -> None:
        clsid = word_check.word_progid_clsid()
        self.assertTrue(clsid is None or str(clsid).startswith("{"))

    def test_availability_report_exposes_flag(self) -> None:
        report = word_check.WordAvailability()
        self.assertIn("wpsReplacingWord", report.to_dict())
        self.assertFalse(report.to_dict()["wpsReplacingWord"])
        report.wps_replacing_word = True
        self.assertTrue(report.to_dict()["wpsReplacingWord"])


if __name__ == "__main__":
    unittest.main()
