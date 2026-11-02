# Design

## Context

动机和范围见 [proposal.md](proposal.md)。本设计以 2026-10-31 本地 `main` / `6a3a994` 为源码基线，版本变化后先复核相关位置，不切换或覆盖其他会话的修改。

| 已核对现状 | 位置 | 对设计的约束 |
| --- | --- | --- |
| 编辑器构造原生 `_PreviewBrowser`，明确停用 WebEngine | `doc_tool/ui/content/editor_panel.py:728` | 不能只改现有网页 CSS，必须真正接入编辑器与生命周期 |
| 受控 Markdown 解析去掉缩进，按竖线直接拆表格，每行生成段落 | `doc_tool/application/content/preview.py:688` | 新正文解析使用成熟解析器，原生路径保留为明确的轻量模式 |
| 流程图跳过子图/样式，时序图主要绘制参与者和消息 | `doc_tool/application/content/mermaid.py:705,914` | 官方渲染负责完整语义，不继续扩展自绘布局算法 |
| 工作台常见图预览 `use_cli=False`，导出改为 CLI 优先 | `doc_tool/ui/content/mermaid_dialog.py:228,366` | 需要统一渲染契约，避免进入工作台后换成另一张图 |
| 旧网页直接注入解析 HTML，启用 loose Mermaid；本地页允许远程访问 | `doc_tool/resources/web_preview/preview.html:279,327`；`web_preview_browser.py:98` | 旧分支只能复用资源加载、页面壳和交互思路，不能原样启用 |
| 旧网页强制曲线 basis 和时序编号开启 | `doc_tool/resources/web_preview/preview.html:279` | 不把历史样式强制当成 Typora / VS Code 的标准配置 |
| 网页 Mermaid bundle 与 CLI 锁文件内 Mermaid 均为 11.16.1；CLI 包为 11.17.0 | `doc_tool/resources/web_preview/mermaid.min.js`；`tools/mermaid-cli/package-lock.json` | 先用现有引擎版本建立基准；PATH 中实际 CLI 版本还须另核对 |
| 两个 PyInstaller spec 排除 WebEngine/WebChannel | `packaging/doc_tool.spec:164`；`doc_tool_onefile.spec:129` | 安装版/便携版必须验证最终 EXE，而不是源码页面或文件存在 |
| 正文准备已有来源与缓存报告，正式围栏出稿承诺范围仍有限 | `doc_tool/application/prepared_source.py:42,55,70,100` | 复用 `SourceLocation`、`GeneratedAsset`、`PreparedSource.line_map`；不扩大全部 Word 图类型承诺 |

现有相关变更均未假定已归档。`content-authoring-workbench/design.md` 的“排除 WebEngine”和内置子集策略在本功能上由本变更提议替换，其他创作能力及历史任务记录不改。`product-v26-delivery-baseline/specs/readonly-html-preview/spec.md` 的独立离线 HTML 契约继续生效。

`pyside6-app-shell` 已要求业务层不新增 Qt 依赖。本变更把浏览器对象、线程和页面生命周期放在 UI 边界；纯配置、结果元数据、来源映射与缓存键保持普通 Python 数据结构。

## Goals / Non-Goals

**Goals:**

- 以 [content-editor 增量](specs/content-editor/spec.md)、[Markdown 阅读规格](specs/markdown-reading-preview/spec.md)和 [Mermaid 渲染规格](specs/mermaid-diagram-rendering/spec.md)作为行为权威。
- 先得到可在真实冻结包中工作的最小离线浏览器链路，再迁移正文和图形入口。
- 所有异步结果关联页面、章节、缓冲版本和配置；测试观察真实网页结果，不靠原生文档兼容桩证明浏览器成功。

**Non-Goals:**

