# -*- coding: utf-8 -*-
"""MAIN2-A：导入结果完整可重开、批量接续与真实数量读回。"""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.intake_batch import (  # noqa: E402
    ITEM_CANCELLED, ITEM_FAILED, ITEM_OK, ITEM_PENDING_CONVERT,
    BatchItemResult, BatchResult, retry_selected_word_items,
)
from doc_tool.application.intake_result_page import IntakeResultPage  # noqa: E402


def _details(count: int):
    rows = []
    for index in range(count):
        rows.append({
            "feature": "image" if index % 2 == 0 else "formula",
            "handling": "placeholder" if index % 2 == 0 else "original-only",
            "target_chapter": "第{0}章".format(index % 5 + 1),
            "target_path": "第{0}章/节{1}.md".format(index % 5 + 1, index),
            "target_line": index + 1,
            "detail": "第 {0} 项说明".format(index + 1),
            "action": "",
        })
    return rows


class _FakeHost:
    """记录动作目标的最小宿主（不发真实 UI 动作）。"""

    def __init__(self, page: IntakeResultPage) -> None:
        self.page = page
        self.located = []
        self.opened = []
        self.replaced = []
        self.rebuilt = 0

    def _build_intake_page(self, project_root):
        return self.page

    def _locate_intake_finding(self, page, item, window=None):
        self.located.append((page.projectRoot, item.get("target_path"), item.get("target_line")))

    def _open_intake_original(self, page, item):
        self.opened.append(item.get("target_path"))

    def _replace_intake_image(self, page, item, window=None):
        self.replaced.append(item.get("target_line"))
        # 真实账本读回：处理后记录数量减少。
        self.page.details = [row for row in self.page.details if row is not item]
        self.rebuilt += 1
        return True


