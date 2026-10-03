# product-v39-rd-workspace-productivity 实施任务

5 批/20 项，按 A→B→C→D→E 推进。保留既有实现和本次复核修正；旧实机缺项不阻断独立编码。勾选需要实际入口/行为证据，计划校验不算业务验收。

## 1. 39-A 研发列表与处理入口

- [x] 1.1 成员/条目/矩阵/影响/集合列表增加搜索、筛选摘要和详情区，稳定 ID/路径可复制，主列表显示可理解信息。（证据：test_rd_workspace_surface.py、test_matrix_page_v29.py、test_rd_workspace_entry.py）
- [x] 1.2 接入用户级筛选/页签/位置恢复及清除筛选，定位来源后返回原选择，坏记录回退默认。（证据：scripts/tests/test_v37_navigation_context.py（来源返回恢复筛选与选中行）、test_ui2_home_continue.py（会话恢复/坏字段回退））
- [x] 1.3 矩阵优先显示真实需求分母、未覆盖/部分覆盖及 N/A，分页不改变统计口径。（证据：scripts/tests/test_v39_matrix_coverage.py；本轮验证=25 条需求分 3 页时指标与覆盖率完全一致，未声明需求时为 N/A 而非 0%）
- [x] 1.4 影响/复核页按待处理状态组织，展示变化来源与路径，空、缺成员、只读状态都有可执行下一步。（证据：test_impact_v29.py、test_rd_workspace_surface.py、test_v32_delivery_ui.py）

## 2. 39-B 关系与复核交互

- [x] 2.1 优化双端选择器的成员/章节/编号/摘要/来源检索，按稳定身份建立关系，验证显示编号重复不串成员。（证据：test_relations_v29.py、test_item_actions_v29.py 的 projectId+itemId 身份断言）
- [x] 2.2 明确缓冲关系草稿和仅保存相关端点动作，验证两端保存范围与其他未保存章节保持。（证据：test_relations_v29.py、test_rd_workspace_surface.py::_on_save_endpoints_and_add 用例）
- [x] 2.3 复核详情显示已保存摘要、变化和过期原因，接通定位→修正→重检，不能自动升级通过。（证据：test_versioned_review_v28.py、test_rd_workspace_surface.py 的复核/重检用例）
- [ ] 2.4 用三成员场景从真实按钮验证关系→矩阵→变更→复核→返回，包含缺端点和只读成员局部继续。（服务与按钮路径已实现并有单成员/两成员用例；缺真实三成员工程条件，保留待验收）

## 3. 39-C 成员成果与集合

- [x] 3.1 比较选择器按真实集合路径/ID和时间区分同名版本，用用户选定的两份集合生成差异。（证据：test_collection_v29.py、test_collection_ops_v29.py）
- [x] 3.2 复用 delivery 队列/collection_bridge 展示成员部分成功、已可用成果、待 Word 和只补失败入口。（证据：test_v32_delivery_ui.py、test_v32_collection_bridge.py、test_v32_delivery_progress.py）
- [x] 3.3 完善集合差异分组、成果打开和恢复副本目标/冲突/重命名/跳过详情，源与当前缓冲不被覆盖。（证据：test_collection_ops_v29.py 的恢复目标/冲突用例）
- [x] 3.4 验证缺成员、单项失败、取消后再补和原轮捕获缺失，旧成果可用，不新增第二套队列/状态语义。（证据：test_v32_delivery_progress.py、test_export_round_recovery.py、test_core_export_snapshot.py）

## 4. 39-D 后台与大工程视图

- [x] 4.1 测量 RD 打开/刷新、索引、矩阵、影响、检查、集合导出/恢复的耗时，按实际瓶颈确定后台改动范围。（证据：analysis/main-d/measure-check-hotpath.json（120 章索引/检查热路径 ×5 次采样）、test_v36_large_document.py::test_benchmark_script_produces_report_with_counts）
- [x] 4.2 将慢路径移入 TaskRunner，UI 回传可展示数据；按工作区/项目/请求代次隔离晚到结果与销毁生命周期。（证据：test_v36_large_document.py::test_workspace_renders_first_screen_before_index_finishes、::test_stale_generation_result_is_ignored_by_panel、test_main_d_lint_scope.py::PreviewLifecycleTests）
- [x] 4.3 实现分页/渐进扫描、实际计数、1 秒内取消确认及部分结果，末页仍可定位，Word 退出单列。（证据：test_v39_matrix_coverage.py（分页计数）、test_v36_large_document.py::test_cancelled_build_keeps_partial_and_can_retry、test_v32_delivery_progress.py）
- [ ] 4.4 测量多次切换/关闭后的对象释放，对 50/300/1000 章节至少 5 次采样并对照无缓存完整结果，未达目标如实记录。（120 章 ×5 次采样与缓存损坏对照已完成，见 analysis/main-d/measure-check-hotpath.json；50/300/1000 三档与关闭后对象释放未在本环境完整采样，保留待补）

## 5. 39-E 团队试点与后续选择

- [ ] 5.1 执行三成员创建→条目/关系→覆盖→影响→成员交付→集合比较/副本恢复闭环，核对内容/身份/范围。（单成员/两成员服务闭环用例已通过；三成员真实工程需外部条件，保留待验收）
- [x] 5.2 运行 RD/CORE/V3.2/V3.6 与本次修复相关回归，保留来源摘要、覆盖口径、部分成果和正式状态断言。（证据：analysis/regression/report.json 分块回归清单 + test_v39_matrix_coverage.py、test_v36_large_document.py、test_v32_*、test_collection*_v29）
- [ ] 5.3 执行可用的真实大工程/团队/Word/缩放试点并记录观察；缺环境只保留对应任务，不将性能或视觉标为全部通过。（本机无真实大工程/团队/Word/多缩放条件，保留待验收）
- [x] 5.4 更新独立台账与产品路线图/OpenSpec strict，根据实测高频问题给出下一阶段候选及进入条件，不自动扩张为云平台。（本次更新 tasks 与 docs/product-v37-v39-execution.md，含下一直接任务与进入条件）
