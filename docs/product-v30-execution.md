# V3.0 正文复用服务层执行证据（批次 30-B/C/E）

- 日期：2026-10-01
- 范围：`openspec/changes/product-v30-content-reuse` 的**服务层 P0/P1 能力**（正文模块库、固定引用与复制编辑、统一展开、选择升级与实例追踪、产品变体、展开兼容副本）。
- 本次只新增 3 个服务模块 + 1 个测试文件 + 本证据文件，并只勾选真正实现且测过的任务项。
- 未做：GUI 入口、CLI 子命令、Word/HTML/预览管线接线、离线包导入导出专项测试、v1/v2 全量回归、发布号收尾。

## 1. 复用与差额

| 复用 | 来源 | 用法 |
|---|---|---|
| 原子写入 | `doc_tool/application/content/writer.py`（`atomic_write`/`atomic_write_bytes`） | 模块正文/元数据/资源/副本统一落盘，跨卷回退已由既有实现处理 |
| hash 与命名 | `doc_tool/application/intake_contract.py`（`sha256_file`/`sha256_text`） | 模块正文与资源 hash、依赖 hash |
| 章节顺序 | `doc_tool/application/chapter_order.py`（`resolve_chapter_order`） | 变体有效章节＝项目顺序筛选后再做 include/exclude |
| 变量语义 | `chapter_order.resolve_variables` 的既有规则（围栏/资源路径不替换、不递归求值） | `{{module.name}}` 参数替换沿用同一规则，未新增表达式引擎 |
| 夹具 | `scripts/tests/core_fixtures.py`（`scratch_dir`/`cleanup`/`two_chapter_project`/`tiny_png`） | 真实导入项目 + 仓库内 `tmp/core-scratch/`，不使用 `tempfile` |

差额（本次补齐的服务层）：模块提取与不可变发布、库索引/检索/预览、项目固定副本安装、slot 标记与统一 resolver、参数/标题偏移/资源改写、循环与深度兜底、版本差异与选择性升级、实例身份与覆盖率解释、显式变体有效内容、展开兼容副本与可搬目录自检。

## 2. 完成编号（已勾选，共 14 项）

`1.2` `2.2` `2.3` `3.1` `3.2` `3.3` `3.5` `4.1` `4.2` `4.3` `4.5` `5.1` `5.4` `6.3`

未完成（保持未勾选，18 项）：`1.1` `1.3` `1.4` `2.1` `2.4` `2.5` `3.4` `4.4` `5.2` `5.3` `6.1` `6.2` `6.4` `6.5` `7.1` `7.2` `7.3` `7.4`。
其中 `2.1`/`2.4` 已有可用实现但缺少本轮专项测试（未测不勾）；`3.4`/`5.2`/`5.3`/`6.1`/`6.2`/`6.4` 属管线与入口，未实施。

## 3. 真实接口（新增文件）

### `doc_tool/application/content/modules.py`（正文模块库）

- 数据：`ModuleParameter`、`ModuleResource`、`Module`（`module.yml` schema 1：moduleId/version/title/tags/description/bodyFile/bodySha256/parameters/resources/source）、`PublishedModule`、`ExtractionResult`。
- 提取：`extract_module(body, module_id=…, version=…, tags=…, parameters=…, resource_roots=[contentRoot, assetRoot], base_dir=project_root, resource_sources=…)` → 收集 `![…](images/x.png)`（含 `"标题"` 与引用式定义），改写为 `resources/<name>`，记录 `sha256` 与 `sourcePaths`；缺失资源保留原引用并给 warning。
- 库：`ModuleLibrary(root)`：`refresh/index_error/damaged_report/issues`、`entries/modules/get/versions/search(query|tags)/preview(id, version, params)`；`publish(module, resources=…)` 不可原地覆盖（同版本不同内容 → 候选 `1.0.0-2`）、`next_version`、`export_module`、`import_module`、`save_examples`。
- 项目固定副本：`project_module_root/project_module_dir/install_module/install_from_library` → `reuse/modules/<slug>/<version>/{module.yml,_body.md,resources/…}`；已存在同版本不覆盖。
- 参数与层级：`apply_module_parameters(text, defaults, values)`（声明默认 → 调用方值 → 未声明保留字面值；围栏内不替换）、`shift_headings(text, offset)`（1～6 截断并提示，源模块不改）。
- 资源与来源：`resolve_module_asset`、`rewrite_resource_paths(text, mapper)`、`relative_asset_display`、`parse_doc_items`（`<!-- DOC-ITEM: id | 标题 -->`）、`missing_module_placeholder`、`missing_resource_placeholder`。

