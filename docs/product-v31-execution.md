# V3.1 团队协作服务层执行台账（批次 31-A / 31-B / 31-C）

执行日期：2026-10-01。入口：[V3.0～V3.3 产品方向与执行计划](product-plan-v3.0-v3.3.md) 第 4 节。
关联 change：`product-v31-team-workflow`。任务状态唯一源为
[openspec/changes/product-v31-team-workflow/tasks.md](../openspec/changes/product-v31-team-workflow/tasks.md)，
本台账只记录证据与遗留，不虚勾未完成项。

本轮实现**服务层 P0 能力**（A 章节历史、C 离线交接包），并顺带完成 B 的负责人/我的待办服务与测试；
D（渐进命令注册）与 E/F 未实现，保持未勾选。

## 批次状态

| 批次 | 已勾选/合计 | 状态 | 验证 |
|---|---|---|---|
| 31-A 章节历史 | 4/4 | 只读 Git 历史 + 重命名跟随 + 本地历史回退 + 缓冲比较 + ContentWriter 新保存恢复 | `test_v31_team_workflow.py` 8 项（含真实 Git 仓库夹具）通过 |
| 31-B 负责人/待办 | 4/4 | 可选 `team.yml` + 负责人叠加记录 + 未分配/我的待办筛选，复用 V2.8/V2.9 真实状态 | 同上 6 项通过 |
| 31-C 离线交接包 | 5/5 | ZIP 包 + 清单 schema 1 + 差异计划 + 选择应用 + 幂等 + 资源 hash + 回滚 + 异项目新副本 | 同上 13 项通过 |
| 31-D 命令注册 | 0/5 | **未实现**（时间不足，见遗留） | 无 |
| 31-E 协作整合 | 0/4 | 未实现（依赖 D 的注册表） | 无 |
| 31-F 试点收尾 | 0/5 | 未实现 | 无 |

合计 **13/46** 已勾选。未勾选项均为本轮未实现，不做虚勾。

## 新增/修改文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `doc_tool/application/content/chapter_history.py` | 新增 | 章节只读 Git/本地历史、历史正文、缓冲比较、恢复入口 |
| `doc_tool/application/content/assignments.py` | 新增 | 可选团队配置、负责人/说明叠加记录、待办聚合与筛选 |
| `doc_tool/application/content/handoff.py` | 新增 | 离线交接包导出/读取、应用计划、选择应用、幂等、回滚、异项目副本 |
| `scripts/tests/test_v31_team_workflow.py` | 新增 | 32 项 unittest（unittest 风格，夹具用 `core_fixtures.scratch_dir/cleanup`） |
| `docs/product-v31-execution.md` | 新增 | 本台账 |
| `openspec/changes/product-v31-team-workflow/tasks.md` | 修改 | 仅勾选本轮真正实现并测过的 13 项；未实现项保持 `- [ ]` |

未修改任何界面、重导入、其它文档或其它 change 的文件。

## 1. 复用与差额

工作树基准 HEAD `1cc28ca`（工作树含并发会话未提交改动，本轮不覆盖其文件）；当前应用版本 `2.9.0`。

| 环节 | 复用（未重建） | 本包补的差额 |
|---|---|---|
| Git 查询 | `content/vcs_changes.py` 的 `find_git_repo_root`、命令执行/解码惯例、`_GIT_TYPE_FROM_STATUS` 语义 | 章节级 `git log --follow` 列表 + 逐提交 `git show --name-status -z` 读取（`chapter_history.py`） |
| 本地历史 | `content/local_history.py` 的 `LocalHistoryStore`（`list_entries`/`preview`/`restore`）、`content/changes.py` 的 `render_unified_diff` | 章节历史门面的自动回退、统一 `ChapterCommit` 视图、缓冲比较事实 |
| 恢复写入 | `content/writer.py` 的 `ContentWriter`（未保存保护 + 写前恢复点 + 会话清单） | 只读历史 → 新保存的入口 `restore_local_version`（不改 Git 历史） |
| 评审/影响状态 | `review/versioned_review.py` 的 `legacy_status`、`review/review_store.py` 的 `ReviewStore`、`content/impact.py` 的 `ReviewRecordStore.pending()` | 负责人/说明的旁挂叠加记录（`.state/assignments.json`），**不新建审批状态** |
| 交接打包约定 | `export/review_package.py` 的 `schema`/`projectId`/`packageId`/`createdAt`/`contentHashes` 契约与异项目拒绝语义 | 内容交接包 `doc-tool-handoff/v1`：章节正文 + 基准/当前 hash + 资源 + 模块/来源索引 |
| 写盘安全 | `content/writer.py` 的 `atomic_write`/`atomic_write_bytes` | 交接应用的本次范围快照与回滚 |

