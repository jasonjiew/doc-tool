# -*- coding: utf-8 -*-
"""Mermaid 图形工作台对话框。"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
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
    """源码编辑、按行错误定位、去抖实时预览和导出动作选择。"""

    def __init__(self, source: str = "flowchart TD\n  A[开始] --> B[结束]", *, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mermaid 图形工作台")
        self.resize(960, 640)
        self.action = ""
        self.render_result = None

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
        right_layout.addWidget(QLabel("实时效果预览", right))
        self.preview = QLabel("正在渲染…", right)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(360, 320)
        self.preview.setStyleSheet("QLabel { background: white; border: 1px solid #d7dee8; }")
        right_layout.addWidget(self.preview, 1)
        splitter.addWidget(right)
        splitter.setSizes([480, 480])
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
            self.preview.setPixmap(QPixmap())
            self.preview.setStyleSheet(
                "QLabel { background: #fff5f5; color: #c92a2a; border: 1px solid #ffc9c9; padding: 16px; font-size: 10pt; }"
            )
            self.preview.setText(
                "⚠ 语法存在错误，无法预览：\n\n"
                + "\n".join(item.text() for item in [self.errors.item(i) for i in range(self.errors.count())])
            )
            self.status.setText("⚠ 发现 {0} 个语法问题（双击列表可定位到行）".format(len(issues)))
            return

        actual = detect_kind(source)
        # 实时预览：flowchart/sequenceDiagram 内置快速渲染；其它类型若有 CLI 则走 CLI
        if actual in ("flowchart", "sequenceDiagram"):
            result = render(source, use_cli=False)
        else:
            result = render(source, use_cli=True)

        self.render_result = result
        if not result.ok or not result.png:
            self.preview.setPixmap(QPixmap())
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
            return

        pixmap = QPixmap()
        pixmap.loadFromData(result.png, "PNG")
        self.preview.setStyleSheet("QLabel { background: white; border: 1px solid #d7dee8; }")
        self.preview.setText("")
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.status.setText("✅ 渲染成功 · {0} · {1} · {2}×{3}".format(actual, result.backend, result.width, result.height))

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
