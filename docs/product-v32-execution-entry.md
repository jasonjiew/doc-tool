# V3.2 批次交付入口执行记录（32-A 契约 / 32-F 批次 CLI / 32-E 界面服务层差额）

- 日期：2026-10-02（本机时区）
- 批次：**32-A** 批次契约与默认策略、**32-F** 批次 CLI 与示例、**32-E** 界面服务层差额、
  **32-D** 自动部分验收（4.4）
- 入口：`docs/product-plan-v3.0-v3.3.md` 第 5 节；change：`openspec/changes/product-v32-batch-delivery`
- 本次勾选：**1.1、1.2、1.3、4.4、6.1、6.2、6.3**（逐条证据见第 7 节；未勾原因见第 8 节）
- 上一轮记录：`docs/product-v32-execution.md`（32-B/C/D/E 服务层，来源文件未改动）
- 边界遵守：新增 `doc_tool/application/delivery/{contract,cli_commands,gui_hooks}.py`、
  `examples/delivery/{README.md,batch.json}`、`scripts/tests/test_v32_delivery_entry.py`、本文件；
  只修改 `doc_tool/cli.py`（**仅新增** `delivery-*` 子命令与分派）与
  `openspec/changes/product-v32-batch-delivery/tasks.md`（只勾实测项）。未改 `doc_tool/ui/**`、
  `scripts/tests/run_tests.py`、`queue.py|snapshot_package.py|result_index.py` 的既有函数语义、其它 change 与其它文档。

## 1. 新增/修改文件与真实接口

| 文件 | 内容 | 关键接口 |
|---|---|---|
| `doc_tool/application/delivery/contract.py`（新） | schema 1 批次计划/成员/默认值/策略契约 | `BatchPlan`、`BatchEntry`、`BatchPolicy`、`BatchDefaults`、`parse_plan`、`parse_plan_text`、`load_plan_file`、`plan_report`、`policy_from_legacy_flags`、`legacy_flag_notes`、`entry_matches` |
| `doc_tool/application/delivery/cli_commands.py`（新） | 六个批次命令的实现（结构化结果，打印由 `cli.py` 负责） | `delivery_plan`、`delivery_run`、`delivery_status`、`delivery_retry`、`delivery_package`、`delivery_promote`、`run`、`render`、`main` |
| `doc_tool/application/delivery/gui_hooks.py`（新，纯服务层） | 队列/索引 → 界面状态与动作模型 + 打开路径解析 | `batch_view`、`plan_view`、`result_view`、`member_row`、`resolve_open_target`、`run_action`、`BatchView`/`MemberRow`/`FormatCell`/`ActionModel`/`OpenTarget`/`PlanRow`/`ResultRow` |
| `doc_tool/cli.py`（改） | 新增 `delivery-plan/run/status/retry/package/promote` 子命令与分派 | `main()` 中六个命令转入 `delivery_cli.main(args)`；既有 `project-export`、`assist-*`、`reuse`、`convert`、`pdf`、`template-fill` 等原样保留 |
| `examples/delivery/batch.json`（新） | 可复制示例计划（2 个成员、docx+html、目标目录 `delivery-out`） | schema 1 计划 |
| `examples/delivery/README.md`（新） | Windows 无 Word runner → 有 Word 机器补刷新的可复制命令与平台声明 | 按真实 `--help` 编写 |
| `scripts/tests/test_v32_delivery_entry.py`（新） | 25 个 unittest 用例（32-A/32-E/32-F + 4.4） | 见第 6 节 |

## 2. 任务 1.1：现有 API 核对结果与需补适配（实测记录）

| 现有实现 | 实际签名/行为（本轮实测） | 本轮怎么用 | 仍需补的适配 |
|---|---|---|---|
| `application/project_export.run_project_export(request, *, skip_word_refresh, cancel_token, progress, prior, only_formats, buffer_texts)` | 一轮多格式；`prior` + `only_formats` = 只补失败格式并复用原轮快照；`export-result.json` 固定在目标目录 | 批次执行唯一的出稿调用（队列内） | 无（本轮不改） |
| `application/project_export.read_export_index / report_docx_path / ExportReport.machine_report` | 索引读回、DOCX 判定、机器报告 | CLI 报告与打包来源 | 无 |
| `application/intake_contract`（`ExportRequest`/`ExportScope`/`FormatResult`/`FORMATS`/状态词） | `ExportRequest` **没有变体字段**；`normalize_format` 对未知格式原样返回 | 契约复用范围/格式/状态词；契约层显式拒绝未知格式 | **变体展开未接入出稿请求**：`BatchJob.variantId` 只登记，出稿按项目当前内容 |
| `application/content/variants.py`（`VariantsConfig.load/ids/get`） | 缺失/损坏 `variants.yml` 回退空配置，不阻断 | 计划解析时校验 `variantId`（未知 → 该项 warning，仍可执行） | 变体实际展开（`expand_document_variant`）未接出稿 |
| `application/workspace.py`（`load_workspace`、`valid_members`、`issues`） | 非法成员进 `issues` 并从 `valid_members` 排除，不阻断其它成员；成员按 `projectId`/路径去重 | 计划里 `kind: workspace` 展开为多个成员项 | 无 |
| `domain/output_state.py`（`is_formal_success`）、`pipeline`/`OutputState` | 正式事实唯一来源 | CLI/包/队列都不提升正式级别 | 无 |
| `ui/task_bridge.py`（`TaskRunner.start/cancel/poll/drain_events`、`TaskSpec`） | 依赖 Qt 事件循环（`QTimer` 轮询、`POLL_INTERVAL_MS=100`） | **未复用**：服务层用 `CancellationToken` + 逐项 `progress(job, stage, detail)` 提供同语义的取消/事件 | 2.2 要求的 `TaskRunner` 复用与 GUI 任务区接线 |
| `ui/main_window`、`task_dock`、结果组件 | 需要会话级接线 | 本轮未触碰 `ui/**` | 5.1/5.2/5.4 |
| `application/source_package.py`（`EXCLUDED_*`）、V2.9 `collection_ops` | 排除规则与"相对路径可搬"约定 | 包内排除规则与之一致（沿用上一轮实现） | 3.2 要求的 V2.9 集合打包 API 复用 |
| `cli.py::_project_export_command` | 单一机器报告 + 退出码 0/1/2 的既有先例 | 新命令沿用同一约定与"stdout 只放报告"的重定向手法 | 无 |

