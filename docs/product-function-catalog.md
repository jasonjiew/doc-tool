# 当前产品功能总清单

初始盘点日期：2026-10-01。基准提交：`1cc28ca`，应用版本 `2.9.0`，项目 schema 2。下方详细清单保留当时状态；最新2026-10-03实施增补见文末第13节，审查修复与下一步见第14节，核对提交为 `d68b514`。实时实施状态以对应 change/tasks.md 和实际验证为准。

产品定位：面向企业研发文档团队，用 Markdown 维护结构化内容，以 Word 模板完成正式文档交付，逐步接通需求、设计和测试的关系管理。

## 阅读方法

| 标记 | 含义 |
|---|---|
| 界面 | 已找到用户入口及实现路径；本次静态盘点，不表示所有实机情形已验收 |
| 命令 | 已注册 CLI 命令；不同操作有各自环境要求 |
| 服务 | 有可调用实现，但未发现完整日常界面入口；不能宣传成完整桌面功能 |
| 部分 | 有基础行为或独立入口，尚未接通统一流程 |
| 执行中 | 已有任务计划，正在开发；新增文件不能直接算完成功能 |
| 规划 | 已有提案/设计/规范/任务，业务实现尚未验证 |

正式出稿、可读待完善、参考预览是不同结果状态。无 Word、缺图、模板不完整等情况下优先给可用结果，并明确剩余事项；统一原则见 [流程与兜底](product-flow-fallback-policy.md)。

## 1. 项目与导入

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| 新建、打开、最近项目、多窗口 | 界面；项目会话和编辑上下文恢复 | `ui/main_window.py`、`window_registry.py`、`workbench_state.py` |
| Word 导入项目 | 界面 + 命令；预检、源文件复制、内容拆章、模板提取、试构建及报告 | `application/import_project.py`、`intake_word.py`、导入向导 |
| 样式清点、标题映射、保真提示 | 界面；目前流程存在需要人工确认的情况 | CORE 改为默认尽力导入、显式严格模式；无一级标题、空映射等列入验收 |
| 从 Markdown 创建项目 | 服务已存在，真实界面入口执行中 | 盘点开始时菜单转 Word 向导；末次读取已直接调用建项服务，本轮未验证完整交互 |
| 从规范包创建项目 | 服务已存在，真实界面入口执行中 | `project_from_pack.py`、`standard_pack.py`；末次读取已直接调用建项服务，验收随 CORE |
| 单文件 Word → Markdown | 界面转换工具 + 命令 | `docx_markdown.py`；与项目导入区分 |
| `.doc` 兼容转换 | 部分；依赖 Word 转为 DOCX 后处理 | 无 Word 不宣称 `.doc` 原生离线导入可用 |
| 通用项目 schema、旧项目迁移 | 服务 + 命令；高版本项目只读保护 | `domain/manifest.py`、`project_service.py`、`settings_migration.py`、`migrate` |
| 原文件/复杂内容留存、多个来源容错 | 执行中 | CORE 来源留存清单、可见占位、跳过坏输入；不可把规划算为已全面保真 |
| 源 Word 变化检测、重新导入修订 | 基础界面 + 服务，统一体验执行中 | `content/reimport.py` 有章节基准与冲突保留；`reimport_preview.py` 有预览选择服务，CORE 补未保存缓冲与预览串接 |

## 2. 章节组织与编辑

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| 章节树、添加/删除/重命名、顺序调整 | 界面；配套引用及路径处理 | `ui/content/workspace.py`、章节树与重排/重构服务 |
| 编号重排与改名预览 | 界面 + 命令；查看变更后应用 | `content/refactor.py`、`chapter_reorder.py`、`renumber` |
| Markdown 编辑、保存全部、撤销/重做 | 界面；UTF-8、原子写入等 | `editor_panel.py`、`ContentWriter` |
| 标题、粗斜体、代码、列表、引用、链接 | 界面；快捷插入 | 编辑工具栏；不等同于全功能 Word 所见即所得编辑 |
| 表格骨架、表格格式化 | 界面；普通管道表格、中英文宽度与转义 | `content/table_format.py`；网格、行列管理、TSV 粘贴由 V3.4 规划 |
| 编辑与预览定位、章节大纲、统计 | 界面；章节结构及字数等辅助信息 | 原生预览、`authoring_outline.py` 等 |
| 内容片段库、占位填写 | 界面；复用常用研发文档片段 | 片段库服务及对话框 |
| 搜索、正则/大小写/全词、替换预览 | 界面 + 命令；支持项目内容定位 | `content/search.py`、`replace.py`、搜索/替换面板 |
| 快速打开、命令面板 | 界面；按当前上下文操作 | 主窗口 Ctrl+P/Ctrl+K 入口；V3.1 计划统一命令注册 |
| 格式与术语/拼写辅助检查 | 界面 + 服务；本地规则 | lint、spellcheck、用户词典；没有默认联网改写 |

