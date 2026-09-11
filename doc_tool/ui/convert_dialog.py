# -*- coding: utf-8 -*-
"""文档互转对话框：Word/PDF/Markdown/HTML/TXT/表格/RTF/ODT 批量互转。

交互体验深度参考主流转换工具（CloudConvert、Smallpdf、iLovePDF、Adobe Acrobat、Convertio）：
- 空状态/初次进入：大块拖放区域 + 格式胶囊标签 + 隐私安全保证徽标 + 核心选择按钮；
- 列表状态（已选文件）：紧凑拖放栏 + 批量目标格式切换 + 行级独立目标格式自定义；
- 智能推荐：根据源文件扩展名自动匹配最适用的目标转换格式；
- 丰富状态反馈：待转换、排队中、转换中（实时耗时与百分比）、成功、失败及取消等完备状态；
- 行级快捷操作：单文件打开产物、打开所在文件夹、单项故障重试、单项移除；
- 结构化故障诊断：将 E6001~E6008 错误码转化为用户友好的根因诊断与可执行操作指引；
- 完善的批量能力：支持重试全部失败项、重新转换、批量清空、多选移除、继续追加文件；
- 隐私安全：纯本地离线处理，无网络上传，数据零外泄风险。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QDragMoveEvent,
    QFont,
    QPalette,
)
from doc_tool.ui.styles import SEMANTIC_COLORS
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    TARGET_DOCX,
    TARGET_FORMATS,
    TARGET_LABELS,
    TARGET_PDF,
    available_targets_for,
    convert_paths,
    default_target_for,
    default_timeout_for,
    detect_kind,
    error_resolution_guide,
    expand_sources,
    format_file_size,
    parse_page_range,
    target_for,
    validate_source_signature,
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

# 拖放区与告警里的类型提示：主扩展名
DISPLAY_SUFFIXES = (".docx", ".doc", ".pdf", ".md", ".html", ".txt", ".xlsx", ".csv", ".rtf", ".odt")
FILE_FILTER = "可转换文档 ({0});;所有文件 (*)".format(
    " ".join("*" + suffix for suffix in SUPPORTED_SUFFIXES)
)
SUPPORTED_HINT = " ".join(DISPLAY_SUFFIXES)


class _DropZone(QFrame):
    """拖放区域：支持空态欢迎模式与列表紧凑模式，拖入时高亮。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("card", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 18, 24, 18)
        self._layout.setSpacing(6)

        # 头部标题（兼容既有测试 dlg._drop_zone._title.text()）
        self._title = QLabel("把文件拖到这里，或点击选择", self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._title.font()
        font.setPointSize(11)
        font.setBold(True)
        self._title.setFont(font)
        self._layout.addWidget(self._title)

        # 提示文案（兼容既有测试 dlg._drop_zone._hint）
        self._hint = QLabel(
            "支持 {0} —— 可多选，也可拖入整个文件夹".format(SUPPORTED_HINT),
            self,
        )
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setProperty("statusTone", "neutral")
        self._layout.addWidget(self._hint)

        # 隐私安全承诺徽标
        self._security_badge = QLabel(
            "🛡️ 100% 本地纯离线互转 · 无网络上传 · 严格保护文档隐私安全",
            self,
        )
        self._security_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_font = self._security_badge.font()
        badge_font.setPointSize(8.5)
        self._security_badge.setFont(badge_font)
        self._security_badge.setStyleSheet("color: #059669; margin-top: 2px;")
        self._layout.addWidget(self._security_badge)

    def set_compact_mode(self, compact: bool) -> None:
        """已有文件时切为紧凑条形，空列表时恢复大卡片。"""
        if compact:
            self._layout.setContentsMargins(14, 8, 14, 8)
            self._layout.setSpacing(2)
            self._security_badge.setVisible(False)
            self._title.setText("📄 拖入更多文件至此追加，或点击继续选择")
            font = self._title.font()
            font.setPointSize(9.5)
            font.setBold(False)
            self._title.setFont(font)
            self._hint.setVisible(False)
        else:
            self._layout.setContentsMargins(24, 18, 24, 18)
            self._layout.setSpacing(6)
            self._security_badge.setVisible(True)
            self._title.setText("把文件拖到这里，或点击选择")
            font = self._title.font()
            font.setPointSize(11)
            font.setBold(True)
            self._title.setFont(font)
            self._hint.setVisible(True)
            self._hint.setText("支持 {0} —— 可多选，也可拖入整个文件夹".format(SUPPORTED_HINT))

    def set_drag_over(self, active: bool) -> None:
        """拖悬高亮：只在拖入时覆盖主题边框，平时仍走全局 card 样式。"""
        if active:
            accent = self.palette().color(QPalette.ColorRole.Highlight).name()
            self._title.setText("松开鼠标，添加这些文件")
            self.setStyleSheet(
                "#dropZone {{ border: 2px dashed {0}; background-color: #f0f7ff; }}".format(accent)
            )
        else:
            self.setStyleSheet("")
            if self._security_badge.isVisible():
                self._title.setText("把文件拖到这里，或点击选择")
            else:
                self._title.setText("📄 拖入更多文件至此追加，或点击继续选择")

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.set_drag_over(True)
        else:
            event.ignore()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _RowActionWidget(QWidget):
    """行级操作按钮条：移除、打开产物、打开目录、重试。"""

    remove_clicked = Signal(Path)
    retry_clicked = Signal(Path)

    def __init__(self, path: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._path = path
        self._target_path: Optional[Path] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # 移除按钮
        self._remove_btn = QPushButton("✕ 移除", self)
        self._remove_btn.setProperty("btnRole", "compact")
        self._remove_btn.setToolTip("从转换列表中移除此文件")
        self._remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self._path))
        layout.addWidget(self._remove_btn)

        # 打开产物文件
        self._open_btn = QPushButton("📄 打开", self)
        self._open_btn.setProperty("btnRole", "compact")
        self._open_btn.setToolTip("直接打开转换生成的产物文件")
        self._open_btn.setVisible(False)
        self._open_btn.clicked.connect(self._on_open_file)
        layout.addWidget(self._open_btn)

        # 打开输出目录
        self._folder_btn = QPushButton("📁 目录", self)
        self._folder_btn.setProperty("btnRole", "compact")
        self._folder_btn.setToolTip("打开产物所在的文件夹")
        self._folder_btn.setVisible(False)
        self._folder_btn.clicked.connect(self._on_open_folder)
        layout.addWidget(self._folder_btn)

        # 重试单项
        self._retry_btn = QPushButton("🔄 重试", self)
        self._retry_btn.setProperty("btnRole", "compact")
        self._retry_btn.setToolTip("重新转换此项")
        self._retry_btn.setVisible(False)
        self._retry_btn.clicked.connect(lambda: self.retry_clicked.emit(self._path))
        layout.addWidget(self._retry_btn)

    def set_target(self, target: Optional[Path]) -> None:
        self._target_path = target

    def set_status_succeeded(self, target: Path) -> None:
        self._target_path = target
        self._remove_btn.setVisible(False)
        self._open_btn.setVisible(True)
        self._folder_btn.setVisible(True)
        self._retry_btn.setVisible(False)

    def set_status_failed(self) -> None:
        self._remove_btn.setVisible(True)
        self._open_btn.setVisible(False)
        self._folder_btn.setVisible(False)
        self._retry_btn.setVisible(True)

    def set_status_idle(self) -> None:
        self._remove_btn.setVisible(True)
        self._open_btn.setVisible(False)
        self._folder_btn.setVisible(False)
        self._retry_btn.setVisible(False)

    def set_running(self, running: bool) -> None:
        self.setEnabled(not running)

    def _on_open_file(self) -> None:
        if self._target_path and self._target_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._target_path)))
        else:
            QMessageBox.warning(
                self,
                "无法打开产物",
                "产物文件不存在或已被移动：\n{0}".format(self._target_path or "（路径为空）"),
            )

    def _on_open_folder(self) -> None:
        if self._target_path and self._target_path.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._target_path.parent)))
        else:
            QMessageBox.warning(
                self,
                "无法打开文件夹",
                "产物所在文件夹不存在或无法访问：\n{0}".format(
                    getattr(self._target_path, "parent", "")
                ),
            )


