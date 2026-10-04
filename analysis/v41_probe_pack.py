import sys
from pathlib import Path
sys.path.insert(0, ".")
from doc_tool.application.standard_pack import load_project_pack, bundled_standards_root

print("bundled root:", bundled_standards_root())
for ref in ({"id": "generic-requirement", "version": "1.0.0"},
            {"id": "generic-requirement", "version": "1.0.0", "source": "bundled"}):
    m, probs = load_project_pack(bundled_standards_root().parent, ref)
    print("ref", ref, "->", None if m is None else (m.pack_id, m.version), probs[:2])
import inspect
print(inspect.getdoc(load_project_pack)[:400])