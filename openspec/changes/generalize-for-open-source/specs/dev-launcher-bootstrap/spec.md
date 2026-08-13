## MODIFIED Requirements

### Requirement: Launcher probes PySide6 and stays silent when present
中性名称的公共启动脚本 SHALL 在启动应用前以 `python -c "from PySide6.QtWidgets import QApplication"` 探测依赖（若 `.vendor\site-packages\PySide6` 存在，SHALL 先将该目录加入 `PYTHONPATH` 再探测）。探测成功时 SHALL 直接启动公共应用，不显示安装提示或公司品牌。

#### Scenario: PySide6 provided by .vendor
- **WHEN** `.vendor\site-packages\PySide6` 存在且探测通过
- **THEN** 公共启动脚本直接运行应用，无安装提示

#### Scenario: PySide6 provided by pip
- **WHEN** `.vendor` 不存在但 PySide6 已 pip 安装、探测通过
- **THEN** 公共启动脚本直接运行应用，无安装提示

### Requirement: Launcher bootstraps PySide6 when missing
当 PySide6 探测失败时，公共启动脚本 SHALL 使用中性提示说明缺失并询问是否自动下载安装。用户确认后 SHALL 运行 `scripts\setup_pyside6.py`；安装成功 SHALL 重新设置 vendor 路径并继续启动应用。

#### Scenario: User confirms install
- **WHEN** 探测失败且用户确认安装
- **THEN** 启动脚本运行 `scripts\setup_pyside6.py`，成功后设置 `.vendor\site-packages` 到 `PYTHONPATH` 并启动应用

#### Scenario: User declines install
- **WHEN** 探测失败且用户拒绝安装
- **THEN** 启动脚本打印中性的手动安装指引，不修改任何文件并不启动应用

### Requirement: Install failure is reported with guidance
当 `scripts\setup_pyside6.py` 运行失败时，公共启动脚本 SHALL 打印不含公司品牌的错误与手动重试指引并以非零码退出。

#### Scenario: Automatic install fails
- **WHEN** 自动安装命令返回非零
- **THEN** 启动脚本打印错误与手动重试指引，以非零码退出，不启动应用

### Requirement: Launcher script stays ASCII-only
公共启动脚本 SHALL 使用中性文件名并保持纯 ASCII 字节，新增提示与注释 MUST 使用英文；旧公司品牌启动脚本 MUST NOT 进入公共发行清单。

#### Scenario: Inspect script bytes and name
- **WHEN** 发布检查公共启动脚本的文件名和字节内容
- **THEN** 文件名不含公司品牌，文件内不包含大于 0x7F 的非 ASCII 字节，且旧品牌脚本不在发布产物中