差额明确不做的事：没有把 `vcs_changes`/`reimport_plan` 的基础动作重写成新产品成果；
没有复用 `collection_ops.export_package`（基线清单契约不同，仅沿用其“越界/缺失跳过并记录”的安全打包原则）。

## 2. 真实接口（本轮产物）

### chapter_history.py

- `ChapterHistoryService(project_root, content_root, state_dir=None, *, git_executable=None, timeout=20.0, runner=None, writable=True, local_history=None)`
- `collect(query_or_rel_path) -> ChapterHistory`（`source` 取 `git`/`local`/`current`，永不抛未捕获异常）
- `collect_git_history(rel, *, limit=50, offset=0) -> Optional[List[ChapterCommit]]`（`None` = 需要回退）
- `read_version(rel_path, version_id, source="git") -> HistoryVersion`（`available` + `note` 明示缺失范围）
- `compare_current(rel_path, version_id, buffer_text=None, source="git") -> BufferComparison`
- `snapshot_current(rel, *, operation="manual")`、`restore_local_version(rel, snapshot_id, writer, *, confirmed=False, expected_sha256=None)`
- `parse_git_log_z(bytes) -> List[dict]`（纯函数，逐提交解析 `--name-status -z`）
- 数据类：`ChapterCommit`（含 `content_path` / `was_renamed`）、`HistoryVersion`（含 `images_unavailable_note`）、`ChapterHistory`、`BufferComparison`

### assignments.py

- `load_team_config(project_root, *, path=None) -> TeamConfig`（坏/缺 `team.yml` 归未分配 + `error` 说明）
- `AssignmentStore(state_dir)`：`assign(item_id, assignee, *, source="", note=None, by="")`、`get`、`records`、`clear`（只读 `writable=False` 抛 `PermissionError`）
- `build_todo_board(*, review_store=None, relation_store=None, impact_report=None, assignments=None, team=None) -> TodoBoard`
- `todos_for(board, assignee=None, *, source=None, include_unassigned=False)`、`assign_todo(...)`、`render_todo_board(board, *, limit=50)`
- 叠加记录文件：项目 `.state/assignments.json`（schemaVersion 1）；待办标识：`comment:<id>` / `relation:<id>` / `impact:<n>`

### handoff.py

- `export_handoff_package(project_root, destination, *, chapters, content_root=None, asset_roots=(), project_id="", project_name="", document_version="", baseline=None, baseline_id="", baseline_state=None, created_by="", texts=None, package_name="内容交接包.zip", comments=(), modules=(), source_index=()) -> HandoffPackage`
- `read_handoff_manifest(package_path) -> HandoffPackage`（坏 ZIP/缺清单/契约不匹配 → `warnings`，不抛）
- `read_handoff_entry` / `handoff_entry_text`
- `plan_handoff_apply(package_path, project_root, *, content_root=None, asset_roots=(), project_id="", selected=None, include_deletions=False, state_dir=None, buffer_texts=None, local_modules=None) -> HandoffApplyPlan`（纯只读）
- `apply_handoff_plan(plan, *, project_root=None, content_root=None, asset_roots=(), writer=None, writer_factory=None, state_dir=None) -> HandoffApplyResult`
- `import_handoff_as_new_copy(package_path, destination_root, *, selected=None, include_resources=True) -> dict`
- `HandoffApplyState(state_dir)`：`.state/handoff_applied.json`（`packageId` + `entryId` + `incomingHash` 幂等账本）
- 包契约：`doc-tool-handoff/v1`，清单 `handoff-manifest.json`（schemaVersion 1），章节正文 `content/<rel>`、资源 `resources/<name>`

## 3. 正常路径与兜底

