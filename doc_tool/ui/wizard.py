# -*- coding: utf-8 -*-
"""新建项目向导（PySide6 QWizard）。

向导流程：
1. 选择源 DOCX 文件
2. 执行预检，展示标题/图片/表格计数、保真风险分级报告和告警（阻断告警需显式确认）
3. 样式映射：把 Word 段落样式映射到章节级别（覆盖自动识别，含非标准 Heading 文档）
4. 选择通用模式或需求/详细设计预设，填写文档信息和目标父目录（含往返严格开关）
5. 执行事务化导入（含往返差异门禁）
6. 显示导入结果（成功/失败）

业务步骤与规则与 Tk 版一致，仅替换组件为 ``QWizard``。预检与导入均在
后台线程执行（``TaskRunner``），支持安全取消（阶段边界生效）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
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
    fidelity = getattr(preview, "fidelity", None)
    if fidelity is not None and fidelity.findings:
        lines.append("")
        lines.append("保真风险：")
        for finding in fidelity.findings:
            tag = {
                "BLOCK": "阻断",
                "WARN": "告警",
                "INFO": "提示",
            }.get(finding.severity, finding.severity)
            sample = "（{0}）".format("、".join(finding.samples)) if finding.samples else ""
            lines.append("  [{0}] {1}: {2}{3}".format(tag, finding.label, finding.count, sample))
        if fidelity.has_block:
            lines.append("  ⛔ 存在阻断特性：默认阻止导入，可在确认风险后勾选「仍然导入」。")
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
    """步骤 2：导入预检（异步执行并展示结果，含保真风险与阻断确认）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 2/6：导入预检")
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
        self._confirm_block = QCheckBox(
            "我已了解上述阻断特性可能导致内容损失，仍然导入", self
        )
        self._confirm_block.hide()
        self._confirm_block.toggled.connect(lambda _checked: self.completeChanged.emit())
        layout.addWidget(self._confirm_block)
        self._preview_ok = False
        self._has_block = False

    def initializePage(self) -> None:
        wizard = self.wizard()
        self._preview_ok = False
        self._has_block = False
        self._preview_text.clear()
        self._confirm_block.hide()
        self._confirm_block.setChecked(False)
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
            self._has_block = bool(
                ok
                and preview is not None
                and getattr(preview, "fidelity", None) is not None
                and preview.fidelity.has_block
            )
            if self._has_block:
                self._confirm_block.show()
            else:
                self._confirm_block.hide()
                self._confirm_block.setChecked(False)
        self._status_label.setText("预检完成" if self._preview_ok else "预检未通过")
        self.completeChanged.emit()

    def _set_text(self, text: str) -> None:
        self._preview_text.setPlainText(text)

    def isComplete(self) -> bool:
        # 结构性预检通过，且（无阻断特性，或用户显式确认「仍然导入」）。
        if not self._preview_ok:
            return False
        if self._has_block:
            return self._confirm_block.isChecked()
        return True


class _StyleMappingPage(QWizardPage):
    """步骤 3：样式映射（候选样式 → 章节级别）。

    把 Word 段落样式映射到章节级别（1~6）或「忽略」；用户映射覆盖自动识别
    结果。完成映射后即时校验：至少一个样式映射到级别 1，且层级不跳跃。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 3/6：样式映射")
        layout = QVBoxLayout(self)
        hint = QLabel(
            "把 Word 段落样式映射到章节级别（1~6，或「忽略」视为正文）。"
            "至少需要一个样式映射到级别 1，且映射后层级不能跳跃。",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._status = QLabel("", self)
        self._status.setObjectName("statusMuted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._table = QTableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["样式名", "样式 ID", "使用次数", "章节级别"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)
        self._rows: list = []

    def initializePage(self) -> None:
        preview = self.wizard()._preview
        self._populate(preview)
        self.completeChanged.emit()

    def _populate(self, preview) -> None:
        self._table.clearContents()
        self._rows = []
        census = dict(getattr(preview, "style_census", None) or {})
        auto_map = dict(getattr(preview, "heading_style_map", None) or {})
        # 候选：正文实际使用过的段落样式（排除 Normal/正文样式）。
        candidates = [
            c for c in census.values()
            if c.usage_count > 0 and c.style_id.lower() != "normal"
        ]
        candidates.sort(key=lambda c: (-c.usage_count, c.name))
        self._table.setRowCount(len(candidates))
        for row, census_entry in enumerate(candidates):
            self._table.setItem(row, 0, QTableWidgetItem(census_entry.name))
            self._table.setItem(row, 1, QTableWidgetItem(census_entry.style_id))
            self._table.setItem(row, 2, QTableWidgetItem(str(census_entry.usage_count)))
            combo = QComboBox(self)
            combo.addItem("忽略", 0)
            for level in range(1, 7):
                combo.addItem("级别 {0}".format(level), level)
            default_level = auto_map.get(census_entry.style_id, 0)
            index = combo.findData(default_level)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(self._on_mapping_changed)
            self._table.setCellWidget(row, 3, combo)
            self._rows.append({"style_id": census_entry.style_id, "combo": combo})
        if not candidates:
            self._status.setText(
                "未发现可映射的段落样式（正文样式除外）。若文档标题未应用任何段落样式，"
                "将无法构建章节结构。"
            )

    def _on_mapping_changed(self, *_args) -> None:
        self.completeChanged.emit()

    def mapping(self) -> Dict[str, int]:
        """返回当前映射：styleId -> 级别（忽略的样式不包含）。"""
        result: Dict[str, int] = {}
        for row in self._rows:
            level = row["combo"].currentData()
            if level:
                result[row["style_id"]] = int(level)
        return result

    def isComplete(self) -> bool:
        return 1 in self.mapping().values()

    def validatePage(self) -> bool:
        mapping = self.mapping()
        from doc_tool.adapters.preflight import validate_heading_mapping

        error = validate_heading_mapping(
            self.wizard()._source_page.source_path(), mapping
        )
        if error:
            QMessageBox.warning(self, "样式映射无效", error)
            return False
        self.wizard()._heading_style_map = mapping
        return True


class _ProjectInfoPage(QWizardPage):
    """步骤 4：项目信息（含往返严格开关）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 4/6：项目信息")
        self.setCommitPage(True)
        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        left = QVBoxLayout()

        # 公共版只创建通用大文档项目，不再提供需求/详细设计类型单选（任务 4.2）。

        self._doc_no_entry = self._field_row(left, "文档编号（可选）：")
        self._doc_name_entry = self._field_row(left, "文档名称：")
        self._doc_version_entry = self._field_row(left, "文档版本（可选）：")
        self._project_name_entry = self._field_row(left, "项目目录名：")

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("目标父目录：", self))
        self._target_entry = QLineEdit(self)
        target_row.addWidget(self._target_entry, 1)
        browse_btn = QPushButton("浏览…", self)
        browse_btn.clicked.connect(self._browse_target)
        target_row.addWidget(browse_btn)
        left.addLayout(target_row)
        self._exact_roundtrip = QCheckBox(
            "往返检查要求完全一致（存在非关键差异也阻止导入）", self
        )
        left.addWidget(self._exact_roundtrip)
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
        self._doc_no_entry.setText(wizard._doc_no)
        self._doc_name_entry.setText(wizard._doc_name)
        self._doc_version_entry.setText(wizard._doc_version)
        self._project_name_entry.setText(wizard._project_name)
        self._target_entry.setText(wizard._target_parent)
        wizard.button(QWizard.WizardButton.NextButton).setText("开始导入")

    def validatePage(self) -> bool:
        wizard = self.wizard()
        wizard._doc_type = "general"
        wizard._doc_no = self._doc_no_entry.text().strip()
        wizard._doc_name = self._doc_name_entry.text().strip()
        wizard._doc_version = self._doc_version_entry.text().strip()
        wizard._project_name = self._project_name_entry.text().strip()
        wizard._target_parent = self._target_entry.text().strip()
        wizard._require_exact_roundtrip = self._exact_roundtrip.isChecked()
        error = wizard._validate_project_info()
        if error:
            QMessageBox.warning(self, "项目信息无效", error)
            return False
        return True


