# -*- coding: utf-8 -*-
"""旧版专用项目迁移测试。

任务 5.4-5.6：旧 requirement/design 项目复制迁移为通用项目，验证后原子发布；
失败回滚、源项目不变、重复迁移、缺失资源、损坏模板诊断。

夹具：完全人工合成的最小旧 requirement/design 项目（不读取仓库 content/ 真实
业务文档），复用真实模板结构以保证可构建。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
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

from doc_tool.application.migrate_project import migrate_legacy_project  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

REQUIREMENT_TEMPLATE = os.path.join(REPO_ROOT, "templates", "requirement-template.docx")

MINIMAL_CONTENT = {
    "第1章 概述/_index.md": "本文档用于迁移验证。\n",
    "第1章 概述/1.1 背景.md": "测试背景描述。\n",
    "第1章 概述/1.2 目标.md": "验证迁移后内容与资源完整。\n",
}


def _make_legacy_project(root, doc_type: str = "requirement") -> Path:
    """构造一个可构建的最小旧版专用项目（requirement 或 design）。"""
    root = Path(root).resolve()
    template_dir = root / "template"
    template_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REQUIREMENT_TEMPLATE, template_dir / "template.docx")

    content_dir = root / "content" / doc_type
    for relative, body in MINIMAL_CONTENT.items():
        path = content_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")

    for sub in ("images", "tables"):
        (root / "assets" / doc_type / sub).mkdir(parents=True, exist_ok=True)
    (root / "original").mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_dir / "template.docx", root / "original" / "source.docx")
    (root / "output").mkdir(parents=True, exist_ok=True)

    manifest = ProjectManifest(
        documentType=doc_type,
        documentNo="FIXTURE-001",
        documentName="迁移验证项目",
        documentVersion="1.0",
        sourceSha256="fixture",
        paths={
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content/{0}".format(doc_type),
            "assetRoot": "assets/{0}".format(doc_type),
            "tableRoot": "assets/{0}/tables".format(doc_type),
        },
        headingStyles={1: "2", 2: "3", 3: "5", 4: "6", 5: "7", 6: "8"},
        bodyStyle="4",
    )
    manifest.save(root, backup=False)
    return root


def _source_fingerprint(source: Path) -> dict:
    """记录源项目全部文件路径+内容，用于验证迁移后源不变。"""
    fingerprint = {}
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name != "project.lock":
            fingerprint[str(path.relative_to(source))] = path.read_bytes()
    return fingerprint


class LegacyMigrationTests(unittest.TestCase):
    """任务 5.4：旧项目成功迁移为通用项目。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-migrate-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_requirement_migrates_to_general(self):
        source = _make_legacy_project(os.path.join(self._tmp, "src"), "requirement")
        target = os.path.join(self._tmp, "dst")
        before = _source_fingerprint(source)

        result = migrate_legacy_project(source, target)

        self.assertTrue(result.success, "迁移应成功：{0}".format(
            [(e.stage, e.status, e.detail) for e in result.events if e.status == "failed"]))
        self.assertEqual(result.target, Path(target).resolve())
        # 目标清单为 general，目录已重写
        manifest = ProjectManifest.load(target)
        self.assertEqual(manifest.documentType, "general")
        self.assertEqual(manifest.documentNo, "FIXTURE-001")
        self.assertTrue((Path(target) / "content" / "general").is_dir())
        self.assertFalse((Path(target) / "content" / "requirement").exists())
        self.assertTrue((Path(target) / "assets" / "general" / "tables").is_dir())
        # 内容完整迁移
        self.assertTrue((Path(target) / "content" / "general" / "第1章 概述" / "1.1 背景.md").is_file())
        # 迁移报告已写入
        report = json.loads(
            (Path(target) / "logs" / "migration.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["sourceDocumentType"], "requirement")
        self.assertEqual(report["targetDocumentType"], "general")
        # 源项目未被修改
        self.assertEqual(_source_fingerprint(source), before)

    def test_design_migrates_to_general(self):
        source = _make_legacy_project(os.path.join(self._tmp, "src-design"), "design")
        target = os.path.join(self._tmp, "dst-design")
        result = migrate_legacy_project(source, target)
        self.assertTrue(result.success)
        self.assertEqual(ProjectManifest.load(target).documentType, "general")

    def test_source_unchanged_after_migration(self):
        source = _make_legacy_project(os.path.join(self._tmp, "src-keep"), "requirement")
        before = _source_fingerprint(source)
        migrate_legacy_project(source, os.path.join(self._tmp, "dst-keep"))
        self.assertEqual(_source_fingerprint(source), before)

    def test_general_source_rejected(self):
        """general 项目不是旧版专用项目，拒绝迁移且不创建目标。"""
        source = _make_legacy_project(os.path.join(self._tmp, "src-gen"), "general")
        target = os.path.join(self._tmp, "dst-gen")
        result = migrate_legacy_project(source, target)
        self.assertFalse(result.success)
        self.assertFalse(Path(target).exists())

    def test_target_exists_rejected(self):
        source = _make_legacy_project(os.path.join(self._tmp, "src-dup"), "requirement")
        target = os.path.join(self._tmp, "dst-dup")
        Path(target).mkdir()
        result = migrate_legacy_project(source, target)
        self.assertFalse(result.success)
        # 源项目不受影响
        self.assertTrue(ProjectManifest.load(source).documentType == "requirement")

    def test_missing_resource_blocks_migration(self):
        """迁移验证缺失资源引用应失败并回滚（源不变、无半成品）。"""
        source = _make_legacy_project(os.path.join(self._tmp, "src-miss"), "requirement")
        # 在正文中引用一张不存在的图片
        content_md = (
            Path(source) / "content" / "requirement" / "第1章 概述" / "1.1 背景.md"
        )
        content_md.write_text("![缺失图片](images/not-found.png)\n", encoding="utf-8")
        before = _source_fingerprint(source)
        target = os.path.join(self._tmp, "dst-miss")

        result = migrate_legacy_project(source, target)

        self.assertFalse(result.success, "缺失资源应阻止迁移")
        self.assertFalse(Path(target).exists(), "失败时不应有半成品目标")
        # 暂存已清理
        staging = [d for d in os.listdir(self._tmp) if d.startswith(".dst-miss.migrate-staging")]
        self.assertEqual(staging, [], "失败后暂存目录应被清理")
        self.assertEqual(_source_fingerprint(source), before)

    def test_broken_template_blocks_migration(self):
        """损坏模板导致试构建失败应回滚，源不变。"""
        source = _make_legacy_project(os.path.join(self._tmp, "src-tpl"), "requirement")
        (Path(source) / "template" / "template.docx").write_bytes(b"not a docx")
        before = _source_fingerprint(source)
        target = os.path.join(self._tmp, "dst-tpl")

        result = migrate_legacy_project(source, target)

        self.assertFalse(result.success)
        self.assertFalse(Path(target).exists())
        self.assertEqual(_source_fingerprint(source), before)

    def test_migrated_project_is_buildable_and_validatable(self):
        """迁移后的 general 项目可通过构建与校验（试构建已覆盖，此处再验证产物）。"""
        source = _make_legacy_project(os.path.join(self._tmp, "src-ok"), "requirement")
        target = os.path.join(self._tmp, "dst-ok")
        self.assertTrue(migrate_legacy_project(source, target).success)
        from doc_tool.adapters.kernel import build_with_project, validate_with_project

        manifest = ProjectManifest.load(target)
        paths = manifest.resolve_paths(target)
        output = build_with_project(manifest, paths)
        self.assertTrue(Path(output).suffix == ".docx")
        self.assertTrue(validate_with_project(manifest, paths))


if __name__ == "__main__":
    unittest.main(verbosity=2)
