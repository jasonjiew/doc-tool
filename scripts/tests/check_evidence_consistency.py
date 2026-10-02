# -*- coding: utf-8 -*-
"""证据/台账一致性核对（同步/归档前置）。

核对项：
  1. 每个 change 的 proposal/design/tasks/specs 齐备，且 `openspec validate --strict` 通过；
  2. tasks.md 勾选数与剩余任务编号，与准备度报告表格一致（防台账过期）；
  3. tasks.md 与本版执行台账里提到的**文件路径**都能解析到真实文件（含 basename 兜底）；
  4. 提到的 `scripts/tests/test_*.py` 若未注册进 `run_tests.py` 默认清单，作为提醒列出；
  5. 每个 change 的执行台账存在且非空（有实际记录）。

用法：``python scripts\\tests\\check_evidence_consistency.py``
退出码：0 = 无失败；1 = 存在失败项（缺文件/校验失败/台账缺失）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGES = (
    ("product-core-import-export", "CORE", "docs/product-core-workflow-execution.md"),
    ("product-v30-content-reuse", "V3.0", "docs/product-v30-execution-entry.md"),
    ("product-v31-team-workflow", "V3.1", "docs/product-v31-execution.md"),
    ("product-v32-batch-delivery", "V3.2", "docs/product-v32-execution-entry.md"),
    ("product-v33-authoring-assistance", "V3.3", "docs/product-v33-execution.md"),
)
KNOWN_SUFFIXES = (".py", ".md", ".json", ".yml", ".yaml", ".ps1", ".spec", ".xml", ".zip", ".docx", ".html")
#: 运行期/项目内路径（真实存在于用户项目而非本仓库），核对时跳过。
RUNTIME_PREFIXES = (
    "reuse/", ".state/", "quality/", "content/", "collections/", "logs/", "output/",
    "original/", "assets/", "templates/", "config/", "delivery-out/",
)
PATH_PATTERN = re.compile(r"[A-Za-z0-9_.\\/\-]+\.[A-Za-z0-9]{2,5}")


def _file_index() -> dict:
    """basename -> 相对路径列表（用于兜底解析只写文件名的证据）。"""
    index: dict = {}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith((".git/", "tmp/", "build/", "dist/", ".vendor/")):
            continue
        index.setdefault(path.name, []).append(rel)
    return index


def _resolve(raw: str, index: dict):
    text = raw.strip().strip("`").replace("\\", "/").strip("\"'")
    if not text or not text.endswith(KNOWN_SUFFIXES):
        return None
    if any(token in text for token in ("*", "?", "<", ">", "{", "}")):
        return None
    if text.startswith(("http://", "https://")):
        return None
    if text.startswith("/"):
        return None  # 片段（如某些用户级路径的后半段），不是仓库内文件
    candidates = [text]
    if not text.startswith(("doc_tool/", "scripts/", "docs/", "openspec/", "packaging/", "examples/")):
        candidates += [
            "scripts/tests/" + text,
            "docs/" + text,
            "packaging/" + text,
            "doc_tool/" + text,      # 台账里常按 doc_tool 内相对路径书写（application/ui/domain/...）
            "doc_tool/application/" + text,
        ]
    for candidate in candidates:
        if (REPO_ROOT / candidate).is_file():
            return candidate
    name = Path(text).name
    matches = index.get(name) or []
    if len(matches) == 1:
        return matches[0]
    return None


def _openspec(args) -> subprocess.CompletedProcess:
    found = shutil.which("openspec") or shutil.which("openspec.cmd")
    cmd = [found, *args] if found else ["cmd", "/c", "openspec", *args]
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> int:
    index = _file_index()
    failures: list = []
    warnings: list = []
    lines = ["# 证据/台账一致性核对", "",
             "由 `scripts/tests/check_evidence_consistency.py` 生成。", ""]
    registered = (REPO_ROOT / "scripts" / "tests" / "run_tests.py").read_text(encoding="utf-8")

    # 当前态文档（交接说明/准备度/最终报告）必须引用**最新**证据文件与最新测试文件数，
    # 避免出现“文档说 1 项失败、实际已全绿”这类漂移。
    registered_count = len(re.findall(r'"(test_[A-Za-z0-9_]+\.py)"', registered))
    junit_candidates = sorted(REPO_ROOT.glob("test-results-full-v3-r*.xml"))
    latest_junit = junit_candidates[-1].name if junit_candidates else ""
    current_docs = (
        REPO_ROOT / "docs" / "product-v3-handoff.md",
        REPO_ROOT / "docs" / "product-v3-release-readiness.md",
        REPO_ROOT / "docs" / "product-v3-final-report.md",
    )
    for doc in current_docs:
        if not doc.is_file():
            failures.append("缺少当前态文档：{0}".format(doc.name))
            continue
        body = doc.read_text(encoding="utf-8")
        if latest_junit and latest_junit not in body:
            failures.append("{0}: 未引用最新证据 {1}".format(doc.name, latest_junit))
        if "{0} 个测试文件".format(registered_count) not in body                 and "{0} 文件".format(registered_count) not in body:
            failures.append(
                "{0}: 未写明最新测试文件数（应为 {1}）".format(doc.name, registered_count)
            )
    lines.append("## 当前态文档一致性")
    lines.append("- 最新证据：{0}；注册测试文件数：{1}".format(latest_junit or "（无）", registered_count))
    lines.append("")

    for change, label, ledger_rel in CHANGES:
        base = REPO_ROOT / "openspec" / "changes" / change
        lines.append("## {0}（`{1}`）".format(label, change))
        for name in ("proposal.md", "design.md", "tasks.md"):
            if not (base / name).is_file():
                failures.append("{0}: 缺少 {1}".format(change, name))
        if not (base / "specs").is_dir():
            failures.append("{0}: 缺少 specs/".format(change))
        proc = _openspec(["validate", change, "--strict"])
        ok = proc.returncode == 0
        lines.append("- 严格校验：{0}".format("valid" if ok else "INVALID"))
        if not ok:
            failures.append("{0}: validate --strict 未通过".format(change))

        tasks_text = (base / "tasks.md").read_text(encoding="utf-8")
        done = len(re.findall(r"- \[x\] ", tasks_text))
        todo = re.findall(r"- \[ \] (\d+\.\d+)", tasks_text)
        lines.append("- 勾选 {0} 项；剩余：{1}".format(done, ", ".join(todo) or "—"))

        readiness = REPO_ROOT / "docs" / "product-v3-release-readiness.md"
        if readiness.is_file():
            row = next((line for line in readiness.read_text(encoding="utf-8").splitlines()
                        if "`{0}`".format(change) in line), "")
            if row and ("| {0} |".format(done) not in row):
                failures.append("{0}: 准备度报告勾选数与 tasks.md 不一致（报告行为 {1}）".format(change, row.strip()))
            if row and todo:
                for task_id in todo:
                    if task_id not in row:
                        failures.append("{0}: 准备度报告缺少剩余任务 {1}".format(change, task_id))

        ledger = REPO_ROOT / ledger_rel
        if not ledger.is_file() or len(ledger.read_text(encoding="utf-8").strip()) < 200:
            failures.append("{0}: 执行台账缺失或过短（{1}）".format(change, ledger_rel))
        else:
            lines.append("- 执行台账：`{0}`（{1} 字节）".format(ledger_rel, ledger.stat().st_size))

        sources = [tasks_text]
        if ledger.is_file():
            sources.append(ledger.read_text(encoding="utf-8"))
        refs = set()
        for text in sources:
            for match in PATH_PATTERN.findall(text):
                resolved = _resolve(match, index)
                if resolved:
                    refs.add((match, resolved))
                elif match.endswith(KNOWN_SUFFIXES) and "/" in match.replace("\\", "/"):
                    normalized = match.replace("\\", "/")
                    if normalized.startswith(RUNTIME_PREFIXES) or normalized.startswith("/"):
                        continue  # 运行期/项目内路径，非仓库证据文件
                    refs.add((match, None))
        missing = sorted({raw for raw, resolved in refs if resolved is None})
        for raw in missing:
            failures.append("{0}: 证据引用的文件不存在：{1}".format(change, raw))
        test_refs = sorted({resolved for _raw, resolved in refs if resolved and Path(resolved).name.startswith("test_") and resolved.endswith(".py")})
        for rel in test_refs:
            if Path(rel).name not in registered:
                warnings.append("{0}: 测试文件未注册进 run_tests.py 默认清单：{1}".format(change, rel))
        lines.append("- 证据文件引用 {0} 条（解析成功 {1} 条）".format(len(refs), len(refs) - len(missing)))
        lines.append("")

    lines += ["## 汇总", "",
              "- 失败项：{0}".format(len(failures)), "- 提醒项：{0}".format(len(warnings)), ""]
    for item in failures:
        lines.append("- [失败] " + item)
    for item in warnings:
        lines.append("- [提醒] " + item)
    report = REPO_ROOT / "docs" / "product-v3-evidence-check.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", report.relative_to(REPO_ROOT))
    print("failures:", len(failures), "warnings:", len(warnings))
    for item in failures:
        print("  FAIL", item)
    for item in warnings:
        print("  WARN", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())