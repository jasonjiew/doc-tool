## 1. 可配置质量规则（服务层先行）

- [x] 1.1 新增 `doc_tool/application/content/quality_rules.py`：`QualityRulesConfig` 读写 `.state/quality_rules.json`（每规则 `rule_id/enabled/severity/params`，原子写，损坏回退默认；按文档类型提供默认规则集）
- [x] 1.2 `LintIssue` 扩展 `rule_id` 与 `severity` 字段（非破坏性追加）；`ContentLinter` 重构为读配置执行，既有三类规则映射为默认开启规则
- [x] 1.3 实现 `required_section` 规则：按配置必备章节标题集合扫描索引标题清单
- [x] 1.4 实现 `field_completeness` 规则：按配置「字段名→正则/次数」扫描正文
- [x] 1.5 实现 `numbering_uniqueness` 规则：复用 `index.py` 标题与 `references.py` `leading_number` 检重复章节号/锚点（含同文件内重复与跨文件重复锚点）
- [x] 1.6 实现 `sensitive_info` 规则：默认敏感模式（手机号/身份证/口令关键词），可配置增删，默认 `warning`
- [x] 1.7 实现 `interface_table_structure` 规则：标题含「接口」的章节缺接口表格时报告，需求文档默认开启
- [x] 1.8 单测：配置读写/损坏回退/只读不写/空规则数组、各新规则正向与边界、既有三类规则回归

## 2. 需求—设计—测试追踪矩阵

- [x] 2.1 新增 `doc_tool/application/content/traceability.py`：`TraceabilityService` 复用 `index.py` 标题清单与 `references.py` `leading_number` 解析条目编号，识别需求/设计/接口/验收关联
- [x] 2.2 纯函数 `build_matrix(...)` 生成需求→设计→接口/验收矩阵与覆盖率统计，报告导出为 Markdown
- [x] 2.3 变更影响分析：基于引用索引（`REF_SECTION`/`REF_LINK`）列出受影响下游条目
- [x] 2.4 追踪数据落盘 `.state/traceability.json`，索引/引用刷新后增量重建
- [x] 2.5 单测：条目解析（含未编号条目）、矩阵生成、未映射清单、删除章节的影响分析

## 3. 项目设置与版本基线

- [x] 3.1 `manifest.py` 新增可选字段 `publishNotes`（缺省为空，`to_dict/from_dict` 兼容）与纯函数 `increment_version(current, kind)`
- [x] 3.2 新增 `doc_tool/ui/settings_dialog.py`：编辑文档编号/名称/版本/刷新超时/模板路径/发布说明，校验复用 `ProjectManifest` 语义，保存走 `manifest.save`（时间戳备份）
- [x] 3.3 新增 `CheckpointStore`：命名检查点归档到 `.state/checkpoints/<名称>/`（清单副本+内容快照+校验报告），重名拒绝
- [x] 3.4 冻结基线（`.state/baselines/<版本>.json` 记录快照哈希与设置）与恢复基线（经 `ContentWriter` 写回并进改动清单，恢复前确认）
- [x] 3.5 纯函数 `pre_publish_checks(...) -> List[CheckItem]`：质量规则无 error、无未解决评审、版本 ≥ 基线、无未完成改动；`main_window._on_merge` 接线展示
- [x] 3.6 单测：设置保存/无效拒绝/只读禁用、版本递增、检查点重名、冻结/恢复/取消、检查清单分支

## 4. 版本历史与产物对比

- [x] 4.1 新增 `doc_tool/application/content/history.py`：`BuildHistoryStore` 写 `.state/history/<时间戳>.json`（时间/版本/内容快照哈希/模板与资源哈希/输出 SHA-256/`diagnostic`）
- [x] 4.2 `pipeline.run_pipeline` 发布成功后回调 `BuildHistoryStore` 归档（失败构建不归档）
- [x] 4.3 历史列表纯函数：按时间倒序，标注正式/诊断与输出状态
- [x] 4.4 内容差异：两版哈希集合分类 `added/modified/deleted`，diff 复用 `render_unified_diff`；DOCX 差异抽取正文文本对比
- [x] 4.5 一键回滚：`HistoryStore.restore(version)` 用 `ContentWriter` 写回内容快照并重建输出，回滚进改动清单，回滚前确认
- [x] 4.6 单测：归档字段、失败不归档、差异分类、回滚/取消回滚

## 5. PDF/HTML 导出与视觉对比

- [x] 5.1 新增 `doc_tool/application/export/pdf_html.py`：PDF 导出优先经 Word 另存，无 Word 时经构建链路生成并标注「非 Word 导出」；HTML 由 `preview.render_markdown_html` 渲染并包章节导航
- [x] 5.2 导出文件落盘输出目录评审子目录，带版本与导出时间
- [x] 5.3 新增 `VisualDiffService`：两版页面渲染为图像（PDF 逐页、HTML 经 Qt 渲染），页面像素级对比圈定差异区域；仅两版快照哈希不同时执行
- [x] 5.4 差异点击定位：点击差异区域打开对应章节并定位；标记「已查看」
- [x] 5.5 单测：HTML 渲染、无 Word 导出标注、差异区域计算、无对比基线提示

## 6. 评审与审批

