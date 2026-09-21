## 目标

把 Doc Tool 从"单机完整"推进到"团队与流水线可用"：CI 可产预发布稿并由任一 Word 机器正式化；多文档共享章节；章节历史、提交门禁、评审联动在工具内闭环；AI 以受控 provider 形式提供两个确定收益点。

## 决策

### D1 `staged` 状态与 promote

- `OutputState` 状态集：`draft`（快速构建）→ **`staged`**（无 Word 构建 + 前校验 + 终审通过，待刷新）→ `formal`。
- `doc-tool build --stage`：`skip_word_refresh=True` 但不打 `diagnostic`，产物名 `<doc>.staged.docx`，`.state.json` 记录 `sourceTreeSha256`（content + assets + manifest 的归一化哈希）、`appVersion`、audit 报告。
- `doc-tool refresh --promote <staged.docx>`（GUI：打开项目时检测到 staged 且 hash 与当前源一致 → 提示"一键正式化"）：
  1. 校验 `sourceTreeSha256` 与当前源一致，否则拒绝（防止源已变而正式化旧稿）；
  2. 复制到临时文件 → `refresh_fields.supervise` → `validate_post` → `audit` → 原子发布为正式名并归档 `BuildHistoryStore`；
  3. 删除 staged 产物。
- 项目锁在 promote 期间持有 `TASK_REFRESH`。
- CI 示例（`docs/ci-examples/gitlab-ci.yml`）：`doc-tool check` → `doc-tool build --stage` → 上传制品；Windows runner 或人工机器执行 promote。

### D2 Include

- 标记：`<!-- INCLUDE: <relative path> -->`，相对于当前文件；解析后路径必须在项目根或 `manifest.includeRoots`（相对项目根的目录列表，允许 `../common`）内，复用 `writer._resolve_inside` 思路做 realpath 白名单校验。
- `STAGE_PREPARE` 展开（深度 ≤ 5，循环检测 → `lint.include_cycle` error）；被包含内容中的相对图片路径按被包含文件位置改写。
- 预览：编辑器渲染时展开并以浅色边框标注"来自 xxx.md（只读）"。
- 树：被 include 的文件若在项目内，以链接图标标识并可跳转；被 include 文件被 rename 时 `RefactorEngine` 同步更新 INCLUDE 标记。
- 改动检测：`changed_chapters()` 把被 include 文件的改动归到所有包含它的章节。

### D3 章节 Git 历史

- `vcs_changes.file_history(rel_path, limit=50) -> List[HistoryItem(sha, author, date, subject)]`（`git log --follow --format=%H%x1f%an%x1f%aI%x1f%s -- <path>`；SVN `svn log --xml`）。
- `vcs_changes.file_at_revision(rel_path, sha) -> str`（`git show <sha>:<repo-rel>`）。
- UI：树右键"历史…" → `ui/content/history_dialog.py` 列表 + 选中即与当前内容 side-by-side（复用改动面板 diff 组件）；"打开此版本为只读标签"。
- 编辑器状态栏：`git log -1 --format=%an %ar -- <path>` 结果缓存于 `ContentIndex`（文件保存/提交后失效）。

### D4 提交门禁与评审联动

- `git_commit_dialog`：打开时对本次改动章节运行 `ContentLinter.run(files=…)`，顶部显示"N 错误 / M 警告"，`gates.commit_lint: error` 时有 error 禁用提交按钮并可点击跳转。
- 提交成功后解析消息 `(?:Fixes|Resolves|修复)\s+(R-\d+)`（`ReviewComment.seq` 对应 `R-<seq>`），`ReviewStore.update_comment(status="confirmed_pending_review", commit=sha)`；评审面板显示提交号并支持"复核通过"。
- `approval_gate` 把 `confirmed_pending_review` 视为未关闭。

### D5 HTML 评审包

- `export/pdf_html.export_html` 扩展：每个改动章节前后对照（复用 `review_docx._build_annotated_diff_lines` 的行级 diff 数据，渲染为 HTML 而非 DOCX）+ 意见表单（纯前端 JS，按"下载 JSON"导出）。
- 评审面板"导入意见"支持该 JSON（幂等键沿用 `(review_ref, row_serial)`）。
- 输出目录 `output/review/review-html-<版本>-<时间戳>/`，含 `index.html` 与内嵌资源（图片 base64，避免路径依赖）。