class _ExecutingPage(QWizardPage):
    """步骤 4：执行导入。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 5/6：正在导入…")
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

    def isComplete(self) -> bool:
        """导入任务运行期间禁用 Next，避免跳到结果页时 _import_result 仍为 None。"""
        return bool(getattr(self.wizard(), "_step4_done", False))

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
        self.setTitle("步骤 6/6：导入结果")
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
        self._doc_version = ""
        self._project_name = ""
        self._target_parent = ""
        self._heading_style_map: Optional[dict] = None
        self._require_exact_roundtrip = False
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
        self._mapping_page = _StyleMappingPage(self)
        self._info_page = _ProjectInfoPage(self)
        self._executing_page = _ExecutingPage(self)
        self._result_page = _ResultPage(self)
        self.addPage(self._source_page)
        self.addPage(self._preflight_page)
        self.addPage(self._mapping_page)
        self.addPage(self._info_page)
        self.addPage(self._executing_page)
        self.addPage(self._result_page)

        self.currentIdChanged.connect(self._on_page_changed)
        self.button(QWizard.WizardButton.CancelButton).clicked.connect(
            self._on_cancel_clicked
        )

    def run(self) -> Optional[str]:
        """运行向导，返回项目路径（导入成功）或 None（取消/失败）。

        导入失败时结果页的「关闭」也会 accept() 本向导，但目标目录可能
        未生成；此时返回 None，避免主窗口随后把失败路径当项目打开并
        误报「打开项目失败」。
        """
        if self.exec() == QDialog.DialogCode.Accepted:
            result = getattr(self, "_import_result", None)
            if (
                result is not None
                and result.success
                and getattr(self, "_target_root", "")
            ):
                return self._target_root
        return None

    # --- 页面切换 ---

    def _on_page_changed(self, _page_id: int) -> None:
        self.button(QWizard.WizardButton.NextButton).setEnabled(
            self.currentPage().isComplete()
        )
        self.button(QWizard.WizardButton.BackButton).setEnabled(
            self.currentPage().isComplete()
            and self.currentId() not in (0, 4)
        )

    # --- 预检 ---

    def _start_preflight(self, on_done) -> None:
        """后台执行预检，只返回数据，不访问任何 Qt 控件。"""
        self._last_error_code = None

        def run_preflight():
            from doc_tool.adapters.preflight import preflight
            from doc_tool.domain.errors import DocToolError

            try:
                # 宽松扫描：结构性错误仍 fail-closed；未识别到 Heading 1 不阻断，
                # 交由「样式映射」步骤由用户映射（覆盖自动识别）。
                preview = preflight(
                    self._source_page.source_path(), allow_missing_headings=True
                )
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
                    "\n\n提示：未检测到可自动识别的 Heading 1 标题样式。\n"
                    "请在「样式映射」步骤把标题段落样式映射到章节级别后继续。"
                )
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
        heading_map = self._mapping_page.mapping() or None
        request = ImportRequest(
            source_docx=Path(self._source_page.source_path()),
            target_project_root=Path(target_root),
            document_type=self._doc_type,
            document_no=self._doc_no,
            document_name=self._doc_name,
            document_version=self._doc_version,
            require_exact_roundtrip=bool(self._require_exact_roundtrip),
            heading_style_map=heading_map,
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
        if not self._doc_name:
            return "请填写文档名称。"
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
