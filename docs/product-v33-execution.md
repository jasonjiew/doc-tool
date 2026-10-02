# V3.3 本地写作辅助与可选模型执行台账

执行日期：2026-10-01。入口：[V3 总计划](product-plan-v3.0-v3.3.md) 第 6 节（V3.3 功能表）与第 7 节（33-A→F 顺序），原则：[流程与兜底](product-flow-fallback-policy.md)。关联 change：`product-v33-authoring-assistance`（proposal/design/3 specs/tasks 全套）。

状态唯一源仍是 [该 change 的 tasks.md](../openspec/changes/product-v33-authoring-assistance/tasks.md)；本台账只记录证据、兜底与遗留，未实现/未验证的编号保持未勾选，真实模型连通单列为可选试点。

本版按「无模型完整可用」实施：本地检索、确定性建议、差异采纳/一次撤销、可选 provider（默认禁用）四块先落地，再接入门面、GUI 面板离屏与 CLI；正文保存、复核状态、追踪关系与文档版本继续由既有服务单一负责。

## 1. 状态总览

| 批次 | 任务 | 完成 | 直接验证 | 下一项 |
|---|---|---|---|---|
| 33-A 搜索 | 4 | 4/4 | `test_v33_authoring_assistance.py::EvidenceSearchTests`（9 项）通过 | — |
| 33-B 本地建议 | 5 | 5/5 | `SuggestionTests`（6 项）通过 | — |
| 33-C 采纳 | 4 | 4/4 | `AdoptionTests`（5 项）通过 | — |
| 33-D provider | 5 | 5/5 | `ProviderTests`（6 项）通过 | 真实模型连通试点（可选） |
| 33-E 整合 | 4 | 2/4 | `IntegrationTests`（3 项）通过 | 5.1 / 5.3 待 main_window 与 V3.1 落地 |
| 33-F 验收 | 4 | 2/4 | 直接/相关/全量回归留证 + OpenSpec strict 校验通过；6.2/6.3 未执行 | 6.2 / 6.3 |
| 合计 | 26 | 22/26 | 新测试 29 项全过（exit 0）；未完成 5.1/5.3/6.2/6.3 | — |

## 2. 用户可用行为（本版真实入口）

- **本地检索（无模型）**：`LocalEvidenceSearch` 在显式加入的项目内容根、模块库目录/文件与当前编辑缓冲中做文本/术语检索；结果带来源身份、`rel_path:行号`、项目版本/模块版本（未登记则标“未登记”）、内容 hash 与匹配原因（文本/术语/正则）；缓冲命中标“当前缓冲未保存”，来源变化命中标“陈旧”。
- **确定性建议（无模型）**：`SuggestionEngine` 复用既有 `ContentLinter`（required_section/field_completeness/todo_residual/term_case）、`quality/terms.json` + 术语别名映射、`ReferenceScanner` 悬空引用、`ReviewRecordStore.pending()` 与本地改动清单，产出填写提示/术语建议/引用提示/复核提示/修订摘要候选；每条都有 id、kind、证据、目标范围、baseHash、before/after、状态、origin、coverage。
- **差异采纳与撤销**：`AdoptionSession` 让用户勾选建议后一次性写入**编辑缓冲**，返回 before/after 与统一差异；整批改动是一个事务，支持且仅支持一次撤销；正文保存仍调用既有 `ContentWriter`。
- **可选增强（默认关闭）**：`ProviderGateway.enhance()` 只在显式点击时调用；未启用/无凭据/超时/断网/坏响应/取消/命令缺失都回退本地候选并集中说明；请求范围与截断可见。
- **命令入口**：`assist-search`、`assist-suggest`、`assist-adopt`（只预览差异，不写正文）、`assist-provider`（只显示凭据环境变量名）。
- **GUI 面板**：`doc_tool/ui/assist_panel.py` 提供资料搜索/来源引用与复制正文/建议收件区/差异预览/增强按钮，插入正文与摘要候选通过信号交给编辑器既有插入与修订对话框路径。

## 3. 每批证据

### 33-A 本地资料检索（1.1～1.4，4/4）

