# V3.2 批量交付与换机正式化：服务层执行证据

- 日期：2026-10-01（本机时区）
- 批次：32-B 持久本地队列、32-C 可携带交付包、32-D 换机补刷新与登记、32-E 结果索引与选择归档（服务层）
- 入口：`docs/product-plan-v3.0-v3.3.md` 第 5 节；change：`openspec/changes/product-v32-batch-delivery`
- 本次勾选：**2.1、2.5、3.1、3.3、4.1、4.2、4.3**（其余保持未勾选，原因见第 7 节）
- 边界遵守：只新增 `doc_tool/application/delivery/**`、`scripts/tests/test_v32_batch_delivery.py`、本文件，并只勾选
  `openspec/changes/product-v32-batch-delivery/tasks.md` 中真正实现并测过的项；未改 `cli.py`、`ui/**`、
  `scripts/tests/run_tests.py`、README、其它 docs 与其它 change。

## 1. 新增文件与真实接口

| 文件 | 内容 | 关键接口 |
|---|---|---|
| `doc_tool/application/delivery/__init__.py` | 服务层导出 | `DeliveryQueue`/`build_delivery_package`/`formalize_package`/`build_result_index`/`archive_selection` |
| `doc_tool/application/delivery/queue.py` | 持久批次队列（schema 1，本地 JSON） | `DeliveryQueue.enqueue/run_pending/resume/cancel/retry_unfinished/machine_report`、`BatchJob`、`EnqueueResult` |
| `doc_tool/application/delivery/snapshot_package.py` | 自足快照包 + 换机补刷新/正式化 | `build_delivery_package`、`read_delivery_package`、`verify_delivery_package`、`formalize_package` |
| `doc_tool/application/delivery/result_index.py` | 结果索引视图 + 选择归档 | `build_result_index`、`ResultIndex`、`archive_selection`、`ArchiveOutcome` |
| `scripts/tests/test_v32_batch_delivery.py` | 22 个 unittest 用例 | 见第 5 节 |

产物路径（运行时数据，均为相对/可注入）：

- 队列 store：默认 `~/.<配置目录>/delivery/delivery-queue.json`，测试与调用方可用 `DeliveryQueue(store_path)` 注入；
  `batchId`/`jobId`/`requestId`/`attempts`/逐项状态与产物路径全部落在该文件，**不含正文**。
- 交付包：`delivery-manifest.json`（schema 1）+ `docx/`（可读稿）+ `snapshot/`（固定正文/底模/资源，相对路径）
  + `reports/export-result.json`（路径改写为包内相对）+ `DELIVERY_PACKAGE.md`；可输出 `.zip` 或目录。
- 正式化登记：目标目录下 `delivery-registry.json`（键 = packageId + 输入 digest + 目标位置），可用
  `registry_path` 注入；登记失败的新 DOCX 安全副本写 `<目标目录>/待登记/`。
- 选择归档：`selection-manifest.json`（含 `partial`/`omitted`/`missing`）。

## 2. 复用与差额（未重造）

复用的既有实现（直接调用，未复制逻辑）：

- `doc_tool/application/project_export.py`：`run_project_export`（含 `prior` + `only_formats` 的"只补失败格式"语义）、
  `read_export_index`、`report_docx_path`、`ExportReport`、`export-result.json` schema 1。
- `doc_tool/application/intake_contract.py`：`ExportRequest`/`ExportScope`/`FormatResult` 与状态词
  （`ready`/`pending-refresh`/`pending-convert`/`failed`/`cancelled`/`skipped`）、`fresh_output_path`、`sha256_file`、
  `sha256_text`、`normalize_format(s)`、`sanitize_name_part`、`utc_now_iso`。
- `doc_tool/application/effective_snapshot.py`：`capture_snapshot`/`EffectiveSnapshot`/`mark_source_updated`
  （出稿轮与包内快照都由它产生，包不重新定义快照格式）。
- `doc_tool/application/source_package.py`：排除规则（Git/凭据/缓存/日志/中间产物）与"相对路径可搬"的既有约定。
- `doc_tool/domain/output_state.py`：`write_state`/`read_state`/`is_formal_success` —— 正式成功事实的**唯一**来源；
  队列/包/归档都不提升正式级别，`formal` 字段直接取自该判定。
- `doc_tool/domain/cancellation.py`：`CancellationToken`（阶段边界取消）；`doc_tool/application/content/writer.py`：
  `atomic_write`（store、包清单、登记文件全部原子写）。
- `scripts/tests/core_fixtures.py`：`scratch_dir`/`cleanup`/`two_chapter_project`（真实导入产物夹具）。

有意留下的差额（本批次未实现，对应任务保持未勾选）：

- 未复用 `ui/task_bridge.py` 的 `TaskRunner`：GUI 逐项事件桥接属于 32-E/32-F，未触碰 `ui/**`；
  服务层用 `CancellationToken` + 逐项 `progress(job, stage, detail)` 回调提供同一取消/事件语义。
