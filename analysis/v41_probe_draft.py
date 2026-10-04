import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, ".")
from doc_tool.application.pack_authoring import draft_from_pack
from doc_tool.application.standard_pack import load_project_pack

work = Path(tempfile.mkdtemp(prefix="probe-draft-"))
PACK = Path("standards/generic-requirement")
d = draft_from_pack(PACK, work / "副本")
print("root", d.root, "exists", Path(d.root).is_dir())
print("template", repr(d.template), "isfile", Path(d.template).is_file() if d.template else None)
print("pack_id", d.pack_id, "version", d.version)
print("files:", sorted(p.name for p in Path(d.root).iterdir()))
for ref in ({"id": "generic-requirement", "version": "1.0.0"}, {"packId": "generic-requirement", "version": "1.0.0"}):
    m, probs = load_project_pack(PACK.parent, ref)
    print("ref", ref, "->", None if m is None else m.pack_id, probs)