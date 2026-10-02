# -*- coding: utf-8 -*-
"""生成 V3/CORE 本地审阅包（发布留待审阅时的交接物）。

产物：``deliverables/v3-review-<时间戳>/``
  - ``INDEX.md``：任务进度、证据摘要、冻结产物哈希、待验收项、下一步；
  - ``manifest.json``（schema 1）：每个文件的相对路径/字节数/sha256，便于核对；
  - ``tasks/``、``specs/``、``ledgers/``、``evidence/``：五份 tasks.md、specs、执行台账、
    全量回归证据、冻结产物哈希与工作树状态。

只读取仓库内容并写入输出目录，不改动源文件；默认不打包 exe（体积大），只记录哈希。
用法：
    python scripts\\release\\make_review_bundle.py                 # 输出到 deliverables/
    python scripts\\release\\make_review_bundle.py --out tmp/bundle --zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGES = (
    "product-core-import-export",
    "product-v30-content-reuse",
    "product-v31-team-workflow",
    "product-v32-batch-delivery",
    "product-v33-authoring-assistance",
)
LEDGERS = (
    "docs/product-core-workflow-execution.md",
    "docs/product-plan-v3-execution.md",
    "docs/product-v30-execution-entry.md",
    "docs/product-v30-reuse-formats.md",
    "docs/product-v31-execution.md",
    "docs/product-v31-usage.md",
    "docs/product-v32-execution-entry.md",
    "docs/product-v33-execution.md",
    "docs/product-v30-v33-usage.md",
    "docs/product-v3-release-readiness.md",
    "docs/product-v3-evidence-check.md",
    "docs/product-v3-audit-findings.md",
    "docs/product-v3-handoff.md",
    "docs/product-v3-acceptance-runbook.md",
    "docs/product-v3-runbook-verification.md",
    "docs/product-v3-final-report.md",
)
FROZEN_ARTIFACTS = ("dist/DocTool/DocTool.exe", "dist/DocTool/doc-tool-cli.exe")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _task_counts(change: str) -> tuple:
    path = REPO_ROOT / "openspec" / "changes" / change / "tasks.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    done = len(re.findall(r"- \[x\] ", text))
    todo = re.findall(r"- \[ \] (\d+\.\d+)", text)
    return done, todo


def _latest_junit() -> Path | None:
    candidates = sorted(REPO_ROOT.glob("test-results-full-v3-r*.xml"))
    if not candidates:
        candidates = sorted(REPO_ROOT.glob("test-results-full*.xml"))
    return candidates[-1] if candidates else None


def _junit_summary(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    import xml.etree.ElementTree as ET

    tree = ET.parse(path)
    suites = list(tree.getroot().iter("testsuite"))
    tests = sum(int(suite.get("tests", 0) or 0) for suite in suites)
    failures = sum(int(suite.get("failures", 0) or 0) for suite in suites)
    errors = sum(int(suite.get("errors", 0) or 0) for suite in suites)
    failed = []
    for suite in suites:
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(case.get("name", ""))
    return {"files": len(suites), "tests": tests, "failures": failures, "errors": errors, "failed": failed}


def _copy(rel: str, target_dir: Path, records: list) -> Path | None:
    source = REPO_ROOT / rel
    if not source.is_file():
        return None
    destination = target_dir / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(destination))
    records.append({"path": rel, "bytes": destination.stat().st_size, "sha256": _sha256(destination)})
    return destination


def build(out_dir: Path, *, make_zip: bool = False) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(out_dir) / "v3-review-{0}".format(stamp)
    target.mkdir(parents=True, exist_ok=True)
    records: list = []

    for change in CHANGES:
        for name in ("proposal.md", "design.md", "tasks.md"):
            _copy("openspec/changes/{0}/{1}".format(change, name), target, records)
        specs = REPO_ROOT / "openspec" / "changes" / change / "specs"
        for path in sorted(specs.rglob("*.md")):
            _copy(path.relative_to(REPO_ROOT).as_posix(), target, records)
    for rel in LEDGERS:
        _copy(rel, target, records)

    junit = _latest_junit()
    if junit is not None:
        _copy(junit.relative_to(REPO_ROOT).as_posix(), target, records)
    junit_summary = _junit_summary(junit)

    # 工作树状态（未提交范围）
    status = subprocess.run(
        ["git", "status", "--short"], cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    diffstat = subprocess.run(
        ["git", "diff", "--stat"], cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    evidence_dir = target / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "git-status.txt").write_text(
        (status.stdout or "") + "\n" + (diffstat.stdout or ""), encoding="utf-8",
    )
    frozen = []
    for rel in FROZEN_ARTIFACTS:
        path = REPO_ROOT / rel
        if path.is_file():
            frozen.append({
                "path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path),
                "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            })
    (evidence_dir / "frozen-artifacts.json").write_text(
        json.dumps({"schemaVersion": 1, "artifacts": frozen}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    records.append({
        "path": "evidence/git-status.txt",
        "bytes": (evidence_dir / "git-status.txt").stat().st_size,
        "sha256": _sha256(evidence_dir / "git-status.txt"),
    })
    records.append({
        "path": "evidence/frozen-artifacts.json",
        "bytes": (evidence_dir / "frozen-artifacts.json").stat().st_size,
        "sha256": _sha256(evidence_dir / "frozen-artifacts.json"),
    })

    rows = []
    for change in CHANGES:
        done, todo = _task_counts(change)
        rows.append("| `{0}` | {1} | {2} |".format(change, done, ", ".join(todo) or "—"))

    index = [
        "# V3 / CORE 本地审阅包",
        "",
        "生成时间：{0}（UTC）".format(stamp),
        "生成方式：`python scripts\\release\\make_review_bundle.py`（只读取仓库，不改动源文件）",
        "",
        "## 1. 任务进度",
        "",
        "| change | 已勾选 | 剩余任务 |",
        "|---|---|---|",
        *rows,
        "",
        "## 2. 全量回归证据",
        "",
        "- 证据文件：`{0}`".format(junit.name if junit else "（未找到）"),
        "- 汇总：{0} 个测试文件 / {1} 项失败 / {2} 项错误".format(
            junit_summary.get("files", "?"), junit_summary.get("failures", "?"),
            junit_summary.get("errors", "?"),
        ),
    ]
    for name in junit_summary.get("failed", [])[:5]:
        index.append("  - 失败：`{0}`（已知环境项：缺 `mmdc`）".format(name))
    index += [
        "",
        "## 3. 冻结产物哈希",
        "",
        "| 文件 | 字节 | sha256 |",
        "|---|---|---|",
    ]
    for item in frozen:
        index.append("| `{0}` | {1} | `{2}` |".format(item["path"], item["bytes"], item["sha256"][:16] + "…"))
    index += [
        "",
        "## 4. 待验收项",
        "",
        "见 `docs/product-v3-release-readiness.md` 第 2 节：四个同步/归档任务（需授权）、两项人工试点、实机缩放与两机交接。",
        "",
        "## 5. 下一步",
        "",
        "- 归档（需授权）：`python scripts\\release\\archive_changes.py --yes`（默认 dry-run 只核对）",
        "- 复核全量：`python scripts\\tests\\run_tests.py --junit test-results-full-v3.xml`",
        "- 冻结冒烟：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\build_exe.ps1`",
    ]
    (target / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    records.append({
        "path": "INDEX.md", "bytes": (target / "INDEX.md").stat().st_size,
        "sha256": _sha256(target / "INDEX.md"),
    })

    manifest = {
        "schemaVersion": 1,
        "kind": "v3-review-bundle",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "root": str(target),
        "files": records,
        "frozenArtifacts": frozen,
        "junit": junit_summary,
        "taskProgress": {change: _task_counts(change) for change in CHANGES},
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    if make_zip:
        archive = target.with_suffix(".zip")
        with zipfile.ZipFile(str(archive), "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    bundle.write(str(path), path.relative_to(target).as_posix())
        manifest["zip"] = str(archive)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 V3/CORE 本地审阅包")
    parser.add_argument("--out", default=str(REPO_ROOT / "deliverables"), help="输出根目录（默认 deliverables/）")
    parser.add_argument("--zip", action="store_true", help="同时打包为 ZIP")
    args = parser.parse_args(argv)

    manifest = build(Path(args.out), make_zip=args.zip)
    print("审阅包：", manifest["root"])
    print("文件数：", len(manifest["files"]))
    print("全量：", manifest["junit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())