## 3. 图片、图形与资源

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| 图片按钮、拖放、剪贴板粘贴 | 界面；入库和引用维护 | `asset_manager.py`、编辑器 |
| 图片说明与尺寸、批量图片 | 界面；资产引用与属性编辑 | 图片面板、批量图片对话框 |
| 图片资源浏览、缺失引用与批量修复 | 界面 + 服务 | `image_assets.py`、`asset_batch.py` |
| Mermaid 模板、语法反馈、预览 | 界面；编辑源码和诊断定位 | Mermaid 对话框、解析/渲染服务；渲染环境仍有待分类的回归失败 |
| 图形缩放、平移、全屏、高清查看 | 界面 | `diagram_viewer.py` |
| 缺图占位、同源图形缓存/源码兜底 | 部分，CORE 统一完善 | 输出需记录降级来源，不能把旧图当成当前源码的成功渲染 |

## 4. 预览、构建和导出

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| 原生 Markdown 预览 | 界面；默认 Qt 原生预览与延迟更新 | 与正式 Word 分页/版式分开；旧 WebEngine 分支不作为主体验 |
| 项目构建管线 | 界面 + 命令；装配、变量、图形、构建、校验、Word 刷新等 | `application/pipeline.py`、`build`；按实际 OutputState 标识结果 |
| 模板底模、封面、页眉页脚、样式 | 界面使用 + 服务 | 原有模板资源保留；任意模板字段绑定不作为已实现承诺 |
| Word 内联格式、列表、代码容器 | 服务接入构建；支持合同中的表达范围 | `docx-expression-contract`；代码容器与用户表格分开 |
| 普通表格与复杂原生表格 | 服务接入构建；复杂表格保留路径及影子内容 | 不能宣称任意复杂对象都可在 Markdown 自由编辑且无损回写 |
| 图表题注、编号域、引用、书签 | 服务接入构建 | 题注注册和 SEQ/REF 等；正式刷新取决于实际 Word 执行 |
| 分页、章节横向等版式标记 | 部分；构建已有表达能力 | CORE 统一到易用版式入口与普通表格/图片适配 |
| 修订记录、版本摘要及章节链接 | 界面 + 命令 | 修订记录对话框、`autolink`；修订记录与内容基线不同 |
| 构建历史与结果打开 | 界面 | 主窗口构建历史入口；不等于跨项目版本集合界面 |
| 离线只读 HTML 包 | 界面；整份/当前章节及资源导航 | `readonly_html.py`；既有入口默认已保存内容 |
| Markdown 填充 Word 模板 | 独立界面 + 命令；方案、最近使用、预检和进度 | `template_fill.py`、`template-fill`；不与项目导入混淆 |
| Word 转 PDF、参考 PDF | 部分；Word PDF 与参考排版路径分别存在 | 参考 PDF 不算正式 Word 同版式 PDF |
| 当前未保存内容出稿、DOCX/PDF/HTML/源码 ZIP 同源导出 | 执行中 | CORE 有效内容捕获与统一导出；结果先可用、失败格式可重试 |
| 持久队列、断点续跑、跨机字段刷新 | 规划 | V3.2；现有任务执行器不算持久交付队列 |

