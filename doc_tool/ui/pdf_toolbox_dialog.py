# -*- coding: utf-8 -*-
"""PDF 工具箱：页面组织、格式转换、页面编辑与安全优化中心。

采用专业的一站式 PDF 处理中心架构：
1. 首页导航大厅（Portal Hub）：
   - 分类筛选标签（全部 / 常用推荐 / 页面组织 / 格式转换 / 编辑标注 / 安全与优化）
   - 实时搜索过滤框（支持工具名、关键词实时检索）
   - 工具入口卡片网格（清晰图标、功能简述、格式徽标、常用推荐标记）
   - 离线隐私与安全保障提示
2. 专属工具工作区（Dedicated Workspace）：
   - 快速返回首页与多工具下拉快捷切换
   - 拖拽投放区与文件选择校验
   - 列表文件大小、页数/规格实时提取与操作工具条
   - 针对各工具的专属参数配置表单（含密码强度检测、水印平铺/多方位、版面边距等）
   - 状态追踪（排队、处理中、成功、失败、取消）
   - 产物直接交付体验（打开文件、定位目录、重试、再次处理）
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
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
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
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
    TOOL_REORDER,
    TOOL_ROTATE,
    TOOL_SPEC_BY_ID,
    TOOL_SPECS,
    TOOL_SPLIT,
    TOOL_TO_IMAGES,
    TOOL_TO_TEXT,
    TOOL_WATERMARK,
    PdfToolBatchResult,
    PdfToolRecord,
    evaluate_password_strength,
    expand_sources,
    get_pdf_info,
    parse_page_ranges,
    parse_page_selection,
    run_pdf_tool,
)
from doc_tool.domain.errors import (
    DocToolError,
    PdfInputError,
    PdfPageSelectionError,
)
from doc_tool.ui.task_bridge import (
    POLL_INTERVAL_MS,
    TaskEvent,
    TaskRunner,
    TaskSpec,
)

# 工具图标映射
TOOL_ICONS: Dict[str, str] = {
    TOOL_MERGE: "📑",
    TOOL_SPLIT: "✂️",
    TOOL_EXTRACT: "📥",
    TOOL_DELETE: "🗑️",
    TOOL_ROTATE: "🔄",
    TOOL_REORDER: "🔀",
    TOOL_TO_IMAGES: "🖼️",
    TOOL_IMAGES_TO_PDF: "📷",
    TOOL_TO_TEXT: "📝",
    TOOL_WATERMARK: "💧",
    TOOL_PAGE_NUMBERS: "🔢",
    TOOL_METADATA: "ℹ️",
    TOOL_ENCRYPT: "🔒",
    TOOL_DECRYPT: "🔓",
    TOOL_COMPRESS: "🗜️",
}

# 常用推荐高频工具
FEATURED_TOOL_IDS: Set[str] = {
    TOOL_MERGE,
    TOOL_SPLIT,
    TOOL_COMPRESS,
    TOOL_WATERMARK,
    TOOL_IMAGES_TO_PDF,
    TOOL_TO_IMAGES,
    TOOL_ENCRYPT,
}


def _format_size(size_bytes: int) -> str:
    """智能格式化文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024.0:.1f} KB"
    else:
        return f"{size_bytes / (1024.0 * 1024.0):.2f} MB"


