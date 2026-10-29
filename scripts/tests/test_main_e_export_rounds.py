# -*- coding: utf-8 -*-
"""MAIN-E 5.3/5.4：同轮多格式同源、目标占用换副本、单格式失败保留其余。"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts"),
                  str(REPO_ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_project_build as T  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    SOURCE_MODE_SAVED,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
    ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402

NL = chr(10)


class ExportRoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-e-export-"))
        self.project = Path(T._setup_project(str(self.tmp / "项目")))
        T._make_manifest(str(self.project)).save(self.project)
        self.sources = {
            path.relative_to(self.project): path.read_text(encoding="utf-8")
            for path in (self.project / "content").rglob("*.md")
        }
        self.destination = self.tmp / "导出"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _export(self, destination=None, formats=(FORMAT_DOCX, FORMAT_HTML)):
        return run_project_export(
            ExportRequest(
                project_root=str(self.project),
                formats=list(formats),
                source_mode=SOURCE_MODE_SAVED,
                destination=str(destination or self.destination),
            ),
            skip_word_refresh=True,
        )

    def test_multi_format_shares_one_capture_and_keeps_sources(self):
        report = self._export()
        self.assertTrue(report.captureId)
        paths = {}
        for result in report.results:
            # 无 Word 刷新时 DOCX 是「可读待刷新」；HTML 直接可用。两者都必须落到真实文件。
            if result.format == FORMAT_DOCX:
                self.assertIn(
                    result.status, (STATUS_READY, STATUS_PENDING_REFRESH),
                    (result.format, result.message),
                )
            else:
                self.assertEqual(result.status, STATUS_READY, (result.format, result.message))
            paths[result.format] = Path(result.path)
        self.assertTrue(paths[FORMAT_DOCX].is_file())
        self.assertTrue(paths[FORMAT_HTML].is_file())
        # 同一轮捕获：两个格式来自同一 captureId 与同一份快照
        self.assertTrue(report.snapshotWorkDir)
        self.assertEqual(report.sourceMode, SOURCE_MODE_SAVED)
        # 源 Markdown 未被出稿改动
        for rel, text in self.sources.items():
            self.assertEqual((self.project / rel).read_text(encoding="utf-8"), text)

    def test_occupied_target_gets_a_fresh_copy_path(self):
        first = self._export()
        first_docx = next(
            Path(item.path) for item in first.results if item.format == FORMAT_DOCX
        )
        second = self._export()
        second_docx = next(
            Path(item.path) for item in second.results if item.format == FORMAT_DOCX
        )
        self.assertTrue(first_docx.is_file(), "上一轮成果必须保留")
        self.assertNotEqual(first_docx, second_docx)
        self.assertTrue(second_docx.is_file())

    def test_single_format_failure_keeps_other_results(self):
        from unittest.mock import patch

        from doc_tool.application import project_export as module

        original = module._run_html

        def _boom(*_args, **_kwargs):
            raise OSError("模拟 HTML 写入失败")

        with patch.object(module, "_run_html", side_effect=_boom):
            report = run_project_export(
                ExportRequest(
                    project_root=str(self.project),
                    formats=[FORMAT_HTML, FORMAT_DOCX],
                    source_mode=SOURCE_MODE_SAVED,
                    destination=str(self.destination),
                ),
                skip_word_refresh=True,
            )
        statuses = {item.format: item.status for item in report.results}
        self.assertIn(statuses[FORMAT_DOCX], (STATUS_READY, STATUS_PENDING_REFRESH))
        self.assertNotIn(statuses[FORMAT_HTML], (STATUS_READY, STATUS_PENDING_REFRESH))
        docx = next(item for item in report.results if item.format == FORMAT_DOCX)
        self.assertTrue(Path(docx.path).is_file())
        self.assertTrue(original is not None)

    def test_unwritable_destination_falls_back_or_reports(self):
        from doc_tool.application.intake_contract import (
            SCOPE_PROJECT,
            ExportScope,
            resolve_export_directory,
        )

        blocked = self.tmp / "blocked"
        blocked.write_text("不是目录", encoding="utf-8")
        destination, note = resolve_export_directory(
            blocked, [self.project / "output"]
        )
        self.assertNotEqual(Path(destination), blocked)
        self.assertTrue(Path(destination).is_dir())
        self.assertTrue(note)
        self.assertEqual(ExportScope().kind, SCOPE_PROJECT)


    def test_diagnostics_persistence_and_desensitization(self):
        """Task 3.1-3.4: 导出生成 diagnostics.json 与同源 Markdown，且白名单脱敏。"""
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX,
            SCOPE_PROJECT,
            SOURCE_MODE_SAVED,
            ExportRequest,
            ExportScope,
        )
        from doc_tool.application.project_export import run_project_export
        from doc_tool.domain.export_diagnostics import ExportDiagnostics

        request = ExportRequest(
            project_root=str(self.project),
            formats=[FORMAT_DOCX],
            scope=ExportScope(kind=SCOPE_PROJECT),
            source_mode=SOURCE_MODE_SAVED,
            destination=str(self.project / "output"),
        )
        report = run_project_export(request, skip_word_refresh=True)
        self.assertTrue(report.executionId.startswith("exec-"))
        self.assertTrue(report.diagnostics)
        self.assertTrue(Path(report.diagnosticsPath).is_file())
        self.assertTrue(Path(report.diagnosticsMdPath).is_file())

        md_content = Path(report.diagnosticsMdPath).read_text(encoding="utf-8")
        self.assertIn("# 导出诊断报告", md_content)
        self.assertIn(report.executionId, md_content)
        # 脱敏验证：不能包含用户绝对主目录
        self.assertNotIn("Users\\", md_content)

    def test_old_index_compatibility_without_diagnostics(self):
        """Task 3.5: 旧版本 export-result.json 缺少 diagnostics 字段时兼容读取，不报错不伪造。"""
        import json
        from doc_tool.application.project_export import read_export_index
        from doc_tool.ui.export_rounds import load_round_from_index

        index_file = self.project / "output" / "export-result.json"
        index_file.parent.mkdir(parents=True, exist_ok=True)
        old_data = {
            "schemaVersion": 1,
            "roundId": "20261028-120000",
            "captureId": "cap-20261028-old",
            "createdAt": "2026-10-28T12:00:00Z",
            "projectRoot": str(self.project),
            "destination": str(self.project / "output"),
            "results": [
                {
                    "format": "docx",
                    "status": "ready",
                    "path": str(self.project / "output" / "old.docx"),
                    "usable": True,
                }
            ],
        }
        index_file.write_text(json.dumps(old_data), encoding="utf-8")

        read_back = read_export_index(index_file)
        self.assertIsNotNone(read_back)
        self.assertEqual(read_back.roundId, "20261028-120000")
        self.assertEqual(read_back.executionId, "")
        self.assertIsNone(read_back.diagnostics)

        round_view = load_round_from_index(index_file)
        self.assertIsNotNone(round_view)
        self.assertEqual(round_view.round_id, "20261028-120000")
        self.assertIn("未附带详细诊断数据", round_view.diagnostics_markdown)

    def test_diagnostics_unwritable_fallback_to_memory(self):
        """Task 3.5: 当诊断无法持久化时，回退到内存并允许复制，saved 标 False。"""
        from doc_tool.domain.export_diagnostics import ExportDiagnostics
        from unittest.mock import patch

        diag = ExportDiagnostics(
            roundId="R-MEM",
            captureId="cap-mem",
            message="内存诊断测试",
            stages=[{"stage": "preprocess", "outcome": "failed", "detail": "假错误"}],
            failedStage="preprocess",
            errorCode="ERR_TEST",
        )
        with patch("pathlib.Path.mkdir", side_effect=OSError("模拟只读目录无法创建")):
            saved_ok = diag.save(self.tmp / "nonexistent" / "dir")
        self.assertFalse(saved_ok)
        self.assertFalse(diag.saved)
        md = diag.to_markdown()
        self.assertIn("未持久保存（内存可复制）", md)
        self.assertIn("ERR_TEST", md)

    def test_results_view_primary_action_and_copy_diagnostics(self):
        """Task 5.1 & 5.2: 依据事实派生单一主要操作，并支持复制诊断。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX,
            FORMAT_PDF,
            STATUS_FAILED,
            STATUS_PENDING_REFRESH,
            STATUS_READY,
        )
        from doc_tool.ui.export_results_view import ExportResultsView
        from doc_tool.ui.export_rounds import ExportRoundView, RoundFormatView

        app = QApplication.instance() or QApplication([])
        located = []
        view = ExportResultsView(on_locate_source=lambda p, l: located.append((p, l)))

        # 1. 有可用 Word 产物：主要操作为「打开 Word」
        dummy_docx = self.project / "output" / "test.docx"
        dummy_docx.write_text("word", encoding="utf-8")
        round1 = ExportRoundView(
            round_id="R1",
            project_root=str(self.project),
            formats=[
                RoundFormatView(format=FORMAT_DOCX, status=STATUS_READY, path=str(dummy_docx), usable=True)
            ],
        )
        view.render([round1], "R1")
        self.assertFalse(view._primary_btn.isHidden())
        self.assertEqual(view._primary_btn.text(), "打开 Word")

        # 2. Word 待刷新：主要操作为「打开 Word (待刷新)」
        round2 = ExportRoundView(
            round_id="R2",
            project_root=str(self.project),
            formats=[
                RoundFormatView(format=FORMAT_DOCX, status=STATUS_PENDING_REFRESH, path=str(dummy_docx), usable=True)
            ],
        )
        view.render([round2], "R2")
        self.assertEqual(view._primary_btn.text(), "打开 Word (待刷新)")

        # 3. 失败且有确切源定位：主要操作为「定位问题」
        round3 = ExportRoundView(
            round_id="R3",
            project_root=str(self.project),
            failed_stage="preprocess",
            locations=[{"path": "ch1.md", "line": 42}],
            diagnostics={"message": "图片缺失", "locations": [{"path": "ch1.md", "line": 42}]},
            formats=[RoundFormatView(format=FORMAT_DOCX, status=STATUS_FAILED, usable=False)],
        )
        view.render([round3], "R3")
        self.assertEqual(view._primary_btn.text(), "定位问题")
        view._primary_btn.click()
        self.assertEqual(located, [("ch1.md", 42)])

        # 4. 复制诊断到剪贴板
        view._copy_diag_btn.click()
        clip_text = app.clipboard().text()
        self.assertIn("图片缺失", clip_text)

    def test_pipeline_failure_with_trailing_cleanup_and_readable_draft_branches(self):
        """Task 11.1: 覆盖失败后还有清理事件、以及仍保留可读稿的分支，显示实际失败阶段。"""
        from unittest.mock import patch
        from doc_tool.application.pipeline import PipelineResult, StageEvent
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, STATUS_FAILED, STATUS_PENDING_REFRESH,
        )
        from doc_tool.ui.export_rounds import round_view_from_report

        # 分支 1：构建前校验失败，且随后伴随 cleanup 事件
        fake_fail_events = [
            StageEvent(stage="build", status="succeeded", detail="构建完成"),
            StageEvent(
                stage="validate_pre", status="failed", error_code="E2001",
                detail="表格语法错误", metrics={"locations": [{"relPath": "01-a.md", "line": 15}]}
            ),
            StageEvent(stage="cleanup", status="succeeded", detail="清理临时资源"),
        ]
        pipe_fail = PipelineResult(
            success=False, events=fake_fail_events, output_path=None,
            pending_output_path=None, error_code="E2001"
        )

        with patch("doc_tool.application.pipeline.run_pipeline", return_value=pipe_fail):
            report = self._export(formats=[FORMAT_DOCX])

        docx_res = report.result_for(FORMAT_DOCX)
        self.assertEqual(docx_res.status, STATUS_FAILED)
        self.assertEqual(docx_res.failed_stage, "validate_pre", "不能只取最后的 cleanup 事件作为失败阶段")
        self.assertEqual(docx_res.error_code, "E2001")
        self.assertEqual(report.diagnostics["failedStage"], "validate_pre")
        self.assertEqual(report.diagnostics["errorCode"], "E2001")

        round_view = round_view_from_report(report)
        self.assertEqual(round_view.failed_stage, "validate_pre")
        self.assertEqual(round_view.error_code, "E2001")
        self.assertIsNotNone(round_view.primary_location)
        self.assertIn("validate_pre", round_view.diagnostics_markdown)

        # 分支 2：Word 刷新失败，但仍保留可读稿待刷新产物
        dummy_draft = self.tmp / "draft.docx"
        dummy_draft.write_text("dummy-content", encoding="utf-8")
        fake_refresh_fail_events = [
            StageEvent(stage="build", status="succeeded", detail="构建完成"),
            StageEvent(stage="word_refresh", status="failed", error_code="E4001", detail="Word 刷新超时"),
        ]
        pipe_refresh_fail = PipelineResult(
            success=False, events=fake_refresh_fail_events,
            output_path=str(dummy_draft), pending_output_path=str(dummy_draft),
            error_code="E4001"
        )

        with patch("doc_tool.application.pipeline.run_pipeline", return_value=pipe_refresh_fail):
            report2 = self._export(formats=[FORMAT_DOCX])

        docx_res2 = report2.result_for(FORMAT_DOCX)
        self.assertTrue(docx_res2.usable, "可读稿产物必须保留且可打开")
        self.assertEqual(docx_res2.status, STATUS_PENDING_REFRESH)
        self.assertEqual(docx_res2.failed_stage, "word_refresh", "不能因 usable=True 丢弃真实失败阶段")
        self.assertEqual(docx_res2.error_code, "E4001")
        self.assertEqual(report2.diagnostics["failedStage"], "word_refresh")

        round_view2 = round_view_from_report(report2)
        self.assertTrue(round_view2.has_usable_docx)
        self.assertTrue(round_view2.has_pending_refresh)
        self.assertEqual(round_view2.failed_stage, "word_refresh")
        self.assertIn("word_refresh", round_view2.diagnostics_markdown)

    def test_results_view_more_menu_actions_and_evidence_open(self):
        """Task 11.2 & 11.3: 更多菜单收纳其余动作与打开本次记录，不重复平铺。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, STATUS_FAILED, STATUS_READY,
        )
        from doc_tool.ui.export_results_view import ExportResultsView
        from doc_tool.ui.export_rounds import ExportRoundView, RoundFormatView

        app = QApplication.instance() or QApplication([])
        opened_records = []
        view = ExportResultsView(on_open_format=lambda fmt, path: opened_records.append((fmt, path)))

        dummy_md = self.project / "output" / "diagnostics" / "exec-test" / "diagnostics.md"
        dummy_md.parent.mkdir(parents=True, exist_ok=True)
        dummy_md.write_text("# 诊断记录", encoding="utf-8")

        round_obj = ExportRoundView(
            round_id="R-TEST",
            capture_id="C-TEST",
            project_root=str(self.project),
            diagnostics_md_path=str(dummy_md),
            formats=[RoundFormatView(format=FORMAT_DOCX, status=STATUS_FAILED, usable=False)],
        )
        view.render([round_obj], "R-TEST")

        # 主要动作应为重试本次内容
        self.assertEqual(view._primary_btn.text(), "重试本次内容")
        # 次级完整工具箱收起至更多，不平铺重复
        self.assertFalse(view._retry_btn.isVisible())
        self.assertFalse(view._regenerate_btn.isVisible())
        self.assertFalse(view._destination_btn.isVisible())
        self.assertFalse(view._copy_diag_btn.isVisible())

        # 更多菜单中不包含主要动作「重试本次内容」，但包含「打开本次记录」
        menu_actions = {a.text(): a for a in view._more_menu.actions()}
        self.assertNotIn("重试本次内容", menu_actions)
        self.assertIn("打开本次记录", menu_actions)
        self.assertIn("按当前内容生成", menu_actions)

        # 触发打开本次记录
        menu_actions["打开本次记录"].trigger()
        self.assertEqual(opened_records, [("markdown", str(dummy_md))])

        # 记录不存在时安全提示不崩溃
        dummy_md.unlink()
        view._open_saved_record()
        self.assertIn("未保存或文件不存在", view._warning.text())

if __name__ == "__main__":
    unittest.main()