- 未复用 V2.9 collection 打包 API：包内的"收必要文件 + 排除规则"由本模块实现（功能等价，规则与
  `source_package.EXCLUDED_*` 保持一致），未调用 `collection_ops`。
- 未实现"本应用跨进程 Word 占用标识"与"临时幂等故障自动重试一次"（见第 7 节 2.3/2.4）。
## 3. 正常路径

1. `DeliveryQueue.enqueue(...)` 登记项目/变体/范围/格式（可带 `requestId`）→ store 落盘（原子写）。
2. `run_pending()` 串行调用 `run_project_export`：单项完成即写回 `report`/状态/`attempts`；单项异常只把该项标 `failed`。
3. `build_delivery_package(report_or_index, target=…zip)`：把该轮可读 DOCX、其他可用格式产物、固定快照
   （content/template/assets/project.yml）与改写后的报告打成相对路径包。
4. 换目录/换机器 `formalize_package(package, destination=…, word_available=…)`：校验清单与 hashes → 准备包工作副本 →
   按包内原快照只补 `pending-refresh`/`pending-convert` 阶段 → 用 `is_formal_success` 判定后写本地登记。
5. `build_result_index([...])` 汇总导出索引/交付包/队列 store；`archive_selection(index, zip, selection=[...])`
   输出所选结果与选择清单。

## 4. 兜底路径（与验收 A32-1/2/3/5 对应）

- 重复点击：同项目+变体+范围+格式的未完成项复用原 `jobId`（`reused=True`）；已完成项 `skipped=True`，不重复登记。
- 个别失败：三成员真实出稿中一项失败（不存在项目）仍保留另外两项可用产物与各自索引。
- 取消：`cancel()` 只改未完成项；执行中 `CancellationToken` 生效时**当前项跑完并保留结果**，其余项标 `cancelled`。
- 中断：启动时 `running/preparing` → `interrupted`，`resume()` 只处理未完成范围，已完成项 `attemptCount` 不变。
- store 损坏：坏文件隔离为 `*.corrupt`，队列仍可入队执行，已生成产物不受影响。
- Word 忙/不可用：该项转 `waiting-refresh`（可读 DOCX 保留），其它离线成员继续；`skip_word_refresh=True` 由调用方
  明确要求时同样只记"待刷新"，不冒充正式。
- 无 Word 换机：包保持 `waiting-refresh`、原包不删除、可读 DOCX 复制到目标目录；有 Word 时按包内快照补刷新。
- 登记幂等/失败：`packageId + 输入 digest + 目标位置` 命中已有记录直接返回（`already-registered`，不新增历史）；
  登记写入失败（测试注入 OSError）保留新 DOCX 到 `待登记/`，原 `delivery-registry.json` 内容逐字节不变。
- 源后来变化：只提示"本次按包内捕获快照（capturedAt）处理"，历史包不失效，且不改写当前项目正文/底模。
- 包损坏：坏 ZIP/非本应用包 → `invalid`；成员哈希不符 → 校验不通过并列出问题，不做半可信处理。

