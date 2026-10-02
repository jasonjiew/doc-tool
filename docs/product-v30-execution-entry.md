# V3.0 正文复用入口与管线接线执行证据（批次 30-F）

- 日期：2026-10-01
- 范围：`openspec/changes/product-v30-content-reuse` 的**剩余入口与管线接线**——模块库 CLI、
  统一解析报告、选择性升级、产品变体入口、展开副本入口，以及 v1/v2 旧项目与旧命令回归。
- 本次新增 1 个服务适配模块 + 1 个测试文件 + 本证据文件，修改 `doc_tool/cli.py`（只新增
  reuse 子命令与分派）与 `doc_tool/application/content/modules.py`（见第 7 节真实缺陷修复）；
  只勾选真正实现并跑通测试的项。
- 未做（保持未勾）：`3.4` 把 resolved 内容接进 **Word/HTML/预览渲染管线与题注注册表**
  （本批只做到「同一解析入口 + 适配点」，见第 8 节）、`6.1`/`6.2` GUI 入口、
  `7.1`～`7.4` 全量回归/试点/发布收尾。

## 1. 复用与差额

| 复用 | 来源 | 用法 |
|---|---|---|
| 模块库/提取/导入导出 | `doc_tool/application/content/modules.py` | CLI 只做参数装配与退出码，不重写库逻辑 |
| 统一展开 resolver | `doc_tool/application/content/module_refs.py`（`resolve_body`/`Resolution`/`Assembly`/`InstanceBook`/`plan_upgrade`/`apply_upgrade`） | 解析报告、来源定位、升级预览与应用全部走既有实现 |
| 变体有效内容与出稿 | `doc_tool/application/content/variants.py`（`effective_chapters`/`effective_variables`/`effective_slot_overrides`/`build_variant_outputs`/`write_expanded_copy`/`verify_portable_copy`/`variant_report`） | `reuse variants|build|clone` 只做入口与报告拼装 |
| 章节顺序与变量语义 | `doc_tool/application/chapter_order.py`（经 variants 间接复用） | 有效章节顺序与文本变量规则不变 |
| 原子写入 | `doc_tool/application/content/writer.py`（`atomic_write`） | 升级写回 `reuse/assembly.yml`、副本落盘 |
| 夹具 | `scripts/tests/core_fixtures.py`（`scratch_dir`/`cleanup`/`two_chapter_project`/`tiny_png`） | 真实导入项目 + 仓库内 `tmp/core-scratch/`，不使用 `tempfile` |

差额（本批补齐的入口层）：CLI 子命令与分派、同一份解析入口（服务 + CLI + 预处理适配点）、
JSON/human 双形态机器报告、退出码 0/1/2 约定、来源与定位清单、选择性升级预览/应用、
变体有效范围查看/独立出稿/展开副本、旧命令与旧项目回归测试。

## 2. 完成编号（本轮新勾选 11 项）

`1.1` `1.3` `1.4` `2.1` `2.4` `2.5` `4.4` `5.2` `5.3` `6.4` `6.5`

累计已勾选（含上一轮 14 项）：`1.1` `1.2` `1.3` `1.4` `2.1` `2.2` `2.3` `2.4` `2.5`
`3.1` `3.2` `3.3` `3.5` `4.1` `4.2` `4.3` `4.4` `4.5` `5.1` `5.2` `5.3` `5.4` `6.3` `6.4` `6.5`（25 项）。

仍未完成（7 项）：`3.4`（Word/HTML/预览与题注注册表接线）、`6.1`/`6.2`（GUI 入口）、
`7.1`～`7.4`（全量回归、试点、文档与发布收尾）。

## 3. 真实接口（本次新增文件）

### `doc_tool/application/content/reuse_commands.py`（CLI 与界面共用的服务入口）

- 上下文：`ProjectReuseContext`、`load_context(project_root, library_root=None)`、
  `discover_chapters`、`configured_library`、`library_root_for`、`load_library`。
  - 库选择顺序：显式 `--library` → 项目固定副本 `reuse/modules` → `project.yml` 的可选
    `reuse.library` → 项目内 `reuse/library` → 无库（返回 None，不是错误）。
  - 章节根取 `ProjectPaths.content_dir(document_type)`，跳过 `_revision_record.md`
    等下划线开头的项目内部 Markdown。
