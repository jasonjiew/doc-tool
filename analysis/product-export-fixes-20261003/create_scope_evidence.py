"""Repeat two actual result-button cases and retain their HTML evidence."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["PRODUCT_EXPORT_FIX_EVIDENCE"] = "1"
from scripts.tests.test_export_round_recovery import RoundRegenerationTests

suite = unittest.TestSuite(RoundRegenerationTests(name) for name in (
    "test_selected_chapter_regeneration_creates_actual_scoped_html",
    "test_current_chapter_regeneration_keeps_original_chapter_after_navigation",
))
if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
