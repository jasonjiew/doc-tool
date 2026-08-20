# -*- coding: utf-8 -*-
"""集中 QSS 主题与 Qt 原生高 DPI。

浅色为默认主题，提供深色切换入口（``toggle_theme``）。语义色沿用
``SEMANTIC_COLORS``；状态含义始终由文字表达，颜色只是辅助通道。

高 DPI 由 Qt 6 原生处理（默认开启 per-monitor 缩放），不再依赖
``shcore.SetProcessDpiAwareness`` hack——``setup_high_dpi`` 保留为
空操作以兼容旧调用与既有测试。

控件层级通过动态属性选择器表达：
- ``QPushButton[btnRole=primary|secondary|compact]``
- ``QLabel[statusTone=neutral|success|warning|failure]``
"""

from __future__ import annotations

import os

from doc_tool.resources import resource_path

# --- 字体层级（微软雅黑中文字体栈，等宽回退 Consolas） ---
# 注意：QSS 的 px 是物理像素、不随系统显示缩放；用 pt（点）才会按 DPI 缩放。
FONT_FAMILY = "Microsoft YaHei UI"
FONT_FAMILY_MONO = "Consolas"
FONT_BODY = 10
FONT_SMALL = 9
FONT_HEADING = 12
FONT_TITLE = 16

# --- 标准间距（逻辑像素） ---
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 20

# --- 语义色（浅色主题） ---
SEMANTIC_COLORS = {
    "neutral": "#4b5563",
    "success": "#176b3a",
    "warning": "#8a5a00",
    "failure": "#a12622",
}

# --- 语义色（深色主题） ---
SEMANTIC_COLORS_DARK = {
    "neutral": "#9ca3af",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "failure": "#f87171",
}

# 浅色主题面板色板
_LIGHT = {
    "window": "#f5f6f8",
    "panel": "#ffffff",
    "panel_alt": "#f0f1f4",
    "border": "#d5d8dd",
    "text": "#1f2328",
    "text_muted": "#57606a",
    "text_on_accent": "#ffffff",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_press": "#1e40af",
    "selection_bg": "#dbeafe",
    "selection_fg": "#1f2328",
    "input_bg": "#ffffff",
    "disabled_text": "#9ca3af",
    "running_hl": "#eff6ff",
}

# 深色主题面板色板
_DARK = {
    "window": "#1e1f24",
    "panel": "#26272e",
    "panel_alt": "#2c2d35",
    "border": "#3a3b44",
    "text": "#e5e7eb",
    "text_muted": "#9ca3af",
    "text_on_accent": "#ffffff",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "accent_press": "#1d4ed8",
    "selection_bg": "#2b3a5a",
    "selection_fg": "#e5e7eb",
    "input_bg": "#1b1c21",
    "disabled_text": "#6b7280",
    "running_hl": "#26334a",
}


def _font_rule(pt: int, bold: bool = False) -> str:
    # 用 pt 而非 px：px 是物理像素不随 DPI 缩放，pt 会随系统显示缩放。
    return 'font-family: "{0}", "Microsoft YaHei", "PingFang SC", sans-serif;' \
        ' font-size: {1}pt;'.format(FONT_FAMILY, pt) + (
            " font-weight: 600;" if bold else ""
        )