## 5. 验证命令与真实结果

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path; python scripts\tests\test_v32_batch_delivery.py
```

真实结果（2026-10-01 本机实测）：

| 次数 | 输出 | 退出码 |
|---|---|---|
| 1 | `Ran 22 tests in 56.107s` + `OK` | 0 |
| 2（干净捕获） | `Ran 22 tests in 42.213s` + `OK` | 0 |

未运行整套 `scripts/tests/run_tests.py`（按本批约定只跑本文件，避免与其他会话的并发改动互相影响）。

覆盖对照（22 个用例）：

- 32-B：`enqueue` 去重与已完成跳过、`requestId` 幂等、串行部分失败保留其它（替身）、真实出稿三成员一项失败
  （另两项产物/索引均在且可打开）、`cancel` 保留已完成、执行中取消保留当前项、新实例 `resume`、未知 `running`
  → `interrupted` 后继续、store 损坏隔离、只重试未完成项（`only_formats` + `prior` 复用原轮）、Word 忙转待刷新。
- 32-C：包内清单一律相对路径（无原机器绝对路径、无 `:` 盘符、无 `.git`/`__pycache__`/`logs`/`output`）、
  `reports/export-result.json` 的 `destination=.`/`snapshotWorkDir=snapshot`、hashes 校验通过、缺可读 DOCX 时拒绝打包。
- 32-D：ZIP 解压到新目录后 `formalize_package` 基于包内快照补格式（`waiting-refresh` + 可读 DOCX）、
  原包不删除、注册一次后重复处理为 `already-registered` 且登记条数不变、登记失败保留安全副本且旧记录不变、
  源改动后仅提示捕获快照、坏包/哈希不符被拒。
- 32-E：索引列出成员/变体/格式/状态/路径与来源种类（导出索引、交付包、批次队列）、整体状态 `partial` 不冒充
  `complete`、被删文件进入缺失清单、选择归档带 `partial/omitted/missing`、可从交付包 ZIP 内取结果归档。
## 6. 已实现并测过、但对应任务未勾选的能力（避免误判为"没做"）

| 能力 | 真实接口 | 未勾选原因 |
|---|---|---|
| 串行编排 + 逐项事件 + 取消 | `DeliveryQueue.run_pending(progress=…, cancel_token=…)` | 2.2 还要求复用 `TaskRunner`（GUI 层），本批未触碰 `ui/**` |
| Word 忙/不可用转待刷新、离线成员继续 | `DeliveryQueue(word_probe=…)` | 2.3 还要求"本应用跨进程 Word 占用标识"，未实现 |
| 中断继续 / 已完成跳过 / 只重试未完成项 | `resume`、`retry_unfinished`、`is_retryable` | 2.4 还要求"临时幂等故障最多自动一次"，未实现（常量 `AUTO_RETRY_LIMIT` 已留位，默认 0 次） |
| 快照收必要文件 + 排除 Git/凭据/缓存 | `build_delivery_package` | 3.2 还要求复用 V2.9 集合打包 API，改用本模块排除规则 |
| 交付包可读索引/报告、各格式状态独立 | `reports/export-result.json`（包内相对） | 3.3 已勾选 |
| 结果索引 + 选择归档（部分范围/缺失清单） | `build_result_index`、`archive_selection` | 5.3 还要求"完整集合登记复用 V2.9"，未实现；5.1/5.2/5.4 含 GUI 展示与打开动作 |

## 7. 未勾选与未验收项

- **2.2**：未复用 `TaskRunner`（GUI 任务区），本批不动 `ui/**`。
- **2.3**：未实现本应用**跨进程** Word 占用标识；串行化仅在单个队列进程内成立。
- **2.4**：未实现"临时幂等故障自动重试一次"；失败项需用户 `retry_unfinished`。
- **3.2**：未复用 V2.9 collection 打包 API（功能等价实现）。
- **3.4**：包版本不符时的"回退阅读/导出"路径未实现（当前对 schema/kind 不符直接判 `invalid`）。
- **3.5**：断网、同名文件冲突、旧状态包、非法附件等场景未逐一覆盖；已覆盖换目录/非法包/哈希不符/来源变化。
- **4.4**：严格模式未满足仍给参考产物在包正式化侧未单独测（队列侧 strict → `failed` 但保留可用结果仅由代码保证）。
- **4.5 真实 Word 用例**：本机 Word 可用（出稿轮 PDF 直接转换成功），但**正式化刷新用注入的 refresh adapter 替身**
  覆盖；真实 Word 补刷新/后校验/audit 需在有 Word 的实机补证（对应 7.3）。
- **32-E 全部（5.1-5.4）**：服务层（索引 + 归档）已实现并测过；GUI 任务区展示/打开包/补刷新入口属 `ui/**`，
  本批未做；5.3 的"完整集合登记复用 V2.9"未实现。
- **32-F（批次 CLI）**：按本批优先级未做（`cli.py` 属禁止修改范围）。
- 未验收：两台真实机器、真实 Word 刷新、10 成员批次实测（7.2/7.3）。

## 8. 环境事实与限制

- 本机 Python 3.13.13；Word 可用（PDF 在出稿轮内直接转换成功，故 `pendingStages` 实测为 `['docx-refresh']`；
  无 Word 分支由 `word_available=False` 与注入探测覆盖，不声称"本机无 Word 实测"）。
- 本工作区的文件系统**禁止硬链接**（harness 文件写入报 `EXDEV: cross-device link not permitted`，`edit` 报
  `ReplaceFileW EIO (Win32 1175)`），因此本次源码文件用 PowerShell + .NET `UTF8Encoding($false)`（无 BOM）写入；
  这不影响仓库内容，只影响工具选择。若后续会话仍需编辑这些文件，请优先用同样的写入方式或先确认文件系统限制消失。
- 未改动 `scripts/tests/run_tests.py`，本文件不会被整套测试自动收录（如需纳入需由负责任务的会话添加）。

## 9. 下一任务

1. 补 32-F：CLI `delivery run/status/retry/package/promote` 接同一编排与退出码契约（0/1/2）。
2. 补 32-E GUI：任务区显示批次成员/变体/格式/状态/路径，提供"只重试未完成/继续中断/打开包/补刷新"入口，
   复用本服务层接口（`machine_report()`、`unfinished_jobs()`、`retry_unfinished()`、`formalize_package()`）。
3. 补 2.3/2.4 差额：本应用跨进程 Word 占用标识、临时幂等故障自动重试一次（上限 1）。
4. 补 3.4/3.5/4.4：包版本不符回退、严格模式参考产物用例、断网/同名/旧包场景。
5. 实机验收：真实 Word 机 `formalize_package` 补刷新 + 后校验 + 登记，10 成员批次实测（7.2/7.3）。