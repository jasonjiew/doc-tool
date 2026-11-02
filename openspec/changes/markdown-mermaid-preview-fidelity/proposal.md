# Proposal

## Why

用户要求 doc-tool 的 Markdown 阅读效果对齐 Typora / VS Code。当前预览使用 Qt 富文本和自写 Markdown/Mermaid 子集解析：嵌套列表、表格对齐及转义存在缺口，流程图分组/样式和时序图控制块会被略过，工作台预览与导出还使用不同后端。

仓库已有 WebEngine 页面，但编辑器未接入，两个打包规格仍排除相关模块；发布说明中的“已支持”不能作为预发成品可用的证据。本变更提供可由其他会话执行的完整规格、设计、任务和验收入口。

## What Changes

- 把桌面侧边预览升级为离线浏览器阅读预览：推荐复用 PySide6 的 QWebEngine，以 markdown-it 处理声明支持的 Markdown 方言，独立 CSS 控制排版。
- 为现有原生预览保留明确标识的轻量模式；高保真运行时不可用时不影响正文编辑、保存和已有出稿入口。
- 阅读区、Mermaid 工作台和大图入口使用同版本官方 Mermaid 校验与渲染，保留流程图子图/样式及复杂时序语义；图形导出遵循相同的源码、配置、字体与尺寸契约。
- 保留项目图片尺寸、题注、模块展开、提示块、原始源码定位、未保存缓冲和多窗口隔离；高保真预览不得通过保存或改写 Markdown 实现。
- 处理刷新乱序、滚动位置、离线资源边界、渲染失败与降级状态，并验证安装版和便携版最终 EXE。
- 非目标：替换纯文本编辑器、复刻 Typora 即时编辑、重写全部 Word/HTML 导出、承诺 Word 分页一致、升级 Mermaid 大版本、修改项目数据格式、自动提交/发布/归档。

## Capabilities

### New Capabilities

- `markdown-reading-preview`：标准正文语义、阅读样式、项目扩展适配、源码联动、更新一致性、本地资源与离线运行时交付。需求编号为 REQ-MD-01～REQ-MD-08。
- `mermaid-diagram-rendering`：官方语法权威、流程图和时序图语义、入口一致性、图形导出与降级可见性。需求编号为 REQ-MM-01～REQ-MM-06。

### Modified Capabilities

- `content-editor`：修改已有“侧边 md 预览”要求，区分桌面高保真阅读预览、轻量近似预览与正式 Word 版式；保留实时去抖和编辑安全语义。需求编号为 REQ-ED-01。

## Impact

- 主要实现位置：`doc_tool/ui/content/editor_panel.py`、`web_preview_browser.py`、`mermaid_dialog.py`、`diagram_viewer.py`，`doc_tool/application/content/preview.py`、`mermaid.py`，`doc_tool/resources/web_preview/`。
- 分发位置：`packaging/doc_tool.spec`、`packaging/doc_tool_onefile.spec`、`packaging/publish_release.py`、依赖/许可清单及资源定位入口。新增或调整的库和字体须精确锁定、记录来源与许可；业务应用层不得新增 WebEngine 依赖。
- 既有契约：`openspec/specs/content-editor/spec.md`；活动变更 `content-authoring-workbench` 中的近似 Mermaid/排除 WebEngine 取舍由本变更在相关功能上取代，不修改其历史任务完成记录。
- 兼容边界：`product-v26-delivery-baseline` 的只读离线 HTML 包仍可独立用浏览器打开，不得变成依赖桌面 WebEngine 的文件；无 GUI 的 CLI 能力不得因导入 Qt WebEngine 而失效。
- 取证基线：2026-10-31，本地 `main` / `6a3a994c5762a64cf18bdb057a6b4b491f42ee2c`，创建本变更前工作树干净；未刷新远端。Codegraph 未使用：目标仓没有索引，使用限定范围源码检索。
- 当前范围仅为计划产物与 OpenSpec 校验；实现、业务测试、视觉对照、性能量测、预发安装验证均未执行。执行会话从 `handoff.md` 和 `tasks.md` 续接。
