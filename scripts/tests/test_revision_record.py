# -*- coding: utf-8 -*-
"""修订记录自动测试（纯应用层，无 Qt 依赖）。

覆盖：
- 路径 → 章节/小节标签（含 _index.md、深层目录、空格去除）
- 新增/修改/删除分组的定位清单（只报「哪些小节动了」，不猜「改了什么」）
- 非 Markdown 条目（资源/project.yml）与修订记录元数据文件不进入清单
- 修订记录表读取：末行版本号、只有表头、版本号写坏时的降级
- 合并期版本号同步：``_revision_record.md`` 末行版本号 → ``documentVersion``；
  无表/无数据行时沿用清单版本号；构建失败时回滚
- 旧项目从模板初始化 ``_revision_record.md``（仅在缺失时创建，从不覆盖）
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-tool/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from doc_tool.application.content.changes import ChangeItem  # noqa: E402
from doc_tool.application.content.revision_record import (  # noqa: E402
    build_revision_record,
    document_version_from_record,
    ensure_revision_record,
    has_revision_table,
    last_revision_version,
    normalize_revision_version,
    section_labels,
)
from doc_tool.application.content.snapshot import ContentSnapshot  # noqa: E402
from doc_tool.application.pipeline import (  # noqa: E402
    STAGE_REVISION,
    PipelineResult,
    _prepare_revision_sync,
    _refresh_content_baseline,
    _rollback_revision_sync,
    _sync_revision_version,
)
from doc_tool.domain.paths import ProjectPaths  # noqa: E402

def _item(rel_path: str, status: str = "modified", baseline: str = "") -> ChangeItem:
    return ChangeItem(
        rel_path=rel_path,
        status=status,
        baseline_rel_path=baseline or rel_path,
    )


def _build(items) -> str:
    return build_revision_record(items)


class SectionLabelsTest(unittest.TestCase):
    def test_requirement_module_file(self):
        self.assertEqual(
            section_labels(
                "requirement/第3章 功能需求/3.7 产品管理/3.7.9 呼吸机应用升级.md"
            ),
            ("3.7产品管理", "3.7.9呼吸机应用升级"),
        )

    def test_file_directly_under_chapter(self):
        self.assertEqual(
            section_labels("design/第1章 引言/1.1 目的.md"),
            ("第1章引言", "1.1目的"),
        )

    def test_deep_nested_file(self):
        self.assertEqual(
            section_labels(
                "design/第3章 设备端功能设计/3.1 呼吸机结果集数据上传/"
                "3.1.1 功能描述.md"
            ),
            ("3.1呼吸机结果集数据上传", "3.1.1功能描述"),
        )

    def test_index_md_uses_folder(self):
        self.assertEqual(
            section_labels("requirement/第3章 功能需求/3.7 产品管理/_index.md"),
            ("3.7产品管理", "3.7产品管理"),
        )

    def test_markdown_suffix(self):
        self.assertEqual(
            section_labels("requirement/第2章 系统概述/2.1 项目背景与目标.markdown"),
            ("第2章系统概述", "2.1项目背景与目标"),
        )


class BuildRevisionRecordTest(unittest.TestCase):
    def test_added_only(self):
        items = [_item(
            "requirement/第3章 功能需求/3.7 产品管理/3.7.9 呼吸机应用升级.md",
            "added",
        )]
        self.assertEqual(
            _build(items),
            "新增：\n3.7产品管理->3.7.9呼吸机应用升级",
        )

    def test_deleted_only(self):
        items = [_item(
            "requirement/第3章 功能需求/3.7 产品管理/3.7.8 应用升级.md",
            "deleted",
        )]
        self.assertEqual(
            _build(items),
            "删除：\n3.7产品管理->3.7.8应用升级",
        )

    def test_empty_groups_omitted(self):
        items = []
        self.assertEqual(_build(items), "")

    def test_non_markdown_skipped(self):
        items = [
            _item("assets/images/img_0001.png", "added"),
            _item("project.yml", "modified"),
            _item(
                "requirement/第3章 功能需求/3.7 产品管理/3.7.9 呼吸机应用升级.md",
                "added",
            ),
        ]
        self.assertEqual(
            _build(items),
            "新增：\n3.7产品管理->3.7.9呼吸机应用升级",
        )

    def test_group_order_added_modified_deleted(self):
        items = [
            _item("content/a/1 新增.md", "added"),
            _item("content/a/2 删除.md", "deleted"),
            _item("content/a/3 修改.md", "modified"),
        ]
        text = _build(items)
        self.assertLess(text.index("新增："), text.index("修改："))
        self.assertLess(text.index("修改："), text.index("删除："))

    def test_modified_reports_location_only(self):
        """修改条目只报「章节->小节」，不再从差异反推「改了什么」。"""
        rel = "requirement/第3章 功能需求/3.7 产品管理/3.7.8 应用升级.md"
        self.assertEqual(
            _build([_item(rel)]),
            "修改：\n3.7产品管理->3.7.8应用升级",
        )

    def test_revision_record_file_skipped(self):
        """_revision_record.md 是元数据，不能作为改动条目进入清单。"""
        items = [
            _item("requirement/_revision_record.md", "modified"),
            _item("requirement/第3章 功能需求/3.7 产品管理/3.7.9 升级.md", "added"),
        ]
        self.assertEqual(_build(items), "新增：\n3.7产品管理->3.7.9升级")

    def test_same_section_deduplicated(self):
        """同一小节多个条目（如 .md/.markdown 混排）只出现一次。"""
        base = "requirement/第3章 功能需求/3.7 产品管理/"
        items = [
            _item(base + "_index.md", "modified"),
            _item(base + "3.7.9 升级.md", "modified"),
            _item(base + "_index.md", "modified"),
        ]
        self.assertEqual(
            _build(items),
            "修改：\n3.7产品管理->3.7产品管理\n3.7产品管理->3.7.9升级",
        )

    def test_unknown_status_ignored(self):
        """未知状态（未来新增的状态值）不应挤进任何分组。"""
        self.assertEqual(_build([_item("content/a/1 示例.md", "renamed")]), "")


class NormalizeVersionTest(unittest.TestCase):
    """版本号最小安全校验（该值会成为 documentVersion 并进封面/文件名）。"""

    def test_normalize_revision_version_rejects_table_breakout(self):
        self.assertEqual(normalize_revision_version(" 2.6 "), "2.6")
        for value in ("", "2|6", "2.6\nnext"):
            with self.assertRaises(ValueError):
                normalize_revision_version(value)


class RevisionTableReadTest(unittest.TestCase):
    """修订记录表读取：末行版本号 / 只有表头 / 行写坏时的降级。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.md = Path(self.tmp) / "_revision_record.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, content):
        self.md.write_text(content, encoding="utf-8")

    _HEADER = (
        "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
        "|------|----------|----------|--------|\n"
    )

    def test_last_row_version_wins(self):
        self._write(
            "# 修订记录\n\n" + self._HEADER
            + "| V3.7 | 历史 | 2026-05-06 | 罗新亮 |\n"
            + "| V3.8 | 新增呼吸机接口 | 2026-07-01 | 王杰 |\n"
            "\n<!-- 表后说明 -->\n"
        )
        self.assertTrue(has_revision_table(self.md))
        # last_revision_version 是原样读取；文档版本号统一去掉 V 前缀。
        self.assertEqual(last_revision_version(self.md), "V3.8")
        self.assertEqual(document_version_from_record(self.md), "3.8")

    def test_header_only_table_has_no_version(self):
        """只有表头：作者还没写过修订记录 → 沿用清单版本号。"""
        self._write("# 修订记录\n\n" + self._HEADER)
        self.assertTrue(has_revision_table(self.md))
        self.assertIsNone(last_revision_version(self.md))
        self.assertIsNone(document_version_from_record(self.md))

    def test_empty_version_cell_falls_back(self):
        self._write(self._HEADER + "|  | 摘要 | / | / |\n")
        self.assertIsNone(document_version_from_record(self.md))

    def test_missing_file_and_no_table(self):
        self.assertIsNone(document_version_from_record(self.md))
        self.assertFalse(has_revision_table(self.md))
        self._write("# 无表格\n")
        self.assertFalse(has_revision_table(self.md))
        self.assertIsNone(document_version_from_record(self.md))

    def test_parse_revision_markdown_keeps_first_data_row(self):
        """修复：parse_markdown_table 已跳过分隔行，rows[2:] 会丢掉 V1.0。"""
        self._write(
            self._HEADER
            + "| V1.0 | 首次创建 | / | / |\n"
            + "| V1.1 | 补充 | / | / |\n"
        )
        from build_docx import _parse_revision_markdown  # noqa: E402

        rows = _parse_revision_markdown(str(self.md))
        self.assertEqual([row[0] for row in rows], ["V1.0", "V1.1"])


class _FakeLog:
    """只记录调用的日志替身（RuntimeLog 会写盘，同步逻辑用不着）。"""

    def __init__(self):
        self.entries = []

    def info(self, stage, event="", metrics=None):
        self.entries.append(("info", stage, event))

    def warn(self, stage, event="", metrics=None):
        self.entries.append(("warn", stage, event))


