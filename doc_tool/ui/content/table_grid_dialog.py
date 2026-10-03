# -*- coding: utf-8 -*-
"""表格网格与“粘贴为表格”对话框（V3.4 34-B/34-C）。

界面只负责编辑与预览：表格模型、解析、序列化与片段定位都在
``application/content/table_grid.py``；应用动作由编辑器用一个 ``QTextCursor``
编辑单元完成，因此一次撤销即可还原。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content import table_grid as grid

_ALIGN_LABELS = (
    ("默认", "default"),
    ("左对齐", "left"),
    ("居中", "center"),
    ("右对齐", "right"),
)


class TableGridDialog(QDialog):
    """普通表格网格编辑：行列增删移动、列对齐、Tab 导航与一次应用。"""

    def __init__(self, model: grid.TableModel, *, parent=None):
        super().__init__(parent)
        self.setObjectName("tableGridDialog")
        self.setWindowTitle("编辑表格" if model.start_line <= 0 else "编辑表格（第 {0} 行起）".format(model.start_line))
        self.setMinimumSize(720, 480)
        self._model = model
        self._original_text = model.serialize()
        self._source_changed = False
        self.pending_text = ""
        self.relocate_requested = False
        #: 网格局部撤销/重做（不改编辑器，只在对话框内回退网格操作）。
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self._restoring = False
        self._last_state: Optional[dict] = None
        self._build_ui()
        self._load_model(model)
        self.table.itemChanged.connect(self._on_item_changed)
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    # --- 构建 ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.notice = QLabel("")
        self.notice.setObjectName("tableGridNotice")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        self.table = QTableWidget(0, 0, self)
        self.table.setObjectName("tableGrid")
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Tab/Shift+Tab 在焦点位于网格内时也要跨行导航。
        self.table.installEventFilter(self)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        layout.addWidget(self.table, 1)

        row_buttons = QHBoxLayout()
        self.add_row_btn = QPushButton("添加行")
        self.add_row_btn.clicked.connect(lambda: self._insert_row(after=True))
        row_buttons.addWidget(self.add_row_btn)
        self.insert_row_btn = QPushButton("上方插入行")
        self.insert_row_btn.clicked.connect(lambda: self._insert_row(after=False))
        row_buttons.addWidget(self.insert_row_btn)
        self.remove_row_btn = QPushButton("删除行")
        self.remove_row_btn.clicked.connect(self._remove_rows)
        row_buttons.addWidget(self.remove_row_btn)
        self.move_row_up_btn = QPushButton("上移行")
        self.move_row_up_btn.clicked.connect(lambda: self._move_row(-1))
        row_buttons.addWidget(self.move_row_up_btn)
        self.move_row_down_btn = QPushButton("下移行")
        self.move_row_down_btn.clicked.connect(lambda: self._move_row(1))
        row_buttons.addWidget(self.move_row_down_btn)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        col_buttons = QHBoxLayout()
        self.add_col_btn = QPushButton("添加列")
        self.add_col_btn.clicked.connect(lambda: self._insert_column(after=True))
        col_buttons.addWidget(self.add_col_btn)
        self.insert_col_btn = QPushButton("左侧插入列")
        self.insert_col_btn.clicked.connect(lambda: self._insert_column(after=False))
        col_buttons.addWidget(self.insert_col_btn)
        self.remove_col_btn = QPushButton("删除列")
        self.remove_col_btn.clicked.connect(self._remove_columns)
        col_buttons.addWidget(self.remove_col_btn)
        self.move_col_left_btn = QPushButton("左移列")
        self.move_col_left_btn.clicked.connect(lambda: self._move_column(-1))
        col_buttons.addWidget(self.move_col_left_btn)
        self.move_col_right_btn = QPushButton("右移列")
        self.move_col_right_btn.clicked.connect(lambda: self._move_column(1))
        col_buttons.addWidget(self.move_col_right_btn)
        col_buttons.addStretch(1)
        layout.addLayout(col_buttons)

        align_buttons = QHBoxLayout()
        align_buttons.addWidget(QLabel("列对齐"))
        self.align_buttons: Dict[str, QPushButton] = {}
        for label, key in _ALIGN_LABELS:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=key: self._set_alignment(value))
            align_buttons.addWidget(button)
            self.align_buttons[key] = button
        self.undo_btn = QPushButton("撤销网格操作")
        self.undo_btn.setToolTip("只回退网格内的行列/单元格改动（Ctrl+Z）")
        self.undo_btn.clicked.connect(self.undo_grid)
        align_buttons.addWidget(self.undo_btn)
        self.redo_btn = QPushButton("重做")
        self.redo_btn.clicked.connect(self.redo_grid)
        align_buttons.addWidget(self.redo_btn)
        self.support_btn = QPushButton("支持范围…")
        self.support_btn.setToolTip("查看普通表格支持的表达与不支持时的原文保留方式")
        self.support_btn.clicked.connect(self._show_support)
        align_buttons.addWidget(self.support_btn)
        self.preview_btn = QPushButton("预览 Markdown")
        self.preview_btn.clicked.connect(self._show_preview)
        align_buttons.addWidget(self.preview_btn)
        align_buttons.addStretch(1)
        layout.addLayout(align_buttons)

        footer = QHBoxLayout()
        self.hint = QLabel("可用 Tab / Shift+Tab 在单元格间移动；标题行是第一行。")
        self.hint.setWordWrap(True)
        footer.addWidget(self.hint, 1)
        self.relocate_btn = QPushButton("重新定位并应用")
        self.relocate_btn.setEnabled(False)
        self.relocate_btn.clicked.connect(self._request_relocate)
        footer.addWidget(self.relocate_btn)
        self.copy_btn = QPushButton("复制 Markdown")
        self.copy_btn.clicked.connect(self._copy_markdown)
        footer.addWidget(self.copy_btn)
        self.apply_btn = QPushButton("应用")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        footer.addWidget(self.apply_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)
        layout.addLayout(footer)

    # --- 网格局部撤销 ---

    def _snapshot(self) -> dict:
        return {"matrix": self._matrix(), "alignments": list(self._alignments)}

    def _restore(self, state: dict) -> None:
        self._restoring = True
        try:
            self._apply_matrix(state.get("matrix") or [[""]], record=False)
            self._alignments = list(state.get("alignments") or [])
            self._alignments_after_change()
        finally:
            self._restoring = False
        self._last_state = self._snapshot()

    def _push_undo(self) -> None:
        if self._restoring or self._last_state is None:
            return
        self._undo_stack.append(self._last_state)
        self._redo_stack.clear()

    def _on_item_changed(self, _item) -> None:
        if self._restoring:
            return
        self._push_undo()
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    def undo_grid(self) -> None:
        if not self._undo_stack:
            self.notice.setText("没有可撤销的网格操作")
            return
        state = self._undo_stack.pop()
        self._redo_stack.append(self._snapshot())
        self._restore(state)
        self._update_undo_buttons()

    def redo_grid(self) -> None:
        if not self._redo_stack:
            self.notice.setText("没有可重做的网格操作")
            return
        state = self._redo_stack.pop()
        self._undo_stack.append(self._snapshot())
        self._restore(state)
        self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        self.undo_btn.setEnabled(bool(self._undo_stack))
        self.redo_btn.setEnabled(bool(self._redo_stack))

    def _load_model(self, model: grid.TableModel) -> None:
        rows = 1 + len(model.rows)
        columns = max(1, model.column_count)
        self.table.setRowCount(rows)
        self.table.setColumnCount(columns)
        self.table.setHorizontalHeaderLabels(
            ["第 {0} 列".format(index + 1) for index in range(columns)]
        )
        self.table.setVerticalHeaderLabels(["表头"] + [
            "第 {0} 行".format(index + 1) for index in range(len(model.rows))
        ])
        for index, value in enumerate(model.header):
            self.table.setItem(0, index, QTableWidgetItem(value))
        for row_index, row in enumerate(model.rows):
            for col_index, value in enumerate(row):
                self.table.setItem(row_index + 1, col_index, QTableWidgetItem(value))
        if model.warnings:
            self.notice.setText("；".join(model.warnings))

    # --- 网格操作 ---

    def _selected_rows(self) -> List[int]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return rows or [max(0, self.table.currentRow())]

    def _selected_columns(self) -> List[int]:
        columns = sorted({index.column() for index in self.table.selectedIndexes()})
        return columns or [max(0, self.table.currentColumn())]

    def _insert_row(self, *, after: bool) -> None:
        rows = self._selected_rows()
        target = max(rows) + (1 if after else 0)
        self._push_undo()
        self._restoring = True
        try:
            self.table.insertRow(max(1, target))
        finally:
            self._restoring = False
        self._relabel_rows()
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    def _remove_rows(self) -> None:
        rows = [row for row in self._selected_rows() if row > 0]
        if not rows:
            self.notice.setText("表头行不可删除；请选择数据行。")
            return
        self._push_undo()
        self._restoring = True
        try:
            for row in sorted(rows, reverse=True):
                self.table.removeRow(row)
        finally:
            self._restoring = False
        self._relabel_rows()
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    def _move_row(self, delta: int) -> None:
        rows = [row for row in self._selected_rows() if row > 0]
        if not rows:
            self.notice.setText("表头行不可移动；请选择数据行。")
            return
        if delta < 0 and min(rows) <= 1:
            return
        if delta > 0 and max(rows) >= self.table.rowCount() - 1:
            return
        self._move_rows(rows, delta)

    def _move_rows(self, rows: List[int], delta: int) -> None:
        values = self._row_values()
        order = list(range(len(values)))
        for row in (sorted(rows, reverse=True) if delta > 0 else sorted(rows)):
            index = row - 1
            target = index + delta
            if 0 <= target < len(order):
                order[index], order[target] = order[target], order[index]
        self._apply_rows([values[index] for index in order])

    def _insert_column(self, *, after: bool) -> None:
        columns = self._selected_columns()
        target = max(columns) + (1 if after else 0)
        self._push_undo()
        self._restoring = True
        try:
            self.table.insertColumn(max(0, target))
            self._alignments.insert(max(0, target), "default")
        finally:
            self._restoring = False
        self._alignments_after_change()
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    def _remove_columns(self) -> None:
        columns = self._selected_columns()
        if len(columns) >= self.table.columnCount():
            self.notice.setText("至少保留一列。")
            return
        self._push_undo()
        self._restoring = True
        try:
            for column in sorted(columns, reverse=True):
                self.table.removeColumn(column)
                del self._alignments[column]
        finally:
            self._restoring = False
        self._alignments_after_change()
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    def _move_column(self, delta: int) -> None:
        columns = self._selected_columns()
        if delta < 0 and min(columns) <= 0:
            return
        if delta > 0 and max(columns) >= self.table.columnCount() - 1:
            return
        values = self._matrix()
        alignments = list(self._alignments)
        order = list(range(len(values[0])))
        for column in (sorted(columns, reverse=True) if delta > 0 else sorted(columns)):
            target = column + delta
            if 0 <= target < len(order):
                order[column], order[target] = order[target], order[column]
        self._push_undo()
        self._alignments = [alignments[index] for index in order]
        self._apply_matrix([[row[index] for index in order] for row in values], record=False)
        self._last_state = self._snapshot()
        self._update_undo_buttons()

    def _set_alignment(self, value: str) -> None:
        self._push_undo()
        for column in self._selected_columns():
            self._alignments[column] = value
        self._last_state = self._snapshot()
        self._update_undo_buttons()
        self.notice.setText(
            "列 {0} 已设为 {1}".format(
                "、".join(str(column + 1) for column in self._selected_columns()),
                dict((key, label) for label, key in _ALIGN_LABELS).get(value, value),
            )
        )

    def _show_support(self) -> None:
        lines = ["{0}：{1}".format(key, text) for key, text in grid.SUPPORT_MATRIX.items()]
        QMessageBox.information(self, "普通表格支持范围", "\n".join(lines))

    def _show_preview(self) -> None:
        QMessageBox.information(self, "Markdown 预览", self.markdown_text())

    def _request_relocate(self) -> None:
        self.pending_text = self.markdown_text()
        self.relocate_requested = True
        self.accept()

    def _copy_markdown(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.markdown_text())
        self.notice.setText("网格内容已复制，可在编辑器中粘贴；原表格未被修改。")

    # --- 数据往返 ---

    def _matrix(self) -> List[List[str]]:
        rows = []
        for row in range(self.table.rowCount()):
            values = []
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                values.append(item.text() if item is not None else "")
            rows.append(values)
        return rows or [[""]]

    def _row_values(self) -> List[List[str]]:
        return self._matrix()[1:]

    def _apply_rows(self, rows: List[List[str]]) -> None:
        self._apply_matrix([self._matrix()[0]] + rows)

    def _apply_matrix(self, matrix: List[List[str]], *, record: bool = True) -> None:
        if record:
            self._push_undo()
        restoring = self._restoring
        self._restoring = True
        try:
            self.table.setRowCount(len(matrix))
            self.table.setColumnCount(len(matrix[0]) if matrix else 1)
            for row_index, row in enumerate(matrix):
                for column, value in enumerate(row):
                    self.table.setItem(row_index, column, QTableWidgetItem(value))
            self._relabel_rows()
            self._alignments_after_change()
        finally:
            self._restoring = restoring
        if record:
            self._last_state = self._snapshot()
            self._update_undo_buttons()

    def _relabel_rows(self) -> None:
        self.table.setVerticalHeaderLabels(
            ["表头"] + ["第 {0} 行".format(index) for index in range(1, self.table.rowCount())]
        )

    def _alignments_after_change(self) -> None:
        while len(self._alignments) < self.table.columnCount():
            self._alignments.append("default")
        self._alignments = self._alignments[: self.table.columnCount()]
        self.table.setHorizontalHeaderLabels(
            ["第 {0} 列（{1}）".format(
                index + 1,
                dict((key, label) for label, key in _ALIGN_LABELS).get(self._alignments[index], "默认"),
            ) for index in range(self.table.columnCount())]
        )

    @property
    def _alignments(self) -> List[str]:
        if not hasattr(self, "_align_values"):
            self._align_values: List[str] = list(self._model.alignments)
        return self._align_values

    @_alignments.setter
    def _alignments(self, value: List[str]) -> None:
        self._align_values = list(value)

    def result_model(self) -> grid.TableModel:
        matrix = self._matrix()
        model = grid.model_from_matrix(
            matrix, has_header=True, alignments=self._alignments,
            rel_path=self._model.rel_path, start_line=self._model.start_line,
        )
        model.raw_input = self._model.raw_input
        model.warnings = list(self._model.warnings)
        model.supported = self._model.supported
        return model

    def markdown_text(self) -> str:
        return self.result_model().serialize()

    def is_dirty(self) -> bool:
        return self.markdown_text().strip() != self._original_text.strip()

    def set_source_changed(self, reason: str) -> None:
        """原片段已变/歧义：保留网格内容，提供重新定位或复制文本。"""
        self._source_changed = True
        self.pending_text = self.markdown_text()
        self.notice.setText(
            "原表格未被覆盖：{0}。可“重新定位并应用”选择目标表格，或“复制 Markdown”保留结果。".format(reason)
        )
        self.relocate_btn.setEnabled(True)

    def source_changed(self) -> bool:
        return self._source_changed

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt 命名
        from PySide6.QtCore import QEvent

        if watched is self.table and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                delta = -1 if (
                    key == Qt.Key.Key_Backtab or event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ) else 1
                self._move_cell(delta)
                return True
            if key == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.redo_grid()
                else:
                    self.undo_grid()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        key = event.key()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            delta = -1 if key == Qt.Key.Key_Backtab or event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self._move_cell(delta)
            return
        super().keyPressEvent(event)

    def _move_cell(self, delta: int) -> None:
        row, column = self.table.currentRow(), self.table.currentColumn()
        if row < 0 or column < 0:
            self.table.setCurrentCell(0, 0)
            return
        columns = max(1, self.table.columnCount())
        flat = row * columns + column + delta
        flat = max(0, min(flat, self.table.rowCount() * columns - 1))
        self.table.setCurrentCell(flat // columns, flat % columns)
        self.table.editItem(self.table.currentItem())


class TablePasteDialog(QDialog):
    """“粘贴为表格”预览：行列数、首行表头选项、支持边界与原文回退。"""

    #: 结果模式：插入表格 / 插入原文 / 取消。
    MODE_TABLE = "table"
    MODE_RAW = "raw"

    def __init__(self, result: grid.DelimitedResult, *, parent=None):
        super().__init__(parent)
        self.setObjectName("tablePasteDialog")
        self.setWindowTitle("粘贴为表格")
        self.setMinimumSize(640, 460)
        self._result = result
        self.mode = ""
        self._build_ui()
        self._load(result)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.summary = QLabel("")
        self.summary.setObjectName("tablePasteSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        options = QHBoxLayout()
        self.header_check = QCheckBox("首行为表头")
        self.header_check.setChecked(True)
        self.header_check.stateChanged.connect(self._refresh_preview)
        options.addWidget(self.header_check)
        self.raw_btn = QPushButton("插入原文（普通粘贴）")
        self.raw_btn.setToolTip("无法等价表示时保留剪贴板原文，不丢内容")
        self.raw_btn.clicked.connect(lambda: self._finish(self.MODE_RAW))
        options.addWidget(self.raw_btn)
        options.addStretch(1)
        layout.addLayout(options)

        self.table = QTableWidget(0, 0, self)
        self.table.setObjectName("tablePastePreview")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 2)

        self.page_label = QLabel("")
        self.page_label.setObjectName("tablePastePageLabel")
        self.page_label.setWordWrap(True)
        layout.addWidget(self.page_label)

        self.warning_text = QPlainTextEdit()
        self.warning_text.setReadOnly(True)
        self.warning_text.setObjectName("tablePasteWarnings")
        self.warning_text.setMaximumHeight(96)
        layout.addWidget(self.warning_text)

        footer = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        footer.addWidget(self.hint, 1)
        self.insert_btn = QPushButton("插入表格")
        self.insert_btn.setDefault(True)
        self.insert_btn.clicked.connect(lambda: self._finish(self.MODE_TABLE))
        footer.addWidget(self.insert_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)
        layout.addLayout(footer)

    def _load(self, result: grid.DelimitedResult) -> None:
        source_label = {"tsv": "制表符分隔（TSV）", "markdown": "已有管道表格"}.get(result.source, "文本")
        self.summary.setText(
            "来源：{0}；{1} 行 × {2} 列".format(source_label, result.row_count, result.column_count)
        )
        self.warning_text.setPlainText("\n".join(result.warnings))
        if not result.ok:
            self.insert_btn.setEnabled(False)
            self.header_check.setEnabled(False)
            self.hint.setText("{0}；可用“插入原文”或直接 Ctrl+V 保留内容。".format(result.error))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        result = self._result
        rows = [list(row) for row in (result.rows or [])]
        has_header = bool(self.header_check.isChecked())
        shown, truncated, total = grid.preview_rows(rows)
        columns = max((len(row) for row in rows), default=0)
        self.table.setRowCount(len(shown))
        self.table.setColumnCount(max(1, columns))
        for row_index, row in enumerate(shown):
            for column in range(columns):
                value = row[column] if column < len(row) else ""
                item = QTableWidgetItem(value)
                if has_header and row_index == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row_index, column, item)
        self.page_label.setText(
            "预览显示前 {0} 行 / 共 {1} 行（应用后完整插入，不截断）".format(len(shown), total)
            if truncated else "共 {0} 行，已全部显示".format(total)
        )
        if not self.hint.text():
            self.hint.setText("数值、日期与 =公式 都按文本保留；引号内换行转为 {0}。".format(grid.MULTILINE_MARKER))

    def _finish(self, mode: str) -> None:
        self.mode = mode
        self.accept()

    def markdown_text(self) -> str:
        model = grid.model_from_matrix(
            self._result.rows, has_header=bool(self.header_check.isChecked()),
        )
        return model.serialize()

    def raw_text(self) -> str:
        return self._result.raw_input or "\n".join("\t".join(row) for row in self._result.rows or [])
