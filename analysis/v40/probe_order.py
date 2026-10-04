import sys, tempfile, shutil
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from pathlib import Path
from unittest.mock import patch
from scripts.tests import core_fixtures as fixtures
from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest
from doc_tool.application import project_export as exporter
from doc_tool.domain import output_state

work = Path(tempfile.mkdtemp(prefix="probe-order-"))
proj = fixtures.two_chapter_project(work / "proj")
order = []
orig_layout = exporter._apply_layout
orig_write = output_state.write_state
def L(*a, **k):
    out = orig_layout(*a, **k)
    order.append(("layout", getattr(out, "rewritten", None)))
    return out
def W(*a, **k):
    order.append(("state", k.get("formal"), str(a[0])[-12:] if a else ""))
    return orig_write(*a, **k)
req = ExportRequest(project_root=str(proj), formats=[FORMAT_DOCX], source_mode="saved",
                    destination=str(work / "out"), layout_profile="body-adaptive")
with patch.object(exporter, "_apply_layout", L), patch.object(output_state, "write_state", W):
    rep = exporter.run_project_export(req, skip_word_refresh=True)
print("ORDER:")
for item in order:
    print("  ", item)
print("target:", rep.result_for("docx").path)
shutil.rmtree(work, ignore_errors=True)