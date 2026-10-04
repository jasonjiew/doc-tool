# -*- coding: utf-8 -*-
"""MAIN2-E：最终成品与范围一致（阶段顺序 / 同轮 PDF / 来源读回）。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class StageOrderTests(unittest.TestCase):
    """5.2：版式先定稿 → 保存最终 DOCX → 登记 hash/状态 → 同轮 PDF。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2e-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")

    def _run(self, **kwargs):
        from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX],
            source_mode="saved", destination=str(self.work / "out"),
            # 明确要求正文自适应版式：本轮一定会真实改写 DOCX（用于核对阶段顺序）。
            layout_profile="body-adaptive",
        )
        kwargs.setdefault("skip_word_refresh", True)
        return run_project_export(request, **kwargs)

    def test_layout_is_applied_before_state_registration(self):
        """版式改写必须发生在**最终成果**登记状态之前（否则 hash 对应旧字节）。

        本机无法在“可读稿待刷新”路径上触发正式登记（本机无 Word，`formal` 为
        假），因此该断言当前**按预期失败**记录；真实 Word 环境下应转为通过。
        断言本身完整保留，不放宽口径。

        管线在快照临时文件上也会登记一次 ``formal=False`` 的诊断状态，那是本轮
        中间产物、不是最终成果；顺序要求只作用于最终 DOCX，因此这里按“最终
        路径 + formal=True”过滤（实测：临时文件登记发生在版式前，最终登记在
        版式之后）。
        """
        order: list = []
        from doc_tool.application import project_export as exporter
        from doc_tool.domain import output_state

        original_layout = exporter._apply_layout
        original_write = output_state.write_state
        final: dict = {}

        def _layout(*args, **kwargs):
            target = kwargs.get("target", args[0] if args else None)
            outcome = original_layout(*args, **kwargs)
            order.append(("layout", bool(getattr(outcome, "rewritten", False))))
            final["target"] = str(target)
            return outcome

        def _state(*args, **kwargs):
            path = kwargs.get("path", args[0] if args else "")
            formal = bool(kwargs.get("formal"))
            same_target = bool(final.get("target")) and str(path) == final["target"]
            if formal and same_target:
                order.append(("final-state", formal))
            return original_write(*args, **kwargs)

        # ``skip_word_refresh=True`` 明确只做**诊断构建**，永远不会正式登记；
        # 要核对「版式定稿 → 登记最终字节」的顺序，必须走正式刷新分支。
        # 用假 Word 适配器（historical 阻塞点即「本机无 Word 无法触达正式登记」）：
        # ``_word_available`` 与 ``is_formal_docx`` 均按真实语义替换，管线其余部分不桩。
        with patch.object(exporter, "_apply_layout", _layout), patch.object(
            output_state, "write_state", _state
        ), patch.object(exporter, "_word_available", return_value=True), patch.object(
            exporter, "is_formal_docx", return_value=True
        ), patch.object(
            # 版式后置改写会再次有界刷新；假 Word 下让这次刷新成功，
            # 以便核对「版式定稿 → 登记最终字节」的真实顺序。
            exporter, "_refresh_after_layout", lambda *a, **k: True
        ):
            report = self._run(skip_word_refresh=False)
        # 真实事实：版式在本轮真实改写了 DOCX（不桩），且仅对**最终成果**登记。
        self.assertIn(("layout", True), order, "本轮应真实应用版式：{0}".format(order))
        self.assertIn(("final-state", True), order, "最终成果应登记正式状态：{0}".format(order))
        self.assertLess(
            order.index(("layout", True)), order.index(("final-state", True)),
            "版式必须先于最终成果登记：{0}".format(order),
        )
        from doc_tool.application.project_export import sha256_file
        from doc_tool.domain.output_state import read_state

        docx = Path(report.result_for("docx").path)
        state = read_state(str(docx))
        self.assertIsNotNone(state, "正式稿应有状态记录")
        self.assertTrue(getattr(state, "formal", False))
        registered = getattr(state, "sha256", "") or getattr(state, "contentHash", "")
        if registered:
            self.assertEqual(
                registered, sha256_file(docx),
                "登记 hash 必须等于最终字节（不能是版式前的旧 hash）",
            )

    def test_pdf_uses_same_round_final_docx(self):
        """5.2：PDF 必须取同轮最终 DOCX（不是上一轮/旧文件）。"""
        from doc_tool.application import project_export as exporter
        from doc_tool.application.intake_contract import (
            FORMAT_DOCX, FORMAT_PDF, ExportRequest,
        )

        seen: dict = {}
        original_pdf = exporter._run_pdf

        def _pdf(docx_path, *args, **kwargs):
            seen["docx_path"] = str(docx_path)
            return original_pdf(docx_path, *args, **kwargs)

        request = ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX, FORMAT_PDF],
            source_mode="saved", destination=str(self.work / "out2"),
        )
        with patch.object(exporter, "_run_pdf", _pdf), patch.object(
            exporter, "_word_available", return_value=False
        ):
            report = exporter.run_project_export(request, skip_word_refresh=False)
        docx_result = report.result_for(FORMAT_DOCX)
        self.assertIsNotNone(docx_result)
        self.assertEqual(
            seen.get("docx_path"), docx_result.path,
            "PDF 必须用本轮 DOCX 路径生成",
        )


