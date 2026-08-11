# -*- coding: utf-8 -*-
"""全局替换面板（底部工具面板）。

默认逐项确认：命中列表 + 选中行的"前/后"diff 预览，"替换此项/跳过此条"
逐条处理。"全部替换"为显式选项，先汇总再经确认对话框批量写回。

写回经 ``ReplaceService.apply_matches``（每文件 .md.bak + 改动清单），
完成后回调 ``on_applied`` 由主窗口触发校验管线检测悬空引用。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.replace import (
    ReplaceMatch,
    ReplacePreview,
    ReplaceService,
    diff_line,
)

# 文档类型过滤下拉（与搜索面板一致）。
_TYPE_FILTERS = (
    ("全部", None),
    ("需求文档", "requirement"),
    ("详细设计文档", "design"),
    ("通用大文档", "general"),
)


class ReplacePanel(QWidget):
    """全局替换面板。

    ``writer``：``ContentWriter``；``on_applied``：一批替换写回后回调
    （主窗口据此触发校验管线）。
    """

    def __init__(
        self,
        service: ReplaceService,
        writer,
        *,
        on_applied: Optional[Callable[[], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._writer = writer
        self._on_applied = on_applied
        self._writable = writable
        self._matches: List[ReplaceMatch] = []
        self._preview: Optional[ReplacePreview] = None

        self._build_inputs()
        self._build_diff()
        self._build_results()

    # --- 构建 ---

    def _build_inputs(self) -> None:
        inputs = QFrame(self)
        inputs.setProperty("card", True)
        layout = QVBoxLayout(inputs)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(QLabel("查找：", inputs))
        self._find_entry = QLineEdit(inputs)
        row1.addWidget(self._find_entry, 1)
        row1.addWidget(QLabel("替换为：", inputs))
        self._replace_entry = QLineEdit(inputs)
        row1.addWidget(self._replace_entry, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        self._regex_cb = QCheckBox("正则", inputs)
        self._case_cb = QCheckBox("区分大小写", inputs)
        self._word_cb = QCheckBox("整词", inputs)
        row2.addWidget(self._regex_cb)
        row2.addWidget(self._case_cb)
        row2.addWidget(self._word_cb)
        self._type_box = QComboBox(inputs)
        self._type_box.addItems([label for label, _ in _TYPE_FILTERS])
        row2.addWidget(self._type_box)
        row2.addStretch(1)
        self._find_btn = QPushButton("查找全部", inputs)
        self._find_btn.setProperty("btnRole", "secondary")
        self._find_btn.clicked.connect(self.find_all)
        row2.addWidget(self._find_btn)
        layout.addLayout(row2)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)
        outer.addWidget(inputs)

    def _build_diff(self) -> None:
        diff_frame = QFrame(self)
        diff_frame.setProperty("card", True)
        layout = QVBoxLayout(diff_frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self._before_text = self._make_readonly()
        layout.addWidget(self._before_text)
        arrow = QLabel("↓ 替换为", diff_frame)
        arrow.setObjectName("statusMuted")
        layout.addWidget(arrow)
        self._after_text = self._make_readonly()
        layout.addWidget(self._after_text)

        outer = QVBoxLayout(self)
        outer.addWidget(diff_frame)

    def _build_results(self) -> None:
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["文件", "行", "原文"])
        self._tree.setColumnWidth(0, 260)
        self._tree.setColumnWidth(1, 48)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.currentItemChanged.connect(lambda _a, _b: self._update_diff())

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._replace_one_btn = QPushButton("替换此项", self)
        self._replace_one_btn.setProperty("btnRole", "primary")
        self._replace_one_btn.clicked.connect(self.replace_one)
        actions.addWidget(self._replace_one_btn)
        self._skip_btn = QPushButton("跳过此条", self)
        self._skip_btn.setProperty("btnRole", "secondary")
        self._skip_btn.clicked.connect(self.skip_one)
        actions.addWidget(self._skip_btn)
        self._replace_all_btn = QPushButton("全部替换…", self)
        self._replace_all_btn.setProperty("btnRole", "secondary")
        self._replace_all_btn.clicked.connect(self.replace_all)
        actions.addWidget(self._replace_all_btn)
        actions.addStretch(1)
        self._rollback_btn = QPushButton("回滚本次替换", self)
        self._rollback_btn.setProperty("btnRole", "compact")
        self._rollback_btn.clicked.connect(self.rollback)
        actions.addWidget(self._rollback_btn)
        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.setProperty("btnRole", "compact")
        self._clear_btn.clicked.connect(self.clear)
        actions.addWidget(self._clear_btn)

        outer = QVBoxLayout(self)
        outer.addWidget(self._tree, 1)
        outer.addLayout(actions)
        self._update_action_state()

    @staticmethod
    def _make_readonly() -> QPlainTextEdit:
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setMaximumHeight(40)
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        return text

    # --- 行为 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    def find_all(self) -> None:
        try:
            preview = self._service.build_preview(
                self._find_entry.text().strip(),
                regex=self._regex_cb.isChecked(),
                case_sensitive=self._case_cb.isChecked(),
                whole_word=self._word_cb.isChecked(),
                document_types=self._selected_types(),
            )
        except ValueError as exc:
            self._set_status("查询无效：{0}".format(exc))
            return
        self._preview = preview
        self._matches = list(preview.matches)
        self._render_matches()
        if preview.total == 0:
            self._set_status("无匹配")
        else:
            self._set_status(
                "共 {0} 处（{1} 个文件），逐项确认后写回".format(
                    preview.total, preview.file_count
                )
            )

    def replace_one(self) -> None:
        match = self._selected_match()
        if match is None:
            return
        results = self._service.apply_matches(
            [match], self._replace_entry.text(), self._writer
        )
        self._matches.remove(match)
        self._render_matches()
        self._set_status("已替换 1 处")
        self._after_applied(results)

    def skip_one(self) -> None:
        match = self._selected_match()
        if match is None:
            return
        self._matches.remove(match)
        self._render_matches()
        self._set_status("已跳过 1 处")

    def replace_all(self) -> None:
        if not self._matches:
            self._set_status("无命中可替换")
            return
        replacement = self._replace_entry.text()
        total = len(self._matches)
        files = {m.rel_path for m in self._matches}
        confirmed = QMessageBox.question(
            self,
            "全部替换",
            "将替换 {0} 处命中，涉及 {1} 个文件。\n"
            "每文件会保留 .md.bak 备份，可一键回滚。\n"
            "确认执行？".format(total, len(files)),
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        results = self._service.apply_matches(self._matches, replacement, self._writer)
        self._matches = []
        self._preview = None
        self._render_matches()
        self._set_status("已批量替换 {0} 处（{1} 个文件）".format(total, len(files)))
        self._after_applied(results)

    def rollback(self) -> None:
        failures = self._writer.manifest.rollback()
        if failures:
            self._set_status("回滚失败：{0}".format(", ".join(failures)))
        else:
            self._set_status("已回滚本次替换")
            if self._on_applied is not None:
                self._on_applied()

    def clear(self) -> None:
        self._matches = []
        self._preview = None
        self._render_matches()
        self._set_status("")

    # --- 内部 ---

    def _after_applied(self, results) -> None:
        if self._on_applied is not None:
            self._on_applied()
        self._update_action_state()

    def _render_matches(self) -> None:
        self._tree.clear()
        for i, match in enumerate(self._matches):
            preview_text = match.line_text.strip()
            if len(preview_text) > 160:
                preview_text = preview_text[:160] + "…"
            item = QTreeWidgetItem(
                [match.rel_path, str(match.line_no), preview_text]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)
        self._update_diff()
        self._update_action_state()

    def _selected_match(self) -> Optional[ReplaceMatch]:
        item = self._tree.currentItem()
        if item is None:
            return None
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= index < len(self._matches)):
            return None
        return self._matches[index]

    def _update_diff(self) -> None:
        match = self._selected_match()
        if match is None:
            self._before_text.clear()
            self._after_text.clear()
            return
        before, after = diff_line(match, self._replace_entry.text())
        self._before_text.setPlainText(before)
        self._after_text.setPlainText(after)

    def _update_action_state(self) -> None:
        can_write = self._writable
        has_matches = bool(self._matches)
        self._replace_one_btn.setEnabled(can_write and has_matches)
        self._skip_btn.setEnabled(has_matches)
        self._replace_all_btn.setEnabled(can_write and has_matches)
        self._rollback_btn.setEnabled(can_write)
        self._clear_btn.setEnabled(has_matches)

    def _selected_types(self) -> Optional[List[str]]:
        label = self._type_box.currentText()
        value = next((v for l, v in _TYPE_FILTERS if l == label), None)
        return [value] if value else None

    def _set_status(self, text: str) -> None:
        if not hasattr(self, "_status_label"):
            self._status_label = QLabel(self)
            self._status_label.setObjectName("statusMuted")
            self._status_label.setWordWrap(True)
            self._status_label.setMaximumHeight(32)
            self.layout().addWidget(self._status_label)
        self._status_label.setText(text)
