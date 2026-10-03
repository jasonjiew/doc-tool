# V3.6 大文档性能执行台账

更新日期：2026-10-03（Asia/Shanghai）。执行基准 HEAD `d68b514` + 工作树。任务勾选只由 [V3.6 tasks](../openspec/changes/product-v36-large-document-performance/tasks.md) 维护。统一入口见 [总路线图](product-master-roadmap.md)。

策略按要求执行：**先同机真实基准 → 找实际瓶颈 → 再做增量复用**。缓存是可丢弃的派生数据，业务记录（条目 ID、关系、评审、版本集合）永不以缓存为权威；缓存关闭/损坏时行为与直接读取一致。

## 1. 批次状态

| 批次 | 状态 | 证据 |
|---|---|---|
| 36-A 性能基准 | 完成 1.1～1.4 | [同机基准](../analysis/product-v36-large-document-performance/benchmark.json)、[测量脚本](../scripts/perf/v36_benchmark.py) |
| 36-B 增量索引 | 完成 2.1～2.4 | [相关回归](../analysis/product-v36-large-document-performance/v36-related.xml) |
| 36-C 捕获与装配集成 | 完成 3.1～3.4 | 同上 |
| 36-D 可交互视图 | 完成 4.1～4.4 | 同上 |
| 36-E 对照验收 | 5.1、5.2、5.4 完成；5.3 真实大项目/Word 试用待验收 | 同上 |

## 2. 同机基准与实测结果

环境：Windows 11（10.0.22631）、Python 3.12.14、12 逻辑核、AMD64；每阶段 5 次样本，冷/热分别统计（median / p95）。样例为确定性生成：每章含标题、段落、普通表格、条目标记。

| 样例 | 文件数 | 条目 | 正文字节 | 索引冷启动 median | 增量刷新 median | 旧全量刷新 median | 解析次数（增量 / 旧） |
|---|---|---|---|---|---|---|---|
| 50 章节 | 101 | 600 | 102,834 | 0.147s | 0.111s | 0.168s | +0 / +101 |
| 300 章节 | 601 | 3,600 | 617,034 | 0.917s | 0.787s | 0.944s | +0 / +601 |
| 1,000 章节 | 2,001 | 12,000 | 2,056,934 | 2.703s | 2.095s | 3.010s | +0 / +2,001 |

其他阶段（1,000 章节 median）：检索全量 0.018s、单章预览 0.0002s、检查 2.756s、出稿源阶段（HTML）14.06s；索引构建 Python 追踪峰值内存 8.05 MB。观测数据只含计数/时长/摘要，不含正文（测试断言）。

**瓶颈判定**：重复刷新时"全部失效后重建"导致每条文件重复解析——这是可消除的真实重复解析；绝对耗时最大的阶段是出稿装配与检查（属于 CORE/RD 既有链路，本版不改变其语义）。

## 3. 目标达成情况（如实记录，不虚报）

| 目标 | 实测 | 结论 |
|---|---|---|
| 目标热路径解析次数减少 ≥70% | 重复刷新解析次数由 N 降为 **0**（-100%） | 达成 |
| 中大样例热路径 p95 改善 ≥30% | 1,000 章节 p95 2.116s vs 3.039s = **-30.4%**（三次同机运行 30.4%～31.7%，稳定达标）；300 章节 p95 0.968s vs 1.434s = **-32.5%**（三次同机运行区间 13.7%～34.2%，**波动跨过 30% 阈值**） | **大样例达成；中等样例不稳定**，见下方离散说明 |
| 小样例 p95 不恶化 >10% | 50 章节 p95 0.113s vs 0.172s = -34.4% | 达成（实际改善） |

离散与噪声说明（按要求报告，不外推为 SLA）：同一台机器、同一输入下重复三轮 5 样本基准，300 章节的中位改善分别为 13.2%、27.7%、16.6%，p95 改善分别为 13.7%、34.2%、32.5%；该规模下耗时由"内容摘要读取 + 目录遍历"主导（本卷存在文件过滤驱动，单文件打开开销明显），解析节省的绝对时间占比小，因此改善比例随机器负载波动并跨过 30% 阈值。1,000 章节三轮 p95 改善为 31.7%、31.1%、30.4%，稳定达标；50 章节三轮均改善 16%～34%，无退化。结论：**解析次数目标确凿达成（-100%），耗时目标在大样例达成、中等样例不稳定**；不修改既定目标，也不据此宣称所有规模加速。

## 3.1 捕获作用域索引与装配指纹（36-C 3.1 / 3.2）实现要点

