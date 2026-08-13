## Context

质量追溯链路现状：`lint.py` 只有写死的三类检查（重复标题/术语/TODO）与 `TermStore` 的 `.state/terms.json` 模式；`index.py` / `references.py` 已能提供标题、锚点、章节号与引用解析；`manifest.py` 持有文档编号/名称/版本/刷新超时/模板样式并已实现备份式 `save`；`output_state.py` 与 `pipeline.py` 已写输出状态与原子发布；`snapshot.py` + `writer.py` 建立了「基线哈希 + 改动清单 + 备份/回收站回滚」的完整会话账本。上述能力足够支撑本变更全部 7 个能力，无需新依赖；所有新存储都落在项目 `.state/`，沿用「JSON 原子写 + 目录隔离」既有模式，保证对构建/校验不可见、可整目录清理。

本变更按依赖排序推进：质量规则（检查基座）→ 追踪矩阵（消费标题/编号）→ 项目设置/版本基线（写 `project.yml` + 基线）→ 版本历史（消费构建输出）→ PDF/HTML 导出（消费产物）→ 评审审批（消费内容与门禁）→ 重新导入（消费导入适配器）。

## Goals / Non-Goals

**Goals:**

- 把检查从写死的三类扩展为可开关、可调参、按文档类型区分的规则集，兼容既有 `content-lint` 入口与结果面板。
- 提供需求—设计—测试/接口追踪矩阵、覆盖率与变更影响分析，数据落盘 `.state/traceability.json`。
- 图形化编辑项目设置；版本递增、命名检查点、冻结/恢复基线、发布前检查清单。
- 每次成功构建归档内容/模板/资源哈希与输出状态到 `.state/history/`；支持 Markdown/DOCX 差异查看与一键回滚。
- 一键导出评审版 PDF/HTML 并做相邻版本页面级视觉对比。
- 评审意见、评审包、签字记录与发布审批门禁，全部落盘 `.state/reviews/`。
- 源 Word 更新后重新导入：章节级差异、冲突预览、可撤销合并、不覆盖本地修改。
- 全部服务保持纯逻辑可单测（无 Qt 依赖）；UI 沿用现有离屏测试模式。

**Non-Goals:**

- 不做多人实时协作、不做跨机器签名字段校验（签字为本地记录，不接外部 CA/PKI）。
- 不做 PDF 的 Word 级保真：无 Word 环境导出 PDF 标注「非 Word 导出」，不追求与 Word 完全一致。
- 视觉对比不做机器学习语义差异，仅做页面级像素对比与区域圈定。
- 版本历史不做跨项目归档、不做产物级字节差异（DOCX 按正文文本差异对比）。
- 不改变 `content_baseline.json` / `content_changes.json` 现有格式；不新增运行时依赖。

## Decisions

### 1. 可配置质量规则：`QualityRuleEngine` 读配置执行规则集

新建 `doc_tool/application/content/quality_rules.py`：`QualityRulesConfig`（`.state/quality_rules.json`，每规则 `rule_id/enabled/severity/params`，默认按文档类型合并）+ `QualityRuleEngine`（对 `ContentIndex` 执行规则，返回带 `rule_id` 与 `severity` 的 `LintIssue` 扩展）。`ContentLinter` 重构为引擎的薄封装：默认规则（重复标题/术语/TODO）映射为 `duplicate_title/term_case/todo_residual` 规则保留默认开启，`check_all` 改为读配置执行。`LintIssue` 增加 `rule_id` 与 `severity` 字段（非破坏性追加，既有面板只读 `rule/message` 字段不受影响）。

**Alternatives considered:**

- 直接在 `lint.py` 堆新函数 → 无法开关/调参，规则越多越难维护；独立引擎支持按文档类型分发默认集。
- 规则放 `config/` 全局 yml → 项目间共享会串扰；规则是项目级配置，放 `.state/quality_rules.json` 与 `terms.json` 同域。

### 2. 追踪矩阵：`TraceabilityService` 解析 + 纯函数生成

新建 `doc_tool/application/content/traceability.py`：`TraceabilityService` 复用 `ContentIndex` 标题清单与 `references.py` 的 `leading_number` 识别条目编号，识别「需求/设计/接口/验收」关键字关联关系；`build_matrix` 为纯函数生成矩阵与覆盖率，报告为 Markdown。数据落盘 `.state/traceability.json`，在索引/引用刷新后增量重建。变更影响分析复用引用索引：某文件被 `REF_SECTION`/`REF_LINK` 引用时即为受影响下游。

