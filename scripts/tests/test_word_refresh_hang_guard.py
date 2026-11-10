# -*- coding: utf-8 -*-
"""Word 刷新“卡住”防护回归：忙锁快速失败、取消可终止、阶段预算与错误码。

覆盖用户报障“导出 Word 卡在 Word 刷新”的四条可验证路径：

1. 目标文档被 Word 占用（``~$`` 忙锁）时立即失败，不再启动 Word 干等超时；
2. Word 自动化前关闭链接更新等弹窗开关，避免 ``Visible=False`` 下的模态阻塞；
3. 刷新期间取消可终止本次专用 Word，并在约 1～2 秒内返回，而不是等满预算；
4. 取消映射 ``E5003``、忙锁映射 ``E3004``，不误报成“Word 不可用”。
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for path in (str(REPO_ROOT), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)


class RefreshGuardTests(unittest.TestCase):
    """忙锁、只读与 Word 弹窗开关。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="word-hang-guard-"))
        self.target = self.root / "out.docx"
        self.target.write_bytes(b"PK\x03\x04demo")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_busy_lock_is_detected_with_actionable_message(self):
        import refresh_fields

        lock = self.root / ("~$" + self.target.name)
        lock.write_text("owner", encoding="utf-8")
        problem = refresh_fields._output_write_problem(str(self.target))
        self.assertIsNotNone(problem)
        self.assertIn("忙锁", problem)
        self.assertIn("~$", problem)

    def test_readonly_output_is_detected(self):
        import refresh_fields

        os.chmod(self.target, stat.S_IREAD)
        try:
            problem = refresh_fields._output_write_problem(str(self.target))
        finally:
            os.chmod(self.target, stat.S_IWRITE | stat.S_IREAD)
        self.assertIsNotNone(problem)
        self.assertIn("不可写", problem)

    def test_word_application_disables_link_prompts(self):
        import refresh_fields

        class FakeOptions:
            UpdateLinksAtOpen = True
            ConfirmConversions = True

        class FakeWord:
            Visible = True
            DisplayAlerts = 3
            ScreenUpdating = True
            EnableEvents = True
            AutomationSecurity = 1
            Options = FakeOptions()

        word = FakeWord()
        refresh_fields._configure_word_application(word)
        self.assertFalse(word.Visible)
        self.assertEqual(word.DisplayAlerts, 0)
        self.assertFalse(word.ScreenUpdating)
        self.assertFalse(word.EnableEvents)
        self.assertFalse(word.Options.UpdateLinksAtOpen)
        self.assertFalse(word.Options.ConfirmConversions)

    def test_busy_lock_com_error_classified_as_locked(self):
        import refresh_fields

        self.assertEqual(
            refresh_fields._classify_failure(RuntimeError("文件正由另一应用程序使用")),
            refresh_fields.REASON_LOCKED,
        )


class SuperviseCancelTests(unittest.TestCase):
    """取消在冻结线程模式与独立进程模式下都能及时返回。"""

    def setUp(self):
        from doc_tool.domain.cancellation import CancellationToken
        import refresh_fields

        self.rf = refresh_fields
        self.token = CancellationToken()
        self.root = Path(tempfile.mkdtemp(prefix="word-hang-cancel-"))
        self.target = self.root / "out.docx"
        self.target.write_bytes(b"PK\x03\x04demo")
        self.rf.LAST_REPORT.clear()

    def tearDown(self):
        self.rf.LAST_REPORT.clear()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_supervise_short_circuits_on_busy_lock(self):
        lock = self.root / ("~$" + self.target.name)
        lock.write_text("owner", encoding="utf-8")
        with patch.object(self.rf, "refresh_worker") as worker:
            ok, reason = self.rf.supervise(output_path=str(self.target), timeout=5)
        self.assertFalse(ok)
        self.assertEqual(reason, self.rf.REASON_LOCKED)
        worker.assert_not_called()
        self.assertEqual(self.rf.LAST_REPORT.get("currentStage"), "open")

    def test_thread_mode_cancel_returns_quickly(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            self.rf, "refresh_worker", side_effect=lambda **_kwargs: time.sleep(3)
        ), patch.object(
            self.rf, "_get_winword_pids", return_value=set()
        ), patch.object(
            self.rf, "_kill_process_tree", return_value=None
        ):
            timer = threading.Timer(0.2, self.token.request_cancel)
            timer.start()
            started = time.monotonic()
            ok, reason = self.rf.supervise(
                output_path=str(self.target), timeout=30, cancel_token=self.token
            )
            elapsed = time.monotonic() - started
            timer.cancel()

        self.assertFalse(ok)
        self.assertEqual(reason, self.rf.REASON_CANCELLED)
        self.assertLess(elapsed, 4.0, "取消不能等满刷新预算：{0:.1f}s".format(elapsed))
        stages = self.rf.LAST_REPORT.get("stages") or []
        self.assertTrue(
            any(item.get("outcome") == "cancelled" for item in stages),
            self.rf.LAST_REPORT,
        )

    def test_process_mode_cancel_kills_dedicated_worker(self):
        class FakeProcess:
            pid = 4321

            def __init__(self):
                self.alive = True
                self.returncode = None
                self.stderr = io.BytesIO(b"")

            def poll(self):
                return None if self.alive else (self.returncode or 1)

            def wait(self, timeout=None):
                if self.alive:
                    raise subprocess.TimeoutExpired("refresh_fields", timeout or 0)
                return self.returncode or 0

        fake = FakeProcess()
        killed = []

        def _kill(pid):
            killed.append(pid)
            fake.alive = False
            fake.returncode = 1

        with patch.object(self.rf.subprocess, "Popen", return_value=fake), patch.object(
            sys, "executable", "python.exe"
        ), patch.object(sys, "frozen", False, create=True), patch.object(
            self.rf, "_kill_process_tree", side_effect=_kill
        ):
            timer = threading.Timer(0.2, self.token.request_cancel)
            timer.start()
            ok, reason = self.rf.supervise(
                output_path=str(self.target), timeout=30, cancel_token=self.token
            )
            timer.cancel()

        self.assertFalse(ok)
        self.assertEqual(reason, self.rf.REASON_CANCELLED)
        self.assertEqual(killed, [4321], "取消必须结束本次专用 worker 进程树")


