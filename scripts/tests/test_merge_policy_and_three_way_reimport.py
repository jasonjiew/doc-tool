# -*- coding: utf-8 -*-
"""方向 1 / 2 / 3 / 5 专项测试：MergePolicy 容错合入、范围/变体构建、静态 TOC 域合成与块级三方重导入合并。"""

from __future__ import annotations

import hashlib
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

from core_fixtures import two_chapter_project  # noqa: E402
from docx_common import AutomationError, iter_chapter_entries, validate_content_tree  # noqa: E402
from validate_docx import DocxPackage  # noqa: E402
from doc_tool.adapters.kernel import (  # noqa: E402
    build_with_project,
    config_from_project,
    validate_with_project,
)
from doc_tool.application.content.reimport import (  # noqa: E402
    ReimportService,
    compare_chapters,
    merge_markdown_blocks_three_way,
)
from doc_tool.application.pipeline import run_pipeline  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.merge_policy import (  # noqa: E402
    HEADING_NUM_LITERAL,
    MERGE_PROFILE_TOLERANT,
    MergePolicy,
    SCOPED_MERGE_POLICY,
    STRICT_MERGE_POLICY,
    TOLERANT_MERGE_POLICY,
    shift_inline_headings_for_depth,
)
from doc_tool.domain.paths import ProjectPaths  # noqa: E402


class MergePolicyAndTreeTests(unittest.TestCase):
    """方向 1：断号顺延、无编号/中文编号兼容、行内标题自动平移、显式编号前缀合成。"""

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="merge-policy-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = two_chapter_project(self.work / "proj")
        self.manifest = ProjectManifest.load(self.project)
        self.paths = ProjectPaths(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())

    def test_tolerant_policy_renumbers_gaps_and_unnumbered_files(self) -> None:
        # 制造断号（删除第2章后新增第3章、中文编号章与无编号附录）
        (self.content_root / "第3章 系统架构.md").write_text("架构描述正文。\n", encoding="utf-8")
        (self.content_root / "四、安全设计.md").write_text("安全设计正文。\n", encoding="utf-8")
        (self.content_root / "附录说明.md").write_text("附录正文。\n", encoding="utf-8")

        # 严格策略下应当报错阻断
        strict_cfg = config_from_project(self.manifest, self.paths, merge_policy=STRICT_MERGE_POLICY)
        with self.assertRaises(AutomationError):
            validate_content_tree(strict_cfg)

        # 容错策略下自动顺延为连续编号并通过构建与校验
        tolerant_cfg = config_from_project(self.manifest, self.paths, merge_policy=TOLERANT_MERGE_POLICY)
        entries = validate_content_tree(tolerant_cfg)
        top_entries = [e for e in entries if e.depth == 1]
        self.assertEqual([e.number for e in top_entries], [(1,), (2,), (3,), (4,), (5,)])
        self.assertTrue(tolerant_cfg.get("_mergeWarnings"))

        out_docx = self.paths.output_dir / "tolerant_out.docx"
        built = build_with_project(
            self.manifest,
            self.paths,
            output_override=out_docx,
            merge_policy=TOLERANT_MERGE_POLICY,
        )
        self.assertTrue(Path(built).is_file())
        self.assertTrue(
            validate_with_project(
                self.manifest,
                self.paths,
                output_override=out_docx,
                merge_policy=TOLERANT_MERGE_POLICY,
            )
        )

    def test_inline_heading_auto_shift_preserves_code_fences(self) -> None:
        md_file = self.content_root / "第1章 引言" / "1.1 目的.md"
        md_file.write_text(
            "引言说明。\n\n"
            "# 顶层越界小节\n\n"
            "```python\n"
            "# 代码注释不应被平移\n"
            "print('ok')\n"
            "```\n\n"
            "## 二级子小节\n\n"
            "子小节正文。\n",
            encoding="utf-8",
        )
        # depth=2 时，严格模式拒绝 H1/H2 行内标题
        strict_cfg = config_from_project(self.manifest, self.paths, merge_policy=STRICT_MERGE_POLICY)
        with self.assertRaises(AutomationError):
            validate_content_tree(strict_cfg)

        # 容错模式自动将 H1->H3、H2->H4，且代码块内注释保持不变
        shifted, delta = shift_inline_headings_for_depth(
            md_file.read_text(encoding="utf-8"), 2, enabled=True
        )
        self.assertEqual(delta, 2)
        self.assertIn("### 顶层越界小节", shifted)
        self.assertIn("#### 二级子小节", shifted)
        self.assertIn("# 代码注释不应被平移", shifted)

        out_docx = self.paths.output_dir / "shifted_out.docx"
        build_with_project(
            self.manifest,
            self.paths,
            output_override=out_docx,
            merge_policy=TOLERANT_MERGE_POLICY,
        )
        self.assertTrue(
            validate_with_project(
                self.manifest,
                self.paths,
                output_override=out_docx,
                merge_policy=TOLERANT_MERGE_POLICY,
            )
        )

    def test_literal_heading_number_synthesis(self) -> None:
        literal_policy = MergePolicy(
            profile=MERGE_PROFILE_TOLERANT,
            renumber_mode="auto_contiguous",
            auto_shift_inline_headings=True,
            heading_number_mode=HEADING_NUM_LITERAL,
        )
        out_docx = self.paths.output_dir / "literal_num.docx"
        build_with_project(
            self.manifest,
            self.paths,
            output_override=out_docx,
            merge_policy=literal_policy,
        )
        pkg = DocxPackage(str(out_docx), heading_styles=self.manifest.headingStyles)
        headings = [ev.value for ev in pkg.body_events() if ev.kind == "H"]
        self.assertTrue(any(lvl == 1 and text.startswith("第1章") for lvl, text in headings))
        self.assertTrue(any(lvl == 2 and text.startswith("1.1") for lvl, text in headings))
        self.assertTrue(
            validate_with_project(
                self.manifest,
                self.paths,
                output_override=out_docx,
                merge_policy=literal_policy,
            )
        )


