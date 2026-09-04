# -*- coding: utf-8 -*-
"""修订评审面板（底部工具箱第 8 个 Tab）。

以标准 9 列表格为核心模型（增加章节列以便定位）：
1. 顶部工具栏：出稿、回流、新增/删除、生成证据、导出评审纪要。
2. 状态微型仪表盘：总数、已确认、待确认、遗留胶囊统计 + 实时模糊过滤。
3. 高级交互表格：胶囊徽标极速切换状态、日历选择、章节联想下拉、
   双击正文联动定位、全键盘快捷键支持。
4. 导出会议评审稿与横向 A4 评审纪要弹窗。
"""

from __future__ import annotations

import difflib
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import QDate, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPen, QShortcut


def reveal_in_file_manager(target_path: Union[str, Path]) -> None:
    """打开文件所在目录并在 Windows 下尝试高亮选中。"""
    path = Path(target_path).resolve()
    if not path.exists():
        return

    import subprocess
    import sys

    if sys.platform == "win32":
        try:
            subprocess.Popen(f'explorer /select,"{path}"')
            return
        except Exception:
            pass

    folder = path.parent if path.is_file() else path
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.review.review_docx import (
    build_review_draft_docx,
    build_review_minutes_docx,
    extract_comments_from_docx,
    generate_evidence_for_comment,
)
from doc_tool.application.review.review_store import ReviewComment, ReviewStore

COL_SEQ = 0
COL_AUTHOR = 1
COL_CHAPTER = 2
COL_TEXT = 3
COL_ASSIGNEE = 4
COL_PLANNED_DATE = 5
COL_CONFIRM = 6
COL_NOTE = 7
COL_EVIDENCE = 8
COL_OPEN_ISSUE = 9

COLUMN_HEADERS = [
    "序号",
    "提出人",
    "章节",
    "评审问题",
    "责任人",
    "计划完成时间",
    "更改确认",
    "评审记录",
    "更改结果与证据",
    "遗留问题",
]

_CHAPTER_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*|[第][0-9一二三四五六七八九十]+[章节部分篇])")


def _extract_chapter_no_and_title(rel_path: str, content_index=None) -> Tuple[str, str]:
    """从 rel_path 与内容索引推导 (chapter_no, title)。"""
    stem = Path(rel_path).stem
    if stem == "_index":
        parts = rel_path.split("/")
        if len(parts) >= 2:
            stem = parts[-2]

    # 优先从文件名提取编号和标题，例如 "3.7.9 呼吸机应用升级" -> ("3.7.9", "呼吸机应用升级")
    match = _CHAPTER_NUM_RE.match(stem)
    if match:
        ch_no = match.group(1).strip()
        title = stem[match.end():].lstrip(" -_") or stem
        return ch_no, title

    # 若文件名无编号前缀，尝试从索引中的首级标题提取
    if content_index is not None and hasattr(content_index, "headings"):
        headings = content_index.headings.get(rel_path, [])
        if headings:
            h1 = next((h.text.strip() for h in headings if getattr(h, "level", 0) == 1), headings[0].text.strip())
            m = _CHAPTER_NUM_RE.match(h1)
            if m:
                ch_no = m.group(1).strip()
                title = h1[m.end():].lstrip(" -_") or h1
                return ch_no, title
            return "", h1

    return "", stem


class PillBadgeDelegate(QStyledItemDelegate):
    """“更改确认”列胶囊徽标委托。"""

    def paint(self, painter: QPainter, option, index) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "未确认")
        app = QApplication.instance()
        is_dark = False
        if app is not None:
            from doc_tool.ui.styles import is_dark_theme
            is_dark = is_dark_theme(app)
        else:
            is_dark = option.palette.window().color().lightness() < 128

        if "已确认" in text:
            if is_dark:
                bg_color = QColor("#14532d")
                text_color = QColor("#86efac")
                border_color = QColor("#22c55e")
            else:
                bg_color = QColor("#dcfce7")
                text_color = QColor("#166534")
                border_color = QColor("#86efac")
            display_text = "✓ 已确认"
        elif "遗留" in text:
            if is_dark:
                bg_color = QColor("#3b0764")
                text_color = QColor("#c4b5fd")
                border_color = QColor("#8b5cf6")
            else:
                bg_color = QColor("#ede9fe")
                text_color = QColor("#5b21b6")
                border_color = QColor("#c4b5fd")
            display_text = "📌 遗留"
        else:  # 待确认 / 未确认
            if is_dark:
                bg_color = QColor("#451a03")
                text_color = QColor("#fde68a")
                border_color = QColor("#d97706")
            else:
                bg_color = QColor("#fef3c7")
                text_color = QColor("#92400e")
                border_color = QColor("#fcd34d")
            display_text = "⏳ 待确认"

        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 选中行背景保持
            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())

            rect = option.rect
            pill_w = min(max(rect.width() - 14, 60), 84)
            pill_h = 24
            x = rect.x() + (rect.width() - pill_w) // 2
            y = rect.y() + (rect.height() - pill_h) // 2
            pill_rect = QRect(x, y, pill_w, pill_h)

            painter.setBrush(QBrush(bg_color))
            painter.setPen(QPen(border_color, 1))
            painter.drawRoundedRect(pill_rect, 12, 12)

            painter.setPen(text_color)
            font = painter.font()
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, display_text)
        finally:
            painter.restore()


