## ADDED Requirements

### Requirement: 批次操作命令与同源结果
系统 SHALL 提供 delivery run/status/retry/package/promote，读取 schema 1 批次计划并输出 human/JSON，GUI 与 CLI 共用编排及结果模型；现有参数语义兼容。

#### Scenario: 同计划 GUI 与命令行执行
- **WHEN** 两入口在同环境使用相同固定输入和策略
- **THEN** 逐项内容范围/状态/降级一致，JSON 为单独 stdout 文档，日志在 stderr

### Requirement: 结果索引与退出码
系统 MUST 显示实际成员/变体/格式产物及完整性，操作默认 0=有可用结果（可部分/待刷新）、1=无可用方案或严格未满足、2=参数/运行失败；正常 status 查询返回 0，任务失败信息在报告内。

#### Scenario: 部分成功的默认批次
- **WHEN** run 生成部分 DOCX 而其余格式失败且未选择严格模式
- **THEN** 返回 0，报告明确 partial、成功/失败数量和可用路径；严格阈值场景单独返回 1

### Requirement: 可复现自动化示例
系统 SHALL 提供按真实 CLI help 验证的 Windows 无 Word 生成包与有 Word 处理示例，声明实测平台，脚本默认只产生本地可审阅结果。

#### Scenario: 离线流水线执行
- **WHEN** 无 Word 的 Windows runner 按示例生成包
- **THEN** 得到包/报告并能在有 Word 机器继续处理，没有未授权上传、通知或发布步骤
