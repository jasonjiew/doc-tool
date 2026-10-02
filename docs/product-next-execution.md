# RD / V3.4～V3.6 执行台账

计划日期：2026-10-01。统一入口：[产品总路线图](product-master-roadmap.md)，能力现状：[功能清单](product-function-catalog.md)，默认策略：[流程与兜底](product-flow-fallback-policy.md)。

本轮完成 4 份 proposal、4 份 design、9 份 specs、4 份 tasks。新增业务功能未实施、业务测试未运行。4 个 change 的 OpenSpec strict 均通过，status 均为 4/4 artifacts complete；仅说明规划可用于实施。

规划完整性检查通过：26 份相关 Markdown、46 个本地链接有效；84 个任务编号在各包内唯一，21 批均为 4 项，9 个 capability 与 spec 目录一致，新增实施勾选全为 0。新文档无行尾空格，历史 README 的 Markdown 换行写法保留。

## 计划状态

| 包 | change / 任务入口 | 批次/任务 | 实施起始状态 | 自动验收 | 实机 | 下一任务 |
|---|---|---|---|---|---|---|
| RD | [product-rd-workspace-experience](../openspec/changes/product-rd-workspace-experience/tasks.md) | 6/24 | 0/24，规划就绪 | 未执行 | 未执行 | RD-A / 1.1 |
| V3.4 | [product-v34-table-authoring](../openspec/changes/product-v34-table-authoring/tasks.md) | 5/20 | 0/20，规划就绪 | 未执行 | 未执行 | 34-A / 1.1 |
| V3.5 | [product-v35-standard-pack-authoring](../openspec/changes/product-v35-standard-pack-authoring/tasks.md) | 5/20 | 0/20，规划就绪 | 未执行 | 未执行 | 35-A / 1.1 |
| V3.6 | [product-v36-large-document-performance](../openspec/changes/product-v36-large-document-performance/tasks.md) | 5/20 | 0/20，规划就绪 | 未执行 | 未执行 | 36-A / 1.1 |

新范围合计 21 批/84 项。每批 4 项，任务编号在每个 change 内唯一。实时勾选只由对应 tasks 维护；本表起始数不覆盖其他实施任务的后续记录。

旧范围继续使用 [CORE 台账](product-core-workflow-execution.md)、[V3.0～V3.3 台账](product-plan-v3-execution.md)、[V2 台账](product-plan-execution.md)，不合并重置。

## 每批交接记录

```text
日期 / 执行 HEAD / 工作树基准 / 包 / 批次：
完成任务编号 / 当前 tasks 勾选：
复用的真实服务与直接依赖 / 本批补的差额：
用户入口 / 操作步骤 / 实际结果 / 产物位置：
来源模式 / captureId / projectId-itemId / 源与缓冲事实：
默认正常 / 自动兜底 / 待完善 / 未执行：
相关验证命令 / 环境 / 退出码 / 报告：
Word、剪贴板、冻结、视觉或性能实测证据：
已有失败分类 / 环境缺失 / 剩余风险：
下一直接任务 / 阻塞动作与可继续动作：
```

实施记录不可把规划 strict 通过作为用户功能验收。真实试点环境缺失单列，对应未完成任务保留；无关任务继续。RD-A 的历史失败先复现/分类，再记录确认修复，不改弱数据保护和成功状态。
