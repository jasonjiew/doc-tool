# -*- coding: utf-8 -*-
"""测试修订评审纯 Python OOXML 构建、数据模型与反向解析。

覆盖：
1. ReviewComment 9 列表格扩展字段、默认值向后兼容与 ReviewStore 持久化。
2. 会议评审稿生成（去除 w:numPr 杜绝跳号、改动摘要框、文末空白表格）。
3. Word 末尾表格提取（表头识别、字段映射、空行过滤）。
4. 更改结果与行级 diff 证据自动生成。
5. 横向 A4 9 列表格评审纪要 DOCX 与 Markdown 同源生成。
6. ReviewPanel 界面与数据交互（无头模式）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from doc_tool.application.review.review_docx import (
    W_NS,
    build_review_draft_docx,
    build_review_minutes_docx,
    extract_comments_from_docx,
    generate_evidence_for_comment,
    qn,
)
from doc_tool.application.review.review_store import ReviewComment, ReviewStore


class ReviewStoreModelTest(unittest.TestCase):
    """测试评审数据模型与存储操作。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_dir = Path(self.temp_dir) / ".state"
        self.state_dir.mkdir(parents=True)
        self.store = ReviewStore(self.state_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_legacy_json_backward_compatibility(self):
        """测试加载旧格式 comments.json（缺少 9 列扩展字段）依然正常。"""
        comments_file = self.state_dir / "reviews" / "comments.json"
        comments_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_data = {
            "comments": [
                {
                    "comment_id": "c1",
                    "text": "旧评审意见",
                    "author": "张三",
                    "created_at": "2026-09-01T00:00:00Z",
                    "rel_path": "01_intro.md",
                    "line_no": 12,
                    "status": "unresolved",
                    "resolved_at": "",
                    "association_changed": False,
                }
            ]
        }
        comments_file.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

        loaded = self.store.comments()
        self.assertEqual(len(loaded), 1)
        item = loaded[0]
        self.assertEqual(item.comment_id, "c1")
        self.assertEqual(item.text, "旧评审意见")
        # 默认扩展字段
        self.assertEqual(item.seq, 1)
        self.assertEqual(item.chapter_no, "")
        self.assertEqual(item.confirm_status, "未确认")
        self.assertEqual(item.open_issue, "")

    def test_add_and_update_comment(self):
        """测试添加包含 9 列字段的意见并更新。"""
        comment = self.store.add_comment(
            text="接口超时时间建议增加",
            author="李工",
            rel_path="02_api.md",
            line_no=45,
            chapter_no="3.2",
            assignee="王工",
            planned_date="2026-09-10",
            confirm_status="待确认",
            review_note="讨论采纳",
        )
        self.assertEqual(comment.seq, 1)
        self.assertEqual(comment.chapter_no, "3.2")
        self.assertEqual(comment.assignee, "王工")

        # 更新
        self.store.update_comment(
            comment.comment_id,
            confirm_status="已确认",
            evidence="【已修改】已增加到 15s",
        )
        updated = self.store.comments()[0]
        self.assertEqual(updated.confirm_status, "已确认")
        self.assertEqual(updated.evidence, "【已修改】已增加到 15s")

    def test_stats_calculation(self):
        """测试仪表盘统计数据计算。"""
        self.store.add_comment(text="问题1", author="A", confirm_status="已确认")
        self.store.add_comment(text="问题2", author="B", confirm_status="待确认")
        self.store.add_comment(text="问题3", author="C", confirm_status="遗留", open_issue="待后续确认")

        stats = self.store.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["confirmed"], 1)
        self.assertEqual(stats["unconfirmed"], 1)
        self.assertEqual(stats["open_issues"], 1)


