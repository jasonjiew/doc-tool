# V3.1 团队查证、分工与交接：使用说明与限制

配套：[V3 总计划](product-plan-v3.0-v3.3.md)、[流程与兜底原则](product-flow-fallback-policy.md)、[执行台账](product-v31-execution.md)。本页只描述**已实现并测过**的能力；未实现项在文末单列。

## 1. 章节历史（31-A）

- 查看某章由哪次提交改动：`ChapterHistoryService.collect(章节相对路径)`（只读 Git，`--follow` 跟随重命名）。
- **没有 Git 时自动回退本地历史**（`LocalHistoryStore` 恢复点），并在结果中说明来源是本地记录，不假装有 Git 记录。
- 与当前缓冲比较：`compare_current(...)` 明确“缓冲有未保存修改 / 与历史版本不同”。
- 历史只保存**文本**：图片等资源不随历史保留（`images_unavailable_note()` 会说明）。
- 从历史恢复采用“当前新保存”语义，经既有 `ContentWriter` 走备份与原子写，不覆盖 Git 历史。

## 2. 负责人与我的待办（31-B）

- 团队配置是**可选**项目文件（`team.yml`：成员显示名），不要求账号或登录。
- 分配记录写在项目 `.state/assignments.json` 侧车文件中，**不改变**评审记录自身结构：旧记录仍可读，V2.8/V2.9 继续拥有“是否通过”的结论。
- 待办视图：未分配 / 我的待办 / 按来源筛选（`build_todo_board(...)`）。
- 坏配置或坏分配文件不会阻止启动或编辑：降级为“全部未分配”并给出提醒。

## 3. 离线内容交接（31-C）

- 导出：`export_handoff_package(项目, 输出目录, chapters=[...], baseline=..., texts=...)`
  - `baseline` 是**双方共同基准**（章节 → `sha256_text`）；缺失时包会被标记 `baselineState=unknown`，接收方不得被宣称“无冲突”。
  - 包内为所选正文 + 基准 + 资源（同名不同内容按内容 hash 区分，不直接替换）+ 清单（schema 1，相对路径）。
- 查看差异并应用：`plan_handoff_apply(包, 项目, content_root=..., project_id=...)` → `apply_handoff_plan(plan, project_root=..., content_root=...)`
  - 冲突章节**保留本地内容并跳过**，其余已选章节继续；
  - 同一包重复导入幂等（登记账本），异项目可导入为新副本；
  - 写入失败会回滚本轮写入，并保留可恢复信息。
- 删除项默认不应用（`include_deletions=False`）。
- 交接是**导出本地文件**，不自动发送、不推送远端。

## 4. 命令入口（31-D）

- 轻量注册表 `doc_tool/application/command_registry.py`：稳定 `commandId` + 别名 + 上下文条件 + 不可用原因 + 下一步动作。
- 菜单与命令面板由同一份 `menu_items()` / `palette_items()` 生成，**同 handler、同可用性**；未迁移的旧入口用 `append_legacy()` 保持可达，本版不重写 `main_window`。
- 最近命令只记录 ID 与时间（`~/.doctool/recent-commands.json`，schema 1）；缓存损坏会被隔离并回退到注册顺序。
- 已注册命令：`team.chapter-history`、`team.my-todos`、`team.assign`、`team.handoff-export`、`team.handoff-apply`、`team.report`。

## 5. 串联流程与结果页（31-E）

`run_team_flow(项目, chapters=[...], handoff_dir=..., baseline_texts=..., package=...)` 依次执行
历史查证 → 待办分配 → 交接导出 → 选择应用，并返回 `TeamResultPage`：
已处理 / 待处理 / 产物 / 跳过 / 冲突 / 提醒 / 下一步。

- 个别章节冲突、无 Git、缺少共同基准都**只记录不阻断**；
- 只有“没有任何可用结果且没有可继续动作”时才 `blocked=True`；
- 报告可 `to_dict()/to_json()`，供后续 V3.2 批次队列直接消费。

## 6. 已实现之外的限制与待验收

- 31-A：界面侧异步分页调度未接（`limit/offset/truncated` 已就绪）。
- 31-C：删除项应用（`include_deletions`）未接线；未复用 V2.9 集合打包 API（契约不同，仅沿用其“跳过并报告”原则）。
- V3.0 的模块来源/变体范围标记：待其读取接口暴露后由 `run_team_flow` 自动填入。
- **真实团队试点（6.3）**：本机无真实团队环境，单列待验收；自动化的两目录/无 Git 交接见下。
- 冻结包（PyInstaller）与实机 Word 检查属实机项，执行结果见第 7 节。

## 7. 版本源与冻结冒烟（6.4）

- 应用版本源按“当前最高版本”校正：**保持 2.9.0**（最近一次正式发布）。V3.1 未单独发布，
  **V3.1 发布号在同批正式发布时确定**，本版不改版本源、不写死发布号。
- 冻结冒烟：见 `docs/product-v30-v33-usage.md` 的“版本源与收尾现状”一节与
  `build_exe.ps1`（onedir 构建 + `scripts/tests/test_frozen_smoke.py`）。
- 已完成的自动化证据（替代部分手工试点）：
  - `test_v31_team_flow.py`：两目录两作者，含**无 Git 目录**（夹具在仓库外，实测 `git_root() is None`）、
    冲突章保留本地内容、其余应用成功、重复导入幂等；
  - `test_v31_team_workflow.py` 32 项 + `test_v31_command_registry.py` 13 项：历史/待办/交接/命令注册表；
  - 全量回归：`run_tests.py` 114 文件仅 1 项环境失败（mermaid 缺 `mmdc`）。
