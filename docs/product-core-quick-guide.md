# 主流程快速指南（导入 → 编辑 → 出稿 → 再次修订）

配套：[主功能优化计划](product-core-workflow-plan.md)、[易用性契约](product-core-usability-contract.md)、[兜底原则](product-flow-fallback-policy.md)、[执行台账](product-core-workflow-execution.md)。本页描述**当前已实现**的默认流程与支持范围；未实现项在文末单列，不在界面宣称可用。

## 1. 导入一份文档（默认路径）

1. 首页「新建项目…」或文件菜单「导入文档（Word / Markdown）…」（Ctrl+N）→ 选择 DOCX/DOC/Markdown。
2. 系统自动识别格式并调用对应建项服务：Word 走导入向导，Markdown 按列表顺序建**一份**项目，规范包目录走规范包建项。
3. 普通模式默认值：文档名取可信名称（否则文件名）、位置取有效默认目录、编号可空、版本默认 `1.0`；Word 保持源格式，Markdown 用通用模板。
4. 完成后直接进入编辑。已有工作区发起导入时**不切走**当前编辑，新项目在新窗口打开。

无标题样式 → 自动按单章接管全部可读正文；标题跳级 → 按整理计划补上级结构（结果中说明整理动作）；标题前正文 → 按明确范围保留为「前言」章（若只是封面图片则按底模封面处理并保留原件）。

## 2. 复杂内容与缺资源

- 公式/文本框/脚注/批注/修订等暂不可编辑对象：正文保留位置，原件保留在 `original/source.docx`，导入记录 `original/import-record.json` 分别标明**可编辑保留 / 参考文本降级 / 原件留存**，不会把“原件留存”说成“已可编辑”。
- 缺一张图片：正文留可见占位 `[[待完善：图片｜来源：…]]`，导入继续，结果说明“对照未完成”的原因。
- 严格模式（项目信息 → 高级选项勾选“严格往返”）按阈值在**发布前**拒绝新项目，源文件与诊断保留；普通模式不因缺口阻断。
- 试构建失败会先用通用底模**重试一次**；仍失败才判定该输入失败，并留下诊断日志。

## 3. 出稿（Word / PDF / 离线 HTML / 源码包）

统一入口：`project-export`（CLI）或界面出稿动作。默认：整份文档 + 当前编辑内容 + Word + 有效导出目录。

```
doc-tool project-export --project <项目目录> [--formats docx,pdf,html,source-zip]
                        [--scope project|current-chapter|chapters] [--chapters a,b]
                        [--destination 目录] [--source-mode saved|current-buffer]
                        [--layout template|body-adaptive] [--landscape-chapters 标题]
                        [--page-break-before-chapter] [--no-refresh] [--strict]
                        [--include-original] [--retry-of export-result.json]
                        [--output human|json]
```

- 一轮出稿基于**同一份内容快照**（`captureId` 固定）：捕获后继续编辑不影响本轮结果，源文件不被改写、脏标记不清除。
- 命令行没有界面缓冲：`--source-mode current-buffer` 会被明确拒绝，默认 `saved`。
- 缺 Word：仍给可读 DOCX（状态“待刷新”）与离线 HTML，PDF 标“待转换”。
- 已生成可读 DOCX 即可打开；字段刷新/PDF 转换随后进行。
- 同名冲突采用安全新名（`名称-2.docx`）；单格式失败不影响其它已完成结果。
- 只补失败格式：`--retry-of <export-result.json> --retry-formats pdf` 使用**原轮**快照与 DOCX。
- 输出目录失效：自动回退到有效项目/用户导出目录并在结果中写明实际位置，已选范围与格式保留。
- 聚合索引：`export-result.json`（schema 1）记录 captureId、范围/来源、各格式 path/hash/status/backend/warnings。

## 4. 范围、映射预设与文件批次（服务层）

- 章节范围：只纳入所选章节（按项目顺序），自动保留上级结构；范围外引用集中在结果说明。
- 映射预设：`intake-presets.json`（与模板填充配方分开存储）；失配项回退自动识别/单章并记录实际决定。
- Word 批次：一文件一项目、串行、同名安全后缀、失败/待转换项可只重试失败部分、取消保留已完成项目。
- Markdown 批次：多文件按确认顺序建成一份项目，支持资源根与底模。

## 5. 再次修订（外部 Word 修改接回）

已打开项目中选择外部修订稿 → 走既有差异重导入（预览/选择应用/冲突跳过），不新建项目、不覆盖整个项目；本轮来源作为**新来源版本**登记（`original/versions/`），旧原件不被覆盖。

## 6. 有限 Word 排版

默认**完全遵循底模**。选择「正文自适应」时只做三件有确定规则的事：普通图片按当前节正文宽度等比缩小（小图不放大）、普通表格设置列宽并重复表头、显式章前分页与章级横向（该章未形成独立节时按章前分页处理并说明）。复杂表格默认原样保留；超宽内容保留并定位提醒，不隐藏列、不裁剪图片、不任意缩小字号。

## 7. 本轮未实现 / 待验收（不要当作可用）

- 界面级：结果页的“打开文件/目录 / 就地替换图片 / 查看原件”深链接、进度百分比展示、1280×720 与 125%/150% 缩放的实际可达性检查。
- 实机：Word 版式观感、字段刷新后的目录/页码正确性、冻结包（PyInstaller）出稿、断网源码包构建。
- 尚未实现的任务编号见 [执行台账](product-core-workflow-execution.md)（CORE 31/40）。
