## ADDED Requirements

### Requirement: Index reuse is determined by content and dependencies
系统 SHALL 使用内容摘要、解析器版本、项目身份及影响结果的配置/装配指纹决定索引复用，正确处理新增、删除、移动和同大小内容变化；缓存不是任何业务记录的权威存储。

#### Scenario: Same size content changes
- **WHEN** 文件内容改变但字节数和 mtime 初筛值不足以判断变化
- **THEN** 实际摘要失效对应缓存，索引与直接解析新内容一致

#### Scenario: Configuration changes
- **WHEN** 影响解析的规范或变量发生变化
- **THEN** 相关派生索引重算，不能继续输出旧配置下的结果

### Requirement: Broken caches fall back to source
系统 SHALL 在缓存损坏、格式未知、版本不匹配或写入失败时直接读取源内容，保留普通功能可用并报告必要诊断，不将缺缓存当成项目损坏。

#### Scenario: Corrupted cache
- **WHEN** 持久缓存文件被截断
- **THEN** 项目通过直接读取继续搜索/检查，可重建缓存，业务文件不被改写

### Requirement: Captures isolate saved and unsaved content
系统 SHALL 按 captureId 使用准确的已保存/缓冲内容摘要，复用 V3.0 的实际装配指纹，并保证同轮预览、检查与出稿读取相同内容。

#### Scenario: Unsaved chapter differs from disk
- **WHEN** 当前捕获含一个未保存章节
- **THEN** 该章节使用捕获内容而非磁盘旧缓存，其余未变章节可以复用，成果记录该 captureId

#### Scenario: Reused module version changes
- **WHEN** 某装配槽位选择了另一模块版本或变量值
- **THEN** 依赖该槽位的索引失效，其内容与实际解析结果一致
