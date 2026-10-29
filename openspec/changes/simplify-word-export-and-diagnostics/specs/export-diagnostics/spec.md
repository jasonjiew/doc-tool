## Purpose

定义 Word 文档导出从输入捕获到成果写入的诊断契约，使作者和维护者可以从同一导出记录理解失败原因、定位原始 Markdown 与资源、查看阶段证据并复制可读 Markdown。诊断保持可恢复和可追溯，服务已有结果与正式状态，不承担第二套生命周期或人工审批。

## ADDED Requirements

### Requirement: Each export diagnostic belongs to the actual execution

[CF-04] 系统 SHALL 将导出的阶段事实、错误、警告和各格式结果关联到真实项目、执行及已存在的捕获身份，覆盖输入准备、预处理、构建、校验、Word 刷新和写成果。阶段状态 SHALL 由已有执行事件产生；捕获前失败须保留已知执行身份并标捕获未建立，不伪造成功阶段或捕获标识。各格式可用性与正式状态 SHALL 沿用既有权威结果。

#### Scenario: Capture fails before a snapshot exists
- **WHEN** 无法读取当前输入而导出在建立快照前失败
- **THEN** 结果包含该次已知项目、执行时间、输入准备阶段和原因，捕获明确为未建立，查看与复制诊断仍可用

#### Scenario: Validation fails after building a file
- **WHEN** 构建产生文件但刷新前校验失败
- **THEN** 诊断分别保留构建成功和校验失败的事实、错误码及可用报告，不将整个过程归类为 Word 刷新失败

#### Scenario: One format fails after others succeed
- **WHEN** 同一捕获的 Word、HTML 已成功而 PDF 失败
- **THEN** 诊断保留各格式状态及实际失败阶段，成功文件仍可打开，聚合诊断不提升或降低已有成果的正式状态

#### Scenario: A failure is followed by cleanup or skipped stages
- **WHEN** 真实构建或校验失败后还记录了跳过、清理或结束事件
- **THEN** 结果、历史视图和 Markdown 诊断仍保留真正失败阶段、错误码及已存在源位置，不将最后一条清理事件或格式名当成唯一失败阶段

#### Scenario: Readable output exists despite a failed stage
- **WHEN** 任务保留了可用 Word，但其中一个实际阶段失败或未完成
- **THEN** 文件可打开性保持，失败阶段和待办仍进入诊断，不因文件可用而丢弃已发生的失败，也不把可读稿登记为正式成功

#### Scenario: Failure evidence reaches the real result view
- **WHEN** 真实导出服务返回内容或资源失败，且底层已产生结构化阶段与位置
- **THEN** 经结果记录转换后，界面、复制的 Markdown 和保存的诊断仍表达相同阶段和原章节位置，不要求调用者手工补造位置或重跑任务

### Requirement: Failure location maps to original authoring content

内容和资源问题的诊断 SHALL 在可核实时携带原项目内 Markdown 相对路径、原始行位置、资源引用及来源类型；临时文件位置 SHALL 作为技术详情保留而不替代原位置。预处理展开或行数改变后仍须保持映射。无法确定位置时 SHALL 标明未知及原因，定位动作仅打开当前项目内已核实目标，不通过临时路径猜造位置。

#### Scenario: Original image is read from a temporary resource directory
- **WHEN** 图片处理失败且该引用可映射到原 Markdown
- **THEN** 诊断同时指出原章节与图片引用、实际读取位置及失败阶段，用户可定位原文，不必在临时目录中反查来源

#### Scenario: Mermaid replacement changes later line numbers
- **WHEN** Mermaid 预处理改变文本行数，后面的普通图片触发错误
- **THEN** 诊断定位该图片在原 Markdown 的行号，不把预处理副本的行号当成原行号

#### Scenario: Location is ambiguous or stale
- **WHEN** 来源存在歧义、文件已移动或当前文本与错误发生时内容不一致
- **THEN** 诊断显示来源限制，提供查看证据或核实原文件的动作，不跳到一个未经验证的行号或修改当前正文