- 复用接口核对（1.1）：`ContentIndexService.discover_files/read_lines`（发现与行口径）、`content.search.compile_pattern`（正则/整词边界同一套语义）、`intake_contract.sha256_text`（hash 口径）、`content.writer.atomic_write`（缓存原子写）、`domain.content_index.path_natural_sort_key`（稳定排序）。V3.0 模块库 tasks 仍为 0/32（并行会话已有 `content/modules.py`、`content/module_refs.py` 等在途文件，但接口未验收），按“遇直接接口缺口先补最小适配”提供 `EvidenceSource.from_module(目录/文件)`，模块条目以 `source_id + rel_path + hash` 定位；待 V3.0 验收后改用其模块身份/版本 API。
- 实现（1.2）：`assist/search_local.py` 的 `EvidenceSource/BufferDocument/EvidenceDocument/SearchHit/SearchOutcome`；结果字段含 `sourceId/sourceKind/sourceLabel/relPath/line/text/matchReason/matchedTerm/contentHash/version/stale/unsaved`；缓冲与磁盘同路径时缓冲优先并标 `unsaved=True`。
- 缓存与兜底（1.3）：用户级 `user_cache_dir()/evidence-index.json`（可用 `DOC_TOOL_ASSIST_CACHE` 覆盖），按 `size:mtime_ns` 判定来源变化；缓存不可解析/结构错误 → `cache_status=rebuilt` + `fallback_reason`，直接读取可读文本继续检索；非 UTF-8/不可读条目进 `skipped` 不阻断其余结果；`refresh_stale=True` 按需重读并回写缓存；索引按 `batch_size` 分批并可传 `cancel_token` 供后台线程取消。
- 测试（1.4）：`EvidenceSearchTests` 覆盖跨项目/模块来源区分与版本、中文术语、缓冲未保存、陈旧标记与按需刷新、坏缓存回退 + 非法条目跳过、分批进度与取消、引用/复制文本、非法正则报错、显式范围不外扩。夹具为「两项目 + 三模块」（`build_project`/`build_modules`），目录取自 `core_fixtures.scratch_dir()`。
- 用户可用行为：搜索面板/CLI 先给可用结果，再集中列出陈旧/未保存/跳过/截断说明。
- 默认与兜底：无缓存→直接读文本；缓存坏→回退并重建；来源变化→先给陈旧结果并提示刷新；范围为空→明确提示“请用 --project/--module 显式指定”，不静默成功。

### 33-B 本地建议与修订候选（2.1～2.5，5/5）

- 模型（2.1）：`Suggestion/SuggestionEvidence/SuggestionSet`，字段 `suggestionId/kind/title/detail/rationale/evidence/targetRelPath/startLine/endLine/rangeLabel/baseHash/before/after/applyMode/status/origin/coverage/editable/notEvidence`；`not_evidence` 固定 True，`SuggestionSet.facts_note` 明示“不构成需求满足、测试通过或正式门禁证据”。
- 确定性提示（2.2）：规范缺失章节给 `## 标题 + "> 待填写：…"` 占位（`coverage=partial`，说明插入位置为建议值）；字段完整性/TODO 只给提示（`applyMode=none`、`coverage=insufficient`、`after=""`），不虚构实现或测试通过事实。
- 事实复用（2.3）：失效引用来自 `ReferenceScanner` 的 `dangling/confirmed|suspect`（不猜目标、不改链接）；待复核来自 `ReviewRecordStore.pending()`（只提示，不改状态）；模块来源以最小适配接入：`module_roots` 中的模块命中作为填写建议的“模块库可复用要点”依据（只作依据、不复制原文），模块版本更新事件依赖尚未实现的 V3.0 模块库，另列遗留。
- 摘要候选（2.4）：`revision_summary_candidates()` 复用 `build_change_items` + `build_revision_record`，产出“章节定位”和“改动统计”两个候选，`applyMode=none`、`field=revision-summary`；采纳只填原修订框，新增修订记录仍由原追加确认动作执行（文档版本唯一来源不变）。
- 测试（2.5）：`SuggestionTests` 覆盖无模型全种类建议、依据完整性与 forbidden 事实扫描、提示类范围不足、修订候选来自本地改动、目标变化重算/冲突跳过且其余可用、既有 lint 事实不重复造、模块依据不复制原文。
- 未新增发布门禁：建议状态是 `proposed/stale/conflict/accepted/ignored/unavailable`，与质量门禁/评审状态无耦合。

### 33-C 差异采纳与撤销（3.1～3.4，4/4）

- 收件区（3.1）：`AdoptionSession.preview_diff()` 复用 `changes.render_unified_diff`；`export_text()` 输出来源/范围/before-after/依据，供只读查看与导出。
- 缓冲事务与保存（3.2）：`adopt()` 只在传入的编辑缓冲文本上应用替换/插入，返回 `buffer_updates` 与 `AdoptionTransaction(before_texts, applied_ids)`；`undo()` 只能成功一次，第二次明确返回“已经撤销过”；保存由 `AuthoringAssistant.save_buffers(writer)` 调用既有 `ContentWriter.write_text`（自动 .bak 与改动清单）。
- 目标变化与摘要（3.3）：`SuggestionEngine.refresh()` 在目标 hash 变化后唯一定位则重算（更新行号/baseHash），零匹配或多匹配则标 `conflict` 并保留用户内容；采纳阶段再次校验 `before` 唯一性，冲突项跳过、其余继续；摘要候选只进 `summary_candidates`，不写正文。
- 测试（3.4）：`AdoptionTests` 覆盖采纳不改原文件、一次撤销与二次撤销拒绝、保存走 ContentWriter 且 `project.yml`/复核记录字节不变、冲突跳过其余继续、只读可看/导出不可写、摘要候选不新增修订记录。
- `AdoptionOutcome.side_effects` 恒为空并断言 `changed_review_state is False`：不自动改复核、关系、门禁或版本号。