- 不更换 `QPlainTextEdit` 编辑、保存、撤销、备份、草稿和只读锁模型。
- 首期基础方言为 CommonMark 加表格/任务列表/删除线，保留已有项目扩展。数学、脚注、任意 HTML、Typora 所有插件和即时编辑不自动纳入本期。
- 不把浏览器排版传播为 Word 模板排版，也不把所有 CLI/HTML 导出重写为 GUI 浏览器任务。
- 不升级 PySide6 或 Mermaid 大版本作为默认前提；不引入 Electron/Tauri/WebView2 整体迁移。

## Decisions

### D1. 浏览器阅读模式与原生轻量模式并存

对应 REQ-ED-01、REQ-MD-08。

- 选 QWebEngine：与现有 PySide6 同栈，仓库已有网页资源与浏览器适配器。先使用现有声明版本 PySide6 6.8.3 的能力，验证兼容后决定需要的精确依赖清单。
- 在 UI 建立预览适配边界，避免 `editor_panel` 同时依赖两套控件私有行为。建议的最小操作为更新正文/配置、定位来源、请求图形结果、释放页面；方法命名在实现中按现有惯例确定。
- 高保真默认；用户可主动选轻量。组件缺失、页面加载失败、渲染进程异常时显示原因和实际模式，自动保住轻量/源码阅读及编辑能力。禁止无限重启渲染进程。
- 采用按需导入和按需创建，应用/CLI 启动不能因顶层导入 WebEngine 失败而整体退出。Qt 对象在 GUI 主线程使用，纯计算可交给既有任务机制。
- 旧 `_CompatTextDocument` 是兼容桩，不能用其纯文本内容证明网页已正确渲染；保留必要兼容接口时，仍须从真实页面取渲染完成信号和 DOM/SVG 证据。

取舍：原生 Qt 富文本继续承担轻量兜底，不能满足完整 CSS 排版；WebView2 可减随包运行时但增加 Qt/Windows 集成，当前不选；QWebEngine 的包体、启动和受管环境兼容成本必须记录实测数据。

### D2. markdown-it 解析正文，项目扩展先适配后渲染

对应 REQ-MD-01～REQ-MD-04。

- 首期采用浏览器本地 markdown-it，固定具体版本/插件列表和构建结果；以与 Qt 运行时兼容的 bundle 为交付，不让终端 npm 安装或访问 CDN。
- 复用既有有效正文/模块展开入口，保留当前未保存缓冲。不要给预览再实现一套题注或固定模块展开器。
- 原文与有效正文分开持有。利用解析 token 的块行范围，叠加项目预处理的来源映射，生成块 ID → 原文件/行区间的注册表。现有 `PreparedSource.line_map` 只是已知复用点，不冒充已经覆盖模块跨文件映射；不足时扩展现有来源结果，不能把转换后行号直接回传。
- 图片尺寸后缀用解析规则转换为图片元数据，保留逻辑宽高；不得全局正则替换围栏/行内代码中的相似字符串。
- 项目提示块和占位符作为显式扩展；正文 HTML 首期保持受控，不为追求 Typora 兼容而直接打开任意 HTML 执行。
- `render_markdown_html` 保留既有轻量及相关导出调用语义。不要把返回 HTML 的同步服务偷偷替换成依赖 GUI 的异步服务。

取舍：旧 Marked 页面可作集成原型；最终选 markdown-it 便于对齐 VS Code 的解析/扩展体系和块来源信息。首期不同时引入另一套 Python Markdown 主解析器，以免增加方言分叉。

### D3. 独立阅读主题与统一图形配置

对应 REQ-MD-03、REQ-MM-04。

- CSS 按正文/代码/图形区域限定作用域，避免全局标签样式污染 Mermaid 生成的 SVG/HTML 标签。
- 默认中文/西文字体优先使用现有 Windows 字体栈，代码使用等宽字体；记录实际可用字体和回退。仓库当前没有随包字体目录，不能声称已经内嵌中文字体。
- 参考应用先设置同字体、字号、宽度与缩放再做截图对照。若确实需要新增本地字体，单列来源、许可、体积和加载验证，不接入在线字体。
- 图形字体加载完成、绘制容器具有可用尺寸后才执行渲染；节点尺寸和整体缩放分开处理。使用字体就绪信号，避免固定延时碰运气。
- 用一份可序列化配置描述引擎版本、主题、字体、布局、标签方式、背景、逻辑尺寸和导出倍率。配置优先级为受控默认 → 当前阅读主题 → 允许的图内覆盖；运行权限和全局脚本/任意 CSS 注入选项不接受正文覆盖。
- 不强制自动编号或额外改曲线。源码没有声明时使用已记录的统一默认，不同入口不得各自另设默认。