- `application/effective_snapshot.py`：`EffectiveSnapshot.captureIndex` 记录本轮捕获每章真实内容摘要（relPath → sha256），进入索引与 `to_dict`，供派生索引按 captureId 判定复用。
- `incremental_index.capture_index_service()`：构造捕获作用域索引——缓存条目按 `captureId` 隔离（不同捕获不得互用）；`override_texts` 中的未保存缓冲只用内存文本与真实摘要，既不读磁盘也不写持久缓存。
- `incremental_index.chapter_assembly_fingerprints()` + `module_fingerprint()`：按章解析 V3.0 模块指令，把每个槽位的 `moduleId@version`、模块正文/参数默认值/资源摘要与槽位参数一起哈希；未引用模块的章节指纹为空，因此模块或变量变化只失效真正依赖它的章节（`ContentIndexService(per_file_fingerprint=...)` 接入缓存键）。
- 证据：`test_v36_large_document.py::CaptureScopeTests`（3 项）与 `ModuleFingerprintTests`（2 项）。

## 3.2 36-D 检索与列表视图（4.1～4.4）实现要点

- `content/search.py` 新增 `SearchService.search_progressive()` 与 `run_progressive_search()`：按文件分批扫描，用 `SearchProgress`（只含计数）报告“已扫描 M/N 文件、已找到 K 处”；取消时返回已获得命中并置 `partial=True`；结果带 `generation`/`projectId`/`captureId`。
- `ui/content/search_panel.py`：运行中显示「取消」按钮（点击立即确认并保留已找到结果）、扫描中只报“已找到”数量、完成后才给完整统计；结果按请求代次校验，旧代次结果不更新界面；兼容只实现 `search()` 的服务（旧调用方与测试替身）。
- `ui/content/workspace.py`：`context_provider` 提供 `projectId` 与本轮索引捕获标识 `captureId`（`index-N`，每次重建索引递增）。
- **章节首屏**（4.2）：`_render_first_screen()` 在后台解析开始前先用目录扫描渲染前 200 个章节，状态栏提示“已显示前 N 个章节（共 M 个），正在解析全文索引…”；`ContentIndexService.build(on_progress=...)` 按每 25 个文件回报“已解析 N/M 个章节”。
- **问题分页**（4.2）：`ui/content/lint_panel.py` 单页渲染 200 条并显示“显示更多…（已显示 N/M）”，状态栏给出“已显示前 N / 共 M 项”，筛选变化回到第一页，内容不截断。
- **内存与对象释放**（4.4）：基准脚本在索引释放后单独测量预览峰值，并报告 `indexPeakMB`/`previewPeakMB`/`retainedAfterReleaseMB`/`releasedRatio`；测试断言释放索引后回收大部分派生内存（本机 99% 以上）。

证据：`test_v36_large_document.py::ProgressiveViewTests`（4 项）+ `ProgressiveChapterTests`（5 项：进度计数、上下文事件转发、首屏渲染、问题分页、内存释放）。

## 4. 实现要点

1. `application/content/incremental_index.py`：`ChapterCache`（内容摘要 + 解析器版本 + 配置/装配指纹 + 容量清理 + 原子写 + 损坏重建 + 可关闭）与 `CaptureIndex`（未保存缓冲的本轮内存摘要）。
2. `content/index.py`：`ContentIndexService` 支持可选缓存与 `config_fingerprint`；`build()` 复用摘要一致文件的已解析行与标题；`refresh()` 改为**按内容摘要判定变化**的增量重扫（mtime/size 只作提示），删除条目随文件消失同步清理；暴露 `stats()`（解析/复用次数、缓存统计，不含正文）。
3. 无缓存、缓存损坏、版本不认识、写入失败、关闭缓存时一律回退直接读取源码；业务记录不受缓存影响。
4. `scripts/perf/v36_benchmark.py`：确定性样例 + 阶段计时 + 冷/热分布 + 计数 + 内存观测 + 旧全量刷新对照，输出 JSON 证据；作为观察脚本不进入默认测试清单。

## 5. 未完成项与原因

| 任务 | 状态 | 说明与继续条件 |
|---|---|---|
| 5.3 真实大项目与 Word 桌面试用 | 待验收 | 需真实大项目与 Word 环境；复验步骤：用真实项目跑 `scripts/perf/v36_benchmark.py` 记录源阶段与内存，再执行正式出稿记录 Word 阶段耗时与 OutputState |

环境证据（2026-10-03 本机实测）：`doc_tool.application.word_check.check_pywin32()` 返回 **False**，`import win32com.client` 失败（`No module named 'win32com'`）、`win32process` 不存在，因此本机无法执行 Word COM 自动化、真实剪贴板/IME 与 Word 视觉验收；这些项按要求保持未勾选。

