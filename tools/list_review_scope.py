# -*- coding: utf-8 -*-
"""\u5ba1\u67e5\u53f0\u8d26\u672b\u6b21\u8986\u76d6\u6821\u9a8c\uff1a\u5217\u51fa**\u672c\u8f6e\u65b0\u589e\u7684\u5168\u90e8\u6e90\u6587\u4ef6**\uff0c\u4f9b\u4eba\u5de5\u9010\u4e2a\u786e\u8ba4\u5df2\u5165\u53f0\u8d26\u3002"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(".")


def tracked_new_files():
    out = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    untracked = []
    modified = []
    for line in (out.stdout or "").splitlines():
        status, _, path = line[:2], line[2:3], line[3:].strip()
        if path.startswith("tmp/") or path.startswith("tmp\\"):
            continue
        if status.strip() == "??":
            untracked.append(path)
        else:
            modified.append(path)
    return untracked, modified


def main() -> int:
    untracked, modified = tracked_new_files()
    src_new = [p for p in untracked if p.endswith(".py")]
    test_new = [p for p in src_new if pathlib.Path(p).name.startswith("test_")]
    module_new = [p for p in src_new if p not in test_new]
    print("== \u672c\u8f6e\u672a\u8ddf\u8e2a\u7684\u6a21\u5757\u6587\u4ef6 ==")
    for path in sorted(module_new):
        print("  ", path)
    print("== \u672c\u8f6e\u672a\u8ddf\u8e2a\u7684\u6d4b\u8bd5\u6587\u4ef6 ==")
    for path in sorted(test_new):
        print("  ", path)
    print("== \u5df2\u8ddf\u8e2a\u4f46\u4fee\u6539\u7684\u6587\u4ef6\u6570\uff1a", len(modified))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())