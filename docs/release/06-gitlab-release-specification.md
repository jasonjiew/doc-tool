# GitLab Release 发布规范与免流水线机制

## 1. 规范概述
按照项目发布规范：
**内网 GitLab (`http://192.168.0.242:8899/application/ai/doc-tool`) 的正式 Release 统一通过本地脚本手动上传与发布，不依赖、不强制要求执行 GitLab CI 流水线。每个正式 Release 必须包含安装包、免安装便携版及完整的校验和与 SBOM 资产，严禁空版本发布。**

## 2. 制定背景与原则
1. **免流水线依赖**：内网 GitLab 环境可能缺少持续在线或具备完整 PySide6/Inno Setup 打包环境的 Windows Runner。若强制绑定 GitLab CI 流水线，会导致 Release 任务长时间处于 `pending` 状态无法交付。
2. **单一可信脚本发布**：内网发布统一采用项目自带的 [`packaging/publish_release.py`](../../packaging/publish_release.py) 进行原子发布。
3. **资产完整性红线**：每个正式版本 Release **必须**挂载完整的二进制分发产物与校验文件，确保内网工程师与终端用户可直接一键下载安装或解压运行。

## 3. 必须包含的发布资产清单（Release Assets）

| 资产文件名 | 类型 | 规范说明 |
| :--- | :--- | :--- |
| `DocTool-Setup-<version>.exe` | **安装包** | Windows 标准安装程序，默认安装至 `%LOCALAPPDATA%\DocTool`，无需管理员权限 |
| `DocTool-Setup-<version>.exe.sha256` | 校验和 | 安装包 SHA-256 散列值文件 |
| `DocTool-<version>-portable.zip` | **免安装便携版** | 解压即用便携包，包含 `DocTool.exe`、`doc-tool-cli.exe`、`启动DocTool.cmd`、`diagnose.cmd` |
| `DocTool-<version>-portable.zip.sha256` | 校验和 | 便携包 SHA-256 散列值文件 |
| `DocTool-<version>-sbom.txt` | 合规清单 | 依赖与组件物料清单 SBOM |
| `DocTool-<version>.cdx.json` | 机器清单 | CycloneDX 标准 SBOM JSON |
| `DocTool-<version>.spdx.json` | 机器清单 | SPDX 标准 SBOM JSON |
| `latest.json` | 升级配置 | 用于应用客户端检查更新与在线升级的元数据 |

## 4. 标准本地打包与发布流程

### 4.1 准备环境与凭据
- 在项目根目录放置 `.gitlab_token` 文件，或在运行终端设置环境变量：
  ```powershell
  $env:GITLAB_TOKEN = "glpat-xxxxxxxxxxxxxxxxxxxx"
  ```
- 确认当前版本号已在 [`doc_tool/domain/version.py`](../../doc_tool/domain/version.py) 完成升级（如 `v3.0.3`），并在 Git 打上对应 Tag。

### 4.2 本地打包资产（构建安装包与便携版）
在项目根目录下依次执行：
```powershell
# 1. 编译 PyInstaller onedir 并制作免安装便携包（生成 DocTool-<version>-portable.zip）
powershell -File build_exe.ps1 -Portable -SkipTests

# 2. 编译 Inno Setup 安装包（生成 DocTool-Setup-<version>.exe）
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss

# 3. 生成安装包 SHA-256 校验和与 SBOM
python -c "import hashlib; h = hashlib.sha256(open('packaging/Output/DocTool-Setup-3.0.3.exe', 'rb').read()).hexdigest().upper(); open('packaging/Output/DocTool-Setup-3.0.3.exe.sha256', 'w').write(f'{h}  DocTool-Setup-3.0.3.exe\n')"
python packaging\generate_sbom.py --requirements requirements.txt --requirements requirements-build.txt --cyclonedx packaging\Output\DocTool-3.0.3.cdx.json --spdx packaging\Output\DocTool-3.0.3.spdx.json
```

### 4.3 执行手动发布与上传
在项目根目录下执行：
```powershell
# 使用本地已打包产物直接发布到内网 GitLab（自动上传至 Package Registry 并注入 Release 下载链接）
python packaging/publish_release.py
```

### 4.4 验证发布结果
访问内网 GitLab 仓库 Releases 页面核验：
- 访问地址：`http://192.168.0.242:8899/application/ai/doc-tool/-/releases`
- 确认目标版本标签（如 `v3.0.3`）已正常显示，包含完整的版本更新日志，且 **“Assets” 区域必须列出安装包、免安装便携版、校验和及 SBOM 的直接下载链接**。
