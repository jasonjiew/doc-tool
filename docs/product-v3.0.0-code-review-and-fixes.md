# 改动代码审核与修复报告（v3.0.0）

审核范围：本工作树相对 HEAD `7ba19dd` 的全部改动（58 个已跟踪文件改动 + 272 个未跟踪新增文件），
重点为 `doc_tool/application/**`、`doc_tool/adapters/**`、`doc_tool/domain/**`、`doc_tool/ui/**`、
`scripts/tests/**`、`packaging/**` 与 CI 配置。审核方式：逐文件对照 diff 阅读 + 调用方契约核对 +
pyflakes 静态检查 + 真实运行验证（含 Word COM 实机探测）。

## 一、严重缺陷（会导致功能不可用或静默数据错误）

### 1. `scripts/refresh_fields.py` 被写空（0 字节），Word 刷新链路整体失效
- 现象：该文件在工作树中是唯一一个 0 字节的已跟踪文件（450 行被清空），但
  `doc_tool/adapters/kernel.py`、`doc_tool/application/template_fill.py`、`scripts/run_pipeline.py`
  与两个 PyInstaller spec 仍导入/拉起它。
- 根因：`tools/_patch*.json` 表明该文件应被 V4.0 40-B 补丁改成带 `LAST_REPORT` 阶段事实的版本；
  写入过程中落成了空文件（本机 `ReplaceFileW`/硬链接式原子替换在 D 盘不可用，实测复现同类失败）。
- 修复：按 `_patch11`→`_patch15` 的原始意图重建该文件（19,956 → 22,194 字节），补回
  40-B 契约：`LAST_REPORT`、`_bounded_supervise_in_thread`、阶段标记解析、停止预算清理。

### 2. 重建过程中发现契约缺口：`STAGE_PENDING` 使用但未导入
- 现象：`scripts/refresh_fields.py` 的 stderr 读取线程在解析到第一个阶段标记后即因
  `NameError` 退出，`[REASON]` 标记永远读不到，刷新失败一律被归类为 `refresh_failed`
  （保存失败被误报）。
- 修复：把 `STAGE_PENDING` 加入 `doc_tool.domain.word_operations` 导入列表。

### 3. `communicate()` 与后台读线程抢同一个 stderr（双读者）
- 现象：`supervise` 既起后台线程排空 `stderr`，又调用 `process.communicate()`，
  两个读者互相截断输出，阶段事实与原因键都可能丢失。
- 修复：改用 `process.wait(timeout=...)`，`stderr` 只由后台线程读取
  （`test_review_20261004_regressions.test_word_refresh_has_one_stderr_reader` 已由失败转为通过）。

### 4. `word_check.check_word_dispatchable` 结果分支是死代码，Word 可用性被误判为不可用
- 现象：`if message[0] == result` 的成功分支被粘贴到了 `_sweep_new_word()` 函数体末尾、
  且在 `return len(killed)` 之后，永不执行；spawn 探测永远返回 `(False, "")`。
  同时超时后不再强杀挂起的探测子进程。
- 修复：把结果分支移回正确位置（`for message in reversed(messages)`），并恢复超时强杀。

### 5. `word_check.check_word_available` 从不写入 `word_dispatchable`
- 现象：`available` 依赖 `report.word_dispatchable`，但该字段只在静态检查分支被赋值，
  探测成功时仍为 `False` → 所有正式合并/`.doc` 转换/PDF 导出在装有 Word 的机器上被拒绝，
  且 `reasons` 为空（提示「未知原因」）。
- 实测证据：修复前 `available=False, wordDispatchable=False, version=16.0, reasons=[]`；
  修复后 `available=True, wordDispatchable=True, version=16.0`（本机 Word 16.0）。
- 修复：探测后写回 `report.word_dispatchable = bool(success)`，并去掉重复的 `deadline` 赋值。

## 二、运行时必崩缺陷（pyflakes `undefined name`，共 5 处真实调用位置）

对全仓做 pyflakes 检查得到 38 处 `undefined name`；逐条判定「注解位置（`from __future__ import annotations` 下不求值）」
与「真实取值位置」后，确认 5 处会在运行中抛 `NameError`：

