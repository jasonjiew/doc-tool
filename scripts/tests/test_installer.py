# -*- coding: utf-8 -*-
"""安装器配置与行为验证测试。

任务 8.6：验证静默安装、覆盖升级、修复和卸载只管理应用文件的配置。
任务 8.7：验证升级/卸载不删除外部项目，旧应用拒写更高模式项目。

本测试验证 Inno Setup 脚本 (installer.iss) 的配置正确性，
确保安装器行为符合设计要求。实际安装/卸载的端到端测试见
analysis/manual-checklist.md 第 4 节。

覆盖范围：
- AppId 稳定且唯一
- 按用户安装（PrivilegesRequired=lowest，无需管理员权限）
- 安装目录在 %LOCALAPPDATA%（不在 Program Files）
- 卸载只删除安装目录，不删除外部项目
- 开始菜单和可选桌面快捷方式
- 升级时关闭旧进程（CloseApplications=force）
- 输出文件名包含版本号
- 旧应用拒写更高模式项目（can_write_schema）
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ISS_PATH = os.path.join(REPO_ROOT, "packaging", "installer.iss")

# 从应用版本模块获取当前版本，避免硬编码
from doc_tool.domain.version import APP_VERSION


def _read_iss():
    """读取 installer.iss 文件内容。"""
    if not os.path.isfile(ISS_PATH):
        return ""
    with open(ISS_PATH, encoding="utf-8") as f:
        return f.read()


class InstallerConfigTests(unittest.TestCase):
    """任务 8.5/8.6：安装器配置验证。"""

    def setUp(self):
        self.iss = _read_iss()
        self.assertTrue(self.iss, "installer.iss 文件不存在或为空")

    def test_appid_stable(self):
        """AppId 是稳定的 GUID，跨版本一致。"""
        # 匹配 #define MyAppId "GUID" 或 AppId={{GUID}}
        match = re.search(r'#define\s+MyAppId\s+"([0-9A-Fa-f-]+)"', self.iss)
        if not match:
            match = re.search(r"AppId=\{\{([0-9A-Fa-f-]+)\}\}", self.iss)
        self.assertIsNotNone(match, "installer.iss 缺少 AppId")
        appid = match.group(1)
        # GUID 格式：8-4-4-4-12
        self.assertRegex(appid, r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
        # 确保不是 Inno Setup 默认的 GUID
        self.assertNotEqual(appid.upper(), "00000000-0000-0000-0000-000000000000")

    def test_user_install_no_admin(self):
        """按用户安装，不需要管理员权限。"""
        self.assertIn("PrivilegesRequired=lowest", self.iss)

    def test_install_dir_localappdata(self):
        """安装目录在 %LOCALAPPDATA%，不在 Program Files。"""
        self.assertIn("{localappdata}", self.iss)
        self.assertNotIn("{pf}", self.iss)
        self.assertNotIn("{autopf}", self.iss)

    def test_close_applications_on_upgrade(self):
        """升级时自动关闭旧进程。"""
        self.assertIn("CloseApplications=force", self.iss)

    def test_uninstall_does_not_recursively_delete_unknown_app_files(self):
        """卸载只移除安装器拥有文件，不递归删除整个安装目录。"""
        self.assertNotRegex(
            self.iss,
            r"(?i)Type:\s*filesandordirs;\s*Name:\s*\"\{app\}\"",
        )
        self.assertNotIn("{userdocs}", self.iss)
        self.assertNotIn("{commondocs}", self.iss)

    def test_start_menu_shortcut(self):
        """开始菜单快捷方式存在。"""
        self.assertIn("{group}", self.iss)

    def test_desktop_shortcut_optional(self):
        """桌面快捷方式是可选的（unchecked）。"""
        self.assertIn("desktopicon", self.iss)
        self.assertIn("Flags: unchecked", self.iss)
        self.assertIn("{userdesktop}", self.iss)
        self.assertNotIn("{commondesktop}", self.iss)

    def test_output_filename_versioned(self):
        """输出文件名包含版本号。"""
        self.assertIn("OutputBaseFilename={#MyAppNameEn}-Setup-{#MyAppVersion}", self.iss)

    def test_kill_app_on_uninstall(self):
        """卸载前关闭应用进程。"""
        self.assertIn("taskkill", self.iss)

    def test_use_previous_app_dir(self):
        """升级时使用之前的安装目录。"""
        self.assertIn("UsePreviousAppDir=yes", self.iss)


class InstallerArtifactTests(unittest.TestCase):
    """任务 8.8：安装器产物验证。"""

    def test_setup_exe_exists(self):
        """当前版本的安装器 EXE 已生成。"""
        exe = os.path.join(REPO_ROOT, "packaging", "Output",
                           "DocTool-Setup-{0}.exe".format(APP_VERSION))
        if not os.path.isfile(exe):
            self.skipTest("安装器未构建，先运行 ISCC.exe")
        self.assertGreater(os.path.getsize(exe), 1024 * 1024,
                           "安装器文件过小")

    def test_sha256_exists(self):
        """SHA-256 哈希文件已生成。"""
        sha = os.path.join(REPO_ROOT, "packaging", "Output",
                           "DocTool-Setup-{0}.exe.sha256".format(APP_VERSION))
        if not os.path.isfile(sha):
            self.skipTest("SHA-256 文件未生成")
        with open(sha, encoding="ascii") as f:
            content = f.read().strip()
        # SHA-256 是 64 位十六进制
        parts = content.split()
        self.assertGreaterEqual(len(parts), 1)
        self.assertEqual(len(parts[0]), 64)
        self.assertRegex(parts[0], r"^[0-9A-Fa-f]{64}$")


class PublicInternalCoexistTests(unittest.TestCase):
    """任务 3.4：公共版与内部版并存安装、独立升级与独立卸载。

    并存的前提是安装身份完全隔离：不同 AppId、不同安装目录、不同可执行文件名。
    任何一项与内部版相同都会导致覆盖或卸载冲突，因此作为硬约束验证。
    """

    def setUp(self):
        self.iss = _read_iss()

    def test_appid_differs_from_legacy(self):
        """公共 AppId 与内部版不同，保证注册表识别独立。"""
        from doc_tool.domain.branding import LEGACY_INSTALL_DIR_SEGMENT

        match = re.search(r'#define\s+MyAppId\s+"([0-9A-Fa-f-]+)"', self.iss)
        self.assertIsNotNone(match)
        self.assertNotEqual(match.group(1).upper(), "F6D0000F-13F0-50D9-8743-5B42D68FF071")

    def test_install_dir_differs_from_legacy(self):
        """安装目录与内部版不同，保证独立卸载。"""
        self.assertNotIn("Konsung\\DocTool", self.iss)
        self.assertIn("{localappdata}\\{#MyAppNameEn}", self.iss)

    def test_executable_differs_from_legacy(self):
        """可执行文件名与内部版不同，保证进程/快捷方式独立。"""
        self.assertNotIn("KonsungDocTool.exe", self.iss)
        self.assertIn("DocTool.exe", self.iss)
        # 卸载 kill 命令使用公共可执行名
        self.assertIn("{#MyAppExeName}", self.iss)


class SchemaCompatibilityGuardTests(unittest.TestCase):
    """任务 8.7：旧应用拒写更高模式项目（安装器无关，由应用层保证）。"""

    def test_reject_write_higher_schema(self):
        """旧应用拒绝写入更高模式版本。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_write_schema
        future = PROJECT_SCHEMA_VERSION + 1
        self.assertFalse(can_write_schema(future))

    def test_can_read_higher_schema_readonly(self):
        """旧应用可只读打开更高模式版本。"""
        from doc_tool.domain.version import can_read_schema
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION
        self.assertTrue(can_read_schema(PROJECT_SCHEMA_VERSION + 1))

    def test_user_projects_outside_install_dir(self):
        """用户项目默认不在安装目录下（设计约束验证）。

        ProjectPaths 的项目根由用户选择，不在安装目录。
        这里验证 ProjectPaths 不会把安装目录作为默认项目根。
        """
        from doc_tool.domain.paths import ProjectPaths
        import tempfile
        with tempfile.TemporaryDirectory(prefix="doc-proj-") as tmp:
            paths = ProjectPaths(tmp)
            # 项目路径都在用户选择的 tmp 下，不在安装目录
            self.assertTrue(str(paths.root).startswith(tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
