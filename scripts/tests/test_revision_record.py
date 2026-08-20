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
        self.assertEqual(last_revision_version(self.md), "V3.8")
        self.assertEqual(document_version_from_record(self.md), "V3.8")

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

    def _manifest(self, version="V3.7"):
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
        manifest = self._manifest("V3.7")
        status, result, plan = self._sync(manifest)
        self.assertEqual(status, "succeeded")
        self.assertEqual(manifest.documentVersion, "V3.8")
        self.assertIn("V3.7 → V3.8", self._detail(result))
        self.assertEqual(
            [event.stage for event in result.events], [STAGE_REVISION] * 2
        )
        # 修订记录文件本身从不被改写：整表内容由构建侧覆盖进 Word。
        self.assertNotIn("V3.9", self.md.read_text(encoding="utf-8"))
        # 构建失败回滚：清单版本号退回原值（清单只在发布成功后落盘）。
        _rollback_revision_sync(plan, manifest, _FakeLog())
        self.assertEqual(manifest.documentVersion, "V3.7")

    def test_same_version_is_noop(self):
        self.md.write_text(
            self._HEADER + "| V3.8 | 上次合并 | 2026-07-01 | 王杰 |\n",
            encoding="utf-8",
        )
        manifest = self._manifest("V3.8")
        status, result, plan = self._sync(manifest)
        self.assertEqual(status, "succeeded")
        self.assertEqual(manifest.documentVersion, "V3.8")
        self.assertIn("已与 _revision_record.md 末行一致", self._detail(result))
        self.assertFalse(plan["applied"])

    def test_missing_record_keeps_manifest_version(self):
        """无修订记录表（旧项目模板也没有）：沿用清单版本号，合并照常。"""
        manifest = self._manifest("V3.7")
        status, result, _plan = self._sync(manifest)
        self.assertEqual(status, "skipped")
        self.assertEqual(manifest.documentVersion, "V3.7")
        self.assertIn("没有修订记录表", self._detail(result))

    def test_header_only_table_keeps_manifest_version(self):
        self.md.write_text("# 修订记录\n\n" + self._HEADER, encoding="utf-8")
        manifest = self._manifest("V3.7")
        status, result, _plan = self._sync(manifest)
        self.assertEqual(status, "skipped")
        self.assertEqual(manifest.documentVersion, "V3.7")
        self.assertIn("还没有数据行", self._detail(result))

    def test_broken_paths_do_not_block_build(self):
        """读取整体失败（清单/路径异常）也只跳过同步，不抛给管线。"""
        broken = types.SimpleNamespace(
            documentVersion="V3.7",
            documentType="requirement",
            relative_content_root=lambda: "",  # 触发 PathEscapeError
            relative_template_docx=lambda: "template/template.docx",
        )
        self.assertIsNone(_prepare_revision_sync(broken, self.paths))
        result = PipelineResult(success=False)
        status = _sync_revision_version(None, broken, result, _FakeLog())
        self.assertEqual(status, "skipped")
        self.assertEqual(broken.documentVersion, "V3.7")
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
            manifest = self._manifest("V2.4")
            status, _result, _plan = self._sync(manifest)
        finally:
            if previous is None:
                sys.modules.pop("extract_revision_record", None)
            else:
                sys.modules["extract_revision_record"] = previous
        self.assertEqual(status, "succeeded")
        self.assertEqual(manifest.documentVersion, "V2.5")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
