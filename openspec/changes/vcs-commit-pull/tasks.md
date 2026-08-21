## 1. 应用层：提交与拉取（纯逻辑，先测）

- [x] 1.1 `doc_tool/application/content/vcs_changes.py` 新增通用命令助手
      `_run_vcs_command(command, cwd, timeout, runner) -> Optional[str]`
- [x] 1.2 新增 `_git_commit_all`：paths 从报告文件推导（含重命名 old_path），
      `git add -A -- <paths>` + `git commit -m <msg> -- <paths>`
- [x] 1.3 新增 `_svn_commit_all`：未版本化 `svn add --parents --force`、
      删除 `svn rm --force`，任一步失败中止，再 `svn commit -m <msg> -- <paths>`
- [x] 1.4 新增公开 `commit_all(report, message, *, timeout, runner)`，
      本地报告返回 `当前项目不在版本控制内，无法提交`
- [x] 1.5 新增公开 `pull_changes(report, *, timeout, runner) -> PullResult`：
      git pull / svn update，本地返回 `ok=False`
- [x] 1.6 空 repository_root / 空提交信息 / 空改动文件的防御返回
- [x] 1.7 拉取反馈：`PullResult(ok, summary, changed_files, conflicts, error)`；
      git 对比前后 HEAD 统计带入文件、`git ls-files -u` 提取未合并路径；
      svn 解析 U/A/D/G/E 变更与 C 冲突并提取 revision

## 2. 面板与工作区接线

- [x] 2.1 `changes_panel.py`：构造函数新增 `on_commit(message)` / `on_pull()`
- [x] 2.2 顶部行新增「提交改动」（弹窗收集提交信息）与「拉取更新」（确认框），
      仅 writable 且 git/svn 启用，tooltip 标注真实命令
- [x] 2.3 `workspace.py` 新增 `_commit_all_changes(message)`（成功后清空会话
      改动清单并失效缓存）与 `_pull_changes() -> PullResult`（失效缓存），接线到面板
- [x] 2.4 拉取反馈：状态行展示摘要（更新了 N 个文件 / 已是最新版本）；
      冲突弹窗列出冲突文件；失败展示命令错误；执行期间等待光标

## 3. 自动化测试

- [x] 3.1 `test_vcs_changes.py::VcsCommitPullTests`：git 提交三态（改/增/删）、
      双项目隔离、空信息、命令失败、仓库根缺失
- [x] 3.2 同上：svn 提交注入命令序列断言（add/rm/commit）、add 失败中止、
      空信息；本地报告拒绝提交与拉取
- [x] 3.3 同上：拉取注入命令断言、真实 git pull 更新工作树、失败文案、
      git 带入文件统计（前后 HEAD diff）、git 冲突未合并路径（ls-files -u）、
      svn 变更/冲突解析（U/A/C 行）、svn 失败文案
- [x] 3.4 `test_multi_window.py`：工作区级提交（`.gitignore .state/`）、
      双项目提交隔离、本地项目拒绝
- [x] 3.5 全量默认套件回归通过