class ChapterOrderScopeAndVariantTests(unittest.TestCase):
    """方向 2 & 5：chapterOrder 显式编排、局部章节范围合并、单变体正式构建与静态 TOC 缓存。"""

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="order-scope-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = two_chapter_project(self.work / "proj")
        self.manifest = ProjectManifest.load(self.project)
        self.paths = ProjectPaths(self.project)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())

    def test_chapter_order_reorders_chapters_in_build_and_validate(self) -> None:
        # 将第2章排在第1章之前
        self.manifest.chapters = ["第2章 设计", "第1章 引言"]
        self.manifest.save(self.project)

        cfg = config_from_project(self.manifest, self.paths)
        entries = [entry for entry, _ in iter_chapter_entries(cfg) if entry.depth == 1]
        self.assertEqual([e.title for e in entries], ["设计", "引言"])
        self.assertEqual([e.number for e in entries], [(1,), (2,)])

        out_docx = self.paths.output_dir / "reordered.docx"
        build_with_project(self.manifest, self.paths, output_override=out_docx)
        self.assertTrue(
            validate_with_project(self.manifest, self.paths, output_override=out_docx)
        )

    def test_scoped_chapter_merge_builds_selected_subset_only(self) -> None:
        out_docx = self.paths.output_dir / "scoped_ch2.docx"
        build_with_project(
            self.manifest,
            self.paths,
            output_override=out_docx,
            chapter_scope=["第2章 设计"],
        )
        pkg = DocxPackage(str(out_docx), heading_styles=self.manifest.headingStyles)
        h1_titles = [ev.value[1] for ev in pkg.body_events() if ev.kind == "H" and ev.value[0] == 1]
        self.assertEqual(len(h1_titles), 1)
        self.assertIn("设计", h1_titles[0])
        self.assertTrue(
            validate_with_project(
                self.manifest,
                self.paths,
                output_override=out_docx,
                chapter_scope=["第2章 设计"],
            )
        )

    def test_variant_pipeline_builds_filtered_chapters_and_variables(self) -> None:
        # 在第2章写入变量占位，并配置 variants.yml 只包含第2章且注入变量
        ch2_files = list((self.content_root / "第2章 设计").glob("*.md"))
        self.assertTrue(ch2_files)
        ch2_files[0].write_text("本模块面向 {{client_name}} 提供服务。\n", encoding="utf-8")

        variants_yml = (
            "schemaVersion: 1\n"
            "variants:\n"
            "  - variantId: enterprise\n"
            "    name: 企业版\n"
            "    include:\n"
            "      - 第2章 设计\n"
            "    variables:\n"
            "      client_name: 星河智联专有云\n"
        )
        (self.project / "variants.yml").write_text(variants_yml, encoding="utf-8")

        res = run_pipeline(
            self.manifest,
            self.paths,
            skip_word_refresh=True,
            variant_id="enterprise",
        )
        self.assertTrue(res.success, [ (e.stage, e.status, e.detail) for e in res.events ])
        self.assertIsNotNone(res.output_path)
        self.assertIn("enterprise", Path(res.output_path).parts)
        pkg = DocxPackage(res.output_path, heading_styles=self.manifest.headingStyles)
        events = pkg.body_events()
        self.assertTrue(any(ev.kind == "P" and "星河智联专有云" in ev.value for ev in events))
        h1_titles = [ev.value[1] for ev in events if ev.kind == "H" and ev.value[0] == 1]
        self.assertEqual(len(h1_titles), 1)

    def test_static_toc_cache_synthesized_without_word_refresh(self) -> None:
        # The fixture's normal template has no TOC. Add an actual complex
        # field so an empty cache cannot make this test pass vacuously.
        from docx import Document
        from docx.oxml import parse_xml

        template = Path(config_from_project(self.manifest, self.paths)["paths"]["template"])
        document = Document(str(template))
        toc = parse_xml(r'''<w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:sdtContent>
            <w:p><w:r><w:t>目录</w:t></w:r></w:p>
            <w:p>
              <w:r><w:fldChar w:fldCharType="begin"/></w:r>
              <w:r><w:instrText xml:space="preserve"> TOC \o "1-3" \h \z \u </w:instrText></w:r>
              <w:r><w:fldChar w:fldCharType="separate"/></w:r>
              <w:r><w:fldChar w:fldCharType="end"/></w:r>
            </w:p>
          </w:sdtContent>
        </w:sdt>''')
        document.element.body.insert(0, toc)
        document.save(str(template))
        # 新增第3章后构建（不经 Word 刷新），静态 TOC 缓存应立即包含第1、2、3章
        (self.content_root / "第3章 部署方案.md").write_text("部署正文。\n", encoding="utf-8")
        out_docx = self.paths.output_dir / "static_toc.docx"
        build_with_project(self.manifest, self.paths, output_override=out_docx)
        pkg = DocxPackage(str(out_docx), heading_styles=self.manifest.headingStyles)
        toc_cached = pkg.toc_cached_paragraphs()
        self.assertTrue(toc_cached, "Static TOC cache must not be empty")
        joined = "\n".join(toc_cached)
        self.assertIn("部署方案", joined)


