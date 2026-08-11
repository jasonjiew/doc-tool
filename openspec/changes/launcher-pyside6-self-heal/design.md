# Design: 启动脚本 PySide6 自愈引导

## Context

「启动康尚文档工具.cmd」当前逻辑：检测 python → 若 `.vendor\site-packages\PySide6` 存在则加入 `PYTHONPATH` → `python -m doc_tool.app`。PySide6 不进仓库（`.vendor/`、虚拟环境均被 gitignore），全新 clone 后必缺；此开发机上 pip 又被亿赛通 DLP 拦截原子重命名（`WinError 17`），唯一可行安装路径是现有 `scripts/setup_pyside6.py`（下载 wheel + zipfile 解压到 `.vendor/site-packages`）。启动脚本只报错、不引导，导致每次重新下载都复发。

约束：脚本必须保持纯 ASCII（cmd.exe 按系统 ANSI 代码页解析批处理，非 ASCII 字节会破坏解析，现有注释已注明）。

## Goals / Non-Goals

**Goals:**
- 全新下载后「双击启动脚本 → 确认一次 → 正常启动」，无需记得任何手工步骤。
- 依赖已就绪时（无论 pip 装的还是 `.vendor`）启动行为完全不变，零打扰、幂等。
- 复用 `scripts/setup_pyside6.py`，不改任何 Python 代码。
- 保持纯 ASCII、保持既有退出码与错误提示风格。

**Non-Goals:**
- 修复 pip/DLP 本身。
- 把 PySide6 提交进仓库（体积与二进制入库问题，明确排除）。
- 改动运行时应用、打包/安装器或最终用户体验。

## Decisions

### D1. 探测方式：`python -c "import PySide6"` 而非仅查目录
- **选择**：先按现状设置 vendor `PYTHONPATH`，再 `python -c "from PySide6.QtWidgets import QApplication" >nul 2>&1` 探测；`errorlevel` 非 0 才进入引导分支。
- **理由**：只看 `.vendor` 目录会误判「pip 已装但无 vendor」的机器（非 DLP 机器会被不必要地打扰）。且 `import PySide6` 过弱——pip 部分安装残留可让顶层包可导入而 `QtWidgets` 缺失；探测镜像应用首个真实依赖 `QtWidgets.QApplication`，探不到即真缺 GUI 库。
- **备选**：仅 `if exist ".vendor\site-packages\PySide6"`（误判 pip 已装的机器）、`import PySide6`（pip 半装时误判可启动）——均否决。

### D2. 引导交互：`set /p` 确认，默认拒绝
- **选择**：提示 `PySide6 not found. Install now (~200 MB, one-time)? [Y/N]`，输入 `Y/y` 才安装；回车或其它输入均视为拒绝，打印手动指引退出。
- **理由**：200MB 下载应当显式确认；默认拒绝避免误触。指引文案沿用脚本既有的 `[ERROR]` 英文风格。
- **备选**：静默自动下载 —— 免打扰但下载体积大且可能超时，否决。

### D3. 安装命令：直接复用 `scripts\setup_pyside6.py`
- **选择**：确认后 `python scripts\setup_pyside6.py`，失败（`errorlevel` 非 0）则打印错误与手动重试指引退出。
- **理由**：该脚本已验证 DLP 环境可用、幂等、自带 `verify()` 自检；不改任何 Python 代码。
- **备选**：在批处理里复刻下载/解压逻辑 —— 重复且难维护，否决。

### D4. 安装成功后重新设置 vendor 路径再启动
- **选择**：安装成功后重新执行「若 `.vendor\site-packages\PySide6` 存在则加入 `PYTHONPATH`」，再进入原有 `python -m doc_tool.app` 启动路径（复用 `:launch` 标签，后续错误处理不变）。
- **理由**：首次探测时 `.vendor` 还不存在，`PYTHONPATH` 未含 vendor 路径；安装后才生成，须重设，否则启动仍会失败。

### D5. 保持纯 ASCII
- 所有新增提示/注释用英文 ASCII；中文说明只放 README。

## Risks / Trade-offs

- **下载体积与网络**：首次缺失时需下载约 200MB → 仅在探测真缺失时触发，提示中标注体积；下载失败走 D3 错误分支给出手动指引，不阻塞后续手动重试。
- **误判「已装」**：理论上若 `import` 可通但运行时缺共享库，启动仍可能失败 → 该情况走既有 `:startup_failed` 提示，属既有行为，不在本变更范围。
- **英文提示**：中文用户看到英文提示 → 与脚本现状一致，README 提供中文说明。
- **非 DLP 机器**：pip 已装时探测通过，完全不受影响；未装时走 `setup_pyside6.py` 也兼容（仅多一次下载），不会更差。

## Migration Plan

- 单文件改动，无数据/配置迁移。回滚 = `git revert` 该提交或直接还原 `.cmd`。
- 验证步骤：
  1. 正常路径：现有 `.vendor` 存在，双击/运行脚本应直接启动，无任何提示。
  2. 模拟缺失：临时改名 `.vendor` → 运行脚本 → 确认出现提示；输入 `N` → 打印指引并退出；输入 `Y` → 自动安装并启动。
  3. 恢复 `.vendor`，确认 1 仍成立。
