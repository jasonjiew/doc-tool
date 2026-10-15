# -*- coding: utf-8 -*-
"""主流程 6 大智能化特性专项单元测试。

覆盖：
1. 导入提取阶段：内联富文本格式还原、连续代码行智能聚类、图表题注与正文引用自动绑定
2. 引用与编辑阶段：自然语言题注（免 {#id}）与自然中文交叉引用（见图《xxx》/表/章节）动态域生成
3. 重导入合并阶段：跨文件章节改名/顺延移位内容指纹对齐 + Markdown 表格行/单元格级三方合并
4. 复杂表格（XML Table）阶段：可读 Markdown 代理表生成、解析跳过与单元格文字修改精准回填 <w:tc>
5. 正式合入排版阶段：无元数据手写表格自适应列宽计算、超宽大表自动横版分节、无尺寸图片智能 DPI 缩放
6. 修订记录与版本阶段：基于基线快照差异的智能修订摘要生成与版本号自动演进
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from core_fixtures import scratch_dir, two_chapter_project
from doc_tool.adapters.importer import extract_content
from doc_tool.adapters.kernel import ensure_kernel_importable
from doc_tool.application.content.reimport import (
    ReimportService,
    compare_chapters,
    merge_markdown_blocks_three_way,
    merge_table_block_three_way,
)
from doc_tool.application.content.revision_record import (
    append_smart_revision_entry,
    bump_revision_version,
    generate_smart_revision_summary,
)
from doc_tool.application.pipeline import run_pipeline
from doc_tool.domain.blocks import (
    KIND_COMPLEX_TABLE,
    KIND_IMAGE,
    KIND_TABLE,
    parse_blocks,
)
from doc_tool.domain.captions import build_registry, resolve_inline_references
from doc_tool.domain.markdown_structure import check_table_structure
from doc_tool.domain.smart_features import (
    apply_complex_table_proxy_edits,
    bind_imported_captions_and_references,
    compute_smart_column_widths,
    estimate_unannotated_table_natural_width,
    extract_complex_table_proxy_rows,
    format_complex_table_proxy_lines,
)
ensure_kernel_importable()
from build_docx import image_size_emu
from docx_common import ImageReference

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def qn(prefix: str, local: str) -> str:
    return "{{{0}}}{1}".format(NS[prefix], local)


class SmartMainflowFeaturesTest(unittest.TestCase):
    def setUp(self) -> None:
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        self.root = scratch_dir("smart_mainflow_features")
        self.project_root = two_chapter_project(self.root)
        self.manifest = ProjectManifest.load(self.project_root)
        self.paths = ProjectPaths(self.project_root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------------
    # Direction 1: 导入提取智能化（内联格式、代码块聚类、题注与引用自动绑定）
    # ------------------------------------------------------------------
    def test_direction1_smart_import_inline_code_and_caption_binding(self) -> None:
        lines = [
            "系统架构如图 1-1 所示，核心参数配置参见表 1-1。",
            "",
            "![img_0001.png](../../assets/images/img_0001.png =400x200)",
            "",
            "图 1-1 系统部署架构图",
            "",
            "表 1-1 核心配置参数表",
            "",
            "<!-- TBL:cols=3000,5000 -->",
            "| 参数名 | 说明 |",
            "| --- | --- |",
            "| timeout | 超时时间 |",
        ]
        bound_map = bind_imported_captions_and_references(lines)
        self.assertIn("fig:1-1", bound_map)
        self.assertIn("tbl:1-1", bound_map)
        joined = "\n".join(lines)
        # 图片与表格均自动绑定稳定 {#fig-...} / {#tbl-...} 锚点
        self.assertIn("Figure: 系统部署架构图 {#fig-1-1}", joined)
        self.assertIn("Table: 核心配置参数表 {#tbl-1-1}", joined)
        # 正文中的 "图 1-1" 和 "表 1-1" 自动替换为动态交叉引用 @fig-... / @tbl-...
        self.assertIn("如@fig-1-1 所示", joined)
        self.assertIn("参见@tbl-1-1", joined)

        # 构造带加粗、斜体、等宽代码段与连续代码段落的测试 docx 并执行 extract_content
        src_docx = self.root / "smart_import_src.docx"
        tpl_docx = self.paths.resolve(self.manifest.relative_template_docx())
        shutil.copyfile(tpl_docx, src_docx)

        with zipfile.ZipFile(src_docx, "r") as zin:
            entries = {name: zin.read(name) for name in zin.namelist()}
        doc_xml = ET.fromstring(entries["word/document.xml"])
        body = doc_xml.find("w:body", NS)
        sect_pr = body.find("w:sectPr", NS)
        for child in list(body):
            if child is not sect_pr:
                body.remove(child)

        def _add_heading(text: str, style_id: str) -> None:
            p = ET.Element(qn("w", "p"))
            ppr = ET.SubElement(p, qn("w", "pPr"))
            ET.SubElement(ppr, qn("w", "pStyle"), {qn("w", "val"): style_id})
            r = ET.SubElement(p, qn("w", "r"))
            t = ET.SubElement(r, qn("w", "t"))
            t.text = text
            body.insert(len(list(body)) - (1 if sect_pr is not None else 0), p)

        _add_heading("第1章 引言", "1")
        _add_heading("1.1 目的", "11")

        # 富文本段落：包含普通文本 + 加粗 + 斜体 + Consolas 内联代码
        p_rich = ET.Element(qn("w", "p"))
        r1 = ET.SubElement(p_rich, qn("w", "r"))
        ET.SubElement(r1, qn("w", "t")).text = "本节说明"
        r2 = ET.SubElement(p_rich, qn("w", "r"))
        r2_pr = ET.SubElement(r2, qn("w", "rPr"))
        ET.SubElement(r2_pr, qn("w", "b"))
        ET.SubElement(r2, qn("w", "t")).text = "核心接口"
        r3 = ET.SubElement(p_rich, qn("w", "r"))
        r3_pr = ET.SubElement(r3, qn("w", "rPr"))
        ET.SubElement(r3_pr, qn("w", "i"))
        ET.SubElement(r3, qn("w", "t")).text = "约束条件"
        r4 = ET.SubElement(p_rich, qn("w", "r"))
        r4_pr = ET.SubElement(r4, qn("w", "rPr"))
        ET.SubElement(r4_pr, qn("w", "rFonts"), {qn("w", "ascii"): "Consolas"})
        ET.SubElement(r4, qn("w", "t")).text = "max_retry=3"
        body.insert(len(list(body)) - (1 if sect_pr is not None else 0), p_rich)

        # 连续 3 段 Consolas 代码行 -> 应自动聚类为围栏代码块
        for code_line in ("import json", "def parse_payload(raw):", "    return json.loads(raw)"):
            p_code = ET.Element(qn("w", "p"))
            r_c = ET.SubElement(p_code, qn("w", "r"))
            r_cpr = ET.SubElement(r_c, qn("w", "rPr"))
            ET.SubElement(r_cpr, qn("w", "rFonts"), {qn("w", "ascii"): "Consolas"})
            ET.SubElement(r_c, qn("w", "t")).text = code_line
            body.insert(len(list(body)) - (1 if sect_pr is not None else 0), p_code)

        entries["word/document.xml"] = ET.tostring(doc_xml, encoding="utf-8", xml_declaration=True)
        with zipfile.ZipFile(src_docx, "w", zipfile.ZIP_DEFLATED) as zout:
            for name, data in entries.items():
                zout.writestr(name, data)

        out_content = self.root / "extracted_content"
        out_assets = self.root / "extracted_assets"
        out_tables = self.root / "extracted_tables"
        extract_content(
            str(src_docx),
            str(out_content),
            str(out_assets),
            str(out_tables),
            "design",
            heading_style_map={"1": 1, "11": 2},
        )
        md_files = list(out_content.rglob("*.md"))
        self.assertTrue(md_files)
        md_text = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
        self.assertIn("**核心接口**", md_text)
        self.assertIn("*约束条件*", md_text)
        self.assertIn("`max_retry=3`", md_text)
        self.assertIn("```python\nimport json\ndef parse_payload(raw):\n    return json.loads(raw)\n```", md_text)

    # ------------------------------------------------------------------
    # Direction 2: 自然语言题注（免 {#id}）与自然中文交叉引用
    # ------------------------------------------------------------------
    def test_direction2_natural_caption_and_chinese_xref_build(self) -> None:
        img_dir = self.paths.resolve(self.manifest.relative_asset_root()) / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / "topo.png"
        Image.new("RGB", (240, 120), color=(40, 120, 200)).save(img_path)

        sec1 = (
            self.paths.resolve(self.manifest.relative_content_root())
            / "第1章 引言"
            / "1.1 目的.md"
        )
        sec1.write_text(
            "本文档架构见图《系统网络拓扑图》，关键指标参见表“接口延迟预算表”，"
            "设计详见《2.1 架构》章节。\n\n"
            "![图：系统网络拓扑图](images/topo.png =240x120)\n\n"
            "表：接口延迟预算表\n\n"
            "| 阶段 | 预算耗时 | 备注说明 |\n"
            "| --- | --- | --- |\n"
            "| 鉴权 | 5ms | 本地缓存命中 |\n"
            "| 推理 | 45ms | GPU 批处理 |\n",
            encoding="utf-8",
        )

        parsed = parse_blocks(sec1.read_text(encoding="utf-8"), str(sec1))
        figs = [b for b in parsed.blocks if b.kind == KIND_IMAGE]
        tbls = [b for b in parsed.blocks if b.kind == KIND_TABLE]
        self.assertEqual(len(figs), 1)
        self.assertEqual(figs[0].caption, "系统网络拓扑图")
        self.assertTrue(figs[0].ident.startswith("fig-auto-"))
        self.assertEqual(len(tbls), 1)
        self.assertEqual(tbls[0].caption, "接口延迟预算表")
        self.assertTrue(tbls[0].ident.startswith("tbl-auto-"))

        registry = build_registry([parsed])
        resolved_txt = resolve_inline_references(
            "请见图《系统网络拓扑图》及表“接口延迟预算表”。",
            registry,
        )
        self.assertIn("图 1", resolved_txt)
        self.assertIn("表 1", resolved_txt)

        # 执行诊断构建管线，验证生成的 docx 中包含 REF 域与章节内部超链接
        out_docx = self.paths.output_dir / "natural_xref_out.docx"
        pipe_res = run_pipeline(
            self.manifest,
            self.paths,
            skip_word_refresh=True,
            output_override=str(out_docx),
        )
        self.assertTrue(pipe_res.success, msg=str(pipe_res.events))
        with zipfile.ZipFile(out_docx, "r") as zf:
            doc_xml_str = zf.read("word/document.xml").decode("utf-8", errors="replace")
        self.assertIn("REF cap_fig_auto_", doc_xml_str)
        self.assertIn("REF cap_tbl_auto_", doc_xml_str)
        self.assertIn("SEQ 图", doc_xml_str)
        self.assertIn("SEQ 表", doc_xml_str)
        self.assertIn("w:anchor=", doc_xml_str)

    # ------------------------------------------------------------------
    # Direction 3: 跨文件改名/顺延指纹对齐 + Markdown 表格行/单元格级三方合并
    # ------------------------------------------------------------------
    def test_direction3_reimport_rename_shift_and_table_cell_merge(self) -> None:
        # 3A: Markdown 表格行/单元格级三方合并
        base_tbl = (
            "<!-- TBL:cols=2000,3000,3000 -->\n"
            "| 参数名 | 默认值 | 说明 |\n"
            "| --- | --- | --- |\n"
            "| timeout | 30s | 请求超时 |\n"
            "| retries | 3 | 重试次数 |\n"
        )
        local_tbl = (
            "<!-- TBL:cols=2000,3000,3000 -->\n"
            "| 参数名 | 默认值 | 说明 |\n"
            "| --- | --- | --- |\n"
            "| timeout | 60s | 请求超时 |\n"
            "| retries | 3 | 重试次数 |\n"
            "| backoff | 200ms | 本地新增退避参数 |\n"
        )
        remote_tbl = (
            "<!-- TBL:cols=2000,3000,3000 -->\n"
            "| 参数名 | 默认值 | 说明 |\n"
            "| --- | --- | --- |\n"
            "| timeout | 30s | 请求超时 |\n"
            "| retries | 5 | 远端提升重试上限 |\n"
        )
        merged_tbl_res = merge_table_block_three_way(base_tbl, local_tbl, remote_tbl)
        self.assertIsNotNone(merged_tbl_res)
        assert merged_tbl_res is not None
        merged_tbl_text, tbl_merge_ok = merged_tbl_res
        self.assertTrue(tbl_merge_ok)
        self.assertIn("| timeout | 60s | 请求超时 |", merged_tbl_text)
        self.assertIn("| retries | 5 | 远端提升重试上限 |", merged_tbl_text)
        self.assertIn("| backoff | 200ms | 本地新增退避参数 |", merged_tbl_text)

        # 验证 merge_markdown_blocks_three_way 自动调用表格级三方合并
        block_merge = merge_markdown_blocks_three_way(
            "前导段落。\n\n" + base_tbl,
            "前导段落。\n\n" + local_tbl,
            "前导段落。\n\n" + remote_tbl,
        )
        self.assertEqual(block_merge.conflicts, [])
        self.assertIn("| timeout | 60s | 请求超时 |", block_merge.merged_text)
        self.assertIn("| retries | 5 | 远端提升重试上限 |", block_merge.merged_text)

        # 3B: 跨文件章节改名/顺延移位内容指纹对齐
        old_rel = "design/第1章 引言/1.2 范围.md"
        new_rel = "design/第1章 引言/1.3 系统适用范围.md"
        p1_base = "本系统适用于重症监护病房（ICU）呼吸机数据采集与波形实时监控场景。"
        p2_base = "支持 HL7 与私有二进制协议双通道接入，保障断网续传与本地缓存安全。"
        shared_body = p1_base + "\n\n" + p2_base + "\n"
        local_root = self.root / "reimport_local"
        incoming_root = self.root / "reimport_incoming"
        (local_root / "design/第1章 引言").mkdir(parents=True, exist_ok=True)
        (incoming_root / "design/第1章 引言").mkdir(parents=True, exist_ok=True)

        local_body = (
            p1_base + "（本地作者补充：支持边缘网关部署模式。）\n\n" + p2_base + "\n"
        )
        remote_body = (
            p1_base + "\n\n" + p2_base + "\n\n外部审阅补充：符合医疗器械网络安全规范。\n"
        )
        (local_root / old_rel).write_text(local_body, encoding="utf-8")
        (incoming_root / new_rel).write_text(remote_body, encoding="utf-8")

        import hashlib
        base_sha = hashlib.sha1(shared_body.encode("utf-8")).hexdigest()
        changes = compare_chapters(
            local_root,
            incoming_root,
            base_hashes={old_rel: base_sha},
            base_texts={old_rel: shared_body},
        )
        # 应仅产出 1 条对齐后的变更（new_rel），且 renamed_from 指向 old_rel
        self.assertEqual(len(changes), 1)
        ch = changes[0]
        self.assertEqual(ch.rel_path, new_rel)
        self.assertEqual(ch.renamed_from, old_rel)
        self.assertEqual(ch.status, "modified")
        self.assertIn("本地作者补充", ch.merged_content)
        self.assertIn("外部审阅补充", ch.merged_content)

    # ------------------------------------------------------------------
    # Direction 4: 复杂表格（XML Table）可读 Markdown 代理与单元格修改精准回填
    # ------------------------------------------------------------------
    def test_direction4_complex_table_markdown_proxy_and_cell_backfill(self) -> None:
        tbl_xml_str = (
            '<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:tblGrid><w:gridCol w:w=\"2000\"/><w:gridCol w:w=\"4000\"/></w:tblGrid>"
            "<w:tr>"
            "<w:tc><w:tcPr><w:vMerge w:val=\"restart\"/></w:tcPr><w:p><w:r><w:t>模块A</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>初始指标说明</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "<w:tr>"
            "<w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>"
            "<w:tc><w:p><w:r><w:t>二级指标说明</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
            "</w:tbl>"
        )
        tbl_el = ET.fromstring(tbl_xml_str)
        rows, _tc_grid = extract_complex_table_proxy_rows(tbl_el)
        self.assertEqual(rows, [["模块A", "初始指标说明"], ["", "二级指标说明"]])

        proxy_lines = format_complex_table_proxy_lines(tbl_el)
        md_doc_text = (
            "<!-- TABLE:1:tbl_0001.xml -->\n"
            + "\n".join(proxy_lines)
            + "\n\n后续普通段落。\n"
        )
        # check_table_structure 不应把代理块当成普通未标注表格报错
        errs = check_table_structure(md_doc_text.splitlines())
        self.assertEqual(errs, [])

        # parse_blocks 应将代理表消费进 ComplexTable.proxy_rows
        doc = parse_blocks(md_doc_text, "chapter.md")
        complex_blocks = [b for b in doc.blocks if b.kind == KIND_COMPLEX_TABLE]
        self.assertEqual(len(complex_blocks), 1)
        self.assertEqual(
            complex_blocks[0].proxy_rows,
            [["模块A", "初始指标说明"], ["", "二级指标说明"]],
        )

        # 修改代理表中的单元格文字并回填到 XML
        edited_proxy = [["模块A", "已更新的核心指标（<=10ms）"], ["", "二级指标说明"]]
        updated_cnt = apply_complex_table_proxy_edits(tbl_el, edited_proxy)
        self.assertEqual(updated_cnt, 1)
        # 验证 vMerge 属性完好无损，且文字已精准写入对应 <w:tc>
        after_rows, _ = extract_complex_table_proxy_rows(tbl_el)
        self.assertEqual(
            after_rows,
            [["模块A", "已更新的核心指标（<=10ms）"], ["", "二级指标说明"]],
        )
        first_tc = tbl_el.findall("./w:tr", NS)[0].findall("./w:tc", NS)[0]
        self.assertIsNotNone(first_tc.find("./w:tcPr/w:vMerge", NS))

    # ------------------------------------------------------------------
    # Direction 5: 无元数据表格自适应列宽、超宽表自动横版、图片智能 DPI 缩放
    # ------------------------------------------------------------------
    def test_direction5_smart_column_widths_auto_landscape_and_dpi_image(self) -> None:
        rows = [
            ["序号", "配置项", "详细功能说明与生产环境阈值约束要求"],
            ["1", "max_conn", "单个网关节点允许维持的最大并发长连接数量，默认 4096"],
            ["2", "heartbeat_sec", "设备端与服务端双向心跳检测间隔秒数，超时自动重连"],
        ]
        widths = compute_smart_column_widths(rows, 9000)
        self.assertEqual(len(widths), 3)
        self.assertEqual(sum(widths), 9000)
        # 第 1 列（序号）最窄，第 3 列（长说明）最宽
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])

        # 超宽 8 列无元数据手写表估算宽度应超过竖版上限
        wide_rows = [
            ["字段1", "字段2", "字段3", "字段4", "字段5", "字段6", "字段7", "字段8"],
            [
                "较长的业务描述内容A",
                "较长的业务描述内容B",
                "较长的业务描述内容C",
                "较长的业务描述内容D",
                "较长的业务描述内容E",
                "较长的业务描述内容F",
                "较长的业务描述内容G",
                "较长的业务描述内容H",
            ],
        ]
        est_w = estimate_unannotated_table_natural_width(wide_rows)
        self.assertGreater(est_w, 10000)

        # 图片物理尺寸智能缩放验证
        icon_path = self.root / "small_icon.png"
        Image.new("RGB", (48, 48), color=(0, 128, 255)).save(icon_path)
        max_w_emu = 6000000
        ref_no_size = ImageReference(
            alt="icon",
            relative_path="small_icon.png",
            width_px=None,
            height_px=None,
        )
        w_emu, h_emu = image_size_emu(str(icon_path), ref_no_size, max_w_emu)
        # 48px 图标不应被拉伸到页面宽度（应保持约 0.5 英寸 = 457200 EMU）
        self.assertLess(w_emu, 600000)
        self.assertEqual(w_emu, h_emu)

        # 高分宽幅无 DPI 截图（1920x1080）应按 144 DPI 缩放并受 max_width 约束
        hi_path = self.root / "retina_shot.png"
        Image.new("RGB", (1920, 1080), color=(20, 20, 20)).save(hi_path)
        w_hi, h_hi = image_size_emu(str(hi_path), ref_no_size, max_w_emu)
        self.assertLessEqual(w_hi, max_w_emu)
        self.assertAlmostEqual(w_hi / float(h_hi), 1920.0 / 1080.0, places=2)

    # ------------------------------------------------------------------
    # Direction 6: 基于基线快照差异的智能修订摘要生成与版本号自动演进
    # ------------------------------------------------------------------
    def test_direction6_smart_revision_summary_and_auto_version_bump(self) -> None:
        self.assertEqual(bump_revision_version("1.0"), "1.1")
        self.assertEqual(bump_revision_version("V3.8"), "V3.9")
        self.assertEqual(bump_revision_version("1.0.2"), "1.0.3")
        self.assertEqual(bump_revision_version("1.0.2", level="minor"), "1.1.0")

        content_root = self.paths.resolve(self.manifest.relative_content_root())
        sec1 = content_root / "第1章 引言" / "1.1 目的.md"
        sec2 = content_root / "第2章 设计" / "2.1 架构.md"
        base_sec1 = sec1.read_text(encoding="utf-8")
        base_sec2 = sec2.read_text(encoding="utf-8")

        import hashlib
        reimport_base = self.paths.state_dir / "reimport_base.json"
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        reimport_base.write_text(
            json.dumps(
                {
                    "files": {
                        "第1章 引言/1.1 目的.md": hashlib.sha1(base_sec1.encode("utf-8")).hexdigest(),
                        "第2章 设计/2.1 架构.md": hashlib.sha1(base_sec2.encode("utf-8")).hexdigest(),
                    },
                    "contents": {
                        "第1章 引言/1.1 目的.md": base_sec1,
                        "第2章 设计/2.1 架构.md": base_sec2,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # 在 1.1 目的.md 中新增一张表，并新增 1.3 术语定义.md
        sec1.write_text(
            base_sec1.rstrip()
            + "\n\n| 参数 | 含义 |\n| --- | --- |\n| mode | 运行模式 |\n",
            encoding="utf-8",
        )
        sec3 = content_root / "第1章 引言" / "1.3 术语定义.md"
        sec3.write_text("定义本文档涉及的核心缩略语。\n", encoding="utf-8")

        summary, changed = generate_smart_revision_summary(self.manifest, self.paths)
        self.assertIn("第1章 引言/1.1 目的.md", changed)
        self.assertIn("第1章 引言/1.3 术语定义.md", changed)
        self.assertIn("新增", summary)
        self.assertIn("修改", summary)
        self.assertIn("新增表格 1 处", summary)

        entry = append_smart_revision_entry(
            self.manifest,
            self.paths,
            author="智能构建助手",
            date="2026-10-15",
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["normalized_version"], "1.1")
        rev_md = (content_root / "_revision_record.md").read_text(encoding="utf-8")
        self.assertIn("智能构建助手", rev_md)
        self.assertIn("新增表格 1 处", rev_md)


if __name__ == "__main__":
    unittest.main()