### D6 AI provider

- `application/ai/provider.py`：
  ```python
  class AIProvider(Protocol):
      def complete(self, system: str, user: str, *, max_tokens: int, timeout: float) -> str: ...
  ```
  实现：`HttpChatProvider`（OpenAI 兼容 `/v1/chat/completions`，`endpoint`/`model`/`apiKeyEnv`/`proxy` 来自 manifest `ai:`；密钥只从环境变量读取，绝不写入 manifest/日志）与 `CommandProvider`（本地命令 stdin/stdout，供离线模型）。
- 启用条件：`manifest.ai.endpoint` 或 `ai.command` 非空且 `ai.enabled: true`；否则所有 AI 入口不渲染。
- 用途 1 修订摘要：`revision_record.suggest_summaries(prefill, diff_snippets, provider)`；输入截断到 8k 字符；输出解析为 1~3 条候选，显示在弹窗"建议"区，点击填入摘要框。
- 用途 2 术语审查：`lint` 新规则 `ai_term_consistency`（默认 off，级别 info）：对改动章节按 2k 字符分块 + 术语库发送，输出 `LintIssue(fix=None)`；问题中心标注"AI 建议"。
- 隐私：发送前对 `sensitive_info` 规则命中的片段做掩码；`RuntimeLog` 只记录请求大小与耗时；`docs/ai-privacy.md` 说明数据边界。
- 失败/超时静默降级为"无建议"，不阻断任何流程。

### D7 项目锁租约

- `project.lock` 新增 `heartbeat`（ISO 时间，持锁任务每 30s 刷新）与 `leaseSeconds`（默认 300）。
- 判定顺序：同主机 PID 存活 → 活动锁；不同主机 → 若 `now - heartbeat < leaseSeconds` 视为活动锁（显示占用者与时间），否则陈旧可接管。
- 旧格式（无 heartbeat）按现有规则处理。

### D8 命令注册表

- `ui/command_registry.py`：`register(id, title, category, callback, *, shortcut=None, enabled=lambda: True)`；`MainWindow` 与各面板在构造时注册；`open_command_palette` 从注册表构建条目，支持最近使用（`.state/ui/recent_commands.json`）。
- 现有静态命令逐步迁移，菜单项与命令面板由同一注册表驱动，杜绝两处不一致。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| promote 正式化了与源不一致的 staged 稿 | 源树哈希强校验；hash 不一致直接拒绝并提示重新 stage |
| Include 越界读取 | realpath 白名单；越界即 error 且不展开 |
| AI 端点泄露敏感内容 | 默认禁用；仅发送片段；敏感词掩码；文档化边界；企业可仅启用 `CommandProvider` 本地模型 |
| 提交门禁被绕过（外部 git） | 门禁定位为"工具内提醒"，真正阻断交给 CI `doc-tool check` |
| 命令注册表迁移遗漏动作 | `test_command_palette` 断言注册表与菜单动作集合一致 |

## 验收标准

- 无 Word 的 Linux 容器执行 `doc-tool check && doc-tool build --stage` 得到 `staged.docx`；Windows 机器 `refresh --promote` 后 `output/` 出现正式稿且 `.state.json` 为 `formal`；改动源后 promote 被拒绝。
- `<!-- INCLUDE: ../common/terms.md -->` 在预览与 Word 中展开；循环 include 被 Lint 阻断；越界路径被拒绝。
- 章节右键"历史"列出提交，选中显示 diff；状态栏显示最近修改人。
- 提交含 `Fixes R-3` 后评审面板意见 3 状态变更并显示提交号；`gates.commit_lint: error` 时含错误无法提交。
- HTML 评审包在无 Word 机器浏览器中打开可填写意见并导出 JSON，工具可导入且幂等。
- 未配置 `ai:` 时 UI 无任何 AI 入口；配置后修订弹窗出现建议，术语审查结果进问题中心为 info；断网时功能静默降级。
- 两台机器通过网络盘同开一个项目：第二台看到"被 X@host 占用"；第一台崩溃 5 分钟后第二台可接管。
- 命令面板包含"导出评审稿""设为基线""历史"等面板动作，且最近使用置顶。