### 33-D 可选模型 adapter（4.1～4.5，5/5）

- 协议与配置（4.1）：`WritingProvider.suggest_revision/suggest_terms` 两个方法；`FakeWritingProvider` 记录调用并可脚本化成功/超时/坏结构/取消；`ProviderConfig` 默认 `enabled=False, provider=disabled`，`ProviderConfigStore` 默认写用户级 `user_config_dir()/provider.json`，配置内只有 `credentialEnv` 名称，无凭据值；显式传 `project_root` 时拒绝写入项目目录。
- 本地命令 adapter（4.2）：`LocalCommandProvider` 只用配置里的可执行文件与参数（`shell=False`），请求经 stdin JSON、响应经 stdout JSON；非零退出/文件不存在/超时/非 JSON 分别映射为可回退错误；结构校验由 `validate_provider_response` 完成；缺失命令时 adapter 自身抛 `ProviderCommandMissing`（测试直接断言，不启动任何进程）。取消语义：调用前取消→`cancelled` 且不发起请求（已测）；调用中不做强制中断，由超时兜底（记入遗留说明）。
- HTTP adapter（4.3）：`HttpProvider` 仅在显式 `enhance()` 时调用；端点/模型来自配置，凭据只读用户环境变量；`transport` 可注入便于离线验证；HTTP 状态/URLError/超时/JSON 解析失败映射为可回退状态。真实端点的协议核实与连通属可选试点，未执行（单列待验收）。
- 范围与回退（4.4）：请求文本默认 8000 字符截断，结果含 `requestedChars/actualChars/truncated/maxChars/target/scope`；超时/断网/无凭据/坏响应/取消/命令缺失都保留本地候选、`attempts=1` 不重试，日志仅有目标/范围/长度/状态。
- 测试（4.5）：`ProviderTests` 覆盖默认禁用零调用、超时/断网/坏响应/无凭据回退且不重试、取消不调用、9000 字符截断为 8000 且目标与范围可见、凭据不入配置/日志/项目文件、响应含“执行命令”不入建议且不触发 `subprocess.run`、非法出处降级为措辞候选、真实解释器命令 adapter 结构校验（环境不允许管道子进程时 skip）。

### 33-E 写作入口整合（5.1～5.4，2/4）

- 门面（5.2 支撑）：`assist/service.py` 的 `AuthoringAssistant` 统一搜索/建议/采纳/撤销/保存/增强/状态，CLI 与面板同源；`enhance()` 未启用时返回 `disabled` + 本地候选，增强按钮始终可见可用。
- 面板（5.1 部分、5.2）：`doc_tool/ui/assist_panel.py` 显示资料范围、结果列表（带未保存/陈旧标记）、插入来源引用/复制正文按钮、建议收件区（勾选采纳/忽略/撤销）、before-after 预览、provider 目标与上限；`insert_requested`/`summary_candidate` 信号交给编辑器既有插入与修订对话框。
- CLI（5.3 部分）：`assist-search/assist-suggest/assist-adopt/assist-provider` 与门面同源，结构化输出可 JSON；结果集中提示覆盖/陈旧/跳过/增强未执行。
- 端到端（5.4）：`IntegrationTests` 跑「查资料→建议→勾选采纳→一次撤销→再次采纳→既有保存路径→修订候选→离线 HTML 出稿」全流程，另有 GUI 离屏测试（`QT_QPA_PLATFORM=offscreen`）覆盖面板交互。
- 未完成：5.1 的编辑器实际接线需要修改 `doc_tool/ui/main_window.py`，本任务明确禁止修改该文件，因此面板尚未挂到菜单/停靠（面板与信号已就绪，离屏测试通过）；固定模块引用依赖尚未实现的 V3.0，当前以普通文字来源引用替代。5.3 的“V3.1 共享命令/上下文和概览”同样依赖未验收的 V3.1（tasks 0/27，并行在途的 `content/handoff.py`、`content/assignments.py` 尚未接入），本版只提供 CLI 命令入口与集中提示。

### 33-F 无模型验收与版本收尾（6.1～6.4，1/4）

