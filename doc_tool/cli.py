# -*- coding: utf-8 -*-
"""统一 CLI：兼容 build/info，并提供机器可读质量命令。"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
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

    # V2.7 27-G：统一检查入口。默认只做源检查，warning 不阻断。
    check_p = sub.add_parser("check", help="统一检查（源检查/可选构建与终审）")
    check_p.add_argument("--project", required=True, help="项目目录")
    check_p.add_argument("--output", choices=("text", "json", "sarif"), default="text")
    check_p.add_argument("--fail-on", choices=("error", "warning"), default="error")
    check_p.add_argument("--build", action="store_true", help="同时做一次诊断构建并审查产物")
    check_p.add_argument("--strict", action="store_true", help="显式严格交付：把约定规则提升为阻断")
    check_p.add_argument("--jobs", type=int, default=1, help="保留参数：当前检查为单项目串行")

    # V2.9 29-D：显式图矩阵与可解释覆盖率。
    trace_p = sub.add_parser("trace", help="需求—设计—测试矩阵与覆盖率")
    trace_p.add_argument("--project", help="单项目目录")
    trace_p.add_argument("--workspace", help="工作区目录（与 --project 二选一）")
    trace_p.add_argument("--format", choices=("markdown", "json", "csv"), default="markdown")
    trace_p.add_argument("--fail-on-uncovered", action="store_true", help="存在未覆盖需求时退出 1")

    # V2.9 29-E：变更影响与复核状态。
    impact_p = sub.add_parser("impact", help="变更影响与待复核")
    impact_p.add_argument("--project", help="单项目目录")
    impact_p.add_argument("--workspace", help="工作区目录（与 --project 二选一）")
    impact_p.add_argument("--baseline", help="可选：基线快照目录用于比对方案")
    impact_p.add_argument("--item", action="append", default=[], help="受控变更的条目 projectId/itemId，可重复")
    impact_p.add_argument("--format", choices=("markdown", "json"), default="markdown")
    impact_p.add_argument("--fail-on-pending", action="store_true", help="存在待复核时退出 1")

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

    autolink_p = sub.add_parser("autolink", help="为修订记录表摘要自动赋值章节文档超链接")
    autolink_p.add_argument("--project", "-p", nargs="*", default=["."], help="项目目录（支持多个，默认当前目录）")
    autolink_p.add_argument("--latest-only", action="store_true", help="仅为末尾最新一条（正式初稿/当前发版行）赋值超链接")
    autolink_p.add_argument("--version", "-v", dest="target_version", help="指定仅为特定版本（如 V2.6）赋值超链接")
    autolink_p.add_argument("--dry-run", action="store_true", help="只预览改动，不写盘")
    _add_output(autolink_p)
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
        "--template", default="",
        help="Word 底模（.docx）：Markdown → Word 时按模板样式、封面与页眉装配"
             "（模板填充，离线出稿）；仅对 Markdown 源生效，不填走内置 CSS 版式",
    )
    convert_p.add_argument(
        "--timeout", type=int, default=0,
        help="单个文件超时秒数；0 = 按方向自动（导出 300，PDF 重排 900）",
    )
    _add_output(convert_p)

    pdf_p = sub.add_parser(
        "pdf",
        help="PDF 工具箱：合并/拆分/提取/删除/旋转/转图片/图片转PDF/转文本/水印/页码/元数据/加密/解密/压缩",
    )
    from doc_tool.application.pdf_tools import add_pdf_tool_arguments

    add_pdf_tool_arguments(pdf_p)
    _add_output(pdf_p)

    tf_p = sub.add_parser(
        "template-fill",
        help="模板填充：Word 底模 + 多个 Markdown 按顺序合并为单个 Word（离线出稿）",
    )
    tf_p.add_argument(
        "sources", nargs="+",
        help="Markdown 文件（.md/.markdown），按给定顺序合并为同一文档的连续章节",
    )
    tf_p.add_argument("--template", required=True, help="Word 底模（.docx）")
    tf_p.add_argument("--output", required=True, help="输出 DOCX 路径（冲突时默认换名）")
    tf_p.add_argument("--dry-run", action="store_true", help="只读预检，不装配 DOCX")
    tf_p.add_argument("--report-format", choices=['text', 'json'], default='text')
    tf_p.add_argument("--strict", action="store_true", help="显式严格检查：降级提醒阻止生成")
    tf_p.add_argument(
        "--map", dest="style_maps", action="append", default=[],
        help="标题样式映射，格式 样式ID=级别（可重复），如 --map 章标题=1；"
             "底模样式可自动识别时无需提供",
    )
    tf_p.add_argument(
        "--refresh-fields", action="store_true",
        help="出稿后用本机 Word 刷新目录/域（需 Word；无 Word 时保留打开刷新标记）",
    )
    tf_p.add_argument(
        "--clean-body", action="store_true",
        help="底模为现成文档时，从第一个标题 1 起清理旧正文（封面/页眉/样式保留）",
    )
    return parser


def _convert_command(args) -> int:
    """文档互转：不依赖项目上下文，方向由注册表（扩展名 + --to）判定。"""
    from pathlib import Path

    from doc_tool.application.convert import (
        MARKDOWN_SUFFIXES, convert_paths, expand_sources,
    )

    sources = expand_sources(args.sources)
    if not sources:
        print(
            "没有可转换的文件（支持 .docx/.doc/.pdf/.md/.html/.txt/.xlsx/.csv/.rtf/.odt）。",
            file=sys.stderr,
        )
        return 2

    template_path = (getattr(args, "template", "") or "").strip() or None
    if template_path and not any(
        Path(source).suffix.lower() in MARKDOWN_SUFFIXES for source in sources
    ):
        print(
            "--template 仅对 Markdown 源生效：本次输入中没有 Markdown 文件。",
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
        template_path=template_path,
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


def _pdf_command(args) -> int:
    """PDF 工具箱：面向任意 PDF 或图片文件，不依赖项目上下文。"""
    from doc_tool.application.pdf_tools import (
        expand_sources,
        pdf_options_from_args,
        run_pdf_tool,
    )

    sources = expand_sources(args.sources, tool_id=args.tool)
    if not sources:
        print("没有可处理的有效源文件。", file=sys.stderr)
        return 2

    def _progress(done, total, record):
        targets_str = "、".join(p.name for p in record.outputs) if record.outputs else "（无产物）"
        print(
            "[{0}/{1}] {2} {3} → {4} {5}".format(
                done,
                total,
                record.label,
                record.source.name,
                targets_str,
                record.status,
            ),
            file=sys.stderr,
            flush=True,
        )

    options = pdf_options_from_args(args)
    result = run_pdf_tool(
        args.tool,
        sources,
        output_dir=args.target_dir or None,
        overwrite=args.overwrite,
        options=options,
        on_progress=_progress,
    )

    if getattr(args, "output", "human") == "json":
        import json

        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success else 1

    for record in result.records:
        targets_str = "、".join(p.name for p in record.outputs) if record.outputs else "（无产物）"
        line = "{0} [{1}] {2} → {3}".format(
            "OK" if record.ok else "FAIL",
            record.label,
            record.source.name,
            targets_str,
        )
        if not record.ok:
            line += "  [{0}] {1}".format(record.error_code, record.detail)
        elif record.detail:
            line += "  {0}".format(record.detail)
        print(line)
        if record.note:
            print("    {0}".format(record.note))
    print(result.summary())
    return 0 if result.success else 1


def _template_fill_command(args) -> int:
    """模板填充：底模 + 多个 Markdown 按顺序合并为单个 Word（离线）。"""
    from pathlib import Path

    from doc_tool.application.template_fill import (
        TemplateFillError,
        fill_markdown_with_template,
    )

    sources = [Path(item) for item in args.sources]
    for source in sources:
        if source.suffix.lower() not in (".md", ".markdown"):
            print(
                "源必须是 Markdown 文件（.md/.markdown）：{0}".format(source.name),
                file=sys.stderr,
            )
            return 2

    style_map = {}
    for item in getattr(args, "style_maps", None) or []:
        key, _, value = item.partition("=")
        try:
            style_map[key.strip()] = int(value.strip())
        except ValueError:
            print(
                "样式映射格式无效：{0!r}（应为 样式ID=级别，如 章标题=1）".format(item),
                file=sys.stderr,
            )
            return 2

    def _warning(message: str) -> None:
        print("[warn] {0}".format(message), file=sys.stderr, flush=True)

    try:
        from doc_tool.application.template_fill_plan import plan_template_fill, execute_template_fill
        plan = plan_template_fill(sources, args.template, args.output, mapping=style_map,
                                  strict=getattr(args, 'strict', False))
        if getattr(args, 'dry_run', False):
            print(plan.report(getattr(args, 'report_format', 'text')))
            return 0 if plan.viable else 1
        result = execute_template_fill(
            sources,
            args.template,
            args.output,
            heading_style_map=style_map or None,
            refresh_fields=bool(args.refresh_fields),
            clean_body_from_first_heading=bool(args.clean_body),
            on_warning=_warning,
            strict=getattr(args, 'strict', False),
        )
    except TemplateFillError as exc:
        print(
            "[FAIL] 模板填充失败（{0}）：{1} {2}".format(
                exc.code, exc.user_message, exc.suggested_action
            ),
            file=sys.stderr,
        )
        return 1

    summary = "模板填充完成：{0} 个章节".format(result.chapters)
    if result.images:
        summary += "、图片 {0} 张".format(result.images)
    print("{0} → {1}".format(summary, result.output))
    for warning in result.warnings:
        print("[warn] {0}".format(warning))
    return 0


def _impact_command(args) -> int:
    """变更影响：输出直接/传递影响与待复核状态。

    退出码：0=正常；1=存在待复核且显式要求；2=参数或执行失败。
    **不会修改任何下游正文**。
    """
    from doc_tool.application.content.impact import (
        ReviewRecordStore,
        compute_impact,
    )

    if bool(args.project) == bool(args.workspace):
        print("[FAIL] 请二选一地指定 --project 或 --workspace。", file=sys.stderr)
        return 2
    root = Path(args.project or args.workspace)
    if not root.is_dir():
        print("[FAIL] 路径不存在：{0}".format(root), file=sys.stderr)
        return 2
    try:
        graph, _documents = _collect_graph(Path(root), workspace=bool(args.workspace))
        changed = {}
        for token in args.item or []:
            project_id, _, item_id = str(token).partition("/")
            if not project_id or not item_id:
                print("[FAIL] --item 应为 projectId/itemId：{0}".format(token), file=sys.stderr)
                return 2
            changed[(project_id, item_id)] = "显式声明的受控变更"
        if not changed:
            changed = _detect_changes(Path(root), args.baseline)
        report = compute_impact(changed, graph)
        store = ReviewRecordStore(Path(root) / ".state")
        pending = store.pending()
        report.warnings.extend(
            "待复核关系 {0}：{1}".format(item.relation_id, item.status)
            for item in pending[:20]
        )
    except Exception as exc:  # noqa: BLE001 - 执行失败退出 2
        print("[FAIL] 影响计算失败：{0}".format(exc), file=sys.stderr)
        return 2
    print(report.export(args.format))
    if args.fail_on_pending and pending:
        print("[FAIL] 存在 {0} 条待复核关系。".format(len(pending)), file=sys.stderr)
        return 1
    return 0


def _collect_graph(root: Path, *, workspace: bool):
    """收集关系图与文档快照（单项目或工作区）。"""
    from doc_tool.application.content.relations import RELATIONS_NAME, RelationGraph, load_relations

    graph = RelationGraph()
    documents = []
    if workspace:
        from doc_tool.application.workspace import load_workspace

        space = load_workspace(root)
        for member in space.valid_members:
            project_root = space.member_project_root(member)
            if project_root is None:
                continue
            documents.extend(_project_documents(project_root))
            path = project_root / RELATIONS_NAME
            if path.is_file():
                loaded = load_relations(path)
                graph.relations.extend(loaded.relations)
                graph.issues.extend(loaded.issues)
    else:
        documents.extend(_project_documents(root))
    path = root / RELATIONS_NAME
    if path.is_file():
        loaded = load_relations(path)
        graph.relations.extend(loaded.relations)
        graph.issues.extend(loaded.issues)
    return graph, documents


def _detect_changes(root: Path, baseline: str) -> dict:
    """无显式 --item 时：从基线快照与当前内容比对推出变更。

    缺少可用基线时**不推断**，返回空并由调用方提醒。
    """
    if not baseline:
        return {}
    from doc_tool.application.content.impact import ItemSnapshot, diff_snapshots

    base_dir = Path(baseline)
    if not base_dir.is_dir():
        return {}
    documents = _project_documents(root)
    before = {}
    after = {}
    for rel_path, text in documents:
        snapshot = _snapshot_from_text(rel_path, text)
        if snapshot is None:
            continue
        key, item = snapshot
        after[key] = item
        base_file = base_dir / rel_path
        if base_file.is_file():
            base_snapshot = _snapshot_from_text(rel_path, base_file.read_text(encoding="utf-8"))
            if base_snapshot is not None:
                before[base_snapshot[0]] = base_snapshot[1]
    changed, _spec = diff_snapshots(before, after)
    return changed


def _snapshot_from_text(rel_path: str, text: str):
    """从 Markdown 文本提取一条条目快照（字段级，不依赖编号）。"""
    import re as _re

    from doc_tool.application.content.impact import ItemSnapshot
    from doc_tool.application.content.traceable_items import parse_marker

    match = _re.search(r"<!--\s*DOC-ITEM:([^>]*?)-->", str(text or ""))
    if match is None:
        return None
    ref, _error = parse_marker(match.group(0))
    if ref is None:
        return None
    title = ""
    for line in str(text or "").splitlines():
        heading = _re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if heading:
            title = heading.group(1).strip()
            break
    body = "\n".join(
        line for line in str(text or "").splitlines() if not _re.search(r"DOC-ITEM", line)
    )
    return ref.key, ItemSnapshot(key=ref.key, title=title, body=body)


def _trace_command(args) -> int:
    """显式图矩阵：stdout 只输出单一文档（markdown/json/csv）。

    退出码：0=正常；1=存在未覆盖需求且显式要求；2=参数或执行失败。
    """
    from doc_tool.application.content.trace_matrix import build_coverage, export_report

    if bool(args.project) == bool(args.workspace):
        print("[FAIL] 请二选一地指定 --project 或 --workspace。", file=sys.stderr)
        return 2
    root = Path(args.project or args.workspace)
    if not root.is_dir():
        print("[FAIL] 路径不存在：{0}".format(root), file=sys.stderr)
        return 2
    try:
        coverage = _collect_coverage(Path(root), workspace=bool(args.workspace))
    except Exception as exc:  # noqa: BLE001 - 执行失败必须退出 2
        print("[FAIL] 矩阵计算失败：{0}".format(exc), file=sys.stderr)
        return 2
    print(export_report(coverage, args.format))
    if args.fail_on_uncovered and coverage.uncovered:
        print(
            "[FAIL] 存在 {0} 条未覆盖需求。".format(len(coverage.uncovered)),
            file=sys.stderr,
        )
        return 1
    return 0


def _collect_coverage(root: Path, *, workspace: bool):
    """从单项目或工作区收集条目与关系后计算覆盖率。"""
    from doc_tool.application.content.relations import RELATIONS_NAME, load_relations
    from doc_tool.application.content.trace_matrix import build_coverage
    from doc_tool.application.content.traceable_items import build_item_index

    documents = []
    relation_paths = []
    if workspace:
        from doc_tool.application.workspace import load_workspace

        space = load_workspace(root)
        for member in space.valid_members:
            project_root = space.member_project_root(member)
            if project_root is None:
                continue
            relation_paths.append(project_root / RELATIONS_NAME)
            documents.extend(_project_documents(project_root))
        relation_paths.append(root / RELATIONS_NAME)
    else:
        relation_paths.append(root / RELATIONS_NAME)
        documents.extend(_project_documents(root))

    graph = None
    for path in relation_paths:
        if not path.is_file():
            continue
        loaded = load_relations(path)
        if graph is None:
            graph = loaded
        else:
            graph.relations.extend(loaded.relations)
            graph.issues.extend(loaded.issues)
    if graph is None:
        from doc_tool.application.content.relations import RelationGraph

        graph = RelationGraph()
    index = build_item_index(documents)
    return build_coverage(list(index.items.values()), graph)


def _project_documents(project_root: Path):
    """读取项目内的全部 Markdown（按相对路径）。"""
    from doc_tool.domain.manifest import ProjectManifest

    manifest = ProjectManifest.load(project_root)
    paths = manifest.resolve_paths(project_root)
    documents = []
    if paths.content_root.is_dir():
        for path in sorted(paths.content_root.rglob("*.md")):
            if path.is_file():
                documents.append(
                    (path.relative_to(paths.content_root).as_posix(), path.read_text(encoding="utf-8"))
                )
    return documents


def _check_command(args) -> int:
    """统一检查命令：stdout 只输出单一结构化文档，日志走 stderr。

    退出码：0=未达阀值；1=达到检查阀值；2=参数或执行失败。
    运行失败不得伪装成检查通过。
    """
    from doc_tool.application.check import run_check, serialize_check_text
    from doc_tool.application.issues import issue_type_for_stage  # noqa: F401  (保持词汇一致性引用)
    from doc_tool.cli_serializers import serialize_sarif

    project = Path(args.project)
    if not project.is_dir():
        print(
            "[FAIL] 项目路径不存在: {0}".format(args.project),
            file=sys.stderr,
        )
        return 2
    try:
        report = run_check(
            project,
            fail_on=args.fail_on,
            strict=bool(args.strict),
            build=bool(args.build),
        )
    except Exception as exc:  # noqa: BLE001 - 运行失败必须以 2 退出
        print("[FAIL] 检查执行失败：{0}".format(exc), file=sys.stderr)
        return 2

    if args.output == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.output == "sarif":
        print(serialize_sarif_for_check(report))
    else:
        print(serialize_check_text(report))
    return report.exit_code


def serialize_sarif_for_check(report) -> str:
    """把统一检查报告转成 SARIF（复用现有序列化器的规则 ID 与位置约定）。"""
    from doc_tool.application.cli_commands import CommandResult, ProjectCommandResult
    from doc_tool.cli_serializers import serialize_sarif

    item = ProjectCommandResult(
        project=report.project_id,
        success=report.exit_code == 0,
        error_code="" if report.exit_code == 0 else "E2002",
        issues=report.sorted_issues(),
    )
    return serialize_sarif(CommandResult("check", [item]))


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


def _force_utf8_stdio() -> None:
    """Force UTF-8 on stdout/stderr.

    Help text and diagnostics contain CJK characters. On a non-UTF-8
    console (frozen exe on an English-locale Windows) printing them
    raises UnicodeEncodeError and the CLI exits with code 1.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    legacy = _legacy(args, parser)
    if legacy is not None:
        return legacy
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "impact":
        return _impact_command(args)
    if args.command == "trace":
        return _trace_command(args)
    if args.command == "check":
        return _check_command(args)
    if args.command == "convert":
        # 互转不依赖项目，也不走质量命令的序列化通道。
        return _convert_command(args)
    if args.command == "template-fill":
        return _template_fill_command(args)
    if args.command == "pdf":
        return _pdf_command(args)

    from doc_tool.application.cli_commands import (
        import_command, lint_command, migrate_command, preflight_command,
        autolink_command, renumber_command, search_command, status_command, validate_command,
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
        elif args.command == "autolink":
            result = autolink_command(args)
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
