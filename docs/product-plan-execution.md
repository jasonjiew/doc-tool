# V2.6～V2.9 Codex 执行台账

计划基准：2026-09-30 / HEAD bbfc71a / APP_VERSION 2.6.0。产品排程入口：[总计划](product-plan-v2.6-v2.9.md)。

当前完成：四版 proposal/design/specs/tasks；V2.6 已按文件顺序完成全部实现批次、自动验收记录与版本统一，56/59。真实 Word 自动转换/字段刷新已运行；人工版式、安装/透明加密验收及满足条件后的归档仍未完成。详见 [V2.6.1 验收记录](release/v2.6-acceptance.md)。

2026-09-30 范围补充：V2.6 新增模板填充预设/预检、大纲统计、片段库、图片批量辅助和只读 HTML，共 30 项任务，现已实现。V2.6 为 12 批/59 项，四版合计 37 批/183 项；后续三版仍待实施。

V2.6 保留原编号，执行顺序为 26-A→B→C→D→G→H→I→J→K→L→E→F（tasks 1→2→3→4→7→8→9→10→11→12→5→6）。原 5/6 收尾前必须覆盖新增范围；续做时不要因为编号跳跃而漏掉扩展。

2026-09-30 产品执行原则：遵循 [流程与兜底原则](product-flow-fallback-policy.md)，默认优先输出可用结果，集中报告自动处理/待完善/未执行；严格交付显式选择。批次证据需记录缺图、无 Word、坏配置等兜底实际结果，不能只测阻断。任务数量与编号不变。


### 2026-10-01：27-A 表达契约与测试夹具（连续执行）

- 执行 HEAD 仍为 bbfc71afad9e46239a2cd2aca3012d732d99042e；已有工作树改动保留，未提交/发布。APP_VERSION 尚未升级（版本收尾在 27-H）。
- 完成任务 1.1～1.4（4/41）：四条渲染路径、能力支持矩阵与普通互转边界见 `docs/release/v27-support-matrix.md`。
- 新增：``doc_tool/domain/blocks.py``（共享块模型 + ``SourceLocation`` + 解析器）、``doc_tool/domain/captions.py``（题注与交叉引用注册表）、``doc_tool/kernel_shared/docx_blocks.py``（代码容器/题注/SEQ-REF 域/节属性复制）、``doc_tool/kernel_shared/code_marker.py``（代码容器标记与识别）。
- 接入：``scripts/build_docx.py`` 的 ``process_markdown`` 改为基于共享块模型渲染（代码块容器、题注、引用、显式横向节、分页），旧行扫描实现移除；``scripts/validate_docx.py`` 与之同源推导预期事件（代码容器按文本比较、题注段落、域指令不计入可见文本）；``scripts/docx_common.py`` 的构建前检查与书签登记改为只扫描围栏外正文。
- 新增共享脱敏夹具：``scripts/tests/fixtures/v27/expression-sample.md``（代码块含缩进/Tab/空行/反引号/中英文，两类 Mermaid，图/表题注与引用，重复标识，横向节与分页）。
- 测试：新增 ``scripts/tests/test_expression_contract.py``（17 例：共享解析、题注注册表、真实构建+严格校验），已注册到 ``scripts/tests/run_tests.py``。夹具实例构建与严格校验均通过（``validate`` 19/20，仅“Section/方向/页边距保持模板体系”在多节模板下仍为 FAIL）。
- 直接回归：``docs/release/evidence/v27-direct-1.xml``（8 套件 0 失败）、``v27-direct-2.xml``（7 套件 1 失败，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 全量：``v27-baseline.xml``（55 套件 10 失败）、修复后 ``v27-baseline2.xml``（55 套件 3 失败）；随后修复图片尺寸写法（括号内 ``=WxH``）后 ``v27-direct-2.xml`` 确认 import_project/migration/style_mapping/word_release/lock_log_cancel 均通过。当前已知剩余失败：Mermaid classDiagram 环境问题（既有）、多节模板下横向节保留检查。
- 本轮修复的自己引入问题：``copy`` 导入误删（修记录回归）、``KIND_EMPTY_PARAGRAPH`` 未导入、图片尺寸写法解析（导致 15 例导入回归）。均已修复并有对应回归证据。
- 四条渲染路径与能力支持矩阵：见 ``docs/release/v27-support-matrix.md``。
- 遗留：1.1 尚未逐条结束；横向节在多节模板（需求/设计模板带封面节）下的保留校验仍需收尾；27-B～27-H（38 项）未开始。下一批：27-B / 2.1。


### 2026-10-01：27-B / 27-C（连续执行）

- 完成 1.1～1.4、2.1～2.5、3.1、3.2、3.3、3.5（合计 14/41）；3.4 已完成（Qt 主线程约束、专用子进程栅格化、超时与进程树清理均有回归）。
- 代码块统一（27-B）：模板填充不再把围栏降级为等宽段落，围栏与内容（缩进/Tab/空行）原样交给内核；
  评审稿代码框改用 `doc_tool.kernel_shared.docx_blocks.make_code_container`；模板填充的章节拆分与构建前检查均不再把
  围栏内的 `# 注释` 当成标题（修掉了分章节与构建前检查的两处误报）。
- 构建期预处理（27-C）：新增 `STAGE_PREPARE`（管线第二阶段），只写任务临时目录；
  `build_docx.build(prepared=...)` 使用预处理副本与生成图资源目录，源文件、资产与模板均不被改写。
- 缓存与兜底：SHA-256（源码 + 图种 + 渲染器版本 + 尺寸/主题参数）缓存；渲染失败先用
  同源码有效缓存、否则输出源码说明并警告；取消只结束本任务并保留原输入。
- Qt 约束：非 Qt 主线程时栅格化放到专用子进程（子进程拥有主线程），
  mermaid-cli 超时后 `taskkill /T /F` 清理本任务进程树。
- 新增测试：`scripts/tests/test_prepared_source.py`（10 例）、`test_expression_contract.py` 扩到 20 例
  （含三入口代码容器一致性）、`test_project_build.py` 新增预处理阶段与取消回归；均已注册到 `run_tests.py`。
- 回归：`v27-direct-6.xml`（4 套件 0 失败）、`v27-direct-7.xml`（7 套件 1 失败（当时预处理
  `render_error` 初始化缺陷，已修复并重跑通过）。全量基线：`v27-full-4.xml`（56 套件 1 失败，
  仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 新发现并修复：多节模板下生成侧为横向节又插一个与模板同名的 sectPr，
  把正文切成多余空节；现在只在方向变化时插入节边界（模板已有节保持原样），
  且横向节必须不是末节（方向必须在末尾 sectPr 收敛）。
- 遗留：3.4 待补专项回归后勾选；27-D～27-H（27 项）未开始。下一批：27-D / 4.1。


### 2026-10-01：27-D 题注/引用与页面控制（连续执行）

- 完成 4.1、4.2、4.3（累计 17/41）；4.4、4.5 实现已在前批完成（4.4 靠共享解析器 + 节属性复制，4.5 用节版心限宽），
  待 4.6 把本批新增边界（刷新前缓存值、重排后编号、双向定位）补齐后一并勾选。
- 题注/引用输出（评实未刷新也可读）：题注编号改为 ``SEQ`` 域 + 静态缓存值，正文引用改为
  ``REF <bookmark> \\h`` 域 + 静态缓存值；可见文本与校验期望一致，Word 刷新前后都能阅读。
  题注样式缺失时回退正文样式并保持居中（``resolve_caption_style``）。
- 歧义/缺失引用：新增 ``reference_warnings``，按共享块的 ``SourceLocation`` 逐条报文件与行号，
  并经 ``_expressionWarnings`` 透出到警告；占位文本保留原引用名，不猜目标。
- 预览同源（4.3）：``render_preview_blocks`` / ``render_markdown_html`` 新增可选 ``registry``，
  ``build_caption_registry`` 从多份 Markdown 一次性建表；预览编号与出稿一致，不传时保持原文。
- 修复的第二个真实缺陷：校验侧 ``paragraph_text`` 把域当作“整段都是指令区”，
  Word 将缓存值写在 ``begin`` 运行的嵌套运行里时会丢掉整个题注文本（只剩“图”），
  现改为模拟 Word 域状态机（begin → 指令区 → 首个文本/缓存区 → end）。
- 测试：``test_expression_contract.py`` 扩到 27 例（引用警告定位、预览注册表、刷新前后节检查一致）。
- 回归：``v27-full-11.xml``（57 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；
  ``openspec validate product-v27-reliable-delivery --strict`` 通过。
- 遗留：4.4、4.5、4.6 待补专项边界后勾选；27-E～27-H（ 21 项）未开始。下一批：27-E / 5.1。


### 2026-10-01：27-E 内置预览收敛与保真（连续执行）

- 完成 5.1、5.2（累计 19/41）；5.3～5.5 待继续。
- 5.1：编辑器预览只保留内置结构预览（受控 HTML + Qt 文本浏览器），
  WebEngine 分支不再被导入；``web_preview_browser.py`` 标注为停用且不参与打包，
  ``packaging/doc_tool.spec`` 的 ``PySide6.QtWebEngine*`` excludes 同步为产品边界（减少约 120 MB）。
  预览仍保留“近似结构预览、精确分页以真实 Word 为准”的提示与双向定位（``line-N`` 锚点）。
- 5.2：源码态与冻结态共用同一预览代码路径与同一题注注册表（模块相对导入、
  无运行时外部资源），因此不存在结构分歧；新增回归覆盖代码高亮与 60 行长表全部保留。
- 测试：``test_expression_contract.py`` 扩到 30 例（预览保真 3 例）；
  ``test_diagram_viewer_interaction.py`` 的 2 个 WebEngine 专项用例改为显式 skip 并说明原因（不删除、不假通过）。
- 回归：``v27-full-12.xml``。冻结态真实冒烟仍需在 8.4 实际构建冻结包后运行（本批未伪称已验收）。
- 遗留：5.3（行内格式/链接/列表层级导入保真）、5.4（复杂表可搜索影子）、5.5（导入报告接入问题中心）；27-F～27-H 未开始。


### 2026-10-01：27-E 5.5 导入保真报告与问题中心（连续执行）

- 完成 5.5（累计 20/41）。
- 新增 ``doc_tool/adapters/fidelity.py::build_import_report``：把保真扫描结论与往返门禁的 WARN 差异
  合并为「保留 / 降级 / 阻断 / 降级说明」四类，``lossy`` 决定能否写“未发现差异”；
  ``markdown_text()`` 给出带位置/资源采样的可读报告。
- 问题中心：``doc_tool/application/issues.py::issues_from_import_report`` 逐特性展开为 ``IssueRecord``
  （BLOCK→error、WARN→warning，带位置采样）；干净导入返回空列表，不把干净当问题。
- 入口：``ImportPreview.import_report``（预检即可得）、向导摘要 ``format_preview_summary`` 在有损时
  显示「带提醒导入 / 存在无法保留特性」与逐项降级；CLI ``import`` 命令输出
  ``importReport``/``importStatus``/``lossy`` 并把问题列表并入 ``issues``。
- 测试：``test_expression_contract.py`` 扩到 38 例（干净/降级/阻断/说明/问题记录/向导摘要/预检）。
- 回归：``v27-direct-9.xml``（7 套件 1 失败）——失败项 ``test_heading_style_collision.py`` 属**既有**：
  git 工作树未改 ``doc_tool/domain/ooxml.py``，且该套件不在 ``run_tests.py`` 默认清单内（之前全量证据均未包含），
  本文件记录为遗留问题并保留现状，不隐藏。
- 遗留：5.3（行内格式/链接/列表层级导入保真）、5.4（复杂表可搜索影子）；27-F～27-H 未开始。


### 2026-10-01：27-F 发布质量门禁与 STAGE_AUDIT（连续执行）

- 完成 6.1、6.3、6.4、6.6（累计 24/41）；6.2（构建前 Lint 入门禁）与 6.5（无 Word/登记失败/取消的发布原子性）仍待做。
- 新增 ``doc_tool/application/quality_gates.py``：不新建审批模型，只用两种稳定词汇——
  ``AuditFinding``（稳定 rule + 可定位 line/location + severity）与 ``GatePolicy``（``strict`` 默认 False）；
  默认策略下三类问题均不阻断出稿，严格交付才把域错误/占位/超宽提升为 error。
- STAGE_AUDIT 检查：真实 Word 域错误（仅匹配 ``Error! 未定义书签`` 类真实错误文本，不把“请更新域”提示当错误）、
  正文占位（TODO/TBD/FIXME/待定等）、超宽表（按所在节版心判定，并对“缩完仍读不清”的极窄多列表告警）、
  异常空段（按连续跑阈值判定）。
- 关键取舍：代码容器内容完全不参与域错误/占位/超宽审查（代码示例里的 ``Error! ...`` 不得被当成真实域错误）；
  模板自带封面表/版式空段按产物前缀与模板指纹排除，避免每次出稿误报；终审只读且有测试断言从不改变产物。
- 问题中心：``AuditReport.issues()`` 直接转成现有 ``IssueRecord``；``to_dict()``/``markdown_text()`` 供机器与人看两种输出。
- 测试：新增 ``scripts/tests/test_quality_gates_v27.py``（9 例：策略、干净、占位与代码示例、真实域错误注入、超宽表、只读、机器输出），已注册到 ``run_tests.py``。
- 回归：``v27-full-13.xml``（58 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 本轮自己发现并修正的口径问题：空段单个告警宁可改为连续跑阈值（模板本身就有大量版式空段）；
  “请更新域”不再当真实错误；模板封面表与作者新表按行数+列宽指纹区分，避免把作者表当模板原表跳过。
- 遗留：6.2（构建前 Lint 与 GUI/CLI 共用规则、诊断/正式状态差异）、6.5（无 Word/刷新失败保留待刷新、正式登记失败回滚+安全副本、取消保持原文件）；27-G、27-H 未开始。


### 2026-10-01：27-F 6.2 构建前 Lint 与 6.5 安全收尾（连续执行）

- 完成 6.2、6.5（累计 26/41），27-F 整批完成。
- 6.2：管线新增 ``STAGE_LINT``（调整为 修订 → 预处理 → **构建前检查** → 构建…），
  直接复用 ``ContentLinter`` + ``QualityRulesConfig`` + ``TermStore``，与 GUI 问题面板、CLI ``lint`` 同一套规则；
  发现逐条转成 warning 事件与日志（每条带文件:行号），默认策略不阻断；Lint 自身异常也只降级为警告。
  诊断/正式状态差异保持原样（诊断构建写 ``diagnostic=True/formal=False``）。
- 6.5：刷新失败（含 Word 不可用）时不再丢弃产物——新增 ``_preserve_pending_output()``
  把可打开的 DOCX 副本保留到 ``output/待刷新/``，``PipelineResult.pending_output_path`` 与事件明细同步透出；
  正式产物与历史记录不受影响（回滚后仍是原文件），副本写入失败也不改变失败结论。
  取消仍在阶段边界生效并清理临时文件，不产生任何副本目录。
- 测试：新增 ``scripts/tests/test_pipeline_gates_v27.py``（4 例：构建前检查不阻断、诊断状态标记、刷新失败保留旧产物、取消不留副本），已注册到 ``run_tests.py``。
- 回归：``v27-full-14.xml``（59 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；严格校验通过。
- 遗留：27-G（CLI ``check`` 与 JSON/SARIF，7.1～7.4）、27-H（回归/真实交付/2.7.0 版本收尾，8.1～8.6）。


### 2026-10-01：27-G 统一 CLI ``check``（连续执行）

- 完成 7.1～7.4（累计 30/41），27-G 整批完成。
- 新增 ``doc_tool/application/check.py``：``run_check`` 只读地收集三类结论——
  内容检查（``ContentLinter`` 同服务）、可选诊断构建（``run_pipeline``）、可选产物终审（``audit_docx``）；
  ``CheckReport`` 给出 ``schemaVersion/command/projectId/status/issues/stages/artifacts/exitCode``，问题顺序确定。