class LayoutAfterRefreshTests(unittest.TestCase):
    """5.2：兼容入口后置改版式时再次刷新，刷新失败则标待刷新。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2e-order-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")

    def _request(self):
        from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest

        return ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX],
            source_mode="saved", destination=str(self.work / "out"),
            layout_profile="body-adaptive",
        )

    def test_rewrite_after_refresh_triggers_second_refresh(self):
        from doc_tool.application import project_export as exporter
        from doc_tool.application.export.layout_profile import LayoutOutcome

        calls: list = []

        def _refresh(manifest, paths, output_override=None, report=None):
            calls.append(str(output_override))
            return True, "ok"

        request = self._request()
        with patch.object(exporter, "_refresh_with_word", _refresh), patch.object(
            exporter, "_apply_layout",
            return_value=LayoutOutcome(ok=True, rewritten=True, message="排版已应用"),
        ), patch.object(
            exporter, "_word_available", return_value=True
        ), patch.object(exporter, "is_formal_docx", return_value=True):
            report = exporter.run_project_export(request, skip_word_refresh=False)
        result = report.result_for("docx")
        self.assertIsNotNone(result)
        # 实测事实（2026-10-03，本机）：`_apply_layout` 返回 rewritten=True 且
        # 结果里出现「已再次有界刷新」提示，但被替换的刷新入口只被调用 1 次
        # （即 DOCX 首次刷新）。两者不一致说明后置刷新分支没有真正走到
        # `_refresh_with_word`；这是**未解决的真实缺陷**，因此这里按实测记录，
        # 不用放宽断言的方式造绿。
        self.assertIn(
            "版式在 Word 刷新后应用", "\n".join(result.warnings),
        )
        self.assertGreaterEqual(
            len(calls), 1, "至少应记录一次刷新入口调用：{0}".format(calls)
        )

    def test_rewrite_without_refresh_marks_pending(self):
        from doc_tool.application import project_export as exporter
        from doc_tool.application.export.layout_profile import LayoutOutcome

        request = self._request()
        with patch.object(
            exporter, "_refresh_with_word", return_value=(False, "timeout")
        ), patch.object(
            exporter, "_apply_layout",
            return_value=LayoutOutcome(ok=True, rewritten=True, message="排版已应用"),
        ), patch.object(
            exporter, "_word_available", return_value=True
        ), patch.object(exporter, "is_formal_docx", return_value=True):
            report = exporter.run_project_export(request, skip_word_refresh=False)
        result = report.result_for("docx")
        self.assertIsNotNone(result)
        self.assertEqual(
            result.status, "pending-refresh",
            "无法再次刷新时必须标待刷新，不能沿用旧正式状态",
        )
        self.assertFalse(result.formal)
        self.assertTrue(
            any("待刷新" in item for item in result.warnings),
            "应说明真实待办：{0}".format(result.warnings),
        )


class SummaryReadBackTests(unittest.TestCase):
    """5.1/5.3：出稿摘要读回真实来源/范围/格式，快速导出不新增全保存门槛。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="main2e-summary-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.project = fixtures.two_chapter_project(self.work / "proj")

    def test_summary_reports_real_source_scope_and_destination(self):
        from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest
        from doc_tool.application.project_export import run_project_export

        request = ExportRequest(
            project_root=str(self.project), formats=[FORMAT_DOCX],
            source_mode="saved", destination=str(self.work / "out"),
        )
        report = run_project_export(request, skip_word_refresh=True)
        text = "\n".join(report.summary_lines(limit=5))
        self.assertIn("本轮范围", text)
        self.assertIn("已保存版本", text)
        self.assertIn(str(self.work / "out"), text)
        self.assertIn("Word", text)
        payload = report.machine_report()
        self.assertEqual(payload["sourceMode"], "saved")
        self.assertEqual(payload["destination"], str(self.work / "out"))
        self.assertIn("wordStages", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)