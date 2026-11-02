with open('scripts/tests/run_tests.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = """from __future__ import annotations

import argparse"""

replacement = """from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse"""

assert target in code, "Target not found in run_tests.py"
code = code.replace(target, replacement, 1)

with open('scripts/tests/run_tests.py', 'w', encoding='utf-8', newline='') as f:
    f.write(code)
print("Added stdout/stderr encoding reconfigure to run_tests.py")
