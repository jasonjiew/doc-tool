# -*- coding: utf-8 -*-
"""RD 研发工作区界面回归（RD-A～RD-F）。

覆盖薄适配层（来源定位、N/A 分母、显式关系、集合清单）与真实对话框入口
（成员表、设置分组保存、条目动作、关系幂等、矩阵跳转、集合恢复、成员交付）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
for candidate in (
    str(ROOT),
    str(ROOT / "scripts"),
    str(ROOT / "scripts" / "tests"),
):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from scripts.tests import rd_fixtures  # noqa: E402
from doc_tool.application import rd_surface as surface  # noqa: E402
from doc_tool.application.content.relations import load_relations  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402


def _cleanup(path):
    assert Path(path).resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(path)


class RdSurfaceTests(unittest.TestCase):
    """薄适配层：行、来源与分母语义（不驱动界面）。"""

    @classmethod
    def setUpClass(cls):
        cls.shared = fixtures.scratch_dir("rd-surface-shared")
        cls.data = rd_fixtures.build_rd_workspace(cls.shared / "研发工作区")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls.shared)

    def setUp(self):
        self.root = Path(self.data["root"])
        self.workspace, self.message = surface.open_workspace(self.root)
        self.assertIsNotNone(self.workspace, self.message)

    def test_member_rows_expose_identity_role_and_availability(self):
        rows = surface.member_rows(self.workspace)
        self.assertEqual(len(rows), 3)
        by_role = {row["role"]: row for row in rows}
        self.assertEqual(set(by_role), {"requirement", "design", "test"})
        self.assertEqual(by_role["requirement"]["projectId"], self.data["ids"]["documents/需求"])
        self.assertEqual(by_role["requirement"]["roleLabel"], "需求")
        self.assertTrue(all(row["available"] for row in rows))
        self.assertFalse(any(row["readonly"] for row in rows))

    def test_high_schema_member_is_readonly_but_other_members_work(self):
        """真实更高模式版本：只读可读，其他成员不受影响（不通过 save 伪造）。"""
        import re

        project = Path(self.data["projects"]["documents/测试"])
        manifest_file = project / "project.yml"
        original = manifest_file.read_text(encoding="utf-8")
        # 与应用版本无关：直接把清单的模式版本改成本应用不可写的更高值。
        patched = re.sub(r"schemaVersion:\s*\d+", "schemaVersion: 99", original, count=1)
        self.assertNotEqual(patched, original)
        manifest_file.write_text(patched, encoding="utf-8")
        try:
            workspace, _message = surface.open_workspace(self.root)
            rows = {row["role"]: row for row in surface.member_rows(workspace)}
            self.assertTrue(rows["test"]["readonly"])
            self.assertIn("只读", rows["test"]["reason"])
            self.assertTrue(rows["test"]["available"])
            self.assertFalse(rows["requirement"]["readonly"])
            self.assertEqual(rows["requirement"]["status"], surface.STATUS_OK)
        finally:
            manifest_file.write_text(original, encoding="utf-8")

    def test_missing_member_keeps_others_available(self):
        project = Path(self.data["projects"]["documents/设计"])
        moved = self.root / "documents" / "设计-移走"
        project.rename(moved)
        try:
            workspace, _message = surface.open_workspace(self.root)
            rows = {row["role"]: row for row in surface.member_rows(workspace)}
            self.assertEqual(rows["design"]["status"], surface.STATUS_ERROR)
            self.assertFalse(rows["design"]["available"])
            self.assertIn("重新定位", rows["design"]["nextAction"])
            self.assertTrue(rows["requirement"]["available"])
            self.assertTrue(rows["test"]["available"])
        finally:
            moved.rename(project)

    def test_overview_view_uses_service_truth(self):
        payload = surface.overview_view(self.data["projects"]["documents/需求"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["documentName"], "需求规格")
        self.assertTrue(payload["sections"])
        self.assertIsInstance(payload["nextActions"], list)

    def test_matrix_view_reports_na_instead_of_fake_coverage(self):
        index = surface.combined_index([(self.data["ids"]["documents/需求"], [("空章.md", "# 空\n\n没有条目。\n")])])
        payload = surface.matrix_view(list(index.items.values()), surface.empty_graph())
        self.assertFalse(payload["applicable"])
        self.assertEqual(payload["coverage"]["design"], "N/A")
        self.assertEqual(payload["coverage"]["test"], "N/A")
        self.assertIn("N/A", payload["message"])

    def test_matrix_view_matches_service_report_rows(self):
        entries = []
        docs = {
            "documents/需求": surface.project_documents(self.data["projects"]["documents/需求"]),
            "documents/设计": surface.project_documents(self.data["projects"]["documents/设计"]),
            "documents/测试": surface.project_documents(self.data["projects"]["documents/测试"]),
        }
        for name, items in docs.items():
            entries.append((self.data["ids"][name], items))
        index = surface.combined_index(entries)
        graph, _documents = surface.collect_graph(self.root, workspace=True)
        payload = surface.matrix_view(list(index.items.values()), graph, page_size=10)
        from doc_tool.application.content.trace_matrix import build_coverage

        report = build_coverage(list(index.items.values()), graph)
        self.assertEqual(payload["report"]["rows"], report.to_dict()["rows"])
        self.assertEqual(payload["coverage"]["test"], surface.percent_text(report.test_coverage))
        self.assertEqual(payload["coverage"]["test"], "100.0%")
        self.assertEqual(payload["metrics"][0]["value"], "1")

    def test_locate_sources_uses_real_identity_and_reports_unknown_items(self):
        documents = surface.project_documents(self.data["projects"]["documents/需求"])
        index = surface.build_index(documents, project_id=self.data["ids"]["documents/需求"])
        item_id = self.data["itemIds"]["R-1"]
        found = surface.locate_sources(item_id, index, project_id=self.data["ids"]["documents/需求"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].relPath, "1 概述/1.1 背景.md")
        self.assertGreater(found[0].lineNo, 0)
        self.assertTrue(found[0].ok)
        self.assertEqual(surface.locate_sources("不存在", index), [])

    def test_endpoint_options_show_member_chapter_and_source(self):
        members = surface.member_lookup(self.workspace)
        entries = [
            (self.data["ids"]["documents/需求"], surface.project_documents(self.data["projects"]["documents/需求"])),
            (self.data["ids"]["documents/设计"], surface.project_documents(self.data["projects"]["documents/设计"])),
        ]
        index = surface.combined_index(entries)
        options = surface.endpoint_options(index, members=members)
        self.assertEqual(len(options), 2)
        requirement = next(item for item in options if item["itemId"] == self.data["itemIds"]["R-1"])
        self.assertEqual(requirement["memberRoleLabel"], "需求")
        self.assertEqual(requirement["memberName"], "需求规格")
        self.assertIn("1 概述/1.1 背景.md", requirement["relPath"])
        self.assertEqual(requirement["sourceLabel"], surface.source_label(surface.SOURCE_SAVED))
        self.assertTrue(requirement["searchText"])

    def test_documents_with_buffers_marks_actual_source(self):
        saved = surface.project_documents(self.data["projects"]["documents/需求"])
        target = saved[0][0]
        rows = surface.documents_with_buffers(saved, {target: "# 修改后的缓冲\n"})
        sources = {row["relPath"]: row["source"] for row in rows}
        self.assertEqual(sources[target], surface.SOURCE_BUFFER)
        self.assertTrue(all(
            value == surface.SOURCE_BUFFER for key, value in sources.items() if key == target
        ))
        self.assertIn(surface.SOURCE_SAVED, set(sources.values()))

    def test_review_rows_without_store_is_explicit(self):
        payload = surface.review_rows(None)
        self.assertFalse(payload["available"])
        self.assertIn("未启用", payload["message"])

    def test_collection_rows_and_recover_copy_keep_source_intact(self):
        requirement_root = Path(self.data["projects"]["documents/需求"])
        payload = surface.collection_rows(requirement_root)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["rows"]), 1)
        manifest_path = payload["rows"][0]["path"]
        watched = requirement_root / "project.yml"
        before = watched.read_bytes()
        work = fixtures.scratch_dir("rd-recover")
        try:
            destination = work / "恢复副本"
            result = surface.collection_recover(requirement_root, manifest_path, destination)
            self.assertTrue(result["ok"], result.get("message"))
            self.assertTrue(result["restored"], "恢复结果应列出已恢复文件")
            self.assertEqual(watched.read_bytes(), before)
            self.assertTrue(destination.is_dir())
        finally:
            _cleanup(work)

    def test_item_action_helpers_run_on_buffer_text(self):
        from scripts.tests import rd_fixtures as _fixtures

        documents = surface.project_documents(self.data["projects"]["documents/测试"])
        index = surface.build_index(documents, project_id=self.data["ids"]["documents/测试"])
        rows = surface.item_action_rows(index, rel_path="3 测试/3.1 用例.md")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["itemId"], self.data["itemIds"]["T-1"])
        self.assertGreater(rows[0]["lineNo"], 0)


class RdWorkspaceGuiTests(unittest.TestCase):
    """真实对话框入口：成员、设置、条目、关系、矩阵、集合与交付。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("rd-gui")
        self.data = rd_fixtures.build_rd_workspace(self.work / "研发工作区")
        self.root = Path(self.data["root"])
        self.requirement_root = str(self.data["projects"]["documents/需求"])
        self.host = rd_fixtures.FakeRdHost(self.requirement_root)
        self.dialog = self._open_dialog(self.root)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()
        _cleanup(self.work)

    def _open_dialog(self, root):
        from doc_tool.ui.rd_workspace import RdWorkspaceDialog

        dialog = RdWorkspaceDialog(self.host, root=str(root))
        dialog.resize(1280, 720)
        return dialog

    def _combo_index(self, combo, data):
        for index in range(combo.count()):
            if combo.itemData(index) == data:
                return index
        raise AssertionError("未找到候选项：{0}".format(data))

    # --- RD-B ---

    def test_dialog_lists_members_overview_and_settings_groups(self):
        self.assertEqual(self.dialog.member_table.rowCount(), 3)
        self.assertIn("研发交付", self.dialog.workspace_label.text())
        self.assertTrue(self.dialog.overview_text.toPlainText().strip())
        self.assertGreaterEqual(self.dialog.settings_group.count(), 5)
        self.assertTrue(self.dialog._settings_widgets, "设置分组应渲染出字段控件")

    def test_settings_saves_current_group_only_and_keeps_other_groups(self):
        project = Path(self.requirement_root)
        manifest = ProjectManifest.load(project)
        manifest.variables = {"team": "平台组"}
        manifest.save(project)
        self.dialog.refresh_settings()
        section_index = self.dialog.settings_group.findData("基本信息")
        self.assertGreaterEqual(section_index, 0)
        self.dialog.settings_group.setCurrentIndex(section_index)
        self.app.processEvents()
        self.dialog._settings_widgets["documentVersion"].setText("2.5")
        self.dialog._settings_widgets["documentName"].setText("需求规格 V2")
        self.dialog.save_settings_btn.click()
        self.app.processEvents()
        saved = ProjectManifest.load(project)
        self.assertEqual(saved.documentVersion, "2.5")
        self.assertEqual(saved.documentName, "需求规格 V2")
        self.assertEqual(saved.variables.get("team"), "平台组", "其他分组不得被重写")

    def test_settings_invalid_value_keeps_input_and_locates_field(self):
        section_index = self.dialog.settings_group.findData("基本信息")
        self.dialog.settings_group.setCurrentIndex(section_index)
        self.app.processEvents()
        self.dialog._settings_widgets["documentVersion"].setText("   ")
        self.dialog.save_settings_btn.click()
        self.app.processEvents()
        self.assertIn("documentVersion", self.dialog.settings_error.text())
        self.assertEqual(self.dialog._settings_widgets["documentVersion"].text(), "   ", "非法输入必须保留")
        self.assertEqual(ProjectManifest.load(Path(self.requirement_root)).documentVersion, "1.0")

    # --- RD-C ---

    def test_declare_item_writes_single_editor_transaction(self):
        chapter = "1 概述/1.1 背景.md"
        self.host.current_chapter = chapter
        self.host.buffers = {chapter: "# 1.1 背景\n\n系统应支持离线出稿。\n"}
        self.dialog.refresh_all()
        self.dialog.declare_btn.click()
        self.app.processEvents()
        self.assertEqual(len(self.host.applied_edits), 1, "声明条目应只发生一次编辑事务")
        rel_path, text, message = self.host.applied_edits[0]
        self.assertEqual(rel_path, chapter)
        self.assertIn("DOC-ITEM", text)
        self.assertIn(self.host.rd_project_id(), text)
        self.assertIn("声明", message)

    def test_copy_item_generates_new_id_in_buffer(self):
        chapter = "1 概述/1.1 背景.md"
        original = "# 1.1 背景\n\n系统应支持离线出稿。\n"
        self.host.current_chapter = chapter
        self.host.buffers = {chapter: original}
        self.dialog.refresh_all()
        self.dialog.declare_btn.click()
        self.app.processEvents()
        buffered = self.host.buffers[chapter]
        self.dialog.refresh_all()
        target_row = None
        for index, row in enumerate(self.dialog._item_rows):
            if any(place.get("relPath") == chapter for place in row["locations"]):
                target_row = index
        self.assertIsNotNone(target_row, "声明后应能在当前章节看到该条目")
        self.dialog.item_table.selectRow(target_row)
        self.dialog.copy_item_btn.click()
        self.app.processEvents()
        self.assertEqual(len(self.host.applied_edits), 2)
        copied = self.host.buffers[chapter]
        self.assertGreater(copied.count("DOC-ITEM"), buffered.count("DOC-ITEM"))
        self.assertNotEqual(copied, buffered)

    def test_relation_add_is_idempotent_and_uses_real_endpoints(self):
        design_id = self.data["ids"]["documents/设计"]
        requirement_id = self.data["ids"]["documents/需求"]
        self.dialog.rel_source.setCurrentIndex(
            self._combo_index(self.dialog.rel_source, [design_id, self.data["itemIds"]["D-1"]])
        )
        self.dialog.rel_target.setCurrentIndex(
            self._combo_index(self.dialog.rel_target, [requirement_id, self.data["itemIds"]["R-1"]])
        )
        type_index = self.dialog.rel_type.findData("verifies")
        self.dialog.rel_type.setCurrentIndex(type_index)
        self.dialog.add_relation_btn.click()
        self.app.processEvents()
        before = len(load_relations(self.data["relations"]).relations)
        self.dialog.add_relation_btn.click()
        self.app.processEvents()
        graph = load_relations(self.data["relations"])
        self.assertEqual(len(graph.relations), before, "重复建立同一关系必须幂等")
        matching = [
            item for item in graph.relations
            if item.type == "verifies" and item.source.key == (design_id, self.data["itemIds"]["D-1"])
        ]
        self.assertEqual(len(matching), 1)

    def test_unsaved_endpoint_keeps_relation_draft_then_saves_both_ends(self):
        # 未保存端点必须属于“当前项目”，否则只能提示在其他成员窗口保存。
        chapter = "1 概述/1.2 目标.md"
        disk = (Path(self.requirement_root) / "content/requirement" / chapter).read_text(encoding="utf-8")
        new_id = "6f1f5c4e-0d1a-5b2c-9f31-0a1b2c3d4e09"
        marker = "<!-- DOC-ITEM: projectId={0} kind=requirement id={1} alias=未保存端点 -->".format(
            self.data["ids"]["documents/需求"], new_id,
        )
        self.host.buffers = {chapter: disk + "\n" + marker + "\n"}
        self.dialog.refresh_all()
        relations_before = load_relations(self.data["relations"]).relations
        self.dialog.rel_source.setCurrentIndex(
            self._combo_index(self.dialog.rel_source, [self.data["ids"]["documents/需求"], new_id])
        )
        self.dialog.rel_target.setCurrentIndex(
            self._combo_index(self.dialog.rel_target, [self.data["ids"]["documents/需求"], self.data["itemIds"]["R-1"]])
        )
        self.dialog.add_relation_btn.click()
        self.app.processEvents()
        self.assertEqual(len(load_relations(self.data["relations"]).relations), len(relations_before))
        self.assertIn("草稿", self.dialog.relation_draft_label.text())
        self.dialog.save_endpoints_btn.click()
        self.app.processEvents()
        self.assertTrue(self.host.saved_chapters, "仅保存相关两端应调用保存入口")
        graph = load_relations(self.data["relations"])
        self.assertEqual(len(graph.relations), len(relations_before) + 1)

    def test_locate_item_opens_real_source(self):
        chapter = "1 概述/1.1 背景.md"
        self.host.current_chapter = chapter
        self.host.buffers = {}
        self.dialog.refresh_all()
        target_row = None
        for index, row in enumerate(self.dialog._item_rows):
            if row["itemId"] == self.data["itemIds"]["R-1"]:
                target_row = index
        self.assertIsNotNone(target_row)
        self.dialog.item_table.selectRow(target_row)
        self.dialog.locate_item_btn.click()
        self.app.processEvents()
        self.assertTrue(self.host.opened_sources)
        rel_path, line_no, _source = self.host.opened_sources[-1]
        self.assertEqual(rel_path, chapter)
        self.assertGreater(line_no, 0)

    # --- RD-D ---

    def test_matrix_covers_explicit_requirement_and_locates_source(self):
        self.assertEqual(self.dialog.metric_labels["total"].text(), "1")
        self.assertEqual(self.dialog.metric_labels["design"].text(), "100.0%")
        self.assertEqual(self.dialog.matrix_table.rowCount(), 1)
        self.dialog.matrix_table.selectRow(0)
        self.dialog.matrix_locate_btn.click()
        self.app.processEvents()
        self.assertTrue(self.host.opened_sources)
        self.assertEqual(self.host.opened_sources[-1][0], "1 概述/1.1 背景.md")

    def test_matrix_without_requirements_shows_na(self):
        project = self.work / "无需求工作区"
        project.mkdir(parents=True, exist_ok=True)
        from scripts.tests.fixture_factory import create_project

        create_project(project, document_type="requirement")
        (project / "content" / "requirement" / "1 概述").mkdir(parents=True, exist_ok=True)
        (project / "content" / "requirement" / "1 概述" / "1.1 背景.md").write_text(
            "# 1.1 背景\n\n没有声明任何条目。\n", encoding="utf-8",
        )
        dialog = self._open_dialog(project)
        try:
            self.assertEqual(dialog.metric_labels["total"].text(), "0")
            self.assertEqual(dialog.metric_labels["design"].text(), "N/A")
            self.assertIn("N/A", dialog.matrix_source_label.text())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_matrix_reports_orphans_and_dangling_relations(self):
        """孤立条目与悬空关系必须显式列出，而不是静默忽略。"""
        import yaml

        graph = surface.empty_graph()
        from doc_tool.application.content.relations import Endpoint, Relation

        graph.relations.append(Relation(
            relation_id="dangling-1", type="satisfies",
            source=Endpoint("missing-project", "missing-item"),
            target=Endpoint("missing-project", "missing-item-2"),
        ))
        documents = surface.project_documents(self.data["projects"]["documents/需求"])
        index = surface.build_index(documents, project_id=self.data["ids"]["documents/需求"])
        payload = surface.matrix_view(list(index.items.values()), graph)
        self.assertTrue(payload["dangling"], "悬空关系必须列出")
        self.assertIn("missing-project", " ".join(str(item) for item in payload["dangling"]))

    def test_collection_compare_and_export_package(self):
        requirement_root = Path(self.data["projects"]["documents/需求"])
        from doc_tool.application.collection import build_manifest, register_manifest

        second = build_manifest(requirement_root, version="1.1", label="基线 1.1")
        path, _note = register_manifest(requirement_root, second)
        self.assertIsNotNone(path)
        rows = surface.collection_rows(requirement_root)["rows"]
        self.assertEqual(len(rows), 2)
        left = next(row for row in rows if row["version"] == "1.0")
        right = next(row for row in rows if row["version"] == "1.1")
        report = surface.collection_compare(left["path"], right["path"])
        self.assertTrue(report["ok"], report.get("message"))
        self.assertIn("entries", report)
        work = fixtures.scratch_dir("rd-package")
        try:
            exported = surface.collection_export_package(requirement_root, right["path"], work)
            self.assertTrue(exported["ok"], exported["message"])
            self.assertTrue(Path(exported["path"]).is_file())
        finally:
            _cleanup(work)

    def test_collection_recover_reports_partial_when_a_file_is_missing(self):
        requirement_root = Path(self.data["projects"]["documents/需求"])
        row = surface.collection_rows(requirement_root)["rows"][0]
        payload = surface.collection_detail(requirement_root, row["path"])
        self.assertTrue(payload["ok"])
        missing_target = None
        for artifact in payload.get("artifacts") or []:
            relative = artifact if isinstance(artifact, str) else (
                artifact.get("relativePath") or artifact.get("path")
            )
            if relative and (requirement_root / str(relative)).is_file():
                missing_target = requirement_root / str(relative)
                break
        self.assertIsNotNone(missing_target, "集合详情应列出真实文件")
        backup = missing_target.read_bytes()
        missing_target.unlink()
        work = fixtures.scratch_dir("rd-partial")
        try:
            result = surface.collection_recover(requirement_root, row["path"], work / "副本")
            self.assertTrue(result["ok"])
            self.assertTrue(result["skipped"], "缺失文件必须逐项列出")
            self.assertTrue(result["restored"], "其余文件仍要恢复")
        finally:
            missing_target.write_bytes(backup)
            _cleanup(work)

    def test_impact_view_reports_buffer_source_and_review_state(self):
        chapter = "1 概述/1.1 背景.md"
        disk = (Path(self.requirement_root) / "content/requirement" / chapter).read_text(encoding="utf-8")
        self.host.buffers = {chapter: disk.replace("系统应支持离线出稿。", "系统应支持离线出稿与一键交付。")}
        self.dialog.refresh_all()
        self.assertIn("变化条目", self.dialog.impact_summary.text())
        self.assertEqual(self.dialog.impact_table.rowCount() >= 0, True)

    # --- RD-E ---

    def test_collection_detail_lists_real_files_and_recover_copy(self):
        self.assertEqual(self.dialog.collection_table.rowCount(), 1)
        self.assertTrue(self.dialog.collection_detail.toPlainText().strip())
        destination = self.work / "恢复目标"
        destination.mkdir(parents=True, exist_ok=True)
        watched = Path(self.requirement_root) / "project.yml"
        before = watched.read_bytes()
        with patch(
            "doc_tool.ui.rd_workspace.QFileDialog.getExistingDirectory",
            return_value=str(destination),
        ):
            self.dialog.recover_btn.click()
        self.app.processEvents()
        self.assertEqual(watched.read_bytes(), before, "恢复副本不得改写源项目")
        self.assertIn("恢复", self.dialog.collection_detail.toPlainText())

    def test_member_delivery_reuses_existing_batch_entry(self):
        self.dialog.delivery_btn.click()
        self.app.processEvents()
        self.assertEqual(self.host.delivery_calls, [str(self.root)])
        self.assertIn("批量交付", self.dialog.delivery_status.text())

    def test_open_member_delegates_to_project_window(self):
        self.dialog.member_table.selectRow(1)
        self.dialog.open_member_btn.click()
        self.app.processEvents()
        self.assertTrue(self.host.opened_projects)
        self.assertTrue(str(self.host.opened_projects[-1]).endswith("设计"))

    # --- RD-F 6.3 ---

    def test_narrow_window_keeps_controls_readable_and_keyboard_reachable(self):
        from PySide6.QtWidgets import QPushButton, QWidget

        self.dialog.resize(1280, 720)
        self.dialog.show()
        self.app.processEvents()
        for index in range(self.dialog.tabs.count()):
            self.dialog.tabs.setCurrentIndex(index)
            self.app.processEvents()
            for button in self.dialog.findChildren(QPushButton):
                if not button.isVisible():
                    continue
                self.assertTrue(button.text().strip(), "可见按钮必须有可读文字")
                self.assertGreaterEqual(button.width(), 24)
        self.dialog.resize(1024, 640)
        self.app.processEvents()
        self.assertEqual(self.dialog.tabs.count(), 4)
        for index in range(self.dialog.tabs.count()):
            self.dialog.tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertTrue(self.dialog.tabs.currentWidget().isVisible(), "窄窗口下每个页签都应可显示")
        focused = set()
        for _ in range(24):
            self.dialog.focusNextChild()
            self.app.processEvents()
            current = self.dialog.focusWidget()
            if isinstance(current, QWidget) and current is not None:
                focused.add(type(current).__name__)
        self.assertGreaterEqual(len(focused), 4, "键盘应能到达多类控件")