| 场景 | 正常路径 | 兜底（已验证） |
|---|---|---|
| 章节历史 | Git 可用：`git log --follow --diff-filter=ACMR` 列提交 + 逐提交 `git show --name-status -z` 取该提交时点路径与正文 | 不在仓库/未跟踪/浅克隆/命令失败 → 自动回退 `LocalHistoryStore`，并在 `note`/`warnings` 说明；两者都无 → 返回当前磁盘内容 + 来源说明 |
| 历史恢复 | 经 `ContentWriter.write_text` 走未保存保护 + 写前恢复点 + 会话清单，成为一次新保存 | 只读项目 → `PermissionError`；正文已变化 → `expected_sha256` 校验失败并提示刷新 |
| 负责人 | `team.yml` schema 1 读取展示名与当前身份，负责人写在 `.state` 叠加记录 | 缺/坏 `team.yml`、坏 `assignments.json` → 全部归“未分配” + `warnings`，编辑与出稿不受影响 |
| 交接导出 | 有基准：清单写 `baseHash` + `hash`，`baselineState=known` | 无基准：`baselineState=unknown` + `NO_BASELINE_NOTICE`，**不宣称无冲突**；资源读不到/越界 → 记 `warnings` 跳过，其余内容仍可读 |
| 交接应用 | 本地 == 基准 → 直接应用；本地缺失且无基准 → 新增 | 本地 ≠ 基准（含未保存缓冲）→ 冲突，保留本地、列为待处理，其余合法项继续；未选中 → `REASON_DESELECTED`；显式空选择 → 一项都不应用 |
| 幂等 | 已记录且本地未再改 → `already-applied`，不重复写 | 应用后本地又改过 → 重新比较并按冲突跳过，**不强行恢复旧状态** |
| 资源同名 | 本地缺同名 → 写 `resources/<name>` | 同名不同内容 → 写 `shared.handoff.png` 兄弟副本并在 `renamed_resources` 报告，**绝不原地替换** |
| 写失败 | 全部成功 → `success=True` | 任一项写入失败 → 回滚本次已写范围（含已写资源），`rolledBack=True`，返回原因 |
| 异项目包 | 同项目 → 正常计划 | 异项目 → `same_project=False`，`apply` 拒绝，改走 `import_handoff_as_new_copy` 写入新目录，原项目不动 |
| 固定模块 | 包内模块快照元数据随包携带 | 接收方缺模块 → `module_missing` + 说明（不改其他引用）；版本/hash 不同 → `module_conflicts` 候选，不替换本地模块 |

## 4. 验证命令与真实结果

```text
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path
python scripts\tests\test_v31_team_workflow.py
```

真实输出（2026-10-01，Windows / Python 3.13.13 / Git 2.45.1.windows.1）：

```text
Ran 32 tests in 51.372s

OK
```

退出码 `0`。测试类与覆盖：

- `ChapterHistoryFallbackTests`（7 项）：无 Git 回退本地历史、本地恢复点新保存、坏恢复点回退且有说明、Git 失败回退、无历史只给当前内容、非法路径、缓冲比较事实、历史缺图说明、不可获取提交有说明。
- `ChapterHistoryGitTests`（3 项）：真实小仓库（两次提交 + 一次重命名）历史与重命名跟随、历史正文本读取与缓冲比较、`--name-status -z` 逐提交解析。
- `AssignmentTests`（6 项）：分配/更换/未分配分组、只读拒改、关系待办只列未通过项、分配不替代复核状态（真实 `confirm_comment` 才结束待办）、缺/坏配置回退、坏叠加记录回退。
- `HandoffTests`（14 项）：包与清单 schema 1、无基准明确说明、离线跨目录可读且发送方不被修改、部分冲突跳过其余应用、二次导入幂等 + 后续修改不覆盖、坏幂等账本仍可应用、异项目新副本、同名资源不替换、缺资源跳过、显式取消不写入、固定模块缺失/冲突报告、写失败回滚本次范围、坏包不抛异常。

Git 相关测试在本机有 Git 时建临时仓库（夹具目录内 `git init` + 两次提交 + `git mv` 重命名）；
若本机无 Git，这些测试会断言兜底路径可用后 `skipTest`，不会静默通过。

## 5. 未验收项与遗留

