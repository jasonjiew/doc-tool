# 发布前自动化门禁结果归档

> 任务 11.4：运行全量自动测试、OpenSpec 验证、依赖审计、泄漏扫描、冻结与安装级
> 冒烟测试并归档报告。

- 归档日期：2026-08-13
- 分支：`feat/generalize-for-open-source`
- 运行环境：Windows 11 Pro for Workstations，Python 3.13.13

## 全量自动测试

- 运行器：`scripts/tests/run_tests.py`（24 个测试文件，含新增的 brand /
  settings-migration / migration / public-export 测试）。
- 结果：**全部通过（退出码 0）**。首次运行存在一次锁并发测试超时（本机 DLP
  环境下多进程文件锁偶发慢，单测重跑通过，非代码回归）；干净重跑全绿。

## OpenSpec 验证

- `openspec validate generalize-for-open-source` → **通过**
- 进度：54/61 任务完成；剩余为权利人/环境依赖项（见下）。

## 依赖审计

- `packaging/audit_dependencies.py` 校验运行与构建依赖版本；依赖 `pip-audit`
  （由 CI 安装 `pip-audit==2.9.0`，本开发环境未安装，审计在干净 Runner 执行）。
- 依赖清单：`requirements.txt`、`requirements-build.txt`。
- 结构化 SBOM：CycloneDX（`sbom.cdx.json`）与 SPDX（`sbom.spdx.json`），
  由 `packaging/generate_sbom.py` 生成。
- 许可证说明：`THIRD_PARTY_LICENSES.txt`（含 PySide6/Qt 动态链接说明）。

## 泄漏扫描（公共源码 + OOXML 内容）

- 净化导出：`packaging/export_public_source.py`（排除公司目录/旧入口/AI dot-dir）。
- 扫描：`packaging/scan_leaks.py --source-root <导出>`（品牌/编号/产品/域名/
  RFC1918/凭据/OOXML 内部内容/路径）。
- 结果：**通过** —— 未发现生产文档/品牌/内网/凭据泄漏；导出无被排除/隐藏/未跟踪文件。

## 发布授权门禁

- `packaging/release_gate.py --public` → **正确阻断**（著作权/品牌/许可证等
  6 项未决决策，仅允许内部测试产物）。

## 冻结与安装级冒烟（需发布环境）

- 冻结应用冒烟：`scripts/tests/test_frozen_smoke.py`（需先 PyInstaller 构建）。
- 安装/卸载/升级冒烟：`scripts/tests/test_installer_smoke.ps1`（需 Inno Setup 与
  干净 Windows Runner）。
- 真实 Word 验收：任务 11.5（需交互式 Word 会话）。

## 归档位置

- 门禁脚本：`packaging/`（`export_public_source.py`、`scan_leaks.py`、
  `release_gate.py`、`generate_release_notes.py`、`generate_sbom.py`）。
- 发布决策/检查单：`docs/release/`。

## 后续更新

- 2026-08-14：6 项未决发布决策已由权利人（wangjie）确认并转为 DECIDED
  （`docs/release/02-release-decisions.md`）；`LICENSE`（MIT）与 `SECURITY.md`
  私密报告邮箱已补齐；`release_gate.py --public` 改为放行，正式公共 Release
  门禁通过。
