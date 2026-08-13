## ADDED Requirements

### Requirement: 源文档更新检测
系统 SHALL 在打开项目时对比 `project.yml` 的 `sourceSha256` 与当前 `original/source.docx` 的 SHA-256；不一致时提示源 Word 已更新，并提供重新导入入口。

#### Scenario: 检测到源文档更新
- **WHEN** 当前源 DOCX 的 SHA-256 与清单记录不一致
- **THEN** 系统提示源 Word 已更新并显示重新导入入口

#### Scenario: 源文档未更新
- **WHEN** 源 DOCX 的 SHA-256 与清单一致
- **THEN** 系统不显示重新导入提示

#### Scenario: 源文档缺失
- **WHEN** `original/source.docx` 不存在
- **THEN** 系统提示源文档缺失，禁用重新导入入口

### Requirement: 章节级差异预览
系统 SHALL 在重新导入前经 `preflight` 预检新源文档，并与当前内容做章节级对比（复用 `index.py` 标题索引与 `snapshot.py` 的哈希对比）：列出新增/修改/删除/未变的章节及差异摘要，供用户确认。

#### Scenario: 预览章节级差异
- **WHEN** 用户触发重新导入并选择新源 DOCX
- **THEN** 系统预检新源并列出章节级新增/修改/删除/未变清单

#### Scenario: 预检失败中止导入
- **WHEN** 新源文档预检失败（结构或资源问题）
- **THEN** 系统中止导入并展示稳定错误码与建议，当前内容不变

### Requirement: 冲突预览与不覆盖合并
系统 SHALL 在合并时识别冲突：当前内容相对基线有本地修改的章节，与新源同章节内容不同则标记为冲突；合并结果经用户确认后写入，**不覆盖已有 Markdown 修改**——冲突章节默认保留本地修改并单独列出供用户逐章选择。

#### Scenario: 无冲突章节自动合入
- **WHEN** 新源章节与当前内容无本地修改冲突
- **THEN** 系统按新源内容合入该章节

#### Scenario: 冲突章节保留本地修改
- **WHEN** 章节在新源与本地均有修改且内容不同
- **THEN** 系统默认保留本地修改，并把该章节列为冲突供用户选择

#### Scenario: 用户逐章选择冲突结果
- **WHEN** 用户在冲突预览中为某章节选择「采用新源」
- **THEN** 系统以新源内容覆盖该章节并记录为手动选择

### Requirement: 可撤销合并
系统 SHALL 把重新导入的全部写入经 `ContentWriter` 记录进改动清单（备份 + 原子写），用户可经改动面板一键回滚整次重导入；合并完成后更新 `sourceSha256` 并重建索引与追踪数据。

#### Scenario: 回滚整次重导入
- **WHEN** 用户对刚完成的重导入执行回滚
- **THEN** 系统按改动清单恢复合并前内容，清单清空

#### Scenario: 合并后更新源指纹
- **WHEN** 重导入合并完成
- **THEN** 系统更新 `project.yml` 的 `sourceSha256` 并重建内容索引与追踪矩阵
