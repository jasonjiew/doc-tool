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
    from doc_tool.domain.branding import APP_DISPLAY_NAME

    labels = [
        ("应用版本", "appVersion"),
        ("提交标识", "commit"),
        ("项目模式版本", "projectSchemaVersion"),
        ("Python", "python"),
        ("平台", "platform"),
        ("架构", "machine"),
    ]
    lines = ["{0} - 环境诊断".format(APP_DISPLAY_NAME)]
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

    from doc_tool.domain.branding import APP_DISPLAY_NAME
    from doc_tool.domain.version import APP_VERSION, get_build_info

    dialog = QDialog(parent)
    dialog.setWindowTitle("关于 / 环境诊断")
    dialog.resize(520, 460)
    dialog.setMinimumSize(420, 380)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(8)

    title = QLabel(APP_DISPLAY_NAME, dialog)
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

        # 定时器必须挂到 dialog 下：孤儿 singleShot 在对话框关闭后 2 秒内
        # 回调会访问已销毁的 copied_label，抛 RuntimeError。
        if copy_diagnostics._clear_timer is None:
            timer = QTimer(dialog)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: copied_label.setText(""))
            copy_diagnostics._clear_timer = timer
        copy_diagnostics._clear_timer.start(2000)

    copy_diagnostics._clear_timer = None


    # 检查更新按钮与状态
    check_update_btn = QPushButton("检查更新…", dialog)
    check_update_btn.setProperty("btnRole", "secondary")

    update_status_label = QLabel("", dialog)
    update_status_label.setObjectName("updateStatusLabel")

    def _do_check():
        update_status_label.setText("\u6b63\u5728\u68c0\u67e5\u66f4\u65b0\u2026")
        check_update_btn.setEnabled(False)
        from doc_tool.application.updater import check_for_updates, UpdateCheckResult
        import threading
        from PySide6.QtCore import QTimer

        def _bg():
            try:
                res = check_for_updates(force=True)
            except Exception as exc:
                res = UpdateCheckResult(error=str(exc))

            def _update_ui():
                try:
                    check_update_btn.setEnabled(True)
                    if res.error:
                        update_status_label.setText(f"\u68c0\u67e5\u5931\u8d25: {res.error}")
                    elif res.has_update and res.manifest:
                        update_status_label.setText(f"\u53d1\u73b0\u65b0\u7248\u672c v{res.manifest.version}\uff01")
                        show_update_dialog(
                            dialog,
                            res.manifest,
                            on_upgrade_confirmed=getattr(parent, "_perform_upgrade", None),
                        )
                    else:
                        update_status_label.setText("\u5f53\u524d\u5df2\u662f\u6700\u65b0\u7248\u672c")
                except RuntimeError:
                    pass

            QTimer.singleShot(0, dialog, _update_ui)

        threading.Thread(target=_bg, daemon=True).start()

    check_update_btn.clicked.connect(_do_check)
    button_row.addWidget(update_status_label)
    button_row.addWidget(check_update_btn)

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


def show_update_dialog(parent, manifest, on_upgrade_confirmed=None) -> None:
    """显示版本更新提示与 Release Notes 预览弹窗。"""
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QFrame
    )
    from doc_tool.application.updater import skip_version

    dialog = QDialog(parent)
    dialog.setWindowTitle(f"发现新版本 - v{manifest.version}")
    dialog.resize(500, 420)
    dialog.setMinimumSize(400, 320)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    title_label = QLabel(f"发现 Doc Tool 新版本 v{manifest.version}！", dialog)
    title_label.setObjectName("welcomeTitle")
    layout.addWidget(title_label)

    if manifest.release_notes:
        notes_frame = QFrame(dialog)
        notes_frame.setProperty("card", True)
        n_layout = QVBoxLayout(notes_frame)
        n_layout.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel("更新说明：", notes_frame)
        lbl.setObjectName("statusMuted")
        n_layout.addWidget(lbl)
        notes_edit = QTextEdit(notes_frame)
        notes_edit.setReadOnly(True)
        notes_edit.setPlainText(manifest.release_notes)
        n_layout.addWidget(notes_edit)
        layout.addWidget(notes_frame)

    btn_row = QHBoxLayout()
    skip_btn = QPushButton("跳过此版本", dialog)
    skip_btn.setProperty("btnRole", "secondary")

    def _on_skip():
        skip_version(manifest.version)
        dialog.reject()

    skip_btn.clicked.connect(_on_skip)
    btn_row.addWidget(skip_btn)
    btn_row.addStretch(1)

    later_btn = QPushButton("稍后提示", dialog)
    later_btn.clicked.connect(dialog.reject)
    btn_row.addWidget(later_btn)

    upgrade_btn = QPushButton("立即升级并重启", dialog)
    upgrade_btn.setProperty("btnRole", "primary")

    def _on_upgrade():
        dialog.accept()
        if on_upgrade_confirmed:
            on_upgrade_confirmed(manifest)

    upgrade_btn.clicked.connect(_on_upgrade)
    btn_row.addWidget(upgrade_btn)

    layout.addLayout(btn_row)
    dialog.exec()
