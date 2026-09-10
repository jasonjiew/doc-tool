# -*- coding: utf-8 -*-
"""self_heal（冻结启动自愈）单元测试。

覆盖：ASCII 判定、日志写入、导入失败可见报错（退出码 2）、其它启动异常兜底，
以及「不再迁移到 %TEMP%」的回归断言。所有外部副作用（消息框、日志、文件
写入）均以 mock/tempdir 隔离。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)

from doc_tool.application import self_heal  # noqa: E402


class AsciiTests(unittest.TestCase):
    def test_ascii_paths(self):
        self.assertTrue(self_heal._is_ascii(r"C:\Temp\DocTool"))
        self.assertFalse(self_heal._is_ascii("C:\\Users\\张三\\AppData"))
        self.assertFalse(self_heal._is_ascii(None))


class CandidateBaseTests(unittest.TestCase):
    def test_prefers_ascii_temp(self):
        env = {"TEMP": r"C:\Temp", "PUBLIC": r"C:\Users\Public"}
        with mock.patch.dict(os.environ, env, clear=True):
            bases = self_heal._candidate_bases()
        self.assertEqual(bases[0], r"C:\Temp")
        self.assertIn(r"C:\Users\Public", bases)

    def test_non_ascii_temp_falls_back_to_public(self):
        env = {"TEMP": "C:\\Users\\张三\\Temp", "PUBLIC": r"C:\Users\Public"}
        with mock.patch.dict(os.environ, env, clear=True):
            bases = self_heal._candidate_bases()
        self.assertNotIn("C:\\Users\\张三\\Temp", bases)
        self.assertEqual(bases[0], r"C:\Users\Public")


class HandleBlockedImportTests(unittest.TestCase):
    def test_always_reports_and_returns_two(self):
        """不再迁移：任何导入失败都直接写日志 + 弹框，退出码 2。"""
        with mock.patch.object(
            self_heal, "_write_log", return_value=[r"C:\x\DocTool-startup.log"]
        ) as fake_log, mock.patch.object(self_heal, "_message_box") as fake_box:
            rc = self_heal.handle_blocked_import(ImportError("blocked"))
        self.assertEqual(rc, 2)
        self.assertTrue(fake_log.called)
        self.assertTrue(fake_box.called)
        box_text = fake_box.call_args[0][1]
        self.assertIn("blocked", box_text)

    def test_log_lines_contain_error_and_frozen_state(self):
        captured = {}

        def fake_write_log(log):
            captured["lines"] = list(log)
            return [r"C:\x\DocTool-startup.log"]

        with mock.patch.object(self_heal, "_write_log", side_effect=fake_write_log), mock.patch.object(
            self_heal, "_message_box"
        ):
            rc = self_heal.handle_blocked_import(ImportError("boom: _socket"))
        self.assertEqual(rc, 2)
        lines = "\n".join(captured["lines"])
        self.assertIn("import error: ImportError('boom: _socket')", lines)
        self.assertIn("DocTool 启动诊断", lines)

    def test_no_relocation_code_left(self):
        """1.4.4 回归：自愈模块不再包含复制到 %TEMP% 的迁移逻辑。"""
        with open(
            os.path.join(REPO_ROOT, "doc_tool", "application", "self_heal.py"),
            encoding="utf-8",
        ) as fh:
            src = fh.read()
        for marker in ("dt_run_", "_write_relaunch_script", "_spawn_via_explorer", "DOCTOOL_RELOCATED"):
            self.assertNotIn(marker, src, "self_heal 不应再引用迁移逻辑: {0}".format(marker))


class ReportStartupFailureTests(unittest.TestCase):
    def test_reports_and_returns_two(self):
        with mock.patch.object(
            self_heal, "_write_log", return_value=[r"C:\x\DocTool-startup.log"]
        ) as fake_log, mock.patch.object(self_heal, "_message_box") as fake_box:
            rc = self_heal.report_startup_failure(RuntimeError("boom"))
        self.assertEqual(rc, 2)
        self.assertTrue(fake_log.called)
        box_text = fake_box.call_args[0][1]
        self.assertIn("boom", box_text)


class EntryGuardTests(unittest.TestCase):
    """冻结入口守卫：1.4.2 期间曾因重写 app.py 丢失 __main__ 守卫导致 exe 静默退出。"""

    def test_app_py_invokes_main_under_main_guard(self):
        with open(os.path.join(REPO_ROOT, "doc_tool", "app.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('if __name__ == "__main__":', src)
        self.assertIn("sys.exit(main())", src)

    def test_frozen_branch_hooks_present(self):
        with open(os.path.join(REPO_ROOT, "doc_tool", "app.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("self_heal.handle_blocked_import", src)
        self.assertIn("self_heal.report_startup_failure", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
