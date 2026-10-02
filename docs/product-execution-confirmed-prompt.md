# 执行前复核与最终持续指令

复核日期：2026-10-02（Asia/Shanghai）。读取时 HEAD：`2e5be72`，应用版本 `2.9.0`；工作树含上一轮 UI 的未提交实现及下一轮 UI2 规划。本次仅复核和整理指令，不启动业务实施，不覆盖其他任务文件。

## 1. 已确认的修正

| 原指令问题 | 修正 |
|---|---|
| 从 CORE/V3.0～V3.3 再按整包执行 | 五包已勾选 151/157；先核对实际差额，保留已完成代码和证据 |
| 遗漏当前 UI2 计划 | 下一轮优先 `product-ui-experience-next`，再 RD/V3.4/V3.5/V3.6 |
| 旧包收尾可能变成后续前置条件 | 人工/实机/归档缺项只影响对应项，不要求关闭旧包才开始新功能 |
| 单包执行文档只授权本包 | 此持续指令明确覆盖后续五包；完成一个包的可执行项后继续下一包 |
| 普通报错或技术决策可能触发反复暂停 | 在现有需求范围内自行排查/修复/补最小适配；仅真正无法继续时暂停 |
| 工作树已有 UI 文件 | 继承当前实现，不清空/回滚；有同文件并发修改时先避开重叠区域并记录 |

## 2. 任务状态快照

| change | 已勾选/总项 | 本轮执行策略 |
|---|---|---|
| product-core-import-export | 39/40 | 8.5 收尾，按真实证据补差额；不阻塞新功能 |
| product-v30-content-reuse | 31/32 | 7.4 收尾，复用实际装配/模块服务 |
| product-v31-team-workflow | 25/27 | 6.3 团队试点、6.5 收尾单列 |
| product-v32-batch-delivery | 31/32 | 7.5 收尾，复用实际持久队列/刷新服务 |
| product-v33-authoring-assistance | 25/26 | 6.2 人工试点，保留现有本地及可选模型能力 |
| product-ui-interaction-polish | 19/20 | 5.3 实机缺项单列，继承已有 UI 实现 |
| product-ui-experience-next | 0/26 | 当前下一包，UI2-A→B→C→D→E→F |
| product-rd-workspace-experience | 0/24 | UI2 后按已有研发服务补界面 |
| product-v34-table-authoring | 0/20 | 普通表格网格和 TSV 粘贴 |
| product-v35-standard-pack-authoring | 0/20 | 规范包制作和隔离样例 |
| product-v36-large-document-performance | 0/20 | 基准、增量索引与大项目视图 |

下一轮五包合计 **27 批/110 项**，这是读取时的任务范围，执行时重新读取任务状态。已勾选不替代真实功能和环境证据；本轮不因旧任务仍有空勾选就重做已经实现的引擎。

复核结果：五个下一轮 change 的 OpenSpec strict 均退出码 0，proposal/design/specs/tasks 均完整；UI2 的 apply instructions 为 ready，26 项待实施。任务编号在各包内唯一，批次数量与计划一致。读取既有 `test-results-full-v3-r40.xml` 和 `analysis/ui-polish-final.xml` 均为 failures=0；这些是历史回归证据，本轮未重跑业务测试，后续修改仍需相关验证。

历史报告中的“未提交”是当时记录；当前已有 `2e5be72` 提交且另有 UI 工作树修改，判断以实时 Git 为准。

## 3. 可复制给执行 Codex 的提示词

```text
在 D:/ai_develop_project_space/doc-tool 持续实施当前产品队列。先阅读适用的 AGENTS.md 和以下文档：
- D:/ai_develop_project_space/doc-tool/docs/product-master-roadmap.md
- D:/ai_develop_project_space/doc-tool/docs/product-execution-confirmed-prompt.md
- D:/ai_develop_project_space/doc-tool/docs/product-flow-fallback-policy.md
- D:/ai_develop_project_space/doc-tool/docs/product-ui-experience-next-plan.md
- D:/ai_develop_project_space/doc-tool/docs/product-ui-experience-next-execution.md

先核对实时 HEAD、工作树、tasks 和最近证据。CORE/V3.0～V3.3 读取时为151/157，上一轮UI为19/20；这些数字只是快照。继承现有代码、布局、未提交修改和验证，已实现能力只补实际差额。旧人工/实机/归档收尾不作为后续全局前置条件。

本次授权连续执行以下五包，而非只执行一个页面包：
1. product-ui-experience-next（UI2-A→B→C→D→E→F）
2. product-rd-workspace-experience
3. product-v34-table-authoring
4. product-v35-standard-pack-authoring
5. product-v36-large-document-performance

每包使用 openspec-apply-change，先运行 openspec status 与 openspec instructions apply，读取其返回的真实 proposal/design/specs/tasks 路径，再从下一未完成任务推进。完成本包所有可执行项后直接进入下一包；单包文档中的“仅本包”范围不作为这次整轮终点。若已有任务正进行，先完成该批直接验证再接队列。

优先日常可用：主按钮可读、首页继续工作、章节定位后能返回、阅读视图不改正文、真实导出设置与成果恢复。快速Word保持整份/当前内容（含未保存缓冲）/Word/模板/非严格默认。复用 QAction、主题、会话、TaskRunner、ExportRequest/ExportScope/LayoutProfile、捕获、OutputState、模块、关系、评审及持久队列，避免重复建设业务引擎。

默认尽力跑通并考虑兜底。缺Word/Git/模型、坏可选配置、单格式或成员失败、资源缺失和冲突项只影响对应动作；保留可用成果/合法部分，提供定位、修改设置、继续或重试。高级选项按需展开。保护源文件、未保存缓冲、来源身份和旧产物；补旧轮使用匹配的roundId/captureId，按当前修改出稿生成新轮，正式成功按真实状态判定。

普通技术错误自行复现和修复，接口差额补最小适配；需求内的小幅实现调整同步到相关设计/任务说明并继续。某项确实缺环境/依赖时记录具体任务与继续条件，保留未勾选并推进无依赖项。以上自主修复和局部继续要求优先于工作流中对普通报错的暂停建议。涉及功能边界重大改变或不可逆真实数据操作时不擅自扩大执行。

每批从真实GUI/CLI入口验证实际行为与成果，保存命令/环境/退出码/截图或报告，勾真实完成任务并更新所属独立台账。测试适配新界面时保持来源、范围、内容、撤销和数据保护断言。批次执行必要相关检查；稳定整合后运行必要全量回归和OpenSpec strict，避免每个小改动重复全量扫描。

真实Windows缩放、IME、Word视觉、团队试点等缺环境时写明待验收与复验步骤，继续其余工作；可读结果、模拟验证和规划校验不能冒充正式/实机成功。如实报告部分完成。

普通选择自行判断，每批结束后继续执行，上下文压缩后从tasks/台账恢复。仅在确需必要用户信息且无合理默认、涉及未授权的不可逆真实数据操作，或所有剩余项都没有可继续路径时暂停，并写清阻塞和继续入口。

本次范围为本地实施与验证；归档、远程发布、推送、修改系统安全配置和向他人发送消息另行处理。最终报告各包实际完成编号、可用主流程、验证及成果路径、兜底、待验收项和下一任务。持续实施，不只给计划后结束。
```

总路线图继续维护排程，当前包的 tasks 是实施状态来源；本文件是执行前复核快照及指令，不替代各包台账。