**当前 CLI（本轮改动前）**：`build/info/preflight/import/validate/check/trace/impact/lint/search/assist-*/status/migrate/autolink/renumber/project-export/reuse/convert/pdf/template-fill`；
本轮新增 6 个 `delivery-*`（见第 4 节），既有命令未改语义（原单项目入口冒烟见第 6 节）。

## 3. 32-A 契约（`contract.py`）

- **schema 1 计划**：`schemaVersion`、`batchId`、`policy`、`defaults`、`entries[]`。
  成员字段：`id`/`member`/`kind`(project|workspace)/`variantId`/`formats`/`destination`/`outputName`/`scope`/
  `sourceMode`/`strict`/`refresh`/`requestId`。JSON 与 YAML 都可读（`.json` 走 `json.loads`，其余走 `yaml.safe_load`）。
- **路径解析**：成员/目标相对 `--base-dir`，未给时相对计划文件所在目录；绝对路径按原样。
- **默认值优先级**：成员字段 > `defaults` 段 > 契约默认（`formats=[docx]`、`refresh=True`、`sourceMode=saved`、`strict=False`）。
- **默认策略（测试逐字段固定）**：`execution=serial`、`wordBusy=waiting-refresh`、`onPartial=keep-useful`、
  `strict=False`、`refresh=True`、`autoRetryLimit=0`、`idempotencyScope=local-common-registry`、`sourceMode=saved`。
- **默认值适配（旧入口标志 → 新模型）**：`policy_from_legacy_flags(strict=…, no_refresh=…)`；
  `legacy_flag_notes()` 对 `--source-mode current-buffer`（命令行无界面缓冲）、`--no-refresh`、`--strict` 给出显式说明。
  注：`delivery-run --no-refresh` 的语义是**执行时跳过 Word 刷新**（逐项落 `waiting-refresh`），
  不改变计划里 `refresh` 的声明；两者都在测试里固定。
- **非法成员只影响该项**：`BatchEntry.status ∈ ready|warning|invalid`，问题写在该项 `problems` 上；
  `ready|warning` 才可执行，`invalid` 进入 `skipped` 并在报告里集中列出（成员目录不存在/缺 `project.yml`/
  未知格式/`current-chapter` 缺 `current`/`current-buffer` 在命令行不可用）。
- **计划级问题**（schema 不符、根节点非映射、无 entries、文件缺失/不可读）→ `plan.problems` → CLI 退出码 2。

## 4. 32-F 批次 CLI、退出码与示例

| 命令 | 关键参数 | 行为 |
|---|---|---|
| `delivery-plan` | `--plan --base-dir --destination --formats --variant --strict --no-refresh --json/--output` | 只读预览：成员/变体/格式/目标/成员级问题；不执行、不入队（测试断言不产生队列文件） |
| `delivery-run` | 同上 + `--store --continue --retry-failed --cancel-after N` | 入队（去重、已完成跳过）后串行执行；`--continue` 续 `queued/interrupted`；`--retry-failed` 只补 `failed/partial/waiting-refresh`（复用原轮快照）；`--cancel-after N` 取消其余未开始项（已完成保留） |
| `delivery-status` | `--store --index(可重复) --plan --base-dir --json` | 只读：队列 + 结果索引 + 界面视图；**正常含失败任务也返回 0**，失败信息在报告内 |
| `delivery-retry` | `--store --job-id(可重复) --no-refresh --json` | 只重试未完成项（`is_retryable`），不重走已完成项 |
| `delivery-package` | `--from` 或 `--store [--job-id]`、`--target --variant --include-original --json` | 自足交付包（`.zip`/目录，包内相对路径） |
| `delivery-promote` | `package`、`--destination --word-available auto|yes|no --registry --source-project --json` | 换机按包内快照补刷新并本地登记；无 Word/刷新失败保持 `waiting-refresh`，原包不删除 |

**退出码契约（实测）**：`0` = 至少一个所请求范围内的可用结果（可含部分失败/待刷新/可读稿）；
`1` = 完全没有可用结果，或 `--strict` 阈值未满足；`2` = 参数/输入非法（计划不可读、schema 不符、
无可执行成员、store 缺失、包不存在、`--continue`/`--retry-failed` 互斥、argparse 层拒绝的取值）。
逐项 `exitCode`（0=该项有可用结果、1=该项无可用结果、2=未执行/取消）写进 `jobs[]`；
`delivery-plan` 只预览：`0` = 计划已解析、`2` = 计划不可读或结构非法。

**JSON 单一文档**：`--json`（= `--output json`）时 stdout 只有一个 JSON 报告，
库内过程输出统一重定向到 stderr（沿用 `project-export` 的既有手法）。

