import sys
from pathlib import Path
sys.path.insert(0, ".")
from doc_tool.application.intake_contract import resolve_export_directory
for label, cand in (("nul-char", Path("C:\\x") / ("bad\\x00name")), ("empty", Path("")), ("relative-bad", Path("C:\\nul\\..\\nul\\x"))):
    try:
        r = resolve_export_directory(cand, [])
        print(label, "-> resolved:", r)
    except OSError as exc:
        print(label, "-> OSError:", str(exc)[:150])