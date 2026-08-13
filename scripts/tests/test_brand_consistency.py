# -*- coding: utf-8 -*-
"""公共品牌一致性测试。

任务 2.6：扫描生产代码、打包脚本与候选产物，阻断公司名称、网址、内部编号
或旧可执行文件名；并校验集中品牌元数据模块（``doc_tool/domain/branding.py``）
提供的公共身份一致且中性。

覆盖范围：
- 品牌元数据模块的公共值（显示名/程序标识/CLI 名/组织设置键/可执行文件名）
- 生产代码（doc_tool/）不含禁止品牌、网址、内部编号、旧可执行文件名
- 打包脚本（packaging/）不含上述禁止标识
- 扫描词表（packaging/scan_vocabulary.txt）存在且包含必需类别
- 候选产物 dist/（若存在）不含旧可执行文件名

说明：
- ``doc_tool/domain/branding.py`` 有意保留内部版遗留标识常量（LEGACY_*），
  供设置迁移与兼容检测读取，因此扫描时显式排除该文件。
- ``packaging/scan_vocabulary.txt`` 是被扫描词表本身，列出禁止词条，因此排除。
- 测试夹具（scripts/tests/fixtures）与文档目录的脱敏由任务 8.4 处理，不在本测试范围。
"""

from __future__ import annotations

import os
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


# 禁止出现在公共源码/打包脚本中的标识（大小写不敏感子串匹配）。
FORBIDDEN_TERMS = [
    "康尚",
    "康尚健康云",
    "konsung",
    "konsung.com",
    "KonsungDocTool",
    "KF-2090",
    "KSHC",
    "KSOA",
    "KSFD",
    "KSDCD",
    "KSCC",
    "KSAT",
    "KSCDSS",
    "Kmilight",
    "健康云",
]

# 有意保留禁止词的公共文件（白名单）。
EXCLUDED_FILES = {
    os.path.normpath("doc_tool/domain/branding.py"),
    os.path.normpath("packaging/scan_vocabulary.txt"),
    os.path.normpath("packaging/export_public_source.py"),
}

# 被扫描的目录。
SCAN_DIRS = ["doc_tool", "packaging"]

# 可读取的文本扩展名。
TEXT_SUFFIXES = {".py", ".iss", ".spec", ".ps1", ".txt", ".yml", ".yaml", ".json", ".md"}


class BrandingMetadataTests(unittest.TestCase):
    """集中品牌元数据模块提供中性一致的公共身份。"""

    def test_public_identity_values(self):
        from doc_tool.domain.branding import (
            APP_DISPLAY_NAME,
            APP_EXECUTABLE_NAME,
            APP_PROGRAM_ID,
            APP_SETTINGS_APPLICATION_KEY,
            CLI_NAME,
            ORGANIZATION_SETTINGS_KEY,
        )

        self.assertEqual(APP_DISPLAY_NAME, "Doc Tool")
        self.assertEqual(APP_PROGRAM_ID, "DocTool")
        self.assertEqual(APP_EXECUTABLE_NAME, "DocTool.exe")
        self.assertEqual(CLI_NAME, "doc-tool")
        self.assertEqual(ORGANIZATION_SETTINGS_KEY, "DocToolProject")
        self.assertEqual(APP_SETTINGS_APPLICATION_KEY, "DocTool")

    def test_public_identity_contains_no_company_brand(self):
        """公共品牌占位值本身不得包含公司品牌。"""
        from doc_tool.domain.branding import (
            APP_DISPLAY_NAME,
            APP_EXECUTABLE_NAME,
            APP_PROGRAM_ID,
            CLI_NAME,
            ORGANIZATION_SETTINGS_KEY,
            PRODUCT_DESCRIPTION,
            USER_CONFIG_DIR_NAME,
        )

        values = [
            APP_DISPLAY_NAME,
            APP_EXECUTABLE_NAME,
            APP_PROGRAM_ID,
            CLI_NAME,
            ORGANIZATION_SETTINGS_KEY,
            PRODUCT_DESCRIPTION,
            USER_CONFIG_DIR_NAME,
        ]
        lowered = " ".join(values).lower()
        for term in ("konsung", "康尚", "konsung.com"):
            self.assertNotIn(term, lowered)

    def test_legacy_identifiers_present_for_migration(self):
        """内部版遗留标识必须保留在 branding 模块，供设置迁移与兼容检测。"""
        from doc_tool.domain.branding import (
            LEGACY_APP_DISPLAY_NAME,
            LEGACY_EXECUTABLE_NAME,
            LEGACY_INSTALL_DIR_SEGMENT,
            LEGACY_ORGANIZATION_KEY,
            LEGACY_USER_CONFIG_DIR_NAME,
        )

        self.assertEqual(LEGACY_ORGANIZATION_KEY, "Konsung")
        self.assertEqual(LEGACY_APP_DISPLAY_NAME, "康尚文档工具")
        self.assertEqual(LEGACY_USER_CONFIG_DIR_NAME, "konsung-doc-tool")
        self.assertEqual(LEGACY_EXECUTABLE_NAME, "KonsungDocTool.exe")
        self.assertEqual(LEGACY_INSTALL_DIR_SEGMENT, "Konsung\\DocTool")