**本轮发现并修复的真实缺陷（共用目标目录）**：统一出稿把一轮索引固定在目标目录的
`export-result.json`，多个成员共用同一目标目录时该索引会被后一个成员覆盖，失败的成员还可能留下
"没有可用产物"的索引；`delivery-package --store` 若从该索引取报告，就会打出"本轮没有可打开 DOCX"。
修复两点：① 同一目标目录的多个成员自动分到 `<目标>/<成员名>`（报告里以 `destinationNotes` 明示）；
② 打包优先使用**任务自身落盘的报告**，索引仅作兜底。两条都有测试覆盖。

**示例与平台声明**：`examples/delivery/batch.json` 的成员是占位相对路径 `members/Alpha`、`members/Beta`，
用 `--base-dir <你的目录>` 指向真实成员即可预览/执行（示例本身在测试里就是这样被真实两章项目驱动执行的）。
`examples/delivery/README.md` 声明：命令在 **Windows + Python 3.13.13** 实测；本机 Word 可用，
因此"无 Word"分支用 `--no-refresh` 显式复现；**未**在无 Word 的独立机器/第二台真实机器上实测（属 7.3），
其它操作系统未验证、不作为支持范围。示例脚本不含上传/通知/公开发布步骤。

## 5. 32-E 界面服务层差额（`gui_hooks.py`）

- **已实现（纯服务层，不导入任何 Qt 绑定，测试直接断言源码中无 `PySide6`/`doc_tool.ui`/`QWidget`）**：
  逐成员行（`MemberRow`：成员/变体/范围/状态/状态词/逐格式单元 `FormatCell`（各格式状态独立、路径、
  可用性、正式标记）/可用计数/待补格式/DOCX/索引/尝试次数/等待原因/错误）；
  批次视图（`BatchView`：`overallStatus`、counts、行、动作、提醒，可叠加结果索引视图 `ResultView`）；
  计划预览（`PlanView`/`PlanRow`）；动作模型（`run-pending`/`resume-interrupted`/`retry-unfinished`/
  `refresh-pending`/`cancel-unfinished` 与逐行 `open-result`/`open-index`，含 `enabled` + 不可用原因 +
  `detail.jobIds` 参数）；动作执行（`run_action` → `DeliveryQueue.run_pending/resume/retry_unfinished/cancel`）；
  打开路径解析（`OpenTarget`：本地文件 / 目录 / `<包.zip>::包内成员` / 缺失 / 无路径，不伪造可打开）。
- **未做（导致 5.1/5.2/5.4 不勾选）**：任务区控件接线（`ui/task_dock`/结果组件渲染这些模型）、
  打开动作的实际调用（`QDesktopServices`/系统默认程序）、无 Word/部分失败时 GUI 连续编辑的交互测试。
  这些需要 `ui/main_window` 会话；本批次按边界未触碰 `ui/**`。

## 6. 验证命令与真实结果

```powershell
# 1) 本轮新增入口测试（32-A/32-E/32-F + 4.4）
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path; python scripts\tests\test_v32_delivery_entry.py
# 2) 上一轮服务层回归
python scripts\tests\test_v32_batch_delivery.py
```

| 次数 | 命令 | 真实输出 | 退出码 |
|---|---|---|---|
| 1 | `test_v32_delivery_entry.py` | `Ran 25 tests in 81.348s` + `OK` | 0 |
| 2 | `test_v32_batch_delivery.py` | `Ran 22 tests in 34.985s` + `OK` | 0 |

CLI 冒烟（真实两章项目夹具：2 个可执行成员 + 1 个清单校验失败的成员；`--no-refresh` 跳过 Word 刷新）：

| 命令（去掉路径） | 关键结果 | 退出码 |
|---|---|---|
| `delivery-plan --plan … --json` | `executableCount=3`、`skipped=0` | 0 |
| `delivery-run --plan … --store … --no-refresh --json` | `overallStatus=partial`；逐项 `waiting-refresh/exitCode 0`（docx+html、docx）、`failed/exitCode 1`（无可用格式） | 0 |
| `delivery-status --store … --json` | `counts`: waiting-refresh 2 / failed 1；失败信息在报告内 | 0 |
| `delivery-run … --strict --continue --json` | `strict=true`、`overallStatus=partial`、可读参考产物仍在 | 1 |
| `delivery-package --store … --target …zip --json` | `package.ok=true`，包内无绝对路径 | 0 |
| `delivery-promote …zip --destination … --word-available no --json` | `status=waiting-refresh`、可读 DOCX 存在、原包保留、无 `delivery-registry.json` | 0 |
| `delivery-run … --cancel-after 1 --json` | 1 项有尝试历史、其余 `cancelled`（`exitCode 2`、可用结果为 0） | 0 |
| `delivery-promote 不存在的包 --json` | 报告在 stdout，错误信息明确 | 2 |
| `project-export --project … --formats docx,html --no-refresh --output json`（原单项目入口） | `usable=['docx','html']`、`docxPath` 有值 | 0 |
| `template-fill --help`（原入口参数不受影响） | 帮助含 `--output`（DOCX 路径语义） | 0 |

未运行整套 `scripts/tests/run_tests.py`（按本批约定只跑上述两个文件 + CLI 冒烟，避免与并发会话互相影响）。

## 7. 勾选与证据对照

