# -*- coding: utf-8 -*-
"""右侧任务详情：流式日志 + 终态结果卡片 + 技术详情。

``LogStream``：可折叠日志视图，自动跟随最新事件；用户离开底部时保留位置
并显示待读计数。折叠期间继续接收事件。提供复制日志与打开日志目录。

``ResultCard``：终态结果卡片——成功时按实际产物提供打开产物/所在目录/
校验报告入口；失败时优先显示原因与建议，并把错误码、阶段、异常摘要、
日志路径置于可展开的技术详情。渲染与点击前检查路径存在性。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.ui.workbench_state import ResultState


class LogStream(QWidget):
    """可折叠、可复制、可跟随的日志视图。"""

    def __init__(
        self,
        *,
        on_copy: Optional[Callable[[], None]] = None,
        on_open_dir: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._lines: List[str] = []
        self._expanded = True
        self._at_bottom = True
        self._pending_unread = 0
        self._on_copy = on_copy
        self._on_open_dir = on_open_dir

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 标题行：状态 + 待读 + 折叠/展开 + 复制 + 打开目录
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._summary_label = QLabel("日志", self)
        self._summary_label.setObjectName("statusMuted")
        header.addWidget(self._summary_label)
        header.addStretch(1)

        self._pending_label = QLabel("", self)
        self._pending_label.setObjectName("statusWarning")
        self._pending_label.hide()
        header.addWidget(self._pending_label)

        self._copy_btn = QPushButton("复制", self)
        self._copy_btn.setProperty("btnRole", "compact")
        self._copy_btn.clicked.connect(self._handle_copy)
        header.addWidget(self._copy_btn)

        self._open_dir_btn = QPushButton("日志目录", self)
        self._open_dir_btn.setProperty("btnRole", "compact")
        self._open_dir_btn.clicked.connect(self._handle_open_dir)
        header.addWidget(self._open_dir_btn)

        self._toggle_btn = QPushButton("折叠", self)
        self._toggle_btn.setProperty("btnRole", "compact")
        self._toggle_btn.clicked.connect(self.toggle_expanded)
        header.addWidget(self._toggle_btn)
        layout.addLayout(header)

        self._view = QPlainTextEdit(self)
        self._view.setObjectName("logView")
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        layout.addWidget(self._view, 1)

        self._apply_expanded()

    # --- 日志内容 ---

    def append_line(self, text: str) -> None:
        """追加带时间戳的一行日志；折叠或离开底部时累计待读。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = "[{0}] {1}".format(timestamp, text)
        self._lines.append(line)
        if self._expanded:
            self._view.appendPlainText(line)
            if self._at_bottom:
                self._view.verticalScrollBar().setValue(
                    self._view.verticalScrollBar().maximum()
                )
                self._pending_unread = 0
            else:
                self._pending_unread += 1
        else:
            self._pending_unread += 1
        self._update_pending()

    def set_lines(self, lines: List[str]) -> None:
        """整体替换日志内容（展开时全量刷新）。"""
        self._lines = list(lines)
        self._view.clear()
        if self._expanded:
            self._view.setPlainText("\n".join(self._lines))
            self._view.verticalScrollBar().setValue(
                self._view.verticalScrollBar().maximum()
            )

    def clear(self) -> None:
        self._lines = []
        self._view.clear()
        self._pending_unread = 0
        self._at_bottom = True
        self._update_pending()

    def full_text(self) -> str:
        return "\n".join(self._lines)

    @property
    def pending_unread(self) -> int:
        return self._pending_unread

    # --- 折叠/展开 ---

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._apply_expanded()

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _apply_expanded(self) -> None:
        if self._expanded:
            self._view.show()
            self._toggle_btn.setText("折叠")
            self._summary_label.setText(
                "日志已展开" + self._pending_suffix()
            )
            # 折叠期间到达的行只累积进 _lines、未写入视图：展开时全量回放，
            # 避免可见日志与待读计数永久错位（append_line/set_lines 同路径）。
            if self._view.toPlainText() != "\n".join(self._lines):
                self._view.setPlainText("\n".join(self._lines))
                self._view.verticalScrollBar().setValue(
                    self._view.verticalScrollBar().maximum()
                )
            self._pending_unread = 0
        else:
            self._view.hide()
            self._toggle_btn.setText("展开")
            self._summary_label.setText(
                "日志已折叠" + self._pending_suffix()
            )
        self._update_pending()

    def _pending_suffix(self) -> str:
        return (
            " · {0} 条待读".format(self._pending_unread)
            if self._pending_unread
            else ""
        )

    def _update_pending(self) -> None:
        if self._pending_unread:
            self._pending_label.setText("{0} 条新日志…".format(self._pending_unread))
            self._pending_label.show()
        else:
            self._pending_label.hide()
        self._summary_label.setText(
            ("日志已展开" if self._expanded else "日志已折叠")
            + self._pending_suffix()
        )

    def _on_scroll(self, value: int) -> None:
        bar = self._view.verticalScrollBar()
        self._at_bottom = bar.maximum() - value <= 2
        if self._at_bottom:
            self._pending_unread = 0
            self._update_pending()

    def _handle_copy(self) -> None:
        if self._on_copy is not None:
            self._on_copy()

    def _handle_open_dir(self) -> None:
        if self._on_open_dir is not None:
            self._on_open_dir()