- 6.1（已勾选）：直接套件（新测试 29 项，exit 0）与相关既有套件（`test_cli_machine.py` 12 项、`test_cli_check_v27.py` 8 项、`test_command_palette.py` 4 项、`test_format_check_search.py` 11 项、`test_authoring_services.py` 80 项）全部通过；全量 `run_tests.py` 95 个文件中 94 个通过，唯一失败文件 `test_gui_services.py` 的 6 项与本版无关且不含 assist 引用（见第 5 节）；A33-1～6 的无模型/默认/故障兜底证据见第 4 节，真实模型连通试点按可选单列（第 7 节）。
- 6.2：三类文档人工试点（资料定位耗时、建议采纳/撤销、人工摘要修改、基线提升）**未执行**，保持未勾选。
- 6.3：本台账已记录检索/建议/provider 配置与数据范围说明；应用版本源仍为 `2.9.0`（V3.0～V3.2 未实现，不在本版校正 V3.3 发布号），冻结冒烟未执行，保持未勾选。
- 6.4：`openspec validate product-v33-authoring-assistance --strict` 通过（`Change 'product-v33-authoring-assistance' is valid`）；任务勾选与本台账证据逐条核对；真实模型连通未连通也未记为通过。

## 4. 验收标准对照（A33-1～6）

| 验收 | 结论 | 直接证据 |
|---|---|---|
| A33-1 当前工作区/模块检索有来源和版本，陈旧/未保存可识别，索引损坏仍能查当前资料 | 满足 | `EvidenceSearchTests`：跨项目/模块来源与版本、缓冲 `unsaved`、陈旧标记与按需刷新、坏缓存回退 + 非法条目跳过 |
| A33-2 没有模型可获得填写/术语/修订候选，事实来自实际数据，不凭空产生通过证据 | 满足 | `SuggestionTests`：五类建议 + 依据 + forbidden 事实扫描 + `notEvidence=True` + 提示类 `coverage=insufficient` |
| A33-3 选择采纳→编辑缓冲→一次撤销→正常保存；目标变动跳过冲突且其余继续 | 满足 | `AdoptionTests` + `IntegrationTests`：缓冲更新/差异、一次撤销、ContentWriter 保存、冲突跳过其余继续 |
| A33-4 provider disabled 时保存/检查/出稿无网络/模型调用；两种 adapter 用 fake 验证接口和坏响应 | 满足 | `ProviderTests.test_default_disabled_never_calls_provider` + 端到端出稿 `provider_call_count == 0`；命令/HTTP adapter 用 fake 与注入 transport 验证 |
| A33-5 请求范围/截断可见、凭据不入文件/包/日志，模型响应不执行命令、不自动改正文 | 满足 | `ProviderTests.test_request_scope_truncation_and_credentials_stay_out_of_files_and_logs`、`test_response_cannot_execute_commands_or_fake_local_evidence` |
| A33-6 断网/超时/无凭据回本地结果；无需真实模型账号也能完成基础验收，可选连通试点单独记录 | 满足 | `test_timeout_network_bad_response_and_missing_credential_fall_back_without_retry`；真实连通试点见第 7 节待验收 |

## 5. 回归结果（2026-10-01）

- **新套件（本版）**：`python scripts\tests\test_v33_authoring_assistance.py` → `Ran 29 tests ... OK`，exit 0。
- **全量回归（记录时点：当时 95 个文件）**：`run_tests.py` 运行 95 个测试文件；94 OK、1 失败。
  > 更正（第十四轮独立审计）：该记录已过期——当前默认清单为 **127 个测试文件**，`test_v33_authoring_assistance.py` 等 V3.3 用例**已注册**；最近一次全量实测（124 文件）只有 `test_gui_services.py` 1 项失败（Mermaid 预览缺 `mmdc`），并非此处记载的 6 项。
- **失败文件（记录时点）**：`test_gui_services.py`（当时 170 项中 6 项失败；**现为 1 项**，Mermaid 预览）：`test_mermaid_dialog_templates_and_interactive_validation`、`test_open_incompatible_project_readonly`、`test_preflight_block_gate_requires_confirmation`、`test_style_mapping_page_mapping_and_complete`、`test_smart_skip_next_id_with_heading1`、`test_smart_skip_next_id_without_heading1`。
- **与本版关系**：失败项集中在 Mermaid 对话框、只读项目打开、导入向导保真/样式映射，均不引用 `doc_tool/*/assist*` 或 `doc_tool/application/assist/*`（已检索失败输出）；这些区域在当前工作树中由其它在途改动（`doc_tool/ui/wizard.py`、`doc_tool/ui/main_window.py` 等）修改，属既有无关失败，不拖住本批实现。
- **未注册说明（已失效）**：当时 `test_v33_authoring_assistance.py` 未加入 `run_tests.py`；**现已注册**（连同 `test_v33_registry.py`、`test_v33_editor_wiring.py`、`test_v33_three_document_pilot.py`）。

## 6. 数据与配置范围（新增，可缺省）

