# -*- coding: utf-8 -*-
"""把分块并行运行的 stdout 日志回放成 report.json（保留真实退出码与计数）。

并行版在开始写 JSON 前被中断时，日志里逐行的 ``[i/N] file rc=.. Xs {counts}``
就是真实结果。本脚本按同一口径重建报告，避免丢掉已完成的覆盖。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

LINE_RE = re.compile(
    r"^\[(?P<index>\d+)/(?P<total>\d+)\]\s+(?P<file>\S+)\s+rc=(?P<rc>-?\d+)\s+"
    r"(?P<seconds>[\d.]+)s\s+(?P<counts>\{.*\})\s*$"
)


def main() -> int:
    log = Path(sys.argv[1])
    out = Path(sys.argv[2])
    entries = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        try:
            counts = ast.literal_eval(match.group("counts"))
        except Exception:
            counts = {}
        entries.append({
            "file": match.group("file"),
            "returncode": int(match.group("rc")),
            "seconds": float(match.group("seconds")),
            "counts": counts,
            "timedOut": int(match.group("rc")) == -1,
            "tail": "",
        })
    totals = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for entry in entries:
        for key in totals:
            totals[key] += int(entry["counts"].get(key, 0))
    report = {
        "generatedAt": "replayed-from-log",
        "source": str(log),
        "files": entries,
        "totals": totals,
        "failedFiles": [e["file"] for e in entries if e["returncode"] != 0 and not e["timedOut"]],
        "timedOutFiles": [e["file"] for e in entries if e["timedOut"]],
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("entries", len(entries), "totals", totals,
          "failed", len(report["failedFiles"]), "timeout", len(report["timedOutFiles"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())