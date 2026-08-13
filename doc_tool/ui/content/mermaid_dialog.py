# -*- coding: utf-8 -*-
"""Mermaid 图形工作台对话框。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.mermaid import render, validate


class MermaidDialog(QDialog):
    """源码编辑、按行错误、去抖实时预览和导出动作选择。"""

    def __init__(self, source: str = "flowchart TD\n  A[开始] --> B[结束]", *, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mermaid 图形工作台")
        self.resize(920, 620)
        self.action = ""
        self.render_result = None

        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Mermaid 源码", left))
        self.source_edit = QPlainTextEdit(left)
        self.source_edit.setPlainText(source)
        left_layout.addWidget(self.source_edit, 2)
        left_layout.addWidget(QLabel("语法问题（双击定位）", left))
        self.errors = QListWidget(left)
        self.errors.itemActivated.connect(self._locate_error)
        left_layout.addWidget(self.errors, 1)
        splitter.addWidget(left)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("实时预览（近似效果）", right))
        self.preview = QLabel("正在渲染…", right)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(360, 320)
        self.preview.setStyleSheet("QLabel { background: white; border: 1px solid #d7dee8; }")
        right_layout.addWidget(self.preview, 1)
        splitter.addWidget(right)
        splitter.setSizes([460, 460])
        outer.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.status = QLabel("", self)
        self.status.setObjectName("statusMuted")
        actions.addWidget(self.status, 1)
        insert_btn = QPushButton("插入 Word", self)
        insert_btn.setProperty("btnRole", "primary")
        insert_btn.clicked.connect(lambda: self._finish("insert"))
        actions.addWidget(insert_btn)
        replace_btn = QPushButton("转换并替换源码", self)
        replace_btn.setProperty("btnRole", "secondary")
        replace_btn.clicked.connect(lambda: self._finish("replace"))
        actions.addWidget(replace_btn)
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        outer.addLayout(actions)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.refresh_preview)
        self.source_edit.textChanged.connect(lambda: self._timer.start())
        QTimer.singleShot(0, self.refresh_preview)

    def source(self) -> str:
        return self.source_edit.toPlainText()

    def refresh_preview(self) -> None:
        source = self.source()
        issues = validate(source)
        self.errors.clear()
        for issue in issues:
            item = QListWidgetItem("第 {0} 行：{1}".format(issue.line, issue.message))
            item.setData(Qt.ItemDataRole.UserRole, issue.line)
            self.errors.addItem(item)
        if issues:
            self.render_result = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("无法预览：\n" + "\n".join(item.text() for item in [self.errors.item(i) for i in range(self.errors.count())]))
            self.status.setText("发现 {0} 个语法问题".format(len(issues)))
            return
        # 实时预览必须用内置渲染器（use_cli=False）：mmdc 子进程最长阻塞 30s，
        # 在 UI 线程同步跑会让对话框每输入一次冻结一次；内置渲染器即时返回，
        # 与「实时预览（近似效果）」的定位一致。
        result = render(source, use_cli=False)
        self.render_result = result
        if not result.ok or not result.png:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("渲染失败：{0}".format(result.error or "未知原因"))
            self.status.setText(result.error or "渲染失败")
            return
        pixmap = QPixmap()
        pixmap.loadFromData(result.png, "PNG")
        self.preview.setText("")
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.status.setText("渲染成功 · {0} · {1}×{2}".format(result.backend, result.width, result.height))

    def _locate_error(self, item) -> None:
        line = int(item.data(Qt.ItemDataRole.UserRole) or 1)
        block = self.source_edit.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            cursor = QTextCursor(block)
            self.source_edit.setTextCursor(cursor)
            self.source_edit.centerCursor()
            self.source_edit.setFocus()

    def _finish(self, action: str) -> None:
        self.refresh_preview()
        if self.render_result is None or not self.render_result.ok or not self.render_result.png:
            self.status.setText("请先修复语法或渲染错误")
            return
        self.action = action
        self.accept()
