# -*- coding: utf-8 -*-
"""首页任务页：「项目出稿 + 常用工具」双栏（无项目时显示，沿用 EmptyState 名）。

自上而下：
- 标题行（品牌徽标 + 产品定位 + 版本徽章）与副标题；
- Docs-as-Code 3 步流水线引导条（导入拆解 → 协同撰写 → 规范出稿）与全局命令面板快捷入口；
- 主体双栏（左 6 右 4）：
  * 左栏：新建/打开项目核心入口、最近项目列表（支持快速过滤、在文件夹定位、复制路径、从列表移除、失效检测；无条目时显示空态引导）；
  * 右栏：文档互转卡片（支持拖放高亮、多格式独立直达胶囊）与 PDF 工具箱卡片（支持常用离线工具直达胶囊）；
- 底部锚定行：离线安全提示、使用说明、快捷键速查与关于。

整页支持滚动与响应式自适应，防范小屏幕截断；全部样式走 styles.py 全局 QSS 规则。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolTip,
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
PDF_TOOLBOX_CARD_BADGE = "15 项离线工具 · 批量安全处理"
RECENT_EMPTY_TEXT = "把 Word 源文档用「新建项目」导入后，会在这里列出最近项目。"


def _format_last_opened(last_opened: str) -> str:
    """把最近打开的 ISO 时间戳渲染成「N 天前打开」。"""
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


class _ClickablePill(QLabel):
    """可点击的微型操作胶囊（继承 QLabel 保持对既有查找断言与 QSS pill 规则的兼容）。"""

    clicked = Signal()

    def __init__(self, text: str, *, muted: bool = False, tooltip: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setProperty("pill", "true")
        if muted:
            self.setProperty("pillTone", "muted")
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def _make_pill(text: str, *, muted: bool = False, tooltip: str = "", parent=None) -> QLabel:
    """小圆角徽章 pill（继承 QLabel，兼顾静态展示与可选点击）。"""
    return _ClickablePill(text, muted=muted, tooltip=tooltip, parent=parent)


class _ClickableCard(QFrame):
    """整卡响应左键点击的卡片（最近项目卡 / 互转卡）。"""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _LinkLabel(QLabel):
    """底部 accent 色文字入口（使用说明 / 关于）。"""

    clicked = Signal()

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("homeAccent")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
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
        on_remove_recent: Optional[Callable[[str], None]] = None,
        on_convert: Optional[Callable[[Optional[str]], None]] = None,
        on_pdf_toolbox: Optional[Callable[[Optional[str]], None]] = None,
        on_drop_files: Optional[Callable[[List[Path]], None]] = None,
        on_show_help: Optional[Callable[[], None]] = None,
        on_about: Optional[Callable[[], None]] = None,
        on_command_palette: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("homeRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_new_project = on_new_project
        self._on_open_project = on_open_project
        self._on_open_recent = on_open_recent
        self._on_remove_recent = on_remove_recent
        self._on_convert = on_convert
        self._on_pdf_toolbox = on_pdf_toolbox
        self._on_drop_files = on_drop_files
        self._on_show_help = on_show_help
        self._on_about = on_about
        self._on_command_palette = on_command_palette
        self._enabled = True
        self._drag_over = False
        self._buttons: List[QPushButton] = []
        self._recent_cards: List[QFrame] = []
        self._empty_label: Optional[QLabel] = None
        self._all_recent_entries: List[RecentEntry] = []

        # 仅首页视图接收拖放（工作台视图不设置）。
        self.setAcceptDrops(True)

        # 外层布局：通过 QScrollArea 实现自适应防截断
        root_vbox = QVBoxLayout(self)
        root_vbox.setContentsMargins(0, 0, 0, 0)
        root_vbox.setSpacing(0)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setObjectName("homeScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._content_widget = QWidget(self._scroll_area)
        self._content_widget.setObjectName("homeContent")
        self._content_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self._content_widget)
        layout.setContentsMargins(40, 24, 40, 20)
        layout.setSpacing(10)
        self._content_layout = layout
        self._empty_box: Optional[QFrame] = None
        self._search_empty_label: Optional[QLabel] = None

        # 1. 标题行：品牌徽标 + 产品定位 + 版本徽章
        head = QHBoxLayout()
        head.setSpacing(10)
        brand = QLabel("DocTool", self._content_widget)
        brand.setObjectName("homeBrandIcon")
        head.addWidget(brand)
        title = QLabel(PRODUCT_DESCRIPTION_UI, self._content_widget)
        title.setObjectName("welcomeTitle")
        head.addWidget(title)
        self._version_badge = _make_pill(
            "v{0}".format(APP_VERSION), muted=True, parent=self._content_widget
        )
        self._version_badge.setToolTip("当前版本 v{0}".format(APP_VERSION))
        head.addWidget(self._version_badge)
        head.addStretch(1)
        layout.addLayout(head)

        subtitle = QLabel(
            "从 Word 导入成 Markdown 项目出稿；常用互转在右侧，把文件拖进窗口即可发起。",
            self._content_widget,
        )
        subtitle.setObjectName("homeSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # 2. Docs-as-Code 流水线向导条（5 秒快速理解核心作业流）
        layout.addWidget(self._build_pipeline_banner())
        layout.addSpacing(4)

        # 3. 主体双栏（左 6 右 4）
        body = QHBoxLayout()
        body.setSpacing(24)
        layout.addLayout(body, 1)
        body.addWidget(self._build_left_column(), 6)
        body.addWidget(self._build_right_column(), 4)
        self._body_layout = body

        layout.addStretch(1)
        layout.addLayout(self._build_footer())

        self._scroll_area.setWidget(self._content_widget)
        root_vbox.addWidget(self._scroll_area)

    # --- 各区块构建 ---

    def _build_pipeline_banner(self) -> QWidget:
        """Docs-as-Code 3 步流水线引导条：清晰传达从 Word 到合规出稿的闭环心智。"""
        banner = QFrame(self._content_widget)
        banner.setObjectName("pipelineBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 6, 12, 6)
        banner_layout.setSpacing(8)

        steps = [
            ("①", "导入拆解", "Word 智能分章"),
            ("②", "协同撰写", "Markdown 审查"),
            ("③", "规范出稿", "自动化合规 DOCX"),
        ]
        for i, (num, stitle, sdesc) in enumerate(steps):
            if i == 0:
                s_frame = _ClickableCard(banner)
                s_frame.setObjectName("pipelineStep1Card")
                s_frame.setProperty("pipelineStep", "true")
                s_frame.setToolTip("点击快速开始：从 Word 源文档导入并新建项目工程 (Ctrl+N)")
                s_frame.clicked.connect(self._handle_new)
            else:
                s_frame = QFrame(banner)
                s_frame.setProperty("pipelineStep", "true")
                if i == 1:
                    s_frame.setToolTip("导入或打开项目后，在工作台中编辑与审查 Markdown 文档")
                else:
                    s_frame.setToolTip("在工作台一键执行合规构建，自动刷新目录与页码出稿")

            s_box = QHBoxLayout(s_frame)
            s_box.setContentsMargins(4, 2, 4, 2)
            s_box.setSpacing(5)

            n_lbl = QLabel(num, s_frame)
            n_lbl.setObjectName("pipelineStepNum")
            s_box.addWidget(n_lbl)

            t_box = QVBoxLayout()
            t_box.setSpacing(0)
            t_lbl = QLabel(stitle, s_frame)
            t_lbl.setObjectName("pipelineStepTitle")
            d_lbl = QLabel(sdesc, s_frame)
            d_lbl.setObjectName("pipelineStepDesc")
            t_box.addWidget(t_lbl)
            t_box.addWidget(d_lbl)
            s_box.addLayout(t_box)

            banner_layout.addWidget(s_frame)

            if i < len(steps) - 1:
                arr = QLabel("➔", banner)
                arr.setObjectName("pipelineArrow")
                banner_layout.addWidget(arr)

        banner_layout.addStretch(1)

        cmd_btn = QPushButton("⌨ Ctrl+K 命令", banner)
        cmd_btn.setObjectName("pipelineCmdBtn")
        cmd_btn.setToolTip("打开全局命令面板，快速检索执行任意操作 (Ctrl+K)")
        cmd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cmd_btn.clicked.connect(self._handle_command_palette)
        banner_layout.addWidget(cmd_btn)

        return banner

    def _build_left_column(self) -> QWidget:
        column = QWidget(self._content_widget)
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
        new_btn.setToolTip("从 Word 导入并新建项目工程 (Ctrl+N)")
        new_btn.setMinimumHeight(36)
        new_btn.clicked.connect(self._handle_new)

        open_btn = QPushButton("📁  打开项目…", column)
        open_btn.setProperty("btnRole", "secondary")
        open_btn.setToolTip("打开本地已有项目工程目录 (Ctrl+O)")
        open_btn.setMinimumHeight(36)
        open_btn.clicked.connect(self._handle_open)

        actions.addWidget(new_btn)
        actions.addWidget(open_btn)
        actions.addStretch(1)
        inner.addLayout(actions)
        self._buttons = [new_btn, open_btn]

        inner.addSpacing(4)

        # 最近项目标题行 + 搜索过滤框
        recent_header = QHBoxLayout()
        recent_header.setSpacing(10)
        recent_title = QLabel("最近项目", column)
        recent_title.setObjectName("homeSubheading")
        recent_header.addWidget(recent_title)

        self._search_input = QLineEdit(column)
        self._search_input.setObjectName("recentSearchInput")
        self._search_input.setPlaceholderText("🔍 快速搜索项目…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._filter_recent_cards)
        self._search_input.setVisible(False)
        recent_header.addWidget(self._search_input, 1)

        inner.addLayout(recent_header)

        self._recent_frame = QFrame(column)
        self._recent_layout = QVBoxLayout(self._recent_frame)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(8)
        inner.addWidget(self._recent_frame)
        inner.addStretch(1)
        return column

    def _build_right_column(self) -> QWidget:
        column = QWidget(self._content_widget)
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
        convert_layout.setContentsMargins(18, 16, 18, 16)
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

        # 快捷直达胶囊（保留既有文本满足测试断言，支持点击直达指定目标格式）
        chips = QHBoxLayout()
        chips.setSpacing(6)
        formats = [
            (".docx", "docx", "点击发起：转为 Word 文档 (.docx)"),
            (".pdf", "pdf", "点击发起：转为 PDF 文件 (.pdf)"),
            (".md", "md", "点击发起：提取为 Markdown (.md)"),
            (".html", "html", "点击发起：导出为网页 (.html)"),
        ]
        for chip_text, fmt_key, tip in formats:
            pill = _ClickablePill(chip_text, tooltip=tip, parent=self._convert_card)
            pill.clicked.connect(lambda f=fmt_key: self._handle_convert(f))
            chips.addWidget(pill)
        chips.addStretch(1)
        convert_layout.addLayout(chips)
        convert_layout.addStretch(1)

        badge = QLabel(CONVERT_CARD_BADGE, self._convert_card)
        badge.setObjectName("homeAccent")
        convert_layout.addWidget(badge)
        inner.addWidget(self._convert_card)

        # PDF 工具箱卡：可点击打开独立对话框，支持快捷工具直达胶囊
        self._pdf_card = _ClickableCard(column)
        self._pdf_card.setObjectName("pdfCard")
        self._pdf_card.setProperty("card", True)
        self._pdf_card.clicked.connect(self._handle_pdf_toolbox)
        pdf_layout = QVBoxLayout(self._pdf_card)
        pdf_layout.setContentsMargins(18, 16, 18, 16)
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

        # 常用离线工具胶囊直达（保留既有文本满足测试断言）
        chips_pdf = QHBoxLayout()
        chips_pdf.setSpacing(6)
        pdf_tools = [
            ("合并", "merge", "快速打开：合并多个 PDF 文件"),
            ("拆分", "split", "快速打开：按页码拆分提取 PDF"),
            ("水印", "watermark", "快速打开：添加文本或图片水印防扩散"),
            ("加密", "encrypt", "快速打开：设置访问与操作密码"),
            ("解密", "decrypt", "快速打开：移除已有保护密码"),
            ("压缩", "compress", "快速打开：优化降低 PDF 体积"),
            ("页码", "page_numbers", "快速打开：编排与插入页码"),
        ]
        for chip_text, tool_id, tip in pdf_tools:
            pill = _ClickablePill(chip_text, tooltip=tip, parent=self._pdf_card)
            pill.clicked.connect(lambda t=tool_id: self._handle_pdf_toolbox(t))
            chips_pdf.addWidget(pill)
        chips_pdf.addStretch(1)
        pdf_layout.addLayout(chips_pdf)
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
        footer.setSpacing(12)
        tip = QLabel(
            "💡 提示：文件较多时可整个文件夹拖入；全能互转与 PDF 工具箱均为纯本地离线处理，数据零外传。",
            self._content_widget,
        )
        tip.setObjectName("homeMuted")
        tip.setWordWrap(True)
        tip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(tip, 1)

        help_link = _LinkLabel("使用说明", self._content_widget)
        help_link.clicked.connect(self._handle_show_help)
        footer.addWidget(help_link)
        footer.addSpacing(10)

        shortcut_link = _LinkLabel("快捷键", self._content_widget)
        shortcut_link.clicked.connect(self._handle_command_palette)
        footer.addWidget(shortcut_link)
        footer.addSpacing(10)

        about_link = _LinkLabel("关于", self._content_widget)
        about_link.clicked.connect(self._handle_about)
        footer.addWidget(about_link)
        return footer

    # --- 最近项目渲染与管理 ---

    def set_recent_projects(self, entries: List[RecentEntry], enabled: bool = True) -> None:
        """渲染最近项目卡片；无条目时显示空态引导，两者互斥。"""
        self._all_recent_entries = list(entries or [])
        for card in self._recent_cards:
            card.deleteLater()
        self._recent_cards = []
        if getattr(self, "_empty_box", None) is not None:
            self._empty_box.deleteLater()
            self._empty_box = None
        if self._empty_label is not None:
            self._empty_label.deleteLater()
            self._empty_label = None
        if getattr(self, "_search_empty_label", None) is not None:
            self._search_empty_label.deleteLater()
            self._search_empty_label = None

        if hasattr(self, "_search_input"):
            self._search_input.setVisible(len(self._all_recent_entries) >= 3)
            self._search_input.clear()

        if not entries:
            self._empty_box = QFrame(self._recent_frame)
            self._empty_box.setObjectName("recentEmptyBox")
            box_layout = QVBoxLayout(self._empty_box)
            box_layout.setContentsMargins(14, 12, 14, 12)
            box_layout.setSpacing(6)

            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            icon = QLabel("📂", self._empty_box)
            title = QLabel("暂无最近项目", self._empty_box)
            title.setObjectName("homeSubheading")
            title_row.addWidget(icon)
            title_row.addWidget(title)
            title_row.addStretch(1)
            box_layout.addLayout(title_row)

            self._empty_label = QLabel(RECENT_EMPTY_TEXT, self._empty_box)
            self._empty_label.setObjectName("homeMuted")
            self._empty_label.setWordWrap(True)
            box_layout.addWidget(self._empty_label)

            btn = QPushButton("＋  导入首个文档…", self._empty_box)
            btn.setProperty("btnRole", "secondary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._handle_new)
            box_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

            self._recent_layout.addWidget(self._empty_box)
            return

        # 实例化全部条目卡片（最多 10 条，默认展示前 MAX_VISIBLE_RECENT 条）
        for idx, entry in enumerate(self._all_recent_entries[:10]):
            card = self._build_recent_card(entry)
            card.setEnabled(enabled and self._enabled)
            card.setVisible(idx < MAX_VISIBLE_RECENT)
            self._recent_layout.addWidget(card)
            self._recent_cards.append(card)

    def _build_recent_card(self, entry: RecentEntry) -> QFrame:
        card = _ClickableCard(self._recent_frame)
        card.setObjectName("recentCard")
        card.setProperty("card", True)
        card.clicked.connect(lambda path=entry.path: self._handle_recent(path))
        card._entry_data = entry

        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(8)

        file_icon = QLabel("📄", card)
        file_icon.setObjectName("recentFileIcon")
        row.addWidget(file_icon)

        column = QVBoxLayout()
        column.setSpacing(2)
        name = QLabel(entry.document_name or entry.name, card)
        name.setObjectName("homeSubheading")
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name.setMinimumWidth(60)
        column.addWidget(name)

        meta = _format_last_opened(entry.last_opened)
        meta_text = entry.path if not meta else "{0}   ·   {1}".format(meta, entry.path)
        meta_label = QLabel(meta_text, card)
        meta_label.setObjectName("homeMuted")
        meta_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta_label.setMinimumWidth(60)
        column.addWidget(meta_label)
        row.addLayout(column, 1)

        # 路径存在性校验
        exists = Path(entry.path).is_dir()
        if not exists:
            card.setToolTip("项目目录已移动或删除：{0}\n点击 ✕ 可直接从列表移除".format(entry.path))
            invalid_pill = _make_pill("路径失效", muted=True, parent=card)
            invalid_pill.setProperty("pillTone", "warning")
            invalid_pill.setToolTip("项目目录已移动或删除，点击 ✕ 可直接从列表移除")
            row.addWidget(invalid_pill)
        else:
            card.setToolTip(entry.path)

        badge_text = _type_badge_label(entry.document_type)
        if badge_text:
            row.addWidget(_make_pill(badge_text, muted=True, parent=card))

        # 快捷辅助操作：定位 / 复制路径 / 从列表移除 (固定小尺寸)
        locate_btn = QPushButton("📁", card)
        locate_btn.setProperty("recentAction", "true")
        locate_btn.setFixedSize(26, 24)
        locate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if exists:
            locate_btn.setToolTip("在文件资源管理器中定位目录")
            locate_btn.clicked.connect(lambda _=False, p=entry.path: self._handle_locate_project(p))
        else:
            locate_btn.setEnabled(False)
            locate_btn.setToolTip("目录不存在或已移动，无法在资源管理器中定位")
        row.addWidget(locate_btn)

        copy_btn = QPushButton("📋", card)
        copy_btn.setProperty("recentAction", "true")
        copy_btn.setToolTip("复制项目绝对路径")
        copy_btn.setFixedSize(26, 24)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(lambda _=False, p=entry.path, b=copy_btn: self._handle_copy_path(p, b))
        row.addWidget(copy_btn)

        remove_btn = QPushButton("✕", card)
        remove_btn.setObjectName("recentRemoveBtn")
        remove_btn.setProperty("recentAction", "remove")
        remove_btn.setToolTip("从最近项目列表中移除")
        remove_btn.setFixedSize(26, 24)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(lambda _=False, p=entry.path: self._handle_remove_recent(p))
        row.addWidget(remove_btn)

        hint = QLabel("打开 →", card)
        hint.setObjectName("homeAccent")
        row.addWidget(hint)
        return card

    def _filter_recent_cards(self, query: str) -> None:
        """最近项目输入过滤：支持实时搜索全量历史，并呈现未找到空态反馈。"""
        q = query.strip().lower()
        if not q:
            if getattr(self, "_search_empty_label", None) is not None:
                self._search_empty_label.setVisible(False)
            for idx, card in enumerate(self._recent_cards):
                card.setVisible(idx < MAX_VISIBLE_RECENT)
            return

        matched_count = 0
        for card in self._recent_cards:
            entry = getattr(card, "_entry_data", None)
            if not entry:
                continue
            name = (entry.document_name or entry.name or "").lower()
            path = (entry.path or "").lower()
            matched = (q in name or q in path)
            card.setVisible(matched)
            if matched:
                matched_count += 1

        if matched_count == 0:
            if getattr(self, "_search_empty_label", None) is None:
                self._search_empty_label = QLabel(self._recent_frame)
                self._search_empty_label.setObjectName("homeMuted")
                self._search_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._recent_layout.addWidget(self._search_empty_label)
            self._search_empty_label.setText("未找到与「{0}」匹配的最近项目".format(query.strip()))
            self._search_empty_label.setVisible(True)
        else:
            if getattr(self, "_search_empty_label", None) is not None:
                self._search_empty_label.setVisible(False)

    def _handle_locate_project(self, path: str) -> None:
        """在文件资源管理器中打开项目目录。"""
        if not path or not path.strip():
            return
        p = Path(path)
        if p.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        elif p.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))
        else:
            QToolTip.showText(QCursor.pos(), "项目目录已移动或删除，无法在资源管理器中定位")

    def _handle_copy_path(self, path: str, btn: QPushButton) -> None:
        """复制项目路径到剪贴板并提示。"""
        if not path:
            return
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard:
                clipboard.setText(path)
                QToolTip.showText(btn.mapToGlobal(btn.rect().center()), "路径已复制到剪贴板")
        except Exception:
            pass

    def _handle_remove_recent(self, path: str) -> None:
        """从最近列表中移除该条目。"""
        if self._on_remove_recent is not None:
            self._on_remove_recent(path)

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

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.set_drag_over(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
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

    def _handle_convert(self, target_format: Optional[str] = None) -> None:
        if self._on_convert is not None:
            try:
                self._on_convert(target_format)
            except TypeError:
                self._on_convert()

    def _handle_pdf_toolbox(self, tool_id: Optional[str] = None) -> None:
        if self._on_pdf_toolbox is not None:
            try:
                self._on_pdf_toolbox(tool_id)
            except TypeError:
                self._on_pdf_toolbox()

    def _handle_show_help(self) -> None:
        if self._on_show_help is not None:
            self._on_show_help()

    def _handle_about(self) -> None:
        if self._on_about is not None:
            self._on_about()

    def _handle_command_palette(self) -> None:
        if self._on_command_palette is not None:
            self._on_command_palette()
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_responsive_layout(event.size().width())

    def _apply_responsive_layout(self, width: int) -> None:
        """根据当前宽度响应式自适应单栏/双栏与边距。"""
        if hasattr(self, "_body_layout") and self._body_layout is not None:
            if width < 768:
                self._body_layout.setDirection(QBoxLayout.Direction.TopToBottom)
                if hasattr(self, "_content_layout") and self._content_layout is not None:
                    self._content_layout.setContentsMargins(18, 16, 18, 16)
            else:
                self._body_layout.setDirection(QBoxLayout.Direction.LeftToRight)
                if hasattr(self, "_content_layout") and self._content_layout is not None:
                    self._content_layout.setContentsMargins(40, 24, 40, 20)
