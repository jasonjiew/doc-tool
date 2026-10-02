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

def _add_version_target(parser: argparse.ArgumentParser) -> None:
    """把 ``<moduleId>[@version]`` 展开成 (moduleId, version)。"""
    parser.add_argument("--module", required=True, help="模块 id，可写 id@version")
    parser.add_argument(
        "--module-version", dest="module_version", default="",
        help="模块版本（已写在 --module id@version 时可省）；"
             "本命令的 --version 归全局构建信息，勿混用",
    )

def _add_reuse_sources(parser: argparse.ArgumentParser) -> None:
    """项目/库的公共输入：项目目录与可选库目录。"""
    parser.add_argument("--project", default="", help="项目目录（含 project.yml）；与 --library 二选一")
    parser.add_argument(
        "--library", default="",
        help="模块库目录；缺省时按「项目固定副本 → 项目配置 → reuse/library」自动选择",
    )

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
    # CORE R5：命名导入映射预设（应用 / 保存）
    import_p.add_argument("--preset", default="", help="应用的命名导入映射预设（未命中项回退自动识别）")
    import_p.add_argument("--save-preset", dest="save_preset", default="",
                          help="导入成功后把本次使用的映射保存为命名预设")
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

    assist_search = sub.add_parser(
        "assist-search", help="在显式加入的项目/模块范围内检索本地资料（来源/版本/定位）",
    )
    assist_search.add_argument("--project", action="append", default=[], help="项目目录，可重复")
    assist_search.add_argument("--module", action="append", default=[], help="模块库目录或文件，可重复")
    assist_search.add_argument("--query", default="", help="检索词（默认按文本匹配）")
    assist_search.add_argument("--term", action="append", default=[], help="术语/别名，可重复")
    assist_search.add_argument("--limit", type=int, default=200, help="命中上限（默认 200）")
    assist_search.add_argument("--cache-dir", default="", help="索引缓存目录（默认用户级缓存）")
    _add_output(assist_search)

    assist_suggest = sub.add_parser(
        "assist-suggest", help="用现有规则/术语/引用/复核事实生成建议（无模型）",
    )
    assist_suggest.add_argument("--project", required=True, help="项目目录")
    assist_suggest.add_argument("--kind", action="append", default=[], help="限定建议种类，可重复")
    assist_suggest.add_argument("--cache-dir", default="", help="索引缓存目录（默认用户级缓存）")
    _add_output(assist_suggest)

    assist_adopt = sub.add_parser(
        "assist-adopt", help="预览建议采纳的 before/after 差异（不写正文）",
    )
    assist_adopt.add_argument("--project", required=True, help="项目目录")
    assist_adopt.add_argument("--suggestion", action="append", default=[], help="建议 id，可重复")
    assist_adopt.add_argument("--kind", action="append", default=[], help="限定建议种类，可重复")
    assist_adopt.add_argument("--cache-dir", default="", help="索引缓存目录（默认用户级缓存）")
    _add_output(assist_adopt)

    assist_provider = sub.add_parser(
        "assist-provider", help="显示可选模型 provider 配置状态（不含凭据）",
    )
    assist_provider.add_argument("--config", default="", help="provider 配置文件（默认用户级）")
    _add_output(assist_provider)

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

    pexport_p = sub.add_parser(
        "project-export",
        help="项目统一出稿：Word/PDF/离线HTML/源码包，同一轮内容，支持仅补失败格式",
    )
    pexport_p.add_argument("--project", required=True, help="项目目录（含 project.yml）")
    pexport_p.add_argument(
        "--formats", default="docx",
        help="逗号分隔格式：docx,pdf,html,source-zip（缺省 docx）",
    )
    pexport_p.add_argument(
        "--scope", choices=["project", "current-chapter", "chapters"], default="project",
        help="出稿范围：整份/当前章/勾选章节（缺省整份）",
    )
    pexport_p.add_argument(
        "--chapters", default="",
        help="勾选章节（相对 contentRoot 的路径，逗号分隔）；按项目顺序输出",
    )
    pexport_p.add_argument(
        "--current-chapter", default="",
        help="当前章（相对 contentRoot 的路径）；与 --scope current-chapter 搭配",
    )
    pexport_p.add_argument("--destination", default="", help="输出目录；缺省项目 output/")
    pexport_p.add_argument("--output-name", default="", help="输出文件名（不含扩展名）")
    pexport_p.add_argument(
        "--source-mode", choices=["saved", "current-buffer"], default="saved",
        help="内容来源：saved=已保存版本（CLI 缺省）；current-buffer 需要 UI 缓冲，"
             "命令行无缓冲时明确拒绝，不谎称读取到界面内容",
    )
    pexport_p.add_argument(
        "--layout", choices=["template", "body-adaptive"], default="template",
        help="排版：template=完全遵循底模（缺省）；body-adaptive=图片按正文宽度等比缩小、"
             "普通表格等宽并重复表头",
    )
    pexport_p.add_argument(
        "--landscape-chapters", default="",
        help="显式横向章节（逗号分隔章节标题）；仅作用于这些章，未形成独立节时按章前分页",
    )
    pexport_p.add_argument(
        "--page-break-before-chapter", action="store_true",
        help="章前分页（缺省沿用模板）",
    )
    pexport_p.add_argument(
        "--no-refresh", action="store_true",
        help="跳过 Word 字段刷新（只出可读稿，结果标为待刷新）",
    )
    pexport_p.add_argument(
        "--strict", action="store_true",
        help="严格模式：出现失败/待转换格式时按非零退出码返回",
    )
    pexport_p.add_argument(
        "--include-original", action="store_true",
        help="源码包内包含原件 original/source.docx（缺省不含）",
    )
    pexport_p.add_argument(
        "--retry-of", default="",
        help="按既有 export-result.json 仅补失败格式（使用原轮快照与 DOCX）",
    )
    pexport_p.add_argument(
        "--retry-formats", default="",
        help="与 --retry-of 搭配：只补这些格式（逗号分隔）；缺省补全部失败/待转换格式",
    )
    pexport_p.add_argument(
        "--output", choices=["human", "json"], default="human",
        help="输出形式：human 摘要 / json 单一机器报告",
    )    # ------------------------------------------------------------------
    # V3.0 30-F：正文复用入口（模块库 / 统一解析 / 选择性升级 / 产品变体）
    # 与界面模块库面板调用同一份服务入口，机器报告与退出码自带约定：
    # 0=有可用正文/结果，2=参数非法（项目或变体/模块不存在、严格模式未达标），
    # 1=完全无可用内容。
    # ------------------------------------------------------------------
    reuse = sub.add_parser(
        "reuse",
        help="模块库与正文复用："
             "`reuse list|show|extract|import|export|install`、"
             "`reuse resolve|upgrade`、`reuse variants|build|check|clone`",
    )
    reuse_sub = reuse.add_subparsers(dest="reuse_command")

    reuse_list = reuse_sub.add_parser("list", help="列出/检索本地模块库")
    _add_reuse_sources(reuse_list)
    reuse_list.add_argument("--query", default="", help="按名称/标签/正文/描述检索")
    reuse_list.add_argument("--tag", action="append", default=[], help="限定标签，可重复")
    _add_output(reuse_list)

    reuse_show = reuse_sub.add_parser("show", help="查看模块元数据与参数预览")
    _add_reuse_sources(reuse_show)
    _add_version_target(reuse_show)
    reuse_show.add_argument(
        "--param", action="append", default=[], help="参数覆盖 name=value，可重复（同 resolver 规则）"
    )
    reuse_show.add_argument("--body", action="store_true", help="同时输出未替换的模块原文")
    _add_output(reuse_show)

    reuse_extract = reuse_sub.add_parser(
        "extract", help="从已保存章节或明确缓冲快照提取模块（资源一并收集）"
    )
    _add_reuse_sources(reuse_extract)
    reuse_extract.add_argument("--chapter", required=True, help="宿主章节相对路径（相对 contentRoot）")
    reuse_extract.add_argument("--module-id", default="", help="模块 id（缺省按正文标题推断）")
    reuse_extract.add_argument(
        "--module-version", dest="module_version", default="1.0.0",
        help="模块版本（缺省 1.0.0）；本命令的 --version 归全局构建信息，勿混用",
    )
    reuse_extract.add_argument("--title", default="", help="模块标题")
    reuse_extract.add_argument("--tag", action="append", default=[], help="标签，可重复")
    reuse_extract.add_argument("--description", default="", help="模块说明")
    reuse_extract.add_argument(
        "--parameter", action="append", default=[],
        help="声明参数 name=默认值[:说明]，可重复",
    )
    reuse_extract.add_argument(
        "--current-buffer", default="",
        help="显式缓冲快照文件（界面未保存缓冲导出）；给出时按 current-buffer 来源提取，不读盘",
    )
    _add_output(reuse_extract)

    reuse_import = reuse_sub.add_parser("import", help="离线导入模块包（非法附件跳过并报告）")
    reuse_import.add_argument("source", nargs="+", help="模块目录（含 module.yml），可多个")
    reuse_import.add_argument(
        "--library", default="", help="目标库目录（缺省 <项目>/reuse/library 或当前目录 reuse/library）"
    )
    reuse_import.add_argument("--project", default="", help="项目目录（用于推导缺省库目录）")
    _add_output(reuse_import)

    reuse_export = reuse_sub.add_parser("export", help="导出选定的模块包（Markdown + 元数据 + 资源）")
    _add_reuse_sources(reuse_export)
    reuse_export.add_argument("--target", required=True, help="导出目标目录")
    reuse_export.add_argument(
        "--module", action="append", default=[],
        help="模块 id 或 id@version，可重复；缺省导出库中全部模块",
    )
    _add_output(reuse_export)

    reuse_install = reuse_sub.add_parser(
        "install", help="把库中的模块固定复制进项目 reuse/modules（出稿不再依赖库）"
    )
    reuse_install.add_argument("--project", required=True, help="项目目录")
    reuse_install.add_argument("--library", default="", help="模块库目录（缺省自动选择）")
    reuse_install.add_argument(
        "--module", action="append", default=[],
        help="模块 id 或 id@version，可重复；缺省安装项目装配里声明的全部模块",
    )
    _add_output(reuse_install)

    reuse_resolve = reuse_sub.add_parser(
        "resolve",
        help="按项目固定版本统一展开正文，输出解析报告（来源/hash/行号 + 兜底清单）",
    )
    _add_reuse_sources(reuse_resolve)
    reuse_resolve.add_argument("--variant", default="", help="按命名变体的有效内容解析")
    reuse_resolve.add_argument("--chapter", default="", help="只解析这一章（相对 contentRoot）")
    reuse_resolve.add_argument(
        "--with-text", action="store_true", help="机器报告内附展开后的正文文本"
    )
    reuse_resolve.add_argument(
        "--strict", action="store_true", help="严格模式：缺项算失败（退出码 2），默认只提示"
    )
    reuse_resolve.add_argument(
        "--record-instances", action="store_true",
        help="把明确纳入追踪的 slot 条目落盘为 reuse/instances.yml 并输出覆盖率",
    )
    reuse_resolve.add_argument(
        "--slots", default="", help="逗号分隔的 slot 列表（只登记这些）"
    )
    _add_output(reuse_resolve)

    reuse_upgrade = reuse_sub.add_parser(
        "upgrade",
        help="查看模块版本差异并选择性升级（缺省只预览，--apply 才写 reuse/assembly.yml）",
    )
    reuse_upgrade.add_argument("--project", required=True, help="项目目录")
    reuse_upgrade.add_argument("--library", default="", help="模块库目录（缺省自动选择）")
    reuse_upgrade.add_argument("--module", required=True, help="模块 id")
    reuse_upgrade.add_argument("--to", dest="target_version", default="", help="目标版本（缺省取库中最新）")
    reuse_upgrade.add_argument(
        "--slot", action="append", default=[], help="只升级这些 slotId，可重复；缺省全部受影响引用"
    )
    reuse_upgrade.add_argument(
        "--apply", action="store_true", help="确认并写盘（缺省仅预览差异，不改配置）"
    )
    _add_output(reuse_upgrade)

    reuse_variants = reuse_sub.add_parser(
        "variants", help="列出可用变体与其有效范围（章节/变量/模块版本）"
    )
    reuse_variants.add_argument("--project", required=True, help="项目目录")
    reuse_variants.add_argument("--variant", default="", help="查看该变体的有效范围")
    _add_output(reuse_variants)

    reuse_build = reuse_sub.add_parser(
        "build",
        help="按变体生成独立输出目录（各 variantId 互不覆盖）与范围机器报告",
    )
    reuse_build.add_argument("--project", required=True, help="项目目录")
    reuse_build.add_argument("--library", default="", help="模块库目录（缺省自动选择）")
    reuse_build.add_argument(
        "--variant", action="append", default=[],
        help="只构建这些变体，可重复；缺省构建 variants.yml 中的全部（无配置时等价默认项目）",
    )
    reuse_build.add_argument("--destination", default="", help="输出根目录（缺省 output/variants）")
    _add_output(reuse_build)

    reuse_check = reuse_sub.add_parser(
        "check",
        help="按变体做解析检查：缺模块/缺参数/循环/严格项（不写任何正文）",
    )
    reuse_check.add_argument("--project", required=True, help="项目目录")
    reuse_check.add_argument("--library", default="", help="模块库目录（缺省自动选择）")
    reuse_check.add_argument("--variant", default="", help="按该变体的有效内容检查")
    reuse_check.add_argument(
        "--strict", action="store_true", help="严格模式：缺项按退出码 2 返回"
    )
    _add_output(reuse_check)

    reuse_clone = reuse_sub.add_parser(
        "clone",
        help="导出已展开普通正文的新项目副本（普通 Markdown + 资源，可搬目录打开）",
    )
    reuse_clone.add_argument("--project", required=True, help="源项目目录（只读，不改动）")
    reuse_clone.add_argument("--library", default="", help="模块库目录（缺省自动选择）")
    reuse_clone.add_argument("--target", required=True, help="副本输出目录（必须不存在或是空目录）")
    reuse_clone.add_argument("--variant", default="", help="只导出该变体的有效内容")
    _add_output(reuse_clone)

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

    # V3.2 32-F：批次交付 CLI（与界面同源）。退出码：0=有可用结果（可含部分失败/
    # 待刷新）、1=完全没有可用结果或严格阈值未满足、2=参数或输入非法；
    # delivery-status 为只读查询，正常（含失败任务）返回 0，失败信息在报告内。
    def _add_delivery_plan_args(target: argparse.ArgumentParser) -> None:
        target.add_argument("--plan", required=True, help="schema 1 批次计划（.json/.yaml/.yml）")
        target.add_argument(
            "--base-dir", default="",
            help="成员/输出相对路径的基准目录（缺省为计划文件所在目录）",
        )
        target.add_argument("--destination", default="", help="覆盖所有成员的输出目录")
        target.add_argument(
            "--formats", default="", help="覆盖所有成员的目标格式（逗号分隔，如 docx,html）",
        )
        target.add_argument(
            "--variant", default="",
            help="覆盖所有成员的变体 ID（随任务/交付包登记；出稿按项目当前内容）",
        )
        target.add_argument(
            "--strict", action="store_true",
            help="显式严格交付策略：阈值未满足时退出 1，可读参考产物仍保留",
        )
        target.add_argument(
            "--no-refresh", action="store_true",
            help="本机不做 Word 刷新：逐项转「待刷新」，可在有 Word 的环境补",
        )
        target.add_argument(
            "--output", choices=("human", "json"), default="human",
            help="human 摘要 / json 单一机器报告",
        )
        target.add_argument("--json", action="store_true", help="等价 --output json")

    env_p = sub.add_parser(
        "env-check", help="受限环境自检：目录可写性 / docx 是否被透明加密 / 目标是否已存在",
    )
    env_p.add_argument("--dir", default="", help="要探测可写性的目录（缺省为当前目录）")
    env_p.add_argument("--docx", default="", help="要探测可读性的 .docx 路径")
    env_p.add_argument("--target", default="", help="准备导入到的项目目录（存在则提示）")
    env_p.add_argument("--output", choices=("human", "json"), default="human")
    env_p.add_argument("--json", action="store_true", help="等价 --output json")

    ipresets_p = sub.add_parser("intake-presets", help="导入映射预设：list / show / delete")
    ipresets_p.add_argument("preset_action", nargs="?", default="list",
                            choices=("list", "show", "delete"), help="操作（默认 list）")
    ipresets_p.add_argument("name", nargs="?", default="", help="预设名称或 id（show/delete 用）")
    ipresets_p.add_argument("--output", choices=("human", "json"), default="human")
    ipresets_p.add_argument("--json", action="store_true", help="等价 --output json")

    tflow_p = sub.add_parser(
        "team-flow",
        help="V3.1 串联流程：历史查证 → 待办分配 → 交接导出或应用（结果页报告）",
    )
    tflow_p.add_argument("--project", required=True, help="项目目录（含 project.yml）")
    tflow_p.add_argument("--chapters", default="", help="逗号分隔的章节（导出交接包用；缺省整份）")
    tflow_p.add_argument("--handoff", default="", help="交接包导出目录（目录，缺省为项目 output/交接）")
    tflow_p.add_argument("--package", default="", help="要应用的交接包（.zip 或目录）")
    tflow_p.add_argument("--apply", default="", help="应用时只应用这些章节（逗号分隔；缺省全部可应用）")
    tflow_p.add_argument("--assignee", default="", help="待办清点时按负责人筛选")
    tflow_p.add_argument("--assign-targets", dest="assign_targets", default="",
                         help="分配负责人时指定的目标（逗号分隔）")
    tflow_p.add_argument("--output", choices=("human", "json"), default="human")
    tflow_p.add_argument("--json", action="store_true", help="等价 --output json")

    dplan_p = sub.add_parser(
        "delivery-plan", help="预览批次计划成员/变体/格式/目标（只读，不执行）",
    )
    _add_delivery_plan_args(dplan_p)

    drun_p = sub.add_parser(
        "delivery-run", help="按计划入队并串行执行（部分成功保留，可中断继续）",
    )
    _add_delivery_plan_args(drun_p)
    drun_p.add_argument("--store", default="", help="批次队列 store 路径（缺省为用户配置目录）")
    drun_p.add_argument(
        "--continue", dest="continue_mode", action="store_true",
        help="继续上次未落定项（queued/interrupted）；已完成项默认跳过",
    )
    drun_p.add_argument(
        "--retry-failed", action="store_true",
        help="只重试失败/待刷新/部分完成项（复用该项原轮快照）",
    )
    drun_p.add_argument(
        "--cancel-after", type=int, default=None, metavar="N",
        help="执行 N 项后取消其余未开始项（已完成结果保留）",
    )

    dstatus_p = sub.add_parser(
        "delivery-status", help="查询批次队列与结果索引（只读，正常返回 0）",
    )
    dstatus_p.add_argument("--store", default="", help="批次队列 store 路径")
    dstatus_p.add_argument(
        "--index", action="append", default=[],
        help="额外结果来源：导出目录/export-result.json/交付包，可重复",
    )
    dstatus_p.add_argument("--plan", default="", help="可选：同时预览批次计划")
    dstatus_p.add_argument("--base-dir", default="", help="计划成员相对路径的基准目录")
    dstatus_p.add_argument(
        "--output", choices=("human", "json"), default="human", help="human 摘要 / json 机器报告",
    )
    dstatus_p.add_argument("--json", action="store_true", help="等价 --output json")

    dretry_p = sub.add_parser(
        "delivery-retry", help="只重试未完成项（复用原轮快照，不重走全部任务）",
    )
    dretry_p.add_argument("--store", required=True, help="批次队列 store 路径")
    dretry_p.add_argument("--job-id", action="append", default=[], help="只重试这些 jobId，可重复")
    dretry_p.add_argument(
        "--no-refresh", action="store_true", help="本机不做 Word 刷新：逐项转「待刷新」",
    )
    dretry_p.add_argument(
        "--output", choices=("human", "json"), default="human", help="human 摘要 / json 机器报告",
    )
    dretry_p.add_argument("--json", action="store_true", help="等价 --output json")

    dpkg_p = sub.add_parser(
        "delivery-package", help="生成自足交付包（.zip 或目录，包内一律相对路径）",
    )
    dpkg_p.add_argument(
        "--from", dest="source", default="",
        help="来源：一轮导出目录或 export-result.json（与 --store 二选一）",
    )
    dpkg_p.add_argument(
        "--store", default="", help="或从批次队列取（缺省取最后一个有可用结果的成员）",
    )
    dpkg_p.add_argument("--job-id", default="", help="配合 --store：指定成员任务")
    dpkg_p.add_argument(
        "--target", default="", help="输出 .zip 或目录（缺省为来源旁的 delivery-package.zip）",
    )
    dpkg_p.add_argument("--variant", default="", help="包内记录的变体 ID（缺省取任务记录）")
    dpkg_p.add_argument(
        "--include-original", action="store_true", help="包内包含原件 original/source.docx",
    )
    dpkg_p.add_argument(
        "--output", choices=("human", "json"), default="human", help="human 摘要 / json 机器报告",
    )
    dpkg_p.add_argument("--json", action="store_true", help="等价 --output json")

    dprom_p = sub.add_parser(
        "delivery-promote", help="换机按包内快照补刷新并本地登记（需 Word；无 Word 保持待刷新）",
    )
    dprom_p.add_argument("package", help="交付包路径（.zip 或目录）")
    dprom_p.add_argument(
        "--destination", default="", help="目标目录（缺省为包旁 <包名>-formalized）",
    )
    dprom_p.add_argument(
        "--word-available", choices=("auto", "yes", "no"), default="auto",
        help="显式声明本机 Word 可用性（缺省自动探测；no=只保留待刷新可读稿）",
    )
    dprom_p.add_argument(
        "--registry", default="", help="登记文件路径（缺省为 <目标目录>/delivery-registry.json）",
    )
    dprom_p.add_argument(
        "--source-project", default="", help="可选：原项目目录，仅用于提示源后来变化",
    )
    dprom_p.add_argument(
        "--output", choices=("human", "json"), default="human", help="human 摘要 / json 机器报告",
    )
    dprom_p.add_argument("--json", action="store_true", help="等价 --output json")
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

