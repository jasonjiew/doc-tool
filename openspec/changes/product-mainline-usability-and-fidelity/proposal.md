## Why

现有V4.0～V4.3偏重运行、模板、检查和团队交付，导入后继续写、接收源Word修订、当前章节操作、缺图修复和最终出稿仍缺具体优化任务。静态复核看到服务与真实入口的接入差额，需在V4.0之后补主线可用性，再进入模板和团队工作流。

## What Changes

- 导入结果沿用真实记录，改为可再次打开、可筛选/分页的处理列表；超过40项仍能查看和定位，成功项目可立即编辑，批量只重试对应项。
- 将已有复导入只读计划/差异选择接入真实入口，包含当前脏内容与预览后变化；默认先应用合法项，冲突/脏项保留或另存副本。
- 章节复制以当前有效正文为默认，身份、引用和路径正确；现有移动/改名/排序保持上下文，不要求先保存整份。
- 图片清单/替换/清理接入同一活缓冲事实，外部替代图直接导入，按明确引用应用、可撤销，不默认删除正文行。
- 核对并修正版式处理→Word刷新→最终状态/摘要→PDF的顺序；沿用并复验现有HTML独立目录，修正捕获来源提示/清单，范围与成品事实可读回。
- 以Word、Markdown和外部修订三条真实入口闭环验收；MAIN2-A～F，6批/24项，旧MAIN任务与已实现引擎保持。

## Capabilities

### New Capabilities
- `actionable-import-continuation`: 可重开且完整的导入结果、批量接续和立即编辑。
- `desktop-source-update-workflow`: 已有差异服务接到真实复导入入口和当前内容。
- `effective-authoring-and-assets`: 当前章节操作、资源修复与缓冲一致性。
- `coherent-final-export`: 最终版式/刷新/状态/PDF一致和独立离线成果。

### Modified Capabilities
无。现有versioned-review-loop、content-refactor、release-quality-gates等主规范契约继续遵循；新增桌面组合与成品一致性契约，不重建底层服务。

## Impact

涉及main_window导入/复导入入口、intake_result_page/batch、reimport_preview/plan/service、工作区buffer provider/applier、章节与图片面板、project_export/pipeline/LayoutProfile/output_state及离线HTML。复用CORE捕获和V4.0后台/Word适配；不添加必经质量审批、不自动写回脏正文，不扩大为任意Word对象编辑器。
