# -*- coding: utf-8 -*-
"""模板填充的标题样式手动映射对话框。

模板的标题样式无法自动识别（自定义命名且无大纲级别）时，把模板里的
段落样式逐个列出让用户映射到标题级别 1~6 或「忽略」；映射只作用于本次
模板填充，不落盘。交互模型与导入向导的「样式映射」页一致：
至少一个级别 1、级别连续、一个级别只能对应一个样式。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from doc_tool.application.template_fill import StyleInfo, validate_style_map

_LEVEL_IGNORE = 0


class TemplateStyleMapDialog(QDialog):
    """模板段落样式 → 标题级别的手动映射表。"""

    def __init__(
        self,
        styles: List[StyleInfo],
        current: Optional[Dict[str, int]] = None,
        parent: Optional[QDialog] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("模板标题样式映射")
        self.resize(560, 420)
        self._styles = styles

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(QLabel(
            "该模板未自动识别出标题样式：请把承载各级标题的样式映射到级别 1~6，"
            "其余保持「忽略」（按正文处理）。映射仅对本次转换生效。",
            self,
        ))
        layout.setContentsMargins(14, 12, 14, 12)

        self._table = QTableWidget(len(styles), 3, self)
        self._table.setHorizontalHeaderLabels(["样式 ID", "样式名称", "标题级别"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self._table, 1)

        current = current or {}
        for row, info in enumerate(styles):
            id_item = QTableWidgetItem(info.style_id)
            id_item.setToolTip(info.style_id)
            self._table.setItem(row, 0, id_item)
            self._table.setItem(row, 1, QTableWidgetItem(info.name))
            combo = QComboBox(self._table)
            combo.setProperty("btnRole", "compact")
            combo.addItem("忽略", _LEVEL_IGNORE)
            for level in range(1, 7):
                combo.addItem("标题 {0}".format(level), level)
            preset = current.get(info.style_id, _LEVEL_IGNORE)
            index = combo.findData(preset)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(self._refresh_error)
            self._table.setCellWidget(row, 2, combo)

        self._error = QLabel("", self)
        self._error.setProperty("statusTone", "failure")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(self)
        self._ok_button = buttons.addButton(
            QDialogButtonBox.StandardButton.Ok
        )
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_error()

    def _mapping(self) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        for row, info in enumerate(self._styles):
            combo = self._table.cellWidget(row, 2)
            if combo is None:
                continue
            level = combo.currentData()
            if isinstance(level, int) and level != _LEVEL_IGNORE:
                mapping[info.style_id] = level
        return mapping

    def _refresh_error(self, *_args) -> None:
        errors = validate_style_map(self._mapping())
        self._error.setText("\n".join(errors))
        self._ok_button.setEnabled(not errors)

    def _on_accept(self) -> None:
        errors = validate_style_map(self._mapping())
        if errors:
            self._error.setText("\n".join(errors))
            return
        self.accept()

    def mapping(self) -> Dict[str, int]:
        """ accept 后的「样式ID→级别」映射（未选择级别 1 时为空）。"""
        mapping = self._mapping()
        return mapping if 1 in mapping.values() else {}
