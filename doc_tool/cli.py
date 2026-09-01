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
    # 公共 CLI 只提供项目上下文构建（通用与旧版专用项目均可）；
    # 仓库内置 `build requirement|design|all` 旧入口已退出公共产品面（任务 7.3）。
    build_p = sub.add_parser("build", help="构建并校验文档（项目上下文）")
    build_p.add_argument("--skip-word-refresh", action="store_true")
    build_p.add_argument("--project", required=True, help="项目目录")
    # 修订记录没有命令行参数：内容与版本号都由 content/<类型>/_revision_record.md
    # 一处维护，构建按该文件为准（末行版本号 → documentVersion，数据行整表覆盖
    # Word 修订记录表）。CI/脚本要写修订记录就直接改那个文件。
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

    migrate = sub.add_parser("migrate", help="把旧版专用项目迁移为通用大文档项目")
    migrate.add_argument("--project", required=True, help="源旧版项目目录")
    migrate.add_argument("--target", required=True, help="目标通用项目目录（必须不存在）")
    _add_output(migrate)

    renumber_p = sub.add_parser("renumber", help="把章节目录编号重排为连续（默认预览，--apply 才写盘）")
    renumber_p.add_argument("--project", required=True, help="项目目录")
    renumber_p.add_argument(
        "--dir", default="",
        help="仅重编号该内容相对目录（相对 contentRoot，如 第4章 WEB端功能设计/4.7 示例模块）；缺省扫描整个内容根",
    )
    renumber_p.add_argument(
        "--apply", action="store_true",
        help="确认并应用重编号（缺省仅预览，不写盘）",
    )
    _add_output(renumber_p)

    convert_p = sub.add_parser(
        "convert", help="文档互转：Word/PDF/Markdown/HTML/TXT/表格/RTF/ODT（任意文件，无需项目）"
    )
    from doc_tool.application.convert import TARGET_FORMATS

    convert_p.add_argument(
        "sources", nargs="+",
        help="待转换文件或文件夹（.docx/.doc/.pdf/.md/.html/.txt/.xlsx/.csv/.rtf/.odt）",
    )
    convert_p.add_argument(
        "--to", choices=list(TARGET_FORMATS), default=None,
        help="转出格式（pdf/md/html/docx/txt/csv/xlsx）；仅对存在该方向的源生效，"
             "其余源按缺省方向转换（Word/PDF/MD/HTML 缺省见使用说明第 6 节）",
    )
    convert_p.add_argument(
        "--toc", action="store_true",
        help="Markdown/HTML → Word 时在文首插入 1~3 级目录",
    )
    convert_p.add_argument(
        "--pages", default="",
        help="页范围（如 1-5 或 3）；仅对转出 PDF 的方向生效，留空表示全部页面",
    )
    convert_p.add_argument(
        "--target-dir", default="", help="输出目录；缺省与各源文件同目录"
    )
    convert_p.add_argument("--overwrite", action="store_true", help="覆盖同名输出文件")
    convert_p.add_argument(
        "--timeout", type=int, default=0,
        help="单个文件超时秒数；0 = 按方向自动（导出 300，PDF 重排 900）",
    )
    _add_output(convert_p)
    return parser


def _convert_command(args) -> int:
    """文档互转：不依赖项目上下文，方向由注册表（扩展名 + --to）判定。"""
    from doc_tool.application.convert import convert_paths, expand_sources

    sources = expand_sources(args.sources)
    if not sources:
        print(
            "没有可转换的文件（支持 .docx/.doc/.pdf/.md/.html/.txt/.xlsx/.csv/.rtf/.odt）。",
            file=sys.stderr,
        )
        return 2

    def _progress(done, total, record):
        print(
            "[{0}/{1}] {2} → {3} {4}".format(
                done,
                total,
                record.source.name,
                record.target.name or "（未生成）",
                record.status,
            ),
            file=sys.stderr,
            flush=True,
        )

    result = convert_paths(
        sources,
        args.target_dir or None,
        overwrite=args.overwrite,
        target_format=args.to,
        with_toc=args.toc,
        page_range=args.pages or None,
        timeout_seconds=float(args.timeout) if args.timeout else None,
        on_progress=_progress,
    )
    if getattr(args, "output", "human") == "json":
        import json

        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success else 1
    for record in result.records:
        line = "{0} {1} → {2}".format(
            "OK" if record.ok else "FAIL",
            record.source.name,
            record.target.name or "（未生成）",
        )
        if not record.ok:
            line += "  [{0}] {1}".format(record.error_code, record.detail)
        print(line)
        if record.note:
            print("    {0}".format(record.note))
    print(result.summary())
    return 0 if result.success else 1


def _legacy(args, parser: argparse.ArgumentParser) -> Optional[int]:
    if args.version or args.command == "info":
        from doc_tool import get_build_info
        for key, value in get_build_info().items():
            print("{0}: {1}".format(key, value))
        return 0
    if args.command != "build":
        return None
    # 公共 CLI 只支持基于项目目录的构建（通用与旧版专用项目均可）。
    if not args.project:
        parser.error("build 需要 --project <项目目录>")
    from doc_tool.adapters.kernel import ensure_kernel_importable
    ensure_kernel_importable()
    from doc_tool.application.pipeline import run_pipeline
    from doc_tool.domain.manifest import ProjectManifest
    manifest = ProjectManifest.load(args.project)
    result = run_pipeline(
        manifest,
        manifest.resolve_paths(args.project),
        skip_word_refresh=args.skip_word_refresh,
    )
    for event in result.events:
        line = "[{0}] {1}".format(event.status.upper(), event.stage)
        if event.detail:
            line += ": {0}".format(event.detail)
        if event.error_code:
            line += " ({0})".format(event.error_code)
        print(line)
        # 内核给出结构化出错位置时逐条列出：命令行使用者（包括 CI）
        # 不应该只拿到一个错误码，而要能直接看到哪个文件第几行要改。
        for item in (event.metrics or {}).get("locations") or ():
            if not isinstance(item, dict):
                continue
            where = str(item.get("relPath") or item.get("path") or "")
            if item.get("line") is not None:
                where = "{0}:{1}".format(where, item["line"])
            parts = [where, str(item.get("message") or ""), str(item.get("hint") or "")]
            print("  - {0}".format(" ".join(part for part in parts if part).strip()))
    return 0 if result.success else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    legacy = _legacy(args, parser)
    if legacy is not None:
        return legacy
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "convert":
        # 互转不依赖项目，也不走质量命令的序列化通道。
        return _convert_command(args)

    from doc_tool.application.cli_commands import (
        import_command, lint_command, migrate_command, preflight_command,
        renumber_command, search_command, status_command, validate_command,
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
        elif args.command == "migrate":
            result = migrate_command(args)
        elif args.command == "renumber":
            result = renumber_command(args)
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
