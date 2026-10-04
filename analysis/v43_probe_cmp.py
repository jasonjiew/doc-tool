import sys, tempfile
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from doc_tool.application.collection import build_manifest, register_manifest
from doc_tool.application.delivery.revision_compare import _categorized, list_versions, compare_versions

work = Path(tempfile.mkdtemp(prefix="probe-cmp-"))
opts = []
for version, files in (
    ("v1", (("content/a.md", "A1"), ("standards/pack.yml", "P1"), ("modules/m1.md", "M1"))),
    ("v2", (("content/a.md", "A1"), ("standards/pack.yml", "P2"), ("modules/m1.md", "M2"))),
):
    root = work / ("项目-" + version)
    for rel, content in files:
        t = root / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(content, encoding="utf-8")
    m = build_manifest(root, version=version, label="同类集合")
    path, err = register_manifest(root, m)
    o = list_versions(root)[0]
    opts.append(o)
    cat = _categorized(o.path)
    print(version, "path", Path(o.path).name, "categories", {k: sorted(v) for k, v in cat.items()})
raw = Path(opts[0].path).read_text(encoding="utf-8")
print("manifest head:", raw[:300].replace(chr(10), " | "))
import yaml
data = yaml.safe_load(raw)
print("keys:", sorted(data.keys()))
print("files type:", type(data.get("files")), "len:", len(data.get("files") or []))
print("first file:", (data.get("files") or [{}])[0])
cmp = compare_versions(opts[0].identity, opts[1].identity, options=opts)
print("known", cmp.known, "reason", cmp.reason)
print("sourceChanges", cmp.sourceChanges)
print("assembledChanges", cmp.assembledChanges)
print("groups", {k: len(v) for k, v in cmp.groups.items()})
print("unavailable", cmp.unavailableGroups)