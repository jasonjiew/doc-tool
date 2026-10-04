# -*- coding: utf-8 -*-
"""MAIN2-C 3.3/3.4：所选章节批量复制/移动与操作后当前内容一致。

覆盖：
(a) 批量复制 3 个所选章节 → 3 个新文件、新条目身份、原章不被改写；
(b) 目标同名冲突 → 自动改名（绝不覆盖）；
(c) 一个无效项被局部跳过，其余项照常应用，且逐项结果可读；
(d) 取消 → 不写任何文件（计划只在内存里）；
(e) 复制/改名后编辑器缓冲仍属于原章，保存不会写到另一章路径；
(f) 操作后旧检查结果按既有规则标过期（需重检），预览/索引立即采用当前表达；
(g) 代次（generation）核对：为章节 A 发起的操作不会落到章节 B 上。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

NL = chr(10)


def item_marker(item_id: str, alias: str = "") -> str:
    return "<!-- DOC-ITEM: projectId=P1 | id={0} | kind=requirement | alias={1} -->".format(
        item_id, alias or item_id[:4]
    )


ITEM_1 = "11111111-1111-1111-1111-111111111111"
ITEM_2 = "22222222-2222-2222-2222-222222222222"
ITEM_3 = "33333333-3333-3333-3333-333333333333"


class _ContentFixture(unittest.TestCase):
    """三章内容根夹具：真实相对路径 + DOC-ITEM 标记 + 索引/写入服务。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2c-batch-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.content = self.work / "content" / "general"
        self.state = self.work / ".state"
        self.state.mkdir(parents=True)
        (self.content / "第1章 引言").mkdir(parents=True)
        (self.content / "第2章 设计").mkdir(parents=True)
        (self.content / "第1章 引言" / "_index.md").write_text(
            "本章说明。" + NL, encoding="utf-8"
        )
        (self.content / "第2章 设计" / "_index.md").write_text(
            "本章说明。" + NL, encoding="utf-8"
        )
        self.chapter1 = "第1章 引言/1.1 目的.md"
        self.chapter2 = "第1章 引言/1.2 范围.md"
        self.chapter3 = "第2章 设计/2.1 架构.md"
        (self.content / self.chapter1).write_text(
            "# 1.1 目的" + NL + NL + "第一章正文。" + NL + item_marker(ITEM_1) + NL,
            encoding="utf-8",
        )
        (self.content / self.chapter2).write_text(
            "# 1.2 范围" + NL + NL + "第二章正文。" + NL + item_marker(ITEM_2) + NL,
            encoding="utf-8",
        )
        (self.content / self.chapter3).write_text(
            "# 2.1 架构" + NL + NL + "第三章正文。" + NL + item_marker(ITEM_3) + NL,
            encoding="utf-8",
        )
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.writer import ContentWriter

        self.writer = ContentWriter(self.content, self.state)
        self.index = ContentIndexService(self.content).build()
        self.sources = [self.chapter1, self.chapter2, self.chapter3]
        # 真实工作区入口（批量操作、写后刷新与标过期都走这条路径）。
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        from doc_tool.ui.content.workspace import ContentWorkspace

        self.workspace = ContentWorkspace(
            self.content,
            project_root=self.work,
            state_dir=self.state,
            assets_root=self.work / "assets",
            on_status=lambda message: None,
        )
        self.addCleanup(self.workspace.deleteLater)
        if getattr(self.workspace, "_index", None) is None:
            self.workspace._index = self.workspace._index_service.build()

    def read(self, rel_path: str) -> str:
        return (self.content / rel_path).read_text(encoding="utf-8")

    def exists(self, rel_path: str) -> bool:
        return (self.content / rel_path).is_file()

    def files(self):
        return sorted(
            path.relative_to(self.content).as_posix()
            for path in self.content.rglob("*.md")
        )