### `doc_tool/application/content/module_refs.py`（固定引用/复制编辑/展开/实例）

- 稳定语法：
  - 固定引用 ``` ```doc-module id=<id> version=<version> slot=<slotId> [headingOffset=<n>] ``` + 参数行 `name=value`；
  - 复制编辑 ``` ```doc-module-copy slot=… version=… source=… ``` + 复制时正文 + 来源注释；
  - 项目装配 `reuse/assembly.yml`（slotId/moduleId/version/chapter/params/headingOffset），实例映射 `reuse/instances.yml`（instanceId/slotId/originItemId/moduleId/version/chapter/included）。
- 扫描与生成：`scan_directives`、`strip_directives`、`canonical_directive`、`canonical_copy_block`、`parse_attrs`、`new_slot_id`。
- 展开：`resolve_body(text, project_root=…, library=…, variables=…, host_path=…, asset_root=…, cache=…, max_depth=5, slot_overrides=…, strict=False)` → `Resolution{text, segments, warnings, errors, slots, dependencies, copies}`；每段带 `SourceLocation(moduleId, version, slotId, moduleDir, hostLine, hostPath)`、`resources`、`dependencyHashes`；取模块顺序为**项目固定副本 → 库中同版本缓存 → 可读占位**；`ResolutionCache` 按输入签名缓存，保证预览/Word/HTML/检查同源。
- 升级：`module_difference(current, target)`、`plan_upgrade(assembly, module_id, current, target)`、`apply_upgrade(assembly, plan, slot_ids=…)`（只改明确选中的 slot，`AssemblySlot.with_version` 返回副本，原配置可回退）。
- 实例：`InstanceBook(project_root)`：`register/include/exclude/refresh_positions/by_slot/instance_for/instance_id_for/pruned/coverage/save/load`；`include_items_in_tracking(book, resolution, slot_ids=…)`（明确纳入才登记）、`tracked_copies`、`coverage_of`。

### `doc_tool/application/content/variants.py`（产品变体与展开副本）

- 配置：`Variant`（variantId/name/include/exclude/variables/slots/modules）、`VariantsConfig.load`（schema 1，缺失/损坏回退空配置）、`VariantsStore`（`variants.yml` 读写）。
- 有效内容：`effective_chapters(discovered, declared, variant)`（项目顺序 → include/exclude，越界项忽略并提示，空前回退全部）、`effective_variables`、`effective_slot_overrides`（slot 精确 → `module:<id>` → `*`）、`variant_scope`、`unknown_variant_message`（列出可选项，不偷偷换型号）。
- 出稿：`expand_document_variant(...)`、`variant_output_dir`、`build_variant_outputs(... variant_ids=[...])` → 每个 variantId 独立目录，记录章节/变量/模块版本/hash/宿主、`variant_report`、`coverage_note`。
- 展开兼容副本：`write_expanded_copy(...)` → 普通 Markdown + 资源（按章节相对路径）+ `_copy.yml` + `README-展开副本.md` + `_index.md`；`verify_portable_copy(root)` 自检所有本地引用在副本内可用（可搬目录打开）。

## 4. 产物路径

- 服务：`doc_tool/application/content/modules.py`、`module_refs.py`、`variants.py`
- 测试：`scripts/tests/test_v30_content_reuse.py`（36 项）
- 项目内 sidecar（运行时生成，不是本次提交物）：`reuse/assembly.yml`、`reuse/instances.yml`、`reuse/modules/<slug>/<version>/`、`variants.yml`
- 夹具：`tmp/core-scratch/<prefix>-<pid>-<n>/`（`cleanup` 由测试 teardown 处理）

## 5. 正常与兜底行为（已测）

