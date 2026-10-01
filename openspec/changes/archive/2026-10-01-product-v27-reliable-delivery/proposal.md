## Why

正式项目构建、模板填充、普通互转和评审稿使用不同的渲染路径，代码块、图表和复杂页面的效果存在差异；现有发布管线缺少统一产物终审。团队需要在 V2.6.x 基线之上建立可预测的 Word 表达与发布质量契约。

## What Changes

- 统一项目出稿、模板填充、评审稿的结构化表达：代码块、离线 Mermaid 流程图/时序图、图表题注、交叉引用、显式横向节与分页。
- 建立共享解析/渲染契约与来源定位，修复相关导入/往返校验，普通互转按支持矩阵给出差异提示。
- 统一开发态与冻结包的结构预览路径；预览仍不承诺 Word 分页完全一致。
- 增加构建前检查与产物终审，默认自动修复/降级并带提醒出稿；严格交付由用户显式选择。缺图、图渲染失败、引用和分节问题有可用兜底，不要求逐项放行理由，无法安全产出才停止。
- 提供统一 `check` 命令以及结构化构建报告，GUI 与 CLI 使用同一门禁。
- 发布快照补齐表达/检查报告；在三类真实文档中验证代码、图片、表格、引用与页眉页脚。

## Capabilities

### New Capabilities

- `docx-expression-contract`: 多入口共享的 Word 表达、预处理、近似预览及导入保真契约。
- `release-quality-gates`: 默认兜底出稿、源检查/终审、显式严格交付和安全登记。
- `document-check-cli`: `check`、结构化构建输出与 GUI/CLI 一致性。

### Modified Capabilities

无。现有 `content-editor` 的近似预览要求保持，由新增表达契约补充支持范围。

## Impact

- 涉及 `scripts/{build_docx,docx_common,validate_docx}.py`、`adapters/{kernel,importer,roundtrip}.py`、`application/{pipeline,template_fill,markdown_word,cli_commands}.py`、预览/Mermaid/评审渲染及打包配置。
- 在 `project.yml` v1 增加可选门禁字段，旧项目缺省行为兼容；不在本版做 Manifest v2 和整包内核搬迁。
- 前置：本批直接依赖的 V2.6 服务及相关检查可用；无关遗留/实机缺环境不阻止独立开发。下一版为 `product-v28-team-standardization`。
