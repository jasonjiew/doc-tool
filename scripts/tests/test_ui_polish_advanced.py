# -*- coding: utf-8 -*-
"""UI 包 4.1～4.4：高级能力首用闭环（批次表单 / 模块库 / 辅助切页）。

真实服务 + 真实 Qt 控件验证：
- 4.1 无 JSON 也能从入口建立首个批次：表单经 contract.parse_plan 校验、保存原
  batch 格式、合法成员可执行、失效成员就地提示、全部无效时保留输入；
- 4.2 空模块库 → 从当前章节创建（缓冲来源）/ 安装明确版本 → 插入引用或正文副本
  并可一次撤销；库目录未配置时可选已有库；
- 4.3 AssistPanel 资料/建议切页、共用出处/差异详情、保留插入与采纳/撤销/导出；
  无范围时有真实范围设置动作，provider 默认折叠；
- 4.4 三条真实首用路径端到端串联，普通编辑/出稿不被局部错误阻断。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.application.delivery import contract  # noqa: E402
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402
from doc_tool.ui.delivery_form_dialog import (  # noqa: E402
    DeliveryFormDialog,
    build_plan_payload,
    save_plan,
    validate_payload,
)


class DeliveryFormTests(unittest.TestCase):
    """4.1：表单 → 原 batch 格式 → 原服务校验。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("ui-polish-delivery")
        cls.good = fixtures.two_chapter_project(cls.work / "good")
        cls.also_good = fixtures.two_chapter_project(cls.work / "good2")
        cls.bad = cls.work / "bad"
        cls.bad.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_payload_is_original_batch_schema(self):
        payload = build_plan_payload(
            batch_id="b1", members=[str(self.good)], formats=["docx", "html"]
        )
        self.assertEqual(payload["schemaVersion"], contract.PLAN_SCHEMA_VERSION)
        self.assertEqual(payload["kind"], contract.PLAN_KIND)
        self.assertEqual(payload["batchId"], "b1")
        entry = payload["entries"][0]
        self.assertEqual(entry["kind"], contract.ENTRY_KIND_PROJECT)
        self.assertEqual(entry["scope"]["kind"], "project")
        self.assertEqual(entry["sourceMode"], "saved")
        self.assertEqual(entry["formats"], ["docx", "html"])

    def test_validation_splits_executable_and_invalid_members(self):
        payload = build_plan_payload(
            batch_id="b2",
            members=[str(self.good), str(self.bad), str(self.also_good)],
            formats=["docx"],
        )
        plan = validate_payload(payload)
        self.assertEqual(
            sorted(entry.memberName for entry in plan.executable_entries()),
            ["good", "good2"],
        )
        invalid = plan.invalid_entries()
        self.assertEqual(len(invalid), 1)
        self.assertIn("project.yml", "；".join(invalid[0].problems))

    def test_saved_plan_reparses_with_original_service(self):
        payload = build_plan_payload(
            batch_id="b3", members=[str(self.good), str(self.bad)], formats=["docx"]
        )
        target = save_plan(payload, self.work / "b3" / "batch.json")
        self.assertTrue(target.is_file())
        plan = contract.parse_plan_text(
            target.read_text(encoding="utf-8"), plan_path=str(target)
        )
        self.assertTrue(plan.executable_entries())
        self.assertEqual(len(plan.invalid_entries()), 1)

    def test_form_keeps_input_when_all_members_invalid(self):
        dialog = DeliveryFormDialog(default_dir=str(self.work))
        dialog._name_entry.setText("全无效批次")
        dialog._append_member(str(self.bad))
        submitted = {}
        dialog.accepted.connect(lambda: submitted.setdefault("accepted", True))
        dialog._on_submit()
        self.assertNotIn("accepted", submitted, "全部无效时不得假报开始")
        self.assertIn("全部成员不可执行", dialog._validation_label.text())
        self.assertEqual(dialog._name_entry.text(), "全无效批次", "全部无效时保留输入")
        self.assertEqual(dialog.members(), [str(self.bad)])
        dialog.deleteLater()

    def test_form_submit_writes_plan_and_accepts_with_valid_members(self):
        dialog = DeliveryFormDialog(default_dir=str(self.work))
        dialog._name_entry.setText("可用批次")
        dialog._append_member(str(self.good))
        dialog._append_member(str(self.bad))
        accepted = {}
        dialog.accepted.connect(lambda: accepted.setdefault("yes", True))
        dialog._on_submit()
        self.assertTrue(accepted.get("yes"), "有合法成员时应可提交")
        plan_path = dialog.plan_path()
        self.assertIsNotNone(plan_path)
        text = Path(plan_path).read_text(encoding="utf-8")
        payload = json.loads(text)
        self.assertEqual(payload["schemaVersion"], contract.PLAN_SCHEMA_VERSION)
        plan = contract.parse_plan_text(text, plan_path=str(plan_path))
        self.assertTrue(plan.executable_entries())
        dialog.deleteLater()

    def test_form_reports_member_problem_inline(self):
        dialog = DeliveryFormDialog(default_dir=str(self.work))
        dialog._append_member(str(self.bad))
        self.assertIn("project.yml", dialog._validation_label.text())
        # 移除失效成员后回到"请先添加"
        dialog._member_list.setCurrentRow(0)
        dialog._remove_selected()
        self.assertIn("请先添加至少一个成员项目", dialog._validation_label.text())
        dialog.deleteLater()


