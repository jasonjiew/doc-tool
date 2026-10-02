## ADDED Requirements

### Requirement: Collection browsing uses existing manifests
系统 SHALL 提供版本集合列表、详情、差异和包导出 GUI，并从已有清单展示源内容、资源、配置、评审、关系与产物状态，不依据目录名推断正式成功。

#### Scenario: Compare two collections
- **WHEN** 用户选择两份已有版本集合进行比较
- **THEN** 显示现有 compare_baselines 的变化及来源，能打开真实成果和清单

### Requirement: Member outputs retain partial success
系统 SHALL 使用 CORE 捕获及统一出稿接口协调本轮成员成果，沿用 Word 串行调用及实际 OutputState，逐成员记录完成、待处理、失败和取消状态，已可用成果可立即打开。

#### Scenario: Word unavailable
- **WHEN** 工作区成员捕获成功但 Word 不可用
- **THEN** 可读成果与来源清单保留，正式刷新列为待处理，不将整轮伪装成正式完成

#### Scenario: One member fails
- **WHEN** 三成员中一份无法生成而另两份成功
- **THEN** 成功成果仍可打开/打包，清单保留失败成员和原因并可重试

### Requirement: Recover into a new copy
系统 SHALL 调用既有集合恢复服务生成新副本，展示摘要检查与部分恢复结果，不覆盖当前源项目或未保存缓冲。

#### Scenario: Restore damaged collection
- **WHEN** 集合中一个资源缺失，其余文件验证通过
- **THEN** 验证通过的部分可在新目录恢复，缺失项列明，原工作区及缓冲不变

### Requirement: Cancellation does not erase completed outputs
系统 SHALL 在集合操作提供阶段进度和取消反馈，保留取消前已完成成果并如实记录未完成成员；持久跨运行续跑沿用后续交付队列实现。

#### Scenario: Cancel between members
- **WHEN** 第一成员成果已生成，用户取消后续成员处理
- **THEN** 第一成员成果可用，后续成员显示取消/未完成，不生成假的成功标记