class ReviewDocxDraftTest(unittest.TestCase):
    """测试会议评审稿 DOCX 生成。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_docx = Path(self.temp_dir) / "评审稿.docx"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_review_draft_structure(self):
        """验证生成的评审稿结构：标题、文字编号、无 w:numPr、改动摘要框、文末空白表。"""
        changed_items = [
            {
                "chapter_no": "3.2",
                "title": "通信接口升级",
                "status": "modified",
                "diff_summary": "+15行 / -3行",
                "rel_path": "03_interface.md",
                "markdown_content": "# 通信接口\n\n- 支持重试机制\n- 最大超时 10s\n",
            },
            {
                "chapter_no": "5.1",
                "title": "废弃旧服务",
                "status": "deleted",
                "diff_summary": "-50行",
                "rel_path": "05_old.md",
                "markdown_content": "旧服务废弃前说明",
            },
        ]

        build_review_draft_docx(
            template_path=None,
            output_path=self.output_docx,
            document_name="呼吸机软件规格说明书",
            document_version="2.6",
            changed_items=changed_items,
            include_blank_table=True,
            blank_rows_count=5,
        )

        self.assertTrue(self.output_docx.exists())

        # 读取 DOCX 校验 XML 节点
        with zipfile.ZipFile(self.output_docx, "r") as archive:
            doc_xml = archive.read("word/document.xml")

        root = etree.fromstring(doc_xml)

        # 1. 验证标题包含文档名称
        all_text = "".join(root.itertext())
        self.assertIn("《呼吸机软件规格说明书 - 修订评审稿》", all_text)
        self.assertIn("v2.6", all_text)

        # 2. 验证改动章节标题：文字编号拼接，且绝不带 w:numPr
        paragraphs = root.findall(".//" + qn("p"))
        heading_32_found = False
        for p in paragraphs:
            p_text = "".join(p.itertext()).strip()
            if "3.2 通信接口升级" in p_text:
                heading_32_found = True
                # 必须无 w:numPr（防止 Word 自动重新编号）
                num_pr = p.find(".//" + qn("numPr"))
                self.assertIsNone(num_pr, "评审稿章节标题不应含有 w:numPr")

        self.assertTrue(heading_32_found, "未找到章节标题 3.2")

        # 3. 验证改动摘要框
        self.assertIn("【改动摘要】", all_text)
        self.assertIn("+15行 / -3行", all_text)

        # 4. 验证删除章节提示
        self.assertIn("本节在当前最新版本中已被删除", all_text)

        # 5. 验证附录空白表格存在
        self.assertIn("附录：评审意见记录表", all_text)
        tables = root.findall(".//" + qn("tbl"))
        self.assertGreaterEqual(len(tables), 2)  # 摘要框与附录表


class ExtractCommentsFromDocxTest(unittest.TestCase):
    """测试从 Word 文档中反向提取末尾评审表。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.docx_path = Path(self.temp_dir) / "会议评审表.docx"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_comments_success(self):
        """测试从包含评审表格的 DOCX 提取意见数据并跳过空白行。"""
        # 生成带表格的 DOCX
        items = [
            ReviewComment(
                comment_id="1",
                text="协议头校验和算法不明确",
                author="赵工",
                created_at="2026-09-03",
                rel_path="",
                line_no=1,
                seq=1,
                chapter_no="3.2",
                assignee="钱工",
                planned_date="2026-09-08",
                confirm_status="已确认",
                review_note="按 CRC32 补充",
                evidence="",
                open_issue="",
            ),
            ReviewComment(
                comment_id="2",
                text="缺少降级策略时序图",
                author="孙工",
                created_at="2026-09-03",
                rel_path="",
                line_no=1,
                seq=2,
                chapter_no="4.1",
                assignee="李工",
                planned_date="2026-09-12",
                confirm_status="待确认",
                review_note="待绘制",
                evidence="",
                open_issue="时序图绘制中",
            ),
        ]

        # 导出纪要 DOCX（含标准表）
        build_review_minutes_docx(
            output_path=self.docx_path,
            document_name="测试文档",
            document_no="DOC-001",
            document_version="1.0",
            review_date="2026-09-03",
            comments=items,
        )

        # 反向提取
        extracted = extract_comments_from_docx(self.docx_path)
        self.assertEqual(len(extracted), 2)

        first = extracted[0]
        self.assertEqual(first.seq, 1)
        self.assertEqual(first.author, "赵工")
        self.assertEqual(first.chapter_no, "3.2")
        self.assertEqual(first.text, "协议头校验和算法不明确")
        self.assertEqual(first.assignee, "钱工")
        self.assertEqual(first.planned_date, "2026-09-08")
        self.assertEqual(first.confirm_status, "已确认")
        self.assertEqual(first.review_note, "按 CRC32 补充")