**Alternatives considered:**

- 新写一套标题解析 → 与 `index.py`/`references.py` 漂移；直接消费既有索引与引用。
- 矩阵存到 `content_changes.json` → 那是会话改动账本，语义不符；独立 `.state/traceability.json`。

### 3. 项目设置/版本基线：设置页 + `ProjectManifest` 扩展 + 检查点

设置页新增 `doc_tool/ui/settings_dialog.py`，编辑 `manifest` 字段，校验复用 `ProjectManifest.__post_init__` 语义，保存走 `manifest.save`（自带备份）。`project.yml` 新增可选字段 `publishNotes`（发布说明，缺省为空，向后兼容）。版本递增为纯函数 `increment_version(current, kind)`。检查点 `CheckpointStore` 归档到 `.state/checkpoints/<名称>/`（清单副本 + 内容快照 + 校验报告），重名拒绝。冻结基线 = 记一份 `.state/baselines/<版本>.json`（含快照哈希与设置）；恢复基线 = 用 `ContentWriter` 写回基线内容（进改动清单可回滚）。发布前检查清单为纯函数 `pre_publish_checks(...) -> List[CheckItem]`，消费质量规则结果、评审状态、未完成改动状态与基线版本比较。

**Alternatives considered:**

- 直接改 `config/` 下 yml → 那只是迁移期静态配置，运行时权威是 `project.yml`；只改清单。
- 冻结基线复用 `ContentSnapshot.take` → 快照是会话基线，语义不同；独立基线目录记录版本化基线。

### 4. 版本历史：`BuildHistoryStore` 消费管线终态

新建 `doc_tool/application/content/history.py`：`BuildHistoryStore` 在 `pipeline.run_pipeline` 发布成功后由管线回调写入 `.state/history/<时间戳>.json`，记录时间、版本、内容快照哈希（复用 `snapshot` 哈希函数）、模板/资源目录哈希、输出 SHA-256、输出状态摘要（`formal`/`stages`）与 `diagnostic` 标记。内容对比：取两历史记录的哈希集合做 `added/modified/deleted` 分类，diff 复用 `render_unified_diff`。一键回滚：`BuildHistoryStore.restore(version)` 用 `ContentWriter` 写回内容 + 重新构建输出，动作进改动清单，回滚前校验快照完整（缺失/损坏拒绝恢复）。DOCX 差异：解包 `word/document.xml` 抽纯文本（复用 importer 的 XML 解析风格）做文本差异，不逐字节比。

**Alternatives considered:**

- 历史归档到 `output/` 下状态文件 → 输出目录会被发布覆盖；`.state/history/` 独立隔离。
- 回滚直接覆盖文件 → 不可撤销；统一经 `ContentWriter` 进改动清单。

### 5. PDF/HTML 导出与视觉对比：复用产物 + 页面渲染

新建 `doc_tool/application/export/pdf_html.py`：PDF 导出优先经 Word 另存当前正式产物（`refresh_with_project` 同链路），无 Word 时经构建链路生成并标注；HTML 由 `preview.render_markdown_html` 渲染并包章节导航。视觉对比 `VisualDiffService`：把两版 PDF/HTML 页面渲染为图像（PDF 逐页，HTML 经 Qt `QTextDocument` 渲染为图像），做页面像素差异（逐块比较，圈定差异区域），仅当两版快照哈希不同才执行。差异区域点击经既有 `open_file(rel_path, line)` 定位到章节。

**Alternatives considered:**

- 用第三方渲染库 → 新增运行时依赖，被 Non-Goals 排除；复用既有 Word 链路与 Qt 渲染。
- 视觉对比存版本历史 → 本能力不存储历史，仅消费 `history` 能力提供的相邻版本。

### 6. 评审审批：`ReviewStore` 原子追加

新建 `doc_tool/application/review/review_store.py`：`ReviewStore` 管理 `.state/reviews/comments.json`（章节级意见，追加与状态变更）与 `signoffs.json`（只追加不可改）；`ReviewPackageBuilder` 导出评审包（意见 + 快照 + 差异摘要）到评审子目录。发布审批门禁为纯函数 `approval_gate(...) -> GateResult`，在 `main_window._on_merge` 与 `pipeline` 发布前置检查：未解决意见、签字要求未满足则默认中止，提供「跳过审批」显式覆盖并在发布历史标注。意见在文件删除/重命名时保留并标注「关联章节已变更」。

