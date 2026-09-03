# -*- coding: utf-8 -*-
"""PDF 工具箱对话框：页面组织、格式转换、页面编辑与安全优化。

采用与 ConvertDialog 一致的成熟范式：
- 左侧工具清单：按「页面组织 / 转换 / 编辑 / 安全与优化」4 大分类组织 14 个工具；
- 右侧功能区：顶部工具说明与拖放区，中部文件表格（支持合并时的上移/下移排序），
  选项卡切换各工具专属参数，底部输出目录、同名覆盖、进度条与详情日志；
- 异步工作流：通过 TaskRunner 在后台工作线程执行，progress 信号回填界面，
  支持随时取消。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.pdf_tools import (
    CATEGORIES,
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    TOOL_COMPRESS,
    TOOL_DECRYPT,
    TOOL_DELETE,
    TOOL_ENCRYPT,
    TOOL_EXTRACT,
    TOOL_IDS,
    TOOL_IMAGES_TO_PDF,
    TOOL_MERGE,
    TOOL_METADATA,
    TOOL_PAGE_NUMBERS,
    TOOL_ROTATE,
    TOOL_SPEC_BY_ID,
    TOOL_SPECS,
    TOOL_SPLIT,
    TOOL_TO_IMAGES,
    TOOL_TO_TEXT,
    TOOL_WATERMARK,
    PdfToolBatchResult,
    PdfToolRecord,
    expand_sources,
    parse_page_ranges,
    parse_page_selection,
    run_pdf_tool,
)
from doc_tool.domain.errors import (
    PdfInputError,
    PdfPageSelectionError,
)
from doc_tool.ui.task_bridge import (
    POLL_INTERVAL_MS,
    TaskEvent,
    TaskRunner,
    TaskSpec,
)


class _DropZone(QFrame):
    """首屏拖放区：点击挑选文件，拖入时高亮。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("card", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(4)
        self._title = QLabel("把文件拖到这里，或点击选择", self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)
        self._hint = QLabel("支持 .pdf 文件 —— 可多选，也可拖入整个文件夹", self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)

    def set_hint(self, hint_text: str) -> None:
        self._hint.setText(hint_text)

    def set_drag_over(self, active: bool) -> None:
        if active:
            accent = self.palette().color(QPalette.ColorRole.Highlight).name()
            self._title.setText("松开鼠标，添加这些文件")
            self.setStyleSheet(
                "#dropZone {{ border: 2px dashed {0}; }}".format(accent)
            )
        else:
            self._title.setText("把文件拖到这里，或点击选择")
            self.setStyleSheet("")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PdfToolboxDialog(QDialog):
    """PDF 工具箱对话框。"""

    progress = Signal(int, int, object)  # done, total, PdfToolRecord

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        busy_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(parent)
        self._busy_check = busy_check
        self._sources: List[Path] = []
        self._rows: Dict[str, int] = {}
        self._runner = TaskRunner()
        self._last_result: Optional[PdfToolBatchResult] = None
        self.progress.connect(self._on_progress)

        self.setWindowTitle("PDF 工具箱（合并 / 拆分 / 水印 / 加密等）")
        self.setMinimumSize(880, 660)
        self.setAcceptDrops(True)

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(12)

        # 1. 左侧工具列表导航
        left_box = QVBoxLayout()
        left_box.setSpacing(6)
        nav_label = QLabel("选择功能：", self)
        left_box.addWidget(nav_label)

        self._tool_list = QListWidget(self)
        self._tool_list.setFixedWidth(190)
        self._populate_tool_list()
        self._tool_list.currentItemChanged.connect(self._on_tool_changed)
        left_box.addWidget(self._tool_list)
        main_layout.addLayout(left_box)

        # 2. 右侧主工作区
        right_box = QVBoxLayout()
        right_box.setSpacing(8)

        # 顶部：工具说明横幅与拖放区
        self._desc_label = QLabel(self)
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("font-weight: bold; padding: 4px;")
        right_box.addWidget(self._desc_label)

        self._drop_zone = _DropZone(self)
        self._drop_zone.clicked.connect(self._on_add_files)
        right_box.addWidget(self._drop_zone)

        # 文件操作工具条
        toolbar = QHBoxLayout()
        self._add_files_btn = QPushButton("添加文件…", self)
        self._add_files_btn.clicked.connect(self._on_add_files)
        toolbar.addWidget(self._add_files_btn)

        self._add_folder_btn = QPushButton("添加文件夹…", self)
        self._add_folder_btn.clicked.connect(self._on_add_folder)
        toolbar.addWidget(self._add_folder_btn)

        self._move_up_btn = QPushButton("上移 ↑", self)
        self._move_up_btn.clicked.connect(self._on_move_up)
        toolbar.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("下移 ↓", self)
        self._move_down_btn.clicked.connect(self._on_move_down)
        toolbar.addWidget(self._move_down_btn)

        self._remove_btn = QPushButton("移除选中", self)
        self._remove_btn.clicked.connect(self._on_remove_selected)
        toolbar.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(self._clear_btn)

        toolbar.addStretch()
        right_box.addLayout(toolbar)

        # 文件清单表格
        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["源文件", "状态", "输出产物"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setMaximumHeight(160)
        right_box.addWidget(self._table)

        # 选项配置区（多工具面板堆叠）
        self._opt_group = QGroupBox("功能参数设置", self)
        opt_group_layout = QVBoxLayout(self._opt_group)
        self._options_stack = QStackedWidget(self._opt_group)
        self._build_options_pages()
        opt_group_layout.addWidget(self._options_stack)
        right_box.addWidget(self._opt_group)

        # 输出目录与覆盖设置
        out_layout = QHBoxLayout()
        out_label = QLabel("输出目录：", self)
        out_layout.addWidget(out_label)
        self._out_dir_edit = QLineEdit(self)
        self._out_dir_edit.setPlaceholderText("缺省与各源文件同目录")
        out_layout.addWidget(self._out_dir_edit)
        self._browse_dir_btn = QPushButton("浏览…", self)
        self._browse_dir_btn.clicked.connect(self._on_browse_output_dir)
        out_layout.addWidget(self._browse_dir_btn)

        self._overwrite_box = QCheckBox("覆盖同名文件", self)
        out_layout.addWidget(self._overwrite_box)
        right_box.addLayout(out_layout)

        # 进度条
        self._progress = QProgressBar(self)
        self._progress.setTextVisible(True)
        self._progress.setVisible(False)
        right_box.addWidget(self._progress)

        # 详情日志框
        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(100)
        right_box.addWidget(self._details)

        # 底部状态栏与按钮
        bot_layout = QHBoxLayout()
        self._status_label = QLabel("就绪", self)
        bot_layout.addWidget(self._status_label)
        bot_layout.addStretch()

        self._start_btn = QPushButton("开始处理", self)
        self._start_btn.setDefault(True)
        self._start_btn.clicked.connect(self._on_start)
        bot_layout.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("取消", self)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        bot_layout.addWidget(self._cancel_btn)

        self._open_dir_btn = QPushButton("打开输出文件夹", self)
        self._open_dir_btn.setEnabled(False)
        self._open_dir_btn.clicked.connect(self._on_open_output_dir)
        bot_layout.addWidget(self._open_dir_btn)

        self._close_btn = QPushButton("关闭", self)
        self._close_btn.clicked.connect(self.close)
        bot_layout.addWidget(self._close_btn)

        right_box.addLayout(bot_layout)
        main_layout.addLayout(right_box)

        # 轮询定时器
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._runner.poll)

        # 默认选中第一个功能
        self._select_first_tool()

    def _populate_tool_list(self) -> None:
        """按分类填充左侧功能列表，分类名作为禁用标题项。"""
        tools_by_cat: Dict[str, List[Any]] = {cat: [] for cat in CATEGORIES}
        for spec in TOOL_SPECS:
            if spec.category in tools_by_cat:
                tools_by_cat[spec.category].append(spec)

        for cat in CATEGORIES:
            # 分类标题项
            cat_item = QListWidgetItem("【 {0} 】".format(cat))
            cat_item.setFlags(Qt.ItemFlag.NoItemFlags)
            cat_item.setForeground(Qt.GlobalColor.darkGray)
            self._tool_list.addItem(cat_item)

            for spec in tools_by_cat[cat]:
                item = QListWidgetItem("  {0}".format(spec.label))
                item.setData(Qt.ItemDataRole.UserRole, spec.id)
                self._tool_list.addItem(item)

    def _select_first_tool(self) -> None:
        for i in range(self._tool_list.count()):
            item = self._tool_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole):
                self._tool_list.setCurrentItem(item)
                break

    def _current_tool_id(self) -> str:
        item = self._tool_list.currentItem()
        if item:
            tid = item.data(Qt.ItemDataRole.UserRole)
            if tid:
                return str(tid)
        return TOOL_MERGE

    def _on_tool_changed(
        self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]
    ) -> None:
        if not current:
            return
        tid = current.data(Qt.ItemDataRole.UserRole)
        if not tid:
            return
        spec = TOOL_SPEC_BY_ID.get(tid)
        if not spec:
            return

        # 更新横幅说明与拖放区提示
        desc_text = "{0}：{1}\n提示：{2}".format(spec.label, spec.description, spec.hint)
        self._desc_label.setText(desc_text)

        accepts_str = " ".join(spec.accepts)
        self._drop_zone.set_hint(
            "支持 {0} —— 可多选，也可拖入整个文件夹".format(accepts_str)
        )

        # 仅 merge 支持上下移动排序
        is_merge = tid == TOOL_MERGE
        self._move_up_btn.setVisible(is_merge)
        self._move_down_btn.setVisible(is_merge)

        # 切换选项面板
        idx = TOOL_IDS.index(tid) if tid in TOOL_IDS else 0
        self._options_stack.setCurrentIndex(idx)

    # --- 各工具专属选项面板构建 ---

    def _build_options_pages(self) -> None:
        # 1. merge
        p_merge = QWidget()
        l_merge = QFormLayout(p_merge)
        self._merge_name = QLineEdit(p_merge)
        self._merge_name.setPlaceholderText("缺省为「<首个文件>_合并.pdf」")
        l_merge.addRow("输出文件名：", self._merge_name)
        self._options_stack.addWidget(p_merge)

        # 2. split
        p_split = QWidget()
        l_split = QFormLayout(p_split)
        self._split_mode = QComboBox(p_split)
        self._split_mode.addItems(["逐页拆分 (each)", "按固定页数拆分 (every-n)", "按指定范围拆分 (range)"])
        self._split_every = QSpinBox(p_split)
        self._split_every.setRange(1, 9999)
        self._split_every.setValue(1)
        self._split_ranges = QLineEdit(p_split)
        self._split_ranges.setPlaceholderText("如 1-3,5-8,10")
        l_split.addRow("拆分模式：", self._split_mode)
        l_split.addRow("每组页数：", self._split_every)
        l_split.addRow("页码范围：", self._split_ranges)
        self._options_stack.addWidget(p_split)

        # 3. extract
        p_extract = QWidget()
        l_extract = QFormLayout(p_extract)
        self._extract_pages = QLineEdit(p_extract)
        self._extract_pages.setPlaceholderText("如 1-5,8,11-13（必填）")
        l_extract.addRow("提取页码：", self._extract_pages)
        self._options_stack.addWidget(p_extract)

        # 4. delete
        p_delete = QWidget()
        l_delete = QFormLayout(p_delete)
        self._delete_pages = QLineEdit(p_delete)
        self._delete_pages.setPlaceholderText("如 2,4-6（必填）")
        l_delete.addRow("删除页码：", self._delete_pages)
        self._options_stack.addWidget(p_delete)

        # 5. rotate
        p_rotate = QWidget()
        l_rotate = QFormLayout(p_rotate)
        self._rotate_deg = QComboBox(p_rotate)
        self._rotate_deg.addItem("顺时针 90°", 90)
        self._rotate_deg.addItem("顺时针 180°", 180)
        self._rotate_deg.addItem("逆时针 90° (270°)", 270)
        self._rotate_pages = QLineEdit(p_rotate)
        self._rotate_pages.setPlaceholderText("留空表示全部页面；也可填 1,3-5")
        l_rotate.addRow("旋转角度：", self._rotate_deg)
        l_rotate.addRow("生效页面：", self._rotate_pages)
        self._options_stack.addWidget(p_rotate)

        # 6. to_images
        p_to_img = QWidget()
        l_to_img = QFormLayout(p_to_img)
        self._to_img_fmt = QComboBox(p_to_img)
        self._to_img_fmt.addItems(["PNG", "JPG"])
        self._to_img_dpi = QSpinBox(p_to_img)
        self._to_img_dpi.setRange(36, 600)
        self._to_img_dpi.setValue(150)
        self._to_img_pages = QLineEdit(p_to_img)
        self._to_img_pages.setPlaceholderText("留空表示全部页面")
        l_to_img.addRow("导出格式：", self._to_img_fmt)
        l_to_img.addRow("分辨率 DPI：", self._to_img_dpi)
        l_to_img.addRow("页面范围：", self._to_img_pages)
        self._options_stack.addWidget(p_to_img)

        # 7. images_to_pdf
        p_img_pdf = QWidget()
        l_img_pdf = QFormLayout(p_img_pdf)
        self._img_pdf_a4 = QCheckBox("A4 居中适应版面（默认原尺寸）", p_img_pdf)
        self._img_pdf_name = QLineEdit(p_img_pdf)
        self._img_pdf_name.setPlaceholderText("缺省为「<首个文件>_图片.pdf」")
        l_img_pdf.addRow("版面选项：", self._img_pdf_a4)
        l_img_pdf.addRow("输出文件名：", self._img_pdf_name)
        self._options_stack.addWidget(p_img_pdf)

        # 8. to_text
        p_text = QWidget()
        l_text = QFormLayout(p_text)
        self._to_text_pages = QLineEdit(p_text)
        self._to_text_pages.setPlaceholderText("留空表示全部页面")
        l_text.addRow("提取页面：", self._to_text_pages)
        self._options_stack.addWidget(p_text)

        # 9. watermark
        p_wm = QWidget()
        l_wm = QFormLayout(p_wm)
        self._wm_text = QLineEdit(p_wm)
        self._wm_text.setText("内部机密")
        self._wm_font_size = QSpinBox(p_wm)
        self._wm_font_size.setRange(8, 200)
        self._wm_font_size.setValue(48)
        self._wm_opacity = QSpinBox(p_wm)
        self._wm_opacity.setRange(1, 100)
        self._wm_opacity.setValue(30)
        self._wm_opacity.setSuffix(" %（颜色减淡模拟）")
        self._wm_angle = QSpinBox(p_wm)
        self._wm_angle.setRange(-180, 180)
        self._wm_angle.setValue(45)
        self._wm_mode = QComboBox(p_wm)
        self._wm_mode.addItem("页面居中 (center)", "center")
        self._wm_mode.addItem("全页平铺 (tiled)", "tiled")
        self._wm_color = QLineEdit(p_wm)
        self._wm_color.setText("#ff0000")
        self._wm_pages = QLineEdit(p_wm)
        self._wm_pages.setPlaceholderText("留空表示全部页面")
        l_wm.addRow("水印文字：", self._wm_text)
        l_wm.addRow("文字大小：", self._wm_font_size)
        l_wm.addRow("不透明度：", self._wm_opacity)
        l_wm.addRow("旋转角度：", self._wm_angle)
        l_wm.addRow("排版方式：", self._wm_mode)
        l_wm.addRow("文字颜色：", self._wm_color)
        l_wm.addRow("生效页面：", self._wm_pages)
        self._options_stack.addWidget(p_wm)

        # 10. page_numbers
        p_pn = QWidget()
        l_pn = QFormLayout(p_pn)
        self._pn_pos = QComboBox(p_pn)
        self._pn_pos.addItem("底部居中", "bottom-center")
        self._pn_pos.addItem("底部靠左", "bottom-left")
        self._pn_pos.addItem("底部靠右", "bottom-right")
        self._pn_pos.addItem("顶部居中", "top-center")
        self._pn_pos.addItem("顶部靠左", "top-left")
        self._pn_pos.addItem("顶部靠右", "top-right")

        self._pn_fmt = QComboBox(p_pn)
        self._pn_fmt.addItems(["第n页/共N页", "第n页", "n/N", "-n-", "n"])

        self._pn_start = QSpinBox(p_pn)
        self._pn_start.setRange(1, 9999)
        self._pn_start.setValue(1)

        self._pn_skip_first = QCheckBox("跳过首页（封面不显示）", p_pn)
        self._pn_font_size = QSpinBox(p_pn)
        self._pn_font_size.setRange(6, 72)
        self._pn_font_size.setValue(10)
        self._pn_margin = QSpinBox(p_pn)
        self._pn_margin.setRange(6, 144)
        self._pn_margin.setValue(24)
        self._pn_color = QLineEdit(p_pn)
        self._pn_color.setText("#000000")

        l_pn.addRow("对齐位置：", self._pn_pos)
        l_pn.addRow("编号格式：", self._pn_fmt)
        l_pn.addRow("起始页码：", self._pn_start)
        l_pn.addRow("首页跳过：", self._pn_skip_first)
        l_pn.addRow("字体大小：", self._pn_font_size)
        l_pn.addRow("边距磅值：", self._pn_margin)
        l_pn.addRow("页码颜色：", self._pn_color)
        self._options_stack.addWidget(p_pn)

        # 11. metadata
        p_meta = QWidget()
        l_meta = QFormLayout(p_meta)
        self._meta_title = QLineEdit(p_meta)
        self._meta_author = QLineEdit(p_meta)
        self._meta_subject = QLineEdit(p_meta)
        self._meta_keywords = QLineEdit(p_meta)
        l_meta.addRow("文档标题：", self._meta_title)
        l_meta.addRow("作者：", self._meta_author)
        l_meta.addRow("主题：", self._meta_subject)
        l_meta.addRow("关键字：", self._meta_keywords)
        self._options_stack.addWidget(p_meta)

        # 12. encrypt
        p_enc = QWidget()
        l_enc = QFormLayout(p_enc)
        self._enc_user_pw = QLineEdit(p_enc)
        self._enc_user_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._enc_owner_pw = QLineEdit(p_enc)
        self._enc_owner_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._enc_owner_pw.setPlaceholderText("缺省同打开密码")

        perm_box = QHBoxLayout()
        self._enc_print = QCheckBox("打印", p_enc)
        self._enc_print.setChecked(True)
        self._enc_copy = QCheckBox("复制", p_enc)
        self._enc_modify = QCheckBox("修改", p_enc)
        self._enc_annotate = QCheckBox("批注", p_enc)
        perm_box.addWidget(self._enc_print)
        perm_box.addWidget(self._enc_copy)
        perm_box.addWidget(self._enc_modify)
        perm_box.addWidget(self._enc_annotate)

        l_enc.addRow("打开密码：", self._enc_user_pw)
        l_enc.addRow("权限密码：", self._enc_owner_pw)
        l_enc.addRow("允许权限：", perm_box)
        self._options_stack.addWidget(p_enc)

        # 13. decrypt
        p_dec = QWidget()
        l_dec = QFormLayout(p_dec)
        self._dec_pw = QLineEdit(p_dec)
        self._dec_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._dec_pw.setPlaceholderText("若为加密文档请输入密码；仅所有者锁定时可留空")
        l_dec.addRow("解除密码：", self._dec_pw)
        self._options_stack.addWidget(p_dec)

        # 14. compress
        p_comp = QWidget()
        l_comp = QFormLayout(p_comp)
        self._comp_strip_meta = QCheckBox("剥离冗余元数据 (Producer/Creator 等)", p_comp)
        self._comp_strip_meta.setChecked(True)
        l_comp.addRow("优化项：", self._comp_strip_meta)
        self._options_stack.addWidget(p_comp)

    def _collect_options(self, tool_id: str) -> Dict[str, Any]:
        """按当前工具收集选项字典。"""
        opts: Dict[str, Any] = {}
        if tool_id == TOOL_MERGE:
            name = self._merge_name.text().strip()
            if name:
                opts["output_name"] = name
        elif tool_id == TOOL_SPLIT:
            mode_idx = self._split_mode.currentIndex()
            modes = ["each", "every-n", "range"]
            opts["mode"] = modes[mode_idx]
            opts["every"] = self._split_every.value()
            opts["ranges"] = self._split_ranges.text().strip()
        elif tool_id == TOOL_EXTRACT:
            opts["pages"] = self._extract_pages.text().strip()
        elif tool_id == TOOL_DELETE:
            opts["pages"] = self._delete_pages.text().strip()
        elif tool_id == TOOL_ROTATE:
            opts["degrees"] = self._rotate_deg.currentData()
            opts["pages"] = self._rotate_pages.text().strip()
        elif tool_id == TOOL_TO_IMAGES:
            opts["image_format"] = self._to_img_fmt.currentText().lower()
            opts["dpi"] = self._to_img_dpi.value()
            opts["pages"] = self._to_img_pages.text().strip()
        elif tool_id == TOOL_IMAGES_TO_PDF:
            opts["a4"] = self._img_pdf_a4.isChecked()
            name = self._img_pdf_name.text().strip()
            if name:
                opts["output_name"] = name
        elif tool_id == TOOL_TO_TEXT:
            opts["pages"] = self._to_text_pages.text().strip()
        elif tool_id == TOOL_WATERMARK:
            opts["text"] = self._wm_text.text().strip()
            opts["font_size"] = float(self._wm_font_size.value())
            opts["opacity"] = self._wm_opacity.value()
            opts["angle"] = float(self._wm_angle.value())
            opts["mode"] = self._wm_mode.currentData()
            opts["color"] = self._wm_color.text().strip() or "#ff0000"
            opts["pages"] = self._wm_pages.text().strip()
        elif tool_id == TOOL_PAGE_NUMBERS:
            opts["position"] = self._pn_pos.currentData()
            opts["format"] = self._pn_fmt.currentText()
            opts["start"] = self._pn_start.value()
            opts["skip_first"] = self._pn_skip_first.isChecked()
            opts["font_size"] = float(self._pn_font_size.value())
            opts["margin"] = float(self._pn_margin.value())
            opts["color"] = self._pn_color.text().strip() or "#000000"
        elif tool_id == TOOL_METADATA:
            t = self._meta_title.text().strip()
            a = self._meta_author.text().strip()
            s = self._meta_subject.text().strip()
            k = self._meta_keywords.text().strip()
            if any((t, a, s, k)):
                opts["title"] = t
                opts["author"] = a
                opts["subject"] = s
                opts["keywords"] = k
        elif tool_id == TOOL_ENCRYPT:
            opts["user_password"] = self._enc_user_pw.text().strip()
            opts["owner_password"] = self._enc_owner_pw.text().strip()
            opts["allow_print"] = self._enc_print.isChecked()
            opts["allow_copy"] = self._enc_copy.isChecked()
            opts["allow_modify"] = self._enc_modify.isChecked()
            opts["allow_annotate"] = self._enc_annotate.isChecked()
        elif tool_id == TOOL_DECRYPT:
            opts["password"] = self._dec_pw.text().strip()
        elif tool_id == TOOL_COMPRESS:
            opts["strip_metadata"] = self._comp_strip_meta.isChecked()
        return opts

    # --- 文件添加与表格维护 ---

    def _on_add_files(self) -> None:
        tid = self._current_tool_id()
        spec = TOOL_SPEC_BY_ID.get(tid)
        accepts = spec.accepts if spec else PDF_SUFFIXES
        flt = "支持文件 ({0});;所有文件 (*)".format(" ".join("*" + s for s in accepts))
        picked, _ = QFileDialog.getOpenFileNames(self, "添加待处理文件", "", flt)
        if picked:
            self._ingest_paths([Path(p) for p in picked])

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            tid = self._current_tool_id()
            found = expand_sources([folder], tool_id=tid)
            self._ingest_paths(found)

    def _ingest_paths(self, paths: List[Path]) -> None:
        tid = self._current_tool_id()
        spec = TOOL_SPEC_BY_ID.get(tid)
        accepts = spec.accepts if spec else (PDF_SUFFIXES + IMAGE_SUFFIXES)

        skipped = 0
        for path in paths:
            p = Path(path).resolve()
            if not p.is_file():
                continue
            if p.suffix.lower() not in accepts:
                skipped += 1
                continue
            key = str(p).lower()
            if key in self._rows:
                continue

            row = self._table.rowCount()
            self._rows[key] = row
            self._sources.append(p)
            self._table.insertRow(row)

            item_src = QTableWidgetItem(p.name)
            item_src.setToolTip(str(p))
            self._table.setItem(row, 0, item_src)

            item_status = QTableWidgetItem("待处理")
            self._table.setItem(row, 1, item_status)

            item_out = QTableWidgetItem("—")
            self._table.setItem(row, 2, item_out)

        self._update_ui_state()
        if skipped > 0:
            QMessageBox.information(
                self,
                "提示",
                "已跳过 {0} 个格式不匹配的文件（当前功能仅支持 {1}）。".format(
                    skipped, "、".join(accepts)
                ),
            )

    def _on_remove_selected(self) -> None:
        selected_rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()}, reverse=True
        )
        for row in selected_rows:
            if row < len(self._sources):
                p = self._sources.pop(row)
                self._rows.pop(str(p).lower(), None)
            self._table.removeRow(row)
        # 重建索引映射
        self._rebuild_row_map()
        self._update_ui_state()

    def _on_clear(self) -> None:
        self._sources.clear()
        self._rows.clear()
        self._table.setRowCount(0)
        self._details.clear()
        self._update_ui_state()

    def _on_move_up(self) -> None:
        row = self._table.currentRow()
        if row <= 0 or row >= len(self._sources):
            return
        self._sources[row - 1], self._sources[row] = (
            self._sources[row],
            self._sources[row - 1],
        )
        self._refresh_table()
        self._table.selectRow(row - 1)

    def _on_move_down(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._sources) - 1:
            return
        self._sources[row], self._sources[row + 1] = (
            self._sources[row + 1],
            self._sources[row],
        )
        self._refresh_table()
        self._table.selectRow(row + 1)

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        self._rows.clear()
        for idx, p in enumerate(self._sources):
            key = str(p).lower()
            self._rows[key] = idx
            self._table.insertRow(idx)
            item_src = QTableWidgetItem(p.name)
            item_src.setToolTip(str(p))
            self._table.setItem(idx, 0, item_src)
            self._table.setItem(idx, 1, QTableWidgetItem("待处理"))
            self._table.setItem(idx, 2, QTableWidgetItem("—"))

    def _rebuild_row_map(self) -> None:
        self._rows.clear()
        for idx, p in enumerate(self._sources):
            self._rows[str(p).lower()] = idx

    def _update_ui_state(self) -> None:
        count = len(self._sources)
        self._status_label.setText("已添加 {0} 个文件".format(count))

    def _on_browse_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self._out_dir_edit.setText(folder)

    # --- 任务执行与调度 ---

    def _on_start(self) -> None:
        if self._runner.is_running:
            return
        if not self._sources:
            QMessageBox.information(self, "提示", "请先添加待处理的文件。")
            return

        tid = self._current_tool_id()
        spec = TOOL_SPEC_BY_ID.get(tid)
        if not spec:
            return

        if spec.plural and len(self._sources) < 2 and tid == TOOL_MERGE:
            QMessageBox.warning(self, "提示", "合并操作至少需要添加 2 个 PDF 文件。")
            return

        if self._busy_check is not None and self._busy_check():
            QMessageBox.warning(
                self, "提示", "主窗口已有任务正在运行，请等待其完成后再操作。"
            )
            return

        options = self._collect_options(tid)

        # 校验输入非空
        if tid == TOOL_WATERMARK and not options.get("text"):
            QMessageBox.warning(self, "提示", "请填写水印文字内容。")
            return
        if tid == TOOL_ENCRYPT and not options.get("user_password"):
            QMessageBox.warning(self, "提示", "加密操作必须设置打开密码。")
            return
        if tid in (TOOL_EXTRACT, TOOL_DELETE) and not options.get("pages"):
            QMessageBox.warning(self, "提示", "请指定要操作的页码范围。")
            return

        out_dir = self._out_dir_edit.text().strip() or None
        overwrite = self._overwrite_box.isChecked()

        for r in range(self._table.rowCount()):
            self._table.setItem(r, 1, QTableWidgetItem("处理中…"))
            self._table.setItem(r, 2, QTableWidgetItem("—"))

        total_steps = 1 if spec.plural else len(self._sources)
        self._progress.setRange(0, total_steps)
        self._progress.setValue(0)
        self._progress.setVisible(True)

        self._details.clear()
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._open_dir_btn.setEnabled(False)
        self._status_label.setText("正在处理…")

        started = self._runner.start(
            TaskSpec(
                name="pdf_tool_" + tid,
                target=run_pdf_tool,
                args=(tid, list(self._sources)),
                kwargs={
                    "output_dir": out_dir,
                    "overwrite": overwrite,
                    "options": options,
                    "on_progress": self._emit_progress,
                },
                timeout_seconds=600,
            ),
            on_event=self._on_task_event,
            on_done=self._on_done,
        )
        if not started:
            QMessageBox.warning(self, "提示", "已有任务正在运行。")
            return
        self._timer.start()

    def _emit_progress(self, done: int, total: int, record: PdfToolRecord) -> None:
        self.progress.emit(done, total, record)

    def _on_progress(self, done: int, total: int, record: PdfToolRecord) -> None:
        self._progress.setValue(done)
        key = str(record.source).lower()
        row = self._rows.get(key)
        spec = TOOL_SPEC_BY_ID.get(record.tool)
        if row is not None and row < self._table.rowCount():
            status_text = "{0} · {1:.2f}s".format(record.status, record.elapsed_seconds)
            item_status = QTableWidgetItem(status_text)
            if not record.ok:
                item_status.setForeground(Qt.GlobalColor.red)
            else:
                item_status.setForeground(Qt.GlobalColor.darkGreen)
            self._table.setItem(row, 1, item_status)

            out_names = "、".join(p.name for p in record.outputs) if record.outputs else "（无产物）"
            self._table.setItem(row, 2, QTableWidgetItem(out_names))

        if spec and spec.plural:
            # 整批产物：除首行更新产物外，其余参与行也更新状态，避免悬挂「处理中…」
            for r in range(self._table.rowCount()):
                if r == row:
                    continue
                if record.ok:
                    status_str = "已合并" if record.tool == TOOL_MERGE else "已合成"
                    it = QTableWidgetItem(status_str)
                    it.setForeground(Qt.GlobalColor.darkGreen)
                    self._table.setItem(r, 1, it)
                else:
                    it_fail = QTableWidgetItem(record.status)
                    it_fail.setForeground(Qt.GlobalColor.red)
                    self._table.setItem(r, 1, it_fail)

        line = "{0} [{1}] {2}".format(
            "✓" if record.ok else "✗", record.label, record.source.name
        )
        if record.outputs:
            line += " → " + "、".join(p.name for p in record.outputs)
        if not record.ok:
            line += " [{0}] {1}".format(record.error_code or "?", record.detail)
        elif record.detail:
            line += " ({0})".format(record.detail)
        self._details.appendPlainText(line)
        if record.note:
            self._details.appendPlainText("    提示: {0}".format(record.note))

    def _on_task_event(self, event: TaskEvent) -> None:
        if event.detail:
            self._details.appendPlainText("[{0}] {1}".format(event.status, event.detail))

    def _on_done(self, result: Any) -> None:
        self._timer.stop()
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._open_dir_btn.setEnabled(True)

        if isinstance(result, PdfToolBatchResult):
            self._last_result = result
            self._status_label.setText(result.summary())
            self._details.appendPlainText("\n" + result.summary())
            if result.cancelled:
                QMessageBox.information(self, "操作已取消", result.summary())
            elif result.failed > 0:
                QMessageBox.warning(self, "处理完成（存在失败项）", result.summary())
            else:
                QMessageBox.information(self, "处理完成", result.summary())
        else:
            self._status_label.setText("操作结束")

    def _on_cancel(self) -> None:
        self._runner.cancel()
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("正在取消…")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._runner.is_running:
            reply = QMessageBox.question(
                self,
                "任务正在运行",
                "当前有任务正在执行，确定要取消并退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._runner.cancel()
                self._timer.stop()
                event.accept()
            else:
                event.ignore()
        else:
            self._timer.stop()
            event.accept()

    def _on_open_output_dir(self) -> None:
        out_dir = self._out_dir_edit.text().strip()
        if not out_dir:
            if self._last_result and self._last_result.records:
                for rec in self._last_result.records:
                    if rec.outputs:
                        out_dir = str(rec.outputs[0].parent)
                        break
            if not out_dir and self._sources:
                out_dir = str(self._sources[0].parent)
        if out_dir and Path(out_dir).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        else:
            QMessageBox.information(self, "打开目录", "输出目录尚未生成或不存在。")

    # --- 拖放事件支持 ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_zone.set_drag_over(True)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_zone.set_drag_over(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_zone.set_drag_over(False)
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        if paths:
            tid = self._current_tool_id()
            found = expand_sources(paths, tool_id=tid)
            self._ingest_paths(found)
            event.acceptProposedAction()
