## ADDED Requirements

### Requirement: Import accepts a company DOCX with an arbitrary filename
系统 SHALL 允许用户选择任意合法文件名的 `.docx`，并显式选择或确认需求说明书/详细设计说明书类型，不得依赖硬编码源文件名。

#### Scenario: Import a valid renamed DOCX
- **WHEN** 用户选择一个结构合法但文件名与历史基线不同的公司 DOCX，并确认文档类型
- **THEN** 系统使用所选文件作为项目源文档继续预检，不因文件名不同而失败

#### Scenario: Reject unsupported input
- **WHEN** 用户选择非 DOCX、加密包或无法解析的文件
- **THEN** 系统拒绝导入，显示稳定错误码和修复建议，且不创建项目目录

### Requirement: Source structure is validated before extraction
系统 MUST 在写入正式项目之前校验 DOCX ZIP/XML、关系目标、Heading 样式映射、至少一个 Heading 1 以及可闭合的章节层级。

#### Scenario: Valid heading structure
- **WHEN** 源文档的 Heading 1~3 能映射为合法章节树
- **THEN** 系统显示标题级别计数和章节摘要，并允许继续导入

#### Scenario: Missing Heading 1
- **WHEN** 源文档没有可识别的 Heading 1
- **THEN** 系统阻断导入并说明需要修复 Word 标题样式，不依据加粗文本静默猜测章节

### Requirement: Import is transactional and atomic
系统 SHALL 在目标父目录的唯一暂存目录完成复制、模板生成、正文/资源提取、章节拆分和验证，只有全部成功后才原子发布正式项目。

#### Scenario: Successful atomic publication
- **WHEN** 所有导入阶段和试构建验证均成功
- **THEN** 系统将暂存目录原子重命名为最终项目目录，并将项目状态标记为可用

#### Scenario: Failure during extraction
- **WHEN** 图片关系、复杂表格提取或章节验证任一阶段失败
- **THEN** 系统不发布正式项目，不修改源文档，并提供诊断日志位置

### Requirement: Existing projects are protected from re-import overwrite
系统 MUST 默认拒绝将首次导入结果写入一个已经存在的项目目录，且不得隐式删除或合并其中的 Markdown。

#### Scenario: Target project already exists
- **WHEN** 用户指定的最终项目目录已经存在
- **THEN** 系统在任何提取写入前停止，并要求选择新项目名称或其他目录

### Requirement: Original document and template are preserved
系统 SHALL 把源 DOCX 的只读副本和 SHA-256 保存到项目中，并从该副本生成保留封面、修订记录、样式、编号、分节、页眉、页脚和页面设置的项目模板。

#### Scenario: Import completes
- **WHEN** 合法公司 DOCX 导入成功
- **THEN** `original/source.docx` 与用户选择的源文件内容哈希一致，项目模板保留正文前公司模板体系且不包含旧业务正文

### Requirement: Chapter tree follows Word heading hierarchy
系统 SHALL 将 Heading 1 生成一级章节目录，将具有子节点的 Heading 2 生成二级目录，将 Heading 3 生成独立 Markdown，并把父章节自身正文写入同目录 `_index.md` 且位于子章节之前。

#### Scenario: Split a feature chapter
- **WHEN** Word 包含 Heading 1“第3章 功能需求”、Heading 2“3.1 KSHC”及 Heading 3“3.1.1 登录页”“3.1.2 首页”
- **THEN** 系统生成对应的两级目录和两个 Markdown 文件，文件路径与章节层级一致

#### Scenario: Parent heading contains body
- **WHEN** Heading 2 后存在正文且随后还有 Heading 3
- **THEN** 系统把该正文写入 Heading 2 目录的 `_index.md`，不并入第一个 Heading 3 文件

### Requirement: Business elements and order are extracted without silent loss
系统 MUST 按源文档顺序提取正文、真实换行、内部标题、普通表格、图片和复杂表格；不能无损表达为 Markdown 的表格 SHALL 保存为受引用的 OOXML 资源。

#### Scenario: Mixed content extraction
- **WHEN** 一个章节依次包含正文、图片、普通表格和合并单元格复杂表格
- **THEN** 生成的 Markdown 与资源引用保持相同事件顺序，且所有引用资源存在并可解析

#### Scenario: Missing relationship target
- **WHEN** 源文档正文引用不存在的图片 relationship 目标
- **THEN** 系统让导入失败而不是跳过该图片或生成残缺项目

### Requirement: Project manifest is portable and versioned
系统 SHALL 创建包含模式版本、项目标识、文档元数据、相对路径、源哈希和创建版本的 `project.yml`；所有持久化资源路径 MUST 相对项目根并经过目录包含校验。

#### Scenario: Move project to another computer
- **WHEN** 用户把完整项目目录复制到另一台安装了兼容应用的电脑
- **THEN** 系统仅依赖项目内相对路径打开和校验项目，不要求原电脑绝对路径存在

#### Scenario: Resource path escapes project root
- **WHEN** 项目清单或 Markdown 资源解析到项目根以外的位置
- **THEN** 系统拒绝读取或打包该资源并报告安全错误