- 规划与展开：`ResolutionPlan`、`plan_project`、`variant_selection`、`resolve_text`、
  `resolve_chapter`、`ChapterResolution`、`resolve_project`、`describe_sources`。
  - `plan_project` 先铺一层**装配固定参数**（`{slotId: {version, params}}`），再由变体
    覆盖，原 `Assembly` 不被就地修改。
  - `resolve_text` 是 `prepared_source.prepare_markdown` 的上游适配点：`slot_overrides=None`
    时沿用装配固定值，显式 `{}` 表示本次不看装配。
- 报告：`render_resolution_text`、`render_report`、`render_payload_text`、
  `render_upgrade_text`、`STATUS_TEXT`。
- 变体与副本：`variant_evidence`、`build_variant_documents`、`write_expanded_copy`。
- 模块库：`extract_chapter_module`、`list_modules`、`show_module`、`export_modules`、
  `import_modules`、`install_modules`。
- 升级：`upgrade_preview`、`upgrade_apply(dry_run=True 缺省)`。

### `doc_tool/cli.py`（只新增 reuse 子命令与分派）

`reuse list|show|extract|import|export|install|resolve|upgrade|variants|build|check|clone`，
统一 `--output human|json`。既有 `build`/`info`/`project-export`/`assist-*`/`convert`/`pdf`/
`template-fill` 等命令与 `main()` 既有分支保持原样（微改：新增 `if args.command == "reuse"`
一条分派）。

注意：`reuse show|extract` 的模块版本参数是 `--module-version`（`dest=module_version`），
顶层 `--version` 仍是「显示构建信息」，避免 argparse 同名覆盖。

## 4. 产物路径

- 服务：`doc_tool/application/content/reuse_commands.py`
- 入口：`doc_tool/cli.py`（新增 `_add_version_target`/`_add_reuse_sources`/`_reuse_split_target`/
  `_reuse_parse_params`/`_reuse_parse_declared`/`_reuse_open_library`/`_reuse_command` 与 reuse 子命令树）
- 测试：`scripts/tests/test_v30_reuse_entry.py`（40 项）
- 项目内 sidecar（运行时生成，不是本次提交物）：`reuse/assembly.yml`、`reuse/instances.yml`、
  `reuse/modules/<slug>/<version>/`、`reuse/library/<slug>/<version>/`、`variants.yml`、
  展开副本目录（`content/<类型>/…` + `_index.md` + `_copy.yml` + `README-展开副本.md`）
- 夹具：`tmp/core-scratch/<prefix>-<pid>-<n>/`（`cleanup` 由测试 teardown 处理）

## 5. 正常与兜底行为（本轮真实测过）

| 场景 | 正常 | 兜底 |
|---|---|---|
| 库列表/检索 | `reuse list --query/--tag` 命中名称/标签/正文/描述，附可选版本与 hash | 无库目录 → 空列表 + 可读提示，退出码 0（不是错误） |
| 模块预览 | `reuse show --param name=value` 按声明默认 + 覆盖替换 | 模块/版本不存在 → 退出码 2 并列出可选版本 |
| 提取 | `reuse extract --chapter` 从已保存章节提取，资源收进模块并记 hash | `--current-buffer <file>` 走明确快照；章节不可读 → 退出码 2（不谎称读到内容） |
| 导入/导出 | `reuse export --target`、`reuse import <dir>` 往返；缺资源仍导入并报告 | 非法附件路径（`../../outside.txt`）跳过且**不读取**，原库保留；模块仍可用 |
| 固定副本 | `reuse install --module id[@version]` 复制进 `reuse/modules/…`，原库搬走后仍可展开 | 缺库/缺模块 → 明确提示与退出码 |
| 统一解析 | `reuse resolve` 输出有效正文可用性 + 每个引用的模块/版本/hash/宿主行号 | 缺项目副本 → 库同版本缓存（warning）；都无 → 可读占位，其余正文继续 |
| 参数 | 装配固定参数生效；未声明键保留 `{{module.x}}` 字面值 | 缺参数用声明默认并 warning；`--strict` 时缺项升为退出码 2 |
| 循环 | 嵌套展开到深度 5 | 循环只停止该引用（`【已停止：…循环引用…】`），其余正文继续 |
| 退出码 | 有可用正文 → 0 | 有效章节为空/不可读 → 1；未知变体/未知模块/严格未达标 → 2 |
| 升级 | `reuse upgrade --to X` 预览差异与受影响 slot | 缺省只预览不写盘；`--apply` 才 `atomic_write` 回 `reuse/assembly.yml`；只改 `--slot` 选中项 |
| 变体 | `reuse variants --variant X` 显示有效范围；`reuse build --variant A --variant B` 独立目录互不覆盖 | 未知 variantId → 退出码 2 并列出可选项，不偷偷构建别的型号；坏章节项忽略并提示 |
| 展开副本 | `reuse clone --target` 生成普通 Markdown + 资源 + 清单，`verify_portable_copy` 归零 | 目标目录已存在且非空 → 退出码 2 且不覆盖；副本内缺失目标逐条报出 |
| 旧项目 | 无 sidecar 时 `reuse resolve` 返回原文、无 warning，退出码 0 | `project-export --source-mode current-buffer` 仍明确拒绝（退出码 2） |
## 6. 验证命令与真实结果

