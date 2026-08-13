## ADDED Requirements

### Requirement: 规则配置存储
系统 SHALL 提供可配置的质量规则集，配置落盘项目 `.state/quality_rules.json`，每条规则含 `rule_id`、`enabled`、`severity`（error/warning/info，`info` 为只读结果级别，可配置严重级别为 error/warning）与规则参数；配置读写沿用 `TermStore` 的原子写模式（`.tmp` + `os.replace`），损坏或缺失时回退默认配置，`rules` 为空列表（全部关闭）时不得回退默认。

#### Scenario: 保存规则配置
- **WHEN** 用户修改规则开关、严重级别或参数并保存
- **THEN** 系统原子写入 `.state/quality_rules.json`，后续检查按新配置执行

#### Scenario: 配置缺失回退默认
- **WHEN** 项目没有 `.state/quality_rules.json` 或文件损坏
- **THEN** 系统以文档类型默认规则集执行检查，不报错、不写坏配置

#### Scenario: 只读项目不可写配置
- **WHEN** 项目以只读方式打开
- **THEN** 系统可查看规则配置，但禁用保存入口，不写 `.state/`

### Requirement: 必备章节检查
系统 SHALL 依据规则配置检查文档是否包含必备章节（按文档类型配置标题文本集合，如需求文档的「范围」「总体描述」），缺失时输出带 `severity` 与 `rule_id=required_section` 的检查结果。

#### Scenario: 检出缺失必备章节
- **WHEN** 文档类型配置了必备章节，且某必备标题在索引标题清单中不存在
- **THEN** 系统输出一条 `required_section` 结果，标注缺失章节名与建议插入位置

#### Scenario: 必备章节全部存在
- **WHEN** 文档包含全部配置的必备章节
- **THEN** 系统不输出 `required_section` 结果

### Requirement: 字段完整性检查
系统 SHALL 依据规则配置检查正文必填字段（配置为「字段名 → 正则/出现次数」），如文档编号、修订记录等字段缺失或格式不符时输出 `rule_id=field_completeness` 结果，可点击定位到相关章节。

#### Scenario: 检出必填字段缺失
- **WHEN** 配置的必填字段在正文中不存在
- **THEN** 系统输出 `field_completeness` 结果并定位到最可能的章节

#### Scenario: 字段存在但格式不符
- **WHEN** 字段内容不匹配配置的格式正则
- **THEN** 系统输出结果并给出期望格式说明

### Requirement: 编号唯一性检查
系统 SHALL 检查章节编号与锚点编号的唯一性：跨文件重复的章节号（`X.Y` 前缀）与重复的标题锚点输出 `rule_id=numbering_uniqueness` 结果，沿用 `index.py` 标题索引与 `references.py` 的 `leading_number` 解析。

#### Scenario: 检出重复章节号
- **WHEN** 两个不同文件或标题使用相同的章节号前缀
- **THEN** 系统列出所有出现位置，并标记后出现的重复项

#### Scenario: 编号唯一时无结果
- **WHEN** 全部章节号唯一
- **THEN** 系统不输出 `numbering_uniqueness` 结果

### Requirement: 敏感信息检查
系统 SHALL 依据可配置的敏感信息模式（默认含手机号、身份证号、明文口令关键词）扫描正文，命中时输出 `rule_id=sensitive_info` 结果；默认级别为 `warning`，模式可在配置中增删。

#### Scenario: 检出敏感信息
- **WHEN** 正文包含配置的敏感信息模式
- **THEN** 系统输出 `sensitive_info` 结果并定位到命中行

#### Scenario: 命中默认级别为告警
- **WHEN** 敏感信息规则未被单独配置严重级别
- **THEN** 结果严重级别为 `warning`，不阻断正式构建

#### Scenario: 关闭敏感信息规则
- **WHEN** 用户在配置中关闭 `sensitive_info` 规则
- **THEN** 后续检查不再输出该规则的结果

### Requirement: 接口表结构检查
系统 SHALL 检查标题含「接口」的章节是否包含接口表格（含表头与数据行），缺失时输出 `rule_id=interface_table_structure` 结果；需求文档默认开启该规则。

#### Scenario: 检出接口章节缺表
- **WHEN** 某「接口」章节正文没有以 `|` 开头的表格行
- **THEN** 系统输出 `interface_table_structure` 结果并定位到该章节

#### Scenario: 接口章节含表不报
- **WHEN** 「接口」章节包含接口表格（表头 + 数据行）
- **THEN** 系统不输出 `interface_table_structure` 结果

### Requirement: 文档类型专属规则
系统 SHALL 为 `requirement` / `design` / `general` 三类文档提供各自的默认规则集（如需求文档默认开启必备章节与接口表结构检查，设计文档默认开启编号唯一性），并允许用户按项目覆盖。

#### Scenario: 默认规则随文档类型
- **WHEN** 新项目为需求文档且未自定义规则
- **THEN** 系统按其默认规则集执行检查

#### Scenario: 项目级覆盖默认规则
- **WHEN** 用户为某项目关闭某条默认规则并保存
- **THEN** 该项目后续检查以覆盖后的配置执行，其他项目不受影响
