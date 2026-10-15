# -*- coding: utf-8 -*-
"""多规则标题识别与可配置目录树打散策略专项单测。"""

from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from doc_tool.adapters.importer import split_into_tree
from doc_tool.adapters.preflight import preflight
from doc_tool.application.import_project import ImportRequest, import_first_time
from doc_tool.domain.split_rules import (
    CLUSTER_APPENDIX,
    CLUSTER_ENGINEERING,
    CLUSTER_ITEM_ANCHOR,
    CLUSTER_OFFICIAL_CN,
    NUMBERING_CLEAN_TITLE,
    NUMBERING_PRESERVE_SEMANTIC,
    PROFILE_AUTO_RULES,
    PROFILE_CHAPTER_ONLY,
    PROFILE_COMPACT,
    PROFILE_DEEP_ITEM,
    PROFILE_PRESERVE_NUMBERING,
    PROFILE_STANDARD,
    SplitPolicy,
    match_text_heading_rule,
    recognize_document_headings,
    strip_heading_prefix,
)

import contextlib
import shutil
from core_fixtures import scratch_dir


@contextlib.contextmanager
def core_tempdir(name: str):
    root = scratch_dir(name)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _make_rich_body_docx(path: Path, paragraphs: list[dict]) -> Path:
    """生成带自定义段落属性（numPr / 粗体 / 字号 / 居中）的无 Heading 样式 DOCX。"""
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{w_ns}">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>'
        "</w:styles>"
    )
    p_nodes = []
    for item in paragraphs:
        text = item.get("text", "")
        ppr_parts = ['<w:pStyle w:val="Normal"/>']
        if item.get("jc"):
            ppr_parts.append(f'<w:jc w:val="{item["jc"]}"/>')
        if item.get("ilvl") is not None:
            num_id = item.get("num_id", "1")
            ppr_parts.append(
                f'<w:numPr><w:ilvl w:val="{item["ilvl"]}"/><w:numId w:val="{num_id}"/></w:numPr>'
            )
        rpr_parts = []
        if item.get("bold"):
            rpr_parts.append("<w:b/>")
        if item.get("sz"):
            rpr_parts.append(f'<w:sz w:val="{item["sz"]}"/>')
        ppr_xml = f"<w:pPr>{''.join(ppr_parts)}</w:pPr>"
        rpr_xml = f"<w:rPr>{''.join(rpr_parts)}</w:rPr>" if rpr_parts else ""
        p_nodes.append(f"<w:p>{ppr_xml}<w:r>{rpr_xml}<w:t>{text}</w:t></w:r></w:p>")

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{w_ns}"><w:body>'
        + "".join(p_nodes)
        + "<w:sectPr/></w:body></w:document>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdStyles" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("word/styles.xml", styles_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
    return path


class MultiRuleRecognitionTests(unittest.TestCase):
    """验证工程编号、公文编号、附录编号、业务条目、骨架标题、numPr 与排版信号识别。"""

    def test_engineering_numbering_and_false_positive_guards(self):
        m1 = match_text_heading_rule("第1章 系统总体设计")
        self.assertIsNotNone(m1)
        self.assertEqual(m1.level, 1)
        self.assertEqual(m1.cluster, CLUSTER_ENGINEERING)

        m2 = match_text_heading_rule("1.1 功能架构")
        self.assertIsNotNone(m2)
        self.assertEqual(m2.level, 2)

        m3 = match_text_heading_rule("1.1.1 登录模块")
        self.assertIsNotNone(m3)
        self.assertEqual(m3.level, 3)

        m4 = match_text_heading_rule("1.1.1.1 令牌刷新机制")
        self.assertIsNotNone(m4)
        self.assertEqual(m4.level, 4)

        # 句末标点与裸版本号绝不误判为标题
        self.assertIsNone(match_text_heading_rule("1.1 本节用于说明系统架构的整体原则。"))
        self.assertIsNone(match_text_heading_rule("3.0.0"))
        self.assertIsNone(match_text_heading_rule("2026.10.15"))

    def test_official_chinese_and_appendix_numbering(self):
        c1 = match_text_heading_rule("一、建设背景与目标")
        self.assertIsNotNone(c1)
        self.assertEqual((c1.level, c1.cluster), (1, CLUSTER_OFFICIAL_CN))

        c2 = match_text_heading_rule("（一）总体建设目标")
        self.assertIsNotNone(c2)
        self.assertEqual((c2.level, c2.cluster), (2, CLUSTER_OFFICIAL_CN))

        c3 = match_text_heading_rule("1、阶段性指标")
        self.assertIsNotNone(c3)
        self.assertEqual((c3.level, c3.cluster), (3, CLUSTER_OFFICIAL_CN))

        c4 = match_text_heading_rule("（1）性能指标")
        self.assertIsNotNone(c4)
        self.assertEqual((c4.level, c4.cluster), (4, CLUSTER_OFFICIAL_CN))

        a1 = match_text_heading_rule("附录A 术语与缩略语")
        self.assertIsNotNone(a1)
        self.assertEqual((a1.level, a1.cluster), (1, CLUSTER_APPENDIX))

        a2 = match_text_heading_rule("A.1 核心术语")
        self.assertIsNotNone(a2)
        self.assertEqual((a2.level, a2.cluster), (2, CLUSTER_APPENDIX))

        a3 = match_text_heading_rule("A.1.1 缩略语明细")
        self.assertIsNotNone(a3)
        self.assertEqual((a3.level, a3.cluster), (3, CLUSTER_APPENDIX))

    def test_item_anchor_and_skeleton_matching(self):
        # 默认不开启业务条目切分时，[REQ-001] 不升格为章节标题
        self.assertIsNone(match_text_heading_rule("[REQ-001] 用户登录认证", split_item_anchors=False))
        # 开启 split_item_anchors 时升格为父级 + 1 级标题
        anchor = match_text_heading_rule(
            "[REQ-001] 用户登录认证", parent_level=2, split_item_anchors=True
        )
        self.assertIsNotNone(anchor)
        self.assertEqual((anchor.level, anchor.cluster), (3, CLUSTER_ITEM_ANCHOR))

        skel = match_text_heading_rule(
            "3. 接口设计", skeleton_titles=("概述", "接口设计", "部署方案")
        )
        self.assertIsNotNone(skel)
        self.assertEqual(skel.rule, "skeleton")

    def test_ooxml_numpr_and_typography_signals(self):
        with core_tempdir("numpr-signals") as root:
            docx_path = _make_rich_body_docx(
                root / "signals.docx",
                [
                    {"text": "系统总体方案", "bold": True, "sz": 32, "jc": "center"},
                    {"text": "概述说明正文段落，包含充足的上下文描述信息。"},
                    {"text": "功能架构设计", "ilvl": 0, "bold": True, "sz": 28},
                    {"text": "权限子模块", "ilvl": 1, "bold": True, "sz": 24},
                    {"text": "本段为权限子模块的详细业务说明，包含完整句子。"},
                ],
            )
            with zipfile.ZipFile(docx_path) as zf:
                parts = {
                    "word/document.xml": zf.read("word/document.xml"),
                    "word/styles.xml": zf.read("word/styles.xml"),
                }
            policy = SplitPolicy.from_profile(PROFILE_AUTO_RULES)
            matches = recognize_document_headings(parts, {}, policy=policy)
            levels = [(m.text, m.level, m.rule) for m in matches]
            self.assertEqual(len(levels), 3)
            self.assertEqual(levels[0][0], "系统总体方案")
            self.assertEqual(levels[0][1], 1)
            self.assertEqual(levels[1], ("功能架构设计", 1, "numpr_list"))
            self.assertEqual(levels[2], ("权限子模块", 2, "numpr_list"))


class SplitPolicyTreeTests(unittest.TestCase):
    """验证 SplitPolicy 4 档深度、跳级桥接、防碎片最小字数内聚、编号保留模式。"""

    def _write_stage_md(self, folder: Path, content: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        md = folder / "01-chapter.md"
        md.write_text(content, encoding="utf-8")
        return md

    def test_chapter_only_and_compact_profiles(self):
        sample = "\n".join([
            "# 引言",
            "本章导言。",
            "## 目的",
            "目的正文。",
            "### 细则",
            "细则正文。",
        ])
        with core_tempdir("split-profiles") as root:
            # 1. chapter_only：只拆到第1章目录，## 与 ### 留在 _index.md
            c_dir = root / "chapter_only"
            self._write_stage_md(c_dir, sample)
            stats1 = split_into_tree(c_dir, policy=SplitPolicy.from_profile(PROFILE_CHAPTER_ONLY))
            self.assertEqual((stats1.dirs, stats1.mds, stats1.indexes), (1, 0, 1))
            index_txt = (c_dir / "第1章 引言" / "_index.md").read_text(encoding="utf-8")
            self.assertIn("## 目的", index_txt)
            self.assertIn("### 细则", index_txt)

            # 2. compact (max_split_depth=2)：拆到 1.1 目的.md，### 留在 1.1 目的.md 内
            k_dir = root / "compact"
            self._write_stage_md(k_dir, sample)
            stats2 = split_into_tree(k_dir, policy=SplitPolicy.from_profile(PROFILE_COMPACT))
            self.assertEqual((stats2.dirs, stats2.mds, stats2.indexes), (1, 1, 1))
            leaf_txt = (k_dir / "第1章 引言" / "1.1 目的.md").read_text(encoding="utf-8")
            self.assertIn("### 细则", leaf_txt)

    def test_bridge_jumped_levels(self):
        sample = "\n".join([
            "# 系统架构",
            "架构导言。",
            "### 跳级三级小节",
            "原本会因缺少二级父节点被吞入 _index.md 的正文。",
        ])
        with core_tempdir("bridge-jumps") as root:
            s_dir = root / "bridged"
            self._write_stage_md(s_dir, sample)
            stats = split_into_tree(s_dir, policy=SplitPolicy.from_profile(PROFILE_STANDARD))
            self.assertEqual(stats.bridged_jumps, 1)
            self.assertTrue((s_dir / "第1章 系统架构" / "1.1 跳级三级小节.md").is_file())

    def test_anti_fragmentation_coalesces_tiny_leaves_only(self):
        long_text = "这是一段足够长的详细设计正文内容，" * 10
        sample = "\n".join([
            "# 核心设计",
            "## 简短小节",
            "### 简短条目A",
            "仅十余字。",
            "### 简短条目B",
            "也很短。",
            "## 充实小节",
            "### 充实条目A",
            long_text,
        ])
        with core_tempdir("anti-frag") as root:
            f_dir = root / "coalesce"
            self._write_stage_md(f_dir, sample)
            policy = SplitPolicy(max_split_depth=3, min_leaf_chars=80)
            stats = split_into_tree(f_dir, policy=policy)
            self.assertEqual(stats.coalesced_nodes, 2)
            # 1.1 简短小节 因全部子叶子均短于 80 字，内聚为单个 .md 文件
            short_md = f_dir / "第1章 核心设计" / "1.1 简短小节.md"
            self.assertTrue(short_md.is_file())
            self.assertIn("### 简短条目A", short_md.read_text(encoding="utf-8"))
            # 1.2 充实小节 含有长文本子叶子，保持目录 + 1.2.1 充实条目A.md
            rich_md = f_dir / "第1章 核心设计" / "1.2 充实小节" / "1.2.1 充实条目A.md"
            self.assertTrue(rich_md.is_file())

    def test_deep_item_splits_four_levels_and_item_anchors(self):
        sample = "\n".join([
            "# 功能需求",
            "## 用户管理",
            "### 认证子模块",
            "[REQ-001] 密码复杂度校验",
            "密码必须至少包含 8 位字符。",
            "[REQ-002] 登录失败锁定",
            "连续失败 5 次后锁定账户 15 分钟。",
        ])
        with core_tempdir("deep-item") as root:
            d_dir = root / "deep"
            self._write_stage_md(d_dir, sample)
            policy = SplitPolicy.from_profile(PROFILE_DEEP_ITEM)
            stats = split_into_tree(d_dir, policy=policy)
            self.assertEqual(stats.max_depth_reached, 4)
            self.assertEqual(stats.rule_promoted_nodes, 2)
            req1 = (
                d_dir
                / "第1章 功能需求"
                / "1.1 用户管理"
                / "1.1.1 认证子模块"
                / "1.1.1.1 [REQ-001] 密码复杂度校验.md"
            )
            req2 = (
                d_dir
                / "第1章 功能需求"
                / "1.1 用户管理"
                / "1.1.1 认证子模块"
                / "1.1.1.2 [REQ-002] 登录失败锁定.md"
            )
            self.assertTrue(req1.is_file())
            self.assertTrue(req2.is_file())

    def test_strip_heading_prefix_modes(self):
        self.assertEqual(
            strip_heading_prefix("第1章 总体概述", mode=NUMBERING_PRESERVE_SEMANTIC),
            "总体概述",
        )
        self.assertEqual(
            strip_heading_prefix("1.2 接口要求", mode=NUMBERING_PRESERVE_SEMANTIC),
            "接口要求",
        )
        # 语义前缀（公文/附录/条目锚点）在 NUMBERING_PRESERVE_SEMANTIC 下保留
        self.assertEqual(
            strip_heading_prefix("一、总体要求", mode=NUMBERING_PRESERVE_SEMANTIC),
            "一、总体要求",
        )
        self.assertEqual(
            strip_heading_prefix("附录A 术语", mode=NUMBERING_PRESERVE_SEMANTIC),
            "附录A 术语",
        )
        # NUMBERING_CLEAN_TITLE 彻底剥离前缀
        self.assertEqual(
            strip_heading_prefix("一、总体要求", mode=NUMBERING_CLEAN_TITLE),
            "总体要求",
        )


class EndToEndRuleImportAndPresetTests(unittest.TestCase):
    """验证无 Heading 样式的编号 Word 文档通过多规则识别完成首次导入与预设复用。"""

    def test_headless_numbered_docx_imports_into_multi_file_tree_and_saves_preset(self):
        with core_tempdir("e2e-rule-import") as root:
            src = _make_rich_body_docx(
                root / "numbered-normal.docx",
                [
                    {"text": "第1章 项目概述"},
                    {"text": "本项目旨在提升文档拆解与结构化治理能力。"},
                    {"text": "1.1 建设背景"},
                    {"text": "现有外部 Word 文档常缺失标准 Heading 样式。"},
                    {"text": "1.2 建设目标"},
                    {"text": "支持多规则识别与可配置打散深度。"},
                    {"text": "第2章 技术方案"},
                    {"text": "2.1 规则引擎设计"},
                    {"text": "综合利用编号簇、列表层级与排版特征。"},
                ],
            )
            # 1. 默认无参 preflight 保持向后兼容（has_heading1=False，但产出 rule_headings 与推荐策略）
            default_preview = preflight(str(src), allow_missing_headings=True)
            self.assertFalse(default_preview.has_heading1)
            self.assertGreaterEqual(len(default_preview.rule_headings), 5)
            self.assertIsNotNone(default_preview.recommended_split_policy)

            # 2. 使用 preserve_numbering 策略导入：自动拆分为 2 章、3 个二级 .md 文件并保存预设
            target1 = root / "proj-rule-1"
            req1 = ImportRequest(
                source_docx=src,
                target_project_root=target1,
                document_type="general",
                document_no="SPEC-001",
                document_name="多规则拆分规范",
                document_version="1.0",
                split_policy=PROFILE_PRESERVE_NUMBERING,
                intakeSavePreset="无样式编号拆分配方",
            )
            res1 = import_first_time(req1)
            self.assertTrue(res1.success, f"import failed: {res1.error_code} {res1.events}")
            self.assertEqual(res1.savedPreset, "无样式编号拆分配方")

            content_root = target1 / "content" / "general"
            self.assertTrue((content_root / "第1章 项目概述" / "_index.md").is_file())
            self.assertTrue((content_root / "第1章 项目概述" / "1.1 建设背景.md").is_file())
            self.assertTrue((content_root / "第1章 项目概述" / "1.2 建设目标.md").is_file())
            self.assertTrue((content_root / "第2章 技术方案" / "2.1 规则引擎设计.md").is_file())

            # 3. 第二份同类无样式文档直接复用已保存预设「无样式编号拆分配方」
            target2 = root / "proj-rule-2"
            req2 = ImportRequest(
                source_docx=src,
                target_project_root=target2,
                document_type="general",
                document_no="SPEC-002",
                document_name="多规则预设复用",
                document_version="1.0",
                intakePresetName="无样式编号拆分配方",
            )
            res2 = import_first_time(req2)
            self.assertTrue(res2.success, f"preset import failed: {res2.error_code} {res2.events}")
            content_root2 = target2 / "content" / "general"
            self.assertTrue((content_root2 / "第1章 项目概述" / "1.1 建设背景.md").is_file())
            self.assertTrue((content_root2 / "第2章 技术方案" / "2.1 规则引擎设计.md").is_file())


if __name__ == "__main__":
    unittest.main()
