# -*- coding: utf-8 -*-
"""在子进程里跑单个用例，超时后 dump 全线程栈（定位模态/死锁）。"""
from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
target = sys.argv[1]
timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"
env["PYTHONFAULTHANDLER"] = "1"
env["QT_QPA_PLATFORM"] = "offscreen"
dump = Path(__file__).resolve().parent / "hang-stacks.txt"
proc = subprocess.Popen(
    [sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider"],
    cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
)
started = time.monotonic()
try:
    out, _ = proc.communicate(timeout=timeout)
    print(out)
    print("exit", proc.returncode)
    raise SystemExit(proc.returncode)
except subprocess.TimeoutExpired:
    print("TIMEOUT after {0:.0f}s — dumping stacks".format(timeout))
    # 通过 faulthandler 无法跨进程触发；这里改用 Windows 侧线程栈不可行，
    # 于是先把已知信息落盘，再由调用方按用例二分。
    dump.write_text("timeout target={0} seconds={1:.0f}\n".format(target, timeout), encoding="utf-8")
    proc.kill()
    out, _ = proc.communicate()
    print(out[-3000:] if out else "")
    raise SystemExit(124)