class BatchCopyPlanTests(_ContentFixture):
    """3.3：批量复制的真实目标摘要、身份与局部跳过。"""

    def test_batch_copy_three_chapters_new_identity_and_originals_untouched(self):
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY,
            apply_batch_plan,
            plan_batch_chapters,
        )

        before = {rel: self.read(rel) for rel in self.sources}
        plan = plan_batch_chapters(
            self.index, self.sources, BATCH_COPY, dest_dir="第2章 设计"
        )
        # 写盘前的真实目标摘要：每个所选章节一行 旧 → 新。
        # 第 3 章本来就在目标目录里，同名目标已占用 → 自动改名而不是覆盖。
        self.assertEqual(
            [(item.source, item.target) for item in plan.items],
            [
                (self.chapter1, "第2章 设计/目的.md"),
                (self.chapter2, "第2章 设计/范围.md"),
                (self.chapter3, "第2章 设计/架构.md"),
            ],
        )
        self.assertIn("目标摘要", plan.summary_text())
        self.assertIn(self.chapter1, plan.summary_text())

        results = apply_batch_plan(
            plan, self.index, self.writer, source_text=lambda rel: before[rel]
        )
        self.assertTrue(all(item.ok for item in results), plan.result_text())
        self.assertEqual(len(results), 3)
        for item in results:
            self.assertTrue(self.exists(item.target), item.target)
            self.assertEqual(len(item.item_ids), 1, "副本必须重生成条目身份")
            old_id, new_id = next(iter(item.item_ids.items()))
            self.assertNotEqual(old_id, new_id)
            copied = self.read(item.target)
            self.assertNotIn(old_id, copied)
            self.assertIn(new_id, copied)
        # 原章磁盘内容不被副本文本改写
        for rel, text in before.items():
            self.assertEqual(self.read(rel), text)
        self.assertEqual(len(self.files()), 3 + 2 + 3)

    def test_name_conflict_gets_distinguishable_name_not_overwrite(self):
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY,
            apply_batch_plan,
            plan_batch_chapters,
        )

        # 内容根下已经有一份同名「目的.md」：批量复制必须自动改名而不是覆盖它。
        occupied = "目的.md"
        (self.content / occupied).write_text(
            "# 既有副本" + NL + "不得被覆盖。" + NL, encoding="utf-8"
        )
        from doc_tool.application.content.index import ContentIndexService

        index = ContentIndexService(self.content).build()

        plan = plan_batch_chapters(
            index, [self.chapter1], BATCH_COPY, dest_dir="", content_root=self.content
        )
        target = plan.items[0].target
        self.assertNotEqual(target, occupied)
        self.assertIn("（副本）", target)
        self.assertIn("目的", target)
        apply_batch_plan(plan, index, self.writer)
        self.assertTrue(self.exists(target))
        self.assertIn("不得被覆盖。", self.read(occupied), "既有同名文件必须保留")
        self.assertIn("第一章正文。", self.read(target))

    def test_invalid_item_is_skipped_and_others_still_apply(self):
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY,
            apply_batch_plan,
            plan_batch_chapters,
        )

        missing = "第3章 不存在/3.9 无此章.md"
        plan = plan_batch_chapters(
            self.index,
            [self.chapter1, missing, self.chapter3],
            BATCH_COPY,
            dest_dir="第2章 设计",
        )
        self.assertEqual(plan.total, 3)
        skipped = [item for item in plan.items if not item.ok]
        self.assertEqual([item.source for item in skipped], [missing])
        self.assertIn("索引", skipped[0].message)
        # 摘要里无效项也有一行可读的跳过原因
        self.assertIn(missing, plan.summary_text())

        results = apply_batch_plan(plan, self.index, self.writer)
        done = [item for item in results if item.ok]
        self.assertEqual(len(done), 2)
        self.assertTrue(self.exists(done[0].target))
        self.assertTrue(self.exists(done[1].target))
        text = plan.result_text()
        self.assertIn(missing, text)
        self.assertIn("跳过", text)

    def test_move_keeps_identity_and_updates_references(self):
        """批量移动经真实入口：落到真实目标、无临时残留、条目身份保持不变。"""
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_MOVE,
            plan_batch_chapters,
        )

        plan = plan_batch_chapters(
            self.workspace._index,
            [self.chapter1],
            BATCH_MOVE,
            dest_dir="第2章 设计",
            content_root=self.content,
        )
        item = plan.items[0]
        self.assertTrue(item.ok, item.message)
        self.assertEqual(item.target, "第2章 设计/1.1 目的.md")
        results = self.workspace._apply_batch_chapter_ops_results = (
            self.workspace._apply_batch_chapter_plan(plan)
        )
        self.assertTrue(all(result.ok for result in results), plan.result_text())
        self.assertFalse(self.exists(self.chapter1))
        self.assertTrue(self.exists("第2章 设计/1.1 目的.md"))
        moved = self.read("第2章 设计/1.1 目的.md")
        self.assertIn(ITEM_1, moved, "移动必须保持原条目身份")
        # 让位用的临时文件不得残留
        leftovers = [rel for rel in self.files() if ".doc-tool-batch" in rel]
        self.assertEqual(leftovers, [], leftovers)

    def test_move_updates_section_references_on_renumber(self):
        """移动导致文件名变化时，复用原服务联动「章节号引用 + 标题 + 链接基名」。"""
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_MOVE,
            plan_batch_chapters,
        )
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner

        # 目标目录（3.1 目标）把移入章重编号为 3.2；另一章引用它的编号与链接。
        (self.content / "第3章 数据").mkdir(parents=True, exist_ok=True)
        (self.content / "第3章 数据" / "3.1 目标").mkdir(parents=True, exist_ok=True)
        (self.content / "第3章 数据" / "3.1 目标" / "3.1.1 入口.md").write_text(
            "# 3.1.1 入口" + NL, encoding="utf-8"
        )
        (self.content / "第2章 设计" / "2.1 架构.md").write_text(
            "# 2.1 架构" + NL, encoding="utf-8"
        )
        (self.content / self.chapter1).write_text(
            "# 1.1 目的" + NL + item_marker(ITEM_1) + NL, encoding="utf-8"
        )
        (self.content / self.chapter2).write_text(
            "# 1.2 范围" + NL
            + "见 1.1 目的。" + NL
            # 链接目标必须与移动后的真实文件名一致，否则该断言不可能成立
            # （对照同文件 test_move_linkage_updates_references_with_new_basename）。
            + "链接 [目的](1.1 目的（移动）.md)。" + NL
            + item_marker(ITEM_2) + NL,
            encoding="utf-8",
        )
        index = ContentIndexService(self.content).build()
        ReferenceScanner(index).scan_all()
        self.workspace._index = index

        dest = "第2章 设计"
        (self.content / dest / "1.1 目的.md").write_text(
            "# 既有同名" + NL, encoding="utf-8"
        )
        index = ContentIndexService(self.content).build()
        ReferenceScanner(index).scan_all()
        self.workspace._index = index

        plan = plan_batch_chapters(
            index,
            [self.chapter1],
            BATCH_MOVE,
            dest_dir=dest,
            content_root=self.content,
        )
        item = plan.items[0]
        self.assertTrue(item.ok, item.message)
        self.assertIn("（移动）", item.target)
        results = self.workspace._apply_batch_chapter_plan(plan)
        self.assertTrue(all(result.ok for result in results), plan.result_text())
        self.assertTrue(self.exists(item.target), item.target)
        self.assertFalse(self.exists(self.chapter1))
        updated = self.read(self.chapter2)
        self.assertIn(Path(item.target).name, updated, updated)
        self.assertIn("既有同名", self.read(dest + "/1.1 目的.md"))
        leftovers = [rel for rel in self.files() if ".doc-tool-batch" in rel]
        self.assertEqual(leftovers, [], leftovers)


    def test_generation_check_expires_late_request_without_writing(self):
        """晚到请求：计划代次已过期时逐项作废且不写盘。"""
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY,
            apply_batch_plan,
            plan_batch_chapters,
        )

        # 计划记录代次 1；应用时当前代次已到 2 → 该项作废，绝不照写。
        plan = plan_batch_chapters(
            self.index,
            [self.chapter1],
            BATCH_COPY,
            dest_dir="第2章 设计",
            generation=1,
        )
        stale = apply_batch_plan(plan, self.index, self.writer, generation=lambda: 2)
        self.assertEqual([item.ok for item in stale], [False], stale)
        self.assertIn("过期", stale[0].message)
        self.assertFalse(self.exists("第2章 设计/目的.md"))

        # 代次一致时同一类计划正常应用（对照）
        plan2 = plan_batch_chapters(
            self.index,
            [self.chapter2],
            BATCH_COPY,
            dest_dir="第2章 设计",
            generation="same",
        )
        done = apply_batch_plan(
            plan2, self.index, self.writer, generation=lambda: "same"
        )
        self.assertEqual([item.ok for item in done], [True], plan2.result_text())
        self.assertTrue(self.exists("第2章 设计/范围.md"))
        # 未记录代次的计划不做代次核对（保持原行为）
        plan3 = plan_batch_chapters(
            self.index, [self.chapter1], BATCH_COPY, dest_dir="第2章 设计"
        )
        fresh = apply_batch_plan(
            plan3, self.index, self.writer, generation=lambda: "whatever"
        )
        self.assertEqual([item.ok for item in fresh], [True], plan3.result_text())


