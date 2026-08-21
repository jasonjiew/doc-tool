# -*- coding: utf-8 -*-
"""self_heal（冻结启动自愈）单元测试。

覆盖：ASCII 判定、重拉脚本生成（纯 ASCII）、explorer 中继启动、
防死循环可见报错、其它启动异常兜底。所有外部副作用（消息框、日志、
子进程、文件写入）均以 mock/tempdir 隔离。
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


class RelaunchScriptTests(unittest.TestCase):
    def test_cmd_bootstrap_is_ascii_and_delegates_to_ps1(self):
        """cmd 按 ANSI 代码页解析：引导脚本必须纯 ASCII，只负责跳转到 .ps1。"""
        raw = self_heal._RELAUNCH_CMD_BODY.encode("ascii")  # 不是 ASCII 会直接抛异常
        self.assertIn(b"dt_relaunch.ps1", raw)
        self.assertIn(b"powershell", raw)

    def test_ps1_body_quotes_src_single_quoted(self):
        """源路径内嵌进 .ps1 必须用单引号并转义，避免 PowerShell 展开 $ 与 `。"""
        with tempfile.TemporaryDirectory() as tmp:
            fake_dir = os.path.join(tmp, "含中文目录 DocTool$var")
            with mock.patch.object(self_heal, "_candidate_bases", return_value=[tmp]), mock.patch.object(
                self_heal, "_app_dir", return_value=fake_dir
            ):
                cmd_path = self_heal._write_relaunch_script([])
            ps1 = os.path.join(tmp, self_heal._RELAUNCH_PS1)
            self.assertTrue(os.path.isfile(cmd_path))
            self.assertTrue(os.path.isfile(ps1))
            with open(cmd_path, "rb") as fh:
                fh.read().decode("ascii")
            with open(ps1, "rb") as fh:
                content = fh.read()
            self.assertTrue(content.startswith(b"\xef\xbb\xbf"), "ps1 必须带 UTF-8 BOM")
            text = content.decode("utf-8-sig")
            self.assertIn("$src = '{0}'".format(fake_dir), text)
            self.assertIn("DOCTOOL_RELOCATED", text)
            self.assertIn("dt_run_", text)

    def test_write_relaunch_script_all_bases_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "no", "such", "base")
            with mock.patch.object(self_heal, "_candidate_bases", return_value=[bad]):
                with mock.patch.object(os, "makedirs", side_effect=OSError("denied")):
                    self.assertIsNone(self_heal._write_relaunch_script([]))


class SpawnExplorerTests(unittest.TestCase):
    def test_spawn_uses_explorer(self):
        env = {k: v for k, v in os.environ.items() if k != self_heal.RELOCATED_ENV}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            self_heal.subprocess, "Popen"
        ) as fake_popen:
            ok = self_heal._spawn_via_explorer(r"C:\Temp\dt_relaunch.cmd", [])
        self.assertTrue(ok)
        args, _kwargs = fake_popen.call_args
        self.assertEqual(args[0][0].lower(), "explorer.exe")
        self.assertEqual(args[0][1], r"C:\Temp\dt_relaunch.cmd")


class HandleBlockedImportTests(unittest.TestCase):
    def test_relocated_marker_short_circuits(self):
        with mock.patch.dict(os.environ, {self_heal.RELOCATED_ENV: "1"}), mock.patch.object(
            self_heal, "_write_log", return_value=[r"C:\x\DocTool-startup.log"]
        ) as fake_log, mock.patch.object(self_heal, "_message_box") as fake_box, mock.patch.object(
            self_heal, "_write_relaunch_script"
        ) as fake_gen:
            rc = self_heal.handle_blocked_import(ImportError("blocked"))
        self.assertEqual(rc, 2)
        fake_gen.assert_not_called()
        self.assertTrue(fake_log.called)
        self.assertTrue(fake_box.called)

    def test_success_path_spawns_explorer_and_returns_zero(self):
        env = {k: v for k, v in os.environ.items() if k != self_heal.RELOCATED_ENV}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            self_heal, "_write_relaunch_script", return_value=r"C:\Temp\dt_relaunch.cmd"
        ), mock.patch.object(
            self_heal, "_spawn_via_explorer", return_value=True
        ) as fake_spawn, mock.patch.object(self_heal, "_write_log"):
            rc = self_heal.handle_blocked_import(ImportError("blocked"))
        self.assertEqual(rc, 0)
        self.assertTrue(fake_spawn.called)

    def test_relay_failure_reports(self):
        env = {k: v for k, v in os.environ.items() if k != self_heal.RELOCATED_ENV}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            self_heal, "_write_relaunch_script", return_value=None
        ), mock.patch.object(
            self_heal, "_write_log", return_value=[r"C:\x\DocTool-startup.log"]
        ), mock.patch.object(self_heal, "_message_box") as fake_box:
            rc = self_heal.handle_blocked_import(ImportError("blocked"))
        self.assertEqual(rc, 2)
        self.assertTrue(fake_box.called)


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
        src = open(os.path.join(REPO_ROOT, "doc_tool", "app.py"), encoding="utf-8").read()
        self.assertIn('if __name__ == "__main__":', src)
        self.assertIn("sys.exit(main())", src)

    def test_frozen_branch_hooks_present(self):
        src = open(os.path.join(REPO_ROOT, "doc_tool", "app.py"), encoding="utf-8").read()
        self.assertIn("self_heal.handle_blocked_import", src)
        self.assertIn("self_heal.report_startup_failure", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
