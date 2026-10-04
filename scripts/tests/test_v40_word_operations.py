# -*- coding: utf-8 -*-
"""40-B：Word 各阶段有界执行、归属证据与停止预算。

覆盖三条真实契约（不依赖本机安装 Word）：

1. 阶段事实：启动/打开/处理/写成果/退出各自记录真实耗时与预算，超时阶段明确；
2. 归属证据：只有启动前后 PID 差集或 ActiveWindow 证明过的实例才可清理；
   无法证明归属时保留残留事实，绝不按进程名清理用户 Word；
3. 停止预算：超时任务在“总预算 + 停止预算”内返回，未确认终止时不假称已停止。
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.adapters import word_convert  # noqa: E402
from doc_tool.domain.word_operations import (  # noqa: E402
    OWNERSHIP_PID_DIFF,
    OWNERSHIP_UNKNOWN,
    STAGE_BUSY_LOCK,
    STAGE_CLEANUP,
    STAGE_OPEN,
    STAGE_PROCESS,
    STAGE_SAVE,
    STAGE_START,
    STAGE_TIMEOUT,
    WordBudgets,
    WordOperationReport,
    budgets_for_timeout,
    is_busy_lock_error,
    ownership_from_object,
    ownership_from_pid_diff,
    stop_and_cleanup,
    total_budget_seconds,
)


class BudgetTests(unittest.TestCase):
    def test_total_budget_matches_legacy_timeout(self):
        """既有单值超时换算后总预算一致：不给历史调用方偷偷加等待。"""
        budgets = budgets_for_timeout(300)
        self.assertAlmostEqual(total_budget_seconds(budgets), 300.0, places=6)
        self.assertEqual(budgets.cleanup, WordBudgets().cleanup)

    def test_stage_budget_mapping(self):
        budgets = WordBudgets(start=5, open=6, process=7, save=8, quit=9, cleanup=2)
        self.assertEqual(budgets.for_stage(STAGE_BUSY_LOCK), 5)
        self.assertEqual(budgets.for_stage(STAGE_START), 5)
        self.assertEqual(budgets.for_stage(STAGE_OPEN), 6)
        self.assertEqual(budgets.for_stage(STAGE_PROCESS), 7)
        self.assertEqual(budgets.for_stage(STAGE_SAVE), 8)
        self.assertEqual(budgets.for_stage(STAGE_CLEANUP), 2)


class StageFactTests(unittest.TestCase):
    def test_stage_records_real_elapsed_and_timeout(self):
        report = WordOperationReport(operation="word-convert")
        report.stage(STAGE_START, "启动", elapsed=1.5)
        report.stage(STAGE_OPEN, "打开")
        report.timed(STAGE_PROCESS, time.monotonic() - 0.01)
        self.assertEqual(report.currentStage, STAGE_PROCESS)
        start = report.stage_fact(STAGE_START)
        self.assertAlmostEqual(start.elapsedSeconds, 1.5, places=3)
        # 没有显式耗时的阶段不伪造耗时。
        self.assertEqual(report.stage_fact(STAGE_OPEN).elapsedSeconds, 0.0)

        report.note_timeout(STAGE_PROCESS, "超过处理预算")
        self.assertEqual(report.timeoutStage, STAGE_PROCESS)
        self.assertEqual(report.stage_fact(STAGE_PROCESS).outcome, STAGE_TIMEOUT)
        self.assertFalse(report.ok)

    def test_timeout_stage_created_when_never_recorded(self):
        """卡在取得 PID 之前：一个阶段都没记录也要能说清卡在哪。"""
        report = WordOperationReport(operation="word-convert")
        report.note_timeout(STAGE_START, "启动未返回")
        fact = report.stage_fact(STAGE_START)
        self.assertIsNotNone(fact)
        self.assertEqual(fact.outcome, STAGE_TIMEOUT)
        self.assertEqual(fact.budgetSeconds, report.budgets.start)

    def test_diagnostic_summary_has_no_business_body(self):
        report = WordOperationReport(
            operation="word-convert:docx_to_pdf",
            source=r"D:\proj\正文.docx", target=r"D:\out\正文.pdf",
        )
        report.stage(STAGE_OPEN, "已打开源文档", elapsed=0.4)
        report.note_cleanup("已终止 PID 4321")
        text = report.diagnostic_summary()
        self.assertIn("word-convert:docx_to_pdf", text)
        self.assertIn("打开文档", text)
        self.assertIn("已终止 PID 4321", text)
        self.assertNotIn("BusinessBodySecret", text)
        payload = report.to_dict()
        self.assertEqual(payload["stages"][0]["stage"], STAGE_OPEN)
        self.assertTrue(payload["ok"])

    def test_summary_line_marks_over_budget(self):
        report = WordOperationReport(operation="x")
        fact = report.stage(STAGE_SAVE, "写出 DOCX", elapsed=200.0)
        self.assertTrue(fact.overBudget)
        self.assertIn("超预算", fact.summary_line())


class OwnershipTests(unittest.TestCase):
    def test_pid_diff_is_provable(self):
        ownership = ownership_from_pid_diff(4321, [111, 222])
        self.assertTrue(ownership.provable)
        self.assertEqual(ownership.proof, OWNERSHIP_PID_DIFF)
        self.assertEqual(ownership.pidsBefore, [111, 222])

    def test_no_pid_is_unknown(self):
        ownership = ownership_from_pid_diff(None, [111])
        self.assertFalse(ownership.provable)
        self.assertEqual(ownership.proof, OWNERSHIP_UNKNOWN)

    def test_object_without_window_is_unknown(self):
        class _Word:
            ActiveWindow = None

        self.assertFalse(ownership_from_object(_Word()).provable)
        self.assertFalse(ownership_from_object(None).provable)

    def test_unprovable_ownership_never_kills(self):
        report = WordOperationReport(operation="word-convert")
        killed = []

        def _kill():
            killed.append(True)

        outcome = stop_and_cleanup(report, kill=_kill, budget_seconds=0.2)
        self.assertEqual(killed, [])
        self.assertTrue(outcome.residual)
        self.assertFalse(outcome.fullyStopped)
        self.assertTrue(report.residual)
        self.assertIn("无法证明", outcome.detail)

    def test_provable_ownership_kills_and_confirms(self):
        report = WordOperationReport(operation="word-convert")
        report.set_ownership(ownership_from_pid_diff(777, [1]))
        state = {"alive": True}
        killed = []

        def _kill():
            killed.append(True)
            state["alive"] = False

        outcome = stop_and_cleanup(
            report, kill=_kill, is_alive=lambda: state["alive"],
            budget_seconds=0.5, wait=lambda _s: None,
        )
        self.assertEqual(killed, [True])
        self.assertTrue(outcome.fullyStopped)
        self.assertIn("终止本次专用进程", report.cleanup)

    def test_unconfirmed_stop_is_residual_not_success(self):
        report = WordOperationReport(operation="word-convert")
        report.set_ownership(ownership_from_pid_diff(777, [1]))
        outcome = stop_and_cleanup(
            report, kill=lambda: None, is_alive=lambda: True,
            budget_seconds=0.05, wait=lambda seconds: time.sleep(seconds),
        )
        self.assertFalse(outcome.stopped)
        self.assertTrue(outcome.residual)
        self.assertTrue(report.residual)
        self.assertIn("未确认终止", report.residualDetail)

    def test_busy_lock_classification(self):
        self.assertTrue(is_busy_lock_error(RuntimeError("文件正由另一应用程序使用")))
        self.assertTrue(is_busy_lock_error(RuntimeError("The file is locked for editing")))
        self.assertFalse(is_busy_lock_error(RuntimeError("unrelated")))


class BoundedConvertTests(unittest.TestCase):
    """用桩替换会话体，验证监督者在真实预算内返回并登记事实。"""

    def setUp(self):
        self._original = word_convert._run_session
        self._tmp = Path(self._enter_tmp())
        self.source = self._tmp / "source.docx"
        self.source.write_bytes(b"PK\x03\x04stub")
        self.target = self._tmp / "out.pdf"

    def _enter_tmp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        return self._tmpdir.name

    def tearDown(self):
        word_convert._run_session = self._original

    def test_hung_process_stage_returns_within_stop_budget(self):
        release = threading.Event()
        stages = []

        def _hang(source, target, mode, handle, with_toc=False, page_range=None,
                  report=None, progress_cb=None):
            handle.begin(STAGE_START)
            if report is not None:
                report.stage(STAGE_START, "启动专用 Word 实例", elapsed=0.0)
            stages.append(STAGE_START)
            release.wait(30)

        word_convert._run_session = _hang
        report = WordOperationReport(
            operation="word-convert:docx_to_pdf",
            budgets=WordBudgets(start=1, open=1, process=1, save=1, quit=1, cleanup=2),
        )
        started = time.monotonic()
        outcome = word_convert.convert_document(
            self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
            timeout_seconds=1, report=report,
        )
        elapsed = time.monotonic() - started
        release.set()
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, word_convert.REASON_TIMEOUT)
        self.assertEqual(stages, [STAGE_START])
        # 总预算(1s) + 停止预算(2s) 是硬上限，实测必须落在这个量级内。
        self.assertLess(elapsed, 6.0)
        self.assertEqual(report.timeoutStage, STAGE_START)
        self.assertIn("启动 Word", report.timeoutDetail)
        # 桩没有真实 PID：归属不可证明，因此不清理、留残留事实。
        self.assertTrue(report.residual)
        self.assertIn("无法证明", report.diagnostic_summary())
        # 线程在停止预算内还没回收完：不能假称已经停止。
        self.assertIn("仍在回收中", report.residualDetail)
        payload = report.to_dict()
        self.assertEqual(payload["timeoutStage"], STAGE_START)
        self.assertFalse(payload["ownership"]["provable"])

    def test_normal_session_records_all_stages(self):
        def _ok(source, target, mode, handle, with_toc=False, page_range=None,
                report=None, progress_cb=None):
            handle.begin(STAGE_START)
            if report is not None:
                report.stage(STAGE_START, "start", elapsed=0.1)
                report.stage(STAGE_OPEN, "open", elapsed=0.2)
                report.stage(STAGE_SAVE, "save", elapsed=0.3)
                report.stage("quit", "quit", elapsed=0.05)
            handle.end()
            return word_convert._outcome(
                mode, source, target, True, word_convert.REASON_OK, "PDF 已生成"
            )

        word_convert._run_session = _ok
        report = WordOperationReport(operation="word-convert:docx_to_pdf")
        outcome = word_convert.convert_document(
            self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
            timeout_seconds=10, report=report,
        )
        self.assertTrue(outcome.ok)
        self.assertTrue(report.ok)
        names = [item.name for item in report.stages]
        self.assertEqual(names, [STAGE_START, STAGE_OPEN, STAGE_SAVE, "quit"])

    def test_failure_never_leaves_unknown_stage(self):
        def _boom(source, target, mode, handle, with_toc=False, page_range=None,
                  report=None, progress_cb=None):
            return word_convert._outcome(
                mode, source, target, False,
                word_convert.REASON_WORD_UNAVAILABLE, "未安装 pywin32",
            )

        word_convert._run_session = _boom
        report = WordOperationReport(operation="word-convert:docx_to_pdf")
        outcome = word_convert.convert_document(
            self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
            timeout_seconds=10, report=report,
        )
        self.assertFalse(outcome.ok)
        self.assertTrue(report.stages)
        self.assertFalse(report.ok)


class SimulatedStallTests(unittest.TestCase):
    """40-B 2.4：模拟启动前/打开/刷新/保存/退出卡住与占用。

    断言四件事：有界返回（不无限等待）、阶段归类正确、归属不明时**不清理任何
    进程**、原有来源文件与旧成果保持不被覆盖。
    """

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)
        self.source = self.tmp / "source.docx"
        self.source.write_bytes(b"PK\x03\x04original-source-bytes")
        self.target = self.tmp / "out.pdf"
        self._original = word_convert._run_session
        self.addCleanup(self._restore)

    def _restore(self):
        word_convert._run_session = self._original

    def _stall_at(self, stage: str):
        """桩：进入指定阶段后一直不返回（COM 调用不可中断的等效模拟）。"""
        import threading

        release = threading.Event()
        entered = []

        def _hang(source, target, mode, handle, with_toc=False, page_range=None,
                  report=None, progress_cb=None):
            handle.begin(stage)
            if report is not None:
                report.stage(stage, "stalled", elapsed=0.0)
            if progress_cb is not None:
                progress_cb(stage, "stalled")
            entered.append(stage)
            release.wait(30)

        return _hang, entered, release

    def test_every_stage_stalls_within_total_plus_stop_budget(self):
        budgets = WordBudgets(start=1, open=1, process=1, save=1, quit=1, cleanup=1)
        for stage in (STAGE_START, STAGE_OPEN, STAGE_PROCESS, STAGE_SAVE, "quit"):
            hang, entered, release = self._stall_at(stage)
            word_convert._run_session = hang
            report = WordOperationReport(
                operation="word-convert:docx_to_pdf", budgets=budgets,
            )
            started = time.monotonic()
            outcome = word_convert.convert_document(
                self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
                timeout_seconds=1, report=report,
            )
            elapsed = time.monotonic() - started
            release.set()
            self.assertFalse(outcome.ok, stage)
            self.assertEqual(outcome.reason, word_convert.REASON_TIMEOUT, stage)
            self.assertEqual(entered, [stage])
            self.assertEqual(report.timeoutStage, stage)
            # 总预算 1s + 停止预算 1s 是上限；实测留出宽松余量但必须有限。
            self.assertLess(elapsed, 20.0, "阶段 {0} 必须有界返回".format(stage))
            self.assertTrue(report.residual, "归属不明的卡住必须留残留事实")
            # 源文件与旧成果不被本次失败改动。
            self.assertEqual(self.source.read_bytes(), b"PK\x03\x04original-source-bytes")
            self.assertFalse(self.target.exists())

    def test_busy_lock_stage_is_recorded_when_open_is_blocked(self):
        """打开阶段遇到占用锁：阶段归类为打开，结果说明可读，不改源文件。"""
        def _busy(source, target, mode, handle, with_toc=False, page_range=None,
                  report=None, progress_cb=None):
            handle.begin(STAGE_OPEN)
            if report is not None:
                report.stage(STAGE_OPEN, "文件被占用", elapsed=0.1)
            return word_convert._outcome(
                mode, source, target, False, word_convert.REASON_CONVERT_FAILED,
                "文件正由另一应用程序使用，无法打开",
            )

        word_convert._run_session = _busy
        report = WordOperationReport(operation="word-convert:docx_to_pdf")
        outcome = word_convert.convert_document(
            self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
            timeout_seconds=10, report=report,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(report.currentStage, STAGE_OPEN)
        self.assertTrue(is_busy_lock_error(RuntimeError(outcome.detail)))
        self.assertIn("文件被占用", "\n".join(report.stage_lines()))

    def test_user_owned_word_is_never_cleaned(self):
        """归属不可证明时，清理入口一次都不能被调用（用户 Word 保持）。"""
        import threading

        killed = []
        release = threading.Event()

        def _hang(source, target, mode, handle, with_toc=False, page_range=None,
                  report=None, progress_cb=None):
            handle.begin(STAGE_START)
            release.wait(30)

        word_convert._run_session = _hang
        original_kill = word_convert._kill_process_tree
        word_convert._kill_process_tree = lambda pid: killed.append(pid)
        try:
            report = WordOperationReport(
                operation="word-convert:docx_to_pdf",
                budgets=WordBudgets(start=1, open=1, process=1, save=1, quit=1, cleanup=1),
            )
            outcome = word_convert.convert_document(
                self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
                timeout_seconds=1, report=report,
            )
        finally:
            release.set()
            word_convert._kill_process_tree = original_kill
        self.assertFalse(outcome.ok)
        self.assertEqual(killed, [], "没有归属证据时不得清理任何 Word 进程")
        self.assertTrue(report.residual)

    def test_progress_callback_receives_real_stages(self):
        seen = []

        def _ok(source, target, mode, handle, with_toc=False, page_range=None,
                report=None, progress_cb=None):
            for stage in (STAGE_START, STAGE_OPEN, STAGE_PROCESS, STAGE_SAVE, "quit"):
                handle.set_stage(stage)
                if report is not None:
                    report.stage(stage, "ok", elapsed=0.01)
                if progress_cb is not None:
                    progress_cb(stage, "ok")
            return word_convert._outcome(
                mode, source, target, True, word_convert.REASON_OK, "PDF 已生成"
            )

        word_convert._run_session = _ok
        report = WordOperationReport(operation="word-convert:docx_to_pdf")
        outcome = word_convert.convert_document(
            self.source, self.target, word_convert.MODE_DOCX_TO_PDF,
            timeout_seconds=10, report=report,
            progress_cb=lambda stage, detail: seen.append(stage),
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(seen, [STAGE_START, STAGE_OPEN, STAGE_PROCESS, STAGE_SAVE, "quit"])
        self.assertTrue(report.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)