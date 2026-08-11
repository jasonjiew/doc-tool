# -*- coding: utf-8 -*-
"""内容操作服务层自动测试（纯服务，不依赖 GUI）。

覆盖：
- 内容索引构建/失效/增量重建（任务 1.x）
- 引用解析与悬空检测（任务 2.x）
- 写入安全与回滚（任务 3.x）
- 全文搜索服务（任务 5.x）
- 全局替换服务（任务 7.x）
- 重命名联动服务（任务 8.x）
- 术语检查服务（任务 9.x）
"""

from __future__ import annotations

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
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make_project(files: dict) -> Path:
    """在临时目录构建 project_root/content/<类型> 结构的假项目，返回 content_root。

    files: {"requirement/第1章 引言/1.1 目的.md": "# 引言\n正文...", ...}

    每个测试使用独立的 project_root（content_root 的父目录），避免 .state 等
    共享系统临时目录导致测试间污染。
    """
    project_root = Path(tempfile.mkdtemp(prefix="doc-tool-content-"))
    content_root = project_root / "content"
    for rel, text in files.items():
        path = content_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return content_root


class ContentIndexTests(unittest.TestCase):
    """任务 1.x：索引构建、失效与增量重建。"""

    def setUp(self) -> None:
        self.files = {
            "requirement/第1章 引言/1.1 目的.md": (
                "# 1.1 目的\n"
                "本功能用于实现健康档案管理。\n"
            ),
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md": (
                "# 3.1.4 居民信息\n"
                "包含居民档案、健康档案。\n"
            ),
            "design/第1章 引言/1.1 目的.md": (
                "# 1.1 目的\n"
                "详细设计说明。\n"
            ),
        }
        self.content_root = make_project(self.files)
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)

    def _build(self):
        from doc_tool.application.content.index import ContentIndexService

        service = ContentIndexService(self.content_root)
        return service.build()

    def test_build_indexes_files_and_types(self):
        """构建后收录全部文件并推断文档类型。"""
        index = self._build()
        self.assertEqual(len(index.files), 3)
        self.assertIn(
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md",
            index.files,
        )
        self.assertEqual(
            index.files[
                "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
            ].document_type,
            "requirement",
        )
        self.assertEqual(index.document_types, {"requirement", "design"})

    def test_build_indexes_type_dir_layout(self):
        """布局 B：content_root 本身是文档类型目录（content/requirement 直接含章节）。

        真实项目 `contentRoot: content/requirement` 时，章节目录直接挂在 content_root
        下（无类型子目录），索引必须能直接递归收录，并按目录名推断文档类型。
        """
        from doc_tool.application.content.index import ContentIndexService

        project_root = Path(tempfile.mkdtemp(prefix="doc-tool-content-b-"))
        self.addCleanup(shutil.rmtree, project_root, ignore_errors=True)
        content_root = project_root / "content" / "requirement"
        files = {
            "第1章 引言/1.1 目的.md": "# 1.1 目的\n正文。\n",
            "第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md": "# 3.1.4 居民信息\n正文。\n",
        }
        for rel, text in files.items():
            path = content_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        service = ContentIndexService(content_root)
        index = service.build()
        self.assertEqual(len(index.files), 2)
        self.assertIn("第1章 引言/1.1 目的.md", index.files)
        # 布局 B 下文档类型由 content_root 目录名推断
        self.assertEqual(
            index.files["第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"].document_type,
            "requirement",
        )
        self.assertEqual(index.document_types, {"requirement"})

    def test_build_indexes_lines(self):
        """行索引保留原始行文本。"""
        index = self._build()
        rel = "requirement/第1章 引言/1.1 目的.md"
        self.assertEqual(index.lines[rel][0], "# 1.1 目的")
        self.assertIn("健康档案管理", index.lines[rel][1])

    def test_build_indexes_headings(self):
        """标题清单解析行号、级别与锚点 id。"""
        index = self._build()
        rel = "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        headings = index.headings[rel]
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0].level, 1)
        self.assertEqual(headings[0].line_no, 1)
        self.assertEqual(headings[0].text, "3.1.4 居民信息")

    def test_slugify_cjk_heading(self):
        """CJK 标题锚点保留中文字符。"""
        from doc_tool.application.content.index import slugify_heading

        self.assertEqual(slugify_heading("3.1.4 居民信息"), "314-居民信息")
        self.assertEqual(slugify_heading("设备管理"), "设备管理")

    def test_invalidate_and_rebuild_file(self):
        """失效后重建单个文件，反映磁盘最新内容。"""
        from doc_tool.application.content.index import ContentIndexService

        service = ContentIndexService(self.content_root)
        index = service.build()
        rel = "requirement/第1章 引言/1.1 目的.md"
        path = self.content_root / rel

        # 外部修改文件后标记失效
        path.write_text("# 1.1 目的（已改）\n新正文\n", encoding="utf-8")
        index.invalidate(rel)
        self.assertFalse(index.is_valid(rel))

        service.rebuild_file(index, rel)
        self.assertTrue(index.is_valid(rel))
        self.assertEqual(index.lines[rel][0], "# 1.1 目的（已改）")

    def test_invalidate_deleted_file_removes_entry(self):
        """文件被删除后重建，条目被移除。"""
        from doc_tool.application.content.index import ContentIndexService

        service = ContentIndexService(self.content_root)
        index = service.build()
        rel = "design/第1章 引言/1.1 目的.md"
        (self.content_root / rel).unlink()
        index.invalidate(rel)
        service.refresh_dirty(index)
        self.assertNotIn(rel, index.files)

    def test_refresh_dirty_rebuilds_all_invalid(self):
        """refresh_dirty 批量重建全部失效文件。"""
        from doc_tool.application.content.index import ContentIndexService

        service = ContentIndexService(self.content_root)
        index = service.build()
        for rel in list(index.files)[:2]:
            index.invalidate(rel)
        service.refresh_dirty(index)
        self.assertEqual(len(index.invalid_files), 0)

    def test_refresh_detects_add_remove_change(self):
        """refresh 全量重扫：新增/删除/变更文件均反映到索引。"""
        from doc_tool.application.content.index import ContentIndexService

        service = ContentIndexService(self.content_root)
        index = service.build()
        # 删除一个、新增一个、修改一个
        (self.content_root / "design/第1章 引言/1.1 目的.md").unlink()
        new_file = self.content_root / "requirement/第3章 功能需求/3.1 KSHC/3.9.9 新增.md"
        new_file.parent.mkdir(parents=True, exist_ok=True)
        new_file.write_text("# 3.9.9 新增\n内容\n", encoding="utf-8")
        changed = self.content_root / "requirement/第1章 引言/1.1 目的.md"
        changed.write_text("# 1.1 目的\n改后\n", encoding="utf-8")

        count = service.refresh(index)
        self.assertEqual(count, len(index.files))
        # 删除的条目被移除
        self.assertNotIn("design/第1章 引言/1.1 目的.md", index.files)
        # 新增的条目已收录
        self.assertIn("requirement/第3章 功能需求/3.1 KSHC/3.9.9 新增.md", index.files)
        # 变更内容已重建
        self.assertEqual(
            index.lines["requirement/第1章 引言/1.1 目的.md"][1],
            "改后",
        )

    def test_build_respects_cancel_token(self):
        """取消令牌在文件边界安全中断索引构建。"""
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.domain.cancellation import CancellationToken

        service = ContentIndexService(self.content_root)
        token = CancellationToken()
        token.request_cancel()
        with self.assertRaises(Exception):
            service.build(cancel_token=token)

    def test_discover_filters_non_type_dirs(self):
        """仅收录文档类型目录内的 .md，非类型目录不入索引。"""
        from doc_tool.application.content.index import ContentIndexService

        stray = self.content_root / "stray-notes/x.md"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("# x\n", encoding="utf-8")
        service = ContentIndexService(self.content_root)
        self.assertEqual(len(service.discover_files()), 3)