class _ScanMixin:
    """共享的目录扫描逻辑。"""

    def _iter_text_files(self, root: Path):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = os.path.normpath(path.relative_to(REPO_ROOT).as_posix())
            if rel in EXCLUDED_FILES:
                continue
            if "__pycache__" in path.parts or ".git" in path.parts:
                continue
            yield rel, path

    def _scan_for_terms(self, root: Path, terms):
        hits = []
        for rel, path in self._iter_text_files(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lowered = text.lower()
            for term in terms:
                if term.lower() in lowered:
                    hits.append("{0}: {1}".format(rel, term))
        return hits


class BrandConsistencySourceTests(_ScanMixin, unittest.TestCase):
    """生产代码与打包脚本不含禁止品牌/编号/网址/旧可执行文件名。"""

    def test_production_code_clean(self):
        root = Path(REPO_ROOT)
        hits = []
        for dirname in SCAN_DIRS:
            hits.extend(self._scan_for_terms(root / dirname, FORBIDDEN_TERMS))
        # 顶层 scripts/*.py（内核脚本）随应用打包并进入公共导出，需一并覆盖扫描；
        # scripts/migration/ 与 scripts/tests/ 为内部/测试目录，不进入公共产物。
        scripts_dir = root / "scripts"
        for path in sorted(scripts_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lowered = text.lower()
            for term in FORBIDDEN_TERMS:
                if term.lower() in lowered:
                    hits.append("{0}: {1}".format(path.name, term))
        self.assertEqual(hits, [])

    def test_installer_uses_public_identity(self):
        """安装器不含公司品牌，使用公共 AppId/安装目录/可执行文件名。"""
        iss_path = Path(REPO_ROOT) / "packaging" / "installer.iss"
        text = iss_path.read_text(encoding="utf-8")
        self.assertNotIn("康尚", text)
        self.assertNotIn("konsung", text.lower())
        self.assertNotIn("Konsung\\DocTool", text)
        self.assertNotIn("F6D0000F-13F0-50D9-8743-5B42D68FF071", text)
        self.assertIn("DocTool.exe", text)

    def test_spec_uses_public_executable_name(self):
        for spec_name in ("doc_tool.spec", "doc_tool_onefile.spec"):
            spec = (Path(REPO_ROOT) / "packaging" / spec_name).read_text(encoding="utf-8")
            self.assertIn('name="DocTool"', spec)
            self.assertNotIn("KonsungDocTool", spec)

    def test_scan_vocabulary_has_required_categories(self):
        """扫描词表存在且包含必需类别（任务 1.4）。"""
        vocab = Path(REPO_ROOT) / "packaging" / "scan_vocabulary.txt"
        self.assertTrue(vocab.is_file())
        text = vocab.read_text(encoding="utf-8")
        for category in ("[brand]", "[doc-number]", "[product]", "[domain]", "[rfc1918]", "[sensitive-path]"):
            self.assertIn(category, text)


class BrandConsistencyArtifactTests(unittest.TestCase):
    """候选产物（dist/）不含旧可执行文件名。"""

    def test_dist_has_no_legacy_executable(self):
        dist_dir = Path(REPO_ROOT) / "dist"
        if not dist_dir.is_dir():
            self.skipTest("dist/ 目录不存在，跳过产物扫描")
        for path in dist_dir.rglob("KonsungDocTool.exe"):
            self.fail("dist 中发现旧可执行文件名: {0}".format(path))
        for path in dist_dir.rglob("*KonsungDocTool*"):
            self.fail("dist 中发现含旧产品名的文件: {0}".format(path))


class PublicLauncherTests(unittest.TestCase):
    """任务 7.1-7.4：公共启动脚本中性、纯 ASCII；旧品牌/.cmd 兼容入口退出。"""

    def test_public_launcher_exists_and_is_ascii_only(self):
        """公共启动脚本使用中性文件名且内容纯 ASCII。"""
        launcher = Path(REPO_ROOT) / "start-doc-tool.cmd"
        self.assertTrue(launcher.is_file(), "公共启动脚本 start-doc-tool.cmd 缺失")
        data = launcher.read_bytes()
        non_ascii = [b for b in data if b > 0x7F]
        self.assertEqual(non_ascii, [], "公共启动脚本必须保持纯 ASCII 字节")
        text = data.decode("ascii")
        self.assertNotIn("Konsung", text)
        self.assertNotIn("康尚", text)
        self.assertIn("Doc Tool", text)

    def test_public_launcher_preserves_probe_and_bootstrap_semantics(self):
        """公共启动脚本保留 PySide6 探测、vendor 路径与引导安装语义。"""
        launcher = (Path(REPO_ROOT) / "start-doc-tool.cmd").read_bytes().decode("ascii")
        self.assertIn("PySide6.QtWidgets import QApplication", launcher)
        self.assertIn(".vendor\\site-packages", launcher)
        self.assertIn("setup_pyside6.py", launcher)
        self.assertIn("python -m doc_tool.app", launcher)

    def test_legacy_cmd_launchers_excluded_from_public_export(self):
        """旧品牌启动脚本与需求/设计/全部生成 .cmd 兼容入口不进入公共导出。"""
        import importlib.util

        module_path = Path(REPO_ROOT) / "packaging" / "export_public_source.py"
        spec = importlib.util.spec_from_file_location("doc_tool_export", module_path)
        export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export)

        for legacy in (
            "启动康尚文档工具.cmd",
            "全部生成.cmd",
            "生成需求说明书.cmd",
            "生成详细设计说明书.cmd",
        ):
            self.assertTrue(
                export._is_excluded(legacy),
                "旧品牌/专用构建 .cmd 必须被公共导出排除: {0}".format(legacy),
            )

    def test_cli_build_requires_project(self):
        """公共 CLI build 只接受 --project，旧 requirement/design/all 入口已删除。"""
        from doc_tool.cli import build_parser

        with self.assertRaises(SystemExit):
            build_parser().parse_args(["build", "requirement"])
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["build", "design"])
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["build", "all"])
        args = build_parser().parse_args(["build", "--project", "x"])
        self.assertEqual(args.project, "x")


if __name__ == "__main__":
    unittest.main()
