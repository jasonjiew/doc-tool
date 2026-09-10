# -*- coding: utf-8 -*-
"""测试高频操作按钮重定位、自适应校验与文件锁探针功能。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Ensure QApplication exists for widget testing
_app = QApplication.instance() or QApplication([])

from doc_tool.application.project_service import ProjectSummary
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.ui.main_window import MainWindow, TASK_UI
from doc_tool.ui.project_bar import ProjectBar
from doc_tool.ui.workbench_state import ActionState, WorkbenchState


class TestActionPositioningAndLogic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="doc-test-action-pos-")
        self.work = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_project_bar_button_order_and_labels(self):
        bar = ProjectBar()
        self.assertEqual(bar._validate_btn.text(), "项目检查")
        self.assertEqual(bar._diag_btn.text(), "快速构建")
        self.assertEqual(bar._merge_btn.text(), "正式出稿")

        # 检查主操作角色
        self.assertEqual(bar._validate_btn.property("btnRole"), "secondary")
        self.assertEqual(bar._diag_btn.property("btnRole"), "secondary")
        self.assertEqual(bar._merge_btn.property("btnRole"), "primary")

        # 检查布局中的相对位置：项目检查在快速构建左侧，快速构建在正式出稿左侧
        main_layout = bar.layout().itemAt(0).layout()
        idx_validate = -1
        idx_diag = -1
        idx_merge = -1
        for i in range(main_layout.count()):
            w = main_layout.itemAt(i).widget()
            if w == bar._validate_btn:
                idx_validate = i
            elif w == bar._diag_btn:
                idx_diag = i
            elif w == bar._merge_btn:
                idx_merge = i

        self.assertTrue(idx_validate != -1 and idx_diag != -1 and idx_merge != -1)
        self.assertLess(idx_validate, idx_diag, "项目检查应排在快速构建之前")
        self.assertLess(idx_diag, idx_merge, "快速构建应排在正式出稿之前")

    def test_task_ui_and_task_labels(self):
        self.assertEqual(TASK_UI["validate"]["label"], "项目检查")
        self.assertEqual(TASK_UI["diag_build"]["label"], "快速构建")
        self.assertEqual(TASK_UI["merge"]["label"], "正式出稿")

        self.assertEqual(MainWindow._task_label("validate"), "项目检查")
        self.assertEqual(MainWindow._task_label("diag_build"), "快速构建")
        self.assertEqual(MainWindow._task_label("merge"), "正式出稿")

    def test_on_validate_with_fallback_existing_docx(self):
        """当当前版本产物不存在，但 output 目录下有历史产物时，自适应选用已有产物而不报错。"""
        window = MainWindow()
        manifest = ProjectManifest(
            documentNo="DOC-001",
            documentName="测试手册",
            documentVersion="2.0",
            documentType="requirement",
            sourceSha256="",
        )
        paths = ProjectPaths(self.work)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        # 创建历史 1.0 版产物（与 2.0 产物名不一致）
        hist_docx = paths.output_dir / "DOC-001 测试手册(1.0).docx"
        hist_docx.write_text("dummy", encoding="utf-8")

        summary = ProjectSummary(
            manifest=manifest,
            paths=paths,
            project_root=self.work,
            is_writable=True,
            source_exists=False,
            template_exists=False,
            content_exists=True,
            output_exists=True,
        )
        window._project_summary = summary

        started_specs = []
        window._start_task = lambda spec: started_specs.append(spec)
        with patch.object(window, "_show_error") as mock_err:
            window._on_validate()
            # 不应当弹“Word 产物不存在”错误框
            mock_err.assert_not_called()

        self.assertEqual(len(started_specs), 1)
        spec = started_specs[0]
        self.assertEqual(spec.name, "validate")
        # 验证使用了 output_override 传入 fallback 的已有产物
        self.assertEqual(spec.kwargs.get("output_override"), str(hist_docx))
        window.close()

    def test_on_validate_without_any_docx_runs_source_check(self):
        """当 output 目录下完全没有 docx 时，执行纯源码检查，不阻断用户。"""
        window = MainWindow()
        manifest = ProjectManifest(
            documentNo="DOC-001",
            documentName="测试手册",
            documentVersion="1.0",
            documentType="requirement",
            sourceSha256="",
        )
        paths = ProjectPaths(self.work)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        content_dir = self.work / "content" / "requirement"
        content_dir.mkdir(parents=True, exist_ok=True)

        summary = ProjectSummary(
            manifest=manifest,
            paths=paths,
            project_root=self.work,
            is_writable=True,
            source_exists=False,
            template_exists=False,
            content_exists=True,
            output_exists=True,
        )
        window._project_summary = summary

        started_specs = []
        window._start_task = lambda spec: started_specs.append(spec)
        with patch.object(window, "_show_error") as mock_err:
            window._on_validate()
            # 不应当弹“Word 产物不存在”错误框
            mock_err.assert_not_called()

        self.assertEqual(len(started_specs), 1)
        spec = started_specs[0]
        self.assertEqual(spec.name, "validate")
        # 验证不是直接调用的 validate_with_project（而是源码检查函数）
        from doc_tool.adapters.kernel import validate_with_project
        self.assertNotEqual(spec.target, validate_with_project)
        window.close()

    def test_run_source_content_check_execution(self):
        """测试 _run_source_content_check 内部执行与质量规则错误行格式化（防止 AttributeError）。"""
        window = MainWindow()
        manifest = ProjectManifest(
            documentNo="DOC-001",
            documentName="测试手册",
            documentVersion="1.0",
            documentType="requirement",
            sourceSha256="",
        )
        paths = ProjectPaths(self.work)
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        content_dir = self.work / "content" / "requirement"
        content_dir.mkdir(parents=True, exist_ok=True)
        (content_dir / "01_test.md").write_text("#1.1 错误标题\n正文", encoding="utf-8")

        summary = ProjectSummary(
            manifest=manifest,
            paths=paths,
            project_root=self.work,
            is_writable=True,
            source_exists=False,
            template_exists=False,
            content_exists=True,
            output_exists=False,
        )

        started_specs = []
        window._start_task = lambda spec: started_specs.append(spec)
        window._run_source_content_check(summary)

        self.assertEqual(len(started_specs), 1)
        spec = started_specs[0]
        res = spec.target(*spec.args)
        log_file = paths.logs_dir / "requirement-validation.md"
        self.assertTrue(log_file.exists())
        log_text = log_file.read_text(encoding="utf-8")
        self.assertIn("源码与结构检查报告", log_text)
        window.close()

    def test_check_output_file_locked_probe(self):
        """测试文件锁定探测功能。"""
        window = MainWindow()
        test_file = self.work / "locked_test.docx"
        test_file.write_text("hello", encoding="utf-8")

        # 未被锁定时返回 False
        self.assertFalse(window._check_output_file_locked_and_prompt(test_file))

        # 文件不存在时返回 False
        self.assertFalse(window._check_output_file_locked_and_prompt(self.work / "not_exist.docx"))
        window.close()


if __name__ == "__main__":
    unittest.main()
