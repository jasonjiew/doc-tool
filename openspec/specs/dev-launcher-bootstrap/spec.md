# dev-launcher-bootstrap 规范

## Purpose

规定「start-doc-tool.cmd」在运行时依赖 PySide6 缺失时自动引导安装的行为，保证重新下载项目后「双击 → 确认一次 → 可用」的一步到位体验；依赖已就绪时启动行为不受任何影响。

## Requirements

### Requirement: Launcher probes PySide6 and stays silent when present
启动脚本 SHALL 在启动应用前以 `python -c "from PySide6.QtWidgets import QApplication"` 探测依赖（若 `.vendor\site-packages\PySide6` 存在，SHALL 先将该目录加入 `PYTHONPATH` 再探测）。探测成功时 SHALL 直接启动应用，不显示任何安装提示。

#### Scenario: PySide6 provided by .vendor
- **WHEN** `.vendor\site-packages\PySide6` 存在且探测通过
- **THEN** 启动脚本直接运行应用，无安装提示

#### Scenario: PySide6 provided by pip
- **WHEN** `.vendor` 不存在但 PySide6 已 pip 安装、探测通过
- **THEN** 启动脚本直接运行应用，无安装提示

### Requirement: Launcher bootstraps PySide6 when missing
当 PySide6 探测失败时，启动脚本 SHALL 提示缺失并询问是否自动下载安装（约 200MB，仅首次）。用户确认后 SHALL 运行 `scripts\setup_pyside6.py`；安装成功 SHALL 重新设置 vendor 路径并继续启动应用。

#### Scenario: User confirms install
- **WHEN** 探测失败且用户确认安装
- **THEN** 启动脚本运行 `scripts\setup_pyside6.py`，成功后设置 `.vendor\site-packages` 到 `PYTHONPATH` 并启动应用

#### Scenario: User declines install
- **WHEN** 探测失败且用户拒绝安装
- **THEN** 启动脚本打印手动安装指引（`python scripts\setup_pyside6.py`），不修改任何文件并不启动应用

### Requirement: Install failure is reported with guidance
当 `scripts\setup_pyside6.py` 运行失败时，启动脚本 SHALL 打印错误与手动重试指引并以非零码退出。

#### Scenario: Automatic install fails
- **WHEN** 自动安装命令返回非零
- **THEN** 启动脚本打印错误与手动重试指引，以非零码退出，不启动应用

### Requirement: Launcher script stays ASCII-only
启动脚本 SHALL 保持纯 ASCII 字节（cmd.exe 按系统 ANSI 代码页解析批处理，非 ASCII 字节会破坏解析），新增提示与注释 MUST 使用英文。

#### Scenario: Inspect script bytes
- **WHEN** 检查「start-doc-tool.cmd」的字节内容
- **THEN** 文件内不包含任何大于 0x7F 的非 ASCII 字节
