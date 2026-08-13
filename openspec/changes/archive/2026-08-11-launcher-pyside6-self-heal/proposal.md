# Proposal: 启动脚本 PySide6 自愈引导

## Why

`.vendor/` 与虚拟环境都不进仓库，PySide6 靠本地一次性安装。重新 clone/下载项目后 PySide6 必然缺失，双击「启动康尚文档工具.cmd」只会在 `python -m doc_tool.app` 处报「当前环境缺少 PySide6」并退出——用户得自己记得去跑 `python scripts/setup_pyside6.py`（此机器上 pip 又被 DLP 拦截）。README 虽写了手工步骤，但没人会主动去读，问题每次重新下载都会复发。

## What Changes

- 「启动康尚文档工具.cmd」启动前用 `python -c "import PySide6"` 探测依赖：
  - 探测通过 → 照常启动，无任何额外打扰（幂等）。
  - 探测失败 → 提示 PySide6 缺失，询问是否自动下载安装（约 200MB，仅首次）。
    - 确认 → 运行 `python scripts\setup_pyside6.py`，成功后加入 vendor 路径并继续启动。
    - 安装失败 → 打印错误与手动重试指引，退出。
    - 拒绝 → 打印「下次运行 python scripts\setup_pyside6.py」指引，退出。
- 脚本文件保持纯 ASCII（cmd.exe 用 ANSI 代码页解析批处理，中文会破坏解析）。
- README 增补一行「首次运行会自动引导安装 PySide6」说明。
- **BREAKING**: 无。既有正常启动路径与已有错误提示保留。

## Capabilities

### New Capabilities
- `dev-launcher-bootstrap`: 启动脚本 `.cmd` 在 PySide6 缺失时自动引导安装并继续启动，保证「重新下载项目 → 双击 → 确认一次 → 可用」的一步到位体验。

### Modified Capabilities
<!-- 无既有规范的需求发生变化 -->

## Impact

- 唯一改动文件：`启动康尚文档工具.cmd`（+ README 说明）。
- 无 Python 代码改动；复用现有 `scripts/setup_pyside6.py`（不变）。
- 依赖：运行 `setup_pyside6.py` 需要网络下载 wheel（约 200MB，仅缺失时一次）。
- 不影响打包产物（PyInstaller onedir 自带依赖，最终用户无感）。
