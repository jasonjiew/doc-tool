# Doc Tool 三阶段迭代计划（编排层）

> 依据：`analysis/feature-audit.md`（基于 HEAD `12e8483` / v2.5.1）。
> 本文件只做编排；每个阶段对应一个 OpenSpec 变更（proposal / design / tasks），按 `openspec/changes/<name>/` 实施与验收。
> 取代 `docs/roadmap.md` 中已完成的计划 1~6 之后的后续排程；`docs/roadmap.md` 保留为历史。

## 总览

| 阶段 | 版本 | OpenSpec 变更 | 主题 | 周期 | 依赖 |
|---|---|---|---|---|---|
| 一 | v2.6 | `phase1-delivery-quality-quickwins` | 交付质量速赢：代码块、发布终审、`check` 门禁、Local History、术语库、修订预填、预览引擎统一、证书出仓 | 1~2 月 | 无 |
| 二 | v2.7 / v2.8 | `phase2-word-expression-and-collab` | Word 表达与协作：Mermaid 出图、题注/交叉引用、横向节、Manifest v2、设置页、导入保真、冲突视图、重导入预览、工程重构 | 2~4 月 | 阶段一 `docx_blocks`/`STAGE_AUDIT`/`gates` |
| 三 | v3.0+ | `phase3-product-evolution` | 产品级演进：staged/promote、Include、章节历史、提交门禁与评审联动、HTML 评审包、AI provider、锁租约、命令注册表 | 按需裁剪 | 阶段二 `STAGE_PREPARE`/内核入包 |

## TOP 20 → 阶段映射

| # | 建议 | 阶段 |
|---|---|---|
| 1 | 代码块容器 | 一 |
| 2 | Mermaid 构建期出图 | 二 |
| 3 | 发布终审 `STAGE_AUDIT` | 一 |
| 4 | 题注 + 交叉引用 | 二 |
| 5 | 预览引擎一致性 | 一 |
| 6 | 证书出仓 | 一 |
| 7 | 导入行内格式/列表层级 | 二 |
| 8 | 复杂表影子 Markdown | 二 |
| 9 | `doc-tool check` / `build --output json` / 前置 Lint | 一 |
| 10 | Manifest v2（chapters/variables） | 二 |
| 11 | Git 冲突解决视图 | 二 |
| 12 | 重新导入异步 + 预览 | 二 |
| 13 | Local History + 回收站 | 一 |
| 14 | 项目设置页扩展 | 二 |
| 15 | 企业术语库 | 一 |
| 16 | 修订记录预填 | 一 |
| 17 | 横向节 | 二 |
| 18 | 接入已有服务（trace CLI / 构建历史 / 基线 / HTML 评审包） | 一（trace、历史）/ 三（HTML 包） |
| 19 | `main_window` 拆分 + 内核入包 + coverage 回 CI | 二 |
| 20 | staged/promote + AI provider | 三 |

## 明确不做

Web 实时协同；自研排版/PDF 引擎；PDF 工具箱新增项；PlantUML / Draw.io / 数学公式；审批流 / 电子签章 / 归档系统；AI 问答、AI 自动改写、AI 自动更新文档；所见即所得复杂表编辑器（除非阶段二影子表被证明不够）。

## 落地机制

- 每个阶段以 `openspec-apply-change` 实施，`tasks.md` 逐项勾选；阶段 design.md 的"验收标准"全部通过后 `openspec-archive-change` 归档并同步 `openspec/specs/`。
- 阶段内可拆小版本（阶段二建议 v2.7 / v2.8）；阶段三各节相互独立可裁剪。
- 每完成一个阶段，更新本文件总览表状态列。