| 位置 | 问题 | 修复 |
| --- | --- | --- |
| `doc_tool/application/prepared_source.py:319` | 使用 `sys.executable` 但未 `import sys` | 补 `import sys` |
| `doc_tool/ui/empty_state.py:840/861/896` | 使用 `QCursor.pos()` 但 QtGui 未导入 `QCursor`（3 处提示气泡必崩） | 导入 `QCursor` |
| `doc_tool/ui/main_window.py:1316` | `logger` 从未定义（无状态栏时的兜底分支） | 定义模块级 `logger`，改为标准 `logging` 调用 |
| `doc_tool/ui/main_window.py:4899` | 字典推导 `if` 子句引用生成器内部变量 `rel`，且被外层 `except` 静默吞掉，导致磁盘正文不参与差异计算 | 改用推导自身变量 `rel_path`（已验证可运行） |
| `doc_tool/ui/content/lint_panel.py:926` | `GroupedFixItem` 只在另一函数的局部导入，此处不可见（正文已变化时的跳过分支必崩） | 提升为模块级导入 |

另把 13 个文件中仅出现在注解位置、但确实未导入的 typing 名字补齐（`Union`/`Tuple`/`Dict`/`Sequence`/
`Optional`/`Any`/`Mapping`/`pathlib`），使 `typing.get_type_hints()` 与未来去掉 `__future__` 导入后都不会崩；
`tools/gen_v27_samples.py` 的 `TAB_RETURN if False else ...` 死代码一并清理。

修复后 `python -m pyflakes doc_tool scripts tools packaging` 的 `undefined name` 为 **0**。

## 三、中危缺陷（行为错误/静默误报）

| # | 位置 | 问题 | 修复 |
| --- | --- | --- | --- |
| 1 | `content/reimport.py` 预览 | 解析失败分支绕过唯一 `rmtree`，且每轮预览都在 `.state` 留下整份文档副本 | 失败分支即时清理；新一轮预览前释放上一轮隔离目录 |
| 2 | `content/batch_chapter_ops.py:292` | 「移动到自身目录」探测把候选自身当作占用，永远认为需要移动，实际 apply 又过滤 `old==new` → 报「N/N 成功」但什么都没做 | 传入 `{rel}` 作为已腾空集合，正确识别空操作 |
| 3 | `content/batch_chapter_ops.py:169` | 无标记时也删除尾随数字：`Windows 11`→`Windows`、`3.1`→`3.` 破坏标题与章节号 | 只删除紧跟标记之后的数字 |
| 4 | `content/asset_manager.py:246` | 编辑器缓冲的图片只按 `assets/<类型>/<目标>` 一条规则解析，`images/` 形式被误判「缺失引用」，面板据此提供删除/修复 | 与磁盘侧扫描同规则，兼容 `assets/<类型>/images/<文件名>` |
| 5 | `content/tree.py:96` | 用分组循环遗留的 `first` 判定当前文件首段 | 改用 `parts[0]` |
| 6 | `content/batch_chapter_ops.py:60` | `ok` 分支丢弃 `message`，「目标未能改名」事实不可见 | `ok` 分支也拼接 message |
| 7 | `delivery/handover.py:75` | 目录形式成果包按 zip 解析，完好包被报「包文件不存在 / 包内文件 0 个」 | 目录走真实文件清单，文件才走 zip |
| 8 | `ui/content/lint_panel.py` | 「暂不处理」只写 `_suppressed`，渲染与计数都不读它 → 该功能实际不可达 | 渲染前先按 `_suppressed` 过滤，行与「共 N 项」同步 |
| 9 | `ui/content/workspace.py:2152` | 每次批量操作都留下一个隐藏顶层对话框 | 只保留最近一次并释放上一个 |
| 10 | `ui/batch_result_window.py:125` | 「打开所选项目」无条件 `break`，只打开第一项 | 遍历全部选中项 |
| 11 | `ui/content/issues_panel.py` | `set_check_context`/`set_baseline_issues` 无生产调用方，「检查范围/时点」与「新增/消失/保留」永远显示未知 | 在 `_on_lint_issues` 接入真实时点与上一轮结果作为基线 |
| 12 | `project_export.py:323` | 残留未使用导入 `is_formal_success`，形成第二处判断入口 | 删除 |

## 四、已修复的低危问题

- `scripts/refresh_fields.py` 的 `_kill_process_tree` 既无 `timeout` 也不捕获异常，
  超时清理可能无限挂住；已对齐同类实现（`timeout=10` + 不遮蔽原始结果）。
- `scripts/tests/measure_core_baseline.py` 文档字符串中的 `\t`/`\m` 无效转义（SyntaxWarning）；
  改为正斜杠路径。

## 五、版本与发布门禁

