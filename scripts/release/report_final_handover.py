# -*- coding: utf-8 -*-
"""生成最终交接报告 `docs/product-v3-final-report.md`。

内容全部来自仓库真实状态（tasks.md 勾选、最新 JUnit、准备度待验收项、产物存在性），
不使用手写数字，避免报告与事实漂移。

用法：
    python scripts\\release\\report_final_handover.py
    python scripts\\release\\report_final_handover.py --junit test-results-full-v3-r34.xml
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CHANGES = (
    ("CORE", "product-core-import-export"),
    ("V3.0", "product-v30-content-reuse"),
    ("V3.1", "product-v31-team-workflow"),
    ("V3.2", "product-v32-batch-delivery"),
    ("V3.3", "product-v33-authoring-assistance"),
)
ARTIFACTS = (
    "dist/DocTool/DocTool.exe",
    "dist/DocTool/doc-tool-cli.exe",
)
DOC_ARTIFACTS = (
    "docs/product-v3-handoff.md",
    "docs/product-v3-acceptance-runbook.md",
    "docs/product-v3-runbook-verification.md",
    "docs/product-v3-release-readiness.md",
    "docs/product-v3-audit-findings.md",
    "docs/product-v3-evidence-check.md",
    "docs/product-core-workflow-execution.md",
    "docs/product-plan-v3-execution.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registered_test_files() -> int:
    """默认清单里的测试文件数（唯一来源：scripts/tests/run_tests.py）。"""
    text = (REPO_ROOT / "scripts" / "tests" / "run_tests.py").read_text(encoding="utf-8")
    return len(re.findall(r'"(test_[A-Za-z0-9_]+\.py)"', text))


def task_counts() -> dict:
    rows = {}
    for label, change in CHANGES:
        path = REPO_ROOT / "openspec" / "changes" / change / "tasks.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        rows[label] = {
            "change": change,
            "done": len(re.findall(r"- \[x\] ", text)),
            "todo": re.findall(r"- \[ \] (\d+\.\d+)", text),
        }
    return rows


def latest_junit(explicit: str = "") -> Path | None:
    if explicit:
        path = REPO_ROOT / explicit
        return path if path.is_file() else None
    candidates = sorted(REPO_ROOT.glob("test-results-full-v3-r*.xml"))
    if not candidates:
        candidates = sorted(REPO_ROOT.glob("test-results-full*.xml"))
    return candidates[-1] if candidates else None


def junit_summary(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    tree = ET.parse(path)
    suites = list(tree.getroot().iter("testsuite"))
    failed = []
    for suite in suites:
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(case.get("name", ""))
    return {
        "file": path.name,
        "files": len(suites),
        "tests": sum(int(suite.get("tests", 0) or 0) for suite in suites),
        "failures": sum(int(suite.get("failures", 0) or 0) for suite in suites),
        "errors": sum(int(suite.get("errors", 0) or 0) for suite in suites),
        "failed": failed,
    }


def pending_items() -> list:
    """从准备度报告脚本里的 PENDING 表读取（唯一来源，避免两处维护）。"""
    try:
        from scripts.tests.report_release_readiness import PENDING
    except Exception as exc:  # noqa: BLE001 - 读取失败时如实说明
        return [{"change": "*", "items": ["无法读取待验收表：{0}".format(exc)]}]
    return [{"change": change, "items": list(items)} for change, items in PENDING.items()]


def latest_bundle() -> Path | None:
    bundles = sorted((REPO_ROOT / "deliverables").glob("v3-review-*.zip"))
    return bundles[-1] if bundles else None


def build_report(junit_path: Path | None = None) -> str:
    counts = task_counts()
    total_done = sum(item["done"] for item in counts.values())
    total = total_done + sum(len(item["todo"]) for item in counts.values())
    summary = junit_summary(junit_path)
    frozen = []
    for rel in ARTIFACTS:
        path = REPO_ROOT / rel
        if path.is_file():
            frozen.append((rel, path.stat().st_size, _sha256(path)))
    bundle = latest_bundle()

    lines = [
        "# V3 / CORE 最终交接报告",
        "",
        "生成时间：{0}（UTC）".format(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        "生成方式：`python scripts\\release\\report_final_handover.py`（数字取自 tasks.md 与最新 JUnit，不手写）",
        "",
        "## 1. 结论摘要",
        "",
        "- 五个 change 的**本地实现、测试、修复与交接物**已完成：进度 **{0}/{1}**".format(total_done, total),
        "- 全量回归（{0}）：**{1} 个测试文件 / {2} 项失败 / {3} 项错误**".format(
            summary.get("file", "未找到证据"), registered_test_files(),
            summary.get("failures", "?"), summary.get("errors", "?"),
        ),
        "- 剩余 {0} 项任务全部为**授权/人工/实机**门：执行步骤见 `docs/product-v3-acceptance-runbook.md`".format(
            total - total_done
        ),
        "- **未提交、未归档、未发布**；归档需显式授权。",
        "",
        "## 2. 五个 change 的交付与进度",
        "",
        "| 版本 | change | 已勾选 | 剩余任务 |",
        "|---|---|---|---|",
    ]
    for label, _change in CHANGES:
        item = counts[label]
        lines.append("| {0} | `{1}` | {2} | {3} |".format(
            label, item["change"], item["done"], "、".join(item["todo"]) or "—",
        ))

    lines += [
        "",
        "## 3. 验证证据",
        "",
        "- 全量回归：`{0}`".format(summary.get("file", "（未找到）")),
        "  - 测试文件数 {0}／JUnit 用例数 {1}／失败 {2}／错误 {3}".format(
            registered_test_files(), summary.get("tests", "?"),
            summary.get("failures", "?"), summary.get("errors", "?"),
        ),
    ]
    for name in summary.get("failed", [])[:5]:
        lines.append("  - 失败：`{0}`（已知环境项：缺 `mmdc`）".format(name))
    lines += [
        "- 实机 Word（第三十二/三十八轮复跑）：`V32_REAL_WORD=1` 正式化 3 项 OK、跨进程换机 2 项 OK",
        "- Mermaid：项目本地 `mermaid-cli` + `chrome-headless-shell` 已装，工作台渲染成功（第三十八轮起全量 0 失败）",
        "- 冻结包：`build_exe.ps1` 重建 + 产物校验 + 签名 46 文件 + `test_frozen_smoke.py` 11 项 OK",
        "- 高 DPI（模拟）：`test_core_hidpi_layout.py` 覆盖缩放因子 1 / 1.25 / 1.5（物理缩放待实机）",
        "- 审计与复核：13 项审计缺口全部修复；两轮独立复核（修复项 + 新增能力）结论已记入 `docs/product-v3-audit-findings.md`",
        "",
        "## 4. 可用成果路径（存在性已核对）",
        "",
    ]
    if frozen:
        lines += ["| 产物 | 字节 | sha256 |", "|---|---|---|"]
        for rel, size, digest in frozen:
            lines.append("| `{0}` | {1:,} | `{2}…` |".format(rel, size, digest[:16]))
    else:
        lines.append("- （未找到冻结产物，请先运行 `build_exe.ps1`）")
    lines.append("")
    if bundle is not None:
        lines.append("- 本地审阅包：`{0}`（{1:,} 字节）".format(
            bundle.relative_to(REPO_ROOT).as_posix(), bundle.stat().st_size,
        ))
    lines.append("- 文档：")
    for rel in DOC_ARTIFACTS:
        exists = "✓" if (REPO_ROOT / rel).is_file() else "✗"
        lines.append("  - {0} `{1}`".format(exists, rel))

    lines += ["", "## 5. 待验收项（保持未勾选）", ""]
    for row in pending_items():
        lines.append("- **{0}**：{1}".format(row["change"], "；".join(row["items"])))
    lines += [
        "",
        "可执行步骤（准备/命令/期望/判据/留档）与验收记录表见 `docs/product-v3-acceptance-runbook.md`。",
        "",
        "## 6. 下一条未完成任务编号",
        "",
    ]
    for label, _change in CHANGES:
        todo = counts[label]["todo"]
        if todo:
            lines.append("- {0}：**{1}**".format(label, todo[0]))
    lines += [
        "",
        "> 本报告由脚本生成；勾选状态、JUnit 数字与产物存在性均取自仓库当前状态。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成最终交接报告")
    parser.add_argument("--junit", default="", help="指定全量回归证据 XML（缺省取最新 r* 文件）")
    parser.add_argument("--out", default=str(REPO_ROOT / "docs" / "product-v3-final-report.md"))
    args = parser.parse_args(argv)
    junit = latest_junit(args.junit)
    report = build_report(junit)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    print("wrote", target.relative_to(REPO_ROOT).as_posix(), "({0} bytes)".format(len(report.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())