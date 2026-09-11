# -*- coding: utf-8 -*-
"""新建项目向导（PySide6 QWizard 深度优化版）。

优化特性：
1. 步骤 1：现代文件拖拽区（DropZone），松手即选，智能提取元数据与后台静默速诊；
2. 智能跳步：对规范文档自动跳过技术日志与冗余样式映射，直达项目信息确认；
3. 步骤 2：双栏所见即所得样式大纲树，正文首句样例回显，大纲层级实时联动与平滑降级；
4. 步骤 3：项目路径智能填充（记忆最近路径），行内重名检测与一键递增后缀，高级选项折叠收拢；
5. 步骤 4：流水线 Stepper 步进器实时进度动效与安全可逆错误恢复；
6. 步骤 5：正向反馈成就感看板，直观展示生成内容统计与一键进入工作台主按钮。
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from doc_tool.application.project_service import load_recent_projects
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


def get_default_target_parent() -> str:
    """获取默认的项目生成存放父目录（优先从最近项目中提取父目录，否则默认使用 Documents/DocToolProjects）。"""
    try:
        recent = load_recent_projects()
        for entry in recent:
            try:
                p = Path(entry.project_root).parent
                if p.exists() and p.is_dir():
                    return str(p)
            except Exception:
                pass
    except Exception:
        pass
    return str(Path.home() / "Documents" / "DocToolProjects")


class _DropZone(QFrame):
    """拖放选择区：支持鼠标拖拽放入 .docx 文件，松手即触发。"""

    clicked = Signal()
    file_dropped = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("card", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(6)

        self._icon_label = QLabel("📄", self)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._icon_label.font()
        font.setPointSize(28)
        self._icon_label.setFont(font)
        layout.addWidget(self._icon_label)

        self._title = QLabel("将 Word 文档 (.docx) 拖放到此处，或点击选择文件", self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = self._title.font()
        title_font.setPointSize(11)
        title_font.setBold(True)
        self._title.setFont(title_font)
        layout.addWidget(self._title)

        self._hint = QLabel(
            "文档将被只读复制到新建项目中进行智能拆解，源文件不会受任何修改",
            self,
        )
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setObjectName("statusMuted")
        layout.addWidget(self._hint)

    def set_drag_over(self, active: bool) -> None:
        if active:
            accent = self.palette().color(QPalette.ColorRole.Highlight).name()
            self._title.setText("松开鼠标，立即载入该 Word 文档")
            self.setStyleSheet(
                "#dropZone {{ border: 2px dashed {0}; border-radius: 8px; background: rgba(37, 99, 235, 0.05); }}".format(
                    accent
                )
            )
        else:
            self._title.setText("将 Word 文档 (.docx) 拖放到此处，或点击选择文件")
            self.setStyleSheet("")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".docx"):
                    event.acceptProposedAction()
                    self.set_drag_over(True)
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".docx"):
                    event.acceptProposedAction()
                    return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.set_drag_over(False)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path.lower().endswith(".docx"):
                    event.acceptProposedAction()
                    self.file_dropped.emit(path)
                    return
        super().dropEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _SourcePage(QWizardPage):
    """步骤 1：选择源 Word 文档（拖放区 + 静默速诊 + 智能跳步分流）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 1：选择源 Word 文档")
        self.setSubTitle("导入已有 Word 文档，系统将自动识别目录大纲并拆解为 Markdown 章节。")

        self._source_path: Optional[str] = None
        self._preflight_done = False
        self._wants_tuning = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 拖放区
        self._drop_zone = _DropZone(self)
        self._drop_zone.clicked.connect(self._browse)
        self._drop_zone.file_dropped.connect(self._on_file_selected)
        layout.addWidget(self._drop_zone)

        # 选中文件后的文件信息卡片（默认隐藏）
        self._file_card = QFrame(self)
        self._file_card.setProperty("card", True)
        self._file_card.hide()
        card_layout = QHBoxLayout(self._file_card)
        card_layout.setContentsMargins(14, 10, 14, 10)

        doc_icon = QLabel("📄", self._file_card)
        font = doc_icon.font()
        font.setPointSize(20)
        doc_icon.setFont(font)
        card_layout.addWidget(doc_icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self._file_name_label = QLabel("", self._file_card)
        fn_font = self._file_name_label.font()
        fn_font.setBold(True)
        self._file_name_label.setFont(fn_font)
        info_col.addWidget(self._file_name_label)

        self._file_meta_label = QLabel("", self._file_card)
        self._file_meta_label.setObjectName("statusMuted")
        info_col.addWidget(self._file_meta_label)
        card_layout.addLayout(info_col, 1)

        change_btn = QPushButton("更换文件…", self._file_card)
        change_btn.setProperty("btnRole", "secondary")
        change_btn.clicked.connect(self._browse)
        card_layout.addWidget(change_btn)
        layout.addWidget(self._file_card)

        # 保留 _source_entry 以满足测试兼容（隐藏）
        self._source_entry = QLineEdit(self)
        self._source_entry.setReadOnly(True)
        self._source_entry.hide()
        layout.addWidget(self._source_entry)

        # 速诊状态与诊断胶囊面板
        self._diag_box = QFrame(self)
        self._diag_box.setProperty("card", True)
        self._diag_box.hide()
        diag_layout = QVBoxLayout(self._diag_box)
        diag_layout.setContentsMargins(12, 10, 12, 10)
        diag_layout.setSpacing(8)

        self._diag_title = QLabel("正在诊断文档结构与格式特征…", self._diag_box)
        diag_layout.addWidget(self._diag_title)

        # 三颗诊断胶囊
        capsules_layout = QHBoxLayout()
        self._capsule_heading = QLabel("📊 章节结构: 分析中", self._diag_box)
        self._capsule_heading.setStyleSheet("padding: 4px 8px; border-radius: 4px; background: rgba(0,0,0,0.04);")
        self._capsule_media = QLabel("🖼 多媒体: 统计中", self._diag_box)
        self._capsule_media.setStyleSheet("padding: 4px 8px; border-radius: 4px; background: rgba(0,0,0,0.04);")
        self._capsule_fidelity = QLabel("🛡 保真度: 检测中", self._diag_box)
        self._capsule_fidelity.setStyleSheet("padding: 4px 8px; border-radius: 4px; background: rgba(0,0,0,0.04);")

        capsules_layout.addWidget(self._capsule_heading)
        capsules_layout.addWidget(self._capsule_media)
        capsules_layout.addWidget(self._capsule_fidelity)
        capsules_layout.addStretch(1)
        diag_layout.addLayout(capsules_layout)

        # 智能分流横幅与微调选项
        self._smart_banner = QLabel("", self._diag_box)
        self._smart_banner.setWordWrap(True)
        diag_layout.addWidget(self._smart_banner)

        self._tuning_check = QCheckBox("我需要手动微调段落与章节样式映射（高级选项）", self._diag_box)
        self._tuning_check.hide()
        self._tuning_check.toggled.connect(self._on_tuning_toggled)
        diag_layout.addWidget(self._tuning_check)

        layout.addWidget(self._diag_box)

        # 生成目录配置卡片（默认隐藏，选中文档后展示；未自定义时使用默认推荐路径）
        self._dir_box = QFrame(self)
        self._dir_box.setProperty("card", True)
        # self._dir_box.hide()
        dir_layout = QVBoxLayout(self._dir_box)
        dir_layout.setContentsMargins(14, 10, 14, 10)
        dir_layout.setSpacing(8)

        self._custom_dir_check = QCheckBox("自定义生成目录", self._dir_box)
        self._custom_dir_check.setChecked(False)
        self._custom_target_check = self._custom_dir_check
        self._custom_dir_check.toggled.connect(self._on_custom_dir_toggled)
        dir_layout.addWidget(self._custom_dir_check)

        self._default_path_label = QLabel("", self._dir_box)
        self._default_path_label.setObjectName("statusMuted")
        self._default_path_label.setWordWrap(True)
        self._default_path_label.setStyleSheet(
            "padding: 6px 10px; border-radius: 4px; background: rgba(0,0,0,0.03); color: #333333;"
        )
        dir_layout.addWidget(self._default_path_label)

        self._custom_dir_container = QWidget(self._dir_box)
        custom_layout = QHBoxLayout(self._custom_dir_container)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)

        target_lbl = QLabel("存放位置：", self._custom_dir_container)
        self._target_entry = QLineEdit(self._custom_dir_container)
        self._target_entry.setPlaceholderText("选择项目生成的父目录")
        self._target_entry.textChanged.connect(self._on_target_changed)
        self._browse_btn = QPushButton("浏览…", self._custom_dir_container)
        self._browse_btn.setProperty("btnRole", "secondary")
        self._browse_btn.clicked.connect(self._browse_target)

        custom_layout.addWidget(target_lbl)
        custom_layout.addWidget(self._target_entry, 1)
        custom_layout.addWidget(self._browse_btn)

        dir_layout.addWidget(self._custom_dir_container)
        self._custom_dir_container.hide()

        layout.addWidget(self._dir_box)
        layout.addStretch(1)

        default_dir = get_default_target_parent()
        self._target_entry.setText(default_dir)
        self._update_default_path_label()

    def _get_default_dir(self) -> str:
        wizard = self.wizard()
        if wizard and hasattr(wizard, "_get_default_target_parent"):
            return wizard._get_default_target_parent()
        return get_default_target_parent()

    def _update_default_path_label(self) -> None:
        wizard = self.wizard()
        default_dir = (
            wizard._default_target_parent
            if (wizard and getattr(wizard, "_default_target_parent", None))
            else self._get_default_dir()
        )
        path = self._target_entry.text().strip() or default_dir
        self._default_path_label.setText(
            f"📁 默认生成位置：{path}（系统推荐默认路径，无需手动配置）"
        )

    def _on_custom_dir_toggled(self, checked: bool) -> None:
        wizard = self.wizard()
        if wizard:
            wizard._custom_target_dir = checked
        if checked:
            self._default_path_label.hide()
            self._custom_dir_container.show()
            if not self._target_entry.text().strip():
                self._target_entry.setText(self._get_default_dir())
        else:
            self._custom_dir_container.hide()
            self._default_path_label.show()
            default_dir = (
                wizard._default_target_parent
                if (wizard and hasattr(wizard, "_default_target_parent") and wizard._default_target_parent)
                else self._get_default_dir()
            )
            self._target_entry.setText(default_dir)
            if wizard:
                wizard._target_parent = default_dir
            self._update_default_path_label()

        if wizard and hasattr(wizard, "_info_page"):
            info = wizard._info_page
            if hasattr(info, "_custom_dir_check") and info._custom_dir_check.isChecked() != checked:
                info._custom_dir_check.setChecked(checked)
            if hasattr(info, "_target_entry") and info._target_entry.text() != self._target_entry.text():
                info._target_entry.setText(self._target_entry.text())

        self.completeChanged.emit()

    def _browse_target(self) -> None:
        current = self._target_entry.text().strip() or self._get_default_dir()
        path = QFileDialog.getExistingDirectory(self, "选择存放父目录", current)
        if path:
            self._target_entry.setText(path)

    def _on_target_changed(self, text: str) -> None:
        path = text.strip()
        wizard = self.wizard()
        if wizard:
            wizard._target_parent = path
            if hasattr(wizard, "_info_page"):
                info = wizard._info_page
                if hasattr(info, "_target_entry") and info._target_entry.text() != text:
                    info._target_entry.setText(text)
        self._update_default_path_label()
        self.completeChanged.emit()

    def _browse(self) -> None:
        path = QFileDialog.getOpenFileName(
            self, "选择源 Word 文档", "", "Word 文档 (*.docx);;所有文件 (*.*)"
        )[0]
        if path:
            self._on_file_selected(path)

    def _on_file_selected(self, path: str) -> None:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return
        self._source_path = str(p)
        self._source_entry.setText(str(p))

        # 更新文件信息卡片
        self._drop_zone.hide()
        self._file_card.show()
        self._file_name_label.setText(p.name)
        size_kb = p.stat().st_size / 1024
        size_str = f"{size_kb / 1024:.2f} MB" if size_kb >= 1024 else f"{size_kb:.1f} KB"
        mod_time = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        self._file_meta_label.setText(f"文件大小: {size_str}  ·  修改时间: {mod_time}")

        # 同步向导默认项目信息（重置旧映射与预览，更新为新选文档名称）
        wizard = self.wizard()
        wizard._heading_style_map = None
        wizard._preview = None
        if hasattr(wizard, "_mapping_page"):
            wizard._mapping_page._table.clearContents()
            wizard._mapping_page._rows = []

        source_name = p.stem
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', source_name).strip(" .") or "doc_project"
        wizard._doc_name = source_name
        wizard._project_name = safe_name
        if hasattr(wizard, "_info_page"):
            wizard._info_page._doc_name_entry.setText(source_name)
            wizard._info_page._project_name_entry.setText(safe_name)

        # 确保生成目录卡片展示并同步默认目录
        default_dir = self._get_default_dir()
        if not wizard._target_parent.strip():
            wizard._target_parent = default_dir
        if not self._target_entry.text().strip():
            self._target_entry.setText(wizard._target_parent)
        self._update_default_path_label()
        self._dir_box.show()

        # 启动后台静默诊断
        self._start_silent_preflight()
        self.completeChanged.emit()

    def _start_silent_preflight(self) -> None:
        wizard = self.wizard()
        self._diag_box.show()
        self._diag_title.setText("正在后台智能诊断文档结构与格式特征…")
        self._capsule_heading.setText("📊 章节结构: 分析中…")
        self._capsule_media.setText("🖼 多媒体: 统计中…")
        self._capsule_fidelity.setText("🛡 保真度: 检测中…")
        self._smart_banner.setText("")
        self._tuning_check.hide()
        self._preflight_done = False

        wizard._start_preflight(on_done=self._on_silent_preflight_done)

    def _on_silent_preflight_done(self, response) -> None:
        wizard = self.wizard()
        self._preflight_done = True
        if response is None or not response[0]:
            err_msg = response[2] if response else "预检诊断未能完成"
            self._diag_title.setText("⚠ 文档诊断提示")
            self._smart_banner.setStyleSheet("color: #a12622; font-weight: bold;")
            self._smart_banner.setText(f"诊断未通过：{err_msg}")
            self.completeChanged.emit()
            return

        ok, preview, text = response
        wizard._preview = preview
        h1_count = preview.heading_level_counts.get(1, 0)
        total_headings = sum(preview.heading_level_counts.values())
        self._capsule_heading.setText(f"📊 章节结构: {h1_count} 个一级章，共 {total_headings} 个标题")
        self._capsule_media.setText(f"🖼 多媒体: {preview.image_count} 张图片 · {preview.table_count} 个表格")

        fidelity = getattr(preview, "fidelity", None)
        has_block = bool(fidelity and fidelity.has_block)
        if has_block:
            self._capsule_fidelity.setText("🛡 保真度: ⛔ 存在阻断特性")
            self._capsule_fidelity.setStyleSheet("padding: 4px 8px; border-radius: 4px; background: rgba(161, 38, 34, 0.1); color: #a12622; font-weight: bold;")
        elif getattr(preview, "warnings", None):
            self._capsule_fidelity.setText(f"🛡 保真度: 🟡 存在 {len(preview.warnings)} 项格式提示")
            self._capsule_fidelity.setStyleSheet("padding: 4px 8px; border-radius: 4px; background: rgba(138, 90, 0, 0.1); color: #8a5a00;")
        else:
            self._capsule_fidelity.setText("🛡 保真度: 🟢 结构完整适配")
            self._capsule_fidelity.setStyleSheet("padding: 4px 8px; border-radius: 4px; background: rgba(23, 107, 58, 0.1); color: #176b3a;")

        self._diag_title.setText("✓ 文档结构诊断就绪")

        if preview.has_heading1 and not has_block:
            self._smart_banner.setStyleSheet("color: #176b3a; font-weight: bold;")
            self._smart_banner.setText(f"✓ 已自动识别标准章节大纲（共 {h1_count} 个一级章，{total_headings} 个标题层级），无需手动配置样式。点击「下一步」将直接确认项目位置。")
            self._tuning_check.show()
            self._tuning_check.setChecked(False)
            self._wants_tuning = False
        elif not preview.has_heading1:
            self._smart_banner.setStyleSheet("color: #8a5a00;")
            self._smart_banner.setText("ℹ 未自动识别到标准 Heading 1 标题样式。点击「下一步」将引导您进入「样式映射」确认章节划分。")
            self._tuning_check.hide()
            self._wants_tuning = True
        else:
            self._smart_banner.setStyleSheet("color: #a12622;")
            self._smart_banner.setText("⛔ 文档中包含阻断特性，下一步将展示详细风险报告并需您确认。")
            self._tuning_check.hide()
            self._wants_tuning = True

        self.completeChanged.emit()
        if hasattr(self.wizard(), "_update_next_button_text"):
            self.wizard()._update_next_button_text()

    def _on_tuning_toggled(self, checked: bool) -> None:
        self._wants_tuning = checked
        if hasattr(self.wizard(), "_update_next_button_text"):
            self.wizard()._update_next_button_text()

    def isComplete(self) -> bool:
        if not self._source_path:
            return False
        if self._custom_dir_check.isChecked() and not self._target_entry.text().strip():
            return False
        wizard = self.wizard()
        if wizard and getattr(wizard, "_runner", None) and wizard._runner.is_running:
            return False
        return True

    def source_path(self) -> Optional[str]:
        return self._source_path

    @property
    def wants_custom_mapping(self) -> bool:
        return self._wants_tuning


