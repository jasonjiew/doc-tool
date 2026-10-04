# -*- coding: utf-8 -*-
"""V4.1 41-A：本地企业模板目录（可重建引用、同名校验、坏索引回退）。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.template_library import (  # noqa: E402
    INDEX_NAME,
    USE_EXPORT,
    USE_FILL,
    USE_SKELETON,
    build_library,
    index_path,
    load_library,
    read_index,
    recipe_for,
    relocate_warning,
    scan_roots,
    write_index,
)

PACK_YML = (
    "schemaVersion: 1\n"
    "packId: {pack_id}\n"
    "version: 1.2.0\n"
    "documentKind: requirement\n"
    "description: {description}\n"
    "unknownField: {unknown}\n"
)


def _make_pack(root: Path, pack_id: str, *, description: str = "测试包", unknown: str = "keep") -> Path:
    pack = root / pack_id
    (pack / "skeleton").mkdir(parents=True, exist_ok=True)
    (pack / "skeleton" / "1 引言.md").write_text("# 引言\n", encoding="utf-8")
    (pack / "pack.yml").write_text(
        PACK_YML.format(pack_id=pack_id, description=description, unknown=unknown),
        encoding="utf-8",
    )
    return pack


def _make_docx(path: Path, payload: bytes = b"PK\x03\x04stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-lib-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.standards = self.work / "standards"
        self.templates = self.work / "templates"
        _make_pack(self.standards, "generic-requirement")
        _make_docx(self.standards / "generic-requirement" / "template.docx", b"PK\x03\x04pack-template")
        _make_docx(self.templates / "requirement-template.docx", b"PK\x03\x04fill-template")
        (self.templates / "requirement-template.recipe.json").write_text(
            json.dumps({"styleMap": {"Heading1": "标题 1"}}, ensure_ascii=False), encoding="utf-8"
        )

    def test_scan_separates_uses(self):
        entries = scan_roots([self.standards], templates_root=self.templates)
        by_use = {}
        for item in entries:
            by_use.setdefault(item.use, []).append(item.name)
        self.assertEqual(by_use.get(USE_SKELETON), ["generic-requirement"])
        self.assertEqual(by_use.get(USE_EXPORT), ["generic-requirement 底模"])
        self.assertEqual(by_use.get(USE_FILL), ["requirement-template"])

    def test_summary_is_real_content_digest(self):
        entries = scan_roots([self.standards], templates_root=self.templates)
        skeleton = [item for item in entries if item.use == USE_SKELETON][0]
        export = [item for item in entries if item.use == USE_EXPORT][0]
        fill = [item for item in entries if item.use == USE_FILL][0]
        self.assertEqual(len(skeleton.summary), 64, "规范包摘要来自 pack.yml 的真实 sha256")
        self.assertEqual(len(export.summary), 64, "底模摘要来自 template.docx 的真实 sha256")
        self.assertEqual(len(fill.summary), 64)
        self.assertNotEqual(export.summary, fill.summary, "不同内容不得共享摘要")
        self.assertTrue(recipe_for(fill).endswith(".recipe.json"))

    def test_same_name_different_source_is_not_merged(self):
        other = self.work / "another-standards"
        _make_pack(other, "generic-requirement", description="另一来源")
        entries = scan_roots([self.standards, other])
        skeletons = [item for item in entries if item.use == USE_SKELETON]
        self.assertEqual(len(skeletons), 2, "同名不同来源必须保留两条，不按显示名合并")
        self.assertEqual(len({item.entryId for item in skeletons}), 2)
        self.assertEqual(len({item.source for item in skeletons}), 2)
        self.assertNotEqual(skeletons[0].summary, skeletons[1].summary)

    def test_unknown_declarations_kept_and_bad_pack_skipped(self):
        entries = scan_roots([self.standards])
        skeleton = [item for item in entries if item.use == USE_SKELETON][0]
        self.assertEqual(skeleton.unknown.get("unknownField"), "keep", "未知声明必须保留")
        broken = self.work / "broken"
        (broken / "bad-pack").mkdir(parents=True)
        (broken / "bad-pack" / "pack.yml").write_text("schemaVersion: 1\n", encoding="utf-8")
        warnings: list = []
        entries = scan_roots([broken], warnings=warnings)
        self.assertEqual(entries, [], "无法解析的包不得产出条目")
        self.assertTrue(warnings, "坏包应给出提醒而不是静默忽略")

    def test_missing_root_is_reported_not_fatal(self):
        warnings: list = []
        entries = scan_roots([self.work / "nope"], warnings=warnings)
        self.assertEqual(entries, [])
        self.assertTrue(any("目录不存在" in item for item in warnings))

    def test_bundled_standards_are_marked_fixed(self):
        entries = scan_roots([self.standards])
        self.assertTrue(all(item.fixed for item in entries), "内置 standards 标记为固定包")
        self.assertTrue(all(item.sourceKind == "bundled-standards" for item in entries))


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-index-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.standards = self.work / "standards"
        self.state = self.work / ".state"
        _make_pack(self.standards, "generic-design")

    def test_build_writes_rebuildable_index(self):
        library = build_library([self.standards], state_dir=self.state)
        target = index_path(self.state)
        self.assertTrue(target.is_file(), "应写出索引：{0}".format(target))
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertTrue(payload["entries"])
        self.assertIn("summary", payload["entries"][0])

    def test_corrupt_index_falls_back_to_directory_scan(self):
        library = build_library([self.standards], state_dir=self.state)
        self.assertTrue(library.entries)
        index_path(self.state).write_text("{ not json", encoding="utf-8")
        self.assertIsNone(read_index(self.state), "坏索引不得当作可用")
        rebuilt = load_library([self.standards], state_dir=self.state)
        self.assertTrue(rebuilt.entries, "坏索引必须能重建")
        self.assertFalse(rebuilt.fromIndex)
        # 原规范包资源保持可用
        self.assertTrue((self.standards / "generic-design" / "pack.yml").is_file())

    def test_index_marks_missing_source_for_relocation(self):
        build_library([self.standards], state_dir=self.state)
        shutil.rmtree(self.standards / "generic-design")
        library = load_library([self.standards], state_dir=self.state)
        missing = [item for item in library.entries if item.missing]
        self.assertTrue(missing, "来源消失必须标出而不是当作可用")
        messages = relocate_warning(library)
        self.assertTrue(any("重新定位" in item for item in messages))

    def test_search_and_filter(self):
        _make_pack(self.standards, "generic-test", description="测试文档规范")
        library = load_library([self.standards], state_dir=self.state)
        self.assertTrue(library.search("design"))
        self.assertTrue(library.search("", use=USE_SKELETON))
        self.assertEqual(library.search("", use=USE_FILL), [], "该目录没有模板填充条目")
        self.assertTrue(library.search("测试文档"))
        self.assertIn("骨架建项", library.summary_line())

    def test_write_then_read_round_trip_keeps_facts(self):
        library = build_library([self.standards], state_dir=self.state)
        write_index(library, self.state)
        cached = read_index(self.state)
        self.assertIsNotNone(cached)
        original = sorted((item.entryId, item.use, item.summary) for item in library.entries)
        restored = sorted((item.entryId, item.use, item.summary) for item in cached.entries)
        self.assertEqual(original, restored)


if __name__ == "__main__":
    unittest.main(verbosity=2)