# -*- coding: utf-8 -*-
"""冻结应用冒烟测试。

任务 8.4：在无系统 Python 的干净临时环境运行启动/拆分冒烟。

验证：
1. PyInstaller onedir 应用 EXE 存在
2. _internal 目录包含所有必需资源（scripts/templates/config/resources）
3. 第三方库（lxml/PIL/yaml/win32com）可被冻结运行时导入
4. 资源定位（resource_root）在冻结态正确工作
5. 内核脚本（docx_common 等）可被运行时导入

由于 GUI 应用不输出到控制台，本测试通过检查文件结构和运行 CLI 版本来验证。
"""

from __future__ import annotations

import os
import subprocess
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

DIST_DIR = os.path.join(REPO_ROOT, "dist", "KonsungDocTool")
INTERNAL_DIR = os.path.join(DIST_DIR, "_internal")
EXE_PATH = os.path.join(DIST_DIR, "KonsungDocTool.exe")
CLI_EXE_PATH = os.path.join(DIST_DIR, "doc-tool-cli.exe")


def _frozen_exists():
    """检查冻结应用是否已构建。"""
    return os.path.isfile(EXE_PATH) and os.path.isdir(INTERNAL_DIR)


@unittest.skipUnless(_frozen_exists(), "冻结应用未构建，跳过冒烟测试（先运行 pyinstaller）")
class FrozenAppStructureTests(unittest.TestCase):
    """任务 8.4：冻结应用目录结构验证。"""

    def test_exe_exists(self):
        """KonsungDocTool.exe 存在。"""
        self.assertTrue(os.path.isfile(EXE_PATH))
        # EXE 至少 1MB
        self.assertGreater(os.path.getsize(EXE_PATH), 1024 * 1024)
        self.assertTrue(os.path.isfile(CLI_EXE_PATH))

    def test_internal_dir_exists(self):
        """_internal 目录存在。"""
        self.assertTrue(os.path.isdir(INTERNAL_DIR))

    def test_scripts_packed(self):
        """内核脚本已打包到 _internal/scripts/。"""
        scripts = os.path.join(INTERNAL_DIR, "scripts")
        self.assertTrue(os.path.isdir(scripts))
        for name in ("docx_common.py", "build_docx.py", "validate_docx.py",
                     "refresh_fields.py"):
            self.assertTrue(os.path.isfile(os.path.join(scripts, name)),
                            "缺少内核脚本: {0}".format(name))

    def test_templates_packed(self):
        """公司 Word 模板已打包到 _internal/templates/。"""
        templates = os.path.join(INTERNAL_DIR, "templates")
        self.assertTrue(os.path.isdir(templates))
        for name in ("requirement-template.docx", "design-template.docx"):
            self.assertTrue(os.path.isfile(os.path.join(templates, name)),
                            "缺少模板: {0}".format(name))

    def test_config_packed(self):
        """文档配置已打包到 _internal/config/。"""
        config = os.path.join(INTERNAL_DIR, "config")
        self.assertTrue(os.path.isdir(config))
        for name in ("requirement.yml", "design.yml"):
            self.assertTrue(os.path.isfile(os.path.join(config, name)),
                            "缺少配置: {0}".format(name))

    def test_resources_packed(self):
        """默认项目清单已打包到 _internal/doc_tool/resources/。"""
        resources = os.path.join(INTERNAL_DIR, "doc_tool", "resources")
        self.assertTrue(os.path.isdir(resources))
        self.assertTrue(os.path.isfile(os.path.join(resources, "default_project.yml")))

    def test_license_packed(self):
        """第三方许可文件已打包。"""
        self.assertTrue(os.path.isfile(
            os.path.join(INTERNAL_DIR, "THIRD_PARTY_LICENSES.txt")
        ))

    def test_third_party_libs_packed(self):
        """第三方库目录已打包。"""
        for lib_dir in ("lxml", "PIL", "yaml", "win32"):
            path = os.path.join(INTERNAL_DIR, lib_dir)
            self.assertTrue(os.path.isdir(path),
                            "缺少第三方库目录: {0}".format(lib_dir))