class DatePickerDelegate(QStyledItemDelegate):
    """“计划完成时间”列日历选择委托。"""

    def createEditor(self, parent: QWidget, option, index) -> QWidget:
        editor = QDateEdit(parent)
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("yyyy-MM-dd")
        current_text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        d = QDate.fromString(current_text, "yyyy-MM-dd")
        if d.isValid():
            editor.setDate(d)
        else:
            editor.setDate(QDate.currentDate())
        return editor

    def setModelData(self, editor: QWidget, model, index) -> None:
        if isinstance(editor, QDateEdit):
            date_str = editor.date().toString("yyyy-MM-dd")
            model.setData(index, date_str, Qt.ItemDataRole.EditRole)


class ChapterDelegate(QStyledItemDelegate):
    """“章节”列改动章节联想下拉委托。"""

    def __init__(self, get_chapters_callable: Callable[[], List[str]], parent=None):
        super().__init__(parent)
        self._get_chapters = get_chapters_callable

    def createEditor(self, parent: QWidget, option, index) -> QWidget:
        combo = QComboBox(parent)
        combo.setEditable(True)
        for ch in self._get_chapters():
            combo.addItem(ch)
        return combo

    def setEditorData(self, editor: QWidget, index) -> None:
        if isinstance(editor, QComboBox):
            val = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            editor.setCurrentText(val)

    def setModelData(self, editor: QWidget, model, index) -> None:
        if isinstance(editor, QComboBox):
            text = editor.currentText().strip()
            # 若选择了形如 "3.2 接口设计"，提取章节号 "3.2"
            parts = text.split(maxsplit=1)
            ch_no = parts[0] if parts else text
            model.setData(index, ch_no, Qt.ItemDataRole.EditRole)


