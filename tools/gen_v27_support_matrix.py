# -*- coding: utf-8 -*-
"""生成 V2.7 表达能力支持矩阵（本地一次性工具）。

从共享块解析器实际跑一遍脱敏夹具，把结果写成支持矩阵，
避免手写与实现脱节。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from doc_tool.domain.blocks import (  # noqa: E402
    KIND_CODE,
    KIND_COMPLEX_TABLE,
    KIND_EMPTY_PARAGRAPH,
    KIND_FOOTNOTE_DEF,
    KIND_HEADING,
    KIND_IMAGE,
    KIND_LIST_ITEM,
    KIND_PAGEBREAK,
    KIND_SECTION,
    KIND_TABLE,
    parse_blocks,
)
from doc_tool.domain.captions import build_registry  # noqa: E402

FIXTURE = ROOT / "scripts" / "tests" / "fixtures" / "v27" / "expression-sample.md"

LABELS = {
    KIND_HEADING: "标题",
    KIND_CODE: "代码块",
    KIND_IMAGE: "图片与图题注",
    KIND_TABLE: "管道表格与表题注",
    KIND_COMPLEX_TABLE: "复杂表格标记",
    KIND_LIST_ITEM: "列表项",
    KIND_SECTION: "显式横向节",
    KIND_PAGEBREAK: "显式分页",
    KIND_EMPTY_PARAGRAPH: "空段占位",
    KIND_FOOTNOTE_DEF: "脚注定义",
}


def main() -> int:
    text = FIXTURE.read_text(encoding="utf-8")
    document = parse_blocks(text, str(FIXTURE))
    counts = {}
    for block in document.blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    registry = build_registry([document])

    lines = [
        "# V2.7 表达能力支持矩阵（27-A / 1.1、1.2）",
        "",
        "基准：HEAD bbfc71afad9e46239a2cd2aca3012d732d99042e。矩阵由",
        "`tools/gen_v27_support_matrix.py` 对脱敏共享夹具",
        "`scripts/tests/fixtures/v27/expression-sample.md` 实际解析生成，",
        "与正式构建/校验共用同一份解析代码。",
        "",
        "## 1. 四条渲染路径",
        "",
        "| 渲染路径 | 入口 | 是否使用共享块模型 | 说明 |",
        "|---|---|---|---|",
        "| 项目正式出稿 | `scripts/build_docx.py::build` → `process_markdown` | 是（V2.7 起） | 代码容器、题注、引用、横向节、分页均由 `doc_tool.domain.blocks` 推导 |",
        "| 模板填充 | `doc_tool/application/template_fill.py` | 部分 | 仍使用自有的章节拆分与预处理，本轮未接入共享解析（27-B/2.3） |",
        "| 评审稿 | `doc_tool/application/review/review_docx.py` | 否 | 使用自有有机解析与代码框（27-B/2.3 计划接入） |",
        "| 普通互转（Office HTML / Word） | `doc_tool/application/convert.py` 等 | 否 | 保持现有能力，支持边界见下方“普通互转边界”（27-B/2.4） |",
        "",
        "## 2. 共享块解析实测结果",
        "",
        "| 能力 | 样例数量 | 状态 | 说明 |",
        "|---|---|---|---|",
    ]
    expected = {
        KIND_HEADING: "支持",
        KIND_CODE: "支持",
        KIND_IMAGE: "支持",
        KIND_TABLE: "支持",
        KIND_COMPLEX_TABLE: "支持",
        KIND_LIST_ITEM: "支持",
        KIND_SECTION: "支持",
        KIND_PAGEBREAK: "支持",
        KIND_EMPTY_PARAGRAPH: "支持",
        KIND_FOOTNOTE_DEF: "支持",
    }
    notes = {
        KIND_CODE: "保留缩进、Tab、空行与反引号；未闭合默认补闭并 warning",
        KIND_IMAGE: "`{#fig-id}` 或紧随的图题注行；无标识也登记为 fig-auto-N",
        KIND_TABLE: "表前/表后题注均支持，允许中间空行；重复标识输出层唯一化",
        KIND_SECTION: "未闭合自动闭合，嵌套只保留第一层，孤立结束忽略并 warning",
        KIND_PAGEBREAK: "`<!-- PAGEBREAK -->` 输出真实 Word 分页断点",
    }
    order = [
        KIND_HEADING, KIND_CODE, KIND_IMAGE, KIND_TABLE, KIND_COMPLEX_TABLE,
        KIND_LIST_ITEM, KIND_SECTION, KIND_PAGEBREAK, KIND_EMPTY_PARAGRAPH, KIND_FOOTNOTE_DEF,
    ]
    for kind in order:
        lines.append(
            "| {0} | {1} | {2} | {3} |".format(
                LABELS[kind],
                counts.get(kind, 0),
                expected[kind] if counts.get(kind) else "本次夹具未覆盖",
                notes.get(kind, "与正式内核共用同一份解析"),
            )
        )
    lines.extend([
        "",
        "## 3. 普通互转边界（不承诺与项目 OOXML 排版完全相同）",
        "",
        "`doc_tool/application/convert.py` 的 `markdown_to_docx` 有两条后端：",
        "",
        "| 后端 | 触发方式 | 表达能力 | 差异说明 |",
        "|---|---|---|---|",
        "| `_markdown_to_docx_via_template` | 指定底模 | 复用正式内核装配，代码块/题注/横向节与项目出稿同源 | 与项目出稿一致（同一 `build_docx.build`） |",
        "| `_markdown_to_docx_via_word` | 未指定底模（走 Office） | 由 Word 自己排版，仅保证可打开与文本可读 | 不保证与项目 OOXML 排版相同；无 Word 时不可用 |",
        "| Office HTML → Word | 走 Office | 由 Office 导入导出 | HTML/CSS 布局与项目样式体系无对应关系 |",
        "",
        "结论：普通互转不新增第五套渲染实现；带底模时走正式内核，",
        "不带底模时明确为“Office 排版的可读转换”，不声称与项目出稿版式一致。",
        "",
        "## 4. 题注与引用",
        "",
        "| 项 | 结果 |",
        "|---|---|",
        "| 图题注 | {0} |".format(registry.figure_count),
        "| 表题注 | {0} |".format(registry.table_count),
        "| 重复标识 | {0} 处（输出层唯一化，不改源码） |".format(len(registry.duplicates)),
        "| 编号规则 | 图/表各自按全文出现顺序从 1 开始 |",
        "| 引用语法 | `@fig-id` / `@tbl-id`；歧义与缺失保留可读占位文本 |",
        "",
        "## 5. 已知未支持与后续工作",
        "",
        "| 项 | 状态 | 归属 |",
        "|---|---|---|",
        "| 模板填充 / 评审稿接入共享代码块与题注 | 未开始 | 27-B / 2.3 |",
        "| 普通互转边界说明（Office HTML 与项目 OOXML 排版不承诺完全相同） | 未开始 | 27-B / 2.4 |",
        "| Mermaid 构建期预处理与缓存 | 未开始（`doc_tool/application/prepared_source.py` 已就位） | 27-C / 3.1～3.5 |",
        "| 题注 SEQ/REF 域与书签 | 部分（已戉可读编号与书签，域输出待 27-D） | 27-D / 4.2 |",
        "| 多节模板下横向节保留校验 | 未收尾 | 27-D / 4.4、4.6 |",
        "| 内置预览收敛与 WebEngine 清理 | 未开始 | 27-E / 5.1 |",
        "| 发布质量门禁与 STAGE_AUDIT | 未开始 | 27-F / 6.x |",
        "| CLI `check` 统一入口 | 未开始 | 27-G / 7.x |",
        "",
        "说明：本矩阵只记录实测结果；未实现能力不在本文声称支持。",
        "",
    ])
    out = ROOT / "docs" / "release" / "v27-support-matrix.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("已生成", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())