# -*- coding: utf-8 -*-
"""新建项目向导（PySide6 QWizard）。

向导流程：
1. 选择源 DOCX 文件
2. 执行预检，展示标题/图片/表格计数和告警（阻断告警时不可继续）
3. 选择通用模式或需求/详细设计预设，填写文档信息和目标父目录
4. 执行事务化导入
5. 显示导入结果（成功/失败）

业务步骤与规则与 Tk 版一致，仅替换组件为 ``QWizard``。预检与导入均在
后台线程执行（``TaskRunner``），支持安全取消（阶段边界生效）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from doc_tool.ui.task_bridge import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    ERR_WATCHDOG_TIMEOUT,
    POLL_INTERVAL_MS,
    TaskRunner,
    TaskSpec,
)

PREFLIGHT_TIMEOUT_SECONDS = 90

# 文档类型预设标签。
_DOC_TYPE_LABELS = {
    "general": "通用大文档",
    "requirement": "需求文档预设",
    "design": "详细设计预设",
}


def format_preview_summary(preview) -> str:
    """把 ``ImportPreview`` 转成向导文本；保持为纯函数便于无界面测试。"""
    lines = ["标题计数："]
    for level, count in sorted(preview.heading_level_counts.items()):
        lines.append("  Heading {0}: {1}".format(level, count))
    lines.extend([
        "",
        "图片数量：{0}".format(preview.image_count),
        "表格数量：{0}".format(preview.table_count),
        "",
    ])
    if preview.warnings:
        lines.append("告警：")
        lines.extend("  ⚠ {0}".format(warning) for warning in preview.warnings)
    else:
        lines.append("无告警。")
    suggestion = getattr(preview, "document_type_suggestion", None)
    if suggestion is not None:
        lines.extend([
            "",
            "建议模式：{0}".format(
                _DOC_TYPE_LABELS.get(
                    suggestion.document_type, suggestion.document_type
                )
            ),
            "原因：{0}".format(suggestion.reason),
        ])
    return "\n".join(lines)


class _SourcePage(QWizardPage):
    """步骤 1：选择源 Word 文档。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 1/5：选择源 Word 文档")
        layout = QVBoxLayout(self)
        hint = QLabel(
            "选择要导入的 .docx 文件。文件将被只读复制到项目中，源文件不会被修改。",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        file_row = QHBoxLayout()
        self._source_entry = QLineEdit(self)
        self._source_entry.setReadOnly(True)
        file_row.addWidget(self._source_entry, 1)
        browse_btn = QPushButton("浏览…", self)
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        self._source_path: Optional[str] = None

    def _browse(self) -> None:
        path = QFileDialog.getOpenFileName(
            self, "选择源 Word 文档", "", "Word 文档 (*.docx);;所有文件 (*.*)"
        )[0]
        if path:
            self._source_path = path
            self._source_entry.setText(path)
            wizard = self.wizard()
            source_name = Path(path).stem
            if not getattr(wizard, "_doc_name", "").strip():
                wizard._doc_name = source_name
            if not getattr(wizard, "_project_name", "").strip():
                wizard._project_name = source_name
            self.completeChanged.emit()

    def isComplete(self) -> bool:
        return bool(self._source_path)

    def source_path(self) -> Optional[str]:
        return self._source_path


class _PreflightPage(QWizardPage):
    """步骤 2：导入预检（异步执行并展示结果）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 2/5：导入预检")
        layout = QVBoxLayout(self)
        self._status_label = QLabel("准备中…", self)
        layout.addWidget(self._status_label)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)
        self._preview_text = QPlainTextEdit(self)
        self._preview_text.setReadOnly(True)
        layout.addWidget(self._preview_text, 1)
        self._preview_ok = False

    def initializePage(self) -> None:
        wizard = self.wizard()
        self._preview_ok = False
        self._preview_text.clear()
        self._progress.hide()
        self._status_label.setText("正在预检…")
        wizard._start_preflight(on_done=self._on_preflight_done)

    def _on_preflight_done(self, response) -> None:
        wizard = self.wizard()
        if response is None:
            if wizard._last_error_code == ERR_WATCHDOG_TIMEOUT:
                text = (
                    "预检超时。\n\n建议：请确认源文件未被占用、文件可正常用 Word 打开，然后重试。"
                )
            else:
                text = "预检异常终止。"
            self._preview_ok = False
            self._set_text(text)
        else:
            ok, preview, text = response
            self._preview_ok = bool(ok)
            self._set_text(text)
            wizard._preview = preview
            if ok and preview is not None and preview.document_type_suggestion is not None:
                suggestion = preview.document_type_suggestion
                if suggestion.confidence == "high":
                    wizard._doc_type = suggestion.document_type
        self._status_label.setText("预检完成" if self._preview_ok else "预检未通过")
        self.completeChanged.emit()

    def _set_text(self, text: str) -> None:
        self._preview_text.setPlainText(text)

    def isComplete(self) -> bool:
        return self._preview_ok


class _ProjectInfoPage(QWizardPage):
    """步骤 3：项目信息。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 3/5：项目信息")
        self.setCommitPage(True)
        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        left = QVBoxLayout()

        self._type_radios: dict = {}
        type_label = QLabel("文档类型：", self)
        left.addWidget(type_label)
        for value, text in _DOC_TYPE_LABELS.items():
            radio = QRadioButton(text, self)
            radio.setProperty("docType", value)
            left.addWidget(radio)
            self._type_radios[value] = radio
        self._type_radios["general"].setChecked(True)

        self._doc_no_entry = self._field_row(left, "文档编号（通用可选）：")
        self._doc_name_entry = self._field_row(left, "文档名称：")
        self._doc_version_entry = self._field_row(left, "文档版本（通用可选）：")
        self._project_name_entry = self._field_row(left, "项目目录名：")

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("目标父目录：", self))
        self._target_entry = QLineEdit(self)
        target_row.addWidget(self._target_entry, 1)
        browse_btn = QPushButton("浏览…", self)
        browse_btn.clicked.connect(self._browse_target)
        target_row.addWidget(browse_btn)
        left.addLayout(target_row)
        form.addLayout(left)
        layout.addLayout(form)
        layout.addStretch(1)

    def _field_row(self, layout, text: str) -> QLineEdit:
        layout.addWidget(QLabel(text, self))
        entry = QLineEdit(self)
        layout.addWidget(entry)
        return entry

    def _browse_target(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目标父目录")
        if path:
            self._target_entry.setText(path)
            wizard = self.wizard()
            if not wizard._project_name.strip():
                source_name = Path(wizard._source_path).stem
                wizard._project_name = source_name
                self._project_name_entry.setText(source_name)

    def initializePage(self) -> None:
        wizard = self.wizard()
        self._type_radios.get(wizard._doc_type, self._type_radios["general"]).setChecked(True)
        self._doc_no_entry.setText(wizard._doc_no)
        self._doc_name_entry.setText(wizard._doc_name)
        self._doc_version_entry.setText(wizard._doc_version)
        self._project_name_entry.setText(wizard._project_name)
        self._target_entry.setText(wizard._target_parent)
        wizard.button(QWizard.WizardButton.NextButton).setText("开始导入")

    def validatePage(self) -> bool:
        wizard = self.wizard()
        wizard._doc_type = next(
            (v for v, r in self._type_radios.items() if r.isChecked()), "general"
        )
        wizard._doc_no = self._doc_no_entry.text().strip()
        wizard._doc_name = self._doc_name_entry.text().strip()
        wizard._doc_version = self._doc_version_entry.text().strip()
        wizard._project_name = self._project_name_entry.text().strip()
        wizard._target_parent = self._target_entry.text().strip()
        error = wizard._validate_project_info()
        if error:
            QMessageBox.warning(self, "项目信息无效", error)
            return False
        return True


class _ExecutingPage(QWizardPage):
    """步骤 4：执行导入。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 4/5：正在导入…")
        layout = QVBoxLayout(self)
        self._status_label = QLabel("准备中…", self)
        layout.addWidget(self._status_label)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        layout.addWidget(self._progress)
        self._detail = QLabel("", self)
        self._detail.setObjectName("statusMuted")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)
        layout.addStretch(1)
        self._started = False

    def initializePage(self) -> None:
        wizard = self.wizard()
        self._status_label.setText("正在导入…")
        wizard._do_import(on_done=self._on_done)
        self._started = True

    def _on_done(self, result, target_root: str) -> None:
        wizard = self.wizard()
        if wizard._closing:
            wizard.reject()
            return
        wizard._import_result = result
        wizard._target_root = target_root
        wizard._step4_done = True
        wizard.next()

    def cleanupPage(self) -> None:
        self._started = False


class _ResultPage(QWizardPage):
    """步骤 5：导入结果。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 5/5：导入结果")
        layout = QVBoxLayout(self)
        self._result_label = QLabel(self)
        self._result_label.setObjectName("resultTitle")
        layout.addWidget(self._result_label)
        self._result_detail = QPlainTextEdit(self)
        self._result_detail.setReadOnly(True)
        layout.addWidget(self._result_detail, 1)

    def initializePage(self) -> None:
        wizard = self.wizard()
        self._render(wizard._import_result, wizard._target_root)
        wizard.button(QWizard.WizardButton.NextButton).setText("关闭")
        wizard.button(QWizard.WizardButton.BackButton).setEnabled(False)

    def _render(self, result, target_root: str) -> None:
        if result is None:
            if self.wizard()._last_error_code == ERR_WATCHDOG_TIMEOUT:
                self._result_label.setText("✗ 导入超时")
                self._result_label.setProperty("statusTone", "failure")
                self._result_detail.setPlainText(
                    "导入运行时间超过限制，界面已停止跟踪。\n\n"
                    "请检查目标目录和应用日志；若后台仍占用 Word，请退出应用后重试。"
                )
            else:
                self._result_label.setText("✗ 导入异常终止")
                self._result_label.setProperty("statusTone", "failure")
                self._result_detail.setPlainText("导入线程未返回结果，请查看应用日志。")
        elif result.success:
            self._result_label.setText("✓ 导入成功")
            self._result_label.setProperty("statusTone", "success")
            detail_lines = [
                "项目目录：{0}".format(target_root),
                "源文件指纹：{0}".format(
                    (result.source_sha256 or "")[:12] + "…"
                ),
                "",
                "阶段事件：",
            ]
            for event in result.events:
                detail_lines.append("  {0}: {1}".format(event.stage, event.status))
            self._result_detail.setPlainText("\n".join(detail_lines))
        else:
            cancelled = result.error_code == "E5003"
            self._result_label.setText(
                "⊘ 导入已取消" if cancelled else "✗ 导入失败"
            )
            self._result_label.setProperty(
                "statusTone", "warning" if cancelled else "failure"
            )
            error_lines = [
                "错误码：{0}".format(result.error_code or "未知"),
                "",
                "阶段事件：",
            ]
            for event in result.events:
                line = "  {0}: {1}".format(event.stage, event.status)
                if event.detail:
                    line += " — {0}".format(event.detail)
                if "errorCode" in event.metrics:
                    line += "（{0}）".format(event.metrics["errorCode"])
                error_lines.append(line)
            if result.diagnostic_log:
                error_lines.append("")
                error_lines.append("诊断日志：{0}".format(result.diagnostic_log))
            self._result_detail.setPlainText("\n".join(error_lines))


class ImportWizard(QWizard):
    """新建项目向导（QWizard）。

    返回项目目录路径（成功）或 None（取消）。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建项目向导")
        self.resize(680, 540)
        self.setMinimumSize(520, 440)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        # 共享状态
        self._source_path: Optional[str] = None
        self._preview = None
        self._doc_type = "general"
        self._doc_no = ""
        self._doc_name = ""
        self._doc_version = "1.0"
        self._project_name = ""
        self._target_parent = ""
        self._last_error_code: Optional[str] = None
        self._closing = False
        self._import_result = None
        self._target_root = ""
        self._step4_done = False

        self._runner = TaskRunner()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_runner)

        self._source_page = _SourcePage(self)
        self._preflight_page = _PreflightPage(self)
        self._info_page = _ProjectInfoPage(self)
        self._executing_page = _ExecutingPage(self)
        self._result_page = _ResultPage(self)
        self.addPage(self._source_page)
        self.addPage(self._preflight_page)
        self.addPage(self._info_page)
        self.addPage(self._executing_page)
        self.addPage(self._result_page)

        self.currentIdChanged.connect(self._on_page_changed)
        self.button(QWizard.WizardButton.CancelButton).clicked.connect(
            self._on_cancel_clicked
        )

    def run(self) -> Optional[str]:
        """运行向导，返回项目路径或 None。"""
        if self.exec() == QDialog.DialogCode.Accepted:
            return self._target_root
        return None

    # --- 页面切换 ---

    def _on_page_changed(self, _page_id: int) -> None:
        self.button(QWizard.WizardButton.NextButton).setEnabled(
            self.currentPage().isComplete()
        )
        self.button(QWizard.WizardButton.BackButton).setEnabled(
            self.currentPage().isComplete()
            and self.currentId() not in (0, 3)
        )

    # --- 预检 ---

    def _start_preflight(self, on_done) -> None:
        """后台执行预检，只返回数据，不访问任何 Qt 控件。"""
        self._last_error_code = None

        def run_preflight():
            from doc_tool.adapters.preflight import preflight
            from doc_tool.domain.errors import DocToolError

            try:
                preview = preflight(self._source_page.source_path())
            except DocToolError as exc:
                return (
                    False,
                    None,
                    "预检失败：{0}\n\n建议：{1}".format(
                        exc.user_message, exc.suggested_action
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                return False, None, "预检失败：{0}".format(str(exc)[:200])

            text = format_preview_summary(preview)
            if not preview.has_heading1:
                text += (
                    "\n\n阻断：未检测到 Heading 1 标题样式，无法导入。\n"
                    "请在 Word 中为一级标题应用「标题 1」样式后重新导入。"
                )
                return False, preview, text
            return True, preview, text

        started = self._runner.start(
            TaskSpec(
                name="preflight",
                target=run_preflight,
                timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS,
            ),
            on_event=self._on_task_event,
            on_done=on_done,
        )
        if started:
            self._poll_timer.start()
        else:
            on_done((False, None, "预检任务仍在运行，请稍候。"))

    # --- 导入 ---

    def _do_import(self, on_done) -> None:
        """执行事务化导入。"""
        from doc_tool.application.import_project import ImportRequest, import_first_time

        self._last_error_code = None
        target_root = str(
            Path(self._target_parent) / self._project_name
        )
        request = ImportRequest(
            source_docx=Path(self._source_page.source_path()),
            target_project_root=Path(target_root),
            document_type=self._doc_type,
            document_no=self._doc_no,
            document_name=self._doc_name,
            document_version=self._doc_version,
        )
        started = self._runner.start(
            TaskSpec(
                name="import",
                target=import_first_time,
                args=(request,),
                timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS,
            ),
            on_event=self._on_task_event,
            on_done=lambda result: on_done(result, target_root),
        )
        if started:
            self._poll_timer.start()

    def _on_task_event(self, event) -> None:
        if event.kind == "failed":
            self._last_error_code = event.error_code

    def _poll_runner(self) -> None:
        self._runner.poll()
        if self._closing and not self._runner.is_running:
            self._poll_timer.stop()
            self.reject()
            return
        if not self._runner.is_running:
            self._poll_timer.stop()

    # --- 校验 ---

    def _validate_project_info(self) -> str:
        """验证项目信息字段；返回错误文本（空串表示通过）。"""
        if self._doc_type in ("requirement", "design") and not self._doc_no:
            return "需求/详细设计预设必须填写文档编号。"
        if not self._doc_name:
            return "请填写文档名称。"
        if self._doc_type in ("requirement", "design") and not self._doc_version:
            return "需求/详细设计预设必须填写文档版本。"
        if not self._project_name:
            return "请填写项目目录名。"
        if not self._target_parent:
            return "请选择目标父目录。"
        project_name = self._project_name
        if (
            project_name in (".", "..")
            or Path(project_name).name != project_name
            or any(c in project_name for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in project_name)
            or project_name.rstrip(" .") != project_name
        ):
            return "项目目录名包含 Windows 不允许的字符或路径片段。"
        return ""

    # --- 取消 ---

    def _on_cancel_clicked(self) -> None:
        """取消/关闭：任务运行中先请求安全取消，停止后再关闭。"""
        if self._runner.is_running:
            self._closing = True
            self._runner.cancel()
            self.button(QWizard.WizardButton.CancelButton).setEnabled(False)
        else:
            self.reject()

    def reject(self) -> None:
        """防止运行中直接关闭（安全取消语义）。"""
        if self._runner.is_running and not self._closing:
            self._closing = True
            self._runner.cancel()
            self.button(QWizard.WizardButton.CancelButton).setEnabled(False)
            return
        super().reject()
