import sys, tempfile, os
from pathlib import Path
sys.path.insert(0, ".")
from doc_tool.application.intake_contract import resolve_export_directory
work = Path(tempfile.mkdtemp(prefix="probe-dir2-"))
bad = work / "bad"
bad.write_text("x", encoding="utf-8")
resolved, note = resolve_export_directory(bad, [work / "alsobad" / "y"])
print("resolved:", resolved, "exists:", Path(resolved).exists(), "is_file:", Path(resolved).is_file())
print("note:", note)
print("bad is file:", bad.is_file(), "alsobad exists:", (work / "alsobad").exists())
print("probe left:", [str(p.relative_to(work)) for p in work.rglob(".doctool-write-probe")])
print("all entries:", sorted(str(p.relative_to(work)) for p in work.rglob("*"))[:12])