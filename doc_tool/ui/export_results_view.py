# -*- coding: utf-8 -*-
"""非模态成果视图：按轮次显示逐文件状态、路径与打开/恢复动作。

UI 包 UI-C 3.1/3.3 的视图层：

- 顶部选择本项目最近轮次（关闭后可从「成果」再次打开）；
- 每个格式一行：状态、真实路径、打开/定位；路径失效给「重新定位」提示；
- 底部动作：补这次成果（原轮）、按当前修改重新生成、换目录并重新导出；
- 无产物时只显示摘要与原因，不编造「打开」按钮；
- 普通完成不抢焦点（本视图只渲染，不主动 raise/聚焦）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from doc_tool.ui.flow_row import FlowRow
from PySide6.QtWidgets import (
    QComboBox,
    QSizePolicy,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ExportResultsView(QWidget):
    """成果页：轮次选择 + 逐文件结果 + 恢复动作。"""

    def __init__(
        self,
        *,
        on_open_format: Optional[Callable[[str, str], None]] = None,
        on_locate_format: Optional[Callable[[str], None]] = None,
        on_retry_formats: Optional[Callable[[object], None]] = None,
        on_regenerate_round: Optional[Callable[[object], None]] = None,
        on_change_destination: Optional[Callable[[object], None]] = None,
        on_open_settings: Optional[Callable[[object], None]] = None,
        on_select_round: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_open_format = on_open_format
        self._on_locate_format = on_locate_format
        self._on_retry_formats = on_retry_formats
        self._on_regenerate_round = on_regenerate_round
        self._on_change_destination = on_change_destination
        self._on_open_settings = on_open_settings
        self._on_select_round = on_select_round
        self._rounds: List[object] = []
        self._current = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QLabel("轮次：", self))
        self._round_box = QComboBox(self)
        self._round_box.setObjectName("resultsRoundBox")
        self._round_box.currentIndexChanged.connect(self._on_round_selected)
        self._round_box.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._round_box.setMinimumWidth(80)
        header.addWidget(self._round_box, 1)
        layout.addLayout(header)

        self._summary = QLabel("", self)
        self._summary.setObjectName("statusMuted")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_host = QWidget(scroll)
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        scroll.setWidget(self._rows_host)
        layout.addWidget(scroll, 1)

        self._warning = QLabel("", self)
        self._warning.setObjectName("statusMuted")
        self._warning.setWordWrap(True)
        layout.addWidget(self._warning)

        actions = FlowRow(stack_below=380, parent=self)
        actions.inner_layout.setContentsMargins(0, 0, 0, 0)
        self._retry_btn = QPushButton("补这次成果（原轮）", self)
        self._retry_btn.setProperty("btnRole", "compact")
        self._retry_btn.setToolTip("用旧捕获与原范围只补缺失/失败格式，不读当前新正文")
        self._retry_btn.clicked.connect(lambda: self._invoke(self._on_retry_formats))
        actions.add(self._retry_btn)

        self._regenerate_btn = QPushButton("按当前修改重新生成", self)
        self._regenerate_btn.setProperty("btnRole", "compact")
        self._regenerate_btn.setToolTip("收集当前编辑器缓冲，建立新轮次并显示采用的格式/范围")
        self._regenerate_btn.clicked.connect(lambda: self._invoke(self._on_regenerate_round))
        actions.add(self._regenerate_btn)

        self._settings_btn = QPushButton("更改设置…", self)
        self._settings_btn.setProperty("btnRole", "compact")
        self._settings_btn.setToolTip("带入本轮原范围/格式/目录打开导出设置，提交产生新轮")
        self._settings_btn.clicked.connect(lambda: self._invoke(self._on_open_settings))
        self._actions_row = actions
        actions.add(self._settings_btn)

        self._destination_btn = QPushButton("换目录并重新导出…", self)
        self._destination_btn.setProperty("btnRole", "compact")
        self._destination_btn.setToolTip("明示来源/范围并建立新轮次，默认当前内容；旧成果保留")
        self._destination_btn.clicked.connect(lambda: self._invoke(self._on_change_destination))
        actions.add(self._destination_btn)
        layout.addWidget(actions)

        self.set_rounds([], "")

    # --- 渲染 ---

    def set_rounds(self, rounds: List[object], selected_round_id: str = "") -> None:
        """更新轮次列表（保持选择；新轮不被迟到结果覆盖）。"""
        self._rounds = list(rounds or [])
        self._round_box.blockSignals(True)
        self._round_box.clear()
        for item in reversed(self._rounds):
            label = item.summary_line()
            self._round_box.addItem(label, item.round_id)
        index = 0
        if selected_round_id:
            for position in range(self._round_box.count()):
                if self._round_box.itemData(position) == selected_round_id:
                    index = position
                    break
        if self._round_box.count():
            self._round_box.setCurrentIndex(index)
        self._round_box.blockSignals(False)

    def render(self, rounds: List[object], selected_round_id: str = "") -> None:
        self.set_rounds(rounds, selected_round_id)
        self._render_current()

    def current_round(self):
        index = self._round_box.currentIndex()
        if 0 <= index < self._round_box.count():
            round_id = self._round_box.itemData(index)
            for item in self._rounds:
                if item.round_id == round_id:
                    return item
        return self._rounds[-1] if self._rounds else None

    def _render_current(self) -> None:
        round_view = self.current_round()
        self._current = round_view
        self._clear_rows()
        if round_view is None:
            self._summary.setText("本项目还没有可显示的出稿成果。")
            self._warning.setText("")
            for button in (self._retry_btn, self._regenerate_btn, self._destination_btn):
                button.setEnabled(False)
            return

        self._summary.setText(
            "{0}\n输出位置：{1}".format(
                round_view.summary_line(), round_view.destination or "（未记录）"
            )
        )
        unsaved = len(round_view.unsaved_chapters)
        warnings = list(round_view.warnings)
        if unsaved:
            warnings.insert(0, "本轮包含 {0} 章未保存修改（源文件未被改写）".format(unsaved))
        self._warning.setText("\n".join(warnings[:3]))

        for item in round_view.formats:
            self._add_row(item)
        if not round_view.formats:
            empty = QLabel("本轮没有格式结果（命令未产出文件）。", self._rows_host)
            empty.setObjectName("statusMuted")
            empty.setWordWrap(True)
            self._rows_layout.addWidget(empty)

        self._retry_btn.setEnabled(bool(round_view.has_retryable))

    def _add_row(self, item) -> None:
        row = QFrame(self._rows_host)
        row.setProperty("cardClass", "result")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        title = QLabel(item.describe(), row)
        title.setWordWrap(True)
        layout.addWidget(title)
        if item.path:
            path_label = QLabel(item.path, row)
            path_label.setObjectName("statusMuted")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(path_label)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        if item.can_open:
            open_btn = QPushButton("打开", row)
            open_btn.setProperty("btnRole", "compact")
            open_btn.clicked.connect(
                lambda _checked=False, f=item.format, p=item.path: self._open_format(f, p)
            )
            buttons.addWidget(open_btn)
        if item.path and Path(item.path).exists():
            locate_btn = QPushButton("定位文件", row)
            locate_btn.setProperty("btnRole", "compact")
            locate_btn.clicked.connect(
                lambda _checked=False, p=item.path: self._locate_format(p)
            )
            buttons.addWidget(locate_btn)
        if item.is_stale:
            hint = QLabel("路径已失效：可重新定位或按当前修改重新生成", row)
            hint.setObjectName("statusWarning")
            hint.setWordWrap(True)
            buttons.addWidget(hint, 1)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._rows_layout.addWidget(row)

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def clear(self) -> None:
        self._rounds = []
        self._current = None
        self._round_box.blockSignals(True)
        self._round_box.clear()
        self._round_box.blockSignals(False)
        self._clear_rows()
        self._summary.setText("")
        self._warning.setText("")

    # --- 事件 ---

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._actions_row.apply_width(int(event.size().width()) - 8)

    def _on_round_selected(self, _index: int) -> None:
        self._render_current()
        if self._on_select_round is not None and self._current is not None:
            self._on_select_round(self._current.round_id)

    def _on_open_settings(self) -> None:
        """从旧轮打开导出设置：提交产生新轮，不改变旧轮历史。"""
        if self._on_open_settings is None or self._current is None:
            return
        self._on_open_settings(self._current)

    def _invoke(self, callback) -> None:
        if callback is None or self._current is None:
            return
        callback(self._current)

    def _open_format(self, fmt: str, path: str) -> None:
        if self._on_open_format is not None:
            self._on_open_format(fmt, path)

    def _locate_format(self, path: str) -> None:
        if self._on_locate_format is not None:
            self._on_locate_format(path)


__all__ = ["ExportResultsView"]