def _env_check_command(args) -> int:
    """受限环境自检：目录可写性、docx 是否被透明加密、目标是否已存在。

    退出码：0=未发现问题；3=发现环境问题（提示见 advice）。
    """
    from doc_tool.application.env_probe import diagnose_environment

    directory = str(getattr(args, "dir", "") or "") or None
    docx = str(getattr(args, "docx", "") or "") or None
    target = str(getattr(args, "target", "") or "") or None
    if not directory and target:
        directory = str(Path(target).parent)
    if not directory and not docx:
        directory = str(Path.cwd())
    result = diagnose_environment(
        directory=directory, docx=docx,
        target_exists=target if (target and Path(target).exists()) else None,
    )
    payload = result.to_dict()
    payload["schemaVersion"] = 1
    payload["directory"] = directory or ""
    payload["docx"] = docx or ""
    if getattr(args, "json", False) or str(getattr(args, "output", "human")) == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("环境自检：{0}".format("通过" if result.ok else "发现问题"))
        for item in result.checks:
            print("  [{0}] {1}：{2}".format("OK" if item["ok"] else "问题", item["kind"], item["detail"]))
        for item in result.advice:
            print("  建议：{0}".format(item))
    return 0 if result.ok else 3


def _intake_presets_command(args) -> int:
    """CORE R5：命名导入映射预设的查看/删除（保存经 `import --save-preset`）。"""
    from doc_tool.application.intake_presets import IntakePresets

    presets = IntakePresets()
    action = str(getattr(args, "preset_action", "") or "list")
    if action == "list":
        rows = [
            {"presetId": item.presetId, "name": item.name, "styles": len(item.mapping),
             "stylesMissing": len(item.unmatched) if hasattr(item, "unmatched") else 0}
            for item in presets.presets
        ]
        payload = {"schemaVersion": 1, "presets": rows, "path": str(presets.path) if hasattr(presets, "path") else ""}
        if getattr(args, "json", False) or str(getattr(args, "output", "human")) == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if not rows:
                print("（暂无导入预设；用 import --save-preset 名称 保存）")
            for row in rows:
                print("· {0}（{1} 个样式）".format(row["name"], row["styles"]))
        return 0
    name = str(getattr(args, "name", "") or "").strip()
    preset = presets.find(name)
    if preset is None:
        print("未找到导入预设：{0}".format(name), file=sys.stderr)
        return 2
    if action == "show":
        payload = preset.to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2) if (
            getattr(args, "json", False) or str(getattr(args, "output", "human")) == "json"
        ) else "预设：{0}\n样式映射：{1}".format(preset.name, preset.mapping))
        return 0
    if action == "delete":
        presets.delete(preset.presetId)
        print("已删除导入预设：{0}".format(preset.name))
        return 0
    print("未知操作：{0}".format(action), file=sys.stderr)
    return 2