| 编号 | 结论 | 证据 |
|---|---|---|
| 1.1 | 已核对并记录 | 本文件第 2 节（含 `TaskRunner`/`TaskSpec`、`pipeline`/`OutputState`、集合、变体 API、当前 CLI 与需补适配） |
| 1.2 | 已实现且已测 | `contract.py` schema 1 计划/成员/策略模型；`test_v32_delivery_entry.ContractTests.test_default_policy_and_legacy_flag_adapter_are_pinned`；正式事实仍只由 `domain/output_state.py` 判定 |
| 1.3 | 已实现且已测 | `parse_plan`（项目/工作区/变体/格式/默认值/非法成员隔离）；`ContractTests.test_plan_parses_members_defaults_and_isolates_invalid_items`（工作区展开 2 项、4 个非法项逐条原因）、`test_unknown_variant_is_item_warning_not_blocking`、`test_plan_overrides_force_strict_and_destination`、`test_plan_parses_yaml_plan`、`test_plan_file_level_problems_are_reported` |
| 4.4 | 已实现且已测 | `DeliveryCliTests.test_package_then_promote_in_new_directory`（`--word-available no` → `waiting-refresh`、可读 DOCX 存在、原包保留、不写正式登记）；`PackageFormalizeTests.test_refresh_failure_keeps_waiting_refresh_and_original_package`（刷新适配器抛错同样保持待刷新）；严格未满足仍保留可读产物的证据在 `test_strict_threshold_returns_one_but_keeps_readable_results`（批次运行层） |
| 6.1 | 已实现且已测 | `cli_commands.py` 六个命令全接既有编排（`DeliveryQueue`/`run_project_export`/`build_delivery_package`/`formalize_package`）；`DeliveryCliTests.test_help_exposes_delivery_contract_options`、`test_invalid_inputs_return_two`、YAML 计划用例 `ContractTests.test_plan_parses_yaml_plan`、`--strict` 用例 `test_strict_threshold_returns_one_but_keeps_readable_results` |
| 6.2 | 已实现且已测 | human/JSON 输出（`render`）+ 单一 JSON 文档（`_json` 断言整段 stdout 可解析）；退出码 0/1/2 与 `status` 只读返回 0：`test_run_partial_success_defaults_to_zero_with_per_item_exit_codes`（逐项 `exitCode` 0/0/1）、`test_status_is_read_only_and_reports_failures_inside`、`test_strict_threshold_returns_one_but_keeps_readable_results`、`test_conflicting_modes_return_two_without_touching_store`、`test_invalid_inputs_return_two` |
| 6.3 | 示例已提供且两段本地流程已实测 | `examples/delivery/{batch.json,README.md}`；`DeliveryCliTests.test_example_plan_and_readme_are_runnable_against_base_dir`（用真实成员目录按 `--base-dir` 驱动示例计划，2 个可执行成员、目标解析在基准目录下）；无 Word 段（`--no-refresh` → 包）与"有 Word 机"段（换目录 `delivery-promote`，无 Word 时 `waiting-refresh`）见第 6 节冒烟表；README 按实测声明平台，**真实第二台机器/真实 Word 正式化仍未验收**（7.3） |

## 8. 未勾选与未验收项（含原因）

- **1.4**：未建立"断网"夹具；原单项目入口只用冒烟验证（`project-export` 退出 0、`template-fill --help` 退出 0），
  没有登记进测试文件，故不勾。
- **2.2**：未复用 `TaskRunner`（GUI 事件桥接）；服务层仍是 `CancellationToken` + 逐项 progress 回调。
- **2.3**：未实现本应用**跨进程** Word 占用标识；串行化只在单个队列进程内成立。
- **2.4**：未实现"临时幂等故障自动重试一次"（`AUTO_RETRY_LIMIT` 仍留位默认 0，需用户显式 `delivery-retry`）。
- **3.2**：未复用 V2.9 collection 打包 API（沿用上一轮功能等价实现）。
- **3.4**：包版本不符时的"回退阅读/导出"未实现（schema/kind 不符直接判 `invalid`）。
- **3.5**：断网、同名文件冲突、旧状态包、非法附件等场景未逐一覆盖（已覆盖换目录、非法包、哈希不符、来源变化）。
- **4.5**：fake refresh 成功/失败、登记故障、重复处理、旧源变更均已测（上一轮 22 用例 + 本轮
  `PackageFormalizeTests.test_refresh_failure_keeps_waiting_refresh_and_original_package`），但该项要求
  "真实 Word 用例在可用环境补证"，本机虽有 Word，本批未驱动真实 Word 正式化 → 保持未勾（并入 7.3）。
- **5.1/5.2/5.3/5.4**：5.1/5.2/5.4 的**控件接线**未做（只有 `gui_hooks.py` 服务层模型，界面控件接线需
  `ui/main_window` 会话）；5.3 的"完整集合登记复用 V2.9"未实现。
- **6.4**：测试已按"输出/参数/部分成功/严格阈值/恢复"实现（第 7 节 6.2 行），示例脚本不含自动上传/消息/公开发布；
  但**新测试文件未注册进 `scripts/tests/run_tests.py` 的 `DEFAULT_TESTS`**——该文件在本轮允许范围之外，
  故不勾（见第 10 节第 1 条）。
- **7.1-7.5**：未跑整套套件与 A32-1～6 全场景留证；10 成员批次实测、真实 Word/两机交接、版本收尾与
  OpenSpec 校验/归档均未做。

## 9. 环境事实与限制

- Python **3.13.13**（Windows）；本机 Word 可用，但本轮所有出稿都用 `--no-refresh`（逐项待刷新），
  `delivery-promote` 用 `--word-available no`，**未驱动真实 Word**，不声称真实 Word 正式化已验收。
- 本工作区文件系统对 DSH `write`/`edit` 报 `EXDEV: cross-device link not permitted` / `ReplaceFileW EIO`：
  本轮源码与文档都改用「先写临时文件，再用 PowerShell `[System.IO.File]::WriteAllText`（UTF-8 无 BOM）/
  `Copy-Item` / Python `Path.write_text` 落到仓库」的方式写入，仓库内容与编码（无 BOM）已逐文件核对。
