# Markdown 语义与扩展验收夹具集 (Fidelity Fixtures)

本目录包含 `markdown-mermaid-preview-fidelity` 规格验收所使用的标准输入夹具及预期观察结果。
每个夹具声明其来源、对应需求、环境前提与可观察预期。

## 夹具清单

| 夹具文件 | 对应需求 | 关键测试点 |
| --- | --- | --- |
| `01_markdown_semantics.md` | REQ-MD-01 | 多层嵌套列表、起始编号、普通软换行 vs 硬换行、行内代码保护（链接/图片/HTML/Mermaid 关键字）、代码块高亮、任务列表、删除线、引用块 |
| `02_tables.md` | REQ-MD-02 | 转义竖线 `\|` 不拆列、左/中/右三向列对齐、宽表横向滚动不截断、长表尾行及后续正文完整性 |
| `03_project_extensions.md` | REQ-MD-04, REQ-MD-05 | 图片尺寸后缀 `{width=...}`、构建占位符 `{{...}}`、提示块、代码块内扩展字符串保护（不被误替换） |
| `04_mermaid_flowchart.md` | REQ-MM-01, REQ-MM-02 | 子图分组嵌套、节点样式 `style`/`classDef`、多方向、带文字连线、循环回边、超长中文节点标签 |
| `05_mermaid_sequence.md` | REQ-MM-01, REQ-MM-03 | `alt`/`else` 分支、`opt` 条件、`loop` 循环、`par`/`and` 并行、`Note` 备注、参与者别名、激活条 `activate`/`deactivate`、`autonumber` 编号 |
| `06_mermaid_edge_cases.md` | REQ-MM-01, REQ-MM-06 | `%%{init: ...}%%` 前置配置、语法错误映射与行号、未打包图类型与优雅降级提示 |

## 参考环境清单与基线参数

- **操作系统**：Windows (x64)
- **GUI 运行时**：Python 3.13.13 + PySide6 6.8.3 (QtWebEngineWidgets + QtWebChannel)
- **VS Code 参考应用**：VS Code 1.143.0（已安装，路径：`D:\Users\18098\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd`），正文浅色/深色主题，内置 CommonMark 预览。
- **Typora 参考应用**：`not-installed`（未在本机安装，标记为 `missing` / 人工视觉对照受限）。
- **Word 应用程序**：Microsoft Office Word（已安装，路径：`C:\Program Files\Microsoft Office\Root\Office16\WINWORD.EXE`），可用于 DOCX 插入图片和保真度验证。
- **Mermaid CLI (mmdc)**：`not-found`（PATH 无全局 mmdc），验证离线桌面“无 Node/npm 导出”独立能力的纯净性。
- **基线排版参数**：
  - 阅读正文宽度：默认自适应，最大行宽 860px-960px 居中
  - 中文字体栈：`"Segoe UI", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif`
  - 代码字体栈：`Consolas, "Cascadia Code", "Courier New", monospace`
  - 缩放：100% (1.0)
