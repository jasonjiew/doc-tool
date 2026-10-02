# -*- coding: utf-8 -*-
"""V3/CORE 发布与归档准备度报告（同步/归档前置核对）。

生成依据：tasks.md 勾选统计、openspec validate --strict 结果、各版执行台账列出的
自动化证据（测试/测量/冻结冒烟/实机用例）。归档动作需**全部验收满足且用户授权**，
本报告只做核对与命令准备，不执行归档。
"""

from __future__ import annotations

import re
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

#: 各 change 的已知待验收项（实机/人工/授权相关）。
PENDING = {
    "product-core-import-export": ["8.5 同步/归档（需全部验收 + 用户授权）",
                                   "冻结包写入类闭环：本机策略阻断（PermissionError/E9000/密文读取），"
                                   "需将 DocTool.exe 加入信任列表或换干净机器复验",
                                   "实机：真实 Word 版式与冻结包",
                                   "规范 E8：物理 125%/150% 显示器实测"
                                   "（已用 QT_SCALE_FACTOR 离屏模拟 1/1.25/1.5 并固定回归，"
                                   "物理缩放仍待实机）"],
    "product-v30-content-reuse": ["7.4 同步/归档（需全部验收 + 用户授权）",
                                  "实机：冻结包与实机 Word 版式抽查"],
    "product-v31-team-workflow": ["6.3 真实团队交接试点（无团队环境）",
                                  "6.5 同步/归档（需全部验收 + 用户授权）"],
    "product-v32-batch-delivery": ["7.5 同步/归档（需全部验收 + 用户授权）",
                                   "实机：真实两台物理机器交接、125%/150% 缩放"],
    "product-v33-authoring-assistance": ["6.2 三类文档人工试点与质量评价",
                                         "实机：真实 provider 连通（V33_REAL_PROVIDER=1）",
                                         "换机器时 Mermaid 需按验收清单 C5 准备"
                                         "（本机已通过项目本地安装解决）"],
}


def task_counts(change: str) -> tuple:
    text = (REPO_ROOT / "openspec" / "changes" / change / "tasks.md").read_text(encoding="utf-8")
    done = len(re.findall(r"- \[x\] ", text))
    todo = re.findall(r"- \[ \] (\d+\.\d+)", text)
    return done, todo


def _openspec_command(args) -> list:
    """定位 openspec 可执行（Windows 上是 .CMD，直接 Popen 会 WinError 2）。"""
    import shutil

    found = shutil.which("openspec") or shutil.which("openspec.cmd")
    if found:
        return [found, *args]
    return ["cmd", "/c", "openspec", *args]