- **并发风险（重要）**：本仓库同时有其它会话在改仓库（本轮期间 `doc_tool/cli.py` 被多次整体重写，
  `scripts/tests/run_tests.py`、`doc_tool/application/command_registry.py`、V3.1 相关文件同期在改）。
  本轮 `delivery-*` 注册与分派在写入后已回读复核仍然存在，并且**只做"新增子命令 + 新增分派分支"**，
  未改动任何既有命令；若后续 `cli.py` 再次被整体重写，请按第 4 节的参数表重新插入（`main()` 中的分派点在
  `assist-*` 分支之前，`build_parser()` 里 `return parser` 之前）。

## 10. 下一任务

1. **6.4 收尾**：把 `test_v32_delivery_entry.py` 加入 `scripts/tests/run_tests.py` 的 `DEFAULT_TESTS`
   （本轮越界未改），然后跑整套套件（7.1）。
2. **5.1/5.2/5.4 接线**：在 `ui/main_window` 会话里用
   `gui_hooks.batch_view/plan_view/result_view/resolve_open_target/run_action` 渲染任务区并接打开动作。
3. **差额**：2.2（TaskRunner 复用）、2.3（跨进程 Word 标识）、2.4（幂等临时故障自动重试一次）、
   3.2（V2.9 集合打包）、3.4（包版本回退）、3.5（断网/同名/旧包/非法附件）、1.4（断网夹具 + 原入口兼容登记）。
4. **实机验收**：真实 Word 正式化（7.3/4.5 真实分支）、两机交接（7.3）、10 成员批次实测（7.2），
   随后 7.1/7.4/7.5（套件与 A32-1～6 留证、文档/版本源/冻结冒烟、OpenSpec 校验与归档）。

## 续：32-E GUI 入口与 2.2 TaskRunner 复用（父会话第五轮）

```text
实现：`doc_tool/application/delivery/gui_tasks.py`（Qt-free 任务适配：plan_preview /
  run_plan_task / retry_unfinished_task / status_snapshot）+ 操作菜单「批量交付（持久队列）…」
  （Ctrl+Alt+B）：选计划 → 预览可执行/无效成员 → 经 `_start_task` 后台串行执行 →
  结果页给「打开首个产物 / 打开结果目录 / 只重试未完成项 / 补刷新（正式稿）」。
  可打开产物来自队列内各成员可用格式 + 结果索引（含待刷新项），不重走已完成成员。
验证：python scripts\tests\test_v32_delivery_ui.py -> Ran 8 tests OK (exit 0)
  覆盖：计划预览、串行执行保留可用结果与幂等入队、只补未完成项、状态快照含批次/结果视图、
        非法成员只报告不执行、入口经 TaskRunner 启动、结果页四个动作、补刷新传 skip_word_refresh=False。
  回归：test_v32_delivery_entry.py 25 OK、test_v32_batch_delivery.py 22 OK。
示例安全：examples/delivery 扫描无 upload/publish/notify/http 调用。
遗留：4.5/7.3 真实 Word 正式化与两机交接、7.2 10 成员实测、7.4 版本源/冻结、7.5 同步归档；
      3.2/3.4/3.5 与 1.4 的服务差额见第 8 节。
下一批 / 下一任务：32-F/1.4
```

## 续二：2.3 跨进程 Word 占用标识与 2.4 临时故障自动重试（父会话第六轮）

```text
实现：
  - `doc_tool/application/delivery/word_busy.py`：用户级 `word-busy.json` 标记
    （schema 1，记录 owner/pid/since），带 TTL 与进程存活校验；过期或持有进程已退出
    视为陈旧并可被接管，避免崩溃后永久阻塞批次。
  - 队列 `_word_available` 现在先读标记、再探测本机 Word：被其它进程占用时本项转
    待刷新（可读 DOCX/HTML 保留），其它成员继续。
  - 队列新增 `_call_runner_with_retry`：仅对 OSError/TimeoutError 这类临时故障自动
    重试 `AUTO_RETRY_LIMIT=1` 次，尝试记录 `autoRetries`/`retryReason` 并追加一条
    说明；内容与参数类失败不重试。
验证：python scripts\tests\test_v32_word_busy_retry.py -> Ran 7 tests OK (exit 0)
  覆盖：登记/占用拒绝/释放、陈旧标记接管、probe 优先级、被占用项转待刷新且可读副本
        仍在、临时故障重试一次后成功、非临时失败不重试、持续失败在限额后停止。
  回归：test_v32_batch_delivery.py 22 OK、test_v32_delivery_entry.py 25 OK（本轮复跑）。
遗留：3.2/3.4/3.5 与 1.4 的服务差额；4.5/7.2/7.3 实机；7.4/7.5 收尾。
下一批 / 下一任务：32-C/3.4
```

## 续三：3.4 包版本回退与 3.5 旧包/非法附件（父会话第六轮）

```text
实现：`doc_tool/application/delivery/package_version.py`
  - `version_fallback(package)`：清单 kind 匹配但 schemaVersion 不同 → readableOnly
    （高版本“只回退阅读/导出”，低版本“按只读兼容，正式化回原机”）
  - `readable_artifacts(package)`：列出包内可导出产物（docx/html/zip，包内相对路径）
  接线：`verify_delivery_package` 对回退包返回 ok=True + readableOnly + versionNote 并列出
    可导出产物；`formalize_package` 对回退包返回 status=readable-only 并给下一步提示，
    不在未知版本语义下执行正式化。
  安全：`verify_delivery_package` 新增非法附件校验（绝对路径/盘符/`..` 一律判不可用）。
验证：python scripts\tests\test_v32_package_version.py -> Ran 7 tests OK (exit 0)
  覆盖：同版本正常、较新版本回退可读且可导出 DOCX、较旧版本只读且正式化被拒、
        无关 kind 不回退、包内路径全相对且无凭据/.git、越界成员判不可用、坏 ZIP 不抛。
  回归：test_v32_batch_delivery 22 OK / test_v32_delivery_entry 25 OK / test_v32_delivery_ui 8 OK。
遗留：1.4（单项目入口离线夹具测试）、3.2（复用 V2.9 集合打包 API）、4.5/7.2/7.3 实机、7.4/7.5 收尾。
下一批 / 下一任务：32-A / 1.4
```

