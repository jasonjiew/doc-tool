# -*- coding: utf-8 -*-
"""打包与资源定位测试。

任务 8.2：验证 resource_root() 在开发态与冻结态（PyInstaller）资源定位一致。
任务 8.7：验证旧应用拒写更高模式项目（can_write_schema）。

覆盖范围：
- resource_root() 开发态返回 doc_tool/resources/ 目录
- resource_root() 冻结态（模拟 sys._MEIPASS）返回 _MEIPASS/doc_tool/resources
- resource_path() 正确拼接子路径
- 默认配置文件 default_project.yml 在开发态可访问
- can_read_schema / can_write_schema 的向前/向后兼容语义
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ResourceRootTests(unittest.TestCase):
    """任务 8.2：resource_root() 开发态与冻结态定位。"""

    def test_dev_mode_returns_resources_dir(self):
        """开发态：resource_root() 返回 doc_tool/resources/ 目录。"""
        from doc_tool.resources import resource_root

        root = resource_root()
        self.assertTrue(os.path.isdir(root))
        # 必须包含 default_project.yml
        self.assertTrue(os.path.isfile(os.path.join(root, "default_project.yml")))

    def test_dev_mode_resource_path(self):
        """resource_path() 正确拼接子路径。"""
        from doc_tool.resources import resource_path

        p = resource_path("default_project.yml")
        self.assertTrue(os.path.isfile(p))

    def test_frozen_mode_returns_meipass_resources(self):
        """冻结态：模拟 sys._MEIPASS，resource_root() 返回 _MEIPASS/doc_tool/resources。"""
        from doc_tool.resources import resource_root

        with tempfile.TemporaryDirectory(prefix="doc-meipass-") as tmp:
            # 模拟 PyInstaller 冻结环境
            fake_resources = os.path.join(tmp, "doc_tool", "resources")
            os.makedirs(fake_resources)
            # 放入一个标记文件
            marker = os.path.join(fake_resources, "default_project.yml")
            with open(marker, "w", encoding="utf-8") as f:
                f.write("# frozen marker")

            with patch.object(sys, "_MEIPASS", tmp, create=True):
                root = resource_root()
                self.assertEqual(os.path.normpath(root), os.path.normpath(fake_resources))
                self.assertTrue(os.path.isfile(os.path.join(root, "default_project.yml")))

    def test_frozen_mode_resource_path(self):
        """冻结态：resource_path() 在 _MEIPASS 下定位资源。"""
        from doc_tool.resources import resource_path

        with tempfile.TemporaryDirectory(prefix="doc-meipass-") as tmp:
            fake_resources = os.path.join(tmp, "doc_tool", "resources")
            os.makedirs(fake_resources)
            marker = os.path.join(fake_resources, "test.yml")
            with open(marker, "w", encoding="utf-8") as f:
                f.write("# test")

            with patch.object(sys, "_MEIPASS", tmp, create=True):
                p = resource_path("test.yml")
                self.assertTrue(os.path.isfile(p))

    def test_default_project_yml_loadable(self):
        """默认项目清单在开发态可被 yaml 加载。"""
        import yaml

        from doc_tool.resources import resource_path

        p = resource_path("default_project.yml")
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)
        self.assertIn("schemaVersion", data)
        self.assertEqual(data["schemaVersion"], 1)


class SchemaCompatibilityTests(unittest.TestCase):
    """任务 8.7：旧应用拒写更高模式项目。"""

    def test_can_write_current_schema(self):
        """当前应用可写当前模式版本。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_write_schema

        self.assertTrue(can_write_schema(PROJECT_SCHEMA_VERSION))

    def test_reject_write_higher_schema(self):
        """旧应用拒绝写入更高模式版本（避免破坏性降级）。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_write_schema

        future = PROJECT_SCHEMA_VERSION + 1
        self.assertFalse(can_write_schema(future))

    def test_can_read_higher_schema(self):
        """当前应用可只读打开更高模式版本（向前兼容展示）。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_read_schema

        future = PROJECT_SCHEMA_VERSION + 1
        self.assertTrue(can_read_schema(future))

    def test_reject_read_unknown_lower_schema(self):
        """未知的历史低版本不可读（无降级迁移）。"""
        from doc_tool.domain.version import can_read_schema

        # 假设的 v0（不存在于 SUPPORTED_PROJECT_SCHEMA_VERSIONS）
        self.assertFalse(can_read_schema(0))


class PackageAllowlistTests(unittest.TestCase):
    def test_strict_allowlist_rejects_unknown_file(self):
        import importlib.util

        module_path = Path(REPO_ROOT) / "packaging" / "scan_leaks.py"
        spec = importlib.util.spec_from_file_location("doc_tool_scan_leaks", module_path)
        scan_leaks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scan_leaks)

        with tempfile.TemporaryDirectory(prefix="doc-allowlist-") as tmp:
            root = Path(tmp)
            (root / "DocTool.exe").write_bytes(b"exe")
            (root / "customer-data.txt").write_text("secret", encoding="utf-8")
            leaks = scan_leaks.scan_allowlist(root)
            self.assertTrue(any("customer-data.txt" in item for item in leaks))
            self.assertFalse(any("DocTool.exe" in item for item in leaks))


