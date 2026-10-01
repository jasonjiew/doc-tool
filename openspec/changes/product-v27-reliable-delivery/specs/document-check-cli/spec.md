## ADDED Requirements

### Requirement: 统一检查命令
系统 SHALL 提供 `check --project <dir> --output text|json|sarif --fail-on error|warning [--build] [--strict]`，复用 GUI 的检查与兜底。默认 fail-on error，warning 自动继续；严格策略由 --strict 或已有明确策略选项启用。

#### Scenario: 同项目检查结果一致
- **WHEN** 同一项目通过 GUI 与 CLI 使用同一规则检查
- **THEN** 问题规则、严重度、来源和阻断结论相同，结果顺序确定

### Requirement: 退出码明确
CLI MUST 使用 0 表示未达到失败阈值、1 表示检查/构建问题达到阈值、2 表示参数或执行失败；运行失败不得伪装检查通过。

#### Scenario: warning 阈值
- **WHEN** 项目只有 warning 且 fail-on 为 warning
- **THEN** 命令退出 1；fail-on 为 error 时退出 0

#### Scenario: 参数或执行失败
- **WHEN** 项目路径不存在或任务运行失败
- **THEN** 命令退出 2 并给出可定位原因

### Requirement: 可解析输出
系统 SHALL 为 JSON 检查和构建报告输出 schemaVersion、command、projectId、status、issues、stages、artifacts、exitCode；SARIF 使用稳定规则 ID。结构化 stdout MUST 不混入日志，运行信息走 stderr。

#### Scenario: 自动化解析
- **WHEN** 调用 check 或 build 并选择 JSON 输出
- **THEN** stdout 可作为单一 JSON 文档解析，阶段未执行/失败信息和退出码一致

#### Scenario: SARIF 导出
- **WHEN** 选择 SARIF 输出
- **THEN** 输出可解析的 SARIF，并保留原 Markdown 的文件与行位置