def build_qss(dark: bool = False) -> str:
    """构建整套 QSS 主题字符串（浅色默认 / 深色可切换）。"""
    c = _DARK if dark else _LIGHT
    sem = SEMANTIC_COLORS_DARK if dark else SEMANTIC_COLORS
    running_hl = c["running_hl"]

    tone_rules = []
    for tone, color in sem.items():
        tone_rules.append(
            'QLabel[statusTone="{0}"], QStatusBar QLabel[statusTone="{0}"]'
            " {{ color: {1}; }}".format(tone, color)
        )
    tone_qss = "\n".join(tone_rules)

    return """
QWidget {{ {font_body} color: {text}; }}
QMainWindow, QDialog, QWizard {{ background: {window}; }}
QWidget[card="true"] {{ background: {panel}; border: 1px solid {border}; border-radius: 6px; }}

/* --- 菜单栏 / 菜单 --- */
QMenuBar {{ {font_body} background: {panel}; border-bottom: 1px solid {border}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {selection_bg}; color: {selection_fg}; border-radius: 4px; }}
QMenu {{ {font_body} background: {panel}; border: 1px solid {border}; }}
QMenu::item {{ padding: 5px 22px; background: transparent; }}
QMenu::item:selected {{ background: {selection_bg}; color: {selection_fg}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

/* --- 状态栏 --- */
QStatusBar {{ {font_small} background: {panel_alt}; border-top: 1px solid {border}; color: {text_muted}; }}
QStatusBar::item {{ border: none; }}

/* --- 顶部项目条 --- */
QToolBar#projectBar {{ background: {panel}; border-bottom: 1px solid {border}; spacing: 8px; padding: 4px 8px; }}
QToolBar#projectBar QLabel {{ color: {text}; }}

/* --- 按钮层级 --- */
QPushButton {{ {font_body} background: {panel_alt}; border: 1px solid {border}; border-radius: 4px; padding: 5px 14px; }}
QPushButton:hover {{ background: {panel}; border-color: {accent}; }}
QPushButton:pressed {{ background: {accent_press}; color: {text_on_accent}; }}
QPushButton:disabled {{ color: {disabled_text}; background: {panel_alt}; border-color: {border}; }}

QPushButton[btnRole="primary"] {{ background: {accent}; color: {text_on_accent}; border: 1px solid {accent}; font-weight: 600; }}
QPushButton[btnRole="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[btnRole="primary"]:pressed {{ background: {accent_press}; }}
QPushButton[btnRole="primary"]:disabled {{ background: {disabled_text}; color: {text_on_accent}; border-color: {disabled_text}; }}

QPushButton[btnRole="secondary"] {{ padding: 4px 12px; }}
QPushButton[btnRole="compact"] {{ padding: 3px 9px; {font_small} }}

/* --- 输入控件 --- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {{ {font_body} background: {input_bg}; border: 1px solid {border}; border-radius: 4px; padding: 3px 6px; selection-background-color: {accent}; selection-color: {text_on_accent}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{ border-color: {accent}; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{ color: {disabled_text}; background: {panel_alt}; }}
QComboBox {{ {font_body} background: {input_bg}; border: 1px solid {border}; border-radius: 4px; padding: 3px 8px; }}
QComboBox:focus {{ border-color: {accent}; }}
QComboBox QAbstractItemView {{ background: {panel}; border: 1px solid {border}; selection-background-color: {selection_bg}; selection-color: {selection_fg}; }}
QCheckBox, QRadioButton {{ {font_body} background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}

/* --- 树 / 列表 / 表格 --- */
QTreeView, QListView, QTreeWidget, QTableWidget, QTableView {{ {font_body} background: {panel}; alternate-background-color: {panel_alt}; border: 1px solid {border}; }}
QTreeView::item, QListView::item, QTreeWidget::item {{ padding: 2px 4px; }}
QTreeView::item:hover, QListView::item:hover, QTreeWidget::item:hover {{ background: {selection_bg}; }}
QTreeView::item:selected, QListView::item:selected, QTreeWidget::item:selected, QTableView::item:selected {{ background: {selection_bg}; color: {selection_fg}; }}
QHeaderView::section {{ {font_small} background: {panel_alt}; color: {text_muted}; border: none; border-right: 1px solid {border}; border-bottom: 1px solid {border}; padding: 3px 6px; }}

/* --- 步骤清单（右侧 Dock） --- */
QListWidget#stepList {{ background: {panel}; border: 1px solid {border}; }}
QListWidget#stepList::item {{ {font_body} padding: 5px 8px; border-bottom: 1px solid {panel_alt}; }}
QListWidget#stepList::item[stepRunning="true"] {{ background: {running_hl}; border-left: 3px solid {accent}; }}

/* --- 日志 / 结果卡片 --- */
QPlainTextEdit#logView {{ font-family: "{mono}"; font-size: {font_small_pt}pt; background: {input_bg}; }}
QFrame[cardClass="result"] {{ background: {panel}; border: 1px solid {border}; border-radius: 6px; }}
QFrame[cardClass="resultSuccess"] {{ background: {panel}; border: 1px solid {success}; border-radius: 6px; }}
QFrame[cardClass="resultFailure"] {{ background: {panel}; border: 1px solid {failure}; border-radius: 6px; }}

/* --- 标签页 / Dock --- */
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{ {font_body} background: {panel_alt}; border: 1px solid {border}; padding: 4px 12px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QTabBar::tab:selected {{ background: {panel}; color: {text}; border-bottom-color: {panel}; }}
QTabBar::tab:hover:!selected {{ background: {panel}; }}
QDockWidget {{ {font_body} titlebar-close-icon: none; }}
QDockWidget::title {{ background: {panel_alt}; border-bottom: 1px solid {border}; padding: 4px 8px; font-weight: 600; }}
QDockWidget::close-button, QDockWidget::float-button {{ background: transparent; border: none; padding: 2px; }}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{ background: {selection_bg}; border-radius: 3px; }}

/* --- 进度条 --- */
QProgressBar {{ {font_small} background: {panel_alt}; border: 1px solid {border}; border-radius: 4px; text-align: center; color: {text}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

/* --- 滚动条 --- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {text_muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; width: 0; }}

/* --- 分割条 / 提示 --- */
QSplitter::handle {{ background: {border}; }}
QToolTip {{ {font_body} background: {panel}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}

/* --- 命名标题/语义标签（字体层级 + 辅助色） --- */
QLabel#welcomeTitle {{ {title} color: {text}; }}
QLabel#barTitle, QLabel#dockTitle, QLabel#sectionTitle {{ {font_heading} color: {text}; }}
QLabel#resultTitle, QLabel#recentTitle {{ {font_heading} color: {text}; }}
QLabel#statusMuted, QLabel#techDetail {{ {font_small} color: {text_muted}; }}
QLabel#statusWarning {{ {font_small} color: {warning}; }}

/* --- 语义色标签 --- */
{tone_rules}
""".format(
        font_body=_font_rule(FONT_BODY),
        font_small=_font_rule(FONT_SMALL),
        font_small_pt=FONT_SMALL,
        font_heading=_font_rule(FONT_HEADING, bold=True),
        title=_font_rule(FONT_TITLE, bold=True),
        mono=FONT_FAMILY_MONO,
        tone_rules=tone_qss,
        window=c["window"],
        panel=c["panel"],
        panel_alt=c["panel_alt"],
        border=c["border"],
        text=c["text"],
        text_muted=c["text_muted"],
        text_on_accent=c["text_on_accent"],
        accent=c["accent"],
        accent_hover=c["accent_hover"],
        accent_press=c["accent_press"],
        selection_bg=c["selection_bg"],
        selection_fg=c["selection_fg"],
        input_bg=c["input_bg"],
        disabled_text=c["disabled_text"],
        running_hl=running_hl,
        success=sem["success"],
        failure=sem["failure"],
        warning=sem["warning"],
    )


def apply_theme(app, dark: bool = False) -> None:
    """为 QApplication 应用统一主题。"""
    app.setStyleSheet(build_qss(dark))


def is_dark_theme(app) -> bool:
    """判断当前主题是否为深色（通过调色板亮度近似）。"""
    sheet = app.styleSheet()
    return bool(sheet and "color: #e5e7eb" in sheet)


def toggle_theme(app) -> bool:
    """切换浅色/深色主题，返回切换后的深色状态。"""
    target_dark = not is_dark_theme(app)
    apply_theme(app, dark=target_dark)
    return target_dark


def setup_high_dpi() -> None:
    """高 DPI 由 Qt 原生处理；保留为空操作以兼容旧调用与测试。"""
    return None


def set_window_icon(window) -> bool:
    """为 QWindow 设置应用图标。

    开发态从 ``doc_tool/resources/app.ico`` 读取，打包态从 PyInstaller
    资源目录读取。图标缺失时静默跳过（不阻断启动）。

    返回 True 表示图标已应用，False 表示图标不可用。
    """
    icon = resource_path("app.ico")
    if not os.path.isfile(icon):
        return False
    try:
        from PySide6.QtGui import QIcon

        window.setWindowIcon(QIcon(icon))
        return True
    except Exception:
        return False