class GenerateEvidenceTest(unittest.TestCase):
    """测试根据基线与当前 Markdown 差异生成证据。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.content_root = Path(self.temp_dir) / "content"
        self.content_root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    class MockSnapshot:
        def __init__(self, baseline_dict):
            self._baselines = baseline_dict

        def content_of(self, rel_path: str):
            return self._baselines.get(rel_path)

    def test_modified_evidence(self):
        """测试修改文件的证据文本生成。"""
        rel_path = "03_section.md"
        base_text = "line 1\nline 2\nline 3\n"
        curr_text = "line 1\nline 2 modified\nline 3\nline 4 added\n"

        (self.content_root / rel_path).write_text(curr_text, encoding="utf-8")
        snapshot = self.MockSnapshot({rel_path: base_text})

        c = ReviewComment(
            comment_id="c1",
            text="意见描述",
            author="测试人",
            created_at="",
            rel_path=rel_path,
            line_no=1,
            chapter_no="3.1",
        )

        evidence = generate_evidence_for_comment(c, self.content_root, snapshot, today_str="2026-09-03")
        self.assertIn("【已修改】3.1节已修改", evidence)
        self.assertIn("新增 2 行", evidence)
        self.assertIn("删减 1 行", evidence)
        self.assertIn("2026-09-03", evidence)

    def test_added_evidence(self):
        """测试新增章节的证据生成。"""
        rel_path = "04_new.md"
        curr_text = "line 1\nline 2\nline 3\nline 4\n"
        (self.content_root / rel_path).write_text(curr_text, encoding="utf-8")
        snapshot = self.MockSnapshot({})

        c = ReviewComment(
            comment_id="c2",
            text="补充新章节",
            author="测试人",
            created_at="",
            rel_path=rel_path,
            line_no=1,
            chapter_no="4.1",
        )

        evidence = generate_evidence_for_comment(c, self.content_root, snapshot, today_str="2026-09-03")
        self.assertIn("【新增章节】4.1节已新增（共 4 行）", evidence)


class ReviewMinutesTest(unittest.TestCase):
    """测试标准 A4 横向评审纪要 DOCX 与 Markdown 导出。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_docx = Path(self.temp_dir) / "评审纪要.docx"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_minutes_a4_landscape_and_markdown(self):
        """测试横向 A4 页面、商务蓝表头、tblHeader 及同源 Markdown。"""
        comments = [
            ReviewComment(
                comment_id="1",
                text="建议增加超时自动断开机制",
                author="周工",
                created_at="2026-09-03",
                rel_path="03_comm.md",
                line_no=1,
                seq=1,
                chapter_no="3.4",
                assignee="吴工",
                planned_date="2026-09-05",
                confirm_status="已确认",
                review_note="采纳并已完成",
                evidence="【已修改】3.4节新增4行",
                open_issue="无",
            )
        ]

        docx_res, md_res = build_review_minutes_docx(
            output_path=self.output_docx,
            document_name="监护仪详细设计",
            document_no="DOC-MED-2026",
            document_version="1.2",
            review_date="2026-09-03",
            comments=comments,
            organizer="评审委员会",
        )

        self.assertTrue(docx_res.exists())
        self.assertTrue(md_res.exists())

        # 检查 DOCX 横向设置与表头
        with zipfile.ZipFile(docx_res, "r") as archive:
            doc_xml = archive.read("word/document.xml")

        root = etree.fromstring(doc_xml)

        # 页面横向 Landscape
        sect_pr = root.find(".//" + qn("sectPr"))
        self.assertIsNotNone(sect_pr)
        pg_sz = sect_pr.find(qn("pgSz"))
        self.assertEqual(pg_sz.get(qn("orient")), "landscape")
        self.assertEqual(pg_sz.get(qn("w")), "16838")  # 297mm
        self.assertEqual(pg_sz.get(qn("h")), "11906")  # 210mm

        # 表头具有 tblHeader
        tbl_header = root.find(".//" + qn("tblHeader"))
        self.assertIsNotNone(tbl_header, "纪要表格表头必须包含 tblHeader 以支持分页重复")

        # 检查 Markdown 文件内容
        md_text = md_res.read_text(encoding="utf-8")
        self.assertIn("# 《监护仪详细设计 - 评审纪要》", md_text)
        self.assertIn("| 序号 | 提出人 | 章节 | 评审问题 | 责任人 |", md_text)
        self.assertIn("建议增加超时自动断开机制", md_text)
        self.assertIn("【已修改】3.4节新增4行", md_text)


