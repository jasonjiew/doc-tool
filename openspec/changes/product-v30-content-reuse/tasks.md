> 入口：`docs/product-plan-v3.0-v3.3.md`。按 30-A→G 执行；先核对正在实施的 V2.8/V2.9 真实接口，前置只检查本批直接依赖。遵循兜底原则，证据写 `docs/product-plan-v3-execution.md`，不改并发任务的 V2 台账。

## 1. 数据契约与前置适配（批次 30-A）

- [x] 1.1 核对当前 HEAD/工作树/APP_VERSION 与预处理、变量、资产、条目、集合 API，记录复用/缺口清单和直接检查结果
- [x] 1.2 定义 module manifest、assembly、instances、variants 各 schema 1 数据模型及无 sidecar 默认行为
- [x] 1.3 定义 resolved 内容/来源/资源映射接口，建立两项目、三模块、两变体的脱敏夹具
- [x] 1.4 验证旧 v1/v2 项目不启用新功能时解析/构建行为，新增模型与默认兜底直接测试

## 2. 本地模块库（批次 30-B）

- [x] 2.1 实现从保存章节/明确缓冲快照提取模块，复用引用工具收集所需图片/表格并记录来源
- [x] 2.2 实现本地库目录、名称/标签/正文索引、列表/预览及配置损坏手工选择回退
- [x] 2.3 实现模块不可变版本保存、相同版本不同内容候选换名及项目内固定快照安装
- [x] 2.4 实现选定模块离线导入/导出，缺资源合法部分继续、非法附件跳过及原库保留
- [x] 2.5 测试跨目录/断网库使用、版本冲突、只读/取消、资源依赖及故障回退，提供三公开示例模块

## 3. 统一引用展开（批次 30-C）

- [x] 3.1 实现 slot 标记和 assembly resolver，输出源位置/依赖 hashes，在现有 Mermaid 预处理前接入
- [x] 3.2 复用变量实现 module 参数、标题偏移与图片源路径改写，不执行表达式/资源路径替换
- [x] 3.3 实现固定嵌套依赖、深度/循环检测和同版本缓存/占位兜底，合法其余内容继续
- [x] 3.4 同源展开覆盖**预览**：`EditorPanel`/`TabsHost`/`ContentWorkspace` 支持注入 `text_resolver`，`MainWindow._preview_text_resolver()` 复用 `reuse_hook.build_project_resolver`；只读 HTML 导出 `export_readonly_html(..., text_resolver=...)` 同样先展开再渲染 → 预览/检查/Word/HTML 用同一份内容（`test_v30_preview_instances.py` 2 项）
- [x] 3.5 测试跨入口一致、参数/层级、缺模块/图片/参数、循环/坏配置与严格策略，源正文不改

## 4. 升级和追踪实例（批次 30-D）

- [x] 4.1 实现模块新版本与项目固定版本差异、受影响 slot 列表，复用现有差异视图
- [x] 4.2 选择升级只替换合法已选引用，原配置/快照可恢复，复制编辑正文不随升级变化
- [x] 4.3 实例/覆盖率有产品写入路径：新增 `reuse_commands.record_instances()` 把明确纳入追踪的 slot 落盘为 `reuse/instances.yml` 并输出覆盖率分母（悬空实例只作证据、不写入；重复执行幂等）；`resolve_project(record_instances=True)`、CLI `reuse resolve --record-instances [--slots]` 与 GUI 面板「解析本项目引用」都已接线（`test_v30_preview_instances.py` 3 项）
- [x] 4.4 接入条目索引/影响/集合资源，升级保持来源可匹配身份，删除/悬空待处理而不伪造关联
- [x] 4.5 测试两 slot/两项目身份、重排/版本升级/删除、未纳入分母、升级取消/失败/部分应用

## 5. 产品变体（批次 30-E）

- [x] 5.1 实现显式章节 include/exclude、变量及 slot 版本覆盖的有效内容解析，坏可选项回退
- [x] 5.2 项目/工作区入口可选择变体，按原章节顺序筛选，题注和引用按有效内容计算
- [x] 5.3 构建/HTML/历史和矩阵带 variantId/有效范围/模块版本，输出目录隔离且分母可解释
- [x] 5.4 测试两型号差异、未知变体参数、范围外关系、不互相覆盖、无变体旧行为及默认/严格策略

## 6. 可用入口与兼容副本（批次 30-F）

- [x] 6.1 正文模块入口（列表/搜索/预览/解析报告）已接入内容菜单：`ui/reuse_dialog.py` + `main_window._on_reuse_dialog`，能力全部复用 `reuse_commands`（`test_v30_reuse_ui.py` 6 项）
- [x] 6.2 变体选择与展开副本入口可用：对话框内置变体下拉（`variant_evidence`/`resolve_project`）与「生成展开副本…」（`write_expanded_copy`，副本无引用标记、可搬目录）
- [x] 6.3 导出已展开普通正文的新项目副本，复用 V2.9 身份映射和资源复制，旧应用无需识别新标记
- [x] 6.4 核对 CLI help 后新增 reuse list/show/import/export 与 build/check 的显式变体选项，同源解析/机器报告
- [x] 6.5 跑引用→升级→两变体出稿→展开副本场景及 GUI 离屏/CLI 回归，注册新增测试

## 7. 试点与版本收尾（批次 30-G）

- [x] 7.1 直接套件（36+40+5 项）与版内全量回归（114 文件）已跑；A30-1～6 逐条留证见 docs/product-v30-execution-entry.md；唯一失败为环境项（mermaid 缺 mmdc），已单列
- [x] 7.2 离线与换目录试点：三公共模块 × 两文档 × 两型号（变量差异与章节排除均生效）、公共库两文档共享、整棵树换目录后再出稿、展开副本搬到另一目录自检通过；实机 Word 版式与冻结包检查按约定单列待验收（`scripts/tests/test_v30_offline_pilot.py` 3 项）
- [x] 7.3 复用/变体格式与展开回退指南已落 `docs/product-v30-reuse-formats.md`，使用说明与限制见 `docs/product-v30-v33-usage.md`；版本源按当前最高版本保持 **2.9.0**，V3.0 发布号留待同批正式发布时确定（未发布不改版本源）
- [ ] 7.4 验证 OpenSpec、任务证据与新台账；全部验收满足后同步/归档，否则保留待验收，先生成本地审阅物
