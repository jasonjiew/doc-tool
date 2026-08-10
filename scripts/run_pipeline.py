# -*- coding: utf-8 -*-
"""Fail-fast daily build/validate/Word-refresh pipeline."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional, Sequence

from docx_common import discover_document_types


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_step(label: str, arguments: Sequence[str]) -> bool:
    command = [sys.executable] + [os.path.join(BASE, item) if index == 0 else item for index, item in enumerate(arguments)]
    print("\n== {0} ==".format(label), flush=True)
    result = subprocess.run(command, cwd=BASE, check=False)
    if result.returncode != 0:
        print("[FAIL] {0}，退出码 {1}".format(label, result.returncode), file=sys.stderr, flush=True)
        return False
    return True


def pipeline(document: str, skip_word_refresh: bool) -> bool:
    if not run_step("{0}: 构建 DOCX".format(document), ("scripts/build_docx.py", document)):
        return False
    if not run_step("{0}: 刷新前严格校验".format(document), ("scripts/validate_docx.py", document)):
        return False
    if skip_word_refresh:
        print("[SKIP] 已显式跳过 Word 实机刷新；本次仅完成构建级验证。", flush=True)
        return True
    if not run_step("{0}: Word 实机刷新".format(document), ("scripts/refresh_fields.py", document)):
        return False
    return run_step(
        "{0}: 刷新后严格校验".format(document),
        ("scripts/validate_docx.py", document, "--require-refreshed"),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="一键构建、严格校验、Word 刷新、二次校验")
    available = discover_document_types()
    if not available:
        print("[FAIL] 未在 config/ 目录发现任何 .yml 配置", file=sys.stderr)
        return 1
    choices = tuple(available) + ("all",)
    parser.add_argument("document", choices=choices, nargs="?", default="all")
    parser.add_argument(
        "--skip-word-refresh",
        action="store_true",
        help="显式跳过 Word 实机刷新，仅用于无 Word 的诊断环境",
    )
    args = parser.parse_args(argv)
    targets = tuple(available) if args.document == "all" else (args.document,)
    for target in targets:
        if not pipeline(target, args.skip_word_refresh):
            return 1
    print("\n[SUCCESS] 所有指定文档均已完成。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
