# -*- coding: utf-8 -*-
"""Codex 式步骤清单组件（右侧任务/结果 Dock）。

由 ``derive_step_list`` 生成的 ``StepItem`` 渲染：每个步骤显示字形图标 +
中文标签 + 状态文字，状态不依赖纯颜色（高对比度主题仍可读）。当前步骤
高亮；底部显示总体进度（完成步骤数/总步骤数）与已用时间。心跳任务只
显示单个进行中步骤，不伪造百分比。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from doc_tool.ui.styles import SEMANTIC_COLORS, SEMANTIC_COLORS_DARK
from doc_tool.ui.workbench_state import (
    STEP_STATUS_CANCELLED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SKIPPED,
    STEP_STATUS_SUCCESS,
    StepItem,
)

# 状态字形：字形 + 文字共同表达状态，颜色仅为辅助。
_GLYPHS = {
    STEP_STATUS_PENDING: "○",
    STEP_STATUS_RUNNING: "▶",
    STEP_STATUS_SUCCESS: "✓",
    STEP_STATUS_SKIPPED: "—",
    STEP_STATUS_FAILED: "✗",
    STEP_STATUS_CANCELLED: "⊘",
}

_STATUS_TEXT = {
    STEP_STATUS_PENDING: "",
    STEP_STATUS_RUNNING: "进行中",
    STEP_STATUS_SUCCESS: "成功",
    STEP_STATUS_SKIPPED: "已跳过",
    STEP_STATUS_FAILED: "失败",
    STEP_STATUS_CANCELLED: "已取消",
}


def _semantic_color(status: str, dark: bool = False) -> str:
    """把步骤状态映射为语义色（仅辅助，不承担唯一表达）。"""
    table = {
        STEP_STATUS_SUCCESS: "success",
        STEP_STATUS_FAILED: "failure",
        STEP_STATUS_CANCELLED: "warning",
        STEP_STATUS_RUNNING: "neutral",
    }
    tone = table.get(status, "neutral")
    colors = SEMANTIC_COLORS_DARK if dark else SEMANTIC_COLORS
    return colors[tone]


class WorkStepList(QListWidget):
    """步骤清单：QListWidget 行 = 一个步骤（字形 + 标签 + 状态文字）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("stepList")
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dark = False

    def set_dark(self, dark: bool) -> None:
        self._dark = dark

    def set_steps(self, steps: List[StepItem], current_stage: str = "") -> None:
        """重建步骤清单；``current_stage`` 为当前进行中阶段（可空）。"""
        self.clear()
        for step in steps:
            status_text = _STATUS_TEXT.get(step.status, "")
            glyph = _GLYPHS.get(step.status, "○")
            label = "{0} {1}".format(glyph, step.label)
            if status_text:
                label += " · {0}".format(status_text)
            if step.detail and step.status in (
                STEP_STATUS_FAILED,
                STEP_STATUS_CANCELLED,
                STEP_STATUS_SKIPPED,
            ):
                label += " — {0}".format(step.detail)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, step.stage)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if step.status == STEP_STATUS_RUNNING:
                item.setBackground(
                    QBrush(QColor(self._running_highlight()))
                )
            item.setForeground(QBrush(QColor(_semantic_color(step.status, self._dark))))
            self.addItem(item)
        if current_stage:
            for row in range(self.count()):
                if self.item(row).data(Qt.ItemDataRole.UserRole) == current_stage:
                    self.scrollToItem(self.item(row))
                    break

    def _running_highlight(self) -> str:
        return "#26334a" if self._dark else "#eff6ff"


class StepListFooter(QWidget):
    """步骤清单底部：总体进度 + 已用时间。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 2)
        layout.setSpacing(4)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._summary_label = QLabel("0/0 步骤", self)
        row.addWidget(self._summary_label)
        row.addStretch(1)
        self._elapsed_label = QLabel("已用时间 00:00", self)
        self._elapsed_label.setObjectName("statusMuted")
        row.addWidget(self._elapsed_label)
        layout.addLayout(row)

    def set_progress(self, done: int, total: int, running_weight: float = 0.0) -> None:
        """总体完成度：完成步骤数 + 进行中步骤插值权重 / 总步骤数。"""
        if total <= 0:
            self._progress.setValue(0)
            self._summary_label.setText("—")
            return
        effective = done + max(0.0, min(0.9, float(running_weight)))
        percent = min(100, max(0, int(round(effective * 100.0 / total))))
        self._progress.setValue(percent)
        self._progress.setFormat("{0}%".format(percent))
        self._summary_label.setText("{0}/{1} 步骤".format(done, total))

    def set_elapsed(self, seconds: int) -> None:
        """设置已用时间（秒）；仅心跳任务也会持续显示。"""
        minutes, sec = divmod(max(0, seconds), 60)
        self._elapsed_label.setText(
            "已用时间 {0:02d}:{1:02d}".format(minutes, sec)
        )
