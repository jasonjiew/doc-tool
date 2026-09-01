# Doc Tool 文档工具

> 公司内部项目，仅限内部使用，请勿对外分发源码与安装包。

面向需求说明书、详细设计、技术手册等大型 Word 文档的 Windows 桌面维护工具：把 Word 文档转成
可维护、可审查、可可靠重建的 Markdown 项目，编辑完成后一键重建正式 DOCX 交付物。

- 当前版本：**2.0.0**（安装版 + 免安装便携版）
- 项目地址：<http://192.168.0.242:8899/application/ai/doc-tool>
- 下载入口：<http://192.168.0.242:8899/application/ai/doc-tool/-/releases>
- 使用说明：[docs/使用说明.md](docs/使用说明.md)

## 功能简介

- **Word 导入**：识别 Heading 1～6、图片、表格，保留封面、样式、页面设置、页眉页脚；
- **Markdown 工作台**：章节树管理、多标签编辑、实时预览、全文搜索与替换、图片与 Mermaid 图表；
- **修订记录**：以 `content/<类型>/_revision_record.md` 为唯一维护点，末行版本号即文档版本号；
- **校验与出稿**：结构/资源/模板校验 → 重建 DOCX → 调用 Word 刷新目录与页码 → 复验后原子发布；
- **文档互转**：工具菜单里的批量互转，对标在线转换平台的常用功能集——Word/PDF/Markdown/HTML/
  TXT/XLSX/CSV/RTF/ODT 互转（方向矩阵见使用说明第 6 节）：Word↔PDF（支持页范围）、Markdown/HTML →
  Word（本机 Word 完成并自带排版样式：宋体/Times、内置标题层级、表格边框、代码块底纹、图片内嵌）、
  Word → Markdown（离线完成，单文件 .md + assets 资源目录）、Markdown/Word/Excel → HTML、
  XLSX↔CSV、TXT/Excel/CSV → PDF（经 Word 排版导出）、RTF/ODT 导入；
- **安全编辑**：自动草稿、崩溃恢复、变更对比与回滚、项目锁与只读模式。

## 系统要求

- Windows 10 / 11，无需安装 Python；
- 正式出稿需要安装 Microsoft Word（导入、编辑、校验、诊断构建不依赖 Word）；Word↔PDF、
  Markdown/HTML → Word、TXT/Excel/CSV → PDF、RTF/ODT 导入等互转方向必须由本机 Word 完成
  （Word → Markdown/HTML、XLSX↔CSV 离线完成，不需要 Word）。

## 安装与使用

两种分发方式，任选其一（推荐安装版）：

| 方式 | 说明 |
| --- | --- |
| 安装版 `DocTool-Setup-2.0.0.exe` | 双击安装，默认安装到 `%LOCALAPPDATA%\DocTool`，无需管理员权限 |
| 便携版 `DocTool-2.0.0-portable.zip` | 解压到任意目录，首次先双击「安装证书.cmd」导入公司证书，之后双击「启动DocTool.cmd」启动 |

> 安装目录/便携包根部的 `diagnose.cmd` 为诊断脚本，遇到启动问题双击运行，
> 将生成的 `DocTool-diagnose.txt` 发给维护人员即可。

典型流程：

1. 打开程序，选择「新建项目…」，选择一个有规范 Heading 结构的 `.docx`；
2. 确认标题样式映射、填写文档编号与名称，等待导入完成；
3. 在章节树中编辑 Markdown 正文，维护修订记录（出稿前在修订记录表末尾加一行，末行版本号即文档版本号）；
4. 校验项目（F5）→ 正式合并出稿，可交付 DOCX 输出到项目目录 `output/`。

## 从源码运行与开发

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
python -m doc_tool.app        # 启动桌面应用
python scripts\tests\run_tests.py   # 运行完整测试
```

## 打包发布

本地打包（需要 Inno Setup）：

```powershell
.\packaging\build.ps1                    # 安装版 DocTool-Setup-2.0.0.exe
.\build_exe.ps1 -Portable                # 免安装便携包 DocTool-2.0.0-portable.zip
```

发布新版本需同步版本号（当前 2.0.0）：`doc_tool/domain/version.py`、
`.gitlab-ci.yml`、`packaging/build.ps1`、`packaging/installer.iss`。
打包产物输出到 `packaging/Output/`，发布到 GitLab Releases 时请使用中文发布说明。

## 代码结构

```text
doc_tool/       应用代码（domain 领域模型 / application 用例 / adapters 适配 / ui 界面）
scripts/        构建、校验、字段刷新与测试脚本
packaging/      PyInstaller 打包、Inno Setup 安装器、便携包与审计脚本
docs/           使用说明、设计与迁移文档
openspec/       功能规格、设计文档与变更任务
```

## 已知限制

- 仅支持有规范 Heading 结构的 `.docx`，不支持旧版 `.doc`（互转里 `.doc` 只支持出 PDF）；
- 正式出稿依赖桌面版 Microsoft Word 刷新目录与页码；互转中走 Word 的方向（Word↔PDF、
  Markdown/HTML → Word、TXT/Excel/CSV → PDF、RTF/ODT 导入）同样依赖本机 Word；
- PDF 转回 Word 是有损的素材级还原（Word 的 PDF 重排会丢标题层级：实测 21 页文档只还原出 7 个 1 级标题），导入前需在 Word 中复核补齐标题样式；
- Markdown → Word 走 HTML 导入，落的是通用排版样式，源文件里的精细排版无法一一保留；Word → Markdown 导出的图片不保留显示尺寸方言（通用 Markdown 不认 `=96x96` 后缀）；
- 公司透明加密（亿赛通 DocGuard）环境下 Python 侧读不到 Word 生成的 PDF，因此 PDF 一律交由 Word 读写，产物只做存在性校验；
- MHT (.mht/.mhtml) 经真机探针验证本机 Word 无法打开，互转不提供该格式；XLSX 转 CSV 只导第一个工作表，公式单元格取的是 Excel 上次保存的缓存值；
- 极复杂的 Word 对象只能作为 OOXML 资源保留，不能在 Markdown 中直接编辑。
