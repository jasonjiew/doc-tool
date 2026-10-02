## ADDED Requirements

### Requirement: Background views reject stale results
系统 SHALL 为耗时视图提供后台执行、项目/捕获/请求代次标记和分页或渐进反馈，界面只应用当前代次结果，部分结果不得伪装为完整扫描。

#### Scenario: Switch chapters during preview
- **WHEN** 用户切换章节后上一章节的后台预览才完成
- **THEN** 旧结果不覆盖当前章节，当前编辑缓冲保持

#### Scenario: Search is still scanning
- **WHEN** 搜索仅完成首批章节并找到若干结果
- **THEN** 界面标明已找到及扫描进度，完成后才给出完整总数

### Requirement: Cancellation preserves useful results
系统 SHALL 在不超过 1 秒内确认界面取消请求，保留可识别的已完成结果并提供重试；不可立即中断的 Word 阶段要显示实际停止状态，不伪造完成。

#### Scenario: Cancel an index scan
- **WHEN** 用户在大项目扫描期间取消
- **THEN** 界面及时确认，已有结果标识为部分结果，用户仍能继续编辑

### Requirement: Performance claims require same-host evidence and correctness
系统 SHALL 用 50/300/1,000 章节样例记录同机冷/热阶段、输入与环境、至少 5 次样本及内存，并比较无缓存结果；目标热路径解析次数至少减少 70%、中大样例 p95 耗时至少改善 30%、小样例 p95 不恶化超过 10%，调整目标需有基准理由。

#### Scenario: Validate an optimization
- **WHEN** 某热路径优化完成
- **THEN** 报告包含基准与优化样本分布、次数/时长/内存、语义对照及目标结果，不用单次最快值宣称完成

#### Scenario: Build a formal Word document
- **WHEN** 用户在缓存命中的项目执行正式出稿
- **THEN** 仍完整执行规定 Word 阶段，正式状态以实际 OutputState 为准，不能凭缓存命中跳过刷新
