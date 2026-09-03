# -*- coding: utf-8 -*-
"""首页任务页：「项目出稿 + 常用工具」双栏（无项目时显示，沿用 EmptyState 名）。

自上而下：标题行（产品定位 + 版本徽章）、副标题、主体双栏（左 6 右 4）与
底部锚定行。左栏是新建/打开入口与最近项目卡片（无条目时显示空态文案，
卡片与空态互斥）；右栏是文档互转拖放卡与 PDF 工具箱卡。

互转卡可点击、且整页接受文件拖放：拖入时互转卡高亮（虚线切实线 +
accent 浅底，标题切换为「松开鼠标，添加这些文件」），dragLeave/drop 还原；
松手后把本地路径交回主窗口，由 ``ConvertDialog._ingest_paths`` 展开文件夹
一层并填入清单。仅本页设置 ``acceptDrops``，工作台视图不受影响。

样式一律走 ``styles.py`` 的全局 QSS 规则（objectName / 动态属性选择器），
不在控件上写内联样式，保证深浅两套主题都正确。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.tree import DEFAULT_TYPE_LABELS
from doc_tool.application.project_service import RecentEntry
from doc_tool.domain.branding import PRODUCT_DESCRIPTION_UI
from doc_tool.domain.version import APP_VERSION

# 最近项目卡展示上限（与旧版列表一致）。
MAX_VISIBLE_RECENT = 5

# 类型徽章短标签；未知类型回退章节树的完整类型映射。
_TYPE_BADGE_LABELS = {
    "requirement": "需求",
    "design": "设计",
    "general": "通用",
}

CONVERT_CARD_TITLE = "文档互转"
CONVERT_DRAG_TITLE = "松开鼠标，添加这些文件"
CONVERT_CARD_DESC = (
    "把 Word / PDF / Markdown / HTML 文件拖到本窗口\n"
    "任意位置即可互转；也可点击挑选文件批量处理。"
)
CONVERT_DRAG_DESC = "已识别拖入的文件，进入互转窗口。"
CONVERT_CARD_BADGE = "Word ↔ PDF ↔ Markdown · 支持整个文件夹拖入"
PDF_TOOLBOX_CARD_TITLE = "PDF 工具箱"
PDF_TOOLBOX_CARD_DESC = (
    "合并、拆分、加水印、加密解密与页面组织。\n"
    "纯离线处理，点击挑选 PDF 文件快速操作。"
)
PDF_TOOLBOX_CARD_BADGE = "14 项离线工具 · 批量安全处理"
RECENT_EMPTY_TEXT = "把 Word 源文档用「新建项目」导入后，会在这里列出最近项目。"


def _format_last_opened(last_opened: str) -> str:
    """把最近打开的 ISO 时间戳渲染成「N 天前打开」。

    旧版记录没有时间戳或值损坏时返回空串，卡片只显示路径（向后兼容）。
    """
    if not last_opened:
        return ""
    try:
        opened = datetime.fromisoformat(last_opened)
    except ValueError:
        return ""
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - opened).days
    if days <= 0:
        return "今天打开"
    if days == 1:
        return "昨天打开"
    return "{0} 天前打开".format(days)


def _type_badge_label(document_type: str) -> str:
    """文档类型 → 徽章短文案；空类型返回空串（不显示徽章）。"""
    if not document_type:
        return ""
    if document_type in _TYPE_BADGE_LABELS:
        return _TYPE_BADGE_LABELS[document_type]
    return DEFAULT_TYPE_LABELS.get(document_type, document_type)


def _make_pill(text: str, *, muted: bool = False, parent=None) -> QLabel:
    """小圆角徽章 pill（样式见 QSS ``QLabel[pill="true"]`` 规则）。"""
    label = QLabel(text, parent)
    label.setProperty("pill", "true")
    if muted:
        label.setProperty("pillTone", "muted")
    return label


class _ClickableCard(QFrame):
    """整卡响应左键点击的卡片（最近项目卡 / 互转卡）。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _LinkLabel(QLabel):
    """底部 accent 色文字入口（使用说明 / 关于）。"""

    clicked = Signal()

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("homeAccent")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class EmptyState(QWidget):
    """首页任务页（视图状态 EMPTY 时的中央页）。"""

    def __init__(
        self,
        *,
        on_new_project: Optional[Callable[[], None]] = None,
        on_open_project: Optional[Callable[[], None]] = None,
        on_open_recent: Optional[Callable[[str], None]] = None,
        on_convert: Optional[Callable[[], None]] = None,
        on_pdf_toolbox: Optional[Callable[[], None]] = None,
        on_drop_files: Optional[Callable[[List[Path]], None]] = None,
        on_show_help: Optional[Callable[[], None]] = None,
        on_about: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        # 自绘 window 底色：裸 QWidget 不带 WA_StyledBackground 时不画 QSS 背景，
        # 深色主题下脱离 QMainWindow（如离屏抓图）会露出系统浅色底。
        self.setObjectName("homeRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_new_project = on_new_project
        self._on_open_project = on_open_project
        self._on_open_recent = on_open_recent
        self._on_convert = on_convert
        self._on_pdf_toolbox = on_pdf_toolbox
        self._on_drop_files = on_drop_files
        self._on_show_help = on_show_help
        self._on_about = on_about
        self._enabled = True
        self._drag_over = False
        self._buttons: List[QPushButton] = []
        self._recent_cards: List[QFrame] = []
        self._empty_label: Optional[QLabel] = None
        # 仅首页视图接收拖放（工作台视图不设置）。
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 36, 48, 24)
        layout.setSpacing(12)

        # 标题行：品牌徽章 + 产品定位 + 版本徽章
        head = QHBoxLayout()
        head.setSpacing(10)
        brand = QLabel("DocTool", self)
        brand.setObjectName("homeBrandIcon")
        head.addWidget(brand)
        title = QLabel(PRODUCT_DESCRIPTION_UI, self)
        title.setObjectName("welcomeTitle")
        head.addWidget(title)
        self._version_badge = _make_pill(
            "v{0}".format(APP_VERSION), muted=True, parent=self
        )
        self._version_badge.setToolTip("当前版本 v{0}".format(APP_VERSION))
        head.addWidget(self._version_badge)
        head.addStretch(1)
        layout.addLayout(head)

        subtitle = QLabel(
            "从 Word 导入成 Markdown 项目出稿；常用互转在右侧，把文件拖进窗口即可发起。",
            self,
        )
        subtitle.setObjectName("homeSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(28)
        layout.addLayout(body, 1)
        body.addWidget(self._build_left_column(), 6)
        body.addWidget(self._build_right_column(), 4)

        layout.addStretch(1)
        layout.addLayout(self._build_footer())

    # --- 各区块构建 ---

    def _build_left_column(self) -> QWidget:
        column = QWidget(self)
        inner = QVBoxLayout(column)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(12)

        section = QLabel("项目出稿", column)
        section.setObjectName("sectionTitle")
        inner.addWidget(section)

        guide = QLabel(
            "从 Word (.docx) 源文档一键拆解为规范 Markdown 项目，支持自动分章与排版校验。",
            column,
        )
        guide.setObjectName("homeMuted")
        guide.setWordWrap(True)
        inner.addWidget(guide)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        new_btn = QPushButton("＋  新建项目…", column)
        new_btn.setProperty("btnRole", "primary")
        new_btn.setMinimumHeight(36)
        new_btn.clicked.connect(self._handle_new)
        open_btn = QPushButton("📁  打开项目…", column)
        open_btn.setProperty("btnRole", "secondary")
        open_btn.setMinimumHeight(36)
        open_btn.clicked.connect(self._handle_open)
        actions.addWidget(new_btn)
        actions.addWidget(open_btn)
        actions.addStretch(1)
        inner.addLayout(actions)
        self._buttons = [new_btn, open_btn]

        inner.addSpacing(6)
        recent_title = QLabel("最近项目", column)
        recent_title.setObjectName("homeSubheading")
        inner.addWidget(recent_title)

        self._recent_frame = QFrame(column)
        self._recent_layout = QVBoxLayout(self._recent_frame)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(8)
        inner.addWidget(self._recent_frame)
        inner.addStretch(1)
        return column

    def _build_right_column(self) -> QWidget:
        column = QWidget(self)
        inner = QVBoxLayout(column)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(12)

        section = QLabel("工具", column)
        section.setObjectName("sectionTitle")
        inner.addWidget(section)

        # 互转卡（核心）：拖入时整卡高亮（QSS dragOver 态）。
        self._convert_card = _ClickableCard(column)
        self._convert_card.setObjectName("convertCard")
        self._convert_card.setProperty("card", True)
        self._convert_card.clicked.connect(self._handle_convert)
        convert_layout = QVBoxLayout(self._convert_card)
        convert_layout.setContentsMargins(20, 18, 20, 18)
        convert_layout.setSpacing(8)

        convert_head = QHBoxLayout()
        convert_head.setSpacing(10)
        convert_icon = QLabel("⇄", self._convert_card)
        convert_icon.setObjectName("convertCardIcon")
        convert_head.addWidget(convert_icon)
        convert_title_box = QVBoxLayout()
        convert_title_box.setSpacing(2)
        self._convert_title = QLabel(CONVERT_CARD_TITLE, self._convert_card)
        self._convert_title.setObjectName("sectionTitle")
        convert_title_box.addWidget(self._convert_title)
        convert_sub = QLabel("多格式双向互转 · 批量处理", self._convert_card)
        convert_sub.setObjectName("homeMuted")
        convert_title_box.addWidget(convert_sub)
        convert_head.addLayout(convert_title_box, 1)
        convert_layout.addLayout(convert_head)

        self._convert_desc = QLabel(CONVERT_CARD_DESC, self._convert_card)
        self._convert_desc.setObjectName("homeMuted")
        convert_layout.addWidget(self._convert_desc)
        convert_layout.addSpacing(2)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for chip in (".docx", ".pdf", ".md", ".html", ".txt", ".xlsx", ".rtf"):
            chips.addWidget(_make_pill(chip, parent=self._convert_card))
        chips.addStretch(1)
        convert_layout.addLayout(chips)
        convert_layout.addStretch(1)
        badge = QLabel(CONVERT_CARD_BADGE, self._convert_card)
        badge.setObjectName("homeAccent")
        convert_layout.addWidget(badge)
        inner.addWidget(self._convert_card)

        # PDF 工具箱卡：可点击打开独立对话框。
        self._pdf_card = _ClickableCard(column)
        self._pdf_card.setObjectName("pdfCard")
        self._pdf_card.setProperty("card", True)
        self._pdf_card.clicked.connect(self._handle_pdf_toolbox)
        pdf_layout = QVBoxLayout(self._pdf_card)
        pdf_layout.setContentsMargins(20, 18, 20, 18)
        pdf_layout.setSpacing(8)

        pdf_head = QHBoxLayout()
        pdf_head.setSpacing(10)
        pdf_icon = QLabel("📑", self._pdf_card)
        pdf_icon.setObjectName("pdfCardIcon")
        pdf_head.addWidget(pdf_icon)
        pdf_title_box = QVBoxLayout()
        pdf_title_box.setSpacing(2)
        self._pdf_title = QLabel(PDF_TOOLBOX_CARD_TITLE, self._pdf_card)
        self._pdf_title.setObjectName("sectionTitle")
        pdf_title_box.addWidget(self._pdf_title)
        pdf_sub = QLabel("页面管理 · 安全水印 · 优化压缩", self._pdf_card)
        pdf_sub.setObjectName("homeMuted")
        pdf_title_box.addWidget(pdf_sub)
        pdf_head.addLayout(pdf_title_box, 1)
        pdf_layout.addLayout(pdf_head)

        self._pdf_desc = QLabel(PDF_TOOLBOX_CARD_DESC, self._pdf_card)
        self._pdf_desc.setObjectName("homeMuted")
        pdf_layout.addWidget(self._pdf_desc)
        pdf_layout.addSpacing(2)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for chip in ("合并", "拆分", "水印", "加密", "解密", "压缩", "页码"):
            chips.addWidget(_make_pill(chip, parent=self._pdf_card))
        chips.addStretch(1)
        pdf_layout.addLayout(chips)
        pdf_layout.addStretch(1)
        badge = QLabel(PDF_TOOLBOX_CARD_BADGE, self._pdf_card)
        badge.setObjectName("homeAccent")
        pdf_layout.addWidget(badge)
        self._placeholder_card = self._pdf_card  # 向后兼容旧属性访问
        inner.addWidget(self._pdf_card)

        inner.addStretch(1)
        return column

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        tip = QLabel("提示：文件较多时可整个文件夹拖入；旧版 .doc 仅支持转出 PDF。", self)
        tip.setObjectName("homeMuted")
        footer.addWidget(tip)
        footer.addStretch(1)
        help_link = _LinkLabel("使用说明", self)
        help_link.clicked.connect(self._handle_show_help)
        footer.addWidget(help_link)
        footer.addSpacing(10)
        about_link = _LinkLabel("关于", self)
        about_link.clicked.connect(self._handle_about)
        footer.addWidget(about_link)
        return footer

    # --- 最近项目渲染 ---

    def set_recent_projects(self, entries: List[RecentEntry], enabled: bool = True) -> None:
        """渲染最近项目卡片（最多 5 条）；无条目时显示空态文案，两者互斥。"""
        for card in self._recent_cards:
            card.deleteLater()
        self._recent_cards = []
        if self._empty_label is not None:
            self._empty_label.deleteLater()
            self._empty_label = None
        if not entries:
            self._empty_label = QLabel(RECENT_EMPTY_TEXT, self._recent_frame)
            self._empty_label.setObjectName("homeMuted")
            self._recent_layout.addWidget(self._empty_label)
            return
        for entry in entries[:MAX_VISIBLE_RECENT]:
            card = self._build_recent_card(entry)
            card.setEnabled(enabled and self._enabled)
            self._recent_layout.addWidget(card)
            self._recent_cards.append(card)

    def _build_recent_card(self, entry: RecentEntry) -> QFrame:
        card = _ClickableCard(self._recent_frame)
        card.setObjectName("recentCard")
        card.setProperty("card", True)
        card.setToolTip(entry.path)
        card.clicked.connect(lambda path=entry.path: self._handle_recent(path))
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)

        file_icon = QLabel("📄", card)
        file_icon.setObjectName("recentFileIcon")
        row.addWidget(file_icon)

        column = QVBoxLayout()
        column.setSpacing(4)
        name = QLabel(entry.document_name or entry.name, card)
        name.setObjectName("homeSubheading")
        column.addWidget(name)
        meta = _format_last_opened(entry.last_opened)
        meta_text = entry.path if not meta else "{0}   ·   {1}".format(meta, entry.path)
        meta_label = QLabel(meta_text, card)
        meta_label.setObjectName("homeMuted")
        column.addWidget(meta_label)
        row.addLayout(column, 1)
        badge_text = _type_badge_label(entry.document_type)
        if badge_text:
            row.addWidget(_make_pill(badge_text, muted=True, parent=card))
        hint = QLabel("打开 →", card)
        hint.setObjectName("homeAccent")
        row.addWidget(hint)
        return card

    def set_enabled(self, enabled: bool) -> None:
        """任务运行中冻结本页全部可点击入口。"""
        self._enabled = bool(enabled)
        for button in self._buttons:
            button.setEnabled(self._enabled)
        for card in self._recent_cards:
            card.setEnabled(self._enabled)
        self._convert_card.setEnabled(self._enabled)
        if hasattr(self, "_pdf_card"):
            self._pdf_card.setEnabled(self._enabled)

    # --- 拖放（整页接收，高亮互转卡） ---

    def set_drag_over(self, active: bool) -> None:
        """拖放悬停高亮：互转卡虚线切实线 + accent 浅底 + 文案切换。"""
        if self._drag_over == active:
            return
        self._drag_over = active
        self._convert_card.setProperty("dragOver", "true" if active else "false")
        style = self._convert_card.style()
        style.unpolish(self._convert_card)
        style.polish(self._convert_card)
        self._convert_title.setText(CONVERT_DRAG_TITLE if active else CONVERT_CARD_TITLE)
        self._convert_desc.setText(CONVERT_DRAG_DESC if active else CONVERT_CARD_DESC)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.set_drag_over(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.set_drag_over(False)
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths and self._on_drop_files is not None:
            event.acceptProposedAction()
            self._on_drop_files(paths)

    # --- 事件转发 ---

    def _handle_new(self) -> None:
        if self._on_new_project is not None:
            self._on_new_project()

    def _handle_open(self) -> None:
        if self._on_open_project is not None:
            self._on_open_project()

    def _handle_recent(self, path: str) -> None:
        if self._on_open_recent is not None:
            self._on_open_recent(path)

    def _handle_convert(self) -> None:
        if self._on_convert is not None:
            self._on_convert()

    def _handle_pdf_toolbox(self) -> None:
        if self._on_pdf_toolbox is not None:
            self._on_pdf_toolbox()

    def _handle_show_help(self) -> None:
        if self._on_show_help is not None:
            self._on_show_help()

    def _handle_about(self) -> None:
        if self._on_about is not None:
            self._on_about()