## 5. 检查、设置与规范

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| 源检查、结构校验、构建报告 | 界面 + 命令 | `check.py`、`quality_gates.py`、lint/validate |
| 问题中心、严重程度、来源定位 | 界面；汇总检查结果与修复入口 | `issues_panel.py` |
| 机器可读检查 | 命令；text/json/sarif、阈值与严格选项 | `check`；不同命令保留自身参数语义 |
| 项目基本设置 | 界面；编号、名称、版本、模板、超时、发布说明 | `ui/settings_dialog.py` |
| 样式、变量、术语、规则等完整设置模型 | 服务，界面部分缺失 | `application/settings.py`；RD-B 接入字段模型和真实保存结果 |
| 项目概览、过期报告、下一步建议 | 服务，未发现独立完整概览界面 | `overview.py`；RD-B 接入 |
| 声明式规范包安装与固定版本资源 | 服务 | `standard_pack.py`、`pack_resources.py`，schema 1；默认可用资源兜底 |
| 规范包可视化制作、样例试用、分享 | 规划 | V3.5；不重复规范包消费/安装引擎 |

## 6. 本地历史、评审与研发联动

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| 工作区内容基线与修改 Diff | 界面；当前内容快照及差异 | `content/snapshot.py`、改动面板；与命名基线/集合快照区分 |
| 本地历史、草稿、崩溃恢复、垃圾箱 | 界面 + 服务；无 Git 仍有本地恢复路径 | LocalHistory、autosave、recovery；按真实写入路径记录备份结果 |
| 命名文档基线、冻结及副本恢复 | 服务；部分已有工作区基线入口 | `content/baselines.py`；不能笼统宣称版本中心全部接通 |
| 评审意见、筛选、状态、章节定位 | 界面 | `review_panel.py` 和 ReviewStore |
| 评审 Word 草稿、Word 批注导入、证据/纪要 | 界面 + 服务 | review export、extract_comments 等；不冒充外部审批或电子签名 |
| 绑定内容摘要的版本化评审生命周期 | 服务 + RD-D 界面；复核绑定已保存摘要，内容再变标为待重检 | `versioned_review.py`、`impact.ReviewRecordStore`；`ui/rd_workspace.py` 只显示与请求重检，不自动升级为通过 |
| 需求/设计/测试成员工作区 | 服务 + RD-B 界面；角色是通用项目元数据 | `workspace.py`、`ui/rd_workspace.py`；引用/复制加入、移除、重新定位、只读成员禁写 |
| 稳定条目 ID、复制/重编号语义 | 服务 + RD-C 界面；写回编辑缓冲一次撤销 | `traceable_items.py`、`item_actions.py`；显示编号不取代稳定身份 |
| 显式满足/验证/依赖关系 | 服务 + RD-C 界面；双端检索显示成员/章节/来源 | `relations.py`；未落盘端点保留草稿并可“仅保存相关两端”，不按编号猜关联 |
| 覆盖矩阵、孤立条目、分页定位 | 命令 + 服务 + RD-D 界面 | `trace_matrix.py`、`trace`、`ui/rd_workspace.py`；只统计显式声明需求，无需求为 N/A |
| 变更影响、语义摘要、待复核记录 | 命令 + 服务 + RD-D 界面；标明已保存/缓冲来源 | `impact.py`、`impact`；界面与 CLI 复用同一收集与报告实现 |
| 版本集合捕获、清单、比较、导出包、恢复副本 | 服务 + RD-E 界面；成员出稿复用既有批量交付 | `collection.py`、`collection_ops.py`、`ui/rd_workspace.py`；缺成员/单成员失败保留其他结果，恢复只出新副本 |
| 跨文件版本内容复用、变量变体 | 规划 | V3.0，独立于当前片段插入 |
| 章节负责人、三方交接、冲突跳过 | 规划 | V3.1，独立于当前 Git/SVN 功能 |

## 7. Git/SVN 与工作台

| 功能 | 状态与范围 | 实现依据 / 待补 |
|---|---|---|
| Git/SVN 状态、Diff、提交 | 界面 + 服务 | `content/vcs_changes.py`、改动面板；不同后端支持范围不同 |
| Git 暂存/提交、推送/拉取、分支、stash | 界面 | 主窗口 Git 菜单；真实冲突暂存路径仍有历史待核对问题 |
| 单文件/全部撤销修改 | 界面；配套恢复及未保存处理 | 按文件能力执行，不能删除用户未交付内容 |
| 多面板布局、显示/隐藏、全屏、主题 | 界面 | Dock 工作台、F11、深浅主题 |
| 后台任务、进度、日志、取消、环境诊断 | 界面 + 服务 + `info` 命令 | TaskRunner、中文错误及阶段报告；仍需真实场景测量响应 |
| 无 Git 使用 | 已有本地编辑/历史路径 | Git 不是普通文档流程的前置条件 |