## 6. 验证命令与证据

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:PRODUCT_V36_EVIDENCE='1'
$env:PYTHONPATH='D:/ai_develop_project_space/doc-tool/tmp/v26-test-deps'
$env:QT_QPA_PLATFORM='offscreen'
# 同机基准（5 次样本，冷/热与旧全量对照）
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/perf/v36_benchmark.py --sizes 50,300,1000 --samples 5 --out analysis/product-v36-large-document-performance/benchmark.json
# 正确性回归
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/tests/run_tests.py --junit analysis/product-v36-large-document-performance/v36-related.xml test_v36_large_document.py test_content_operations.py test_format_check_search.py test_v33_background_index.py test_authoring_services.py test_core_export_snapshot.py
```

- [同机基准](../analysis/product-v36-large-document-performance/benchmark.json)：50/300/1,000 章节，冷/热 5 次分布 + 旧全量刷新对照 + 解析计数 + 内存与对象释放（`memory` 字段；预览峰值在索引释放后经 `reset_peak()` 单独测量）。
- [内存对照（单样本）](../analysis/product-v36-large-document-performance/memory.json)：索引峰值 1.00/2.49/9.08 MB、预览峰值均约 0.03 MB、释放后残留 0.001/0.000/0.92 MB（释放比例 99.9%/100%/89.9%）。
- [缓存损坏兜底记录](../analysis/product-v36-large-document-performance/cache-corruption.json)：截断缓存被忽略并重建，直接读取兜底。
- 本包新增 `scripts/tests/test_v36_large_document.py` 31 项用例（缓存命中/失效、同大小修改、增删移、配置与解析器版本、损坏/关闭/写入失败、容量清理、捕获隔离、缓存与直接扫描结果一致、同轮预览/检查/出稿一致、取消后重试、基准脚本冒烟）。

## 7. 缓存使用与回退说明

- 缓存位置：`<项目>/.state/cache/content-index-v1.json`；可直接删除，下次访问自动重建。
- 关闭方式：构造 `ContentIndexService(content_root, cache=None)`（默认即为关闭）；关闭时不读不写，结果与直接读取一致（测试断言）。
- 版本与失效：`PARSER_VERSION` 变化、配置/装配指纹变化、内容摘要变化、文件新增/删除/移动均会失效对应条目；缓存条目另按 `captureId` 隔离，装配指纹可细化到“单个章节引用的模块”。
- 缓冲/变体内容：通过 `override_texts` 只用内存文本与真实摘要，不读磁盘、不写缓存（`capture_index_service`）。
- 应用内接入：`ui/content/workspace.py` 的 `_index_service_for()` 默认启用项目级缓存（`<project>/.state/cache/`），构造失败或缓存不可用时自动退回无缓存索引；`test_v36_large_document.py::test_workspace_index_service_uses_project_cache` 断言应用内服务命中缓存。

## 8. 全量回归中的测试适配（保持原断言意图）

全量回归（171 文件）暴露以下需要适配或修正的断言，均已按“保留原意图、允许新能力”调整并复验通过：

| 文件 | 原因 | 适配 |
|---|---|---|
| `test_ui_polish_toolbar.py` | V3.4 新增「表格网格/粘贴为表格」后，原“恰好 14 个动作”断言失效 | 改为断言原 14 个动作不丢失且相对顺序不变、且所有当前动作都有找回路径（宽窗口同排 / 窄窗口溢出菜单） |
| `test_word_release.py` | 当前 3.12 解释器没有 `win32process`（pywin32 为 3.13 构建） | 该 PID 提取用例 `skipUnless(pywin32 可用)`，其余 Word 释放用例继续执行 |
| `test_frozen_smoke.py` | 冻结包虽含 `win32com` 目录，但其依赖在当前解释器不可导入 | 仅当当前解释器能导入 `win32com` 时才断言冻结包可导入；lxml/PIL/yaml 断言保留 |
| `test_final_handover_report.py` | 交接报告每次生成的时间戳不同，原断言逐字比较导致跨秒偶发失败（与本包无关） | 比较前归一化“生成时间”行，其余内容仍逐字一致 |
| `test_v36_large_document.py`（本包） | 面板用例直接调用 `runner.poll()`，未走面板自身轮询，取消按钮收起依赖定时器 | 用例改走 `panel._poll()`；同时 API 在终态回调即收起取消按钮，不再依赖定时器 |

这些都是测试与环境的适配，不是产品缺陷：新增能力与可选依赖（前两项）、冻结包环境的 pywin32 缺失、时间戳/轮询时序假设。

全量回归（最终状态，含 36-C/36-D 补齐后）：`scripts/tests/run_tests.py` 默认清单 **171 个测试文件、0 失败、内部用例 2801 项**（1747s），报告 `analysis/product-full-regression-round2.xml`；此前一轮（本轮功能前）为 [171 文件 / 0 失败 / 2791 项](../analysis/product-full-regression-green.xml)。

## 实施后审查补记（2026-10-03）

已继承本包实现并补真实差额，范围、修复和验收见 [实施后报告](product-post-implementation-review-20261003.md)。本次相关回归27文件/552用例、最终规范回归4文件/75用例以及报告回归7用例通过；保留本包原实机未完成项，没有重置原勾选。当前新开发接 [MAIN+V3.7～V3.9](product-v37-v39-roadmap.md)，正常首项MAIN-A 1.1，已有批次先完成再插入；此前171文件全量为历史证据。
