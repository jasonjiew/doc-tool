## ADDED Requirements

### Requirement: Mermaid 源码识别与编辑入口
系统 SHALL 识别 Markdown 中的 ```mermaid 围栏代码块，以及历史遗留的裸 `flowchart`/`sequenceDiagram` 源码段落（未用围栏包裹）；两者均提供专用工作台编辑入口，裸源码 SHALL 提示用户转换。

#### Scenario: 围栏代码块识别
- **WHEN** 文档包含 ```mermaid 围栏块
- **THEN** 系统识别其起止行并可在工作台打开编辑

#### Scenario: 裸源码识别与提示
- **WHEN** 正文段落以 `flowchart`/`sequenceDiagram` 起始且非围栏块
- **THEN** 系统识别为历史遗留 Mermaid 源码，可在工作台编辑并选择「转换并替换源码」

#### Scenario: 打开工作台编辑
- **WHEN** 用户对已识别的 Mermaid 源码触发编辑
- **THEN** 工作台加载源码，修改可写回原位置

### Requirement: 语法检查
系统 SHALL 对 `flowchart` 与 `sequenceDiagram` 子集执行语法检查（节点/边/配对括号/箭头/标签引号/注释），错误 SHALL 按行报告并支持定位到源码行；合法图 SHALL 无错误。

#### Scenario: 语法错误按行定位
- **WHEN** 源码在某行存在未闭合括号或非法边定义
- **THEN** 系统报告错误所在行号与原因，点击可定位到该行

#### Scenario: 合法图无错误
- **WHEN** 源码为合法的 flowchart 或 sequenceDiagram
- **THEN** 语法检查通过，无错误提示

#### Scenario: 不支持的类型提示
- **WHEN** 源码使用非 flowchart/sequenceDiagram 的图类型（如 gantt、pie）
- **THEN** 系统提示该类型不在当前子集支持范围，不静默当作合法

### Requirement: 实时预览
系统 SHALL 在工作台内提供实时渲染预览，随源码编辑去抖刷新；渲染失败时 SHALL 显示错误占位而非崩溃，预览 SHALL 标注为近似效果。

#### Scenario: 编辑后去抖刷新
- **WHEN** 用户编辑源码且超过去抖窗口
- **THEN** 预览自动刷新为最新图

#### Scenario: 渲染失败显示错误占位
- **WHEN** 源码存在语法错误或渲染后端不可用
- **THEN** 预览区显示错误信息与原因，编辑器不受影响

### Requirement: 一键导出并插入 Word
系统 SHALL 将图渲染为 SVG/PNG 保存到资源目录 `assets/<类型>/images/`，并在光标处插入图片引用（可带尺寸后缀）；用户选择替换时 SHALL 用图片引用替换原源码块。渲染后端优先检测 `mermaid-cli`，不可用时回退内置子集渲染器；两者均不可用 SHALL 给出清晰错误。

#### Scenario: 导出 PNG 并插入引用
- **WHEN** 用户点击「插入 Word」且渲染成功
- **THEN** 系统生成图片文件到资源目录并在光标处插入 `![图](images/mermaid_NNNN.png =宽x高)` 引用

#### Scenario: 替换源码块
- **WHEN** 用户选择「转换并替换源码」
- **THEN** 原 Mermaid 源码块被图片引用替换，构建后 Word 显示渲染图

#### Scenario: 渲染后端不可用
- **WHEN** 既无 mermaid-cli 且内置渲染器不支持该图类型
- **THEN** 系统提示需要安装 mermaid-cli 或调整图类型，不插入无效引用

#### Scenario: 批量转换既有裸源码
- **WHEN** 用户对当前文档执行「批量转换」且存在多处裸 Mermaid 源码
- **THEN** 系统逐个渲染为图片并替换源码，汇总成功与失败项

### Requirement: 与预览/构建链路一致
插入的图片引用 SHALL 被编辑器阅读预览与 Word 构建正确渲染；Mermaid 围栏块在阅读预览中 SHALL 以渲染图呈现（渲染失败时显示源码或错误占位）。

#### Scenario: 阅读预览显示渲染图
- **WHEN** 编辑器阅读预览遇到 Mermaid 围栏块
- **THEN** 预览以渲染图呈现，而非纯文本

#### Scenario: 构建产物包含图
- **WHEN** 含 Mermaid 图片引用的文档执行构建
- **THEN** 构建产物包含该图片，与既有图片引用行为一致
