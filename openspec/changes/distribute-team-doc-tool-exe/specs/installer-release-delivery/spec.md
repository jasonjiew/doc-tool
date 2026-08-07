## ADDED Requirements

### Requirement: The installed application is self-contained
发布包 SHALL 捆绑兼容的 Python 运行时、应用代码、模板资源以及运行期依赖，团队成员安装后 MUST NOT 需要单独安装 Python、pip、pyyaml、lxml、Pillow 或 pywin32。

#### Scenario: Launch on a clean supported Windows computer
- **WHEN** 用户在未安装 Python但满足系统要求的 Windows 电脑上安装并启动应用
- **THEN** 应用可以打开、新建项目并执行不依赖 Word 的预检与拆分功能

### Requirement: One setup executable installs the directory-based application bundle
构建系统 SHALL 先生成经过冒烟测试的 PyInstaller onedir 应用，再将其封装为单个版本化 Setup EXE，安装器 MUST 创建可识别的应用版本和开始菜单入口。

#### Scenario: Install a release package
- **WHEN** 用户运行 `KonsungDocTool-Setup-X.Y.Z.exe` 并完成安装
- **THEN** 安装目录包含应用可执行文件及受管理依赖，开始菜单入口能启动相同版本应用

### Requirement: Application files and user projects are isolated
安装器 MUST 只拥有程序安装目录中的应用文件，不得把用户项目登记为安装内容；应用升级、修复和卸载 SHALL 保留用户选择目录中的 `original/content/assets/output`。

#### Scenario: Upgrade the application
- **WHEN** 用户从旧版本安装器升级到兼容新版本
- **THEN** 应用文件被替换，已有项目内容和上次有效输出保持不变

#### Scenario: Uninstall the application
- **WHEN** 用户卸载应用
- **THEN** 程序快捷方式和安装文件被删除，外部用户项目仍完整存在

### Requirement: Releases are built from versioned private Git source
正式发布 MUST 来自公司私有 Git 中的不可变版本标签，应用内版本、安装器版本和标签 SHALL 一致；工作区存在未提交更改的本地构建不得被标记为正式 Release。

#### Scenario: Build a tagged release
- **WHEN** CI 处理合法的 `vX.Y.Z` 标签
- **THEN** CI 从该提交生成版本一致的应用和安装器，并把提交标识写入可查看的构建信息

#### Scenario: Version mismatch
- **WHEN** 标签、应用版本或安装器版本不一致
- **THEN** 发布流水线失败且不创建正式 Release

### Requirement: The release pipeline enforces quality gates
CI MUST 在发布安装器前运行单元测试、输入契约测试、负向校验、导入/维护/合并回归、冻结程序冒烟以及安装/升级/卸载数据保留测试。

#### Scenario: Any release test fails
- **WHEN** 任一测试或安装级冒烟返回失败
- **THEN** 流水线停止，不上传或发布该版本安装包

### Requirement: Release artifacts provide integrity and provenance
每个 Release SHALL 至少包含版本化安装器、SHA-256 校验清单和发布说明；若公司提供代码签名证书，程序与安装器 MUST 在发布前签名并验证签名。

#### Scenario: Download a release
- **WHEN** 团队成员查看一个成功发布的版本
- **THEN** 能下载安装器和对应哈希，并从发布说明看到版本、兼容环境、变更和已知限制

#### Scenario: Configured signature validation fails
- **WHEN** CI 已配置代码签名但签名或验证步骤失败
- **THEN** 流水线停止且不得发布未通过签名验证的安装器

### Requirement: Production documents are excluded from application packages
打包清单 MUST 只包含应用资源、净化模板和测试夹具，不得包含 `projects/`、生产 `output/`、真实客户 DOCX 或项目日志；CI SHALL 对打包文件清单执行拒绝规则。

#### Scenario: Production DOCX appears in package inputs
- **WHEN** 打包目录意外包含未列入允许清单的生产 DOCX
- **THEN** CI 阻断打包并报告违规路径，不生成安装器

### Requirement: Installed application reports environment readiness
应用 SHALL 显示应用版本、提交标识、项目模式版本、Windows 信息和 Word 可用性，并提供可复制的脱敏诊断摘要。

#### Scenario: User requests support information
- **WHEN** 用户打开“关于/环境诊断”并复制摘要
- **THEN** 摘要包含定位版本和依赖状态所需信息，但不包含正文、凭据或用户项目业务内容

### Requirement: Rollback does not perform destructive project downgrade
安装器 SHALL 允许重新安装上一受支持应用版本，但旧应用遇到更高项目模式版本时 MUST 拒绝写入，而不是自动降级或删除项目数据。

#### Scenario: Older application opens a newer project
- **WHEN** 回滚后的应用打开由更高模式版本保存的项目
- **THEN** 应用只读显示并提示恢复兼容版本，不修改项目清单或内容
