# -*- coding: utf-8 -*-
"""按文件分块运行 scripts/tests，逐块限时，避免整套挂起并保留真实覆盖统计。

输出：analysis/regression/report.json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "scripts" / "tests"
OUT = Path(__file__).resolve().parent / "report.json"
PER_FILE_TIMEOUT = 300

SUMMARY_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")
COUNT_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


def counts(text: str) -> dict:
    found = {}
    for line in text.splitlines():
        if not line.strip().startswith(("=", "!", "FAILED", "ERROR")) and " in " not in line:
            continue
        for number, kind in COUNT_RE.findall(line):
            found[kind] = found.get(kind, 0) + int(number)
    return found


def main() -> int:
    files = sorted(TESTS.glob("test_*.py"))
    report = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": [], "totals": {}}
    totals = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    failed_files = []
    timed_out = []
    for index, path in enumerate(files, start=1):
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(path), "-q", "-p", "no:cacheprovider"],
                cwd=str(REPO), capture_output=True, text=True, timeout=PER_FILE_TIMEOUT,
            )
            text = (proc.stdout or "") + (proc.stderr or "")
            code = proc.returncode
            timed_out_flag = False
        except subprocess.TimeoutExpired as exc:
            text = ((exc.stdout or b"").decode("utf-8", "replace")
                    if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
            code = -1
            timed_out_flag = True
        elapsed = round(time.perf_counter() - started, 2)
        file_counts = counts(text)
        for key in totals:
            totals[key] += file_counts.get(key, 0)
        entry = {
            "file": path.name,
            "returncode": code,
            "seconds": elapsed,
            "counts": file_counts,
            "timedOut": timed_out_flag,
            "tail": "\n".join(text.strip().splitlines()[-8:]),
        }
        report["files"].append(entry)
        if timed_out_flag:
            timed_out.append(path.name)
        elif code != 0:
            failed_files.append(path.name)
        print("[{0}/{1}] {2} rc={3} {4}s {5}".format(
            index, len(files), path.name, code, elapsed, file_counts))
        sys.stdout.flush()
    report["totals"] = totals
    report["failedFiles"] = failed_files
    report["timedOutFiles"] = timed_out
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TOTALS", totals, "failed", len(failed_files), "timeout", len(timed_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())