class PipelineRefreshGuardTests(unittest.TestCase):
    """管线层的错误码与取消语义。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="word-hang-pipeline-")
        self.project_root = self._tmp
        from test_project_build import _make_manifest, _setup_project

        _setup_project(self.project_root)
        self._make_manifest = _make_manifest

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _manifest_paths(self):
        manifest = self._make_manifest(self.project_root)
        return manifest, manifest.resolve_paths(self.project_root)

    def test_locked_reason_maps_to_E3004(self):
        from doc_tool.adapters import kernel
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline

        manifest, paths = self._manifest_paths()
        fake_report = word_check.WordAvailability(available=True)
        with patch.object(
            word_check, "check_word_available", return_value=fake_report
        ), patch.object(
            kernel, "refresh_with_project", return_value=(False, "locked")
        ), patch.object(
            kernel, "validate_with_project", return_value=True
        ):
            result = run_pipeline(manifest, paths, skip_word_refresh=False)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E3004")
        failed = [event for event in result.events if event.error_code == "E3004"]
        self.assertTrue(failed, [(event.stage, event.status) for event in result.events])
        self.assertIn("占用", failed[0].detail or "")

    def test_kernel_passes_cancel_token_to_supervise(self):
        import refresh_fields
        from doc_tool.adapters import kernel
        from doc_tool.domain.cancellation import CancellationToken

        manifest, paths = self._manifest_paths()
        token = CancellationToken()
        with patch.object(
            refresh_fields, "supervise", return_value=(True, "ok")
        ) as supervise, patch.object(kernel, "ensure_kernel_importable"):
            ok, reason = kernel.refresh_with_project(
                manifest, paths, cancel_token=token
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertIs(supervise.call_args.kwargs.get("cancel_token"), token)

    def test_cancel_during_word_refresh_returns_cancelled_and_cleans_temp(self):
        from doc_tool.adapters import kernel
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.cancellation import CancellationToken

        manifest, paths = self._manifest_paths()
        token = CancellationToken()
        fake_report = word_check.WordAvailability(available=True)

        def refresh(*_args, **_kwargs):
            token.request_cancel()
            return (False, "cancelled")

        with patch.object(
            word_check, "check_word_available", return_value=fake_report
        ), patch.object(
            kernel, "refresh_with_project", side_effect=refresh
        ), patch.object(
            kernel, "validate_with_project", return_value=True
        ):
            result = run_pipeline(
                manifest, paths, skip_word_refresh=False, cancel_token=token
            )

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E5003")
        self.assertTrue(
            any(event.status == "cancelled" for event in result.events),
            [(event.stage, event.status) for event in result.events],
        )
        self.assertEqual(list(paths.output_dir.glob(".tmp-*.docx")), [])
        # 取消不应产生“待刷新”副本或覆盖既有正式输出。
        self.assertFalse((paths.output_dir / "待刷新").exists())


if __name__ == "__main__":
    unittest.main()
