> 入口：`docs/product-plan-v3.0-v3.3.md`。顺序 32-A→G，直接依赖管线/集合/变体解析。默认逐项继续、Word 串行、用户主动提交/继续，无服务器部署前置；证据写 V3 台账。

## 1. 批次数据和适配（批次 32-A）

- [x] 1.1 核对现有 TaskRunner/TaskSpec、pipeline/OutputState、集合及变体 API，记录需补适配与当前 CLI
- [x] 1.2 定义 schema 1 批次计划/job/attempt/result 和可恢复状态，不重定义正式成功事实
- [x] 1.3 实现项目/工作区/变体/格式计划解析与正常默认值，非法成员只影响该项并集中提示
- [x] 1.4 建立三项目（含一个坏格式）+ 两变体成员 + 断网/无 Word 夹具：坏格式成员单独失败其它继续、断网下批次照常出稿、无 Word 全部转待刷新且可读副本保留、原单项目入口在批次之外保持兼容（`scripts/tests/test_v32_entry_points.py` 4 项）

## 2. 持久本地队列（批次 32-B）

- [x] 2.1 实现用户级原子 job store、requestId 去重和 attempt 历史，正文快照与日志范围明确
- [x] 2.2 串行编排复用 TaskRunner 且**逐项进度已接线**：`gui_tasks.run_plan_task/retry_unfinished_task` 声明 `on_event`，TaskRunner 自动注入；队列 per-item progress 经 `_QueueProgressRelay` 转成 `delivery:<stage>` 阶段事件（含 jobId/成员/变体 metrics）推给 Dock。`test_v32_delivery_progress.py` 5 项（含真实 TaskRunner 端到端注入 + 取消令牌）
- [x] 2.3 本应用跨进程 Word 占用标识已**接入生产路径**：队列在真正驱动 Word 前 `word_busy.acquire`（本应用其它进程持有时本项转待刷新并给出原因），执行结束（含异常）`release`，TTL/进程存活校验兜底崩溃；`test_v32_word_busy_retry.py` 9 项含 2 项生产路径补测（运行期标记存在、结束即释放、他人持有→转待刷新）
- [x] 2.4 临时幂等故障自动重试一次：仅对 OSError/TimeoutError（文件占用/临时不可写）自动重试 `AUTO_RETRY_LIMIT=1` 次并记录 `autoRetries`/说明；内容与参数类失败不重试（同套件 7 项）
- [x] 2.5 测试重复点击/中断/恢复/部分失败/重试/取消与 store 损坏，已生成结果不丢

## 3. 可携带交付包（批次 32-C）

- [x] 3.1 定义 package manifest 的来源/版本/variant/input digest/产物/hashes/pendingStages/完整性
- [x] 3.2 包内容复用 V2.9 集合包装：`delivery/collection_bridge.py` 复用 `collection.collect_files/build_manifest/register_manifest` 与 `collection_ops.export_package`（跳过 .git/缓存/虚拟环境并分类），交付包内落 `collection-manifest.yml` 并在包清单给出 `collection` 摘要（`test_v32_collection_bridge.py`）
- [x] 3.3 生成可读包索引/报告及现有状态 adapter，DOCX/HTML/PDF 各格式状态独立
- [x] 3.4 包版本不符回退阅读/导出：`delivery/package_version.py` 判定只读回退（版本高/低于当前），`verify_delivery_package` 对回退包返回 ok+readableOnly 并列出可导出产物，`formalize_package` 明确拒绝（status=readable-only）并提示升级/回原机（`test_v32_package_version.py`）
- [x] 3.5 旧包/同名/非法附件场景：包内路径全相对且无 .git/凭据/用户配置；越界成员（`..`、绝对路径、盘符）判不可用；坏 ZIP 报错不抛；同名资源按内容 hash（既有 31-C 包测试）

## 4. 换机刷新与登记（批次 32-D）