def _team_flow_command(args) -> int:
    """V3.1 5.1：串联历史查证 → 待办分配 → 交接导出/应用，输出结果页报告。

    退出码：0=有可用结果或已完成动作；1=无可用结果且无可继续动作（blocked）；2=参数非法。
    """
    from doc_tool.application.content.team_flow import run_team_flow

    project = Path(str(getattr(args, "project", "") or ""))
    if not project.is_dir():
        print("项目目录不存在：{0}".format(project), file=sys.stderr)
        return 2

    def _items(value) -> list:
        if not value:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item) for item in value]

    chapters = _items(getattr(args, "chapters", ""))
    if chapters and getattr(args, "package", ""):
        print("--chapters 与 --package 不可同时使用：分别用于导出与应用。", file=sys.stderr)
        return 2
    if not chapters and not getattr(args, "package", ""):
        # 未指定章节时按整份项目内容串流程
        pass
    try:
        page = run_team_flow(
            project,
            chapters=chapters,
            handoff_dir=getattr(args, "handoff", "") or None,
            package=getattr(args, "package", "") or None,
            apply_selected=_items(getattr(args, "apply", "")) or None,
            assignee=str(getattr(args, "assignee", "") or ""),
            assign_targets=_items(getattr(args, "assign_targets", "")),
        )
    except Exception as exc:  # noqa: BLE001 - 参数/环境问题如实报错，不谎报通过
        print("团队流程未完成：{0}".format(exc), file=sys.stderr)
        return 2

    payload = page.to_dict()
    payload["summary"] = list(page.summary_lines())
    output = str(getattr(args, "output", "human") or "human")
    if getattr(args, "json", False):
        output = "json"
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in payload["summary"]:
            print(line)
    if page.blocked:
        return 1
    return 0