## 续四：3.2/5.3 复用 V2.9 集合包装与登记（父会话第七轮）

```text
实现：`doc_tool/application/delivery/collection_bridge.py`
  - `collection_manifest_for` 复用 `collection.build_manifest`（收集规则/分类/跳过 .git、
    缓存、虚拟环境）并在目录内落 `collection-manifest.yml`
  - `export_collection_zip` 复用 `collection_ops.export_package`（越界/缺失/改动项跳过）
  - `register_collection` 复用 `collection.register_manifest`（原子登记，失败不删成果）
  接线：交付包（目录与 ZIP）内新增集合清单与 `collection` 摘要；选择归档在**完整**时登记
    集合基线，部分范围只标注（`complete=False`、清空 registrationPath 并注明），缺失列 missing。
修复的真实缺陷（本机可复现，影响面超出本包）：
  `collection.register_manifest` 与 `content/impact.ReviewRecordStore.save` 使用裸
  `os.replace`，在跨设备/文件过滤层拒绝 rename 的机器上抛 `WinError 17` → 集合登记与
  负责人记录必然失败。已按既有 `atomic_write` 惯例加 `shutil.move` 回退。
验证：python scripts\tests\test_v32_collection_bridge.py -> Ran 7 tests OK (exit 0)
  覆盖：桥接清单/登记/安全 ZIP、跳过 .git 与 __pycache__、目录包与 ZIP 包含集合清单、
        完整选择登记、部分选择不登记完整基线、空索引明确失败。
  回归：test_v32_batch_delivery 22 OK / test_v32_delivery_entry 25 OK。
遗留：1.4（断网夹具与单项目入口测试）、4.5/7.2/7.3 实机、7.1/7.4/7.5 收尾。
下一批 / 下一任务：32-A / 1.4
```

## 续五：1.4 多项目/变体与断网/无 Word/坏格式夹具（父会话第七轮）

```text
夹具：三项目（Alpha/Beta 有效 + Broken 清单 YAML 损坏）+ 两个变体成员（Alpha 的
  standard/pro 变体）+ 断网（socket.connect/create_connection/connect_ex 全部失败）+
  无 Word（注入探测返回不可用）。
验证：python scripts\tests\test_v32_entry_points.py -> Ran 4 tests OK (exit 0)
  覆盖：计划列出全部成员且坏格式成员在执行时**单独失败**（3 个完成 / 1 个失败，其它继续）、
        断网下批次仍正常出稿（≥3 个可打开产物）、无 Word 全部转待刷新且可读副本仍在、
        原单项目入口兼容（有效项目可用；坏项目抛结构化 DocToolError，批次路径捕获后只让该项失败）。
  回归：test_v32_batch_delivery 22 OK / test_v32_delivery_entry 25 OK /
        test_v32_collection_bridge 7 OK / test_collection_v29 16 OK。
遗留：4.5/7.2/7.3 实机（真实 Word 正式化、两机交接、10 成员实测）；7.1 A32 场景表；
      7.4 版本源/冻结；7.5 同步归档。
下一批 / 下一任务：32-G / 7.1
```

## A32-1～6 场景留证（父会话第七轮，直接套件 + 全量回归）

| 场景 | 证据（真实运行） | 结果 |
|---|---|---|
| A32-1 多项目/多成员提交部分成功、失败项可续跑 | `test_v32_entry_points.py`（3 有效 + 1 坏格式：3 完成 1 失败其它继续）、`test_v32_batch_delivery.py`（入队/部分失败/取消保留） | 通过 |
| A32-2 中断后只补未完成、重复处理不重复登记、取消保留 | 同两份套件（resume/retry_unfinished/幂等入队/取消保留已完成） | 通过 |
| A32-3 无 Word 得可读包待刷新、源后来修改不破坏固定交付 | `test_v32_word_busy_retry.py` + `test_v32_entry_points.py`（无 Word 全转待刷新且可读副本在）+ `test_v32_delivery_entry.py`（包内原快照、原包保留） | 通过 |
| A32-4 真实 Word 生成并刷新/后校验并登记、失败保留可读 DOCX | `test_v32_real_word_formalize.py`（`V32_REAL_WORD=1`）：包内快照真实刷新 → `is_formal_success` 认定为正式 → 登记写入且原包保留；等效独立目录（换机）同样通过；重复正式化 `already-registered` 幂等；无 Word 时保持待刷新且可读 DOCX 保留 | 通过 |
| A32-5 缺 PDF/非法源/Word 忙默认部分继续、严格模式阻断、单一登记一致 | `test_v32_package_version.py`（非法附件/坏包/版本回退）+ CLI 冒烟（严格阈值 exit 1）+ `test_v32_delivery_entry.py`（登记失败保留安全副本） | 通过 |
| A32-6 GUI/CLI 同计划同状态、JSON 可解析、示例可运行 | `test_v32_delivery_ui.py`（入口走 TaskRunner、结果页四动作）+ `test_v32_delivery_entry.py`（JSON 报告与退出码）+ `examples/delivery`（无 upload/publish/notify） | 通过（GUI 控件深度接线为服务层模型 + 既有 Dock/对话框） |

