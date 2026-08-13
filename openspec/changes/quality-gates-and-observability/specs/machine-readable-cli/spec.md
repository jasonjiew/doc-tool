## ADDED Requirements

### Requirement: 命令集扩展

CLI SHALL 在既有 `build`/`info` 之外提供 `preflight`、`import`、`validate`、`lint`、`search`、`status` 子命令，每个命令 SHALL 复用对应应用服务与既有校验/安全边界，不绕过项目锁、取消令牌与错误码映射。未定义命令 SHALL 以参数错误退出并打印帮助提示。

#### Scenario: preflight 命令

- **WHEN** 用户运行 `doc-tool preflight --docx <文件>`
- **THEN** 执行现有导入预检并报告结果与错误码

#### Scenario: import 命令

- **WHEN** 用户运行 `doc-tool import --docx <文件> --name <项目名>`
- **THEN** 执行导入并输出新项目路径

#### Scenario: validate、lint、search、status 命令

- **WHEN** 用户分别运行 `validate`、`lint`、`search`、`status`
- **THEN** 分别输出校验结果、lint 发现、搜索结果与项目状态

#### Scenario: 未知子命令

- **WHEN** 用户输入未定义的子命令
- **THEN** 以参数错误退出（退出码 2）并在 stderr 打印用法提示

### Requirement: JSON 输出

上述命令 SHALL 支持 `--output json`，输出稳定的 JSON schema（含命令名、成功与否、错误码、结果对象/数组）；默认人类可读输出 SHALL 保持为现有样式，JSON 模式 MUST 不把日志与进度文本写入 stdout。

#### Scenario: JSON 结构稳定

- **WHEN** 用户以 `--output json` 运行 `validate`
- **THEN** stdout 是单一合法 JSON 文档，字段名与结构稳定

#### Scenario: 失败也输出合法 JSON

- **WHEN** 命令失败且使用 JSON 输出
- **THEN** stdout 仍是合法 JSON，包含错误码与建议，退出码按失败语义返回

#### Scenario: 默认人类可读

- **WHEN** 用户不指定 `--output`
- **THEN** 输出与现有命令一致的简洁中文文本

### Requirement: SARIF 输出

`validate` 与 `lint` 命令 SHALL 支持 `--format sarif`，输出 SARIF 2.1.0 兼容报告：规则 SHALL 映射到错误码或规则 id，结果 SHALL 携带 level（映射严重度）与指向文件行的 location；无问题时 SHALL 输出含空 results 的合法 SARIF。

#### Scenario: validate SARIF

- **WHEN** 校验存在失败条目
- **THEN** SARIF 包含对应 result，level 映射严重度，location 指向文件与行

#### Scenario: lint SARIF

- **WHEN** lint 检查发现命中
- **THEN** SARIF 报告包含 ruleId 与 message，定位到文件行

#### Scenario: 无问题的 SARIF

- **WHEN** 校验全部通过
- **THEN** 输出含空 results 数组的合法 SARIF 2.1.0 文档

### Requirement: JUnit 输出

`validate` 命令 SHALL 支持 `--format junit`，输出 JUnit XML，使 CI 可展示与门禁；每个文档类型或项目 SHALL 对应独立 testcase/testsuite，失败条目 SHALL 映射为失败的 testcase 并携带消息。

#### Scenario: 校验 JUnit

- **WHEN** 校验完成并以 JUnit 格式输出
- **THEN** 生成 JUnit XML，失败条目映射为失败 testcase

#### Scenario: 批量项目 JUnit

- **WHEN** 一次校验多个项目
- **THEN** 每个项目或文档类型对应独立 testsuite，汇总结果可被 CI 消费

### Requirement: 批量项目处理与稳定退出码

相关命令 SHALL 支持一次传入多个项目（重复 `--project` 或参数列表），逐项目执行并聚合结果；退出码 SHALL 遵循稳定语义：0 全部成功、1 至少一个失败、2 参数错误、3 批量部分成功。

#### Scenario: 批量全部成功

- **WHEN** 校验两个项目且均通过
- **THEN** 退出码为 0，JSON 结果包含两个项目的独立结果

#### Scenario: 批量部分失败

- **WHEN** 两个项目中一个成功一个失败
- **THEN** 退出码为 3，结果区分成功与失败项目及其错误码

#### Scenario: 参数错误

- **WHEN** 缺少必需参数或参数非法
- **THEN** 退出码为 2，stderr 打印用法说明

### Requirement: 进度与日志隔离

机器可读模式下，进度事件与日志 SHALL 写入 stderr 或日志文件，MUST 不污染 stdout 的数据输出；批量执行中单个项目失败 SHALL 不中断其余项目。

#### Scenario: 日志不污染 stdout

- **WHEN** 批量命令以 JSON 模式运行且管线产生进度事件
- **THEN** stdout 只含最终 JSON，进度与日志出现在 stderr 或日志文件

#### Scenario: 单项目失败不中断批量

- **WHEN** 批量执行中某个项目失败
- **THEN** 其余项目继续执行，最终结果聚合所有项目的成功与失败信息
