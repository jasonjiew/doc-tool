## 目标

改动面板补齐版本控制「提交」与「拉取」（git > svn），与既有检测/回滚共享
Project Context 隔离原则：提交范围 = 报告内变更文件（已排除 `.state/` 等
应用内部目录与其它项目），拉取为仓库级操作。

## 决策

### D1 提交范围用文件 pathspec

- 报告 `ChangeReport.files` 已按 `project_root` 过滤并经 `_PROJECT_INTERNAL_DIRS`
  排除 `.state` / `output` / `logs`。提交直接以这些文件为 pathspec：
  - git：`git add -A -- <paths>` + `git commit -m <msg> -- <paths>`；
  - svn：逐文件 `svn add`（未版本化）/ `svn rm`（删除）后
    `svn commit -m <msg> -- <paths>`。
- 重命名条目同时携带 `old_path`，加入 paths 集合保证旧路径的删除一并提交。
- 反例（否决）：项目目录 pathspec（如 `proj_a`）会把 `.state/` 等内部状态
  一并提交，污染版本历史。

### D2 失败即中止，错误可见

- `svn add` / `svn rm` 任一步失败即中止，不继续 commit（避免半提交状态）。
- 单条命令失败返回非零时，捕获 stderr（截断 300 字符）拼入失败列表，
  由面板状态行展示；空列表 = 全部成功。

### D3 空提交信息与空改动

- 提交信息去空白后为空 → 返回 `提交信息不能为空`，不执行任何命令。
- 报告无文件 → 返回 `当前项目没有可提交的改动`。

### D4 拉取语义与反馈

- git：`git pull`；svn：`svn update`；均在仓库根（repository_root）执行，
  120s 超时。完成后工作区失效缓存并重建索引/树/徽标。
- 面板确认框提示先保存所有打开的编辑内容；执行期间显示等待光标。
- 返回 `PullResult(ok, summary, changed_files, conflicts, error)`：
  - git 统计：拉取前 `git rev-parse HEAD` 记基线，成功后对比新 HEAD，
    `git diff --name-only <旧> <新>` 得到带入文件；冲突（pull 非零退出）时
    `git ls-files -u` 列出未合并路径。
  - svn 统计：解析 `svn update` 输出——`U/A/D/G/E` 计为变更、`C` 计为冲突；
    提取 "Updated to revision N." 附到摘要。
  - 无带入文件 → 摘要「已是最新版本」。
- 面板反馈：成功 → 状态行「拉取完成：更新了 N 个文件」；冲突 → 弹窗列出
  冲突文件（git 冲突视为失败，svn 冲突视为完成但有冲突）；失败 → 状态行
  展示 `git pull 失败：<输出>` / `svn update 失败：<输出>`。

### D5 UI 接线

- `ChangesPanel` 新增 `on_commit(message)` / `on_pull()` 回调参数（可空）。
- 「提交改动」「拉取更新」按钮仅在 `writable` 且检测来源为 git/svn 时启用；
  tooltip 随来源标注真实命令（git add/commit、svn add/rm/commit、git pull、
  svn update）。
- `ContentWorkspace` 提供 `_commit_all_changes(message)` / `_pull_changes()`，
  成功后清空会话改动清单（提交已入库）并失效仓库缓存；刷新由面板经
  `on_restored` 触发。

## 数据结构

- 无新增持久化结构；复用 `ChangeReport` / `ChangedFile`。
- 新增纯函数：

```
commit_all(report, message, *, timeout=60, runner=None) -> List[str]
pull_changes(report, *, timeout=120, runner=None) -> PullResult
```

`runner` 供测试注入假 subprocess（与 `rollback_all` 同模式）。

`PullResult` 字段：`ok`（是否成功；git 冲突为失败，svn 冲突不算失败）、
`summary`（摘要文本）、`changed_files`（带入文件，相对仓库根）、
`conflicts`（冲突文件）、`error`（失败原因，含命令输出）。

## 错误码 / 文案

- `当前项目不在版本控制内，无法提交` / `无法拉取`（source=local）
- `提交信息不能为空`
- `当前项目没有可提交的改动`
- `git add 失败：<stderr>` / `git commit 失败：<stderr>`
- `svn add 失败（<path>）：<stderr>` / `svn rm 失败（<path>）：<stderr>`
- `svn commit 失败：<stderr>`
- `git pull 失败：<输出>` / `svn update 失败：<输出>`
- `Git 仓库根不可用` / `SVN 工作副本根不可用` / `<verb>：仓库根不可用`
- 冲突反馈：`git ls-files -u` / svn 输出 `C` 行提取冲突文件清单
