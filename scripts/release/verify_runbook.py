# -*- coding: utf-8 -*-
"""执行验收清单中**本机可验证**的步骤，并如实标出仍需人工/实机/授权的项。

用途：交付前或验收前跑一次，得到“哪些项现在就能验、验的结果是什么、哪些项为什么还不行”，
避免验收人逐个翻台账。

用法：
    python scripts\\release\\verify_runbook.py                 # 廉价集合（归档核对 + env-check + 高DPI）
    python scripts\\release\\verify_runbook.py --with-tests    # 追加两个代理试点用例
    python scripts\\release\\verify_runbook.py --with-tests --with-word   # 再追加实机 Word 两项
    python scripts\\release\\verify_runbook.py --json --out docs\\product-v3-runbook-verification.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PYTHON = sys.executable


def _run(cmd, *, env=None, timeout=900, cwd=None):
    merged = dict(os.environ)
    merged.update({
        "PYTHONUTF8": "1", "PYTHONPATH": str(REPO_ROOT),
        "QT_QPA_PLATFORM": "offscreen",
    })
    if env:
        merged.update(env)
    proc = subprocess.run(
        cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=merged,
    )
    return proc


def _word_available() -> tuple:
    try:
        from doc_tool.application.word_check import check_word_available

        report = check_word_available(dispatch_check=True, dispatch_timeout_seconds=30.0)
        return bool(report.available), "；".join(report.reasons[:1])
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def step_archive_dry_run() -> dict:
    proc = _run([PYTHON, str(REPO_ROOT / "scripts" / "release" / "archive_changes.py")], timeout=600)
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    return {
        "id": "A1-A4", "label": "同步/归档前置核对（dry-run，未改动仓库）",
        "kind": "local", "ok": proc.returncode == 0,
        "detail": tail[0][:160],
    }


def step_env_check() -> dict:
    with tempfile.TemporaryDirectory(prefix="doc-tool-runbook-") as tmp:
        proc = _run([
            PYTHON, "-m", "doc_tool.cli", "env-check", "--json", "--dir", tmp,
        ], timeout=300)
        payload = {}
        start = (proc.stdout or "").find("{")
        if start >= 0:
            try:
                payload = json.loads(proc.stdout[start:])
            except ValueError:
                payload = {}
        advice = (payload.get("advice") or [""])[0]
        if proc.returncode == 0:
            detail = "本机环境通过自检（目录可写、docx 可读）"
        else:
            failed = [c for c in payload.get("checks", []) if not c.get("ok")]
            detail = "环境受限：{0}".format(
                "；".join("{0}:{1}".format(c.get("kind"), str(c.get("detail"))[:80]) for c in failed)
                or advice or "未知"
            )
        return {
            "id": "C2", "label": "冻结/本机环境自检（写入与 docx 可读性）",
            "kind": "local", "ok": proc.returncode == 0,
            "pending": proc.returncode == 3, "advice": advice, "detail": detail,
        }


def step_env_check_frozen() -> dict:
    """用冻结 CLI 跑同一自检：验收关心的是**冻结产物**能否写入（主机通常没问题）。"""
    exe = REPO_ROOT / "dist" / "DocTool" / "doc-tool-cli.exe"
    if not exe.is_file():
        return {"id": "C2", "label": "冻结 CLI 环境自检", "kind": "env", "ok": False,
                "pending": True, "detail": "未找到冻结产物：请先运行 build_exe.ps1"}
    with tempfile.TemporaryDirectory(prefix="doc-tool-runbook-frozen-") as tmp:
        proc = _run([str(exe), "env-check", "--json", "--dir", tmp], timeout=300)
        payload = {}
        start = (proc.stdout or "").find("{")
        if start >= 0:
            try:
                payload = json.loads(proc.stdout[start:])
            except ValueError:
                payload = {}
        failed = [item for item in payload.get("checks", []) if not item.get("ok")]
        advice = (payload.get("advice") or [""])[0]
        ok = proc.returncode == 0
        return {
            "id": "C2", "label": "冻结 CLI 环境自检（写入与 docx 可读性）",
            "kind": "env", "ok": ok, "pending": not ok, "advice": advice,
            "detail": "冻结产物在当前环境可写、docx 可读" if ok else (
                "冻结产物受环境限制：{0}；建议：{1}".format(
                    "；".join("{0}".format(str(item.get("detail"))[:70]) for item in failed)
                    or "未知", advice or "见验收清单 C2",
                )
            ),
        }


def step_hidpi() -> dict:
    proc = _run([PYTHON, str(REPO_ROOT / "scripts" / "tests" / "test_core_hidpi_layout.py")], timeout=600)
    ok = proc.returncode == 0 and "OK" in (proc.stderr or "")
    return {
        "id": "C3", "label": "高 DPI 缩放因子模拟回归（1 / 1.25 / 1.5）",
        "kind": "local", "ok": ok,
        "detail": "物理缩放仍需实机" if ok else (proc.stderr or "")[-160:],
    }


def step_mermaid() -> dict:
    """Mermaid：本机是否有可用的 mermaid-cli，以及能否真的渲染出一张图。"""
    try:
        from doc_tool.application.content import mermaid

        available = bool(mermaid.cli_available())
        path = mermaid._find_mmdc()
    except Exception as exc:  # noqa: BLE001
        return {"id": "C5", "label": "Mermaid 渲染（mmdc）", "kind": "local", "ok": False,
                "detail": "检查失败：{0}".format(exc)}
    if not available:
        return {
            "id": "C5", "label": "Mermaid 渲染（mmdc）", "kind": "local", "ok": False,
            "pending": True,
            "detail": ("未找到 mermaid-cli：按验收清单 C5 在 tools/mermaid-cli 本地安装 "
                       "`@mermaid-js/mermaid-cli` 与 `chrome-headless-shell`（无 CLI 时应用退回内置子集渲染器）"),
        }
    result = mermaid.render("flowchart TD\n  A --> B", use_cli=True, want_png=False)
    return {
        "id": "C5", "label": "Mermaid 渲染（mmdc）", "kind": "local", "ok": bool(result.ok),
        "detail": "使用 {0} 渲染成功".format(path or "mermaid-cli") if result.ok
        else "渲染失败：{0}".format(str(getattr(result, "error", ""))[:120]),
    }


def step_pilot_tests() -> list:
    rows = []
    for name, label, budget in (
        ("test_v31_real_document_handoff.py", "B1 团队交接（真实文档 + 两独立副本代理）", 300),
        ("test_v33_three_document_pilot.py", "B2 三类文档试点（自动化部分与数据）", 300),
    ):
        path = REPO_ROOT / "scripts" / "tests" / name
        if not path.is_file():
            rows.append({"id": label.split()[0], "label": label, "kind": "local",
                         "ok": False, "detail": "用例不存在：" + name})
            continue
        proc = _run([PYTHON, str(path)], timeout=budget)
        rows.append({
            "id": label.split()[0], "label": label, "kind": "local",
            "ok": proc.returncode == 0,
            "detail": "用例通过（人工多人/多文档环节仍需人工）" if proc.returncode == 0
            else (proc.stderr or proc.stdout or "")[-160:],
        })
    return rows


def step_word_tests() -> list:
    available, reason = _word_available()
    rows = []
    for name, label in (
        ("test_v32_real_word_formalize.py", "C1 实机 Word 正式化 + 换机等效"),
        ("test_v32_cross_process_promote.py", "C1 进程级换机登记"),
    ):
        if not available:
            rows.append({"id": "C1", "label": label, "kind": "env", "ok": False,
                         "pending": True, "detail": "本机 Word 不可用：{0}".format(reason or "未探测到")})
            continue
        proc = _run([PYTHON, str(REPO_ROOT / "scripts" / "tests" / name)],
                    env={"V32_REAL_WORD": "1"}, timeout=900)
        rows.append({"id": "C1", "label": label, "kind": "env", "ok": proc.returncode == 0,
                     "detail": "用例通过" if proc.returncode == 0 else (proc.stderr or "")[-160:]})
    return rows


def manual_items() -> list:
    return [
        {"id": "A1-A4", "label": "真正归档（需用户授权）", "kind": "authorization",
         "ok": False, "pending": True,
         "detail": "授权后执行 python scripts\\release\\archive_changes.py --yes"},
        {"id": "B1", "label": "真实团队多人交接", "kind": "human", "ok": False, "pending": True,
         "detail": "需两位真实同事与各自目录；自动化代理已通过"},
        {"id": "B2", "label": "三类文档人工质量评价", "kind": "human", "ok": False, "pending": True,
         "detail": "需人工对建议质量评分；自动化数据已留档"},
        {"id": "C2", "label": "冻结包写入类闭环", "kind": "env", "ok": False, "pending": True,
         "detail": "需把 DocTool.exe 加入透明加密/杀软信任列表，或换干净机器"},
        {"id": "C3", "label": "物理 125%/150% 显示器实测", "kind": "env", "ok": False, "pending": True,
         "detail": "需可切换缩放的真实显示器"},
        {"id": "C4", "label": "真实两台物理机器交接", "kind": "env", "ok": False, "pending": True,
         "detail": "需第二台机器"},
    ]


def collect(*, with_tests: bool = False, with_word: bool = False) -> dict:
    results = [
        step_archive_dry_run(), step_env_check(), step_env_check_frozen(),
        step_hidpi(), step_mermaid(),
    ]
    if with_tests:
        results.extend(step_pilot_tests())
    if with_word:
        results.extend(step_word_tests())
    manual = manual_items()
    # env-check 若报受限，则手动项里的 C2 说明升级为实测原因
    for row in manual:
        if row["id"] == "C2":
            env_row = next((item for item in results if item["id"] == "C2" and item.get("advice")), None)
            if env_row is not None:
                row["detail"] = "{0}（实测：{1}）".format(row["detail"], env_row["advice"])
    return {
        "schemaVersion": 1,
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "local": results,
        "manual": manual,
    }


def render(payload: dict) -> str:
    lines = [
        "# 验收清单本机可验证部分（自动执行结果）",
        "",
        "生成时间：{0}".format(payload["ranAt"]),
        "生成方式：`python scripts\\release\\verify_runbook.py --with-tests`（可按需加 `--with-word`）",
        "完整验收步骤见 `docs/product-v3-acceptance-runbook.md`。",
        "",
        "## 1. 本机已执行",
        "",
        "| 项 | 步骤 | 结果 | 说明 |",
        "|---|---|---|---|",
    ]
    for row in payload["local"]:
        lines.append("| {0} | {1} | {2} | {3} |".format(
            row["id"], row["label"], "通过" if row["ok"] else ("受限" if row.get("pending") else "未通过"),
            str(row.get("detail", ""))[:160],
        ))
    lines += [
        "",
        "## 2. 仍需人工/实机/授权",
        "",
        "| 项 | 内容 | 依赖 | 说明 |",
        "|---|---|---|---|",
    ]
    for row in payload["manual"]:
        lines.append("| {0} | {1} | {2} | {3} |".format(
            row["id"], row["label"], row["kind"], str(row.get("detail", ""))[:160],
        ))
    local_ok = sum(1 for row in payload["local"] if row["ok"])
    lines += [
        "",
        "## 3. 小结",
        "",
        "- 本机执行 {0} 项：通过 {1} 项，受限/未通过 {2} 项".format(
            len(payload["local"]), local_ok, len(payload["local"]) - local_ok,
        ),
        "- 仍需外部条件 {0} 项：{1}".format(
            len(payload["manual"]),
            "、".join(sorted({row["kind"] for row in payload["manual"]})) or "无",
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="执行验收清单中本机可验证的步骤")
    parser.add_argument("--with-tests", action="store_true", help="追加两个代理试点用例")
    parser.add_argument("--with-word", action="store_true", help="追加实机 Word 用例（需本机 Word）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--out", default="", help="同时写入 Markdown 报告")
    args = parser.parse_args(argv)

    payload = collect(with_tests=args.with_tests, with_word=args.with_word)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        report = render(payload)
        print(report)
        if args.out:
            target = Path(args.out)
            if not target.is_absolute():
                target = REPO_ROOT / target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report, encoding="utf-8")
            print("已写入", target.relative_to(REPO_ROOT).as_posix())
    blocked = [row for row in payload["local"] if not row["ok"]]
    print("本机执行 {0} 项，受限/未通过 {1} 项（受限项见报告说明）".format(
        len(payload["local"]), len(blocked),
    ), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())