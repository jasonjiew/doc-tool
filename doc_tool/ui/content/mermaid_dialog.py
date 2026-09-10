# -*- coding: utf-8 -*-
"""Mermaid 图形工作台对话框。"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPixmap, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.mermaid import detect_kind, render, validate

_MERMAID_TEMPLATES = {
    "流程图 (Flowchart TD)": "flowchart TD\n    A[开始] --> B{判断条件}\n    B -- 是 --> C[执行处理]\n    B -- 否 --> D[跳过处理]\n    C --> E[结束]\n    D --> E",
    "流程图 (Flowchart LR)": "flowchart LR\n    Client[客户端] --> Gateway[API网关] --> Service[业务服务] --> DB[(数据库)]",
    "时序图 (Sequence)": "sequenceDiagram\n    autonumber\n    actor 用户\n    participant 前端\n    participant 后端\n    用户->>前端: 点击操作\n    前端->>后端: 发送请求\n    后端-->>前端: 返回结果\n    前端-->>用户: 界面更新",
    "类图 (Class)": "classDiagram\n    class Animal {\n        +String name\n        +makeSound()\n    }\n    class Dog {\n        +bark()\n    }\n    Animal <|-- Dog",
    "状态图 (State)": "stateDiagram-v2\n    [*] --> 待处理\n    待处理 --> 处理中: 开始\n    处理中 --> 已完成: 成功\n    处理中 --> 失败: 异常\n    失败 --> 待处理: 重试\n    已完成 --> [*]",
    "实体关系图 (ER)": "erDiagram\n    CUSTOMER ||--o{ ORDER : places\n    ORDER ||--|{ LINE-ITEM : contains\n    CUSTOMER }|..|{ DELIVERY-ADDRESS : uses",
    "甘特图 (Gantt)": "gantt\n    title 项目里程碑排期\n    dateFormat YYYY-MM-DD\n    section 规划\n    需求调研   :done,    des1, 2026-09-01,2026-09-05\n    架构评审   :active,  des2, 2026-09-06, 5d\n    section 开发\n    核心模块   :         des3, after des2, 10d",
    "饼图 (Pie)": 'pie title 模块代码覆盖率\n    "已覆盖" : 85\n    "未覆盖" : 15',
    "思维导图 (Mindmap)": "mindmap\n  root((系统架构))\n    前端展现\n      编辑器\n      图形工作台\n    后端内核\n      Markdown解析\n      Mermaid校验\n      Word构建",
    "时间线 (Timeline)": "timeline\n    title 技术演进历程\n    2024 : 概念验证 : 架构设计\n    2025 : 核心功能上线 : 自动化构建\n    2026 : 全流程合规 : 深度渲染优化",
    "Git分支图 (GitGraph)": "gitGraph\n    commit\n    branch feature\n    checkout feature\n    commit\n    commit\n    checkout main\n    merge feature\n    commit",
}


class MermaidDialog(QDialog):
    """源码编辑、按行错误定位、去抖实时预览、缩放查看与导出动作选择。"""

    def __init__(self, source: str = "flowchart TD\n  A[开始] --> B[结束]", *, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mermaid 图形工作台")
        self.resize(1000, 660)
        self.action = ""
        self.render_result = None
        self._current_pixmap: QPixmap | None = None
        self._zoom_factor: float = 1.0
        self._fit_mode: bool = True

        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Mermaid 源码", left))
        top_bar.addStretch()
        top_bar.addWidget(QLabel("示例模板：", left))
        self.template_combo = QComboBox(left)
        self.template_combo.addItem("选择示例模板…")
        for title in _MERMAID_TEMPLATES:
            self.template_combo.addItem(title)
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        top_bar.addWidget(self.template_combo)
        left_layout.addLayout(top_bar)

        self.source_edit = QPlainTextEdit(left)
        self.source_edit.setPlainText(source)
        left_layout.addWidget(self.source_edit, 2)
        left_layout.addWidget(QLabel("语法诊断与问题定位（双击定位到对应行）", left))
        self.errors = QListWidget(left)
        self.errors.itemActivated.connect(self._locate_error)
        left_layout.addWidget(self.errors, 1)
        splitter.addWidget(left)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("实时效果预览", right))
        preview_header.addStretch()

        self.zoom_out_btn = QPushButton("-", right)
        self.zoom_out_btn.setToolTip("缩小 (Ctrl+滚轮向下)")
        self.zoom_out_btn.setFixedWidth(28)
        self.zoom_out_btn.clicked.connect(self._zoom_out)

        self.zoom_label = QLabel("100%", right)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setFixedWidth(48)

        self.zoom_in_btn = QPushButton("+", right)
        self.zoom_in_btn.setToolTip("放大 (Ctrl+滚轮向上)")
        self.zoom_in_btn.setFixedWidth(28)
        self.zoom_in_btn.clicked.connect(self._zoom_in)

        self.fit_btn = QPushButton("适应窗口", right)
        self.fit_btn.setToolTip("按窗口自适应缩放")
        self.fit_btn.clicked.connect(self._fit_to_window)

        self.reset_btn = QPushButton("1:1", right)
        self.reset_btn.setToolTip("恢复原始 1:1 像素大小")
        self.reset_btn.clicked.connect(self._reset_zoom)

        preview_header.addWidget(self.zoom_out_btn)
        preview_header.addWidget(self.zoom_label)
        preview_header.addWidget(self.zoom_in_btn)
        preview_header.addWidget(self.fit_btn)
        preview_header.addWidget(self.reset_btn)
        right_layout.addLayout(preview_header)

        self.scroll_area = QScrollArea(right)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("QScrollArea { background: #f8fafc; border: 1px solid #d7dee8; }")

        self.preview = QLabel("正在渲染…", self.scroll_area)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(360, 320)
        self.preview.setStyleSheet("QLabel { background: white; border: 1px solid #d7dee8; }")
        self.scroll_area.setWidget(self.preview)

        self.scroll_area.viewport().installEventFilter(self)
        self.preview.installEventFilter(self)

        right_layout.addWidget(self.scroll_area, 1)
        splitter.addWidget(right)
        splitter.setSizes([480, 520])
        outer.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.status = QLabel("", self)
        self.status.setObjectName("statusMuted")
        actions.addWidget(self.status, 1)
        insert_btn = QPushButton("插入 Word", self)
        insert_btn.setProperty("btnRole", "primary")
        insert_btn.setToolTip("生成高清图片并插入 Word 引用标记 (Ctrl+Enter)")
        insert_btn.clicked.connect(lambda: self._finish("insert"))
        actions.addWidget(insert_btn)
        QShortcut(QKeySequence("Ctrl+Return"), self, lambda: self._finish("insert"))
        QShortcut(QKeySequence("Ctrl+Enter"), self, lambda: self._finish("insert"))
        QShortcut(QKeySequence("Ctrl+="), self, self._zoom_in)
        QShortcut(QKeySequence("Ctrl++"), self, self._zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self._zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self._fit_to_window)
        QShortcut(QKeySequence("Ctrl+1"), self, self._reset_zoom)
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

    def _on_template_selected(self, index: int) -> None:
        if index <= 0:
            return
        key = self.template_combo.itemText(index)
        content = _MERMAID_TEMPLATES.get(key)
        if content:
            self.source_edit.setPlainText(content)
        self.template_combo.setCurrentIndex(0)

    def source(self) -> str:
        return self.source_edit.toPlainText()

    def refresh_preview(self) -> None:
        source = self.source()
        issues = validate(source)
        self.errors.clear()

        # 波浪线标记源码错误行
        selections: List[QTextEdit.ExtraSelection] = []
        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        fmt.setUnderlineColor(QColor("#e03131"))

        for issue in issues:
            item = QListWidgetItem("第 {0} 行：{1}".format(issue.line, issue.message))
            item.setData(Qt.ItemDataRole.UserRole, issue.line)
            self.errors.addItem(item)

            block = self.source_edit.document().findBlockByNumber(max(0, issue.line - 1))
            if block.isValid():
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)

        self.source_edit.setExtraSelections(selections)

        if issues:
            self.render_result = None
            self._current_pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setMinimumSize(0, 0)
            self.preview.setMaximumSize(16777215, 16777215)
            self.preview.setStyleSheet(
                "QLabel { background: #fff5f5; color: #c92a2a; border: 1px solid #ffc9c9; padding: 16px; font-size: 10pt; }"
            )
            self.preview.setText(
                "⚠ 语法存在错误，无法预览：\n\n"
                + "\n".join(item.text() for item in [self.errors.item(i) for i in range(self.errors.count())])
            )
            self.status.setText("⚠ 发现 {0} 个语法问题（双击列表可定位到行）".format(len(issues)))
            self.zoom_label.setText("100%")
            return

        actual = detect_kind(source)
        # 实时预览：flowchart/sequenceDiagram 内置快速渲染；其它类型若有 CLI 则走 CLI
        if actual in ("flowchart", "sequenceDiagram"):
            result = render(source, use_cli=False)
        else:
            result = render(source, use_cli=True)

        self.render_result = result
        if not result.ok or (not result.png and not result.svg):
            self._current_pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setMinimumSize(0, 0)
            self.preview.setMaximumSize(16777215, 16777215)
            if "需要启用 mermaid-cli" in (result.error or "") or "未安装" in (result.error or ""):
                self.preview.setStyleSheet(
                    "QLabel { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 16px; font-size: 10pt; }"
                )
                self.preview.setText(
                    "✅ 语法校验通过（{0} 格式完全正确）\n\n"
                    "当前图表类型依赖 mermaid-cli 渲染器生成高保真图片。\n"
                    "已通过静态语法校验，插入 Word 或构建时将自动调用 CLI 渲染。".format(actual)
                )
                self.status.setText("✅ 语法有效 · {0}".format(actual))
            else:
                self.preview.setStyleSheet(
                    "QLabel { background: #fff5f5; color: #c92a2a; border: 1px solid #ffc9c9; padding: 16px; }"
                )
                self.preview.setText("渲染失败：{0}".format(result.error or "未知原因"))
                self.status.setText(result.error or "渲染失败")
            self.zoom_label.setText("100%")
            return

        pixmap = QPixmap()
        if result.png:
            pixmap.loadFromData(result.png, "PNG")
        elif result.svg:
            pixmap.loadFromData(result.svg, "SVG")
        self._current_pixmap = pixmap
        self.preview.setStyleSheet("QLabel { background: white; border: 1px solid #d7dee8; }")
        self.preview.setText("")
        self._update_pixmap_display()
        self.status.setText("✅ 渲染成功 · {0} · {1} · {2}×{3}".format(actual, result.backend, result.width, result.height))

    def eventFilter(self, watched, event) -> bool:
        if watched in (self.scroll_area.viewport(), self.preview):
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    num_degrees = event.angleDelta().y()
                    if num_degrees > 0:
                        self._zoom_in()
                    elif num_degrees < 0:
                        self._zoom_out()
                    return True
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                if self._fit_mode or abs(self._zoom_factor - 1.0) > 0.05:
                    self._reset_zoom()
                else:
                    self._fit_to_window()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode and self._current_pixmap and not self._current_pixmap.isNull():
            self._update_pixmap_display()

    def _zoom_in(self) -> None:
        if not self._current_pixmap or self._current_pixmap.isNull():
            return
        self._fit_mode = False
        self._zoom_factor = min(5.0, round(self._zoom_factor * 1.25, 2))
        self._update_pixmap_display()

    def _zoom_out(self) -> None:
        if not self._current_pixmap or self._current_pixmap.isNull():
            return
        self._fit_mode = False
        self._zoom_factor = max(0.2, round(self._zoom_factor * 0.8, 2))
        self._update_pixmap_display()

    def _fit_to_window(self) -> None:
        if not self._current_pixmap or self._current_pixmap.isNull():
            return
        self._fit_mode = True
        self._update_pixmap_display()

    def _reset_zoom(self) -> None:
        if not self._current_pixmap or self._current_pixmap.isNull():
            return
        self._fit_mode = False
        self._zoom_factor = 1.0
        self._update_pixmap_display()

    def _update_pixmap_display(self) -> None:
        if not self._current_pixmap or self._current_pixmap.isNull():
            return
        if self._fit_mode:
            avail_w = max(100, self.scroll_area.viewport().width() - 24)
            avail_h = max(100, self.scroll_area.viewport().height() - 24)
            scale_w = avail_w / self._current_pixmap.width() if self._current_pixmap.width() > 0 else 1.0
            scale_h = avail_h / self._current_pixmap.height() if self._current_pixmap.height() > 0 else 1.0
            scale = min(1.0, scale_w, scale_h)
            target_w = max(10, int(self._current_pixmap.width() * scale))
            target_h = max(10, int(self._current_pixmap.height() * scale))
            scaled = self._current_pixmap.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(scaled)
            self.preview.setFixedSize(scaled.size())
            if self._current_pixmap.width() > 0:
                pct = int((scaled.width() / self._current_pixmap.width()) * 100)
                self.zoom_label.setText(f"{pct}%")
        else:
            target_w = max(20, int(self._current_pixmap.width() * self._zoom_factor))
            target_h = max(20, int(self._current_pixmap.height() * self._zoom_factor))
            scaled = self._current_pixmap.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(scaled)
            self.preview.setFixedSize(scaled.size())
            self.zoom_label.setText(f"{int(self._zoom_factor * 100)}%")

    def _locate_error(self, item) -> None:
        line = int(item.data(Qt.ItemDataRole.UserRole) or 1)
        block = self.source_edit.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            self.source_edit.setTextCursor(cursor)
            self.source_edit.centerCursor()
            self.source_edit.setFocus()

    def _finish(self, action: str) -> None:
        """导出动作：重新用 mermaid-cli（若可用）渲染，保证与官方效果一致。"""
        source = self.source()
        issues = validate(source)
        if issues:
            self.status.setText("⚠ 源码存在 {0} 处语法错误，请先修复后再继续".format(len(issues)))
            return
        # 实时预览用内置渲染器（快），导出用 mermaid-cli 官方渲染；未安装时自动回退。
        result = render(source, use_cli=True)
        if not result.ok or not result.png:
            self.status.setText("渲染失败：{0}".format(result.error or "未知原因"))
            return
        self.render_result = result
        if result.backend == "mermaid-cli":
            self.status.setText("已用 mermaid-cli 渲染，可插入 Word")
        else:
            self.status.setText("未检测到 mermaid-cli，已用内置渲染器（近似效果）；安装 mermaid-cli 后导出自动升级为官方渲染")
        self.action = action
        self.accept()
