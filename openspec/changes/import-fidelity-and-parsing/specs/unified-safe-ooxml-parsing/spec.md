## ADDED Requirements

### Requirement: 统一安全 OOXML 解析入口
系统 SHALL 提供单一的安全 OOXML 解析入口 `doc_tool/domain/ooxml.py`，模板生成、复杂表格读取、导入、构建与校验 SHALL 全部经同一入口读取 DOCX 包与解析 XML 部件，不得在 `preflight.py`、`importer.py`、`build_docx.py`、`validate_docx.py` 等处各自实现包读取与 XML 解析。

#### Scenario: 五个链路读取同一包入口
- **WHEN** 模板生成、导入预检、构建、校验或复杂表格读取需要打开同一个 DOCX 包
- **THEN** 五个链路调用同一 `read_docx_package` 入口读取部件，行为与安全参数完全一致

#### Scenario: 解析函数唯一
- **WHEN** 任意链路需要把 XML 部件字节解析为 lxml 元素树
- **THEN** 调用统一的 `parse_xml_safe`，仓库内不存在第二条可被业务代码直接调用的 XML 解析路径

#### Scenario: 删除重复解析实现
- **WHEN** 统一入口就绪后审查 `preflight.py` / `importer.py` / `build_docx.py` / `validate_docx.py` 的解析代码
- **THEN** 各模块不再包含独立的 `etree.fromstring` 调用点，重复的 ZIP 上限检查与 XML 防御参数被删除

### Requirement: 包体量与压缩比安全上限
系统 SHALL 在解压前校验 DOCX 包体量：条目数、总展开体积、单条目体积、压缩比均不得超过安全上限；任一超限 SHALL 拒绝读取并报告具体条目。上限 SHALL 由统一入口集中定义，全链路一致。

#### Scenario: 条目数超限被拒绝
- **WHEN** DOCX 包包含超过 20000 个 ZIP 条目
- **THEN** 系统拒绝读取该包，报告条目数超限

#### Scenario: 单条目体积超限被拒绝
- **WHEN** 包内存在超过 256MB 的单个条目
- **THEN** 系统拒绝读取，报告超限条目名

#### Scenario: 异常压缩比被拒绝
- **WHEN** 包内某条目压缩比超过 2000 倍（解压炸弹特征）
- **THEN** 系统在解压前拒绝读取，不展开该条目

#### Scenario: 正常包不受影响
- **WHEN** DOCX 包体量在安全上限内且 CRC 校验通过
- **THEN** 系统正常读取全部所需部件，不产生误拒绝

### Requirement: XML 安全解析与良构校验
系统 SHALL 以禁用 DTD、实体解析、网络访问与超大树模式的安全解析器解析全部 XML/rels 部件；部件包含 DTD 或实体声明 SHALL 被拒绝；XML 良构错误 SHALL 被识别为解析失败而非崩溃。

#### Scenario: DTD/实体声明被拒绝
- **WHEN** XML 部件包含 `<!DOCTYPE` 或 `<!ENTITY` 声明
- **THEN** 系统拒绝该部件并给出部件名

#### Scenario: 良构错误被识别
- **WHEN** XML 部件存在未闭合标签或其他良构错误
- **THEN** 系统报告该部件的解析失败与原因，不抛未捕获异常

#### Scenario: 正常 XML 解析成功
- **WHEN** 部件为标准 OOXML 且无 DTD/实体声明
- **THEN** 系统以禁用网络与外部实体模式解析成功

### Requirement: 关系目标与正文引用完整性统一校验
系统 SHALL 在统一入口校验每条 relationship 的目标部件存在（外部链接与文档内书签锚点除外）、正文引用的 rId 在关系表中存在、图片关系不指向外部链接；该校验 SHALL 全链路复用同一实现，替代预检与校验器各自的独立逻辑。

#### Scenario: 关系目标缺失被检出
- **WHEN** 某 relationship 的 Target 在包内不存在且非外部链接
- **THEN** 系统报告目标缺失并给出 rId 与解析后的目标路径

#### Scenario: 正文引用不存在的 rId 被检出
- **WHEN** 正文 `w:drawing`/`w:hyperlink`/`v:imagedata` 引用了关系表中不存在的 rId
- **THEN** 系统报告缺失 rId 并给出建议

#### Scenario: 外部链接图片被检出
- **WHEN** 正文图片关系为外部链接（TargetMode=External 或 URL 目标）
- **THEN** 导入侧将其视为不可生成自包含项目的错误，构建/校验侧给出同类提示

#### Scenario: 书签锚点不误报
- **WHEN** 超链接的目标是文档内书签（如 `_Toc123`，TargetMode=Internal）
- **THEN** 系统不将其当作缺失部件误报

### Requirement: 标题样式与文本提取逻辑收敛
系统 SHALL 将 heading 样式解析、标题树构建、层级跳跃校验与段落文本提取收敛到统一实现，供导入、构建、校验复用；各链路的标题识别结果 SHALL 保持一致。

#### Scenario: 标题样式映射三处一致
- **WHEN** 同一源文档分别经导入、构建、校验识别 Heading 样式映射
- **THEN** 三处得到相同的 styleId→级别映射

#### Scenario: 层级跳跃规则一致
- **WHEN** 导入预检与构建前检查分别校验标题层级
- **THEN** 采用同一规则：首个标题须为 H1，后续级别递增不超过 1

### Requirement: 错误映射与稳定错误码
统一入口 SHALL 抛出中性解析异常（含部件名与原因），不直接抛 lxml 异常；各调用方 SHALL 将中性异常映射为自己的错误类型——导入侧映射为 `InvalidDocxError`/`BrokenRelationshipError` 等 `DocToolError` 子类，构建/校验侧映射为 `AutomationError`，并给出稳定错误码与修复建议。

#### Scenario: 导入侧映射
- **WHEN** 导入预检捕获统一入口抛出的解析异常
- **THEN** 系统映射为对应 `DocToolError` 子类，带错误码、用户可读信息与建议动作

#### Scenario: 构建/校验侧映射
- **WHEN** 构建或校验捕获统一入口抛出的解析异常
- **THEN** 系统映射为 `AutomationError`，消息含部件名与失败原因

#### Scenario: 试构建产物校验复用
- **WHEN** `import_project` 对试构建产物执行 ZIP/XML 校验
- **THEN** 复用统一入口，产物不合法时映射为结构化的 `DocToolError`
