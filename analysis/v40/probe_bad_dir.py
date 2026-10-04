import sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from doc_tool.application.intake_contract import resolve_export_directory
work = Path(tempfile.mkdtemp(prefix="probe-dir-"))
bad = work / "bad"
bad.write_text("x", encoding="utf-8")
candidates = [
    ("file-as-dir", bad),
    ("nul-device", Path("NUL") / "x"),
    ("invalid-char", Path(str(work) + "\\in<valid>")),
]
for label, cand in candidates:
    try:
        resolve_export_directory(cand, [work / "alsobad" / "y"])
        print(label, "-> resolved (no error)")
    except OSError as exc:
        print(label, "-> OSError:", str(exc)[:170])