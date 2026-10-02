## Why

CORE/V3 功能已大量接通，但日常操作仍受入口命名、工具栏挤压、空闲面板和模态结果影响。2026-10-02 的真实 Qt 离屏样例中，1280×720 的正文编辑控件仅约 336×121，14 个格式动作被压缩；需要把已实现能力整理成容易发现、可连续工作的界面。

## What Changes

- 首页按继续编辑/导入组织，拖放与按钮同语义；顶部提供已实现的快速 Word 导出，技术动作按需展开。
- 工具栏增加溢出及明确上下文，收敛空闲 Dock、大纲和路径摘要，保护小窗口正文空间和键盘操作。
- 扩展已有TaskDock/结果视图，将导入、出稿、批量交付及普通注册表完成反馈接入非模态成果；逐文件打开、原轮补缺、当前修改新轮和换目录重新导出各自来源明确。
- 为已有模块库/批量交付服务补空状态下一步和最小表单入口，保留高级包文件导入及技术详情。

## Capabilities

### New Capabilities

- `task-oriented-workbench-interaction`: 首页、拖放、主操作及高级入口的一致交互。
- `responsive-editor-interaction`: 小窗口编辑空间、动作溢出、上下文和键盘行为。
- `nonblocking-operation-results`: 可持续查看的成果、部分成功、异步重试及状态反馈。

### Modified Capabilities

无。复用已有服务与 CORE/V3 内容/出稿契约，新增具体界面要求；不改业务含义。

## Impact

涉及 `empty_state.py`、`project_bar.py`、`main_window.py`、编辑器/Dock、TaskDock、导入向导、复用与辅助面板。复用现有注册表、SessionState、有效捕获、导出、模块及交付队列服务。2026-10-02最终复核：5批/20项，编号保留，实施起始0/20；任务与真实实机验收分开，缺环境仅影响直接相关项。最终入口见 [最终计划](../../../docs/product-ui-interaction-final-plan.md)，证据见 [调研](../../../docs/product-ui-interaction-research.md)。RD及后续版本保持各自能力归属。
