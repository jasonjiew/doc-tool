## ADDED Requirements

### Requirement: Local drafts are independent of installed packs
系统 SHALL 提供从现有包或选定项目资源创建本地制作草稿的 GUI，允许不完整草稿保存，并与已安装固定版本及源项目分离。

#### Scenario: Save unfinished draft
- **WHEN** 用户选择模板和骨架但尚未填写版本
- **THEN** 草稿能保存/重开，不能被误报为已可安装包，源项目不变

### Requirement: Editors respect existing resource formats
系统 SHALL 提供基础信息、模板、骨架、变量、术语和支持规则的制作界面，按现有包消费者建立资源映射并保留未知声明字段；变量应用位置必须符合实际支持范围。

#### Scenario: Convert project configuration to pack resources
- **WHEN** 用户将项目支持的变量和术语选入制作草稿
- **THEN** 生成现有包消费者可读取的资源，样例项目读回值一致

#### Scenario: Template fields outside supported scope
- **WHEN** 模板页眉含当前替换器未支持的占位
- **THEN** 界面显示未绑定及模板编辑入口，不将正文变量测试当作页眉替换成功

### Requirement: Frozen packages preserve version identity
系统 SHALL 沿用 schema 1 生成文件摘要及可消费 ZIP，阻止同身份版本的不同内容静默覆盖，提供另存新版本，并保持源项目现有固定资源不变。

#### Scenario: Export changed existing version
- **WHEN** 用户修改已冻结版本并用同版本号导出
- **THEN** 不覆盖既有产物，提供新版本/新目录操作，当前项目固定包仍不改变

### Requirement: Sharing exports only declared resources
系统 SHALL 在导出前展示文件清单，只包含选定规范资源、骨架及必要包内资产，排除凭证、Git、缓存、历史和交付输出，分享操作只生成本地文件。

#### Scenario: Export from a project with history
- **WHEN** 来源项目有 .git、用户配置与构建输出
- **THEN** 导出 ZIP 不含这些目录，现有规范包加载器能读取所选资源