- [x] 4.1 实现 promote_package 校验与包工作副本，复用 Word 刷新/后校验/audit，不依赖原电脑项目路径
- [x] 4.2 快照文档版本与变体**真正固定**：`ExportRequest.variant_id` 贯通出稿，`capture_snapshot(..., variant_id=...)` 用 `variants.expand_document_variant(write=False)` 把变体的有效章节/变量/模块版本物化进快照（未纳入章节同时记为 omitted），队列 `BatchJob.request()` 与交付包分别记录 `variantId` 与 `variantApplied`；未知变体只提醒并按项目当前内容继续（不阻断）。源后来变化仍只提示时点（`test_v32_variant_export.py` 5 项）
- [x] 4.3 本地包+digest+目标登记去重，失败回滚正式元数据/文件并保留新 DOCX 安全副本
- [x] 4.4 无 Word/刷新失败保留 waiting-refresh 包，严格未满足仍给参考产物，原包不删除
- [x] 4.5 真实 Word 用例已跑通（`V32_REAL_WORD=1` + `test_v32_real_word_formalize.py` 3 项）：包内快照真实刷新并后校验通过、OutputState 判定正式、登记写入、原包与源项目保留；期间修复两处真实缺陷（正式状态未随目的小写入、Word 探测 10 s 超时误判）

## 5. 结果中心与选择归档（批次 32-E）

- [x] 5.1 计划预览与结果页除摘要外，**「显示详细信息」渲染逐成员/变体/格式/状态/路径**：结果负载新增 `memberRows`（`gui_hooks.MemberRow.to_dict()`），`_delivery_member_lines()` 逐条列出成员（变体）｜状态｜可用格式数 + 每个格式的状态与产物路径（缺失标注）；计划预览列出成员｜变体｜格式｜状态。`test_v32_delivery_progress.py` 中的渲染用例断言明细含成员/格式/状态/路径
- [x] 5.2 结果页提供「只重试未完成项 / 补刷新（正式稿）/ 打开首个产物 / 打开结果目录」；补跑使用队列内原轮快照，不重走已完成成员（`test_v32_delivery_ui.py` 8 项）
- [x] 5.3 选择归档完整集合登记复用 V2.9：归档后按集合清单登记；**部分范围不登记完整基线**（`complete=False`、`registrationPath` 清空并注明），缺失路径列 missing（同套件 7 项）
- [x] 5.4 选择归档与路径换名用例在 `test_v32_batch_delivery.py`（选择归档/部分范围）与 `test_v32_collection_bridge.py`（集合登记/安全 ZIP）；状态完整性见 `test_v32_delivery_ui.py`；无 Word 与部分失败不中断见 `test_v32_entry_points.py`（审计更正：原引用 `test_v32_delivery_entry.py` 有误）

## 6. 批次 CLI 和流水线（批次 32-F）

- [x] 6.1 CLI delivery run/status/retry/package/promote 接同一编排，YAML/JSON 计划和 --strict 显式策略
- [x] 6.2 复用 human/JSON 输出，操作退出码 0/1/2 与 status 查询契约一致，逐项状态/exitCode 清楚
- [x] 6.3 提供 Windows 无 Word 生成包→另一 Word 机处理的本地流水线示例，平台按实测声明
- [x] 6.4 `test_v32_delivery_entry.py`、`test_v32_delivery_batch*.py`、`test_v32_delivery_ui.py` 已注册进 `run_tests.py`；示例脚本扫描无 upload/publish/notify/http 调用

## 7. 批量试点与版本收尾（批次 32-G）

- [x] 7.1 直接套件与全量回归已跑；A32-1～6 逐条留证（A32-4 由真实 Word 用例补齐），见 docs/product-v32-execution-entry.md 的 A32 场景表
- [x] 7.2 10 成员批次实测（本机脱敏夹具，`measure_v32_batch10.py`）：**总耗时 81.6 s（约 8.2 s/成员）**、产物 337,508 B、队列存储 44,127 B；1 个坏成员失败后修复再续跑只重跑 1 个成员（6.7 s），总数 10 全部完成、尝试记录 11 条。结构数字可精确复现；耗时随机器负载差异大（隔离约 82～87 s、并发约 125 s）。**更正**：此前记录的 10.88 s / 1.09 s 为异常偏快值（疑暖缓存），不作为优化预算基线（见 `docs/product-v3-audit-findings.md`）
- [x] 7.3 真实 Word 与换机等效验证：真实 Word 正式化通过；包复制到独立目录树（等效另一台机器）后仍可正式化并登记；重复正式化幂等。真实两台物理机器交接与缩放检查单列待验收
- [x] 7.4 批次/交付包/CLI/流水线/恢复说明与版本源已更新（`docs/product-v30-v33-usage.md` 第 2、4 节），版本源保持 2.9.0、V3.2 发布号留待同批发布时确定；冻结冒烟实测通过（同上），并复核冻结 CLI 含 V3 命令：`delivery-plan/delivery-run/project-export --help` 均 exit 0
- [ ] 7.5 OpenSpec 校验和任务/台账证据核对，全部验收满足后同步/归档，本地成果可审阅