| 内容 | 位置 | 说明 |
|---|---|---|
| 检索索引缓存 | 用户级 `user_cache_dir()/evidence-index.json`（Windows 默认 `%LOCALAPPDATA%\doc-tool\assist`，可用 `DOC_TOOL_ASSIST_CACHE` 覆盖） | 可随时删除重建；记录 `sourceId/relPath/contentHash/statKey/sizeBytes` 与（≤1MB 文件的）行文本；坏文件自动回退直接读文本 |
| provider 配置 | 用户级 `user_config_dir()/provider.json`（Windows 默认 `%APPDATA%\doc-tool\assist`，可用 `DOC_TOOL_ASSIST_CONFIG` 覆盖） | 只存 `enabled/provider/command/args/endpoint/model/timeoutSeconds/maxChars/credentialEnv/authHeader/authScheme`；显式传 `project_root` 时拒绝写入项目 |
| 凭据 | 用户环境变量（名称由 `credentialEnv` 配置） | 只读、不缓存、不写盘；日志与结果只出现变量名与“是否已设置” |
| 模型请求内容 | 仅本次显式选中的上下文 | 默认上限 8000 字符，超过即截断并在结果中显示 `requestedChars/actualChars/truncated` 与目标 |
| 项目内新增文件 | 无 | 本版不新增项目 schema、不写 sidecar、不写正文（除作者走既有保存路径） |

## 7. 未完成与待验收（不虚勾，不伪造通过）

| 编号/事项 | 状态 | 原因与后续动作 |
|---|---|---|
| 5.1 编辑器实际接入面板 | 未完成 | 需要修改 `doc_tool/ui/main_window.py`，本任务明确禁止修改；`AssistPanel` 与信号已就绪并有离屏测试，接线为后续一个入口改动 |
| 5.3 接 V3.1 共享命令/上下文与项目概览 | 未完成 | V3.1（`product-v31-team-workflow`，tasks 0/27）未验收，无共享命令注册表/概览接口（并行在途文件未接入）；本版先提供 CLI 命令入口与集中提示 |
| 5.4 新测试注册进默认套件 | 部分 | 流程与离屏测试已跑通；`scripts/tests/run_tests.py` 的 `DEFAULT_TESTS` 本任务禁止修改，注册待批 |
| 6.2 三类文档人工试点（定位耗时、采纳/撤销、摘要修改、基线） | 未执行 | 需真实文档与人工操作记录 |
| 6.3 版本源校正与冻结冒烟 | 未执行 | 应用版本源仍为 `2.9.0`；V3.0～V3.2 未实现，不在本版校正 V3.3 发布号；冻结/安装包冒烟未跑 |
| 真实 provider 连通试点 | 未执行（可选） | 无真实模型端点/账号；接口、故障回退与凭据约束已由 fake/注入 transport 验证。需试点时：配置用户级 `provider.json` + 环境变量凭据，按实际端点核实协议后单列记录 |
| 大库实机性能 | 未测量 | 分批索引 + 取消令牌 API 已验证；未在真实大库上测定位耗时与内存 |
| 调用中取消 | 未实现强制中断 | 采用「调用前取消 + 超时兜底」，不在模型调用中途杀进程（避免半成品响应）；如后续需要可在 adapter 内加中断 |

## 8. 验证命令与结果

```text
# 直接（必须项）
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path
python scripts\tests\test_v33_authoring_assistance.py
→ Ran 29 tests ... OK（exit 0）

# 相关既有套件（未修改其文件）
python scripts\tests\test_cli_machine.py            → OK（12 项）
python scripts\tests\test_cli_check_v27.py          → OK（8 项）
python scripts\tests\test_command_palette.py        → OK（4 项）
python scripts\tests\test_format_check_search.py    → OK（11 项）
python scripts\tests\test_authoring_services.py     → OK（80 项）

# 静态检查（新文件）
python -m pyflakes doc_tool\application\assist\*.py doc_tool\ui\assist_panel.py scripts\tests\test_v33_authoring_assistance.py
→ 无输出（无未使用导入/未定义名）

# 规划校验
openspec validate product-v33-authoring-assistance --strict
→ Change 'product-v33-authoring-assistance' is valid

# CLI 冒烟（无模型）
python -m doc_tool.cli assist-search --project <项目> --module <模块> --query PACS --cache-dir <缓存目录>   → exit 0
python -m doc_tool.cli assist-suggest --project <项目> --output json                                      → exit 0
python -m doc_tool.cli assist-adopt --project <项目>                                                      → exit 0（仅预览）
python -m doc_tool.cli assist-provider --config <配置>                                                     → exit 0
```

## 9. 新增/修改文件清单

新增：

