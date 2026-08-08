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
            (root / "KonsungDocTool.exe").write_bytes(b"exe")
            (root / "customer-data.txt").write_text("secret", encoding="utf-8")
            leaks = scan_leaks.scan_allowlist(root)
            self.assertTrue(any("customer-data.txt" in item for item in leaks))
            self.assertFalse(any("KonsungDocTool.exe" in item for item in leaks))


class ReleasePipelineTests(unittest.TestCase):
    def test_hash_is_generated_after_all_signing_steps(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        self.assertGreater(
            package_block.rfind("Get-FileHash"),
            package_block.rfind("signtool.Source sign"),
        )
        self.assertIn("signtool.Source verify", package_block)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
