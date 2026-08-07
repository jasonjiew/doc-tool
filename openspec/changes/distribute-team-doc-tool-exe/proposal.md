## Why

现有工具已经能够从章节 Markdown 重建并严格校验公司 Word，但首次拆分仍依赖固定文件名和迁移脚本，运行环境还要求成员自行安装 Python 与依赖，无法安全地直接交付团队。需要将它产品化为可安装的 Windows 桌面工具，让成员只通过 Release 安装包完成“导入 Word、自动拆分、迭代维护、一键合并”，同时由私有 Git 保持源码、版本和发布过程可追溯。

## What Changes

- 增加多项目工作区：每个项目独立保存原始 Word、模板、Markdown、图片、复杂表格、配置、日志和输出，不把用户数据写入安装目录。
- 增加安全的首次导入流程：允许选择任意文件名的公司需求/详细设计 DOCX，预检标题样式和包结构，在临时目录完成模板提取、正文/资源提取、章节树拆分和校验，通过后原子发布；已有项目默认拒绝覆盖。
- 增加团队桌面入口：提供新建/打开项目、导入拆分、打开 Markdown 目录、校验、合并生成 Word、打开输出目录等操作，并展示可定位的进度、错误和日志。
- 复用并改造现有构建、严格校验和 Word 刷新能力，使其接收项目配置与路径，不再依赖仓库内固定目录或固定源文件名。
- 使用 PyInstaller 的目录式应用包收集 Python、依赖和静态资源，再封装为单个 Windows 安装程序；成员无需单独安装 Python。
- 增加私有 Git 的自动发布流程：标签触发测试、Windows 打包、安装/卸载冒烟测试、哈希生成和 Release 发布。
- 应用升级和卸载不得删除或覆盖用户项目；正式发布合并仍要求本机安装 Microsoft Word，缺失时给出明确阻断提示。

## Capabilities

### New Capabilities

- `word-project-import`: 从公司 DOCX 安全创建独立文档项目，提取模板、章节 Markdown、图片和复杂表格，并在发布项目前完成结构校验。
- `desktop-document-workflow`: 通过 Windows 桌面界面管理项目、维护入口、校验及一键合并，保留公司 Word 模板体系并提供可靠日志与错误恢复。
- `installer-release-delivery`: 从私有 Git 可复现地构建、测试、签名/校验并发布团队可安装的 Windows EXE，确保安装、升级、卸载与用户项目数据隔离。

### Modified Capabilities

无。当前 OpenSpec 中尚无既有能力规格；现有脚本行为将作为新能力的实现基础和兼容基线。

## Impact

- 受影响代码：`scripts/migration/`、`scripts/build_docx.py`、`scripts/validate_docx.py`、`scripts/refresh_fields.py`、`scripts/run_pipeline.py` 需要从固定仓库路径重构为项目上下文驱动。
- 新增代码：桌面 GUI/应用服务层、项目模型与清单、导入编排器、资源定位适配、安装打包配置、版本信息、发布流水线与安装级测试。
- 新增构建依赖：PyInstaller、Windows 安装器编译工具；运行期继续捆绑 `pyyaml`、`lxml`、Pillow、pywin32。
- 外部依赖：正式 TOC、页码和 NUMPAGES 刷新需要交互式 Windows 用户环境中的 Microsoft Word；不把 Word COM 部署为无人值守服务器服务。
- 数据与安全：源码和发布流程进入公司私有 Git；真实项目文档默认不进入工具源码仓库，日志不得记录正文或敏感路径之外的文档内容。