- `doc_tool/application/assist/__init__.py`：包说明与批次索引。
- `doc_tool/application/assist/models.py`：共享模型、状态词、用户级路径与截断/指令检测工具。
- `doc_tool/application/assist/search_local.py`：33-A 本地检索、缓冲叠加、陈旧检查、用户级缓存与坏索引回退。
- `doc_tool/application/assist/suggestions.py`：33-B 确定性建议、模块依据、刷新重算/冲突。
- `doc_tool/application/assist/adoption.py`：33-C 差异采纳、一次撤销、只读导出。
- `doc_tool/application/assist/provider.py`：33-D provider 协议、配置、命令/HTTP adapter、fake、网关与脱敏日志。
- `doc_tool/application/assist/service.py`：33-E 门面（搜索/建议/采纳/保存/增强）。
- `doc_tool/application/assist/cli_commands.py`：33-E CLI 命令实现与渲染。
- `doc_tool/ui/assist_panel.py`：33-E 写作辅助面板（信号对接编辑器既有操作）。
- `scripts/tests/test_v33_authoring_assistance.py`：29 项自动测试（29-A～E + 无模型验收）。
- `docs/product-v33-execution.md`：本台账。

修改：

- `doc_tool/cli.py`：新增 `assist-search/assist-suggest/assist-adopt/assist-provider` 四个子命令与 `_assist_command` 分派（既有命令行为不变，相关套件通过）。

未修改（按要求）：`doc_tool/ui/main_window.py`、`scripts/tests/run_tests.py`、`docs/product-plan-v3-execution.md`、`docs/product-core-workflow-execution.md`、其它 change 的 tasks.md。

## 续：5.1 编辑器接线与 5.3 共享命令/概览（父会话本轮实施）

```text
批次 / 完成编号：33-E 5.1、5.3（余 6.2 人工试点、6.3 版本源/冻结）
实现：
  5.1 菜单「资料搜索与写作建议…」（Ctrl+Alt+A）打开 AssistPanel 停靠面板；
      insert_requested → 当前编辑器光标插入（QPlainTextEdit 撤销栈，一次撤销）；
      summary_candidate → 只填既有修订记录编辑器，未打开时复制到剪贴板并说明，不新建发布状态；
      视图菜单提供显隐入口；无项目时给明确提示。
  5.3 `doc_tool/application/assist/commands.py`：把 assist.search/suggest/adopt/undo/provider/overview
      注册进 V3.1 共享命令注册表（同 handler、同可用性、菜单与面板同状态）；
      `build_assist_overview` 集中提示资料范围/陈旧来源/增强未执行（未启用模型时不谎称已增强）。
修复：工作区 relPath 需带文档类型前缀（`general/第 x 章 …`），已抽出
      `main_window._open_chapter_in_workspace` 供导入结果页定位动作与面板共用。
验证命令 / 退出码：
  python scripts\tests\test_v33_editor_wiring.py -> Ran 4 tests OK (exit 0)
  python scripts\tests\test_v33_registry.py      -> Ran 5 tests OK (exit 0)
  python scripts\tests\test_v33_authoring_assistance.py -> Ran 29 tests OK (未回归)
  python scripts\tests\test_core_result_page.py  -> Ran 7 tests OK（定位动作改用统一助手后仍通过）
未验收：6.2 三类文档人工试点（需真实文档与人工记录）、6.3 版本源校正与冻结冒烟（待发布批次）
下一批 / 下一任务：33-F / 6.2
```

## 续：6.3 说明/版本源与冻结冒烟（父会话第十轮）

```text
文档：`docs/product-v30-v33-usage.md` 第 3 节（检索/建议/adopt/provider/无模型兜底/限制）
  与第 4.1 节版本源表；原任务备注“V3.0～V3.2 未实现”已过期（现仅缺实机/试点项）。
版本源：保持 2.9.0；V3.3 发布号同批发布时确定。
冻结冒烟（真实执行，按实际环境登记为已通过）：产物校验 + 签名 + test_frozen_smoke 11 项 OK；
  冻结 CLI 复核 assist-search / assist-provider --help exit 0。
OpenSpec：openspec validate product-v33-authoring-assistance --strict → valid
遗留：6.2 三类文档人工试点（需真实文档/人工）、同步/归档。
```

## 续二：6.2 三类真实文档自动化试点记录（父会话第十一轮）

