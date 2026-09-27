# markdown-template-fill 规格模板填充（Word 模板 + Markdown → 格式一致的 Word）

## ADDED Requirements

### Requirement: 模板样式解析
系统 SHALL 解析用户提供的 Word 模板（.docx）的样式表，推导「标题级别 → 样式ID」映射与正文样式，默认无需用户手动配置；解析 SHALL 复用统一安全 OOXML 解析入口。

#### Scenario: 标准 Heading 模板自动解析
- **WHEN** 用户选择样式规范（Heading 1~6 / 标题 1~6）的模板
- **THEN** 系统自动推导各级标题样式与正文样式，用户无需手动映射

#### Scenario: 自定义样式模板提示映射
- **WHEN** 模板标题使用自定义样式命名（如「章标题」）导致自动解析不完整
- **THEN** 系统列出候选样式与使用次数，允许用户把样式映射到级别 1~6 后继续转换

#### Scenario: 无标题样式的模板回退
- **WHEN** 模板未定义任何可用标题样式
- **THEN** 系统回退 Word 内置「标题 1~6」样式约定并给出告警，不阻断转换

#### Scenario: 映射有效性校验
- **WHEN** 用户提交的样式映射缺少级别 1 或映射后标题序列存在层级跳跃
- **THEN** 系统拒绝开始转换并提示具体错误位置对应的样式

### Requirement: 模板底模填充构建
系统 SHALL 以用户模板为底模生成 DOCX：模板的 styles.xml、页眉页脚、封面、节属性与多级列表编号 SHALL 原样保留，Markdown 内容按标题级别应用模板对应样式装配；转换 SHALL 支持单个或多个 Markdown 文件。

#### Scenario: 格式与模板一致
- **WHEN** 用户选择模板与 Markdown 文件执行转换
- **THEN** 产物 DOCX 的标题段落样式、正文字体字号、页眉页脚与封面版式与模板一致

#### Scenario: 标题编号继承
- **WHEN** 模板的多级列表编号与标题样式关联
- **THEN** 产物标题按模板编号规则自动编号；模板无关联多级列表时产物为无编号标题并告警

#### Scenario: 多文件合并填充
- **WHEN** 一次调用传入多个 Markdown 文件（服务/API 层）
- **THEN** 系统按传入顺序依次填充为同一文档的连续章节；互转中心按「每个 Markdown 一个 Word」逐文件填充

#### Scenario: 转换失败不留半成品
- **WHEN** 构建过程中发生不可恢复错误
- **THEN** 系统清理临时文件、不产出损坏的 DOCX，并给出包含原因的错误报告

### Requirement: 内容转换保真
系统 SHALL 将 Markdown 的标题、段落、列表、表格与图片转换为模板版式下的对应 Word 元素；相对路径图片 SHALL 内嵌到产物；无法内嵌的图片（缺失、远程）SHALL 告警但不阻断。

#### Scenario: 图片内嵌
- **WHEN** Markdown 引用相对路径图片且文件存在
- **THEN** 图片按模板版式内嵌到产物对应位置

#### Scenario: 图片缺失告警
- **WHEN** Markdown 引用的图片文件缺失或为远程地址
- **THEN** 转换完成并给出告警清单，不因单个图片失败而中止

### Requirement: 目录与域刷新
系统 SHALL 在产物中标记打开时刷新域（updateFields）；在具备 Word 环境时 SHALL 支持可选执行 COM 域刷新以直接产出带目录页码的成品。

#### Scenario: 有 Word 环境直接刷新
- **WHEN** 本机具备 Word 且用户启用域刷新
- **THEN** 产物目录与页码域已刷新为实际值，打开即为成品

#### Scenario: 离线环境保留刷新标记
- **WHEN** 本机无 Word 环境或用户未启用域刷新
- **THEN** 产物保留 updateFields 标记，Word 打开时提示刷新目录，转换不失败

### Requirement: 既有转换行为不变
模板填充 SHALL 为纯增量能力：不选择模板时互转中心与 CLI 的行为 SHALL 与既有完全一致；新增参数 SHALL 为可选且默认不启用模板填充。

#### Scenario: 不选模板走既有版式
- **WHEN** 用户在互转中心选择 Markdown 转 Word 且不选择底模
- **THEN** 转换走既有 CSS 版式链路，产物与升级前一致

#### Scenario: 既有调用方无需修改
- **WHEN** 既有代码或脚本调用 `convert_paths` 与 `convert` CLI 而不传新参数
- **THEN** 行为与升级前完全一致