class _PreflightPage(QWizardPage):
    """步骤 2：导入预检（展示完整日志报告与阻断风险确认）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 2/6：导入预检与保真风险确认")
        layout = QVBoxLayout(self)
        self._status_label = QLabel("准备中…", self)
        layout.addWidget(self._status_label)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
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
        if getattr(wizard, "_preview", None) is not None:
            preview = wizard._preview
            text = format_preview_summary(preview)
            self._preview_ok = True
            self._set_text(text)
            self._has_block = bool(
                getattr(preview, "fidelity", None) is not None
                and preview.fidelity.has_block
            )
            if self._has_block:
                self._confirm_block.show()
            else:
                self._confirm_block.hide()
                self._confirm_block.setChecked(False)
            self._status_label.setText("预检完成")
            self.completeChanged.emit()
            return

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
        if not self._preview_ok:
            return False
        if self._has_block:
            return self._confirm_block.isChecked()
        return True


class _StyleMappingPage(QWizardPage):
    """步骤 3：样式映射（左侧智能建议表格 + 右侧实时大纲预览树）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 3/6：确认章节划分与样式映射")
        self.setSubTitle("把 Word 段落样式映射到章节层级；右侧大纲树将实时联动呈现拆解效果。")
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # 左栏：样式映射表格
        left_widget = QWidget(self)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        left_hint = QLabel("段落样式建议（优先展示疑似标题样式）：", self)
        left_hint.setObjectName("statusMuted")
        left_layout.addWidget(left_hint)

        self._table = QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["样式名", "样式 ID", "正文样例首句", "使用次数", "章节级别"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        left_layout.addWidget(self._table, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("statusMuted")
        self._status.setWordWrap(True)
        left_layout.addWidget(self._status)
        splitter.addWidget(left_widget)

        # 右栏：实时大纲预览
        right_widget = QWidget(self)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)

        right_header = QHBoxLayout()
        right_title = QLabel("实时大纲树预览：", self)
        right_title.setObjectName("statusMuted")
        right_header.addWidget(right_title)
        right_header.addStretch(1)

        self._degrade_btn = QPushButton("自动平滑降级", self)
        self._degrade_btn.setProperty("btnRole", "compact")
        self._degrade_btn.setToolTip("检测到层级跳跃时，自动将间断级别平滑连续排列")
        self._degrade_btn.hide()
        self._degrade_btn.clicked.connect(self._auto_smooth_degrade)
        right_header.addWidget(self._degrade_btn)
        right_layout.addLayout(right_header)

        self._tree_status = QLabel("大纲就绪", self)
        self._tree_status.setWordWrap(True)
        right_layout.addWidget(self._tree_status)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        right_layout.addWidget(self._tree, 1)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._rows: list = []

    def initializePage(self) -> None:
        preview = self.wizard()._preview
        self._populate(preview)
        self._update_outline_tree()
        self.completeChanged.emit()

    def _populate(self, preview) -> None:
        self._table.clearContents()
        self._rows = []
        census = dict(getattr(preview, "style_census", None) or {})
        auto_map = dict(getattr(preview, "heading_style_map", None) or {})

        candidates = [
            c for c in census.values()
            if c.usage_count > 0 and c.style_id.lower() != "normal"
        ]

        def sort_priority(c):
            is_mapped = c.style_id in auto_map
            is_suspected = getattr(c, "suspected_heading", False)
            return (0 if is_mapped else (1 if is_suspected else 2), -c.usage_count, c.name)

        candidates.sort(key=sort_priority)
        self._table.setRowCount(len(candidates))

        for row, census_entry in enumerate(candidates):
            self._table.setItem(row, 0, QTableWidgetItem(census_entry.name))
            self._table.setItem(row, 1, QTableWidgetItem(census_entry.style_id))

            sample = getattr(census_entry, "sample_text", "") or "—"
            sample_item = QTableWidgetItem(sample)
            sample_item.setToolTip(sample)
            self._table.setItem(row, 2, sample_item)

            self._table.setItem(row, 3, QTableWidgetItem(str(census_entry.usage_count)))

            combo = QComboBox(self)
            combo.addItem("忽略 (作为正文)", 0)
            combo.addItem("级别 1 (章标题)", 1)
            combo.addItem("级别 2 (节标题)", 2)
            combo.addItem("级别 3 (小节标题)", 3)
            combo.addItem("级别 4 (子节标题)", 4)
            combo.addItem("级别 5", 5)
            combo.addItem("级别 6", 6)

            default_level = auto_map.get(census_entry.style_id, 0)
            index = combo.findData(default_level)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(self._on_mapping_changed)

            self._table.setCellWidget(row, 4, combo)
            self._rows.append({"style_id": census_entry.style_id, "combo": combo})

        if not candidates:
            self._status.setText("未发现可映射的段落样式（正文除外）。")

    def _on_mapping_changed(self, *_args) -> None:
        self._update_outline_tree()
        self.completeChanged.emit()

    def _update_outline_tree(self) -> None:
        self._tree.clear()
        mapping = self.mapping()
        source_path = self.wizard()._source_page.source_path()
        if not source_path or not Path(source_path).exists():
            self._tree_status.setText("源文档暂未就绪")
            return

        from doc_tool.adapters.preflight import generate_preview_heading_tree

        headings, error = generate_preview_heading_tree(source_path, mapping)
        used_levels = {row["combo"].currentData() for row in self._rows if row["combo"].currentData() > 0}
        has_gap = any(curr > prev + 1 for prev, curr in zip(sorted(used_levels), sorted(used_levels)[1:]))
        missing_h1 = bool(used_levels) and 1 not in used_levels

        if error:
            self._tree_status.setStyleSheet("color: #a12622; font-weight: bold;")
            self._tree_status.setText(f"⚠ {error}")
            if has_gap or missing_h1 or "跳跃" in error or "层级" in error or "第一个标题" in error:
                self._degrade_btn.show()
            else:
                self._degrade_btn.hide()
        else:
            ch_count = sum(1 for h in headings if h.level == 1)
            self._tree_status.setStyleSheet("color: #176b3a;")
            self._tree_status.setText(f"✓ 大纲完整无跳跃（共 {ch_count} 章 {len(headings)} 个标题）")
            self._degrade_btn.hide()

        level_nodes: Dict[int, QTreeWidgetItem] = {}
        for h in headings:
            node_text = f"{'📁 ' if h.level == 1 else '📄 '}{h.text or f'（级别 {h.level} 标题）'}"
            item = QTreeWidgetItem([node_text])
            if h.level == 1:
                self._tree.addTopLevelItem(item)
                level_nodes[1] = item
                for k in list(level_nodes.keys()):
                    if k > 1:
                        del level_nodes[k]
            else:
                parent_level = h.level - 1
                while parent_level >= 1 and parent_level not in level_nodes:
                    parent_level -= 1
                if parent_level in level_nodes:
                    level_nodes[parent_level].addChild(item)
                else:
                    self._tree.addTopLevelItem(item)
                level_nodes[h.level] = item
                for k in list(level_nodes.keys()):
                    if k > h.level:
                        del level_nodes[k]

        self._tree.expandAll()

    def _auto_smooth_degrade(self) -> None:
        used_levels = sorted({row["combo"].currentData() for row in self._rows if row["combo"].currentData() > 0})
        if not used_levels:
            return
        level_map = {old: idx + 1 for idx, old in enumerate(used_levels)}
        for row in self._rows:
            old = row["combo"].currentData()
            if old in level_map:
                new_idx = row["combo"].findData(level_map[old])
                if new_idx >= 0 and new_idx != row["combo"].currentIndex():
                    row["combo"].blockSignals(True)
                    row["combo"].setCurrentIndex(new_idx)
                    row["combo"].blockSignals(False)
        self._update_outline_tree()
        self.completeChanged.emit()

    def mapping(self) -> Dict[str, int]:
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
            self._tree_status.setStyleSheet("color: #a12622; font-weight: bold;")
            self._tree_status.setText(f"⚠ {error}")
            QMessageBox.warning(self, "样式映射无效", error)
            return False
        self.wizard()._heading_style_map = mapping
        return True


class _ProjectInfoPage(QWizardPage):
    """步骤 4：项目信息（智能路径填充 + 行内重名防冲突 + 高级选项折叠）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 4/6：项目信息与存储位置")
        self.setSubTitle("确认项目名称与保存目录。系统已自动智能填充安全名称与推荐路径。")
        self.setCommitPage(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 核心设置区
        core_box = QFrame(self)
        core_box.setProperty("card", True)
        core_layout = QVBoxLayout(core_box)
        core_layout.setSpacing(10)

        # 1. 文档名称
        name_row = QHBoxLayout()
        name_lbl = QLabel("文档名称：", core_box)
        name_lbl.setFixedWidth(100)
        self._doc_name_entry = QLineEdit(core_box)
        self._doc_name_entry.setPlaceholderText("如：系统总体设计方案")
        self._doc_name_entry.textChanged.connect(self._on_inputs_changed)
        name_row.addWidget(name_lbl)
        name_row.addWidget(self._doc_name_entry, 1)
        core_layout.addLayout(name_row)

        # 2. 项目目录名
        proj_row = QHBoxLayout()
        proj_lbl = QLabel("项目目录名：", core_box)
        proj_lbl.setFixedWidth(100)
        self._project_name_entry = QLineEdit(core_box)
        self._project_name_entry.setPlaceholderText("存储文件夹名称（英文/拼音/汉字）")
        self._project_name_entry.textChanged.connect(self._on_inputs_changed)
        proj_row.addWidget(proj_lbl)
        proj_row.addWidget(self._project_name_entry, 1)
        core_layout.addLayout(proj_row)

        # 3. 目标父目录与自定义选项
        self._custom_dir_check = QCheckBox("自定义生成目录", core_box)
        self._custom_dir_check.setChecked(False)
        self._custom_target_check = self._custom_dir_check
        self._custom_dir_check.toggled.connect(self._on_custom_dir_toggled)
        core_layout.addWidget(self._custom_dir_check)

        self._default_path_label = QLabel("", core_box)
        self._default_path_label.setObjectName("statusMuted")
        self._default_path_label.setWordWrap(True)
        self._default_path_label.setStyleSheet(
            "padding: 6px 10px; border-radius: 4px; background: rgba(0,0,0,0.03); color: #333333;"
        )
        core_layout.addWidget(self._default_path_label)

        self._custom_dir_container = QWidget(core_box)
        custom_layout = QHBoxLayout(self._custom_dir_container)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)

        target_lbl = QLabel("存放位置：", self._custom_dir_container)
        target_lbl.setFixedWidth(100)
        self._target_entry = QLineEdit(self._custom_dir_container)
        self._target_entry.setPlaceholderText("项目将存放在此目录下")
        self._target_entry.textChanged.connect(self._on_inputs_changed)
        custom_layout.addWidget(target_lbl)
        custom_layout.addWidget(self._target_entry, 1)

        self._browse_btn = QPushButton("浏览…", self._custom_dir_container)
        self._browse_btn.setProperty("btnRole", "secondary")
        self._browse_btn.clicked.connect(self._browse_target)
        custom_layout.addWidget(self._browse_btn)

        core_layout.addWidget(self._custom_dir_container)
        self._custom_dir_container.hide()

        # 完整路径实时回显与重名冲突检测
        self._path_preview_label = QLabel("", core_box)
        self._path_preview_label.setObjectName("statusMuted")
        core_layout.addWidget(self._path_preview_label)

        conflict_row = QHBoxLayout()
        self._conflict_label = QLabel("", core_box)
        self._conflict_label.setStyleSheet("color: #a12622; font-weight: bold;")
        self._conflict_label.hide()
        conflict_row.addWidget(self._conflict_label)

        self._suffix_btn = QPushButton("自动添加后缀 (v2)", core_box)
        self._suffix_btn.setProperty("btnRole", "compact")
        self._suffix_btn.hide()
        self._suffix_btn.clicked.connect(self._apply_suggested_name)
        conflict_row.addWidget(self._suffix_btn)
        conflict_row.addStretch(1)
        core_layout.addLayout(conflict_row)

        layout.addWidget(core_box)

        # 高级设置折叠区
        self._advanced_group = QGroupBox("⚙ 高级设置（可选）", self)
        self._advanced_group.setCheckable(True)
        self._advanced_group.setChecked(False)
        adv_layout = QVBoxLayout(self._advanced_group)
        adv_layout.setSpacing(8)

        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("文档编号：", self._advanced_group))
        self._doc_no_entry = QLineEdit(self._advanced_group)
        self._doc_no_entry.setPlaceholderText("选填，如 PRD-2026-001")
        meta_row.addWidget(self._doc_no_entry, 1)

        meta_row.addWidget(QLabel("版本号：", self._advanced_group))
        self._doc_version_entry = QLineEdit(self._advanced_group)
        self._doc_version_entry.setPlaceholderText("选填，如 1.0.0")
        meta_row.addWidget(self._doc_version_entry, 1)
        adv_layout.addLayout(meta_row)

        self._exact_roundtrip = QCheckBox(
            "往返检查完全一致（严格模式，要求字节/元素级对齐）", self._advanced_group
        )
        self._exact_roundtrip.setChecked(False)
        self._exact_roundtrip.setToolTip(
            "严格模式：要求反向编译构建后与源文档完全一致。普通写作与导入建议保持关闭以提高容错率。"
        )
        adv_layout.addWidget(self._exact_roundtrip)
        layout.addWidget(self._advanced_group)

        layout.addStretch(1)
        self._suggested_safe_name = ""

    def initializePage(self) -> None:
        wizard = self.wizard()
        if not getattr(wizard, "_default_target_parent", ""):
            wizard._default_target_parent = self._get_default_target_parent()

        is_custom = bool(getattr(wizard, "_custom_target_dir", False))
        if hasattr(wizard, "_source_page") and wizard._source_page._custom_dir_check.isChecked():
            is_custom = True

        if not is_custom:
            if wizard._target_parent.strip():
                wizard._default_target_parent = wizard._target_parent
            else:
                wizard._target_parent = wizard._default_target_parent
        else:
            if not wizard._target_parent.strip():
                wizard._target_parent = wizard._default_target_parent

        self._doc_no_entry.setText(wizard._doc_no)
        self._doc_name_entry.setText(wizard._doc_name)
        self._doc_version_entry.setText(wizard._doc_version)
        self._project_name_entry.setText(wizard._project_name)
        self._target_entry.setText(wizard._target_parent)

        self._custom_dir_check.setChecked(is_custom)
        self._update_dir_visibility(is_custom)

        wizard.button(QWizard.WizardButton.NextButton).setText("开始导入")
        self._check_path_and_conflict()

    def _get_default_target_parent(self) -> str:
        wizard = self.wizard()
        if wizard and hasattr(wizard, "_get_default_target_parent"):
            return wizard._get_default_target_parent()
        return get_default_target_parent()

    def _update_dir_visibility(self, is_custom: bool) -> None:
        if is_custom:
            self._default_path_label.hide()
            self._custom_dir_container.show()
        else:
            self._custom_dir_container.hide()
            self._default_path_label.show()
            self._update_default_path_label()

    def _update_default_path_label(self) -> None:
        wizard = self.wizard()
        default_dir = (
            wizard._default_target_parent
            if (wizard and getattr(wizard, "_default_target_parent", None))
            else self._get_default_target_parent()
        )
        parent_path = self._target_entry.text().strip() or default_dir
        self._default_path_label.setText(
            f"📁 默认生成位置：{parent_path}（系统推荐默认路径，无需手动配置）"
        )

    def _on_custom_dir_toggled(self, checked: bool) -> None:
        wizard = self.wizard()
        if wizard:
            wizard._custom_target_dir = checked
        if checked:
            self._default_path_label.hide()
            self._custom_dir_container.show()
            if not self._target_entry.text().strip():
                self._target_entry.setText(self._get_default_target_parent())
        else:
            self._custom_dir_container.hide()
            self._default_path_label.show()
            default_dir = (
                wizard._default_target_parent
                if (wizard and hasattr(wizard, "_default_target_parent") and wizard._default_target_parent)
                else self._get_default_target_parent()
            )
            self._target_entry.setText(default_dir)
            if wizard:
                wizard._target_parent = default_dir
            self._update_default_path_label()

        # 同步回源页面
        if wizard and hasattr(wizard, "_source_page"):
            sp = wizard._source_page
            if hasattr(sp, "_custom_dir_check") and sp._custom_dir_check.isChecked() != checked:
                sp._custom_dir_check.setChecked(checked)
            if hasattr(sp, "_target_entry") and sp._target_entry.text() != self._target_entry.text():
                sp._target_entry.setText(self._target_entry.text())

        self._check_path_and_conflict()
        self.completeChanged.emit()

    def _browse_target(self) -> None:
        current = self._target_entry.text().strip() or self._get_default_target_parent()
        path = QFileDialog.getExistingDirectory(self, "选择存放父目录", current)
        if path:
            self._target_entry.setText(path)
            self._on_inputs_changed()

    def _on_inputs_changed(self) -> None:
        target_path = self._target_entry.text().strip()
        wizard = self.wizard()
        if wizard and target_path:
            wizard._target_parent = target_path
            if hasattr(wizard, "_source_page"):
                sp = wizard._source_page
                if hasattr(sp, "_target_entry") and sp._target_entry.text() != self._target_entry.text():
                    sp._target_entry.setText(self._target_entry.text())
        self._update_default_path_label()
        self._check_path_and_conflict()
        self.completeChanged.emit()

    def _check_path_and_conflict(self) -> None:
        parent_path = self._target_entry.text().strip()
        proj_name = self._project_name_entry.text().strip()
        if parent_path and proj_name:
            full_path = Path(parent_path) / proj_name
            self._path_preview_label.setText(f"📁 完整项目存储路径：{full_path}")
            if full_path.exists():
                self._conflict_label.show()
                self._conflict_label.setText("⚠ 该位置已存在同名项目目录，导入将无法继续")
                base_name = re.sub(r"-v\d+$", "", proj_name)
                idx = 2
                while (Path(parent_path) / f"{base_name}-v{idx}").exists():
                    idx += 1
                self._suggested_safe_name = f"{base_name}-v{idx}"
                self._suffix_btn.setText(f"一键更名为 {self._suggested_safe_name}")
                self._suffix_btn.show()
            else:
                self._conflict_label.hide()
                self._suffix_btn.hide()
        else:
            self._path_preview_label.setText("")
            self._conflict_label.hide()
            self._suffix_btn.hide()

    def _apply_suggested_name(self) -> None:
        if self._suggested_safe_name:
            self._project_name_entry.setText(self._suggested_safe_name)
            self._check_path_and_conflict()

    def isComplete(self) -> bool:
        doc_name = self._doc_name_entry.text().strip()
        proj_name = self._project_name_entry.text().strip()
        is_custom = self._custom_dir_check.isChecked()
        parent_path = (
            self._target_entry.text().strip()
            if is_custom
            else (self._target_entry.text().strip() or self._get_default_target_parent())
        )
        if not (doc_name and proj_name and parent_path):
            return False
        try:
            if (Path(parent_path) / proj_name).exists():
                return False
        except Exception:
            return False
        if (
            proj_name in (".", "..")
            or Path(proj_name).name != proj_name
            or any(c in proj_name for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in proj_name)
            or proj_name.rstrip(" .") != proj_name
        ):
            return False
        return True

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
            self._conflict_label.setText(f"⚠ {error}")
            self._conflict_label.show()
            QMessageBox.warning(self, "项目信息无效", error)
            return False

        full_target = Path(wizard._target_parent) / wizard._project_name
        if full_target.exists():
            self._conflict_label.setText("⚠ 目标项目目录已存在，请修改目录名或点击自动添加后缀")
            self._conflict_label.show()
            QMessageBox.warning(self, "目标目录冲突", f"目录已存在：{full_target}\n请修改项目目录名避免覆盖。")
            return False

        return True


class _ExecutingPage(QWizardPage):
    """步骤 5：流水线 Stepper 实时导入中。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 5/6：正在执行流水线导入…")
        self.setSubTitle("系统正在事务化构建项目结构，提取文本、表格与多媒体资源。")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        stepper_box = QFrame(self)
        stepper_box.setProperty("card", True)
        stepper_layout = QVBoxLayout(stepper_box)
        stepper_layout.setSpacing(10)

        self._steps_def = [
            ("validate", "1. 验证目标环境与项目目录"),
            ("template", "2. 复制源文档并初始化排版模板"),
            ("content", "3. 解析正文结构与提取图片表格"),
            ("split", "4. 拆解生成 Markdown 章节树"),
            ("publish", "5. 试构建与发布就绪"),
        ]

        self._step_labels: Dict[str, QLabel] = {}
        for key, title in self._steps_def:
            row = QHBoxLayout()
            lbl = QLabel(f"○  {title}", stepper_box)
            lbl.setStyleSheet("color: #6b7280; font-size: 10pt;")
            self._step_labels[key] = lbl
            row.addWidget(lbl)
            row.addStretch(1)
            stepper_layout.addLayout(row)

        layout.addWidget(stepper_box)

        self._detail_label = QLabel("正在启动流水线执行引擎…", self)
        self._detail_label.setObjectName("statusMuted")
        layout.addWidget(self._detail_label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        layout.addWidget(self._progress)
        layout.addStretch(1)

        self._started = False

    def initializePage(self) -> None:
        wizard = self.wizard()
        self._reset_stepper()
        self._detail_label.setText("正在执行项目导入…")
        wizard._step4_done = False
        wizard._import_started = False
        wizard._do_import(on_done=self._on_done)
        self._started = True

    def _reset_stepper(self) -> None:
        for key, title in self._steps_def:
            self._step_labels[key].setText(f"○  {title}")
            self._step_labels[key].setStyleSheet("color: #6b7280; font-size: 10pt;")

    def on_stage_event(self, event) -> None:
        stage = getattr(event, "stage", "")
        detail = getattr(event, "detail", "")

        step_map = {
            "validate_target": "validate",
            "preflight": "validate",
            "create_staging": "template",
            "copy_source": "template",
            "generate_template": "template",
            "extract_content": "content",
            "split_content": "split",
            "validate_structure": "split",
            "save_manifest": "split",
            "trial_build": "publish",
            "roundtrip_check": "publish",
            "publish": "publish",
        }

        active_key = step_map.get(stage)
        if not active_key:
            return

        step_keys = [k for k, _ in self._steps_def]
        if active_key in step_keys:
            active_idx = step_keys.index(active_key)
            for idx, (k, title) in enumerate(self._steps_def):
                if idx < active_idx:
                    self._step_labels[k].setText(f"✓  {title}")
                    self._step_labels[k].setStyleSheet("color: #176b3a; font-weight: bold;")
                elif idx == active_idx:
                    self._step_labels[k].setText(f"⟳  {title}")
                    self._step_labels[k].setStyleSheet("color: #2563eb; font-weight: bold;")
                else:
                    self._step_labels[k].setText(f"○  {title}")
                    self._step_labels[k].setStyleSheet("color: #6b7280;")

        if detail:
            self._detail_label.setText(detail)

    def isComplete(self) -> bool:
        return bool(getattr(self.wizard(), "_step4_done", False))

    def _on_done(self, result, target_root: str) -> None:
        wizard = self.wizard()
        if wizard._closing:
            wizard.reject()
            return
        wizard._import_result = result
        wizard._target_root = target_root
        wizard._step4_done = True
        if result and getattr(result, "success", False):
            for k, title in self._steps_def:
                self._step_labels[k].setText(f"✓  {title}")
                self._step_labels[k].setStyleSheet("color: #176b3a; font-weight: bold;")
        wizard.next()

    def cleanupPage(self) -> None:
        self._started = False


class _ResultPage(QWizardPage):
    """步骤 6：成就感看板与可逆容错。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("步骤 6/6：导入完成看板")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 成功看板容器
        self._success_card = QFrame(self)
        self._success_card.setProperty("card", True)
        succ_layout = QVBoxLayout(self._success_card)
        succ_layout.setContentsMargins(20, 16, 20, 16)
        succ_layout.setSpacing(10)

        self._success_title = QLabel("🎉 项目已成功创建并就绪！", self._success_card)
        s_font = self._success_title.font()
        s_font.setPointSize(14)
        s_font.setBold(True)
        self._success_title.setFont(s_font)
        self._success_title.setStyleSheet("color: #176b3a;")
        succ_layout.addWidget(self._success_title)

        self._path_display = QLabel("", self._success_card)
        self._path_display.setWordWrap(True)
        succ_layout.addWidget(self._path_display)

        # 统计勋章
        self._badges_layout = QHBoxLayout()
        self._badge_headings = QLabel("📑 章节就绪", self._success_card)
        self._badge_headings.setStyleSheet("padding: 4px 10px; border-radius: 4px; background: rgba(37, 99, 235, 0.08); color: #2563eb; font-weight: bold;")
        self._badge_images = QLabel("🖼 图片已提取", self._success_card)
        self._badge_images.setStyleSheet("padding: 4px 10px; border-radius: 4px; background: rgba(0,0,0,0.05);")
        self._badge_tables = QLabel("📊 表格已拆解", self._success_card)
        self._badge_tables.setStyleSheet("padding: 4px 10px; border-radius: 4px; background: rgba(0,0,0,0.05);")
        self._badges_layout.addWidget(self._badge_headings)
        self._badges_layout.addWidget(self._badge_images)
        self._badges_layout.addWidget(self._badge_tables)
        self._badges_layout.addStretch(1)
        succ_layout.addLayout(self._badges_layout)

        # 主操作按钮行
        actions_row = QHBoxLayout()
        self._open_project_btn = QPushButton("🚀 进入工作台开始编辑", self._success_card)
        self._open_project_btn.setProperty("btnRole", "primary")
        self._open_project_btn.setMinimumHeight(34)
        self._open_project_btn.clicked.connect(self._on_open_project_clicked)
        actions_row.addWidget(self._open_project_btn)

        self._reveal_btn = QPushButton("在资源管理器中打开", self._success_card)
        self._reveal_btn.setProperty("btnRole", "secondary")
        self._reveal_btn.setMinimumHeight(34)
        self._reveal_btn.clicked.connect(self._on_reveal_clicked)
        actions_row.addWidget(self._reveal_btn)
        actions_row.addStretch(1)
        succ_layout.addLayout(actions_row)

        layout.addWidget(self._success_card)

        # 失败/告警提示卡片
        self._failure_card = QFrame(self)
        self._failure_card.setProperty("card", True)
        fail_layout = QVBoxLayout(self._failure_card)
        fail_layout.setContentsMargins(16, 12, 16, 12)
        fail_layout.setSpacing(8)

        self._failure_title = QLabel("✗ 项目导入未完成", self._failure_card)
        f_font = self._failure_title.font()
        f_font.setPointSize(12)
        f_font.setBold(True)
        self._failure_title.setFont(f_font)
        self._failure_title.setStyleSheet("color: #a12622;")
        fail_layout.addWidget(self._failure_title)

        self._failure_reason = QLabel("", self._failure_card)
        self._failure_reason.setStyleSheet("color: #a12622; font-weight: bold;")
        self._failure_reason.setWordWrap(True)
        self._failure_reason.hide()
        fail_layout.addWidget(self._failure_reason)

        self._failure_hint = QLabel(
            "您可以点击下方「上一步」返回修改项目名称或选择新的存储目录，表单数据已全额保留。",
            self._failure_card,
        )
        self._failure_hint.setWordWrap(True)
        fail_layout.addWidget(self._failure_hint)
        layout.addWidget(self._failure_card)

        # 保留原有标签和纯文本以便测试兼容
        self._result_label = QLabel(self)
        self._result_label.setObjectName("resultTitle")
        self._result_label.hide()
        layout.addWidget(self._result_label)

        # 详细事件与诊断日志
        self._detail_group = QGroupBox("▶ 详细执行事件与诊断日志", self)
        self._detail_group.setCheckable(True)
        self._detail_group.setChecked(False)
        detail_layout = QVBoxLayout(self._detail_group)
        self._result_detail = QPlainTextEdit(self._detail_group)
        self._result_detail.setReadOnly(True)
        detail_layout.addWidget(self._result_detail)
        layout.addWidget(self._detail_group, 1)

    def initializePage(self) -> None:
        wizard = self.wizard()
        result = wizard._import_result
        target_root = wizard._target_root
        self._render(result, target_root)

        is_success = bool(result and result.success)
        finish_btn = wizard.button(QWizard.WizardButton.FinishButton)
        target_text = "进入工作台" if is_success else "关闭"
        wizard.button(QWizard.WizardButton.NextButton).setText(target_text)
        if finish_btn:
            finish_btn.setText(target_text)
        wizard.button(QWizard.WizardButton.BackButton).setEnabled(not is_success)

    def _render(self, result, target_root: str) -> None:
        if result is None:
            self._success_card.hide()
            self._failure_card.show()
            self._failure_title.setText("✗ 导入异常终止或超时")
            self._result_label.setText("✗ 导入异常终止")
            self._result_label.setProperty("statusTone", "failure")
            self._result_detail.setPlainText("导入任务未返回正常结果，请检查应用日志。")
        elif result.success:
            self._failure_card.hide()
            self._success_card.show()
            self._result_label.setText("✓ 导入成功")
            self._result_label.setProperty("statusTone", "success")

            self._path_display.setText(f"项目目录：{target_root}")

            preview = getattr(self.wizard(), "_preview", None)
            if preview:
                total_h = sum(preview.heading_level_counts.values())
                self._badge_headings.setText(f"📑 {total_h} 个章节结构")
                self._badge_images.setText(f"🖼 {preview.image_count} 张图片")
                self._badge_tables.setText(f"📊 {preview.table_count} 个表格")

            detail_lines = [
                f"项目目录：{target_root}",
                f"源文件指纹：{(result.source_sha256 or '')[:12]}…",
                "",
                "阶段事件：",
            ]
            for event in result.events:
                detail_lines.append(f"  {event.stage}: {event.status}")
            self._result_detail.setPlainText("\n".join(detail_lines))
        else:
            self._success_card.hide()
            self._failure_card.show()
            cancelled = result.error_code == "E5003"
            self._failure_title.setText("⊘ 导入已取消" if cancelled else f"✗ 导入未成功（错误码：{result.error_code or '未知'}）")
            self._result_label.setText("⊘ 导入已取消" if cancelled else "✗ 导入失败")
            self._result_label.setProperty("statusTone", "warning" if cancelled else "failure")

            fail_reason = ""
            for ev in reversed(result.events):
                if ev.status == "failed" and ev.detail:
                    fail_reason = ev.detail
                    break
            if not fail_reason and result.diagnostic_log:
                fail_reason = result.diagnostic_log.strip().splitlines()[0][:120]
            if fail_reason:
                self._failure_reason.setText(f"失败原因：{fail_reason}")
                self._failure_reason.show()
            else:
                self._failure_reason.hide()

            error_lines = [
                f"错误码：{result.error_code or '未知'}",
                "",
                "阶段事件：",
            ]
            for event in result.events:
                line = f"  {event.stage}: {event.status}"
                if event.detail:
                    line += f" — {event.detail}"
                if "errorCode" in event.metrics:
                    line += f"（{event.metrics['errorCode']}）"
                error_lines.append(line)
            if result.diagnostic_log:
                error_lines.append("")
                error_lines.append(f"诊断日志：{result.diagnostic_log}")
            self._result_detail.setPlainText("\n".join(error_lines))

    def _on_open_project_clicked(self) -> None:
        self.wizard().accept()

    def _on_reveal_clicked(self) -> None:
        target = self.wizard()._target_root
        if target and os.path.exists(target):
            try:
                os.startfile(target)
            except Exception:
                subprocess.Popen(["explorer", target])


class ImportWizard(QWizard):
    """新建项目向导（QWizard 深度优化版）。

    返回项目目录路径（成功）或 None（取消）。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建项目向导")
        self.resize(760, 560)
        self.setMinimumSize(600, 480)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        # 共享状态
        self._source_path: Optional[str] = None
        self._preview = None
        self._heading_style_map: Optional[Dict[str, int]] = None
        self._doc_type: str = "general"
        self._doc_no: str = ""
        self._doc_name: str = ""
        self._doc_version: str = ""
        self._project_name: str = ""
        self._target_parent: str = ""
        self._default_target_parent: str = get_default_target_parent()
        self._custom_target_dir: bool = False
        self._require_exact_roundtrip: bool = False
        self._target_root: str = ""
        self._import_result = None
        self._import_started = False
        self._step4_done = False
        self._closing = False
        self._last_error_code: Optional[str] = None

        self._runner = TaskRunner()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_runner)

        # 六个标准页面
        self._source_page = _SourcePage(self)
        self._preflight_page = _PreflightPage(self)
        self._mapping_page = _StyleMappingPage(self)
        self._info_page = _ProjectInfoPage(self)
        self._executing_page = _ExecutingPage(self)
        self._result_page = _ResultPage(self)

        self.setPage(0, self._source_page)
        self.setPage(1, self._preflight_page)
        self.setPage(2, self._mapping_page)
        self.setPage(3, self._info_page)
        self.setPage(4, self._executing_page)
        self.setPage(5, self._result_page)

        self.currentIdChanged.connect(self._on_page_changed)
        self.button(QWizard.WizardButton.CancelButton).clicked.connect(
            self._on_cancel_clicked
        )

    def _get_default_target_parent(self) -> str:
        return get_default_target_parent()

    def nextId(self) -> int:
        """自适应智能跳步逻辑：规范文档自动跳过技术日志与冗余映射。"""
        current = self.currentId()
        if current == -1:
            current = self.startId()
        if current == 0:
            preview = self._preview
            has_block = bool(
                preview is not None
                and getattr(preview, "fidelity", None) is not None
                and preview.fidelity.has_block
            )
            wants_tuning = getattr(self._source_page, "wants_custom_mapping", False)

            if preview and preview.has_heading1 and not has_block and not wants_tuning:
                return 3

            if preview and wants_tuning and not has_block:
                return 2

            return 1
        elif current == 1:
            preview = self._preview
            wants_tuning = getattr(self._source_page, "wants_custom_mapping", False)
            if preview and preview.has_heading1 and not wants_tuning:
                return 3
            return 2
        elif current == 2:
            return 3
        elif current == 3:
            return 4
        elif current == 4:
            return 5
        elif current == 5:
            return -1
        return super().nextId()

    def back(self) -> None:
        """回退导航：若在导入失败结果页，跳过正在执行页直接回退至项目配置页。"""
        if self.currentId() == 5:
            while self.currentId() in (4, 5) and len(self.visitedIds()) > 1:
                super().back()
            return
        super().back()

    def run(self) -> Optional[str]:
        if self.exec() == QDialog.DialogCode.Accepted:
            result = getattr(self, "_import_result", None)
            if (
                result is not None
                and result.success
                and getattr(self, "_target_root", "")
            ):
                return self._target_root
        return None

    def _on_page_changed(self, _page_id: int) -> None:
        page = self.currentPage()
        if page is None:
            return
        self.button(QWizard.WizardButton.NextButton).setEnabled(
            page.isComplete()
        )
        current = self.currentId()
        allow_back = (
            current not in (0, 4)
            and (current != 5 or (self._import_result is not None and not self._import_result.success))
        )
        self.button(QWizard.WizardButton.BackButton).setEnabled(allow_back)
        self._update_next_button_text()

    def _update_next_button_text(self) -> None:
        current = self.currentId()
        if current == -1:
            current = self.startId()
        next_btn = self.button(QWizard.WizardButton.NextButton)
        if current == 0:
            if self.nextId() == 3:
                next_btn.setText("下一步：确认项目信息")
            elif self.nextId() == 2:
                next_btn.setText("下一步：配置样式映射")
            elif self.nextId() == 1:
                if self._preview and getattr(self._preview, "fidelity", None) and self._preview.fidelity.has_block:
                    next_btn.setText("下一步：查看风险报告")
                else:
                    next_btn.setText("下一步")
            else:
                next_btn.setText("下一步")
        elif current == 3:
            next_btn.setText("开始导入")
        elif current == 5:
            target_text = (
                "进入工作台"
                if (self._import_result and self._import_result.success)
                else "关闭"
            )
            next_btn.setText(target_text)
            finish_btn = self.button(QWizard.WizardButton.FinishButton)
            if finish_btn:
                finish_btn.setText(target_text)
        else:
            next_btn.setText("下一步")

    def _start_preflight(self, on_done) -> None:
        self._last_error_code = None

        def run_preflight():
            from doc_tool.adapters.preflight import preflight
            from doc_tool.domain.errors import DocToolError

            try:
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

    def _do_import(self, on_done) -> None:
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
        self._import_started = True
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
        else:
            from doc_tool.application.import_project import ImportResult

            on_done(
                ImportResult(
                    success=False,
                    error_code="E9000",
                    events=[],
                ),
                target_root,
            )

    def _on_task_event(self, event) -> None:
        if event.kind == "failed":
            self._last_error_code = event.error_code
        elif event.kind == "stage":
            if hasattr(self, "_executing_page"):
                self._executing_page.on_stage_event(event)

    def _poll_runner(self) -> None:
        self._runner.poll()
        if self._closing and not self._runner.is_running:
            self._poll_timer.stop()
            self.reject()
            return
        if not self._runner.is_running:
            self._poll_timer.stop()

    def _validate_project_info(self) -> str:
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

    def _on_cancel_clicked(self) -> None:
        if self._runner.is_running:
            self._closing = True
            self._runner.cancel()
            self.button(QWizard.WizardButton.CancelButton).setEnabled(False)
        else:
            self.reject()

    def reject(self) -> None:
        if self._runner.is_running and not self._closing:
            self._closing = True
            self._runner.cancel()
            self.button(QWizard.WizardButton.CancelButton).setEnabled(False)
            return
        super().reject()
