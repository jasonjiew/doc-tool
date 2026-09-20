# Doc Tool 文档工程化工作台

> **Docs-as-Code for Enterprise Documents**  
> 把大型 Word 文档工程化拆解为可版本追踪、可多人协同、可严谨审查的 Markdown 章节树，并在出稿时一键可靠重建为符合企业规范的正式 DOCX 交付物。

[![Version](https://img.shields.io/badge/version-2.5.1-blue.svg)](https://github.com/wangjie0721666-web/doc-tool/releases/tag/v2.5.1)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

- **当前版本**：`v2.5.1`（企业安装版 + 免安装便携版）
- **代码仓库**：<https://github.com/wangjie0721666-web/doc-tool>
- **发布下载**：<https://github.com/wangjie0721666-web/doc-tool/releases>
- **详细指南**：[docs/使用说明.md](docs/使用说明.md)

---

## 为什么需要 Doc Tool？（核心痛点与解决对策）

> **一句话定调**：Word 是优秀的“受控交付格式”，却是极差的“协同编辑工具”。**交付必须是合规 Word，但编写绝不能直接用 Word。**

### 传统大型 Word 痛点 vs Doc Tool 解决方案

| 痛点维度 | 传统 Word 协作噩梦 | Doc Tool 破局解法（Docs-as-Code） |
| :--- | :--- | :--- |
| **版本控制** | `.docx` 是二进制黑盒，Git 看不到哪行被改，提交全凭猜，无法开展代码级审查（PR/MR）。 | **行级 Diff**：文本化存储，Git 精确追踪每行文字与表格的变更，审查一清二楚。 |
| **多人协作** | 多人改同一文档只能微信来回传文件，最后人工肉眼合并，极易覆盖或漏改（Merge Hell）。 | **章节解耦**：张三改第 2 章，李四改第 3 章，在各自 `.md` 提交，Git 秒级自动合并零冲突。 |
| **格式排版** | 随意粘贴即带入样式垃圾；字体、行距忽大忽小，工程师 40% 时间浪费在手工调格式上。 | **内容样式分离**：平时只写纯 Markdown 内容；封面/页眉/宋体/样式由底模在出稿时全自动装配注入。 |
| **稳定性能** | 插入几十张高清图后，动辄几十兆的 Word 极易卡顿崩溃，遭遇断电甚至损坏整个文件。 | **轻快永不损毁**：纯文本秒开、零内存负担，毫秒级全库检索，多级自动草稿与锁机制护航。 |
| **AI 赋能** | 大语言模型极难理解庞大复杂的 Word 嵌套 XML，无法借助现代 AI 提升文档生产力。 | **天然 AI 友好**：Markdown 是大模型最擅长的结构化文本，无缝衔接 AI 润色审查，再编译回 Word。 |

---

## 为什么要把 Word 打散成多个 Markdown 文件？

核心思想就是 **“分而治之，各司其职”**：

```mermaid
graph LR
    subgraph Input ["输入源"]
        Word[大型受控 Word 文档]
    end

    subgraph Decompose ["拆解：关注点分离"]
        Tree["章节 Markdown 树\n(各自编写，并发零冲突)"]
        Tpl["企业排版底模\n(统一格式，严禁污染)"]
        Rev["单点修订记录\n(_revision_record.md)"]
    end

    subgraph Workflow ["Docs-as-Code 日常协同"]
        Git["Git 行级版本追踪 & PR 审查"]
        Edit["秒级命令流编辑 / 智能表格 / 代码高亮"]
        Review["离线差分评审稿导出 & 意见闭环"]
    end

    subgraph Output ["自动化重建交付"]
        Gen["一键自动化编译 + 域刷新"]
        FinalDOCX["高品质合规 DOCX 交付物"]
    end

    Word --> Decompose
    Decompose --> Workflow
    Workflow --> Output
```

1. **分而治之（解决协作冲突）**：将动辄几十万字的大文档按标题层级拆成 `content/第3章 系统设计/3.1 架构.md`，团队成员只维护各自的文件，彻底告别“传文件合并”的原始协作方式。
2. **各司其职（解决排版错乱）**：工程师 **99% 的精力只需专注写 Markdown 正文内容**；封面的文档编号与版本、受控页眉版次、中英文字体、段落间距全部交由出稿管线自动化灌装，彻底杜绝样式漂移。
3. **闭环审查（解决会议评审）**：工具自动嗅探改动章节，一键导出“修改前/修改后上下排版对照”的正式 Word 会议评审稿；评审会后标准评审单可离线一键导入，意见自动与章节绑定闭环。
4. **两全其美（兼顾效率与规范）**：**过程享受 Markdown 的高效轻盈与 Git 版本红利，结果保住企业 Word 交付物的专业严谨**。

---

## 核心功能矩阵

### 1. 结构化 Word 导入与项目化管理
- **智能层级嗅探**：精准识别 Heading 1～6、图片、表格与正文字段，保留页面设置与页眉页脚；
- **双向往返门禁（Roundtrip Guard）**：导入时自动进行预检与试构建，确保解析与还原可逆保真；
- **单点修订维护**：以 `_revision_record.md` 为唯一维护点，末行版本号严格绑定为文档交付版本号。

### 2. 现代化桌面创作工作台（v2.5.1）
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
| **安装版（推荐）** | `DocTool-Setup-2.5.1.exe` | 双击运行安装，默认部署到 `%LOCALAPPDATA%\DocTool`（**无需管理员权限**）。支持桌面快捷方式与开始菜单，升级自动平滑迁移配置。 |
| **免安装便携版** | `DocTool-2.5.1-portable.zip` | 解压即用。首次先双击「`安装证书.cmd`」导入企业根证书，之后双击「`启动DocTool.cmd`」启动。适合受限受管办公机。 |

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
