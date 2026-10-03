"""Check current planning links, task counts, and recorded review evidence."""
import ast
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CHANGES = [
    "product-core-import-export", "product-v30-content-reuse",
    "product-v31-team-workflow", "product-v32-batch-delivery",
    "product-v33-authoring-assistance", "product-ui-interaction-polish",
    "product-ui-experience-next", "product-rd-workspace-experience",
    "product-v34-table-authoring", "product-v35-standard-pack-authoring",
    "product-v36-large-document-performance",
]
DOCS = [
    "docs/product-execution-review-20261003.md",
    "docs/product-execution-confirmed-prompt.md",
    "docs/product-master-roadmap.md", "docs/product-next-execution.md",
    "docs/product-ui-experience-next-execution.md",
    "docs/product-function-catalog.md",
    "openspec/changes/product-rd-workspace-experience/design.md",
    "openspec/changes/product-rd-workspace-experience/tasks.md",
    "openspec/changes/product-v36-large-document-performance/design.md",
]


def xml_summary(path):
    root = ET.parse(path).getroot()
    return {"executionItems": int(root.attrib["tests"]),
            "failedExecutionItems": int(root.attrib["failures"])}


def main():
    errors = []
    tasks = {}
    for name in CHANGES:
        path = ROOT / "openspec" / "changes" / name / "tasks.md"
        rows = re.findall(r"^- \[([ xX])\] (\d+\.\d+)\s", path.read_text(encoding="utf-8"), re.M)
        ids = [row[1] for row in rows]
        if len(ids) != len(set(ids)):
            errors.append("Duplicate task IDs: " + name)
        tasks[name] = {"checked": sum(state.lower() == "x" for state, _ in rows),
                       "total": len(rows),
                       "unchecked": [task_id for state, task_id in rows if state == " "]}
    next_tasks = [tasks[name] for name in CHANGES[-4:]]
    if sum(item["total"] for item in next_tasks) != 84:
        errors.append("Next four package task total is no longer 84")

    links = 0
    for relative in DOCS:
        path = ROOT / relative
        value = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]*\]\(([^\n)]+)\)", value):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z]+://", target, re.I):
                continue
            resolved = Path(target)
            if not resolved.is_absolute():
                resolved = path.parent / resolved
            links += 1
            if not resolved.exists():
                errors.append("Missing local link: " + relative + " -> " + target)
        for number, line in enumerate(value.splitlines(), 1):
            if line.rstrip() != line:
                errors.append("Trailing whitespace: " + relative + ":" + str(number))

    tree = ast.parse((ROOT / "scripts/tests/run_tests.py").read_text(encoding="utf-8"))
    registered = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_TESTS" for target in node.targets
        ):
            registered = ast.literal_eval(node.value)
    if registered is None:
        errors.append("DEFAULT_TESTS not found")

    direct = ET.parse(OUT / "direct-checks.xml").getroot()
    unit_runs = []
    for case in direct.findall(".//testcase"):
        count = re.search(r"Ran (\d+) tests? in", case.findtext("system-out", ""))
        if count:
            unit_runs.append({"file": case.attrib["name"], "cases": int(count.group(1))})
    probes = json.loads((OUT / "export-boundaries.json").read_text(encoding="utf-8"))
    fonts = json.loads((OUT / "ui2-acceptance-with-fonts/font-environment.json").read_text(encoding="utf-8"))
    font_result = xml_summary(OUT / "font-checks.xml")
    if not fonts["supportsChineseGlyph"] or font_result["failedExecutionItems"]:
        errors.append("Chinese font acceptance failed")
    report = {
        "date": "2026-10-03", "timezone": "Asia/Shanghai",
        "head": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "taskSnapshot": tasks, "nextPackageTasks": sum(item["total"] for item in next_tasks),
        "nextPackageUncheckedTasks": sum(len(item["unchecked"]) for item in next_tasks),
        "checkedMarkdownFiles": len(DOCS), "checkedLocalLinks": links,
        "initialDirectChecks": xml_summary(OUT / "direct-checks.xml"),
        "unitTestFiles": len(unit_runs), "unitTestCases": sum(item["cases"] for item in unit_runs),
        "unitTestRuns": unit_runs, "confirmedExportGaps": probes["confirmed_gaps"],
        "historicalFullRun": xml_summary(ROOT / "analysis/ui2-final.xml"),
        "currentDefaultTestFiles": len(registered) if registered else None,
        "allDefaultFilesRerunThisTurn": False,
        "chineseFontAcceptance": font_result, "font": fonts,
        "realDpiImeWordTrial": False, "errors": errors,
    }
    (OUT / "review-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "head", "nextPackageTasks", "nextPackageUncheckedTasks", "checkedMarkdownFiles",
        "checkedLocalLinks", "unitTestFiles", "unitTestCases", "confirmedExportGaps",
        "currentDefaultTestFiles", "chineseFontAcceptance", "errors",
    )}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
