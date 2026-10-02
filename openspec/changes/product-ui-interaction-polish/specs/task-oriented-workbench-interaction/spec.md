## ADDED Requirements

### Requirement: Consistent document entry and primary action
系统 SHALL 让首页主区域拖放与导入按钮调用同一实际建项路由，区分工具转换区域，保留当前未保存文档；顶部日常主操作使用现有整份/当前内容快速Word导出，菜单/按钮/Ctrl+E同handler与可用性，技术动作按需可达。

#### Scenario: Import by dropping a document
- **WHEN** 用户向首页主区域拖入有效 DOCX 或 Markdown
- **THEN** 使用与导入按钮相同的建项服务，不能意外进入互转，源已选择后最多2次主要提交进入编辑

#### Scenario: Export current edits
- **WHEN** 用户在文档工作台点击顶部导出 Word
- **THEN** 调用真实快速导出并反映整份/当前内容来源，已有未保存内容按 CORE 捕获处理

#### Scenario: Start quick export after an advanced round
- **WHEN** 之前出稿使用部分章节、saved来源或strict，而用户再次点顶部“导出 Word”
- **THEN** 使用整份/current-buffer的日常默认，不隐式继承旧高级决定；无Git/Word不会额外阻断可读稿，已有冲突任务只限制本次重复启动

#### Scenario: Import with existing dirty tabs
- **WHEN** 当前工作区有未保存修改而用户发起导入或接收外部修订
- **THEN** 沿现有上下文和未保存处理，DOCX逐份及MD顺序组稿各自语义明确，不因入口调整自动覆盖或切走当前缓冲

### Requirement: Commands share discoverable entry and availability
系统 SHALL 将重复命令分组合并为单一可发现入口，同一动作在菜单、顶部及命令面板使用既有注册表/handler和实际可用性，禁用依赖动作给出具体原因而不阻断无关写作。

#### Scenario: Invoke the same primary action from different entries
- **WHEN** 用户从按钮、菜单或命令面板发起同一日常动作
- **THEN** 实际参数/默认行为一致，普通成功不追加强制确认，当前冲突条件在各入口一致反映

### Requirement: Import has a clear default path
系统 SHALL 在选源后突出普通开始导入，细调章节/映射为可发现的副操作，预检及提取仍使用相同决定，失败保留输入及可用恢复动作。

#### Scenario: Continue without advanced settings
- **WHEN** 有效来源已自动识别而用户未请求细调
- **THEN** 用户直接开始导入，无强制风险确认或编号填写，仍保留高级路径

### Requirement: Advanced features have a first-use path
系统 SHALL 用已有服务提供新建交付批次的成员/变体/格式/目录表单、模块空库创建/安装入口和辅助资料范围说明；高级文件导入及技术详情仍可用，不要求用户先手写 JSON。

#### Scenario: Create the first delivery batch
- **WHEN** 用户尚无 batch.json 并选择批量交付
- **THEN** 可用表单生成原服务可消费的计划并开始，缺成员只影响对应项

#### Scenario: Some batch members are invalid
- **WHEN** 新建表单包含合法和失效成员
- **THEN** 原服务校验后的合法成员可执行，失效项有定位/移除/跳过动作；全部无效时保留输入并解释原因，不假报开始或全批完成

#### Scenario: Empty module library
- **WHEN** 当前项目没有模块
- **THEN** 界面提供从当前章节创建或安装已有模块的实际动作，普通编辑仍可继续

#### Scenario: Insert a selected module version
- **WHEN** 用户选定已有模块和明确版本，插入固定引用或复制正文
- **THEN** 使用已有模块/资源与编辑器事务，来源可解析且一次撤销还原；当前缓冲为空时不能拿旧磁盘内容冒充创建来源

#### Scenario: No assistance scope
- **WHEN** 辅助功能没有本地资料范围
- **THEN** 界面解释范围及下一步，依赖范围的动作不冒充有效，编辑/出稿不受阻
