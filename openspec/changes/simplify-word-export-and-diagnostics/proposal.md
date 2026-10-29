# Word 导出、交互与样式优化

> 2026-10-29 整合修订：在同一个 change 中完成六项交互修正与本次样式优化。统一执行入口为 `tasks.md`，界面说明为 `ui-interaction-plan.md`；沿用已有任务编号和完成记录，新增样式任务不代勾。先闭合功能，再应用样式，最后统一验收，不重做前次导出重构。

## Why

用户的主线是“Word 拆成 Markdown → AI 修改 → 合回 Word”。当前导出同时暴露快速构建、正式出稿、导出设置和多种重试动作；截图中的失败只给出临时目录下 `img_0172.png` 不存在，无法直接定位章节或找回完整诊断。本次以“先确认简洁设置，再开始生成”为默认流程，异常时直接说明原因、位置和可执行的下一步。

## What Changes

- 将桌面日常出稿收敛为“导出 Word…”主按钮、“更多”菜单和简短的最近结果入口；主按钮先打开同一简洁设置页，用户确认后点击“开始生成”。
- 顶部按钮、菜单与 Ctrl+E 共用设置与提交路径；自动预填文件名、位置、范围和内容来源，默认整份、当前内容及原有模板，高级属性与排版选项折叠；提交不隐式保存全部正文。
- 普通完成在原结果面板反馈，按真实状态推荐一个主要动作；重试保持本次捕获，使用当前内容重新生成明确另建一次导出。
- 把快照准备、资源预处理、构建、校验、Word 刷新和成果写入的诊断接到同一结果记录；自动保存机器事实与同源 Markdown 诊断，关闭面板、重开项目后仍可查看。
- 先复现普通图片与 Mermaid 混排的资源根覆盖问题，再统一构建与校验的资源解析和源位置映射；失败说明回到原 Markdown，而非只展示临时路径。
- 保留原件、源 Markdown、未保存缓冲、已有成果和正式状态判定；缺 Word 继续提供可读稿与真实“待刷新”状态。
- 复用现有蓝色主操作、深浅主题和中文字体层级，统一主页面动作、导出表单、结果与错误信息的视觉层级和间距；设置仍先确认，正常操作次数不增加。

## Capabilities

### New Capabilities

- `export-diagnostics`：导出全阶段诊断的采集、关联、持久化、兼容读取与 Markdown 呈现；不承担新的业务生命周期。

### Modified Capabilities

- `pyside6-app-shell`：调整项目条的默认导出操作及其与菜单、快捷键的共同执行契约，补充主题一致的按钮层级、表单反馈和窄窗可达要求。
- `work-detail-pane`：结果卡片的主要动作、非模态反馈、源位置、技术详情和历史恢复，补充短原因、状态与路径的阅读层级。
- `docx-expression-contract`：补充生成图与原始图片混排时的资源身份、构建/校验一致性及失败定位要求。
- `content-editor`：本次补充低频工具固定收纳，以及导出前识别外部修改与未保存缓冲冲突的行为；复用现有编辑器和来源选择。

## Impact

- 导出入口与设置：`doc_tool/ui/project_bar.py`、`main_window.py`、`export_settings_dialog.py`、`controllers/export_orchestrator.py`；复用现有 TaskRunner、ExportRequest 和 EffectiveSnapshot。
- 结果与诊断：`doc_tool/application/project_export.py`、`intake_contract.py`、`pipeline.py`，以及 `doc_tool/ui/export_rounds.py`、`export_results_view.py`、`task_dock.py`。
- 资源处理：`doc_tool/application/prepared_source.py`、`doc_tool/adapters/kernel.py`、`scripts/build_docx.py`、`scripts/validate_docx.py` 及其现有共享解析能力。
- 接口兼容：已有 CLI 命令、参数、退出码、聚合索引和各格式状态保持含义；新增诊断字段采用可选扩展，旧记录按缺少诊断兼容显示。
- 依赖与分发：沿用 Python/PySide6 和已有 Word 后端；本计划不要求新增依赖、安装、提交、发布或修改机器配置。
- 样式落点：优先 `doc_tool/ui/styles.py` 和上述现有控件的布局/主题属性；编辑器正文及 Word 成品的字体、模板与排版不随界面样式变化。

## Scope and Existing Work

沿用既有变更的已实现能力与未完成实机验收，不重置历史任务或重复声明其完成状态：

- [统一导出](../product-core-import-export/specs/unified-project-export/spec.md)：同一捕获、多格式部分成功、原输入重试及正式状态。
- [快捷默认与高级设置](../product-ui-experience-next/specs/desktop-export-configuration/spec.md)：默认整份当前内容，高级范围显式选择。
- [非模态结果与恢复](../product-ui-interaction-polish/specs/nonblocking-operation-results/spec.md)：后台任务、项目/轮次隔离及保留可用成果。
- [已有运行诊断](../product-v40-runtime-and-word-reliability/specs/runtime-recovery-and-evidence/spec.md)：阶段事实、环境摘要与原轮恢复。

本次增量是当前源码与上述契约之间的真实差额，以及用户新提出的导出入口收敛。需求正文以本 change 的 `specs/` 为准，实施顺序以 `tasks.md` 为准。

## Non-goals