1. **31-D 渐进命令注册（4.1～4.5）全部未实现**：本轮未定义 `commandId`/别名/上下文/可用原因/handler，也未接菜单与命令面板；D 是 P1 且时间不足。
2. **31-E 日常协作整合（5.1～5.4）未实现**：历史→待办→交接→应用→复核的串联入口与结果页未做；服务层接口已具备（可被后续界面/队列直接调用）。
3. **31-F 试点与收尾（6.1～6.5）未实现**：未跑全量回归、未做两目录两作者模拟、未更新使用说明、未做 OpenSpec 严格校验与归档。
4. **31-C 差额**：未复用 `collection_ops` 的安全打包实现（契约不同，只沿用其原则）；未做删除项默认未选之外的软删除实测（`include_deletions` 参数已留，删除应用未接线）。
5. **31-A 差额**：未做真正的异步分页调度（`limit`/`offset` 与 `truncated` 已就绪，界面侧异步加载未接）；`git log --follow` 在重命名提交处按 git 语义不计为新正文版本（已用 `--diff-filter=ACMR` 固定语义并在测试中断言）。
6. **环境限制（非代码缺陷）**：本机文件过滤层拒绝 `os.replace` 跨设备移动，`content/impact.py` 的 `ReviewRecordStore.save()`（使用裸 `os.replace`）在夹具目录会抛 `WinError 17`。该文件不在本轮允许修改范围，因此相关测试改为直接写台账 JSON 再用存储读取，交接/历史/负责人三条链路的写盘都走 `atomic_write`（含 `shutil.move` 回退）不受影响。`AssignmentStore.save()` 已额外捕获该错误并降级为会话内可用 + `warnings`。

## 6. 下一任务

1. 实现 31-D 命令注册服务（实施落地为 `doc_tool/application/command_registry.py`：稳定 `commandId`、别名、上下文、可用原因、handler、最近命令只记 ID/时间、坏缓存默认排序），只迁移本版历史/待办/交接入口，不全量重写 `main_window`（tasks 4.1→4.5）。
2. 接 31-E：把历史查证、待办分配、交接导出、选择应用串成一条结果页流程，结果页列已处理/待处理/产物（tasks 5.1→5.4）。
3. 接 31-F：注册新测试到直接套件、跑全量回归与 OpenSpec 严格校验、更新使用说明并归档（tasks 6.1→6.5）。
4. 补齐 31-C 删除项应用接线（`include_deletions` 软删除实测）与 31-A 异步分页调度。

## 续：31-D 命令注册与 5.3 服务级报告（父会话本轮实施）

```text
日期 / 执行HEAD / 工作树基准：2026-10-01 / 1cc28ca + 并发会话未提交改动
批次 / 完成编号：31-D 4.1-4.5；31-E 5.3（5.1/5.2/5.4 未做）
复用与差额：复用 chapter_history/assignments/handoff 三个服务与既有评审/影响数据；
  新增轻量注册表与入口适配，未重写 main_window，未重建意见生命周期
真实接口：ChapterHistoryService.collect/git_root、AssignmentStore+build_todo_board、
  export_handoff_package / plan_handoff_apply / apply_handoff_plan
用户可用行为 / 产物：菜单与命令面板同 handler 同可用性；team.report 产出 schema 1 JSON；
  交接包真实写入指定目录并回报实际产物路径（既有服务把 destination 当目录，已在入口适配）
正常与兜底：无 Git → 历史走本地兜底并在条目中说明；未迁移旧入口保持可达；
  坏最近命令缓存隔离后按注册顺序；命令异常包装为结果（不崩界面）
验证命令 / 退出码：
  python scripts\tests\test_v31_command_registry.py  -> Ran 13 tests OK (exit 0)
  python scripts\tests\test_v31_team_workflow.py     -> Ran 32 tests OK (exit 0)
  python scripts\tests\test_command_palette.py       -> Ran 4 tests OK (exit 0)
未验收环境 / 遗留：31-E 5.1/5.2/5.4（串联流程与结果页、GUI 离屏双副本）与 31-F 收尾；
  V3.0 相关入口接入同一注册表（待其 CLI/面板落地）
下一批 / 下一任务：31-E / 5.1
```

## 续二：31-E 串联流程与结果页（父会话本轮实施）

```text
批次 / 完成编号：31-E 5.1 / 5.2 / 5.4（6.1-6.5 待做）
新增能力：`content/team_flow.py` 串起 历史查证 → 待办分配 → 交接导出 → 选择应用，
  并给出结果页模型（已处理/待处理/产物/跳过/冲突/提醒）；仅当无任何可用结果且
  无可继续动作时才 blocked
真实接口：export_handoff_package(含 baseline/texts/content_root/project_id) /
  plan_handoff_apply / apply_handoff_plan（按对象属性读取 applicable/applied/skipped/conflicts）
两目录两作者实测：作者改两章并带共同基准导出 → 接收方本地改过的一章判冲突并保留
  本地内容，另一章应用成功；结果页同时列出“已应用/跳过/冲突”
无 Git 兜底：历史走本地恢复点；无共同基准时交接包标为“无基准”，结果页提示需人工确认
验证命令 / 退出码：
  python scripts\tests\test_v31_team_flow.py        -> Ran 5 tests OK (exit 0)
  python scripts\tests\test_v31_command_registry.py -> Ran 13 tests OK (exit 0)
  python scripts\tests\test_v31_team_workflow.py    -> Ran 32 tests OK (exit 0)
未验收：6.1 全量回归记录、6.2 无 Git 目录双副本模拟、6.3 真实团队试点、
  6.4 使用说明/版本源/冻结冒烟、6.5 同步归档
下一批 / 下一任务：31-F / 6.1
```