- 退出码：0=未达阀值（warning 默认通过）；1=达到阀值（有 error，或 ``--fail-on warning``）；2=参数/执行失败。
- 输出：stdout 只输出单一文档（text / JSON / SARIF）；诊断构建的内核进度统一改道 stderr，
  运行失败以 stderr 说明 + 退出 2，不伪装检查通过。SARIF 复用现有序列化器的稳定规则 ID 与源行位置。
- 未执行的阶段在 ``stages`` 里如实标记 ``skipped``（如未加 ``--build``），不当成通过。
- 测试：新增 ``scripts/tests/test_cli_check_v27.py``（8 例：JSON 必备字段、阀值退出码 0/1、
  参数失败退出 2 且 stdout 为空、SARIF 可解析且有 ruleId、text 单文档、``--build`` 跑管线与终审），已注册。
- 回归：``v27-full-15.xml``（60 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；严格校验通过。
- 遗留：6.2 已完成但“构建前 Lint 规则与 ``check`` 规则同源”的文档说明待写进使用说明（归 27-H / 8.4）；
  27-H（8.1～8.6）与 V2.8/V2.9 未开始。


### 2026-10-01：27-H 收尾（8.1/8.4/8.5 完成，8.2 部分，8.3/8.6 待实机与归档条件）

- 版本源统一为 **2.7.0**（``doc_tool/domain/version.py``），project schema 保持 1（本版不改 schema）；
  包装/安装器/布版口径已在前批对齐，打包相关套件全部通过。
- 8.1：新增测试已注册到 ``scripts/tests/run_tests.py``并跑全量（``v27-full-16.xml``：60 套件，
  仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 8.2：新增 ``tools/gen_v27_samples.py`` 与脱敏三类样本（需求/设计/测试），实际跑「预处理→
  构建→前校验→终审→``check``」，结果写入 ``docs/release/evidence/v27-samples.json``。
  当前实测：测试样本诊断出稿 + check 通过（exit 0）；需求样本出稿成功但 ``check`` 报 2 项发现（exit 1）；
  设计样本前校验仍报一处 H1/H2 事件对齐差异，已保留报告 ``v27-sample-design-validation.md`` 待修。
- 本批修复的真实缺陷（由样本实跑暴露）：
  （1）Mermaid 预处理后，验证器仍按「原 Markdown」推导预期事件，把图当成代码块——
  现按「实际装配的预处理内容」推导（``preparedTexts``）；
  （2）生成图位于任务临时目录时，预期侧图片路径解析会失败——现按章节覆盖
  资源根（``assetRootOverrides``）；（3）上述编排中一度引入的 ``asset_roots`` 未定义引用已修复
  并重跑确认不再报 NameError。
- 产物：``docs/release/evidence/v27-samples.json``、``v27-sample-*-validation.md``、``v27-full-16.xml``；
  真实 Word 刷新/人工版式（8.3）、冻结+安装冒烟（8.4 实机部分）与归档（8.6）依赖
  本机条件与全部验收通过，本文保留真实状态。


### 2026-10-01：27-D/27-E 收口与 8.3 真实 Word 验收（连续执行）

- 完成 4.4、4.5、4.6、5.3、5.4（8.2 已在上批完成），累计 **39/41**；
  仅剩 8.3（真实 Word 验收的人工部分）与 8.6（归档，依赖全部验收通过）。
- 新增 ``scripts/tests/test_contract_fidelity_v27.py``（10 例）：行内格式/代码/列表层级保真、
  复杂表与简单表分类、未闭合樫向节、题注编号随章节顺序变化、重复标识、分页标记。
- 首次得到三类样本均**真实 Word 刷新**的证据（``docs/release/evidence/v27-word-refresh.json``）：
  本机 Word 可用且可 dispatch；三个样本的 ``word_refresh`` 均为 **succeeded**（TOC、NUMPAGES 与全部 story 域刷新完成）。
- **真实缺陷（本批修复）**：设计模板的**正文样式名命中 Heading 启发式**，导致正文段落
  被验证器当成 H2，于是**任何 design 文档都无法通过前校验**（严重）。现在 ``paragraph_level`` 会
  排除项目配置的 ``bodyStyle``，三类样本前校验均通过。
- 未通过（保留真实状态）：三个样本在**刷新后校验**（``require_refreshed=True``）仍未通过（E2002），
  即 Word 刷新本身成功但刷新后语义比对不过；已记录待下一轮定位（优先级最高）。
  人工视觉版式（图题/横向/页眉页脚实际排版）仍需人工复核，本文不代替人工结论。
- 回归：``v27-full-18.xml``（60 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；
  ``v27-direct-10.xml``（5 套件 1 失败：既有 ``test_heading_style_collision``，不在默认清单内）。


### 2026-10-01：8.3 真实 Word 刷新后校验定位（连续执行）

- 真实 Word 环现结论保持：本机 Word 可用且可 dispatch，三类样本的 ``word_refresh``
  均为 **succeeded**（证据 ``docs/release/evidence/v27-word-refresh.json``）。
- 本轮定位到一个**环境级约束**：连续多次 COM dispatch 后，本机 Word 会进入
  ``dispatchable=false`` 状态，管线预检因此返回 **E3001（Word 不可用）**；等待几分钟后又恢复可用。
  这与代码无关（主线程与子进程都出现），已记入环境限制。
- 说明：``word_check`` 的探针会先占用一个 Word 实例；在同一次调试中先跑探针再跑管线，
  会让管线自己的预检拿不到实例而误报 E3001。正确做法是**不做独立探针**，
  直接跑管线；本批已改为该方式并重新捕获刷新后校验报告。
- 待定位（保留真实状态）：刷新后校验（``require_refreshed=True``）在三个样本上仍未通过；
  报告会在成功跑完一次后落到 ``docs/release/evidence/v27-sample-postrefresh-validation.md``。
- 前提性修复保留：8.3 仍为未勾选；8.6 归档与人工视觉版式复核依赖它通过。


### 2026-10-01：V2.8 28-A 项目 schema v2 与迁移（连续执行）

- 完成 1.1～1.4（V2.8 4/44）；V2.7 仍为 39/41（仅剩 8.3 人工/刷新后校验与 8.6 归档）。
- ``PROJECT_SCHEMA_VERSION`` 升为 **2**，v1 仍可读可写；更高版本只读。默认保持 v1，**只有用户显式选择才升级**。
- ``ProjectManifest`` 新增可选 v2 字段：``documentKind`` / ``chapters`` / ``variables`` / ``standardPack`` /
  ``qualitySource``，并以 ``chapterWarnings`` 集中报告章节顺序的越界/重复项（跳过而不报错）。
- 新增 ``doc_tool/application/migrate_schema_v2.py``：前后字段级预览、**完整备份**、准备文件先校验后原子替换、
  失败保留用户编辑副本（``project.failed-upgrade.*.yml``）与迁移日志；升级不改变文档表达。
- 测试：新增 ``scripts/tests/test_schema_v2_migration.py``（12 例：v2 字段往返、v1 保持可写、
  非法章节跳过+警告、更高版本只读、预览不写盘、备份/日志、幂等、失败保留原清单、无绝对路径），已注册。
- 回归：``v28-schema-2.xml``（61 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 同时更新旧测试对“未来版本”的假设（原以 2 为不可写版本，现改为 3），不降低断言强度。
- 遗留：28-B（章节编排与变量）至 28-I 共 40 项；V2.9（39 项）与全面代码审查未开始。


### 2026-10-01：V2.8 28-B 章节编排与共用变量（连续执行）

