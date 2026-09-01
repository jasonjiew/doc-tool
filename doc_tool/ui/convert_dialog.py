# -*- coding: utf-8 -*-
"""文档互转对话框：Word/PDF/Markdown/HTML/TXT/表格/RTF/ODT 批量互转。

交互按公开转换工具的通行范式组织（拖放区 → 转换为 → 进度 → 取回结果）：

- 首屏是大块拖放区，点击可挑选文件，整窗接受拖入（文件或整个文件夹）；
- 「转换为」选择器（取值与中文标签来自方向注册表 ``TARGET_FORMATS``/
  ``TARGET_LABELS``）给出整批的目标格式；某个源不存在该方向时按源族缺省
  方向转换，方向列会显示实际走向；
- 走本机 Word 的方向（PDF/DOCX/HTML/RTF/ODT 相关）由 Word 在后台线程完成；
  Word→Markdown、Markdown/Excel→HTML、表格互转等是纯 Python 离线转换，
  不装 Word 也能用；
- 「页范围」只对转出 PDF 的方向生效（Word 导出参数级支持，见探针结论）。

UI 线程不直接调 Word——长任务经 ``TaskRunner`` 后台执行并带看门狗，工作线程
通过 ``progress`` 信号回填表格行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.convert import (
    KIND_LABELS,
    SUPPORTED_SUFFIXES,
    TARGET_FORMATS,
    TARGET_LABELS,
    convert_paths,
    default_timeout_for,
    detect_kind,
    expand_sources,
    parse_page_range,
)
from doc_tool.domain.errors import (
    PageRangeError,
    TextEncodingError,
    UnsupportedConversionError,
)
from doc_tool.ui.task_bridge import (
    ERR_WATCHDOG_TIMEOUT,
    POLL_INTERVAL_MS,
    TaskEvent,
    TaskRunner,
    TaskSpec,
)

# 拖放区与告警里的类型提示：主扩展名即可（.markdown/.htm 是同族别名，列出太长）。
DISPLAY_SUFFIXES = (".docx", ".doc", ".pdf", ".md", ".html", ".txt", ".xlsx", ".csv", ".rtf", ".odt")
FILE_FILTER = "可转换文档 ({0});;所有文件 (*)".format(
    " ".join("*" + suffix for suffix in SUPPORTED_SUFFIXES)
)
SUPPORTED_HINT = " ".join(DISPLAY_SUFFIXES)


class _DropZone(QFrame):
    """首屏拖放区：点击挑选文件，拖入时高亮。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("card", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(4)
        self._title = QLabel("把文件拖到这里，或点击选择", self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)
        self._hint = QLabel(
            "支持 {0} —— 可多选，也可以直接拖入整个文件夹".format(SUPPORTED_HINT),
            self,
        )
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)

    def set_drag_over(self, active: bool) -> None:
        """拖悬高亮：只在拖入时覆盖主题边框，平时仍走全局 card 样式。"""
        if active:
            accent = self.palette().color(QPalette.ColorRole.Highlight).name()
            self._title.setText("松开鼠标，添加这些文件")
            self.setStyleSheet(
                "#dropZone {{ border: 2px dashed {0}; }}".format(accent)
            )
        else:
            self._title.setText("把文件拖到这里，或点击选择")
            self.setStyleSheet("")

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ConvertDialog(QDialog):
    """Word ↔ PDF ↔ Markdown 批量互转。"""

    progress = Signal(int, int, object)  # done, total, ConversionRecord

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        busy_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(parent)
        self._busy_check = busy_check
        self._sources: List[Path] = []
        self._rows: Dict[str, int] = {}
        self._summarized: set = set()
        self._last_records: List[object] = []
        self._runner = TaskRunner()
        self.progress.connect(self._on_progress)

        self.setWindowTitle("文档互转（Word / PDF / Markdown / 表格等）")
        self.setMinimumSize(760, 600)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._drop_zone = _DropZone(self)
        self._drop_zone.clicked.connect(self._on_add_files)
        layout.addWidget(self._drop_zone)

        toolbar = QHBoxLayout()
        add_files = QPushButton("添加文件…", self)
        add_files.clicked.connect(self._on_add_files)
        add_folder = QPushButton("添加文件夹…", self)
        add_folder.clicked.connect(self._on_add_folder)
        remove_btn = QPushButton("移除选中", self)
        remove_btn.clicked.connect(self._on_remove_selected)
        clear_btn = QPushButton("清空", self)
        clear_btn.clicked.connect(self._on_clear)
        for button in (add_files, add_folder, remove_btn, clear_btn):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("转换为：", self))
        self._format_combo = QComboBox(self)
        for target_format in TARGET_FORMATS:
            self._format_combo.addItem(TARGET_LABELS.get(target_format, target_format), target_format)
        self._format_combo.setToolTip(
            "整批的目标格式。某源不存在该方向时按缺省方向转换（方向列显示实际走向）；"
            "如选 PDF 时 .docx 出 PDF、.pdf/.md 源仍按缺省转 Word。"
        )
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        toolbar.addWidget(self._format_combo)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["源文件", "方向", "输出", "结果"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table, 1)

        options = QHBoxLayout()
        options.addWidget(QLabel("输出到：", self))
        self._output_edit = QLineEdit(self)
        self._output_edit.setPlaceholderText("留空 = 与各源文件同目录")
        options.addWidget(self._output_edit, 1)
        browse = QPushButton("浏览…", self)
        browse.clicked.connect(self._on_choose_output)
        options.addWidget(browse)
        self._overwrite = QCheckBox("覆盖同名文件", self)
        options.addWidget(self._overwrite)
        layout.addLayout(options)

        extras = QHBoxLayout()
        self._with_toc = QCheckBox("Word 产物文首生成目录（1~3 级）", self)
        self._with_toc.setToolTip(
            "仅对「转为 Word」的文件生效：用内置标题样式生成目录并自动刷新页码。"
        )
        extras.addWidget(self._with_toc)
        extras.addStretch(1)
        extras.addWidget(QLabel("页范围（转 PDF）：", self))
        self._pages_edit = QLineEdit(self)
        self._pages_edit.setPlaceholderText("如 1-5，留空为全部")
        self._pages_edit.setMaximumWidth(150)
        self._pages_edit.setToolTip(
            "仅对转出 PDF 的方向生效（Word 导出参数级支持）；格式如 1-5 或 3。"
        )
        extras.addWidget(self._pages_edit)
        extras.addWidget(QLabel("单文件超时（秒）：", self))
        self._timeout = QSpinBox(self)
        self._timeout.setRange(0, 7200)
        self._timeout.setSingleStep(60)
        self._timeout.setSpecialValueText("自动（按方向）")
        self._timeout.setValue(0)
        extras.addWidget(self._timeout)
        layout.addLayout(extras)

        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        self._progress.setFormat("%v / %m")
        layout.addWidget(self._progress)

        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setAcceptDrops(False)
        self._details.setMaximumHeight(120)
        self._details.setPlaceholderText("逐文件结果与结构核验说明会列在这里。")
        layout.addWidget(self._details)

        self._status = QLabel("就绪。", self)
        self._status.setProperty("statusTone", "neutral")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(self)
        self._run_button = QPushButton("开始转换", self)
        self._run_button.setProperty("btnRole", "primary")
        self._run_button.setEnabled(False)
        self._run_button.clicked.connect(self._on_run)
        buttons.addButton(self._run_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._cancel_button = QPushButton("取消", self)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._cancel_button.setEnabled(False)
        buttons.addButton(self._cancel_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        self._open_output_button = QPushButton("打开输出文件夹", self)
        self._open_output_button.setEnabled(False)
        self._open_output_button.clicked.connect(self._on_open_output_folder)
        buttons.addButton(self._open_output_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    # --- 拖放 ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_zone.set_drag_over(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._drop_zone.set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._drop_zone.set_drag_over(False)
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            event.acceptProposedAction()
            self._ingest_paths(paths)

    def _ingest_paths(self, paths: List[Path]) -> None:
        """拖放入口：文件夹展开为一层内的可转换文件，文件原样交清单。"""
        collected: List[Path] = []
        for path in paths:
            if path.is_dir():
                collected.extend(expand_sources([path]))
            else:
                collected.append(path)
        if collected:
            self._append([str(path) for path in collected])

    # --- 文件清单 ---

    def _target_format(self) -> Optional[str]:
        """当前选中的转出格式；显式传给批量层，不存在的方向由注册表回落缺省。"""
        return self._format_combo.currentData()

    def _on_add_files(self) -> None:
        picked, _ = QFileDialog.getOpenFileNames(self, "添加待转换文件", "", FILE_FILTER)
        if picked:
            self._append(picked)

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "添加文件夹（一层内的可转换文件）")
        if folder:
            self._append([str(path) for path in expand_sources([folder])])

    def _append(self, paths) -> None:
        skipped = []
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                continue
            try:
                kind = detect_kind(path, self._target_format())
            except UnsupportedConversionError:
                skipped.append(path.name)
                continue
            if str(path) in self._rows:
                continue
            self._rows[str(path)] = self._table.rowCount()
            self._table.insertRow(self._table.rowCount())
            self._sources.append(path)
            self._set_item(self._table.rowCount() - 1, 0, str(path))
            self._set_item(self._table.rowCount() - 1, 1, KIND_LABELS[kind])
            self._set_item(self._table.rowCount() - 1, 2, "（待转换）")
        self._refresh_count_status()
        self._log_markdown_summaries()
        self._run_button.setEnabled(bool(self._sources))
        if skipped:
            QMessageBox.warning(
                self,
                "已跳过不支持的文件",
                "当前转出格式下可转换 {0}，以下 {1} 个文件未加入：\n{2}".format(
                    SUPPORTED_HINT,
                    len(skipped),
                    "\n".join(skipped[:10]) + ("\n…" if len(skipped) > 10 else ""),
                ),
            )

    def _log_markdown_summaries(self) -> None:
        """刚加入的 Markdown 源给一行体量摘要，转换前心里有数。"""
        from doc_tool.application.markdown_word import markdown_word_summary, read_markdown_text

        for path in self._sources:
            if path.suffix.lower() not in (".md", ".markdown"):
                continue
            if str(path) in self._summarized:
                continue
            self._summarized.add(str(path))
            try:
                self._details.appendPlainText(
                    "{0}：{1}。".format(path.name, markdown_word_summary(read_markdown_text(path)))
                )
            except OSError as exc:
                self._details.appendPlainText("{0}：读取失败（{1}）".format(path.name, exc))
            except TextEncodingError:
                self._details.appendPlainText(
                    "{0}：编码无法识别（E6007），请另存为 UTF-8 后再加入。".format(path.name)
                )

    def _on_format_changed(self, _index: int) -> None:
        """切换转出格式后重算每行的方向；不再支持的行原地标出，转换时给出错误码。"""
        for row in range(self._table.rowCount()):
            path = Path(self._table.item(row, 0).text())
            try:
                self._set_item(row, 1, KIND_LABELS[detect_kind(path, self._target_format())])
            except UnsupportedConversionError:
                self._set_item(row, 1, "不支持该转出格式")

    def _on_remove_selected(self) -> None:
        rows = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)
        self._rebuild_rows()

    def _on_clear(self) -> None:
        self._table.setRowCount(0)
        self._sources = []
        self._rows = {}
        self._summarized = set()
        self._details.clear()
        self._run_button.setEnabled(False)
        self._set_status("就绪。", "neutral")

    def _rebuild_rows(self) -> None:
        """删行后剩余行号整体前移，按表格现状重建行号索引与源清单。"""
        self._rows = {}
        self._sources = []
        for row in range(self._table.rowCount()):
            path = self._table.item(row, 0).text()
            self._rows[path] = row
            self._sources.append(Path(path))
        self._summarized &= {str(path) for path in self._sources}
        self._refresh_count_status()
        self._run_button.setEnabled(bool(self._sources))

    def _refresh_count_status(self) -> None:
        if self._runner.is_running:
            return
        if self._sources:
            self._set_status("已选 {0} 个文件，点击「开始转换」处理。".format(len(self._sources)), "neutral")
        else:
            self._set_status("就绪。", "neutral")

    def _on_choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self._output_edit.setText(folder)

    def _set_item(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        self._table.setItem(row, column, item)

    def _set_status(self, text: str, tone: str = "neutral") -> None:
        self._status.setText(text)
        self._status.setProperty("statusTone", tone)
        # 动态属性变化需重刷样式才能反映到语义色。
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    # --- 转换 ---

    def _on_run(self) -> None:
        if self._runner.is_running:
            return
        if not self._sources:
            QMessageBox.information(self, "开始转换", "请先添加要转换的文件。")
            return
        if self._busy_check is not None and self._busy_check():
            QMessageBox.warning(
                self, "开始转换", "主窗口已有任务正在运行，请等待其完成后再互转。"
            )
            return
        output_dir = self._output_edit.text().strip() or None
        requested = float(self._timeout.value())
        timeout = requested if requested > 0 else None
        pages_text = self._pages_edit.text().strip() or None
        try:
            parse_page_range(pages_text)
        except PageRangeError:
            QMessageBox.warning(
                self, "开始转换",
                "页范围格式不正确：请填「1-5」或「3」（1 起，起始页不大于结束页），"
                "留空表示全部页面。",
            )
            return
        # 看门狗只是兜底解放界面：按本批涉及方向的最大默认值估算总预算。
        per_file = requested or max(self._estimate_timeout(path) for path in self._sources)
        started = self._runner.start(
            TaskSpec(
                name="convert",
                target=convert_paths,
                args=(list(self._sources), output_dir),
                kwargs={
                    "overwrite": self._overwrite.isChecked(),
                    "target_format": self._target_format(),
                    "with_toc": self._with_toc.isChecked(),
                    "page_range": pages_text,
                    "timeout_seconds": timeout,
                    "on_progress": self._emit_progress,
                },
                timeout_seconds=per_file * (len(self._sources) + 1) + 60,
            ),
            on_event=self._on_task_event,
            on_done=self._on_done,
        )
        if not started:
            QMessageBox.warning(self, "开始转换", "已有转换任务正在运行。")
            return
        self._details.clear()
        self._table.resizeColumnsToContents()
        for row in range(self._table.rowCount()):
            self._set_item(row, 3, "排队中")
        self._progress.setRange(0, max(1, len(self._sources)))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._open_output_button.setEnabled(False)
        self._run_button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._set_status("转换中…（Word 在后台运行，可最小化本窗口）", "warning")
        self._timer.start()

    def _estimate_timeout(self, path: Path) -> float:
        """单个源文件的看门狗预算；方向判定失败的行按最常见方向兜底。"""
        try:
            return float(default_timeout_for(detect_kind(path, self._target_format())))
        except UnsupportedConversionError:
            return float(default_timeout_for("docx_to_pdf"))

    def _emit_progress(self, done: int, total: int, record) -> None:
        # 工作线程回调：只发信号，界面更新留在 UI 线程。
        self.progress.emit(done, total, record)

    def _on_progress(self, done: int, total: int, record) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        row = self._rows.get(str(record.source))
        text = "{0} · {1:.1f}s".format(record.status, record.elapsed_seconds)
        if not record.ok and record.error_code:
            text = "{0} · {1}".format(record.error_code, record.detail or record.reason)
        elif record.ok and record.detail:
            text = "{0} · {1}".format(record.status, record.detail)
        if row is not None and row < self._table.rowCount():
            self._set_item(row, 3, text)
            # 计划阶段就失败的行没有产物路径（target 为空 Path），不能显示成 "."。
            self._set_item(row, 2, str(record.target) if record.target.name else "（未生成）")
        self._log_record(record)
        self._set_status("转换中… {0}/{1}".format(done, total), "warning")

    def _log_record(self, record) -> None:
        line = "{0}  {1} → {2}".format(
            "✓" if record.ok else "✗", record.source.name, record.target.name or "（未生成）"
        )
        if not record.ok:
            line += "  [{0}] {1}".format(record.error_code or "?", record.detail)
        self._details.appendPlainText(line)
        if record.note:
            self._details.appendPlainText("    {0}".format(record.note))

    def _on_cancel(self) -> None:
        self._runner.cancel()
        self._cancel_button.setEnabled(False)
        self._set_status("正在取消：当前文件的 Word 调用会先跑完。", "warning")

    def _on_task_event(self, event: TaskEvent) -> None:
        if event.kind == "failed" and event.error_code == ERR_WATCHDOG_TIMEOUT:
            self._details.appendPlainText("转换任务超时，已停止界面跟踪；后台 Word 进程可能仍在回收。")

    def _poll(self) -> None:
        self._runner.poll()
        if not self._runner.is_running:
            self._timer.stop()

    def _on_done(self, result) -> None:
        self._run_button.setEnabled(bool(self._sources))
        self._cancel_button.setEnabled(False)
        self._progress.setVisible(False)
        if result is None:
            self._set_status("转换未正常结束，请查看日志目录。", "failure")
            return
        self._last_records = list(result.records)
        succeeded_dirs = sorted(
            {record.target.parent for record in self._last_records if record.ok}
        )
        self._open_output_button.setEnabled(bool(succeeded_dirs))
        if result.success:
            self._set_status(result.summary() + " 双击列表行可打开对应输出文件夹。", "success")
        else:
            self._set_status(result.summary(), "failure" if result.failed else "neutral")
        pending = [record for record in self._last_records if record.ok and record.note]
        if pending:
            self._details.appendPlainText("—— 结构核验 ——")
            for record in pending:
                self._details.appendPlainText(
                    "{0}: {1}".format(record.target.name, record.note)
                )

    def _on_open_output_folder(self) -> None:
        """打开本次成功产物的所在文件夹（多个时只开第一个，其余在详情里）。"""
        dirs = sorted(
            {record.target.parent for record in self._last_records if record.ok}
        )
        if not dirs:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dirs[0])))

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        """双击行：打开该行输出的所在文件夹（不打开文件本身，避免打断 Word）。"""
        item = self._table.item(row, 2)
        if item is None:
            return
        target = Path(item.text())
        folder = target.parent
        # 「（待转换）」这类占位文本没有扩展名，不会误当成产物路径。
        if target.suffix and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def reject(self) -> None:
        if self._runner.is_running:
            self._on_cancel()
            return
        super().reject()