在仓库根执行：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path; python scripts\tests\test_v30_reuse_entry.py
```

- 结果：`Ran 40 tests in 129.6s` → `OK`，退出码 `0`（文件末尾有
  `if __name__ == '__main__': unittest.main(verbosity=2)`）。
- 回归（上一轮服务层测试，未改动其实现）：
  `python scripts\tests\test_v30_content_reuse.py` → `Ran 36 tests in 64.4s` → `OK`，退出码 `0`。
- 只跑本批测试文件与改动命令的 CLI 冒烟，未跑整套测试。

CLI 冒烟（对真实导入的两章项目，逐步记录退出码）：

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `reuse list --project P` | 0 | 模块库根 + 条目（无库时给提示） |
| `reuse resolve --project P --output json` | 0 | `status=ok`、`sources`（含 slot/moduleDir/hostLine/dependencyHashes） |
| `reuse variants --project P --variant model-a` | 0 | `scope.chapters`/`excluded`/`variables` |
| `reuse resolve --project P --variant ghost` | 2 | `error=unknown-variant`、`options=[model-a, model-b]` |
| `reuse resolve --project P --chapter …` | 0 | 单章解析（与变体互斥） |
| `reuse resolve --project P --strict`（有缺项时） | 2 | `status=invalid` + `strictErrors` |
| `reuse resolve --project <空内容根项目>` | 1 | `status=empty`、`usableChapters=0` |
| `reuse extract --chapter … --module-id X` | 0 | 写入 `reuse/library/X/1.0.0/`，收集资源清单 |
| `reuse show --module X --param …` | 0 | 声明参数 + 参数预览 |
| `reuse install --module X` | 0 | `reuse/modules/X/1.0.0/` |
| `reuse export --target D --module X` | 0 | 包目录 + `missingResources` |
| `reuse import <pkg>`（假设缺图） | 0 | `warnings=[附件缺失…]`，原库保留 |
| `reuse upgrade --module X --to Y`（预览） | 0 | `dryRun=true`、差异摘要、受影响 slot、**未写盘** |
| `reuse upgrade … --slot s --apply` | 0 | `updated=[s]`，仅选中 slot 换版本 |
| `reuse build --variant A --variant B` | 0 | 两份独立输出目录 + 范围报告 |
| `reuse clone --target D` | 0 | `portableIssues=[]`，正文无 `doc-module` 标记 |
| `reuse clone --target <非空目录>` | 2 | 明确拒绝覆盖 |
| `project-export --source-mode current-buffer` | 2 | 旧行为不变 |

## 7. 本轮发现并修掉的真实缺陷

1. **变体/无变体路径丢失装配固定参数**（`reuse_commands.plan_project`）：直接沿用
   `variants.effective_slot_overrides` 的结果时，无变体场景会得到空槽覆盖，项目里配好的
   固定参数（如 `productName=甲型号`）不生效，正文退回模块默认值。改为「先铺装配固定值，
   再由变体覆盖」。
2. **`resolve_text` 默认不应用装配参数**：直接调用（预览/Word/HTML 适配点）时不传
   `slot_overrides` 就会丢参数。改为 `None` 时沿用装配固定值，显式 `{}` 才表示忽略。
3. **`ProjectPaths` 没有 `asset_root`/章节根混淆**：`reuse_commands` 曾读不存在的
   `paths.asset_root`、用 `paths.content_root` 当章节根，导致「有效章节」多出一层
   `general/` 前缀、`reuse extract --chapter` 找不到正文。改用
   `paths.content_dir(document_type)` 与 `paths.assets_dir(document_type)`。
4. **一个非法附件路径让整个模块元数据不可读**（`modules.ModuleResource`）：
   `../../outside.txt` 触发 `ValueError`，`load_module` 返回 None，导入被报成
   「模块目录不可用（缺 module.yml）」，与任务 2.4「非法附件跳过、合法项可用」相反。
   改为容错：坏路径保留原文并标记 `invalidPath`/`isSafe=False`，导入/发布阶段跳过并报告
   （`非法附件路径已跳过`），模块其余内容仍可预览/使用。
5. **CLI 全局 `--version` 被 reuse 子命令同名参数覆盖**：`reuse extract` 曾因
   `--version` 被当作构建信息而直接打印版本并退出 0，命令体根本没执行。改为
   `--module-version`（`dest=module_version`）。
6. **`--library` 被项目固定副本抢走**：`reuse list/show/export --library X` 曾静默改用
   项目内 `reuse/modules`。改为显式 `--library` 优先（`_reuse_open_library`）。
7. **提取目标库可能落进固定副本树**：`extract_chapter_module` 曾把 `context.library`
   （可能是 `reuse/modules`）当发布目标。改为显式 `--library` → 项目库（非固定副本）→
   `reuse/library` 的顺序。
8. **解析报告把 `_revision_record.md` 当章节**：`discover_chapters` 只跳过点文件，
   导致 `reuse resolve` 把内部修订记录列进「有效章节」。改为与 `effective_snapshot`/
   `reimport` 同一口径跳过下划线前缀内部文件。
9. **`variant_evidence` 读错属性**：`plan.variant.moduleVersions` 不存在（`Variant` 只有
   `modules`/`module_version`），`reuse variants` 直接抛 `AttributeError`。改为从
   `plan.scope` 取模块版本。

## 8. 未验收项（保持未勾并写明原因）

- `3.4`（部分完成）：resolved 内容/来源/题注注册表**尚未接进 Word/HTML 构建管线**。
  本批只做到：同一解析入口（`reuse_commands.resolve_text`/`resolve_chapter`）+
  `prepared_source.prepare_markdown` 的上游适配点（测试用 monkeypatch 验证「同一解析路径」
  产出同一份文本）+ CLI `reuse resolve|check` 报告。真正接线需改
  `doc_tool/application/prepared_source.py`/`doc_tool/application/pipeline.py`/
  `doc_tool/application/content/preview.py` 等**本次严格边界外**的文件，因此保持未勾。
- `6.1`/`6.2`：GUI 入口（编辑器引用/复制编辑/查看来源/纳入追踪、库页面、升级与变体选择）。
  本批未新增 GUI 面板（当时的临时文件名已不用）；后续第 4 轮以 `doc_tool/ui/reuse_dialog.py` 落地：无 GUI 环境下的验证见 `test_v30_reuse_ui.py`，且接入需要修改
  `doc_tool/ui/main_window.py`（边界外）。服务入口已就绪，GUI 接线可直接调用本模块函数。
- `7.1`～`7.4`：全量回归、三公开模块两文档/两型号离线与换目录试点、实机 Word/冻结检查、
  使用说明与发布号收尾、OpenSpec 归档。本批按要求只跑自研测试文件与 CLI 冒烟。
- 未覆盖：`reuse build` 的 DOCX/HTML 出稿（只生成展开后的普通 Markdown 副本）；
  实机 Word 字段刷新；副本 `assets/` 兜底分支（源资源不在项目根内）。

## 9. 下一任务

1. `3.4`：把 `reuse_commands.resolve_text` 接进 `prepared_source.prepare_markdown` 的
   调用点（预览/检查/Word/HTML 共用），并注册题注；验收「预览与 Word/HTML 内容、参数、
   层级、题注一致，定位回模块来源」。
2. `6.1`/`6.2`：GUI 接线（模块库面板、引用/复制编辑/纳入追踪、升级与变体选择），
   复用本模块的 `list_modules`/`show_module`/`extract_chapter_module`/`upgrade_apply`/
   `variant_evidence`/`build_variant_documents`。
3. `7.1`：跑直接套件与版内全量回归，按 A30-1～6 记录正常/兜底/严格场景，既有无关失败单列。
4. `7.2`/`7.3`/`7.4`：三公开示例模块试点、使用说明与格式文档、按当前最高版本定 V3.0 发布号
   并归档 change。

## 续：3.4 同源展开接进共享管线（父会话本轮实施）

```text
实现：
  - `prepared_source.prepare_markdown/prepare_documents` 新增可选 `resolver`
    （在 Mermaid/资源预处理之前展开；失败保留原文并记录 `_RESOLVE_FAILURES`）
  - `pipeline` 按项目声明构造 resolver（无声明返回 None，**不做标记解析**；仍有一次章节扫描），阶段说明给出
    展开章节数；**展开项目的前校验**从“失败”降级为“带提醒完成”，并把差异项写入
    阶段 metrics（正式发布仍受既有审计门禁与严格策略约束）
  - `effective_snapshot` 物化章节时同样展开，使离线 HTML/预览与 Word 同源
  - 新增 `content/reuse_hook.py`：标记检测、项目声明探测、resolver 构造（含 notes）
