# -*- coding: utf-8 -*-
"""V3.0 正文复用/变体服务测试（批次 30-B/30-C/30-D/30-E）。

覆盖：
- 模块提取（正文 + 引用资源）、库检索/预览、不可变版本与候选版本、库损坏回退；
- 固定引用展开：参数默认/字面值、标题偏移、循环停止、固定版本升级前后出稿一致；
- 复制编辑不被升级影响、实例身份稳定与覆盖率分母、缺模块兜底；
- 产品变体有效范围/文本覆盖/独立输出、展开兼容副本可搬目录打开。

夹具目录统一用 ``scripts.tests.core_fixtures`` 的仓库内临时目录。
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests.core_fixtures import cleanup, scratch_dir, tiny_png, two_chapter_project  # noqa: E402

from doc_tool.application.content import module_refs as refs  # noqa: E402
from doc_tool.application.content import modules as modules  # noqa: E402
from doc_tool.application.content import variants as variants  # noqa: E402

CHAPTER_ONE = "第1章 引言/1.1 目的.md"
CHAPTER_TWO = "第2章 设计/2.1 架构.md"
DOCUMENT_TYPE = "general"


@dataclass
class ReuseCase:
    """一个可复用的测试场景：两章项目 + 模块库 + 装配。"""

    root: Path
    lib_root: Path
    lib: modules.ModuleLibrary
    content_root: Path
    assembly: refs.Assembly = field(default_factory=refs.Assembly)

    def chapter(self, relative: str = CHAPTER_ONE) -> Path:
        return self.content_root / relative

    def read(self, relative: str = CHAPTER_ONE) -> str:
        return self.chapter(relative).read_text(encoding="utf-8")

    def write(self, text: str, relative: str = CHAPTER_ONE) -> None:
        self.chapter(relative).write_text(text, encoding="utf-8")

    def assemble_overrides(self) -> dict:
        """把项目装配的固定参数转成 resolver 覆盖（等价编辑器"插入并使用固定参数"）。"""
        return {
            slot.slotId: {"version": slot.version, "params": dict(slot.params)}
            for slot in self.assembly.slots
        }

    def resolve(
        self,
        text: str,
        *,
        host_path: str = CHAPTER_ONE,
        library: modules.ModuleLibrary = None,
        variables=None,
        cache=None,
        slot_overrides=None,
        strict: bool = False,
    ) -> refs.Resolution:
        return refs.resolve_body(
            text,
            project_root=self.root,
            library=self.lib if library is None else library,
            variables=variables or {},
            host_path=host_path,
            cache=cache,
            slot_overrides=slot_overrides,
            strict=strict,
        )


def _module_body(product: str = "示例产品", marker: str = "示例") -> str:
    return (
        "# {0}\n\n"
        "本段说明 {0} 的通用约定，产品名：{{{{module.productName}}}}。\n\n"
        "<!-- DOC-ITEM: REQ-TERM-01 | 术语一致性 -->\n"
        "- 术语以本模块为准。\n"
    ).format(product, marker=marker)


def _iface_body() -> str:
    return (
        "# 接口约定\n\n"
        "![接口示意图](images/img_0001.png)\n\n"
        "统一前缀：{{module.productName}}，版本 {{{{module.apiVersion}}}}。\n\n"
        "<!-- DOC-ITEM: REQ-IFACE-01 | 接口前缀 -->\n"
        "- 接口前缀与产品名一致。\n"
    )


def make_case(prefix: str = "v30", *, with_iface: bool = True) -> ReuseCase:
    """构造两章项目 + 两/三个模块的夹具（真实导入项目，可整体搬目录）。"""
    base = scratch_dir(prefix)
    root = two_chapter_project(base / "proj-{0}".format(prefix), document_type=DOCUMENT_TYPE)
    content_root = root / "content" / DOCUMENT_TYPE
    lib_root = base / "lib-{0}".format(prefix)

    images = root / "assets" / DOCUMENT_TYPE / "images"
    images.mkdir(parents=True, exist_ok=True)
    tiny_png(images / "img_0001.png")

    lib = modules.ModuleLibrary(lib_root)
    lib.publish(modules.Module(
        moduleId="term-standard",
        version="1.0.0",
        title="通用术语",
        body=_module_body("通用术语"),
        tags=["通用", "术语"],
        description="公共术语与接口约定",
        parameters=[{"name": "productName", "default": "示例产品", "description": "产品名"}],
        source={"path": CHAPTER_ONE},
    ))
    if with_iface:
        extract = modules.extract_module(
            _iface_body(),
            module_id="iface-spec",
            version="1.0.0",
            tags=["接口"],
            parameters=[{"name": "productName", "default": "示例产品"},
                        {"name": "apiVersion", "default": "v1"}],
            resource_roots=[content_root, root / "assets" / DOCUMENT_TYPE],
            base_dir=root,
            source={"path": CHAPTER_ONE},
        )
        lib.publish(extract.module, resources=extract.sourcePaths)

    case = ReuseCase(root=root, lib_root=lib_root, lib=lib, content_root=content_root)
    case.assembly = refs.Assembly(slots=[
        refs.AssemblySlot(slotId="slot-term", moduleId="term-standard", version="1.0.0",
                          chapter=CHAPTER_ONE, params={"productName": "甲型号"}),
        refs.AssemblySlot(slotId="slot-iface", moduleId="iface-spec", version="1.0.0",
                          chapter=CHAPTER_ONE),
    ])
    case.assembly.save(root)
    for slot in case.assembly.slots:
        if case.lib.get(slot.moduleId, slot.version) is None:
            continue
        modules.install_from_library(root, case.lib, slot.moduleId, slot.version)

    case.write(
        "# 目的\n\n本章说明目的。\n\n"
        + refs.canonical_directive("term-standard", "1.0.0", "slot-term")
        + "\n"
        + refs.canonical_directive("iface-spec", "1.0.0", "slot-iface")
        + "\n本章结尾。\n"
    )
    case.write("# 架构\n\n本章说明架构。\n", CHAPTER_TWO)
    return case


class ModuleLibraryTests(unittest.TestCase):
    """30-B：提取、检索预览、不可变版本、项目固定副本。"""

    def setUp(self) -> None:
        self.case = make_case("b1")
        self.addCleanup(cleanup, self.case.root.parent)

    def test_extract_module_collects_body_and_referenced_resources(self):
        body = self.case.read()
        before = self.case.read()
        result = modules.extract_module(
            _iface_body(),
            module_id="iface-extract",
            version="0.9.0",
            tags=["接口"],
            parameters=[{"name": "productName", "default": "示例产品"}],
            resource_roots=[self.case.content_root, self.case.root / "assets" / DOCUMENT_TYPE],
            base_dir=self.case.root,
        )
        self.assertEqual(result.collected, ["images/img_0001.png"])
        self.assertEqual(result.missing, [])
        self.assertEqual(len(result.module.resources), 1)
        self.assertTrue(result.module.resources[0].sha256)
        self.assertIn("resources/img_0001.png", result.module.body)
        self.assertNotIn("images/img_0001.png", result.module.body)
        self.assertIn("REQ-IFACE-01", result.module.body)
        self.assertTrue(result.sourcePaths)
        # 提取不改动源章节
        self.assertEqual(self.case.read(), before)
        self.assertIn("本章结尾。", body)

    def test_missing_resource_keeps_literal_reference_and_reports(self):
        result = modules.extract_module(
            "# 缺图\n\n![x](images/img_missing.png)\n",
            module_id="iface-missing",
            version="1.0.0",
            resource_root=self.case.content_root,
        )
        self.assertEqual(result.missing, ["images/img_missing.png"])
        self.assertIn("images/img_missing.png", result.module.body)
        self.assertTrue(any("资源缺失" in item for item in result.warnings))

    def test_library_search_and_preview_use_declared_defaults(self):
        hits = self.case.lib.search("通用术语")
        self.assertEqual([item.identity for item in hits], ["term-standard@1.0.0"])
        self.assertEqual(self.case.lib.search("", tags=["接口"])[0].moduleId, "iface-spec")
        self.assertEqual(self.case.lib.search("不存在的关键词"), [])
        preview = self.case.lib.preview("term-standard", "1.0.0")
        self.assertIn("示例产品", preview)
        preview_named = self.case.lib.preview("term-standard", "1.0.0", {"productName": "乙型号"})
        self.assertIn("乙型号", preview_named)
        self.assertIsNone(self.case.lib.preview("term-standard", "9.9.9"))

    def test_same_version_different_content_keeps_old_and_saves_candidate(self):
        original = self.case.lib.get("term-standard", "1.0.0").body
        changed = modules.Module(
            moduleId="term-standard",
            version="1.0.0",
            title="通用术语",
            body=_module_body("通用术语二稿"),
            tags=["通用"],
            parameters=[{"name": "productName", "default": "示例产品"}],
        )
        published = self.case.lib.publish(changed)
        self.assertEqual(published.version, "1.0.0-2")
        self.assertEqual(published.candidate, "1.0.0-2")
        self.assertTrue(any("候选版本" in item for item in published.warnings))
        self.assertEqual(self.case.lib.get("term-standard", "1.0.0").body, original)
        self.assertIn("二稿", self.case.lib.get("term-standard", "1.0.0-2").body)
        self.assertEqual(sorted(self.case.lib.versions("term-standard")), ["1.0.0", "1.0.0-2"])

    def test_corrupt_index_falls_back_to_directory_scan(self):
        index_path = self.case.lib_root / modules.INDEX_FILE_NAME
        index_path.write_text("{ this is not json", encoding="utf-8")
        library = modules.ModuleLibrary(self.case.lib_root)
        self.assertTrue(library.index_error)
        self.assertIn("索引", library.damaged_report)
        self.assertEqual(library.get("term-standard", "1.0.0").moduleId, "term-standard")

    def test_missing_library_directory_is_empty_not_error(self):
        library = modules.ModuleLibrary(self.case.lib_root / "not-there")
        self.assertEqual(library.modules(), [])
        self.assertIsNone(library.get("term-standard", "1.0.0"))
        self.assertTrue(library.issues)

    def test_project_install_is_offline_copy(self):
        target = modules.project_module_dir(self.case.root, "iface-spec", "1.0.0")
        self.assertTrue((target / modules.MANIFEST_FILE_NAME).is_file())
        self.assertTrue((target / "resources" / "img_0001.png").is_file())
        self.assertTrue((target / modules.BODY_FILE_NAME).is_file())
        # 项目内固定副本不依赖原库：库目录搬走后仍可展开
        moved = self.case.lib_root.with_name(self.case.lib_root.name + "-moved")
        self.case.lib_root.rename(moved)
        try:
            resolution = self.case.resolve(self.case.read(), library=None)
            self.assertIn("接口约定", resolution.text)
            self.assertNotIn(modules.MODULE_MISSING_TEMPLATE.split("{")[0], resolution.text)
            self.assertEqual(
                sorted(resolution.resources().keys()), ["resources/img_0001.png"]
            )
        finally:
            moved.rename(self.case.lib_root)

class ResolutionTests(unittest.TestCase):
    """30-C：参数、层级偏移、循环、固定版本、复制编辑。"""

    def setUp(self) -> None:
        self.case = make_case("c1")
        self.addCleanup(cleanup, self.case.root.parent)

    def test_slot_reference_uses_project_fixed_copy_and_reports_origin(self):
        resolution = self.case.resolve(
            self.case.read(), slot_overrides=self.case.assemble_overrides()
        )
        self.assertIn("通用术语", resolution.text)
        self.assertIn("甲型号", resolution.text)
        self.assertIn("本章结尾。", resolution.text)
        self.assertEqual(resolution.slots, ["slot-term", "slot-iface"])
        self.assertEqual(
            resolution.manifest(),
            {"slot-term": "term-standard@1.0.0", "slot-iface": "iface-spec@1.0.0"},
        )
        origin = resolution.source_for_slot("slot-term")
        self.assertIsNotNone(origin)
        self.assertIn("term-standard@1.0.0", origin.display)
        self.assertIn(CHAPTER_ONE, origin.display)
        # 源正文不被展开改写
        self.assertIn("```doc-module", self.case.read())

    def test_missing_parameter_uses_declared_default(self):
        self.case.write("# 目的\n\n" + refs.canonical_directive(
            "term-standard", "1.0.0", "slot-term") + "\n")
        resolution = self.case.resolve(self.case.read())
        self.assertIn("示例产品", resolution.text)
        self.assertTrue(any("声明默认值" in item for item in resolution.warnings))

    def test_undeclared_parameter_keeps_literal_value(self):
        self.case.lib.publish(modules.Module(
            moduleId="term-literal", version="1.0.0", title="字面值模块",
            body="# 字面值模块\n\n声明键：{{module.productName}}；未声明键：{{module.unknownKey}}。\n",
            parameters=[{"name": "productName", "default": "示例产品"}],
        ))
        modules.install_from_library(self.case.root, self.case.lib, "term-literal", "1.0.0")
        self.case.write(
            "# 目的\n\n"
            + refs.canonical_directive("term-literal", "1.0.0", "slot-literal", {"nobody": "x"})
            + "\n"
        )
        resolution = self.case.resolve(self.case.read())
        self.assertIn("声明键：示例产品", resolution.text)
        self.assertIn("{{module.unknownKey}}", resolution.text)
        self.assertTrue(any("未声明" in item for item in resolution.warnings))
        self.assertTrue(any("nobody" in item for item in resolution.warnings))

    def test_prefixed_variables_reach_declared_parameters(self):
        self.case.write("# 目的\n\n" + refs.canonical_directive(
            "term-standard", "1.0.0", "slot-term") + "\n")
        resolution = self.case.resolve(self.case.read(), variables={"module.productName": "丙型号"})
        self.assertIn("丙型号", resolution.text)

    def test_heading_offset_shifts_levels_and_clips(self):
        self.case.write(
            "# 目的\n\n"
            + refs.canonical_directive("term-standard", "1.0.0", "slot-term", heading_offset=2)
            + "\n"
        )
        resolution = self.case.resolve(self.case.read())
        self.assertIn("### 通用术语", resolution.text)
        self.assertIn("标题偏移", " ".join(resolution.warnings))
        self.case.write(
            "# 目的\n\n"
            + refs.canonical_directive("term-standard", "1.0.0", "slot-term", heading_offset=-3)
            + "\n"
        )
        clipped = self.case.resolve(self.case.read())
        self.assertIn("# 通用术语", clipped.text)
        self.assertTrue(any("截断" in item for item in clipped.warnings))
        # 源模块未被改动
        self.assertIn("# 通用术语", self.case.lib.get("term-standard", "1.0.0").body)

    def test_cycle_stops_only_that_reference(self):
        self.case.lib.publish(modules.Module(
            moduleId="loop-a", version="1.0.0", title="循环A",
            body="# 循环A\n\n" + refs.canonical_directive("loop-b", "1.0.0", "slot-loop-a") + "\n",
        ))
        self.case.lib.publish(modules.Module(
            moduleId="loop-b", version="1.0.0", title="循环B",
            body="# 循环B\n\n" + refs.canonical_directive("loop-a", "1.0.0", "slot-loop-b") + "\n",
        ))
        modules.install_from_library(self.case.root, self.case.lib, "loop-a", "1.0.0")
        modules.install_from_library(self.case.root, self.case.lib, "loop-b", "1.0.0")
        self.case.write(
            "# 目的\n\n宿主开始。\n\n"
            + refs.canonical_directive("loop-a", "1.0.0", "slot-loop")
            + "\n宿主结束。\n"
        )
        resolution = self.case.resolve(self.case.read())
        self.assertIn("宿主开始。", resolution.text)
        self.assertIn("宿主结束。", resolution.text)
        self.assertIn("循环A", resolution.text)
        self.assertIn("循环B", resolution.text)
        self.assertTrue(any("循环引用" in item for item in resolution.warnings))
        self.assertTrue(resolution.degraded)
        # 其余章节照常展开
        other = self.case.resolve(
            "# 架构\n\n" + refs.canonical_directive("term-standard", "1.0.0", "slot-other") + "\n",
            host_path=CHAPTER_TWO,
        )
        self.assertIn("通用术语", other.text)
        self.assertFalse(any("循环引用" in item for item in other.warnings))

    def test_fixed_version_output_unchanged_after_library_upgrade(self):
        before = self.case.resolve(self.case.read())
        self.assertIn("通用术语", before.text)
        self.case.lib.publish(modules.Module(
            moduleId="term-standard",
            version="2.0.0",
            title="通用术语",
            body=_module_body("通用术语").replace("通用约定", "新版通用约定"),
            tags=["通用"],
            parameters=[{"name": "productName", "default": "示例产品"}],
        ))
        after = self.case.resolve(self.case.read())
        self.assertEqual(before.text, after.text)
        self.assertIn("通用约定", after.text)
        self.assertNotIn("新版通用约定", after.text)
        self.assertEqual(after.manifest()["slot-term"], "term-standard@1.0.0")

    def test_copy_edit_is_plain_body_and_immune_to_upgrade(self):
        copied_body = "# 复制来的术语\n\n复制编辑正文，产品名写死为丁型号。\n"
        self.case.write(
            "# 目的\n\n"
            + refs.canonical_copy_block(copied_body, slot_id="slot-copy", version="1.0.0",
                                        source=CHAPTER_ONE)
            + "\n"
            + refs.canonical_directive("term-standard", "1.0.0", "slot-term")
            + "\n"
        )
        resolution = self.case.resolve(self.case.read())
        self.assertIn("复制编辑正文", resolution.text)
        self.assertNotIn("```doc-module-copy", resolution.text)
        self.assertEqual([segment.kind for segment in resolution.segments].count("copy"), 1)
        self.assertEqual(resolution.copies, ["slot-copy"])
        self.assertEqual(resolution.slots, ["slot-term"])
        self.case.lib.publish(modules.Module(
            moduleId="term-standard", version="2.0.0", title="通用术语",
            body=_module_body("通用术语").replace("通用约定", "升级后的约定"),
            parameters=[{"name": "productName", "default": "示例产品"}],
        ))
        after = self.case.resolve(self.case.read())
        self.assertIn("复制编辑正文，产品名写死为丁型号。", after.text)
        self.assertNotIn("升级后的约定", after.text)

class InstanceTrackingTests(unittest.TestCase):
    """30-D：实例身份、覆盖率分母、选择升级。"""

    def setUp(self) -> None:
        self.case = make_case("d1")
        self.addCleanup(cleanup, self.case.root.parent)

    def _book(self) -> refs.InstanceBook:
        resolution = self.case.resolve(self.case.read())
        book = refs.InstanceBook(self.case.root)
        refs.include_items_in_tracking(book, resolution, host_path=CHAPTER_ONE)
        book.save()
        return book

    def test_same_slot_keeps_identity_and_new_slot_gets_new_id(self):
        book = self._book()
        first = {item.slotId: item.instanceId for item in book.entries()}
        self.assertEqual(set(first), {"slot-term", "slot-iface"})
        self.assertNotEqual(first["slot-term"], first["slot-iface"])
        # 重排章节位置后身份不变
        book.refresh_positions({"slot-term": CHAPTER_TWO, "slot-iface": CHAPTER_TWO})
        book.save()
        reloaded = refs.InstanceBook.load(self.case.root)
        after = {item.slotId: item.instanceId for item in reloaded.entries()}
        self.assertEqual(first, after)
        self.assertEqual(reloaded.by_slot("slot-term")[0].chapter, CHAPTER_TWO)
        # 新 slot 分配新身份
        resolution = self.case.resolve(
            "# 目的\n\n" + refs.canonical_directive("term-standard", "1.0.0", "slot-new") + "\n"
        )
        refs.include_items_in_tracking(reloaded, resolution)
        new_ids = {item.slotId: item.instanceId for item in reloaded.entries()}
        self.assertIn("slot-new", new_ids)
        self.assertNotIn(new_ids["slot-new"], [first["slot-term"], first["slot-iface"]])

    def test_coverage_denominator_only_counts_explicit_instances(self):
        book = self._book()
        coverage = refs.coverage_of(book)
        self.assertEqual(coverage.denominator, 2)  # 只算明确纳入的条目：term 1 + iface 1
        self.assertEqual(coverage.coverage, 1.0)
        self.assertTrue(book.exclude("slot-iface", "REQ-IFACE-01"))
        coverage_after = refs.coverage_of(book)
        self.assertEqual(coverage_after.denominator, 1)
        self.assertIn("REQ-IFACE-01", [
            item.originItemId for item in book.entries() if not item.included
        ])
        self.assertFalse(book.include("slot-unknown", "REQ-X"))

    def test_upgrade_plan_and_partial_apply(self):
        target = modules.Module(
            moduleId="term-standard", version="2.0.0", title="通用术语",
            body=_module_body("通用术语").replace("通用约定", "升级后的约定")
            + "\n新增段落。\n",
            parameters=[{"name": "productName", "default": "示例产品"},
                        {"name": "owner", "default": "质量组"}],
        )
        self.case.lib.publish(target)
        current = self.case.lib.get("term-standard", "1.0.0")
        plan = refs.plan_upgrade(self.case.assembly, "term-standard", current, target)
        self.assertEqual(plan.affected_slot_ids(), ["slot-term"])
        self.assertTrue(plan.difference.bodyChanged)
        self.assertEqual(plan.difference.parametersAdded, ["owner"])

        updated, applied = refs.apply_upgrade(self.case.assembly, plan, slot_ids=["slot-term"])
        self.assertEqual(applied, ["slot-term"])
        self.assertEqual(updated.get("slot-term").version, "2.0.0")
        self.assertEqual(updated.get("slot-iface").version, "1.0.0")
        # 未选实例不会被升级
        updated_none, applied_none = refs.apply_upgrade(self.case.assembly, plan, slot_ids=[])
        self.assertEqual(applied_none, ["slot-term"])
        self.assertEqual(updated_none.get("slot-term").version, "2.0.0")

    def test_upgraded_slot_changes_output_only_for_that_slot(self):
        target = modules.Module(
            moduleId="term-standard", version="2.0.0", title="通用术语",
            body=_module_body("通用术语").replace("通用约定", "升级后的约定"),
            parameters=[{"name": "productName", "default": "示例产品"}],
        )
        self.case.lib.publish(target)
        current = self.case.lib.get("term-standard", "1.0.0")
        plan = refs.plan_upgrade(self.case.assembly, "term-standard", current, target)
        updated, _applied = refs.apply_upgrade(self.case.assembly, plan, slot_ids=["slot-term"])
        modules.install_from_library(self.case.root, self.case.lib, "term-standard", "2.0.0")
        overrides = {
            slot.slotId: {"version": slot.version} for slot in updated.slots
        }
        resolution = self.case.resolve(self.case.read(), slot_overrides=overrides)
        self.assertIn("升级后的约定", resolution.text)
        self.assertEqual(resolution.manifest()["slot-iface"], "iface-spec@1.0.0")
        self.assertEqual(resolution.manifest()["slot-term"], "term-standard@2.0.0")

    def test_tracked_copies_are_reported_but_not_counted(self):
        self.case.write(
            "# 目的\n\n"
            + refs.canonical_copy_block("# 复制段\n\n复制内容。\n", slot_id="slot-copy")
            + "\n"
            + refs.canonical_directive("term-standard", "1.0.0", "slot-term")
            + "\n"
        )
        resolution = self.case.resolve(self.case.read())
        book = refs.InstanceBook(self.case.root)
        refs.include_items_in_tracking(book, resolution)
        self.assertEqual(refs.tracked_copies(book, resolution), ["slot-copy"])
        self.assertEqual(book.by_slot("slot-copy"), [])
        self.assertEqual(refs.coverage_of(book).denominator, 1)


class FallbackTests(unittest.TestCase):
    """30-C/30-E：缺模块、缺资源、严格模式、无变体旧行为。"""

    def setUp(self) -> None:
        self.case = make_case("f1")
        self.addCleanup(cleanup, self.case.root.parent)

    def test_missing_module_placeholder_keeps_rest_of_body(self):
        self.case.write(
            "# 目的\n\n前面正文。\n\n"
            + refs.canonical_directive("term-unknown", "1.0.0", "slot-missing")
            + "\n后面正文。\n"
        )
        resolution = self.case.resolve(self.case.read())
        self.assertIn("前面正文。", resolution.text)
        self.assertIn("后面正文。", resolution.text)
        self.assertIn("term-unknown@1.0.0", resolution.text)
        self.assertIn("待补充", resolution.text)
        self.assertTrue(resolution.degraded)
        self.assertTrue(any("未找到固定副本" in item for item in resolution.warnings))

    def test_missing_project_copy_uses_same_version_library_cache(self):
        import shutil

        shutil.rmtree(
            str(modules.project_module_dir(self.case.root, "iface-spec", "1.0.0")),
            ignore_errors=True,
        )
        resolution = self.case.resolve(self.case.read())
        self.assertIn("接口约定", resolution.text)
        self.assertTrue(any("同版本缓存" in item for item in resolution.warnings))
        self.assertEqual(resolution.manifest()["slot-iface"], "iface-spec@1.0.0")

    def test_missing_resource_keeps_placeholder_and_other_content(self):
        resolution = self.case.resolve(self.case.read())
        self.assertEqual(sorted(resolution.resources().keys()), ["resources/img_0001.png"])
        # 删除项目固定副本内的资源后仍可继续，并给出可读提示
        target = modules.project_module_dir(self.case.root, "iface-spec", "1.0.0") / "resources"
        for child in target.iterdir():
            child.unlink()
        degraded = self.case.resolve(self.case.read(), library=None)
        self.assertIn("统一前缀", degraded.text)
        self.assertTrue(any("资源" in item for item in degraded.warnings))
        self.assertEqual(degraded.resources(), {})

    def test_cache_is_keyed_by_slot_overrides(self):
        """同一份正文用不同 slot 覆盖展开必须得到不同结果（缓存键含覆盖项）。"""
        cache = refs.ResolutionCache()
        text = self.case.read()
        base = self.case.resolve(text, cache=cache)
        overridden = self.case.resolve(
            text, cache=cache,
            slot_overrides={"slot-term": {"params": {"productName": "戊型号"}}},
        )
        self.assertIn("示例产品", base.text)
        self.assertIn("戊型号", overridden.text)
        self.assertNotEqual(base.text, overridden.text)
        again = self.case.resolve(text, cache=cache)
        self.assertEqual(again.text, base.text)

    def test_strict_mode_collects_errors(self):
        self.case.write(
            "# 目的\n\n"
            + refs.canonical_directive("term-unknown", "1.0.0", "slot-missing")
            + "\n"
        )
        resolution = self.case.resolve(self.case.read(), strict=True)
        self.assertTrue(resolution.errors)
        self.assertFalse(resolution.is_clean())
        lenient = self.case.resolve(self.case.read(), strict=False)
        self.assertFalse(lenient.errors)
        self.assertTrue(lenient.is_clean())

    def test_corrupt_assembly_and_variants_fall_back_to_defaults(self):
        (self.case.root / refs.ASSEMBLY_RELATIVE).write_text("{ broken", encoding="utf-8")
        assembly = refs.Assembly.load(self.case.root)
        self.assertEqual(assembly.slots, [])
        (self.case.root / variants.VARIANTS_RELATIVE).write_text("variants: [", encoding="utf-8")
        config = variants.VariantsConfig.load(self.case.root)
        self.assertEqual(config.variants, [])
        chapters, excluded, warnings = variants.effective_chapters(
            [CHAPTER_ONE, CHAPTER_TWO], [CHAPTER_ONE, CHAPTER_TWO], None
        )
        self.assertEqual(chapters, [CHAPTER_ONE, CHAPTER_TWO])
        self.assertEqual(excluded, [])
        self.assertEqual(warnings, [])

    def test_extraction_result_reports_illegal_targets(self):
        result = modules.extract_module(
            "# 非法\n\n![x](../outside.png)\n",
            module_id="iface-illegal",
            version="1.0.0",
            resource_root=self.case.content_root,
        )
        self.assertEqual(result.missing, [])
        self.assertTrue(result.module.resources == [])

class VariantTests(unittest.TestCase):
    """30-E：显式变体配置、独立输出、未知变体、默认行为。"""

    def setUp(self) -> None:
        self.case = make_case("e1")
        self.addCleanup(cleanup, self.case.root.parent)
        self.lib = self.case.lib
        self.lib.publish(modules.Module(
            moduleId="io-spec", version="1.0.0", title="接口规格",
            body="# 接口规格\n\nIO 规格正文，产品名：{{module.productName}}。\n",
            tags=["接口", "规格"],
            parameters=[{"name": "productName", "default": "示例产品"}],
        ))
        self.lib.publish(modules.Module(
            moduleId="term-standard", version="2.0.0", title="通用术语",
            body=_module_body("通用术语").replace("通用约定", "升级后的约定"),
            tags=["通用"],
            parameters=[{"name": "productName", "default": "示例产品"}],
        ))
        modules.install_from_library(self.case.root, self.lib, "io-spec", "1.0.0")
        self.case.write(
            "# 架构\n\n本章说明架构。\n\n"
            + refs.canonical_directive("io-spec", "1.0.0", "slot-io")
            + "\n",
            CHAPTER_TWO,
        )
        self.discovered = [CHAPTER_ONE, CHAPTER_TWO]
        self.variant_a = variants.Variant(
            variantId="model-a", name="甲型号",
            include=[CHAPTER_ONE], variables={"productName": "甲型号"},
            modules={"term-standard": "2.0.0"},
        )
        self.variant_b = variants.Variant(
            variantId="model-b", name="乙型号",
            include=[CHAPTER_TWO], exclude=[], variables={"productName": "乙型号"},
            modules={"io-spec": "1.0.0"},
        )
        self.config = variants.VariantsConfig(variants=[self.variant_a, self.variant_b])

    def _assemble(self) -> refs.Assembly:
        assembly = refs.Assembly(slots=[
            refs.AssemblySlot(slotId="slot-term", moduleId="term-standard", version="1.0.0",
                              chapter=CHAPTER_ONE, params={"productName": "甲型号"}),
            refs.AssemblySlot(slotId="slot-iface", moduleId="iface-spec", version="1.0.0",
                              chapter=CHAPTER_ONE),
            refs.AssemblySlot(slotId="slot-io", moduleId="io-spec", version="1.0.0",
                              chapter=CHAPTER_TWO),
        ])
        assembly.save(self.case.root)
        return assembly

    def test_two_variants_differ_in_chapters_variables_and_module_version(self):
        assembly = self._assemble()
        runs, problems = variants.build_variant_outputs(
            self.case.root, self.case.root / "out",
            discovered=self.discovered, config=self.config, assembly=assembly, library=self.lib,
        )
        self.assertEqual(problems, [])
        self.assertEqual([run.variantId for run in runs], ["model-a", "model-b"])
        run_a, run_b = runs
        self.assertEqual(run_a.chapters, [CHAPTER_ONE])
        self.assertEqual(run_a.excluded, [CHAPTER_TWO])
        self.assertEqual(run_b.chapters, [CHAPTER_TWO])
        self.assertEqual(run_b.excluded, [CHAPTER_ONE])
        self.assertEqual(run_a.moduleVersions["slot-term"], "term-standard@2.0.0")
        self.assertEqual(run_b.moduleVersions["slot-io"], "io-spec@1.0.0")
        self.assertNotEqual(run_a.outputDir, run_b.outputDir)

        text_a = (Path(run_a.outputDir) / "content" / DOCUMENT_TYPE / CHAPTER_ONE).read_text(
            encoding="utf-8"
        )
        text_b = (Path(run_b.outputDir) / "content" / DOCUMENT_TYPE / CHAPTER_TWO).read_text(
            encoding="utf-8"
        )
        self.assertIn("甲型号", text_a)
        self.assertIn("升级后的约定", text_a)
        self.assertNotIn("乙型号", text_a)
        self.assertIn("乙型号", text_b)
        self.assertNotIn("甲型号", text_b)
        # 两份产物都存在且互不覆盖
        self.assertTrue(
            (Path(run_a.outputDir) / "content" / DOCUMENT_TYPE / CHAPTER_ONE).is_file()
        )
        self.assertTrue(
            (Path(run_b.outputDir) / "content" / DOCUMENT_TYPE / CHAPTER_TWO).is_file()
        )
        # 源项目正文未被改动
        self.assertIn("```doc-module", self.case.read())
        self.assertIn("```doc-module", self.case.read(CHAPTER_TWO))

    def test_variant_scope_reports_effective_range_and_excluded_note(self):
        assembly = self._assemble()
        scope = variants.variant_scope(
            self.variant_a, discovered=self.discovered,
            project_variables={"productName": "项目默认"}, assembly=assembly,
        )
        self.assertEqual(scope.chapters, [CHAPTER_ONE])
        self.assertEqual(scope.excluded, [CHAPTER_TWO])
        self.assertEqual(scope.variables["productName"], "甲型号")
        self.assertEqual(scope.moduleVersions["term-standard"], "2.0.0")
        coverage = variants.coverage_note(
            variants.VariantRun(variantId="model-a", name="甲型号", outputDir="x",
                                chapters=[CHAPTER_ONE]),
            [CHAPTER_ONE, CHAPTER_TWO],
        )
        self.assertEqual(coverage["counted"], [CHAPTER_ONE])
        self.assertEqual(coverage["excluded"], [CHAPTER_TWO])
        self.assertTrue(coverage["note"])

    def test_unknown_variant_is_reported_not_silently_replaced(self):
        assembly = self._assemble()
        runs, problems = variants.build_variant_outputs(
            self.case.root, self.case.root / "out-unknown",
            discovered=self.discovered, config=self.config, assembly=assembly,
            library=self.lib, variant_ids=["model-x"],
        )
        self.assertEqual(runs, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("model-x", problems[0])
        self.assertIn("model-a", problems[0])
        self.assertFalse((self.case.root / "out-unknown").exists())

    def test_bad_section_items_fall_back_to_project_values(self):
        bad = variants.Variant(
            variantId="model-bad", name="坏配置",
            include=[CHAPTER_ONE, "不存在的章节.md"],
            exclude=["也不存在.md"],
            variables={"productName": "坏型号"},
        )
        chapters, excluded, warnings = variants.effective_chapters(
            self.discovered, self.discovered, bad
        )
        self.assertEqual(chapters, [CHAPTER_ONE])
        self.assertEqual(excluded, [CHAPTER_TWO])
        self.assertTrue(any("未找到" in item for item in warnings))
        all_excluded = variants.Variant(variantId="none", name="空范围", exclude=["第1章 引言", "第2章 设计"])
        chapters_all, _excluded, warnings_all = variants.effective_chapters(
            self.discovered, self.discovered, all_excluded
        )
        self.assertEqual(chapters_all, self.discovered)
        self.assertTrue(any("有效章节为空" in item for item in warnings_all))

    def test_unknown_slot_override_is_ignored(self):
        assembly = self._assemble()
        variant = variants.Variant(
            variantId="model-slot", name="槽位覆盖",
            slots={"slot-not-exists": {"version": "9.9.9"}},
        )
        overrides, warnings = variants.effective_slot_overrides(assembly, variant)
        self.assertEqual(overrides, {})
        self.assertTrue(any("未匹配" in item for item in warnings))

    def test_no_variant_configuration_keeps_project_behavior(self):
        assembly = self._assemble()
        chapters, excluded, warnings = variants.effective_chapters(
            self.discovered, self.discovered, None
        )
        self.assertEqual(chapters, self.discovered)
        self.assertEqual(excluded, [])
        self.assertEqual(warnings, [])
        runs, problems = variants.build_variant_outputs(
            self.case.root, self.case.root / "out-default",
            discovered=self.discovered, config=variants.VariantsConfig(), assembly=assembly,
            library=self.lib,
        )
        self.assertEqual(problems, [])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].variantId, "")
        self.assertEqual(runs[0].chapters, self.discovered)
        text = (Path(runs[0].outputDir) / "content" / DOCUMENT_TYPE / CHAPTER_ONE).read_text(
            encoding="utf-8"
        )
        self.assertIn("通用术语", text)


class PortableCopyTests(unittest.TestCase):
    """30-E/F：展开兼容副本（普通 Markdown、资源内嵌、可搬目录打开）。"""

    def setUp(self) -> None:
        self.case = make_case("p1")
        self.addCleanup(cleanup, self.case.root.parent)

    def test_expanded_copy_is_plain_markdown_with_local_assets(self):
        target = self.case.root / "out" / "expanded"
        run = variants.write_expanded_copy(
            self.case.root, target,
            discovered=[CHAPTER_ONE, CHAPTER_TWO],
            assembly=self.case.assembly, library=self.case.lib,
        )
        self.assertEqual(run.chapters, [CHAPTER_ONE, CHAPTER_TWO])
        text = (target / "content" / DOCUMENT_TYPE / CHAPTER_ONE).read_text(encoding="utf-8")
        self.assertNotIn("```doc-module", text)
        self.assertIn("通用术语", text)
        self.assertIn("来源：", text)
        self.assertTrue((target / variants.COPY_MANIFEST_NAME).is_file())
        self.assertTrue((target / variants.COPY_README_NAME).is_file())
        self.assertTrue((target / variants.COPY_INDEX_NAME).is_file())
        self.assertEqual(variants.verify_portable_copy(target), [])
        self.assertTrue(run.assets)
        manifest = (target / variants.COPY_MANIFEST_NAME).read_text(encoding="utf-8")
        self.assertIn("term-standard@1.0.0", manifest)

    def test_copy_can_be_moved_and_still_verifies(self):
        import shutil

        first = self.case.root / "out" / "expanded"
        variants.write_expanded_copy(
            self.case.root, first, discovered=[CHAPTER_ONE],
            assembly=self.case.assembly, library=self.case.lib,
        )
        moved = self.case.root / "moved-copy"
        shutil.move(str(first), str(moved))
        self.assertEqual(variants.verify_portable_copy(moved), [])
        text = (moved / "content" / DOCUMENT_TYPE / CHAPTER_ONE).read_text(encoding="utf-8")
        for match in __import__("re").finditer(r"!\[[^\]]*\]\((?P<target>[^)\s]+)\)", text):
            candidate = (
                moved / "content" / DOCUMENT_TYPE / CHAPTER_ONE
            ).parent / match.group("target")
            self.assertTrue(candidate.is_file(), match.group("target"))

    def test_copy_of_variant_only_contains_its_range(self):
        assembly = refs.Assembly(slots=[
            refs.AssemblySlot(slotId="slot-term", moduleId="term-standard", version="1.0.0",
                              chapter=CHAPTER_ONE),
        ])
        variant = variants.Variant(variantId="model-a", name="甲型号", include=[CHAPTER_ONE])
        target = self.case.root / "out" / "variant-a"
        run = variants.write_expanded_copy(
            self.case.root, target, discovered=[CHAPTER_ONE, CHAPTER_TWO],
            declared=[CHAPTER_ONE, CHAPTER_TWO], assembly=assembly, variant=variant,
            library=self.case.lib,
        )
        self.assertEqual(run.chapters, [CHAPTER_ONE])
        self.assertEqual(run.excluded, [CHAPTER_TWO])
        self.assertFalse(
            (target / "content" / DOCUMENT_TYPE / CHAPTER_TWO).exists()
        )
        self.assertEqual(variants.verify_portable_copy(target), [])
        index = (target / variants.COPY_INDEX_NAME).read_text(encoding="utf-8")
        self.assertIn("model-a", index)
        self.assertIn(CHAPTER_ONE, index)


if __name__ == '__main__':
    unittest.main(verbosity=2)