## 8. 独立转换工具：20 个方向

依据 `application/convert.py` 的 `DIRECTIONS` 注册表。它们是独立转换工具，不等于统一项目导出已经接通；Word 后端操作需要相应环境，PDF 转 Word 也不承诺任意版式无损。

| 来源 | 已注册目标 |
|---|---|
| Word | PDF、Markdown、HTML |
| PDF | Word |
| Markdown | Word、HTML |
| HTML | Word、PDF |
| TXT | PDF |
| XLSX | CSV、HTML、PDF |
| CSV | XLSX、PDF |
| RTF | PDF、Word、Markdown、TXT |
| ODT | PDF、Word |

## 9. PDF 工具箱：15 项

依据 `application/pdf_tools.py` 的 `TOOL_SPECS`；界面与 `pdf` 命令消费同一注册表。旧文档中的“14 项”未包含页面重排。

| 分类 | 功能 |
|---|---|
| 页面 | 合并、拆分、提取、删除、旋转、重排 |
| 转换 | PDF → 图片、图片 → PDF、PDF → 文本 |
| 编辑 | 文本水印、页码、元数据 |
| 保护/体积 | 加密、解除密码、无损结构压缩 |

文本提取针对文本图层，扫描件 OCR 未实现；压缩不承诺图片重编码和显著压缩率。现阶段保留这些辅助工具，主排程聚焦研发文档闭环。

## 10. CLI、分发和运维

当前注册命令：`build`、`info`、`preflight`、`import`、`validate`、`check`、`trace`、`impact`、`lint`、`search`、`status`、`migrate`、`autolink`、`renumber`、`convert`、`pdf`、`template-fill`。

`template-fill --output` 是 DOCX 文件路径，不能被后续统一导出改成目录。`check` 支持 text/json/sarif；各命令格式选项按各自解析器使用。工作区建管、集合恢复、复用和持久队列不能凭服务存在宣称已有 CLI。

已有冻结打包、便携包/安装包、依赖与环境诊断、版本管理、签名配置、开源发布清理及泄漏扫描脚本。安装升级、签名、Word COM、冻结运行应记录实际环境结果；源码版本号或归档不代表当前安装包已完成全部实机验收。

## 11. 当前证据与遗留，避免误判

| 证据 | 可得结论 | 不可扩大为 |
|---|---|---|
| V2.7/V2.8/V2.9 已归档，任务分别 41/41、44/44、39/39 | 变更任务账本已闭合并同步规范 | 所有桌面入口、人工 Word 视觉及安装试点均已验证 |
| `docs/release/evidence/v27-word-refresh.json` | 历史 requirement/design/test 三份样例的真实刷新成功且 formal=true | 当前所有模板/Word 版本全面兼容 |
| `v29-post-archive.xml` | 外层 95 个测试执行项中 1 个失败，GUI 服务测试包含 2 个失败 | 全量回归全绿，或两者均已证明是产品缺陷 |
| 高 schema 只读测试替换固定 `schemaVersion: 1` | schema 已为 2，推断夹具替换可能未生效；需要复现验证 | 可以取消高版本只读保护 |
| Mermaid 对话框状态断言失败 | 需要核对渲染环境、状态反馈与源码兜底 | 可以隐藏错误或直接把渲染失败标为成功 |
| 冻结升级证据 WinError 5、sourceUnchanged=true | 升级样例未成功，原项目未被改写 | 冻结升级已验证通过 |
| V2.9 报告明确成员管线、矩阵/关系/复核 GUI 尚未串接 | 这些应进入 RD 产品集成包 | 继续开发第二套关系/集合引擎 |

上述为历史证据读取，本轮未重跑业务回归或执行真实 Word/安装试点。已有失败按影响范围处理，不阻塞无依赖的文档编写和后续开发。

