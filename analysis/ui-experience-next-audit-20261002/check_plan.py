"""Check this proposal's local links, task numbering, and capability structure."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGE = ROOT / "openspec/changes/product-ui-experience-next"
files = [ROOT / "docs/product-ui-experience-next-plan.md",
         ROOT / "docs/product-ui-experience-next-execution.md",
         ROOT / "docs/product-master-roadmap.md", *CHANGE.rglob("*.md")]
errors = []
link_count = 0
for path in files:
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http:", "https:", "codex:", "#")):
            continue
        target = target.split("#", 1)[0].strip("<>")
        if not target:
            continue
        link_count += 1
        if not (path.parent / target).resolve().exists():
            errors.append(f"Missing link: {path.relative_to(ROOT)} -> {target}")

tasks_text = (CHANGE / "tasks.md").read_text(encoding="utf-8")
task_ids = re.findall(r"^- \[[ x]\] (\d+\.\d+)\b", tasks_text, re.M)
expected = [f"{group}.{item}" for group, count in enumerate([4, 4, 5, 5, 4, 4], 1)
            for item in range(1, count + 1)]
if task_ids != expected:
    errors.append(f"Task IDs differ from expected: {task_ids}")
if re.search(r"^- \[x\]", tasks_text, re.M):
    errors.append("Implementation task was checked during planning")

proposal = (CHANGE / "proposal.md").read_text(encoding="utf-8")
capabilities = re.findall(r"^- `(desktop-[a-z-]+)`", proposal, re.M)
specs = sorted(path.parent.name for path in (CHANGE / "specs").glob("*/spec.md"))
if sorted(capabilities) != specs:
    errors.append("Proposal capabilities do not match spec directories")
requirements = scenarios = 0
for spec in (CHANGE / "specs").glob("*/spec.md"):
    content = spec.read_text(encoding="utf-8")
    if not content.startswith("## ADDED Requirements"):
        errors.append(f"Missing delta header: {spec}")
    for block in re.split(r"^### Requirement:", content, flags=re.M)[1:]:
        requirements += 1
        if "SHALL" not in block or "#### Scenario:" not in block:
            errors.append(f"Incomplete requirement: {spec} {block[:40]}")
    for block in re.split(r"^#### Scenario:", content, flags=re.M)[1:]:
        scenarios += 1
        if "**WHEN**" not in block or "**THEN**" not in block:
            errors.append(f"Incomplete scenario: {spec} {block[:40]}")

result = {"tasks": len(task_ids), "implementation_tasks_completed": 0,
          "capabilities": specs, "requirements": requirements, "scenarios": scenarios,
          "local_links_checked": link_count, "errors": errors,
          "scope": "Planning structure only; not UI implementation or business acceptance"}
(Path(__file__).parent / "plan-check.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(bool(errors))
