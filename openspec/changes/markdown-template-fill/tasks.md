# 任务：模板填充（Word 模板 + Markdown → 格式一致的 Word）

## 1. 模板解析与填充服务（先测）

- [x] 1.1 新增 `doc_tool/application/template_fill.py`：`parse_template_styles(template_docx) -> TemplateStyles`（级别→styleId、正文样式、多级列表有无告警），复用 `domain/ooxml.py` 的 `read_docx_package`/`resolve_heading_styles`/`parse_heading_styles`/`heading_style_candidates`，正文样式推断仿 `importer._find_body_style`
- [x] 1.2 `fill_markdown_with_template(markdown_paths, template_docx, output_path, heading_style_map=None, refresh_fields=False, on_warning=None) -> TemplateFillResult`：Markdown 按文件名自然排序 → 临时章节树 → 内核 config 组装（`paths.template`=用户模板、`documentType`=general）→ `scripts/build_docx.py::build(config=...)` → 输出 DOCX；失败抛 `TemplateFillError` 并清理临时目录
- [x] 1.3 样式映射兜底：`heading_style_map`（styleId→级别）覆盖自动解析；映射有效性校验（至少一个级别 1、无层级跳跃）与导入映射规则一致
- [x] 1.4 图片处理：Markdown 相对路径图片复制临时 assets 并内嵌；缺失/远程图片经 `on_warning` 告警不阻断
- [x] 1.5 域刷新：构建后写 `updateFields`；`refresh_fields=True` 且本机有 Word 时走 `scripts/refresh_fields.py` COM 刷新目录

## 2. 互转中心集成

- [x] 2.1 `convert.py`：`DIRECTIONS` 注册「Markdown → Word（模板填充）」方向行与后端；`Direction`/`build_plan`/`convert_paths` 增加可选 `template_path`（及样式映射参数），默认 `None` 时既有方向行为不变
- [x] 2.2 `ui/convert_dialog.py`：源为 Markdown、目标为 Word 的行显示「底模（可选）」文件选择（.docx 过滤）；选中走模板填充后端，未选中走既有 CSS 版式方向
- [x] 2.3 样式映射兜底交互：模板自动解析不完整时展示样式候选映射（复用导入映射交互模型，仅本次生效），校验失败阻止开始并定位到样式
- [x] 2.4 结果反馈：转换完成展示产物路径与告警摘要（无标题编号、图片缺失等）

## 3. CLI

- [x] 3.1 `doc_tool/cli.py` `convert` 子命令增加 `--template <docx>`；校验仅在 Markdown 源转 Word 时生效，否则报参数错误；透传 `template_path`

## 4. 自动化测试

- [x] 4.1 `scripts/tests/test_template_fill.py`：标准 Heading 模板与自定义样式模板的解析；映射覆盖自动解析；缺 H1/层级跳跃拒绝；单文件与多文件填充
- [x] 4.2 产物断言：打开产物核对标题段落 `w:pStyle` 与模板 styleId 一致、正文字体字号继承模板、页眉页脚/节属性保留
- [x] 4.3 图片内嵌与告警：相对路径图片内嵌成功、缺失图片告警不阻断
- [x] 4.4 回归：既有互转方向（不选模板）行为不变，`test_convert.py`/`test_convert_ux.py` 全绿；`convert_paths` 可选参数对既有调用兼容
- [x] 4.5 `test_template_fill.py` 加入 `scripts/tests/run_tests.py` 的 `DEFAULT_TESTS`，通过 CI 门禁（coverage ≥ 60）

## 5. 人工验收与文档

- [ ] 5.1 手工验收：企业真实底模 + 多级标题 Markdown → 生成 Word 打开核对封面/页眉/字体/标题编号与模板一致
- [ ] 5.2 手工验收：自定义样式模板走映射兜底流程；无 Word 环境离线出稿（打开时提示刷新目录）
- [x] 5.3 更新 `docs/使用说明.md` 与 `README.md` 功能矩阵：互转中心新增「Markdown → Word（模板填充）」说明

## 6. 优化增强（第二轮：内容保真 + 专属入口）

- [x] 6.1 行内图片拆出独立成行并内嵌（不再退化为字面文本）；列表缩进在拆分时保留
- [x] 6.2 引用块转左缩进段落（内核 `<!-- P:left=720 -->` 方言）、水平线转空段、标题闭合井号剥除
- [x] 6.3 围栏代码块空行以 `<EMPTY_PAR/>` 保留；文件头 YAML front matter 自动剥离并提取 `title:` 写入文档属性
- [x] 6.4 新增「Markdown 模板填充（底模出稿）」独立入口（工具菜单 + 命令面板）：多 Markdown 按列表顺序合并为单个 Word，支持排序/输出定制/域刷新
- [x] 6.5 互转对话框选定底模后行级格式下拉显示「（模板填充）」标识；目录勾选项提示模板语义
- [x] 6.6 优化项测试：预处理保真单测 7 项 + 端到端集成 1 项 + UI 对话框测试（样式映射/向导/标签）

## 7. 优化补充（第三轮：覆盖保护 + 完整文档底模 + 保真补全）

- [x] 7.1 向导覆盖保护：产物已存在时先确认再生成（服务层为显式覆盖语义，界面不再静默替换）
- [x] 7.2 「拿现成文档当底模」：`parse_template_styles` 检测正文标题段数量；`clean_body_from_first_heading` 复用 `importer.generate_template` 从第一个标题 1 起清理旧正文；向导检测到完整文档时自动勾选清理
- [x] 7.3 Setext 标题（`标题`+`===`/`--`）按 CommonMark 转 ATX（列表项/空行后不误判）；GFM 任务列表 `- [ ]`/`- [x]` 转 ☐/☑ 符号列表项
- [x] 7.4 向导体验：拖放 .md 入列、底模路径记忆（`~/.doctool/template_fill.json`，互转对话框只存不回填）、打开产物/输出文件夹、失败按错误码给出解决指引
- [x] 7.5 CLI 子命令 `template-fill`（多 Markdown 按顺序合并 + `--template/--output/--map/--refresh-fields/--clean-body`）
- [x] 7.6 测试：Setext/任务列表/正文清理/底模记忆/CLI 共 12 项；UI 记忆隔离（基类统一打桩）