### Requirement: Diagnostics survive temporary cleanup and result reopening

系统 SHALL 自动保存每次导出的机器诊断及由同一事实生成的 Markdown 摘要，并从既有导出索引引用；其稳定存放位置 SHALL 不依赖工作快照或预处理临时目录。历史导出和重试的执行证据 SHALL 分别保留。关闭面板、重开项目及清理临时资源后，已保存诊断仍须可查看和复制。

#### Scenario: Reopen after a failed export
- **WHEN** 导出失败后临时目录被清理，用户重新打开该项目的导出记录
- **THEN** 可查看该次真实错误、阶段、来源与日志摘要，已有成功产物仍指向原文件，不要求重跑才能取得诊断

#### Scenario: Retry an existing export
- **WHEN** 用户沿原捕获重试失败格式
- **THEN** 新执行证据关联同一原输入并保留前次失败诊断，历史记录不会把第一次失败覆盖为从未发生

### Requirement: Diagnostic persistence failure preserves useful results

诊断写入 SHALL 使用安全写入方式，避免半写文件被当成完整记录。指定位置不可写时 SHALL 尝试已获准且可写的稳定导出位置；均不可用时 SHALL 显示诊断保存未完成并保留内存中的可复制摘要。诊断保存失败 SHALL 不删除已生成成果、不覆盖旧诊断，也不伪称已经持久保存。

#### Scenario: Diagnostic storage is unavailable
- **WHEN** Word 已生成但诊断主目录和允许的回退目录均不可写
- **THEN** Word 保持可打开，结果明确诊断未保存且当前会话仍可复制，下一次重开不声称存在该次持久诊断

#### Scenario: Write is interrupted
- **WHEN** 诊断保存或更新索引途中失败
- **THEN** 之前完整记录仍可读取，未完成的新记录显示缺失或不可用，不损坏正文、已有成果或其它导出记录

### Requirement: Diagnostic reading and report extensions remain compatible

已有导出索引和 CLI 机器结果 SHALL 通过可选字段扩展诊断，保留既有字段、格式状态与退出码含义。旧记录缺少诊断或新诊断字段无法识别时 SHALL 继续显示其可信成果并说明诊断限制。只读查询 SHALL 不补写历史或把当前内容重新执行后冒充旧证据；CLI 标准输出 SHALL 保持单一合法机器文档。

#### Scenario: Read an older export index
- **WHEN** 用户查看没有诊断字段的历史索引
- **THEN** 原格式状态、路径和可打开性按既有规则显示，诊断标未记录，读取过程不修改项目或捏造旧阶段

#### Scenario: Command line export fails
- **WHEN** CLI 执行导出遇到内容或资源错误
- **THEN** 机器结果包含可用诊断或明确未保存状态，标准输出可解析且无混入日志，原有完全失败与部分可用结果的退出码策略保持

### Requirement: Markdown diagnostic is readable and excludes sensitive content by default

查看、复制与保存的 Markdown 诊断 SHALL 由同一机器事实生成，包含结论、实际阶段、错误码、源位置、处理事实、适用建议及日志引用。默认 SHALL 不附文档全文、凭据、请求认证信息或异常对象局部变量；面向复制的技术路径 SHALL 脱敏，原始业务文本不得直接作为错误详情输出。未知事实 SHALL 明确为未知或未执行。

#### Scenario: Copy diagnostics for troubleshooting
- **WHEN** 用户在结果页选择复制诊断
- **THEN** 得到可直接阅读的 Markdown，阶段和位置与界面一致，既有记录中的敏感字段被过滤，缺 Word 及尚未执行的阶段按事实说明

#### Scenario: An exception contains document text
- **WHEN** 底层异常消息包含正文片段、访问凭据或用户目录信息
- **THEN** 对外复制摘要移除敏感内容并保留可排查的异常类别、错误码和脱敏位置，本地诊断访问遵循既有路径边界
