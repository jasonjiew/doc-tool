## ADDED Requirements

### Requirement: 评审版 PDF/HTML 导出
系统 SHALL 从当前构建产物或 Markdown 内容一键生成评审版 PDF 与 HTML：PDF 复用 Word 输出导出路径（本机 Word 可用时经 Word 另存，否则经构建链路生成只读副本），HTML 由 `preview.render_markdown_html` 渲染并带章节导航；导出文件落盘到项目输出目录的评审子目录。

#### Scenario: 生成评审版 PDF
- **WHEN** 用户触发「导出评审 PDF」
- **THEN** 系统生成带版本与导出时间的 PDF 到评审目录

#### Scenario: 生成评审版 HTML
- **WHEN** 用户触发「导出评审 HTML」
- **THEN** 系统生成带章节导航的 HTML 到评审目录

#### Scenario: 无 Word 时导出 PDF
- **WHEN** 本机无 Microsoft Word，用户仍要求导出 PDF
- **THEN** 系统经构建链路生成只读 PDF 副本并标注「非 Word 导出」，不静默失败

### Requirement: 相邻版本页面级视觉对比
系统 SHALL 对比当前版本与上一版本的 PDF/HTML 页面渲染结果：把两版页面转成图像后做像素级对比，按页输出差异区域；仅当两版对应的历史快照存在差异时才执行视觉对比。

#### Scenario: 页面级差异定位
- **WHEN** 相邻两版存在内容差异且均能渲染为页面
- **THEN** 系统按页标记有差异的页面并圈出差异区域

#### Scenario: 无差异页面
- **WHEN** 某页两版渲染一致
- **THEN** 系统标记该页无差异，不生成差异区域

#### Scenario: 缺失对比基线
- **WHEN** 当前版本没有上一版本可对比（首版或上一版不可渲染）
- **THEN** 系统提示无对比基线，仅提供当前版导出

### Requirement: 差异标注与定位
系统 SHALL 在视觉对比结果中允许用户点击差异区域：点击后打开对应章节的 Markdown 编辑器并定位到相关位置，同时把该差异标记为「已查看」。

#### Scenario: 点击差异定位章节
- **WHEN** 用户点击某差异区域
- **THEN** 系统打开对应章节文件并定位到差异来源位置

#### Scenario: 标记已查看
- **WHEN** 用户确认查看某差异
- **THEN** 系统把该差异标记为「已查看」，在对比结果中变更样式
