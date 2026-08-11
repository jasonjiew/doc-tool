# -*- coding: utf-8 -*-
"""关于/环境诊断对话框（PySide6）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


def format_diagnostic_info(info: dict, report) -> str:
    """生成可复制的纯文本环境诊断信息。"""
    labels = [
        ("应用版本", "appVersion"),
        ("提交标识", "commit"),
        ("项目模式版本", "projectSchemaVersion"),
        ("Python", "python"),
        ("平台", "platform"),
        ("架构", "machine"),
    ]
    lines = ["康尚文档工具 - 环境诊断"]
    lines.extend(
        "{0}：{1}".format(label, info.get(key, "—"))
        for label, key in labels
    )
    lines.extend([
        "Microsoft Word：{0}".format(
            "可用" + (
                "（版本 {0}）".format(report.version)
                if report.available and report.version
                else ""
            )
            if report.available
            else "未检测到"
        ),
        "pywin32：{0}".format(
            "已安装" if report.pywin32_available else "未安装"
        ),
        "交互式会话：{0}".format(
            "是" if report.interactive_session else "否"
        ),
    ])
    if report.reasons:
        lines.append("原因：")
        lines.extend("- {0}".format(reason) for reason in report.reasons)
    return "\n".join(lines)


def show_about_dialog(parent) -> None:
    """显示关于/环境诊断对话框。"""
    from PySide6.QtGui import QGuiApplication

    from doc_tool.domain.version import APP_VERSION, get_build_info

    dialog = QDialog(parent)
    dialog.setWindowTitle("关于 / 环境诊断")
    dialog.resize(520, 460)
    dialog.setMinimumSize(420, 380)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)

    title = QLabel("康尚文档工具", dialog)
    title.setObjectName("welcomeTitle")
    layout.addWidget(title)
    version = QLabel("版本 {0}".format(APP_VERSION), dialog)
    layout.addWidget(version)

    info = get_build_info()

    info_frame = QFrame(dialog)
    info_frame.setProperty("card", True)
    info_layout = QVBoxLayout(info_frame)
    info_layout.setContentsMargins(8, 8, 8, 8)
    info_layout.setSpacing(2)
    for label, key in [
        ("应用版本", "appVersion"),
        ("提交标识", "commit"),
        ("项目模式版本", "projectSchemaVersion"),
        ("Python", "python"),
        ("平台", "platform"),
        ("架构", "machine"),
    ]:
        row = QLabel("{0}：{1}".format(label, info.get(key, "—")), info_frame)
        row.setObjectName("statusMuted")
        info_layout.addWidget(row)
    layout.addWidget(info_frame)

    # Word 可用性（综合检查，含交互式会话；不实际启动 Word 进程）
    from doc_tool.application.word_check import check_word_available

    report = check_word_available(dispatch_check=False)

    word_frame = QFrame(dialog)
    word_frame.setProperty("card", True)
    word_layout = QVBoxLayout(word_frame)
    word_layout.setContentsMargins(8, 8, 8, 8)
    word_layout.setSpacing(2)

    word_text = "可用"
    tone = "success"
    if report.available:
        if report.version:
            word_text = "可用（版本 {0}）".format(report.version)
    else:
        word_text = "未检测到"
        tone = "failure"
    word_title = QLabel("Microsoft Word：{0}".format(word_text), word_frame)
    word_title.setProperty("statusTone", tone)
    word_layout.addWidget(word_title)

    detail = QLabel(
        "  • pywin32：{0}    • 交互式会话：{1}".format(
            "已安装" if report.pywin32_available else "未安装",
            "是" if report.interactive_session else "否",
        ),
        word_frame,
    )
    detail.setObjectName("statusMuted")
    word_layout.addWidget(detail)

    if not report.available:
        note = QLabel(
            "正式合并需要本机安装 Microsoft Word 并在交互式会话中运行；\n"
            "可使用「诊断构建」进行无 Word 测试。",
            word_frame,
        )
        note.setObjectName("statusMuted")
        note.setWordWrap(True)
        word_layout.addWidget(note)
        if report.reasons:
            for reason in report.reasons:
                reason_label = QLabel("  • {0}".format(reason), word_frame)
                reason_label.setObjectName("statusMuted")
                reason_label.setWordWrap(True)
                word_layout.addWidget(reason_label)
    layout.addWidget(word_frame)

    # 操作按钮
    button_row = QHBoxLayout()
    copied_label = QLabel("", dialog)
    copied_label.setProperty("statusTone", "success")
    button_row.addWidget(copied_label)
    button_row.addStretch(1)

    diagnostic_text = format_diagnostic_info(info, report)
    copy_action = QAction(dialog)
    copy_action.setShortcut(QKeySequence("Ctrl+C"))

    def copy_diagnostics() -> None:
        QGuiApplication.clipboard().setText(diagnostic_text)
        copied_label.setText("已复制诊断信息")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(2000, lambda: copied_label.setText(""))

    copy_btn = QPushButton("复制诊断信息", dialog)
    copy_btn.setProperty("btnRole", "secondary")
    copy_btn.clicked.connect(copy_diagnostics)
    button_row.addWidget(copy_btn)

    close_btn = QPushButton("关闭", dialog)
    close_btn.setProperty("btnRole", "primary")
    close_btn.clicked.connect(dialog.accept)
    button_row.addWidget(close_btn)
    layout.addLayout(button_row)

    dialog.exec()