class ConvertDialog(QDialog):
    """Word ↔ PDF ↔ Markdown ↔ 表格 ↔ HTML ↔ 纯文本批量互转。"""

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
        self._row_combos: Dict[str, QComboBox] = {}
        self._row_actions: Dict[str, _RowActionWidget] = {}
        self._summarized: set = set()
        self._last_records: List[object] = []
        self._current_run_sources: List[Path] = []
        self._runner = TaskRunner()
        self._last_run_time: float = 0.0
        self.progress.connect(self._on_progress)

        self.setWindowTitle("文档互转（Word / PDF / Markdown / 表格等）")
        self.resize(880, 640)
        self.setMinimumSize(760, 560)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # 1. 顶部大块 / 紧凑拖放区
        self._drop_zone = _DropZone(self)
        self._drop_zone.clicked.connect(self._on_add_files)
        layout.addWidget(self._drop_zone)

        # 2. 批量操作工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._add_files_btn = QPushButton("添加文件…", self)
        self._add_files_btn.setProperty("btnRole", "secondary")
        self._add_files_btn.clicked.connect(self._on_add_files)
        self._add_folder_btn = QPushButton("添加文件夹…", self)
        self._add_folder_btn.setProperty("btnRole", "secondary")
        self._add_folder_btn.clicked.connect(self._on_add_folder)
        self._remove_btn = QPushButton("移除选中", self)
        self._remove_btn.clicked.connect(self._on_remove_selected)
        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.clicked.connect(self._on_clear)
        for button in (self._add_files_btn, self._add_folder_btn, self._remove_btn, self._clear_btn):
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        toolbar.addWidget(QLabel("全部转换为：", self))
        self._format_combo = QComboBox(self)
        for target_format in TARGET_FORMATS:
            self._format_combo.addItem(
                TARGET_LABELS.get(target_format, target_format), target_format
            )
        self._format_combo.setToolTip(
            "整批的目标格式。某源不存在该方向时按缺省方向转换（方向列显示实际走向）；\n"
            "如选 PDF 时 .docx 出 PDF、.pdf/.md 源仍按缺省转 Word。"
        )
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        toolbar.addWidget(self._format_combo)
        layout.addLayout(toolbar)

        # 3. 文件列表表格（5 列）
        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(["源文件", "方向", "输出", "结果", "操作"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table, 1)

        # 4. 输出路径与常规选项
        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(QLabel("输出到：", self))
        self._output_edit = QLineEdit(self)
        self._output_edit.setClearButtonEnabled(True)
        self._output_edit.setPlaceholderText("留空 = 与各源文件同目录")
        self._output_edit.textChanged.connect(self._on_output_dir_changed)
        options.addWidget(self._output_edit, 1)
        browse = QPushButton("浏览…", self)
        browse.clicked.connect(self._on_choose_output)
        options.addWidget(browse)
        self._overwrite = QCheckBox("覆盖同名文件", self)
        options.addWidget(self._overwrite)
        layout.addLayout(options)

        # 5. 高级参数行（Word 目录、PDF 页范围、超时控制）
        extras = QHBoxLayout()
        extras.setSpacing(8)
        self._with_toc = QCheckBox("Word 产物文首生成目录（1~3 级）", self)
        self._with_toc.setToolTip(
            "仅对「转为 Word」的文件生效：用内置标题样式生成目录并自动刷新页码。"
        )
        extras.addWidget(self._with_toc)
        extras.addStretch(1)

        extras.addWidget(QLabel("页范围（转 PDF）：", self))
        self._pages_edit = QLineEdit(self)
        self._pages_edit.setClearButtonEnabled(True)
        self._pages_edit.setPlaceholderText("如 1-5，留空为全部")
        self._pages_edit.setMaximumWidth(130)
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
        self._timeout.setToolTip("0 表示按各转换方向的缺省安全预算自动设定。")
        extras.addWidget(self._timeout)
        layout.addLayout(extras)

        # 6. 总体进度条与任务提示
        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        self._progress.setFormat("%v / %m (%p%)")
        layout.addWidget(self._progress)

        # 7. 详细执行日志与结构核验说明（抽屉卡）
        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setAcceptDrops(False)
        self._details.setMaximumHeight(110)
        self._details.setPlaceholderText("逐文件结果、结构核验说明及故障排查建议会列在这里。")
        layout.addWidget(self._details)

        # 8. 状态栏
        self._status = QLabel("就绪。", self)
        self._status.setProperty("statusTone", "neutral")
        layout.addWidget(self._status)

        # 9. 底部主控制按钮
        buttons = QDialogButtonBox(self)
        self._run_button = QPushButton("开始转换", self)
        self._run_button.setProperty("btnRole", "primary")
        self._run_button.setEnabled(False)
        self._run_button.clicked.connect(self._on_run)
        buttons.addButton(self._run_button, QDialogButtonBox.ButtonRole.ActionRole)

        self._retry_failed_button = QPushButton("重试失败项", self)
        buttons.addButton(self._retry_failed_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._retry_failed_button.setVisible(False)
        self._retry_failed_button.clicked.connect(self._on_retry_failed)

        self._cancel_button = QPushButton("取消", self)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._cancel_button.setEnabled(False)
        buttons.addButton(self._cancel_button, QDialogButtonBox.ButtonRole.DestructiveRole)

        self._open_output_button = QPushButton("打开输出文件夹", self)
        self._open_output_button.setEnabled(False)
        self._open_output_button.clicked.connect(self._on_open_output_folder)
        buttons.addButton(self._open_output_button, QDialogButtonBox.ButtonRole.ActionRole)

        self._close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 轮询定时器
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    # --- 拖放事件处理 ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and not self._runner.is_running:
            event.acceptProposedAction()
            self._drop_zone.set_drag_over(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and not self._runner.is_running:
            event.acceptProposedAction()
            self._drop_zone.set_drag_over(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_zone.set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_zone.set_drag_over(False)
        if self._runner.is_running:
            event.ignore()
            return
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

    # --- 文件清单管理 ---

    def _target_format(self) -> Optional[str]:
        """当前选中的全局转出格式；显式传给批量层，不存在的方向由注册表回落缺省。"""
        return self._format_combo.currentData()

    def _on_add_files(self) -> None:
        picked, _ = QFileDialog.getOpenFileNames(self, "添加待转换文件", "", FILE_FILTER)
        if picked:
            self._append(picked)

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "添加文件夹（一层内的可转换文件）")
        if folder:
            files = [str(path) for path in expand_sources([folder])]
            if not files:
                QMessageBox.information(
                    self,
                    "未发现支持的文档",
                    "所选文件夹内未发现可转换的文档格式。\n支持格式：{0}".format(SUPPORTED_HINT),
                )
                return
            self._append(files)

    def _append(self, paths) -> None:
        if len(self._sources) >= 500:
            QMessageBox.warning(self, "数量超出建议上限", "列表中已有 500 个文件，单次批量转换建议不超过 500 个文件。")
            return
        skipped = []
        out_dir = self._output_edit.text().strip() or None
        for raw in paths:
            if len(self._sources) >= 500:
                self._details.appendPlainText("⚠️ 已达到 500 个文件建议上限，其余文件已跳过。")
                break
            path = Path(raw)
            if not path.is_file():
                continue
            if str(path) in self._rows:
                self._details.appendPlainText(f"ℹ️ {path.name}：已在转换列表中，跳过重复添加。")
                continue
            valid, err_msg = validate_source_signature(path)
            if not valid:
                self._details.appendPlainText(f"⚠️ {path.name}：跳过无效文件（{err_msg}）")
                skipped.append(f"{path.name} ({err_msg})")
                continue
            try:
                kind = detect_kind(path, self._target_format())
            except UnsupportedConversionError:
                skipped.append(path.name)
                continue

            try:
                size = path.stat().st_size
                if size > 500 * 1024 * 1024:
                    self._details.appendPlainText(f"⚠️ {path.name}：文件较大（{format_file_size(size)}），转换可能耗时较长，建议在高级选项中增加超时时间。")
            except OSError:
                pass

            row_idx = self._table.rowCount()
            self._rows[str(path)] = row_idx
            self._table.insertRow(row_idx)
            self._sources.append(path)

            # Col 0: 源文件（item text 必须为 str(path)，供已有测试和逻辑查验）
            size_str = ""
            try:
                size_str = format_file_size(path.stat().st_size)
            except OSError:
                pass
            item0 = QTableWidgetItem(str(path))
            tip0 = f"文件名称：{path.name}\n完整路径：{path}"
            if size_str:
                tip0 += f"\n文件大小：{size_str}"
            item0.setToolTip(tip0)
            self._table.setItem(row_idx, 0, item0)

            # Col 1: 方向（item text 存 KIND_LABELS[kind]）
            label = KIND_LABELS.get(kind, kind)
            self._set_item(row_idx, 1, label)

            # Col 1 嵌入行级独立的格式选择下拉框
            combo = self._create_row_combo(path, kind)
            self._row_combos[str(path)] = combo
            self._table.setCellWidget(row_idx, 1, combo)

            # Col 2: 输出文件（立即显示预估产物名称与完整悬浮提示）
            predicted = target_for(path, kind, out_dir)
            self._set_item(row_idx, 2, f"（待转换: {predicted.name}）")
            self._table.item(row_idx, 2).setToolTip(f"预估产物路径: {predicted}")

            # Col 3: 状态与结果
            self._set_item(row_idx, 3, "待转换")

            # Col 4: 行级操作按钮
            actions = _RowActionWidget(path, self._table)
            actions.remove_clicked.connect(self._on_remove_single_row)
            actions.retry_clicked.connect(self._on_retry_single)
            self._row_actions[str(path)] = actions
            self._table.setCellWidget(row_idx, 4, actions)

        self._drop_zone.set_compact_mode(bool(self._sources))
        self._refresh_count_status()
        self._log_markdown_summaries()
        self._run_button.setEnabled(bool(self._sources))
        self._run_button.setText("开始转换")
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

    def _create_row_combo(self, path: Path, kind: str) -> QComboBox:
        """为单行创建目标格式选择下拉框，仅呈现该源支持的方向。"""
        combo = QComboBox(self._table)
        combo.setProperty("btnRole", "compact")
        targets = available_targets_for(path)

        current_target_format = self._target_format()
        selected_idx = 0
        for idx, (fmt, lbl) in enumerate(targets):
            combo.addItem(f"转为 {lbl}", fmt)
            if current_target_format and fmt == current_target_format:
                selected_idx = idx

        if targets and selected_idx < len(targets):
            combo.setCurrentIndex(selected_idx)

        combo.currentIndexChanged.connect(lambda _idx, p=path: self._on_row_target_changed(p))
        return combo

    def _on_row_target_changed(self, path: Path) -> None:
        """行级格式下拉变更：同步更新方向标签、预估输出文件名，并重置该行为待转换状态。"""
        p_str = str(path)
        row = self._rows.get(p_str)
        combo = self._row_combos.get(p_str)
        if row is None or combo is None or row < 0 or row >= self._table.rowCount():
            return
        if combo.currentIndex() < 0:
            return
        target_fmt = combo.currentData()
        try:
            kind = detect_kind(path, target_fmt)
            label = KIND_LABELS[kind]
            self._set_item(row, 1, label)
            out_dir = self._output_edit.text().strip() or None
            predicted = target_for(path, kind, out_dir)
            self._set_item(row, 2, f"（待转换: {predicted.name}）")
            self._table.item(row, 2).setToolTip(f"预估产物路径: {predicted}")
            self._set_item(row, 3, "待转换", tone="neutral")
            actions = self._row_actions.get(str(path))
            if actions is not None:
                actions.set_status_idle()
            self._last_records = [r for r in self._last_records if str(r.source) != str(path)]
            failed_count = sum(1 for r in self._last_records if not getattr(r, "ok", False))
            if failed_count > 0:
                self._retry_failed_button.setText(f"重试失败项 ({failed_count})")
                self._retry_failed_button.setVisible(True)
            else:
                self._retry_failed_button.setVisible(False)
            self._run_button.setText("开始转换")
        except UnsupportedConversionError:
            self._set_item(row, 1, "不支持该转出格式", tone="failure")

    def _log_markdown_summaries(self) -> None:
        """刚加入的 Markdown 源给一行体量摘要，转换前心里有数。"""
        from doc_tool.application.markdown_word import (
            markdown_word_summary,
            read_markdown_text,
        )

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
        """切换全局转换格式：联动更新每行的走向与预估产物，并重置为待转换状态。"""
        if self._runner.is_running:
            return
        target_fmt = self._target_format()
        out_dir = self._output_edit.text().strip() or None
        any_changed = False
        for row in range(self._table.rowCount()):
            item0 = self._table.item(row, 0)
            if not item0:
                continue
            path = Path(item0.text())
            combo = self._row_combos.get(str(path))
            if combo is not None:
                idx = combo.findData(target_fmt)
                if idx >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
                    combo.setToolTip("")
                else:
                    cur_lbl = TARGET_LABELS.get(combo.currentData(), str(combo.currentData()))
                    req_lbl = TARGET_LABELS.get(target_fmt, str(target_fmt))
                    combo.setToolTip(f"该源文件（{path.suffix}）不支持转为 {req_lbl}，保持为 {cur_lbl}")
            effective_tf = combo.currentData() if combo else target_fmt
            try:
                kind = detect_kind(path, effective_tf)
                self._set_item(row, 1, KIND_LABELS.get(kind, kind))
                predicted = target_for(path, kind, out_dir)
                self._set_item(row, 2, f"（待转换: {predicted.name}）")
                if self._table.item(row, 2):
                    self._table.item(row, 2).setToolTip(f"预估产物路径: {predicted}")
                self._set_item(row, 3, "待转换", tone="neutral")
                actions = self._row_actions.get(str(path))
                if actions is not None:
                    actions.set_status_idle()
                any_changed = True
            except UnsupportedConversionError:
                pass

        if any_changed:
            self._last_records = []
            self._retry_failed_button.setVisible(False)
            self._run_button.setText("开始转换")
            self._refresh_count_status()

    def _on_output_dir_changed(self, text: str) -> None:
        """输出目录变更时动态刷新列表中待转换条目的预估产物展示。"""
        out_dir = text.strip() or None
        for row in range(self._table.rowCount()):
            item0 = self._table.item(row, 0)
            if not item0:
                continue
            path_str = item0.text()
            path = Path(path_str)
            combo = self._row_combos.get(path_str)
            tf = combo.currentData() if combo else self._target_format()
            try:
                kind = detect_kind(path, tf)
                predicted = target_for(path, kind, out_dir)
                status_item = self._table.item(row, 3)
                if status_item and status_item.text() in ("待转换", "排队中"):
                    self._set_item(row, 2, f"（待转换: {predicted.name}）")
                    self._table.item(row, 2).setToolTip(f"预估产物路径: {predicted}")
            except Exception:
                pass

    def _set_controls_enabled(self, enabled: bool) -> None:
        """在转换任务运行中冻结配置面板与文件增删控件，防止并发状态撕裂。"""
        self._add_files_btn.setEnabled(enabled)
        self._add_folder_btn.setEnabled(enabled)
        self._remove_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        self._format_combo.setEnabled(enabled)
        self._output_edit.setEnabled(enabled)
        self._overwrite.setEnabled(enabled)
        self._with_toc.setEnabled(enabled)
        self._pages_edit.setEnabled(enabled)
        self._timeout.setEnabled(enabled)
        for combo in self._row_combos.values():
            combo.setEnabled(enabled)

    def _on_remove_selected(self) -> None:
        if self._runner.is_running:
            return
        rows = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            item0 = self._table.item(row, 0)
            if item0:
                p_str = item0.text()
                combo = self._row_combos.pop(p_str, None)
                if combo is not None:
                    try:
                        combo.deleteLater()
                    except Exception:
                        pass
                actions = self._row_actions.pop(p_str, None)
                if actions is not None:
                    try:
                        actions.deleteLater()
                    except Exception:
                        pass
            self._table.removeRow(row)
        self._rebuild_rows()

    def _on_remove_single_row(self, path: Path) -> None:
        if self._runner.is_running:
            return
        p_str = str(path)
        row = self._rows.get(p_str)
        if row is not None:
            combo = self._row_combos.pop(p_str, None)
            if combo is not None:
                try:
                    combo.deleteLater()
                except Exception:
                    pass
            actions = self._row_actions.pop(p_str, None)
            if actions is not None:
                try:
                    actions.deleteLater()
                except Exception:
                    pass
            self._table.removeRow(row)
            self._rebuild_rows()

    def _on_clear(self) -> None:
        if self._runner.is_running:
            return
        for w in list(self._row_combos.values()):
            try:
                w.deleteLater()
            except Exception:
                pass
        for w in list(self._row_actions.values()):
            try:
                w.deleteLater()
            except Exception:
                pass
        self._table.setRowCount(0)
        self._sources = []
        self._rows = {}
        self._row_combos = {}
        self._row_actions = {}
        self._last_records = []
        self._summarized = set()
        self._details.clear()
        self._run_button.setEnabled(False)
        self._run_button.setText("开始转换")
        self._retry_failed_button.setVisible(False)
        self._open_output_button.setEnabled(False)
        self._drop_zone.set_compact_mode(False)
        self._set_status("就绪。", "neutral")

    def _rebuild_rows(self) -> None:
        """删行后剩余行号整体前移，按表格现状重建行号索引与源清单。"""
        old_combos = dict(self._row_combos)
        old_actions = dict(self._row_actions)
        self._rows = {}
        self._sources = []
        self._row_combos = {}
        self._row_actions = {}
        for row in range(self._table.rowCount()):
            path_str = self._table.item(row, 0).text()
            self._rows[path_str] = row
            self._sources.append(Path(path_str))
            if path_str in old_combos:
                self._row_combos[path_str] = old_combos[path_str]
            if path_str in old_actions:
                self._row_actions[path_str] = old_actions[path_str]

        self._summarized &= {str(path) for path in self._sources}
        self._last_records = [r for r in self._last_records if Path(getattr(r, "source", "")) in self._sources]
        failed_count = sum(1 for r in self._last_records if not getattr(r, "ok", False))
        if failed_count > 0:
            self._retry_failed_button.setText(f"重试失败项 ({failed_count})")
            self._retry_failed_button.setVisible(True)
        else:
            self._retry_failed_button.setVisible(False)
        self._drop_zone.set_compact_mode(bool(self._sources))
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

    def _set_item(self, row: int, column: int, text: str, tone: Optional[str] = None) -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        if tone and tone in SEMANTIC_COLORS:
            item.setForeground(QColor(SEMANTIC_COLORS[tone]))
        self._table.setItem(row, column, item)

    def _set_status(self, text: str, tone: str = "neutral") -> None:
        self._status.setText(text)
        self._status.setProperty("statusTone", tone)
        # 动态属性变化需重刷样式才能反映到语义色
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    # --- 转换编排与执行 ---

    def _on_run(self, targets_to_run: Optional[List[Path]] = None) -> None:
        """开始转换：防抖、校验、收集行级目标格式并投递任务（支持全量或失败子集重试）。"""
        now = time.monotonic()
        if now - self._last_run_time < 0.5:
            return
        self._last_run_time = now

        if self._runner.is_running:
            return

        active_sources = list(targets_to_run) if targets_to_run is not None else list(self._sources)
        if not active_sources:
            QMessageBox.information(self, "开始转换", "请先添加要转换的文件。")
            return
        if self._busy_check is not None and self._busy_check():
            QMessageBox.warning(
                self, "开始转换", "主窗口已有任务正在运行，请等待其完成后再互转。"
            )
            return

        output_dir = self._output_edit.text().strip() or None
        if output_dir:
            try:
                out_p = Path(output_dir)
                if out_p.is_file():
                    QMessageBox.warning(self, "输出目录无效", "指定的输出目录是一个已有文件，请输入有效的文件夹路径。")
                    return
                out_p.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, "输出目录无效", f"无法创建或访问输出目录：\n{exc}\n请检查路径格式与写入权限。")
                return
        requested = float(self._timeout.value())
        timeout = requested if requested > 0 else None
        pages_text = self._pages_edit.text().strip() or None
        try:
            parse_page_range(pages_text)
        except PageRangeError:
            QMessageBox.warning(
                self,
                "开始转换",
                "页范围格式不正确：请填「1-5」或「3」（1 起，起始页不大于结束页），"
                "留空表示全部页面。",
            )
            return

        # 收集本次运行中各源文件的目标格式
        target_format_map = {}
        for path in active_sources:
            combo = self._row_combos.get(str(path))
            tf = combo.currentData() if combo else self._target_format()
            target_format_map[path] = tf

        global_target = self._target_format()
        if all(tf == global_target for tf in target_format_map.values()):
            effective_target = global_target
        else:
            effective_target = target_format_map

        self._current_run_sources = active_sources
        per_file = requested or max(self._estimate_timeout(path) for path in active_sources)
        started = self._runner.start(
            TaskSpec(
                name="convert",
                target=convert_paths,
                args=(list(active_sources), output_dir),
                kwargs={
                    "overwrite": self._overwrite.isChecked(),
                    "target_format": effective_target,
                    "with_toc": self._with_toc.isChecked(),
                    "page_range": pages_text,
                    "timeout_seconds": timeout,
                    "on_progress": self._emit_progress,
                },
                timeout_seconds=per_file * (len(active_sources) + 1) + 60,
            ),
            on_event=self._on_task_event,
            on_done=self._on_done,
        )
        if not started:
            QMessageBox.warning(self, "开始转换", "已有转换任务正在运行。")
            return

        if targets_to_run is None:
            self._details.clear()
        else:
            self._details.appendPlainText("\n—— 开始重试 " + str(len(active_sources)) + " 个文件 ——")

        self._retry_failed_button.setVisible(False)
        self._table.resizeColumnsToContents()

        # 仅针对本次运行的源文件标记为「排队中」和 running 状态，并刷新预估产物路径
        active_set = {str(p) for p in active_sources}
        for path_str in active_set:
            row = self._rows.get(path_str)
            if row is not None:
                self._set_item(row, 3, "排队中", tone="neutral")
                combo = self._row_combos.get(path_str)
                tf = combo.currentData() if combo else self._target_format()
                try:
                    kind = detect_kind(Path(path_str), tf)
                    predicted = target_for(Path(path_str), kind, output_dir)
                    self._set_item(row, 2, f"（待转换: {predicted.name}）")
                    self._table.item(row, 2).setToolTip(f"预估产物路径: {predicted}")
                except Exception:
                    pass
            if path_str in self._row_actions:
                self._row_actions[path_str].set_running(True)

        self._progress.setRange(0, max(1, len(active_sources)))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._set_controls_enabled(False)
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
        self.progress.emit(done, total, record)

    def _on_progress(self, done: int, total: int, record) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._progress.setFormat(f"%v / %m ({int(done / max(1, total) * 100)}%)")

        row = self._rows.get(str(record.source))
        if record.ok:
            text = "{0} · {1:.1f}s".format(record.status, record.elapsed_seconds)
            tone = "success"
            tip = f"转换成功\n耗时：{record.elapsed_seconds:.2f} 秒\n产物路径：{record.target}"
        else:
            tone = "failure"
            short_title, guide = error_resolution_guide(record.error_code, record.detail)
            if record.error_code:
                text = f"{record.error_code} · {short_title}"
            else:
                text = f"失败 · {short_title}"
            tip = f"状态：转换失败\n错误码：{record.error_code or '无'}\n详情：{record.detail or record.reason}\n💡 解决指引：{guide}"

        if row is not None and row < self._table.rowCount():
            self._set_item(row, 3, text, tone=tone)
            if self._table.item(row, 3):
                self._table.item(row, 3).setToolTip(tip)
            target_str = str(record.target) if record.target.name else "（未生成）"
            self._set_item(row, 2, target_str)
            if self._table.item(row, 2) and record.target.name:
                self._table.item(row, 2).setToolTip(f"产物完整路径: {record.target}")

            # 更新行级操作控件状态
            actions = self._row_actions.get(str(record.source))
            if actions is not None:
                actions.set_running(False)
                if record.ok:
                    actions.set_status_succeeded(record.target)
                else:
                    actions.set_status_failed()

        self._log_record(record)
        self._set_status("转换中… {0}/{1}".format(done, total), "warning")

    def _log_record(self, record) -> None:
        line = "{0}  {1} → {2}".format(
            "✓" if record.ok else "✗", record.source.name, record.target.name or "（未生成）"
        )
        if not record.ok:
            line += "  [{0}] {1}".format(record.error_code or "?", record.detail)
            # 追加可执行指引
            desc, guide = error_resolution_guide(record.error_code, record.detail)
            line += f"\n    💡 解决指引: {guide}"
        self._details.appendPlainText(line)
        if getattr(record, "note", None):
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
        self._set_controls_enabled(True)
        self._run_button.setEnabled(bool(self._sources))
        self._cancel_button.setEnabled(False)
        self._progress.setVisible(False)

        for actions in self._row_actions.values():
            actions.set_running(False)

        if result is None:
            self._set_status("转换未正常结束（可能发生看门狗超时或后台异常终止），请查看日志。", "failure")
            active_set = getattr(self, "_current_run_sources", self._sources)
            for src in active_set:
                src_str = str(src)
                row = self._rows.get(src_str)
                if row is not None:
                    curr_item = self._table.item(row, 3)
                    if curr_item and curr_item.text() in ("待转换", "排队中"):
                        self._set_item(row, 3, "E6004 · 任务超时或异常终止", tone="failure")
                    actions = self._row_actions.get(src_str)
                    if actions is not None:
                        actions.set_status_failed()
            failed_count = sum(1 for r in self._last_records if not getattr(r, "ok", False)) or len(active_set)
            self._retry_failed_button.setText(f"重试失败项 ({failed_count})")
            self._retry_failed_button.setVisible(True)
            return

        # 合并本次运行结果至 self._last_records，保留跨重试的完整批次历史
        new_records_by_source = {
            str(getattr(r, "source", f"rec_{i}")): r
            for i, r in enumerate(result.records)
        }
        merged_records = []
        seen_sources = set()
        for old_rec in self._last_records:
            src_str = str(getattr(old_rec, "source", None))
            if src_str in new_records_by_source:
                merged_records.append(new_records_by_source[src_str])
                seen_sources.add(src_str)
            else:
                merged_records.append(old_rec)
                seen_sources.add(src_str)
        for i, r in enumerate(result.records):
            src_str = str(getattr(r, "source", f"rec_{i}"))
            if src_str not in seen_sources:
                merged_records.append(r)
                seen_sources.add(src_str)
        self._last_records = merged_records

        # 若任务被取消，将本次排队但未执行的条目标记为「已取消」
        if getattr(result, "cancelled", False):
            active_set = getattr(self, "_current_run_sources", self._sources)
            for src in active_set:
                src_str = str(src)
                if src_str not in new_records_by_source:
                    row = self._rows.get(src_str)
                    if row is not None:
                        self._set_item(row, 3, "已取消", tone="neutral")
                    actions = self._row_actions.get(src_str)
                    if actions is not None:
                        actions.set_status_idle()

        succeeded_dirs = sorted(
            {record.target.parent for record in self._last_records if record.ok and record.target.parent.is_dir()}
        )
        self._open_output_button.setEnabled(bool(succeeded_dirs) or bool(self._output_edit.text().strip()))

        # 检查是否有失败条目，显示重试失败项按钮
        failed_count = sum(1 for r in self._last_records if not r.ok)
        if failed_count > 0:
            self._retry_failed_button.setText(f"重试失败项 ({failed_count})")
            self._retry_failed_button.setVisible(True)
        else:
            self._retry_failed_button.setVisible(False)

        total_count = len(self._last_records)
        succeeded_count = sum(1 for r in self._last_records if r.ok)
        
        batch_summary = f"成功 {succeeded_count} 个，失败 {failed_count} 个。"
        error_codes = sorted({r.error_code for r in self._last_records if not r.ok and getattr(r, "error_code", None)})
        if error_codes:
            batch_summary += f" 涉及错误码：{'、'.join(error_codes)}。"

        if getattr(result, "cancelled", False):
            self._set_status(f"转换已取消。已完成 {succeeded_count}/{total_count} 项。", "warning")
        elif failed_count == 0 and total_count > 0:
            self._set_status(batch_summary + " 双击列表行可打开对应输出文件夹。", "success")
            self._run_button.setText("重新转换全部")
        else:
            self._set_status(batch_summary, "failure" if failed_count else "neutral")

        pending = [record for record in self._last_records if record.ok and record.note]
        if pending:
            self._details.appendPlainText("—— 结构核验 ——")
            for record in pending:
                self._details.appendPlainText(
                    "{0}: {1}".format(record.target.name, record.note)
                )

    def _on_retry_failed(self) -> None:
        """重试所有失败项（保持完整源文件列表与表格结构不变）。"""
        if self._runner.is_running or not self._last_records:
            return
        failed_sources = [r.source for r in self._last_records if not r.ok]
        if not failed_sources:
            return
        self._on_run(targets_to_run=failed_sources)

    def _on_retry_single(self, path: Path) -> None:
        """重试单个源文件（保持完整源文件列表与表格结构不变）。"""
        if self._runner.is_running:
            return
        self._on_run(targets_to_run=[path])

    def _on_open_output_folder(self) -> None:
        """打开本次成功产物的所在文件夹（多个时开第一个，或用户指定的输出目录）。"""
        dirs = sorted(
            {record.target.parent for record in self._last_records if record.ok and record.target.parent.is_dir()}
        )
        if dirs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dirs[0])))
            return
        out_text = self._output_edit.text().strip()
        if out_text:
            out_dir = Path(out_text)
            if out_dir.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))
                return
        QMessageBox.information(
            self,
            "打开输出文件夹",
            "未找到可访问的输出文件夹，请确认转换已成功生成产物或指定的输出目录存在。",
        )

    def _on_row_double_clicked(self, row: int, column: int) -> None:
        """双击行：打开该行输出的所在文件夹（不打开文件本身，避免打断 Word）。"""
        if column in (1, 4):
            return
        item = self._table.item(row, 2)
        if item is None:
            return
        text = item.text().strip()
        if not text or text.startswith(("（", "(", "【", "[", "—")):
            return
        target = Path(text)
        if not target.is_absolute():
            return
        folder = target.parent
        if target.suffix and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """快捷键支持：Enter 触发转换，Esc 取消或退出。"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._run_button.isEnabled() and not self._runner.is_running:
                self._on_run()
                return
        elif event.key() == Qt.Key.Key_Escape:
            if self._runner.is_running:
                self._on_cancel()
                return
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not self._runner.is_running:
                self._on_remove_selected()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """窗口关闭：运行中提醒并取消后台任务。"""
        if self._runner.is_running:
            reply = QMessageBox.question(
                self,
                "确认退出",
                "当前有转换任务正在运行，确认取消并关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_cancel()
                event.accept()
            else:
                event.ignore()
                return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._runner.is_running:
            reply = QMessageBox.question(
                self,
                "确认退出",
                "当前有转换任务正在运行，确认取消并关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._on_cancel()
        super().reject()
