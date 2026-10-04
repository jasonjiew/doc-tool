import sys, tempfile
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from scripts.tests import core_fixtures as fixtures
from doc_tool.application.intake_contract import ExportRequest
from doc_tool.application.project_export import run_project_export
from doc_tool.application.delivery.handover import build_handover_package, inspect_package

work = Path(tempfile.mkdtemp(prefix="probe-pkg-"))
proj = fixtures.two_chapter_project(work / "proj")
req = ExportRequest(project_root=str(proj), formats=["docx", "html"],
                    source_mode="saved", destination=str(work / "out"))
report = run_project_export(req, skip_word_refresh=True)
for include in (False, True):
    out = build_handover_package(report, destination=work / ("pkg-%s.zip" % include), include_original=include)
    print("include", include, "ok", out.ok, "purpose", out.facts.purpose if out.facts else None)
    if out.facts:
        print("  refreshInputs", out.facts.refreshInputs[:6])
        print("  entries sample", out.facts.entries[:12])
        print("  offlineEntry", out.facts.offlineEntry, "missing", out.facts.missing)