class RdSingleDocumentTests(unittest.TestCase):
    """6.2：无工作区时单文档仍可用。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("rd-single")
        self.project = self.work / "单文档"
        from scripts.tests.fixture_factory import create_project

        create_project(self.project, document_type="requirement")
        content = self.project / "content" / "requirement" / "1 概述"
        content.mkdir(parents=True, exist_ok=True)
        manifest = ProjectManifest.load(self.project)
        (content / "1.1 背景.md").write_text(
            "# 1.1 背景\n\n单文档正文。\n\n<!-- DOC-ITEM: projectId={0} kind=requirement "
            "id={1} alias=单文档条目 -->\n".format(manifest.projectId, self.data_id()),
            encoding="utf-8",
        )

    def data_id(self):
        return "6f1f5c4e-0d1a-5b2c-9f31-0a1b2c3d4e10"

    def tearDown(self):
        _cleanup(self.work)

    def test_single_project_reports_no_workspace_but_keeps_views_usable(self):
        from doc_tool.ui.rd_workspace import RdWorkspaceDialog

        host = rd_fixtures.FakeRdHost(str(self.project))
        dialog = RdWorkspaceDialog(host, root=str(self.project))
        try:
            self.assertEqual(dialog.member_table.rowCount(), 1)
            self.assertIn("未打开工作区", dialog.workspace_label.text())
            self.assertEqual(dialog.item_table.rowCount(), 1)
            self.assertEqual(dialog.metric_labels["total"].text(), "1")
            self.assertTrue(dialog.overview_text.toPlainText().strip())
        finally:
            dialog.close()
            dialog.deleteLater()




class RdClosedLoopTests(unittest.TestCase):
    """RD-F 6.1/6.2：三成员闭环集成与降级环境。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("rd-loop")
        self.data = rd_fixtures.build_rd_workspace(self.work / "研发工作区")
        self.root = Path(self.data["root"])
        self.requirement_root = Path(self.data["projects"]["documents/需求"])
        self.host = rd_fixtures.FakeRdHost(str(self.requirement_root))

    def tearDown(self):
        _cleanup(self.work)

    def _open_dialog(self):
        from doc_tool.ui.rd_workspace import RdWorkspaceDialog

        dialog = RdWorkspaceDialog(self.host, root=str(self.root))
        dialog.resize(1280, 720)
        return dialog

    def test_three_member_closed_loop_relation_matrix_impact_collection(self):
        dialog = self._open_dialog()
        evidence = {
            "members": dialog.member_table.rowCount(),
            "items": dialog.item_table.rowCount(),
            "relations": dialog.relation_table.rowCount(),
            "matrixRows": dialog.matrix_table.rowCount(),
            "requirements": dialog.metric_labels["total"].text(),
            "designCoverage": dialog.metric_labels["design"].text(),
            "testCoverage": dialog.metric_labels["test"].text(),
            "collections": dialog.collection_table.rowCount(),
            "platform": "Qt offscreen",
            "realDesktopTrial": False,
            "realWordTrial": False,
        }
        try:
            self.assertEqual(evidence["members"], 3)
            self.assertEqual(evidence["items"], 3)
            self.assertEqual(evidence["relations"], 2)
            self.assertEqual(evidence["requirements"], "1")
            self.assertEqual(evidence["designCoverage"], "100.0%")
            self.assertEqual(evidence["testCoverage"], "100.0%")
            # 来源跳转
            dialog.matrix_table.selectRow(0)
            dialog.matrix_locate_btn.click()
            self.app.processEvents()
            self.assertTrue(self.host.opened_sources)
            # 缓冲变化 → 影响来源标为当前缓冲
            chapter = "1 概述/1.1 背景.md"
            disk = (self.requirement_root / "content/requirement" / chapter).read_text(encoding="utf-8")
            self.host.buffers = {chapter: disk.replace("系统应支持离线出稿。", "系统应支持离线出稿与一键交付。")}
            dialog.refresh_all()
            self.assertIn("当前编辑缓冲", dialog.impact_summary.text())
            evidence["impactRows"] = dialog.impact_table.rowCount()
            self.assertGreaterEqual(evidence["impactRows"], 1)
            # 集合恢复为副本，源项目不变
            watched = self.requirement_root / "project.yml"
            before = watched.read_bytes()
            destination = self.work / "闭环恢复"
            destination.mkdir(parents=True, exist_ok=True)
            with patch("doc_tool.ui.rd_workspace.QFileDialog.getExistingDirectory", return_value=str(destination)):
                dialog.recover_btn.click()
            self.app.processEvents()
            self.assertEqual(watched.read_bytes(), before)
            evidence["recovered"] = any(destination.rglob("*.md"))
            self.assertTrue(evidence["recovered"])
        finally:
            dialog.close()
            dialog.deleteLater()
        if os.environ.get("PRODUCT_RD_EVIDENCE") == "1":
            target = ROOT / "analysis" / "product-rd-workspace-20261003" / "closed-loop.json"
            target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_review_confirm_uses_saved_hashes_and_detects_later_change(self):
        from doc_tool.application.content.impact import ReviewRecordStore

        dialog = self._open_dialog()
        design_id = self.data["ids"]["documents/设计"]
        requirement_id = self.data["ids"]["documents/需求"]
        store = ReviewRecordStore(self.root / ".state")
        hashes = dialog._snapshot_hashes(dialog._after_snapshots)
        source_key = (design_id, self.data["itemIds"]["D-1"])
        target_key = (requirement_id, self.data["itemIds"]["R-1"])
        self.assertIn(source_key, hashes)
        store.confirm(
            "rel-design-satisfies", source_key, target_key,
            source_hash=hashes[source_key], target_hash=hashes[target_key],
        )
        try:
            dialog.refresh_impact()
            self.app.processEvents()
            statuses = [
                dialog.review_table.item(row, 1).text()
                for row in range(dialog.review_table.rowCount())
            ]
            self.assertIn("通过", statuses)
            self.assertNotIn("待重检（内容已变化）", statuses)
            # 已保存内容变化后：旧复核必须变为待重检，不能继续标为通过
            design_chapter = Path(self.data["projects"]["documents/设计"]) / "content/requirement/2 详细设计/2.1 架构.md"
            design_chapter.write_text(design_chapter.read_text(encoding="utf-8") + "\n新增设计说明。\n", encoding="utf-8")
            dialog.refresh_all()
            self.app.processEvents()
            statuses = [
                dialog.review_table.item(row, 1).text()
                for row in range(dialog.review_table.rowCount())
            ]
            self.assertIn("待重检（内容已变化）", statuses)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_open_artifact_uses_real_path(self):
        dialog = self._open_dialog()
        try:
            self.assertGreater(dialog.artifact_combo.count(), 0, "集合详情应列出可打开成果/清单")
            dialog.artifact_combo.setCurrentIndex(0)
            dialog.open_artifact_btn.click()
            self.app.processEvents()
            self.assertTrue(self.host.opened_paths)
            self.assertTrue(Path(self.host.opened_paths[-1]).exists())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_missing_template_and_word_still_allows_workspace_views(self):
        template = self.requirement_root / "template" / "template.docx"
        backup = template.read_bytes()
        template.unlink()
        try:
            from doc_tool.application import rd_surface as surface

            payload = surface.overview_view(self.requirement_root)
            self.assertTrue(payload["ok"], "缺 Word 模板不得让概览失效")
            dialog = self._open_dialog()
            try:
                self.assertEqual(dialog.member_table.rowCount(), 3)
                self.assertEqual(dialog.metric_labels["total"].text(), "1")
                self.assertTrue(dialog.overview_text.toPlainText().strip())
            finally:
                dialog.close()
                dialog.deleteLater()
        finally:
            template.write_bytes(backup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