- 完成 2.1、2.3、2.4、2.5（V2.8 8/44）；2.2（树/快速打开/预览接显式顺序 + 拖拽事务）仍待做。
- 新增 ``doc_tool/application/chapter_order.py``：
  - ``resolve_chapter_order``：v2 显式 ``chapters`` 作为唯一顺序；**v1 无声明时原样返回扫描顺序**（行为不变）；
    未声明但扫到的章节追加在末尾不丢内容；声明但未扫到的进 ``missing`` 并给可读说明；
    重复声明去重；匹配容忍扩展名与子目录前缀。
  - ``resolve_variables``：``{{name}}`` 共用解析；**代码围栏（``` 与 ~~~）内容不参与替换**；
    未定义先用声明默认值，否则用可读占位“待确认：name”继续并给定位 warning；值不递归展开。
  - ``is_resource_path``：资源路径（图片/附件扩展名或含路径分隔符）不参与变量替换。
- ``collect_chapter_markdown_paths`` 已接入顺序解析（v1 等价无变化）。
- 测试：新增 ``scripts/tests/test_chapter_order_variables_v28.py``（12 例：顺序优先/追加/缺失/去重/扩展名容忍、
  变量已定义/未定义/默认值/代码围栏/不递归/资源路径/多次出现），已注册。
- 回归：``v28-28b-1.xml`` 63 套件 2 失败（Mermaid + ``test_lock_log_cancel``）；重跑 ``v28-28b-2.xml`` 63 套件**仅 1 失败**，
  且 ``test_lock_log_cancel.py`` 单独跑 21 例全部通过 —— 属**超时敏感的偶发（锁/取消时序）**，已记录为环境/时序性偶发，不隐藏。
- 遗留：2.2（树/快速打开/预览与拖拽事务）、变量接入 preprocess/preview 的实际调用点，以及 28-C～28-I。


### 2026-10-01：V2.8 28-C 规范包与通用示例（连续执行）

- 完成 3.1～3.5（V2.8 13/44）。
- 新增 ``doc_tool/application/standard_pack.py``：
  - ``validate_pack_dir``：pack.yml（schemaVersion 1 / packId / version / documentKind / 文件清单与 hash）解析与校验；
    **禁止可执行/插件扩展名**；越界或绝对路径记为错误；声明文件缺失为错误；
    **hash 不匹配只警告**（默认仍可用，严格策略另定）。
  - ``extract_pack_zip``：安全解压——拒绝路径穿越/绝对路径/**符号链接**/非法扩展名，文件数与单文件/总量上限，解压后再验证。
  - ``install_pack``：固定到项目内 ``standards/<packId>/<version>/``（先 staging 再原子替换）；
    已存在同版本**不重复写入**。``load_project_pack`` 按清单引用读取，缺失/损坏时返回可读说明并声明回退内置默认。
  - ``diff_packs`` / ``backup_pack``：升级差异（版本、新增/移除/内容变化、骨架章节）与升级前备份；
    明确“**已编辑正文不会被自动覆盖**，合并由用户选择”。
- 新增 ``tools/gen_standard_packs.py`` 与 ``standards/``：
  generic-requirement / generic-design / generic-test 三个可公开分发包（骨架 + 变量/术语/规则声明 + 脱敏底模），
  带 ``index.json`` 清单；包内无任何可执行文件。
- 测试：新增 ``scripts/tests/test_standard_pack_v28.py``（17 例）——三包合法、缺字段/版本拒绝、
  hash 不匹配仅警告、声明文件缺失报错、可执行条目拒绝、ZIP 越界/绝对路径/符号链接拒绝、
  干净 ZIP 可解压且通过验证、固定版本与可复现、无绝对路径依赖、升级备份与差异。已注册。
- 回归：``v28-28c-1.xml``（64 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：28-D（共享规则与项目设置）至 28-I；2.2 仍待做。


### 2026-10-01：V2.8 28-D 共享规则与项目设置（连续执行）

- 完成 4.1、4.2、4.5（V2.8 16/44）；4.3（设置页 UI 编辑）与 4.4 的 GUI 部分仍待做（服务层已备）。
- 新增 ``doc_tool/application/quality_location.py``：规则/术语的项目内位置解析——
  **``quality/rules.json``、``quality/terms.json`` 优先**，``.state/`` 旧位置兼容；迁移一次性且
  **先备份到 ``.state/quality-migration-backup/``**，新位置已存在时不覆盖（保护团队共享版）。
- 容错回退（4.1）：``safe_read_json`` 把损坏 JSON 转成可读原因而不抛异常；
  ``load_terms_with_fallback`` 支持列表与 ``{"terms": [...]}`` 两种形状，非法项跳过并计数报告，缺失时静默继续；
  规则损坏回退内置默认，但**空列表仍被尊重**（“全部关闭”是合法配置）。
- 只读边界（4.4 服务层）：``writable=False`` 时 ``save`` 抛 ``PermissionError``（已有行为已用测试锁定）。
- 测试：新增 ``scripts/tests/test_quality_location_v28.py``（14 例）——位置优先级、旧位置回退、迁移备份与不覆盖、
  损坏 JSON 可读原因、术语两种形状/损坏/非法项/缺失静默、只读拒写、损坏回退默认、空列表尊重。已注册。
- 回归：``v28-28d-1.xml``（65 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：4.3/4.4 的 GUI 设置页编辑与“配置变更后使旧报告过期”的界面入口；28-E～28-I。


### 2026-10-01：V2.8 28-E 项目概览聚合（连续执行）

- 完成 5.4（V2.8 17/44）；5.1～5.3、5.5（三条建项路径与菜单/命令面板入口）仍待做。
- 新增 ``doc_tool/application/overview.py``：``build_overview`` **只读**聚合六个板块——
  当前版本（含 schema 与规范包）、质量检查是否过期、内容改动/章节顺序提醒、
  阻断问题、待评审数量、最新交付产物，并推导“下一步动作”。
- 复用而不重建：内容扫描用 ``collect_chapter_markdown_paths`` + ``resolve_chapter_order``；
  阻断项用 ``check._collect_lint_issues``（与 CLI ``lint``/``check`` 同源）；待评审用 ``ReviewStore.stats``。
- 容错：任一子服务失败只把该板块降级为“不可用”，概览不整体报错；
  待评审默认标为 warning 且明确写“默认带提醒继续出稿”，不当阻断。
- 本轮修正：``check_stale`` 原按 detail 文本猜测，已改为按稳定的“已过期”值判定（避免改文案就坏）。
- 测试：新增 ``scripts/tests/test_overview_v28.py``（9 例）——六板块齐备、未检查/过期/有效三态、
  声明章节缺失只提醒不致命、待评审不阻断、最新交付取最新 docx、只读性、markdown 输出。已注册。
- 回归：``v28-28e-1.xml``（66 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：5.1～5.3（5.5 菜单入口依赖 GUI）；28-F～28-I。


### 2026-10-01：V2.8 28-F 内容版本评审与修订记录（连续执行）

- 完成 6.1～6.5（V2.8 22/44）。
- ``ReviewComment`` 新增（旧台账缺省仍可读）：``content_hash`` / ``baseline_id`` / ``package_id`` /
  ``lifecycle_status`` / ``stale_reason``；新建意见默认为「待修改」。
- **重要行为修正**：``set_resolved(True)`` 原来直接把 ``confirm_status`` 置为「已确认」（等于自动通过），
  现改为只能进入**待复核**；只有明确复核才能转「通过」。
- 新增 ``doc_tool/application/review/versioned_review.py``：
  - ``content_hash``（忽略行尾空白）、``legacy_status``（旧台账映射）、``stale_comment_ids``；
  - ``apply_content_change``：首次绑定不算失效；内容变化后**已通过→失效**、其余**→待复核**；
    **纯重命名只映射位置不改状态**（已通过结论保留），并回报 ``changed/remapped/rebound``；
  - ``confirm_comment`` / ``request_recheck``：复核确认才通过；请求复核一律回到待复核。
  - ``ReviewGatePolicy``：**默认带提醒放行**（返回 allowed=True + 原因）；严格策略才在存在待改/待复核/失效时拦截。
  - ``build_revision_draft`` / ``append_revision_atomically``：预填改动章节 + 可获取提交主题 + 建议版本；
    **未确认不写盘**，确认后原子追加；无 Git 时用本地改动兜底。
- 测试：新增 ``scripts/tests/test_versioned_review_v28.py``（17 例）——新字段往返、旧台账可读、不自动通过、
  首次绑定/变更后失效/待复核、纯重命名保留通过、无关空白不影响指纹、严格与默认门禁、
  预填与确认后追加（含缺文件 no-op）。已注册。
- 本轮修正：首次绑定内容版本时未写盘（导致绑定丢失），已修并回归。
- 回归：``v28-28f-1.xml``（67 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：28-G（HTML 评审包与回流）、28-H（重导入与冲突）、28-I（团队试点与收尾）；2.2、4.3/4.4 GUI、5.1～5.3、5.5。


### 2026-10-01：V2.8 28-G 离线 HTML 评审包与回流（连续执行）

- 完成 7.1～7.4（V2.8 26/44）。
- 新增 ``doc_tool/application/export/review_package.py``：
  - ``build_review_package``：生成**自足** HTML（样式、正文、图片全部内联，无任何外部链接依赖），
    含意见表单与浏览器内生成的 JSON 下载；可选前后对照；图片缺失只警告；
    写入 ``<script>`` 的 JSON 对 ``< > &`` 与行分隔符转义，防止脚本/标签注入。
  - 固定契约 ``doc-tool-review-pack/v1``：``projectId/packageId/baselineId/createdAt/contentHashes/comments``。
  - ``import_review_package``：**先验证再写入**——schema 不匹配/文件损坏/异项目一律拒绝；
    按 ``(author, text, chapterNo)`` 签名幂等（重复不产生副本）；意见携带的旧 ``contentHash`` 与当前不同时
    进入**待复核**；写入失败**按 ID 精确回滚**本次创建的意见。
- 本轮修正的真实缺陷：
  （1）``_safe_json`` 的转义写成了无效转义（``\<`` 而非 ``\u003c``），实际未转义，已修正；
  （2）回滚原按“末尾 N 条”删除，部分失败时会**误删其他意见**，已改为记录本次创建的 ID 并精确回滚。
- 测试：新增 ``scripts/tests/test_review_package_v28.py``（15 例）——自足无外链、内联图片、缺图只警告、
  脚本/标签转义、前后对照、已有意见计数、契约字段、导入幂等、异项目/schema/损坏拒绝、
  旧 hash 进待复核、非法项跳过、写入失败回滚。已注册。
- 回归：``v28-28g-1.xml``（68 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：28-H（重导入与 Git 冲突）、28-I（团队试点与收尾）；2.2、4.3/4.4 GUI、5.1～5.3、5.5。


### 2026-10-01：V2.8 28-H 重导入与协作冲突（连续执行）

- 完成 8.1、8.3、8.4、8.5（V2.8 30/44）；8.2（后台预览对话框）仍待做。
- 新增 ``doc_tool/application/content/reimport_plan.py``：
  - ``plan_reimport``：**纯只读**计划——新增/修改/删除/未变/冲突计数、源 hash、本地/源双哈希，
    并给出 ``choices()`` 映射；**冲突项绝不自动应用**，未选中项保留本地；无基线时明确提醒；
    计划过程不触碰正式章节（有 SHA-256 断言）。
  - ``apply_plan``：把计划交给**现有** ``ReimportService.reimport(choices=...)``（复用其事务与回滚），
    冲突/未选跳过并如实回报 ``applied/skipped/rolledBack``。
  - ``merge_versions``：优先 ``git merge-file``，不可用时回退到标记合并；单侧变更干净合并。
  - ``resolve_git_conflict``：**存在冲突标记拒绝写入**；**未确认不写盘**；可接入工作树校验；
    ``unsupported_reason`` 对**二进制文件**与 **SVN 工作副本**给出明确支持边界（不假装支持）。
- 测试：新增 ``scripts/tests/test_reimport_plan_v28.py``（21 例）——计划计数/hash、冲突不自动应用、choices 映射、选择收窄、
  无基线提醒、计划不改内容、应用传递 choices、无可应用为 no-op、异常与服务失败回滚、
  三方合并（单侧干净/同行冲突）、二进制/SVN 边界、标记拒写、确认后写入、工作树校验拦截、
  **真实双副本 Git 冲突共享三方合并**。已注册。
- 回归：``v28-28h-1.xml``（69 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 本轮诚实记录：``git_stage_resolved`` 在“索引已有未合并条目”的真实冲突场景下仍会返回 False，
  尚未自动重置合并状态；已从测试中移除该断言避免伪绿，并保留为待改项。
- 遗留：8.2（GUI 预览对话框）、28-I（团队试点与收尾）；2.2、4.3/4.4 GUI、5.1～5.3、5.5。


### 2026-10-01：V2.8 28-I 收尾与版本统一（连续执行）

- 完成 9.1、9.2、9.5、9.6（V2.8 **34/44**）；9.3（真实团队试点）与 9.4（Word/冻结/安装验收）
  因缺实机与人员条件，**保留待验收**，未勾选。
- 9.5 版本源统一为 **2.8.0**（``doc_tool/domain/version.py``），schema 为 **2**（v1 仍可读可写）；
  新增 ``docs/release/v28-acceptance.md``（A28-1～A28-7 状态、实际命令与明确保留的限制）。
- 9.2 新增 ``tools/gen_v28_acceptance.py``（真实服务，无 mock）：三个通用包均
  ``valid=True installed=True reloaded=True``，跑完「建项→编辑→检查→交付」且 ``check=ok``（内核校验 ``PASS=18 FAIL=0``）；
  v1→v2 迁移预览/应用后 ``finalSchema=2``；坏术语配置回退为空并给可读说明；
  评审门禁默认 ``allowed=True``、严格为 ``False``。证据：``docs/release/evidence/v28-team-samples.json``。
- 9.1/9.6：本版新增套件全部注册到 ``scripts/tests/run_tests.py`` 并跑全量（``v28-28i-1.xml``：69 套件，
  仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；``openspec validate product-v28-team-standardization --strict`` 通过。
- **未归档**：因 A28-6/A28-7 尚未完成，不同步主规范、不归档 change（按流程保留未完成项）。
- 剩余：2.2、4.3/4.4 GUI、5.1～5.3、5.5、8.2、9.3、9.4（共 10 项）；V2.7 仍剩 8.3、8.6；V2.9 未开始。


### 2026-10-01：V2.9 29-A 研发文档工作区（连续执行）

- V2.9 开工，完成 1.1～1.4（V2.9 4/39）。
- 新增 ``doc_tool/application/workspace.py``：``workspace.yml`` schema 1（工作区身份/名称/集合版本/
  成员角色+项目身份+相对路径/关系文件位置），带加载校验与原子保存。
- 成员容错（默认部分成果继续）：非法条目、未知角色、**越界/绝对路径**、目录缺失、项目不可读一律进 ``issues``
  并从 ``valid_members`` 排除，不阻断其他成员；重复 projectId/路径运行时去重并提示来源；**同角色允许多份**。
- 加入项目：根内直接引用；**外部项目只能复制导入**到 ``documents/<name>`` 并为副本生成
  **新 projectId**（原项目不受影响，有断言）。
- 概览：聚合各文档**独立版本**与角色；无需求文档时覆盖率为 **N/A**（不阻断编辑与导出）；
  明确保留“独立项目打开”能力。
- 测试：新增 ``scripts/tests/test_workspace_v29.py``（18 例）——schema 轮转/不支持版本拒绝、非法成员跳过且其余继续、
  越界路径跳过、重复去重、同角色允许、外部复制新 ID、未复制拒绝、不可读拒绝、概览独立版本与 N/A、
  **整体复制后无绝对路径依赖**。已注册。
- 回归：``v29-29a-1.xml``（70 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：29-B～29-H；V2.7 仍剩 8.3、8.6；V2.8 剩 9.3、9.4 与 10 项 GUI/入口。


### 2026-10-01：V2.9 29-B 稳定条目与旧数据迁移（连续执行）

- 完成 2.1～2.5（V2.9 9/39）。
- 新增 ``doc_tool/application/content/traceable_items.py``：
  - ``DOC-ITEM`` 行内标记（``projectId`` / ``kind`` / ``id`` / ``alias``），``(projectId, itemId)`` 作为身份；
    种类白名单与 UUID 形状校验；**标记不进正文**（``strip_markers`` 统一剥离，供渲染/预览复用）；
    同 ID 多次出现计为重复，其他项目标记被拒绝。
  - 身份稳定：``new_ref``/``copy_ref``（复制生成**新 ID**）；``renumber_keeps_ids`` 验证**移动/重编号 ID 不变**；
    ``append_marker`` 只改目标行。
  - 旧编号迁移：``plan_legacy_migration`` 给出**可确认建议**与**歧义列表**（同号跨文档不自动写入）；
    ``apply_migration`` 只应用选中的可确认项，异常不留残标记；明确“未标记内容不自动计入分母”。
  - 评审映射：``map_review_locations`` 把可唯一定位的旧意见映射到条目；位置多匹配为歧义；
    **条目自身重复时仍映射但带 reason 标出待人工确认**；``backup_legacy_item_data`` 迁移前备份旧台账。
- 测试：新增 ``scripts/tests/test_traceable_items_v29.py``（23 例）——标记轮转/种类拒绝/缺字段拒绝/剥离与不进正文、
  重复与异项目拒绝、移动与重编号保留 ID、复制新 ID、仅改目标行、迁移建议/歧义/选中应用/失败不留痕、
  评审映射与歧义、迁移前备份。已注册。
- 本轮修正的真实缺陷：（1）``dup_keys`` 默认为空导致重复条目不被标出，
  已改为默认取 ``index.duplicates``；（2）``traceable_items`` 缺 ``Path`` 导入，已恢复。
- 回归：``v29-29b-1.xml``（71 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：29-C～29-H；2.2 的编辑器/章节 UI 动作入口仍需接到界面（服务已备）。


### 2026-10-01：V2.9 29-C 显式关系与人工关联（连续执行）

- 完成 3.1～3.4（V2.9 13/39）。
- 新增 ``doc_tool/application/content/relations.py``：
  - ``relations.yml`` schema 1：``relationId`` / ``type``（satisfies|verifies|depends_on）/ ``from``/``to`` 端点（projectId+itemId）/ ``note``；
    端点身份与条目身份一致（别名不参与）。
  - 校验：重复边（同类型同端点）、**自环**、**悬空端点**（需传入已知条目）、**环路**（``depends_on`` 上 DFS，visited 防止无限循环）；
    新增同边幂等（返回原有边）；删除返回是否生效。
  - 安全迁移：``migrate_legacy_graph`` **只接受人工确认的关系对**，缺少确认时明确声明“不自动推断关系”。
  - ``relation_sources`` 供 UI 定位两端。**只读项目禁止写入**（``PermissionError``）。
  - 损坏文件与不支持版本一律拒绝而不静默丢弃；文件缺失视为空图。
- 测试：新增 ``scripts/tests/test_relations_v29.py``（17 例）——三种类型轮转、未知类型/损坏/不支持版本拒绝、自环拒绝、
  重复边去重与幂等、悬空与环路检出（含无环链路）、只读禁写、迁移需确认、多对多跨角色、删除与定位、别名不影响身份。已注册。
- 回归：``v29-29c-1.xml``（72 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：29-D～29-H；关系编辑的 GUI 双端选择面板待接入（服务与定位接口已备）；
  关系文件入版本控制需在工作区层接入。


### 2026-10-01：V2.9 29-D 矩阵与可解释覆盖率（连续执行）

- 完成 4.1、4.2、4.4、4.5（V2.9 17/39）；4.3（矩阵 UI、未关联/孤立/悬空列表与后台分页）仍待做。
- 新增 ``doc_tool/application/content/trace_matrix.py``：**新增显式图计算**，不改写旧
  ``TraceabilityService``（保留为只读兼容）；新路径**不用相同编号推断关系**。
  - 分母：仅**已声明为 requirement 的稳定条目**；未标记内容不计入（有专项测试）。
  - 覆盖：``satisfies``（设计）、``verifies``（直接 + 经设计传递的**间接**）；**方向按端点种类判定**。
  - **N/A**：无需求条目时母为 0，覆盖率返回 None（不报 0%）；有专项测试防“假 100%”。
  - 已关联/待复核来自评审生命周期；孤立条目与悬空关系单列。
  - ``export_report``：markdown / csv / json 同源且输出确定（重复导出逐字节相同）。
- 4.4 实现 CLI ``trace``：``--project`` 或 ``--workspace`` 二选一，``--format markdown|json|csv``，
  ``--fail-on-uncovered`` 在存在未覆盖需求时退出 1；参数/执行失败退出 2；stdout 保持单一文档。
  工作区模式复用 ``load_workspace`` 与各成员的 ``relations.yml``。
- 测试：新增 ``scripts/tests/test_trace_matrix_v29.py``（12 例）——全链路直接/间接、无需求 N/A、
  重复边不重复计数、孤立与悬空、待复核不算通过、未标记不计分母、**防假 100%**、导出一致与确定性。已注册。
- 本轮修正的真实缺陷：``verifies`` 分支条件写错（``target in verifies_direct or target in designs``），
  导致直接覆盖永远为 0；已改为**按端点种类**判定方向。
- 回归：``v29-29d-1.xml``（73 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；CLI smoke：
  markdown/csv 退出 0、缺参数退出 2。
- 遗留：4.3（矩阵 UI 与后台分页）；29-E～29-H。


### 2026-10-01：V2.9 29-E 变更影响与复核（连续执行）

- 完成 5.1～5.5（V2.9 22/39）。
- 新增 ``doc_tool/application/content/impact.py``：
  - **语义 hash**：`item_semantic_hash` 只看正文 + 标题语义（剔除前导编号）+ 相关资源，
    **不含位置/编号/行号**；行尾空白不影响；``spec_factor_hash`` 单列模板/规则/术语变化。
    ``diff_snapshots`` 返回变更原因（新增/正文/标题/资源/删除）与规范级变化。
    **仅移动/重编号不触发影响**（有专项测试）。
  - **影响传播**：``compute_impact`` 沿关系反向计算直接/传递影响，每条带**路径与依据**；
    删除与悬空端点同样列入；**visited + 路径重复检测截断环路**；不修改任何下游正文。
  - **复核记录**：``ReviewRecordStore`` 保存 ``relationId`` 两端**当前 hash**；``stale_relations`` 在任一端
    hash 变化或端点消失时置为待复核（**并落盘**）；重复确认覆盖旧记录。
- 5.4 CLI ``impact``：``--project`` / ``--workspace`` 二选一，``--item projectId/itemId``（可重复）或
  ``--baseline`` 快照自动比对（**无可用基线时不推断**），``--format markdown|json``，
  ``--fail-on-pending`` 存在待复核时退出 1；参数/执行失败退出 2。已实测：显式 item 输出含 changed、
  json 提供同源数据、缺参数退出 2。
- 测试：新增 ``scripts/tests/test_impact_v29.py``（19 例）——位置/编号不触发、正文/资源触发、
  规范单列、新增/删除、直接与传递路径、悬空与环路终止、复核确认与失效、
  重复确认覆盖、损坏存储读空、**影响计算不修改存储**。已注册。
- 本轮修正的真实缺陷：（1）删除分支用字符串全等判定，遇到编码差异不生效，已改为关键字判定；
  （2）``stale_relations`` 修改状态后**未落盘**，下次读取仍显示通过，已修正并回归；
  （3）``traceable_items`` 补 ``ItemKey`` 别名供共享。
- 回归：``v29-29e-1.xml``（74 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：29-F（完整集合发布事务）、29-G（基线查询/比较/恢复）、29-H（收尾）；
  5.3 的评审面板/概览 UI 接入待做。


### 2026-10-01：V2.9 29-F 完整集合发布事务（连续执行）

- 完成 6.1～6.5（V2.9 27/39）。
- 新增 ``doc_tool/application/collection.py``：
  - **6.1 基线清单**：``collection.yml`` schema 1 + **逐文件 SHA-256**，收集覆盖清单/正文/
    图片/表格/规范/规则/关系/评审/报告/正式产物十类，跳过版本控制、临时与集合仓库自身；
    ``verify_manifest`` 报缺失/不一致与多余文件；**旧格式（无 files）记为 legacy-partial**。
  - **6.2 租约与锁顺序**：``acquire_lease``/``release_lease`` 在**服务层**拒绝并发写入（非 UI 禁用），
    带持有者、pid 与 TTL（过期可接管）；``project_lock_order`` 按 projectId 排序避免交叉死锁。
  - **6.3/6.4 部分成果与登记**：成员失败/缺资源时仍产出**可用部分 + 缺失清单**（``complete=false``）；
    ``strict=True``（显式选择）另行要求成员齐全；``register_manifest`` 重复版本**另存唯一快照**
    并提示新版本号；**登记失败不删除已有成果**；``release_lease`` 仅本进程（``force`` 可强制）。
- 测试：新增 ``scripts/tests/test_collection_v29.py``（16 例）——十类分类与逐文件 hash、跳过 VCS/仓库、
  部分集合可读与缺失清单、严格策略、**登记失败保留成果**、重复版本另存快照、legacy-partial、
  校验不一致与多余、租约拒绝并发、过期可接管、异进程不可释放、取消释放、锁顺序确定。已注册。
- 本轮修正的真实缺陷：（1）``Lease.expired`` 对 ``ttl=0`` 不生效（永不过期），已改为
  ``ttl<=0`` 即过期；（2）``_read_lease`` 把合法的 ``ttlSeconds: 0`` 当作空值回退默认 900，
  已改为仅在缺键时取默认。
- 回归：``v29-29f-1.xml``（75 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：作业级“以一致快照跑成员构建”仍需在工作区层接入管线；29-G（基线查询/比较/恢复）、29-H（收尾）。


### 2026-10-01：V2.9 29-G 基线查询、比较与恢复（连续执行）

- 完成 7.1～7.5（V2.9 32/39）。
- 新增 ``doc_tool/application/collection_ops.py``：
  - **7.1 查询**：``list_baselines`` / ``describe_baseline``（含分类计数、可打开产物、现场校验问题）；
    ``open_artifact`` 仅对**已登记且存在**的产物返回路径（越界返回 None）；旧记录标 ``legacy-partial``。
  - **7.2 比较与导出**：``compare_baselines`` 按正文/资源/规范与规则/关系/产物五组给出新增/移除/变化；
    ``export_package`` 打 ZIP 并写入基线清单；**越界/缺失/hash 不一致一律跳过并列清单**，无可用内容时不产生空包。
  - **7.3/7.4 安全恢复**：``recover_baseline`` 恢复到**新目录**；只写入 hash 匹配的**可信项**；
    目标冲突**默认换名**；legacy-partial/缺项/损坏只跳过该项、其余继续；写入 ``identity-map.json``
    供关系/评审重定向（itemId 保留）；**全程不写基线目录之外**，原副本与历史只读。
- 测试：新增 ``scripts/tests/test_collection_ops_v29.py``（14 例）——列表/详情/产物打开与越界拒绝、legacy-partial、
  五组比较与无差异、导出含清单、跳过变化与缺失、无可用内容返回 None、完整恢复、
  冲突换名、部分恢复、legacy 只说明、**恢复不越界**。已注册。
- 回归：``v29-29g-1.xml``（76 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）。
- 遗留：29-H（8.1～8.6 收尾：注册与全量回归、性能夹具、真实 Word 全流程、
  冻结/安装回归、发布说明与 2.9.0 版本源、归档）。


### 2026-10-01：V2.9 29-H 收尾与版本统一（连续执行）

- 完成 8.1、8.2、8.5、8.6（V2.9 **36/39**）；8.3（真实 Word 全流程）与 8.4（冻结/安装回归）
  因需实机人工条件，**保留待验收、未勾选**；4.3（矩阵 UI）仍待做。
- 8.5 版本源统一为 **2.9.0**（``doc_tool/domain/version.py``），schema 保持 **2**（v1 仍可读可写）；
  新增 ``docs/release/v29-acceptance.md``（A29-1～A29-6 状态、实际命令、**明确保留的限制**、与前版兼容性）。
- 8.2 新增 ``tools/gen_v29_performance.py``（**真实构建，无 mock**）：3 文档 / 300 章节 / 1000 条目 / 900 条关系；
  实测矩阵 **0.0139s**、影响 **0.0001s**、条目索引 0.0013s，总计 0.0252s，均远低于 5s 阈值 ——
  **未发现性能阻断**，无需修复。证据：``docs/release/evidence/v29-performance.json``。
- 8.1/8.6：V2.9 新增六个套件（workspace / traceable_items / relations / trace_matrix / impact / collection /
  collection_ops）全部注册到 ``scripts/tests/run_tests.py`` 并跑全量（``v29-29h-1.xml``：76 套件，
  仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；``openspec validate --strict`` 通过。
- **未归档**：因 8.3/8.4 尚未完成，按流程**不同步主规范、不归档**。
- 三个 change 的实现工作已到可自主完成的尾部：剩余项均为**待验收环境/人工**或 GUI 接入。
  下一步转入全面代码审查与最终验证（逐文件审查台账）。


### 2026-10-01：三个 change 实现完成后的全面代码审查与最终验证

- **逐文件审查台账**：``docs/release/v27-v29-code-review.md``（V2.7～V2.9 新增/修改文件逐个结论、
  **32 项已修复缺陷**清单、未修复的如实保留项、GUI/CLI 与策略一致性、旧项目兼容性）。
- 最终回归：``docs/release/evidence/v29-final-1.xml``（76 套件，**仅 1 失败**：
  ``test_gui_services.py`` 的 Mermaid ``classDiagram`` Chromium ConnectionClosedError —— **环境限制，非本轮回归**。
- 三个 change 的 ``openspec validate --strict`` 均通过。
- 版本源：**2.9.0**（schema 2，v1 仍可读可写）。
- **未归档**：因 V2.7 8.3/8.6、V2.8 9.3/9.4、V2.9 8.3/8.4 等待验收项存在，
  按流程**不同步主规范、不归档**，change 与未完成项一并保留。


### 2026-10-01：V2.8 5.1 从规范包起步建项（服务层）（连续执行）

- 完成 5.1 的**服务层**（V2.8 35/44）；首页入口与 5.5 菜单/命令面板仍待接入（属 GUI）。
- 新增 ``doc_tool/application/project_from_pack.py``：``create_project_from_pack`` 一步完成
  包校验 → 版本固定到 ``standards/<id>/<version>/`` → 生成**清单/章节骨架/共享配置**；
  骨架按名称排序写入 ``content/`` 并作为**显式 chapters**；变量进清单 ``variables``，
  变量/术语/规则写入项目 ``quality/``（供团队共享）；项目内**无绝对路径**。
- 容错：底模缺失、可选声明文件损坏只警告并继续；包不合法或目标已存在项目时**拒绝且无副作用**（有断言）。
- 测试：新增 ``scripts/tests/test_project_from_pack_v28.py``（8 例）——清单/章节/配置生成、
  变量进清单、重新加载与包可解析、无绝对路径、不覆盖已有项目、非法包无副作用、
  **三个公开包均可建出可用项目**、整体复制后仍可解析。已注册。
- 回归：``v28-5.1-1.xml``（77 套件，仅既有 Mermaid classDiagram Chromium ConnectionClosedError）；
  三个 change 的 ``openspec validate --strict`` 仍通过。


### 2026-10-01：V2.9 2.2 条目动作（服务层）与 8.3 环境复现（连续执行）

- 新增 ``doc_tool/application/content/item_actions.py``：``insert_item``（新条目，可同时写入正文）、
  ``duplicate_item``（**新 ID**，标记只出现在新行，避免两行共用同一 ID）、
  ``renumber_item``（**ID 不变**）、``item_line_numbers``（面板定位）；写入统一经 ``ContentWriter``。
- 测试：新增 ``scripts/tests/test_item_actions_v29.py``（11 例）——新增带正文、指定行插入、
  未知种类拒绝、经 writer 写入、复制新 ID 且不产生重复、源行无标记拒绝、
  重编号保留 ID、空编号拒绝、跨项目标记过滤。已注册。
- **2.2 仍不勾选**：编辑器/章节面板的菜单动作与拖拽事务属 GUI，服务已备但界面未接。
- 8.3 环境复现：本轮再次尝试真实 Word 刷新，预检即返回 **E3001（Word 不可 dispatch）**；
  与上一轮记录一致（连续 COM dispatch 后本机 Word 短时不可用，静置后恢复），**未取得刷新后校验报告**。
  此项仍为最高优先待办，依赖 Word 可用窗口。
- 回归：``v29-final-1.xml``（76 套件）与 ``v28-5.1-1.xml``（77 套件）均仅既有 Mermaid 环境失败。


### 2026-10-01：测试运行器损坏的发现与修复（最终验证期间）

- 最终验证时全量回归**无法运行**：``scripts/tests/run_tests.py`` 当前工作副本被写入了非本文件内容
  （全局总计计划/台账文本混入），Python 报 ``SyntaxError: invalid character '：' (U+FF1A)``。
- 处理：从 ``git cat-file -p HEAD:scripts/tests/run_tests.py`` 恢复干净基线（5929 字节 / 131 行），
  并把本轮 **23 个新增套件名重新录入**清单；现为 139 行 / **68 个套件**，无缺文件、无替换字符。
- 复核：``python tmp\scan_syntax.py`` 扫描全仓 ``*.py`` 的 BOM 与 ``SyntaxError``；
  ``python scripts/tests/run_tests.py --junit docs/release/evidence/v29-final-2.xml``
  → **68 套件 / 1 失败**（仅既有 Mermaid classDiagram Chromium 环境失败）。
- 一并记录：``tools/patch_v27_build.py`` 残留未解码 ``\uXXXX`` 转义（造物过程工具，不在测试清单）；
  ``run_tests.py`` 第 2 行 docstring 含替换字符**在 HEAD 即存在**，非本轮引入，保留现状并如实记录。
- 教训：本会话早期「用脚本改写含中文的 .py」曾把内容写错文件/编码，已在本台账与审查台账双处留痕，
  不隐藏。


### 2026-10-01：测试覆盖补齐与两个真实缺陷修复（最终验证续）

- **发现**：仓库内 19 个已存在的测试套件从未登记到 ``run_tests.py``（V2.6 时代遗留），
  既往全量证据（含 HEAD 的 45 套件基线）**并未覆盖它们**。已全部纳入，纳入前逐个跑过。
- **修复 1（真实代码缺陷）**：``test_heading_style_collision.py`` 失败根因在
  ``doc_tool/domain/ooxml.py::heading_style_candidates``——自定义派生样式（``customStyle=1`` 且有 ``basedOn``）
  沿用内置名称（如“标题1”）时被当成内置样式，使“优先内置名称”的决策失效。
  已修正为派生样式不计入内置，21 例全部通过。
- **修复 2（陈旧断言 + 强度提升）**：``test_step_list.py`` 断言步骤数为 5，而 V2.7 起新增 ``prepare``/``lint``
  阶段后应为 7。已改为 7，并**新增“步骤顺序必须等于 ``PIPELINE_STAGE_ORDER``（去掉 revision）”的同源断言**，
  防止两处各写一份清单漂移——断言强度提高而非降低。
- **最终回归**：``docs/release/evidence/v29-final-4.xml`` = **87 套件（= 磁盘全部测试文件）/ 1 失败**，
  唯一失败仍为既有 Mermaid ``classDiagram`` Chromium 环境问题。
- 其余 17 个套件纳入前即通过。


### 2026-10-01：V2.8 5.2 接管 Word（服务层）与最终回归

- 新增 ``doc_tool/application/intake_word.py``：
  - ``preview_intake``：**只读预览**——复用现有 ``preflight`` 得到标题样式映射与导入保真结论，
    并给出与**选定规范包**的差异说明（来源类别、未识别样式、降级/阻断特性）；预检失败只记一条差异，不整体报错。
  - ``intake_word_project``：把预览结果转为 ``ImportRequest`` 的 ``heading_style_map`` 后调用**现有**
    ``import_first_time``（不重建导入引擎）；成功后把规范包引用/文档类别/章节骨架**回填到清单**，不动导入得到的正文；
    包不合法时**直接中止且不创建项目**。
  - ``preview_intake`` 的本轮修正：未传规范包时「无包」是合法状态，不应判为不可接管（新增 ``pack_requested``）。
- 测试：新增 ``scripts/tests/test_intake_word_v28.py``（7 例，1 例因本机 Word COM 前置条件跳过）——
  预览含包信息与样式映射、缺源文档记为差异、非法包报错、**预览只读**（SHA-256 断言）、
  无包仍可用、非法包中止不建项目、成功时回填包引用与 ``qualitySource=pack``。已注册。
- 最终回归：``docs/release/evidence/v29-final-5.xml`` = **88 套件（= 磁盘全部测试文件）/ 1 失败 / 1 跳过**；
  唯一失败仍为既有 Mermaid ``classDiagram`` Chromium 环境问题。
- V2.8 进度 **36/44**；剩余 8 项：2.2 与 4.3/4.4 GUI、5.3/5.5 入口、8.2 预览对话框、9.3 团队试点、9.4 实机验收。


### 2026-10-01：V2.8 5.3 以 Markdown 建项（服务层）（连续执行）

- 新增 ``doc_tool/application/project_from_markdown.py``：``create_project_from_markdown``
  —— **文件顺序即章节顺序**（可被显式 ``chapter_order`` 覆盖并追加未列入项）；
  资源按名字去重复制到 ``assets/``；**底模与规范包都是可选**（缺失只警告、不阻断，默认兜底）；
  选中规范包时固定版本、记录 ``documentKind`` 与 ``qualitySource=pack``；清单内**无绝对路径**。
- ``describe_entry_point`` 明确三条建项路径的分工，并**显式区分即时模板填充**：
  后者只从一份文档直接生成 docx、**不建项目**，不可持续维护——避免两条产品线互相混淆。
- 测试：新增 ``scripts/tests/test_project_from_markdown_v28.py``（11 例）——文件顺序成章节顺序、
  显式顺序覆盖并追加、资源复制与同名去重、底模可选告警/提供时复制、包固定版本与可解析、
  非法包只警告继续、缺源文件跳过其余继续、不覆盖既有项目、清单无绝对路径、入口说明区分即时填充。已注册。
- 三个建项入口服务层至此齐备：``project_from_pack``（5.1）、``intake_word``（5.2）、
  ``project_from_markdown``（5.3）；仅剩界面入口（5.5）与预览/设置 GUI。
- 最终回归：``docs/release/evidence/v29-final-6.xml`` = **89 套件（= 磁盘全部测试文件）/ 1 失败**；
  唯一失败仍为既有 Mermaid classDiagram Chromium 环境问题。
- V2.8 进度 **37/44**；剩余 7 项：2.2 与 4.3/4.4 GUI、5.5 入口、8.2 预览对话框、9.3 团队试点、9.4 实机验收。


### 2026-10-01：V2.8 8.2 重导入预览会话（服务层）（连续执行）

- 新增 ``doc_tool/application/content/reimport_preview.py``：
  - ``open_preview``：**只读**打开会话，拿到只读计划 + **逐项 unified diff**（无内容时只标无 diff，不阻断）；
  - **脏内容项默认不参与应用**（未保存编辑不被覆盖），窗口分隔符路径也正确识别；
  - ``toggle_selection``：冲突项与脏内容项**拒绝选中**，可反复勾选/取消；
  - ``cancel_session``：取消只丢弃会话，**不写入任何内容**（有 ``reimport`` 未被调用的断言）；
  - ``apply_session``：把选中且未被阻的项交给**现有** ``apply_plan``（复用事务与回滚），
    并如实回报 ``applied / skipped / rolledBack / blocked``。
- 测试：新增 ``scripts/tests/test_reimport_preview_v28.py``（10 例）——会话计数与摘要、脏内容排除、
  diff 生成与缺内容不崩、受阻项拒绝选中、取消不写、应用只传可应用项、失败回滚、
  无选中为 no-op、Windows 分隔符归一。已注册。
- 最终回归：``docs/release/evidence/v29-final-7.xml`` = **90 套件（= 磁盘全部测试文件）/ 1 失败**；
  唯一失败仍为既有 Mermaid classDiagram Chromium 环境问题。
- V2.8 进度 **38/44**；剩余 6 项：2.2 与 4.3/4.4 GUI、5.5 入口、9.3 团队试点、9.4 实机验收。


### 2026-10-01：V2.9 4.3 矩阵分页与来源定位（服务层）（连续执行）

- 新增（``doc_tool/application/content/trace_matrix.py``）：
  - ``build_matrix_page``：把覆盖率报告分页成 UI 可直接渲染的一页，**顺序由报告自身确定**（保证 GUI 与 CLI 一致）；
    越界页返回空页而非报错；支持 ``only_uncovered`` 过滤；同时给出未关联/孤立/悬空清单。
  - ``locate_item``：按 ``itemId`` 返回**全部来源位置**（relPath / 行号 / 所属章节号），支持 projectId 过滤；
    查不到就返回空列表——**界面不得自行猜测位置**。
- 测试：新增 ``scripts/tests/test_matrix_page_v29.py``（8 例）——分页稳定且不重复不遗漏（120 条跨 3 页）、
  越界页为空、仅未覆盖过滤、未关联与孤立暴露、零需求空页有效、定位返回全部位置、
  未知条目返回空、项目过滤生效。已注册。
- 本轮测试侧修正：用例中 ``headingNo`` 期望值原为 ``2.2``，但 ``2.2 二。`` 会被解析为**有序列表项**而非标题，
  该项所属章节实为 ``1``；已按真实语义改正（不是放宽断言）。
- 最终回归：``docs/release/evidence/v29-final-8.xml`` = **91 套件（= 磁盘全部测试文件）/ 1 失败**；
  唯一失败仍为既有 Mermaid classDiagram Chromium 环境问题。
- V2.9 进度 **37/39**，仅剩 8.3（真实 Word 全流程）与 8.4（冻结/安装/升级回归），二者均需实机人工条件。


### 2026-10-01：8.3 Word 可用性疑难定位（连续执行，未取得刷新后报告）

- 本轮为定位 E3001 做了对照实验：
  1. 单独调用 ``check_word_available(dispatch_check=True)`` → **available=True / dispatchable=True**；
  2. 紧接着调用 ``run_pipeline(skip_word_refresh=False)`` → 在 ``STAGE_BUILD`` 的
     **正式模式 Word 预检**处失败，错误明细 ``dispatchable=false``（pywin32 与交互会话均为 true）。
- 结论：**不是探针语义错误，也不是代码分支写错**（同一探针单独可用、管线内不可用），
  而是本机 Word COM 在**连续 DispatchEx 后进入短时不可派发状态**，恢复窗口不确定；
  因此仍**未取得刷新后校验报告**，8.3 保持待办。
- 已经尝试并保留的调试方法学：不要在同一进程里先跑探针再跑管线（探针会先占用一个 Word 实例）；
  正确做法是直接跑管线，让管线自己做唯一一次预检。
- 该环境限制已连续三轮复现，写入审查台账「环境限制」一栏，不虚报通过。


### 2026-10-01：V2.8 4.4 检查报告过期判定与只读边界（服务层）（连续执行）

- 新增 ``doc_tool/application/overview.py::check_report_is_stale``：**可被 GUI 直接复用**的过期判定
  —— 过期为「内容、配置或底模在报告之后又被修改」，**无报告也算过期**（不能把“尚未检查”当有效结论）；
  支持显式传入报告路径。
- 过期输入扩围：除内容与底模外，还覆盖 ``quality/``（规则/术语/变量）、旧位置 ``.state/terms.json``
  与 ``relations.yml`` —— **配置或关系变更后旧报告必须过期**。
- 与概览一致：``build_overview`` 的 check 板块与 ``check_report_is_stale`` 在同一场景下结论一致（有断言）。
- 只读边界（服务层，不依赖界面禁用）：规则配置 ``writable=False`` 禁写、更高 schema 清单禁写、
  关系图 ``writable=False`` 禁写。
- 测试：新增 ``scripts/tests/test_stale_report_v28.py``（12 例）——无报告即过期、报告较新为有效、
  内容/quality 配置/旧术语/关系变更各自触发过期、显式路径生效、概览与判定一致、
  以及三处只读禁写。已注册。
- 最终回归：``docs/release/evidence/v29-final-9.xml`` = **92 套件（= 磁盘全部测试文件）/ 1 失败**；
  唯一失败仍为既有 Mermaid classDiagram Chromium 环境问题。
- V2.8 进度 **39/44**；剩余 5 项：2.2 与 4.3 GUI、5.5 入口、9.3 团队试点、9.4 实机验收。


### 2026-10-01：V2.8 5.5 菜单与命令面板入口（连续执行）

- 在 ``doc_tool/ui/main_window.py`` 的命令面板新增**三条建项路径**入口（类别「新建」）：
  「从规范包起步建项」「接管现有 Word 建项」「以 Markdown 起步建项」，并各自带一句**用途说明**，
  与「即时模板填充」在文案上明确区分（后者不建项目）。
- 处理器 ``_on_create_from_pack`` / ``_on_intake_word`` / ``_on_create_from_markdown``
  **只做入口引导**：复用既有「新建项目」向导与导入向导，不重复实现包解析、预检或写清单；
  状态栏反馈走新增 ``_show_status_message``（无状态栏时退化为日志，不影响主流程）。
- 测试：既有 ``scripts/tests/test_command_palette.py``（4 例）通过；面板与处理器语法校验通过，
  ``main_window`` 可被导入（无循环导入）。
- V2.8 进度 **40/44**；剩余 4 项：2.2 与 4.3 GUI、9.3 团队试点、9.4 实机验收。


### 2026-10-01：V2.8 2.2 章节排序事务与界面顺序（服务层）（连续执行）

- 新增 ``doc_tool/application/content/chapter_reorder.py``：
  - ``display_order``：树 / 快速打开 / 预览统一使用的**唯一顺序**（直接委派 ``resolve_chapter_order``），
    避免界面与构建各算一套顺序。
  - ``plan_reorder``：按拖拽后的目标顺序算出**重编号计划**（保留目录、无编号文件补号），
    并**复用** ``RefactorService.compute_batch_rename_plan`` 得到**引用修正数量与冲突**；纯只读。
  - ``apply_reorder``：应用时**复用** ``RefactorService.apply_rename_plan``（含冲突校验、备份与回滚），
    有冲突则**不触碰服务**直接拒绝。
- 测试：新增 ``scripts/tests/test_chapter_reorder_v28.py``（15 例）——界面顺序与构建契约一致、无声明保持扫描序、
  按目标顺序重编号、无编号补号、关闭重编号只校验、顺序已正确报未变、子目录保留、
  引用修正计数、服务冲突阻止、计划为空阻止、计划文本、冲突不触服务、无重命名 no-op、
  应用走 refactor 事务、服务侧冲突阻止应用。已注册。
- 最终回归：``docs/release/evidence/v29-final-11.xml`` = **93 套件（= 磁盘全部测试文件）/ 1 失败**；
  唯一失败仍为既有 Mermaid classDiagram Chromium 环境问题。
- V2.8 进度 **41/44**；剩余 3 项：4.3 设置页编辑 GUI、9.3 团队试点、9.4 实机验收。


### 2026-10-01：V2.8 4.3 项目设置模型与校验保存（服务层）（连续执行）

- 新增 ``doc_tool/application/settings.py``：
  - ``load_settings``：返回**表单模型**（基本信息 / 样式 / 变量 / 术语 / 规则 / 门禁六区），
    样式枚举复用清单既有映射；``schemaVersion`` 等只读字段显式标 ``editable=False``；
    只读项目给出明确警告。
  - ``save_settings``：**先校验后写入**——版本号非空、门禁来源枚举、术语必须为字符串列表、
    规则必须为列表、变量必须为映射；**任一校验失败不写任何文件**（有断言）；
    通过后写清单与项目 ``quality/``（术语/规则）；只读项目拒绝保存。
- 测试：新增 ``scripts/tests/test_settings_v28.py``（14 例）——六区齐备、样式与变量暴露、
  只读字段、只读项目警告、版本变更保存、空版本拒绝且不写、非法门禁来源拒绝、
  非法术语类型拒绝、术语/规则写入 quality、变量往返、只读拒绝保存、**校验失败无部分写入**。已注册。
- 最终回归：``docs/release/evidence/v29-final-12.xml`` = **94 套件（= 磁盘全部测试文件）/ 1 失败**；
  唯一失败仍为既有 Mermaid classDiagram Chromium 环境问题。
- V2.8 进度 **42/44**；剩余 2 项：9.3 团队试点、9.4 实机验收（均需人工/实机条件）。


### 2026-10-01：E3001 根因定位完成（僵尸 Word 进程占用 COM）

- 本轮做了决定性实验：连续 6 次直接调用 ``check_word_dispatchable``（每次超时 25s）
  —— **6/6 全部失败**，耗时稳定在 ~25.3s（说明是"启动后挂住被强杀"，不是快速报错）。
- 随后枚举系统进程发现**8 个 GUI Word 实例**同时驻留，其中 **4 个启动时间早于本次会话**
  （12:12:48 等，当前时间约 16:4x），即**用户先前打开的 Word 文档**。
- 结论：本机 ``DispatchEx`` 失败的直接原因是**已有 GUI Word 实例占用**——Word 是单实例服务器，
  在已有交互式实例时新建自动化实例会挂住，本工具的超时保护随后强杀并如实返回不可用。
- 这**不是本项目的代码缺陷**：正式合并按 spec **必须**在可用 Word 上执行，此时本就应阻断并建议
  「诊断构建」；``check_word_ready``/`check_word_available` 的探测与阻断行为均正确。
- **未做**：没有结束任何 ``WINWORD.EXE`` 进程——那属于用户材料/用户会话，未经授权不得终止
  （与"不删除用户材料、不做未经授权破坏性操作"的约束一致）。因此 8.3/9.4/8.4 的实机验收
  继续保持待验收状态。
- 后续人工验收前置条件：**先关闭所有已打开的 Word 文档**（或换一台无 Word 实例的机器），
  再执行正式刷新与冻结/安装验收。


### 2026-10-01：工具脚本损坏的隔离与产品代码无损确认（最终验证续）

- 末次语法扫描发现 ``tools/patch_v27_build.py`` 的第 374 行**缺少 docstring 引号**：
  ``_reference_text`` 的文档字符串被当成代码，导致 `SyntaxError: invalid character '；'`。
- 根因：该文件是**本会话早期「用脚本改写 .py」时的产物**，其第 208 行起的补丁串未被正确闭合，
  把后续内容整体吞进字符串，最终形成跨 166 行的未终止字符串。
- 处置：把它移出可执行区（``tools/patch_v27_build.py.broken``）以保留可追溯证据，
  并逐个复核其余同类工具脚本（语法有效者保留，损坏者一并隔离）。
- **产品与测试代码无损**：对 ``doc_tool/**`` 与 ``scripts/**`` 全量 `ast.parse` 扫描
  —— **0 个语法问题**；``scripts/tests/run_tests.py`` 此前已从 HEAD 基线恢复（94 套件）。
- 教训（与上一轮同一根因）：本次会话中「用 Python 脚本改写含中文的 .py」多次引入编码/引号损坏。
  已停止该做法；后续改动采用「先 `ast.parse` 校验、再落盘」的流程，并在本台账留痕。


### 2026-10-01：使用说明补齐 V2.7～V2.9（交付物一致性收口）

- ``docs/使用说明.md`` 原只覆盖到 V2.6.x，缺 V2.7～V2.9 的能力与边界。本轮补齐一节
  「V2.7～V2.9 新增能力速查与已知边界」，含：
  - 出稿可靠性与表达契约（代码容器、题注/交叉引用静态缓存值、Mermaid 预处理与缓存、横向节与分页）；
  - **统一检查入口** ``check`` 的退出码 0/1/2 与“单一文档输出、日志走 stderr”约定；
  - 规范包与项目模式 v2、三条建项路径（并明确与“即时模板填充”的区别）、``quality/`` 共享配置与报告过期；
  - 变更可追溯（工作区、稳定条目 ID、显式关系、覆盖率 N/A、影响与复核、集合基线与安全恢复）；
  - ``trace`` / ``impact`` 命令用法；
  - **已知边界**：正式刷新需可用 Word（已有 GUI 实例驻留会返回 E3001，验收前请关闭全部 Word 文档或换机）、
    生成图位于临时目录但产物已内嵌、部分 GUI 入口以服务层与 CLI 为准。
- 交付物一致性：``tools/check_integrity.py`` 四项自检通过（exit 0）；审阅清单更新为 22 个条目，
  与最终代码/文档逐一对应。


### 2026-10-01：V2.7 验收记录补建（A27-1～A27-6）

- 此前 V2.7 只有支持矩阵与证据 JSON，**缺独立验收记录**（V2.8/V2.9 各有）。
  本轮补建 ``docs/release/v27-acceptance.md``：逐条登记 A27-1～A27-6 的状态、
  实际执行命令与**明确保留的限制**。
- 结论（如实）：
  - **A27-1 / A27-2 / A27-4 / A27-5 通过**（各有对应回归证据）；
  - **A27-3 部分待验收**：编号与引用本身有回归，但「Word 刷新后仍正确」因本机 Word 不可派发未取得报告；
  - **A27-6 待验收**：三类样本的「导入→修改→检查→诊断出稿」已跑完，
    但**真实 Word 样式人工视觉核对未完成**。
- 限制与前置条件同 V2.8/V2.9：先关闭所有已打开的 Word 文档（或换机）后执行正式刷新与人工版式核对。
- 审阅清单已同步加入该文件（SHA-256）。
- 三个 change 的未完成项复核：**各 2 项，共 6 项，全部为实机/人工条件**，逐条原文已核对。


### 2026-10-01：交付链路端到端实跑（最终验证续）

- 新增 ``tools/gen_v29_e2e_chain.py``：用**真实服务与真实 CLI**（无 mock）跑通交付链路，证据 ``docs/release/evidence/v29-e2e-chain.json``。
- 实测结果：
  - 从规范包建项：**通过**（2 个章节骨架，无错误）；
  - ``check --output json``：退出码 **0**、stdout 为单一合法 JSON、``status=ok``；
  - ``trace --format json``：退出码 **0**、stdout 为 JSON、给出设计/测试覆盖率（无关联关系时为 0.0，非 N/A，因分子有需求条目）；
  - ``impact --item GX-E2E-REQ/req-e2e-0001 --format json``：退出码 **0**、stdout 为 JSON、``changed=1``。
- 意义：三个 CLI 入口与建项服务在**当前最终代码**上确为可用，且 stdout/stderr 契约（单一文档）经实测成立。


### 2026-10-01：冻结态规范包依赖缺口发现与修复（跨版本集成审查）

- **发现（真实跨版本集成问题）**：``packaging/doc_tool.spec`` 只随包 ``doc_tool/resources/``，
  而 V2.8 新增的 ``standards/``（三个通用规范包）**未被收进冻结产物**；
  而 ``resource_root()`` 在冻结态只会看 ``sys._MEIPASS/doc_tool/resources``。
  结果：冻结版下「从规范包起步」无包可选。
- **修复**：
  1. ``doc_tool/application/standard_pack.py`` 新增 ``bundled_standards_root()``（源码态优先仓库
     ``standards/``，冻结态用 ``doc_tool/resources/standards``，**两者都无时返回 None 而不静默失败**）
     与 ``list_bundled_packs()``；
  2. ``packaging/doc_tool.spec`` 把 ``standards/`` 收进 ``doc_tool/resources/standards``，使冻结态可用。
- 测试：新增 ``scripts/tests/test_bundled_standards_v28.py``（4 例）——源码态可解析、三个包均合法、
  **打包脚本确实随包 standards/**、两个候选都不存在时返回 None 不抛异常。已注册。
- 这是本轮审查重点中「源码态与冻结态的资源定位/依赖收集/打包安全」一项的实际成果。


### 2026-10-01：冻结态修复回归与交付物快照刷新（最终验证收口）

- 复核冻结态修复未破坏打包链路：``v29-packaging-2.xml`` = **5 套件 / 0 失败**
  （打包、品牌一致性、安装器、公共导出、冻结冒烟）。
- 全量回归：``v29-final-15.xml`` = **95 套件 / 1 失败**（既有 Mermaid classDiagram Chromium 环境问题）。
- 交付物快照刷新：审阅清单更新为 **28 个条目**，含新增的 ``packaging/doc_tool.spec``、
  ``standard_pack.py``、``v29-e2e-chain.json`` 与两份最新证据报告，全部对应审查后最终代码。
- 三个 change 的 ``openspec validate --strict`` 仍全部通过；``tools/check_integrity.py`` 退出码 0。
- 未完成项复核：V2.7 2 项、V2.8 2 项、V2.9 2 项，共 **6 项**，全部为实机/人工前置，状态未变。


### 2026-10-01：规范项到实现/测试的映射逐条核对（最终审查收口）

- 在审查台账追加第十三节：**逐规范文件**（V2.7 3 份 / V2.8 4 份 / V2.9 3 份，共 10 份、40 条 Requirement）
  列出实现与测试落点，供人工复核「实现与 specs 是否一致、是否遗漏功能入口」。
- 核对结果：**映射表中 0 个缺失项**——每份规范声明的能力都有对应实现文件与回归套件；
  未列入映射表的实现文件见审查台账第一至七节的逐文件结论。
- 该节同时给出「缺失项总数」字段，便于后续变更后快速发现回退。


### 2026-10-01：服务层完成度与未接入入口的严格对照

- 用「是否有非测试调用方」逐个核对本轮新增服务，在审查台账新增第十四节：
  列出 11 项「已实现但界面未接入」的服务（设置模型/保存、矩阵分页与定位、重导入预览会话、条目动作、拖拽排序、章节排序、Word 接管差异、Markdown 建项、过期判定、随包规范包）。
- 与 tasks.md 状态逐一核对：上述项对应的 2.2 / 4.3（V2.8）/ 4.3（V2.9）仍为**未勾选**，无伪称。
- V2.8 5.1/5.2/5.3/5.5/8.2 勾选的依据是服务层 + CLI/命令面板入口可用且有端到端证据（v29-e2e-chain.json），已在验收记录与使用说明中声明。


### 2026-10-01：发现页面顺序与构建顺序未同源（待改，未修复）

- **发现**：V2.8 新增的显式章节顺序 ``manifest.chapters`` 目前**只被概览消费**：
  - ``doc_tool/application/overview.py``：``resolve_chapter_order(relative, manifest.chapters)`` —— **有传入**；
  - ``doc_tool/application/pipeline.py``：``resolve_chapter_order(relative)`` —— **未传入**；
  - 内核顺序由 ``scripts/docx_common.py::scan_entries`` 决定：``entries.sort(key=lambda entry: entry.number)``，
    即**按文件名编号排序**，看不到 ``manifest.chapters``。
- **后果**：若作者在 v2 项目中声明了与编号不一致的顺序，**界面按声明、构建按编号**，
  即“界面与构建不同源”——这正是审查要求的「GUI/CLI 行为与状态是否一致」一项。
- **未修复原因**：正确修法需把显式顺序传入**内核** ``iter_chapter_entries``/``scan_entries``
  （涉及 ``scripts/`` 内核与证据比对语义），属跨模块改动，不在本轮剩余预算内完成并充分回归；
  为避免引入未验证改动，**如实记录为待改项**，未作修改。
- 影响范围：仅影响**显式声明且与编号不一致**的 v2 项目；v1 项目与“声明顺序= 编号顺序”的项目行为不变，
  现有回归与端到端证据不受影响。
- **已尝试修复并主动回退**（本轮）：曾在 ``scripts/docx_common.scan_entries`` 加入
``chapter_order`` 参数并在 ``config`` 中传入 ``chapterOrder``，试图让内核按声明顺序排序。
实测发现：内核 ``scan_entries`` 对**无编号文件直接报错**（``章节目录只能包含有编号的文件``），
因此“按声明顺序读取任意文件名”这条路径与内核不变量相冲；且该改动靠近验收期，
缺乏充分回归预算。为不给已验证的交付物引入风险，**已完整回退内核/适配器/管线改动**，
并以 ``v29-revert-check.xml``（6 套件 / 0 失败）验证回退干净。

正确修法（留待后续，属**产品行为决策**）：要么（1）在上层约束声明顺序必须与编号一致
（声明仅作校验），要么（2）在内核支持“无编号也可排序”的语义后再接入。两者均会改变现有约束，
属「无法推断的关键产品要求」，故**不擅自选择**，保留为待改项并已在审查台账记录。


### 2026-10-01：回退后交付物复验（可安全推进工作已尽）

- 内核回退**逐行核对为原样**：``scan_entries`` 签名、排序与错误分支与回退前一致，
  删除的辅助函数无残留引用，``pipeline``/``kernel`` 中显式顺序相关代码为 0 处。
- 复验证据：
  - ``tools/check_integrity.py`` —— 语法/编码、测试清单（95 = 95）、关键模块导入、版本源，**四项全通过**；
  - ``docs/release/evidence/v29-final-17.xml`` —— **95 套件 / 1 失败**，唯一失败仍为既有
    Mermaid ``classDiagram`` Chromium 环境问题（与回退前完全一致，无新增回归）；
  - 三个 change ``openspec validate --strict`` 全部通过。
- **可安全推进的工作已尽**。剩余项分类（均非本轮可自主完成）：
  1. **实机/人工前置 6 项**：真实 Word 刷新与人工版式核对（前置：关闭本机 8 个 GUI Word 实例或换机）、
     冻结/安装/升级/卸载人工执行、真实团队三人角色试点；
  2. **GUI 接入 3 项**（V2.8 2.2 / 4.3、V2.9 4.3）：服务层与回归完备，界面接入属独立界面工程；
  3. **待改项 1 项**：章节顺序与构建同源——已尝试并回退，两条候选修法均改变现有约束，
     属**无法推断的关键产品要求**，留待产品决策。
- 归档（V2.7 8.6 / V2.9 归档）按流程**继续不做**：全部验收未满足，保留 change 与未完成项。


### 2026-10-01：真实 Word 可用窗口内完成刷新环节实测（重大发现 + 修复）

**前提变化**：本轮 Word 短暂可派发（``DispatchEx`` 成功、返回 16.0），因此**首次真实跑通了刷新环节**。

**实测结果（如实）**：三类样本 ``word_refresh`` 均 **succeeded**
（TOC / NUMPAGES / 全部 story 域刷新完成），但 ``validate_post`` **均失败**	ext（E2002）。

**根因定位（关键发现）**：刷新后正文出现

- ``表 错误!未定义书签。``（题注处）
- ``参见 错误!未找到引用源。``（交叉引用处）

定位到 ``scripts/build_docx.py::_caption_paragraph`` 传入 ``bookmark_id=0``，
而 ``docx_blocks.make_caption_paragraph`` 的条件是 ``if bookmark_name and bookmark_id``
——**题注书签从未写入**，而 ``REF`` 域仍指向该书签名，
于是 Word 一刷新就把它换成错误文本。未刷新时之所以正常，是因为**静态缓存值**在撑着。

**已完成修复**（本轮）：

1. ``scripts/build_docx.py`` 新增 ``_next_bookmark_id()`` 并在图题/表题两处调用点分配**唯一书签 id**；
2. ``doc_tool/kernel_shared/docx_blocks.py::make_caption_paragraph`` 调整为
   **书签包住带内容的 SEQ 域 run**（零长度书签在 Word 中不可用）。
3. 验证：构建产物中 ``bookmarkStart`` 已出现 ``cap_tbl_case_018aa99c63``，与 ``REF`` 目标**完全匹配**。

**仍未解决（未隐瞒）**：刷新后校验仍报 3 项失败：

1. 题注/交叉引用仍报“错误!未定义书签”——书签已存在且名字匹配，**还需继续定位**
   （候选：书签位置/作用域、SEQ 与 REF 的互操作、Word 对 ``bookmarkEnd`` 的位置要求）；
2. ``Styles/Font/Theme 刷新后保持模板体系`` 失败：Word 刷新会重写主题字体/颜色定义与部分段落样式。
3. 因 ``validate_post`` 失败，三类样本均**未进入正式发布**，V2.7 8.3 仍**未完成**。

**工具改进**：``tools/gen_v27_word_evidence.py`` 新增 ``--keep``（保留临时目录排查）与
``--only``（单类型重跑），并记录 ``postRefreshFailures`` 明细，使失败**可定位、可复现**。


### 2026-10-01：书签缺失根因修复完成（实测验证）

- **根因**：``scripts/build_docx.py::_caption_paragraph`` 对题注传入 ``bookmark_id=0``，
  而 ``make_caption_paragraph`` 的写入条件是 ``if bookmark_name and bookmark_id``
  ——**题注书签从未进入产物**，但 ``REF`` 域仍指向该名字，Word 一刷新就换成
  “错误!未定义书签”；未刷时靠**静态缓存值**掩盖了这个缺陷。
- **修复（三处）**：
  1. 新增 ``_next_bookmark_id()`` 与 ``set_caption_bookmark_base()``：起点取**模板已有书签的最大 id**，避免撞号；
  2. ``_bookmark_id_for(name)``：**同名书签只写入首次出现**（Word 不允许重名），交叉引用仍能解析；
  3. ``make_caption_paragraph`` 改为**书签包住 SEQ 域 run**（零长度书签在 Word 中不可用）。
- **验证**：
  - ``docs/release/evidence/v29-bookmark-fix3.xml``：``test_expression_contract`` + ``test_project_build`` + ``test_contract_fidelity_v27``
    = **3 套件 / 0 失败**（修复前 ``test_expression_contract`` 因书签重名失败）；
  - 构建产物中 ``bookmarkStart`` 已出现 ``cap_tbl_case_018aa99c63``，与 ``REF`` 目标**完全匹配**；
  - ``docs/release/evidence/v29-final-18.xml``：全量 **95 套件 / 1 失败**（仅既有 Mermaid 环境项）——**无新增回归**。
- **仍未取得刷新后报告**：验证过程中 Word 可派发窗口再次关闭（``E3001``），
  因此“刷新后交叉引用正确”尚未实测确认；V2.7 8.3 保持**未完成**。
- 剩余风险（待下次 Word 窗口）：需重跑三类样本刷新，确认交叉引用不再报错；
  若仍报错，下一个候选原因是 ``Styles/Font/Theme 刷新后保持模板体系`` 校验（Word 会重写主题字体/颜色定义）。


### 2026-10-01：刷新后交叉引用仍报错——已排除两个假因，真因待续（如实）

**已排除的假因（均有实测）**：

1. “书签未写入”——已修复（``_next_bookmark_id`` / ``_bookmark_id_for``），
   产物中确实出现 ``cap_tbl_case_018aa99c63``，与 ``REF`` 目标同名；
2. “书签位置不对（插在 fldChar begin 与 run 之间）”——已改为
   **书签整体包住 SEQ 域**（start 在 begin 之前、end 在 end 之后），XML 已核对。

**实测结果（两次真实刷新）**：刷新仍报 ``表 错误!未定义书签。``——
**两个假因均不成立**，真因待继续定位。候选方向（未验证，不做结论）：

- Word 可能对 ``bookmarkStart`` 作为 ``w:p`` 直接子节点的位置有更严要求（需在某个 ``w:r`` 内）；
- ``SEQ`` 与 ``REF`` 的嵌套关系可能被 Word 重算时解析为无效；
- 模板自身的书签（``_Toc*``）与本工具书签命名空间的交互。

**当前状态**：交叉引用刷新后仍失效，V2.7 8.3（A27-3）**未完成**。
刷新前校验仍全部通过（静态缓存值起作用），因此**非正式发布路径不受影响**；
但“刷新后仍正确”这一条**如实不达标**。

**测试处置**：曾写一份专项书签回归套件，但其断言预设在**带题注的样本**上生效，
而当前模板样本无图/表题注且含自带 ``_Toc`` 书签，导致断言不成立；
**不愿以不成立的断言凑数**，已删除该套件。书签修复本身由
``test_expression_contract`` / ``test_project_build`` / ``test_contract_fidelity_v27``（``v29-bookmark-fix4.xml``，4 套件）与 XML 实测覆盖。

**最终回归**：``docs/release/evidence/v29-final-19.xml`` = **95 套件 / 1 失败**（仅既有 Mermaid 环境项），无新增回归。


### 2026-10-01：书签存活已证实，真因缩小到域代码（实测）

**关键实验（本轮）**：直接调 ``build_with_project`` 后 ``refresh_with_project``，
对**同一产物**在刷新前后各取一次 ``document.xml`` 快照（``refresh ok: True``）：

| 观测 | 刷新前 | 刷新后 |
|------|--------|--------|
| ``cap_tbl_case_018aa99c63`` 书签 | 存在 | **仍存在** |
| ``REF cap_tbl_case_018aa99c63 \\h`` 域 | 存在 | **仍存在** |
| 正文错误文本 | 无 | **有** |

**推论（已排除两类假因）**：书签未被 Word 删除、域也未被删除，
但 Word 仍将 ``REF`` 解析为“未定义书签”——**问题在域代码/书签绑定本身**，
不在“存在性”。剩余可疑点依然是 ``SEQ`` 与 ``REF`` 的嵌套关系。

**同时修正一个真实的 OOXML 结构缺陷**：``make_field`` 原先把 ``w:fldChar``/``w:instrText``
放进一个**包装的 ``w:r``**，形成 ``w:r`` 嵌套 ``w:r``（非法）。已改为返回**扁平 run 列表**，
``make_reference_runs`` 改用 ``extend`` 接收。

**验证**：

- ``docs/release/evidence/v29-flatruns-check.xml``：表达式契约 / 项目构建 / 保真 / 检查 CLI /
  管线门禁 / 预处理源 = **6 套件 / 0 失败**；
- ``docs/release/evidence/v29-final-20.xml``：全量 **95 套件 / 1 失败**（仅既有 Mermaid 环境项），**无新增回归**；
- ``tools/check_integrity.py`` exit 0。

**状态**：交叉引用刷新后仍报错，V2.7 8.3（A27-3）**保持未完成**。
但本轮把范围从“书签可能丢失”缩小到“域代码与书签绑定”，并修掉了一个真实的非法嵌套结构。


### 2026-10-01：交叉引用刷新后失效已修复（实测通过）——重大进展

**真因（终于定位）**：建造的域**缺少 ``w:fldChar w:fldCharType="separate"``**。
OOXML 域必须是 ``begin → instrText → separate → 结果 → end``；
缺少 ``separate`` 时，缓存值被当作**域代码的一部分**，Word 把
``SEQ 表 \\* ARABIC`` 后的 ``1`` 误认为书签名 → **“错误!未定义书签”**。
这一个结构缺陷同时导致了题注号与交叉引用两处报错。

**三处修复（均已用真实 Word 刷新验证）**：

1. ``make_field`` 返回**扁平 run 列表**，消除 ``w:r`` 嵌套 ``w:r`` 的非法结构；
2. 在 ``instrText`` 与结果之间补上 ``fldChar separate``（**关键修复**）；
3. ``make_caption_paragraph`` 让书签**包住整条题注文本**（前缀 + 编号域 + 标签），
   使 ``REF`` 取回完整题注（“表 1 用例表”）而非只有编号；
   同时**书签名去重**（同名只写首次），起点取模板已有书签最大 id。

**实测结果（``docs/release/evidence/v27-word-refresh.json``，三类样本真实刷新）**：

| 样本 | 刷新前校验 | 刷新后校验 |
|------|----------|----------|
| requirement / design / test | PASS | **17 PASS / 1 FAIL**（修复前为 15/3） |

- **题注与交叉引用两项失败已消失**：刷新后正文不再出现“错误!未定义书签”，
  ``REF`` 结果正确为“1”（编号），题注正文为“表 1 用例表”；
- 仅剩 **1 项**：``Styles/Font/Theme Word 刷新后保持模板体系``
  （Word 会重写主题字体/颜色定义与部分段落样式）。

**回归**：``docs/release/evidence/v29-fieldfix-check.xml``（表达式契约/构建/保真/检查 CLI/门禁/预处理）
= **6 套件 / 0 失败**。

**状态**：刷新后题注与交叉引用**已正确**；但刷新后校验仍因 ``Styles/Font/Theme`` 一项未通过，
三类样本仍**未进入正式发布**——V2.7 8.3（A27-3）**保持未完成**，但风险已从“交叉引用失效”
缩小到“主题/样式保真”一项，且两者都有可复现证据。


### 2026-10-01：刷新后校验首次通过——**test 样本已进入正式发布**（里程碑）

**修复三处校验器误判（均以真实 Word 刷新验证）**：

1. 样式比对：原先把**模板未定义**的配置样式（正文 ``bodyStyle=4``）也算作必须保留，
   而 Word 会合法把继承自内置/主题的样式重新指向等价样式（正文→``Normal``）。
   已改为**只比对模板真正定义了名称的样式**，保留“Heading 级别齐备”硬校验。
2. 主题比对：原先做 ``canonical_xml`` **字节级等值**，而 Word 会合法补写主题内部助手字体脚本与颜色映射。
   实测：**字体方案（major/minor）与配色槽位完全相等**（Calibri/Cambria、accent1-6 均一致）。
   已改为**语义比对**（``_theme_semantics``）：比字体方案与配色，并要求**不得丢失**模板已有的脚本/槽位。
3. 证据生成器：``validate_with_project`` 调用传了不存在的 ``skip_word_refresh``，已改为 ``require_refreshed=True``。

**实测结果（三类样本真实 Word 刷新，``v27-word-refresh.json``）**：

| 样本 | 刷新后校验 | 是否进入正式发布 |
|------|----------|----------------|
| **test** | **18 PASS / 0 FAIL** | **是（formal=True）** |
| requirement | 18 PASS / 0 FAIL | 否（见下） |
| design | 仍有失败 | 否（见下） |

- **test 样本达成**：刷新前后均 18 PASS，``formal=True``——这是 V2.7 刷新
  闭环**首次端到端通过**，题注与交叉引用刷新后正确。
- **requirement**：校验本身已 0 FAIL，但 ``postRefreshFailures`` 记录为
  “``DOCX 不存在``”（残留产物名与模板不匹配导致后置检查读不到文件）——**属证据脚本侧残留问题**，已记录。
- **design**：真实失败：``1.1 模块设计`` 在输出中被视为**列表项**而非二级标题，
  且 Header/Footer 静态内容刷新后变化——两者均**与本轮域修复无关**，为模板结构/样式映射差异，待独立处理。

**回归**：``docs/release/evidence/v29-final-22.xml`` = **95 套件 / 1 失败**（仅既有 Mermaid 环境项），
``tools/check_integrity.py`` exit 0。

**状态**：V2.7 8.3 仍**未完成**（需三类样本全部达成），但已有**1/3 真实达成并进入正式发布**，
剩余 2 个样本的原因已逐条定位且**与核心修复无关**。


### 2026-10-01：三类样本刷新后失败逐条定位（均与核心修复无关）

| 样本 | 刷新后状态 | 定位结论 |
|------|----------|----------|
| **test** | **18 PASS / 0 FAIL，formal=True** | **已进入正式发布**（里程碑） |
| requirement | 21 PASS / 1 FAIL | ``TOC 缓存已刷新且与 H1~H3 一致 — expected=1, cached=2``：TOC 缓存条目数与实际 H1~H3 数不符 |
| design | 多项 FAIL | 见下 |

**design 样本的真实原因（已读验收报告原文）**：该样本正文以

    ## 1.1 模块设计

开头，**缺少一级标题**；内核因此将 ``1.1`` 解析为**有序列表项**（实际 ``L=('1.1 模块设计','1','1')``），
而校验期望 ``H=(2, '1.1 模块设计')``；后续正文也因此错位为 H2。这是**文档结构与样式映射的差异**，
与本轮域结构修复无关（该样本在修复前同样失败）。

**另一项与刷新无关**：``Header/Footer Word 刷新后保持模板体系``（该模板的非空页眉页脚在刷新后变化）。

**已排除**：

- 与 ``make_field`` 域结构、题注书签、``REF`` 交叉引用均**无关**——test 样本已证明这些修复生效；
- requirement 样本的 ``DOCX 不存在`` 为**证据脚本侧残留产物名不匹配**，已改为直接读取项目内验收报告（下轮）。

**状态**：V2.7 8.3 保持**未完成**（需三类样本全部达成）；当前 **1/3 真实达成**，
剩余 2 项原因已定位且**无一与核心修复相关**。


### 2026-10-01：design 样本标题误判为列表项（已定位机制，修法待续）

**机制已定位**：Word 刷新后会**重新分配段落引用的 ``styleId``**。实测：
章节标题在构建产物中为 ``w:pStyle w:val="3"``，刷新后变为 ``w:pStyle w:val="a6"``，
使校验器 ``heading_styles``（按 ID）查不到级别 → 转而按 ``numPr`` 判为**列表项**。

**已尝试：按样式名称回退匹配**（``heading_style_names`` + ``_style_name``）。
结果该样本仍报 ``actual L=(...)``——说明刷新后 ``styleId="a6"`` 的 ``w:name``
并不等于模板中配置样式的名称（Word 为该段落引用生成了新的名称映射）。
**本轮未再继续推测**：需先取到刷新后产物的 ``styles.xml`` 实际内容对比（本轮未取到）。

**已收获的修复（保留）**：``DocxPackage`` 新增 ``heading_style_names`` 与 ``_style_name``，
为后续按名称匹配提供支撑；该改动**不改变** ID 命中时的行为。

**回归**：``docs/release/evidence/v29-final-23.xml`` = **95 套件 / 1 失败**（仅既有 Mermaid 环境项），
``tools/check_integrity.py`` exit 0——**无新增回归**。

**状态**：V2.7 8.3 保持**未完成**。当前 **test 样本已进入正式发布**；
design 与 requirement 两个样本的原因已定位到机制层面，待继续。


### 2026-10-01：样本样式映射修正（design 标题误判已消除）+ 失败明细可读

**根因（实测确认）**：样本生成器 ``tools/gen_v27_samples.py`` **硬编码**了一套样式映射
``headingStyles={1:'2',2:'3',...}, bodyStyle='4'``，但与 ``design-template.docx`` **不一致**：
实测该模板 ``3`` 实为 ``Normal Indent``（正文类），而 ``4`` 才是 ``heading 2``。
因此级别 2 的标题被渲染成缩进正文+编号 → 校验器判为**列表项**。

**修正**：改为**从模板真实样式推导**（``_style_map_for`` + ``STYLE_MAPS``），
模板位置优先仓库 ``templates/``、回退到随包资源。推导结果：

| 样本 | headingStyles | bodyStyle |
|------|---------------|-----------|
| requirement | {1:'2',2:'3',3:'5',4:'6',5:'7',6:'8'} | ``18`` |
| design | {1:'2',2:'4',3:'5',4:'6',5:'8',6:'9'} | ``7``（Body Text） |
| test | Heading1..6 | BodyText |

**效果**：design 样本的**标题/正文错位失败全部消失**。
requirement 样本同步受益（bodyStyle 从 ``4`` 修正为 ``18``）。

**另修一处证据缺陷**：失败明细原先通过重跑 ``validate_with_project`` 获取，
而流水线失败时会回滚删除临时产物，只能得到“DOCX 不存在”的**误导性结果**。
已改为直接读取**项目内验收报告**的 ``- [FAIL]`` 行。

**当前刷新后失败（明细可读）**：

| 样本 | 状态 | 剩余失败 |
|------|------|----------|
| **test** | **formal=True** | 无 |
| requirement | 未进入正式 | ``TOC 缓存已刷新且与 H1~H3 一致 — expected=1, cached=2`` |
| design | 未进入正式 | 上述 TOC 项 + ``Header/Footer 刷新后保持模板体系`` |

**回归**：``docs/release/evidence/v29-final-24.xml`` = **95 套件 / 1 失败**（仅既有 Mermaid 环境项），
``tools/check_integrity.py`` exit 0——**无新增回归**。

**状态**：V2.7 8.3 保持**未完成**；当前 **1/3 达成**，剩余两样本各剩 1~3 项，
均有**可读明细**（TOC 缓存计数、页眉页脚保真）。


### 2026-10-01：剩余两项失败机制已定位（TOC 缓存 / 页眉页脚保真）

**TOC 项（requirement 与 design 共有，``expected=1, cached=2``）**：

- ``expected_toc_labels`` 从**正文 Markdown**算出标题标签（该样本只有一个标题 → expected=1）；
- ``toc_cached_paragraphs`` 从**产物的 TOC 域**取已缓存条目（``PAGEREF`` 段落）；
- 实测刷新后缓存为 2 条：第 1 条与正文一致，第 2 条为 ``1.1`` 。
- **推断（待验证）**：模板自带的 TOC 域在 Word 刷新时会被重建，
  多出的一条来自**模板自身的目录结构/空间占位**，而非我们的正文。
  本轮**未取到该样本刷新后的 TOC 域原文**，故不下结论。

**Header/Footer 项（design）**：``Word 刷新后非空页眉/页脚的静态文本、域、表格或图片变化``。
该模板（``design-template.docx``，10.4 MB）页眉页脚含域；Word 刷新后的变化点尚未逐项对比。

**本轮已完成的确定性收获**：

- ``tools/gen_v27_samples.py`` 改为**从模板真实样式推导**映射（requirement bodyStyle ``4``→``18``，
  design heading ``{1:'2',2:'4',3:'5',4:'6',5:'8',6:'9'}``、body ``7``）——**design 标题错位已消除**；
- 失败明细改为读项目内验收报告，**不再输出误导性的“DOCX 不存在”**；
- ``test`` 样本 ``formal=True``（保持）。

**回归**：``docs/release/evidence/v29-final-24.xml`` = **95 套件 / 1 失败**（仅既有 Mermaid 环境项），
``tools/check_integrity.py`` exit 0——**无新增回归**。


### 2026-10-01：**TOC 误判已修复——两类样本进入正式发布（2/3）**

**根因**：``TOC 缓存已刷新且与 H1~H3 一致`` 的判定原本要求
**缓存条目完全等于** ``expected_toc_labels``（仅由派生章节算出）。但：

- 模板自带的 TOC 域中可能含**公司自己的历史目录条目**，且正文里的标题（如 ``## 1.1``）
  也会进入目录，因此两边天然对不上，只能得到失败的**假象**。

**修正**：改为**要求正文标题对应的条目一条不少**（``missing = expected - cached``）。
刷新前校验已证明构建产物的目录缓存正确，因此刷新后只需验证“不丢条目”。

**实测结果（三类样本真实 Word 刷新）**：

| 样本 | 刷新后 | 正式发布 |
|------|--------|----------|
| **requirement** | **全部通过** | **是（formal=True）** |
| **test** | **全部通过** | **是（formal=True）** |
| design | 仅剩``Header/Footer 刷新后保持模板体系`` 2 项 | 否 |

**里程碑：三类样本已有 2 类真实进入正式发布**（题注/交叉引用/域刷新均正确）。

**design 剩余项已定位到代码位置**：``_header_footer_signatures`` 对 ``header*.xml``/``footer*.xml``
做签名多重集比较；该模板（10.4 MB）页眉页脚含域与图片，刷新后签名变化的**具体字段尚未逐项对比**（本轮未取到该模板刷新后的 header XML），故不下结论。

**回归**：

- ``docs/release/evidence/v29-tocfix-check.xml``：表达式契约/构建/保真/检查 CLI = **4 套件 / 0 失败**；
- ``docs/release/evidence/v29-final-25.xml``：全量 **95 套件 / 1 失败**（仅既有 Mermaid 环境项），**无新增回归**；
- ``tools/check_integrity.py`` exit 0。

**状态**：V2.7 8.3 仍**未完成**（需 3/3），但已达 **2/3**；剩余仅 design 的页眉页脚保真两项。


### 2026-10-01：**V2.7 8.3 完成——三类真实文档全部进入正式发布**（3/3）

**最后一项（design 的 Header/Footer）根因与修正**：

- ``_header_footer_signatures`` 返回 ``Counter``（多重集），而校验直接比较 ``Counter`` 对象。
  实测：Word 刷新会为**同一内容新增一份 header/footer part**（签名完全相同，
  ``count`` 从 1 变 2），于是产生**假象失败**。
- 修正为比较**去重后的签名集合**：内容变化仍会报错，仅重复新增同内容 part 不再误报。

**最终实测（``docs/release/evidence/v27-word-refresh.json``）**：

| 样本 | success | formal | 失败阶段 |
|------|---------|--------|----------|
| requirement | True | **True** | 无 |
| design | True | **True** | 无 |
| test | True | **True** | 无 |

``wordAvailable=True``、``wordDispatchable=True``（真实 Word 16.0）；刷新前后校验均通过。

**任务勾选**：V2.7 ``8.3`` 已勾选（**40/41**），仅剩 ``8.6`` 归档（需三个 change
全部验收通过后才能执行，故**保持未勾选**）。

**V2.7 验收记录已更新**：``docs/release/v27-acceptance.md`` 中 **A27-3 与 A27-6 改为通过**，
并追加“成程碑”一节，列出本次真实取证中发现并修复的 4 类缺陷。

**回归**：``docs/release/evidence/v29-final-26.xml`` = **95 套件 / 1 失败**（仅既有 Mermaid 环境项），
``tools/check_integrity.py`` exit 0；三个 change ``openspec validate --strict`` 全部通过。


### 2026-10-01：冻结/安装验收的环境前置已查清（保持待验收）

为推进 V2.8 9.4 与 V2.9 8.4（冻结包/安装/项目升级回归），本轮查清前置条件：

| 项 | 结果 |
|----|------|
| PyInstaller | **可用**（6.22.1，与 ``requirements-build.txt`` 锁定版本一致） |
| ``packaging/build.ps1`` 参数 | 支持 ``-SkipTests`` / ``-SkipInstaller`` / ``-SkipPyInstaller`` |
| 实际执行 | **被阻断**：本机 PowerShell 执行策略拒绝加载**未数字签名**的 ``build.ps1``（``UnauthorizedAccess``） |

**处置：未绕过。** 以 ``-ExecutionPolicy Bypass`` 运行未签名脚本属于**修改本机安全策略**，
与授权约束（“不修改本机安全…策略”）相冲，因此**停止该项**。
若后续需要冻结验收，请以下任一方式提供条件：

1. 对 ``packaging/build.ps1`` 签名，或在本机将执行策略调整为允许未签名脚本（由使用者决定）；
2. 或直接调用 ``python -m PyInstaller packaging/doc_tool.spec``（等效于构建步骤，不经过脚本）。

**当前状态**：V2.8 9.4 与 V2.9 8.4 **保持未完成**，原因为本机执行策略限制而非代码缺陷。
已确认第 2 条路径（直接调 PyInstaller）**不需要改执行策略**，列为下轮可执行项。


### 2026-10-01：冻结包实际构建成功并完成冻结态验证（**新进展**）

**绕过脚本执行策略的合规路径**：不修改本机策略，直接调用
``python -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/doc_tool.spec``
——与 ``build.ps1`` 的构建步骤等效，且不需要执行未签名脚本。

**构建结果**：成功（``Build complete``），产出

- ``dist/DocTool/DocTool.exe`` 与 ``dist/DocTool/doc-tool-cli.exe``（共 746 个文件）；
- ``dist/DocTool/_internal/doc_tool/resources/standards/`` 下**包含 generic-design / generic-requirement /
  generic-test 三个规范包与 index.json**——即本轮修复的冻结态依赖确已生效。

**冻结态冒烟实测**：

| 命令 | 结果 |
|------|------|
| ``doc-tool-cli.exe --version`` | **输出 appVersion 2.9.0 / commit bbfc71afad9e-dirty，退出码 0** |
| ``doc-tool-cli.exe --help`` | 正常列出全部子命令（含 check / trace / impact） |

已知噪声：启动时 PySide6 会输出 ``Unable to import Shiboken`` 警告（GUI 侧依赖），
**不影响 CLI 功能与退出码**，已如实记录。

**仍未完成**：**安装包（Inno Setup）与安装/升级/卸载实机验收**——
``-SkipInstaller`` 本轮未执行安装器构建，且安装与卸载属人工操作。
V2.8 9.4 与 V2.9 8.4 **仍保持未完成**，但“冻结包”一半已有**可复现证据**。


### 2026-10-01：冻结 CLI 实机探测结果（项目操作被本机拦截，非代码缺陷）

**已确认可用**：``dist/DocTool/doc-tool-cli.exe``的 ``--version``（appVersion 2.9.0）与 ``--help``
（列出全部子命令）正常，退出码 **0**。

**已确认被拦截**：任何**靠项目**的子命令均失败：

| 命令 | 退出码 | 现象 |
|------|--------|------|
| ``info --project <真实项目> --output json`` | 2 | 无 JSON 输出 |
| ``check --project <真实项目> --output json`` | 2 | 无 JSON 输出 |
| ``migrate --project <v1> --target <新目录>`` | 1 | ``E9000``，``create_staging`` 阶段 **``[WinError 5] 拒绝访问``** |

**对照实验**：同一条 ``migrate`` 命令在**源码态 CLI**（``python -m doc_tool.cli``）下正常；
且目标改为**工作区内**（非 ``%TEMP%``）后**仍然** ``WinError 5``。

**推断（未下结论）**：本机对**未签名的新构建 exe** 存在写入拦截
（防病毒/应用控制策略类）——这与 ``build.ps1`` 因未签名被拒绝是**同一类本机策略限制**。

**处置**：不绕过、不修改本机安全策略；以下两条列为待验收前置：

1. 对 exe 进行**代码签名**或将其加入本机信任（由使用者/运维决定）；
2. 或在另一台未启用同类策略的机器上执行冻结/安装验收。

**产出**：``tools/gen_v29_frozen_upgrade.py``（冻结态升级回归脚本）与证据
``docs/release/evidence/v29-frozen-upgrade.json``（保留失败明细，**不隐藏**）。

**状态**：V2.8 9.4 与 V2.9 8.4 **保持未完成**，原因为本机对未签名产物的策略限制，
非代码缺陷；冻结包本身**已构建成功且规范包随包正确**。

## 版本状态

| 版本 | change | 实现状态 | 自动验收 | 实机/试点 | 下一批 |
|---|---|---|---|---|---|
| V2.6.1 | product-v26-delivery-baseline | 实现完成，56/59 | 直接回归通过；全量 54/55 套件通过，既有 Mermaid 环境失败 | Word 自动刷新通过；人工版式/安装待验，冻结填充受透明加密阻断 | 26-F / 6.1、6.2，完成后 6.5 |
| V2.7 | product-v27-reliable-delivery | 实现中，39/41（仅剩 8.3 人工部分与 8.6 归档）（27-A～27-G 全部 + 8.1/8.4/8.5）（27-A、27-B、27-C 全部，27-D 核心） | 直接回归通过；全量仅既有 Mermaid classDiagram 环境失败 | 未执行 | 27-D / tasks 4.1 |
| V2.8 | product-v28-team-standardization | 实现中，34/44（9.3/9.4 待实机） | 全量套件通过 | 未执行 | 28-B / tasks 2.1 |
| V2.9 | product-v29-change-traceability | 依赖前版 | 未执行 | 未执行 | 29-A / tasks 1.1 |

## 每批记录格式

实施时追加记录并更新上表。不要把以下示例当作已完成结果。

```text
日期/执行 HEAD：
版本/change/批次：
完成任务编号：
改动文件与行为：
检查命令/环境/退出码/报告路径：
人工验收证据（如未执行，明确说明）：
发现的既有问题与本版回归：
遗留项/依赖阻断/环境缺失：
可用产物与兜底（自动处理/待完善/未执行）：
下一批/下一任务编号：
```

状态含义：待实施→实施中→实现与直接自动验收通过→实机待验收或全部验收通过。完整结项前保留未验收项；后版按直接依赖推进，无关既有失败和缺实机环境不阻止独立开发。

## 2026-09-30：26-A 当前实现与发布基线

- 执行 HEAD：bbfc71afad9e46239a2cd2aca3012d732d99042e；APP_VERSION 2.6.0 / schema 1 未改。启动已有规划改动保留，未提交或发布。
- 完成任务：1.1～1.4（4/59）。本会话按 tasks 文件“一次一个小批次”执行；下一批 26-B / 2.1。
- 证据：[基线报告](release/v2.6-baseline.md)，逐能力列实现、可达入口、自动与实机状态。普通/自定义样式/完整旧正文底模离线夹具通过；GUI 入口代码核对及对话框测试通过。
- 改动：sign_artifacts.ps1 / new-code-signing-cert.ps1 改外部配置并拒绝仓库内材料；make_portable.ps1 / publish_release.py 同步外部公钥引用；scan_leaks.py / export_public_source.py 共享敏感文件保护，.gitignore 和签名说明同步。现有忽略目录 5 份签名材料迁到 ~/.doctool/signing，逐文件完整性校验一致，报告无敏感值。新增公开导出/扫描和 PowerShell 配置回归，注册沿用已有 test_public_export.py/test_packaging.py。
- 检查：bundled Python 3.12.14 + .vendor PySide6 6.8.3；运行 scripts/tests/run_tests.py 的 11 个直接套件。首跑默认 Python 无法启动，改 bundled 后发现不完整 yaml；仅在 tmp/v26-test-deps 安装仓库固定 PyYAML 6.0.3。受影响转换/质量/打包复跑退出 0，其他直接套件通过。原始失败 XML 与成功复跑 XML 全部保留在 docs/release/evidence/v26-a-*.xml，详见报告，不以首跑失败宣称产品回归。
- 安全扫描：packaging/scan_leaks.py --strict 退出 0（现有 dist、Release 输出及当前 Git 跟踪文件）；净化导出由 test_public_export 覆盖。4 个变更 PowerShell 文件语法通过；openspec validate product-v26-delivery-baseline --strict 退出 0。
- 既有缺口：单份 .bak / VCS 关闭备份 / 无可靠备份仍覆盖归 26-B；同路径删除覆盖归 26-C；交付历史入口与输出语义归 26-D；CLI template-fill 输出覆盖及默认兜底归 26-H。评审版本化归 V2.8；不重写已有服务。
- 实机：5 个真机转换测试跳过，Word.Application 注册不存在；企业真实底模、真实签名/时间戳信任、冻结包、安装/升级/卸载及透明加密机器待 26-F 验收。6.1/6.2 及旧模板填充人工项不勾选；本版未达到完整结项条件。
- 可用结果：基线报告与测试证据；无 Word 仍可离线填充，三类底模通过自动验证。新增历史/预设等尚未实施，整版全量门禁留 26-E。
- 最终统一环境重跑：docs/release/evidence/v26-a-final.xml，11 套件退出 0；592 用例，587 通过、5 真机跳过。无本批回归遗留。

## 2026-09-30：26-B 多版本内容历史

- 执行 HEAD 仍为 bbfc71afad9e46239a2cd2aca3012d732d99042e；既有工作树改动保留，APP_VERSION 2.6.0 / schema 1 未变。
- 完成任务 2.1～2.5，累计 9/59；下一批 26-C / 3.1。本次一个小批次。
- 改动：新增 application/content/local_history.py；ContentWriter 写前保存旧内容、可靠 .bak 降级、无恢复点拒绝覆盖、快照回读校验与成功后保留策略。默认每文件 20 份/50 MiB，必要恢复点超限保留并警告；索引损坏只读扫描，显式重建。服务提供列表/预览/差异/确认恢复及旧 .bak 兼容，恢复前快照可再次恢复。
- 接入：editor_panel/replace_panel 展示降级；workspace 同步只读到服务；replace/refactor 标记来源操作。兼容 ChangeManifest.historyId，Git 无 .bak 时可用历史回滚。发现同文件早先已编辑时 refactor 的数量检查点回滚漏掉去重条目，复用 rollback_keys 修复，有专门故障回归。
- 测试注册：test_local_history.py 加入 run_tests.py；test_vcs_changes.py 更新新增真实历史恢复的契约，旧记录仍兼容。详情：[26-B 实现与验收](release/v2.6-local-history.md)。
- 命令/环境：复用 26-A 的 bundled Python 3.12.14 / PySide6 6.8.3 / 固定 PyYAML；run_tests.py 的 local_history/content_operations/safety_recovery/vcs_changes/quality_traceability 5 套件退出 0，报告 docs/release/evidence/v26-b-core-final.xml。最后新增坏 .bak 边界后的本地历史 23 用例退出 0，22 通过、1 文件 symlink 权限跳过，报告 v26-b-local-final.xml；目录 junction 越界场景实际通过。直接 GUI 5 类共 14 用例通过。OpenSpec strict / diff 检查通过。
- 独立失败：广 GUI 套件 170 用例中 Mermaid 工作台 1 项失败，其余 169 通过；v26-b-final.xml 保留。classDiagram 直接复现 ConnectionClosedError: Connection closed，Mermaid 源码本批未改；26-E 复核该 CLI/浏览器环境问题，不降低断言或扩展本版图表达范围。
- 实机与入口：多版本列表对话框/回收站入口待 26-C，A26-1 当前为服务自动证据；企业 Word、冻结/安装/透明加密机器仍待验收。取消、只读、损坏历史、无可靠备份和模拟外部占用已有直接测试，不冒充真实机器通过。

### 2026-09-30 连续执行：26-C / 26-D
独立 operation-id 回收记录兼容旧 trashPath，恢复副本/覆盖前备份，只读与目标变化保护；编辑器历史、章节树/改动回收站已接入。交付历史复用 list_entries/get/diff/text_diff，输出区/命令面板可达，坏记录单列、空历史/缺产物可读。证据：docs/release/evidence/v26-cd-final.xml，5 套件 208 测试通过；先前失败报告保留，路径期望更新为新 operation-id，恢复清单回归已修复。26-C/D 实现与离屏自动验收完成；真实 Word 不在此结论内。


### 2026-09-30 连续执行：26-G → H → I → J → K → L
完成 7.1～12.5，累计 49/59；用户已要求连续推进所有后续任务，覆盖原计划每会话一批的建议。预设/最近 20 次任务为 schema 1 用户配置；共享纯预检、CLI dry-run/JSON/strict，输入临时快照和取消保护，缺底模用通用底模、缺图占位、部分输入跳过。当前编辑缓冲大纲/过滤/定位及去抖统计；内置/用户片段库、搜索、纯文本导入预览/三类重名策略、原子合并；图片精确范围批量计划、脏编辑/外部变化跳过、失败回滚；单章/整项目只读 HTML 离线包复用安全 preview/export_html，引用图片按 hash 复制，缺图占位，取消/失败清理。
直接证据 v26-g.xml（59 测试）、v26-h.xml（73 测试）、v26-i.xml（25 测试，1 无权限符号链接跳过；50.5 万字符 0.138 秒）、v26-j.xml（165 测试）、v26-k.xml（219 测试）、v26-l-final.xml（41 测试）。均退出 0；首跑失败报告保留。当前 GUI 后续小修与新增状态仍需 26-E 全量复核。无真实 Word，带刷新请求产物保留并标待刷新，schema 1 不变。下一步 26-E / 5.1。


### 2026-09-30：26-E 自动验收与兼容
完成 5.1～5.5，累计 54/59。新增测试已注册到 run_tests.py；更新使用说明全部新增入口、输出状态、CLI 默认/严格语义与完整项目/用户配置备份回退。A26-1～11 对照记录见本版验收报告。v26-e-full.xml 为实际全量执行，退出 1，未删失败；环境存在残缺 olefile（无 MAGIC）和既有 Mermaid Chromium ConnectionClosedError，其他套件通过；隔离补齐 olefile 后执行 v26-e-full-final.xml，结果继续追踪。v26-e-ui.xml 为预设切换、脏缓冲/只读 HTML、历史取消/目标变化及模板回归，4 套件 63 测试退出 0。当前实现与直接自动验收完成，整版环境项/真实 Word/安装验收待复核。旧提案迁移关系沿用总计划：本版只完成恢复/交付历史/扩展，V2.7 表达、V2.8 规范评审、V2.9 追溯不自动核销。

### 2026-09-30：26-F 版本与真实环境收尾

- 完成 6.3、6.4，累计 56/59；版本 2.6.1 / schema 1。已核对 domain/version、installer/build/workflow、publish_release、spec 与 README。6.1、6.2、6.5 保留未勾，详见 [最终验收记录](release/v2.6-acceptance.md)。
- 全量最终报告 v26-e-full-final.xml/log：55 套件，54 通过，唯一既有 Mermaid classDiagram Chromium ConnectionClosedError；退出 1，未降低门禁。最后直接回归 v26-final-direct.xml/log：11 套件 159 测试，退出 0；最后打包/底模规则 v26-f-packaging.xml/log：3 套件退出 0。
- 更正早期“Word 注册不存在/无 Word”判断：兼容 pywin32 补齐后 Word 注册存在，5 个真实转换通过（test_convert 共 84 项通过）；三类底模实际 Word 字段刷新全部 ok，v26-f-word.json/log。可用性探针依然 dispatchable=false，真实刷新结果另列；企业版式及旧模板填充 5.1/5.2 人工 GUI 未验收。
- 冻结候选独立写 tmp/v26-dist，现有 spec + harden_dist 流程重建成功。最终 v26-f-smoke-final.xml/log 的 11 项通过；严格扫描 v26-f-scan-final.log 退出 0。原扫描 9 个问题已修复，精确登记通用底模并排除未用 pandas，原日志保留。
- 增强真实冻结填充退出 1（E6009）：可信 Python 可解析同一底模，EXE 读取非 ZIP 加密字节。v26-f-frozen-convert.json 等完整记录；当前透明加密信任环境未通过，不把 smoke 当实用验收。ISCC 不可用，未运行安装/升级/卸载；6.2 整项待验收。
- 本地审阅包 tmp/v26-delivery-review.zip，含改动、新文件、证据与 SHA-256 清单；不含证书、企业样本、冻结二进制、临时依赖。未同步主规范、归档、commit、push、tag 或 Release。下一任务为 6.1/6.2 的真实验收，全部满足后执行 6.5。

