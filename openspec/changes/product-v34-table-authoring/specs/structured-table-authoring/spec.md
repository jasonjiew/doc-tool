## ADDED Requirements

### Requirement: Plain table grid supports routine edits
系统 SHALL 为受支持的普通 Markdown 表格提供网格编辑、行列增删移动、列对齐和键盘导航，保持空单元格及可表达的行内内容；复杂原生表格保持现有保留路径。

#### Scenario: Edit a requirements table
- **WHEN** 用户在普通表格中新增一行、移动一列并设置右对齐
- **THEN** 应用后的表头、行值及列对齐准确，空单元格没有被删除

#### Scenario: Complex table
- **WHEN** 用户选择复杂 Word 原生保留表格
- **THEN** 界面说明网格支持范围并提供原内容查看/复制，不将其静默转换为普通表格

### Requirement: Table application is a single buffer transaction
系统 SHALL 将网格结果仅应用到身份与来源匹配的编辑缓冲片段，支持一次撤销；源片段变化或定位歧义时保留待应用结果并允许重新定位。

#### Scenario: Undo grid changes
- **WHEN** 用户应用多项网格修改后执行一次撤销
- **THEN** 原表格片段恢复，文件其他文字和未保存状态符合编辑器撤销语义

#### Scenario: Source changed while grid open
- **WHEN** 网格打开后原表格被另一个编辑动作修改
- **THEN** 原表格不被旧草稿覆盖，网格结果保留并显示重新定位/查看差异操作

### Requirement: Table content is shared by preview and export
系统 SHALL 将结果序列化到原 Markdown 内容源，正确处理竖线、反斜杠、对齐与空值，并使用现有预览和 CORE 同源导出，不维护第二份权威表格数据。

#### Scenario: Export an unsaved table
- **WHEN** 用户修改网格并选择 CORE 当前内容出稿而未保存
- **THEN** 出稿捕获包含所见表格，保存文件和其他草稿不被隐式改写