class RevisionVersionSyncTest(unittest.TestCase):
    """合并期版本号同步：``_revision_record.md`` 末行 → documentVersion。

    同时覆盖旧项目从模板初始化修订记录，以及发布成功后的会话基线刷新。
    """

    _HEADER = (
        "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
        "|------|----------|----------|--------|\n"
    )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.content_root = self.tmp / "content"
        self.state_dir = self.tmp / ".state"
        self.type_root = self.content_root / "requirement"
        self.type_root.mkdir(parents=True)
        self.md = self.type_root / "_revision_record.md"
        self.paths = ProjectPaths(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manifest(self, version="3.7"):
        """只带同步所需字段的清单替身（真实清单需要完整项目结构）。"""
        return types.SimpleNamespace(
            documentVersion=version,
            documentType="requirement",
            relative_content_root=lambda: "content/requirement",
            relative_template_docx=lambda: "template/template.docx",
        )

    def _sync(self, manifest):
        """跑一遍「准备 + 同步」，返回（阶段状态, 结果对象, 计划）。"""
        plan = _prepare_revision_sync(manifest, self.paths)
        result = PipelineResult(success=False)
        status = _sync_revision_version(plan, manifest, result, _FakeLog())
        return status, result, plan

    def _detail(self, result):
        return result.events[-1].detail

    def test_last_row_version_becomes_document_version(self):
        self.md.write_text(
            "# 修订记录\n\n" + self._HEADER
            + "| V3.7 | 历史 | 2026-05-06 | 罗新亮 |\n"
            + "| V3.8 | 新增呼吸机接口 | 2026-07-01 | 王杰 |\n",
            encoding="utf-8",
        )
        manifest = self._manifest("3.7")
        status, result, plan = self._sync(manifest)
        self.assertEqual(status, "succeeded")
        # 修订记录里写 V3.8，进清单/封面/文件名的一律是去掉 V 的 3.8。
        self.assertEqual(manifest.documentVersion, "3.8")
        self.assertIn("3.7 → 3.8", self._detail(result))
        self.assertEqual(
            [event.stage for event in result.events], [STAGE_REVISION] * 2
        )
        # 修订记录文件本身从不被改写：整表内容由构建侧覆盖进 Word。
        self.assertNotIn("V3.9", self.md.read_text(encoding="utf-8"))
        # 构建失败回滚：清单版本号退回原值（清单只在发布成功后落盘）。
        _rollback_revision_sync(plan, manifest, _FakeLog())
        self.assertEqual(manifest.documentVersion, "3.7")

    def test_same_version_is_noop(self):
        """清单已是 3.8、修订记录末行写 V3.8：去 V 后相同，视为无操作。"""
        self.md.write_text(
            self._HEADER + "| V3.8 | 上次合并 | 2026-07-01 | 王杰 |\n",
            encoding="utf-8",
        )
        manifest = self._manifest("3.8")
        status, result, plan = self._sync(manifest)
        self.assertEqual(status, "succeeded")
        self.assertEqual(manifest.documentVersion, "3.8")
        self.assertIn("已与 _revision_record.md 末行一致", self._detail(result))
        self.assertFalse(plan["applied"])

    def test_missing_record_keeps_manifest_version(self):
        """无修订记录表（旧项目模板也没有）：沿用清单版本号，合并照常。"""
        manifest = self._manifest("3.7")
        status, result, _plan = self._sync(manifest)
        self.assertEqual(status, "skipped")
        self.assertEqual(manifest.documentVersion, "3.7")
        self.assertIn("没有修订记录表", self._detail(result))

    def test_header_only_table_keeps_manifest_version(self):
        self.md.write_text("# 修订记录\n\n" + self._HEADER, encoding="utf-8")
        manifest = self._manifest("3.7")
        status, result, _plan = self._sync(manifest)
        self.assertEqual(status, "skipped")
        self.assertEqual(manifest.documentVersion, "3.7")
        self.assertIn("还没有数据行", self._detail(result))

    def test_broken_paths_do_not_block_build(self):
        """读取整体失败（清单/路径异常）也只跳过同步，不抛给管线。"""
        broken = types.SimpleNamespace(
            documentVersion="3.7",
            documentType="requirement",
            relative_content_root=lambda: "",  # 触发 PathEscapeError
            relative_template_docx=lambda: "template/template.docx",
        )
        self.assertIsNone(_prepare_revision_sync(broken, self.paths))
        result = PipelineResult(success=False)
        status = _sync_revision_version(None, broken, result, _FakeLog())
        self.assertEqual(status, "skipped")
        self.assertEqual(broken.documentVersion, "3.7")
        self.assertIn("读取失败", self._detail(result))

    def test_prepare_bootstraps_record_from_template(self):
        """旧项目缺文件时先按模板初始化，随后即可取到末行版本号。"""
        template = self.paths.resolve("template/template.docx")
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_bytes(b"template")
        fake = types.ModuleType("extract_revision_record")
        fake.extract_revision_rows = lambda _path: [["V2.5", "历史", "/", ""]]
        fake.rows_to_markdown = lambda rows, doc_type: (
            "# {0}\n\n".format(doc_type) + self._HEADER
            + "| {0} | 历史 | / | / |\n".format(rows[0][0])
        )
        previous = sys.modules.get("extract_revision_record")
        sys.modules["extract_revision_record"] = fake
        try:
            manifest = self._manifest("2.4")
            status, _result, _plan = self._sync(manifest)
        finally:
            if previous is None:
                sys.modules.pop("extract_revision_record", None)
            else:
                sys.modules["extract_revision_record"] = previous
        self.assertEqual(status, "succeeded")
        # 模板提取出的历史行写作 V2.5；进清单的是去 V 后的 2.5。
        self.assertEqual(manifest.documentVersion, "2.5")
        self.assertTrue(self.md.is_file())

    def test_ensure_revision_record_bootstraps_missing_file_without_overwrite(self):
        """旧项目首次合并时从模板提取；已有用户文件保持不变。"""
        template = self.tmp / "template.docx"
        template.write_bytes(b"template")
        md = self.tmp / "design" / "_revision_record.md"
        fake = types.ModuleType("extract_revision_record")
        fake.extract_revision_rows = lambda _path: [["V2.5", "历史", "/", ""]]
        fake.rows_to_markdown = lambda rows, doc_type: (
            "# {0}\n\n| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
            "|---|---|---|---|\n| {1} | 历史 | / | / |\n".format(
                doc_type, rows[0][0]
            )
        )
        previous = sys.modules.get("extract_revision_record")
        sys.modules["extract_revision_record"] = fake
        try:
            self.assertTrue(ensure_revision_record(
                md_path=md,
                template_path=template,
                document_type="design",
            ))
            first = md.read_text(encoding="utf-8")
            self.assertIn("V2.5", first)
            self.assertFalse(ensure_revision_record(
                md_path=md,
                template_path=template,
                document_type="design",
            ))
            self.assertEqual(md.read_text(encoding="utf-8"), first)
        finally:
            if previous is None:
                sys.modules.pop("extract_revision_record", None)
            else:
                sys.modules["extract_revision_record"] = previous

    def test_successful_merge_baseline_refresh_uses_content_root(self):
        paths = ProjectPaths(self.tmp)
        chapter = paths.content_root / "design" / "第1章" / "1.1 示例.md"
        record = paths.content_root / "design" / "_revision_record.md"
        chapter.parent.mkdir(parents=True, exist_ok=True)
        record.parent.mkdir(parents=True, exist_ok=True)
        chapter.write_text("正文。\n", encoding="utf-8")
        record.write_text(
            "# 修订记录\n\n"
            "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
            "|------|----------|----------|--------|\n"
            "| 2.5 | 历史 | / | / |\n",
            encoding="utf-8",
        )

        self.assertEqual(_refresh_content_baseline(paths), 2)
        snapshot = ContentSnapshot(paths.state_dir)
        snapshot.load()
        self.assertEqual(
            sorted(snapshot.entries),
            ["design/_revision_record.md", "design/第1章/1.1 示例.md"],
        )


class TemplateExtractionLineBreakTest(unittest.TestCase):
    """模板 → Markdown 的换行兼容（内核提取侧）。

    模板修订摘要普遍一段写一条改动（部分还带 ``w:br``）。旧实现把单元格里所有
    ``w:t`` 直接拼接，段落边界全丢，提取出的 Markdown 挤成一行，回填 Word 后
    也只有一行——这里锁住「段落/``w:br`` → ``<br>`` → 构建侧换行」的整条链路。
    """

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def _cell(self, *paragraphs):
        """按 ``[(文本, 文本…)]`` 造一个 ``w:tc``；元组内多段用 ``w:br`` 连接。"""
        from lxml import etree

        cell = etree.Element(self.W + "tc")
        for parts in paragraphs:
            paragraph = etree.SubElement(cell, self.W + "p")
            if isinstance(parts, str):
                parts = (parts,)
            for index, text in enumerate(parts):
                run = etree.SubElement(paragraph, self.W + "r")
                if index:
                    etree.SubElement(run, self.W + "br")
                node = etree.SubElement(run, self.W + "t")
                node.text = text
        return cell

    def test_cell_text_keeps_paragraph_and_manual_breaks(self):
        from extract_revision_record import _cell_text  # noqa: E402

        cell = self._cell("第一条改动", ("第二条改动", "第三条改动"), "  ", "第四条")
        # 段落之间、w:br 处都换行；纯空白段落丢弃（Word 里作间距用）。
        self.assertEqual(
            _cell_text(cell),
            "第一条改动\n第二条改动\n第三条改动\n第四条",
        )

    def test_cell_text_ignores_field_instructions(self):
        """域指令（``w:instrText``）不是正文，不能混进摘要。"""
        from lxml import etree

        from extract_revision_record import _cell_text  # noqa: E402

        cell = self._cell("显示文本")
        run = etree.SubElement(cell.find(self.W + "p"), self.W + "r")
        instr = etree.SubElement(run, self.W + "instrText")
        instr.text = ' HYPERLINK \\l "_书签" '
        self.assertEqual(_cell_text(cell), "显示文本")

    def test_rows_to_markdown_encodes_breaks_and_escapes(self):
        from extract_revision_record import rows_to_markdown  # noqa: E402

        markdown = rows_to_markdown(
            [["V1.0", "第一条\n第二条 含 | 竖线", "2026-08-20", "张三"]], "design"
        )
        row = [line for line in markdown.splitlines() if line.startswith("| V1.0")][0]
        self.assertEqual(row, "| V1.0 | 第一条<br>第二条 含 \\| 竖线 | 2026-08-20 | 张三 |")

    def test_extracted_breaks_survive_kernel_parser(self):
        """提取 → Markdown → 构建侧解析：换行与竖线都要原样回来。"""
        from docx_common import split_markdown_table_row  # noqa: E402

        from extract_revision_record import _cell_text, rows_to_markdown  # noqa: E402

        summary = _cell_text(self._cell("第一条 | 带竖线", ("第二条", "第三条")))
        markdown = rows_to_markdown([["V1.0", summary, "/", "/"]], "design")
        row = [line for line in markdown.splitlines() if line.startswith("| V1.0")][0]
        self.assertEqual(split_markdown_table_row(row)[1], summary)
        self.assertEqual(summary.count("\n"), 2)


class AutolinkRevisionRecordTest(unittest.TestCase):
    """修订记录自动赋值章节文档超链接测试。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc_tool_autolink_test_"))
        # 建立测试章节目录树
        self.ch4 = self.tmp / "第4章 WEB端功能设计" / "4.8 Kmilight"
        self.ch4.mkdir(parents=True, exist_ok=True)
        (self.ch4 / "4.8.1 APP用户反馈.md").write_text("# 4.8.1 APP用户反馈\n", encoding="utf-8")
        (self.ch4 / "4.8.5 APP基础信息.md").write_text("# 4.8.5 APP基础信息\n", encoding="utf-8")

        self.ch16 = self.tmp / "第16章 RespGo移动端设计"
        self.ch16.mkdir(parents=True, exist_ok=True)
        (self.ch16 / "16.1 验证码服务.md").write_text("# 16.1 验证码服务\n", encoding="utf-8")
        (self.ch16 / "16.2 账号注册.md").write_text("# 16.2 账号注册\n", encoding="utf-8")
        (self.ch16 / "16.16 高频波形数据Protobuf上传.md").write_text("# 16.16 高频波形数据Protobuf上传\n", encoding="utf-8")

        self.ch15 = self.tmp / "第15章 存储设计" / "15.1 呼吸机数据存储"
        self.ch15.mkdir(parents=True, exist_ok=True)
        (self.ch15 / "15.1.1 数据聚合分钟级(数据降维).md").write_text("# 15.1.1\n", encoding="utf-8")
        (self.ch15 / "15.1.3 数据回流／归档恢复.md").write_text("# 15.1.3\n", encoding="utf-8")
        (self.ch15 / "15.1.6 历史数据补偿、重算与校验导出.md").write_text("# 15.1.6\n", encoding="utf-8")

        self.ch10 = self.tmp / "第10章 兼容设计"
        self.ch10.mkdir(parents=True, exist_ok=True)
        (self.ch10 / "10.1 结果集覆盖更新").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_safe_markdown_url(self):
        from doc_tool.application.content.revision_record import safe_markdown_url

        url = safe_markdown_url("第16章 RespGo/16.1 服务(测试).md", is_dir=False)
        self.assertEqual(url, "第16章%20RespGo/16.1%20服务%28测试%29.md")

        dir_url = safe_markdown_url("第4章 WEB端/4.8 Kmilight", is_dir=True)
        self.assertEqual(dir_url, "第4章%20WEB端/4.8%20Kmilight/")

    def test_section_catalog_resolution(self):
        from doc_tool.application.content.revision_record import SectionCatalog

        cat = SectionCatalog(self.tmp)
        self.assertIsNotNone(cat.resolve("第16章 RespGo移动端设计"))
        self.assertIsNotNone(cat.resolve("第16章"))
        self.assertIsNotNone(cat.resolve("16.1 验证码服务"))
        self.assertIsNotNone(cat.resolve("16.1"))
        self.assertIsNotNone(cat.resolve("4.8.5 APP基础信息"))
        self.assertIsNotNone(cat.resolve("4.8 Kmilight"))
        self.assertIsNotNone(cat.resolve("15.1.1"))

    def test_link_revision_summary(self):
        from doc_tool.application.content.revision_record import SectionCatalog, link_revision_summary

        cat = SectionCatalog(self.tmp)
        text = (
            "新增模块：<br>第4章 WEB端功能设计 -> 4.8 Kmilight -> 4.8.5 APP基础信息（移动应用通用基础元数据配置）<br>"
            "第16章 RespGo移动端设计（细化拆解：16.1 验证码服务、16.2 账号注册、16.16 波形数据Protobuf上传）"
        )
        linked = link_revision_summary(text, cat)
        self.assertIn("[第4章 WEB端功能设计](第4章%20WEB端功能设计/)", linked)
        self.assertIn("[4.8 Kmilight](第4章%20WEB端功能设计/4.8%20Kmilight/)", linked)
        self.assertIn("[4.8.5 APP基础信息](第4章%20WEB端功能设计/4.8%20Kmilight/4.8.5%20APP基础信息.md)", linked)
        self.assertIn("（移动应用通用基础元数据配置）", linked)  # 括号说明未被吞入链接
        self.assertIn("[16.1 验证码服务](第16章%20RespGo移动端设计/16.1%20验证码服务.md)", linked)
        self.assertIn("[16.2 账号注册](第16章%20RespGo移动端设计/16.2%20账号注册.md)", linked)
        self.assertIn("[16.16 波形数据Protobuf上传](第16章%20RespGo移动端设计/16.16%20高频波形数据Protobuf上传.md)", linked)

        # 验证幂等性
        second = link_revision_summary(linked, cat)
        self.assertEqual(second, linked)

    def test_autolink_revision_record_text(self):
        from doc_tool.application.content.revision_record import autolink_revision_record_text

        md_table = (
            "# 修订记录\n\n"
            "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
            "|------|----------|----------|--------|\n"
            "| V1.0 | 初始化基本信息 | / | / |\n"
            "| V2.0 | 新增模块：第16章 RespGo移动端设计 -> 16.1 验证码服务 | 2026-08-31 | 李鸿鑫 |\n"
        )

        # 测试全量
        new_md, updated, total = autolink_revision_record_text(md_table, self.tmp)
        self.assertEqual(updated, 1)
        self.assertGreaterEqual(total, 2)
        self.assertIn("[16.1 验证码服务]", new_md)

        # 测试 latest
        new_md2, updated2, total2 = autolink_revision_record_text(md_table, self.tmp, target_version="latest")
        self.assertEqual(updated2, 1)
        self.assertIn("[16.1 验证码服务]", new_md2)

        # 测试特定不存在的版本
        new_md3, updated3, total3 = autolink_revision_record_text(md_table, self.tmp, target_version="V3.0")
        self.assertEqual(updated3, 0)
        self.assertEqual(total3, 0)

    def test_autolink_revision_record_file_and_dry_run(self):
        from doc_tool.application.content.revision_record import autolink_revision_record

        md_file = self.tmp / "_revision_record.md"
        md_table = (
            "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
            "|------|----------|----------|--------|\n"
            "| V2.0 | 新增：16.1 验证码服务 | / | / |\n"
        )
        md_file.write_text(md_table, encoding="utf-8")

        # dry_run 检查
        upd, links, preview = autolink_revision_record(md_file, self.tmp, dry_run=True)
        self.assertEqual(upd, 1)
        self.assertEqual(links, 1)
        self.assertEqual(md_file.read_text(encoding="utf-8"), md_table)  # 未写盘

        # 真实写盘
        upd2, links2, _ = autolink_revision_record(md_file, self.tmp, dry_run=False)
        self.assertEqual(upd2, 1)
        self.assertIn("[16.1 验证码服务]", md_file.read_text(encoding="utf-8"))

    def test_build_docx_renders_markdown_links_in_revision_table(self):
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpressions:
            def __init__(self):
                self.bookmarks = {
                    "16.1 验证码服务": "bm_161",
                    "第16章 RespGo移动端设计": "bm_ch16",
                }
            def find_bookmark_for_section(self, token):
                return self.bookmarks.get(token)

        cell = etree.Element(qn("tc"))
        text = (
            "新增模块：<br>[第16章 RespGo移动端设计](第16章%20RespGo移动端设计/) -> "
            "[16.1 验证码服务](第16章%20RespGo移动端设计/16.1%20验证码服务.md)（用户身份核验）"
        )
        _set_revision_summary_cell(cell, text, expressions=FakeExpressions())

        paragraphs = cell.findall(qn("p"))
        self.assertEqual(len(paragraphs), 1)
        p = paragraphs[0]
        hyperlinks = p.findall(qn("hyperlink"))
        self.assertEqual(len(hyperlinks), 2)
        self.assertEqual(hyperlinks[0].get(qn("anchor")), "bm_ch16")
        self.assertEqual(hyperlinks[1].get(qn("anchor")), "bm_161")

        # 验证超链接严格仅包含章节/小节编号，后随说明文字为普通文本
        hl_texts = ["".join(t.text or "" for t in hl.iter(qn("t"))) for hl in hyperlinks]
        self.assertEqual(hl_texts, ["第16章", "16.1"])

        # 验证显示文字不含原始 Markdown 标记
        t_nodes = p.iter(qn("t"))
        all_text = "".join(t.text or "" for t in t_nodes)
        self.assertNotIn("](", all_text)
        self.assertNotIn(".md", all_text)
        self.assertIn("16.1 验证码服务", all_text)
        self.assertIn("（用户身份核验）", all_text)

    def test_unspaced_section_names(self):
        from doc_tool.application.content.revision_record import SectionCatalog, link_revision_summary

        cat = SectionCatalog(self.tmp)
        # 章节编号与名称无空格连接时，必须整体识别为一个小节链接，不能切断
        text = "新增模块：10.1结果集覆盖更新<br>16.1验证码服务"
        linked = link_revision_summary(text, cat)
        self.assertIn("[10.1结果集覆盖更新](第10章%20兼容设计/10.1%20结果集覆盖更新/)", linked)
        self.assertIn("[16.1验证码服务](第16章%20RespGo移动端设计/16.1%20验证码服务.md)", linked)

    def test_punctuation_and_slash_in_title(self):
        from doc_tool.application.content.revision_record import SectionCatalog, link_revision_summary

        cat = SectionCatalog(self.tmp)
        # 标题包含顿号或斜杠时，完整标题必须被链接包裹，不被标点错误截断
        text = (
            "重构：15.1.6 历史数据补偿、重算与校验导出<br>"
            "15.1.3 数据回流/归档恢复"
        )
        linked = link_revision_summary(text, cat)
        self.assertIn("[15.1.6 历史数据补偿、重算与校验导出](第15章%20存储设计/15.1%20呼吸机数据存储/15.1.6%20历史数据补偿、重算与校验导出.md)", linked)
        self.assertIn("[15.1.3 数据回流/归档恢复](第15章%20存储设计/15.1%20呼吸机数据存储/15.1.3%20数据回流／归档恢复.md)", linked)

    def test_subsection_prefix_fallback(self):
        from doc_tool.application.content.revision_record import SectionCatalog, link_revision_summary

        cat = SectionCatalog(self.tmp)
        # 细化子编号 4.8.1.4 回退到父小节文件 4.8.1 APP用户反馈.md
        text = "4.8.1.4 核心逻辑调整"
        linked = link_revision_summary(text, cat)
        self.assertIn("[4.8.1.4](第4章%20WEB端功能设计/4.8%20Kmilight/4.8.1%20APP用户反馈.md)", linked)

    def test_stop_words_protection(self):
        from doc_tool.application.content.revision_record import SectionCatalog, link_revision_summary

        cat = SectionCatalog(self.tmp)
        # 范围描述中的“各子模块”不应被错误吞入链接文本
        text = "覆盖 16.1~16.20各子模块"
        linked = link_revision_summary(text, cat)
        self.assertIn("[16.1](第16章%20RespGo移动端设计/16.1%20验证码服务.md)", linked)
        self.assertIn("各子模块", linked)
        self.assertNotIn("[16.1~16.20各子模块]", linked)

    def test_build_docx_matches_bookmark_by_target_path(self):
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpressions:
            def __init__(self):
                # 书签 key 为规范化后的全路径，label 文本可能被作者简写
                self.bookmarks = {
                    "D:/repo/content/第16章 RespGo移动端设计/16.1 验证码服务.md": "bm_exact_path",
                }
            def find_bookmark_for_section(self, token):
                return None

        cell = etree.Element(qn("tc"))
        text = "[验证码认证流程](第16章%20RespGo移动端设计/16.1%20验证码服务.md)"
        _set_revision_summary_cell(cell, text, expressions=FakeExpressions())

        paragraphs = cell.findall(qn("p"))
        self.assertEqual(len(paragraphs), 1)
        hyperlinks = paragraphs[0].findall(qn("hyperlink"))
        self.assertEqual(len(hyperlinks), 1)
        self.assertEqual(hyperlinks[0].get(qn("anchor")), "bm_exact_path")


    def test_build_docx_renders_markdown_links_without_expressions(self):
        """当 expressions 为 None 时，Markdown 链接也应被安全剥离语法渲染为纯文本，不泄露原始标记。"""
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        cell = etree.Element(qn("tc"))
        text = "更新：[16.1 验证码服务](第16章%20RespGo移动端设计/16.1%20验证码服务.md)（功能补充）"
        _set_revision_summary_cell(cell, text, expressions=None)

        paragraphs = cell.findall(qn("p"))
        self.assertEqual(len(paragraphs), 1)
        p = paragraphs[0]
        # 无 expressions 时不生成超链接，但显示文本必须纯净
        hyperlinks = p.findall(qn("hyperlink"))
        self.assertEqual(len(hyperlinks), 0)

        t_nodes = p.iter(qn("t"))
        all_text = "".join(t.text or "" for t in t_nodes)
        self.assertNotIn("](", all_text)
        self.assertNotIn(".md", all_text)
        self.assertIn("16.1 验证码服务", all_text)
        self.assertEqual(all_text, "更新：16.1 验证码服务（功能补充）")

    def test_autolink_revision_record_with_custom_header_and_version_normalization(self):
        """支持「版次」或非「版本」表头，且支持 V 前缀规范化匹配。"""
        from doc_tool.application.content.revision_record import autolink_revision_record_text

        md_table = (
            "# 修订记录\n\n"
            "| 版次 | 修改内容 | 修订时间 | 编制人 |\n"
            "|:----:|:---------|:--------:|:------:|\n"
            "| 1.0  | 初始创建 | 2026-08-01 | 王五 |\n"
            "| V2.0 | 调整：16.1 验证码服务 | 2026-09-01 | 李四 |\n"
        )
        # target_version='latest'
        new_md, updated, total = autolink_revision_record_text(md_table, self.tmp, target_version="latest")
        self.assertEqual(updated, 1)
        self.assertIn("[16.1 验证码服务]", new_md)

        # target_version='2.0' 匹配 'V2.0'
        new_md2, updated2, total2 = autolink_revision_record_text(md_table, self.tmp, target_version="2.0")
        self.assertEqual(updated2, 1)
        self.assertIn("[16.1 验证码服务]", new_md2)

    def test_cli_autolink_execution(self):
        """CLI 命令 doc-tool autolink 执行验证（含 dry-run 与写盘）。"""
        from doc_tool.cli import build_parser, main
        from doc_tool.domain.manifest import ProjectManifest

        proj_dir = self.tmp / "test_project"
        content_dir = proj_dir / "content" / "requirement"
        content_dir.mkdir(parents=True, exist_ok=True)
        # 建立章节文件供索引
        (content_dir / "16.1 验证码服务.md").write_text("# 16.1 验证码服务\n", encoding="utf-8")

        rev_file = content_dir / "_revision_record.md"
        rev_file.write_text(
            "| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
            "|------|----------|----------|--------|\n"
            "| V1.0 | 初始版本 | / | / |\n"
            "| V2.0 | 新增：16.1 验证码服务 | / | / |\n",
            encoding="utf-8",
        )
        manifest = ProjectManifest(
            documentType="requirement",
            documentNo="GX-TEST-CLI",
            documentName="CLI测试项目",
            documentVersion="2.0",
            sourceSha256="0" * 64,
        )
        manifest.save(proj_dir)

        # Dry run 测试
        code = main(["autolink", "--project", str(proj_dir), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertNotIn("[16.1 验证码服务]", rev_file.read_text(encoding="utf-8"))

        # 真实写盘测试
        code2 = main(["autolink", "--project", str(proj_dir), "--latest-only"])
        self.assertEqual(code2, 0)
        self.assertIn("[16.1 验证码服务]", rev_file.read_text(encoding="utf-8"))


    def test_autolink_preserves_escaped_pipe_and_empty_cells(self):
        r"""修订记录摘要中含 \| 转义管道符时，列切分不被破坏，且末尾空列不被丢失。"""
        from doc_tool.application.content.revision_record import autolink_revision_record_text

        md_table = (
            "# 修订记录\n\n"
            "| 版本 | 修改摘要 | 修订时间 | 编制人 | 备注 |\n"
            "|:----:|:---------|:--------:|:------:|:----:|\n"
            "| V1.0 | 初始创建 \\| 基础架构搭建 | 2026-08-01 | 王五 |  |\n"
            "| V2.0 | 优化：16.1 验证码服务 \\| 支持短信与邮箱通道 | 2026-09-01 | 李四 ||\n"
        )
        new_md, updated, total = autolink_revision_record_text(md_table, self.tmp)
        self.assertEqual(updated, 1)
        lines = [l for l in new_md.splitlines() if l.strip().startswith("|") and "V2.0" in l]
        self.assertEqual(len(lines), 1)
        # 验证包含 \| 且列数依然为 5 列数据 + 2 个外边框 = 6 个分隔段
        self.assertIn("[16.1 验证码服务]", lines[0])
        self.assertIn(r"\|", lines[0])
        cells = [c.strip() for c in lines[0].strip("|").split("|")]
        # 由于我们保留了 \|，直接 split("|") 会切分成 6 个，但表格语义完整
        self.assertEqual(len(cells), 6)  # 5 列原内容，其中含一个转义管道符

    def test_autolink_latest_only_modifies_only_last_row(self):
        """target_version='latest' 时，仅末尾最新一行被更新，即使前面存在同版本号行。"""
        from doc_tool.application.content.revision_record import autolink_revision_record_text

        md_table = (
            "| 版本 | 修改摘要 | 修订时间 | 编制人 |\n"
            "|:----:|:---------|:--------:|:------:|\n"
            "| V2.0 | 第一阶段：16.1 验证码服务 | 2026-09-01 | 李四 |\n"
            "| V2.0 | 第二阶段：16.1 验证码服务 | 2026-09-02 | 李四 |\n"
        )
        new_md, updated, total = autolink_revision_record_text(md_table, self.tmp, target_version="latest")
        self.assertEqual(updated, 1)
        lines = [l for l in new_md.splitlines() if l.strip().startswith("|") and "V2.0" in l]
        self.assertNotIn("[16.1 验证码服务]", lines[0])
        self.assertIn("[16.1 验证码服务]", lines[1])

    def test_build_docx_matches_bookmark_with_anchor_fragment(self):
        """Markdown 链接包含 #anchor 锚点片段时，Word 书签能正确解析匹配。"""
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpressions:
            def __init__(self):
                self.bookmarks = {
                    "content/16.1 验证码服务.md": "bm_path_match",
                    "content/16.1 验证码服务.md#frag1": "bm_exact_frag",
                }
            def find_bookmark_for_section(self, token):
                if token == "frag1" or token == "16.1 验证码服务":
                    return "bm_found_section"
                return None

        cell = etree.Element(qn("tc"))
        text = "调整：[16.1 验证码服务](16.1%20验证码服务.md#frag1)已上线"
        _set_revision_summary_cell(cell, text, expressions=FakeExpressions())

        paragraphs = cell.findall(qn("p"))
        self.assertEqual(len(paragraphs), 1)
        hyperlinks = paragraphs[0].findall(qn("hyperlink"))
        self.assertEqual(len(hyperlinks), 1)
        self.assertEqual(hyperlinks[0].get(qn("anchor")), "bm_exact_frag")




    def test_build_docx_links_only_section_number_in_summary(self):
        """正式生成修订表时，仅为章节号与小节序号添加内部超链接，其余文本保持普通纯文本。"""
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpressions:
            def __init__(self):
                self.section_number_map = {
                    "第3章": "bm_ch3",
                    "3.4": "bm_34",
                    "第4章": "bm_ch4",
                    "4.5.1": "bm_451",
                    "4.5.1.1": "bm_4511",
                }
            def find_bookmark_for_section(self, token):
                return self.section_number_map.get(token)

        cell = etree.Element(qn("tc"))
        text = "新增模块：第3章,3.4呼吸机同步时区第4章，4.5.1呼吸睡眠报告 -> 4.5.1.1 流程图"
        _set_revision_summary_cell(cell, text, expressions=FakeExpressions())

        p = cell.find(qn("p"))
        hyperlinks = p.findall(qn("hyperlink"))
        self.assertEqual(len(hyperlinks), 5)
        self.assertEqual(hyperlinks[0].get(qn("anchor")), "bm_ch3")
        self.assertEqual(hyperlinks[1].get(qn("anchor")), "bm_34")
        self.assertEqual(hyperlinks[2].get(qn("anchor")), "bm_ch4")
        self.assertEqual(hyperlinks[3].get(qn("anchor")), "bm_451")
        self.assertEqual(hyperlinks[4].get(qn("anchor")), "bm_4511")

        hl_texts = ["".join(t.text or "" for t in hl.iter(qn("t"))) for hl in hyperlinks]
        self.assertEqual(hl_texts, ["第3章", "3.4", "第4章", "4.5.1", "4.5.1.1"])

        all_text = "".join(t.text or "" for t in p.iter(qn("t")))
        self.assertEqual(all_text, text)

    def test_build_docx_chinese_chapter_number_matching(self):
        """支持中文大写章节号（如 第三章、第八章）匹配对应章节书签。"""
        from lxml import etree
        from build_docx import ExpressionManager, _set_revision_summary_cell, qn

        items = {"word/document.xml": b"<w:document/>"}
        rels_el = etree.Element("Relationships")
        expr = ExpressionManager(items, rels_el, [])
        expr.section_number_map["第3章"] = "bm_ch3"
        expr.section_number_map["第8章"] = "bm_ch8"
        expr.section_number_map["8.4"] = "bm_84"

        cell = etree.Element(qn("tc"))
        text = "第八章安全需求->8.4设备证书 第三章功能需求"
        _set_revision_summary_cell(cell, text, expressions=expr)

        p = cell.find(qn("p"))
        hyperlinks = p.findall(qn("hyperlink"))
        self.assertEqual(len(hyperlinks), 3)
        self.assertEqual(hyperlinks[0].get(qn("anchor")), "bm_ch8")
        self.assertEqual(hyperlinks[1].get(qn("anchor")), "bm_84")
        self.assertEqual(hyperlinks[2].get(qn("anchor")), "bm_ch3")

        hl_texts = ["".join(t.text or "" for t in hl.iter(qn("t"))) for hl in hyperlinks]
        self.assertEqual(hl_texts, ["第八章", "8.4", "第三章"])

    def test_find_bookmark_for_section_directory_stem_with_dot(self):
        """目录名包含点号（如 3.4 呼吸机同步时区）时，find_bookmark_for_section 能精准匹配。"""
        from lxml import etree
        from build_docx import ExpressionManager

        items = {"word/document.xml": b"<w:document/>"}
        rels_el = etree.Element("Relationships")
        expr = ExpressionManager(items, rels_el, [])
        key = "D:/content/design/第3章 设备端功能设计/3.4 呼吸机同步时区"
        expr.wrap_bookmark(etree.Element("p"), key)

        bm = expr.find_bookmark_for_section("3.4")
        self.assertIsNotNone(bm)
        self.assertTrue(bm.startswith("doc_"))

    def test_find_bookmark_prefix_fallback_for_deep_section(self):
        """深层未定义标题的编号（如 4.5.1.1.3）能安全降级定位至父级小节（4.5.1）。"""
        from lxml import etree
        from build_docx import ExpressionManager

        items = {"word/document.xml": b"<w:document/>"}
        rels_el = etree.Element("Relationships")
        expr = ExpressionManager(items, rels_el, [])
        expr.section_number_map["4.5.1"] = "bm_parent_451"

        bm = expr.find_bookmark_for_section("4.5.1.1.3")
        self.assertEqual(bm, "bm_parent_451")

    def test_find_bookmark_for_section_chinese_numerals_beyond_twenty(self):
        """测试中文章节数字超过二十（如第二十一章、第三十章）与省略第字（如3章）能精准标准化匹配。"""
        from lxml import etree
        from build_docx import ExpressionManager

        items = {"word/document.xml": b"<w:document/>"}
        rels_el = etree.Element("Relationships")
        expr = ExpressionManager(items, rels_el, [])
        expr.section_number_map["第21章"] = "bm_ch21"
        expr.section_number_map["第30章"] = "bm_ch30"
        expr.section_number_map["第3章"] = "bm_ch3"

        self.assertEqual(expr.find_bookmark_for_section("第二十一章"), "bm_ch21")
        self.assertEqual(expr.find_bookmark_for_section("第三十章"), "bm_ch30")
        self.assertEqual(expr.find_bookmark_for_section("3章"), "bm_ch3")

    def test_find_bookmark_for_section_directory_with_index_md(self):
        """测试包含 _index.md 的父目录章节能通过标题与全称匹配到稳定书签。"""
        from lxml import etree
        from build_docx import ExpressionManager

        items = {"word/document.xml": b"<w:document/>"}
        rels_el = etree.Element("Relationships")
        expr = ExpressionManager(items, rels_el, [])
        key = "D:/content/design/第3章 设备端功能设计/3.2 呼吸机治疗数据上传/_index.md"
        expr.wrap_bookmark(etree.Element("p"), key)

        bm = expr.find_bookmark_for_section("3.2 呼吸机治疗数据上传")
        self.assertIsNotNone(bm)
        self.assertTrue(bm.startswith("doc_"))

    def test_build_docx_revision_summary_real_world_rows(self):
        """针对真实生产文档修订摘要文本进行综合渲染测试，验证章节号匹配与内部书签跳转。"""
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpressions:
            def __init__(self):
                self.section_number_map = {
                    "第3章": "bm_ch3",
                    "3.1": "bm_sec_31",
                    "3.1.1": "bm_sec_311",
                    "3.1.1.4": "bm_sec_3114",
                    "3.2": "bm_sec_32",
                    "3.4": "bm_sec_34",
                    "第4章": "bm_ch4",
                    "4.1.6.4": "bm_sec_4164",
                    "4.1.13": "bm_sec_4113",
                    "第8章": "bm_ch8",
                    "8.4": "bm_sec_84",
                    "第10章": "bm_ch10",
                    "10.1": "bm_sec_101",
                    "10.2": "bm_sec_102",
                    "10.3": "bm_sec_103",
                }
            def find_bookmark_for_section(self, token):
                if token == "第三章":
                    return "bm_ch3"
                if token == "第八章":
                    return "bm_ch8"
                return self.section_number_map.get(token)

        expr = FakeExpressions()
        cases = [
            (
                "新增模块：第3章 3.2 呼吸机治疗数据上传",
                [("第3章", "bm_ch3"), ("3.2", "bm_sec_32")],
            ),
            (
                "3.4 呼吸机同步时区",
                [("3.4", "bm_sec_34")],
            ),
            (
                "修改模块：第3章，3.1呼吸机结果集上传->更新各个模块内容新增模块：第10章，10.1结果集覆盖更新第10章，10.2数据补偿",
                [
                    ("第3章", "bm_ch3"),
                    ("3.1", "bm_sec_31"),
                    ("第10章", "bm_ch10"),
                    ("10.1", "bm_sec_101"),
                    ("第10章", "bm_ch10"),
                    ("10.2", "bm_sec_102"),
                ],
            ),
            (
                "优化模块：整体文档结构化，并按产品模块修改修改模块：3.1SOA -> 3.1.1登录页 -> 3.1.1.4布局",
                [
                    ("3.1", "bm_sec_31"),
                    ("3.1.1", "bm_sec_311"),
                    ("3.1.1.4", "bm_sec_3114"),
                ],
            ),
            (
                "第八章安全需求->8.4设备证书 第三章功能需求",
                [
                    ("第八章", "bm_ch8"),
                    ("8.4", "bm_sec_84"),
                    ("第三章", "bm_ch3"),
                ],
            ),
            (
                "第10章，10.3云平台显示兼容 -> 设置值超限值兼容。修改模块：第4章，4.1.6.4设备管理->修改批量分配核心逻辑",
                [
                    ("第10章", "bm_ch10"),
                    ("10.3", "bm_sec_103"),
                    ("第4章", "bm_ch4"),
                    ("4.1.6.4", "bm_sec_4164"),
                ],
            ),
        ]

        for text, expected_links in cases:
            cell = etree.Element(qn("tc"))
            _set_revision_summary_cell(cell, text, expressions=expr)
            p = cell.find(qn("p"))
            hyperlinks = p.findall(qn("hyperlink"))
            actual_links = [
                ("".join(t.text or "" for t in hl.iter(qn("t"))), hl.get(qn("anchor")))
                for hl in hyperlinks
            ]
            self.assertEqual(actual_links, expected_links, f"Failed for text: {text}")
            all_text = "".join(t.text or "" for t in p.iter(qn("t")))
            self.assertEqual(all_text, text, f"Text corrupted for: {text}")


    def test_build_docx_revision_summary_with_real_expression_manager(self):
        """使用真实的 ExpressionManager（注册包含完整标题的目录与文件条目）测试真实修订记录行，
        确保即使存在同名完整标题，也精准只为章节号（如 3.4, 第3章）添加超链接，正文文字不被污染。"""
        import re
        from lxml import etree
        from build_docx import ExpressionManager, _set_revision_summary_cell, qn
        from docx_common import ChapterEntry

        items = {"word/document.xml": b"<w:document/>"}
        rels_el = etree.Element("Relationships")
        entries = [
            (ChapterEntry("dir", (3,), "设备端功能设计", "D:/content/第3章 设备端功能设计", 1), None),
            (ChapterEntry("file", (3, 1), "呼吸机结果集上传", "D:/content/第3章 设备端功能设计/3.1 呼吸机结果集上传.md", 2), "D:/content/第3章 设备端功能设计/3.1 呼吸机结果集上传.md"),
            (ChapterEntry("file", (3, 1, 1), "设备管理", "D:/content/第3章 设备端功能设计/3.1.1 设备管理.md", 3), "D:/content/第3章 设备端功能设计/3.1.1 设备管理.md"),
            (ChapterEntry("file", (3, 1, 1, 4), "布局", "D:/content/第3章 设备端功能设计/3.1.1.4 布局.md", 4), "D:/content/第3章 设备端功能设计/3.1.1.4 布局.md"),
            (ChapterEntry("file", (3, 2), "呼吸机治疗数据上传", "D:/content/第3章 设备端功能设计/3.2 呼吸机治疗数据上传.md", 2), "D:/content/第3章 设备端功能设计/3.2 呼吸机治疗数据上传.md"),
            (ChapterEntry("file", (3, 4), "呼吸机同步时区", "D:/content/第3章 设备端功能设计/3.4 呼吸机同步时区.md", 2), "D:/content/第3章 设备端功能设计/3.4 呼吸机同步时区.md"),
            (ChapterEntry("dir", (4,), "WEB端功能设计", "D:/content/第4章 WEB端功能设计", 1), None),
            (ChapterEntry("file", (4, 1, 6, 4), "设备管理", "D:/content/第4章 WEB端功能设计/4.1.6.4 设备管理.md", 4), "D:/content/第4章 WEB端功能设计/4.1.6.4 设备管理.md"),
            (ChapterEntry("dir", (8,), "安全需求", "D:/content/第8章 安全需求", 1), None),
            (ChapterEntry("file", (8, 4), "设备证书", "D:/content/第8章 安全需求/8.4 设备证书.md", 2), "D:/content/第8章 安全需求/8.4 设备证书.md"),
            (ChapterEntry("dir", (10,), "兼容设计", "D:/content/第10章 兼容设计", 1), None),
            (ChapterEntry("file", (10, 1), "结果集覆盖更新", "D:/content/第10章 兼容设计/10.1 结果集覆盖更新.md", 2), "D:/content/第10章 兼容设计/10.1 结果集覆盖更新.md"),
            (ChapterEntry("file", (10, 2), "数据补偿", "D:/content/第10章 兼容设计/10.2 数据补偿.md", 2), "D:/content/第10章 兼容设计/10.2 数据补偿.md"),
            (ChapterEntry("file", (10, 3), "云平台显示兼容", "D:/content/第10章 兼容设计/10.3 云平台显示兼容.md", 2), "D:/content/第10章 兼容设计/10.3 云平台显示兼容.md"),
        ]
        expr = ExpressionManager(items, rels_el, entries)

        # 验证章标题自动注册到 section_title_map
        self.assertIn("第3章 设备端功能设计", expr.section_title_map)
        self.assertIn("第3章设备端功能设计", expr.section_title_map)

        cases = [
            (
                "新增模块：第3章 3.2 呼吸机治疗数据上传",
                [
                    ("第3章", expr.find_bookmark_for_section("第3章")),
                    ("3.2", expr.find_bookmark_for_section("3.2")),
                ],
            ),
            (
                "3.4 呼吸机同步时区",
                [("3.4", expr.find_bookmark_for_section("3.4"))],
            ),
            (
                "优化模块：整体文档结构化，并按产品模块修改修改模块：3.1SOA -> 3.1.1登录页 -> 3.1.1.4布局",
                [
                    ("3.1", expr.find_bookmark_for_section("3.1")),
                    ("3.1.1", expr.find_bookmark_for_section("3.1.1")),
                    ("3.1.1.4", expr.find_bookmark_for_section("3.1.1.4")),
                ],
            ),
            (
                "第八章安全需求->8.4设备证书 第三章功能需求",
                [
                    ("第八章", expr.find_bookmark_for_section("第八章")),
                    ("8.4", expr.find_bookmark_for_section("8.4")),
                    ("第三章", expr.find_bookmark_for_section("第三章")),
                ],
            ),
            (
                "更新：[3.4 呼吸机同步时区](D:/content/第3章%20设备端功能设计/3.4%20呼吸机同步时区.md)（新协议）",
                [("3.4", expr.find_bookmark_for_section("3.4"))],
            ),
            (
                "新增模块：[第3章 设备端功能设计](D:/content/第3章%20设备端功能设计) -> [3.2 呼吸机治疗数据上传](D:/content/第3章%20设备端功能设计/3.2%20呼吸机治疗数据上传.md)",
                [
                    ("第3章", expr.find_bookmark_for_section("第3章")),
                    ("3.2", expr.find_bookmark_for_section("3.2")),
                ],
            ),
        ]

        for text, expected_links in cases:
            cell = etree.Element(qn("tc"))
            _set_revision_summary_cell(cell, text, expressions=expr)
            p = cell.find(qn("p"))
            hyperlinks = p.findall(qn("hyperlink"))
            actual_links = [
                ("".join(t.text or "" for t in hl.iter(qn("t"))), hl.get(qn("anchor")))
                for hl in hyperlinks
            ]
            self.assertEqual(actual_links, expected_links, f"Failed for text: {text}")
            all_text = "".join(t.text or "" for t in p.iter(qn("t")))
            expected_text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
            self.assertEqual(all_text, expected_text, f"Text corrupted for: {text}")


    def test_build_docx_markdown_links_prioritize_section_over_file(self):
        """Markdown 链接优先按章节号查找锚点，严格仅为序号加超链接，避免链接到外部文件或污染文字。"""
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn

        class FakeExpressions:
            def __init__(self):
                self.bookmarks = {
                    "D:/repo/content/03_requirements.md": "bm_file_req",
                    "D:/repo/content/16.1 验证码服务.md": "bm_file_161",
                }
                self.section_number_map = {
                    "3.4": "bm_sec_34",
                    "16.1": "bm_sec_161",
                    "第3章": "bm_ch_3",
                }
            def find_bookmark_for_section(self, token):
                return self.section_number_map.get(token)

        expr = FakeExpressions()

        # 场景 1：目标为 .md 文件路径（无 #），但 label 含有小节编号 3.4，优先匹配 3.4 章节书签且仅链接 3.4
        cell1 = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell1, "[3.4 呼吸机同步时区](03_requirements.md)", expressions=expr)
        p1 = cell1.find(qn("p"))
        hls1 = p1.findall(qn("hyperlink"))
        self.assertEqual(len(hls1), 1)
        self.assertEqual(hls1[0].get(qn("anchor")), "bm_sec_34")
        self.assertEqual("".join(hls1[0].itertext()), "3.4")
        self.assertEqual("".join(p1.itertext()), "3.4 呼吸机同步时区")

        # 场景 2：外部 HTTP 链接中含有 3.4 编号，依然匹配内部 3.4 书签跳转，不产生外部文件链接
        cell2 = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell2, "[3.4 呼吸机同步时区](https://example.com/spec.md)", expressions=expr)
        p2 = cell2.find(qn("p"))
        hls2 = p2.findall(qn("hyperlink"))
        self.assertEqual(len(hls2), 1)
        self.assertEqual(hls2[0].get(qn("anchor")), "bm_sec_34")
        self.assertEqual("".join(hls2[0].itertext()), "3.4")
        self.assertEqual("".join(p2.itertext()), "3.4 呼吸机同步时区")

        # 场景 3：外部链接无任何章节序号，不生成超链接，降级为普通正文
        cell3 = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell3, "[外部参考规范](https://example.com/spec.md)", expressions=expr)
        p3 = cell3.find(qn("p"))
        self.assertEqual(len(p3.findall(qn("hyperlink"))), 0)
        self.assertEqual("".join(p3.itertext()), "外部参考规范")

        # 场景 4：一行内包含多个 Markdown 链接，验证章与节均仅链接各自序号
        cell4 = etree.Element(qn("tc"))
        text4 = "新增：[第3章 设备端设计](03.md) -> [3.4 呼吸机同步时区](3.4.md)"
        _set_revision_summary_cell(cell4, text4, expressions=expr)
        p4 = cell4.find(qn("p"))
        hls4 = p4.findall(qn("hyperlink"))
        self.assertEqual(len(hls4), 2)
        self.assertEqual(hls4[0].get(qn("anchor")), "bm_ch_3")
        self.assertEqual("".join(hls4[0].itertext()), "第3章")
        self.assertEqual(hls4[1].get(qn("anchor")), "bm_sec_34")
        self.assertEqual("".join(hls4[1].itertext()), "3.4")
        self.assertEqual("".join(p4.itertext()), "新增：第3章 设备端设计 -> 3.4 呼吸机同步时区")



    def test_find_bookmark_for_section_variants_and_punctuation(self):
        """测试书签查找支持括号变体、末尾标点、X.0 降级、繁体大写中文数字。"""
        from build_docx import ExpressionManager
        from docx_common import ChapterEntry
        from lxml import etree
        import build_docx as bdocx

        items = {}
        rels_el = etree.Element(bdocx.RP_NS + "Relationships")
        entries = [
            (ChapterEntry("dir", (1,), "项目概述", "D:/content/01_overview", 1), "D:/content/01_overview/_index.md"),
            (ChapterEntry("dir", (3,), "设备端功能设计", "D:/content/第3章 设备端功能设计", 1), None),
            (ChapterEntry("file", (3, 4), "呼吸机同步时区", "D:/content/第3章 设备端功能设计/3.4 呼吸机同步时区.md", 2), "D:/content/第3章 设备端功能设计/3.4 呼吸机同步时区.md"),
            (ChapterEntry("dir", (10,), "兼容设计", "D:/content/第10章 兼容设计", 1), None),
        ]
        expr = ExpressionManager(items, rels_el, entries)
        bm_34 = expr.section_number_map["3.4"]
        bm_ch3 = expr.section_number_map["第3章"]
        bm_ch1 = expr.section_number_map["第1章"]
        bm_ch10 = expr.section_number_map["第10章"]

        # 变体测试：(3.4)、（3.4）、[3.4]、3.4.、3.4:
        self.assertEqual(expr.find_bookmark_for_section("(3.4)"), bm_34)
        self.assertEqual(expr.find_bookmark_for_section("（3.4）"), bm_34)
        self.assertEqual(expr.find_bookmark_for_section("[3.4]"), bm_34)
        self.assertEqual(expr.find_bookmark_for_section("【3.4】"), bm_34)
        self.assertEqual(expr.find_bookmark_for_section("3.4."), bm_34)
        self.assertEqual(expr.find_bookmark_for_section("3.4:"), bm_34)

        # 章变体测试：第 3 章、第三章、第3、第3节、第三节、三、拾
        self.assertEqual(expr.find_bookmark_for_section("第 3 章"), bm_ch3)
        self.assertEqual(expr.find_bookmark_for_section("第三章"), bm_ch3)
        self.assertEqual(expr.find_bookmark_for_section("第3节"), bm_ch3)
        self.assertEqual(expr.find_bookmark_for_section("第3"), bm_ch3)
        self.assertEqual(expr.find_bookmark_for_section("三"), bm_ch3)
        self.assertEqual(expr.find_bookmark_for_section("叁"), bm_ch3)
        self.assertEqual(expr.find_bookmark_for_section("第十章"), bm_ch10)
        self.assertEqual(expr.find_bookmark_for_section("拾"), bm_ch10)

        # X.0 降级至第 X 章
        self.assertEqual(expr.find_bookmark_for_section("1.0"), bm_ch1)
        self.assertEqual(expr.find_bookmark_for_section("3.0"), bm_ch3)

    def test_directory_chapter_with_and_without_index_md_bookmarks(self):
        """测试目录型章节不论是否有 _index.md 均能双向命中目录路径和文件路径。"""
        from build_docx import ExpressionManager
        from docx_common import ChapterEntry
        from lxml import etree
        import build_docx as bdocx

        items = {}
        rels_el = etree.Element(bdocx.RP_NS + "Relationships")
        entries = [
            (ChapterEntry("dir", (1,), "项目概述", "D:/content/01_overview", 1), "D:/content/01_overview/_index.md"),
            (ChapterEntry("dir", (2,), "无索引目录", "D:/content/02_noindex", 1), None),
        ]
        expr = ExpressionManager(items, rels_el, entries)
        bm_ch1 = expr.section_number_map["第1章"]
        bm_ch2 = expr.section_number_map["第2章"]

        # 有 _index.md：目录路径与 _index.md 均映射到同一书签
        self.assertIn(os.path.abspath("D:/content/01_overview"), expr.bookmarks)
        self.assertIn(os.path.abspath("D:/content/01_overview/_index.md"), expr.bookmarks)
        self.assertEqual(expr.bookmarks[os.path.abspath("D:/content/01_overview")], bm_ch1)
        self.assertEqual(expr.bookmarks[os.path.abspath("D:/content/01_overview/_index.md")], bm_ch1)

        # 无 _index.md：目录路径直接注册书签
        self.assertIn(os.path.abspath("D:/content/02_noindex"), expr.bookmarks)
        self.assertEqual(expr.bookmarks[os.path.abspath("D:/content/02_noindex")], bm_ch2)

    def test_section_catalog_internal_headings_indexing(self):
        """测试 SectionCatalog 扫描 markdown 内部通过 ## 3.4.1 定义的小节标题。"""
        from doc_tool.application.content.revision_record import SectionCatalog
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            ch_dir = Path(temp_dir) / "第3章 设备端功能设计"
            ch_dir.mkdir(parents=True)
            doc_file = ch_dir / "3.2 设备控制.md"
            doc_file.write_text(
                "# 3.2 设备控制\n\n### 3.2.1 蓝牙配对\n\n逻辑说明\n\n### 3.2.2 协议交互\n\n协议说明\n",
                encoding="utf-8"
            )

            cat = SectionCatalog(temp_dir)
            self.assertIn("3.2", cat.num_map)
            self.assertIn("3.2.1", cat.num_map)
            self.assertIn("3.2.2", cat.num_map)
            self.assertIn("#", cat.num_map["3.2.1"])
            self.assertIn("#", cat.num_map["3.2.2"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_end_to_end_docx_generation_with_revision_hyperlinks(self):
        """端到端真机测试：构建实际 DOCX 压缩包，校验 document.xml 中修订表所有的 w:anchor 100% 存在且均为纯序号。"""
        import tempfile
        import shutil
        import zipfile
        import re
        import build_docx as bdocx
        from build_docx import qn
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        template_path = str(repo_root / "templates" / "requirement-template.docx")
        if not os.path.isfile(template_path):
            self.skipTest("未找到 requirement-template.docx 模板文件")

        temp_dir = tempfile.mkdtemp(prefix="docx_audit_test_")
        try:
            content_dir = os.path.join(temp_dir, "content")
            output_docx = os.path.join(temp_dir, "output.docx")
            os.makedirs(content_dir)

            # 构造完整合规的章节树
            ch1_dir = os.path.join(content_dir, "第1章 项目概述")
            os.makedirs(ch1_dir)
            with open(os.path.join(ch1_dir, "_index.md"), "w", encoding="utf-8") as f:
                f.write("系统项目概述。\n")

            ch2_dir = os.path.join(content_dir, "第2章 架构设计")
            os.makedirs(ch2_dir)
            with open(os.path.join(ch2_dir, "2.1 整体架构.md"), "w", encoding="utf-8") as f:
                f.write("系统整体架构。\n")

            ch3_dir = os.path.join(content_dir, "第3章 设备端功能设计")
            os.makedirs(ch3_dir)
            with open(os.path.join(ch3_dir, "_index.md"), "w", encoding="utf-8") as f:
                f.write("设备端功能总述。\n")
            with open(os.path.join(ch3_dir, "3.1 呼吸机治疗数据上传.md"), "w", encoding="utf-8") as f:
                f.write("呼吸机治疗数据上传。\n")
            with open(os.path.join(ch3_dir, "3.2 设备控制.md"), "w", encoding="utf-8") as f:
                f.write("设备控制。\n\n### 3.2.1 蓝牙配对\n\n配对说明。\n\n### 3.2.2 协议交互\n\n交互说明。\n")
            with open(os.path.join(ch3_dir, "3.3 结果集更新.md"), "w", encoding="utf-8") as f:
                f.write("结果集更新。\n")
            with open(os.path.join(ch3_dir, "3.4 呼吸机同步时区.md"), "w", encoding="utf-8") as f:
                f.write("时区同步。\n")

            ch4_dir = os.path.join(content_dir, "第4章 WEB端功能设计", "4.1 设备中心", "4.1.1 设备配置")
            os.makedirs(ch4_dir)
            with open(os.path.join(ch4_dir, "4.1.1.1 设备管理.md"), "w", encoding="utf-8") as f:
                f.write("设备管理。\n")

            ch5_dir = os.path.join(content_dir, "第5章 兼容设计")
            os.makedirs(ch5_dir)
            with open(os.path.join(ch5_dir, "5.1 结果集覆盖更新.md"), "w", encoding="utf-8") as f:
                f.write("结果集覆盖更新。\n")

            ch6_dir = os.path.join(content_dir, "第6章 RespGo移动端设计")
            os.makedirs(ch6_dir)
            with open(os.path.join(ch6_dir, "6.1 验证码服务.md"), "w", encoding="utf-8") as f:
                f.write("验证码服务。\n")

            rev_md = os.path.join(content_dir, "_revision_record.md")
            with open(rev_md, "w", encoding="utf-8") as f:
                f.write("""# 修订记录

| 版本 | 修改摘要 | 修改时间 | 修改人 |
|------|----------|----------|--------|
| 1.0 | 首次创建 | 2026-01-01 | 张三 |
| 1.1 | 新增模块：第3章 3.2 设备控制，包含3.2.1 蓝牙配对 | 2026-02-01 | 李四 |
| 1.2 | 更新：[3.4 呼吸机同步时区](第3章%20设备端功能设计/3.4%20呼吸机同步时区.md) | 2026-03-01 | 王五 |
| 1.3 | 新增小节：3.4. 呼吸机同步时区 及 (5.1) 结果集更新 | 2026-04-01 | 赵六 |
| 1.4 | 优化：第三章 设备端功能设计 -> [3.1 呼吸机治疗数据上传](第3章%20设备端功能设计/3.1%20呼吸机治疗数据上传.md) | 2026-05-01 | 钱七 |
| 1.5 | 重构：第 4 章 WEB端功能设计 -> 4.1.1.1 设备管理 | 2026-06-01 | 孙八 |
| 1.6 | 更新：第6章 RespGo移动端设计（6.1 验证码服务） | 2026-07-01 | 周九 |
| 1.7 | 新增章节：1.0 项目概述 架构总览 | 2026-08-01 | 孙八 |
| 1.8 | 修复：[3.2.1 蓝牙配对](第3章%20设备端功能设计/3.2%20设备控制.md#321-蓝牙配对) 协议交互修复 | 2026-08-15 | 周九 |
| 1.9 | 参考：第3节 设备端功能设计 | 2026-09-01 | 钱七 |
| 2.0 | 更新：[1 项目概述](第1章%20项目概述/_index.md) 补充说明 | 2026-09-10 | 张三 |
| 2.1 | 变体：1 项目概述 前言调整 | 2026-09-18 | 李四 |
""")

            config = {
                "documentType": "audit_e2e_test",
                "documentNo": "DOC-TEST-001",
                "documentName": "全链路测试说明书",
                "documentVersion": "1.6",
                "template": {"file": template_path},
                "contentRoot": {"path": content_dir},
                "headingStyles": {1: "2", 2: "3", 3: "5", 4: "6", 5: "7", 6: "8"},
                "bodyStyle": "4",
                "paths": {
                    "template": template_path,
                    "content_root": content_dir,
                    "revision_record": rev_md,
                    "asset_root": os.path.join(temp_dir, "assets"),
                    "table_root": os.path.join(temp_dir, "tables"),
                },
            }
            os.makedirs(config["paths"]["asset_root"], exist_ok=True)
            os.makedirs(config["paths"]["table_root"], exist_ok=True)

            bdocx.build(output_override=output_docx, config=config)
            self.assertTrue(os.path.isfile(output_docx))

            with zipfile.ZipFile(output_docx, "r") as zf:
                doc_xml = zf.read("word/document.xml")
            from lxml import etree
            doc_tree = etree.fromstring(doc_xml)

            all_bookmarks = {}
            for p in doc_tree.iter(qn("p")):
                p_text = "".join(p.itertext())
                for bm_start in p.findall(qn("bookmarkStart")):
                    bm_name = bm_start.get(qn("name"))
                    all_bookmarks[bm_name] = (p, p_text)

            body = doc_tree.find(qn("body"))
            rev_tbl = bdocx._find_revision_record_table(body)
            self.assertIsNotNone(rev_tbl)

            rows = rev_tbl.findall(qn("tr"))
            data_rows = rows[2:]
            total_links = 0
            num_pattern = re.compile(r"^(第\s*[0-9一二三四五六七八九十百]+\s*[章节]|第?\s*[0-9一二三四五六七八九十百]+\s*章|\d+(?:\.\d+)+|\d+)$")
            for r_idx, row in enumerate(data_rows):
                cells = row.findall(qn("tc"))
                summary_cell = cells[1]
                summary_p = summary_cell.find(qn("p"))
                hyperlinks = summary_p.findall(qn("hyperlink"))
                for hl in hyperlinks:
                    anchor = hl.get(qn("anchor"))
                    link_text = "".join(hl.itertext())
                    total_links += 1

                    # 1. 每一个 w:anchor 都有 100% 对应的 bookmarkStart
                    self.assertIn(anchor, all_bookmarks, f"锚点 {anchor} 在 document.xml 中不存在")

                    # 2. 超链接文字严格仅为序号
                    self.assertTrue(bool(num_pattern.match(link_text.strip())), f"链接文字不是纯序号: {link_text}")

                    # 3. 书签段落为标题段落
                    target_p, _ = all_bookmarks[anchor]
                    pPr = target_p.find(qn("pPr"))
                    pStyle = pPr.find(qn("pStyle")).get(qn("val")) if pPr is not None and pPr.find(qn("pStyle")) is not None else "None"
                    self.assertIn(pStyle, ["2", "3", "5", "6", "7", "8"])

            self.assertGreaterEqual(total_links, 17)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)



class SectionCatalogEnhanceTest(unittest.TestCase):
    """测试 SectionCatalog 与 link_revision_summary 对阿拉伯数字目录、中文大写章节、前缀降级与变体的支持。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "1 概述"))
        with open(os.path.join(self.tmp, "1 概述", "_index.md"), "w", encoding="utf-8") as f:
            f.write("概述说明。\n")
        os.makedirs(os.path.join(self.tmp, "2 系统架构"))
        with open(os.path.join(self.tmp, "2 系统架构", "2.1 模块划分.md"), "w", encoding="utf-8") as f:
            f.write("模块说明。\n")
        os.makedirs(os.path.join(self.tmp, "第三章 详细设计"))
        with open(os.path.join(self.tmp, "第三章 详细设计", "3.4 设备管理.md"), "w", encoding="utf-8") as f:
            f.write("设备说明。\n")
        from doc_tool.application.content.revision_record import SectionCatalog
        self.cat = SectionCatalog(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_top_level_arabic_chapter_catalog(self):
        self.assertIn("第1章", self.cat.chap_map)
        self.assertIn("1", self.cat.chap_map)
        from doc_tool.application.content.revision_record import link_revision_summary
        res = link_revision_summary("第1章 概述 补充说明", self.cat)
        self.assertIn("[第1章 概述](1%20概述/_index.md)", res)

    def test_chinese_numeral_chapter_catalog(self):
        self.assertIn("第3章", self.cat.chap_map)
        self.assertIn("3", self.cat.chap_map)
        from doc_tool.application.content.revision_record import link_revision_summary
        res = link_revision_summary("第三章 详细设计 补充接口", self.cat)
        self.assertIn("[第三章 详细设计](第三章%20详细设计/)", res)

    def test_x_dot_zero_fallback(self):
        entry, val = self.cat.find_num_entry("1.0")
        self.assertEqual(entry, "1")

    def test_deep_prefix_fallback_to_chapter(self):
        entry, val = self.cat.find_num_entry("2.5.1")
        self.assertEqual(entry, "2")


    def test_section_variant_and_arabic_numeral_linking(self):
        """测试 第3节、单数字章节（1 概述、[1 概述]）与纯数字序号超链接。"""
        from doc_tool.application.content.revision_record import link_revision_summary
        res_sec = link_revision_summary("参考第3节 界面设计相关规范", self.cat)
        # 支持 [章节] 变体
        self.assertIn("[第3节", res_sec)

    def test_build_docx_renders_arabic_chapter_and_clean_number_links(self):
        """Word 构建侧验证：单数字章节、带点、带括号变体均严格仅链接序号。"""
        from lxml import etree
        from build_docx import _set_revision_summary_cell, qn, ExpressionManager

        class MockExpr:
            def __init__(self):
                self.section_number_map = {
                    "1": "bm_ch1",
                    "第1章": "bm_ch1",
                    "3": "bm_ch3",
                    "第3章": "bm_ch3",
                    "3.4": "bm_34",
                }
                self.section_title_map = {
                    "1 概述": "bm_ch1",
                    "概述": "bm_ch1",
                    "3 详细设计": "bm_ch3",
                    "详细设计": "bm_ch3",
                    "3.4 呼吸机同步时区": "bm_34",
                    "呼吸机同步时区": "bm_34",
                }
                self.bookmarks = {
                    "D:/repo/01 概述/_index.md": "bm_ch1",
                    "D:/repo/03 详细设计/3.4 呼吸机同步时区.md": "bm_34",
                }
            def find_bookmark_for_section(self, tok):
                em = ExpressionManager.__new__(ExpressionManager)
                em.bookmarks = self.bookmarks
                em.section_number_map = self.section_number_map
                em.section_title_map = self.section_title_map
                return em.find_bookmark_for_section(tok)

        expr = MockExpr()
        # 1. 单数字章节 Markdown 链接：严格仅链接序号 "1"
        cell1 = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell1, "[1 概述](01%20概述/_index.md) 补充背景说明", expressions=expr)
        hls1 = cell1.findall(".//" + qn("hyperlink"))
        self.assertEqual(len(hls1), 1)
        self.assertEqual("".join(hls1[0].itertext()), "1")
        self.assertEqual(hls1[0].get(qn("anchor")), "bm_ch1")

        # 2. 单数字章节纯文本：严格仅链接序号 "1"
        cell2 = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell2, "1 概述 补充背景说明", expressions=expr)
        hls2 = cell2.findall(".//" + qn("hyperlink"))
        self.assertEqual(len(hls2), 1)
        self.assertEqual("".join(hls2[0].itertext()), "1")
        self.assertEqual(hls2[0].get(qn("anchor")), "bm_ch1")

        # 3. 常见非章节数字（如 "修改了 5 个页面"）：不产生误报链接
        cell3 = etree.Element(qn("tc"))
        _set_revision_summary_cell(cell3, "修改了 5 个页面，2026年9月发布", expressions=expr)
        hls3 = cell3.findall(".//" + qn("hyperlink"))
        self.assertEqual(len(hls3), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