```text
夹具：三份**仓库内真实文档**作为三章正文（README.md 项目说明 / docs/product-flow-fallback-policy.md
  兜底策略 / docs/product-v31-usage.md 使用指南），每章另加一条真实草稿常见的 TODO 占位以触发填空建议；
  术语别名映射 {"文档工具": "DocTool"}（真实词汇统一配置）。
命令：python scripts\tests\test_v33_three_document_pilot.py（输出 PILOT_JSON 一行）

实测（每份文档）：
  项目说明：定位 0.036 s / 25 条命中；建议 8 条，可采纳 1 条（term-wording，replace）；
            采纳 1 条并一次撤销成功恢复；修订摘要候选 2 条；provider 未配置、增强未执行
  兜底策略：定位 0.033 s / 14 条命中；建议 8 条，可采纳 1 条；采纳 1 + 撤销 1；摘要候选 2 条
  使用指南：定位 0.039 s / 15 条命中；建议 8 条，可采纳 1 条；采纳 1 + 撤销 1；摘要候选 2 条

结论（自动化基线）：本地定位在 0.03～0.04 s 量级；无模型也能给出建议与摘要候选；
  采纳进缓冲后一次撤销可完全恢复（三份文档均一致）。
未执行（保持 6.2 未勾选）：三类**文档类型**（方案/报告/说明书）人工试点与质量评价、真实用户确认；
  未知提升目标（模型增强质量）需先有基线再定目标——当前基线为“增强未执行、provider 未配置”。
  实机用例：`V33_REAL_PROVIDER=1` 可跑真实 provider 连通（未执行）。

## 审计更正（父会话第十四轮，独立审计 product-v33 勾选项后）

```text
更正：第 6.1 节的全量回归记录（95 文件 / gui_services 6 项失败 / 未注册说明）已过期，
  现为 127 个注册测试文件、最近全量实测 124 文件仅 1 项环境失败（Mermaid 预览），
  且 V3.3 四个测试文件均已注册；结论“失败与本版无关”仍成立。

仍待处理（见 docs/product-v3-audit-findings.md）：
  ① 1.3/1.4 勾选项含“后台分批/大范围不阻塞”，实现为**同步索引**且无阻塞测量；
  ② 2.3 “模块更新来源接为建议”未实现（仅把模块命中作为填空依据）；
  ③ 3.4 “取消修订”没有真正执行取消的用例；
  ④ 5.3 命令注册表**未在应用内实例化**，`assist.*` 仅存在于库与测试中，
     命令面板仍是硬编码列表（`menu_items`/`palette_items` 为同一函数，等价性测试为空转）；
  ⑤ GUI 采纳只写 `AuthoringAssistant.buffers`，`save_buffers` 仅测试调用 →
     “采纳→一次撤销→保存”在应用内不可达。
```

## 续三：5.3 写作辅助命令接入应用（父会话第十五轮）

```text
问题（第十四轮审计）：`register_assist_commands` 仅被自身与测试引用；应用内命令面板是硬编码列表，
  `assist.*` 在应用里不可达，使用说明第 29 行声称的“同 handler/同可用性”不成立。

修复：`MainWindow` 构建注册表时调用 `register_assist_commands(registry, project_root)`；
  「命令」菜单与命令面板（Ctrl+K / Ctrl+Shift+P）都由注册表渲染，点击统一走 `handle_item`；
  只读/无项目时不可用项在面板显示原因与下一步动作，不进菜单。
验证：test_v33_registry.py 5 项 OK + test_v31_registry_integration.py 4 项 OK
  （集成用例断言窗口注册表中含 `assist.search`/`assist.provider`，面板条目经注册表派发）。
仍待修（保持未勾选）：5.4 应用内“采纳→一次撤销→保存”链路（面板采纳只写 assistant.buffers）。
```

## 续四：5.4 采纳→编辑器→保存链路打通（父会话第十六轮）

```text
问题（第十四轮审计）：面板采纳只写 `AuthoringAssistant.buffers`，`save_buffers` 仅测试调用
  → 应用内“采纳→一次撤销→保存”不可达。

修复：
  - `AssistPanel` 新增 `buffers_changed` 信号：采纳成功与撤销成功时发出当前全文缓冲；
  - `MainWindow._on_assist_buffers_changed`：把缓冲写回对应编辑器标签（标签键支持
    `general/…` 前缀与内容根相对两种写法），整篇替换包在 `beginEditBlock/endEditBlock`
    里 → **一个撤销步**；随后保存沿用编辑器既有路径（ContentWriter）。
  - 顺带修掉一个真实缺陷：`_collect_buffer_texts` 在**编辑器面板**上找 `toPlainText/text`
    （文本其实在内层 `_editor`），导致所有脏标签被跳过——未保存修改从未进入出稿/缓冲；
    现优先 `plain_text()`，其次内层 `_editor.toPlainText()`，并为面板补 `plain_text()` 访问器。

验证：python scripts\tests\test_v33_adoption_editor.py -> Ran 1 test OK（离屏真实面板接线：
  打开章节 → 面板加载建议 → 勾选采纳 → 编辑器出现规范写法且缓冲含改动 → 保存经 ContentWriter 落盘
  → 面板撤销后编辑器恢复原文）。
  回归待跑：core_export_ui / core_export_snapshot / core_gui_loop / v33_editor_wiring / gui_services。