## 续三：6.2 无 Git 目录两作者交接（父会话本轮实施）

```text
场景：夹具建在系统临时目录（仓库之外），先断言 ChapterHistoryService.git_root() is None
  ① 作者改两章 + 共同基准导出交接包（结果页说明“无 Git：使用本地历史”）
  ② 接收方本地改过第一章 → 应用：第一章判冲突并保留本地内容，第二章应用成功
  ③ 重复应用同一包：内容不变、不重复写（幂等）
验证：python scripts\tests\test_v31_team_flow.py -> Ran 6 tests OK (exit 0)
遗留：6.1 全量回归/A31-1～6 逐条留证、6.3 真实团队试点、6.4 版本源/冻结、6.5 同步归档
```

## A31-1～6 场景留证（父会话第四轮，直接套件 + 全量回归）

| 场景 | 证据（真实运行） | 结果 |
|---|---|---|
| A31-1 Git 记录可查可比较 / 无 Git 回退 | `test_v31_team_workflow.py`（真实 Git 仓库重命名跟随、历史文本、无 Git 本地历史、坏恢复点、缓冲比较） | 通过 |
| A31-2 负责人/待办与坏配置 | 同套件（分配/更换/未分配、读取只读拒绝、分配不替代复核状态、坏 team/assignment 配置降级） | 通过 |
| A31-3 交接包与部分应用 | `test_v31_team_flow.py`（两目录两作者：冲突章保留、其余应用成功；资源同名不同内容不替代见 31-C 套件） | 通过 |
| A31-4 幂等与恢复 | 同套件（重复导入内容不变、不重复写）；`test_v31_team_workflow.py`（写失败回滚、坏包不抛） | 通过 |
| A31-5 双入口同状态与旧入口可达 | `test_v31_command_registry.py`（菜单/面板同 handler 同可用性、稳定 ID、最近命令、坏缓存回退、legacy 可达） | 通过 |
| A31-6 无 Git/坏配置/缺资源完整流程 | `test_v31_team_flow.py` 无 Git 组（夹具在仓库之外，实测 `git_root() is None`）+ 无共同基准提示 | 通过 |

全量回归同上（1 项环境失败）；真实团队试点（6.3）与版本源/冻结（6.4）仍单列待验收。

## 续四：6.4 使用说明/版本源与冻结冒烟（父会话第十轮）

```text
文档：`docs/product-v31-usage.md` 第 6 节限制刷新（无 Git 模拟与全量回归已完成、真实团队试点单列）
  + 第 7 节版本源与冻结冒烟；台账同步。
版本源：保持 2.9.0（V3.1 未单独发布，发布号同批发布时确定）。
冻结冒烟（真实执行）：
  powershell.exe -ExecutionPolicy Bypass -File .\build_exe.ps1
  → dist\DocTool\DocTool.exe 9,921,440 B；doc-tool-cli.exe 9,123,016 B
  → 产物内容校验通过；代码签名 46 个文件
  → scripts\tests\test_frozen_smoke.py：Ran 11 tests OK（exit 0）
  → 冻结 CLI：--version（appVersion 2.9.0 / python 3.13.13）与 --help 均 exit 0
OpenSpec：openspec validate product-v31-team-workflow --strict → valid
遗留：6.3 真实团队试点（无团队环境）、6.5 同步/归档（待全部验收）。
```

## 续五：6.3 真实文档代理试点（父会话第十三轮）