### D4. 官方 Mermaid 是高保真模式的唯一语法和布局权威

对应 REQ-MM-01～REQ-MM-04、REQ-MM-06。

- 优先复用已随源码提供的 Mermaid 11.16.1 bundle，核对来源、许可和可用图类型。当前 CLI 锁文件中的版本也为 11.16.1，但实际 PATH CLI 可能不同，不能只凭锁文件断言其一致。
- 阅读区与工作台调用同一组网页解析/渲染逻辑，使用官方 `mermaid.parse` / `mermaid.render`。旧 Python 子集校验只用于轻量路径的能力说明，不再阻挡高保真输入。
- 至少完整验收 flowchart 和 sequenceDiagram；其他随包可用图类型通过能力清单声明，未提供的插件/图标不自动联网补齐。
- 同一页面的图形任务串行使用有效配置，避免 Mermaid 全局配置在并发渲染间交叉；返回时仍校验当前文档版本。跨窗口不共用可变页面状态。
- 大图入口复用同一次官方结果。现有 `diagram_viewer.py` 基于 QPixmap，可在保持原交互入口的前提下增加浏览器 SVG 展示或使用同图浏览器栅格结果，不再重新走内置布局。
- 内置自绘保留为明确标注的近似模式。官方失败不再变成未说明的 `ok=True`；错误、后端、旧图和降级原因分别保留。

取舍：继续补手写子图/时序布局需要追随完整 Mermaid 语义，不采用。直接升 Mermaid 12 会引入默认布局变化，本期不通过升级版本顺带改变所有现有图的布局。

### D5. 桌面图形导出复用浏览器结果，CLI 保持独立适配

对应 REQ-MM-05、REQ-MD-08。

- 桌面在同一官方配置下序列化 SVG，并通过图形专用浏览器页面/视口按该 SVG 的 viewBox 和目标像素倍率生成 PNG；字体与首帧就绪是导出前提。具体页面捕获适配留在 UI 内，结果返回普通字节与元数据。
- 执行第一批必须验证“无 Node + 中文多行 + HTML 型标签/foreignObject + 正确裁切 + DPI”的 PNG 能力。不能把只验证纯 SVG、屏幕截图或 `QSvgRenderer.isValid()` 当作该能力通过。
- 不把含浏览器 HTML 标签的 SVG交给 QtSvg 二次绘制后宣称完整保真。目标环境无法稳定产生 PNG 时保留该交付项未完成，不能改成依赖终端安装 mmdc 以掩盖桌面规格缺口。
- 资源命名、`assets/<类型>/images/` 路径、图片引用及可撤销插入复用现有服务；区分逻辑显示尺寸、物理尺寸、实际像素和像素倍率。
- 无 GUI CLI 继续使用现有 mmdc/近似后端接口，不导入或启动 GUI 浏览器。官方 CLI 适配器共享配置口径并检查实际版本；无法满足时报告实际后端/降级，不许标成与高保真桌面一致。
- 已有 PNG/SVG 图片引用仍可走既有 Word 构建。直接在正式稿中处理 Mermaid 围栏的图种承诺，不因桌面增加能力而自动扩大；需要支持的新出稿图种另按其正式契约处理。

### D6. 结果身份、缓存和更新顺序

对应 REQ-MD-06、REQ-MD-07、REQ-MM-04、REQ-MM-06。

以下字段是建议的数据契约，新增位置和命名以既有代码惯例调整，不代表当前已经存在：