def _project_export_command(args) -> int:
    """项目统一出稿（CORE-H 8.1）：单一机器报告 + 明确退出码。

    退出码约定：0 = 有可用产物（含部分成功/待刷新/待转换）；1 = 完全没有可用产物；
    2 = 参数不可用（例如命令行请求 current-buffer）或严格模式未达标。
    保持 ``template-fill --output`` 的既有语义（DOCX 输出路径）不变。
    """
    import json
    from pathlib import Path

    from doc_tool.application.intake_contract import (
        FORMAT_DOCX, ExportRequest, ExportScope, SCOPE_CHAPTERS, SCOPE_CURRENT_CHAPTER,
        SOURCE_MODE_CURRENT_BUFFER, normalize_formats,
    )
    from doc_tool.application.project_export import (
        read_export_index, retry_export_formats, run_project_export,
    )

    project = Path(args.project)
    if not (project / "project.yml").is_file():
        print("项目目录缺少 project.yml：{0}".format(project), file=sys.stderr)
        return 2
    source_mode = getattr(args, "source_mode", "saved")
    if source_mode == SOURCE_MODE_CURRENT_BUFFER:
        print(
            "命令行没有界面缓冲：--source-mode current-buffer 不可用。"
            "请改用 --source-mode saved（默认），或在界面中按当前内容出稿。",
            file=sys.stderr,
        )
        return 2

    formats = normalize_formats(
        [item for item in (getattr(args, "formats", "") or "docx").split(",") if item.strip()]
    ) or [FORMAT_DOCX]
    chapters = [item.strip() for item in (getattr(args, "chapters", "") or "").split(",") if item.strip()]
    scope_kind = getattr(args, "scope", "project")
    scope = ExportScope(
        kind=scope_kind,
        chapters=chapters if scope_kind == SCOPE_CHAPTERS else [],
        current=(getattr(args, "current_chapter", "") or "") if scope_kind == SCOPE_CURRENT_CHAPTER else "",
    )

    def _progress(fmt, detail):
        print("[{0}] {1}".format(fmt, detail), file=sys.stderr, flush=True)

    retry_of = (getattr(args, "retry_of", "") or "").strip()
    if retry_of:
        prior = read_export_index(retry_of)
        if prior is None:
            print("无法读取原轮导出索引：{0}".format(retry_of), file=sys.stderr)
            return 2
        retry_formats = normalize_formats(
            [item for item in (getattr(args, "retry_formats", "") or "").split(",") if item.strip()]
        ) or prior.failed_formats() or formats
        with contextlib.redirect_stdout(sys.stderr):
            report = retry_export_formats(
                prior, retry_formats, skip_word_refresh=bool(getattr(args, "no_refresh", False)),
                progress=_progress,
            )
    else:
        request = ExportRequest(
            project_root=str(project),
            formats=formats,
            scope=scope,
            source_mode=source_mode,
            destination=getattr(args, "destination", "") or "",
            output_name=getattr(args, "output_name", "") or "",
            layout_profile=getattr(args, "layout", "template") or "template",
            layout={
                "mode": getattr(args, "layout", "template") or "template",
                "landscape_chapters": [
                    item.strip() for item in (getattr(args, "landscape_chapters", "") or "").split(",")
                    if item.strip()
                ],
                "page_break_before_chapter": bool(getattr(args, "page_break_before_chapter", False)),
            },
            refresh=not bool(getattr(args, "no_refresh", False)),
            strict=bool(getattr(args, "strict", False)),
            include_original=bool(getattr(args, "include_original", False)),
        )
        # 内核/管线会把过程输出打印到 stdout；机器报告必须保持纯净。
        with contextlib.redirect_stdout(sys.stderr):
            report = run_project_export(
                request, skip_word_refresh=bool(getattr(args, "no_refresh", False)),
                progress=_progress,
            )

    if getattr(args, "output", "human") == "json":
        print(json.dumps(report.machine_report(), ensure_ascii=False, indent=2))
    else:
        for line in report.summary_lines():
            print(line)
        for item in report.results:
            print("- {0}: {1} {2}".format(item.format, item.label(), item.path or item.message))
        print("索引：{0}".format(report.indexPath))

    if bool(getattr(args, "strict", False)) and report.strict_violations():
        print(
            "严格模式未达标：{0}".format("、".join(report.strict_violations())), file=sys.stderr,
        )
        return 2
    if report.all_failed():
        return 1
    return 0
