## ADDED Requirements

### Requirement: Sample runs are isolated and versioned
系统 SHALL 使用选定草稿资源和固定样例内容创建隔离项目，调用实际创建、检查与 CORE 出稿接口，并将结果绑定草稿摘要与 captureId。

#### Scenario: Run a sample without modifying source
- **WHEN** 用户从当前项目选取样例试用规范包
- **THEN** 结果生成在隔离目录，源文件和未保存缓冲不被修改，报告记录实际输入身份

### Requirement: Sample results distinguish verification levels
系统 SHALL 显示结构、规则、可读成果、待刷新、正式成功和未验证状态；缺 Word 或视觉未验证时仍可保存和导出结构合法包，但不得标记样例正式成功。

#### Scenario: Share without Word
- **WHEN** 包结构合法且 Word 不可用
- **THEN** 可保存草稿及导出包，可读样例/HTML 可打开，Word 刷新与视觉验收列为待验证

#### Scenario: Invalid package structure
- **WHEN** 包身份或路径结构使现有消费者无法读取
- **THEN** 可保存草稿并定位错误，不生成冒充可安装成功的产物

### Requirement: Stale sample evidence remains identifiable
系统 SHALL 在草稿变化后标明旧样例过期，保留旧成果可打开，并允许同一来源重试或显式生成最新样例。

#### Scenario: Change a rule after sample completion
- **WHEN** 样例完成后用户修改规则
- **THEN** 旧结果仍可查看但不代表当前包，重新试用生成绑定新摘要的结果
