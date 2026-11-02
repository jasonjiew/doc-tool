# GitLab Release 发布规范与免流水线机制

## 1. 规范概述
按照项目发布规范：
**内网 GitLab (`http://192.168.0.242:8899/application/ai/doc-tool`) 的正式 Release 统一通过本地脚本手动上传与发布，不依赖、不强制要求执行 GitLab CI 流水线。**

## 2. 制定背景与原则
1. **免流水线依赖**：内网 GitLab 环境可能缺少持续在线或具备完整 PySide6/Inno Setup 打包环境的 Windows Runner。若强制绑定 GitLab CI 流水线，会导致 Release 任务长时间处于 `pending` 状态无法交付。
2. **单一可信脚本发布**：内网发布统一采用项目自带的 [`packaging/publish_release.py`](../../packaging/publish_release.py) 进行原子发布。
3. **支持外部与本地资产源**：
   - 支持从本地 `packaging/Output/` 目录直接上传构建产物（安装包 `DocTool-Setup-<version>.exe`、便携包 `DocTool-<version>-portable.zip` 及 SBOM 等）；
   - 支持通过 `--from-github` 自动拉取公网 GitHub Actions 预编译的发布资产并镜像到内网；
   - 支持纯文本与版本日志直接创建/更新 Release。

## 3. 标准发布流程

### 3.1 准备环境与凭据
- 在项目根目录放置 `.gitlab_token` 文件，或在运行终端设置环境变量：
  ```powershell
  $env:GITLAB_TOKEN = "glpat-xxxxxxxxxxxxxxxxxxxx"
  ```
- 确认当前版本号已在 [`doc_tool/domain/version.py`](../../doc_tool/domain/version.py) 完成升级（如 `v3.0.3`），并在 Git 打上对应 Tag。

### 3.2 执行手动发布
在项目根目录下执行：
```powershell
# 1. 自动从 GitHub 同步资产并发布到内网 GitLab
python packaging/publish_release.py --from-github

# 2. 或使用本地已打包产物直接发布到内网 GitLab
python packaging/publish_release.py

# 3. 或仅同步/创建 Release 说明与版本记录（无需二进制产物）
python packaging/publish_release.py --release-only
```

### 3.3 验证发布结果
访问内网 GitLab 仓库 Releases 页面核验：
- 访问地址：`http://192.168.0.242:8899/application/ai/doc-tool/-/releases`
- 确认目标版本标签（如 `v3.0.3`）已正常显示，包含完整的版本更新日志与（若上传了产物的）下载资产链接。
