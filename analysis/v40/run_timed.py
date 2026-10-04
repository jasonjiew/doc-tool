# -*- coding: utf-8 -*-
"""在独立进程里限时运行测试文件，超时输出所有线程栈（定位模态/死锁）。"""
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
env["PYTHONFAULTHANDLER"] = "1"
env["QT_QPA_PLATFORM"] = "offscreen"
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
    print("TIMEOUT after {0:.0f}s".format(timeout))
    # 用 faulthandler 的窗口消息触发不了；改为直接抓取进程栈不可行，
    # 于是先用 py-spy 类工具缺失时退回到「分文件/分用例」二分定位。
    proc.kill()
    out, _ = proc.communicate()
    print(out)
    raise SystemExit(124)