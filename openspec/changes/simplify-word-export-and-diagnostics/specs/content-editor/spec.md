## ADDED Requirements

### Requirement: Low frequency editor actions stay in the existing overflow menu

[CF-02] 编辑器 SHALL 将本地历史、回滚、外部打开、表格网格、粘贴为表格、Mermaid、批量转图和片段等已收纳的低频操作固定放入已有更多菜单。窗口、预览、侧栏或主题变化 SHALL 不将这些操作重新平铺。常用格式、图片、普通表格和保存 SHALL 保持可达；同一低频操作在菜单中只出现一次，来源可用性和只读保护保持。

#### Scenario: Resize after opening an editor
- **WHEN** 用户打开章节后反复放大缩小窗口或展开收起预览与侧栏
- **THEN** 固定低频操作始终在更多菜单中，不挤回常用工具栏，保存仍可点击或通过原快捷键访问

#### Scenario: Reflow the menu repeatedly
- **WHEN** 编辑器经历多次布局重排、切换章节或主题
- **THEN** 更多菜单保留各项原能力且没有重复条目，一次点击只执行一次对应操作

#### Scenario: Read only editor
- **WHEN** 当前章节以只读方式打开
- **THEN** 更多菜单中的查看和复制按原规则可用，写入类动作不能通过菜单绕过只读保护

### Requirement: Export resolves external edits and unsaved buffer conflicts explicitly

[CF-05] 使用当前编辑内容导出时，系统 SHALL 在本次范围内核对脏缓冲与外部磁盘修改。两方内容分叉或来源不可核实时 SHALL 在现有设置中说明涉及章节，并要求明确选择本次来源；磁盘与缓冲均保持。无冲突 SHALL 沿原确认步骤直接开始。来源确认后、实际捕获前再次变化 SHALL 不被静默忽略；系统须中止该次不一致捕获并说明原因，不自动合并或覆盖正文。

#### Scenario: Only the editor buffer has changed
- **WHEN** 本次范围内仅有窗口未保存修改，磁盘内容与加载基准一致
- **THEN** 默认当前内容可直接确认导出，生成物包含缓冲，源文件和脏标记保持，无额外弹窗或来源选择

#### Scenario: Only an external editor has changed the file
- **WHEN** AI 或外部编辑器改了磁盘正文，窗口内没有该章未保存修改
- **THEN** 本次新导出采用实际磁盘内容，不用旧的干净窗口文本覆盖它，不要求用户先逐章保存或切换标签

#### Scenario: Both the external file and buffer have diverged
- **WHEN** 本次范围内同一章节的磁盘和未保存窗口内容均偏离可核实的加载基准且二者不同
- **THEN** 设置保留已填参数并说明冲突章节，开始前必须明确采用窗口内容或磁盘最新内容；采用窗口时说明外部修改未纳入，采用磁盘时说明未保存窗口修改未纳入，两份原输入均保留

#### Scenario: Different timestamps but identical content
- **WHEN** 外部仅改变修改时间或磁盘与当前缓冲实际内容相同
- **THEN** 不额外要求解决内容冲突，不将时间戳变化本身说成内容丢失

#### Scenario: Unavailable file or missing comparison baseline
- **WHEN** 相关文件不可读、已删除，或恢复草稿缺少可信比较基准
- **THEN** 系统说明来源未知或不可用，不把它当成无外部修改；只有用户明确选择仍可用的来源后才继续，取消保持原缓冲和设置

#### Scenario: Content changes again after source confirmation
- **WHEN** 用户确认来源后，实际捕获所读磁盘内容又发生变化
- **THEN** 本次不一致输入不进入构建，结果说明内容再次变化及原章节；保留窗口、磁盘和已有成果，重开设置时沿用可用参数，不自动切换来源或循环重试

#### Scenario: Conflict is outside the chosen export scope
- **WHEN** 冲突仅存在于本次明确未选的章节
- **THEN** 不阻断当前范围的导出，也不为解决该冲突保存或改写范围外正文

#### Scenario: Retry an already captured export
- **WHEN** 用户重试已有捕获的内容，而磁盘与窗口已有后续修改
- **THEN** 重试继续使用原捕获，不启动当前内容来源选择；需要新内容时走已有新导出设置入口
