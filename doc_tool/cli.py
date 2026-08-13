# -*- coding: utf-8 -*-
"""统一 CLI：兼容 build/info，并提供机器可读质量命令。"""

from __future__ import annotations

import argparse
import contextlib
import sys
from typing import Optional, Sequence


def _add_output(parser: argparse.ArgumentParser, formats=()) -> None:
    parser.add_argument("--output", choices=("human", "json"), default="human")
    if formats:
        parser.add_argument("--format", choices=formats)


def _add_projects(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", action="append", required=True, help="项目目录，可重复")


def build_parser() -> argparse.ArgumentParser:
    from doc_tool.domain.branding import CLI_NAME, PRODUCT_DESCRIPTION

    parser = argparse.ArgumentParser(
        prog=CLI_NAME,
        description=PRODUCT_DESCRIPTION,
    )
    parser.add_argument("--version", action="store_true", help="显示应用版本与构建信息")
    sub = parser.add_subparsers(dest="command")
    build_p = sub.add_parser("build", help="构建并校验文档（兼容入口）")
    build_p.add_argument("document", choices=("general", "requirement", "design", "all"), nargs="?", default="all")
    build_p.add_argument("--skip-word-refresh", action="store_true")
    build_p.add_argument("--project", help="项目目录（使用新项目上下文）")
    sub.add_parser("info", help="显示环境诊断信息")

    preflight = sub.add_parser("preflight", help="导入预检")
    preflight.add_argument("--docx", required=True)
    _add_output(preflight)

    import_p = sub.add_parser("import", help="首次导入项目")
    import_p.add_argument("--docx", required=True)
    import_p.add_argument("--name", required=True)
    import_p.add_argument("--target-dir", default=".")
    # 公共版只创建通用大文档项目；requirement/design 仅旧项目兼容读取，不再可新建。
    import_p.add_argument(
        "--document-type", choices=("general",), default="general",
        help="项目文档类型（公共版固定为 general）",
    )
    import_p.add_argument("--document-no", default="")
    import_p.add_argument("--document-name", default="")
    import_p.add_argument("--document-version", default="")
    _add_output(import_p)

    validate = sub.add_parser("validate", help="校验一个或多个项目")
    _add_projects(validate)
    _add_output(validate, ("sarif", "junit"))

    lint = sub.add_parser("lint", help="检查一个或多个项目")
    _add_projects(lint)
    _add_output(lint, ("sarif",))

    search = sub.add_parser("search", help="搜索一个或多个项目")
    _add_projects(search)
    search.add_argument("--query", required=True)
    search.add_argument("--regex", action="store_true")
    search.add_argument("--case-sensitive", action="store_true")
    search.add_argument("--whole-word", action="store_true")
    search.add_argument("--limit", type=int, default=500)
    _add_output(search)

    status = sub.add_parser("status", help="读取一个或多个项目状态")
    _add_projects(status)
    _add_output(status)
    return parser


def _legacy(args, parser: argparse.ArgumentParser) -> Optional[int]:
    if args.version or args.command == "info":
        from doc_tool import get_build_info
        for key, value in get_build_info().items():
            print("{0}: {1}".format(key, value))
        return 0
    if args.command != "build":
        return None
    if args.project:
        from doc_tool.adapters.kernel import ensure_kernel_importable
        ensure_kernel_importable()
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.manifest import ProjectManifest
        manifest = ProjectManifest.load(args.project)
        result = run_pipeline(manifest, manifest.resolve_paths(args.project), skip_word_refresh=args.skip_word_refresh)
        for event in result.events:
            line = "[{0}] {1}".format(event.status.upper(), event.stage)
            if event.detail:
                line += ": {0}".format(event.detail)
            if event.error_code:
                line += " ({0})".format(event.error_code)
            print(line)
        return 0 if result.success else 1
    if args.document == "general":
        parser.error("general 必须与 --project <项目目录> 一起使用")
    import os
    import subprocess
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, os.path.join(base, "scripts", "run_pipeline.py"), args.document]
    if args.skip_word_refresh:
        cmd.append("--skip-word-refresh")
    return subprocess.run(cmd, cwd=base, check=False).returncode


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    legacy = _legacy(args, parser)
    if legacy is not None:
        return legacy
    if not args.command:
        parser.print_help()
        return 0

    from doc_tool.application.cli_commands import (
        import_command, lint_command, preflight_command, search_command,
        status_command, validate_command,
    )
    # 命令执行期间统一把 stdout 重定向到 stderr：validate/import 等会把进度和
    # 校验报告打印到 stdout（如 ``[requirement] 校验报告: ...``），若只在机器
    # 模式下重定向，human 模式的结果会被过程输出混流，机器模式更会污染 JSON。
    with contextlib.redirect_stdout(sys.stderr):
        if args.command == "preflight":
            result = preflight_command(args.docx)
        elif args.command == "import":
            result = import_command(args)
        elif args.command == "validate":
            result = validate_command(args.project)
        elif args.command == "lint":
            result = lint_command(args.project)
        elif args.command == "search":
            result = search_command(args.project, args.query, args)
        elif args.command == "status":
            result = status_command(args.project)
        else:
            parser.error("未知命令")

    from doc_tool.cli_serializers import (
        serialize_human, serialize_json, serialize_junit, serialize_sarif,
    )
    if getattr(args, "format", None) == "sarif":
        output = serialize_sarif(result)
    elif getattr(args, "format", None) == "junit":
        output = serialize_junit(result)
    elif getattr(args, "output", "human") == "json":
        output = serialize_json(result)
    else:
        output = serialize_human(result)
    print(output)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