全量回归（第十四轮复跑）：`run_tests.py` **124 个测试文件、1 项失败**（`test_gui_services.py` 的 Mermaid 预览，本机缺 `mmdc`）；审计更正：此前写作 114 文件。
A32-4 未完成前 7.1 保持未勾选，不虚勾。

## 续六：7.2 十成员批次实测（父会话第八轮，同机脱敏夹具）

```text
命令：python scripts\tests\measure_v32_batch10.py（输出 JSON）
样本：10 个成员（同一两章项目复制 10 份，其中第 10 个清单故意损坏），全部 docx、saved、refresh=False

结果：
  计划：10 可执行 / 0 无效（计划层为浅校验，坏成员在执行期单独失败）
  首轮：总耗时 10.88 s（约 1.09 s/成员）；9 完成（带提醒）+ 1 失败；9 个可打开产物
  磁盘：产物 337,514 B；队列存储 44,127 B
  续跑：修复坏成员后 retry_unfinished 仅重跑 1 个成员、耗时 1.02 s
       总数 10 全部完成（failed=0），产物增至 374,835 B，尝试记录 11 条（无重复登记）

结论与预算：单成员约 1 s 主要是快照+诊断构建；10 成员串行在 11 s 内完成，
  失败续跑成本与成员数无关（只跑未完成项）。后续优化预算按“减少重复解析/构建”投入，
  不引入常驻服务或并行抢占 Word。
未验收：真实 Word 刷新与两机交接（4.5/7.3）仍单列。
```

## 续七：7.4 说明/版本源与冻结冒烟（父会话第十轮）

```text
文档：`docs/product-v30-v33-usage.md` 第 2 节（批次/交付包/CLI/恢复/Word 占用/自足包/限制）
  与第 4 节（版本源、冻结冒烟、同步归档前置）。
版本源：保持 2.9.0；V3.2 发布号同批发布时确定。
冻结冒烟（真实执行，同一产物）：产物校验通过 + 签名 46 文件 + test_frozen_smoke 11 项 OK；
  冻结 CLI 复核含 V3 命令：delivery-plan / delivery-run / project-export / reuse /
  assist-search / assist-provider 的 --help 全部 exit 0。
OpenSpec：openspec validate product-v32-batch-delivery --strict → valid
遗留：4.5/7.1/7.3（真实 Word COM 间歇超时，实机待验收）、7.5 同步/归档。
```

## 续八：4.5 / 7.3 真实 Word 正式化打通（父会话第十轮）

```text
首次实测失败 → 逐层定位后修复两处真实缺陷，最终通过：
  ① 状态缺失（根因）：管线把正式稿发布在包内快照目录（正式状态记录也在那里），
     `_run_docx` 复制到导出/交付目录后未为目标路径写状态 →
     `is_formal_success(目标)` 为假 → 按包正式化把已刷新的正式稿误判为“待刷新”。
     修复：复制成功后为目的小写 `write_state(formal=True, ...)`。
  ② 探测误判：`check_word_available` 默认 10 s 超时在慢机器上会超时被判“无 Word”。
     修复：单项目出稿/按包正式化的探测放宽到 30 s；调用方已确定的可用性一路传给管线预检
     （`run_project_export(..., word_available=...)` → `run_pipeline(..., word_available=...)`），
     批量队列仍用 10 s（避免每成员长超时）。
验证：$env:V32_REAL_WORD='1'; python scripts\tests\test_v32_real_word_formalize.py
  -> Ran 3 tests OK (58.2 s)
  覆盖：包内原快照真实刷新→正式成功（OutputState 判定）→登记写入、原包保留、源项目未被改写；
        包复制到独立目录树（等效换机）后仍可正式化；重复正式化 already-registered 且只登记一条。
待验收（仍未执行）：真实两机物理交接（当前以等效独立目录替代）、125%/150% 缩放。
```

## 续九：7.3 进程级换机验证（父会话第十三轮）

```text
命令：$env:V32_REAL_WORD='1'; python scripts\tests\test_v32_cross_process_promote.py
  -> Ran 2 tests OK (62.1 s)
场景：包复制到独立目录树 + **独立子进程**执行
  `python -m doc_tool.cli delivery-promote <包> --destination <正式稿> --word-available yes --json`
  （仅隔离工具自身配置/缓存目录；不动 USERPROFILE，避免 Word COM 拿不到真实用户配置）
结果：子进程退出码 0、机器报告 status=registered、`is_formal_success` 判定正式、
  `delivery-registry.json` 写入条目；**第二个全新子进程再跑同一包 → already-registered（幂等）**。
意义：把“换机等效”从“同进程 + 独立目录”提升为“独立进程 + 独立目录 + 独立工具配置”，
  证明补刷新链路不依赖任何进程内状态。
未执行：真实两台物理机器（不同机器/账户）交接、125%/150% 缩放检查。
```

## 7.2 实测数据更正（父会话第十四轮，独立审计 + 复跑）

```text
独立审计复跑（同一脚本、夹具不变）：隔离 87.01 s（8.70 s/成员）、并发 125.19 s（12.52 s/成员）、续跑 10.78 s
本轮复跑（机器较空闲）：81.57 s（8.16 s/成员）、续跑 6.74 s
结构数字：产物 337,508 B（前记 337,514）、队列存储 44,127 B（精确一致）、
          9 完成 + 1 失败、续跑 1 个成员、尝试 11 条、续跑后 10/10

结论：**耗时随机器负载差异极大**（约 80～125 s / 10 成员），此前记录的 10.88 s（1.09 s/成员）
      属异常偏快值，已作废，不作为性能优化预算基线；结构与体积数字可复现。
```

## 续十：2.2 逐项进度接线 + 5.1 结果页逐成员渲染（父会话第十七轮）