遗留（保持未勾选）：1.3 后台分批、1.4 来源去重与阻塞测量、2.3 模块更新来源、3.4 取消修订用例；6.2 人工试点。
```

## 续五：1.3 后台分批索引 + 1.4 来源去重与大范围测量（父会话第二十一轮）

```text
问题（第十四轮审计）：索引构建全同步（`ensure_index` 只在 `search()` 里被调用），
  “后台分批/不阻塞”不成立；也没有“来源去重”用例，`..._does_not_block` 未断言任何阻塞行为。

修复：
  - 新增 `assist/worker.build_index_task`：分批（默认 40/批）、可取消、可报进度的普通函数，
    直接作为 `TaskSpec.target` 交给既有 `TaskRunner`；
  - `AssistPanel`：`index_in_background()` 在后台建索引（编辑不受影响），
    `search()` 在无缓存/陈旧时顺手启动后台索引并在完成回调里 `invalidate()`，
    使下一次检索命中缓存；新增 `has_background_index()/wait_background_index()/background_index_result()`；
  - 去重：`SearchHit` 新增物理 `file_path`，检索按“**物理文件 + 行号 + 内容哈希**”去重，
    同一文件被项目与模块两个来源扫到只报一次，`SearchOutcome.deduped` 记数并在说明里集中提示。

验证：python scripts\tests\test_v33_background_index.py -> Ran 5 tests OK
  · build_index_task 写出缓存、上报批次、可取消
  · 面板首次检索不阻塞（< 5 s，实测远低于此）且立即启动后台索引；后台完成后再次检索命中缓存
  · 同一文件两个来源 → deduped ≥ 1 并给出说明
  · 大范围（120 章、无索引）检索实测 **0.23～0.35 s / 120 条命中**（有界、不阻塞编辑）
  回归：test_v33_authoring_assistance 29 OK／test_v33_registry 5 OK／test_v33_editor_wiring 4 OK／
        test_v33_three_document_pilot OK／test_v33_adoption_editor OK／test_gui_services 170（仅 1 项 mermaid 环境失败）
遗留（保持未勾选）：2.3 模块更新来源、3.4 取消修订用例；6.2 人工试点。
```

## 续六：2.3 模块更新建议 + 3.4 摘要候选真实取消（父会话第二十二轮）

```text
问题（第十四轮审计）：
  2.3 “模块更新来源接为建议”未实现（只把模块命中作为填空依据）；
  3.4 “取消修订”没有真正执行取消的用例（旧用例只重新读盘）。

修复：
  - 新增建议种类 `KIND_MODULE_UPDATE`（标签“模块更新提示”，并入 `KINDS` 与
    `SuggestionSet.counts()`），`collect_module_update_suggestions` 复用 V3.0 的
    `reuse_commands.load_context` + `ModuleLibrary.versions`：固定版本落后 → “模块可升级
    m-x 1.0.0 → 1.1.0（slot s1，章节 …）”，库中无任何版本 → “模块版本缺失”；
    两类都 `applyMode=none`、带依据（装配 slot + 可用版本）、`not_evidence`，不改装配、不建评审状态；
  - 摘要候选新增**可取消入口**：`_on_assist_summary_candidate` 记住插入位置并启用
    内容菜单「取消摘要候选」；`_discard_assist_summary_candidate()` 一次撤销，磁盘与
    `.state/relation_reviews.json` 均不变。
验证：python scripts\tests\test_v33_module_update_cancel.py -> Ran 3 tests OK
  （升级/缺失两类建议及其“无副作用、不当证据”；取消后编辑器回原文、磁盘与评审状态哈希不变；
    对照保存才写盘）
  回归：test_v33_authoring_assistance 29 OK／test_v33_registry 5 OK／test_v33_editor_wiring 4 OK／
        test_v33_adoption_editor OK／test_v33_background_index 5 OK／test_v33_three_document_pilot OK／
        test_v31_command_registry 13 OK（新增 kind 不影响既有断言）
遗留（保持未勾选）：6.2 三类文档**人工**试点与质量评价。
```

## 续七：建议导出入口（父会话第二十七轮）

```text
问题（规范覆盖审计）：规范要求“摘要确认与只读”包含建议导出，但 service.export_suggestions 零生产调用方，
  面板只有“插入引用/复制正文”，导出仅测试可达。

修复：面板采纳区新增「导出建议…」按钮（`export_suggestions_to_file`），调用服务层同一
  `export_suggestions` 生成审阅文本并写盘；只读项目默认文件名标注“（只读项目）”，同样可导出。
验证：scripts/tests/test_spec_gap_entries.py 2 项 OK（常规项目导出内容含建议；只读项目也能导出）。
```
