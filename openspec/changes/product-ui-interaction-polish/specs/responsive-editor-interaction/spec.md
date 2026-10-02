## ADDED Requirements

### Requirement: Default layout preserves writing space
系统 SHALL 以正文为默认布局主体，收敛空闲工具/任务、大纲及元数据摘要，提供恢复默认写作布局并保留用户明确打开的面板；1280×720默认单栏正文控件目标至少560×320，不能通过增大实际窗口尺寸伪装达标。

#### Scenario: Open a project at 1280 by 720
- **WHEN** 用户首用默认布局打开有效项目且未主动展开工具面板
- **THEN** 正文达到目标空间，保存/导出/更多文字和点击区可用，其余面板可随时找回

#### Scenario: User opens a panel
- **WHEN** 用户主动展开问题面板并继续编辑
- **THEN** 后台普通事件不擅自关闭该面板，布局选择不修改正文或未保存状态

#### Scenario: Reopen an existing workspace session
- **WHEN** 已有有效SessionState并重新打开项目
- **THEN** 优先恢复原用户偏好；缺失或损坏时才采用首用写作默认，不新建另一会话文件

#### Scenario: Restore writing layout explicitly
- **WHEN** 用户执行“恢复写作布局”
- **THEN** 仅重设布局显隐/尺寸，正文、草稿、主题、标签及光标/滚动保持，所有被收起的动作仍可找回

### Requirement: Narrow controls use discoverable overflow
系统 SHALL 在窄窗口让动作溢出或重排，保留关键动作、明确更多入口和可复制完整路径；隐藏动作仍能通过菜单/键盘访问，不将宽度压力转为强制超大窗口。

#### Scenario: Long name at 1024 by 640
- **WHEN** 窗口为1024×640且文档名称/路径较长
- **THEN** 保存/导出/更多仍可操作，路径省略可查看完整值，格式动作不会被压成不可辨认竖条

### Requirement: Keyboard actions follow editing context
系统 SHALL 提供上下文明确的当前章/全文查找和写作格式操作，统一菜单/注册表提示及可用性，保留合理Tab顺序和临时层关闭后的焦点，不让普通状态提示抢占输入。

#### Scenario: Search and formatting in editor
- **WHEN** 编辑器有焦点且用户使用Ctrl+F、Ctrl+Shift+F、Ctrl+B/I
- **THEN** 分别进入当前章查找、项目全文查找和写作格式动作，分支动作不抢占该写作上下文

#### Scenario: Format shortcut outside the editor
- **WHEN** 焦点在其他输入框或输入法组合过程中
- **THEN** 不按全局格式操作插入正文或触发分支动作，保留该输入控件正常行为；菜单/注册表提示与实际作用域一致

#### Scenario: Dismiss a temporary panel
- **WHEN** 用户通过Esc或关闭动作结束临时层
- **THEN** 焦点回到合理触发位置/编辑器，帮助等重要入口可用键盘到达
