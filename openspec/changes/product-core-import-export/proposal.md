## Why

企业研发文档团队每天最频繁的工作是接管现有文档、修改正文并再次交付。现有功能已经覆盖导入向导、模板填充、格式互转和只读 HTML，但复杂内容确认、章节选择、未保存内容处理与多格式出稿仍分散，优先打通这些主流程比继续增加外围功能更直接。

## What Changes

- 增加独立的主流程优化包，排在 V3.0 正文复用之前；不重置正在执行的 V2.6～V2.9 任务，也不修改已规划四版的任务编号。
- 收敛接管 Word、Markdown 建项目和临时格式转换的入口；普通导入默认采用可用结果，无标题按单章接管，疑似标题可预览调整，复杂内容不再要求逐项确认才能继续。
- 增加导入范围、可复用样式映射及 Word 文件批次；一份文件失败不影响其他项目，保留原文件和明确的未保留内容位置。
- 增加范围明确的有效内容快照，包含所选章节、资源和用户选择的当前缓冲或已保存内容，供预览、检查和所有出稿格式共同使用。
- 增加统一导出入口：整份/当前章/勾选章节、Word/PDF/HTML/源码包、常用设置、结果打开及仅补失败格式；PDF 使用生成的 Word，缺 Word 保留 DOCX/HTML 并标记待转换。
- 增加有限的 Word 排版优化：图片按正文可用宽度等比缩放、表头跨页重复、正文表格可控宽度及显式横向章节，复杂表格原样保留时不擅自改写；只汇总待完善项。
- 明确日常交互契约：统一导入入口自动识别格式并真实调用建项服务，默认值可直接开工；快速导出默认整份/当前内容/Word，进阶设置折叠，结果可直接打开，问题就地修复。首个可用版本按主流程交付，批量、精细排版和源码包随后补齐。

## Capabilities

### New Capabilities

- `best-effort-project-intake`: 默认可用导入、章节范围与结构调整、映射预设、文件批次及再次导入入口。
- `source-preservation-ledger`: 原文件快照、复杂内容位置和处理记录、可见占位与原件查看。
- `effective-content-snapshot`: 范围与当前缓冲统一捕获、同源预览/检查/导出、进度和取消。
- `unified-project-export`: 多格式出稿、有限排版策略、源码包、格式结果和局部重试。

### Modified Capabilities

无。新增编排层复用现有编辑、保存、导入、重导入和生成能力，旧入口保留适配，不改变其文件格式契约。

## Impact

- 涉及 `application/import_project.py`、`intake_word.py`、`project_from_markdown.py`、`prepared_source.py`、`pipeline.py`、`convert.py`、`content/reimport*.py`、`export/` 与对应 GUI/CLI 入口。
- 复用现有 `original/source.docx`、资源与复杂表格机制、TaskRunner、ContentWriter、OutputState 和构建历史；新增可选的导入记录、快照与导出索引，不创建另一个正式发布状态。
- 保持 project schema 1/2；不要求登录、云服务、模型、OCR、整版 V3 功能或 Word 实机验收完成才能推进独立任务。
- 共 8 批/40 项。产品范围见 `docs/product-core-workflow-plan.md`，执行记录独立写入 `docs/product-core-workflow-execution.md`。
- 易用性标准见 `docs/product-core-usability-contract.md`；要求并入既有 40 项，不增加任务编号或通用交互平台，先验证真实文件和产物闭环。