发布版本统一为 **3.0.0**，五处版本源已一致（正式发布时 CI 会强制校验）：
`doc_tool/domain/version.py`、`packaging/installer.iss`、`packaging/build.ps1`、
`.github/workflows/build-release.yml`、`.gitlab-ci.yml`。
修复前 `installer.iss`/`build.ps1` 为 2.6.1、GitHub workflow 为 2.6.1、GitLab 为 2.6.0、
应用版本为 2.9.0 —— 一旦打 tag 必然被门禁拦下。

## 六、仍未解决（本轮不修，留待后续）

1. **Word 不可用提前返回时的暂存目录**：`run_pipeline` 在该分支直接返回，未清理
   `import_project._create_staging` 产生的 `.proj.import-staging-*`。审核建议的 `_cleanup_temp()`
   经核实是另一函数的嵌套定义、在该作用域不可用（照抄会抛 `NameError`），已撤回；
   正确修法需要在导入/发布流程中明确暂存目录的所有权与清理时机。
2. **`project_export._refresh_after_layout` 的阶段事实写入临时字典**：版式后二次刷新的
   阶段/耗时不会被结果页看到，`wordFacts` 描述的是刷新前的状态。需要打通报告通道（改动面较大）。
3. **`word_convert` HTML→PDF 分支阶段计时错位**：`process` 阶段恒为 `pending/0.0s`，
   耗时被整段记到 `save`。仅影响诊断显示，不影响产物。
4. **`batch_result_window._reload` 依赖宿主副作用**：刷新正确性依赖
   `MainWindow._last_batch_result` 被更新，属隐式耦合，未加回归。
5. `pyflakes` 仍报告大量历史遗留的「导入未使用 / 局部变量未使用」，不影响运行，
   本轮未做全仓清理以免放大改动面。

## 七、验证

- `python -m pyflakes doc_tool scripts tools packaging`：`undefined name` 0 处。
- 全仓 556 个 Python 文件 AST 解析通过，0 语法错误。
- 全量测试套件（`scripts/tests/run_tests.py`）结果见随本次发布的 CI 报告与本轮运行产物。

## 八、主窗口（main_window.py）补充审核

`main_window.py` 是本次改动最大的单文件（+538/−48）。对其 diff 单独复核后，又发现并修复 4 项：

| # | 位置 | 问题 | 修复 |
| --- | --- | --- | --- |
| 1 | `main_window.py:1671/1679` | 命令面板绑定了并不存在的方法 `_on_diag_task`/`_on_validate_task`（真实方法为 `_on_diag_build`/`_on_validate`），且属性在构建条目时即求值 → 只要打开了项目，按下 Ctrl+K 就抛 `AttributeError`，面板根本不出现 | 改为真实方法；并逐条核对全部 `callback=self._on_*` 引用均已存在 |
| 2 | `main_window.py:4917` | 差异预览用了自定义 `on_done`，因此绕过了标准收尾：计时器不停、`_current_task` 残留、任务坞一直显示运行中，导入/打开项目/正式合并/快速构建/重新导入被长期禁用 | 在回调入口无条件结束任务态并刷新交互状态（实测：`current_task` 由 `reimport-preview` 变空、计时器停止） |
| 3 | `main_window.py:5024` | 差异会话给的是 contentRoot 相对路径，而编辑标签键带文档类型前缀，`editor_for` 永远返回 `None` → 「仅保存相关章后刷新」是空操作，还给出错误原因 | 两种键都试（与同文件既有做法一致）；实测相对路径 `x.md` 现可命中 `general/x.md` |
| 4 | `main_window.py:1048/1145/4938` | 导入结果、批量结果、差异预览窗口只 `close()`（仅隐藏）不销毁，每次重开都留下一个隐藏窗口并持有完整结果数据 | 关闭后显式 `deleteLater()` |

### 仍未解决
- **多 Word 批量导入仍在 UI 线程同步执行**：`_start_word_batch`/`_retry_intake_items` 直接调用 `run_word_batch`，
  导入 N 个文件期间窗口完全无响应、无取消、无阶段反馈（单文件路径已走 `TaskRunner`）。
  修法应改为 `self._start_task(TaskSpec(...))`，涉及批量结果的回调接线，本轮未动。
- **混合拖入时静默丢弃不支持项**：`len(word_like) > 1` 时提前 `return`，跳过了逐文件路由，
  「2 个 Word + 1 个 PDF/RAR」不再提示被忽略的文件（单文件路径仍有提示）。

## 九、发布前置校验（本机实测）

