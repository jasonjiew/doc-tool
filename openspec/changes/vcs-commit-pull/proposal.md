## Why

改动面板已完成 Git/SVN 变更检测（git > svn）与「回滚全部」（git restore / svn revert），
但只解决了「看得到、撤得回」，没有解决「交得出、拿得到」：用户仍须离开工具手工
执行 `git add` / `git commit` / `git pull` / `svn update`。对 QMS 文档维护场景，
提交与拉取是高频操作，且手工执行容易把同仓库其它文档项目的改动或应用状态
（`.state/`）一并提交。本变更在现有 Project Context 隔离原则下补齐提交与拉取。

## What Changes

- **提交改动**：改动面板新增「提交改动」按钮（仅 Git/SVN 项目启用）。弹窗收集提交
  信息后执行版本控制提交，git > svn：
  - git：`git add -A -- <变更文件…>` 后 `git commit -m <信息> -- <变更文件…>`，
    范围 = 报告内变更文件（含重命名旧路径），不波及同仓库其它项目，不提交 `.state/`。
  - svn：未版本化新增先 `svn add --parents --force`、删除先 `svn rm --force`，
    再 `svn commit -m <信息> -- <变更文件…>`。
  - 提交成功后清空会话改动清单并失效仓库缓存。
- **拉取更新**：改动面板新增「拉取更新」按钮（仅 Git/SVN 项目启用）。确认后执行
  `git pull`（git）或 `svn update`（svn），随后刷新本地索引与徽标。
- **拉取反馈**：拉取返回结构化结果 `PullResult`——成功摘要（更新了 N 个文件 /
  已是最新版本）、带入文件清单、冲突文件清单与失败原因；面板在状态行展示摘要，
  冲突时弹窗列出冲突文件提示手工解决，失败时展示命令错误文本。

## Capabilities

### New Capabilities

- `vcs-commit`: 定义版本控制提交语义——git add+commit / svn add+rm+commit，
  提交范围严格限定为报告内变更文件（Project Context 隔离、排除 `.state/` 等
  应用内部目录），空提交信息或无可提交改动时给出明确错误。
- `vcs-pull`: 定义版本控制拉取语义——git pull / svn update，仓库级操作，
  完成后刷新工作区状态；本地（无版本控制）项目拒绝执行并给出说明。

### Modified Capabilities

`content-changes-panel`：改动面板新增「提交改动」「拉取更新」入口与状态反馈；
「回滚全部会话改动」行为不变。

## Impact

- **代码**：`doc_tool/application/content/vcs_changes.py`（新增 `commit_all` /
  `pull_changes` 及 git/svn 私有实现与通用命令执行助手）；
  `doc_tool/ui/content/changes_panel.py`（按钮、弹窗、回调接线）；
  `doc_tool/ui/content/workspace.py`（`_commit_all_changes` / `_pull_changes`）。
- **测试**：`scripts/tests/test_vcs_changes.py` 新增 `VcsCommitPullTests`
  （git 提交含项目隔离与 untracked/删除、svn 注入命令序列、拉取注入与真实 git pull、
  本地拒绝）；`scripts/tests/test_multi_window.py` 新增工作区级提交测试
  （含 `.state/` 不入提交与跨项目隔离）。
- **兼容性**：无破坏性变更；本地快照项目按钮禁用，检测/回滚/恢复语义不变。

## Decisions

- **提交范围用文件 pathspec 而非项目目录**：项目目录 pathspec 会把 `.state/`、
  `output/` 等应用内部目录一并提交；报告已按 `_PROJECT_INTERNAL_DIRS` 排除它们，
  提交沿用同一过滤结果，范围与面板展示完全一致。
- **拉取是仓库级操作**：`git pull` / `svn update` 无路径级语义，更新整个工作副本；
  面板在确认框提示先保存所有打开的编辑内容。
- **不实现 push**：本次只做「拉取和提交」（git > svn），push/分支/冲突合并属
  roadmap P2-A 后续项。