```text
问题（第十四轮审计）：
  2.2 界面入口用 TaskSpec(kwargs={}) 启动，队列 per-item progress 永远为 None，
      Dock 只见任务级事件；
  5.1 计划预览/结果页只显示 summary_lines()[:12] 截断摘要，未渲染 gui_hooks 的
      逐成员格式/状态/路径单元格。

修复：
  - `gui_tasks`：新增 `DeliveryStageEvent` 与 `_QueueProgressRelay`，把队列的
    `progress(job, stage, detail)` 转成 `delivery:<stage>` 阶段事件（metrics 带
    jobId/成员/变体/序号）；`run_plan_task` / `retry_unfinished_task` 增加 `on_event`
    参数 → TaskRunner 自动注入（`task_bridge._run` 的 `on_event` 约定），Dock 即可看到
    每个成员的开始/完成/失败/重试。成员名与 `gui_hooks.member_row` 同源解析。
  - 结果负载新增 `memberRows`（MemberRow.to_dict()）；`MainWindow._delivery_member_lines()`
    逐条列出“成员（变体）｜状态｜可用格式数”与每个格式的状态/产物路径（缺失标注），
    结果页与计划预览通过 `setDetailedText` 提供「显示详细信息」。
验证：python scripts\tests\test_v32_delivery_progress.py -> Ran 5 tests OK
  （队列进度→阶段事件；重试路径同样上报；真实 TaskRunner 端到端注入并收到 delivery:* 事件；
   结果页/计划预览明细含成员、变体、格式、状态、产物路径）
  回归：test_v32_delivery_ui 8 OK（测试假对话框补 setDetailedText）、test_v32_batch_delivery 22 OK、
        test_gui_services 170 项仅 1 项环境失败（mermaid）
遗留（保持未勾选）：4.2 变体仅登记不展开；7.5 同步归档；4.5/7.3 需 Word 环境复跑。
```

## 续十一：4.2 变体真正接入出稿（父会话第二十轮）

```text
问题（第十四轮审计）：`variantId` 只是包里的元数据——`ExportRequest` 没有变体字段，
  出稿一律按项目当前内容，交付包里的“变体”名不副实。

修复：
  - `ExportRequest.variant_id`（+ `variantId` 只读属性、from_dict 兼容 variantId）；
  - `capture_snapshot(..., variant_id=...)`：用 `variants.expand_document_variant(write=False)`
    取变体有效内容（章节 include/exclude + 变量 + 模块版本），把快照物化为**变体内容**；
    变体未纳入的章节记为 omitted，不再出现在 Word/HTML/检查/包里；
    未知变体或展开失败 → 只记 `variantWarnings` 并按项目当前内容继续（不阻断出稿）；
  - 报告与队列：`ExportReport.variantId/variantApplied` 进入 `machine_report()`/索引/
    `queue._report_from_dict`；`BatchJob.request()` 带上 `variant_id`；
  - 交付包 `origin.variantId` 优先取报告值并新增 `variantApplied`（包内可核对是否真的按变体出稿）。
验证：python scripts\tests\test_v32_variant_export.py -> Ran 5 tests OK
  （变体限制章节并记录在报告与包里；不带变体仍出整份；未知变体带提醒继续；
   包 origin 记录 variantId+variantApplied；队列任务把变体带进请求与报告）
  回归：test_v32_batch_delivery 22 OK／test_v32_delivery_entry 25 OK／test_v32_delivery_ui 8 OK／
        test_v32_delivery_progress 5 OK／test_core_export_snapshot 16 OK／test_core_cli_export 8 OK／
        test_v30_content_reuse 36 OK
遗留：7.5 同步归档；4.5/7.3 需 Word 环境以 V32_REAL_WORD=1 复跑。
```

## 续十二：实机 Word 证据刷新 + 逐项进度界面可见（父会话第二十四轮）

```text
环境：清理 5 个遗留的无窗口 WINWORD 进程后，Word 16.0 可直接 DispatchEx（2.6 s），
  但启动时间抖动大（2.6～17.6 s）——默认 10 s 探测会误判为“不可用”。

刷新证据：
  $env:V32_REAL_WORD='1'; python scripts\tests\test_v32_real_word_formalize.py
    -> Ran 3 tests OK（73.8 s：包内正式化 / 换机等效目录 / 幂等登记）
  $env:V32_REAL_WORD='1'; python scripts\tests\test_v32_cross_process_promote.py
    -> Ran 2 tests OK（41.8 s：独立子进程 delivery-promote + 二次 already-registered）
    （该用例的可用性探测由默认 10 s 放宽到 60 s，避免慢启动被误判为无 Word）

复核修复：`_on_task_event` 现处理 `stage` 事件 → 逐项进度写入任务面板日志并更新状态栏
  （此前只处理 failed/cancelled/succeeded，后台任务的逐项进度到不了界面）。
```

## 全量回归与实机 Word 复跑（父会话第三十二轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r32.xml
  -> **146 个测试文件 / 1 项失败 / 0 错误**（唯一失败仍为环境项：test_gui_services 的 Mermaid 预览缺 mmdc）
  说明：第三十一轮的那处 Word 依赖失败在本轮未复现（Word 可用 → 生成了可读 DOCX），
        且该用例现只在确认环境原因时 skip —— 套件结论回到“仅 1 项环境失败”。

实机 Word 复跑（清理 1 个遗留无窗口 WINWORD 后，word available=True）：
  $env:V32_REAL_WORD='1'; python scripts\tests\test_v32_real_word_formalize.py
    -> Ran 3 tests OK（61.2 s）
  $env:V32_REAL_WORD='1'; python scripts\tests\test_v32_cross_process_promote.py
    -> Ran 2 tests OK（39.1 s）
```
