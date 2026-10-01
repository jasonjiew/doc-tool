## Context

当前工作树已有 `pipeline.run_pipeline`、`OutputState(formal,diagnostic,...)`、`TaskRunner/TaskSpec`（`ui/task_bridge.py`）和 V2.9 collection/collection_ops。V2.6 有填充最近任务，V2.7 有待刷新可读产物；这些不是持久批量队列或可携带正式化包，本版在其上增加编排。旧 phase3 的 staged/promote 严格源树匹配方案按本版固定快照和默认兜底重新规划。

## Goals / Non-Goals

**Goals:** 多项目/变体一次提交、逐项得到结果，中断可继续；固定产物可换机补刷新和正式登记；GUI/CLI 同源。

**Non-Goals:** 服务器常驻调度、远程 Word SaaS、Linux 排版引擎、强制计划任务、自动公开发布。只有用户提交/继续的任务运行，普通单项目操作仍可用。

## Decisions

### D1：本地持久编排，执行复用当前服务

批次计划 schema 1 含 batchId、entries（project/workspace 路径、variantId、目标格式、输出目录、所选严格策略）。用户级 job store 保存 jobId、batchId、requestId、输入快照位置/digest、attempts、phase、结果路径和时间；正文快照在任务目录，记录不含凭据。

状态为 queued/preparing/running/waiting-refresh/completed/completed-with-warnings/partial/failed/cancelled/interrupted。先串行执行，复用 TaskRunner 事件/取消和单项目管线/集合，不另建业务流水线。Word 刷新使用本应用跨进程占用标识且串行；忙时排待刷新，其他离线任务继续。不操作用户自己的 Word 会话或其他应用进程。

同一次提交 requestId 去重；已有已完成成员默认跳过，用户选择只重试失败/待刷新项。重试产生新 attemptId 并保留旧结果；暂时且幂等故障最多自动重试一次。启动时将未知 running 标 interrupted，检查已落盘结果后用户一键继续，而不是无条件重复正式登记。

### D2：快照包可读也可继续处理

新增独立 delivery-package manifest schema 1：packageId、origin project/workspace ID、文档版本、variantId、capturedAt、应用/支持格式版本、输入和产物相对文件清单/hashes、报告、结果完整性及 pendingStages。内容含 DOCX、构建必需正文/底模/固定模块/变量/规则/资源和阅读索引；复用 V2.9 安全打包，只收必要文件，项目 Git、用户凭据和无关缓存不入包。

OutputState 的 formal/diagnostic 语义不重新定义；包/队列的可用状态通过 adapter 展示，不为此创造另一套“正式成功”判定。无 Word 时可先得到 DOCX/HTML，PDF 不可用只标 PDF 待处理。格式失败影响该成员的对应格式，不撤销其它成果。

### D3：对原快照补刷新，不追逐当前源

接收机 `promote_package()` 校验合法 manifest/hashes，准备该包的工作副本，用现有 Word 刷新 adapter、后校验、audit 和安全登记产生新输出。正常无需重新从 Markdown 全部生成，也不需要原电脑项目路径。其正式版本/variant 与输入 digest 来自包，来源项目后来变化只提示“本次为捕获快照”，不拒绝历史快照正式化。

旧包支持版本不匹配可退为阅读/导出，缺个别资源可按原报告继续可读结果；已损坏 DOCX 不进入 Word，保留其它合法产物，若具备完整构建输入可另尝试重建。Word 不可用/刷新失败，包保持 waiting-refresh，后续再试；原包不删除。严格检查未满足保留可读参考结果，不登记严格正式通过。

### D4：结果和登记可恢复

本地登记键为 packageId+输入 digest+目标位置，已存在相同正式结果可直接打开而不重复建历史；不承诺跨机器无共同记录的全局去重。登记失败回滚正式文件/元数据并保存新 DOCX 安全副本。重复输出路径默认新文件名，完整集合登记继续复用 V2.9 原子事务。结果索引显示每成员/格式/变体的路径、状态、降级和下一动作，汇总不会把 partial 标 complete。

### D5：最小自动化接口

CLI 新增 `delivery` 子命令组 run/status/retry/package/promote，run 读 YAML/JSON 批次计划并可显式 --strict；报告选项复用 --output human|json。参数路径/原有 --output 文件路径不被挪作别义。run/promote 默认 0=至少得到所请求范围内的可用结果（可 partial/待刷新），1=无可用方案/严格未满足，2=参数/运行失败；status 为只读查询，正常含失败任务也返回 0，报告逐项 exitCode/status。

流水线示例先覆盖 Windows 无 Word runner→保存交付包→有 Word 的本地机器人工运行 promote。其他操作系统只有验证后写支持范围，不把旧提案的 Linux 支持当成事实。工具只生成包和脚本示例，上传/通知/发布由调用方明确触发。

## Risks / Trade-offs

- [重复执行生成重复正式记录] → request/attempt 和本地登记键，恢复先核对结果再继续。
- [Word 不稳定拖住批次] → 串行独立阶段、忙/超时转待刷新、其他成员继续。
- [跨机路径/字体差异] → 包相对路径与固定输入，记录实际环境/字体降级，不声称分页必然相同。
- [队列规模造成复杂调度] → 首版串行及按成员继续，按实测再考虑并行。

## Migration Plan

队列和包独立 schema 1，旧单项目命令、状态和填充任务记忆不迁移；新队列可从现有项目/工作区生成计划。旧 staged 类结果无完整快照时标 legacy/read-only，不伪装可正式化。旧应用可阅读已生成 DOCX/HTML。版本收尾根据当时代码核对版本源。

## 验收标准

- A32-1：三项目/两变体提交后逐项可见，个别失败继续，结果索引没有混淆输出。
- A32-2：中断后只续未完成项，重复点击和重试不重复正式登记；取消保留已有结果。
- A32-3：无 Word 得到自足待刷新包，换目录/机器可以阅读；源后来修改不破坏固定快照处理。
- A32-4：真实 Word 机可补刷新/后校验并登记，重复处理幂等，失败保留包和参考 DOCX。
- A32-5：缺 PDF/坏可选资源/Word 忙默认部分结果，严格模式单测，上一正式记录一致。
- A32-6：GUI/CLI 对同计划同状态，JSON/stdout 可解析；Windows 无 Word 流水线示例实测可用。

## Open Questions

无阻止开发的产品决策。首版串行，支持平台只按执行时事实登记；Word/font 真实环境影响对应实机验收，不阻止队列/包服务开发。
