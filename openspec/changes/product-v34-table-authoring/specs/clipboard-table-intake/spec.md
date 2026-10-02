## ADDED Requirements

### Requirement: Explicit table paste uses a preview
系统 SHALL 提供显式“粘贴为表格”，支持引号感知 TSV 与受支持的管道表格，展示行列数、首行表头选择及转换预览；普通文本/图片粘贴保持既有行为。

#### Scenario: Paste TSV
- **WHEN** 用户选择粘贴为表格并提供含空单元格的 TSV
- **THEN** 预览及插入结果保持真实行列，用户能选择首行作为表头

#### Scenario: Ordinary image paste
- **WHEN** 用户在编辑器普通粘贴图片
- **THEN** 沿用既有资产粘贴流程，不打开表格对话框

### Requirement: Cells retain textual meaning
系统 SHALL 将单元格作为字符串处理，保留前导零、日期文本、公式文本和可支持的引号内换行；未支持的换行表示先显式预览并保留原文，不静默删内容或执行公式。

#### Scenario: Leading zeros and formula text
- **WHEN** 输入单元格分别为 0012、2026-10-01 和 =SUM(A1:A2)
- **THEN** 输出保留这些文本值，不计算、改写类型或去除前导零

#### Scenario: Multiline cell outside support
- **WHEN** 输入包含当前后端不能等价表示的多行单元格
- **THEN** 显示转换结果与支持边界，原文可复制，用户能回到文本编辑继续工作

### Requirement: Unsupported inputs remain recoverable
系统 SHALL 对无法解析的表格输入提供原因、原文复制和普通文本粘贴路径；较大可支持输入可以分页预览，但不得截断实际插入内容。

#### Scenario: Large table preview
- **WHEN** 可支持的 1,000 行×20 列输入只显示预览首批
- **THEN** 界面标明显示范围与完整行列数，应用后完整输入均被保留