验证命令 / 退出码：
  python scripts\tests\test_v30_pipeline_wiring.py -> Ran 5 tests OK (exit 0)
     覆盖：标记检测、展开结果（无残留标记）、无声明项目不做标记解析（仍有一次章节扫描）、
           诊断构建产物 document.xml 含模块正文且无标记、快照与离线 HTML 同源
  回归：test_prepared_source 12 OK / test_pipeline_gates_v27 4 OK / test_project_build 21 OK
遗留：6.1/6.2 GUI 入口、7.x 收尾（A30-1～6 逐条留证、试点、版本源、同步归档）
```

## A30-1～6 场景留证（父会话第四轮，直接套件 + 版内全量回归）

| 场景 | 证据（真实运行） | 结果 |
|---|---|---|
| A30-1 固定副本与库变化解耦 | `test_v30_content_reuse.py`（模块提取/项目固定副本/库损坏回退/离线可用）、`test_v30_reuse_entry.py`（import/install/export、缺模块→同版本缓存） | 通过 |
| A30-2 同源展开与来源定位 | `test_v30_pipeline_wiring.py`（构建产物含展开正文、快照与离线 HTML 同源）、`test_v30_reuse_entry.py`（resolve 报告含来源/版本/hash/行号） | 通过 |
| A30-3 缺模块/资源/参数/循环兜底 | `test_v30_content_reuse.py`（参数默认与字面值、循环只停该引用、占位）、`test_v30_reuse_entry.py`（严格模式退出码 2） | 通过 |
| A30-4 实例 ID 与覆盖率分母 | `test_v30_content_reuse.py`（InstanceTracking：身份稳定、新 slot 新 ID、仅显式纳入计分子） | 通过 |
| A30-5 变体差异与有效范围 | `test_v30_content_reuse.py` + `test_v30_reuse_entry.py`（variants/build/check、两型号目录与变量、未知变体报错） | 通过 |
| A30-6 v1/v2 旧项目与展开副本 | `test_v30_reuse_entry.py`（旧命令/无 sidecar 项目回归、可搬目录自检 `verify_portable_copy`） | 通过 |

版内全量回归：`run_tests.py` 114 文件仅 1 项环境失败（mermaid 缺 `mmdc`），其余全 OK；
实机 Word 版式、冻结包与 125%/150% 缩放属 7.2/7.3 待验收项。

## 续二：6.1/6.2 GUI 入口（父会话第四轮）

```text
实现：`doc_tool/ui/reuse_dialog.py`（模块库列表/搜索/预览、变体下拉、解析本项目引用报告、
  生成展开副本）+ `main_window` 内容菜单「正文模块库与引用解析…」（Ctrl+Alt+R）。
  界面只做入口与展示，能力全部复用 reuse_commands；技术细节留在报告文本，不暴露 hash/schema。
