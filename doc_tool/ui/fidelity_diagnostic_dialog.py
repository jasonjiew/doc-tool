# -*- coding: utf-8 -*-
"""高保真预览诊断对话框。

用户在高保真不可用时点「诊断/修复」进入：先看结论与逐项检查，再按运行形态
选择处置——源码态可一键补装 PySide6，打包态只能修分发包或启用兼容模式。

安装与重启都走 ``QProcess``：不阻塞界面，也不需要把 pip 逻辑塞进业务线程。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QProcess, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from doc_tool.application.preview_diagnostic import (
    DiagnosticReport,
    collect_diagnostic,
    resource_directory,
    set_compat_mode,
)


class FidelityDiagnosticDialog(QDialog):
    """展示高保真预览失败原因，并提供补装 / 兼容模式 / 重启入口。"""

    restartRequested = Signal()

    def __init__(
        self,
        parent=None,
        *,
        error_text: str = "",
        traceback_text: str = "",
        report: DiagnosticReport | None = None,
    ) -> None:
        super().__init__(parent)
        self._error_text = str(error_text or "")
        self._traceback_text = str(traceback_text or "")
        self._report = report or collect_diagnostic(
            self._error_text, self._traceback_text
        )
        self._install_process: QProcess | None = None
        self._installing = False

        self.setWindowTitle("高保真预览诊断")
        self.resize(760, 560)
        self._build_ui()
        self._render()

    # --- 界面 ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = QFont(self._summary.font())
        font.setBold(True)
        self._summary.setFont(font)
        layout.addWidget(self._summary)

        self._detail = QPlainTextEdit(self)
        self._detail.setReadOnly(True)
        monospace = QFont("Consolas")
        monospace.setStyleHint(QFont.StyleHint.Monospace)
        self._detail.setFont(monospace)
        layout.addWidget(self._detail, 1)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._btn_copy = QPushButton("复制诊断信息", self)
        self._btn_copy.clicked.connect(self._copy_report)
        buttons.addWidget(self._btn_copy)

        self._btn_recheck = QPushButton("重新检测", self)
        self._btn_recheck.clicked.connect(self._recheck)
        buttons.addWidget(self._btn_recheck)

        self._btn_open_dir = QPushButton("打开资源目录", self)
        self._btn_open_dir.clicked.connect(self._open_resource_dir)
        buttons.addWidget(self._btn_open_dir)

        buttons.addStretch(1)

        self._btn_install = QPushButton("一键安装 PySide6", self)
        self._btn_install.clicked.connect(self._install_pyside)
        buttons.addWidget(self._btn_install)

        self._btn_compat = QPushButton("启用兼容模式并重启", self)
        self._btn_compat.clicked.connect(self._enable_compat_and_restart)
        buttons.addWidget(self._btn_compat)

        self._btn_close = QPushButton("关闭", self)
        self._btn_close.clicked.connect(self.reject)
        buttons.addWidget(self._btn_close)
        layout.addLayout(buttons)

    def _render(self) -> None:
        report = self._report
        self._summary.setText(report.summary)
        self._detail.setPlainText(report.to_text())
        self._btn_install.setVisible(bool(report.can_install))
        self._btn_compat.setVisible(not report.compat_mode)
        self._btn_open_dir.setVisible(not self._resource_available())

    def _resource_available(self) -> bool:
        return (resource_directory() / "preview.html").is_file()

    # --- 动作 ---

    def _copy_report(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._report.to_text())
            self._status.setText("诊断信息已复制到剪贴板。")

    def _recheck(self) -> None:
        self._report = collect_diagnostic(self._error_text, self._traceback_text)
        self._render()
        self._status.setText("已重新检测。")

    def _open_resource_dir(self) -> None:
        target = resource_directory()
        if target.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        else:
            self._status.setText("资源目录不存在：{0}".format(target))

    def _install_pyside(self) -> None:
        if self._installing:
            return
        report = self._report
        if not report.can_install or not report.install_command:
            return
        self._installing = True
        self._btn_install.setEnabled(False)
        self._status.setText("正在安装，请保持网络连接……")
        self._detail.setPlainText("执行：{0}\n\n".format(report.install_command))

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._drain_install_output)
        process.finished.connect(self._on_install_finished)
        process.errorOccurred.connect(self._on_install_error)
        process.start(
            sys.executable,
            ["-m", "pip", "install", "--disable-pip-version-check", "PySide6==6.8.3"],
        )
        self._install_process = process

    def _drain_install_output(self) -> None:
        process = self._install_process
        if process is None:
            return
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not chunk:
            return
        self._detail.appendPlainText(chunk.rstrip())
        scrollbar = self._detail.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def _on_install_finished(self, exit_code: int, _status) -> None:
        self._installing = False
        self._btn_install.setEnabled(True)
        if exit_code == 0:
            self._status.setText("安装完成。需要重启应用后高保真预览才会生效。")
            self._ask_restart()
        else:
            self._status.setText(
                "安装失败（退出码 {0}）。可复制上方输出反馈，或改用离线安装包。".format(exit_code)
            )

    def _on_install_error(self, _error) -> None:
        self._installing = False
        self._btn_install.setEnabled(True)
        self._status.setText("无法启动 pip。请确认当前 Python 环境可用，或使用离线安装包。")

    def _enable_compat_and_restart(self) -> None:
        if not set_compat_mode(True):
            self._status.setText(
                "无法写入配置（用户目录只读）。可手动设置环境变量 "
                "QTWEBENGINE_DISABLE_SANDBOX=1 后重启。"
            )
            return
        self._status.setText("已启用兼容模式（禁用沙箱与 GPU），需要重启应用。")
        self._ask_restart()

    def _ask_restart(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "需要重启",
            "该改动需要重启应用后生效。现在重启吗？\n\n（未保存的编辑内容请先保存）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._restart_app()

    def _restart_app(self) -> None:
        program = sys.executable
        arguments = list(sys.argv[1:]) if getattr(sys, "frozen", False) else list(sys.argv)
        started = QProcess.startDetached(program, arguments)
        if not started:
            self._status.setText("自动重启失败，请手动关闭并重新打开应用。")
            return
        self.restartRequested.emit()
        QApplication.quit()


__all__ = ["FidelityDiagnosticDialog"]
