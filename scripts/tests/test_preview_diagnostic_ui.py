# -*- coding: utf-8 -*-
"""高保真诊断弹窗的渲染与按钮可见性（离屏 Qt）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:  # 无 PySide6 的环境跳过（CI 之外的纯后端环境）
    from PySide6.QtWidgets import QApplication
except Exception:  # noqa: BLE001
    QApplication = None


@unittest.skipIf(QApplication is None, "当前环境没有 PySide6")
class DiagnosticDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _report(self, *, compat=False, can_install=True):
        from doc_tool.application.preview_diagnostic import DiagnosticReport

        return DiagnosticReport(
            frozen=False,
            summary="缺少 QtWebEngine 组件",
            checks=[("模块 QtWebEngineWidgets", "不可用（ImportError）")],
            actions=["点击「一键安装」补装完整 PySide6"],
            can_install=can_install,
            install_command="python -m pip install PySide6==6.8.3",
            compat_mode=compat,
        )

    def test_dialog_shows_summary_and_checks(self) -> None:
        from doc_tool.ui.fidelity_diagnostic_dialog import FidelityDiagnosticDialog

        dialog = FidelityDiagnosticDialog(report=self._report())
        self.assertIn("缺少 QtWebEngine 组件", dialog._summary.text())
        self.assertIn("模块 QtWebEngineWidgets", dialog._detail.toPlainText())
        self.assertIn("PySide6==6.8.3", dialog._detail.toPlainText())

    def test_install_button_only_when_source_mode(self) -> None:
        from doc_tool.ui.fidelity_diagnostic_dialog import FidelityDiagnosticDialog

        dialog = FidelityDiagnosticDialog(report=self._report(can_install=True))
        self.assertFalse(dialog._btn_install.isHidden())

        frozen = FidelityDiagnosticDialog(report=self._report(can_install=False))
        self.assertTrue(frozen._btn_install.isHidden())

    def test_compat_button_hidden_when_already_enabled(self) -> None:
        from doc_tool.ui.fidelity_diagnostic_dialog import FidelityDiagnosticDialog

        dialog = FidelityDiagnosticDialog(report=self._report(compat=True))
        self.assertTrue(dialog._btn_compat.isHidden())

    def test_copy_report_puts_text_on_clipboard(self) -> None:
        from PySide6.QtWidgets import QApplication as _QApplication

        from doc_tool.ui.fidelity_diagnostic_dialog import FidelityDiagnosticDialog

        dialog = FidelityDiagnosticDialog(report=self._report())
        dialog._copy_report()
        clipboard = _QApplication.clipboard()
        self.assertIn("高保真预览诊断", clipboard.text())

    def test_restart_failure_is_reported_instead_of_quitting(self) -> None:
        """``QProcess.startDetached`` 在 PySide6 返回 ``(bool, pid)``。

        失败结果是 ``(False, -1)``，非空元组恒为真；原实现直接 ``if not
        started`` 会把失败当成成功，照样退出应用。
        """
        from unittest.mock import patch as _patch

        from doc_tool.ui import fidelity_diagnostic_dialog as fdd

        class FakeProcess:
            @staticmethod
            def startDetached(*_args, **_kwargs):
                return (False, -1)

        quit_calls = []

        class FakeApplication:
            @staticmethod
            def quit() -> None:  # noqa: D401 - 记录调用
                quit_calls.append(True)

        dialog = fdd.FidelityDiagnosticDialog(report=self._report())
        with _patch.object(fdd, "QProcess", FakeProcess), _patch.object(
            fdd, "QApplication", FakeApplication
        ):
            dialog._restart_app()

        self.assertEqual(quit_calls, [])
        self.assertIn("自动重启失败", dialog._status.text())

    def test_restart_success_quits_and_requests_restart(self) -> None:
        from unittest.mock import patch as _patch

        from doc_tool.ui import fidelity_diagnostic_dialog as fdd

        class FakeProcess:
            @staticmethod
            def startDetached(*_args, **_kwargs):
                return (True, 4242)

        quit_calls = []

        class FakeApplication:
            @staticmethod
            def quit() -> None:
                quit_calls.append(True)

        dialog = fdd.FidelityDiagnosticDialog(report=self._report())
        restarted = []
        dialog.restartRequested.connect(lambda: restarted.append(True))
        with _patch.object(fdd, "QProcess", FakeProcess), _patch.object(
            fdd, "QApplication", FakeApplication
        ):
            dialog._restart_app()

        self.assertEqual(quit_calls, [True])
        self.assertEqual(restarted, [True])


if __name__ == "__main__":
    unittest.main()
