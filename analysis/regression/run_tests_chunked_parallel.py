# -*- coding: utf-8 -*-
"""按文件分块运行 scripts/tests，逐块限时，并保留真实覆盖统计（并行版）。

与 ``run_tests_chunked.py`` 使用完全相同的命令与统计口径：

    python -m pytest <file> -q -p no:cacheprovider   （cwd=仓库根）

区别只在于用固定大小的进程池并行执行多个文件，让 180+ 文件的覆盖核对在可接受
时间内完成。每个文件仍然独立进程、独立超时（默认 300s），因此退出码、通过/失败/
跳过计数、超时标记与串行版同源；不共享解释器状态，不会把两个测试文件的结果混在
一起。

输出：``analysis/regression/report.json``（可用 ``--out`` 改名）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "scripts" / "tests"
OUT = Path(__file__).resolve().parent / "report.json"
PER_FILE_TIMEOUT = 300


def child_env() -> dict:
    """与 ``scripts/tests/run_tests.py``（仓库真实入口）一致的子进程环境。

    不设置 ``PYTHONUTF8=1``/``PYTHONPATH`` 时，读文件用区域编码的用例会以
    ``UnicodeDecodeError`` 失败、控制台输出用例会因编码乱码断言失败——这类
    非零退出是**运行方式差异**而不是产品缺陷。这里与真实入口对齐，避免把
    环境差异记成产品失败。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    paths = [str(REPO)]
    vendor = REPO / ".vendor" / "site-packages"
    if vendor.is_dir():
        paths.insert(0, str(vendor))
    existing = env.get("PYTHONPATH", "")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env

COUNT_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


def counts(text: str) -> dict:
    """从真实 pytest 输出行提取计数（与串行版同一实现）。"""
    found = {}
    for line in (text or "").splitlines():
        if not line.strip().startswith(("=", "!", "FAILED", "ERROR")) and " in " not in line:
            continue
        for number, kind in COUNT_RE.findall(line):
            found[kind] = found.get(kind, 0) + int(number)
    return found


def run_one(path: Path, timeout: int) -> dict:
    started = time.perf_counter()
    text = ""
    code = 0
    timed_out = False
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", "-p", "no:cacheprovider"],
            cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=child_env(),
        )
        text = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        raw_stdout = exc.stdout or b""
        raw_stderr = exc.stderr or b""
        if isinstance(raw_stdout, bytes):
            raw_stdout = raw_stdout.decode("utf-8", "replace")
        if isinstance(raw_stderr, bytes):
            raw_stderr = raw_stderr.decode("utf-8", "replace")
        text = (raw_stdout or "") + (raw_stderr or "")
        code = -1
        timed_out = True
    elapsed = round(time.perf_counter() - started, 2)
    return {
        "file": path.name,
        "returncode": code,
        "seconds": elapsed,
        "counts": counts(text),
        "timedOut": timed_out,
        "tail": "\n".join(text.strip().splitlines()[-8:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=PER_FILE_TIMEOUT)
    parser.add_argument("--only", nargs="*", default=None,
                        help="只运行这些文件名（相对 scripts/tests）")
    parser.add_argument("--skip", nargs="*", default=[],
                        help="跳过这些文件名")
    args = parser.parse_args()

    files = sorted(TESTS.glob("test_*.py"))
    if args.only:
        wanted = set(str(item) for item in args.only)
        files = [item for item in files if item.name in wanted]
    skip = set(str(item) for item in args.skip)
    if skip:
        files = [item for item in files if item.name not in skip]

    def _write_results() -> None:
        """增量落盘：中断/迁移后已完成文件的真实结果不能丢。"""
        ordered = sorted(results, key=lambda item: item["file"])
        totals = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        for entry in ordered:
            for key in totals:
                totals[key] += entry["counts"].get(key, 0)
        payload = {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "python": sys.version,
            "command": "python -m pytest <file> -q -p no:cacheprovider",
            "workers": args.workers,
            "timeoutSeconds": args.timeout,
            "seconds": round(time.perf_counter() - started, 2),
            "requestedFiles": [item.name for item in files],
            "files": ordered,
            "totals": totals,
            "failedFiles": [item["file"] for item in ordered
                            if item["returncode"] != 0 and not item["timedOut"]],
            "timedOutFiles": [item["file"] for item in ordered if item["timedOut"]],
        }
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    started = time.perf_counter()
    results = []
    target = Path(args.out)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = dict((pool.submit(run_one, path, args.timeout), path) for path in files)
        done = 0
        for future in as_completed(futures):
            entry = future.result()
            results.append(entry)
            done += 1
            print("[{0}/{1}] {2} rc={3} {4}s {5}".format(
                done, len(files), entry["file"], entry["returncode"],
                entry["seconds"], entry["counts"]), flush=True)
            # 每个文件完成即落盘：中断后覆盖统计仍然可用。
            _write_results()

    _write_results()
    failed = [item["file"] for item in results
              if item["returncode"] != 0 and not item["timedOut"]]
    timed_out = [item["file"] for item in results if item["timedOut"]]
    print("TOTALS done", len(results), "failed", len(failed), "timeout", len(timed_out),
          "report", str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())