class _DropZone(QFrame):
    """拖放投放区：支持拖入文件/文件夹与点击浏览。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(78)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        self._icon_label = QLabel("📥", self)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 22px;")
        layout.addWidget(self._icon_label)

        self._title_label = QLabel("点击选择文件，或将文件 / 文件夹拖拽到此处", self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("font-weight: bold; color: #1f2328; font-size: 12px;")
        layout.addWidget(self._title_label)

        self._hint_label = QLabel(self)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setStyleSheet("color: #57606a; font-size: 11px;")
        layout.addWidget(self._hint_label)

        self.set_drag_over(False)

    def set_hint(self, hint_text: str) -> None:
        self._hint_label.setText(hint_text)

    def set_drag_over(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "_DropZone { background-color: #dbeafe; border: 2px dashed #2563eb; border-radius: 8px; }"
            )
        else:
            self.setStyleSheet(
                "_DropZone { background-color: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 8px; }"
                "_DropZone:hover { background-color: #f1f5f9; border-color: #94a3b8; }"
            )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _RowActionWidget(QWidget):
    """文件列表行级操作按钮：打开文件、定位目录、重试、移除。"""

    remove_clicked = Signal(Path)
    retry_clicked = Signal(Path)

    def __init__(self, path: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._path = path
        self._target_path: Optional[Path] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(3)

        self._open_btn = QPushButton("📄 打开", self)
        self._open_btn.setProperty("btnRole", "compact")
        self._open_btn.setToolTip("在系统默认程序中直接打开生成的产物文件")
        self._open_btn.setVisible(False)
        self._open_btn.clicked.connect(self._on_open_file)
        layout.addWidget(self._open_btn)

        self._folder_btn = QPushButton("📁 目录", self)
        self._folder_btn.setProperty("btnRole", "compact")
        self._folder_btn.setToolTip("在文件管理器中定位产物所在文件夹")
        self._folder_btn.setVisible(False)
        self._folder_btn.clicked.connect(self._on_open_folder)
        layout.addWidget(self._folder_btn)

        self._retry_btn = QPushButton("🔄 重试", self)
        self._retry_btn.setProperty("btnRole", "compact")
        self._retry_btn.setToolTip("重新处理该单项文件")
        self._retry_btn.setVisible(False)
        self._retry_btn.clicked.connect(lambda: self.retry_clicked.emit(self._path))
        layout.addWidget(self._retry_btn)

        self._remove_btn = QPushButton("✕ 移除", self)
        self._remove_btn.setProperty("btnRole", "compact")
        self._remove_btn.setToolTip("从当前处理列表中移除此文件")
        self._remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self._path))
        layout.addWidget(self._remove_btn)

    def set_target(self, target_path: Optional[Path]) -> None:
        self._target_path = target_path
        has_target = bool(target_path and target_path.exists())
        self._open_btn.setVisible(has_target)
        self._folder_btn.setVisible(has_target)

    def set_failed(self, is_failed: bool) -> None:
        self._retry_btn.setVisible(is_failed)

    def _on_open_file(self) -> None:
        if self._target_path and self._target_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._target_path)))

    def _on_open_folder(self) -> None:
        target = self._target_path or self._path
        folder = target.parent if target else Path.home()
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class _ToolCard(QFrame):
    """首页工具入口卡片：展示图标、分类、名称、说明及格式徽标。"""

    selected = Signal(str)

    def __init__(
        self,
        tool_id: str,
        label: str,
        category: str,
        description: str,
        accepts: Tuple[str, ...],
        is_featured: bool = False,
        is_disabled: bool = False,
        disabled_reason: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._tool_id = tool_id
        self._is_disabled = is_disabled
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor if not is_disabled else Qt.CursorShape.ForbiddenCursor)
        self.setSizePolicy(QFrame.sizePolicy(self).horizontalPolicy(), QFrame.sizePolicy(self).verticalPolicy())
        self.setMinimumSize(210, 126)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # 头部：图标 + 分类 + 常用标记
        header = QHBoxLayout()
        header.setSpacing(8)

        icon_str = TOOL_ICONS.get(tool_id, "📄")
        self._icon_lbl = QLabel(icon_str, self)
        self._icon_lbl.setStyleSheet(
            "font-size: 20px; background-color: #fee2e2; border-radius: 6px; padding: 4px;"
            if not is_disabled else
            "font-size: 20px; background-color: #e2e8f0; border-radius: 6px; padding: 4px;"
        )
        header.addWidget(self._icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        self._title_lbl = QLabel(label, self)
        self._title_lbl.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #1f2328;"
            if not is_disabled else
            "font-weight: bold; font-size: 13px; color: #94a3b8;"
        )
        title_row.addWidget(self._title_lbl)

        if is_featured:
            feat_lbl = QLabel("⭐ 常用", self)
            feat_lbl.setStyleSheet("color: #b45309; background-color: #fef3c7; font-size: 10px; border-radius: 3px; padding: 1px 4px;")
            title_row.addWidget(feat_lbl)
        elif is_disabled:
            dis_lbl = QLabel("即将支持", self)
            dis_lbl.setStyleSheet("color: #64748b; background-color: #e2e8f0; font-size: 10px; border-radius: 3px; padding: 1px 4px;")
            title_row.addWidget(dis_lbl)

        title_row.addStretch()
        title_box.addLayout(title_row)

        cat_lbl = QLabel(category, self)
        cat_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        title_box.addWidget(cat_lbl)

        header.addLayout(title_box, 1)
        layout.addLayout(header)

        # 描述内容
        desc_text = disabled_reason if is_disabled else description
        self._desc_lbl = QLabel(desc_text, self)
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet("color: #475569; font-size: 11px; line-height: 1.3;" if not is_disabled else "color: #94a3b8; font-size: 11px;")
        layout.addWidget(self._desc_lbl, 1)

        # 底部格式徽标与使用提示
        footer = QHBoxLayout()
        footer.setSpacing(4)
        accepts_str = " ".join(accepts[:3])
        fmt_lbl = QLabel(accepts_str, self)
        fmt_lbl.setStyleSheet("color: #64748b; background-color: #f1f5f9; font-size: 10px; border-radius: 3px; padding: 2px 5px;")
        footer.addWidget(fmt_lbl)
        footer.addStretch()

        if not is_disabled:
            go_lbl = QLabel("使用 →", self)
            go_lbl.setStyleSheet("color: #2563eb; font-weight: bold; font-size: 11px;")
            footer.addWidget(go_lbl)

        layout.addLayout(footer)

        self._update_style(False)
        self.setAccessibleName(f"工具卡片：{label}")
        self.setAccessibleDescription(f"分类：{category}，说明：{description or disabled_reason}")
        if is_disabled:
            self.setToolTip(f"「{label}」即将支持：{disabled_reason}")

    def _update_style(self, hover: bool) -> None:
        if self._is_disabled:
            self.setStyleSheet(
                "_ToolCard { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }"
            )
        elif hover:
            self.setStyleSheet(
                "_ToolCard { background-color: #ffffff; border: 1px solid #2563eb; border-radius: 8px; }"
            )
        else:
            self.setStyleSheet(
                "_ToolCard { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; }"
                "_ToolCard:hover { border-color: #3b82f6; background-color: #f8fafc; }"
            )

    def enterEvent(self, event) -> None:  # noqa: N802
        if not self._is_disabled:
            self._update_style(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._is_disabled:
            self._update_style(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_disabled:
                QMessageBox.information(
                    self,
                    "功能规划中",
                    f"「{self._title_lbl.text()}」功能正在规划研发中，敬请期待！",
                )
            else:
                self.selected.emit(self._tool_id)
        super().mousePressEvent(event)


class PdfToolboxDialog(QDialog):
    """PDF 工具箱：页面组织、格式转换、页面编辑与安全优化中心。"""

    progress = Signal(int, int, object)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        busy_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(parent)
        self._busy_check = busy_check
        self._sources: List[Path] = []
        self._rows: Dict[str, int] = {}
        self._row_actions: Dict[str, _RowActionWidget] = {}
        self._runner = TaskRunner()
        self._last_result: Optional[PdfToolBatchResult] = None
        self._active_tool_id: str = TOOL_MERGE

        self.setWindowTitle("PDF 工具箱 · 一站式本地离线 PDF 处理中心")
        self.setMinimumSize(580, 480)
        self.resize(1020, 700)
        self.setAcceptDrops(True)

        self.progress.connect(self._on_progress)

        # 顶层主布局
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # 视图堆叠栈：0 为首页导航大厅，1 为工具操作工作区
        self._view_stack = QStackedWidget(self)
        outer_layout.addWidget(self._view_stack)

        # 构建首页导航大厅视图
        self._portal_widget = QWidget(self)
        self._build_portal_view(self._portal_widget)
        self._view_stack.addWidget(self._portal_widget)

        # 构建工具操作工作区视图
        self._workspace_widget = QWidget(self)
        self._build_workspace_view(self._workspace_widget)
        self._view_stack.addWidget(self._workspace_widget)

        # 内部兼容列表（满足既有测试对 self._tool_list 的访问）
        self._tool_list = QListWidget(self)
        self._tool_list.setVisible(False)
        self._populate_tool_list()
        self._tool_list.currentItemChanged.connect(self._on_internal_tool_list_changed)

        # 轮询定时器
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._runner.poll)

        # 默认选中合并工具
        self.select_tool(TOOL_MERGE)

    # --- 首页导航大厅构建 ---

    def _build_portal_view(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 1. 顶部 Header 栏：Logo、标题与离线隐私保障徽标
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        main_title = QLabel("📑 PDF 工具箱", container)
        main_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0f172a;")
        sub_title = QLabel("纯本地离线安全处理 · 专业清晰 · 高效稳定", container)
        sub_title.setStyleSheet("font-size: 11px; color: #64748b;")
        title_box.addWidget(main_title)
        title_box.addWidget(sub_title)
        top_bar.addLayout(title_box, 1)

        privacy_badge = QLabel("🛡️ 100% 本地离线处理 · 严防数据泄露", container)
        privacy_badge.setStyleSheet(
            "background-color: #ecfdf5; color: #065f46; font-size: 11px; font-weight: bold; border: 1px solid #a7f3d0; border-radius: 6px; padding: 6px 12px;"
        )
        top_bar.addWidget(privacy_badge)
        layout.addLayout(top_bar)

        # 2. 搜索框与分类过滤器
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self._portal_search = QLineEdit(container)
        self._portal_search.setPlaceholderText("🔍 快速搜索工具 (如: 合并、压缩、拆分、水印、加密...)")
        self._portal_search.setClearButtonEnabled(True)
        self._portal_search.setFixedHeight(32)
        self._portal_search.textChanged.connect(self._filter_portal_cards)
        filter_bar.addWidget(self._portal_search, 1)

        # 分类切换按钮组
        self._cat_btn_group = QButtonGroup(container)
        self._cat_btn_group.setExclusive(True)

        categories_to_show = ["全部", "⭐ 常用推荐"] + list(CATEGORIES)
        for idx, cat_name in enumerate(categories_to_show):
            btn = QPushButton(cat_name, container)
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            if idx == 0:
                btn.setChecked(True)
            self._cat_btn_group.addButton(btn, idx)
            btn.clicked.connect(self._filter_portal_cards)
            filter_bar.addWidget(btn)

        layout.addLayout(filter_bar)

        # 3. 工具卡片滚动网格区
        scroll_area = QScrollArea(container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        self._cards_grid = QGridLayout(scroll_content)
        self._cards_grid.setContentsMargins(4, 4, 4, 4)
        self._cards_grid.setSpacing(12)

        self._cards_list: List[_ToolCard] = []
        col_count = 3
        row = 0
        col = 0

        for spec in TOOL_SPECS:
            is_feat = spec.id in FEATURED_TOOL_IDS
            card = _ToolCard(
                tool_id=spec.id,
                label=spec.label,
                category=spec.category,
                description=spec.description,
                accepts=spec.accepts,
                is_featured=is_feat,
                parent=scroll_content,
            )
            card.selected.connect(self.select_tool)
            self._cards_list.append(card)
            self._cards_grid.addWidget(card, row, col)
            col += 1
            if col >= col_count:
                col = 0
                row += 1

        # 添加清晰的“即将支持”占位卡（符合规范需求 5）
        ocr_card = _ToolCard(
            tool_id="ocr",
            label="OCR 文字识别",
            category="转换",
            description="",
            accepts=(".pdf", ".jpg", ".png"),
            is_disabled=True,
            disabled_reason="基于本地深度学习引擎的光学字符识别，提取扫描件文字（即将上线）。",
            parent=scroll_content,
        )
        self._cards_list.append(ocr_card)
        self._cards_grid.addWidget(ocr_card, row, col)

        self._no_results_lbl = QLabel("未找到匹配的 PDF 工具，请尝试其他关键词或切换分类", scroll_content)
        self._no_results_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_results_lbl.setStyleSheet("color: #94a3b8; font-size: 13px; padding: 40px;")
        self._no_results_lbl.setVisible(False)
        self._cards_grid.addWidget(self._no_results_lbl, 0, 0, 1, col_count)

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

        # 4. 底部隐私声明与状态条
        portal_bot = QHBoxLayout()
        notice_lbl = QLabel(
            "🔒 安全声明：所有文档处理均在您的本地设备完成，绝不上传任何云端服务器，保障企业商业机密与敏感文档隐私安全。",
            container,
        )
        notice_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        portal_bot.addWidget(notice_lbl, 1)

        close_portal_btn = QPushButton("关闭", container)
        close_portal_btn.clicked.connect(self.close)
        portal_bot.addWidget(close_portal_btn)
        layout.addLayout(portal_bot)

    def _get_responsive_col_count(self) -> int:
        w = self.width()
        if w < 720:
            return 1
        elif w < 1080:
            return 2
        return 3

    def _filter_portal_cards(self) -> None:
        """根据搜索词和分类过滤首页卡片显示，并紧凑重排避免栅格空白。"""
        search_kw = self._portal_search.text().strip().lower()
        checked_btn = self._cat_btn_group.checkedButton()
        active_cat = checked_btn.text() if checked_btn else "全部"

        # 移除现有网格定位（不销毁组件）
        for i in reversed(range(self._cards_grid.count())):
            self._cards_grid.takeAt(i)

        col_count = self._get_responsive_col_count()
        visible_cards: List[_ToolCard] = []

        for card in self._cards_list:
            spec = TOOL_SPEC_BY_ID.get(card._tool_id)
            if not spec:
                match_cat = active_cat in ("全部", "格式转换", "转换")
                match_search = not search_kw or "ocr" in search_kw or "识别" in search_kw
                is_m = match_cat and match_search
                card.setVisible(is_m)
                if is_m:
                    visible_cards.append(card)
                continue

            # 分类匹配
            if active_cat == "全部":
                match_cat = True
            elif active_cat == "⭐ 常用推荐":
                match_cat = spec.id in FEATURED_TOOL_IDS
            else:
                match_cat = spec.category == active_cat

            # 搜索匹配
            match_search = (
                not search_kw
                or search_kw in spec.label.lower()
                or search_kw in spec.description.lower()
                or search_kw in spec.category.lower()
                or search_kw in spec.id.lower()
                or any(search_kw in s.lower() for s in spec.accepts)
            )

            is_match = match_cat and match_search
            card.setVisible(is_match)
            if is_match:
                visible_cards.append(card)

        # 重新紧凑填充网格
        for idx, card in enumerate(visible_cards):
            self._cards_grid.addWidget(card, idx // col_count, idx % col_count)

        if hasattr(self, "_no_results_lbl"):
            self._no_results_lbl.setVisible(len(visible_cards) == 0)
            if len(visible_cards) == 0:
                self._cards_grid.addWidget(self._no_results_lbl, 0, 0, 1, col_count)

    # --- 视图切换控制 ---

    def _show_portal_view(self) -> None:
        self._view_stack.setCurrentIndex(0)

    def select_tool(self, tool_id: str) -> None:
        """从首页或任意入口切换到指定工具。"""
        if tool_id not in TOOL_SPEC_BY_ID:
            return
        self._active_tool_id = tool_id

        # 同步更新内部 tool_list
        for i in range(self._tool_list.count()):
            item = self._tool_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == tool_id:
                self._tool_list.setCurrentItem(item)
                break

        # 同步更新工作区下拉切换框
        idx = self._quick_tool_combo.findData(tool_id)
        if idx >= 0:
            self._quick_tool_combo.blockSignals(True)
            self._quick_tool_combo.setCurrentIndex(idx)
            self._quick_tool_combo.blockSignals(False)

        spec = TOOL_SPEC_BY_ID[tool_id]
        icon_str = TOOL_ICONS.get(tool_id, "📄")

        # 面包屑与横幅提示更新
        self._breadcrumb_lbl.setText(f"PDF 工具箱  ›  {spec.category}  ›  {icon_str} {spec.label}")
        self._desc_banner.setText(f"<b>{spec.label}</b>：{spec.description}<br><span style='color: #475569;'>提示：{spec.hint}</span>")

        accepts_str = " ".join(spec.accepts)
        self._drop_zone.set_hint(f"支持格式：{accepts_str} —— 点击选择或直接拖入文件 / 文件夹")

        # 排序按钮可见性（合并工具与多图转 PDF 支持列表上下调整顺序）
        can_reorder = tool_id in (TOOL_MERGE, TOOL_IMAGES_TO_PDF)
        self._move_up_btn.setVisible(can_reorder)
        self._move_down_btn.setVisible(can_reorder)

        # 切换选项面板
        opt_idx = TOOL_IDS.index(tool_id) if tool_id in TOOL_IDS else 0
        self._options_stack.setCurrentIndex(opt_idx)

        # 切换至工作区视图
        self._view_stack.setCurrentIndex(1)
        self._update_ui_state()

    def _on_quick_tool_changed(self, index: int) -> None:
        tid = self._quick_tool_combo.itemData(index)
        if tid:
            self.select_tool(str(tid))


    # --- 专属工具操作工作区构建 ---

    def _build_workspace_view(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 1. 顶部导航与功能快速切换栏
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(8)

        self._back_home_btn = QPushButton("← 返回工具导航", container)
        self._back_home_btn.setProperty("btnRole", "secondary")
        self._back_home_btn.setToolTip("返回所有 PDF 工具导航大厅")
        self._back_home_btn.clicked.connect(self._show_portal_view)
        nav_bar.addWidget(self._back_home_btn)

        self._breadcrumb_lbl = QLabel(container)
        self._breadcrumb_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1e293b;")
        nav_bar.addWidget(self._breadcrumb_lbl, 1)

        nav_bar.addWidget(QLabel("快捷切换功能：", container))
        self._quick_tool_combo = QComboBox(container)
        self._quick_tool_combo.setMinimumWidth(180)
        for s in TOOL_SPECS:
            icon_str = TOOL_ICONS.get(s.id, "📄")
            self._quick_tool_combo.addItem(f"{icon_str}  {s.label} ({s.category})", s.id)
        self._quick_tool_combo.currentIndexChanged.connect(self._on_quick_tool_changed)
        nav_bar.addWidget(self._quick_tool_combo)

        layout.addLayout(nav_bar)

        # 工具说明与提示条
        self._desc_banner = QLabel(container)
        self._desc_banner.setWordWrap(True)
        self._desc_banner.setStyleSheet(
            "background-color: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; border-radius: 6px; padding: 6px 12px; font-size: 11px;"
        )
        layout.addWidget(self._desc_banner)

        # 2. 核心工作区：双栏布局（左侧文件清单与投放区，右侧参数设置与输出）
        body_splitter = QSplitter(Qt.Orientation.Horizontal, container)

        # 左栏：文件投放与清单
        left_widget = QWidget(body_splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self._drop_zone = _DropZone(left_widget)
        self._drop_zone.clicked.connect(self._on_add_files)
        left_layout.addWidget(self._drop_zone)

        # 文件操作工具条
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._add_files_btn = QPushButton("添加文件…", left_widget)
        self._add_files_btn.clicked.connect(self._on_add_files)
        toolbar.addWidget(self._add_files_btn)

        self._add_folder_btn = QPushButton("添加文件夹…", left_widget)
        self._add_folder_btn.clicked.connect(self._on_add_folder)
        toolbar.addWidget(self._add_folder_btn)

        self._move_up_btn = QPushButton("上移 ↑", left_widget)
        self._move_up_btn.clicked.connect(self._on_move_up)
        toolbar.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("下移 ↓", left_widget)
        self._move_down_btn.clicked.connect(self._on_move_down)
        toolbar.addWidget(self._move_down_btn)

        self._remove_btn = QPushButton("移除选中", left_widget)
        self._remove_btn.clicked.connect(self._on_remove_selected)
        toolbar.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("清空", left_widget)
        self._clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(self._clear_btn)

        toolbar.addStretch()

        self._file_stats_lbl = QLabel("已选 0 个文件", left_widget)
        self._file_stats_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        toolbar.addWidget(self._file_stats_lbl)

        left_layout.addLayout(toolbar)

        # 文件表格（7 列：序号、源文件、大小、页数/规格、状态、详情与产物、操作）
        self._table = QTableWidget(0, 7, left_widget)
        self._table.setHorizontalHeaderLabels(["#", "源文件", "大小", "页数/规格", "状态", "产物与结果", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setAccessibleName("待处理文件列表")
        self._table.setAccessibleDescription("表格展示待处理的文件序号、名称、大小、页数规格与处理状态")
        left_layout.addWidget(self._table, 1)

        # 文档预览与元信息摘要横幅
        self._preview_banner = QLabel("💡 提示：点击列表中的文件可查看详细规格与元信息", left_widget)
        self._preview_banner.setWordWrap(True)
        self._preview_banner.setStyleSheet(
            "background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 5px 8px; color: #475569; font-size: 11px;"
        )
        left_layout.addWidget(self._preview_banner)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)

        body_splitter.addWidget(left_widget)

        # 右栏：参数配置与执行选项
        right_widget = QWidget(body_splitter)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 功能参数设置（多工具专属面板堆叠）
        self._opt_group = QGroupBox("功能参数设置", right_widget)
        opt_group_layout = QVBoxLayout(self._opt_group)
        opt_group_layout.setContentsMargins(10, 10, 10, 10)
        self._options_stack = QStackedWidget(self._opt_group)
        self._build_options_pages()
        opt_group_layout.addWidget(self._options_stack)
        right_layout.addWidget(self._opt_group)

        # 输出目录与覆盖设置
        out_group = QGroupBox("输出设置", right_widget)
        out_layout = QVBoxLayout(out_group)
        out_layout.setContentsMargins(10, 10, 10, 10)
        out_layout.setSpacing(6)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("目标目录：", out_group))
        self._out_dir_edit = QLineEdit(out_group)
        self._out_dir_edit.setPlaceholderText("缺省与各源文件同目录")
        dir_row.addWidget(self._out_dir_edit, 1)
        self._browse_dir_btn = QPushButton("浏览…", out_group)
        self._browse_dir_btn.clicked.connect(self._on_browse_output_dir)
        dir_row.addWidget(self._browse_dir_btn)
        out_layout.addLayout(dir_row)

        self._source_pw_container = QWidget(out_group)
        pw_row = QHBoxLayout(self._source_pw_container)
        pw_row.setContentsMargins(0, 0, 0, 0)
        pw_lbl = QLabel("原文件密码：", self._source_pw_container)
        pw_lbl.setStyleSheet("font-size: 11px; color: #475569;")
        pw_row.addWidget(pw_lbl)
        self._source_pw_edit = QLineEdit(self._source_pw_container)
        self._source_pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._source_pw_edit.setPlaceholderText("原文件已加密时在此填入密码以解锁")
        pw_row.addWidget(self._source_pw_edit, 1)
        out_layout.addWidget(self._source_pw_container)
        self._source_pw_container.setVisible(False)

        self._overwrite_box = QCheckBox("覆盖同名文件", out_group)
        out_layout.addWidget(self._overwrite_box)
        right_layout.addWidget(out_group)

        # 快捷动作与执行控制
        action_box = QVBoxLayout()
        action_box.setSpacing(6)

        run_row = QHBoxLayout()
        self._start_btn = QPushButton("开始处理", right_widget)
        self._start_btn.setProperty("btnRole", "primary")
        self._start_btn.setFixedHeight(36)
        self._start_btn.setDefault(True)
        self._start_btn.clicked.connect(self._on_start)
        run_row.addWidget(self._start_btn, 2)

        self._cancel_btn = QPushButton("取消", right_widget)
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        run_row.addWidget(self._cancel_btn, 1)
        action_box.addLayout(run_row)

        self._open_dir_btn = QPushButton("📁 打开输出文件夹", right_widget)
        self._open_dir_btn.setEnabled(False)
        self._open_dir_btn.clicked.connect(self._on_open_output_dir)
        action_box.addWidget(self._open_dir_btn)

        right_layout.addLayout(action_box)
        right_layout.addStretch()

        body_splitter.addWidget(right_widget)
        body_splitter.setStretchFactor(0, 3)
        body_splitter.setStretchFactor(1, 2)

        layout.addWidget(body_splitter, 1)

        # 3. 进度条与完成交付横幅
        self._progress = QProgressBar(container)
        self._progress.setTextVisible(True)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # 完成交付横幅
        self._delivery_banner = QFrame(container)
        self._delivery_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self._delivery_banner.setStyleSheet(
            "background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 6px; padding: 6px;"
        )
        self._delivery_banner.setVisible(False)
        deliv_layout = QHBoxLayout(self._delivery_banner)
        deliv_layout.setContentsMargins(8, 4, 8, 4)

        self._delivery_text = QLabel(self._delivery_banner)
        self._delivery_text.setStyleSheet("color: #166534; font-weight: bold;")
        deliv_layout.addWidget(self._delivery_text, 1)

        self._delivery_open_btn = QPushButton("📄 查看产物", self._delivery_banner)
        self._delivery_open_btn.setProperty("btnRole", "compact")
        self._delivery_open_btn.clicked.connect(self._on_open_latest_output)
        deliv_layout.addWidget(self._delivery_open_btn)

        self._delivery_folder_btn = QPushButton("📁 打开所在目录", self._delivery_banner)
        self._delivery_folder_btn.setProperty("btnRole", "compact")
        self._delivery_folder_btn.clicked.connect(self._on_open_output_dir)
        deliv_layout.addWidget(self._delivery_folder_btn)

        self._delivery_reset_btn = QPushButton("继续处理其他文件", self._delivery_banner)
        self._delivery_reset_btn.setProperty("btnRole", "compact")
        self._delivery_reset_btn.clicked.connect(self._on_reset_for_next)
        deliv_layout.addWidget(self._delivery_reset_btn)

        layout.addWidget(self._delivery_banner)

        # 4. 详情日志抽屉
        self._details = QPlainTextEdit(container)
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(85)
        layout.addWidget(self._details)

        # 底部状态行
        bot_row = QHBoxLayout()
        self._status_label = QLabel("就绪", container)
        bot_row.addWidget(self._status_label, 1)

        self._close_btn = QPushButton("关闭", container)
        self._close_btn.clicked.connect(self.close)
        bot_row.addWidget(self._close_btn)
        layout.addLayout(bot_row)

    # --- 各工具参数配置面板构建 ---

    def _build_options_pages(self) -> None:
        # 1. merge
        p_merge = QWidget()
        l_merge = QFormLayout(p_merge)
        self._merge_name = QLineEdit(p_merge)
        self._merge_name.setPlaceholderText("缺省为「<首个文件>_合并.pdf」")
        l_merge.addRow("合并输出名：", self._merge_name)
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
        self._split_ranges.setPlaceholderText("例如: 1-3, 5-8, 10")
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
        self._delete_pages.setPlaceholderText("如 2,4-6（必填，不可删除全部）")
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

        # 6. reorder
        p_reorder = QWidget()
        l_reorder = QFormLayout(p_reorder)
        self._reorder_rule = QLineEdit(p_reorder)
        self._reorder_rule.setPlaceholderText("如 3,1,2,4 或输入 reverse")
        btn_reorder_box = QHBoxLayout()
        btn_rev = QPushButton("倒序反转", p_reorder)
        btn_rev.clicked.connect(lambda: self._reorder_rule.setText("reverse"))
        btn_odd_even = QPushButton("奇偶重排", p_reorder)
        btn_odd_even.clicked.connect(lambda: self._reorder_rule.setText("odd-even"))
        btn_reorder_box.addWidget(btn_rev)
        btn_reorder_box.addWidget(btn_odd_even)
        btn_reorder_box.addStretch()
        l_reorder.addRow("重排顺序：", self._reorder_rule)
        l_reorder.addRow("快捷模板：", btn_reorder_box)
        self._options_stack.addWidget(p_reorder)

        # 7. to_images
        p_to_img = QWidget()
        l_to_img = QFormLayout(p_to_img)
        self._to_img_fmt = QComboBox(p_to_img)
        self._to_img_fmt.addItems(["PNG (无损高质量)", "JPG (小体积)"])
        self._to_img_dpi = QComboBox(p_to_img)
        self._to_img_dpi.addItem("72 DPI (屏幕轻量预览)", 72)
        self._to_img_dpi.addItem("150 DPI (推荐标准)", 150)
        self._to_img_dpi.addItem("300 DPI (高清打印级)", 300)
        self._to_img_dpi.addItem("600 DPI (超高清存档)", 600)
        self._to_img_dpi.setCurrentIndex(1)
        self._to_img_quality = QSpinBox(p_to_img)
        self._to_img_quality.setRange(50, 100)
        self._to_img_quality.setValue(85)
        self._to_img_quality.setSuffix(" % (仅 JPG)")
        self._to_img_pages = QLineEdit(p_to_img)
        self._to_img_pages.setPlaceholderText("留空表示全部页面，如 1-3,5")
        l_to_img.addRow("导出格式：", self._to_img_fmt)
        l_to_img.addRow("分辨率预设：", self._to_img_dpi)
        l_to_img.addRow("JPG 质量：", self._to_img_quality)
        l_to_img.addRow("页面范围：", self._to_img_pages)
        self._options_stack.addWidget(p_to_img)

        # 8. images_to_pdf
        p_img_pdf = QWidget()
        l_img_pdf = QFormLayout(p_img_pdf)
        self._img_page_size = QComboBox(p_img_pdf)
        self._img_page_size.addItem("原图原始尺寸", "original")
        self._img_page_size.addItem("A4 标准页面", "a4")
        self._img_page_size.addItem("A3 大图页面", "a3")
        self._img_page_size.addItem("Letter 页面", "letter")
        self._img_orientation = QComboBox(p_img_pdf)
        self._img_orientation.addItem("自动自适应 (Auto)", "auto")
        self._img_orientation.addItem("纵向 (Portrait)", "portrait")
        self._img_orientation.addItem("横向 (Landscape)", "landscape")
        self._img_margin = QComboBox(p_img_pdf)
        self._img_margin.addItem("无边距 (0 pt)", 0)
        self._img_margin.addItem("窄边距 (18 pt / ~6mm)", 18)
        self._img_margin.addItem("适中边距 (36 pt / ~13mm)", 36)
        self._img_margin.addItem("宽边距 (72 pt / ~25mm)", 72)
        self._img_pdf_name = QLineEdit(p_img_pdf)
        self._img_pdf_name.setPlaceholderText("缺省为「<首个文件>_图片.pdf」")
        l_img_pdf.addRow("页面尺寸：", self._img_page_size)
        l_img_pdf.addRow("页面方向：", self._img_orientation)
        l_img_pdf.addRow("页面边距：", self._img_margin)
        l_img_pdf.addRow("输出文件名：", self._img_pdf_name)
        self._options_stack.addWidget(p_img_pdf)

        # 9. to_text
        p_text = QWidget()
        l_text = QFormLayout(p_text)
        self._to_text_pages = QLineEdit(p_text)
        self._to_text_pages.setPlaceholderText("留空表示全部页面")
        l_text.addRow("提取页面：", self._to_text_pages)
        tip_text = QLabel("注意：仅提取矢量文本图层；扫描件图像请使用 OCR 模块识别。", p_text)
        tip_text.setStyleSheet("color: #64748b; font-size: 11px;")
        l_text.addRow("", tip_text)
        self._options_stack.addWidget(p_text)

        # 10. watermark
        p_wm = QWidget()
        l_wm = QFormLayout(p_wm)
        self._wm_type = QComboBox(p_wm)
        self._wm_type.addItem("文字水印", "text")
        self._wm_type.addItem("图片水印 (徽标/图章)", "image")

        self._wm_text = QLineEdit(p_wm)
        self._wm_text.setText("内部机密")

        img_row = QHBoxLayout()
        self._wm_img_path = QLineEdit(p_wm)
        self._wm_img_path.setPlaceholderText("选择本地 PNG / JPG 图章文件")
        self._wm_browse_img_btn = QPushButton("选择…", p_wm)
        self._wm_browse_img_btn.clicked.connect(self._on_browse_watermark_image)
        img_row.addWidget(self._wm_img_path, 1)
        img_row.addWidget(self._wm_browse_img_btn)

        self._wm_pos = QComboBox(p_wm)
        self._wm_pos.addItem("页面居中 (Center)", "center")
        self._wm_pos.addItem("全页网格平铺 (Tiled)", "tiled")
        self._wm_pos.addItem("左上角 (Top-Left)", "top-left")
        self._wm_pos.addItem("右上角 (Top-Right)", "top-right")
        self._wm_pos.addItem("左下角 (Bottom-Left)", "bottom-left")
        self._wm_pos.addItem("右下角 (Bottom-Right)", "bottom-right")

        self._wm_opacity = QSpinBox(p_wm)
        self._wm_opacity.setRange(1, 100)
        self._wm_opacity.setValue(30)
        self._wm_opacity.setSuffix(" %")

        self._wm_angle = QSpinBox(p_wm)
        self._wm_angle.setRange(-180, 180)
        self._wm_angle.setValue(45)
        self._wm_angle.setSuffix(" °")

        self._wm_font_size = QSpinBox(p_wm)
        self._wm_font_size.setRange(8, 200)
        self._wm_font_size.setValue(48)

        self._wm_color = QLineEdit(p_wm)
        self._wm_color.setText("#ff0000")

        self._wm_scale = QSpinBox(p_wm)
        self._wm_scale.setRange(5, 100)
        self._wm_scale.setValue(30)
        self._wm_scale.setSuffix(" % (页面宽度)")

        self._wm_pages = QLineEdit(p_wm)
        self._wm_pages.setPlaceholderText("留空表示全部页面，如 1-3,5")

        l_wm.addRow("水印类型：", self._wm_type)
        l_wm.addRow("水印文字：", self._wm_text)
        l_wm.addRow("水印图片：", img_row)
        l_wm.addRow("对齐排版：", self._wm_pos)
        l_wm.addRow("不透明度：", self._wm_opacity)
        l_wm.addRow("旋转角度：", self._wm_angle)
        l_wm.addRow("文字字号：", self._wm_font_size)
        l_wm.addRow("文字颜色：", self._wm_color)
        l_wm.addRow("图片缩放：", self._wm_scale)
        l_wm.addRow("生效页面：", self._wm_pages)

        self._wm_type.currentIndexChanged.connect(self._on_wm_type_changed)
        self._on_wm_type_changed(0)
        self._options_stack.addWidget(p_wm)

        # 11. page_numbers
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

        self._pn_skip_first = QCheckBox("跳过首页（封面不添加）", p_pn)
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

        # 12. metadata
        p_meta = QWidget()
        l_meta = QFormLayout(p_meta)
        self._meta_title = QLineEdit(p_meta)
        self._meta_author = QLineEdit(p_meta)
        self._meta_subject = QLineEdit(p_meta)
        self._meta_keywords = QLineEdit(p_meta)
        l_meta.addRow("文档标题：", self._meta_title)
        l_meta.addRow("文档作者：", self._meta_author)
        l_meta.addRow("文档主题：", self._meta_subject)
        l_meta.addRow("关键字：", self._meta_keywords)
        self._options_stack.addWidget(p_meta)

        # 13. encrypt
        p_enc = QWidget()
        l_enc = QFormLayout(p_enc)
        self._enc_user_pw = QLineEdit(p_enc)
        self._enc_user_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._enc_user_pw.textChanged.connect(self._on_password_input_changed)

        self._enc_confirm_pw = QLineEdit(p_enc)
        self._enc_confirm_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._enc_confirm_pw.setPlaceholderText("再次输入以确认密码")
        self._enc_confirm_pw.textChanged.connect(self._on_password_input_changed)

        self._enc_strength_lbl = QLabel("未输入", p_enc)
        self._enc_strength_lbl.setStyleSheet("color: #64748b; font-weight: bold;")

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

        risk_warn = QLabel("⚠️ 风险提示：请妥善备份密码。若密码遗失，任何软件均无法解密恢复文档内容！", p_enc)
        risk_warn.setWordWrap(True)
        risk_warn.setStyleSheet("color: #b45309; font-size: 11px; background-color: #fef3c7; border-radius: 4px; padding: 4px;")

        l_enc.addRow("打开密码：", self._enc_user_pw)
        l_enc.addRow("确认密码：", self._enc_confirm_pw)
        l_enc.addRow("密码强度：", self._enc_strength_lbl)
        l_enc.addRow("权限密码：", self._enc_owner_pw)
        l_enc.addRow("允许操作：", perm_box)
        l_enc.addRow("", risk_warn)
        self._options_stack.addWidget(p_enc)

        # 14. decrypt
        p_dec = QWidget()
        l_dec = QFormLayout(p_dec)
        self._dec_pw = QLineEdit(p_dec)
        self._dec_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._dec_pw.setPlaceholderText("输入打开密码（仅权限锁定时可留空）")
        l_dec.addRow("解除密码：", self._dec_pw)
        tip_dec = QLabel("提示：解除密码后将输出明文未加密的 PDF 文件。", p_dec)
        tip_dec.setStyleSheet("color: #64748b; font-size: 11px;")
        l_dec.addRow("", tip_dec)
        self._options_stack.addWidget(p_dec)

        # 15. compress
        p_comp = QWidget()
        l_comp = QFormLayout(p_comp)
        self._comp_level = QComboBox(p_comp)
        self._comp_level.addItem("标准优化 (推荐无损 + 结构精简)", "standard")
        self._comp_level.addItem("轻度无损 (仅重复对象与内容流压缩)", "lossless")
        self._comp_level.addItem("强力压缩 (极简体积 + 图片智能降噪)", "aggressive")
        self._comp_strip_meta = QCheckBox("剥离冗余制作元数据 (Producer / Creator)", p_comp)
        self._comp_strip_meta.setChecked(True)
        tip_comp = QLabel("处理完成后将详细展示压缩前后体积对比及节省百分比。", p_comp)
        tip_comp.setStyleSheet("color: #64748b; font-size: 11px;")
        l_comp.addRow("压缩等级：", self._comp_level)
        l_comp.addRow("优化项：", self._comp_strip_meta)
        l_comp.addRow("", tip_comp)
        self._options_stack.addWidget(p_comp)

    def _on_wm_type_changed(self, index: int) -> None:
        is_image = index == 1
        self._wm_text.setVisible(not is_image)
        self._wm_font_size.setVisible(not is_image)
        self._wm_color.setVisible(not is_image)
        self._wm_img_path.setVisible(is_image)
        self._wm_browse_img_btn.setVisible(is_image)
        self._wm_scale.setVisible(is_image)

    def _on_browse_watermark_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择水印图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if path:
            self._wm_img_path.setText(path)

    def _on_password_input_changed(self) -> None:
        pw = self._enc_user_pw.text()
        confirm = self._enc_confirm_pw.text()
        eval_res = evaluate_password_strength(pw)
        label = eval_res["label"]
        color = eval_res["color"]

        if confirm and pw != confirm:
            self._enc_strength_lbl.setText(f"{label}（两次输入不一致 ✕）")
            self._enc_strength_lbl.setStyleSheet("color: #dc2626; font-weight: bold;")
        else:
            self._enc_strength_lbl.setText(f"{label} ({eval_res['hint']})")
            self._enc_strength_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

    # --- 收集选项参数 ---

    def _on_table_selection_changed(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._sources):
            self._preview_banner.setText("💡 提示：点击列表中的文件可查看详细规格与元信息")
            return

        src = self._sources[row]
        info = get_pdf_info(src)
        name_str = src.name
        size_str = _format_size(info.get("size_bytes", 0))

        if info.get("type") == "pdf":
            if info.get("error"):
                desc = f"⚠️ <b>{name_str}</b> ({size_str}) · 文件可能已损坏或格式异常：{info.get('error')}"
            elif info.get("is_encrypted"):
                desc = f"🔒 <b>{name_str}</b> ({size_str}) · 受密码保护已加密文档"
            else:
                pc = info.get("page_count", 0)
                dim = info.get("dimensions", "--")
                t = info.get("title") or "（无标题）"
                a = info.get("author") or "（无作者）"
                desc = f"📄 <b>{name_str}</b> · {pc} 页 · 尺寸: {dim} · 大小: {size_str} · 标题: {t} · 作者: {a}"

                # 若当前是元数据工具且用户尚未输入内容，自动带入当前文档元数据
                if self._active_tool_id == TOOL_METADATA:
                    if not self._meta_title.text().strip() and info.get("title"):
                        self._meta_title.setText(info.get("title"))
                    if not self._meta_author.text().strip() and info.get("author"):
                        self._meta_author.setText(info.get("author"))
                    if not self._meta_subject.text().strip() and info.get("subject"):
                        self._meta_subject.setText(info.get("subject"))
                    if not self._meta_keywords.text().strip() and info.get("keywords"):
                        self._meta_keywords.setText(info.get("keywords"))
        elif info.get("type") == "image":
            dim = info.get("dimensions", "--")
            desc = f"🖼️ <b>{name_str}</b> · 分辨率: {dim} · 大小: {size_str}"
        else:
            desc = f"📁 <b>{name_str}</b> · 大小: {size_str}"

        self._preview_banner.setText(desc)

    def _collect_options(self, tool_id: str) -> Dict[str, Any]:
        opts: Dict[str, Any] = {}
        if tool_id == TOOL_MERGE:
            name = self._merge_name.text().strip()
            if name:
                opts["output_name"] = name
        elif tool_id == TOOL_SPLIT:
            mode_map = {0: "each", 1: "every-n", 2: "range"}
            opts["mode"] = mode_map.get(self._split_mode.currentIndex(), "each")
            opts["every"] = self._split_every.value()
            ranges_val = self._split_ranges.text().strip()
            if opts["mode"] == "range":
                if not ranges_val:
                    raise PdfInputError(suggested_action="按页码范围拆分时，请输入页码范围（例如 1-3,5-8）。")
                opts["ranges"] = ranges_val
            elif ranges_val:
                opts["ranges"] = ranges_val
        elif tool_id == TOOL_EXTRACT:
            pages = self._extract_pages.text().strip()
            if not pages:
                raise PdfInputError(suggested_action="请在选项面板中输入要提取的页码（如 1-5,8）。")
            opts["pages"] = pages
        elif tool_id == TOOL_DELETE:
            pages = self._delete_pages.text().strip()
            if not pages:
                raise PdfInputError(suggested_action="请在选项面板中输入要删除的页码（如 2,4-6）。")
            opts["pages"] = pages
        elif tool_id == TOOL_ROTATE:
            opts["degrees"] = int(self._rotate_deg.currentData())
            pages = self._rotate_pages.text().strip()
            if pages:
                opts["pages"] = pages
        elif tool_id == TOOL_REORDER:
            rule = self._reorder_rule.text().strip()
            if not rule:
                raise PdfInputError(suggested_action="请输入重排页码序列（如 3,1,2,4 或 reverse 倒序全部页面）。")
            opts["order"] = rule
        elif tool_id == TOOL_TO_IMAGES:
            opts["image_format"] = "png" if self._to_img_fmt.currentIndex() == 0 else "jpg"
            opts["dpi"] = int(self._to_img_dpi.currentData())
            opts["quality"] = self._to_img_quality.value()
            pages = self._to_img_pages.text().strip()
            if pages:
                opts["pages"] = pages
        elif tool_id == TOOL_IMAGES_TO_PDF:
            opts["page_size"] = str(self._img_page_size.currentData())
            opts["orientation"] = str(self._img_orientation.currentData())
            opts["margin"] = int(self._img_margin.currentData())
            name = self._img_pdf_name.text().strip()
            if name:
                opts["output_name"] = name
        elif tool_id == TOOL_TO_TEXT:
            pages = self._to_text_pages.text().strip()
            if pages:
                opts["pages"] = pages
        elif tool_id == TOOL_WATERMARK:
            wm_type = str(self._wm_type.currentData())
            opts["watermark_type"] = wm_type
            if wm_type == "image":
                img_p = self._wm_img_path.text().strip()
                if not img_p:
                    raise PdfInputError(suggested_action="请选择有效的水印图片文件。")
                opts["image_path"] = img_p
                opts["scale"] = self._wm_scale.value()
            else:
                text = self._wm_text.text().strip()
                if not text:
                    raise PdfInputError(suggested_action="请填写水印文字内容。")
                opts["text"] = text
                opts["font_size"] = float(self._wm_font_size.value())
                opts["color"] = self._wm_color.text().strip() or "#ff0000"

            opts["mode"] = str(self._wm_pos.currentData())
            opts["opacity"] = self._wm_opacity.value()
            opts["angle"] = float(self._wm_angle.value())
            pages = self._wm_pages.text().strip()
            if pages:
                opts["pages"] = pages
        elif tool_id == TOOL_PAGE_NUMBERS:
            opts["position"] = str(self._pn_pos.currentData())
            opts["format"] = self._pn_fmt.currentText()
            opts["start"] = self._pn_start.value()
            opts["skip_first"] = self._pn_skip_first.isChecked()
            opts["font_size"] = float(self._pn_font_size.value())
            opts["margin"] = float(self._pn_margin.value())
            opts["color"] = self._pn_color.text().strip() or "#000000"
        elif tool_id == TOOL_METADATA:
            if self._meta_title.text().strip():
                opts["title"] = self._meta_title.text().strip()
            if self._meta_author.text().strip():
                opts["author"] = self._meta_author.text().strip()
            if self._meta_subject.text().strip():
                opts["subject"] = self._meta_subject.text().strip()
            if self._meta_keywords.text().strip():
                opts["keywords"] = self._meta_keywords.text().strip()
        elif tool_id == TOOL_ENCRYPT:
            user_pw = self._enc_user_pw.text()
            confirm_pw = self._enc_confirm_pw.text()
            if not user_pw:
                raise PdfInputError(suggested_action="加密操作必须设置打开密码。")
            if not confirm_pw:
                raise PdfInputError(suggested_action="请再次输入确认密码。")
            if user_pw != confirm_pw:
                raise PdfInputError(suggested_action="两次输入的打开密码不一致，请核对后重试。")
            opts["user_password"] = user_pw
            if self._enc_owner_pw.text():
                opts["owner_password"] = self._enc_owner_pw.text()
            opts["allow_print"] = self._enc_print.isChecked()
            opts["allow_copy"] = self._enc_copy.isChecked()
            opts["allow_modify"] = self._enc_modify.isChecked()
            opts["allow_annotate"] = self._enc_annotate.isChecked()
        elif tool_id == TOOL_DECRYPT:
            pw = self._dec_pw.text()
            if pw:
                opts["password"] = pw
        elif tool_id == TOOL_COMPRESS:
            opts["level"] = str(self._comp_level.currentData())
            opts["strip_metadata"] = self._comp_strip_meta.isChecked()

        # 若在输出设置中提供了统一原文件解密密码且当前尚未单独设置，补充至 options
        if hasattr(self, "_source_pw_edit"):
            src_pw = self._source_pw_edit.text().strip()
            if src_pw and "password" not in opts:
                opts["password"] = src_pw

        return opts


    # --- 文件列表维护与表格渲染 ---

    def _on_add_files(self) -> None:
        spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)
        if not spec:
            return
        patterns = ["*{0}".format(s) for s in spec.accepts]
        filter_str = "{0} 文件 ({1});;所有文件 (*.*)".format(
            " / ".join(spec.accepts), " ".join(patterns)
        )
        files, _ = QFileDialog.getOpenFileNames(
            self, f"选择待处理文件 - {spec.label}", "", filter_str
        )
        if files:
            self._ingest_paths([Path(p) for p in files])

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择包含待处理文件的文件夹")
        if folder:
            spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)
            accepts = spec.accepts if spec else PDF_SUFFIXES
            found = expand_sources([Path(folder)], accepts)
            if not found:
                QMessageBox.information(
                    self, "未找到文件", f"选定文件夹内未找到符合后缀 ({' '.join(accepts)}) 的文件。"
                )
                return
            self._ingest_paths(found)

    def _ingest_paths(self, paths: List[Path]) -> None:
        """解析并加入待处理列表，查重与过滤。"""
        spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)
        accepts = set(spec.accepts if spec else PDF_SUFFIXES)

        added = 0
        existing_set = {p.resolve() for p in self._sources}

        for p in paths:
            rp = p.resolve()
            if not rp.is_file():
                continue
            if rp.suffix.lower() not in accepts:
                continue
            if rp in existing_set:
                continue
            self._sources.append(rp)
            existing_set.add(rp)
            added += 1

        if added > 0:
            self._refresh_table()
            self._update_ui_state()

    def _on_remove_selected(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        for r in rows:
            if 0 <= r < len(self._sources):
                del self._sources[r]
        self._refresh_table()
        self._update_ui_state()

    def _on_remove_single(self, path: Path) -> None:
        if path in self._sources:
            self._sources.remove(path)
            self._refresh_table()
            self._update_ui_state()

    def _on_retry_single(self, path: Path) -> None:
        if self._active_tool_id in (TOOL_MERGE, TOOL_IMAGES_TO_PDF):
            self._start_processing(self._sources)
        else:
            self._start_processing([path])

    def _on_clear(self) -> None:
        for w in list(self._row_actions.values()):
            try:
                w.deleteLater()
            except Exception:
                pass
        self._row_actions.clear()
        self._sources.clear()
        self._rows.clear()
        self._table.setRowCount(0)
        self._details.clear()
        self._delivery_banner.setVisible(False)
        self._update_ui_state()

    def _on_move_up(self) -> None:
        row = self._table.currentRow()
        if row > 0 and row < len(self._sources):
            self._sources[row - 1], self._sources[row] = (
                self._sources[row],
                self._sources[row - 1],
            )
            self._refresh_table()
            self._table.selectRow(row - 1)

    def _on_move_down(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._sources) - 1:
            self._sources[row], self._sources[row + 1] = (
                self._sources[row + 1],
                self._sources[row],
            )
            self._refresh_table()
            self._table.selectRow(row + 1)

    def _refresh_table(self) -> None:
        """重绘表格内容并提取文件规格与大小。"""
        for w in list(self._row_actions.values()):
            try:
                w.deleteLater()
            except Exception:
                pass
        self._row_actions.clear()
        self._table.setRowCount(len(self._sources))
        self._rows.clear()

        total_bytes = 0

        for row, src in enumerate(self._sources):
            self._rows[str(src)] = row

            # 列 0: 序号
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, item_num)

            # 列 1: 文件名
            item_name = QTableWidgetItem(src.name)
            item_name.setToolTip(str(src))
            self._table.setItem(row, 1, item_name)

            # 元数据检测（大小与页数）
            info = get_pdf_info(src)
            size_b = info.get("size_bytes", 0)
            total_bytes += size_b

            # 列 2: 大小
            item_size = QTableWidgetItem(_format_size(size_b))
            item_size.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, item_size)

            # 检查格式兼容性
            spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)
            accepts = set(spec.accepts if spec else PDF_SUFFIXES)
            is_valid_ext = src.suffix.lower() in accepts

            # 列 2 大文件提示
            if size_b > 200 * 1024 * 1024:
                item_size.setToolTip(f"{_format_size(size_b)} - 文件较大（>200MB），处理可能耗时较长")

            # 列 3: 页数 / 规格
            if not is_valid_ext:
                spec_str = "格式不符"
            elif info.get("type") == "pdf":
                if info.get("error"):
                    spec_str = "⚠ 无法解析"
                elif info.get("is_encrypted"):
                    spec_str = "🔒 加密"
                else:
                    pc = info.get("page_count", 0)
                    spec_str = f"{pc} 页" if pc > 0 else "--"
            elif info.get("type") == "image":
                spec_str = info.get("dimensions", "图片")
            else:
                spec_str = "--"
            item_spec = QTableWidgetItem(spec_str)
            item_spec.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 3, item_spec)

            # 列 4: 状态
            if not is_valid_ext:
                item_status = QTableWidgetItem("格式不符")
                item_status.setForeground(QColor("#dc2626"))
                item_status.setToolTip(f"当前工具「{spec.label if spec else ''}」仅支持 {', '.join(accepts)} 格式")
            elif info.get("error"):
                item_status = QTableWidgetItem("文件异常")
                item_status.setForeground(QColor("#dc2626"))
                item_status.setToolTip(f"无法正常解析该文件：{info.get('error')}")
            else:
                item_status = QTableWidgetItem("就绪")
                item_status.setForeground(QColor("#16a34a"))
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 4, item_status)

            # 列 5: 产物与结果
            item_out = QTableWidgetItem("--")
            self._table.setItem(row, 5, item_out)

            # 列 6: 行级操作
            action_widget = _RowActionWidget(src, self._table)
            action_widget.remove_clicked.connect(self._on_remove_single)
            action_widget.retry_clicked.connect(self._on_retry_single)
            self._row_actions[str(src)] = action_widget
            self._table.setCellWidget(row, 6, action_widget)

        count_str = f"已选 {len(self._sources)} 个文件"
        if total_bytes > 0:
            count_str += f"（总计 {_format_size(total_bytes)}）"
        self._file_stats_lbl.setText(count_str)

        has_enc = any(get_pdf_info(s).get("is_encrypted") for s in self._sources)
        if hasattr(self, "_source_pw_container"):
            self._source_pw_container.setVisible(
                has_enc or self._active_tool_id == TOOL_DECRYPT or bool(self._source_pw_edit.text())
            )

    def _update_ui_state(self) -> None:
        has_files = len(self._sources) > 0
        spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)

        if self._active_tool_id == TOOL_MERGE:
            can_start = len(self._sources) >= 2
        else:
            can_start = has_files

        self._start_btn.setEnabled(can_start)
        self._remove_btn.setEnabled(has_files)
        self._clear_btn.setEnabled(has_files)

        if not has_files:
            self._status_label.setText("等待添加文件")
        elif self._active_tool_id == TOOL_MERGE and len(self._sources) < 2:
            self._status_label.setText("合并操作至少需要添加 2 个 PDF 文件")
        else:
            self._status_label.setText(f"就绪：共 {len(self._sources)} 个文件")

    def _on_browse_output_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self._out_dir_edit.setText(dir_path)

    # --- 任务执行与状态反馈 ---

    def _on_start(self) -> None:
        self._start_processing(self._sources)

    def _start_processing(self, targets: List[Path]) -> None:
        if self._busy_check and self._busy_check():
            QMessageBox.warning(self, "系统忙", "当前有其他任务正在执行，请稍候。")
            return

        if not targets:
            QMessageBox.warning(self, "无文件", "请先添加待处理的文件。")
            return

        tid = self._active_tool_id
        spec = TOOL_SPEC_BY_ID.get(tid)
        if not spec:
            return

        if tid == TOOL_MERGE and len(targets) < 2:
            QMessageBox.warning(self, "文件不足", "合并 PDF 至少需要添加 2 个文件。")
            return

        incompatible = [p.name for p in targets if p.suffix.lower() not in spec.accepts]
        if incompatible:
            acc_fmt = ", ".join(spec.accepts)
            bad_list = chr(10).join(incompatible[:5])
            QMessageBox.warning(
                self,
                "格式不符",
                f"当前「{spec.label}」工具仅支持 {acc_fmt} 格式。\n以下文件不兼容，请先移除：\n{bad_list}",
            )
            return

        corrupted = [p.name for p in targets if get_pdf_info(p).get("error")]
        if corrupted:
            bad_corrupt = chr(10).join(corrupted[:5])
            reply = QMessageBox.warning(
                self,
                "文件异常提示",
                f"检测到以下文件可能已损坏或格式异常：\n{bad_corrupt}\n\n是否仍要尝试处理？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            options = self._collect_options(tid)
        except DocToolError as exc:
            QMessageBox.warning(self, "参数错误", exc.suggested_action or exc.user_message)
            return

        out_dir_text = self._out_dir_edit.text().strip()
        out_dir = Path(out_dir_text) if out_dir_text else None
        overwrite = self._overwrite_box.isChecked()

        # UI 状态切换至处理中
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._add_files_btn.setEnabled(False)
        self._add_folder_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)
        self._delivery_banner.setVisible(False)

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._details.clear()
        self._details.appendPlainText(f"=== 开始执行「{spec.label}」===")
        self._status_label.setText("处理中…")

        def _work(cancel_token: Any) -> PdfToolBatchResult:
            def _prog(d: int, t: int, rec: PdfToolRecord) -> None:
                self._emit_progress(d, t, rec)

            return run_pdf_tool(
                tid,
                targets,
                output_dir=out_dir,
                overwrite=overwrite,
                options=options,
                on_progress=_prog,
                cancel_token=cancel_token,
            )

        task = TaskSpec(
            action_type=f"pdf_tool_{tid}",
            fn=_work,
            on_event=self._on_task_event,
            on_done=self._on_done,
        )

        self._runner.submit(task)
        self._timer.start()

    def _emit_progress(self, done: int, total: int, record: PdfToolRecord) -> None:
        self.progress.emit(done, total, record)

    def _on_progress(self, done: int, total: int, record: PdfToolRecord) -> None:
        pct = int((done / float(total)) * 100) if total > 0 else 0
        self._progress.setValue(pct)
        self._status_label.setText(f"处理中 ({done}/{total}): {record.source.name}")

        spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)
        if spec and spec.is_batch:
            # 批量整包工具（如合并、图片转 PDF）：更新所有相关行
            for r_idx in range(self._table.rowCount()):
                st_item = self._table.item(r_idx, 4)
                if st_item:
                    st_item.setText("成功" if record.ok else "失败")
                    st_item.setForeground(QColor("#16a34a" if record.ok else "#dc2626"))
                o_item = self._table.item(r_idx, 5)
                if o_item:
                    if r_idx == 0:
                        o_item.setText(record.detail or "合并完成")
                        if record.outputs:
                            o_item.setToolTip("\n".join(str(p) for p in record.outputs))
                    else:
                        o_item.setText("已合并至产物文档" if record.ok else "处理失败")
                act_w = self._table.cellWidget(r_idx, 6)
                if isinstance(act_w, _RowActionWidget):
                    p_out = record.outputs[0] if record.outputs else None
                    act_w.set_target(p_out)
                    act_w.set_failed(not record.ok)
        else:
            src_key = str(record.source)
            row = self._rows.get(src_key)
            if row is None and len(self._sources) > 0:
                row = 0

            if row is not None and 0 <= row < self._table.rowCount():
                status_item = self._table.item(row, 4)
                if status_item:
                    status_item.setText("成功" if record.ok else "失败")
                    status_item.setForeground(QColor("#16a34a" if record.ok else "#dc2626"))

                out_item = self._table.item(row, 5)
                if out_item:
                    if record.outputs:
                        out_item.setText(record.detail or f"已生成 {len(record.outputs)} 个产物")
                        out_item.setToolTip("\n".join(str(p) for p in record.outputs))
                    else:
                        out_item.setText(record.detail or ("成功" if record.ok else "失败"))

                act_widget = self._table.cellWidget(row, 6)
                if isinstance(act_widget, _RowActionWidget):
                    primary_out = record.outputs[0] if record.outputs else None
                    act_widget.set_target(primary_out)
                    act_widget.set_failed(not record.ok)

        # 日志追加
        out_desc = f" -> {record.outputs[0].name}" if record.outputs else ""
        log_line = f"[{'OK' if record.ok else 'FAIL'}] {record.source.name}{out_desc} ({record.elapsed_seconds:.2f}s) {record.detail}"
        self._details.appendPlainText(log_line)

    def _on_task_event(self, event: TaskEvent) -> None:
        pass

    def _on_done(self, result: Any) -> None:
        self._timer.stop()
        self._cancel_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._add_files_btn.setEnabled(True)
        self._add_folder_btn.setEnabled(True)
        self._clear_btn.setEnabled(True)

        if not isinstance(result, PdfToolBatchResult):
            self._status_label.setText("执行出错：未知返回类型")
            return

        self._last_result = result
        self._open_dir_btn.setEnabled(True)

        summary = result.summary()
        self._status_label.setText(summary)
        self._details.appendPlainText(f"\n=== 执行完成：{summary} ===")

        # 展示完成交付横幅
        if result.succeeded > 0:
            self._delivery_banner.setVisible(True)
            if result.failed == 0:
                self._delivery_text.setText(f"🎉 全部处理完成！共成功交付 {result.succeeded} 项产物。")
                self._delivery_banner.setStyleSheet("background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 6px;")
            else:
                self._delivery_text.setText(f"⚠️ 处理完成：成功 {result.succeeded} 个，失败 {result.failed} 个。")
                self._delivery_banner.setStyleSheet("background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 6px;")

    def _on_cancel(self) -> None:
        self._runner.cancel()
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("正在取消…")

    def _on_open_output_dir(self) -> None:
        out_dir_text = self._out_dir_edit.text().strip()
        target_dir = Path(out_dir_text) if out_dir_text else None

        if not target_dir or not target_dir.exists():
            if self._last_result and self._last_result.records:
                for r in self._last_result.records:
                    if r.outputs and r.outputs[0].exists():
                        target_dir = r.outputs[0].parent
                        break
            if not target_dir and self._sources:
                target_dir = self._sources[0].parent

        if target_dir and target_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_dir)))
        else:
            QMessageBox.information(self, "提示", "输出目录尚未生成或不存在。")

    def _on_open_latest_output(self) -> None:
        if self._last_result and self._last_result.records:
            for r in reversed(self._last_result.records):
                if r.outputs and r.outputs[0].exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(r.outputs[0])))
                    return
        QMessageBox.information(self, "提示", "未找到可打开的产物文件。")

    def _on_reset_for_next(self) -> None:
        self._delivery_banner.setVisible(False)
        self._progress.setVisible(False)
        self._details.clear()
        self._status_label.setText("就绪")
        self._update_ui_state()

    # --- 内部兼容性接口（满足现有测试套件） ---

    def _populate_tool_list(self) -> None:
        for spec in TOOL_SPECS:
            item = QListWidgetItem(f"  {spec.label}")
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            self._tool_list.addItem(item)

    def _on_internal_tool_list_changed(
        self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]
    ) -> None:
        if current:
            tid = current.data(Qt.ItemDataRole.UserRole)
            if tid:
                self.select_tool(str(tid))

    def _current_tool_id(self) -> str:
        return self._active_tool_id

    def reject(self) -> None:
        if self._runner.is_running:
            reply = QMessageBox.question(
                self,
                "任务进行中",
                "PDF 处理任务仍在执行中，确定要中断并退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._runner.cancel()
        self._timer.stop()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._runner.is_running:
            reply = QMessageBox.question(
                self,
                "任务进行中",
                "PDF 处理任务仍在执行中，确定要中断并退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._runner.cancel()
        self._timer.stop()
        super().closeEvent(event)

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
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_zone.set_drag_over(False)
        urls = event.mimeData().urls()
        if not urls:
            return

        spec = TOOL_SPEC_BY_ID.get(self._active_tool_id)
        accepts = spec.accepts if spec else PDF_SUFFIXES

        paths: List[Path] = []
        for url in urls:
            if url.isLocalFile():
                p = Path(url.toLocalFile()).resolve()
                if p.is_file() and p.suffix.lower() in accepts:
                    paths.append(p)
                elif p.is_dir():
                    paths.extend(expand_sources([p], accepts))

        if paths:
            event.acceptProposedAction()
            if self._view_stack.currentIndex() == 0:
                self._view_stack.setCurrentIndex(1)
            self._ingest_paths(paths)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self._view_stack.currentIndex() == 1:
                self._show_portal_view()
                event.accept()
                return
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_F:
                if self._view_stack.currentIndex() == 0:
                    self._portal_search.setFocus()
                    self._portal_search.selectAll()
                    event.accept()
                    return
            elif event.key() == Qt.Key.Key_O:
                self._on_add_files()
                event.accept()
                return
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._start_btn.isEnabled():
                    self._on_start()
                    event.accept()
                    return
        elif event.key() == Qt.Key.Key_Delete:
            if self._table.hasFocus():
                self._on_remove_selected()
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_cards_grid") and self._view_stack.currentIndex() == 0:
            self._filter_portal_cards()
