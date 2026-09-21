> 第三阶段（v3.0+）实施清单。依赖第二阶段 `STAGE_PREPARE`、`kernel/` 入包、`main_window` 拆分。
> 各节相互独立，可按团队优先级并行或裁剪；建议顺序 1 → 2 → 8 → 3 → 4 → 5 → 7 → 6。
> 来源：`analysis/feature-audit.md` TOP 20 与"可考虑"候选。

## 1. 预发布制品与 promote

- [ ] 1.1 `domain/output_state.py` 新增 `staged` 态与 `sourceTreeSha256`；`application/source_hash.py` 归一化哈希（content/assets/manifest）
- [ ] 1.2 `pipeline.run_pipeline(stage=True)`：无刷新、经前校验与终审、产物 `<doc>.staged.docx`
- [ ] 1.3 `pipeline.promote_staged(path)`：哈希校验 → 刷新 → 后校验 → 终审 → 原子发布 → 历史归档 → 删除 staged
- [ ] 1.4 CLI：`build --stage`、`refresh --promote <file>`、`status` 显示 staged 信息
- [ ] 1.5 GUI：打开项目检测 staged 且哈希一致 → 输出卡片"一键正式化"
- [ ] 1.6 `docs/ci-examples/`：GitLab/GitHub 两份示例流水线
- [ ] 1.7 测试：`test_word_release`（stage/promote/哈希不一致拒绝/promote 中断回滚）、`test_cli_machine`

## 2. Include / 共享章节

- [ ] 2.1 `manifest.includeRoots`；`prepare.py` INCLUDE 展开（深度、循环、白名单、图片路径改写）
- [ ] 2.2 `lint` 新增 `include_cycle`、`include_out_of_root`、`include_missing`
- [ ] 2.3 `preview.py` 展开并标注来源；树链接图标；`RefactorEngine` 更新 INCLUDE 标记
- [ ] 2.4 `changed_chapters()` 归并被包含文件的改动
- [ ] 2.5 测试：`test_project_build`、`test_authoring_services`、`test_content_operations`

## 3. 章节 Git 历史

- [ ] 3.1 `vcs_changes.file_history()` / `file_at_revision()`（git + svn）
- [ ] 3.2 `ui/content/history_dialog.py`：列表 + side-by-side + 只读打开
- [ ] 3.3 编辑器状态栏最近修改人（缓存与失效）
- [ ] 3.4 测试：`test_vcs_changes`（follow 重命名、svn log xml）、`test_gui_services`

## 4. 提交门禁与评审联动

- [ ] 4.1 `manifest.gates.commit_lint`；`git_commit_dialog` 门禁摘要与禁用
- [ ] 4.2 提交后解析 `Fixes R-n`，`ReviewStore` 新状态 `confirmed_pending_review` + `commit` 字段；`approval_gate` 规则更新
- [ ] 4.3 评审面板显示提交号与"复核通过"
- [ ] 4.4 测试：`test_review_docx`/`test_vcs_changes`/`test_gui_services`

## 5. HTML 评审包

- [ ] 5.1 `export/pdf_html.py` 前后对照 HTML（复用行级 diff 数据）+ 意见表单 + JSON 导出
- [ ] 5.2 评审面板"导出 HTML 评审包"按钮；"导入意见"支持 JSON
- [ ] 5.3 测试：`test_quality_traceability`（导出结构）、`test_review_docx`（JSON 幂等导入）

## 6. AI provider（可选）

- [ ] 6.1 `application/ai/provider.py`：协议、`HttpChatProvider`、`CommandProvider`、脱敏与截断工具
- [ ] 6.2 `manifest.ai` 字段与校验；设置页"AI"分页（端点/模型/密钥环境变量名/代理/启用）
- [ ] 6.3 修订摘要建议：`revision_record.suggest_summaries()` + 弹窗"建议"区
- [ ] 6.4 Lint 规则 `ai_term_consistency`（默认 off）与问题中心"AI 建议"标识
- [ ] 6.5 `docs/ai-privacy.md`；`RuntimeLog` 仅记录大小/耗时
- [ ] 6.6 测试：注入假 provider（成功/超时/异常/断网），断言 UI 无端点时不渲染入口、敏感掩码生效

## 7. 项目锁租约

- [ ] 7.1 `project_lock.py`：`heartbeat`/`leaseSeconds`、心跳线程、跨主机判定；旧格式兼容
- [ ] 7.2 UI 提示占用者与时间；过期接管确认
- [ ] 7.3 测试：`test_lock_log_cancel`（跨主机活动/过期/旧格式）

## 8. 命令注册表

- [ ] 8.1 `ui/command_registry.py`；`MainWindow` 与各面板注册；命令面板改由注册表驱动 + 最近使用
- [ ] 8.2 菜单由同一注册表生成（保持现有快捷键）
- [ ] 8.3 测试：`test_command_palette` 断言注册表 ⊇ 菜单动作；最近使用排序

## 9. 回归与发布

- [ ] 9.1 全量测试 + 冻结冒烟 + 安装器冒烟
- [ ] 9.2 团队试点：一个多文档项目使用 Include + staged/promote 流水线跑一个发布周期
- [ ] 9.3 design.md 验收标准逐条勾选；`docs/使用说明.md`、README、`docs/roadmap.md` 更新
- [ ] 9.4 版本升至 3.0.0；`openspec/specs/` 同步；归档本 change