def _reuse_split_target(value: str) -> tuple:
    """把 ``id`` 或 ``id@version`` 拆成 (id, version)。"""
    text = str(value or "").strip()
    if "@" in text:
        module_id, _, version = text.partition("@")
        return module_id.strip(), version.strip()
    return text, ""


def _reuse_parse_params(items) -> tuple:
    """解析 ``name=value`` 参数覆盖；返回 (映射, 错误信息)。"""
    values = {}
    for item in items or []:
        name, sep, value = str(item).partition("=")
        name = name.strip()
        if not sep or not name:
            return {}, "参数应为 name=value：{0!r}".format(item)
        values[name] = value.strip()
    return values, ""


def _reuse_parse_declared(items) -> tuple:
    """解析 ``name=默认值[:说明]`` 的模块参数声明；返回 (声明列表, 错误信息)。"""
    declared = []
    for item in items or []:
        name, sep, value = str(item).partition("=")
        name = name.strip()
        if not sep or not name:
            return [], "参数声明应为 name=默认值[:说明]：{0!r}".format(item)
        default, _, description = value.partition(":")
        declared.append(
            {"name": name, "default": default.strip(), "description": description.strip()}
        )
    return declared, ""


def _reuse_open_library(reuse, project, library_arg: str, explicit: bool):
    """打开需要查看/导出的库：显式 ``--library`` 优先，其余走上下文自动选择。"""
    if explicit:
        return reuse.load_library(project or Path.cwd(), library_arg)
    if project is None:
        return reuse.load_library(Path.cwd(), library_arg)
    return reuse.load_context(project).library


