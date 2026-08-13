# 内部版发布基线（可回滚基线）

> 任务 1.1：记录当前内部版应用版本、项目 schema、安装器 AppId、可执行文件、
> 安装目录和设置命名空间，形成可回滚基线。
>
> 本文件在通用化（generalize-for-open-source）工作开始前冻结内部版现状。
> 任何后续改动都必须保证：旧项目可读、旧设置可迁移、旧安装不被公共版覆盖。

- 记录日期：2026-08-13
- 基线提交：`9600b3013fde`（`feat/ui-interaction-optimization` 分支）
- 运行环境：Windows 11 Pro for Workstations（10.0.22631），Python 3.13.13，
  PySide6 由 `.vendor/site-packages` 提供

## 1. 应用身份

| 项 | 当前内部版值 | 来源 |
| --- | --- | --- |
| 应用语义版本 | `1.0.0` | `doc_tool/domain/version.py` `APP_VERSION` |
| 显示名（中文） | `康尚文档工具` | `doc_tool/app.py` `setApplicationDisplayName` |
| 组织设置键 | `Konsung` | `doc_tool/app.py` `setOrganizationName("Konsung")` |
| QSettings 命名空间 | 组织 `Konsung` + 应用 `康尚文档工具` | 由 `QApplication` 应用名/组织名推导 |
| 项目模式版本（schema） | `1` | `doc_tool/domain/version.py` `PROJECT_SCHEMA_VERSION` |
| 可读写 schema 集合 | `(1,)` | `SUPPORTED_PROJECT_SCHEMA_VERSIONS` |

## 2. 安装与产物身份

| 项 | 当前内部版值 | 来源 |
| --- | --- | --- |
| GUI 可执行文件 | `KonsungDocTool.exe` | `packaging/doc_tool.spec` |
| CLI 可执行文件 | `doc-tool-cli.exe` | `packaging/doc_tool.spec` |
| onedir 目录名 | `dist/KonsungDocTool/` | `packaging/doc_tool.spec` `COLLECT name` |
| 安装目录 | `%LOCALAPPDATA%\Konsung\DocTool` | `packaging/installer.iss` |
| 安装器输出名 | `KonsungDocTool-Setup-<version>.exe` | `packaging/installer.iss` |
| 稳定 AppId | `F6D0000F-13F0-50D9-8743-5B42D68FF071` | `packaging/installer.iss` `#define MyAppId` |
| Publisher | `康尚医疗` | `packaging/installer.iss` |
| App URL | `http://www.konsung.com` | `packaging/installer.iss` |
| 安装器 AppName | `康尚文档工具` | `packaging/installer.iss` |

## 3. 启动与开发入口

| 项 | 当前内部版值 | 来源 |
| --- | --- | --- |
| 根启动脚本 | `启动康尚文档工具.cmd`（含非 ASCII 字节） | 仓库根 |
| 仓库内置生成入口 | `全部生成.cmd` / `生成需求说明书.cmd` / `生成详细设计说明书.cmd` | 仓库根 |
| 根 CLI 入口 | `doc_tool_cli.py` | 仓库根 |
| CLI 程序名 | `doc-tool`，描述 `康尚文档工具：将大型 Word 拆分为 Markdown 维护并可靠合并。` | `doc_tool/cli.py` |

## 4. 项目领域模型

| 项 | 当前内部版值 | 来源 |
| --- | --- | --- |
| 可创建文档类型 | `general` / `requirement` / `design`（CLI `--document-type` 与向导单选） | `doc_tool/cli.py`、`doc_tool/ui/wizard.py` |
| 清单文档类型集合 | `("general", "requirement", "design")` | `doc_tool/domain/manifest.py` `DOCUMENT_TYPES` |
| 内容根默认布局 | `content/<documentType>` | `ProjectManifest.relative_content_root` |
| 资源根默认布局 | `assets/<documentType>` | `ProjectManifest.relative_asset_root` |

## 5. 打包输入（内部版现状）

当前 PyInstaller spec 会隐式收集以下仓库根目录，**这是公共发行必须移除的行为**：

- `scripts/`（含 `scripts/migration/`）— 内核脚本
- `templates/` — 公司 Word 模板（公司材料）
- `config/` — 文档配置（公司材料）
- `THIRD_PARTY_LICENSES.txt`
- `packaging/app.ico`
- `doc_tool/resources/default_project.yml`

## 6. 数据与历史（后续通用化不得触碰）

- 仓库根 `templates/`、`config/`、`content/`、`assets/`、`analysis/`、
  `migration/legacy/` 下的材料属于内部/公司数据，公共源码导出必须排除。
- Git 历史中可能残留内部文档编号、品牌与内网信息；历史清理属独立审批事项。

## 7. 回滚说明

- 公共版使用**新的** AppId、安装目录与可执行文件名，不覆盖内部安装。
- 旧 QSettings 命名空间**只读迁移**，不删除旧值。
- 旧项目**不被原地改写**；迁移必须复制或先备份。
- 代码回滚后，内部版仍可读取未被改写的旧项目与设置。
