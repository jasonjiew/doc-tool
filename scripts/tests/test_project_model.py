# -*- coding: utf-8 -*-
"""项目模型测试：ProjectManifest、ProjectPaths、版本信息与工作区可移植性。

任务 1.6：增加项目工作区夹具，并验证完整项目可复制到另一绝对路径后打开。
覆盖中文、空格、括号、``&`` 等合法 Windows 路径字符。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 让 doc_tool 包可被导入：scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

from doc_tool.domain.errors import (  # noqa: E402
    IncompatibleSchemaError,
    PathEscapeError,
    ProjectManifestError,
)
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402
from doc_tool.domain.version import (  # noqa: E402
    APP_VERSION,
    PROJECT_SCHEMA_VERSION,
    can_read_schema,
    can_write_schema,
    get_build_info,
    is_supported_schema,
)


def _make_manifest(**overrides):
    base = dict(
        documentType="requirement",
        documentNo="KF-2090-1-001",
        documentName="康尚健康云软件需求说明书",
        documentVersion="3.8",
        sourceSha256="abc123",
    )
    base.update(overrides)
    return ProjectManifest(**base)


class VersionTests(unittest.TestCase):
    def test_build_info_contains_required_fields(self):
        info = get_build_info()
        self.assertIn("appVersion", info)
        self.assertIn("commit", info)
        self.assertIn("projectSchemaVersion", info)
        self.assertEqual(info["appVersion"], APP_VERSION)
        self.assertEqual(info["projectSchemaVersion"], str(PROJECT_SCHEMA_VERSION))

    def test_schema_compatibility(self):
        self.assertTrue(is_supported_schema(1))
        self.assertFalse(is_supported_schema(99))
        self.assertTrue(can_write_schema(1))
        self.assertFalse(can_write_schema(2))
        # 更高版本可只读打开（向前兼容）
        self.assertTrue(can_read_schema(2))


class ProjectPathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="doctool_test_")
        self.root = Path(self.tmp)
        self.paths = ProjectPaths(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_standard_paths_under_root(self):
        self.assertEqual(self.paths.source_docx, self.root / "original" / "source.docx")
        self.assertEqual(self.paths.template_docx, self.root / "template" / "template.docx")
        self.assertEqual(self.paths.content_dir("requirement"), self.root / "content" / "requirement")
        self.assertEqual(self.paths.tables_dir("design"), self.root / "assets" / "design" / "tables")

    def test_resolve_relative_path(self):
        resolved = self.paths.resolve("content/requirement/第3章.md")
        self.assertEqual(resolved, (self.root / "content" / "requirement" / "第3章.md").resolve())

    def test_resolve_rejects_absolute_path(self):
        with self.assertRaises(PathEscapeError):
            self.paths.resolve("/etc/passwd")
        with self.assertRaises(PathEscapeError):
            self.paths.resolve("C:/Windows/system32")

    def test_resolve_rejects_parent_traversal(self):
        with self.assertRaises(PathEscapeError):
            self.paths.resolve("../../etc/passwd")

    def test_to_relative_roundtrip(self):
        target = self.root / "assets" / "requirement" / "images" / "login.png"
        rel = self.paths.to_relative(target)
        self.assertEqual(rel, "assets/requirement/images/login.png")
        self.assertEqual(self.paths.resolve(rel), target.resolve())

    def test_chinese_space_bracket_ampersand_paths(self):
        """中文、空格、括号、& 等合法 Windows 路径字符。"""
        special = "content/requirement/第3章 功能需求 (JD & 外发)/3.1 KSHC.md"
        resolved = self.paths.resolve(special)
        self.assertTrue(resolved.is_absolute())
        self.assertTrue(self.paths.is_inside(resolved))

    def test_ensure_directories_creates_structure(self):
        self.paths.ensure_directories("requirement")
        for directory in [
            self.paths.original_dir,
            self.paths.template_dir,
            self.paths.content_dir("requirement"),
            self.paths.images_dir("requirement"),
            self.paths.tables_dir("requirement"),
            self.paths.output_dir,
            self.paths.logs_dir,
            self.paths.state_dir,
        ]:
            self.assertTrue(directory.exists(), "缺失目录: {0}".format(directory))

    def test_is_inside_rejects_outside(self):
        outside = Path(tempfile.gettempdir()) / "other_project"
        self.assertFalse(self.paths.is_inside(outside))


class ProjectManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="doctool_manifest_")
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_save_then_load(self):
        manifest = _make_manifest()
        manifest.paths = {
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content/requirement",
            "assetRoot": "assets/requirement",
            "tableRoot": "assets/requirement/tables",
        }
        manifest.save(self.root)
        self.assertTrue((self.root / "project.yml").exists())

        loaded = ProjectManifest.load(self.root)
        self.assertEqual(loaded.documentType, "requirement")
        self.assertEqual(loaded.documentNo, "KF-2090-1-001")
        self.assertEqual(loaded.sourceSha256, "abc123")
        self.assertEqual(loaded.schemaVersion, PROJECT_SCHEMA_VERSION)
        self.assertEqual(loaded.refreshTimeoutSeconds, 900)

    def test_save_creates_backup_on_overwrite(self):
        manifest = _make_manifest()
        manifest.save(self.root)
        first_updated = manifest.updatedAt
        # 再次保存应产生备份
        manifest.documentVersion = "3.9"
        manifest.save(self.root)
        backups = list((self.root / ".state").glob("project.yml.*.bak"))
        self.assertEqual(len(backups), 1)
        # 备份内容应为旧版本
        import yaml

        backup_data = yaml.safe_load(backups[0].read_text(encoding="utf-8"))
        self.assertEqual(backup_data["documentVersion"], "3.8")

    def test_higher_schema_loads_readonly(self):
        """更高模式版本应只读打开，不抛异常（spec：不兼容项目只读显示）。"""
        import yaml

        data = {
            "schemaVersion": 2,
            "documentType": "requirement",
            "documentNo": "X",
            "documentName": "Y",
            "documentVersion": "1",
            "sourceSha256": "",
        }
        (self.root / "project.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
        loaded = ProjectManifest.load(self.root)
        self.assertEqual(loaded.schemaVersion, 2)
        self.assertFalse(loaded.is_writable())

    def test_load_rejects_missing_schema(self):
        import yaml

        data = {
            "documentType": "requirement",
            "documentNo": "X",
            "documentName": "Y",
            "documentVersion": "1",
            "sourceSha256": "",
        }
        (self.root / "project.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
        with self.assertRaises(ProjectManifestError):
            ProjectManifest.load(self.root)

    def test_rejects_unknown_document_type(self):
        with self.assertRaises(ProjectManifestError):
            _make_manifest(documentType="unknown")

    def test_rejects_short_refresh_timeout(self):
        with self.assertRaises(ProjectManifestError):
            _make_manifest(refreshTimeoutSeconds=10)

    def test_paths_validated_on_resolve(self):
        manifest = _make_manifest()
        manifest.paths = {"sourceDocx": "../../escape.docx"}
        with self.assertRaises(PathEscapeError):
            manifest.resolve_paths(self.root)

    def test_is_writable_for_current_schema(self):
        manifest = _make_manifest()
        self.assertTrue(manifest.is_writable())


class WorkspacePortabilityTests(unittest.TestCase):
    """任务 1.6：完整项目可复制到另一绝对路径后打开。"""

    def setUp(self):
        self.tmp_a = tempfile.mkdtemp(prefix="doctool_port_a_")
        self.tmp_b = tempfile.mkdtemp(prefix="doctool_port_b_")

    def tearDown(self):
        shutil.rmtree(self.tmp_a, ignore_errors=True)
        shutil.rmtree(self.tmp_b, ignore_errors=True)

    def test_project_copied_to_another_path_opens(self):
        root_a = Path(self.tmp_a)
        paths_a = ProjectPaths(root_a)
        paths_a.ensure_directories("requirement")
        # 写入一个示例 Markdown 和图片占位
        chapter_dir = paths_a.content_dir("requirement") / "第3章 功能需求"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        (chapter_dir / "_index.md").write_text("# 功能需求概述\n", encoding="utf-8")

        manifest = _make_manifest()
        manifest.paths = {
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content/requirement",
            "assetRoot": "assets/requirement",
            "tableRoot": "assets/requirement/tables",
        }
        manifest.save(root_a)

        # 复制到另一绝对路径
        root_b = Path(self.tmp_b) / "copied_project"
        shutil.copytree(root_a, root_b)

        # 在新路径打开：仅依赖相对路径
        loaded = ProjectManifest.load(root_b)
        paths_b = loaded.resolve_paths(root_b)
        self.assertTrue(paths_b.content_dir("requirement").exists())
        copied_chapter = paths_b.content_dir("requirement") / "第3章 功能需求" / "_index.md"
        self.assertTrue(copied_chapter.exists())
        self.assertIn("功能需求概述", copied_chapter.read_text(encoding="utf-8"))

    def test_chinese_project_path_portability(self):
        """中文项目路径在复制后仍可正常解析。"""
        root_a = Path(self.tmp_a) / "需求文档项目 (测试)"
        paths_a = ProjectPaths(root_a)
        paths_a.ensure_directories("design")
        manifest = _make_manifest(documentType="design", documentNo="KF-2090-1-006")
        manifest.paths = {
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content/design",
            "assetRoot": "assets/design",
            "tableRoot": "assets/design/tables",
        }
        manifest.save(root_a)

        root_b = Path(self.tmp_b) / "副本 & 备份"
        shutil.copytree(root_a, root_b)
        loaded = ProjectManifest.load(root_b)
        self.assertEqual(loaded.documentType, "design")
        loaded.resolve_paths(root_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