- [x] 6.1 新增 `doc_tool/application/review/review_store.py`：`ReviewStore` 管理 `.state/reviews/comments.json`（章节级意见：文本/作者/时间/rel_path/行号/状态）与 `signoffs.json`（只追加不可改）
- [x] 6.2 意见状态变更（resolved/unresolved，记录解决时间）；文件删除/重命名时保留意见并标注「关联章节已变更」
- [x] 6.3 `ReviewPackageBuilder` 导出评审包（意见+快照+差异摘要）到评审子目录，未解决意见单列
- [x] 6.4 纯函数 `approval_gate(...) -> GateResult`：未解决意见或签字要求未满足默认中止发布；「跳过审批」显式覆盖并在发布历史标注
- [x] 6.5 `main_window._on_merge` 接线审批门禁与评审面板入口
- [x] 6.6 单测：意见增删/状态变更/关联失效、签字只追加、门禁分支与跳过标注

## 7. 更新源 Word 重新导入

- [x] 7.1 新增 `doc_tool/application/content/reimport.py`：`ReimportService` 打开项目时对比 `sourceSha256` 与当前源 DOCX，不一致提示重导入入口
- [x] 7.2 重新导入复用 `preflight` 预检新源与 `extract_content` 暂存提取（沿用暂存隔离），预检失败返回稳定错误码中止
- [x] 7.3 章节级对比：复用 `index` 标题与 `snapshot` 哈希分类新增/修改/删除/未变；无冲突章节自动合入
- [x] 7.4 冲突处理：当前内容有本地修改且与新源不同 → 默认保留本地，冲突章节逐章选择「采用新源」
- [x] 7.5 全部写入经 `ContentWriter` 进改动清单（可整次回滚）；合并后更新 `sourceSha256` 并重建索引与追踪数据
- [x] 7.6 单测：源变更检测（一致/不一致/缺失）、预检失败中止、冲突保留与逐章选择、整次回滚

## 8. 自动化测试与回归

- [ ] 8.1 离屏测试：**部分**——仅设置页校验/只读禁用与 LintIssue 结构已覆盖；检查面板 severity 渲染、矩阵报告、历史列表与回滚、评审面板、重导入冲突预览的离屏测试**未实现**，需补齐
- [x] 8.2 既有 `content-lint` 用例适配新结果结构并回归
- [x] 8.3 管线回归：正式/诊断构建归档历史、失败不归档、发布前门禁分支
- [x] 8.4 全量回归：`scripts/tests/run_tests.py` 全绿

## 8.5 已知集成缺口（服务层已实现并有单测，用户场景暂不可达）

以下各项的服务层纯函数与单测已交付，但生产接线（UI 面板 / CLI 命令 / 管线钩子）**尚未完成**，spec 的对应「WHEN 用户触发」场景在成品中无法触达，须在归档前补齐或明确从发布范围移除：

- 追踪矩阵：`rebuild()` 仅被重导入触发；矩阵生成/影响分析/`.state/traceability.json` 读取无 UI/CLI 入口（spec 需求 2/3/4 的触发场景不可达）。
- 版本历史：历史列表/两版 diff/一键回滚无 UI 面板；历史 DOCX 未留存导致「DOCX 产物对比」不可执行（与 Non-Goal「不含正文副本」冲突，需取舍）。
- PDF/HTML 导出：导出/视觉对比无菜单入口；「优先经 Word 另存」仅实现为未接线的回调钩子；Qt 页面渲染层缺失；差异点击定位/标记已查看无 UI。
- 项目设置/基线：版本递增、检查点、冻结/恢复基线无 UI 入口（`settings_dialog` 仅字段编辑）。
- 评审审批：评审面板过简（无状态切换/签字列表/评审包导出入口）；审批门禁只挂在 `main_window`，`pipeline`/CLI 可绕过；签字要求（`required_roles`）无配置源，门禁不查签字。
- 重导入：章节级差异预览与冲突逐章选择无 UI（`_on_reimport_source` 直接合并）；整次回滚无入口；新源图片/表格/资源映射未同步合并。

## 8.6 合并修订记录集成修复

- [x] 8.6.1 对齐 `content/` 基线与文档类型目录的 rel_path，排除修订记录元数据对正文改动摘要的干扰
- [x] 8.6.2 旧项目正式合并时从模板初始化缺失的 `_revision_record.md`，没有基线时不误递增整本文档
- [x] 8.6.3 正式合并前弹出版本号输入并将用户输入传入修订计划与发布前检查
- [x] 8.6.4 正式发布成功后重建内容基线，补充路径、初始化、版本输入与重复合并回归验证

## 9. 人工验收与文档

- [ ] 9.1 手动验收：规则开关/级别/参数修改立即生效、必备章节/编号唯一/敏感信息检出与定位
- [ ] 9.2 手动验收：追踪矩阵覆盖率与变更影响清单、设置保存与版本递增、检查点/冻结/恢复、发布前清单
- [ ] 9.3 手动验收：历史列表与两版 diff、一键回滚、评审 PDF/HTML 导出与视觉对比定位
- [ ] 9.4 手动验收：评审意见/评审包/签字/审批门禁（含跳过标注）
- [ ] 9.5 手动验收：更新源 Word 后重导入的章节差异、冲突保留本地、整次回滚
- [x] 9.6 更新 `docs/roadmap.md` 总览表「计划 6 质量追溯与交付审阅」状态
