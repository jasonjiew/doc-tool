# 内部版基线测试结果

> 任务 1.3：运行并保存当前全量测试基线。冻结应用冒烟与旧项目构建基线依赖
> Word COM / PyInstaller 发布环境，由 CI / Release 流水线在干净 Runner 执行
> （见任务 9.4）。

## 全量单元/集成测试

- 记录日期：2026-08-13
- 基线提交：`9600b3013fde`（通用化工作开始前）
- 运行器：`scripts/tests/run_tests.py`（默认 23 个测试文件）
- 运行环境：Windows 11 Pro for Workstations，Python 3.13.13，`PYTHONPATH` 含 `.vendor/site-packages`
- **结果：23 个测试文件，0 失败，耗时约 81s**

测试文件清单（全部通过）：
`test_docx_common`、`test_ooxml_security`、`test_validator_negative`、
`test_iteration_scenarios`、`test_project_model`、`test_import_preflight`、
`test_fidelity`、`test_project_build`、`test_import_project`、`test_roundtrip`、
`test_style_mapping`、`test_authoring_services`、`test_issues`、
`test_cli_machine`、`test_quality_gates`、`test_quality_traceability`、
`test_gui_services`、`test_content_operations`、`test_safety_recovery`、
`test_lock_log_cancel`、`test_word_release`、`test_packaging`、`test_installer`。

## 尚未在本环境执行的基线项

| 项 | 执行位置 | 说明 |
| --- | --- | --- |
| 冻结应用冒烟 | 干净 Windows Runner（CI） | 需先 PyInstaller 构建 `dist/DocTool/` |
| 旧 `requirement` 项目构建 | 安装 Word 的交互式会话 | Word COM 刷新与正式构建 |
| 旧 `design` 项目构建 | 安装 Word 的交互式会话 | 同上 |
| 安装/卸载冒烟 | 干净 Windows Runner | `test_installer_smoke.ps1` |