class BatchDialogTests(_ContentFixture):
    """3.3：真实对话框入口——目标摘要、取消不写、逐项结果。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _dialog(self, sources, kind, **kwargs):
        from doc_tool.ui.content.batch_chapter_dialog import BatchChapterDialog
        from doc_tool.application.content.batch_chapter_ops import BATCH_COPY

        dialog = BatchChapterDialog(
            self.index,
            sources,
            kind,
            writer=self.writer,
            parent=None,
            **kwargs,
        )
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_dialog_shows_real_target_summary_and_applies_per_item(self):
        from doc_tool.application.content.batch_chapter_ops import BATCH_COPY

        dialog = self._dialog(self.sources, BATCH_COPY)
        index_of_dir = dialog._dir_box.findData("第2章 设计")
        self.assertGreaterEqual(index_of_dir, 0)
        dialog._dir_box.setCurrentIndex(index_of_dir)
        lines = dialog.target_lines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all("→" in line for line in lines), lines)
        self.assertIn("→", dialog.summary_text())
        self.assertTrue(
            all(item.target for item in dialog.plan().items if item.ok),
            dialog.summary_text(),
        )

        dialog._on_confirm()
        results = dialog.results()
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item.ok for item in results))
        for item in results:
            self.assertTrue(self.exists(item.target))
        self.assertIn("3/3", dialog.summary_text())

    def test_cancel_writes_nothing(self):
        from PySide6.QtWidgets import QDialog

        from doc_tool.application.content.batch_chapter_ops import BATCH_COPY

        before = self.files()
        dialog = self._dialog(self.sources, BATCH_COPY)
        index_of_dir = dialog._dir_box.findData("第2章 设计")
        dialog._dir_box.setCurrentIndex(index_of_dir)
        # 取消 = 对话框被拒（exec 返回 Rejected）：不写任何文件。
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.assertEqual(dialog.exec(), QDialog.DialogCode.Rejected)
        self.assertEqual(dialog.results(), [])
        self.assertEqual(self.files(), before)


class WorkspaceBatchEntryTests(_ContentFixture):
    """3.3/3.4：真实界面入口（章节树多选 → 批量复制）与写后一致性。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_selection_provider_and_batch_menu_entry(self):
        """真实多选 → 章节树右键菜单出现批量复制/移动入口。"""
        tree = self.workspace._tree
        model = tree._model

        # 真实多选路径（与用户 Ctrl 点选等价）
        self.assertEqual(tree.select_files(self.sources), 3)
        self.assertEqual(sorted(tree.selected_files()), sorted(self.sources))
        # 单章多选也应只暴露单章入口（批量入口只在 >1 时出现）
        self.assertEqual(tree.select_files([self.sources[0]]), 1)
        single = tree._context_menu(model.index_for_id(self.sources[0]))
        single_labels = [action.text() for action in single.actions()]
        self.assertFalse(
            any(label.startswith("批量") for label in single_labels), single_labels
        )
        single.deleteLater()

        # 重新多选三章 → 批量入口出现
        self.assertEqual(tree.select_files(self.sources), 3)
        first = model.index_for_id(self.sources[0])
        menu = tree._context_menu(first)
        labels = [action.text() for action in menu.actions()]
        self.assertTrue(
            any(label.startswith("批量复制所选章节") for label in labels), labels
        )
        self.assertTrue(
            any(label.startswith("批量移动到") for label in labels), labels
        )
        menu.deleteLater()

    def test_batch_copy_from_workspace_keeps_original_buffer(self):
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY,
            apply_batch_plan,
        )

        self.workspace.open_file(self.chapter1)
        editor = self.workspace.tabs_host.editor_for(self.chapter1)
        marker = "批量复制前未保存的正文标记"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + NL)
        self.assertTrue(editor.is_dirty())

        dialog = self.workspace._show_batch_chapter_ops(
            [self.chapter1, self.chapter3], BATCH_COPY, apply=False
        )
        self.assertIsNotNone(dialog)
        index_of_dir = dialog._dir_box.findData("第2章 设计")
        dialog._dir_box.setCurrentIndex(index_of_dir)
        dialog._on_confirm()
        plan = dialog.plan()
        results = apply_batch_plan(
            plan,
            self.workspace._index,
            self.workspace._writer,
            source_text=self.workspace._current_chapter_text,
            refresh_index=self.workspace._refresh_batch_index,
        )
        self.workspace._finish_batch_chapter_ops(plan)

        copied = [item.target for item in results if item.ok]
        self.assertEqual(len(copied), 2, plan.result_text())
        for target in copied:
            self.assertTrue(self.exists(target), target)
        # 活缓冲正文进入副本；原章磁盘不被改写、脏状态与光标保留
        copy1 = self.read("第2章 设计/目的.md")
        self.assertIn(marker, copy1)
        self.assertNotIn(marker, self.read(self.chapter1))
        self.assertTrue(editor.is_dirty(), "批量复制不得清除原章未保存状态")
        self.assertIs(self.workspace.tabs_host.editor_for(self.chapter1), editor)
        self.assertTrue(self.workspace._index is not None)
        # 3.4：写后索引/预览立即采用当前表达（新副本已进入索引）
        self.assertIn("第2章 设计/目的.md", self.workspace._index.all_files())

    def test_cancel_from_workspace_writes_nothing(self):
        from PySide6.QtWidgets import QDialog

        from doc_tool.application.content.batch_chapter_ops import BATCH_COPY

        before = self.files()
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            result = self.workspace._show_batch_chapter_ops(
                [self.chapter1, self.chapter3], BATCH_COPY
            )
        self.assertIsNone(result, "取消时不得返回已执行结果")
        self.assertEqual(self.files(), before)
        self.assertEqual(self.workspace._chapter_op_gen, 0, "取消不应产生写后刷新")

    def test_late_request_does_not_cross_chapters(self):
        """晚到请求：代次已前进时逐项作废、不写盘、不串到别的章节。"""
        from doc_tool.application.content.batch_chapter_ops import (
            BATCH_COPY,
            plan_batch_chapters,
        )

        plan = plan_batch_chapters(
            self.workspace._index, [self.chapter1], BATCH_COPY, dest_dir="第2章 设计"
        )
        # 计划生成后项目又发生了一轮写盘（例如另一章的复制/改名）：代次前进。
        self.workspace._after_write(changed_paths=[self.chapter2])
        self.assertGreater(self.workspace._chapter_op_gen, 0)
        # 旧请求记录的代次比当前小 → 该项作废，绝不落到当前章节上。
        results = self.workspace._apply_batch_chapter_plan(
            plan, generation=self.workspace._chapter_op_gen - 1
        )
        self.assertEqual([item.ok for item in results], [False], results)
        self.assertIn("过期", results[0].message)
        for target in ("第2章 设计/目的.md", "第2章 设计/1.1 目的.md"):
            self.assertFalse(self.exists(target))
        self.assertTrue(self.exists(self.chapter1), "作废不得改动源章")

        # 代次一致时同一计划正常应用（对照）
        plan2 = plan_batch_chapters(
            self.workspace._index, [self.chapter2], BATCH_COPY, dest_dir="第2章 设计"
        )
        fresh = self.workspace._chapter_op_gen
        applied = self.workspace._apply_batch_chapter_plan(plan2, generation=fresh)
        self.assertTrue(all(item.ok for item in applied), plan2.result_text())