并发实施补记：末次读取已看到 CORE 的 Word/Markdown 自动识别、Markdown/规范包真实建项入口及导入记录/大纲模块；对应 CORE tasks 当时仍为 0/40，不能凭新增文件判定整包完成。另一个服务修复任务生成的 `analysis/review-regressions-after.xml` 外层 8 个执行项失败为 0，覆盖集合、评审包、版本化评审、公开导出、MD/规范包建项及 schema 迁移等相关测试文件；这份专项证据不替代全量 GUI、Word 视觉及冻结升级验收，亦非本规划会话运行。

## 12. 产品入口收敛与计划归属

默认工作流：打开/新建 → 导入 → 编辑 → 查看问题 → 快速导出 → 打开成果。高级工作流：选择研发工作区 → 条目/关系 → 矩阵/影响 → 评审 → 版本集合/交付。

| 功能缺口 | 唯一实施归属 |
|---|---|
| 默认导入、来源留存、当前缓冲、统一出口、版式及就地兜底 | CORE |
| 工作区/概览/完整设置、条目与关系、矩阵/影响/集合 GUI | RD 集成包 |
| 普通表格网格、TSV 粘贴 | V3.4 |
| 固定版本模块复用与变体 | V3.0 |
| 章节交接、内容历史、统一命令 | V3.1 |
| 规范包制作及样例验证 | V3.5 |
| 持久交付队列、跨机刷新、自动交付接口 | V3.2 |
| 增量索引、大项目视图性能 | V3.6 |
| 本地证据检索、可撤销建议、可选模型 | V3.3 |

下一步的优先级、完整版本规划及可复制执行指令统一见 [产品总路线图](product-master-roadmap.md)；本文件是能力清单，不维护实时任务勾选。

## 13. 2026-10-03 现状增补

CORE/V3.0～V3.3已勾选151/157，默认导入、当前缓冲捕获、统一多格式出稿、模块复用、交接、持久队列和辅助写作代码已存在；初始清单中的“执行中/规划”不得据此作为重新开发这些服务的理由。UI已19/20、UI2已25/26，日常入口、非模态成果、项目条溢出、继续工作、导航/阅读、导出设置和窄面板已提交。

复核发现的三处导出差额已修复：原捕获丢失时保留旧成果，不改读新正文；已知捕获身份必须匹配；选章/当前章再生成及换目录保留范围，失效时回到可见设置。可核验的旧 Word 仍能补 PDF，新增断言回归和实际 HTML 内容检查见 [复核与修正记录](product-execution-review-20261003.md)。RD/V3.4～V3.6 已实施80/84，后续开发从 MAIN 主功能优化接续，再进入 V3.7～V3.9，实机和人工验收仍单列。

RD 研发工作区界面已实施 23/24：新增 `application/rd_surface.py`（薄适配与统一来源定位）与 `ui/rd_workspace.py`（成员/概览/设置、条目/关系、矩阵/影响、集合/成果），主窗口新增「内容 → 研发工作区…」(Ctrl+Alt+D) 入口与宿主适配，顺带补齐设置分组名称写入、关系端点草稿判定、集合导出包目录与过期复核标注。证据见 [RD 执行台账](product-rd-workspace-execution.md)；6.3 真实桌面/Word 试点待验收。

普通表格编辑（V3.4）已实施 19/20：`application/content/table_grid.py` 提供表格模型/转义往返/片段身份，`ui/content/table_grid_dialog.py` 提供网格编辑（行列增删移动、对齐、Tab 导航、网格内撤销）与「粘贴为表格」预览，编辑器工具栏/菜单/命令面板接入，未保存表格进入 CORE 同源出稿；5.2 真实 IME/剪贴板待验收。

规范包制作（V3.5）已实施 19/20：`application/pack_authoring.py` 提供草稿、资源映射、冻结（schema 1 + 实际摘要）、ZIP 导出与隔离样例验证，`ui/standard_pack_dialog.py` 提供制作界面，菜单「内容 → 规范包制作…」接入；既有加载器可消费导出包；企业模板/真实 Word 试点待验收。

