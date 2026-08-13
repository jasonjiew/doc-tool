# -*- coding: utf-8 -*-
"""空状态页：新建项目 / 打开项目 / 最近项目入口。"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.project_service import RecentEntry


class EmptyState(QWidget):
    """无项目时的首屏。"""

    def __init__(
        self,
        *,
        on_new_project: Optional[Callable[[], None]] = None,
        on_open_project: Optional[Callable[[], None]] = None,
        on_open_recent: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_new_project = on_new_project
        self._on_open_project = on_open_project
        self._on_open_recent = on_open_recent
        self._buttons: List[QPushButton] = []
        self._recent_buttons: List[QPushButton] = []
        self._empty_label: Optional[QLabel] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 56, 48, 40)
        layout.setSpacing(10)

        from doc_tool.domain.branding import PRODUCT_DESCRIPTION_UI

        title = QLabel(PRODUCT_DESCRIPTION_UI, self)
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "新建或打开项目后，可在 IDE 工作台完成校验、构建、合并和产物查看。",
            self,
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(subtitle)

        actions = QFrame(self)
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(0, 16, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        new_btn = QPushButton("新建项目…", actions)
        new_btn.setProperty("btnRole", "primary")
        new_btn.clicked.connect(self._handle_new)
        actions_layout.addWidget(new_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._buttons.append(new_btn)

        open_btn = QPushButton("打开项目…", actions)
        open_btn.setProperty("btnRole", "secondary")
        open_btn.clicked.connect(self._handle_open)
        actions_layout.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._buttons.append(open_btn)

        layout.addWidget(actions)

        recent_title = QLabel("最近项目", self)
        recent_title.setObjectName("recentTitle")
        layout.addWidget(recent_title)

        self._recent_frame = QFrame(self)
        self._recent_layout = QVBoxLayout(self._recent_frame)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(4)
        layout.addWidget(self._recent_frame)
        layout.addStretch(1)

    def set_recent_projects(self, entries: List[RecentEntry], enabled: bool = True) -> None:
        """渲染最近项目列表（最多 5 条）。"""
        old_recent = self._recent_buttons
        self._recent_buttons = []
        self._buttons = [b for b in self._buttons if b not in old_recent]
        for button in old_recent:
            button.deleteLater()
        # 清除上次的空提示标签：它不在 _recent_buttons 里，不清理会在多次刷新
        # 时叠加，且出现最近项目后旧空标签仍残留。
        if self._empty_label is not None:
            self._empty_label.deleteLater()
            self._empty_label = None
        if not entries:
            self._empty_label = QLabel(
                "暂无有效最近项目，可从上方新建或打开。", self._recent_frame
            )
            self._empty_label.setObjectName("statusMuted")
            self._recent_layout.addWidget(self._empty_label)
            return
        for entry in entries[:5]:
            label = entry.document_name or entry.name
            button = QPushButton(
                "{0}\n{1}".format(label, entry.path), self._recent_frame
            )
            button.setProperty("btnRole", "secondary")
            button.setToolTip(entry.path)
            button.setEnabled(enabled)
            button.clicked.connect(
                lambda _=False, p=entry.path: self._handle_recent(p)
            )
            self._recent_layout.addWidget(button)
            self._recent_buttons.append(button)
            self._buttons.append(button)

    def set_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    # --- 事件转发 ---

    def _handle_new(self) -> None:
        if self._on_new_project is not None:
            self._on_new_project()

    def _handle_open(self) -> None:
        if self._on_open_project is not None:
            self._on_open_project()

    def _handle_recent(self, path: str) -> None:
        if self._on_open_recent is not None:
            self._on_open_recent(path)
