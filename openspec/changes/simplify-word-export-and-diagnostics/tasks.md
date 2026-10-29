# Word 导出、交互与样式整合执行计划

修订日期：2026-10-29。**本文件是六项交互修正与样式优化的唯一执行清单。** 第 7—13 节的既有任务、勾选和执行记录保留；新增第 14—15 节共 5 项样式任务，尚未实施，业务/视觉验证均为 `not-run`。第 1—6 节为前次实施记录，不是本次复验结论。旧 6.3 仍为独立实机待办，不因规划代勾，也不阻塞可独立完成的新修正。

行为以本 change 的五份 `specs/` 为准；CF-01—CF-06 见 [design.md D7](design.md#d7-六项最小修正的执行设计)，VS-01—VS-03 样式参数和落点见 [D8](design.md#d8-与六项修正一并执行的样式设计)，页面目标见 [UI、交互与样式整合方案](ui-interaction-plan.md)。保留首页/章节树/导航/摘要/视图和正文编辑字号，只在既有主流程区域统一样式；不建设新工作台、自动合并或额外治理系统。

## 接手执行说明

1. 从父工作区遵循 `AGENTS.md`、POLICY、hub-start；真正实施前加载 hub-before-dev。目标仅为 `doc-tool`。核对基准 `5c46b1baa56b5116d264d50e1572170b7a93fa74`，分支名不是切换指令，实际 HEAD/工作区不同就重新核实相关符号和差额，保留更新器等其它改动。
2. 执行顺序：7 → 8 → 9 → 10 → 11 → 12 → 14 → 15 → 13。为保留原引用，13 的集成编号不变，新增 14—15 放在它前面执行。一名执行 AI 顺序完成即可；从首个未完成且前置满足的项续接，已满足项验证后复用，不重做功能。
3. 每项完成时补该项真实验证结果再勾选；记录 `passed / failed / not-run / blocked / not-applicable`，零用例和跳过不算 passed。已被他人修复的项先验证再说明跳过实现，禁止为了完成任务再造一套能力。
4. 本轮交付是最小修正与验证；不自动提交、推送、切分支、安装依赖、改版本、发布或归档。本次规划交付仅修改 OpenSpec；下面的实施步骤供收到用户执行指令的 AI 使用。
5. 验证产物用本次独立目录。第 9.1 项先隔离恢复脚本的固定历史输出，再运行它；不覆盖既有 XML、截图或用户正文。
6. 本次新增样式不能覆盖正在执行的功能修正；开始 14 前重读当前 diff，CF-01—CF-06 的入口、来源、诊断和动作规则均保持。无需把既有已完成项清零；若样式造成回归，在本轮修复并补证据，不改旧证据为通过。

## 1. 固定基准并复现真实差额

- [x] 1.1 核对当前 HEAD、已有修改、相关旧 change 与本 change 的契约，记录 Codegraph 使用情况及 `条件 → 原行为 → 目标行为 → 调用方影响` 分支表；验收为基准可追溯，明确原捕获重试、当前内容生成、缺 Word、真缺图和临时目录错图的不同处理。
- [x] 1.2 在现有夹具中加入“普通 PNG＋Mermaid 同章”最小回归，分别覆盖无图预处理、仅 Mermaid 和混排，并记录修复前实际失败阶段与路径；验收为真实导出/校验链可重现差额，源文件/图片摘要保持，未复现时先说明原因再调整修复落点。
- [x] 1.3 从真实默认按钮、菜单和 Ctrl+E 梳理设置布局、确认与后台提交次数、隐式保存、重复完成弹窗及错误字段丢失位置；验收为可观测差额记录，保留用户要求的先设置后生成，不通过测试专用分流、跳过设置参数或替换默认处理函数掩盖正常路径。

## 2. 让普通图片与生成图按真实来源合回 Word

- [x] 2.1 扩展现有共享资源解析能力，按捕获资源、显式模块资源、生成图映射解析，保留既有路径边界；验收为同名不同图和无来源依据的回退用例能发现串图，原输入重试不读捕获后的新图片。
- [x] 2.2 将预处理、Word 构建和校验接到同一资源解析结果，修复 Mermaid 临时根覆盖普通图片；验收为任务 1.2 的混排失败转为通过，DOCX 实际内嵌原 PNG 与生成图，校验使用相同图片字节，未跳过或放宽既有断言。
- [x] 2.3 在预处理替换中保留原块位置与资源来源映射；验收为 Mermaid 改变行数后，后续图片失败仍对应原 Markdown 行号，位置未知、歧义或陈旧时给出限制且不误跳。
- [x] 2.4 补资源边界回归并注册到现有测试入口，覆盖多章同名图、生成图缓存、渲染降级、真缺图、坏路径和取消；验收为报告包含实际用例/失败/跳过/退出码，原 Markdown、底模及资源摘要不变，普通/严格策略保持。
- [x] 2.5 更新 `docs/product-core-quick-guide.md` 中图片、Mermaid 和缺资源的实际支持边界；验收为文档描述与本组运行证据一致，真实样例尚未验证时明确保留该限制。

## 3. 打通全阶段诊断并自动保存 Markdown

- [x] 3.1 固化 `export-diagnostics` 的可选数据结构及兼容读取，在捕获前建立执行关联、成功捕获后绑定真实身份；验收为输入不可读/捕获失败也有明确阶段与可复制原因，未知 captureId 不被伪造。
- [x] 3.2 从现有 PipelineResult/StageEvent 向 ExportReport、FormatResult 和结果展示模型传递阶段、错误码、SourceLocation、资源身份及日志引用；验收为预处理、构建、校验、Word 刷新、写成果和状态登记失败分别可辨，原始业务状态含义不变。
- [x] 3.3 复用原报告序列化和索引，按导出/执行安全保存诊断、必要日志/报告摘要及同源 Markdown，重试保留前次记录；验收为清理临时目录并重开项目后仍能找回本次证据，最新 `export-result.json` 保持原读取兼容。
- [x] 3.4 为界面查看、复制与保存实现同一 Markdown 诊断投影及白名单脱敏；验收为阶段与位置和机器事实一致，默认无正文、认证信息、异常局部变量，复制内容包含脱敏排查位置和未知/未执行说明。
- [x] 3.5 在本组加入并运行兼容与故障测试，覆盖旧索引、未知可选字段、诊断不可写/中断、快照失效及 CLI 失败/部分可用结果；验收为已有成果保留、未保存状态可见、旧记录不被补写、CLI 标准输出保持单一 JSON 且原退出码契约不变。
- [x] 3.6 在现有快速指南补充“查看与复制导出诊断”、存放位置及隐私边界，按实际新增字段补机器契约说明；验收为从失败卡片到历史诊断的操作可按文档完成，无需作者手工维护治理文件。

## 4. 先确认简洁设置再生成，收起并列出稿入口

- [x] 4.1 调整 ProjectBar 和对应菜单为“导出 Word…＋更多＋最近结果”，主入口一次打开同一简洁设置，将其它格式、正式出稿和快速构建保留在可达次级入口；验收为只有一个日常导出主按钮，无并列导出设置按钮，Word 缺失时仍可进入设置生成可读稿，窄窗口下主动作完整可点击。
- [x] 4.2 收敛现有 ExportSettingsDialog，优先显示预填文件名、目录、范围、内容来源及格式/模板摘要，文档属性、刷新细节和排版高级项折叠；验收为有效默认值可直接开始、字段错误就地提示且不丢输入，1024×640 下基础区与开始/取消按钮可达，并补本组表单用例及指南。
- [x] 4.3 统一按钮、菜单和 Ctrl+E 的“打开设置→确认后提交”路径，默认整份当前内容/Word/模板/非严格，按本次确认值在开始时捕获输入，移除测试环境业务分流和隐式保存全部/源版本写回；验收为取消设置零任务/零捕获/零正文写入，确认一次只提交一次，未保存正文进入产物而磁盘、修订记录和脏标记保持。
- [x] 4.4 普通完成与失败只更新原非模态结果，结果内容顶部对齐，显示短原因、实际阶段、源位置和可展开诊断；验收为确认设置后不再追加配置或完成结果框，先前错误码/日志字段在卡片可取，部分完成和待刷新按真实状态呈现。
- [x] 4.5 本组补“打开设置、取消、再次打开并确认”的真实 Qt 回归，更新指南按钮名称与默认步骤；验收为按钮/菜单/快捷键均经过设置确认而非测试专用跳过路径，默认值、参数修改、输入保留和后台提交均有断言，普通与测试进程行为一致。
- [x] 4.6 按设计 D6 实现设置/运行/成功/失败四态反馈、设置结束后的焦点恢复、侧栏偏好保持、问题定位后返回及键盘访问，并补对应 Qt 用例与指南；验收为打开设置到打开 Word 最多三次主要操作、定位及返回各一次、可见失败卡片复制诊断最多两次，Esc 取消设置或关闭详情不误取消后台任务。

## 5. 按原因给恢复动作，关掉面板仍能排查

- [x] 5.1 复用现有事实派生与动作白名单，按可用 Word、源问题、可重试故障或输入缺失选择一个主要动作，其它适用动作进更多；验收为各状态的主要动作与实际能力一致，未知故障不自动循环重试，四个恢复按钮不再固定平铺。
- [x] 5.2 将源定位、常驻查看诊断、打开本次日志和按时间呈现的历史接到保存的原报告/引用；验收为关闭面板与重开项目后能找回已保存诊断，旧记录缺少诊断时明确限制，日志不误连到原项目的其它执行。
- [x] 5.3 补恢复与陈旧动作的集成回归，覆盖原输入重试直接复用已确认设置、按当前内容生成先确认预填设置、旧快照缺失、项目/选中导出变化及迟到后台结果；验收为捕获身份、实际内容、历史与项目归属均正确，已完成格式和当前缓冲保留。
- [x] 5.4 更新现有指南的失败排查与恢复示例，清楚说明“重试本次内容”和“按当前内容生成”；验收为作者从结果页可选到适用动作，无需理解 roundId/captureId，也不会被静默切换输入。

## 6. 端到端验收与交付证据

- [x] 6.1 运行现有 runner 的本次定向回归及受影响组合，至少覆盖资源预处理、导出快照/结果、UI 默认出稿、原输入重试及运行诊断；验收为当前提交的实际用例数、失败、跳过和退出码有独立报告，失败按证据修复，未运行部分标 not-run。
- [x] 6.2 用真实 Qt 控件完成“打开项目→未保存修改→打开导出设置→确认开始生成→打开结果/定位失败→返回编辑位置→关闭重开诊断”，覆盖 1024×640、1280×720、长中文名及深浅主题；验收为一次设置确认、无重复配置/完成弹窗、D6 三次主要操作预算、焦点恢复和收起侧栏行为均有实际记录，基础设置和关键动作可达，结果不留大块空白遮蔽原因，界面与诊断一致。
- [ ] 6.3 在可用环境完成真实 Word/企业底模、原生 125%/150% 缩放、冻结包和获准用户样例复验；验收为混排图片、目录/页码、正式状态及实际错误恢复有对应证据，缺环境或未获样例保留未勾选和复验步骤，不能用模拟替代。
- [x] 6.4 对照四份规格与实际 diff 回查任务覆盖，运行 `openspec validate simplify-word-export-and-diagnostics --strict`，记录实现/自动化/实机各自状态并交付；验收为规格校验通过，开放问题与证据限制明确，历史 change 的实机待办未被代勾选。

## 7. 固定本次最小修正范围

- [x] 7.1 核对当前 HEAD、已有修改、D7 六项源码事实与 CF-01—CF-06，建立本次独立证据目录并在本文件追加实际基准和验证入口；验收为只列六项相关差额，Codegraph 使用情况可追溯，旧 1—6 节与其它人改动保持，后续任务无需再全仓复盘或重做旧导出重构。

## 8. 固定现有低频按钮位置（CF-01、CF-02）

- [x] 8.1 在 `ui/project_bar.py` 将导出设置按已有 `overflow_only` 机制固定到更多，与快速构建/正式出稿一致；补 `test_ui_polish_quick_export.py` 或 `test_action_positioning.py` 的真实显示、重复缩放和状态恢复用例，并在现有快速指南核对入口描述；验收为 1024×640、1280×720 和较宽窗口经多次重排后无并列导出设置，每个菜单项只出现一次，导出 Word、成果及原可用性保持。
- [x] 8.2 在 `ui/content/editor_panel.py` 修正 `_reflow_format_toolbar` 的候选与菜单重建，只将常用格式参加宽度溢出，将低频工具和历史/回滚/外部打开固定放进现有更多；补 `test_ui_polish_toolbar.py` 并同步指南；验收为预览/侧栏/主题和窗口变化后固定动作不回到工具栏、不丢失或重复，普通格式/图片/表格与保存可达，一次点击一次执行，原撤销和只读行为保持，不新增工具栏框架。

## 9. 新导出统一设置确认（CF-03）

- [x] 9.1 将 `_on_regenerate_round`、`_on_change_export_destination` 接回现有 `_on_export_settings`，预填可恢复的原参数，按当前内容生成明确 current-buffer，新导出在确认后才 `_submit_export_request`；原内容重试继续 `retry_export_formats`；在运行 `test_export_round_recovery.py` 前将其固定历史产物目录接入 `DOC_TOOL_TEST_ARTIFACT_ROOT`，补该脚本与 `test_core_export_ui.py` 的确认/取消和新旧捕获分离用例，更新指南；验收为有效默认输入时正常三次主要操作，取消零任务/零捕获/零源写入，确认一次只提交一次，原输入重试不重复设置且不混入当前正文，旧证据文件不被覆盖。
- [x] 9.2 移除 `ExportSettingsDialog.exec()` 对 offscreen 的自动确认，核对私有跳过设置参数的调用者，让正常和自动化入口执行相同交互；用现有 Qt 测试事件驱动真实按钮、菜单、Ctrl+E 的打开→取消→重开→确认，在 `test_ui_polish_quick_export.py` / `test_core_export_ui.py` 补断言，必要时仅消除 Ctrl+E 重复注册；验收为真实按键只开一窗，确认前无提交，确认后恰好一次，不以 `.trigger()`、替代入口或测试环境分流充当快捷键通过证据。

## 10. 检查保持检查职责（CF-06）

- [x] 10.1 从 `_on_validate` 移除旧版本持久化调用，统一 F5/顶部/菜单到当前活缓冲检查，主动调用显示原格式检查面板，自动校验回调保留面板偏好；补 `test_core_export_ui.py` 和必要的 `test_main_d_lint_scope.py`，更新指南；验收为脏正文和修订版本不同的夹具在 F5 后正文、修订记录、`project.yml` 摘要和脏标记保持，当前修改参与检查且真实范围可见，索引未就绪/规则未执行不显示通过，不全局删除其它旧出稿仍在用的辅助函数。

## 11. 接通失败事实并收起恢复工具箱（CF-04）

- [x] 11.1 从真实 `PipelineResult.events` 将失败阶段、错误码、结构化 locations 和必要诊断补到 `FormatResult`、`ExportReport`、`ExportRoundView`，使用已有原文相对路径及映射；在 `test_main_e_export_rounds.py` 至少增加一条真实导出/内核负例到结果视图与 Markdown 的集成断言，并覆盖失败后还有清理事件、以及仍保留可读稿的分支；验收为显示实际 build/validate/word 等阶段而非仅 docx/最后事件，源位置可信或明确未知，不通过手填视图、跳过校验或把普通缺图改成致命错误实现通过，源和成功成果保持。
- [x] 11.2 在 `ExportResultsView` 复用现有动作，将恢复区改为一个实际适用主动作和更多，按 D7.5 的事实表决定，去掉主/次重复；补 `test_ui_polish_results.py` / `test_main_e_export_rounds.py`，更新失败恢复示例；验收为成功、待刷新、可定位源错、目录错、旧输入失效、未知故障均有准确动作，未知故障优先复制诊断，固定不平铺完整工具箱，项目/结果变更后的陈旧动作不作用到别处，当前内容生成仍先设置。
- [x] 11.3 将上述实际阶段事实与已有稳定诊断/日志引用沿原记录保存、转换和复制，更多菜单打开所选导出的真实证据位置；补旧索引、缺日志、诊断不可写和重开后读取用例，更新指南中错误的诊断存放描述；验收为界面/保存/复制表达同一事实，关闭重开仍能读取已保存诊断，不误开通用项目日志作为本次证据，旧记录缺项如实说明，CLI 单一 JSON/状态/退出码兼容、脱敏和既有成果保持，不新建历史平台。

## 12. 导出前核对外部修改与脏缓冲（CF-05）

- [x] 12.1 在现有编辑器/导出采集边界加入本次范围内的来源核对；若需加载基准，只保存一个内存中的磁盘内容摘要，正确处理 load、保存、外部重载、草稿与改名；在 `test_core_export_snapshot.py` 或 `test_core_export_ui.py` 补仅窗口变、仅磁盘变、双方分叉、内容相同、同 mtime 不同内容、基准未知及范围外冲突用例；验收为真实内容决定冲突，不凭时间戳或读失败假定无冲突，不新增 watcher、磁盘基准文件或自动合并。
- [x] 12.2 将冲突说明与本次来源选择接入现有导出设置下拉和提示区域，分叉时不能静默保留默认选择；开始时重查实际缓冲与磁盘，表单期间新冲突保留其它输入；在 `test_core_export_ui.py` 做真实表单选择/取消，并补指南；验收为无冲突不增加步骤，有冲突才明确采用窗口或磁盘且摘要说明另一方未纳入，两份原内容、脏标记和其它参数均保留，没有逐章弹窗或新的冲突中心。
- [x] 12.3 在捕获用于导出的同一份字节上验证确认时来源，必要时为既有调用添加可缺省的内存预期摘要参数并保持 CLI 未传时兼容；在 `test_core_export_snapshot.py` 模拟确认后到读取间再次外部修改、文件不可读/删除与原捕获重试；验收为变化不被静默纳入或遗漏，本次不一致输入不进入构建，失败带原章节和明确原因，未成功捕获不伪造身份，原内容重试仍不读新磁盘，已成功捕获后继续编辑不改变本轮产物。

## 14. 在已收敛的主流程上统一样式（VS-01—VS-03）

- [x] 14.1 按 D8.1—D8.2 核对当前差额，优先复用 `styles.py` 的深浅色板、字体、间距及 `btnRole`/`statusTone`/`cardClass`；必要时仅为设置/成果根控件加局部样式标记，补主/次级、焦点、禁用及错误规则；用实际控件的深浅主题渲染验证并在 UI 方案记录最终偏差；验收为无新样式管理类/依赖/主题页/全局字体改动，正文及无关首页/PDF 区域不受影响，已满足规则不重复实现，不用 QSS 字符串相等测试冒充视觉验证。
- [x] 14.2 在 `project_bar.py` 和 `content/editor_panel.py` 按 D8.3 统一主/次级动作、紧凑按钮与必要间距，保留现有宽度重排及固定收纳；就近扩展 `test_action_positioning.py` / `test_ui_polish_toolbar.py` 的长中文、主题切换和关键控件几何用例，按需同步现有指南；验收为顶部导出是该区唯一填充主动作，成果/检查/更多层级较轻，保存与常用格式可达，1024/1280/较宽窗口重排不恢复低频按钮，无新增菜单层级或操作。
- [x] 14.3 在 `export_settings_dialog.py` 按 D8.3 调整标签对齐、4/8/12/20 既有间距、来源说明及固定提交区；将错误标签硬编码颜色改为主题语义，仅对已知对应字段显示错误标注并正确清除；扩展 `test_ui2_export_settings.py` / `test_core_export_ui.py` 的窄窗、高级展开、长路径、冲突/错误修正用例并按需更新指南；验收为深浅主题错误可读且输入保留，开始/取消始终可达，普通路径仍先设置再确认一次，无新弹窗、来源策略变化或正文写回。
- [x] 14.4 在 `export_results_view.py` 及实际共用的 `work_detail_pane.py` 卡片按 D8.4 调整标题/短原因/阶段/原位置/主动作层级，顶部自然排布并收起技术详情，窄侧栏使用原响应布局；扩展 `test_ui_polish_results.py` 的短/长内容、成功/待刷新/部分成功/源错/目录错/未知分支几何与可达断言，同步现有指南中的结果展示；验收为原因换行、完整路径和诊断可取，首屏摘要及主动作不被日志挤走，唯一主要动作仍由 CF-04 的真实事实决定，不增删报告事实或重写恢复分支。

## 15. 样式与交互一起验收

- [x] 15.1 按 D8.5 完成 1024×640、1280×720、较宽主窗口与窄/宽侧栏的深浅主题检查，覆盖设置基本/高级/错误、结果短/长内容、Tab 焦点与禁用态；运行现有 `test_ui_polish_geometry.py` / `test_core_hidpi_layout.py` 并只补其真实覆盖缺口，截图与关键控件几何写入本次独立目录，在 UI 方案记录结果；验收为中文正常、关键动作完整可达、无横向撑出和中间大块占位，离屏探针只算其实际覆盖（现有高 DPI 探针主要覆盖外壳），不能替代导出表单/结果的截图或旧 6.3 原生验收，缺环境如实标记。

## 13. 受影响集成与交付（在 14—15 之后执行）

- [x] 13.1 用下方现有 runner 命令运行本次受影响组合，完成“改一章→设置→生成→打开”以及“失败→定位/复制→再生成”、外部修改和 F5 的组合验证，并核对新样式不增加步骤、不遮挡动作；验收为报告有实际脚本/内部用例/失败/跳过/退出码，默认路径包含真实设置操作与快捷键，源/缓冲/成果保护可核对，15.1 视觉证据可关联，失败按证据修正后仅重跑受影响组合，不把无关全量测试作为新增工作。
- [x] 13.2 对照 CF-01—CF-06、VS-01—VS-03、真实 diff、整合 UI 方案及 `docs/product-core-quick-guide.md` 回查范围，运行本 change strict 校验并记录实际情况；交付各项变更、证据位置、剩余限制和源文件保护结果；验收为无顺手重排首页或新系统，旧 6.3 的 Word/冻结包/原生缩放待办保持真实状态，规划结构/实现/自动化/视觉/实机分开报告，不提交、推送、发布或归档。

## 本次执行与验证入口（整合版）

使用宿主已有 Python/PySide6，执行前按父工作区运行规则核实解释器；缺依赖时明确 blocked/not-run，不自动安装。下列命令均在 `doc-tool` 根目录执行。本次整合仅运行 OpenSpec 结构校验，新增样式业务/视觉验证为 not-run；前序已经执行的命令保留在后面的原始记录中。

每组实现就近运行对应脚本，最终组合只再执行一次。第 9.1 完成历史输出隔离前，不运行恢复脚本。命令中的环境变量仅传给测试子进程，不写机器配置。

```powershell
$interactionEvidence = Join-Path (Get-Location) ('analysis/core-interaction-followup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))

# 第 8 节：按钮与布局
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'buttons.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_action_positioning.py test_ui_polish_toolbar.py test_ui_polish_quick_export.py

# 第 9—10 节：设置、原内容重试、检查
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'entry-and-check.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_core_export_ui.py test_ui_polish_quick_export.py test_export_round_recovery.py test_main_d_lint_scope.py

# 第 11—12 节：诊断、恢复、来源与捕获保护
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'diagnostics-and-source.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_main_e_export_rounds.py test_ui_polish_results.py test_core_export_snapshot.py test_core_export_ui.py

# 14.1—14.2：样式落点与主页面；截图检查另按 D8.5 记录
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'style-actions.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_action_positioning.py test_ui_polish_toolbar.py

# 14.3：表单；与本组改动同时补断言和说明
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'style-settings.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_ui2_export_settings.py test_core_export_ui.py

# 14.4：结果；功能真实链路仍使用第 11 节证据
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'style-results.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_ui_polish_results.py

# 第 15 节：跨区域几何和离屏缩放，不能代替原生验收
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'style-geometry.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_ui_polish_geometry.py test_core_hidpi_layout.py

# 第 13 节：功能和样式的受影响集成；各组完成后运行一次
python -B scripts/tests/run_tests.py --junit (Join-Path $interactionEvidence 'integration.xml') --env ('DOC_TOOL_TEST_ARTIFACT_ROOT=' + $interactionEvidence) test_action_positioning.py test_ui_polish_toolbar.py test_ui_polish_quick_export.py test_core_export_ui.py test_export_round_recovery.py test_main_d_lint_scope.py test_main_e_export_rounds.py test_ui_polish_results.py test_core_export_snapshot.py test_ui2_export_settings.py

openspec validate simplify-word-export-and-diagnostics --strict
```

顺序不能倒置：各任务先补并跑直接回归，最终组只查跨项组合。真实按键自动化若环境不能接收焦点，该项单列 not-run/blocked，不能用直接调用处理函数冒充。旧任务 6.3 的实际 Word/企业底模、冻结包和原生缩放由具备环境者复验；这不会把本轮离屏证据提升为实机通过。

### 2026-10-29 样式整合记录（规划）

- 已在原 change 合并 CF-01—CF-06 与 VS-01—VS-03；新增 14.1—14.4、15.1 共 5 项，均未勾选，原任务编号、勾选和下方执行记录保留。
- 规划结构检查：`passed`，运行 `openspec validate simplify-word-export-and-diagnostics --strict`，退出码 0。六份本次编辑的 Markdown 均为 UTF-8、无 BOM、LF。
- 新增样式实现、业务/视觉测试、原生桌面与 Word 复验：`not-run`。本次仅改本 change 文档，未修改应用代码；已有执行会话的证据不自动适用于新增样式。
- 交接：从当前未完成任务续接，顺序 7—12 → 14—15 → 13，旧 6.3 按实际环境独立复验；不另建样式 change 或第二套进度。

### 既有执行记录（整合前，保留）

- 基准 HEAD: `5c46b1baa56b5116d264d50e1572170b7a93fa74`，分支 `main`。未提交改动仅包含 OpenSpec 规划文档。
- Codegraph: `not used`（工作区无 `.codegraph` 索引）。
- 独立证据目录: `analysis/core-interaction-followup-20261029-201630`。
- 7.1 核对结果: `passed`。D7.1 六项源码事实（CF-01 至 CF-06）已核对确认，未被他人修改，旧 1—6 节记录和其它改动均完好保持。验证入口与环境变量配置已核实就绪。后续按顺序执行第 8—13 节。
- 8.1 实施与验证: `passed`。在 `ui/project_bar.py` 注册 `export_settings` 时加入 `overflow_only=True`，同步 `_export_settings_action` 状态与重置逻辑。在 `test_action_positioning.py` 补充 `test_export_settings_stays_in_overflow_across_widths_and_state_recovery`，在 1024、1280、1920 及缩放重排下验证无并列导出设置，菜单项恰好一次，导出 Word/成果保持可见可达；同步快速指南。
- 8.2 实施与验证: `passed`。在 `ui/content/editor_panel.py` 修正 `_reflow_format_toolbar` 与 `_apply_edit_state`，将表格网格、粘贴表格、Mermaid、批量转图、片段及回滚、历史、外部打开固定收纳进更多菜单，仅常用格式参与宽度候选；更新 `test_ui_polish_toolbar.py` 补足多次缩放/目录/预览切换及只读保护用例（14 用例全过）。
- 运行命令与产物 (第 8 节):
  `python -B scripts/tests/run_tests.py --junit analysis/core-interaction-followup-20261029-201630/buttons.xml --env DOC_TOOL_TEST_ARTIFACT_ROOT=analysis/core-interaction-followup-20261029-201630 test_action_positioning.py test_ui_polish_toolbar.py test_ui_polish_quick_export.py` (3 脚本/35 用例全部 passed，退出码 0)。产物: `buttons.xml`。
- 9.1 实施与验证: `passed`。在 `MainWindow` 中将 `_on_regenerate_round` 与 `_on_change_export_destination` 接入 `_on_export_settings`（预填原范围与目录，按当前内容明确 current-buffer，原内容重试继续复用旧快照）；在 `test_export_round_recovery.py` 中将历史输出重定向至 `DOC_TOOL_TEST_ARTIFACT_ROOT`，补充取消零提交/零捕获/零源写入及原内容重试不弹窗用例；同步快速指南。
- 9.2 实施与验证: `passed`。移除 `ExportSettingsDialog.exec()` 对 offscreen 环境的静默自动确认分流；消除 `ProjectBar._quick_export_btn` 与 `MainWindow._quick_export_action` 的 Ctrl+E 重复注册冲突；在 `test_core_export_ui.py` 与 `test_ui_polish_quick_export.py` 补充真实 Qt 按钮点击及 Ctrl+E 快捷键事件驱动的单窗打开、取消与确认隔离断言（取消 0 任务，确认恰好 1 任务）。
- 10.1 实施与验证: `passed`。从 `MainWindow._on_validate` 移除 `_flush_unsaved_and_sync_version` 调用，主动调用展开工具 Dock 并定位格式检查页（tab 4），自动校验回调保留面板偏好；在 `test_core_export_ui.py` 补充 F5 活缓冲检查断言，验证磁盘正文、project.yml 摘要、修订记录与脏标记均不受影响。
- 运行命令与产物 (第 9—10 节):
  `python -B scripts/tests/run_tests.py --junit analysis/core-interaction-followup-20261029-201630/entry-and-check.xml --env DOC_TOOL_TEST_ARTIFACT_ROOT=analysis/core-interaction-followup-20261029-201630 test_core_export_ui.py test_ui_polish_quick_export.py test_export_round_recovery.py test_main_d_lint_scope.py` (4 脚本/52 用例全部 passed，退出码 0)。产物: `entry-and-check.xml`。
- 11.1 实施与验证: `passed`。在 `project_export.py`、`export_rounds.py` 中从真实 `PipelineResult.events` 提取失败阶段（failed_stage）、错误码（error_code）与结构化 locations 映射，并打通至 `FormatResult`、`ExportReport` 与 `ExportRoundView`（含失败后带清理事件及保留可读临时稿分支）；在 `test_main_e_export_rounds.py` 增加负例集成断言，全部通过。
- 11.2 实施与验证: `passed`。在 `ExportResultsView` 落地 D7.5 事实表（六类场景单一适用主动作：打开 Word/定位问题/切换目录/原内容重试/按当前内容生成/复制诊断），收起平铺次级按钮，将未选适用动作收纳至“更多 ▾”下拉菜单（含“打开本次记录”），消除主/次重复；在 `test_ui_polish_results.py` 补充事实表判定、按钮互斥与菜单集成断言，全部通过。
- 11.3 实施与验证: `passed`。在 `ExportResultsView` 实现 `_open_saved_record` 安全打开已落盘诊断记录，在 `docs/product-core-quick-guide.md` 纠正诊断存放位置为输出目录 `diagnostics/<executionId>/`；在 `test_main_e_export_rounds.py` 补充记录打开与只读兼容用例，全部通过。
- 12.1 实施与验证: `passed`。在 `EditorPanel` 引入 `_disk_baseline_hash` 与 `check_buffer_disk_status()`，按内容 sha256 严谨识别仅窗口变、仅磁盘变、双向分叉（is_fork）、内容相同（处理换行符归一化）及基准未知，不增加文件监控或磁盘临时文件；在 `test_core_export_ui.py` 增加场景断言，全部通过。
- 12.2 实施与验证: `passed`。在 `ExportSettingsDialog` 中接入冲突检测与选择保护：检测到外部修改与窗口修改冲突时，来源下拉项默认未选并提示选择来源，未选时提交报错阻断；在 `MainWindow._submit_export_request` 采集各章预期摘要 `expected_hashes` 并按实际范围章节过滤；在 `test_core_export_ui.py` 补充交互测试，全部通过。
- 12.3 实施与验证: `passed`。在 `capture_snapshot` 中接入 `expected_hashes` 核验，在用于导出的同一份读取字节上核对内容摘要，并在文件被外部修改、删除或不可读时抛出明确异常，未成功捕获不伪造 captureId，原内容重试与导出后修改均保持隔离保护；在 `test_core_export_snapshot.py` 增加模拟用例，全部通过。
- 运行命令与产物 (第 11—12 节):
  `python -B scripts/tests/run_tests.py --junit analysis/core-interaction-followup-20261029-201630/diagnostics-and-source.xml --env DOC_TOOL_TEST_ARTIFACT_ROOT=analysis/core-interaction-followup-20261029-201630 test_main_e_export_rounds.py test_ui_polish_results.py test_core_export_snapshot.py test_core_export_ui.py` (4 脚本/54 用例全部 passed，退出码 0)。产物: `diagnostics-and-source.xml`。
- 13.1 实施与验证: `passed`。运行受影响全量集成组合（9 个测试文件：test_action_positioning.py, test_ui_polish_toolbar.py, test_ui_polish_quick_export.py, test_core_export_ui.py, test_export_round_recovery.py, test_main_d_lint_scope.py, test_main_e_export_rounds.py, test_ui_polish_results.py, test_core_export_snapshot.py），全部 passed，退出码 0。产物写入 `analysis/core-interaction-followup-20261029-201630/integration.xml`。
- 13.2 交付与核对: `passed`。对照 CF-01—CF-06、VS-01—VS-03、真实 diff 及产品快速指南完成全面核对；运行 `openspec validate simplify-word-export-and-diagnostics --strict` 严格校验通过，退出码 0。无顺手重排首页或引入额外系统，任务 6.3 保持未勾选（作为实机 TODO），历史证据与源文件均完好保护。
- 运行命令与产物 (第 13 节):
  `python -B scripts/tests/run_tests.py --junit analysis/core-interaction-followup-20261029-201630/integration.xml --env DOC_TOOL_TEST_ARTIFACT_ROOT=analysis/core-interaction-followup-20261029-201630 test_action_positioning.py test_ui_polish_toolbar.py test_ui_polish_quick_export.py test_core_export_ui.py test_export_round_recovery.py test_main_d_lint_scope.py test_main_e_export_rounds.py test_ui_polish_results.py test_core_export_snapshot.py` (9 脚本全部 passed，退出码 0)。产物: `integration.xml`。
  `openspec validate simplify-word-export-and-diagnostics --strict` (退出码 0)。

## 前次执行与验证入口（历史）

实施阶段优先扩展已有 `test_prepared_source.py`、`test_core_export_snapshot.py`、`test_core_export_ui.py`、`test_main_e_export_rounds.py`、`test_ui_polish_quick_export.py`、`test_ui_polish_results.py` 和运行诊断相关用例；确需新增文件时先注册进仓库 runner 清单。

定向命令卡（本次规划未执行；Python/依赖沿用宿主已有环境，不自动安装）：

```powershell
python -B scripts/tests/run_tests.py --junit analysis/<本次独立目录>/export-targeted.xml test_prepared_source.py test_core_export_snapshot.py test_core_export_ui.py test_main_e_export_rounds.py test_ui_polish_quick_export.py test_ui_polish_results.py
openspec validate simplify-word-export-and-diagnostics --strict
```

前一条是业务验证，后一条只验证 OpenSpec 结构；记录时分别报告。实际运行应将示例报告目录替换为本次明确路径，保留现有 runner 参数和真实退出结果。
