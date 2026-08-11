# Tasks: 启动脚本 PySide6 自愈引导

## 1. 修改启动脚本

- [ ] 1.1 在既有 python 检测与 vendor 路径设置之后，加入 `python -c "import PySide6"` 探测分支（沿用 `:launch` 标签，`errorlevel` 非 0 才进入引导）
- [ ] 1.2 探测失败时打印缺失提示并 `set /p` 询问是否安装（默认拒绝；非 `Y/y` 视为拒绝）
- [ ] 1.3 确认后运行 `python scripts\setup_pyside6.py`；失败（`errorlevel` 非 0）则打印错误与手动重试指引并以非零退出
- [ ] 1.4 安装成功后重新执行 vendor 路径设置（`if exist ".vendor\site-packages\PySide6"`），再进入 `:launch` 启动
- [ ] 1.5 拒绝时打印手动指引（`python scripts\setup_pyside6.py`）并不启动

## 2. 验证

- [ ] 2.1 正常路径：`.vendor` 存在时运行脚本应直接启动、无任何安装提示
- [ ] 2.2 模拟缺失 + 拒绝：临时改名 `.vendor` 后运行脚本，输入 `N` 应打印指引并退出、不启动
- [ ] 2.3 模拟缺失 + 确认：同一场景输入 `Y` 应自动安装并启动
- [ ] 2.4 恢复 `.vendor`，回归 2.1 正常路径不受影响
- [ ] 2.5 字节检查：`启动康尚文档工具.cmd` 不含任何大于 0x7F 的非 ASCII 字节

## 3. 文档与提交

- [ ] 3.1 README 增补「首次运行会自动引导安装 PySide6」说明
- [ ] 3.2 提交变更（含 openspec 变更目录），commit message 遵循既有 `fix(launcher):` 前缀
