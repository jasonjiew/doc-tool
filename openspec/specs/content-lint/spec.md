# content-lint

## Purpose

术语/一致性检查能力:重复标题、术语大小写不一致、TODO/TBD 残留检测,结果可点击定位。

## Requirements

### Requirement: 术语/一致性检查
系统 SHALL 提供三类内容一致性检查：重复标题、术语大小写不一致、TODO/TBD 残留标记。检查结果 SHALL 复用搜索结果面板展示，支持点击定位。术语清单（大小写敏感对）存于项目 `.state/terms.json`，可在结果面板增删。

#### Scenario: 检出重复标题
- **WHEN** 两个以上 .md 文件或同文件内存在完全相同的标题文本
- **THEN** 系统在检查结果中列出重复标题及各自位置

#### Scenario: 检出术语大小写不一致
- **WHEN** 术语清单配置了大小写敏感对（如 `KSHC` 与 `kshc`），正文出现非规范写法
- **THEN** 系统在检查结果中标记非规范写法及其位置，供用户统一

#### Scenario: 检出 TODO/TBD 残留
- **WHEN** .md 正文包含 `TODO`、`TBD`、`待补充` 等残留标记
- **THEN** 系统列出残留标记及其位置

#### Scenario: 结果点击定位
- **WHEN** 用户点击某条检查结果
- **THEN** 系统打开对应 .md 并定位到命中位置

### Requirement: 术语清单维护
系统 SHALL 允许用户在结果面板直接查看与增删术语大小写对，术语清单变更后立即生效并重跑相关检查。

#### Scenario: 新增术语条目
- **WHEN** 用户在术语清单中新增一对大小写敏感词
- **THEN** 系统保存到 `.state/terms.json` 并重跑术语大小写检查，纳入新规则

#### Scenario: 删除术语条目
- **WHEN** 用户删除某术语条目
- **THEN** 系统从 `.state/terms.json` 移除该条目，后续检查不再应用该规则
