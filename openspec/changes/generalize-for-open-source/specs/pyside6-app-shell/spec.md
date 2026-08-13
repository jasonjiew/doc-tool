## ADDED Requirements

### Requirement: Application shell uses public-neutral product identity
桌面应用 SHALL 从集中发行元数据设置 `QApplication` 的应用名、显示名与组织设置键，并 SHALL 在窗口标题、关于页、空状态和错误提示中使用通用大型 Word 文档工具定位。公共应用 MUST NOT 显示公司名称或公司专用文档类型品牌。

#### Scenario: Launch public application shell
- **WHEN** 用户启动公共桌面应用
- **THEN** `QApplication`、主窗口和关于页显示一致的中性产品名称和版本

#### Scenario: Inspect public user-facing strings
- **WHEN** 品牌检查扫描桌面应用可见文本
- **THEN** 未发现禁止的公司品牌、公司网址或专用文档编号

## MODIFIED Requirements

### Requirement: Window lifecycle and state persistence are preserved
窗口几何/最大化状态持久化、任务运行中的关闭保护、菜单与键盘快捷键 SHALL 保持现有语义。公共品牌启用新的设置组织键后，应用 SHALL 在首次启动时兼容读取允许的旧设置并复制到新命名空间，MUST NOT 删除或覆盖旧命名空间。

#### Scenario: Close during task
- **WHEN** 用户在后台任务运行时关闭主窗口
- **THEN** 应用沿用现有安全关闭确认与取消策略，任务在安全阶段边界停止后窗口关闭

#### Scenario: Geometry saved
- **WHEN** 用户调整窗口尺寸/位置或最大化后退出
- **THEN** 下次启动从公共设置命名空间恢复相同几何与状态

#### Scenario: Migrate legacy preferences once
- **WHEN** 公共设置尚不存在且应用检测到受支持的旧设置
- **THEN** 应用复制窗口几何、主题和最近项目等允许字段到公共命名空间，保留旧设置不变且不重复覆盖用户的新设置