class ResultCard(QFrame):
    """终态结果卡片：标题 + 摘要 + 建议 + 适用后续操作。"""

    def __init__(
        self,
        *,
        on_open_output: Optional[Callable[[str], None]] = None,
        on_open_directory: Optional[Callable[[str], None]] = None,
        on_open_report: Optional[Callable[[], None]] = None,
        on_show_tech: Optional[Callable[[], None]] = None,
        on_copy_path: Optional[Callable[[str], None]] = None,
        on_export_to: Optional[Callable[[str], None]] = None,
        on_locate_file: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_open_output = on_open_output
        self._on_open_directory = on_open_directory
        self._on_open_report = on_open_report
        self._on_show_tech = on_show_tech
        self._on_copy_path = on_copy_path
        self._on_export_to = on_export_to
        self._on_locate_file = on_locate_file

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(6)

        self._title = QLabel(self)
        self._title.setObjectName("resultTitle")
        self._layout.addWidget(self._title)

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._layout.addWidget(self._summary)

        self._advice = QLabel(self)
        self._advice.setObjectName("statusMuted")
        self._advice.setWordWrap(True)
        self._advice.hide()
        self._layout.addWidget(self._advice)

        self._locations = QLabel(self)
        self._locations.setObjectName("resultLocations")
        self._locations.setWordWrap(True)
        self._locations.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._locations.hide()
        self._layout.addWidget(self._locations)

        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 4, 0, 0)
        self._action_buttons: List[QPushButton] = []
        self._layout.addLayout(self._actions)

        self._tech_frame = QFrame(self)
        self._tech_layout = QVBoxLayout(self._tech_frame)
        self._tech_layout.setContentsMargins(0, 4, 0, 0)
        self._tech_frame.hide()
        self._layout.addWidget(self._tech_frame)

    def render(self, result: ResultState) -> None:
        """按结果状态渲染卡片；仅渲染当前仍存在的路径操作。"""
        status = result.status
        if status == "success":
            self.setProperty("cardClass", "resultSuccess")
            self._title.setText("✓ {0}".format(result.title or "任务完成"))
        elif status in ("failure", "cancelled"):
            self.setProperty("cardClass", "resultFailure")
            self._title.setText("✗ {0}".format(result.title or "任务未完成"))
        else:
            self.setProperty("cardClass", "result")
            self._title.setText(result.title or "任务结果")
        self._title.setProperty("statusTone", {
            "success": "success",
            "failure": "failure",
            "cancelled": "warning",
        }.get(status, "neutral"))
        self._summary.setText(result.summary or "")
        if result.advice:
            self._advice.setText("建议：{0}".format(result.advice))
            self._advice.show()
        else:
            self._advice.hide()

        # 出错位置：失败时直接列出前几条「文件:行号 说明」，让用户不必先
        # 展开技术详情或翻日志就知道改哪里。
        if result.locations:
            shown = list(result.locations[:5])
            text = "\n".join("• {0}".format(line) for line in shown)
            if len(result.locations) > len(shown):
                text += "\n• …共 {0} 处，完整清单见「问题」面板。".format(
                    len(result.locations)
                )
            self._locations.setText(text)
            self._locations.show()
        else:
            self._locations.hide()

        # 重建操作按钮；路径不存在则跳过，避免打开无效路径。
        self._clear_actions()
        output = result.output_path
        output_exists = bool(output and Path(output).is_file())
        if output_exists:
            self._add_action(
                "打开产物",
                lambda _checked=False, p=str(output): self._open_output(p),
            )
            self._add_action(
                "定位文件" if self._on_locate_file is not None else "打开所在目录",
                lambda _checked=False, p=str(output): (
                    self._on_locate_file(p)
                    if self._on_locate_file is not None
                    else self._open_directory(str(Path(p).parent))
                ),
            )
            if self._on_copy_path is not None:
                self._add_action(
                    "复制路径",
                    lambda _checked=False, p=str(output): self._on_copy_path(p),
                )
            if self._on_export_to is not None:
                self._add_action(
                    "另存为…",
                    lambda _checked=False, p=str(output): self._on_export_to(p),
                )
        report = result.report_path
        if report and Path(report).is_file():
            self._add_action("查看校验报告", lambda: self._open_report())
        if status in ("failure", "cancelled") and (
            result.error_code
            or result.stage
            or result.exception_summary
            or result.log_path
            or result.locations
        ):
            self._add_action("技术详情…", lambda: self._show_tech())
            self._render_tech(result)

    # --- 技术详情 ---

    def _render_tech(self, result: ResultState) -> None:
        for child in self._tech_frame.findChildren(QLabel):
            child.deleteLater()
        lines = [
            ("错误码", result.error_code or "未知"),
            ("失败阶段", result.stage or "未知"),
            ("异常摘要", result.exception_summary or "无"),
            ("日志路径", str(result.log_path) if result.log_path else "未生成"),
        ]
        for index, location in enumerate(result.locations[:10], start=1):
            lines.append(("出错位置 {0}".format(index), location))
        for name, value in lines:
            row = QLabel(self._tech_frame)
            row.setObjectName("techDetail")
            row.setWordWrap(True)
            row.setText("{0}：{1}".format(name, value))
            self._tech_layout.addWidget(row)
        self._tech_frame.show()

    def _clear_actions(self) -> None:
        while self._actions.count():
            item = self._actions.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._action_buttons = []
        self._tech_frame.hide()

    def _add_action(self, text: str, callback: Callable[[], None]) -> None:
        button = QPushButton(text, self)
        button.setProperty("btnRole", "compact")
        button.clicked.connect(callback)
        self._actions.addWidget(button)
        self._action_buttons.append(button)

    # --- 回调转发（由主窗口接线，路径存在性已在 render 时校验） ---

    def _open_output(self, path: str) -> None:
        if self._on_open_output is not None:
            self._on_open_output(path)

    def _open_directory(self, path: str) -> None:
        if self._on_open_directory is not None:
            self._on_open_directory(path)

    def _open_report(self) -> None:
        if self._on_open_report is not None:
            self._on_open_report()

    def _show_tech(self) -> None:
        if self._on_show_tech is not None:
            self._on_show_tech()
