"""Observe export boundary behavior without modifying business code or invoking Word."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tests import core_fixtures as fixtures
from doc_tool.application.intake_contract import (
    ExportScope, FORMAT_HTML, SCOPE_CHAPTERS, SOURCE_MODE_SAVED,
)
from doc_tool.application.project_export import ExportReport, retry_export_formats
from doc_tool.ui.export_rounds import round_view_from_report
from doc_tool.ui.main_window import MainWindow


class UnexpectedFreshCapture(Exception):
    pass


def main():
    work = fixtures.scratch_dir("product-review-export-boundaries")
    results = []
    try:
        project = fixtures.two_chapter_project(work / "project")
        chapter = next((project / "content").rglob("*.md"))
        selected = chapter.relative_to(project / "content").as_posix()
        prior = ExportReport(
            roundId="review-old-round", captureId="review-old-capture",
            projectRoot=str(project), sourceMode=SOURCE_MODE_SAVED,
            destination=str(work / "exports"),
            snapshotWorkDir=str(work / "missing-original-capture"),
            scope=ExportScope(kind=SCOPE_CHAPTERS, chapters=[selected]),
        )
        fresh_capture_attempted = False
        with patch(
            "doc_tool.application.project_export.capture_snapshot",
            side_effect=UnexpectedFreshCapture("Current content would be recaptured"),
        ):
            try:
                retry_export_formats(prior, [FORMAT_HTML], skip_word_refresh=True)
            except UnexpectedFreshCapture:
                fresh_capture_attempted = True
        results.append({
            "id": "EX-1", "scenario": "retry_missing_original_capture",
            "expected_current_recapture": False,
            "actual_current_recapture": fresh_capture_attempted,
            "confirmed_gap": fresh_capture_attempted,
        })

        view = round_view_from_report(prior)
        incomplete = ExportReport(roundId=prior.roundId, captureId="")
        accepted = MainWindow._round_identity_matches(view, incomplete)
        results.append({
            "id": "EX-2", "scenario": "known_capture_missing_from_report",
            "expected_identity_match": False, "actual_identity_match": accepted,
            "confirmed_gap": accepted,
        })

        submitted = {}

        def observe_submit(**kwargs):
            submitted.update(kwargs)

        fake_window = SimpleNamespace(
            _project_summary=SimpleNamespace(
                project_root=project,
                paths=SimpleNamespace(output_dir=work / "exports"),
            ),
            _collect_buffer_texts=lambda: {selected: "UNSAVED_REVIEW_MARKER\n"},
            _run_export_task=observe_submit,
            _report_for_round=lambda unused_view: prior,
        )
        MainWindow._on_regenerate_round(fake_window, view)
        request = submitted["args"][0]
        results.append({
            "id": "EX-3", "scenario": "regenerate_selected_chapter_round",
            "expected_scope": prior.scope.to_dict(),
            "actual_scope": request.scope.to_dict(),
            "original_source": prior.sourceMode,
            "new_source": request.source_mode,
            "confirmed_gap": request.scope.to_dict() != prior.scope.to_dict(),
        })
        report = {
            "date": "2026-10-03", "timezone": "Asia/Shanghai",
            "word_invoked": False, "business_code_modified": False,
            "probes": results,
            "confirmed_gaps": sum(bool(item["confirmed_gap"]) for item in results),
        }
        target = Path(__file__).with_name("export-boundaries.json")
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        resolved = work.resolve()
        assert resolved.is_relative_to(fixtures.SCRATCH_ROOT.resolve())
        fixtures.cleanup(resolved)


if __name__ == "__main__":
    main()