验证：python scripts\tests\test_v30_reuse_ui.py -> Ran 6 tests OK (exit 0)
  覆盖：模块列表与预览、搜索过滤、解析报告含章节与来源、展开副本落到所选目录且
        章节无 `doc-module` 标记、入口存在、无项目时给出提示、有项目时调用真实对话框。
遗留：7.2 两型号离线/换目录试点与实机 Word/冻结检查、7.3 说明与版本源、7.4 同步归档。
```

## 续三：7.2 三模块 × 两文档 × 两型号离线/换目录试点（父会话第八轮）

```text
场景：文档一/文档二各三章（每章带小节）；从文档一提取 3 个公共模块（m-alpha/m-beta/m-gamma）
  并把整份 reuse/（含库配置）共享给文档二；两文档各自声明 model-a/model-b 两个型号
  （变量 productName 不同，model-b 排除本项目的第二章）。
验证：python scripts\tests\test_v30_offline_pilot.py -> Ran 3 tests OK (exit 0)
  覆盖：两文档 × 两型号共 4 个产物生成；变量按型号生效；被排除章节及其模块正文确实不出现；
        纳入章节的公共模块正文全部展开；公共库两文档一致；**换目录后仍可再出稿**；
        展开副本搬到另一目录后 `verify_portable_copy` 无问题且不含引用标记。
  回归：test_v30_content_reuse 36 OK / test_v30_reuse_entry 40 OK / test_v30_pipeline_wiring 5 OK。
