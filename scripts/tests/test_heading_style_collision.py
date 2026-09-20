# -*- coding: utf-8 -*-
"""Heading 样式同级多候选冲突回归测试。

真实缺陷：设计类模板的 ``styles.xml`` 同时存在内置 ``heading 1``（styleId
``2``）与基于它派生的自定义 ``标题1``（styleId ``140``，``customStyle="1"``、
``basedOn="2"``、无 ``outlineLvl``）。两者名字都命中「级别 1」，早期实现按
出现顺序把 styleId 反查成 级别 -> styleId，靠后的自定义样式顶掉内置样式，
于是全部一级章写成自定义 ``标题1``：丢掉内置 Heading 的大纲级别、编号
（``numId``）关联与 TOC 归属，Word 里表现为一级大章标题样式异常。

本文件锁定修复后的行为：识别映射保留全部候选，决策映射确定性择优。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from doc_tool.domain.ooxml import (  # noqa: E402
    heading_style_candidates,
    heading_style_usage,
    parse_heading_styles,
    parse_xml_safe,
    resolve_heading_styles,
    resolve_heading_styles_from_xml,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _styles_xml(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="{ns}">{body}</w:styles>'
    ).format(ns=W_NS, body=body).encode("utf-8")


def _builtin_heading(style_id: str, level: int, outline: int) -> str:
    """内置 Heading 样式：非自定义、显式 outlineLvl、基于 Normal。"""
    return (
        '<w:style w:type="paragraph" w:styleId="{sid}">'
        '<w:name w:val="heading {lv}"/>'
        '<w:basedOn w:val="1"/>'
        '<w:pPr><w:outlineLvl w:val="{outline}"/></w:pPr>'
        "</w:style>"
    ).format(sid=style_id, lv=level, outline=outline)


def _derived_heading(style_id: str, level: int, base_id: str, name: str) -> str:
    """派生自定义样式：customStyle=1、基于内置 Heading、无 outlineLvl。"""
    return (
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}">'
        '<w:name w:val="{name}"/>'
        '<w:basedOn w:val="{base}"/>'
        "</w:style>"
    ).format(sid=style_id, name=name, base=base_id)


# 与真实设计模板同构：内置 heading 1 在前，派生「标题1」在后。
COLLIDING_STYLES = _styles_xml(
    '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="Normal"/></w:style>'
    + _builtin_heading("2", 1, 0)
    + _builtin_heading("4", 2, 1)
    + _builtin_heading("5", 3, 2)
    + _derived_heading("140", 1, "2", "标题1")
)

# 无冲突模板：每级恰好一个候选。
CLEAN_STYLES = _styles_xml(
    '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="Normal"/></w:style>'
    + _builtin_heading("2", 1, 0)
    + _builtin_heading("3", 2, 1)
    + _builtin_heading("5", 3, 2)
)


def _document_xml(style_counts) -> bytes:
    """构造只含 pStyle 引用的 document.xml。"""
    paragraphs = "".join(
        '<w:p><w:pPr><w:pStyle w:val="{sid}"/></w:pPr></w:p>'.format(sid=sid)
        for sid, count in style_counts
        for _ in range(count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    ).format(ns=W_NS, body=paragraphs).encode("utf-8")


class CandidateParsingTests(unittest.TestCase):
    """候选解析：同级全部候选都要被保留下来。"""

    def test_both_colliding_candidates_are_found(self):
        root = parse_xml_safe(COLLIDING_STYLES, "word/styles.xml")
        candidates = heading_style_candidates(root)
        level_one = [c for c in candidates if c.level == 1]
        self.assertEqual(sorted(c.style_id for c in level_one), ["140", "2"])

    def test_candidate_metadata_recorded(self):
        root = parse_xml_safe(COLLIDING_STYLES, "word/styles.xml")
        by_id = {c.style_id: c for c in heading_style_candidates(root)}
        builtin = by_id["2"]
        self.assertFalse(builtin.custom)
        self.assertEqual(builtin.outline_level, 0)
        self.assertTrue(builtin.builtin_name)
        derived = by_id["140"]
        self.assertTrue(derived.custom)
        self.assertIsNone(derived.outline_level)
        self.assertEqual(derived.based_on, "2")
        self.assertFalse(derived.builtin_name)

    def test_character_styles_ignored(self):
        xml = _styles_xml(
            _builtin_heading("2", 1, 0)
            + '<w:style w:type="character" w:styleId="54">'
            '<w:name w:val="标题 1 Char"/></w:style>'
        )
        root = parse_xml_safe(xml, "word/styles.xml")
        self.assertEqual([c.style_id for c in heading_style_candidates(root)], ["2"])

    def test_levels_outside_range_ignored(self):
        xml = _styles_xml(_builtin_heading("9", 7, 6))
        self.assertEqual(heading_style_candidates(parse_xml_safe(xml, "word/styles.xml")), [])


class ResolveTests(unittest.TestCase):
    """决策映射：确定性择优，内置 Heading 必须胜出。"""

    def test_builtin_heading_wins_collision(self):
        resolved = resolve_heading_styles_from_xml(COLLIDING_STYLES)
        self.assertEqual(resolved[1], "2")
        self.assertEqual(resolved, {1: "2", 2: "4", 3: "5"})

    def test_clean_styles_unchanged(self):
        self.assertEqual(
            resolve_heading_styles_from_xml(CLEAN_STYLES), {1: "2", 2: "3", 3: "5"}
        )

    def test_empty_input(self):
        self.assertEqual(resolve_heading_styles_from_xml(b""), {})

    def test_usage_overrides_style_shape(self):
        """文档真在用派生样式时，必须继续用它——修复不能改写既有文档语义。"""
        root = parse_xml_safe(COLLIDING_STYLES, "word/styles.xml")
        usage = heading_style_usage(
            parse_xml_safe(_document_xml([("140", 16)]), "word/document.xml")
        )
        self.assertEqual(usage.get("140"), 16)
        self.assertEqual(resolve_heading_styles(root, usage=usage)[1], "140")

    def test_usage_absent_prefers_builtin(self):
        root = parse_xml_safe(COLLIDING_STYLES, "word/styles.xml")
        empty = heading_style_usage(
            parse_xml_safe(_document_xml([("2", 15)]), "word/document.xml")
        )
        self.assertEqual(resolve_heading_styles(root, usage=empty)[1], "2")


class IdentificationMapTests(unittest.TestCase):
    """识别映射：正文里出现的任何标题样式都要能被认出来。"""

    def test_all_candidates_kept_for_identification(self):
        mapping = parse_heading_styles(COLLIDING_STYLES)
        self.assertEqual(mapping["2"], 1)
        self.assertEqual(mapping["140"], 1)
        self.assertEqual(mapping["4"], 2)
        self.assertEqual(mapping["5"], 3)

    def test_identification_covers_decisions(self):
        mapping = parse_heading_styles(COLLIDING_STYLES)
        for level, style_id in resolve_heading_styles_from_xml(COLLIDING_STYLES).items():
            self.assertEqual(mapping[style_id], level)

    def test_empty_input(self):
        self.assertEqual(parse_heading_styles(b""), {})


class KernelSelfHealTests(unittest.TestCase):
    """已存在项目：清单里错误的 140 必须在构建时被纠正为内置样式。"""

    def _template(self, tmp, styles_xml):
        """写一个只含 styles.xml 的最小模板（内核只读该部件）。"""
        path = Path(tmp) / "template.docx"
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/></Types>',
            )
            archive.writestr("word/document.xml", _document_xml([("2", 1)]))
            archive.writestr("word/styles.xml", styles_xml)
        return path

    def _manifest(self, heading_styles):
        from doc_tool.domain.manifest import ProjectManifest

        return ProjectManifest(
            documentType="general",
            documentNo="GX-TEST-009",
            documentName="自修复测试",
            documentVersion="1.0",
            sourceSha256="0" * 64,
            headingStyles=heading_styles,
            bodyStyle="1",
        )

    def test_legacy_140_is_healed_to_builtin(self):
        from doc_tool.adapters.kernel import _effective_heading_styles

        tmp = tempfile.mkdtemp(prefix="doc-tool-heal-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        template = self._template(tmp, COLLIDING_STYLES)
        manifest = self._manifest({1: "140", 2: "4", 3: "5"})
        effective = _effective_heading_styles(manifest, template)
        self.assertEqual(effective[1], "2")
        # 自修复必须写回清单，否则旧项目会一直带着错误映射构建。
        self.assertEqual(manifest.headingStyles[1], "2")

    def test_correct_manifest_untouched(self):
        from doc_tool.adapters.kernel import _effective_heading_styles

        tmp = tempfile.mkdtemp(prefix="doc-tool-heal-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        template = self._template(tmp, COLLIDING_STYLES)
        manifest = self._manifest({1: "2", 2: "4", 3: "5"})
        self.assertEqual(
            _effective_heading_styles(manifest, template), {1: "2", 2: "4", 3: "5"}
        )

    def test_fallback_discovery_also_prefers_builtin(self):
        """清单里是没有候选资格的无效 styleId 时，兜底补全也不得选中派生样式。"""
        from doc_tool.adapters.kernel import _effective_heading_styles

        tmp = tempfile.mkdtemp(prefix="doc-tool-heal-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        template = self._template(tmp, COLLIDING_STYLES)
        # "54" 是真实设计文档里「标题 1 Char」字符样式的编号：不在段落样式集合中，
        # 级别 1 因此走 discovered 兜底分支。
        manifest = self._manifest({1: "54", 2: "4", 3: "5"})
        effective = _effective_heading_styles(manifest, template)
        self.assertEqual(effective[1], "2")
        self.assertEqual(manifest.headingStyles[1], "2")

    def test_genuinely_used_derived_style_is_preserved(self):
        """源文档真的在用派生样式时，清单值必须原样保留（不得改写既有语义）。"""
        from doc_tool.adapters.kernel import _effective_heading_styles

        tmp = tempfile.mkdtemp(prefix="doc-tool-heal-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        template = self._template(tmp, COLLIDING_STYLES)
        manifest = self._manifest({1: "140", 2: "4", 3: "5"})
        usage = heading_style_usage(
            parse_xml_safe(_document_xml([("140", 16)]), "word/document.xml")
        )
        effective = _effective_heading_styles(manifest, template, usage=usage)
        self.assertEqual(effective[1], "140")
        self.assertEqual(manifest.headingStyles[1], "140")

    def test_user_custom_style_without_heading_base_preserved(self):
        """用户手工映射的独立自定义样式（不基于 Heading）必须原样保留。"""
        from doc_tool.adapters.kernel import _effective_heading_styles

        styles = _styles_xml(
            '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="Normal"/></w:style>'
            + _builtin_heading("2", 1, 0)
            + '<w:style w:type="paragraph" w:customStyle="1" w:styleId="99">'
            '<w:name w:val="章标题"/><w:basedOn w:val="1"/></w:style>'
        )
        tmp = tempfile.mkdtemp(prefix="doc-tool-heal-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        template = self._template(tmp, styles)
        manifest = self._manifest({1: "99"})
        effective = _effective_heading_styles(manifest, template)
        self.assertEqual(effective[1], "99")


class RoundtripMapTests(unittest.TestCase):
    """往返门禁必须用「试构建实际写入的样式」识别标题。"""

    def test_manifest_map_forwarded_to_roundtrip(self):
        from unittest import mock

        from doc_tool.application.import_project import ImportRequest, _run_roundtrip_check

        request = ImportRequest(
            source_docx=Path("source.docx"),
            target_project_root=Path("target"),
            document_type="general",
            document_no="GX-TEST-010",
            document_name="往返映射",
            document_version="1.0",
        )
        with mock.patch("doc_tool.adapters.roundtrip.roundtrip_diff") as diff:
            diff.return_value = mock.Mock()
            _run_roundtrip_check(
                request, Path("source.docx"), "trial.docx", {1: "2", 2: "4"}
            )
        self.assertEqual(diff.call_args.kwargs.get("heading_styles"), {1: "2", 2: "4"})

    def test_user_map_takes_precedence(self):
        from unittest import mock

        from doc_tool.application.import_project import ImportRequest, _run_roundtrip_check

        request = ImportRequest(
            source_docx=Path("source.docx"),
            target_project_root=Path("target"),
            document_type="general",
            document_no="GX-TEST-011",
            document_name="用户映射优先",
            document_version="1.0",
            heading_style_map={"99": 1},
        )
        with mock.patch("doc_tool.adapters.roundtrip.roundtrip_diff") as diff:
            diff.return_value = mock.Mock()
            _run_roundtrip_check(
                request, Path("source.docx"), "trial.docx", {1: "2"}
            )
        self.assertEqual(diff.call_args.kwargs.get("heading_styles"), {1: "99"})


class RealTemplateTests(unittest.TestCase):
    """真实随包模板：设计模板必须已不再把 140 判成级别 1。"""

    def _resolve(self, name):
        path = Path(REPO_ROOT) / "templates" / name
        if not path.is_file():
            self.skipTest("模板缺失: {0}".format(path))
        with zipfile.ZipFile(str(path)) as archive:
            return resolve_heading_styles_from_xml(archive.read("word/styles.xml"))

    def test_design_template_prefers_builtin(self):
        resolved = self._resolve("design-template.docx")
        self.assertEqual(resolved.get(1), "2")
        self.assertNotEqual(resolved.get(1), "140")

    def test_requirement_template_unchanged(self):
        self.assertEqual(
            self._resolve("requirement-template.docx"),
            {1: "2", 2: "3", 3: "5", 4: "6", 5: "7", 6: "8"},
        )


if __name__ == "__main__":
    unittest.main()