| 场景 | 正常 | 兜底 |
|---|---|---|
| 固定引用 | 项目固定副本展开，来源定位到模块与宿主章节 | 缺项目副本 → 库同版本缓存（warning）；两者都无 → `【待补充：模块 x@y 未找到固定副本】`，其余正文继续 |
| 参数 | slot/装配提供值生效；`module.<name>` 变量可传入 | 缺参数用声明默认值并 warning；未声明键保留 `{{module.<name>}}` 字面值 |
| 层级 | `headingOffset` 只改输出层级 | 越出 1～6 截断并提示，源模块不变 |
| 循环/深度 | 嵌套模块逐层展开（上限 5） | 循环只停止该引用并输出 `【已停止：…循环引用…】`，其余正文与其他章节继续 |
| 资源 | 按模块固定副本改写为可用相对路径，随副本落地 | 缺失保留占位并 warning；展开副本自检报出缺失目标 |
| 版本 | 同版本不同内容 → 候选 `1.0.0-2`，旧版本保留 | 库索引损坏 → `index_error` 并按目录重建；库缺失 → 空库 + 提示 |
| 变体 | 显式 include/exclude + 变量/slot 版本覆盖，独立目录输出 | 坏章节项忽略并提示；空前范围回退全部；未知 variantId 只报错不构建别的型号 |
| 副本 | 普通 Markdown + 资源 + 清单，可搬目录 | 副本缺失目标由 `verify_portable_copy` 逐条报出 |
| 严格 | — | `resolve_body(strict=True)` 把缺项写入 `errors`（`is_clean()` 为假），默认宽松只给 warning |

## 6. 验证命令与退出码

在仓库根执行（真实结果）：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path; python scripts\tests\test_v30_content_reuse.py
```

- 结果：`Ran 36 tests` → `OK`，退出码 `0`（本次多次全量运行均通过，最后一次 117.2s；文件末尾有 `if __name__ == '__main__': unittest.main(verbosity=2)`）。
- 变异自检（确认断言真实有效，测后已还原源码）：
  - 去掉 `shift_headings` 调用 → `test_heading_offset_shifts_levels_and_clips` 失败（`### 通用术语` 未出现），退出码 1；
  - 去掉副本引用改写 → `PortableCopyTests` 3 项失败，退出码 1；
  - 候选版本号改为原版本 → `test_same_version_different_content_keeps_old_and_saves_candidate` 失败，退出码 1；
  - 还原后重跑全部通过。
- 只运行本文件，未运行整套测试（节省时间）。

## 7. 本轮发现并修掉的真实缺陷

1. 模块资源解析基准单一：章节里的 `images/x.png` 实际在 `assets/<类型>/`，只按内容根查找会误判缺失 → 增加 `resource_roots`/`base_dir`/递归回退，并按项目相对路径记录。
2. 未声明参数被当作可替换值 → 违反“只有声明键可填写”，改为保留字面值并提示。
3. `Resolution.warnings` 丢失段级提示（缺参数/标题偏移） → 段级 warning 汇总进 `Resolution`。
4. `parse_doc_items` 拒绝带连字符的条目 ID（`REQ-TERM-01` 解析为空）→ 正则放宽，实例追踪得以成立。
5. 展开副本资源随目录层级失效 → 资源按“相对该章节文件”的路径落地并改写引用，`verify_portable_copy` 归零。
6. `AssemblySlot` 缺少 `with_version`，选择性升级不可用 → 补齐（原配置不被就地修改）。

## 8. 未验收项

- GUI 入口（引用/复制编辑/查看来源/纳入追踪、库页面、升级与变体选择）：未实现。
- CLI `reuse list/show/import/export` 与 `build/check --variant`：未实现。
- 预览/检查/Word/HTML 管线接线与题注注册表：未接线（resolver 与副本已就绪，接口为 `Resolution`）。
- 离线包（模块导出/导入 + 非法附件跳过 + 原库保留）已有实现但本轮未加专项测试，`2.4` 未勾选。
- 三公开示例模块、两文档/两型号离线和换目录试点、实机 Word/冻结检查：未执行。
- v1/v2 无复用项目全量回归、发布号与归档（30-G）：未执行。
- 副本的 `assets/` 兜底分支（源资源不在项目根内时）无测试覆盖。

## 9. 下一任务

1. `2.4`/`2.5`：为 `import_module`/`export_module` 补非法附件、缺资源、原库保留测试，并提供三个公开示例模块。
2. `3.4`：把 `resolve_body`/`Resolution` 接进预览、检查、Word、HTML 与题注注册表，验证跨入口一致。
3. `5.2`/`5.3`/`6.4`：项目/工作区与 CLI 的变体选择、按 variantId 隔离的输出目录与机器报告。
4. `4.4`：把实例映射接进条目索引/影响/集合，补删除与悬空待处理测试。