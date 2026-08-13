# Contributing to Doc Tool

欢迎贡献！Doc Tool 是一个通用大型 Word 文档工作台，把大型 Word 文档转换为
可维护的 Markdown 章节项目，并可靠重建为 Word。

## 环境搭建

- 需要 Windows 与 Python 3.13。
- 安装依赖：
  ```powershell
  python -m pip install -r requirements.txt -r requirements-build.txt
  ```
- 若受终端安全软件（DLP）限制、pip 无法完成 PySide6 原子安装，运行
  `python scripts\setup_pyside6.py` 把 PySide6 安装到 `.vendor\site-packages`。
- 运行桌面应用：双击 `start-doc-tool.cmd` 或 `python -m doc_tool.app`。

## 运行测试

```powershell
python scripts\tests\run_tests.py
```

- 测试覆盖领域、导入、构建、校验、GUI 服务、打包与发布门禁。
- 提交前请确保全量测试通过（`run_tests.py` 退出码 0）。
- 部分验收需要 Microsoft Word（正式合并/刷新）；无 Word 时用「诊断构建」。

## 分支与提交

- 功能开发请在独立分支进行，合并前通过代码评审。
- 提交信息使用中文/英文均可，但必须描述变更动机与影响范围。
- 保持每次提交聚焦单一逻辑变更，便于回溯与回滚。

## 贡献内容

- **Bug 修复与功能**：先开 Issue 讨论设计，再提 Pull Request。
- **测试**：欢迎补充回归用例；新增功能必须带测试。
- **文档**：README、贡献指南、OpenSpec 规范等。

## 版权贡献约定

- 一旦本仓库确定主许可证（见 LICENSE），你的贡献将以该许可证授权给项目。
- 若贡献包含第三方代码/依赖，须在 PR 中说明其许可证与来源。

## 禁止提交的敏感数据

**严禁** 把以下内容提交到仓库：

- 真实客户、公司、内部系统代号、设备型号或内部文档编号。
- 任何真实业务 Word/Markdown/截图/表格样本（示例必须使用虚构内容）。
- 密钥、证书、令牌、口令或私有网络地址（RFC1918）。
- 内部域名、内网路径或个人信息。

提交前可用发布门禁自查：

```powershell
python packaging/export_public_source.py --output $env:TEMP\pub-export --scan
```

## 行为规范

参与本项目即表示同意遵循 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