class ReferenceScannerTests(unittest.TestCase):
    """任务 2.x：引用解析与悬空检测。"""

    FILES = {
        "requirement/第2章 系统概述/2.3 总体业务图.md": (
            "# 2.3 总体业务图\n"
            "![业务图](images/img_0001.png =642x269)\n"
            "见 [居民信息](3.1.4 居民信息.md) 章节。\n"
        ),
        "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md": (
            "# 3.1.4 居民信息\n"
            "## 设备管理\n"
            "包含居民档案。\n"
            "填写说明见 3.5.1.6.4.1 各治疗模式展示的参数。\n"
            "版本号 2.3.0 不构成章节引用。\n"
            "链接到缺失文件 [x](9.9.9 不存在.md)。\n"
            "纯锚点 [设备管理](#设备管理)。\n"
            "锚点缺失 [y](#不存在的锚点)。\n"
            "外部链接 [官网](https://example.com)。\n"
        ),
        "requirement/第3章 功能需求/3.5 KSAT/3.5.1 呼吸睡眠报告.md": (
            "# 3.5.1 呼吸睡眠报告\n"
            "## 3.5.1.6.4.1 各治疗模式展示的参数\n"
            "展示各治疗模式参数。\n"
        ),
    }

    def setUp(self) -> None:
        self.content_root = make_project(self.FILES)
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)
        # 提供 assets 目录用于图片解析
        img = self.project_root / "assets/requirement/images/img_0001.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"fake")

    def _scan(self):
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner

        index = ContentIndexService(self.content_root).build()
        scanner = ReferenceScanner(index, assets_root=self.project_root / "assets")
        scanner.scan_all()
        return index

    def _refs_of(self, index, rel):
        return index.references.get(rel, [])

    def test_file_link_resolved(self):
        """指向存在 .md 的链接解析为 REF_LINK 且非悬空。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第2章 系统概述/2.3 总体业务图.md"
        )
        link = next(r for r in refs if r.kind == "link")
        self.assertEqual(
            link.target_rel_path,
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md",
        )
        self.assertFalse(link.dangling)

    def test_file_link_dangling(self):
        """指向不存在 .md 的链接标记为确定缺失悬空。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        link = next(r for r in refs if r.kind == "link" and r.dangling)
        self.assertEqual(link.dangling_kind, "confirmed")
        self.assertIsNone(link.target_rel_path)

    def test_section_number_matches_file(self):
        """章节号匹配文件级章节为确认引用。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        section = next(
            r for r in refs if r.kind == "section" and r.target == "3.5.1.6.4.1"
        )
        # 3.5.1.6.4.1 是 3.5.1 文件内的标题编号
        self.assertEqual(
            section.target_rel_path,
            "requirement/第3章 功能需求/3.5 KSAT/3.5.1 呼吸睡眠报告.md",
        )
        self.assertFalse(section.dangling)

    def test_section_number_version_not_flagged(self):
        """版本号（无上下文关键词）不构成悬空引用。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        self.assertFalse(
            any(r.kind == "section" and r.target == "2.3.0" for r in refs)
        )

    def test_section_number_suspect_with_context(self):
        """未命中章节但带上下文关键词的标记为疑似悬空。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        suspects = [r for r in refs if r.dangling and r.dangling_kind == "suspect"]
        # "填写说明见 3.5.1.6.4.1 ..." 已匹配文件内标题，因此无疑似；
        # 该用例的"疑似"需构造：见 8.8.8 不存在章节
        self.assertEqual(suspects, [])

    def test_pure_anchor_resolved(self):
        """纯锚点链接匹配当前文件标题。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        anchor = next(r for r in refs if r.kind == "anchor" and not r.dangling)
        self.assertEqual(anchor.target, "设备管理")
        self.assertFalse(anchor.dangling)

    def test_pure_anchor_dangling(self):
        """缺失锚点链接标记为确定缺失悬空。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        anchor = next(r for r in refs if r.kind == "anchor" and r.dangling)
        self.assertEqual(anchor.dangling_kind, "confirmed")

    def test_image_link_resolved_against_assets(self):
        """图片链接按 assets/<类型>/images 解析；存在则不悬空。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第2章 系统概述/2.3 总体业务图.md"
        )
        image = next(r for r in refs if r.kind == "image")
        self.assertEqual(image.target, "images/img_0001.png")
        self.assertFalse(image.dangling)

    def test_external_link_skipped(self):
        """外部 URL 链接不生成引用。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        )
        self.assertFalse(any("example.com" in r.target for r in refs))

    def test_link_target_not_double_counted_as_section(self):
        """链接目标内的数字不被重复识别为章节引用。"""
        index = self._scan()
        refs = self._refs_of(
            index, "requirement/第2章 系统概述/2.3 总体业务图.md"
        )
        section_targets = [r.target for r in refs if r.kind == "section"]
        self.assertNotIn("3.1.4", section_targets)

    def test_suspect_section_with_context_keyword(self):
        """"见 8.8.8"（未命中章节）标记为疑似悬空。"""
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner

        self.content_root.joinpath(
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        ).write_text(
            self.FILES[
                "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
            ]
            + "补充说明见 8.8.8。\n",
            encoding="utf-8",
        )
        index = ContentIndexService(self.content_root).build()
        ReferenceScanner(
            index, assets_root=self.project_root / "assets"
        ).scan_all()
        refs = index.references[
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"
        ]
        suspect = next(
            r for r in refs if r.kind == "section" and r.target == "8.8.8"
        )
        self.assertTrue(suspect.dangling)
        self.assertEqual(suspect.dangling_kind, "suspect")


class WriteSafetyTests(unittest.TestCase):
    """任务 3.x：备份、原子写、改动清单与回滚。"""

    def setUp(self) -> None:
        self.content_root = make_project(
            {"requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\n原始正文\n"}
        )
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)

    def _writer(self):
        from doc_tool.application.content.writer import ContentWriter

        return ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_write_text_backs_up_and_writes(self):
        """写入前备份 .bak，写入后内容更新。"""
        from pathlib import Path

        writer = self._writer()
        result = writer.write_text(
            "requirement/第1章 引言/1.1 目的.md", "# 1.1 目的\n新正文\n"
        )
        self.assertTrue(result.written)
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 目的.md"),
            "# 1.1 目的\n新正文\n",
        )
        bak = Path(result.backup_path)
        self.assertTrue(bak.exists())
        self.assertEqual(bak.read_text(encoding="utf-8"), "# 1.1 目的\n原始正文\n")

    def test_write_text_records_manifest_entry(self):
        """写入后清单记录 edit 条目。"""
        writer = self._writer()
        writer.write_text("requirement/第1章 引言/1.1 目的.md", "x")
        writer.manifest.load()
        entries = writer.manifest.entries
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0].rel_path, "requirement/第1章 引言/1.1 目的.md"
        )
        self.assertEqual(entries[0].operation, "edit")

    def test_write_text_escape_path_rejected(self):
        """越出 contentRoot 的相对路径被拒绝且不写盘。"""
        writer = self._writer()
        result = writer.write_text("../../evil.md", "x")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_write_failure_keeps_backup(self):
        """原子写失败时保留备份并返回错误。"""
        from unittest import mock

        writer = self._writer()
        with mock.patch(
            "doc_tool.application.content.writer.atomic_write",
            side_effect=OSError("disk full"),
        ):
            result = writer.write_text(
                "requirement/第1章 引言/1.1 目的.md", "x"
            )
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)
        # 备份仍存在
        self.assertTrue(
            (self.content_root / "requirement/第1章 引言/1.1 目的.md.bak").exists()
        )

    def test_rename_records_and_moves(self):
        """重命名移动文件并记录 rename 条目。"""
        writer = self._writer()
        result = writer.rename(
            "requirement/第1章 引言/1.1 目的.md",
            "requirement/第1章 引言/1.1 目标.md",
        )
        self.assertTrue(result.written)
        self.assertTrue(
            (self.content_root / "requirement/第1章 引言/1.1 目标.md").exists()
        )
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 目的.md").exists()
        )
        writer.manifest.load()
        entry = writer.manifest.entries[0]
        self.assertEqual(entry.operation, "rename")
        self.assertEqual(entry.original_path, "requirement/第1章 引言/1.1 目的.md")

    def test_rollback_restores_edit_content(self):
        """回滚用 .bak 恢复编辑内容。"""
        writer = self._writer()
        writer.write_text(
            "requirement/第1章 引言/1.1 目的.md", "# 1.1 目的\n被改\n"
        )
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 目的.md"),
            "# 1.1 目的\n原始正文\n",
        )
        writer.manifest.load()
        self.assertTrue(writer.manifest.empty)

    def test_rollback_restores_rename(self):
        """回滚把文件移回原名并恢复内容。"""
        writer = self._writer()
        writer.rename(
            "requirement/第1章 引言/1.1 目的.md",
            "requirement/第1章 引言/1.1 目标.md",
        )
        # 改名后再编辑新文件
        writer.write_text(
            "requirement/第1章 引言/1.1 目标.md", "# 1.1 目标\n内容\n"
        )
        failures = writer.rollback()
        self.assertEqual(failures, [])
        # rename 条目回滚后应恢复到原文件
        self.assertTrue(
            (self.content_root / "requirement/第1章 引言/1.1 目的.md").exists()
        )
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 目的.md"),
            "# 1.1 目的\n原始正文\n",
        )


class ChapterTreeModelTests(unittest.TestCase):
    """任务 4.x：章节树模型推导（纯函数，不依赖 Tk）。"""

    FILES = [
        "requirement/第1章 引言/1.1 目的.md",
        "requirement/第1章 引言/1.2 范围.md",
        "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md",
        "design/第1章 引言/1.1 目的.md",
    ]

    def _build(self):
        from doc_tool.application.content.tree import build_tree

        return build_tree(self.FILES)

    def test_grouped_by_document_type(self):
        """顶层按文档类型分组，使用中文标签。"""
        items = self._build()
        type_ids = [i.node_id for i in items if i.parent_id is None]
        self.assertEqual(type_ids, ["design", "requirement"])
        by_id = {i.node_id: i for i in items}
        self.assertEqual(by_id["design"].text, "详细设计文档")
        self.assertEqual(by_id["requirement"].text, "需求文档")

    def test_directory_hierarchy_nested(self):
        """章节目录按层级嵌套在类型节点下。"""
        items = self._build()
        dir_items = [i for i in items if not i.is_file]
        chapter = next(
            i for i in dir_items if i.node_id == "requirement/第3章 功能需求"
        )
        self.assertEqual(chapter.parent_id, "requirement")
        section = next(
            i
            for i in dir_items
            if i.node_id == "requirement/第3章 功能需求/3.1 KSHC"
        )
        self.assertEqual(section.parent_id, "requirement/第3章 功能需求")

    def test_file_leaf_under_deepest_dir(self):
        """文件叶子挂在最深目录节点下，rel_path 正确。"""
        items = self._build()
        by_id = {i.node_id: i for i in items}
        file_item = by_id["requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"]
        self.assertTrue(file_item.is_file)
        self.assertEqual(
            file_item.parent_id, "requirement/第3章 功能需求/3.1 KSHC"
        )
        self.assertEqual(
            file_item.rel_path,
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md",
        )

    def test_ancestors_root_to_parent(self):
        """ancestors 返回从根到父级的祖先链。"""
        from doc_tool.application.content.tree import ancestors

        items = self._build()
        chain = ancestors(
            "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md", items
        )
        self.assertEqual(
            chain,
            [
                "requirement",
                "requirement/第3章 功能需求",
                "requirement/第3章 功能需求/3.1 KSHC",
            ],
        )

    def test_directories_deduplicated(self):
        """同一目录下多个文件不重复建目录节点。"""
        items = self._build()
        dir_ids = [i.node_id for i in items if not i.is_file]
        self.assertEqual(len(dir_ids), len(set(dir_ids)))

    def test_natural_sort_orders_numeric_sections(self):
        """章节和文件名按数字段排序，不能把 3.7.10 排在 3.7.2 前。"""
        from doc_tool.application.content.tree import build_tree

        items = build_tree(
            [
                "requirement/第3章/3.7 KSOA/3.7.10 设备管理.md",
                "requirement/第3章/3.7 KSOA/3.7.2 产品管理.md",
                "requirement/第3章/3.7 KSOA/3.7.1 租户管理.md",
            ]
        )
        files = [item.text for item in items if item.is_file]
        self.assertEqual(
            files,
            ["3.7.1 租户管理.md", "3.7.2 产品管理.md", "3.7.10 设备管理.md"],
        )

    def test_filter_keeps_file_ancestors_and_directory_subtree(self):
        """搜索文件时保留定位路径，搜索目录时保留完整模块。"""
        from doc_tool.application.content.tree import build_tree, filter_tree_items

        items = build_tree(
            [
                "requirement/第3章/KSOA/3.7.1 租户管理.md",
                "requirement/第3章/KSOA/3.7.2 产品管理.md",
                "requirement/第3章/KSHC/3.1.1 居民信息.md",
            ]
        )
        tenant = filter_tree_items(items, "租户")
        self.assertEqual(
            [item.text for item in tenant if item.is_file], ["3.7.1 租户管理.md"]
        )
        module = filter_tree_items(items, "ksoa")
        self.assertEqual(
            [item.text for item in module if item.is_file],
            ["3.7.1 租户管理.md", "3.7.2 产品管理.md"],
        )

    def test_integration_with_index(self):
        """与 ContentIndex 集成：从真实索引推导树。"""
        from doc_tool.application.content.index import ContentIndexService

        content_root = make_project(
            {
                "requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\nx\n",
                "requirement/第1章 引言/1.2 范围.md": "# 1.2 范围\nx\n",
            }
        )
        self.addCleanup(shutil.rmtree, content_root, ignore_errors=True)
        from doc_tool.application.content.tree import build_tree

        index = ContentIndexService(content_root).build()
        items = build_tree(index.all_files())
        self.assertEqual(
            sum(1 for i in items if i.is_file), 2
        )

    def test_next_number_increments_sibling_max(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = [
            "requirement/第3章/3.7 KSOA/3.7.1 租户管理.md",
            "requirement/第3章/3.7 KSOA/3.7.2 产品管理.md",
            "requirement/第3章/3.7 KSOA/3.7.10 设备管理.md",
        ]
        result = next_chapter_rel_path("requirement/第3章/3.7 KSOA", files, "权限管理")
        self.assertEqual(
            result, "requirement/第3章/3.7 KSOA/3.7.11 权限管理.md"
        )

    def test_next_from_dir_number_when_no_numeric_siblings(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = ["requirement/第3章/3.7 KSOA/概述.md"]
        result = next_chapter_rel_path("requirement/第3章/3.7 KSOA", files, "权限管理")
        self.assertEqual(
            result, "requirement/第3章/3.7 KSOA/3.7.1 权限管理.md"
        )

    def test_next_fallback_title_when_dir_unnumbered(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = ["requirement/第3章/KSOA/概述.md"]
        result = next_chapter_rel_path("requirement/第3章/KSOA", files, "权限管理")
        self.assertEqual(result, "requirement/第3章/KSOA/权限管理.md")

    def test_next_ignores_subdirectory_files_as_siblings(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = ["requirement/第3章/3.7 KSOA/3.7.1 租户管理/3.7.1.1 详情.md"]
        result = next_chapter_rel_path("requirement/第3章/3.7 KSOA", files, "权限管理")
        self.assertEqual(
            result, "requirement/第3章/3.7 KSOA/3.7.1 权限管理.md"
        )

    def test_qt_model_parent_invariant_and_full_hierarchy(self):
        """Qt ChapterTreeModel 的 parent() 保持模型不变式，且层级完整。

        回归：此前 parent() 对「父节点为顶层类型节点」的章节错误返回根，
        违反 QAbstractItemModel 不变式（parent(index(r,c,p)) == p），
        会导致 QTreeView 展开/层级显示异常。
        """
        from doc_tool.application.content.tree import build_tree
        from doc_tool.ui.content.tree_panel import ChapterTreeModel

        items = build_tree(self.FILES)
        model = ChapterTreeModel(items)

        def same(a, b):
            if a.isValid() != b.isValid():
                return False
            if not a.isValid():
                return True
            return (
                a.row() == b.row()
                and a.column() == b.column()
                and a.internalPointer() == b.internalPointer()
            )

        mismatch = 0
        checked = 0
        stack = [model.index(0, 0).parent()]  # 根（invalid）
        while stack:
            par = stack.pop()
            for row in range(model.rowCount(par)):
                idx = model.index(row, 0, par)
                if model.hasChildren(idx):
                    stack.append(idx)
                checked += 1
                if not same(model.parent(idx), par):
                    mismatch += 1
        self.assertEqual(mismatch, 0)
        self.assertGreater(checked, 4)

        # 顶层类型节点下应能看到章节
        req_row = next(
            row
            for row in range(model.rowCount())
            if model.data(model.index(row, 0)) == "需求文档"
        )
        req_idx = model.index(req_row, 0)
        chapters = [
            model.data(model.index(r, 0, req_idx))
            for r in range(model.rowCount(req_idx))
        ]
        self.assertIn("第1章 引言", chapters)
        self.assertIn("第3章 功能需求", chapters)


class SearchServiceTests(unittest.TestCase):
    """任务 5.x：全文搜索服务。"""

    FILES = {
        "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md": (
            "# 3.1.4 居民信息\n"
            "健康档案管理功能。\n"
            "管理员可查看。\n"
            "KSHC 平台。\n"
        ),
        "requirement/第3章 功能需求/3.1 KSHC/3.1.5 健康档案.md": (
            "# 3.1.5 健康档案\n"
            "档案管理。\n"
            "kshc 小写。\n"
        ),
        "design/第1章 引言/1.1 目的.md": (
            "# 1.1 目的\n"
            "设计说明。\n"
        ),
    }

    def setUp(self) -> None:
        from doc_tool.application.content.index import ContentIndexService

        self.content_root = make_project(self.FILES)
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)
        self.index = ContentIndexService(self.content_root).build()
        from doc_tool.application.content.search import SearchService

        self.service = SearchService(self.index)

    def test_basic_keyword_search(self):
        """关键字命中并返回文件、行号、预览。"""
        from doc_tool.application.content.search import SearchOptions

        result = self.service.search(SearchOptions(query="健康档案"))
        self.assertEqual(result.total, 2)
        self.assertEqual(result.file_count, 2)
        hit = next(h for h in result.hits if "功能" in h.text)
        self.assertEqual(hit.rel_path, "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md")
        self.assertEqual(hit.line_no, 2)

    def test_no_match(self):
        """无命中返回空结果而非报错。"""
        from doc_tool.application.content.search import SearchOptions

        result = self.service.search(SearchOptions(query="不存在词"))
        self.assertEqual(result.total, 0)
        self.assertEqual(result.hits, [])

    def test_regex_search(self):
        """正则模式按模式匹配。"""
        from doc_tool.application.content.search import SearchOptions

        result = self.service.search(SearchOptions(query=r"档案\s*管理", regex=True))
        self.assertGreater(result.total, 0)

    def test_case_sensitive(self):
        """区分大小写时 KSHC 不匹配 kshc。"""
        from doc_tool.application.content.search import SearchOptions

        insensitive = self.service.search(SearchOptions(query="KSHC"))
        sensitive = self.service.search(
            SearchOptions(query="KSHC", case_sensitive=True)
        )
        self.assertGreater(insensitive.total, sensitive.total)

    def test_whole_word_excludes_compound(self):
        """整词模式不匹配复合词：'管理' 不命中 '管理员'。"""
        from doc_tool.application.content.search import SearchOptions

        plain = self.service.search(SearchOptions(query="管理"))
        whole = self.service.search(SearchOptions(query="管理", whole_word=True))
        # 整词下"管理员"中的"管理"不再命中
        self.assertLess(whole.total, plain.total)
        self.assertFalse(
            any(h.text.startswith("管理员") for h in whole.hits)
        )

    def test_document_type_filter(self):
        """按文档类型范围过滤。"""
        from doc_tool.application.content.search import SearchOptions

        result = self.service.search(
            SearchOptions(query="管理", document_types=["design"])
        )
        self.assertEqual(result.total, 0)
        result = self.service.search(
            SearchOptions(query="管理", document_types=["requirement"])
        )
        self.assertGreater(result.total, 0)
        self.assertTrue(
            all(
                h.rel_path.startswith("requirement/") for h in result.hits
            )
        )

    def test_limit_truncation(self):
        """超过上限截断并标记 truncated。"""
        from doc_tool.application.content.search import SearchOptions

        result = self.service.search(
            SearchOptions(query="管理", limit=1)
        )
        self.assertEqual(len(result.hits), 1)
        self.assertTrue(result.truncated)
        self.assertGreater(result.total, 1)

    def test_invalid_regex_raises(self):
        """非法正则抛出 SearchQueryError。"""
        from doc_tool.application.content.search import (
            SearchOptions,
            SearchQueryError,
        )

        with self.assertRaises(SearchQueryError):
            self.service.search(SearchOptions(query="[", regex=True))


class PreviewRendererTests(unittest.TestCase):
    """任务 6.x：md 结构渲染（编辑器侧边预览）。"""

    def test_headings_parsed_with_levels(self):
        """标题按级别解析。"""
        from doc_tool.application.content.preview import render_preview_blocks

        blocks = render_preview_blocks("# 标题一\n## 标题二\n#### 标题四\n")
        headings = [b for b in blocks if b.kind == "heading"]
        self.assertEqual([h.level for h in headings], [1, 2, 4])
        self.assertEqual([h.text for h in headings], ["标题一", "标题二", "标题四"])

    def test_table_rows_with_separator_dropped(self):
        """管道表格解析，表头分隔行被剔除。"""
        from doc_tool.application.content.preview import render_preview_blocks

        md = (
            "| 名称 | 说明 |\n"
            "| --- | --- |\n"
            "| A | 第一 |\n"
            "| B | 第二 |\n"
        )
        blocks = render_preview_blocks(md)
        tables = [b for b in blocks if b.kind == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].rows[0], ["名称", "说明"])
        self.assertEqual(tables[0].rows[2], ["B", "第二"])
        self.assertEqual(len(tables[0].rows), 3)

    def test_image_with_size(self):
        """图片解析路径与尺寸。"""
        from doc_tool.application.content.preview import render_preview_blocks

        blocks = render_preview_blocks(
            "![业务图](images/img_0001.png =642x269)\n"
        )
        images = [b for b in blocks if b.kind == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].image_path, "images/img_0001.png")
        self.assertEqual(images[0].image_size, "642x269")

    def test_comments_and_empty_par_skipped(self):
        """表格指令注释与 EMPTY_PAR 不产生块。"""
        from doc_tool.application.content.preview import render_preview_blocks

        md = (
            "<!-- TBL:style=43 type=auto -->\n"
            "| A | B |\n"
            "<EMPTY_PAR/>\n"
            "正文\n"
        )
        blocks = render_preview_blocks(md)
        kinds = [b.kind for b in blocks]
        self.assertNotIn("blank", kinds)
        self.assertIn("table", kinds)
        self.assertIn("paragraph", kinds)

    def test_preview_summary_counts(self):
        """结构摘要统计标题/段落/表格/图片数量。"""
        from doc_tool.application.content.preview import preview_summary

        summary = preview_summary(
            "# 标题\n正文\n| A |\n![x](y.png =1x1)\n"
        )
        self.assertIn("标题 1", summary)
        self.assertIn("段落 1", summary)
        self.assertIn("表格 1", summary)
        self.assertIn("图片 1", summary)

    def test_normalize_preview_converts_custom_image_size(self):
        """Qt 预览应能读取构建链路使用的图片尺寸扩展语法。"""
        from doc_tool.application.content.preview import normalize_markdown_for_preview

        rendered = normalize_markdown_for_preview(
            "![业务图](images/img_0001.png =642x269)\n<EMPTY_PAR/>\n正文\n"
        )
        self.assertEqual(rendered, "![业务图](images/img_0001.png)\n正文")

    def test_html_preview_renders_markdown_constructs(self):
        """HTML 预览保留项目常用 Markdown 格式，并转义原始 HTML。"""
        from doc_tool.application.content.preview import render_markdown_html

        rendered = render_markdown_html(
            "# 标题\n\n**加粗** 和 *斜体*\n\n- 条目\n\n"
            "| 名称 | 说明 |\n| --- | --- |\n| A | `代码` |\n"
            "\n![图](images/a.png =1x1)\n\n<script>alert(1)</script>\n"
        )
        self.assertIn("<h1>标题</h1>", rendered)
        self.assertIn("<b>加粗</b>", rendered)
        self.assertIn("<i>斜体</i>", rendered)
        self.assertIn("<ul><li>条目</li></ul>", rendered)
        self.assertIn("<table", rendered)
        self.assertIn('<img src="images/a.png" alt="图"/>', rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)


class ReplaceServiceTests(unittest.TestCase):
    """任务 7.x：全局替换服务。"""

    FILES = {
        "requirement/第1章 引言/1.1 目的.md": (
            "# 1.1 目的\n"
            "本系统用于健康档案管理。\n"
            "管理员与档案管理功能。\n"
        ),
        "requirement/第1章 引言/1.2 范围.md": (
            "# 1.2 范围\n"
            "覆盖档案管理范围。\n"
        ),
    }

    def setUp(self) -> None:
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.replace import ReplaceService

        self.content_root = make_project(self.FILES)
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)
        from doc_tool.application.content.writer import ContentWriter

        self.index = ContentIndexService(self.content_root).build()
        self.writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        self.service = ReplaceService(self.index)

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_find_matches_with_positions(self):
        """命中带列位置。"""
        matches = self.service.find_matches("档案管理")
        self.assertGreater(len(matches), 0)
        first = next(m for m in matches if m.rel_path.endswith("1.1 目的.md"))
        self.assertIn("档案管理", first.line_text[first.start : first.end])

    def test_build_preview_counts(self):
        """全部替换前的汇总统计文件与命中数。"""
        preview = self.service.build_preview("档案管理")
        self.assertEqual(preview.total, 3)
        self.assertEqual(preview.file_count, 2)

    def test_apply_matches_writes_files(self):
        """按命中写回文件，保留其余内容。"""
        matches = self.service.find_matches("档案管理")
        results = self.service.apply_matches(matches, "档案", self.writer)
        self.assertTrue(all(r.written for r in results))
        text = self._read("requirement/第1章 引言/1.1 目的.md")
        self.assertNotIn("档案管理", text)
        self.assertIn("档案", text)
        # 每文件保留 .bak
        self.assertTrue(
            (self.content_root / "requirement/第1章 引言/1.1 目的.md.bak").exists()
        )
        # 改动清单有记录
        self.writer.manifest.load()
        self.assertGreater(len(self.writer.manifest.entries), 0)

    def test_apply_single_match(self):
        """逐项模式只替换一条命中。"""
        rel = "requirement/第1章 引言/1.1 目的.md"
        matches = [m for m in self.service.find_matches("档案管理") if m.rel_path == rel]
        self.service.apply_matches(matches[:1], "档案", self.writer)
        text = self._read(rel)
        # 只替换了一处，另一处"档案管理"仍在
        self.assertEqual(text.count("档案管理"), 1)

    def test_multiple_matches_on_same_line(self):
        """同一行多处命中全部替换。"""
        self.content_root.joinpath("requirement/第1章 引言/1.2 范围.md").write_text(
            "x 管理 管理 y\n", encoding="utf-8"
        )
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.replace import ReplaceService

        self.index = ContentIndexService(self.content_root).build()
        self.service = ReplaceService(self.index)
        rel = "requirement/第1章 引言/1.2 范围.md"
        matches = [
            m for m in self.service.find_matches("管理") if m.rel_path == rel
        ]
        self.assertEqual(len(matches), 2)
        self.service.apply_matches(matches, "M", self.writer)
        self.assertEqual(self._read(rel), "x M M y\n")

    def test_rollback_restores_replace(self):
        """回滚恢复替换前内容。"""
        matches = self.service.find_matches("档案管理")
        self.service.apply_matches(matches, "档案", self.writer)
        self.writer.rollback()
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 目的.md"),
            self.FILES["requirement/第1章 引言/1.1 目的.md"],
        )


class RefactorServiceTests(unittest.TestCase):
    """任务 8.x：章节重命名/重编号联动。"""

    FILES = {
        "requirement/第3章 功能需求/3.1 KSHC/3.1.3 团队管理.md": (
            "# 3.1.3 团队管理\n"
            "详见 3.1.4 居民信息。\n"
            "链接 [居民信息](3.1.4 居民信息.md)。\n"
        ),
        "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md": (
            "# 3.1.4 居民信息\n"
            "居民档案内容。\n"
        ),
    }

    def setUp(self) -> None:
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner
        from doc_tool.application.content.refactor import RefactorService
        from doc_tool.application.content.writer import ContentWriter

        self.content_root = make_project(self.FILES)
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)
        self.index = ContentIndexService(self.content_root).build()
        ReferenceScanner(self.index).scan_all()
        self.writer = ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )
        self.service = RefactorService(self.index)

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    OLD = "requirement/第3章 功能需求/3.1 KSHC/3.1.4 居民信息.md"

    def test_plan_detects_section_link_and_title(self):
        """重编号时检出章节引用、链接与自身标题。"""
        plan = self.service.compute_rename_plan(self.OLD, "3.1.5 居民信息.md")
        self.assertIsNotNone(plan)
        old_substrs = sorted({e.old_substr for e in plan.edits})
        # 章节号、链接文件名、标题编号
        self.assertIn("3.1.4", old_substrs)
        self.assertIn("3.1.4 居民信息.md", old_substrs)
        self.assertEqual(plan.old_rel_path, self.OLD)

    def test_apply_renumber_updates_refs_and_renames(self):
        """执行后引用更新、标题更新、文件重命名。"""
        plan = self.service.compute_rename_plan(self.OLD, "3.1.5 居民信息.md")
        self.service.apply_rename_plan(plan, self.writer)

        new_rel = "requirement/第3章 功能需求/3.1 KSHC/3.1.5 居民信息.md"
        self.assertTrue((self.content_root / new_rel).exists())
        self.assertFalse((self.content_root / self.OLD).exists())

        ref_file = self._read("requirement/第3章 功能需求/3.1 KSHC/3.1.3 团队管理.md")
        self.assertIn("详见 3.1.5 居民信息。", ref_file)
        self.assertIn("[居民信息](3.1.5 居民信息.md)", ref_file)

        new_content = self._read(new_rel)
        self.assertIn("# 3.1.5 居民信息", new_content)

    def test_pure_rename_keeps_number(self):
        """同编号改名（重编号=False）只更新链接文件名。"""
        plan = self.service.compute_rename_plan(
            self.OLD, "3.1.4 居民信息v2.md"
        )
        self.assertIsNotNone(plan)
        # 编号未变：无章节号/标题编辑，仅链接文件名
        self.assertFalse(
            any(e.old_substr == "3.1.4" for e in plan.edits)
        )
        self.assertTrue(
            any(e.old_substr == "3.1.4 居民信息.md" for e in plan.edits)
        )

    def test_rollback_restores_rename_and_refs(self):
        """回滚恢复引用文本与文件名。"""
        plan = self.service.compute_rename_plan(self.OLD, "3.1.5 居民信息.md")
        self.service.apply_rename_plan(plan, self.writer)
        self.writer.rollback()

        self.assertTrue((self.content_root / self.OLD).exists())
        self.assertEqual(
            self._read("requirement/第3章 功能需求/3.1 KSHC/3.1.3 团队管理.md"),
            self.FILES["requirement/第3章 功能需求/3.1 KSHC/3.1.3 团队管理.md"],
        )

    def test_unknown_target_returns_none(self):
        """目标不在索引中返回 None。"""
        plan = self.service.compute_rename_plan(
            "requirement/不存在.md", "x.md"
        )
        self.assertIsNone(plan)


class LintTests(unittest.TestCase):
    """任务 9.x：术语/一致性检查。"""

    FILES = {
        "requirement/第1章 引言/1.1 目的.md": (
            "# 1.1 目的\n"
            "KSHC 平台，kshc 小写出现。\n"
            "TODO 待办残留。\n"
        ),
        "design/第1章 引言/1.1 目的.md": (
            "# 1.1 目的\n"
            "详细设计。\n"
        ),
        "requirement/第1章 引言/1.2 范围.md": (
            "# 1.2 范围\n"
            "## 子标题\n"
        ),
    }

    def setUp(self) -> None:
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.lint import ContentLinter, TermStore

        self.content_root = make_project(self.FILES)
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)
        self.index = ContentIndexService(self.content_root).build()
        self.linter = ContentLinter(self.index)
        self.store = TermStore(self.project_root / ".state")

    def test_duplicate_title_detected(self):
        """跨文件重复标题被标记。"""
        issues = self.linter.check_duplicate_titles()
        dupes = [i for i in issues if i.rule == "duplicate_title"]
        self.assertGreater(len(dupes), 0)
        self.assertTrue(
            any("1.1 目的" in i.message for i in dupes)
        )

    def test_todo_residual_detected(self):
        """TODO 残留被标记。"""
        issues = self.linter.check_todo()
        todos = [i for i in issues if i.rule == "todo_residual"]
        self.assertEqual(len(todos), 1)
        self.assertIn("TODO", todos[0].message)

    def test_term_case_detected(self):
        """术语大小写不一致被标记，规范拼写不标记。"""
        issues = self.linter.check_terms(["KSHC"])
        term_issues = [i for i in issues if i.rule == "term_case"]
        # 只有 kshc（小写）被标记，KSHC 规范出现不标记
        self.assertEqual(len(term_issues), 1)
        self.assertIn("kshc", term_issues[0].message)

    def test_check_all_sorted(self):
        """check_all 汇总并排序。"""
        issues = self.linter.check_all(["KSHC"])
        self.assertEqual(
            issues, sorted(issues, key=lambda i: (i.rel_path, i.line_no))
        )

    def test_term_store_roundtrip(self):
        """术语清单保存/读取往返一致。"""
        self.store.save(["KSHC", "KSHC", "", "API"])
        self.assertEqual(self.store.load(), ["KSHC", "API"])

    def test_term_store_missing_returns_empty(self):
        """无清单文件时返回空列表。"""
        self.assertEqual(self.store.load(), [])


class ChangeManifestSerializationTests(unittest.TestCase):
    """改动清单条目 JSON 往返（新增 trash_path 字段必须持久化）。"""

    def test_entry_roundtrip_preserves_trash_path(self):
        from doc_tool.application.content.writer import ChangeEntry, OP_DELETE

        entry = ChangeEntry(
            operation=OP_DELETE,
            rel_path="requirement/第1章/1.1 目的.md",
            trash_path="C:/proj/.state/trash/requirement/第1章/1.1 目的.md",
        )
        restored = ChangeEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.operation, OP_DELETE)
        self.assertEqual(
            restored.trash_path,
            "C:/proj/.state/trash/requirement/第1章/1.1 目的.md",
        )


class ManifestStatusMapTests(unittest.TestCase):
    """徽标状态推导：优先级与 rename/create+edit 映射。"""

    def test_status_precedence_and_mapping(self):
        from doc_tool.application.content.writer import (
            ChangeEntry,
            OP_CREATE,
            OP_DELETE,
            OP_EDIT,
            OP_RENAME,
            manifest_status_map,
        )

        entries = [
            ChangeEntry(operation=OP_EDIT, rel_path="a.md", backup_path="x"),
            ChangeEntry(operation=OP_CREATE, rel_path="b.md"),
            ChangeEntry(operation=OP_DELETE, rel_path="c.md", trash_path="t/c.md"),
            ChangeEntry(operation=OP_RENAME, rel_path="d.md", original_path="e.md"),
            # 先 create 后 edit 同一文件 → 仍为 added
            ChangeEntry(operation=OP_CREATE, rel_path="f.md"),
            ChangeEntry(operation=OP_EDIT, rel_path="f.md", backup_path="y"),
            # 先 edit 后 delete 同一文件 → 覆盖为 deleted
            ChangeEntry(operation=OP_EDIT, rel_path="g.md", backup_path="z"),
            ChangeEntry(operation=OP_DELETE, rel_path="g.md", trash_path="t/g.md"),
        ]
        status = manifest_status_map(entries)
        self.assertEqual(status["a.md"], "modified")
        self.assertEqual(status["b.md"], "added")
        self.assertEqual(status["c.md"], "deleted")
        self.assertEqual(status["d.md"], "modified")
        self.assertNotIn("e.md", status)  # rename 旧路径不标（文件已不存在）
        self.assertEqual(status["f.md"], "added")
        self.assertEqual(status["g.md"], "deleted")


class CreateDeleteTests(unittest.TestCase):
    """任务：新增/删除章节文件 + 回滚恢复。"""

    def setUp(self) -> None:
        self.content_root = make_project(
            {"requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\n原始正文\n"}
        )
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)

    def _writer(self):
        from doc_tool.application.content.writer import ContentWriter

        return ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_create_file_writes_and_records(self):
        writer = self._writer()
        result = writer.create_file(
            "requirement/第1章 引言/1.1 新增.md", "# 1.1 新增\n"
        )
        self.assertTrue(result.written)
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 新增.md"), "# 1.1 新增\n"
        )
        writer.manifest.load()
        entry = writer.manifest.entries[-1]
        self.assertEqual(entry.operation, "create")
        self.assertEqual(entry.rel_path, "requirement/第1章 引言/1.1 新增.md")

    def test_create_existing_rejected(self):
        writer = self._writer()
        result = writer.create_file("requirement/第1章 引言/1.1 目的.md", "x")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_create_escape_path_rejected(self):
        writer = self._writer()
        result = writer.create_file("../../evil.md", "x")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_delete_moves_to_trash_and_records(self):
        from pathlib import Path

        writer = self._writer()
        result = writer.delete_file("requirement/第1章 引言/1.1 目的.md")
        self.assertTrue(result.written)
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 目的.md").exists()
        )
        writer.manifest.load()
        entry = writer.manifest.entries[-1]
        self.assertEqual(entry.operation, "delete")
        self.assertIsNotNone(entry.trash_path)
        self.assertTrue(Path(entry.trash_path).exists())
        self.assertTrue(
            Path(entry.trash_path).as_posix().endswith(
                ".state/trash/requirement/第1章 引言/1.1 目的.md"
            )
        )

    def test_delete_missing_rejected(self):
        writer = self._writer()
        result = writer.delete_file("requirement/第1章 引言/不存在.md")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_rollback_removes_created_file(self):
        writer = self._writer()
        writer.create_file(
            "requirement/第1章 引言/1.1 新增.md", "# 1.1 新增\n"
        )
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 新增.md").exists()
        )
        writer.manifest.load()
        self.assertTrue(writer.manifest.empty)

    def test_rollback_restores_deleted_file(self):
        writer = self._writer()
        writer.delete_file("requirement/第1章 引言/1.1 目的.md")
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 目的.md"),
            "# 1.1 目的\n原始正文\n",
        )
        writer.manifest.load()
        self.assertTrue(writer.manifest.empty)

    def test_rollback_after_create_then_delete(self):
        """新建→删除同一文件后回滚：文件被恢复为最初不存在状态。"""
        writer = self._writer()
        writer.create_file(
            "requirement/第1章 引言/1.1 新增.md", "# 1.1 新增\n"
        )
        writer.delete_file("requirement/第1章 引言/1.1 新增.md")
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 新增.md").exists()
        )


if __name__ == "__main__":
    unittest.main()
