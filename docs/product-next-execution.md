# 当前 V4.0～V4.3 执行入口与历史台账

更新：2026-10-03。最新读取 HEAD `7ba19dd`；MAIN/V3.7～V3.9 已勾选 **75/84**，余下九项按真实依赖分别补验收。当前新增队列 **V4.0→MAIN2→V4.1→V4.2→V4.3**，26 批/104 项、实施 0/104。先完成已有执行中的批次，再从 **40-A 1.1** 接续。见 [新路线图](product-v40-v43-roadmap.md)、[新台账](product-v40-v43-execution.md)、[完整持续指令](product-v40-v43-execution-prompt.md)。 旧RD/V3.4～V3.6已80/84，修复见 [实施后报告](product-post-implementation-review-20261003.md)，MAIN/V3.7～V3.9见 [实际台账](product-v37-v39-execution.md)。

## 1. 前次已实施四包（历史记录）

| 包 | 任务入口 | 已勾选 | 自动证据 | 保留未完成项 |
|---|---|---|---|---|
| RD | [product-rd-workspace-experience](../openspec/changes/product-rd-workspace-experience/tasks.md) | 23/24 | [原相关回归](../analysis/product-rd-workspace-20261003/rd-related.xml) | 6.3 真实桌面/Word 试点 |
| V3.4 | [product-v34-table-authoring](../openspec/changes/product-v34-table-authoring/tasks.md) | 19/20 | [原相关回归](../analysis/product-v34-table-20261003/v34-related.xml) | 5.2 真实 IME/剪贴板 |
| V3.5 | [product-v35-standard-pack-authoring](../openspec/changes/product-v35-standard-pack-authoring/tasks.md) | 19/20 | [原相关回归](../analysis/product-v35-pack-20261003/v35-related.xml) | 5.3 企业底模/Word 试点 |
| V3.6 | [product-v36-large-document-performance](../openspec/changes/product-v36-large-document-performance/tasks.md) | 19/20 | [原相关回归](../analysis/product-v36-large-document-performance/v36-related.xml)、[同机基准](../analysis/product-v36-large-document-performance/benchmark.json) | 5.3 真实大项目/Word 量测 |

独立台账：[RD](product-rd-workspace-execution.md)、[V3.4](product-v34-table-execution.md)、[V3.5](product-v35-standard-pack-execution.md)、[V3.6](product-v36-large-document-execution.md)。原范围21批/84项是规划总量，不是剩余开发量，不能从四包0/84重做。V3.6 性能目标部分达成：重复解析 -100%、1000章节 p95改善31.7%，300章节改善13.7%未达30%目标。

## 2. 前次修复验收（历史证据）

已修正真实表格按钮、空值/撤销/定位，规范草稿与当前冻结、未知资源与消费清单、独立样例与旧轮重试、小窗口/深色布局及历史报告覆盖数。证据：本次 [27文件/552用例相关回归](../analysis/product-post-review-20261003/related-final.xml)、最后 [4文件/75用例规范回归](../analysis/product-post-review-20261003/pack-export-final.xml)、[7项报告回归](../analysis/product-post-review-20261003/handover-final.xml)。

这些专项有重叠，当前默认172文件没有在本次全部重跑。真实环境缺口继续单列，不阻断新队列的独立编码。

## 3. 当前后续范围

| 包 | 主要成果 | 批次/任务 | 当前实施 |
|---|---|---|---|
| V4.0 | 回归事实、Word有界执行、取消/关闭/恢复与成果 | 5/20 | 0/20 |
| MAIN2 | 导入/源修订/当前章节与图片/最终成品主线优化 | 6/24 | 0/24 |
| V4.1 | 本地企业模板、受支持预设、小样/更换与消费 | 5/20 | 0/20 |
| V4.2 | 同机量测、正确增量、问题/规则/成组修正 | 5/20 | 0/20 |
| V4.3 | 交付准备、成员成果、版本比较、接收人包/副本 | 5/20 | 0/20 |

共26批/104项，五个change规划完整、strict valid、apply ready。正常40-A 1.1；V4.0后先 [MAIN2主线优化](product-mainline-optimization.md)，任务/证据更新 [联合台账](product-v40-v43-execution.md)。旧 [CORE](product-core-workflow-execution.md)、[V3.0～V3.3](product-plan-v3-execution.md)、[V2](product-plan-execution.md)、[MAIN/V3.7～V3.9](product-v37-v39-execution.md)台账保留，已实现部分不重做。

## 4. 每批记录

```text
日期 / HEAD / change / 批次 / 当前工作树：
完成编号 / 实际入口与内容成果：
复用服务 / 补的真实差额：
来源与范围 / 当前缓冲 / 原文件事实：
UI主题/尺寸/状态/键盘/返回及证据：
兜底 / 局部待处理 / 未执行：
相关命令 / 环境 / 退出码 / 测试与性能证据：
实机Word/IME/团队已测与未测：
下一直接任务 / 可继续项：
```

每批按实际结果更新独立台账和任务；缺环境只影响对应验收。保留来源摘要、原数据和成功状态断言，不为通过而删掉有效验证。