**Alternatives considered:**

- 意见内嵌进 Markdown → 污染正文与构建；独立 `.state/reviews/`。
- 签字允许修改 → 审计不可信；只追加。

### 7. 重新导入：`ReimportService` 复用首次导入适配器

新建 `doc_tool/application/content/reimport.py`：`ReimportService` 打开项目时对比 `manifest.sourceSha256` 与 `original/source.docx`；重新导入复用 `preflight` 预检新源，`extract_content` 提取到暂存目录（沿用首次导入的暂存 + 原子发布隔离），再做章节级对比（复用 `index` 标题与 `snapshot` 哈希）：无冲突章节自动合入，冲突章节默认保留本地并逐章选择。全部写入经 `ContentWriter` 记入改动清单（可整次回滚）；合并完成更新 `sourceSha256`、重建索引与追踪数据。预检失败沿用 `DocToolError` 稳定错误码中止。

**Alternatives considered:**

- 重新跑 `import_first_time` → 目标是已有项目，目标目录已存在会被拒绝；独立服务复用其适配器与暂存隔离。
- 直接覆盖全部内容 → 丢失本地修改且不可撤销；章节级差异 + 冲突保留 + 改动清单回滚。

## Risks / Trade-offs

- [规则配置膨胀导致误报] → 默认按文档类型给保守规则集；`severity=warning` 默认不阻断；结果面板可点击定位与一键忽略。
- [追踪矩阵解析误关联编号] → 只识别带编号上下文（复用 `leading_number` + 关键字），无法可靠判定时记录为未编号条目而非强行归类。
- [回滚历史版本覆盖后续内容] → 回滚统一进改动清单可二次回滚；回滚前强制确认并展示将丢失的后续改动。
- [无 Word 环境 PDF 保真不足] → 标注「非 Word 导出」；评审场景可接受，正式交付仍走 Word。
- [视觉对比在超大文档上开销高] → 仅在两版快照哈希不同时执行；页面级并行渲染，差异区域粗粒度。
- [审批门禁被跳过失去约束] → 跳过必须在发布历史显式标注「跳过审批」，供审计追溯；门禁默认开启。
- [重新导入误覆盖本地修改] → 冲突章节默认保留本地；合并整次进改动清单可一键回滚。
- [`.state/` 新目录增长] → 每历史仅存哈希与摘要，不含正文副本；提供清理入口（非本变更必须）。

## Migration Plan

1. 服务层先行（纯逻辑可测）：`quality_rules.py` → `traceability.py` → `history.py` → `export/pdf_html.py` → `review_store.py` → `reimport.py`，各配单测。
2. 领域/应用层接线：`manifest.py` 增 `publishNotes` 与 `increment_version`；`pipeline.py` 发布**前**触发审批门禁检查（与 `main_window._on_merge` 一起构成前置门禁），发布**成功后**回调 `BuildHistoryStore` 归档（失败构建不归档）。
3. UI 接线：设置页、检查面板扩展（severity/rule_id）、矩阵/历史/评审/重导入面板；`main_window` 接入菜单与发布前门禁。
4. 自动化测试与回归：既有 `content-lint` 用例适配新结果结构；离屏测试覆盖各面板。
5. 人工验收：按能力逐项走查，覆盖正向与边界分支。

回滚：全部新存储隔离于 `.state/` 新目录与 `project.yml` 可选字段；移除接线即可回退，无需数据迁移。对 `content-lint` 的行为扩展（新增字段、读配置）不影响既有读取方。

## Open Questions

- 视觉对比的页面渲染是否需要可选关闭（大文档性能敏感项目）——倾向提供配置开关，**保留为后续项**；本变更按「仅在两版快照哈希不同时执行 + 页面级粗粒度对比」控制开销。
- 审批门禁的签字要求是「至少一人签字」还是「指定角色签字」——`approval_gate` 已支持 `required_roles` 参数（**按可配置签字要求实现**）；但生产路径尚无签字要求配置源/UI，门禁默认只检查「无未解决意见」，签字要求接线留待人工验收后补充。
- 重新导入对 `_index.md` 父章节正文的合入粒度（整文件 vs 段落级）——**已按文件级章节粒度落地**；段落级合并留待后续。
