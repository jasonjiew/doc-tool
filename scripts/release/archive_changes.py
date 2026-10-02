# -*- coding: utf-8 -*-
"""同步/归档执行器（默认 dry-run）：五个 change 的归档前置核对与一键执行（V3/CORE 收尾）。

安全约定：
- 默认只做核对与打印（``--dry-run`` 为默认），**不改动仓库**；
- 只有显式 ``--yes`` 才调用 ``openspec archive <change> --yes``；
- 执行前逐个跑 ``openspec validate --strict``，任一失败即中止；
- 执行前打印每个 change 的剩余未勾选任务（提醒人工确认是否已获授权）。

用法：
    python scripts\\release\\archive_changes.py               # 核对 + 打印计划
    python scripts\\release\\archive_changes.py --yes         # 真正归档（需用户授权）
    python scripts\\release\\archive_changes.py --json        # 机器可读结果
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGES = (
    "product-core-import-export",
    "product-v30-content-reuse",
    "product-v31-team-workflow",
    "product-v32-batch-delivery",
    "product-v33-authoring-assistance",
)


def _openspec(args):
    found = shutil.which("openspec") or shutil.which("openspec.cmd")
    command = [found, *args] if found else ["cmd", "/c", "openspec", *args]
    return subprocess.run(
        command, cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _remaining_tasks(change: str) -> list:
    path = REPO_ROOT / "openspec" / "changes" / change / "tasks.md"
    if not path.is_file():
        return ["tasks.md 缺失"]
    text = path.read_text(encoding="utf-8")
    return re.findall(r"- \[ \] (\d+\.\d+)", text)


def plan(*, validate: bool = True) -> dict:
    rows = []
    ok = True
    for change in CHANGES:
        entry = {"change": change, "remaining": _remaining_tasks(change), "valid": None, "archived": False}
        change_dir = REPO_ROOT / "openspec" / "changes" / change
        entry["exists"] = change_dir.is_dir()
        if validate and entry["exists"]:
            proc = _openspec(["validate", change, "--strict"])
            entry["valid"] = proc.returncode == 0
            if not entry["valid"]:
                ok = False
                entry["message"] = (proc.stdout or proc.stderr or "").strip()[-200:]
        rows.append(entry)
    return {"ok": ok, "dryRun": True, "changes": rows}


def execute(*, json_output: bool = False) -> int:
    import json as _json

    payload = plan()
    if not payload["ok"]:
        print("存在未通过严格校验的 change，已中止归档。", file=sys.stderr)
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    results = []
    for entry in payload["changes"]:
        change = entry["change"]
        proc = _openspec(["archive", change, "--yes"])
        results.append({
            "change": change,
            "returncode": proc.returncode,
            "output": (proc.stdout or proc.stderr or "").strip()[-300:],
            "archived": (REPO_ROOT / "openspec" / "changes" / "archive" / change).is_dir(),
        })
    listing = _openspec(["list"])
    after = _openspec(["validate", "--strict"])
    payload = {
        "ok": all(item["returncode"] == 0 for item in results),
        "dryRun": False,
        "results": results,
        "list": (listing.stdout or listing.stderr or "").strip()[-500:],
        "validateAll": after.returncode == 0,
    }
    if json_output:
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print("{0}: exit={1} archived={2}".format(item["change"], item["returncode"], item["archived"]))
        print("openspec list/validate 复核：", payload["validateAll"])
    return 0 if payload["ok"] and payload["validateAll"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="五个 change 的归档前置核对与执行（默认 dry-run）")
    parser.add_argument("--yes", action="store_true", help="真正执行归档（需用户授权）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)

    if not args.yes:
        payload = plan()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("归档前置核对（dry-run，未改动仓库）")
            for entry in payload["changes"]:
                print("· {0}：严格校验={1}，剩余任务={2}".format(
                    entry["change"],
                    "valid" if entry["valid"] else ("INVALID" if entry["valid"] is False else "跳过"),
                    "、".join(entry["remaining"]) or "无",
                ))
            print("授权后执行：python scripts\\release\\archive_changes.py --yes")
        return 0 if payload["ok"] else 2
    return execute(json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())