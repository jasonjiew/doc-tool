"""验证本次修复证据、规划勾选、文档链接及源码完整性。"""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
changes = ["product-v37-daily-workflow-ux", "product-v38-authoring-and-exchange-ux", "product-v39-rd-workspace-productivity"]
doc_names = ["product-post-implementation-review-20261003.md", "product-v37-v39-roadmap.md", "product-v37-v39-execution.md", "product-execution-confirmed-prompt.md", "product-next-execution.md", "product-master-roadmap.md", "product-function-catalog.md", "product-execution-review-20261003.md", "product-rd-workspace-execution.md", "product-v34-table-execution.md", "product-v35-standard-pack-execution.md", "product-v36-large-document-execution.md"]
files = [ROOT / "docs" / name for name in doc_names]
plan = []
for change in changes:
    base = ROOT / "openspec/changes" / change
    files.extend(base.rglob("*.md"))
    tasks = (base / "tasks.md").read_text(encoding="utf-8")
    checked = re.findall(r"^- \[x\] (\d+\.\d+)", tasks, re.M)
    pending = re.findall(r"^- \[ \] (\d+\.\d+)", tasks, re.M)
    assert not checked and len(pending) == len(set(pending)) == 20, change
    assert len(list((base / "specs").glob("*/spec.md"))) == 2, change
    plan.append({"change": change, "done": len(checked), "tasks": len(pending)})

link_count = 0
for file in files:
    text = file.read_text(encoding="utf-8")
    assert text.strip(), file
    for match in re.finditer(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^\)]+))\)", text):
        target = (match.group(1) or match.group(2)).strip()
        if not target or target.startswith(("#", "http:", "https:", "mailto:", "app:", "plugin:", "data:")):
            continue
        target = re.sub(r":\d+$", "", unquote(target.split("#", 1)[0]))
        path = (file.parent / target).resolve()
        assert path.exists(), (str(file.relative_to(ROOT)), target)
        link_count += 1

sources = ["doc_tool/application/content/table_grid.py", "doc_tool/application/pack_authoring.py", "doc_tool/ui/content/table_grid_dialog.py", "doc_tool/ui/content/editor_panel.py", "doc_tool/ui/standard_pack_dialog.py", "doc_tool/ui/rd_workspace.py", "doc_tool/ui/styles.py", "scripts/tests/test_product_post_implementation_review.py", "scripts/tests/test_v34_table_authoring.py", "scripts/tests/test_v35_standard_pack.py", "scripts/tests/test_ui_polish_toolbar.py", "scripts/tests/test_final_handover_report.py", "scripts/release/report_final_handover.py", "scripts/tests/run_tests.py"]
for rel in sources:
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert text.strip(), rel
    compile(text, rel, "exec")

reports = []
for name in ("related-final.xml", "pack-export-final.xml", "handover-final.xml"):
    tree = ET.parse(HERE / name)
    suites = list(tree.getroot().iter("testsuite"))
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    outputs = "\n".join(n.text or "" for n in tree.getroot().iter("system-out"))
    internal = sum(int(n) for n in re.findall(r"Ran (\d+) tests? in", outputs))
    assert failures == 0, name
    executed = {case.get("name", "") for case in tree.getroot().iter("testcase")}
    reports.append({"file": name, "files": len(executed), "internalCases": internal, "failuresAndErrors": failures})

geometry = json.loads((HERE / "ui-release/geometry.json").read_text(encoding="utf-8"))
assert len(geometry) == 44
assert all(r["width"] == r["requested"][0] and r["height"] == r["requested"][1] for r in geometry)
registered = len(re.findall(r'"(test_[A-Za-z0-9_]+\.py)"', (ROOT / "scripts/tests/run_tests.py").read_text(encoding="utf-8")))
result = {"markdownFiles": len(files), "localLinks": link_count, "plannedChanges": plan, "compiledSources": len(sources), "reports": reports, "screenshots": len(geometry), "defaultTestFiles": registered, "editorRestoredBlob": "c65c4a36ea76f9dd6b598197d781f4eaf522d232"}
(HERE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
