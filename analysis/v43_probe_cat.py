import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from doc_tool.application.collection import build_manifest, register_manifest, list_manifests
from doc_tool.application.delivery.revision_compare import _categorized, list_versions

work = Path(tempfile.mkdtemp(prefix="probe-cat-"))
root = work / "p1"
for rel, content in (("content/a.md", "A1"), ("standards/pack.yml", "P1"), ("modules/m1.md", "M1")):
    t = root / rel
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(content, encoding="utf-8")
m = build_manifest(root, version="v1", label="L")
path, err = register_manifest(root, m)
print("registered:", path, "err:", repr(err))
print("files in manifest:", [(f.relative_path, f.category) for f in m.files])
print("list_manifests:", list_manifests(root))
cat = _categorized(str(path))
print("categorized keys:", {k: sorted(v) for k, v in cat.items()})
if path is not None:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    print("yaml files sample:", (data.get("files") or [{}])[0])