class BlockLevelThreeWayReimportTests(unittest.TestCase):
    """方向 3：块级三方重导入合并（非重叠块修改自动合入 + 块级冲突精准定位）。"""

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="block-3way-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = two_chapter_project(self.work / "proj")
        self.manifest = ProjectManifest.load(self.project)
        self.paths = ProjectPaths(self.project)
        self.service = ReimportService(self.manifest, self.paths)
        self.content_root = self.paths.resolve(self.manifest.relative_content_root())

    def test_direct_three_way_block_merge_non_overlapping_and_adjacent(self) -> None:
        base_md = (
            "### 业务概述\n\n"
            "第一段：原始基线说明。\n\n"
            "第二段：原始流程描述。\n\n"
            "| 参数 | 默认值 |\n"
            "| --- | --- |\n"
            "| timeout | 30s |\n"
        )
        # 本地修改了第一段，外部修改了第二段与表格（第一段与第二段相邻）
        local_md = (
            "### 业务概述\n\n"
            "第一段：本地作者已补充安全约束说明。\n\n"
            "第二段：原始流程描述。\n\n"
            "| 参数 | 默认值 |\n"
            "| --- | --- |\n"
            "| timeout | 30s |\n"
        )
        incoming_md = (
            "### 业务概述\n\n"
            "第一段：原始基线说明。\n\n"
            "第二段：外部 Word 评审修订了流程描述。\n\n"
            "| 参数 | 默认值 |\n"
            "| --- | --- |\n"
            "| timeout | 60s |\n\n"
            "第三段：外部新增备注段落。\n"
        )
        res = merge_markdown_blocks_three_way(
            base_md, local_md, incoming_md, rel_path="第1章 引言/1.1 目的.md"
        )
        self.assertTrue(res.clean)
        self.assertTrue(res.auto_merged)
        self.assertIn("第一段：本地作者已补充安全约束说明。", res.merged_text)
        self.assertIn("第二段：外部 Word 评审修订了流程描述。", res.merged_text)
        self.assertIn("| timeout | 60s |", res.merged_text)
        self.assertIn("第三段：外部新增备注段落。", res.merged_text)

    def test_direct_three_way_block_merge_overlapping_reports_block_conflict(self) -> None:
        base_md = "第一段基线。\n\n第二段基线。\n"
        local_md = "第一段本地改为 A。\n\n第二段基线。\n"
        incoming_md = "第一段外部改为 B。\n\n第二段外部同时修改。\n"

        res = merge_markdown_blocks_three_way(
            base_md, local_md, incoming_md, rel_path="1.1 目的.md"
        )
        self.assertFalse(res.clean)
        self.assertEqual(len(res.conflicts), 1)
        conflict = res.conflicts[0]
        self.assertEqual(conflict.block_kind, "paragraph")
        self.assertIn("第一段本地改为 A。", conflict.local_text)
        self.assertIn("第一段外部改为 B。", conflict.incoming_text)

    def test_reimport_service_auto_merges_non_overlapping_chapter_edits(self) -> None:
        target_rel = "第1章 引言/1.1 目的.md"
        target_file = self.content_root / target_rel
        base_text = (
            "第一段：初始导入基线内容。\n\n"
            "第二段：初始导入架构说明。\n"
        )
        target_file.write_text(base_text, encoding="utf-8")

        # 写入含 contents 的 reimport_base.json 基线
        hashes = {}
        contents = {}
        for p in self.content_root.rglob("*.md"):
            if p.is_file() and not p.name.startswith("_revision"):
                rel = p.relative_to(self.content_root).as_posix()
                hashes[rel] = hashlib.sha1(p.read_bytes()).hexdigest()
                contents[rel] = p.read_text(encoding="utf-8")
        (self.paths.state_dir / "reimport_base.json").write_text(
            json.dumps({"files": hashes, "contents": contents}, ensure_ascii=False),
            encoding="utf-8",
        )

        # 本地编辑第一段
        target_file.write_text(
            "第一段：本地工程师修改了第一段。\n\n"
            "第二段：初始导入架构说明。\n",
            encoding="utf-8",
        )

        # 构造外部传入目录：外部编辑了同一文件的第二段
        incoming_dir = self.work / "incoming"
        for rel, txt in contents.items():
            out_p = incoming_dir / rel
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(txt, encoding="utf-8")
        (incoming_dir / target_rel).write_text(
            "第一段：初始导入基线内容。\n\n"
            "第二段：外部客户在 Word 中修改了第二段。\n",
            encoding="utf-8",
        )

        changes = compare_chapters(
            self.content_root,
            incoming_dir,
            self.service._base_hashes(),
            self.service._base_texts(),
        )
        by_rel = {c.rel_path: c for c in changes}
        ch = by_rel[target_rel]
        self.assertEqual(ch.status, "modified")
        self.assertFalse(ch.conflict)
        self.assertTrue(ch.use_new)
        self.assertTrue(ch.auto_merged)

        # 执行 reimport 应用合并结果
        dummy_source = self.paths.resolve(self.manifest.relative_source_docx())

        def _extract(_src: Path, dst: Path) -> None:
            for item in incoming_dir.rglob("*.md"):
                rel = item.relative_to(incoming_dir).as_posix()
                out = dst / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")

        result = self.service.reimport(dummy_source, extractor=_extract)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.conflicts, [])

        merged_on_disk = target_file.read_text(encoding="utf-8")
        self.assertIn("第一段：本地工程师修改了第一段。", merged_on_disk)
        self.assertIn("第二段：外部客户在 Word 中修改了第二段。", merged_on_disk)


if __name__ == "__main__":
    unittest.main()