def _page(count: int, project_root: str = "D:/proj") -> IntakeResultPage:
    page = IntakeResultPage(projectRoot=project_root)
    page.details = _details(count)
    page.summary = ["原件已保留：original/source.docx", "{0} 处内容待完善".format(count)]
    page.counts = {"placeholder": count // 2, "original-only": count - count // 2}
    page.toFix = count
    page.hasRecord = True
    return page


class IntakeResultWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _window(self, count: int):
        from doc_tool.ui.intake_result_window import IntakeResultWindow

        page = _page(count)
        host = _FakeHost(page)
        window = IntakeResultWindow(page, host=host)
        self.addCleanup(window.close)
        return window, host, page

    def test_over_forty_items_are_all_reachable(self):
        """超过 40 项时最后一项仍能查看（旧实现 details[:40] 会截断）。"""
        window, _host, page = self._window(120)
        self.assertIn("共 120 项处理事实", window._counts.text())
        # 首页 50 项
        self.assertEqual(window._table.rowCount(  ), 50)
        window._turn_page(1)
        self.assertEqual(window._table.rowCount(), 50)
        window._turn_page(1)
        self.assertEqual(window._table.rowCount(), 20)
        self.assertIn("第 3/3 页", window._page_label.text())
        # 最后一项真实可见
        last_row = window._table.rowCount() - 1
        self.assertIn("第 120 项说明", window._table.item(last_row, 4).text())
        self.assertEqual(window._table.item(last_row, 2).text(), page.details[-1]["target_chapter"])

    def test_search_and_kind_filter_keep_real_total(self):
        window, _host, _page = self._window(120)
        window._search.setText("第 7 项说明")
        self.assertEqual(window._table.rowCount(), 1)
        self.assertIn("共 120 项处理事实，当前筛选 1 项", window._counts.text())
        window._search.clear()
        window._kind_combo.setCurrentIndex(window._kind_combo.findData("formula"))
        self.assertEqual(window._table.rowCount(), 50)
        self.assertIn("当前筛选 60 项", window._counts.text())
        # 零结果不改变总量
        window._search.setText("不存在的关键字")
        self.assertEqual(window._table.rowCount(), 0)
        self.assertIn("共 120 项处理事实，当前筛选 0 项", window._counts.text())

    def test_window_is_non_modal(self):
        window, _host, _page = self._window(3)
        self.assertFalse(window.isModal())
        self.assertTrue(window.windowFlags() & window.windowFlags().Window)

    def test_actions_use_selected_row_and_reload_real_count(self):
        window, host, page = self._window(60)
        window._table.selectRow(0)
        selected = window.selected_row_dict()
        self.assertIsNotNone(selected)
        window._on_locate()
        self.assertEqual(host.located, [(page.projectRoot, selected["target_path"], selected["target_line"])])
        window._table.selectRow(0)
        window._on_replace_image()
        self.assertEqual(host.replaced, [selected["target_line"]])
        # 处理完读回真实记录数量（不是本地减一）
        self.assertEqual(host.rebuilt, 1)
        self.assertEqual(len(window._rows), 59)
        self.assertIn("共 59 项处理事实", window._counts.text())


class BatchContinuationTests(unittest.TestCase):
    def _batch(self):
        return BatchResult(
            parent_dir="D:/out",
            settings={"parentDir": "D:/out", "policy": "normal", "documentNo": "NO-1", "documentVersion": "2.0"},
            items=[
                BatchItemResult(source="D:/in/a.docx", status=ITEM_OK, project_root="D:/out/a"),
                BatchItemResult(source="D:/in/b.docx", status=ITEM_FAILED, message="被占用"),
                BatchItemResult(source="D:/in/c.docx", status=ITEM_PENDING_CONVERT, message="需转换"),
                BatchItemResult(source="D:/in/d.docx", status=ITEM_CANCELLED, message="未开始"),
            ],
        )

    def test_only_selected_items_are_retried(self):
        batch = self._batch()
        seen = {}

        def _fake_batch(sources, **kwargs):
            seen["sources"] = list(sources)
            seen["kwargs"] = kwargs
            return BatchResult(
                parent_dir=kwargs.get("parent_dir") or "",
                settings=dict(batch.settings),
                items=[BatchItemResult(source=str(item), status=ITEM_OK, project_root="D:/out/ok")
                       for item in sources],
            )

        with patch("doc_tool.application.intake_batch.run_word_batch", _fake_batch):
            merged = retry_selected_word_items(batch, ["D:/in/b.docx"])
        self.assertEqual(seen["sources"], ["D:/in/b.docx"], "只补做所选项")
        self.assertEqual(seen["kwargs"]["document_no"], "NO-1", "输入设置保留")
        self.assertEqual(seen["kwargs"]["document_version"], "2.0")
        self.assertEqual(seen["kwargs"]["parent_dir"], "D:/out")
        by_source = {item.source: item for item in merged.items}
        self.assertEqual(by_source["D:/in/a.docx"].status, ITEM_OK, "已成功项目不被重建")
        self.assertEqual(by_source["D:/in/b.docx"].status, ITEM_OK)
        self.assertEqual(by_source["D:/in/c.docx"].status, ITEM_PENDING_CONVERT, "未选项保持原状态")
        self.assertEqual(len(merged.succeeded), 2)

    def test_successful_project_is_never_recreated(self):
        batch = self._batch()
        calls = []

        def _fake_batch(sources, **kwargs):
            calls.append(list(sources))
            return BatchResult(items=[BatchItemResult(source=str(item), status=ITEM_FAILED) for item in sources])

        with patch("doc_tool.application.intake_batch.run_word_batch", _fake_batch):
            retry_selected_word_items(batch, ["D:/in/a.docx", "D:/in/b.docx"])
        self.assertEqual(calls, [["D:/in/b.docx"]], "已成功项目不进入补做清单")

    def test_no_selection_returns_previous_view_unchanged(self):
        batch = self._batch()
        merged = retry_selected_word_items(batch, [])
        self.assertEqual([item.source for item in merged.items], [item.source for item in batch.items])


class MainWindowIntakeResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from scripts.tests import core_fixtures as fixtures

        self.work = fixtures.scratch_dir("main2a-intake")
        self.addCleanup(fixtures.cleanup, self.work)
        self.project = fixtures.two_chapter_project(self.work / "proj")
        from doc_tool.ui.main_window import MainWindow

        with patch("doc_tool.application.project_service.load_recent_projects", return_value=[]):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        from doc_tool.application.import_record import (
            ImportRecord, read_import_record, write_import_record,
        )

        record = read_import_record(self.project)
        if record is None:
            record = ImportRecord(sourceFile="sample.docx", retainedPath="original/source.docx")
        record.findings = []
        from doc_tool.application.intake_contract import PreservationFinding

        for index in range(45):
            record.findings.append(PreservationFinding(
                "image" if index % 3 == 0 else "formula",
                "placeholder" if index % 3 == 0 else "original-only",
                target_chapter="第1章 引言",
                target_path="第1章 引言/1.1 目的.md",
                target_line=index + 1,
                detail="第 {0} 项".format(index + 1),
            ))
        write_import_record(self.project, record)

    class _Summary:
        is_writable = True

        def __init__(self, project: Path):
            from doc_tool.domain.manifest import ProjectManifest
            from doc_tool.domain.paths import ProjectPaths

            self.project_root = str(project)
            self.manifest = ProjectManifest.load(project)
            self.paths = ProjectPaths(project)

    def test_reopen_import_result_after_import(self):
        """导入结果可重开：菜单动作打开非模态窗口并显示真实总数。"""
        self.window._project_summary = self._Summary(self.project)
        self.assertTrue(self.window.reopen_intake_result())
        window = self.window._intake_result_window
        self.assertIsNotNone(window)
        self.assertFalse(window.isModal())
        self.assertIn("共 45 项处理事实", window._counts.text())

    def test_reopen_without_record_reports_next_step(self):
        empty = self.work / "empty"
        empty.mkdir(parents=True, exist_ok=True)
        summary = self._Summary(self.project)
        summary.project_root = str(empty)
        self.window._project_summary = summary
        self.assertFalse(self.window.reopen_intake_result())
        # 就地给出下一步（项目有清单但无导入记录 → 明确指出该情况）。
        messages = [self.window._status_label.text()]
        bar = getattr(self.window, "statusBar", None)
        if callable(bar):
            try:
                messages.append(bar().currentMessage())
            except Exception:  # noqa: BLE001 - 状态栏不可用时只看标签
                pass
        self.assertTrue(
            any("没有导入记录" in text for text in messages),
            "应就地说明该项目没有导入记录：{0}".format(messages),
        )

    def test_locate_action_uses_project_window(self):
        self.window._project_summary = self._Summary(self.project)
        page = self.window._build_intake_page(str(self.project))
        opened = []
        self.window._open_chapter_in_workspace = (
            lambda rel_path, line=None, source="": opened.append((rel_path, line)) or True
        )
        self.window._locate_intake_finding(page, page.details[0])
        self.assertEqual(opened, [("第1章 引言/1.1 目的.md", 1)])


if __name__ == "__main__":
    unittest.main(verbosity=2)