| 校验项 | 命令 | 结果 |
| --- | --- | --- |
| 版本一致性（tag=3.0.0 模拟） | 对比 version.py / installer.iss / build.ps1 / GitHub / GitLab | **PASS**（五处均为 3.0.0） |
| 已跟踪文件泄漏扫描 | 等价于 `scan_leaks --strict` 的仓库扫描部分 | **0 泄漏** |
| 公共发布授权门禁 | `python packaging/release_gate.py --public` | **PASS** |
| 测试注册完整性 | 解析 `run_tests.py` 的 DEFAULT_TESTS | 226 项，0 重复、0 缺失、0 未注册 |
| 全仓语法 | AST 解析 556+ 个 .py | **0 语法错误** |
| 静态未定义名 | `python -m pyflakes doc_tool scripts tools packaging` | `undefined name` **0** |

说明：本机直接运行 `scan_leaks --strict` 会 FAIL，原因见第十一节（陈旧 dist 产物 + 3 个已跟踪文件的启发式误报），与全新克隆的 CI 行为不同。

## 十、全量测试与随之修复的两个缺陷

第一轮全量（226 项）结果：**2 项失败**，均已定位到根因并修复：

1. `test_v40_word_process_hygiene`（2 个子用例）——**本轮修复引入的回归**。
   `check_word_dispatchable` 恢复成功分支后，成功路径不再清扫进程，而 worker 的 `Quit` 是异步的，
   探测结束后仍可能短暂残留 WINWORD，于是「探测后不得出现新增 Word 进程」失败，
   并且残留进程随后退出又让「用户 Word 不得消失」失败。
   修复：无论成败都只清扫**本次探测新增**的进程（baseline 内的用户 Word 绝不动），保留 0.5s 宽限轮。

2. `test_v42_rule_dependencies.test_reset_clears_caches` —— **先前会话遗留的真实缺陷**。
   `incremental_index.content_digest` 只在 `use_stat_cache=True` 时写入 `_DIGEST_CACHE`，
   而生产调用（`index.py` 等）全部使用默认 `False`，因此摘要缓存、容量上限 20000、
   溢出清空策略与 `reset_digest_cache()` 全是死代码，V4.2 想要的增量加速实际未生效。
   修复：改为「**始终登记、仅在 `use_stat_cache=True` 时复用**」——默认路径仍每次都真实读取
   （同大小/同 mtime 的改写照样被发现），正确性不变，缓存与上限策略重新生效。

## 十一、公开导出扫描：未解决，会阻塞 tag 流水线（需业务确认）

`python packaging/export_public_source.py --output <tmp> --scan` 本机 FAIL，共 40 项，拆开看是两类：

- **37 项来自本机陈旧构建产物**（`dist/DocTool/_internal/doc_tool/resources/standards/*/template.docx`
  及其内部品牌词）。`doc_tool/resources/standards/` 在当前源码树中并不存在，是旧布局遗留；
  CI 全新克隆不会出现这些文件，故与本仓库内容无关。
- **3 项来自已跟踪且未修改的源文件**（在 HEAD 即存在，**不是本次改动引入**）：
  1. `scripts/tests/test_core_scope_presets_batch.py:124/131`：样例名 `康尚需求模板` 命中 brand 词。
  2. `scripts/tests/test_v33_authoring_assistance.py:611`：`secret = "sk-v33-secret-value"`
     命中「口令/密钥赋值 模式」启发式——但它是**测试专用假值**，该用例恰恰是在断言密钥不写入日志与文件。
  3. `doc_tool/domain/captions.py`：`token = ...` 与 `token: str` 形参注解命中同一启发式——
     这里的 token 是「占位符标记」语义（`@{kind}-{ident}`），不是凭据。

影响：GitHub Actions 与 GitLab CI 的公开导出扫描任务（`export_public_source --scan` /
`scan_leaks --strict`）会失败，从而阻断 tag 触发的自动构建与 Release 资产上传。
注意 `scan_credentials` 目前**没有文件级豁免机制**，因此处理方式属于门禁策略决定：

- 方案 A（推荐，需改门禁）：为 `scan_credentials` 增加显式「已知误报文件」白名单，
  并在白名单条目上写明理由（测试假值 / 占位符 token 语义）。
- 方案 B（不改门禁）：把 `captions.py` 的 `token` 命名与测试里的假值写法调整为不触发启发式——
  但 `token` 是 `captions.py` 的公开形参名，改名会影响调用方，风险高于方案 A。
- 方案 C：接受该任务失败，人工创建 Release 记录（本轮即按此执行，见发布说明）。

本轮未擅自放宽安全扫描器，也未为过门禁而改动公开 API；建议由项目负责人选定 A 或 B。