class ReviewPanelHeadlessTest(unittest.TestCase):
    """测试 ReviewPanel 在无头环境下的基本构造与信号。"""

    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        self.temp_dir = tempfile.mkdtemp()
        self.state_dir = Path(self.temp_dir) / ".state"
        self.state_dir.mkdir(parents=True)
        self.content_root = Path(self.temp_dir) / "content"
        self.content_root.mkdir(parents=True)

        self.store = ReviewStore(self.state_dir)
        self.store.add_comment(text="初始问题", author="评委1", chapter_no="1.1")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_panel_load_and_add_row(self):
        from doc_tool.ui.content.review_panel import ReviewPanel

        panel = ReviewPanel(
            store=self.store,
            content_root=self.content_root,
        )

        self.assertEqual(panel._table.rowCount(), 1)
        panel._on_add_row()
        self.assertEqual(panel._table.rowCount(), 2)

        # 过滤搜索
        panel._search_edit.setText("不存在的关键字")
        self.assertEqual(panel._table.rowCount(), 0)

        panel._search_edit.setText("")
        self.assertEqual(panel._table.rowCount(), 2)

    def test_pill_badge_delegate_paint(self):
        """测试胶囊徽标委托在未选中和选中状态下的绘制，确保无 AttributeError。"""
        from PySide6.QtCore import QModelIndex
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
        from doc_tool.ui.content.review_panel import PillBadgeDelegate

        delegate = PillBadgeDelegate()
        pix = QPixmap(100, 40)
        painter = QPainter(pix)
        try:
            opt = QStyleOptionViewItem()
            opt.rect = pix.rect()
            opt.state = QStyle.StateFlag.State_None
            delegate.paint(painter, opt, QModelIndex())

            # 选中状态：验证 option.state & QStyle.StateFlag.State_Selected 正常工作
            opt.state = QStyle.StateFlag.State_Selected
            delegate.paint(painter, opt, QModelIndex())
        finally:
            painter.end()

    def test_export_draft_dialog_and_export(self):
        """测试 ExportReviewDraftDialog 弹窗构造、全选切换与返回勾选列表。"""
        from doc_tool.ui.content.review_panel import ExportReviewDraftDialog

        chapters = [
            {"chapter_no": "1.1", "title": "概述", "status": "modified", "diff_summary": "+2/-1"},
            {"chapter_no": "1.2", "title": "术语", "status": "normal", "diff_summary": ""},
        ]
        dlg = ExportReviewDraftDialog(
            document_name="测试文档",
            document_version="1.0",
            changed_chapters=chapters,
            default_output_dir=Path(self.temp_dir),
        )
        self.assertEqual(len(dlg._chapter_checkboxes), 2)
        self.assertEqual(len(dlg.selected_chapters()), 2)

        # 切换全选
        dlg._toggle_select_all()
        self.assertEqual(len(dlg.selected_chapters()), 0)

        dlg._toggle_select_all()
        self.assertEqual(len(dlg.selected_chapters()), 2)
        self.assertTrue(dlg.include_blank_table())
        self.assertTrue(str(dlg.output_path()).endswith(".docx"))

    def test_panel_collect_chapters_with_content_index(self):
        """测试 ReviewPanel 与 ContentIndex 联动，提取章节与全量候选正常。"""
        from doc_tool.domain.content_index import ContentIndex, FileEntry, HeadingEntry
        from doc_tool.ui.content.review_panel import ReviewPanel

        idx = ContentIndex()
        idx.files["01_intro.md"] = FileEntry("01_intro.md", "general", 10)
        idx.files["3.2_api.md"] = FileEntry("3.2_api.md", "general", 20)
        idx.headings["01_intro.md"] = [HeadingEntry("01_intro.md", 1, 1, "1.0 引言", "intro")]

        panel = ReviewPanel(store=self.store, content_root=self.content_root, index=idx)
        all_chs = panel._get_all_chapters()
        self.assertIn("01 intro", all_chs)
        self.assertIn("3.2 api", all_chs)

        candidates = panel._collect_changed_chapters()
        self.assertEqual(len(candidates), 2)

    def test_review_panel_status_tone_and_pill_delegate(self):
        """测试 ReviewPanel 仪表盘标签 statusTone 与 PillBadgeDelegate 绘制。"""
        from doc_tool.ui.content.review_panel import ReviewPanel, PillBadgeDelegate
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem

        panel = ReviewPanel(store=self.store, content_root=self.content_root)
        self.assertEqual(panel._lbl_total.property("statusTone"), "neutral")
        self.assertEqual(panel._lbl_confirmed.property("statusTone"), "success")
        self.assertEqual(panel._lbl_unconfirmed.property("statusTone"), "warning")
        self.assertEqual(panel._lbl_open.property("statusTone"), "purple")

        delegate = PillBadgeDelegate(panel)
        pix = QPixmap(100, 30)
        painter = QPainter(pix)
        opt = QStyleOptionViewItem()
        opt.rect = pix.rect()
        model = panel._table.model()
        index = model.index(0, 6)
        delegate.paint(painter, opt, index)
        painter.end()

    def test_rich_markdown_draft_rendering(self):
        """测试 Markdown 正文中的表格、加粗/斜体/行内代码、代码块、列表深度渲染为 OOXML。"""
        import zipfile
        from lxml import etree
        from doc_tool.application.review.review_docx import build_review_draft_docx, qn

        md = """
## 1.1 总体架构
本模块支持 **高性能** 通信与 *自动重试*，配置项为 `max_retries`。

| 参数 | 类型 | 描述 |
| :--- | :--- | :--- |
| timeout | int | 超时毫秒 |
| ssl | bool | 是否启用安全连接 |

```python
def ping():
    return True
```

- 选项 1
- 选项 2

1. 步骤一
2. 步骤二
"""
        out_docx = Path(self.temp_dir) / "rich_draft.docx"
        build_review_draft_docx(
            template_path=None,
            output_path=out_docx,
            document_name="测试文档",
            document_version="1.0",
            changed_items=[
                {
                    "chapter_no": "1.1",
                    "title": "总体架构",
                    "status": "modified",
                    "diff_summary": "+10/-2",
                    "rel_path": "arch.md",
                    "markdown_content": md,
                }
            ],
            include_blank_table=True,
        )
        self.assertTrue(out_docx.exists())

        # 检查 document.xml 结构
        with zipfile.ZipFile(out_docx, "r") as zf:
            xml_data = zf.read("word/document.xml")
            root = etree.fromstring(xml_data)

            # 检查表格是否渲染：改动摘要框 + 正文 Markdown 表格 + 代码块表格 + 空白附录表格，总表格数 >= 4
            tbls = root.findall(".//" + qn("tbl"))
            self.assertGreaterEqual(len(tbls), 4)

            # 检查加粗标记 <w:b/>
            b_elements = root.findall(".//" + qn("b"))
            self.assertGreaterEqual(len(b_elements), 3)

            # 检查等宽字体代码块 Consolas
            consolas_fonts = root.xpath('//w:rFonts[@w:ascii="Consolas"]', namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"})
            self.assertGreaterEqual(len(consolas_fonts), 2)

    def test_reveal_in_file_manager(self):
        """测试 reveal_in_file_manager 调用无模块缺失异常。"""
        from doc_tool.ui.content.review_panel import reveal_in_file_manager
        # 测试不存在路径安全返回
        reveal_in_file_manager(Path(self.temp_dir) / "non_existent.docx")

    def test_diff_highlight_and_comment_filtering(self):
        """测试差异标红（红色新增/修改，灰色删除线）与 HTML 注释（<!-- TBL:... -->）彻底过滤。"""
        import zipfile
        from lxml import etree
        from doc_tool.application.review.review_docx import build_review_draft_docx, qn

        base_md = """
## 1.1 总体架构
本模块负责核心逻辑处理。
端口设置为 8080。

| 参数 | 类型 |
| :--- | :--- |
| host | str |
"""
        curr_md = """
<!-- TBL:style=42 type=auto tw=0 cols=2743,1127,995,1719,3444 cm=0,0,0,0 ind=0:dxa lay=autofit bd=single:auto:4:0 hdr=0 tcm=90,195,90,195 va=center -->
## 1.1 总体架构与升级
本模块负责核心分布式逻辑处理。
端口设置为 9090。

| 参数 | 类型 |
| :--- | :--- |
| host | str |
| port | int |

- 新增项目清单
"""
        out_docx = Path(self.temp_dir) / "diff_highlight.docx"
        build_review_draft_docx(
            template_path=None,
            output_path=out_docx,
            document_name="测试文档",
            document_version="1.0",
            changed_items=[
                {
                    "chapter_no": "1.1",
                    "title": "总体架构",
                    "status": "modified",
                    "diff_summary": "+2/-0",
                    "rel_path": "arch.md",
                    "markdown_content": curr_md,
                    "base_content": base_md,
                }
            ],
            include_blank_table=False,
            highlight_changes=True,
        )

        with zipfile.ZipFile(out_docx, "r") as zf:
            xml_str = zf.read("word/document.xml").decode("utf-8")
            self.assertNotIn("<!-- TBL:", xml_str)
            self.assertNotIn("cols=2743", xml_str)
            root = etree.fromstring(xml_str.encode("utf-8"))
            red_runs = [el for el in root.iter(qn("color")) if el.get(qn("val")) == "DC2626"]
            strike_runs = list(root.iter(qn("strike")))
            self.assertGreaterEqual(len(red_runs), 3)
            self.assertGreaterEqual(len(strike_runs), 1)

    def test_export_draft_dialog_highlight_toggle(self):
        """测试 ExportReviewDraftDialog 标红复选框状态及读取。"""
        from doc_tool.ui.content.review_panel import ExportReviewDraftDialog

        dlg = ExportReviewDraftDialog(
            document_name="测试文档",
            document_version="1.0",
            changed_chapters=[],
            default_output_dir=Path(self.temp_dir),
        )
        self.assertTrue(dlg.highlight_changes())
        dlg._cb_highlight.setChecked(False)
        self.assertFalse(dlg.highlight_changes())


if __name__ == "__main__":
    unittest.main()