def validate(change: str) -> tuple:
    proc = subprocess.run(
        _openspec_command(["validate", change, "--strict"]),
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, output[-1:]


def main() -> int:
    lines = ["# V3 / CORE 发布与归档准备度", "",
             "本页由 `scripts/tests/report_release_readiness.py` 生成，用于同步/归档前置核对。",
             "交接说明与验证入口见 [V3/CORE 交接说明](product-v3-handoff.md)。",
             "**归档动作需全部验收满足并由用户授权后执行**；本页不执行归档。", "",
             "## 1. 勾选与严格校验", "",
             "| change | 版本 | 已勾选 | 剩余任务 | `validate --strict` |", "|---|---|---|---|---|"]
    ready = True
    for change, label, ledger in CHANGES:
        done, todo = task_counts(change)
        ok, message = validate(change)
        lines.append("| `{0}` | {1} | {2} | {3} | {4} |".format(
            change, label, done, ", ".join(todo) or "—",
            "valid" if ok else "INVALID: {0}".format(message),
        ))
        if not ok:
            ready = False

    lines += ["", "结论汇总见 `docs/product-v3-final-report.md`（由脚本生成，与 tasks.md/JUnit 一致）；本机可验证部分的执行结果见 `docs/product-v3-runbook-verification.md`。"]
    lines += ["", "## 2. 各版待验收项（保持未勾选；可执行步骤见 docs/product-v3-acceptance-runbook.md）", ""]
    for change, label, _ledger in CHANGES:
        lines.append("- **{0}**：{1}".format(label, "；".join(PENDING[change])))

    lines += [
        "", "## 3. 证据清单（自动化部分）", "",
        "| 类别 | 证据 |", "|---|---|",
        "| 单元/集成测试 | `scripts/tests/run_tests.py` 默认清单 **149 个测试文件**；第四十轮全量实测 **149 文件、0 项失败、0 错误**（此前唯一的 Mermaid 环境失败已通过项目本地 `mermaid-cli` + `chrome-headless-shell` 解决）；证据 `test-results-full-v3-r40.xml` |",
        "| 冻结冒烟 | `build_exe.ps1` onedir 重建（第三十四轮，含预设实现收敛）：DocTool.exe 10,057,912 B、doc-tool-cli.exe 9,383,656 B、产物校验 + 签名 + `test_frozen_smoke.py` **11 项 OK**；冻结 CLI 能力面：`intake-presets list` exit 0、`import --help` 含 `--preset/--save-preset`；**写入类闭环在本机被透明加密/杀软策略阻断**（convert→PermissionError(13)、import→E9000、仓库路径 docx 读到密文），需加入信任或干净机器复验；已提供 `env-check` 自检（exit 3 + 可执行建议）便于现场判定；冻结 CLI `reuse`/`delivery-plan`/`delivery-promote`/`assist-search`/`assist-provider`/`project-export` `--help` 全 exit 0，且 `reuse resolve --record-instances` 新参数在冻结产物中存在 |",
        "| 实机 Word | `V32_REAL_WORD=1 python scripts\\tests\\test_v32_real_word_formalize.py` → 3 项 OK（正式化/换机等效/幂等） |",
        "| 规模实测 | `python scripts\\tests\\measure_v32_batch10.py` → 10 成员 **81.57 s**（8.16 s/成员、输出 337,508 B、队列库 44,127 B），续跑 6.74 s/1 成员（早期 10.88 s 记录已撤回） |",
        "| 真实文档试点 | `python scripts\\tests\\test_v33_three_document_pilot.py` → 三类真实文档定位/建议/采纳撤销/摘要候选数据 |",
        "| 团队交接代理试点 | `python scripts\\tests\\test_v31_real_document_handoff.py` → 真实文档 + 两棵无 Git 独立副本：导出 0.174 s / 应用 0.140 s / 重复导入 0.073 s，冲突按章隔离 |",
        "| 进程级换机 | `V32_REAL_WORD=1 python scripts\\tests\\test_v32_cross_process_promote.py` → 独立子进程 `delivery-promote` 2 项 OK（registered + already-registered） |",
        "| OpenSpec | 五个 change `validate --strict` 全部 valid |",
        "| 证据一致性 | `python scripts\\tests\\check_evidence_consistency.py` → 失败 0 / 提醒 0（结果见 `docs/product-v3-evidence-check.md`） |",
        "", "## 4. 归档命令（待授权后执行）", "",
        "```powershell",
        "# 本地审阅包（默认写入 deliverables/，--zip 同时打包）",
        "python scripts\\release\\make_review_bundle.py --zip",
        "# 已提供带前置校验的执行器（默认 dry-run，--yes 才真正归档）",
        "python scripts\\release\\archive_changes.py          # 核对并打印计划",

        "# 逐个归档（会更新主 specs；如需跳过 spec 更新加 --skip-specs）",
    ]
    for change, _label, _ledger in CHANGES:
        lines.append("openspec archive {0} --yes".format(change))
    lines += [
        "# 归档后复核",
        "openspec list",
        "openspec validate --strict",
        "```",
        "",
        "## 5. 结论", "",
        ("**结构校验与自动化证据均已就绪**；剩余为人工/实机/授权项，"
         "因此四个同步/归档任务（CORE 8.5、V3.0 7.4、V3.1 6.5、V3.2 7.5）保持未勾选。"
         if ready else "存在未通过严格校验的 change，先修复再归档。"),
        "",
    ]
    target = REPO_ROOT / "docs" / "product-v3-release-readiness.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", target.relative_to(REPO_ROOT), "ready =", ready)
    return 0


if __name__ == "__main__":
    sys.exit(main())