- 页面快照：编辑会话/窗口标识、章节标识、递增缓冲版本、原文与有效正文 hash、主题/配置 hash、资源根与来源映射。
- 图形身份：块 ID、原文件/行、source hash、渲染引擎版本、配置 hash、字体与逻辑尺寸、实际后端、SVG/PNG、错误/降级原因。
- 页面回包：同一会话/章节/缓冲版本/主题下才应用；切章和关闭时失效旧 token 并释放引用，不等待同步 CLI。
- 图形缓存键包括 source、引擎版本、有效配置、字体、尺寸、输出格式和倍率；更新现有 `mermaid.py` 缓存和 `prepared_source.py` 缓存版本策略。旧缓存缺少这些身份字段时不能算高保真命中，不批量删除用户缓存。
- 第一步先保证去抖、最新结果和滚动块锚点恢复；再按实际量测对正文块和图形复用。不得用不正确的块 diff 换取表面上的更新速度。
- 记录固定样本的首次渲染、更新延迟、峰值内存、启动与包体；当前没有业务性能基线，不预填提升比例或宣称已达成延迟阈值。

### D7. 正文边界、通信与离线资源

对应 REQ-MD-05、REQ-MD-08。

- 不直接沿用旧页面 `innerHTML = marked.parse(...)` 配合任意正文 HTML 的行为。普通正文转义/解析规则、允许的项目扩展、图形生成结果分别处理。
- Mermaid 使用受控配置与官方消毒能力，正文不得覆盖安全参数。错误提示使用文本写入，避免把错误字符串再次作为 HTML 注入。
- 桌面与页面采用小范围结构化通信，优先 QWebChannel；只暴露预览就绪、块定位和图形结果等动作。定位回传块 ID 后在当前快照注册表解析，不接受页面传入任意路径或任意 Python 调用。
- 应用资源和已引用的项目资源使用分别校验的根路径，校验实际解析路径和链接目标；关闭不必要的远程访问，拦截导航与网络取资源。外部链接沿用用户触发的系统浏览器入口。
- WebEngine/WebChannel 对象与资源路由放在 UI。`domain`、`application`、`adapters` 不新增 Qt 依赖，后台任务与 CLI不因导入纯结果对象而拉起浏览器。

### D8. 分发和降级

对应 REQ-ED-01、REQ-MD-08。

- 通过最小冻结包验证后，再调整两个 PyInstaller spec 的模块排除与资源收集；核对 WebEngine 子进程、运行资源、语言资源、静态 JS/CSS、许可文件和资源定位。
- 同步检查实际构建脚本、安装版和便携版；单文件 spec 若仍为维护入口，则同样验证其行为，不以存在一个成功构建替代所有受支持分发形式。
- 不依赖开发机全局 Node/mmdc、系统浏览器安装路径或源码目录中的未打包文件。冻结态和开发态均通过既有资源定位入口取文件。
- 用户可见名称为“高保真阅读预览”与“轻量预览”；加载状态、失败原因和恢复路径清楚，具体后端版本放诊断信息。
- 发布说明依据最终 EXE 实测结果更新，不提前宣布交付；本变更不执行签名、安装到共享目录、上传 Release 或自动升级部署。

## Risks / Trade-offs

| 限制 | 影响 | 处理 | 验证 |
| --- | --- | --- | --- |
| 浏览器运行时增加体积和进程 | 启动、内存及受管环境兼容成本增加 | 最小冻结包先验证，保留轻量入口 | 真实 Windows 安装版/便携版，记录冷启动、内存、包体和失败原因 |
| 旧网页原始 HTML 与远程权限较宽 | 直接恢复旧分支会扩大正文执行与文件访问能力 | D7 的受控正文、资源根和结构化通信 | 活动内容、恶意 URL、路径逃逸与断网场景 |
| 官方 SVG 含 HTML 型标签 | QtSvg 可能漏标签，浏览器捕获可能得到未完成帧 | D5 的独立 PNG 能力验证 | 中文多行、foreignObject、viewBox/DPI 对照及真实 Word 插图 |
| 全文替换和异步乱序 | 阅读位置丢失、旧图覆盖新图 | D6 的身份校验和阅读块恢复 | 快速编辑/切章/主题切换/关闭/多窗口 |
| 模块展开改变行号 | 点击预览定位错误文件或行 | 复用并补齐真实来源映射 | 重复标题、同源多图、模块跨文件展开 |
| 实际 CLI 与 bundle 版本不一致 | 导出结果与桌面不同 | 检查实际版本和配置，报告不一致及降级 | PATH 覆盖、本地 CLI、无 CLI 三种环境 |
| 未安装参考应用或 Word | 缺少真实阅读/插图验收 | 保留自动化结果，人工项目标 not-run/blocked 并注明恢复条件 | 不用 DOM 断言、Mock 或已有历史截图替代实机对照 |

