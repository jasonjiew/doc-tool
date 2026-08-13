## MODIFIED Requirements

### Requirement: 术语/一致性检查
系统 SHALL 从配置读取可执行的质量规则集执行检查，规则按类别组织（必备章节、字段完整性、编号唯一性、术语、敏感信息、接口表结构、文档类型专属规则），结果项 SHALL 携带稳定的 `rule_id` 与 `severity`（error/warning/info）。内置三类基础规则（重复标题、术语大小写不一致、TODO/TBD 残留）作为默认开启的规则保留，检查语义与结果定位能力不变。术语清单（大小写敏感对）存于项目 `.state/terms.json`，可在结果面板增删。

#### Scenario: 检出重复标题
- **WHEN** 两个以上 .md 文件或同文件内存在完全相同的标题文本
- **THEN** 系统在检查结果中列出重复标题及各自位置，并标记对应 `rule_id` 与 `severity`

#### Scenario: 检出术语大小写不一致
- **WHEN** 术语清单配置了大小写敏感对（如 `KSHC` 与 `kshc`），正文出现非规范写法
- **THEN** 系统在检查结果中标记非规范写法及其位置，供用户统一

#### Scenario: 检出 TODO/TBD 残留
- **WHEN** .md 正文包含 `TODO`、`TBD`、`待补充` 等残留标记
- **THEN** 系统列出残留标记及其位置

#### Scenario: 结果点击定位
- **WHEN** 用户点击某条检查结果
- **THEN** 系统打开对应 .md 并定位到命中位置

#### Scenario: 按配置执行规则集
- **WHEN** 用户启用了某文档类型专属规则或关闭某默认规则
- **THEN** 系统仅执行配置中开启的规则，结果项带对应 `rule_id` 与 `severity`
