# Doc Tool 文档工程化工作台

> **Docs-as-Code for Enterprise Documents**  
> 把大型 Word 文档工程化拆解为可版本追踪、可多人协同、可严谨审查的 Markdown 章节树，并在出稿时一键可靠重建为符合企业规范的正式 DOCX 交付物。

[![Version](https://img.shields.io/badge/version-2.3.0-blue.svg)](http://192.168.0.242:8899/application/ai/doc-tool/-/releases/v2.3.0)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-Internal-red.svg)]()

- **当前版本**：`v2.3.0`（企业安装版 + 免安装便携版）
- **代码仓库**：<http://192.168.0.242:8899/application/ai/doc-tool>
- **发布下载**：<http://192.168.0.242:8899/application/ai/doc-tool/-/releases>
- **详细指南**：[docs/使用说明.md](docs/使用说明.md)

---

## 为什么需要 Doc Tool？（存在意义与痛点解构）

在研发、工程、医疗器械、质量合规等高标准体系中，**Microsoft Word（`.docx`）是必不可少的最终受控交付媒介**：它拥有法定封面、受控页眉页脚、版本修订记录表、签批栏以及标准页码体系。

然而，**直接使用 Word 编写与维护动辄几十页、上百页的超大型技术文档（需求规格说明书、架构设计方案、系统详细设计书、接口手册等），是所有工程师与团队的噩梦**。

### 传统 Word 协作的五大死穴

1. **二进制黑盒与版本控制荒漠**  
   `.docx` 本质是一个 ZIP 压缩的 XML 复合二进制包。Git 等版本控制系统无法对其进行行级 diff。团队提交记录里只有一堆“*修改了第3章_最终版.docx*”，看不到哪一行被改动，根本无法开展 Pull Request / Merge Request 与精准的 Peer Review（同行评审）。
2. **多人协同的“合并地狱（Merge Hell）”**  
   当张三负责第 2 章、李四负责第 3 章时，无法同时在一个 Word 文件中编辑。团队只能各自另存文件，最后由一人花费数小时人工肉眼比对、复制粘贴，极易发生改动覆盖、内容漏丢。
3. **格式排版的“熵增污染”与样式漂移**  
   每个人的 Word 版本、系统字体、复制源各不相同。随意从网页、IDE 粘贴一段内容，就会带入未知的样式垃圾。文档越改越长，标题序号断档、中英文字体错乱、行间距忽大忽小、目录索引损坏，工程师将超过 40% 的心智消耗在无意义的调字体、对缩进上。
4. **长文档性能雪崩与崩溃损毁**  
   当 Word 插入了大量高清系统截图、流程图与复杂表格后，文件体积飙升，打开卡顿、滚动掉帧、输入卡死频发，甚至遭遇断电或异常崩溃后整个 `.docx` 损坏无法修复。
5. **AI 时代的结构化断层**  
   现代大语言模型（LLM / Coding Agent）具备极强的内容生成、校验与总结能力，但它们天生擅长纯文本与结构化的 Markdown，极难处理 Word 复杂的嵌套 XML 结构。直接用 Word 无法享受现代 AI 工具带来的生产力红利。

---

## 核心设计哲学：为什么要把 Word 打散成多个 Markdown 文件？

Doc Tool 的核心哲学是 **Docs-as-Code（文档即代码）** 与 **关注点分离（Separation of Concerns）**：

```mermaid
graph LR
    subgraph Input ["输入源"]
        Word[大型受控 Word 文档]
    end

    subgraph Decompose ["工程化解构 (Doc Tool)"]
        Tree["章节 Markdown 树\n(1.1 引言.md / 2.1 架构.md)"]
        Tpl["企业排版底模\n(template.docx 封面/页眉/样式)"]
        Assets["媒体资源池\n(assets/ 图片/图表)"]
        Rev["单点修订记录\n(_revision_record.md)"]
    end

    subgraph Workflow ["Docs-as-Code 日常协同"]
        Git["Git 行级版本追踪 & PR 审查"]
        Edit["秒级命令流编辑 / 智能表格 / 代码高亮"]
        Review["离线差分评审稿导出 & 意见闭环"]
    end

    subgraph Output ["自动化重建交付"]
        Gen["一键编译构建 + Word 域刷新"]
        FinalDOCX["高品质合规 DOCX 交付物"]
    end

    Word --> Decompose
    Decompose --> Workflow
    Workflow --> Output
```

### 1. 章节化粒度：让团队并发协作天然“零冲突”
- 工具基于 Heading 1～6 标题层级，把上百页的庞然大物拆解为树状目录（如 `content/第3章 系统设计/3.1 模块架构.md`）；
- 团队成员各自提交自己负责的章节 `.md` 文件，Git 可以实现毫秒级自动合并，团队并发写作再无冲突与覆盖。

### 2. 内容与排版彻底解耦：工程师只专注内容表达
- **内容归 Markdown**：正文使用纯文本 Markdown 编写，支持 Mermaid 流程图、代码块、数学标记与智能表格，轻盈清爽，杜绝任何格式污染；
- **排版归自动化引擎**：企业标准的封面要素、密级声明、页眉版次、统一字体（中易宋体 / Times New Roman）、标题编号与边框底纹，全部由底层 `template.docx` 模板引擎在合并出稿（Build）时全自动装配注入，统一规范。

### 3. 行级审查与会议评审闭环（Review Loop）
- 每次文档变更，无论增删段落、修改字段、更动表格，在 Git 与内置改动面板（Changes Panel）中均呈现高亮精确的行级 diff；
- **评审稿自动生成**：根据变更基线，一键将改动章节导出为“修改前/修改后上下对照”的正式 Word 评审稿；
- **评审单意见回流**：评审会后填写的标准评审单表格可离线反向导入，意见自动与章节绑定，不解决不放行。

### 4. 极致稳健与 AI 生态友好
- 纯文本 Markdown 永不崩溃，秒级全局检索与正则替换；
- 原生兼容各种 AI Agent、大模型与自动化脚本，随心进行文档重构、翻译与合规审查；最终通过 Doc Tool 一键编译无损还原回标准 Word。

---

## 核心功能矩阵

### 1. 结构化 Word 导入与项目化管理
- **智能层级嗅探**：精准识别 Heading 1～6、图片、表格与正文字段，保留页面设置与页眉页脚；
- **双向往返门禁（Roundtrip Guard）**：导入时自动进行预检与试构建，确保解析与还原可逆保真；
- **单点修订维护**：以 `_revision_record.md` 为唯一维护点，末行版本号严格绑定为文档交付版本号。

### 2. 现代化桌面创作工作台（v2.3.0）
- **全局命令面板（`Ctrl+K` / `Ctrl+Shift+P`）**：无边框居中浮层，一处聚合新建/打开项目、出稿构建、全库校验、Word 逆向导入与诊断等全部操作；
- **章节秒开与快速跳转（`Ctrl+P`）**：毫秒级遍历索引全库 Markdown 章节，支持拼音与文本模糊过滤，键盘回车秒开；
- **Markdown 表格智能编辑与等宽管道对齐**：
  - 基于 Unicode East Asian Width 自适应中英文字宽对齐（汉字/全角标点算 2 宽，ASCII 算 1 宽），保留对齐指示符（`:---:`, `---:`, `:---`）；
  - 表格单元格 `Tab` / `Shift+Tab` 智能跳转选区，末行末列按 `Tab` 自动新增一行；
  - 快捷键 `Ctrl+Alt+T` 一键美化当前表格，完整接入撤销/重做栈（Undo/Redo）；
- **实时代码块语法高亮**：
  - 零外部依赖原生词法染色引擎，覆盖 Python、SQL、C/C++、Bash、JSON、YAML、HTML/XML；
  - 自动适配浅色/深色主题，支持跨行三引号文档字符串与块注释，注入行锚点双向同步定位；
- **内置安全体系**：多级自动草稿、崩溃状态恢复机制、只读工作区写锁、多窗口隔离。

### 3. 改动评审稿导出与意见闭环
- **离线评审稿导出**：自动嗅探版本基线改动章节，按条目生成修改前/修改后上下排版对照的 DOCX；
- **评审单意见回流**：离线解析公司标准评审单 Word 表格，条目号精准匹配章节并幂等回流。

### 4. 全能格式批量互转中心
无需打开项目，支持在 **工具 → 文档互转…** 中拖拽批量转换：
- **Word ↔ PDF**（高质量渲染，支持页码范围过滤）；
- **Markdown / HTML → Word**（内置专业排版样式：标题层级、边框、底纹、图片自动内嵌）；
- **Word → Markdown**（纯离线转换，产出单文件 `.md` 与关联 `assets/` 资源）；
- **XLSX ↔ CSV**、**TXT / Excel / CSV → PDF**、**RTF / ODT 导入**。

### 5. 纯离线安全 PDF 工具箱
集成 14 项常用离线 PDF 操作，无需上传网络，保障企业敏感数据安全：
- **页面组织**：合并多个 PDF、拆分、页面提取、页面逆序、删除指定页、90°/180°/270° 旋转；
- **安全加固**：AES-256 / RC4 安全加密与权限控制、密码解密移除；
- **视觉处理**：平铺/单点自定义文字水印（字号/角度/透明度/颜色）、自动页码编排；
- **优化与提取**：图像无损/有损智能重压缩、PDF 批量转高清图片（PNG/JPG）、多图合成 PDF、元数据编辑与大纲提取；
- **CLI 命令行自动化**：提供 `pdf` 子命令，支持脚本流水线调用。

---

## 快速上手

### 两种分发方式（推荐安装版）

| 分发方式 | 文件名示例 | 说明与推荐场景 |
| :--- | :--- | :--- |
| **安装版（推荐）** | `DocTool-Setup-2.3.0.exe` | 双击运行安装，默认部署到 `%LOCALAPPDATA%\DocTool`（**无需管理员权限**）。支持桌面快捷方式与开始菜单，升级自动平滑迁移配置。 |
| **免安装便携版** | `DocTool-2.3.0-portable.zip` | 解压即用。首次先双击「`安装证书.cmd`」导入企业根证书，之后双击「`启动DocTool.cmd`」启动。适合受限受管办公机。 |

> **诊断提示**：若在特殊加密环境遇到启动问题，双击安装目录或便携包根目录下的 `diagnose.cmd`，将生成的 `DocTool-diagnose.txt` 发送给维护人员。

### 核心出稿工作流（4步交付）

```text
[导入源 Word] → [章节树维护 Markdown] → [F5 校验] → [正式合并 DOCX]
```

1. **新建项目**：按 `Ctrl+N`，选择一份使用标准 `Heading 1～6` 样式的 `.docx` 模板文件，确认层级映射完成导入；
2. **章节编辑**：在左侧章节树中点击对应 `.md` 进行编写，利用 `Ctrl+Alt+T` 美化表格，利用 `Ctrl+P` 秒级切换章节；
3. **维护修订表**：出稿前在 `content/<类型>/_revision_record.md` 底部增加一行说明，**末行版本号即最终出稿的文档版本号**；
4. **一键出稿**：
   - **校验项目（F5）**：检查结构完整性、失效引用与格式门禁（无需安装 Word）；
   - **诊断构建（Ctrl+Shift+B）**：无 Word 环境下快速生成非正式试看 DOCX；
   - **正式合并**：调用本机 Word 自动刷新目录域与页码，在 `output/` 目录下生成正式受控交付物。

---

## 源码开发与打包

### 本地开发环境

```powershell
# 1. 安装核心与构建依赖
python -m pip install -r requirements.txt -r requirements-build.txt

# 2. 启动桌面主应用
python -m doc_tool.app

# 3. 运行全量自动化测试套件（35+ 测试套件）
python scripts\tests\run_tests.py
```

### 一键安装包构建（Windows）

```powershell
# 编译企业安装器（需 Inno Setup 6）
.\packaging\build.ps1

# 编译免安装便携包 ZIP
.\packaging\make_portable.ps1
```

构建产物将统一输出至 `packaging/Output/`。

---

## 项目工程结构

```text
doc-tool/
├─ doc_tool/                    # 应用核心业务逻辑
│  ├─ domain/                   # 核心领域模型（版本号、文档树、校验门禁）
│  ├─ application/              # 核心用例（Word 导入导出、Markdown 渲染、表格引擎、评审闭环）
│  ├─ adapters/                 # 外部适配器（Word COM、Pandoc、文件 IO）
│  └─ ui/                       # PySide6 现代化界面（主窗口、命令面板、多标签工作区、PDF工具箱）
├─ packaging/                   # 打包与发布工程（Inno Setup、PyInstaller spec、加固脚本）
├─ scripts/                     # 自动化脚本库（DOCX 生成与刷新、合规测试、诊断工具）
├─ docs/                        # 详细用户手册与设计决策文档
├─ openspec/                    # OpenSpec 规范化变更提案与任务追踪
└─ templates/                   # 经过净化与受控的企业级标准排版模板
```

---

## 系统运行与环境限制

- **操作系统**：Windows 10 / 11（64-bit）；
- **Word 依赖边界**：文档导入、编辑、语法高亮、校验分析、PDF 工具箱及诊断构建**均不依赖 Word**；正式合并交付物的目录与页码刷新、以及部分 Office 互转方向依赖本机 Microsoft Word；
- **受管透明加密兼容**：针对企业级透明加密系统（如亿赛通 DocGuard）进行了专项加固，所有 `.pyd` 扩展模块均采用策略免密防护与原地启动保护，防止启动假死或动态库加载阻断。