## Migration Plan

按 [tasks.md](tasks.md) 编号顺序推进；阶段依赖为：

1. 固定样本与环境 → 最小离线 WebEngine 和桌面 PNG 验证。
2. 预览适配边界/正文来源 → Markdown 与阅读主题 → 资源边界。
3. 官方 Mermaid 与统一配置 → 工作台/大图 → 桌面及 CLI 导出适配。
4. 来源联动、更新身份、缓存和阅读连续性。
5. 现有回归与真实页面验证 → 完整冻结包 → 干净机断网与参考应用/Word 实机验收。

回退以切换轻量模式和保留旧渲染适配器为主，不迁移或改写用户 Markdown。新增渲染缓存作为可丢弃派生物使用独立身份/格式版本；回退不覆盖既有图片、不可变交付物或历史快照。没有用户明确指令不提交、推送、发布或归档。

## Verification Strategy

- 语义夹具至少覆盖：多层混合列表/起始编号/段落换行、转义竖线/三种列对齐/长宽表、代码保护、图片尺寸/提示块/题注/模块，以及流程图子图/样式/回边/中文长标签、时序图条件/循环/并行/备注/激活条。
- 纯单元测试验证解析前置规则、来源映射、配置/缓存身份与错误分类；不通过重写预期来迎合旧行为。
- GUI 集成使用实际页面就绪和 DOM/SVG 断言，再用截图对照可见外观。必须检查控制框、标签、分组是否存在，而不是仅断言“有一张图片”或 `RenderResult.ok`。
- 现有相关测试入口包括 `test_content_operations.py`、`test_authoring_services.py`、`test_v30_preview_instances.py`、`test_diagram_viewer_interaction.py`、`test_prepared_source.py`、`test_readonly_html.py`、`test_packaging.py`、`test_cli_machine.py`；新测试注册进 `scripts/tests/run_tests.py`。
- 测试报告写本次独立目录并记录内层实际用例/失败/跳过数。无法启动浏览器的环境不能把跳过的 GUI 验收算通过；机器参考应用与正式 Word 检查单列。
- 仅 OpenSpec 校验通过表示文档结构有效，所有任务完成与业务验收另行记录。

## References

- [Qt 6.8 Markdown 编辑器示例](https://doc.qt.io/qtforpython-6.8/examples/example_webenginewidgets_markdowneditor.html)：浏览器页面与桌面通信的官方参考。
- [VS Code Markdown 扩展机制](https://code.visualstudio.com/api/extension-guides/markdown-extension)：CommonMark、markdown-it 与样式扩展。
- [Typora 主题](https://support.typora.io/About-Themes/)与 [Mermaid 配置](https://support.typora.io/Draw-Diagrams-With-Markdown/#global-mermaid-options)：样式和图形参数应分别固定。
- [Mermaid 字体与标签](https://mermaid.js.org/config/usage.html#labels-out-of-bounds)、[布局变化](https://mermaid.js.org/config/layouts)：字体就绪与版本/布局变化对对照结果的影响。
- [Qt SVG 能力范围](https://doc.qt.io/qt-6.8/svgrendering.html)：不能据 SVG 可载入推导完整浏览器标签均已还原。
