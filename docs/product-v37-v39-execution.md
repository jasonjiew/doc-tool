# 主功能优化 + V3.7～V3.9 独立执行台账

日期：2026-10-03。范围依据 [主功能补充](product-main-workflow-optimization.md)及 [产品/UI/交互路线图](product-v37-v39-roadmap.md)，继承 [实施后修复](product-post-implementation-review-20261003.md)，完整指令见 [持续执行提示词](product-execution-confirmed-prompt.md)。

## 1. 当前状态

| 包 | 任务入口 | 规划状态 | 实施勾选 | 下一直接任务 |
|---|---|---|---|---|
| MAIN | [product-main-workflow-optimization](../openspec/changes/product-main-workflow-optimization/tasks.md) | 4/4 artifacts，strict 通过 | 0/24 | MAIN-A 1.1 |
| V3.7 | [product-v37-daily-workflow-ux](../openspec/changes/product-v37-daily-workflow-ux/tasks.md) | 4/4 artifacts，strict 通过 | 0/20 | MAIN可执行项完成后37-A 1.1 |
| V3.8 | [product-v38-authoring-and-exchange-ux](../openspec/changes/product-v38-authoring-and-exchange-ux/tasks.md) | 4/4 artifacts，strict 通过 | 0/20 | 完成 V3.7 可执行项后 38-A 1.1 |
| V3.9 | [product-v39-rd-workspace-productivity](../openspec/changes/product-v39-rd-workspace-productivity/tasks.md) | 4/4 artifacts，strict 通过 | 0/20 | 完成 V3.8 可执行项后 39-A 1.1 |

总范围21批/84项：MAIN六批24项加三版15批60项，尚未实施。各 tasks 为实时勾选唯一来源；本会话完成的是旧功能审查修复和新规划。旧四包 80/84 的四项实机缺口保留，新队列0/84是新增规划，旧四包80/84是既有实施；不能把两者混成需要重做的任务。

## 2. 批次交接模板

```text
日期 / HEAD / 当前工作树 / change / 批次：
实际完成编号 / tasks 当前勾选：
已有能力与本批真实差额：
真实入口 / 默认步骤 / 实际内容或成果：
UI 状态 / 主题 / 尺寸 / 焦点与返回 / 截图几何：
来源身份与范围 / 未保存正文与原件事实：
兜底与部分结果 / 局部待处理动作：
相关测试命令 / 环境 / 退出码 / 证据：
实机/Word/性能已测与未测：
下一直接任务 / 可继续项 / 外部条件：
```

## 3. 验证记录

规划已完成4份proposal、4份design、9份specs、4份tasks，84项均未勾选；`openspec validate <change> --strict` 四包通过。没有以规划校验代替新功能验收。

实施后新增各包记录，保留已有来源/身份/覆盖/成果状态断言。相关检查通过后继续下一批；包末运行当前默认回归并记录真实覆盖数量。真实桌面/Word/团队条件缺失仅保留对应项，不停止独立任务。

## 4. MAIN 独立记录

本次新增主功能规划24项及3份能力规范，尚未实施、未运行业务测试。正常从MAIN-A 1.1开始；已有批次先完成再插入MAIN。执行期间在此按MAIN-A～F记录实际差额、入口与内容证据，保留MAIN-F 6.3真实环境缺口。规划验证见 [记录](../analysis/product-main-plan-20261003/verification.json)。