class ExportReviewDraftDialog(QDialog):
    """「导出会议评审稿」向导弹窗。"""

    def __init__(
        self,
        *,
        document_name: str,
        document_version: str,
        changed_chapters: Sequence[Dict],
        default_output_dir: Path,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出会议评审稿 (Word)")
        self.resize(560, 440)

        self._document_name = document_name
        self._document_version = document_version
        self._changed_chapters = list(changed_chapters)
        self._chapter_checkboxes: List[QCheckBox] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 头部说明
        info_box = QFrame(self)
        info_box.setObjectName("statusContainer")
        info_layout = QVBoxLayout(info_box)
        meta_label = QLabel(
            f"<b>文档：</b>{document_name} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>版本：</b>v{document_version} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>改动章节：</b>共 {len(changed_chapters)} 节",
            info_box,
        )
        info_layout.addWidget(meta_label)
        layout.addWidget(info_box)

        # 勾选章节
        head_layout = QHBoxLayout()
        head_layout.addWidget(QLabel("请勾选本次需要纳入评审的改动章节：", self))
        head_layout.addStretch(1)
        self._select_all_btn = QPushButton("全选 / 取消全选", self)
        self._select_all_btn.setProperty("btnRole", "secondary")
        self._select_all_btn.clicked.connect(self._toggle_select_all)
        head_layout.addWidget(self._select_all_btn)
        layout.addLayout(head_layout)

        # 章节复选框列表
        from PySide6.QtWidgets import QScrollArea

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(6)

        status_map = {"added": "新增", "modified": "已修改", "deleted": "已删除", "normal": "正式"}
        if not changed_chapters:
            scroll_layout.addWidget(QLabel("（当前未检测到章节，将生成空白评审模板）", scroll_content))
        else:
            for item in changed_chapters:
                ch_no = item.get("chapter_no", "")
                title = item.get("title", "")
                st = status_map.get(item.get("status", ""), "正式")
                diff = item.get("diff_summary", "")
                prefix = f"[{st}]"
                ch_title = f"{ch_no} {title}".strip()
                label_text = f"{prefix} {ch_title}"
                if diff:
                    label_text += f" ({diff})"
                cb = QCheckBox(label_text, scroll_content)
                cb.setChecked(True)
                cb.setProperty("chapter_item", item)
                self._chapter_checkboxes.append(cb)
                scroll_layout.addWidget(cb)
        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # 导出选项
        self._cb_highlight = QCheckBox("以红色高亮突出显示变动内容（新增与修改红色加粗，旧文字带删除线）", self)
        self._cb_highlight.setChecked(True)
        layout.addWidget(self._cb_highlight)

        self._cb_append_table = QCheckBox("在文档末尾附带空白 9 列评审记录表 (供会议室就地填写)", self)
        self._cb_append_table.setChecked(True)
        layout.addWidget(self._cb_append_table)

        self._cb_open_folder = QCheckBox("导出完成后打开所在文件夹", self)
        self._cb_open_folder.setChecked(True)
        layout.addWidget(self._cb_open_folder)

        # 提示说明
        tip_lbl = QLabel(
            "💡 提示：导出的评审稿供会议投屏与线下审阅；评委意见可在文末附录表格中填写；若要修改正文内容，请在 doc-tool 中直接编辑 Markdown。",
            self,
        )
        tip_lbl.setWordWrap(True)
        tip_lbl.setObjectName("statusMuted")
        layout.addWidget(tip_lbl)

        # 输出路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("输出路径:", self))
        date_str = datetime.now().strftime("%m%d")
        default_filename = f"评审稿-{document_name}-v{document_version}-{date_str}.docx"
        self._default_path = default_output_dir / default_filename
        self._path_edit = QLineEdit(str(self._default_path), self)
        path_layout.addWidget(self._path_edit, 1)
        browse_btn = QPushButton("浏览...", self)
        browse_btn.clicked.connect(self._browse_path)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        self._export_btn = QPushButton("开始导出 (DOCX)", self)
        self._export_btn.setProperty("btnRole", "primary")
        self._export_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._export_btn)
        layout.addLayout(btn_layout)

    def _toggle_select_all(self) -> None:
        if not self._chapter_checkboxes:
            return
        all_checked = all(cb.isChecked() for cb in self._chapter_checkboxes)
        for cb in self._chapter_checkboxes:
            cb.setChecked(not all_checked)

    def _browse_path(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择保存位置",
            self._path_edit.text(),
            "Word 文档 (*.docx)",
        )
        if file_path:
            self._path_edit.setText(file_path)

    def selected_chapters(self) -> List[Dict]:
        if not self._chapter_checkboxes:
            return self._changed_chapters
        selected = []
        for cb in self._chapter_checkboxes:
            if cb.isChecked():
                selected.append(cb.property("chapter_item"))
        return selected

    def include_blank_table(self) -> bool:
        return self._cb_append_table.isChecked()

    def highlight_changes(self) -> bool:
        return self._cb_highlight.isChecked()

    def open_folder(self) -> bool:
        return self._cb_open_folder.isChecked()

    def output_path(self) -> Path:
        return Path(self._path_edit.text()).resolve()


