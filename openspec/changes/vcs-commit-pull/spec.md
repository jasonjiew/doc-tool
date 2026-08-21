# 版本控制提交与拉取（改动面板）

## 概述

改动面板在既有 Git/SVN 变更检测（git > svn）与「回滚全部」基础上，新增
「提交改动」与「拉取更新」。提交范围严格限定为报告内变更文件（Project
Context 隔离，排除 `.state/` 等应用内部目录）；拉取为仓库级操作。

## 需求

- R1 面板在 Git/SVN 项目提供「提交改动」：收集提交信息，执行版本控制提交
  （git add + commit / svn add + rm + commit），范围 = 报告内变更文件。
- R2 面板在 Git/SVN 项目提供「拉取更新」：执行 git pull / svn update，
  完成后刷新工作区状态。
- R3 本地（无版本控制）项目两个入口禁用，应用层返回明确说明。
- R4 提交信息为空、无可提交改动、命令失败时给出明确错误，不产生半提交。
- R5 提交成功后清空会话改动清单并失效仓库缓存，刷新后显示干净状态。
- R6 git > svn 优先级与既有检测一致。

## 行为契约

### commit_all(report, message) -> List[str]

- source=git：
  1. repository_root 缺失或不可用 → `Git 仓库根不可用`。
  2. message 去空白为空 → `提交信息不能为空`。
  3. 变更文件集合为空 → `当前项目没有可提交的改动`。
  4. 执行 `git add -A -- <paths>`；失败 → `git add 失败：<stderr>`，中止。
  5. 执行 `git commit -m <message> -- <paths>`；失败 → `git commit 失败：<stderr>`。
- source=svn：
  1. repository_root 缺失或不可用 → `SVN 工作副本根不可用`。
  2. message 去空白为空 → `提交信息不能为空`。
  3. 对未版本化文件 `svn add --parents --force <path>`，对删除文件
     `svn rm --force <path>`；任一步失败 → `svn add 失败（<path>）：<stderr>`
     或 `svn rm 失败（<path>）：<stderr>`，中止不 commit。
  4. 执行 `svn commit -m <message> -- <paths>`；失败 → `svn commit 失败：<stderr>`。
- source=local → `当前项目不在版本控制内，无法提交`。

返回空列表表示全部成功。

### pull_changes(report) -> PullResult

- source=git：`git pull`（120s 超时）；source=svn：`svn update`。
- 仓库根缺失 → `ok=False`，`error=<verb>：仓库根不可用`。
- git 成功：对比拉取前后 HEAD，`changed_files` 为带入文件，摘要
  「更新了 N 个文件」或「已是最新版本」；冲突（pull 非零）→ `ok=False`、
  `conflicts` 为未合并路径、`error` 含 git 输出。
- svn 成功：解析输出，`U/A/D/G/E` → `changed_files`、`C` → `conflicts`，
  摘要含数量与 revision；命令失败 → `ok=False`、`error=<verb> 失败：<输出>`。
- source=local → `ok=False`，`error=当前项目不在版本控制内，无法拉取`。

## 验收标准

- [x] 应用层测试（`scripts/tests/test_vcs_changes.py::VcsCommitPullTests`）：
  git 提交（含新增/修改/删除/重命名、项目隔离、空信息、命令失败、仓库根缺失）、
  svn 提交（注入命令序列、add 失败中止、空信息）、拉取（注入命令、真实 git pull、
  失败文案、本地拒绝、git 带入文件统计、git 冲突未合并路径、svn 变更/冲突解析、
  svn 失败）全部通过。
- [x] 工作区级测试（`scripts/tests/test_multi_window.py`）：提交后仓库干净且
  `.state/` 不入提交；两项目提交隔离；本地项目拒绝提交。
- [x] 面板测试（`scripts/tests/test_gui_services.py::ChangesPanelTests`）不受影响。
- [x] 全量默认测试套件（`scripts/tests/run_tests.py`）通过。