```text
命令：python scripts\tests\test_v31_real_document_handoff.py（输出 HANDOFF_JSON）
场景：用**两篇真实文档正文**（兜底策略、V3.1 使用指南）作为两章内容；作者/评审人各一棵
  独立目录树（系统临时目录，仓库之外 → 天然无 Git，实测 git_root() is None）。
实测：交接包导出 0.174 s；应用 0.140 s；重复应用 0.073 s
  处理结果：待办清点 0 项 + 已应用 chapter:第2章；冲突 chapter:第1章（评审人本地批注保留）
  评审人侧第一章保留本地内容，第二章应用作者内容；重复导入不重复写（内容不变）。
结论：真实文档在两棵独立工作副本间的交接链路可用、冲突按章隔离、重复导入幂等。
未执行（6.3 保持未勾选）：真实团队（多人、真实沟通与评审意见）试点与人工确认。
```

## 续六：4.2 命令注册表接入应用（父会话第十五轮）

```text
问题（第十四轮审计）：`register_team_commands` 仅库级可用；`main_window.py` 从不实例化
  `CommandRegistry`，命令面板是硬编码列表，且 `menu_items()`/`palette_items()` 是同一函数
  → “菜单与面板同 handler 同可用性”的等价性断言实为空转。

修复：
  - 注册表两个视图分离：`menu_items()` 只给**当前可用的正式入口**（不含旧入口/不可用项），
    `palette_items()` 给**全部命令**（含旧入口与不可用项，带 reason/nextAction/keywords/searchText/paletteOnly）；
    行数据新增 `legacy` 标记。
  - `MainWindow`：新增 `_command_context()`（项目/可写/空闲/选区/缓冲）、`_ensure_command_registry()`
    （按项目根构建并注册团队命令，项目切换自动重建）、`_registry_palette_items()`（面板条目，
    点击统一走 `registry.handle_item`）、`_build_registry_menu()`/`_refresh_registry_menu()`（「命令」菜单，
    分类子菜单；子菜单显式指定父对象以规避 PySide6 所有权陷阱）。
  - 旧等价性断言改为有意义的不变式：菜单 ⊆ 面板、逐条可用性/原因一致、面板含旧入口与原因。
验证：
  test_v31_command_registry.py -> Ran 13 tests OK（含改写后的双入口不变式）
  test_v31_registry_integration.py -> Ran 4 tests OK（窗口构建注册表、面板经注册表派发、
    只读时不可用项只在面板显示原因、「命令」菜单已填充）
  回归：test_gui_services 170 项仅 1 项环境失败（mermaid）、test_command_palette 4 OK、
        test_v33_registry 5 OK、test_v33_editor_wiring 4 OK、test_core_entries_ui 7 OK
```

## 续四：串联流程真正接入（父会话第二十七轮）

```text
问题（规范覆盖审计）：`run_team_flow`/`TeamResultPage` 只有测试引用，CLI 与界面都没有入口，
  PyInstaller 因此把 `team_flow` 排除在冻结包外——已勾选的 5.1“串联流程”实际不可达；
  同时 `team.chapter-history`/`team.my-todos` 的 handler 结果被 GUI 回调直接丢弃，
  “与未保存缓冲比较”也从未在生产路径传入缓冲。

修复：
  - 命令注册表新增 `team.flow`（协作类，菜单与命令面板可达），handler 调用 `run_team_flow`
    并返回结果页 + summary + blocked；
  - CLI 新增 `team-flow`（--project/--chapters/--handoff/--package/--apply/--assignee/--json），
    退出码 0（有结果/已完成）、1（blocked）、2（参数或环境错误）；
  - `_make_registry_callback` 展示命令结果（摘要 + JSON 详情），并按命令补齐参数：
    章节历史带编辑器缓冲、交接导出选目录、交接应用选包；
  - `team.chapter-history` 取最新可得提交调用 `compare_current(..., buffer_text=…)`，
    返回 `bufferCompared`/`bufferComparison`。

验证：scripts/tests/test_v31_flow_entry.py 4 项 OK、test_v31_registry_display.py 3 项 OK
  （CLI 导出交接包 exit 0 且产物存在；参数错误 exit 2；注册表与窗口面板都含 team.flow；
   待办结果展示而非丢弃；交接应用经选包后展示计划；历史命令携带缓冲）
命令结果展示为**非阻塞**对话框 + 状态栏摘要（模态框会把离屏/无人值守界面卡住，
  实测曾使 test_v31_registry_integration 长时间阻塞，改后 3.7 s 通过）。
冻结复核：重建后 `team_flow` 出现在冻结产物中；`doc-tool-cli.exe team-flow … --json` exit 0，
  processed 含“待办清点：待处理 0 项”“交接包已导出：内容交接包.zip”。
遗留（如实保留）：CORE R5/R9/E8 与 V3.3 导出建议入口（见审计发现 §7）。
```
