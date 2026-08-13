# -*- coding: utf-8 -*-
"""运行 pip-audit 并保存 JSON；发现漏洞或扫描失败即阻断。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(requirements: str, output: str, executable=None) -> int:
    command = executable or [sys.executable, "-m", "pip_audit"]
    completed = subprocess.run(
        list(command) + ["-r", requirements, "--format", "json", "--output", output],
        check=False,
    )
    if not Path(output).exists():
        Path(output).write_text('{"error":"pip-audit did not produce a report"}', encoding="utf-8")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return run(args.requirements, args.output)


if __name__ == "__main__":
    sys.exit(main())