- 重做 Word 导入、Markdown 拆分或编辑器，建设独立 Markdown 平台，接入新模型/provider。
- 修改企业底模、扩大 Word 对象编辑支持范围、重新设计多格式或批量交付引擎。
- 自动补造缺失图片、替换作者正文、放宽校验或将未刷新文件登记为正式稿。
- 自动升级旧项目格式、归档历史 change、发布安装包或操作 Git。

## Evidence and Status

- 基准：`49a594e6841bc926aba0bd302042c9343a6da85f`，分支 `codex/fix-release-ps51-encoding`；提案首次创建时工作树干净，未 fetch。后续设置交互修订只更新本 change，已有其它脚本修改保留。
- 用户依据：本会话对主线和智能化的澄清，以及导出失败截图；截图运行包的版本和源图片实际存在性尚未核实。
- 本轮交互确认：用户明确要求先设置。打开导出、确认设置并开始生成、打开结果是三个正常主要操作；简化设置与消除重复确认属于本次目标，跳过设置不属于目标。
- 源码依据与待验证假设见 [设计](design.md#context)。当前资源问题属于与截图吻合的静态线索，首项任务必须复现后再确认根因。
- Codegraph：not used，项目根未见索引；使用限定文件检索和 OpenSpec 官方 CLI 核对。
- 本轮交付范围为 OpenSpec 规划产物；业务复现、代码实现、自动化测试和真实 Word/桌面验收均为 `not-run`，不能由规格校验替代。

## Follow-up Scope: 六项最小修正

本节记录用户在本会话中进一步确认的范围：“不要做无意义的优化，增加复杂性”，并要求输出可交给其他 AI 执行的详细计划。本次仅更新计划和规格，不实施业务代码。历史 `Evidence and Status` 描述首次规划；后续核对基准为 `5c46b1baa56b5116d264d50e1572170b7a93fa74` / `main`，实现前须重查 HEAD 与工作区，保留并发改动。

| 编号 | 修正内容 | 行为权威来源 |
| --- | --- | --- |
| CF-01 | 顶部“导出设置”固定进入已有更多菜单，窗口重排不恢复并列按钮 | `specs/pyside6-app-shell/spec.md` |
| CF-02 | 编辑器已有低频工具固定进入更多，常用格式与保存仍可达 | `specs/content-editor/spec.md` |
| CF-03 | 日常新导出统一先确认设置；原内容重试复用已确认设置 | `specs/pyside6-app-shell/spec.md`、`specs/work-detail-pane/spec.md` |
| CF-04 | 真实阶段、位置、日志引用传到结果；失败只突出一个适用动作 | `specs/export-diagnostics/spec.md`、`specs/work-detail-pane/spec.md` |
| CF-05 | 导出前发现外部修改与脏缓冲冲突，在已有设置里明确选择来源并保护输入 | `specs/content-editor/spec.md` |
| CF-06 | F5 只检查当前内容，不写回正文或项目版本，并显示已有检查结果 | `specs/pyside6-app-shell/spec.md` |

本次边界：保留首页、章节树、搜索、视图、字号、摘要布局、既有导入与构建服务；不建设检查中心、动态工具栏、自动合并、文件监控服务或新的版本/恢复系统。不调整 Mermaid、图片渲染、底模或正式状态策略，不补造图表支持结论，不修改 CLI 参数、退出码或现有报告 schema 的含义。前次任务 6.3 的实机待办单独保留。

前次走查记录的差额包括：初始隐藏可被布局重排覆盖、当前内容重新生成绕过设置、F5 写回版本且检查面板不可见、失败结构化字段丢失、恢复按钮平铺及脏缓冲未核对外部修改。执行会话已推进其中部分任务；当前是否仍存在，以 `tasks.md` 的实际记录和再次核对为准，不能按这段历史说明重复实现。Codegraph: not used（无项目索引）。

## Integrated UI Scope: 克制的样式优化

用户补充要求“优化一下样式”并“和刚刚的计划一起整合”，因此将样式纳入本 change，不另建变更或第二套进度。既有 CF-01—CF-06 保持，追加以下可见效果；需求正文仍只在本 change 的 `specs/`。

| 编号 | 用户可见的效果 | 需求位置 | 执行任务 |
| --- | --- | --- | --- |
| VS-01 | 导出主按钮清楚，成果/检查/更多层级一致；工具栏紧凑，中文与焦点可读 | `specs/pyside6-app-shell/spec.md` 的统一主题要求 | 14.1、14.2、15.1 |
| VS-02 | 表单分组、输入、说明和错误有间距及层级，开始/取消稳定可达 | `specs/pyside6-app-shell/spec.md` 的表单呈现要求 | 14.3、15.1 |
| VS-03 | 结果先看到状态与短原因，阶段/原位置其次，技术日志折叠；唯一主动作清楚 | `specs/work-detail-pane/spec.md` 的结果阅读层级要求 | 14.4、15.1 |

具体视觉参数与修改落点见 [design.md D8](design.md#d8-与六项修正一并执行的样式设计)，页面示意见 [UI 与交互方案](ui-interaction-plan.md)。样式以现有主题为基础，不新增主题设置页、组件框架、装饰卡片、动画、确认步骤或依赖，不重排首页/章节树/摘要/导航，不改编辑与出稿语义。仅允许为本轮区域补少量样式属性和必要布局调整。

本次整合只更新 OpenSpec 文档。已有实现/验证记录原样保留；新增 VS-01—VS-03 的实现、自动化与实机验收均为 `not-run`，严格规格校验单独记录。
