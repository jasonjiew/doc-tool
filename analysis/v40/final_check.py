# -*- coding: utf-8 -*-
"""V4.0～V4.3 收尾核对脚本：本地可判定项一次跑完，外部条件项如实列出。

用法：``python analysis\v40\final_check.py``
退出码：0 = 本地可判定项全部满足；1 = 有本地项不满足（外部项不影响退出码）。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHANGES = (
    "product-v40-runtime-and-word-reliability",
    "product-mainline-usability-and-fidelity",
    "product-v41-enterprise-template-workflows",
    "product-v42-incremental-quality-workbench",
    "product-v43-delivery-and-revision-workbench",
)

#: 外部条件项（未勾选且本机不可判定）。键为 change，值为条目编号。
EXTERNAL = {
    "product-v40-runtime-and-word-reliability": ["5.3"],
    "product-mainline-usability-and-fidelity": ["6.3"],
    "product-v41-enterprise-template-workflows": ["5.3"],
    "product-v42-incremental-quality-workbench": ["5.3"],
    "product-v43-delivery-and-revision-workbench": ["5.3"],
}


def _tick_counts() -> dict:
    counts = {}
    for change in CHANGES:
        text = (REPO / "openspec" / "changes" / change / "tasks.md").read_text(encoding="utf-8")
        counts[change] = (
            len(re.findall(r"(?m)^- \[x\]", text)),
            len(re.findall(r"(?m)^- \[ \]", text)),
        )
    return counts


def _unticked_ids(change: str) -> list:
    text = (REPO / "openspec" / "changes" / change / "tasks.md").read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r"(?m)^- \[ \] ([0-9.]+)", text)]


def _strict_valid(change: str) -> bool:
    proc = subprocess.run(
        ["npx", "--no-install", "openspec", "validate", change, "--strict"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        errors="replace", shell=(sys.platform == "win32"),
    )
    return "is valid" in (proc.stdout or "")


def main() -> int:
    failures: list = []
    print("=== 1. 五包勾选状态 ===")
    counts = _tick_counts()
    total = 0
    for change in CHANGES:
        done, left = counts[change]
        total += done
        print("  {0:<52} {1}/20 未勾 {2}".format(change, done, left))
    print("  合计 {0}/104".format(total))

    print("=== 2. 未勾选项必须全部是外部条件 ===")
    for change in CHANGES:
        unticked = _unticked_ids(change)
        expected = EXTERNAL.get(change, [])
        if unticked != expected:
            failures.append("{0}: 未勾选项 {1} 与外部条件清单 {2} 不一致".format(
                change, unticked, expected,
            ))
        else:
            print("  {0:<52} 未勾 {1}（外部条件，符合）".format(change, unticked or "无"))

    print("=== 3. OpenSpec strict ===")
    for change in CHANGES:
        ok = _strict_valid(change)
        print("  {0:<52} {1}".format(change, "valid" if ok else "INVALID"))
        if not ok:
            failures.append("{0}: strict 校验未通过".format(change))

    print("=== 4. 关键交付文件存在性 ===")
    deliverables = (
        "doc_tool/application/content/quality_workbench.py",
        "doc_tool/application/delivery/preparation.py",
        "doc_tool/application/delivery/revision_compare.py",
        "doc_tool/application/delivery/handover.py",
        "doc_tool/application/content/batch_chapter_ops.py",
        "doc_tool/application/template_sample.py",
        "doc_tool/application/template_library.py",
        "doc_tool/domain/word_operations.py",
        "doc_tool/ui/intake_result_window.py",
        "doc_tool/ui/batch_result_window.py",
        "doc_tool/ui/reimport_preview_window.py",
        "doc_tool/ui/template_library_dialog.py",
        "docs/product-v40-v43-execution.md",
        "docs/product-v40-v43-recheck.md",
    )
    for rel in deliverables:
        exists = (REPO / rel).is_file()
        if not exists:
            failures.append("缺少交付文件：{0}".format(rel))
    print("  {0}/{1} 存在".format(
        sum(1 for rel in deliverables if (REPO / rel).is_file()), len(deliverables),
    ))

    print("=== 5. 性能事实（唯一未达量化目标，如实展示）===")
    measure = REPO / "analysis" / "v42" / "measure-staged.json"
    if measure.is_file():
        data = json.loads(measure.read_text(encoding="utf-8"))
        for tier in data["tiers"]:
            stages = tier["stages"]
            print("  {0:>4} 章：冷 p95 {1:>8.1f}ms → 热 p95 {2:>8.1f}ms（{3:+.1f}%）".format(
                tier["chapters"], stages["coldTotal"]["p95Ms"],
                stages["hotTotal"]["p95Ms"], tier["p95ImprovementPercent"],
            ))
        print("  targets.met30Percent = {0}（未达标，已写入台账的不可达论证）".format(
            data["targets"].get("met30Percent"),
        ))
    else:
        failures.append("缺少 analysis/v42/measure-staged.json")

    print("=== 6. 外部条件项（需真实环境，本机不可判定）===")
    for change, ids in EXTERNAL.items():
        for item in ids:
            print("  {0} {1}".format(change, item))
    print("  复验步骤见 docs/product-v40-v43-recheck.md")

    print()
    if failures:
        print("本地可判定项未全部满足：")
        for line in failures:
            print("  - " + line)
        return 1
    print("本地可判定项全部满足；剩余 5 项均为外部条件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())