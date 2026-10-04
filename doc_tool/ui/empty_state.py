# -*- coding: utf-8 -*-
"""首页任务页：「项目出稿 + 常用工具」双栏（无项目时显示，沿用 EmptyState 名）。

自上而下：
- 标题行（品牌徽标 + 产品定位 + 版本徽章）与副标题；
- Docs-as-Code 3 步流水线引导条（导入拆解 → 协同撰写 → 规范出稿）与全局命令面板快捷入口；
- 主体双栏（左 6 右 4）：
  * 左栏「项目出稿」：新建/打开项目核心入口、最近项目列表（支持快速过滤、在文件夹定位、复制路径、从列表移除、失效检测；无条目时显示空态引导），同时是主区拖放区（拖入即走导入建项路由）；
  * 右栏：文档互转卡片（自身接收拖放、多格式独立直达胶囊）与 PDF 工具箱卡片（支持常用离线工具直达胶囊）；
- 底部锚定行：离线安全提示、使用说明、快捷键速查与关于。

整页支持滚动与响应式自适应，防范小屏幕截断；全部样式走 styles.py 全局 QSS 规则。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
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
    "把 Word / PDF / Markdown / HTML 文件拖到本卡片上即可互转；\n"
    "拖到左侧「项目出稿」区则按导入建项处理。也可点击挑选文件批量处理。"
)

# 首页两个拖放区语义（用户可见文案，与 EmptyState.drop_zone_for 判定一致）：
# 左侧「项目出稿」区 = 导入建项路由（与「新建项目…」同一服务）；
# 右侧互转卡 = 文档互转路由。互转卡自身接收拖放，两类拖放不再混淆。
INTAKE_DROP_TITLE = "项目出稿（拖入即导入建项）"
INTAKE_DROP_DESC = (
    "把 Word (.docx/.doc) 或 Markdown 文件拖到这里："
    "DOCX 逐份进入导入向导，Markdown 按列表顺序组稿成一份项目。"
)
INTAKE_DROP_HINT = "拖入此处 = 导入建项（等同「新建项目…」）"
INTAKE_DRAG_HINT = "松开鼠标，按导入建项处理这些文件"

#: 拖放路由标识：主区导入建项 / 互转卡格式转换。
DROP_ZONE_INTAKE = "intake"
DROP_ZONE_CONVERT = "convert"
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
        on_relocate_recent: Optional[Callable[[str, str], None]] = None,
        on_convert: Optional[Callable[[Optional[str]], None]] = None,
        on_pdf_toolbox: Optional[Callable[[Optional[str]], None]] = None,
        on_drop_files: Optional[Callable[[List[Path]], None]] = None,
        on_drop_intake: Optional[Callable[[List[Path]], None]] = None,
        on_drop_convert: Optional[Callable[[List[Path]], None]] = None,
        on_toggle_pin: Optional[Callable[[str, bool], None]] = None,
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
        self._on_relocate_recent = on_relocate_recent
        self._on_convert = on_convert
        self._on_pdf_toolbox = on_pdf_toolbox
        self._on_drop_files = on_drop_files
        # 主区「项目出稿」拖放 = 导入建项路由；互转卡拖放 = 格式转换路由。
        # ``on_drop_files`` 保留为两条路由都未接线时的兜底（旧调用方兼容）。
        self._on_toggle_pin = on_toggle_pin
        self._on_drop_intake = on_drop_intake
        self._on_drop_convert = on_drop_convert
        if self._on_drop_convert is None and self._on_drop_files is not None:
            self._on_drop_convert = on_drop_files
        if self._on_drop_intake is None and on_drop_intake is None and on_drop_files is not None \
                and on_drop_convert is None:
            self._on_drop_intake = on_drop_files
        self._on_show_help = on_show_help
        self._on_about = on_about
        self._on_command_palette = on_command_palette
        self._enabled = True
        self._drag_over = False
        self._buttons: List[QPushButton] = []
        self._recent_cards: List[QFrame] = []
        self._empty_label: Optional[QLabel] = None
        self._all_recent_entries: List[RecentEntry] = []
        self._type_filter = ""

        # 仅首页视图接收拖放（工作台视图不设置）。整页仍接收拖放：
        # 实际路由按拖放落点判定（见 ``drop_zone_for``）。
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
        # 本区既是「项目出稿」入口，也是首页主区拖放区：拖入有效 DOCX/Markdown
        # 走与「新建项目…」按钮完全相同的导入建项服务（互转卡仍独立接收拖放）。
        column = _ClickableCard(self._content_widget)
        column.setObjectName("intakeDropCard")
        column.setProperty("card", True)
        column.setToolTip(INTAKE_DROP_HINT)
        self._intake_card = column
        inner = QVBoxLayout(column)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(12)

        section = QLabel("项目出稿（拖入即导入建项）", column)
        section.setObjectName("sectionTitle")
        inner.addWidget(section)

        guide = QLabel(
            "从 Word (.docx) 源文档一键拆解为规范 Markdown 项目，支持自动分章与排版校验。",
            column,
        )
        guide.setObjectName("homeMuted")
        guide.setWordWrap(True)
        inner.addWidget(guide)

        # 拖放语义提示：普通拖放高亮时切换为「松开即导入建项」，与互转卡文案区分。
        self._intake_drop_hint = QLabel(INTAKE_DROP_HINT, column)
        self._intake_drop_hint.setObjectName("homeMuted")
        self._intake_drop_hint.setWordWrap(True)
        inner.addWidget(self._intake_drop_hint)

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
        self._search_input.setPlaceholderText("搜索名称或路径…")
        self._search_input.setClearButtonEnabled(True)
        # 搜索与类型筛选走同一实现：任一变化都同时作用（UI2-B 2.2）。
        self._search_input.textChanged.connect(self._apply_recent_filter)
        self._search_input.setVisible(False)
        recent_header.addWidget(self._search_input, 1)

        # UI2-B 2.2：类型筛选与已有搜索组合作用。
        self._type_combo = QComboBox(column)
        self._type_combo.setObjectName("recentTypeFilter")
        self._type_combo.addItem("全部类型", "")
        for type_key, label in (("requirement", "需求"), ("design", "设计"), ("general", "通用")):
            self._type_combo.addItem(label, type_key)
        self._type_combo.setToolTip("按文档类型筛选最近项目（与搜索组合生效）")
        self._type_combo.currentIndexChanged.connect(self._on_type_filter_changed)
        recent_header.addWidget(self._type_combo)

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

        # UI2-B 2.2：固定项置顶；其余保持最近打开顺序。
        ordered = sorted(
            self._all_recent_entries[:10],
            key=lambda item: (0 if getattr(item, "pinned", False) else 1,),
        )
        for idx, entry in enumerate(ordered):
            card = self._build_recent_card(entry)
            card.setEnabled(enabled and self._enabled)
            card.setVisible(idx < MAX_VISIBLE_RECENT)
            self._recent_layout.addWidget(card)
            self._recent_cards.append(card)
        self._apply_recent_filter()

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

        # 卡片只显示名称、类型、最近打开时间与当前位置（目录名）；
        # 技术指纹与完整路径进入提示/右键，不在卡片里堆叠。
        meta = _format_last_opened(entry.last_opened)
        location = Path(entry.path).name or entry.path
        meta_text = "{0}   ·   {1}".format(meta, location) if meta else location
        meta_label = QLabel(meta_text, card)
        meta_label.setObjectName("homeMuted")
        meta_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta_label.setMinimumWidth(60)
        meta_label.setToolTip("完整路径：{0}".format(entry.path))
        column.addWidget(meta_label)
        row.addLayout(column, 1)

        # 路径存在性校验
        exists = Path(entry.path).is_dir()
        if not exists:
            card.setToolTip(
                "项目目录已移动或删除：{0}\n点击 🔍 可重新定位，点击 ✕ 可从列表移除".format(entry.path)
            )
            invalid_pill = _make_pill("路径失效", muted=True, parent=card)
            invalid_pill.setProperty("pillTone", "warning")
            invalid_pill.setToolTip("项目目录已移动或删除，可重新定位或从列表移除")
            row.addWidget(invalid_pill)
        else:
            card.setToolTip(entry.path)

        badge_text = _type_badge_label(entry.document_type)
        if badge_text:
            row.addWidget(_make_pill(badge_text, muted=True, parent=card))

        # 固定/取消固定（UI2-B 2.2）：只改个人记录，不移动/删除工程。
        pin_btn = QPushButton("📌" if entry.pinned else "☆", card)
        pin_btn.setProperty("recentAction", "pin")
        pin_btn.setObjectName("recentPinBtn")
        pin_btn.setText("已固定" if entry.pinned else "固定")
        pin_btn.setToolTip(
            "取消固定（仅修改个人最近记录）" if entry.pinned
            else "固定到列表顶部（仅修改个人最近记录，不影响工程）"
        )
        pin_btn.setMinimumWidth(48)
        pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pin_btn.clicked.connect(
            lambda _=False, p=entry.path, on=not entry.pinned: self._handle_toggle_pin(p, on)
        )
        row.addWidget(pin_btn)

        # 快捷辅助操作：定位 / 复制路径 / 从列表移除（图标后带文字兜底，
        # 环境缺字形时动作仍可理解）。
        locate_btn = QPushButton("定位" if exists else "重新定位", card)
        locate_btn.setProperty("recentAction", "true")
        locate_btn.setMinimumWidth(56 if exists else 72)
        locate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if exists:
            locate_btn.setToolTip("在文件资源管理器中定位目录")
            locate_btn.clicked.connect(lambda _=False, p=entry.path: self._handle_locate_project(p))
        else:
            # 规范 R9：失效条目要能“重新定位”，而不是只能移除（第二十七轮规范覆盖审计）
            locate_btn.setProperty("recentAction", "relocate")
            locate_btn.setToolTip("项目已移动：重新选择它的目录")
            locate_btn.clicked.connect(
                lambda _=False, p=entry.path: self._handle_relocate_project(p)
            )
        row.addWidget(locate_btn)

        copy_btn = QPushButton("复制路径", card)
        copy_btn.setProperty("recentAction", "true")
        copy_btn.setToolTip("复制项目绝对路径")
        copy_btn.setMinimumWidth(68)
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

    def _on_type_filter_changed(self, _index: int) -> None:
        self.set_type_filter(str(self._type_combo.currentData() or ""))

    def _filter_recent_cards(self, query: str) -> None:
        """兼容入口：搜索文本变化即走统一的搜索+类型过滤。"""
        if hasattr(self, "_search_input") and self._search_input.text() != query:
            self._search_input.setText(query)
        self._apply_recent_filter()

    def _legacy_filter_recent_cards(self, query: str) -> None:
        """旧实现保留为参考路径（当前不再接线）。"""
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

    def _handle_relocate_project(self, path: str) -> None:
        """失效的最近项目：让用户重新选择目录（必须仍是项目）。"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        start_dir = str(Path(path).parent) if path else ""
        chosen = QFileDialog.getExistingDirectory(self, "重新定位项目目录", start_dir)
        if not chosen:
            return
        candidate = Path(chosen)
        manifest_path = candidate / "project.yml"
        if not manifest_path.is_file():
            QMessageBox.information(
                self, "不是项目目录",
                "所选目录缺少 project.yml，无法作为项目重新定位：\n{0}".format(chosen),
            )
            return
        if self._on_relocate_recent is not None:
            self._on_relocate_recent(str(path), str(candidate))
        else:
            QToolTip.showText(QCursor.pos(), "已选择新目录：{0}".format(chosen))

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
        """从最近列表中移除该条目（只改个人记录，不删除工程）。"""
        if self._on_remove_recent is not None:
            self._on_remove_recent(path)

    def _handle_toggle_pin(self, path: str, pinned: bool) -> None:
        """固定/取消固定：只改个人最近记录，不移动或删除工程。"""
        if self._on_toggle_pin is not None:
            self._on_toggle_pin(path, bool(pinned))
        else:
            try:
                from doc_tool.application.project_service import set_recent_pinned

                set_recent_pinned(path, bool(pinned))
                self.set_recent_projects(
                    [
                        item for item in self._all_recent_entries
                    ],
                    enabled=self._enabled,
                )
            except Exception:  # noqa: BLE001 - 固定失败不影响其他入口
                QToolTip.showText(QCursor.pos(), "固定记录未保存")

    # --- 过滤（搜索 + 类型） ---

    def set_type_filter(self, document_type: str) -> None:
        """设置类型筛选与已有搜索组合作用；空值表示全部类型。"""
        self._type_filter = str(document_type or "")
        self._apply_recent_filter()

    def current_type_filter(self) -> str:
        return getattr(self, "_type_filter", "")

    def _apply_recent_filter(self) -> None:
        """把搜索文本与类型筛选一起作用到卡片可见性。"""
        query = self._search_input.text().strip().lower() if hasattr(self, "_search_input") else ""
        type_filter = getattr(self, "_type_filter", "")
        matched = 0
        for card in self._recent_cards:
            entry = getattr(card, "_entry_data", None)
            if entry is None:
                continue
            name = (entry.document_name or entry.name or "").lower()
            path = (entry.path or "").lower()
            text_ok = (not query) or (query in name or query in path)
            type_ok = (not type_filter) or (entry.document_type == type_filter)
            visible = text_ok and type_ok and matched < MAX_VISIBLE_RECENT
            card.setVisible(visible)
            if text_ok and type_ok:
                matched += 1
        has_filter = bool(query or type_filter)
        if has_filter and matched == 0:
            if getattr(self, "_search_empty_label", None) is None:
                self._search_empty_label = QLabel(self._recent_frame)
                self._search_empty_label.setObjectName("homeMuted")
                self._search_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._recent_layout.addWidget(self._search_empty_label)
            detail = []
            if query:
                detail.append("关键词「{0}」".format(query))
            if type_filter:
                detail.append("类型「{0}」".format(_type_badge_label(type_filter) or type_filter))
            self._search_empty_label.setText(
                "没有匹配的最近项目（{0}）：可清除筛选或改用「导入 / 新建项目」。".format(
                    "，".join(detail)
                )
            )
            self._search_empty_label.setVisible(True)
        elif getattr(self, "_search_empty_label", None) is not None:
            self._search_empty_label.setVisible(False)

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
        if hasattr(self, "_intake_card"):
            self._intake_card.setEnabled(self._enabled)

    # --- 拖放（整页接收；按落点区分导入建项 / 互转） ---

    def _reposition_widget(self, widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def set_drag_over(self, active: bool) -> None:
        """拖放悬停高亮：两个拖放区各自给出准确文案与高亮。

        整页接收拖放，所以悬停时两个目标都进入可投放态：左侧「项目出稿」
        区提示按导入建项处理，互转卡保持原有虚线高亮与文案。
        """
        if self._drag_over == active:
            return
        self._drag_over = active
        for card in (self._intake_card, self._convert_card):
            card.setProperty("dragOver", "true" if active else "false")
            self._reposition_widget(card)
        self._convert_title.setText(CONVERT_DRAG_TITLE if active else CONVERT_CARD_TITLE)
        self._convert_desc.setText(CONVERT_DRAG_DESC if active else CONVERT_CARD_DESC)
        hint = getattr(self, "_intake_drop_hint", None)
        if hint is not None:
            hint.setText(INTAKE_DRAG_HINT if active else INTAKE_DROP_HINT)

    def drop_zone_for(self, event) -> str:
        """判定拖放落点属于哪个路由：``DROP_ZONE_INTAKE`` / ``DROP_ZONE_CONVERT``。

        判定顺序（与用户可见文案一致）：
        1. 真实 Qt 拖放事件：按鼠标位置取命中控件，落在左侧「项目出稿」区
           即导入建项，其余（互转卡）走转换；
        2. 事件既无全局位置也无法命中控件时（离屏/桩事件），退回「互转」
           语义，保持既有调用方的默认行为不变。
        """
        point = None
        getter = getattr(event, "position", None)
        if callable(getter):
            try:
                # QDropEvent.position() 相对接收控件；需要换算成屏幕坐标才能和
                # 两个拖放区的全局矩形比较。
                point = self.mapToGlobal(getter().toPoint())
            except Exception:  # noqa: BLE001 - 桩事件没有真实坐标
                point = None
        if point is not None:
            inside_intake = self._contains_global(self._intake_card, point)
            inside_convert = self._contains_global(self._convert_card, point)
            # 窄窗口响应式布局下两区上下相邻且可能重叠：重叠处按文档流顺序
            # 取更靠上的那个区，绝大多数布局下两者互斥、判定唯一。
            if inside_intake and inside_convert:
                intake_top = self._intake_card.mapToGlobal(self._intake_card.rect().topLeft()).y()
                convert_top = self._convert_card.mapToGlobal(self._convert_card.rect().topLeft()).y()
                return DROP_ZONE_INTAKE if intake_top <= convert_top else DROP_ZONE_CONVERT
            if inside_intake:
                return DROP_ZONE_INTAKE
            if inside_convert:
                return DROP_ZONE_CONVERT
        return DROP_ZONE_CONVERT

    def _contains_global(self, widget: QWidget, point) -> bool:
        """控件全局矩形是否包含该点（命中测试不依赖窗口层叠）。"""
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        return widget.rect().translated(top_left).contains(point)

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
        if not paths:
            return
        if self.drop_zone_for(event) == DROP_ZONE_INTAKE and self._on_drop_intake is not None:
            event.acceptProposedAction()
            self._on_drop_intake(paths)
            return
        if self._on_drop_convert is not None:
            event.acceptProposedAction()
            self._on_drop_convert(paths)
            return
        if self._on_drop_intake is not None:
            event.acceptProposedAction()
            self._on_drop_intake(paths)

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