class ReleasePipelineTests(unittest.TestCase):
    def test_hash_is_generated_after_all_signing_steps(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        self.assertGreater(
            package_block.rfind("Get-FileHash"),
            package_block.rfind("signtool.Source sign"),
        )
        self.assertIn("signtool.Source verify", package_block)

    def test_release_gate_blocks_public_until_decisions_resolved(self):
        """任务 9.3：未决发布决策阻断公共正式发布，允许内部测试产物。

        用临时决策表驱动门禁机制，避免随真实决策表进入已决状态后本测试失效。
        """
        import importlib.util

        module_path = Path(REPO_ROOT) / "packaging" / "release_gate.py"
        spec = importlib.util.spec_from_file_location("doc_tool_release_gate", module_path)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)

        with tempfile.TemporaryDirectory(prefix="doc-gate-") as tmp:
            decisions = Path(tmp) / "decisions.md"
            decisions.write_text(
                "| 决策项 | 占位值 | 责任人 | 状态 | 备注 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 品牌/许可证 | — | 权利人 | UNRESOLVED | 未定 |\n",
                encoding="utf-8",
            )
            old_decisions = gate.DECISIONS_FILE
            old_checklist = gate.CHECKLIST_FILE
            gate.DECISIONS_FILE = decisions
            gate.CHECKLIST_FILE = Path(tmp) / "absent-checklist.md"
            try:
                blockers = gate.check_public_gate()
                self.assertTrue(any("品牌/许可证" in b for b in blockers))
                # 未决决策应同时出现在 unresolved_items 中
                self.assertEqual(
                    gate.unresolved_items(decisions), ["品牌/许可证"]
                )
            finally:
                gate.DECISIONS_FILE = old_decisions
                gate.CHECKLIST_FILE = old_checklist

    def test_public_source_export_wired_into_ci(self):
        """任务 9.4：净化源码导出+扫描已接入公共 CI。"""
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertIn("export_public_source.py", ci)
        self.assertIn("release_gate.py --public", ci)

    def test_frozen_build_installs_runtime_and_build_requirements(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        build_block = ci[ci.index("build-onedir:"):ci.index("package-installer:")]
        self.assertIn("-r requirements.txt -r requirements-build.txt", build_block)

    def test_install_level_smoke_runs_before_installer_signing(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        smoke_pos = package_block.index("test_installer_smoke.ps1")
        installer_sign_pos = package_block.index(
            "$signtool.Source sign", package_block.index('$exe = "packaging')
        )
        self.assertLess(smoke_pos, installer_sign_pos)
        self.assertTrue(
            (Path(REPO_ROOT) / "scripts" / "tests" / "test_installer_smoke.ps1").is_file()
        )

    def test_release_requires_clean_tree_and_uses_generated_notes(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertIn("git status --porcelain --untracked-files=all", ci)
        self.assertIn('description: "packaging/Output/release-notes.md"', ci)
        self.assertIn("CI_COMMIT_SHA", ci)


class PortablePackageTests(unittest.TestCase):
    """团队分发便携包：启动脚本入库且可复现打包。

    安全软件（火绒企业版）会拦截未签名 exe 从 %TEMP% 之外加载 DLL，并把反复运行
    的同一路径信誉拖黑。便携包的启动脚本每次把整个目录复制到 %TEMP% 下的全新随机
    目录再启动，绕开这两点。脚本此前只存在于 gitignore 的 dist\\ 下、手工维护，
    清一次 dist 就没了——必须入库并由构建脚本产出。
    """

    LAUNCHER = Path(REPO_ROOT) / "packaging" / "portable" / "启动DocTool.cmd"

    def test_launcher_is_tracked_in_repo(self):
        self.assertTrue(self.LAUNCHER.is_file(), "便携包启动脚本必须入库")

    def test_launcher_is_ascii_only(self):
        """cmd.exe 按系统 ANSI 代码页解析批处理，非 ASCII 字节会破坏解析。"""
        raw = self.LAUNCHER.read_bytes()
        offenders = [
            (index, byte) for index, byte in enumerate(raw) if byte > 0x7F
        ]
        self.assertEqual(offenders, [], "启动脚本出现非 ASCII 字节")

    def test_launcher_copies_to_fresh_temp_dir(self):
        text = self.LAUNCHER.read_text(encoding="ascii")
        # 相对自身定位 DocTool\，解压到任意路径都能用。
        self.assertIn("%~dp0DocTool", text)
        # 每次全新随机目录（名字不含 DocTool），复制后再启动。
        self.assertIn("%TEMP%\\dt_run_", text)
        self.assertIn("robocopy", text)
        self.assertIn("start \"\" \"%TGT%\\DocTool.exe\"", text)

    def test_build_script_exposes_portable_switch(self):
        script = (Path(REPO_ROOT) / "build_exe.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Portable", script)
        # 便携包必须由 onedir 产出，且 zip 里同时包含目录与启动脚本。
        self.assertIn("packaging\\portable\\启动DocTool.cmd", script)
        self.assertIn("Compress-Archive", script)
        self.assertIn("DocTool-$AppVersion-portable.zip", script)

    def test_ci_publishes_portable_package(self):
        """tag 流水线除安装器外还产出便携包，并挂进 Release 资产。"""
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        self.assertIn("DocTool-$env:APP_VERSION-portable.zip", package_block)
        self.assertIn("Compress-Archive", package_block)
        # 便携包也要有校验值，且发布说明与资产链接都要带上。
        self.assertIn('"$portable.sha256"', package_block)
        release_block = ci[ci.index("release-upload:"):]
        self.assertIn("DocTool-$APP_VERSION-portable.zip", release_block)
        self.assertIn("portable.zip.sha256", release_block)
        self.assertIn("启动DocTool.cmd", release_block)

    def test_ci_zips_portable_after_app_signing(self):
        """便携包必须在应用签名之后打，否则包里是未签名 exe（照样被拦）。"""
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        sign_pos = package_block.index("$signtool.Source sign")
        zip_pos = package_block.index("Compress-Archive")
        self.assertLess(sign_pos, zip_pos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