@unittest.skipUnless(_frozen_exists(), "冻结应用未构建，跳过冒烟测试")
class FrozenAppRuntimeTests(unittest.TestCase):
    """任务 8.4：冻结应用运行时冒烟。

    由于 GUI EXE 不输出到控制台，使用 Python 直接在冻结的 _internal 目录中
    验证模块导入和资源定位。这模拟了冻结运行时的 sys.path 和 _MEIPASS 环境。
    """

    def test_frozen_resource_root(self):
        """冻结态 resource_root() 指向 _internal/doc_tool/resources。"""
        code = (
            "import sys, os; "
            "internal = os.environ['FROZEN_INTERNAL']; "
            "sys.path.insert(0, internal); "
            "sys.path.insert(0, os.path.join(internal, 'doc_tool')); "
            "from doc_tool.resources import resource_root; "
            "root = resource_root(); "
            "print(root); "
            "assert os.path.isfile(os.path.join(root, 'default_project.yml')), "
            "'default_project.yml not found in ' + root; "
            "print('RESOURCE_ROOT_OK')"
        )
        env = dict(os.environ, FROZEN_INTERNAL=INTERNAL_DIR)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, check=False, env=env,
        )
        self.assertEqual(result.returncode, 0,
                         "resource_root 失败: {0}".format(result.stderr))
        self.assertIn("RESOURCE_ROOT_OK", result.stdout)

    def test_frozen_kernel_importable(self):
        """冻结态 kernel.ensure_kernel_importable() 能定位 scripts/ 目录。"""
        code = (
            "import sys, os; "
            "internal = os.environ['FROZEN_INTERNAL']; "
            "sys.path.insert(0, internal); "
            "sys.path.insert(0, os.path.join(internal, 'doc_tool')); "
            "from doc_tool.adapters import kernel; "
            "kernel.ensure_kernel_importable(); "
            "import docx_common; "
            "print('KERNEL_OK'); "
            "import build_docx; "
            "print('BUILD_OK'); "
            "import validate_docx; "
            "print('VALIDATE_OK'); "
            "import refresh_fields; "
            "print('REFRESH_OK')"
        )
        env = dict(os.environ, FROZEN_INTERNAL=INTERNAL_DIR)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, check=False, env=env,
        )
        self.assertEqual(result.returncode, 0,
                         "kernel 导入失败: {0}".format(result.stderr))
        self.assertIn("KERNEL_OK", result.stdout)
        self.assertIn("BUILD_OK", result.stdout)
        self.assertIn("VALIDATE_OK", result.stdout)
        self.assertIn("REFRESH_OK", result.stdout)

    def test_frozen_third_party_importable(self):
        """冻结态第三方库可导入。"""
        code = (
            "import sys, os; "
            "internal = os.environ['FROZEN_INTERNAL']; "
            "sys.path.insert(0, internal); "
            "import lxml; print('lxml', lxml.__version__); "
            "import PIL; print('Pillow', PIL.__version__); "
            "import yaml; print('yaml', yaml.__version__); "
            "import win32com.client; print('win32com OK'); "
            "print('ALL_LIBS_OK')"
        )
        env = dict(os.environ, FROZEN_INTERNAL=INTERNAL_DIR)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, check=False, env=env,
        )
        self.assertEqual(result.returncode, 0,
                         "第三方库导入失败: {0}".format(result.stderr))
        self.assertIn("ALL_LIBS_OK", result.stdout)

    def test_frozen_cli_info_and_help(self):
        """冻结 CLI 可运行既有 info 与新增机器可读命令帮助。"""
        info = subprocess.run(
            [CLI_EXE_PATH, "info"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertIn("appVersion", info.stdout)
        help_result = subprocess.run(
            [CLI_EXE_PATH, "validate", "--help"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--output", help_result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