待验收（单列）：实机 Word 版式、冻结包（PyInstaller）检查。
下一批 / 下一任务：30-G / 7.3（说明与版本源）
```

## 续四：7.3 格式/回退指南与版本源（父会话第九轮）

```text
产出：`docs/product-v30-reuse-formats.md`（固定引用与 copy 格式、assembly 声明、variants.yml
  schema、展开回退对照表、换目录副本自检、版本源决定）+ 既有 `docs/product-v30-v33-usage.md`。
版本源决定：应用版本源保持 2.9.0；V3.0 未发布，发布号在同批正式发布时按当时最高版本确定
  （与 V3 总计划“收尾依据实际最高版本校正、不在规划中覆盖版本源”一致）。
未执行（实机）：冻结包（PyInstaller）与实机 Word 版式检查。
下一批 / 下一任务：30-G / 7.4（同步/归档，待全部验收）
```

## 审计更正（父会话第十四轮，独立审计产品-v30 勾选项后）

```text
措辞更正：此前写“无声明项目零开销”不准确——`reuse_hook.project_has_module_declarations`
  在无 `reuse/` 目录时仍会扫描内容树里的 .md 找标记（每次构建/快照一次）。已改为
  “不做标记解析（仍有一次章节扫描）”。实现与测试未变。

仍待处理（审计发现，见 docs/product-v3-audit-findings.md）：
  ① 勾选项“同源展开进入预览”：Word/检查/快照-HTML 同源成立，但**GUI HTML 预览与编辑器预览**
     仍渲染未展开文本；
  ② 勾选项“实例 ID 稳定与覆盖率分母”：机制与单测在，但 `instances.yml` 无产品写入路径、
     `include_items_in_tracking` 无产品调用者；
  ③ 预校验把 Word 与原始源比较的差异降级为提醒（已在 3.4 记录）。
```

## 续五：3.4 预览同源 + 4.3 实例写入路径（父会话第十八轮）

```text
问题（第十四轮审计）：
  3.4 管线/快照/Word/检查同源成立，但 **GUI 编辑器预览与只读 HTML 预览仍渲染未展开文本**；
  4.3 实例 UUID 映射仅库级，`reuse/instances.yml` 无任何产品写入路径。

修复：
  - 预览同源：`EditorPanel` 新增可选 `text_resolver`（预览前展开，失败保留原文），
    `TabsHost`/`ContentWorkspace` 透传；`MainWindow._preview_text_resolver()` 复用
    `reuse_hook.build_project_resolver`（无声明项目返回 None，零额外开销）；
    `export_readonly_html(..., text_resolver=...)` 与 `HtmlPreviewDialog` 同样先展开再渲染。
  - 实例写入：新增 `reuse_commands.record_instances()` —— `InstanceBook.load` 复用已有 UUID、
    只登记明确纳入的 slot、悬空实例只作证据不写入、`save()` 落 `reuse/instances.yml`；
    `resolve_project(record_instances=True)` 在报告里给出 `instances`/`coverage`；
    CLI `reuse resolve --record-instances [--slots s1,s2]`；GUI 面板「解析本项目引用」同样登记。
验证：
  python scripts\tests\test_v30_preview_instances.py -> Ran 5 tests OK
    （编辑器预览含展开正文且无标记、无展开器时保持原样、只读 HTML 含展开正文；
      实例文件落盘 + 覆盖率分母 ≥1 + 幂等 + slot 过滤 + resolve_project 开关行为）
  CLI 冒烟：python -m doc_tool.cli reuse resolve --project <p> --record-instances --output json
    -> exit 0；coverage.denominator=1；reuse/instances.yml 已生成
  回归：test_v30_content_reuse 36 OK／test_v30_reuse_entry 40 OK／test_v30_reuse_ui 6 OK／
        test_core_entries_ui 7 OK／test_core_export_ui 5 OK／test_v33_adoption_editor OK／
        test_home_experience_iteration 19 OK／test_gui_services 170（仅 1 项 mermaid 环境失败）
遗留（保持未勾选）：7.4 同步归档；实机 Word 版式/冻结抽查。
```