class ReviewPanel(QWidget):
    """9 列表格评审面板。"""

    # 当需要打开并定位到文件某行时触发
    request_open_file = Signal(str, int)

    def __init__(
        self,
        *,
        store: ReviewStore,
        content_root: Union[str, Path],
        snapshot=None,
        index=None,
        project_paths=None,
        on_open_file: Optional[Callable[[str, int], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._content_root = Path(content_root).resolve()
        self._snapshot = snapshot
        self._index = index
        self._project_paths = project_paths
        self._on_open_file = on_open_file
        self._writable = writable
        self._comments: List[ReviewComment] = []
        self._filtered_indices: List[int] = []

        self._build_ui()
        self.set_writable(self._writable)
        self.reload()

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._btn_add.setEnabled(writable)
        self._btn_del.setEnabled(writable)
        self._btn_import_word.setEnabled(writable)
        self._btn_evidence.setEnabled(writable)
        self._btn_batch_confirm.setEnabled(writable)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # 1. 顶部工具栏 (4 大功能组 + VLine 隔离)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        # [出稿与回流组]
        self._btn_export_draft = QPushButton("导出评审稿 (Word)", self)
        self._btn_export_draft.setProperty("btnRole", "primary")
        self._btn_export_draft.setToolTip("提取当前改动章节与末尾空白评审表，导出会议 Word 稿")
        self._btn_export_draft.clicked.connect(self._on_export_draft)
        toolbar.addWidget(self._btn_export_draft)

        self._btn_import_word = QPushButton("导入 Word 附录意见表", self)
        self._btn_import_word.setProperty("btnRole", "secondary")
        self._btn_import_word.setToolTip("从会议 Word 评审稿文末附录表格中提取评审意见条目（不包含正文修改同步）")
        self._btn_import_word.clicked.connect(self._on_import_word)
        toolbar.addWidget(self._btn_import_word)

        toolbar.addWidget(self._create_vline())

        # [行编辑维护组]
        self._btn_add = QPushButton("+ 新增意见", self)
        self._btn_add.setProperty("btnRole", "secondary")
        self._btn_add.setToolTip("在末尾添加一行新意见 (快捷键: Ctrl+N)")
        self._btn_add.clicked.connect(self._on_add_row)
        toolbar.addWidget(self._btn_add)

        self._btn_del = QPushButton("- 删除选中", self)
        self._btn_del.setProperty("btnRole", "secondary")
        self._btn_del.setToolTip("删除当前选中的意见行 (快捷键: Delete)")
        self._btn_del.clicked.connect(self._on_delete_selected)
        toolbar.addWidget(self._btn_del)

        toolbar.addWidget(self._create_vline())

        # [闭环辅助组]
        self._btn_evidence = QPushButton("⚡ 一键生成证据", self)
        self._btn_evidence.setProperty("btnRole", "secondary")
        self._btn_evidence.setToolTip("选中行后自动比对基线与当前章节，抓取新增/修改行数填入证据")
        self._btn_evidence.clicked.connect(self._on_generate_evidence)
        toolbar.addWidget(self._btn_evidence)

        toolbar.addWidget(self._create_vline())

        # [最终交付组]
        self._btn_export_minutes = QPushButton("📄 导出评审纪要 (DOCX)", self)
        self._btn_export_minutes.setProperty("btnRole", "primary")
        self._btn_export_minutes.setToolTip("生成标准横向 A4 9 列表格评审纪要 DOCX 及同源 Markdown")
        self._btn_export_minutes.clicked.connect(self._on_export_minutes)
        toolbar.addWidget(self._btn_export_minutes)

        toolbar.addStretch(1)
        main_layout.addLayout(toolbar)

        # 2. 状态微型仪表盘 (Status Dashboard) + 搜索过滤
        dash_layout = QHBoxLayout()
        dash_layout.setContentsMargins(2, 2, 2, 2)
        dash_layout.setSpacing(12)

        self._lbl_total = QLabel("● 总数: 0", self)
        self._lbl_total.setProperty("statusTone", "neutral")
        self._lbl_total.setProperty("strong", "true")
        dash_layout.addWidget(self._lbl_total)

        self._lbl_confirmed = QLabel("✓ 已确认: 0", self)
        self._lbl_confirmed.setProperty("statusTone", "success")
        self._lbl_confirmed.setProperty("strong", "true")
        dash_layout.addWidget(self._lbl_confirmed)

        self._lbl_unconfirmed = QLabel("⏳ 待确认: 0", self)
        self._lbl_unconfirmed.setProperty("statusTone", "warning")
        self._lbl_unconfirmed.setProperty("strong", "true")
        dash_layout.addWidget(self._lbl_unconfirmed)

        self._lbl_open = QLabel("📌 遗留: 0", self)
        self._lbl_open.setProperty("statusTone", "purple")
        self._lbl_open.setProperty("strong", "true")
        dash_layout.addWidget(self._lbl_open)

        dash_layout.addStretch(1)

        self._search_edit = QLineEdit(self)
        self._search_edit.setPlaceholderText("🔍 搜索过滤 (提出人/责任人/章节/关键字)...")
        self._search_edit.setMaximumWidth(280)
        self._search_edit.textChanged.connect(self._apply_filter)
        dash_layout.addWidget(self._search_edit)

        main_layout.addLayout(dash_layout)

        # 3. 10 列表格
        self._table = QTableWidget(self)
        self._table.setColumnCount(len(COLUMN_HEADERS))
        self._table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(True)
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        # 列宽与伸展
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COL_SEQ, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_SEQ, 50)
        header.setSectionResizeMode(COL_AUTHOR, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_AUTHOR, 80)
        header.setSectionResizeMode(COL_CHAPTER, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_CHAPTER, 75)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_ASSIGNEE, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_ASSIGNEE, 80)
        header.setSectionResizeMode(COL_PLANNED_DATE, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_PLANNED_DATE, 110)
        header.setSectionResizeMode(COL_CONFIRM, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_CONFIRM, 100)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(COL_NOTE, 160)
        header.setSectionResizeMode(COL_EVIDENCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_OPEN_ISSUE, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(COL_OPEN_ISSUE, 110)

        # 安装自定义委托
        self._pill_delegate = PillBadgeDelegate(self)
        self._table.setItemDelegateForColumn(COL_CONFIRM, self._pill_delegate)

        self._date_delegate = DatePickerDelegate(self)
        self._table.setItemDelegateForColumn(COL_PLANNED_DATE, self._date_delegate)

        self._chapter_delegate = ChapterDelegate(self._get_all_chapters, self)
        self._table.setItemDelegateForColumn(COL_CHAPTER, self._chapter_delegate)

        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        main_layout.addWidget(self._table, 1)

        # 4. 底部状态与操作辅助条
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(2, 2, 2, 2)

        self._status_tip = QLabel("就绪 | 双击「更改确认」切换状态 | 双击「章节」定位正文", self)
        self._status_tip.setObjectName("statusMuted")
        bottom_bar.addWidget(self._status_tip, 1)

        self._btn_jump = QPushButton("🎯 跳转正文定位", self)
        self._btn_jump.setProperty("btnRole", "secondary")
        self._btn_jump.clicked.connect(self._locate_current_section)
        bottom_bar.addWidget(self._btn_jump)

        self._btn_batch_confirm = QPushButton("✓ 批量设为已确认", self)
        self._btn_batch_confirm.setProperty("btnRole", "secondary")
        self._btn_batch_confirm.clicked.connect(self._batch_confirm_selected)
        bottom_bar.addWidget(self._btn_batch_confirm)

        main_layout.addLayout(bottom_bar)

        # 5. 全局快捷键
        QShortcut(QKeySequence("Ctrl+N"), self, self._on_add_row)
        QShortcut(QKeySequence("Delete"), self, self._on_delete_selected)

    def _create_vline(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setObjectName("statusMuted")
        return line

    # --- 数据加载与渲染 ---

    def reload(self) -> None:
        """从 ReviewStore 重载意见数据。"""
        self._comments = self._store.comments()
        self._apply_filter()
        self._update_dashboard()

    def _update_dashboard(self) -> None:
        stats = self._store.stats()
        self._lbl_total.setText(f"● 总数: {stats['total']}")
        self._lbl_confirmed.setText(f"✓ 已确认: {stats['confirmed']}")
        self._lbl_unconfirmed.setText(f"⏳ 待确认: {stats['unconfirmed']}")
        self._lbl_open.setText(f"📌 遗留: {stats['open_issues']}")

    def _apply_filter(self) -> None:
        query = self._search_edit.text().strip().lower()
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._filtered_indices = []

        for idx, c in enumerate(self._comments):
            if query:
                match = (
                    query in (c.author or "").lower()
                    or query in (c.assignee or "").lower()
                    or query in (c.chapter_no or "").lower()
                    or query in (c.text or "").lower()
                    or query in (c.review_note or "").lower()
                    or query in (c.open_issue or "").lower()
                )
                if not match:
                    continue

            self._filtered_indices.append(idx)
            row = self._table.rowCount()
            self._table.insertRow(row)

            # 填充各列
            item_seq = QTableWidgetItem(str(c.seq or (idx + 1)))
            item_seq.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_seq.setFlags(item_seq.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, COL_SEQ, item_seq)

            item_author = QTableWidgetItem(c.author or "")
            item_author.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_AUTHOR, item_author)

            item_ch = QTableWidgetItem(c.chapter_no or "")
            item_ch.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_ch.setToolTip("双击直接跳转并定位正文")
            self._table.setItem(row, COL_CHAPTER, item_ch)

            item_text = QTableWidgetItem(c.text or "")
            self._table.setItem(row, COL_TEXT, item_text)

            item_assignee = QTableWidgetItem(c.assignee or "")
            item_assignee.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_ASSIGNEE, item_assignee)

            item_date = QTableWidgetItem(c.planned_date or "")
            item_date.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_PLANNED_DATE, item_date)

            confirm_val = c.confirm_status or ("已确认" if c.status == "resolved" else "未确认")
            item_confirm = QTableWidgetItem(confirm_val)
            item_confirm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_confirm.setToolTip("双击在「待确认 ⟷ 已确认 ⟷ 遗留」间切换")
            self._table.setItem(row, COL_CONFIRM, item_confirm)

            item_note = QTableWidgetItem(c.review_note or "")
            self._table.setItem(row, COL_NOTE, item_note)

            item_evidence = QTableWidgetItem(c.evidence or "")
            self._table.setItem(row, COL_EVIDENCE, item_evidence)

            item_open = QTableWidgetItem(c.open_issue or "")
            self._table.setItem(row, COL_OPEN_ISSUE, item_open)

        self._table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        col = item.column()
        if row < 0 or row >= len(self._filtered_indices):
            return

        c_idx = self._filtered_indices[row]
        comment = self._comments[c_idx]
        text = item.text().strip()

        if col == COL_AUTHOR:
            comment.author = text
        elif col == COL_CHAPTER:
            comment.chapter_no = text
        elif col == COL_TEXT:
            comment.text = text
        elif col == COL_ASSIGNEE:
            comment.assignee = text
        elif col == COL_PLANNED_DATE:
            comment.planned_date = text
        elif col == COL_CONFIRM:
            comment.confirm_status = text
            if "已确认" in text:
                comment.status = "resolved"
            elif "遗留" in text:
                comment.status = "unresolved"
            else:
                comment.status = "unresolved"
        elif col == COL_NOTE:
            comment.review_note = text
        elif col == COL_EVIDENCE:
            comment.evidence = text
        elif col == COL_OPEN_ISSUE:
            comment.open_issue = text

        self._store.save_comments(self._comments)
        self._update_dashboard()

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if row < 0 or row >= len(self._filtered_indices):
            return

        c_idx = self._filtered_indices[row]
        comment = self._comments[c_idx]

        if col == COL_CONFIRM:
            # 极速切换状态：待确认 -> 已确认 -> 遗留 -> 待确认
            current = comment.confirm_status or "未确认"
            if "已确认" in current:
                next_val = "遗留"
            elif "遗留" in current:
                next_val = "待确认"
            else:
                next_val = "已确认"
            comment.confirm_status = next_val
            comment.status = "resolved" if next_val == "已确认" else "unresolved"
            self._store.save_comments(self._comments)
            self._table.blockSignals(True)
            self._table.item(row, COL_CONFIRM).setText(next_val)
            self._table.blockSignals(False)
            self._update_dashboard()
        elif col == COL_CHAPTER:
            self._locate_current_section()

    def _on_selection_changed(self) -> None:
        row = self._table.currentRow()
        if row >= 0 and row < len(self._filtered_indices):
            c = self._comments[self._filtered_indices[row]]
            ch_tip = f" (章节 {c.chapter_no})" if c.chapter_no else ""
            self._status_tip.setText(f"选中第 {c.seq or (row + 1)} 条意见{ch_tip} | 快捷键: [Ctrl+N] 新增 [Del] 删除")

    # --- 按钮与交互动作 ---

    def _on_add_row(self) -> None:
        """新增一行意见。"""
        new_c = self._store.add_comment(
            text="（请录入评审问题）",
            author="评审人",
            chapter_no="",
            confirm_status="待确认",
        )
        self.reload()
        # 选中最后一行并聚焦在问题列
        last_row = self._table.rowCount() - 1
        if last_row >= 0:
            self._table.setCurrentCell(last_row, COL_TEXT)
            self._table.editItem(self._table.item(last_row, COL_TEXT))

    def _on_delete_selected(self) -> None:
        """删除选中行。"""
        selected_rows = sorted({item.row() for item in self._table.selectedItems()}, reverse=True)
        if not selected_rows:
            return

        ans = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除选中的 {len(selected_rows)} 条评审意见吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        for row in selected_rows:
            if row < len(self._filtered_indices):
                c_idx = self._filtered_indices[row]
                self._store.delete_comment(self._comments[c_idx].comment_id)
        self.reload()

    def _batch_confirm_selected(self) -> None:
        """批量将选中行标记为已确认。"""
        selected_rows = {item.row() for item in self._table.selectedItems()}
        if not selected_rows:
            return
        for row in selected_rows:
            if row < len(self._filtered_indices):
                c_idx = self._filtered_indices[row]
                comment = self._comments[c_idx]
                comment.confirm_status = "已确认"
                comment.status = "resolved"
        self._store.save_comments(self._comments)
        self.reload()

    def _on_generate_evidence(self) -> None:
        """⚡ 一键为当前行生成证据。"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._filtered_indices):
            QMessageBox.information(self, "提示", "请先在列表中选中一条需要生成证据的意见。")
            return

        c_idx = self._filtered_indices[row]
        comment = self._comments[c_idx]

        evidence_str = generate_evidence_for_comment(
            comment,
            self._content_root,
            self._snapshot,
        )
        comment.evidence = evidence_str
        self._store.save_comments(self._comments)
        self._table.blockSignals(True)
        self._table.item(row, COL_EVIDENCE).setText(evidence_str)
        self._table.blockSignals(False)
        self._status_tip.setText(f"✓ 已为第 {comment.seq} 条意见生成证据：{evidence_str}")

    def _locate_current_section(self) -> None:
        """跳转并定位到对应 Markdown 章节。"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._filtered_indices):
            return

        c = self._comments[self._filtered_indices[row]]
        target_path = c.rel_path
        line_no = c.line_no or 1

        if not target_path and c.chapter_no:
            # 搜索章节对应文件
            clean_ch = c.chapter_no.strip()
            for root, _, files in os.walk(self._content_root):
                for f in files:
                    if f.endswith(".md") and clean_ch in f:
                        target_path = Path(os.path.join(root, f)).relative_to(self._content_root).as_posix()
                        break
                if target_path:
                    break

        if not target_path:
            QMessageBox.information(self, "定位提示", f"未找到章节 [{c.chapter_no}] 对应的 Markdown 文件。")
            return

        if self._on_open_file:
            self._on_open_file(target_path, line_no)
        self.request_open_file.emit(target_path, line_no)

    # --- 导入与导出流程 ---

    def _on_export_draft(self) -> None:
        """弹出向导并导出会议评审稿 Word。"""
        # 获取改动章节列表
        changed = self._collect_changed_chapters()
        doc_name = "技术说明书"
        doc_ver = "1.0"
        template_path = None
        output_dir = self._content_root.parent / "output" / "review"

        if self._project_paths:
            output_dir = self._project_paths.output_dir / "review"
            tpl = self._project_paths.template_docx
            if tpl.exists():
                template_path = tpl

        project_root = self._project_paths.root if self._project_paths else self._content_root.parent
        # 尝试从 project.yml 读取文档名与版本
        try:
            from doc_tool.domain.manifest import ProjectManifest

            manifest = ProjectManifest.load(project_root)
            doc_name = manifest.documentName or doc_name
            doc_ver = manifest.documentVersion or doc_ver
        except Exception:
            pass

        output_dir.mkdir(parents=True, exist_ok=True)
        dlg = ExportReviewDraftDialog(
            document_name=doc_name,
            document_version=doc_ver,
            changed_chapters=changed,
            default_output_dir=output_dir,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected_chapters = dlg.selected_chapters()
        include_table = dlg.include_blank_table()
        highlight_changes = dlg.highlight_changes()
        out_path = dlg.output_path()

        try:
            build_review_draft_docx(
                template_path=template_path,
                output_path=out_path,
                document_name=doc_name,
                document_version=doc_ver,
                changed_items=selected_chapters,
                include_blank_table=include_table,
                highlight_changes=highlight_changes,
            )
            QMessageBox.information(self, "导出成功", f"会议评审稿已生成：\n{out_path}")
            if dlg.open_folder():
                reveal_in_file_manager(out_path)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"生成评审稿失败：{exc}")

    def _on_import_word(self) -> None:
        """从外部 Word 文档末尾表格一键提取意见。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择评审会议 Word 文档",
            str(self._content_root.parent),
            "Word 文档 (*.docx)",
        )
        if not file_path:
            return

        try:
            comments = extract_comments_from_docx(file_path)
            if not comments:
                QMessageBox.warning(
                    self,
                    "未发现意见条目",
                    "在选中的 Word 文档中未识别到填写的评审表格记录。\n\n"
                    "【说明】\n"
                    "1. 本功能仅用于提取 Word 文末附录表格中的「评审意见条目」，不支持将 Word 中修改的正文反向同步为 Markdown。\n"
                    "2. 请确认已在 Word 最末尾的「附录：评审意见记录表」中填写了「提出人」或「评审问题」列。\n"
                    "3. 如需修改文档正文，请直接在左侧章节目录中编辑 Markdown 保存即可。",
                )
                return

            added_count = self._store.import_comments(comments)
            self.reload()
            QMessageBox.information(
                self,
                "导入成功",
                f"成功从 Word 表格识别并导入 {added_count} 条有效评审意见！",
            )
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", f"解析 Word 表格失败：{exc}")

    def _on_export_minutes(self) -> None:
        """一键导出标准 A4 横向评审纪要 DOCX 与 Markdown。"""
        if not self._comments:
            QMessageBox.information(self, "提示", "当前暂无评审意见可导出。")
            return

        doc_name = "技术说明书"
        doc_no = ""
        doc_ver = "1.0"
        output_dir = self._content_root.parent / "output" / "review"
        if self._project_paths:
            output_dir = self._project_paths.output_dir / "review"

        try:
            from doc_tool.domain.manifest import ProjectManifest

            manifest = ProjectManifest.load(self._content_root.parent)
            doc_name = manifest.documentName or doc_name
            doc_no = manifest.documentNo or doc_no
            doc_ver = manifest.documentVersion or doc_ver
        except Exception:
            pass

        output_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        default_file = output_dir / f"评审纪要-{doc_name}-v{doc_ver}-{today}.docx"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出评审纪要",
            str(default_file),
            "Word 文档 (*.docx)",
        )
        if not file_path:
            return

        out_docx = Path(file_path).resolve()
        try:
            docx_res, md_res = build_review_minutes_docx(
                output_path=out_docx,
                document_name=doc_name,
                document_no=doc_no,
                document_version=doc_ver,
                review_date=today,
                comments=self._comments,
            )
            ans = QMessageBox.information(
                self,
                "导出成功",
                f"已成功导出正式《评审纪要》：\n1. Word 版: {docx_res.name}\n2. Markdown 版: {md_res.name}\n\n是否打开所在目录？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                reveal_in_file_manager(docx_res)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"生成评审纪要失败：{exc}")

    # --- 辅助方法 ---

    def _collect_changed_chapters(self) -> List[Dict]:
        """从内容快照与索引汇总改动章节。"""
        results: List[Dict] = []
        if not self._index:
            return results

        all_files = list(self._index.all_files())
        status_map: Dict[str, str] = {}
        if self._snapshot:
            status_map = self._snapshot.diff(self._content_root, all_files)

        for rel in all_files:
            st = status_map.get(rel)
            if not st:
                continue

            chapter_no, title = _extract_chapter_no_and_title(rel, self._index)

            # 读取内容
            full_path = self._content_root / rel
            content = ""
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding="utf-8")
                except OSError:
                    pass

            diff_summary = ""
            base_content = None
            if self._snapshot and st == "modified":
                base_content = self._snapshot.content_of(rel)
                if base_content is not None:
                    diff_lines = list(difflib.unified_diff(base_content.splitlines(), content.splitlines()))
                    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
                    deleted = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
                    diff_summary = f"+{added}行 / -{deleted}行"
            elif self._snapshot and st == "deleted":
                base_content = self._snapshot.content_of(rel)

            results.append(
                {
                    "rel_path": rel,
                    "title": title,
                    "chapter_no": chapter_no,
                    "status": st,
                    "diff_summary": diff_summary,
                    "markdown_content": content,
                    "base_content": base_content,
                }
            )

        # 若当前无改动或未建立基线，则提供全量章节供用户勾选评审
        if not results:
            for rel in all_files:
                if not rel.endswith(".md") or rel.startswith("_"):
                    continue
                chapter_no, title = _extract_chapter_no_and_title(rel, self._index)
                full_path = self._content_root / rel
                content = ""
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                    except OSError:
                        pass
                results.append(
                    {
                        "rel_path": rel,
                        "title": title,
                        "chapter_no": chapter_no,
                        "status": "normal",
                        "diff_summary": "",
                        "markdown_content": content,
                    }
                )

        return results

    def _get_all_chapters(self) -> List[str]:
        """获取当前全部章节编号与标题列表，供下拉联想。"""
        if not self._index:
            return []
        items = []
        for rel in self._index.all_files():
            if not rel.endswith(".md") or rel.startswith("_"):
                continue
            chapter_no, title = _extract_chapter_no_and_title(rel, self._index)
            if chapter_no and title:
                items.append(f"{chapter_no} {title}")
            elif title:
                items.append(title)
        return items

    def _on_context_menu(self, pos) -> None:
        """右键菜单。"""
        menu = QMenu(self)
        row = self._table.currentRow()
        has_sel = row >= 0 and row < len(self._filtered_indices)

        act_locate = menu.addAction("🎯 定位到对应章节正文")
        act_locate.setEnabled(has_sel)
        act_locate.triggered.connect(self._locate_current_section)

        menu.addSeparator()

        act_conf = menu.addAction("✓ 标记为已确认")
        act_conf.setEnabled(has_sel)
        act_conf.triggered.connect(lambda: self._set_selected_status("已确认"))

        act_unconf = menu.addAction("⏳ 设为待确认")
        act_unconf.setEnabled(has_sel)
        act_unconf.triggered.connect(lambda: self._set_selected_status("待确认"))

        act_open = menu.addAction("📌 标记为遗留")
        act_open.setEnabled(has_sel)
        act_open.triggered.connect(lambda: self._set_selected_status("遗留"))

        menu.addSeparator()

        act_evid = menu.addAction("⚡ 自动生成本条证据")
        act_evid.setEnabled(has_sel)
        act_evid.triggered.connect(self._on_generate_evidence)

        act_del = menu.addAction("❌ 删除此行意见")
        act_del.setEnabled(has_sel)
        act_del.triggered.connect(self._on_delete_selected)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _set_selected_status(self, status: str) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._filtered_indices):
            return
        c = self._comments[self._filtered_indices[row]]
        c.confirm_status = status
        c.status = "resolved" if status == "已确认" else "unresolved"
        self._store.save_comments(self._comments)
        self.reload()