大文档性能（V3.6）已实施 19/20：`application/content/incremental_index.py` + `content/index.py` 提供按内容摘要/解析器版本/配置指纹失效的派生缓存与增量刷新，`scripts/perf/v36_benchmark.py` 提供同机基准；实测重复刷新解析次数 -100%，1,000 章节 p95 改善 31.7%、300 章节 13.7% 未达标。检索视图已接入请求代次、渐进扫描与取消（部分结果如实标注）；`EffectiveSnapshot.captureIndex` 记录本轮捕获真实摘要，捕获作用域索引按 captureId 隔离且缓冲内容只用内存摘要；`chapter_assembly_fingerprints` 让模块变化只失效引用它的章节；章节首屏、问题列表分页与对象释放测量已补齐。**未完成**：36-E 5.3 真实大项目与 Word 试用量测。

各包台账：[RD](product-rd-workspace-execution.md)、[V3.4](product-v34-table-execution.md)、[V3.5](product-v35-standard-pack-execution.md)、[V3.6](product-v36-large-document-execution.md)。旧实机、人工试点与归档收尾单列，缺依赖仅影响对应动作。

## 14. 实施后修复与下一轮功能

本次已修正真实表格按钮、空行列与一次撤销、表格来源锚点及草稿继续；规范清空资源/当前冻结、未知字段及资源保留、ZIP清单、独立样例/旧轮重试、关闭保存；小窗口工具栏/滚动表单/深色主题；历史交接报告按实际JUnit计数。详见 [审查与证据](product-post-implementation-review-20261003.md)。当前默认测试172文件；本次运行27文件/552用例相关检查和最终规范/报告专项，没有声称重跑完整默认清单。

下一轮新规划：[MAIN主功能](product-main-workflow-optimization.md)导入质量/当前编辑/资源引用/检查预览/Word出稿24项，V3.7 日常入口/导航/反馈/视觉键盘，V3.8 表格/规范表单/导入导出，V3.9 研发筛选详情/关系复核/成果集合/后台性能。共21批/84项；[产品与交互方案](product-v37-v39-roadmap.md)、[任务台账](product-v37-v39-execution.md)、[完整指令](product-execution-confirmed-prompt.md)。

## 15. 2026-10-03 MAIN + V3.7～V3.9 实施结果

四包 21 批 84 项已完成可执行部分 **75/84**，剩余 9 项全部依赖真实外部条件（Word/企业底模/中文 IME/Excel 剪贴板/真实多成员工程/多缩放显示器）。

- MAIN 23/24：导入代码缩进、保留对象精确到章节文件与行号、多来源同名资源身份与引用映射、替换范围与活缓冲、围栏代码保护、章节复制新身份、预览后内容变化的跳过、检查范围与活内容、差异预览与撤销、关闭生命周期、长表表头、整份出稿补齐父章节正文、单格式失败隔离。唯一剩余：6.3 真实企业底模/Word/IME/Excel 试点。
- V3.7 17/20：跳转返回恢复原页面/筛选/选中行、问题面板无结果时的清除筛选下一步；其余由既有套件固定。剩余：三成员实机、真实截屏、真实桌面/IME/缩放。
- V3.8 19/20：粘贴预览分页（1000×20 末页→完整插入）、规范包骨架默认只含标题层级。剩余：真实 Excel/Word 剪贴板、IME、企业底模。
- V3.9 16/20：矩阵真实分母/N/A 与分页统计口径一致（新增实测）。剩余：三成员实机闭环、50/300/1000 章对象释放、真实大工程试点。

新增/变更能力位置：`doc_tool/adapters/importer.py`（段落原文与定位行）、`doc_tool/application/project_from_markdown.py`（资源身份、章节标题提取）、`doc_tool/application/effective_snapshot.py`（整份补齐父章节正文）、`doc_tool/application/project_export.py`（单格式失败隔离）、`doc_tool/application/content/{replace,refactor,table_grid}.py`、`doc_tool/application/pack_authoring.py`、`doc_tool/ui/navigation_history.py`、`doc_tool/ui/content/{replace_panel,lint_panel,issues_panel,editor_panel,table_grid_dialog,workspace,tree_panel}.py`、`scripts/build_docx.py`。

测试覆盖与证据：分块回归 180 文件 **2860 passed / 4 failed / 15 skipped / 1 timeout**（失败项均为既有环境问题，见台账第 5 节）；本轮新增 11 个测试文件、59 个用例；性能实测见 `analysis/main-d/measure-check-hotpath.json`。详见 [任务台账](product-v37-v39-execution.md)。
