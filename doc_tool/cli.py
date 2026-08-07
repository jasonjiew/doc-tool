# -*- coding: utf-8 -*-
"""命令行入口：保留为现有 ``.cmd`` 使用的 CLI 适配层，并新增 ``--project`` 支持。

任务 1.1：建立 GUI/CLI 入口。日常 ``scripts/run_pipeline.py`` 继续可用；
本模块作为统一 CLI，未来 GUI 也会调用同一应用服务。
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doc-tool",
        description="康尚文档工具：导入、校验、合并公司 Word 文档。",
    )
    parser.add_argument("--version", action="store_true", help="显示应用版本与构建信息")
    sub = parser.add_subparsers(dest="command")

    # 委托现有管线（兼容层），保留 requirement/design/all 与 --skip-word-refresh。
    build_p = sub.add_parser("build", help="构建并校验文档（委托现有管线）")
    build_p.add_argument("document", choices=("requirement", "design", "all"), nargs="?", default="all")
    build_p.add_argument("--skip-word-refresh", action="store_true")
    build_p.add_argument("--project", help="项目目录（使用新项目上下文）")

    sub.add_parser("info", help="显示环境诊断信息")

    args = parser.parse_args(argv)

    if args.version:
        from doc_tool import get_build_info

        info = get_build_info()
        for key, value in info.items():
            print("{0}: {1}".format(key, value))
        return 0

    if args.command == "info":
        from doc_tool import get_build_info

        info = get_build_info()
        for key, value in info.items():
            print("{0}: {1}".format(key, value))
        return 0

    if args.command == "build":
        if args.project:
            # 新入口：使用项目上下文驱动的应用服务。
            from doc_tool.adapters.kernel import ensure_kernel_importable

            ensure_kernel_importable()
            from doc_tool.application.pipeline import run_pipeline
            from doc_tool.domain.manifest import ProjectManifest
            from doc_tool.domain.paths import ProjectPaths

            manifest = ProjectManifest.load(args.project)
            paths = manifest.resolve_paths(args.project)
            result = run_pipeline(
                manifest, paths, skip_word_refresh=args.skip_word_refresh
            )
            for event in result.events:
                status = event.status.upper()
                line = "[{0}] {1}".format(status, event.stage)
                if event.detail:
                    line += ": {0}".format(event.detail)
                if event.error_code:
                    line += " ({0})".format(event.error_code)
                print(line)
            return 0 if result.success else 1

        # 兼容层：委托现有 scripts/run_pipeline.py。
        import os
        import subprocess

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pipeline = os.path.join(base, "scripts", "run_pipeline.py")
        cmd = [sys.executable, pipeline, args.document]
        if args.skip_word_refresh:
            cmd.append("--skip-word-refresh")
        return subprocess.run(cmd, cwd=base, check=False).returncode

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
