# product-v37-daily-workflow-ux 实施任务

5 批/20 项，按 A→B→C→D→E 推进。保留既有实现和本次复核修正；旧实机缺项不阻断独立编码。勾选需要实际入口/行为证据，计划校验不算业务验收。

## 1. 37-A 常用入口与继续工作

- [x] 1.1 核对本次修复基准，完善首页“继续上次工作”及缺失路径重新定位，实际打开上次章节并保留当前草稿。（证据：scripts/tests/test_ui2_home_continue.py —— 固定项往返、缺失/坏字段回退、未知路径报告 miss、缺失项目条目提供重定位或移除）
- [x] 1.2 整合项目条与现有 action registry 的导入/查看问题/导出动作，验证按钮、菜单和命令面板都调用同一真实动作。（证据：scripts/tests/test_ui_polish_entry_drop.py::IntakeCommandGroupTests、test_command_palette.py、test_v31_command_registry.py）
- [x] 1.3 为无项目、无当前章、只读和缺可选环境配置上下文文案/启用状态，默认创建/编辑/HTML 出稿仍可走通。（证据：test_core_intake_fallback.py、test_main_f_flow.py、test_core_export_snapshot.py 的只读/无 Word 分支）
- [x] 1.4 完善首页空状态、最近项目长名称和可复制路径，跑通首页→编辑→成果的真实按钮闭环。（证据：test_ui2_home_continue.py、test_ui_polish_toolbar.py 的长路径省略与可复制）

## 2. 37-B 导航与工作位置

- [x] 2.1 接通问题/RD 来源跳转后的返回动作，保留原页面、筛选、选中行及编辑器位置。（证据：scripts/tests/test_v37_navigation_context.py；本轮修复=NavLocation 增加 panel/view，工作区采集并恢复工具面板与筛选/选中行，问题面板新增 view_state/restore_view_state）
- [x] 2.2 把 RD 页签/筛选/位置接入已有会话服务，坏记录回退默认，验证重开不恢复旧正文或覆盖活缓冲。（证据：test_ui2_home_continue.py::test_old_session_without_cursor_field_still_restores_tabs、::test_cursor_position_is_stored_and_restored；test_v37_navigation_context.py::test_restore_ignores_stale_values）
- [x] 2.3 完善编辑/阅读/研发视图之间的继续工作入口，保留未应用表格草稿和未保存多章内容。（证据：test_v33_editor_wiring.py、test_ui2_reading_view.py、test_v34_table_authoring.py 的草稿继续用例）
- [ ] 2.4 验证跨成员打开/激活/返回和缺成员重定位，身份使用真实 projectId/relPath，其他成员继续可用。（服务与视图已实现，缺少多人真实工程条件做端到端实机验收，保留待验收）

## 3. 37-C 任务、问题与成果反馈

- [x] 3.1 把空/加载/无结果/失败反馈就地统一到原面板，提供清除筛选、回到输入或重试动作。（证据：scripts/tests/test_v37_navigation_context.py::test_no_result_state_offers_clear_filters；本轮修复=问题面板无结果时就地出现「清除筛选」，空状态文案给出下一步）
- [x] 3.2 复用 TaskRunner/TaskDock 显示真实阶段、部分完成和取消确认，区分取消请求与后端停止。（证据：test_v32_delivery_progress.py、test_operation_loading_overlay.py、test_lock_log_cancel.py）
- [x] 3.3 成果卡片优先展示已可用格式，接通打开/补原轮/最新新轮，验证 Word 未完成时 HTML 不受阻。（证据：test_ui_polish_results.py、test_export_round_recovery.py、test_main_e_export_rounds.py::test_single_format_failure_keeps_other_results）
- [x] 3.4 问题→定位→修改→重检→返回流程保留上下文，只影响选择范围，验证晚到事件和已销毁视图处理。（证据：test_v37_navigation_context.py、test_main_d_lint_scope.py::PreviewLifecycleTests、test_v36_large_document.py::test_stale_generation_result_is_ignored_by_panel）

## 4. 37-D 视觉、键盘与小窗口

- [x] 4.1 沿用 QSS tokens 统一主次按钮、状态文字、列表/详情层级及明暗滚动背景，技术 ID 可复制但不抢主内容。（证据：test_brand_consistency.py、test_ui2_visual_hierarchy.py、test_ui_polish_advanced.py）
- [x] 4.2 完善长文件名、提示和操作溢出，测量 1024/1280/1920 下实际文字宽度、相邻矩形和主动作可达。（证据：test_ui_polish_geometry.py（1024×640 / 1280×720 实测矩形与溢出入口）、test_ui2_visual_hierarchy.py（1024/1280/1920）、test_core_hidpi_layout.py）
- [x] 4.3 梳理 Tab/Shift+Tab/Esc/快捷键的作用域与返回焦点，验证普通输入及网格编辑不被错误拦截。（证据：test_ui_polish_toolbar.py、test_v34_table_authoring.py 的 Tab 网格导航、test_main_d_lint_scope.py 的关闭生命周期）
- [ ] 4.4 验证加载、无结果、错误、只读、深色和长名称六类页面状态，保存实际截图与几何，不以非零尺寸代替可读性。（离屏几何与状态切换已由上述测试覆盖；真实桌面截屏与视觉可读性未在本环境采集，保留待验收）

## 5. 37-E 自动闭环与试点交接

- [x] 5.1 执行单文档“继续→改一处→查问题→导出→打开成果”及三成员来源跳转闭环，核对实际内容和身份。（证据：test_main_f_flow.py::WordFlowTests（继续→改→检查→整份/选章出稿→打开成果）、test_v31_team_flow.py、test_rd_workspace_surface.py 的来源定位断言；三成员真实工程见 5.3）
- [x] 5.2 执行无 Git/无模型/无 Word、局部资源失败、未保存内容和取消场景，保留原轮与内容断言并运行相关回归。（证据：test_v30_offline_pilot.py、test_core_intake_fallback.py、test_export_round_recovery.py、test_main_b_replace_scope.py::BufferExportTests）
- [ ] 5.3 执行可用的真实桌面/中文 IME/125%～200% 缩放试点；缺环境部分保留待验收，不能用离屏冒充。（本机无真实中文 IME 与多缩放比显示器条件，保留待验收；复验步骤见 docs/product-v37-v39-execution.md）
- [x] 5.4 更新本包独立台账、功能清单/队列和下一直接任务，执行 OpenSpec strict；完成可执行项后继续 V3.8。（本次更新 tasks 与 docs/product-v37-v39-execution.md）