def _reuse_command(args) -> int:
    """V3.0 正文复用入口（30-F）：模块库、统一解析、选择性升级与产品变体。

    与界面模块库面板共用 ``doc_tool/application/content/reuse_commands.py`` 的同一份
    服务入口，因此跨入口拿到同一份解析结果与报告。

    退出码：0=有可用正文/结果；2=参数非法（项目或变体/模块不存在、严格模式未达标）；
    1=完全无可用内容。执行异常一律退出 2，不谎报通过。
    """
    from doc_tool.application.content import reuse_commands as reuse

    sub = str(getattr(args, "reuse_command", "") or "")
    if not sub:
        print(
            "请指定 reuse 子命令：list|show|extract|import|export|install|"
            "resolve|upgrade|variants|build|check|clone",
            file=sys.stderr,
        )
        return 2

    project_arg = str(getattr(args, "project", "") or "").strip()
    library_arg = str(getattr(args, "library", "") or "").strip()
    # 显式 --library 是权威来源：它覆盖「项目固定副本优先」的自动选择，
    # 否则 ``reuse list/show/export --library X`` 会被项目 reuse/modules 抢走。
    explicit_library = bool(library_arg)
    if project_arg:
        project = Path(project_arg)
        if not (project / "project.yml").is_file():
            print("项目目录缺少 project.yml：{0}".format(project), file=sys.stderr)
            return 2
    else:
        project = None
    if project is None and sub not in ("list", "show", "import"):
        print("该子命令需要 --project：{0}".format(sub), file=sys.stderr)
        return 2
    if sub == "import" and not library_arg and project is None:
        library_arg = str(Path.cwd() / "reuse" / "library")

    try:
        if sub == "list":
            library = _reuse_open_library(reuse, project, library_arg, explicit_library)
            payload = reuse.list_modules(
                library, query=getattr(args, "query", ""), tags=getattr(args, "tag", [])
            )
        elif sub == "show":
            library = _reuse_open_library(reuse, project, library_arg, explicit_library)
            module_id, inline_version = _reuse_split_target(args.module)
            params, error = _reuse_parse_params(getattr(args, "param", None))
            if error:
                print("[FAIL] {0}".format(error), file=sys.stderr)
                return 2
            payload = reuse.show_module(
                library,
                module_id,
                inline_version or getattr(args, "module_version", "") or "",
                params=params,
                with_body=bool(getattr(args, "body", False)),
            )
        elif sub == "extract":
            context = reuse.load_context(project, library_root=library_arg or None)
            buffer_text = ""
            buffer_path = str(getattr(args, "current_buffer", "") or "").strip()
            if buffer_path:
                source_file = Path(buffer_path)
                if not source_file.is_file():
                    print("缓冲快照文件不存在：{0}".format(source_file), file=sys.stderr)
                    return 2
                buffer_text = source_file.read_text(encoding="utf-8")
            declared, error = _reuse_parse_declared(getattr(args, "parameter", None))
            if error:
                print("[FAIL] {0}".format(error), file=sys.stderr)
                return 2
            payload = reuse.extract_chapter_module(
                context,
                getattr(args, "chapter", ""),
                module_id=getattr(args, "module_id", ""),
                version=getattr(args, "module_version", "1.0.0"),
                title=getattr(args, "title", ""),
                tags=getattr(args, "tag", []),
                description=getattr(args, "description", ""),
                parameters=declared,
                buffer_text=buffer_text,
                library_root=library_arg or None,
            )
        elif sub == "import":
            payload = reuse.import_modules(library_arg, args.source)
        elif sub == "export":
            export_library = _reuse_open_library(reuse, project, library_arg, explicit_library)
            targets = [_reuse_split_target(item) for item in (getattr(args, "module", None) or [])]
            if not targets and export_library is not None:
                targets = sorted({(module.moduleId, "") for module in export_library.modules()})
            payload = reuse.export_modules(export_library, targets, args.target)
        elif sub == "install":
            context = reuse.load_context(project, library_root=library_arg or None)
            targets = [_reuse_split_target(item) for item in (getattr(args, "module", None) or [])]
            if not targets:
                targets = [(slot.moduleId, slot.version) for slot in context.assembly.slots]
            if not targets:
                print(
                    "没有可安装的模块：请用 --module id[@version] 指定，或先写 reuse/assembly.yml。",
                    file=sys.stderr,
                )
                return 2
            payload = reuse.install_modules(context, targets)
        elif sub == "resolve":
            chapter = str(getattr(args, "chapter", "") or "").strip()
            variant_id = str(getattr(args, "variant", "") or "").strip()
            if chapter and variant_id:
                print(
                    "--chapter 与 --variant 不可同时使用：请分别解析单章与变体有效内容。",
                    file=sys.stderr,
                )
                return 2
            context = reuse.load_context(project, library_root=library_arg or None)
            if chapter:
                plan = reuse.plan_project(context, variant_id=variant_id)
                resolved = reuse.resolve_chapter(
                    context, chapter, plan=plan, strict=bool(getattr(args, "strict", False))
                )
                usable = not (resolved.missing or resolved.unreadable)
                payload = {
                    "ok": usable,
                    "projectRoot": str(context.project_root),
                    "chapters": [chapter],
                    "chaptersDetail": [resolved.to_dict(withText=True)],
                    "sources": list(resolved.sources),
                    "warnings": list(context.warnings) + list(plan.warnings),
                    "degradation": list(resolved.resolution.warnings),
                    "usableChapters": 1 if usable else 0,
                    "status": "ok" if usable else "empty",
                    "exitCode": reuse.EXIT_OK if usable else reuse.EXIT_EMPTY,
                }
                if resolved.resolution.errors:
                    payload["status"] = "invalid"
                    payload["exitCode"] = reuse.EXIT_USAGE
                    payload["strictErrors"] = list(resolved.resolution.errors)
            else:
                slots = [item for item in str(getattr(args, "slots", "") or "").split(",") if item]
                payload = reuse.resolve_project(
                    context,
                    variant_id=variant_id,
                    strict=bool(getattr(args, "strict", False)),
                    withText=bool(getattr(args, "with_text", False)),
                    record_instances=bool(getattr(args, "record_instances", False)),
                    slot_ids=slots or None,
                )
        elif sub == "upgrade":
            context = reuse.load_context(project, library_root=library_arg or None)
            payload = reuse.upgrade_apply(
                context,
                getattr(args, "module", ""),
                getattr(args, "target_version", "") or "",
                slot_ids=getattr(args, "slot", None) or None,
                dry_run=not bool(getattr(args, "apply", False)),
            )
        elif sub == "variants":
            context = reuse.load_context(project, library_root=library_arg or None)
            payload = reuse.variant_evidence(context, getattr(args, "variant", ""))
            payload.setdefault("exitCode", reuse.EXIT_OK if payload.get("ok") else reuse.EXIT_USAGE)
        elif sub == "build":
            context = reuse.load_context(project, library_root=library_arg or None)
            payload = reuse.build_variant_documents(
                context,
                variant_ids=getattr(args, "variant", None) or None,
                output_dir=getattr(args, "destination", "") or None,
            )
        elif sub == "check":
            context = reuse.load_context(project, library_root=library_arg or None)
            strict = bool(getattr(args, "strict", False))
            payload = reuse.resolve_project(
                context, variant_id=getattr(args, "variant", ""), strict=strict
            )
            problems = list(payload.get("degradation") or [])
            payload["checkedWarnings"] = len(problems)
            if payload.get("status") == "empty":
                payload["ok"] = False
            if problems and strict:
                payload["status"] = "invalid"
                payload["exitCode"] = reuse.EXIT_USAGE
        elif sub == "clone":
            context = reuse.load_context(project, library_root=library_arg or None)
            target = Path(str(getattr(args, "target", "")))
            if target.exists() and any(target.iterdir()):
                print("副本目标目录已存在且非空，未覆盖：{0}".format(target), file=sys.stderr)
                return 2
            payload = reuse.write_expanded_copy(
                context, target, variant_id=getattr(args, "variant", "")
            )
        else:
            print("未知 reuse 子命令：{0}".format(sub), file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - 执行失败必须以 2 退出，不谎报通过
        print("[FAIL] reuse {0} 执行失败：{1}".format(sub, exc), file=sys.stderr)
        return 2

    if getattr(args, "output", "human") == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(reuse.render_payload_text(sub, payload))
    code = payload.get("exitCode")
    return int(code) if code is not None else 0

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
def _assist_command(args) -> int:
    """写作辅助命令（33-E）：与门面同源，只输出结构化/人读结果。"""
    from doc_tool.application.assist import cli_commands

    payload = cli_commands.run(args.command, args)
    output = "json" if getattr(args, "output", "human") == "json" else "human"
    print(cli_commands.render(payload, output=output))
    return 0 if payload.get("success", True) else 1

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
    if args.command == "env-check":
        return _env_check_command(args)
    if args.command == "intake-presets":
        return _intake_presets_command(args)
    if args.command == "team-flow":
        return _team_flow_command(args)
    if args.command == "project-export":
        # 统一出稿自带机器报告与退出码约定，不走质量命令的序列化通道。
        return _project_export_command(args)
    if args.command == "convert":
        # 互转不依赖项目，也不走质量命令的序列化通道。
        return _convert_command(args)
    if args.command == "template-fill":
        return _template_fill_command(args)
    if args.command == "pdf":
        return _pdf_command(args)
    if args.command == "reuse":
        # 正文复用入口自带机器报告与退出码约定，不走质量命令的序列化通道。
        return _reuse_command(args)
    if args.command in (
        "delivery-plan", "delivery-run", "delivery-status",
        "delivery-retry", "delivery-package", "delivery-promote",
    ):
        # 批次交付 CLI 自带机器报告与退出码约定（0/1/2），不走质量命令序列化通道。
        from doc_tool.application.delivery import cli_commands as delivery_cli

        return delivery_cli.main(args)
    if args.command in ("assist-search", "assist-suggest", "assist-adopt", "assist-provider"):
        return _assist_command(args)

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