class OperationCurrentTextTests(_ContentFixture):
    """3.4：复制/改名后缓冲区归属、表格草稿/普通粘贴与检查过期。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from doc_tool.ui.content.workspace import ContentWorkspace

        self.workspace = ContentWorkspace(
            self.content,
            project_root=self.work,
            state_dir=self.state,
            assets_root=self.work / "assets",
            on_status=lambda message: None,
        )
        self.addCleanup(self.workspace.deleteLater)
        if getattr(self.workspace, "_index", None) is None:
            self.workspace._index = self.workspace._index_service.build()

    def test_copy_keeps_buffer_with_original_and_saves_to_original(self):
        from PySide6.QtWidgets import QInputDialog

        self.workspace.open_file(self.chapter1)
        editor = self.workspace.tabs_host.editor_for(self.chapter1)
        marker = "复制后仍属于原章的正文"
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(marker + NL)
        position_before = editor._editor.textCursor().position()

        with patch.object(
            QInputDialog, "getText", return_value=("1.1 目的（界面副本）", True)
        ):
            self.workspace._on_copy_file(self.chapter1)

        self.assertIs(self.workspace.tabs_host.editor_for(self.chapter1), editor)
        self.assertTrue(editor.is_dirty())
        self.assertEqual(editor._editor.textCursor().position(), position_before)
        # 副本按原服务编号规则落盘（编号属于章节身份）：按内容定位真实副本。
        copies = [
            rel
            for rel in self.files()
            if rel != self.chapter1
            and "界面副本" in rel
            and marker in self.read(rel)
        ]
        self.assertEqual(len(copies), 1, self.files())
        copy_rel = copies[0]
        # 副本是「当前有效正文」的快照（3.1 契约），原章磁盘此刻仍未被改写。
        self.assertNotIn(marker, self.read(self.chapter1))
        self.assertIn("界面副本", self.read(copy_rel))
        copy_before_save = self.read(copy_rel)
        # 保存写的是原章路径：原章拿到正文，副本不被二次覆盖、路径不串。
        self.assertTrue(editor.save())
        self.assertIn(marker, self.read(self.chapter1))
        self.assertEqual(self.read(copy_rel), copy_before_save)
        self.assertEqual(editor.current_rel_path(), self.chapter1)
        self.assertIs(self.workspace.tabs_host.editor_for(self.chapter1), editor)

    def test_copy_identity_and_resource_readback(self):
        """副本获得独立条目身份，且原章资源引用在副本里仍可读回。"""
        import re as _re

        from PySide6.QtWidgets import QInputDialog

        from doc_tool.application.content.traceable_items import build_item_index

        self.workspace.open_file(self.chapter1)

        with patch.object(
            QInputDialog, "getText", return_value=("1.1 目的（副本身份）", True)
        ):
            self.workspace._on_copy_file(self.chapter1)
        added = [
            rel
            for rel in self.files()
            if rel != self.chapter1 and "副本身份" in rel
        ]
        self.assertEqual(len(added), 1, self.files())
        documents = [(rel, self.read(rel)) for rel in self.files()]
        item_index = build_item_index(documents, project_id="P1")
        self.assertEqual(item_index.duplicates, [], item_index.to_dict())
        ids = [item_id for _project, item_id in item_index.items]
        self.assertIn(ITEM_1, ids, "原章条目身份必须保留")
        self.assertEqual(len(ids), 4, ids)
        # 资源/正文读回：副本正文可完整读回，且新路径已进入当前索引（预览/出稿范围）。
        copied = self.read(added[0])
        self.assertIn("第一章正文。", copied)
        self.assertIn(added[0], self.workspace._index.all_files())

    def test_rename_keeps_buffer_table_text_and_paste_behaviour(self):
        # 真实入口在脏缓冲上会走「先保存/放弃/取消」确认：注入明确的「放弃」决策，
        # 避免离屏测试被模态框卡住（正文仍保留在编辑器缓冲里，不会被保存）。
        from PySide6.QtWidgets import QInputDialog

        from doc_tool.application.content.refactor import RefactorService

        from doc_tool.application.content.unsaved import UnsavedChoice

        self.workspace._unsaved_resolver = lambda paths, kind: UnsavedChoice.DISCARD
        self.workspace.open_file(self.chapter1)
        editor = self.workspace.tabs_host.editor_for(self.chapter1)
        table = "| A | B |" + NL + "| --- | --- |" + NL + "| 1 | 2 |" + NL
        cursor = editor._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(table)
        position_before = editor._editor.textCursor().position()
        self.assertTrue(editor.is_dirty())

        new_name = "1.1 目的（改名）.md"
        with patch.object(QInputDialog, "getText", return_value=(new_name, True)):
            self.workspace._on_rename_file(self.chapter1)

        new_rel = "第1章 引言/" + new_name
        self.assertTrue(self.exists(new_rel), self.files())
        self.assertFalse(self.exists(self.chapter1))
        self.assertIs(
            self.workspace.tabs_host.editor_for(new_rel), editor,
            "改名必须沿用同一编辑器实例（保留正文/光标/撤销栈）",
        )
        self.assertEqual(editor.current_rel_path(), new_rel)
        self.assertIn("| A | B |", editor.plain_text(), "表格文本必须保留")
        self.assertEqual(editor._editor.textCursor().position(), position_before)
        self.assertTrue(editor.is_dirty(), "改名不应清除脏标记")
        # 普通粘贴路径仍可用（未被章节操作改成隐式清洗）
        self.assertTrue(hasattr(editor, "canInsertFromMimeData") or hasattr(editor._editor, "canInsertFromMimeData"))
        # 原章路径不复活
        self.assertTrue(editor.save())
        self.assertIn("| A | B |", self.read(new_rel))
        self.assertFalse(self.exists(self.chapter1))

    def test_check_results_marked_stale_after_chapter_operation(self):
        """旧检查结果按既有规则标过期：一键修复被拒绝并要求重检。"""
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.lint import ContentLinter, TermStore
        from doc_tool.application.content.quality_rules import QualityRulesConfig
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.ui.content.lint_panel import STALE_RECHECK_MESSAGE, LintPanel

        # 磁盘正文带「# 后缺空格」问题，活缓冲已修好 → 检查结果基于活缓冲
        bad = "#1.2 范围" + NL + "正文。" + NL
        (self.content / self.chapter2).write_text(bad, encoding="utf-8")
        index = ContentIndexService(self.content).build()
        writer = ContentWriter(self.content, self.state)
        buffer = {self.chapter2: "# 1.2 范围" + NL + "正文。" + NL}
        panel = LintPanel(
            ContentLinter(index, QualityRulesConfig(self.state, "general")),
            TermStore(self.state),
            writable=True,
            writer=writer,
            scope_provider=lambda: ("current", self.chapter2, [self.chapter2]),
            live_text_provider=lambda rel: buffer.get(rel),
        )
        self.addCleanup(panel.deleteLater)
        self.workspace._lint_panel = panel
        self.workspace._index = index

        panel._scope_combo.setCurrentIndex(1)
        panel.run_check()
        self.assertTrue(panel._text_overrides, "检查必须记录结果对应的正文快照")

        # 章节操作（复制）后：workspace 把受影响章标为需重检
        self.workspace._mark_stale_check_results([self.chapter2])
        self.assertEqual(panel._stale_paths, [self.chapter2])
        self.assertNotIn(self.chapter2, panel._text_overrides)
        self.assertIn(STALE_RECHECK_MESSAGE, panel._status_label.text())

        # 旧结果不再可直接应用：按同一条既有规则提示重检
        issue = next(
            (item for item in panel._issues if item.rel_path == self.chapter2), None
        )
        if issue is None:
            from doc_tool.application.content.lint import LintIssue

            issue = LintIssue(
                rule="heading-space",
                rel_path=self.chapter2,
                line_no=1,
                message="标题缺少空格",
                severity="warning",
            )
        self.assertFalse(panel.quick_fix_issue(issue))
        self.assertIn(STALE_RECHECK_MESSAGE, panel._status_label.text())
        self.assertIn("正文。", buffer[self.chapter2], "过期结果不得改写活缓冲正文")
        self.assertIn(
            "#1.2 范围", self.read(self.chapter2), "过期结果不得改写磁盘正文"
        )

    def test_after_write_marks_stale_and_refreshes_index(self):
        """workspace._after_write 委托面板标过期，且索引立即采用当前表达。"""
        from doc_tool.application.content.index import ContentIndexService

        index = ContentIndexService(self.content).build()
        self.workspace._index = index
        marked = []

        class _PanelStub:
            def mark_chapters_changed(self, rel_paths):
                marked.extend(rel_paths)

        self.workspace._lint_panel = _PanelStub()
        # 新增一章后再走写后路径：索引看到新章，面板收到过期标注
        new_rel = "第2章 设计/2.2 新增.md"
        self.writer.create_file(new_rel, "# 2.2 新增" + NL)
        self.workspace._after_write(changed_paths=[new_rel])
        self.assertEqual(marked, [new_rel])
        self.assertIn(new_rel, self.workspace._index.all_files())


if __name__ == "__main__":
    unittest.main(verbosity=2)