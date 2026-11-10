# -*- coding: utf-8 -*-
"""成果页：待刷新稿提供「更新目录与页码 (Word)」入口。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from PySide6.QtWidgets import QApplication
except Exception:  # noqa: BLE001
    QApplication = None

from doc_tool.ui.export_rounds import ExportRoundView, RoundFormatView  # noqa: E402

ACTION_TEXT = "更新目录与页码 (Word)"


@unittest.skipIf(QApplication is None, "当前环境没有 PySide6")
class ResultsRefreshActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _round(self, status: str, docx: Path) -> ExportRoundView:
        return ExportRoundView(
            round_id="r-1",
            project_root=str(docx.parent),
            destination=str(docx.parent),
            formats=[
                RoundFormatView(
                    format="docx",
                    status=status,
                    path=str(docx),
                    usable=True,
                    formal=status != "pending-refresh",
                )
            ],
        )

    def _actions(self, view) -> list:
        return [action.text() for action in view._more_menu.actions()]

    def test_pending_round_offers_refresh_action_and_invokes_callback(self) -> None:
        from doc_tool.ui.export_results_view import ExportResultsView

        called = []
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "out.docx"
            docx.write_bytes(b"PK\x03\x04")
            view = ExportResultsView(on_refresh_fields=called.append)
            view.render([self._round("pending-refresh", docx)], "r-1")
            self.assertIn(ACTION_TEXT, self._actions(view))
            action = next(a for a in view._more_menu.actions() if a.text() == ACTION_TEXT)
            action.trigger()

        self.assertTrue(called)
        self.assertEqual(called[0].round_id, "r-1")

    def test_refreshed_round_hides_action(self) -> None:
        from doc_tool.ui.export_results_view import ExportResultsView

        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "out.docx"
            docx.write_bytes(b"PK\x03\x04")
            view = ExportResultsView(on_refresh_fields=lambda _rv: None)
            view.render([self._round("ready", docx)], "r-1")
            self.assertNotIn(ACTION_TEXT, self._actions(view))

    def test_no_callback_hides_action(self) -> None:
        from doc_tool.ui.export_results_view import ExportResultsView

        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "out.docx"
            docx.write_bytes(b"PK\x03\x04")
            view = ExportResultsView()
            view.render([self._round("pending-refresh", docx)], "r-1")
            self.assertNotIn(ACTION_TEXT, self._actions(view))


if __name__ == "__main__":
    unittest.main()
