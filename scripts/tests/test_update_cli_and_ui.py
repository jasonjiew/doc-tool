# -*- coding: utf-8 -*-
"""回归测试：CLI upgrade 命令输出契约与 GUI 升级前置拦截保护。

覆盖 REQ-06。
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve()
DOC_TOOL_ROOT = HERE.parents[2]
if str(DOC_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(DOC_TOOL_ROOT))

from doc_tool.application.cli_commands import upgrade_command
from doc_tool.application.content.unsaved import UnsavedChoice
from doc_tool.application.updater import UpdateCheckResult
from doc_tool.cli import main as cli_main
from doc_tool.domain.update import ReleaseManifest


class TestUpdateCliAndUi(unittest.TestCase):
    """测试 CLI 纯净性、源码自覆盖拦截与 GUI 守卫门禁。"""

    def test_cli_upgrade_check_json_output(self):
        """验证 CLI upgrade --check --output json 结构化输出契约。"""
        fake_manifest = ReleaseManifest(
            tag_name="v3.1.0",
            version="3.1.0",
            installer_url="https://example.com/Setup.exe",
            installer_sha256="abc123",
        )
        fake_check_res = UpdateCheckResult(
            has_update=True,
            current_version="3.0.1",
            latest_version="3.1.0",
            manifest=fake_manifest,
            install_mode="source",
            is_skipped=False,
        )

        with patch("doc_tool.application.updater.check_for_updates", return_value=fake_check_res):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exit_code = cli_main(["upgrade", "--check", "--output", "json"])

            self.assertEqual(exit_code, 0)
            output = buf.getvalue().strip()
            data = json.loads(output)
            self.assertEqual(data["command"], "upgrade")
            self.assertTrue(data["success"])
            self.assertTrue(data["hasUpdate"])
            self.assertEqual(data["latestVersion"], "3.1.0")
            self.assertEqual(data["actionTaken"], "check")
            self.assertEqual(data["manifest"]["installer_sha256"], "abc123")

    def test_cli_capabilities_json_pure_output(self):
        """验证其他命令（如 capabilities）在 JSON 模式下 stdout 绝对纯净，无升级横幅干扰。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = cli_main(["capabilities", "--format", "json"])

        self.assertEqual(exit_code, 0)
        output = buf.getvalue().strip()
        data = json.loads(output)
        self.assertEqual(data["command"], "capabilities")
        self.assertEqual(data["tool"]["name"], "doc-tool")

    def test_cli_source_mode_refusal_to_overwrite(self):
        """验证源码运行态触发升级时拒绝下载自覆盖并提示 git pull。"""
        fake_manifest = ReleaseManifest(
            tag_name="v3.1.0",
            version="3.1.0",
            installer_url="https://example.com/Setup.exe",
        )
        fake_check_res = UpdateCheckResult(
            has_update=True,
            current_version="3.0.1",
            latest_version="3.1.0",
            manifest=fake_manifest,
            install_mode="source",
        )

        with patch("doc_tool.application.updater.check_for_updates", return_value=fake_check_res):
            res = upgrade_command(check_only=False, auto_confirm=True)
            self.assertFalse(res["success"])
            self.assertEqual(res["actionTaken"], "refused_source_mode")
            self.assertIn("git pull", res["error"])

    def test_gui_unsaved_buffer_cancel_gate(self):
        """验证 GUI 存在未保存章节时，用户在弹窗中选择取消会中止升级且不退出的保护。"""
        from doc_tool.ui.main_window import MainWindow

        mock_window = MagicMock(spec=MainWindow)
        mock_manifest = ReleaseManifest(version="3.1.0")

        # 模拟 _confirm_close_with_unsaved 返回 False（用户选择取消）
        mock_window._confirm_close_with_unsaved.return_value = False

        res = MainWindow._perform_upgrade(mock_window, mock_manifest)
        self.assertFalse(res)
        mock_window._confirm_close_with_unsaved.assert_called_once()
        mock_window.close.assert_not_called()

    def test_gui_word_busy_gate(self):
        """验证 Word 处于忙碌状态时升级被安全阻断。"""
        from doc_tool.ui.main_window import MainWindow
        from doc_tool.application.delivery.word_busy import BusyState

        mock_window = MagicMock(spec=MainWindow)
        mock_window._confirm_close_with_unsaved.return_value = True
        mock_manifest = ReleaseManifest(version="3.1.0")

        busy_state = BusyState(busy=True, owner="export_task", pid=1234)

        with patch("doc_tool.application.delivery.word_busy.status", return_value=busy_state):
            with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_box:
                res = MainWindow._perform_upgrade(mock_window, mock_manifest)
                self.assertFalse(res)
                mock_box.assert_called_once()
                self.assertIn("Word 当前正在执行任务", mock_box.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
