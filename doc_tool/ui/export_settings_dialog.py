# -*- coding: utf-8 -*-
"""导出设置表单（UI2-D 4.2～4.4）：把既有 ExportRequest/ExportScope/LayoutProfile
能力做成一张可直接提交的表单。

设计要点：

- 字段只映射既有契约（格式/范围/来源/目录/名称/版式/高级），不新增第二套业务状态；
- 默认值即快捷 Word 的安全默认：Word、整份、当前编辑内容、有效目录、模板、非严格；
- 基础区默认一次「开始导出」即可提交；高级区默认折叠，只暴露 LayoutProfile 已支持字段；
- 空章节选择沿用 CORE 整份回退并在摘要里明示实际策略；目录不可写时由原服务回退并报告；
- 表单关闭不丢编辑缓冲：缓冲由主窗口在提交时收集，本表单只产出请求对象。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.export.layout_profile import (
    MODE_BODY_ADAPTIVE,
    MODE_TEMPLATE,
    TABLE_EQUAL,
    TABLE_KEEP,
    TABLE_PROPORTIONAL,
    LayoutProfile,
)
from doc_tool.application.intake_contract import (
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_PDF,
    FORMAT_SOURCE_ZIP,
    SCOPE_CHAPTERS,
    SCOPE_CURRENT_CHAPTER,
    SCOPE_PROJECT,
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED,
    ExportRequest,
    ExportScope,
    format_label,
)

#: 可导出的格式（与 CORE 契约一致）。
FORMAT_CHOICES = (FORMAT_DOCX, FORMAT_PDF, FORMAT_HTML, FORMAT_SOURCE_ZIP)

#: 版式模式显示名。
_LAYOUT_LABELS = ((MODE_TEMPLATE, "遵循模板"), (MODE_BODY_ADAPTIVE, "正文自适应"))
_TABLE_LABELS = (
    (TABLE_KEEP, "保持原样"),
    (TABLE_PROPORTIONAL, "按比例适配"),
    (TABLE_EQUAL, "等宽均分"),
)


def build_export_request(
    *,
    project_root: str,
    formats: Sequence[str],
    scope_kind: str,
    chapters: Sequence[str] = (),
    current_chapter: str = "",
    source_mode: str,
    destination: str,
    output_name: str = "",
    layout_mode: str = MODE_TEMPLATE,
    image_width: str = "auto-width",
    table_width: str = TABLE_KEEP,
    repeat_header: bool = False,
    allow_row_split: bool = True,
    page_break_before_chapter: bool = False,
    landscape_chapters: Sequence[str] = (),
    variant_id: str = "",
    include_original: bool = False,
    strict: bool = False,
) -> ExportRequest:
    """纯适配：表单字段 → 既有 ``ExportRequest``（不做业务判断）。"""
    scope = ExportScope(
        kind=scope_kind if scope_kind in (SCOPE_PROJECT, SCOPE_CURRENT_CHAPTER, SCOPE_CHAPTERS) else SCOPE_PROJECT,
        chapters=list(chapters or []) if scope_kind == SCOPE_CHAPTERS else [],
        current=current_chapter if scope_kind == SCOPE_CURRENT_CHAPTER else "",
    )
    profile = LayoutProfile(
        mode=layout_mode if layout_mode in (MODE_TEMPLATE, MODE_BODY_ADAPTIVE) else MODE_TEMPLATE,
        image_width=image_width,
        table_width=table_width,
        repeat_header=bool(repeat_header),
        allow_row_split=bool(allow_row_split),
        page_break_before_chapter=bool(page_break_before_chapter),
        landscape_chapters=list(landscape_chapters or []),
    )
    return ExportRequest(
        project_root=str(project_root or ""),
        formats=[fmt for fmt in formats if fmt] or [FORMAT_DOCX],
        scope=scope,
        source_mode=source_mode if source_mode in (SOURCE_MODE_CURRENT_BUFFER, SOURCE_MODE_SAVED) else SOURCE_MODE_CURRENT_BUFFER,
        destination=str(destination or ""),
        output_name=str(output_name or ""),
        layout_profile=profile.mode,
        layout=profile.to_dict() if hasattr(profile, "to_dict") else {},
        strict=bool(strict),
        include_original=bool(include_original),
        variant_id=str(variant_id or ""),
    )


def describe_request(request: ExportRequest, *, total_chapters: int = 0) -> str:
    """提交前的实时摘要：来源 · 范围 · 格式 · 版式 · 输出位置。"""
    source = "当前内容" if request.source_mode == SOURCE_MODE_CURRENT_BUFFER else "已保存版本"
    scope = request.scope.describe(total_chapters)
    formats = " / ".join(format_label(fmt) for fmt in request.formats)
    layout = dict(_LAYOUT_LABELS).get(request.layout_profile, request.layout_profile)
    suffix = "（严格模式）" if request.strict else ""
    return "{0} · {1} · {2} · {3} · {4}{5}".format(
        source, scope, formats, layout, request.destination or "（默认目录）", suffix
    )


class ExportSettingsDialog(QDialog):
    """导出设置：基础字段可直接提交，高级区折叠。"""

    def __init__(
        self,
        *,
        project_root: str = "",
        destination: str = "",
        chapters: Optional[Sequence[str]] = None,
        current_chapter: str = "",
        unsaved_count: int = 0,
        variants: Optional[Sequence[str]] = None,
        notice: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出设置")
        self.resize(720, 640)
        self._project_root = str(project_root or "")
        self._chapters = list(chapters or [])
        self._current_chapter = str(current_chapter or "")
        self._unsaved_count = int(unsaved_count or 0)
        self._variants = list(variants or [])
        self._request: Optional[ExportRequest] = None

        layout = QVBoxLayout(self)
        self._recovery_notice = QLabel(str(notice), self)
        self._recovery_notice.setWordWrap(True)
        self._recovery_notice.setVisible(bool(notice))
        layout.addWidget(self._recovery_notice)
        layout.setSpacing(8)

        # --- 导出什么 ---
        layout.addWidget(self._section_label("导出什么"))
        formats_row = QHBoxLayout()
        self._format_boxes = {}
        for fmt in FORMAT_CHOICES:
            box = QCheckBox(format_label(fmt), self)
            box.setChecked(fmt == FORMAT_DOCX)
            box.toggled.connect(self._refresh_summary)
            self._format_boxes[fmt] = box
            formats_row.addWidget(box)
        formats_row.addStretch(1)
        layout.addLayout(formats_row)
        self._format_hint = QLabel(
            "PDF 需要本机可用的转换环境；缺少时其它格式仍会生成并单独标注。",
            self,
        )
        self._format_hint.setObjectName("statusMuted")
        self._format_hint.setWordWrap(True)
        layout.addWidget(self._format_hint)

        # --- 导出范围 ---
        layout.addWidget(self._section_label("导出范围"))
        scope_row = QHBoxLayout()
        self._scope_combo = QComboBox(self)
        self._scope_combo.addItem("整份文档", SCOPE_PROJECT)
        self._scope_combo.addItem(
            "当前章：{0}".format(Path(self._current_chapter).name or "（未打开章节）"),
            SCOPE_CURRENT_CHAPTER,
        )
        self._scope_combo.addItem("所选章节", SCOPE_CHAPTERS)
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        scope_row.addWidget(self._scope_combo, 1)
        layout.addLayout(scope_row)

        self._chapter_list = QListWidget(self)
        self._chapter_list.setObjectName("exportChapterList")
        self._chapter_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for chapter in self._chapters:
            item = QListWidgetItem(chapter, self._chapter_list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, chapter)
        self._chapter_list.itemChanged.connect(lambda _i: self._refresh_summary())
        self._chapter_list.setVisible(False)
        layout.addWidget(self._chapter_list, 2)
        self._chapter_hint = QLabel("", self)
        self._chapter_hint.setObjectName("statusMuted")
        self._chapter_hint.setWordWrap(True)
        layout.addWidget(self._chapter_hint)

        # --- 内容来源 ---
        layout.addWidget(self._section_label("内容来源"))
        self._source_combo = QComboBox(self)
        self._source_combo.addItem("当前编辑内容（含未保存修改）", SOURCE_MODE_CURRENT_BUFFER)
        self._source_combo.addItem("已保存版本", SOURCE_MODE_SAVED)
        self._source_combo.currentIndexChanged.connect(self._refresh_summary)
        layout.addWidget(self._source_combo)
        self._source_hint = QLabel("", self)
        self._source_hint.setObjectName("statusMuted")
        self._source_hint.setWordWrap(True)
        layout.addWidget(self._source_hint)

        # --- 放在哪里 ---
        layout.addWidget(self._section_label("放在哪里"))
        dest_row = QHBoxLayout()
        self._destination_entry = QLineEdit(self)
        self._destination_entry.setText(str(destination or ""))
        self._destination_entry.setPlaceholderText("默认项目 output 目录")
        self._destination_entry.textChanged.connect(self._refresh_summary)
        dest_row.addWidget(self._destination_entry, 1)
        pick_btn = QDialogButtonBox(self)
        browse = pick_btn.addButton("选择目录…", QDialogButtonBox.ButtonRole.ActionRole)
        browse.clicked.connect(self._pick_destination)
        dest_row.addWidget(pick_btn)
        layout.addLayout(dest_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("文件名（可选）：", self))
        self._name_entry = QLineEdit(self)
        self._name_entry.setPlaceholderText("留空＝按文档编号与版本自动命名")
        self._name_entry.textChanged.connect(self._refresh_summary)
        name_row.addWidget(self._name_entry, 1)
        layout.addLayout(name_row)

        # --- 高级（折叠） ---
        self._advanced_box = QGroupBox("高级设置（默认折叠）", self)
        self._advanced_box.setCheckable(True)
        self._advanced_box.setChecked(False)
        advanced_layout = QVBoxLayout(self._advanced_box)
        self._advanced_box.toggled.connect(self._on_advanced_toggled)

        layout_row = QHBoxLayout()
        layout_row.addWidget(QLabel("版式：", self._advanced_box))
        self._layout_combo = QComboBox(self._advanced_box)
        for value, label in _LAYOUT_LABELS:
            self._layout_combo.addItem(label, value)
        self._layout_combo.currentIndexChanged.connect(self._refresh_summary)
        layout_row.addWidget(self._layout_combo, 1)
        layout_row.addWidget(QLabel("图片宽度：", self._advanced_box))
        self._image_combo = QComboBox(self._advanced_box)
        self._image_combo.addItem("自适应页宽", "auto-width")
        self._image_combo.addItem("保持原始", "keep")
        self._image_combo.currentIndexChanged.connect(self._refresh_summary)
        layout_row.addWidget(self._image_combo, 1)
        advanced_layout.addLayout(layout_row)

        table_row = QHBoxLayout()
        table_row.addWidget(QLabel("普通表格列宽：", self._advanced_box))
        self._table_combo = QComboBox(self._advanced_box)
        for value, label in _TABLE_LABELS:
            self._table_combo.addItem(label, value)
        self._table_combo.currentIndexChanged.connect(self._refresh_summary)
        table_row.addWidget(self._table_combo, 1)
        self._repeat_header = QCheckBox("表头跨页重复", self._advanced_box)
        self._repeat_header.toggled.connect(self._refresh_summary)
        table_row.addWidget(self._repeat_header)
        self._allow_split = QCheckBox("允许行跨页", self._advanced_box)
        self._allow_split.setChecked(True)
        self._allow_split.toggled.connect(self._refresh_summary)
        table_row.addWidget(self._allow_split)
        advanced_layout.addLayout(table_row)

        page_row = QHBoxLayout()
        self._page_break = QCheckBox("章前分页", self._advanced_box)
        self._page_break.toggled.connect(self._refresh_summary)
        page_row.addWidget(self._page_break)
        page_row.addWidget(QLabel("横向章节数：", self._advanced_box))
        self._landscape_count = QSpinBox(self._advanced_box)
        self._landscape_count.setRange(0, len(self._chapters))
        self._landscape_count.valueChanged.connect(self._refresh_summary)
        page_row.addWidget(self._landscape_count)
        self._landscape_hint = QLabel("仅对所选章节按文档顺序生效", self._advanced_box)
        self._landscape_hint.setObjectName("statusMuted")
        page_row.addWidget(self._landscape_hint, 1)
        advanced_layout.addLayout(page_row)

        option_row = QHBoxLayout()
        option_row.addWidget(QLabel("变体：", self._advanced_box))
        self._variant_combo = QComboBox(self._advanced_box)
        self._variant_combo.addItem("（不使用变体）", "")
        for variant in self._variants:
            self._variant_combo.addItem(str(variant), str(variant))
        self._variant_combo.setEnabled(bool(self._variants))
        self._variant_combo.currentIndexChanged.connect(self._refresh_summary)
        option_row.addWidget(self._variant_combo, 1)
        self._include_original = QCheckBox("纳入原件", self._advanced_box)
        self._include_original.toggled.connect(self._refresh_summary)
        option_row.addWidget(self._include_original)
        self._strict = QCheckBox("严格模式", self._advanced_box)
        self._strict.toggled.connect(self._refresh_summary)
        option_row.addWidget(self._strict)
        advanced_layout.addLayout(option_row)
        self._advanced_hint = QLabel(
            "严格模式默认关闭：打开后未达标格式会在结果中单列，不阻断其它格式。",
            self._advanced_box,
        )
        self._advanced_hint.setObjectName("statusMuted")
        self._advanced_hint.setWordWrap(True)
        advanced_layout.addWidget(self._advanced_hint)
        layout.addWidget(self._advanced_box)

        # --- 摘要与提交 ---
        self._summary = QLabel("", self)
        self._summary.setObjectName("statusMuted")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._buttons = QDialogButtonBox(self)
        self._submit_btn = self._buttons.addButton(
            "开始导出", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._buttons.accepted.connect(self._on_submit)
        layout.addWidget(self._buttons)

        self._on_scope_changed(0)
        self._refresh_summary()

    # --- 小工具 ---

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("sectionTitle")
        return label

    def _pick_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "选择导出目录", self._destination_entry.text() or ""
        )
        if chosen:
            self._destination_entry.setText(chosen)

    def _on_scope_changed(self, _index: int) -> None:
        kind = self.scope_kind()
        show_chapters = kind == SCOPE_CHAPTERS
        self._chapter_list.setVisible(show_chapters)
        if show_chapters and not self._chapters:
            self._chapter_hint.setText("当前项目没有可用章节：将按整份文档回退。")
        elif show_chapters:
            self._chapter_hint.setText(
                "按文档顺序导出所选章节；一个都不勾选时沿用整份文档回退。"
            )
        else:
            self._chapter_hint.setText("")
        self._refresh_summary()

    def _on_advanced_toggled(self, checked: bool) -> None:
        self._advanced_box.setTitle(
            "高级设置（{0}）".format("已展开" if checked else "默认折叠")
        )
        self._refresh_summary()

    # --- 状态 ---

    def formats(self) -> List[str]:
        return [fmt for fmt, box in self._format_boxes.items() if box.isChecked()]

    def scope_kind(self) -> str:
        return str(self._scope_combo.currentData() or SCOPE_PROJECT)

    def selected_chapters(self) -> List[str]:
        chosen = []
        for row in range(self._chapter_list.count()):
            item = self._chapter_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                chosen.append(str(item.data(Qt.ItemDataRole.UserRole) or item.text()))
        return chosen

    def source_mode(self) -> str:
        return str(self._source_combo.currentData() or SOURCE_MODE_CURRENT_BUFFER)

    def request(self) -> ExportRequest:
        """当前表单对应的真实请求（未校验，直接映射既有契约）。"""
        landscape = []
        count = int(self._landscape_count.value())
        if count > 0:
            pool = self.selected_chapters() or self._chapters
            landscape = list(pool[:count])
        return build_export_request(
            project_root=self._project_root,
            formats=self.formats(),
            scope_kind=self.scope_kind(),
            chapters=self.selected_chapters(),
            current_chapter=self._current_chapter,
            source_mode=self.source_mode(),
            destination=self._destination_entry.text().strip(),
            output_name=self._name_entry.text().strip(),
            layout_mode=str(self._layout_combo.currentData() or MODE_TEMPLATE),
            image_width=str(self._image_combo.currentData() or "auto-width"),
            table_width=str(self._table_combo.currentData() or TABLE_KEEP),
            repeat_header=self._repeat_header.isChecked(),
            allow_row_split=self._allow_split.isChecked(),
            page_break_before_chapter=self._page_break.isChecked(),
            landscape_chapters=landscape,
            variant_id=str(self._variant_combo.currentData() or ""),
            include_original=self._include_original.isChecked(),
            strict=self._strict.isChecked(),
        )

    def _refresh_summary(self, *_args) -> None:
        request = self.request()
        self._summary.setText(
            "本次将提交：{0}".format(describe_request(request, total_chapters=len(self._chapters)))
        )
        if not self.formats():
            self._summary.setText(
                self._summary.text() + "（未勾选格式：将按默认 Word 提交）"
            )
        if self.source_mode() == SOURCE_MODE_SAVED and self._unsaved_count:
            self._source_hint.setText(
                "已选择「已保存版本」：当前 {0} 章未保存修改不会纳入本次导出，编辑缓冲保持。".format(
                    self._unsaved_count
                )
            )
        elif self.source_mode() == SOURCE_MODE_CURRENT_BUFFER and self._unsaved_count:
            self._source_hint.setText(
                "将包含 {0} 章未保存修改（读取当前编辑缓冲，不写回源文件）。".format(
                    self._unsaved_count
                )
            )
        else:
            self._source_hint.setText("当前没有未保存修改：两种来源内容一致。")
        if self.scope_kind() == SCOPE_CHAPTERS:
            if self.selected_chapters():
                self._chapter_hint.setText(
                    "已选 {0} 章，将按文档顺序导出。".format(
                        len(self.selected_chapters())
                    )
                )
            elif self._chapters:
                self._chapter_hint.setText(
                    "未勾选任何章节：将按整份文档回退（界面已明示，可直接提交或改选）。"
                )

    def _on_submit(self) -> None:
        self._request = self.request()
        self.accept()

    def apply_request(self, request: ExportRequest) -> None:
        """把已有请求带入表单（旧轮“更改设置”）；只读取真实字段，不反解析文本。"""
        if request is None:
            return
        for fmt, box in self._format_boxes.items():
            box.setChecked(fmt in request.formats)
        index = self._scope_combo.findData(request.scope.kind)
        if index >= 0:
            self._scope_combo.setCurrentIndex(index)
        if request.scope.kind == SCOPE_CURRENT_CHAPTER:
            self._current_chapter = request.scope.current if request.scope.current in self._chapters else ""
            index = self._scope_combo.findData(SCOPE_CURRENT_CHAPTER)
            self._scope_combo.setItemText(
                index, "当前章：{0}".format(Path(self._current_chapter).name or "（原章节已不可用，可改选范围）"),
            )
        chosen = set(request.scope.chapters or [])
        if chosen:
            for row in range(self._chapter_list.count()):
                item = self._chapter_list.item(row)
                value = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
                item.setCheckState(
                    Qt.CheckState.Checked if value in chosen else Qt.CheckState.Unchecked
                )
        index = self._source_combo.findData(request.source_mode)
        if index >= 0:
            self._source_combo.setCurrentIndex(index)
        if request.destination:
            self._destination_entry.setText(request.destination)
        if request.output_name:
            self._name_entry.setText(request.output_name)
        index = self._layout_combo.findData(request.layout_profile)
        if index >= 0:
            self._layout_combo.setCurrentIndex(index)
        layout_data = request.layout or {}
        if isinstance(layout_data, dict):
            index = self._image_combo.findData(str(layout_data.get("image_width") or "auto-width"))
            if index >= 0:
                self._image_combo.setCurrentIndex(index)
            index = self._table_combo.findData(str(layout_data.get("table_width") or TABLE_KEEP))
            if index >= 0:
                self._table_combo.setCurrentIndex(index)
            self._repeat_header.setChecked(bool(layout_data.get("repeat_header", False)))
            self._allow_split.setChecked(bool(layout_data.get("allow_row_split", True)))
            self._page_break.setChecked(
                bool(layout_data.get("page_break_before_chapter", False))
            )
            landscape = list(layout_data.get("landscape_chapters") or [])
            if landscape:
                self._landscape_count.setValue(min(len(landscape), self._landscape_count.maximum()))
        index = self._variant_combo.findData(str(request.variant_id or ""))
        if index >= 0:
            self._variant_combo.setCurrentIndex(index)
        self._include_original.setChecked(bool(request.include_original))
        self._strict.setChecked(bool(request.strict))
        self._refresh_summary()
        # 刷新后再追加“原范围失效”提醒：_refresh_summary 会重写该提示。
        if request.scope.kind == SCOPE_CHAPTERS and request.scope.chapters:
            missing = [c for c in request.scope.chapters if c not in self._chapters]
            if missing:
                self._chapter_hint.setText(
                    "原请求中的部分章节已不可用：{0}（可改选或改用整份）".format(
                        "、".join(missing[:3])
                    )
                )
        elif request.scope.kind == SCOPE_CURRENT_CHAPTER and not self._current_chapter:
            self._chapter_hint.setText("原请求的当前章已不可用：请改选章节或整份；直接提交将按整份文档回退。")

    def submitted_request(self) -> Optional[ExportRequest]:
        return self._request


__all__ = [
    "FORMAT_CHOICES",
    "ExportSettingsDialog",
    "build_export_request",
    "describe_request",
]