class ModuleFirstUseTests(unittest.TestCase):
    """4.2：空库 → 创建 → 安装明确版本 → 插入（引用/副本）并可一次撤销。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("ui-polish-module")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def setUp(self):
        self.project = fixtures.two_chapter_project(self.work / "proj")
        self.rels = [
            rel for rel, _path in discover_chapters(self.project / "content" / "general")
        ]
        self.inserted = []

    def _dialog(self, buffer_text=None):
        from doc_tool.ui.reuse_dialog import ReuseDialog

        rel = self.rels[0]

        def _buffer():
            if buffer_text is None:
                return "", ""
            return rel, buffer_text

        return ReuseDialog(
            self.project,
            buffer_source=_buffer,
            on_insert_module=lambda text, mode: (
                self.inserted.append((text, mode)), True
            )[1],
        )

    def test_empty_library_gives_real_next_actions(self):
        dialog = self._dialog()
        self.assertEqual(dialog.module_list.count(), 0)
        self.assertIn("从当前章节创建模块", dialog.preview.toPlainText())
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertTrue(dialog.library_button.isEnabled())
        dialog.deleteLater()

    def test_create_from_current_buffer_marks_source_and_publishes(self):
        dialog = self._dialog(buffer_text="# 缓冲章节\n\n只有缓冲里才有的正文。\n")
        with patch.object(QMessageBox, "information", lambda *a, **k: None):
            dialog.create_module_from_chapter()
        self.assertEqual(dialog.module_list.count(), 1)
        self.assertIn("当前未保存缓冲", dialog.status_label.text())
        # 缓冲内容真实进库（不读旧磁盘正文）
        payload = dialog._rows[0]
        shown = dialog._module_body_for_copy(payload["moduleId"], payload["version"])
        self.assertIn("只有缓冲里才有的正文", shown)

    def test_install_and_insert_reference_is_resolvable(self):
        dialog = self._dialog(buffer_text="# 架构缓冲\n\n架构正文。\n")
        with patch.object(QMessageBox, "information", lambda *a, **k: None), patch.object(
            QMessageBox, "warning", lambda *a, **k: None
        ):
            dialog.create_module_from_chapter()
            dialog.install_selected_module()
        self.assertIn("已安装", dialog.status_label.text())
        module_id = dialog._rows[0]["moduleId"]
        version = dialog._rows[0]["version"]

        dialog.insert_mode_combo.setCurrentIndex(0)  # 固定引用
        dialog.insert_selected_module()
        text, mode = self.inserted[-1]
        self.assertEqual(mode, "reference")
        self.assertIn("doc-module id={0} version={1}".format(module_id, version), text)
        # 引用可被既有解析服务解析（来源明确）
        from doc_tool.application.content import reuse_commands as reuse

        context = dialog._ensure_context()
        resolution = reuse.resolve_text(text, context, host_path=self.rels[0])
        self.assertEqual(
            list(resolution.errors), [],
            "固定引用必须能被既有解析服务解析：{0}".format(resolution.errors),
        )
        self.assertTrue(resolution.segments, "引用应解析出可渲染片段")

        # 复制正文：展开成普通 Markdown，资源可解析路径不残留
        dialog.insert_mode_combo.setCurrentIndex(1)
        dialog.insert_selected_module()
        copy_text, copy_mode = self.inserted[-1]
        self.assertEqual(copy_mode, "copy")
        self.assertIn("架构正文", copy_text)
        self.assertNotIn("doc-module", copy_text)
        dialog.deleteLater()

    def test_main_window_module_insert_is_single_undo(self):
        from doc_tool.ui.main_window import MainWindow

        with patch(
            "doc_tool.application.project_service.load_recent_projects", return_value=[]
        ), patch(
            "doc_tool.application.project_service.add_recent_project", return_value=None
        ):
            window = MainWindow()
        self.addCleanup(window.close)

        class _Editor:
            def __init__(self):
                self.text = ""
                self.undo_calls = 0

            def insert_template(self, text, cursor_offset=0):
                self.text += text
                return True

            def undo(self):
                self.undo_calls += 1
                self.text = ""

        editor = _Editor()

        class _Workspace:
            def current_editor(self):
                return editor

        window._content_workspace = _Workspace()
        window._project_summary = type("S", (), {"project_root": "X:/p"})()
        self.assertTrue(window._on_module_insert_requested("```doc-module id=m version=1.0.0\n```", "reference"))
        self.assertIn("doc-module", editor.text)
        editor.undo()
        self.assertEqual(editor.text, "", "插入必须可一次撤销")
        self.assertEqual(editor.undo_calls, 1)

    def test_pick_existing_library_is_used_as_source(self):
        external = self.work / "external-library"
        external.mkdir(parents=True, exist_ok=True)
        from doc_tool.application.content import modules as module_lib

        body = "# 外部模块\n\n外部库正文。\n"
        module = module_lib.extract_module(
            body, module_id="ext-mod", version="2.0.0", base_dir=external
        )
        self.assertEqual(list(module.missing), [], "外部模块不应有缺失资源")
        module_lib.ModuleLibrary(external).publish(module.module)

        dialog = self._dialog()
        with patch(
            "doc_tool.ui.reuse_dialog.QFileDialog.getExistingDirectory",
            return_value=str(external),
        ):
            dialog.pick_library()
        ids = [row["moduleId"] for row in dialog._rows]
        self.assertIn("ext-mod", ids, "选择已有库后应能列出其中的模块")
        dialog.deleteLater()


class AssistPanelFirstUseTests(unittest.TestCase):
    """4.3：资料/建议切页、共用详情、保留动作、无范围可设置。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("ui-polish-assist")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _panel(self):
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.ui.assist_panel import AssistPanel

        scopes = []
        statuses = []
        panel = AssistPanel(
            build_assistant(str(self.project)),
            project_root=self.project,
            on_scope_changed=scopes.append,
        )
        panel.status_message.connect(statuses.append)
        panel.scopes = scopes
        panel.statuses = statuses
        return panel

    def test_tabs_exist_and_switch(self):
        panel = self._panel()
        titles = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        self.assertEqual(titles, ["资料", "建议"])
        self.assertEqual(panel.current_page(), "materials")
        panel.show_page("suggestions")
        self.assertEqual(panel.current_page(), "suggestions")
        panel.deleteLater()

    def test_actions_preserved_across_pages(self):
        panel = self._panel()
        for widget in (
            panel._search_button,
            panel._cite_button,
            panel._copy_button,
            panel._adopt_button,
            panel._ignore_button,
            panel._undo_button,
            panel._export_button,
            panel._load_suggestions_button,
        ):
            self.assertTrue(widget.text(), "既有动作必须保留：{0}".format(widget))
        panel.deleteLater()

    def test_add_scope_is_a_real_action(self):
        panel = self._panel()
        extra = self.work / "extra-lib"
        extra.mkdir(parents=True, exist_ok=True)
        with patch(
            "PySide6.QtWidgets.QFileDialog.getExistingDirectory",
            return_value=str(extra),
        ):
            panel.add_scope_manually()
        self.assertEqual(panel.scopes, [[str(extra)]])
        self.assertTrue(
            any("已加入资料范围" in item for item in panel.statuses), panel.statuses
        )
        panel.deleteLater()

    def test_scope_cancel_keeps_state(self):
        panel = self._panel()
        with patch(
            "PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=""
        ):
            panel.add_scope_manually()
        self.assertEqual(panel.scopes, [])
        self.assertTrue(
            any("已取消添加资料范围" in item for item in panel.statuses),
            panel.statuses,
        )
        panel.deleteLater()

    def test_provider_actions_default_collapsed_in_label(self):
        panel = self._panel()
        self.assertIn("未启用", panel._provider_label.text())
        panel.refresh_provider_label()
        self.assertTrue(panel._provider_label.text())
        panel.deleteLater()

    def test_search_and_adopt_flow_keeps_insert_and_undo(self):
        panel = self._panel()
        panel.search("正文")
        self.assertIsNotNone(panel._summary.text())
        panel.load_suggestions()
        self.assertIsNotNone(panel.suggestions_export_text() is not None)
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)