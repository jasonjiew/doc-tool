# -*- coding: utf-8 -*-
"""正文模块库与引用解析入口（V3.0 30-F 6.1/6.2）。

界面只做入口与展示，能力全部复用既有服务：

- 模块库：列表 / 搜索 / 预览（``reuse_commands.list_modules`` / ``show_module``）；
- 本项目引用解析报告（``resolve_project`` + ``render_report``），来源、版本、定位都在报告里；
- 变体有效范围（``variant_evidence``）；
- 生成展开副本（``write_expanded_copy``），交给旧应用或外部作者。

不做新的编辑器，也不在界面上暴露内部 hash/schema 术语（技术细节留在报告文本里）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from doc_tool.application.content import reuse_commands as reuse


class ReuseDialog(QDialog):
    """模块库与引用解析对话框（只读展示 + 展开副本导出）。"""

    def __init__(self, project_root, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.setWindowTitle("正文模块库与引用解析")
        self.resize(980, 620)
        self._context = None
        self._rows: List[Dict[str, object]] = []
        self._build_ui()
        self.reload()

    # --- 构建 ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("搜索模块（名称 / 标识 / 标签）")
        self.search_input.textChanged.connect(lambda _text: self.reload())
        top.addWidget(self.search_input, 1)
        self.reload_button = QPushButton("刷新", self)
        self.reload_button.clicked.connect(self.reload)
        top.addWidget(self.reload_button)
        self.copy_button = QPushButton("生成展开副本…", self)
        self.copy_button.setToolTip("导出普通 Markdown 副本（不含模块引用标记），可搬目录打开")
        self.copy_button.clicked.connect(self.export_expanded_copy)
        top.addWidget(self.copy_button)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.module_list = QListWidget(splitter)
        self.module_list.currentRowChanged.connect(self._show_selected_module)
        splitter.addWidget(self.module_list)
        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("变体：", right))
        self.variant_combo = QComboBox(right)
        self.variant_combo.currentIndexChanged.connect(lambda _index: self.refresh_report())
        variant_row.addWidget(self.variant_combo, 1)
        self.report_button = QPushButton("解析本项目引用", right)
        self.report_button.clicked.connect(self.refresh_report)
        variant_row.addWidget(self.report_button)
        right_layout.addLayout(variant_row)
        self.preview = QPlainTextEdit(right)
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("选择左侧模块查看预览，或点「解析本项目引用」查看展开报告")
        right_layout.addWidget(self.preview, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("", self)
        bottom.addWidget(self.status_label, 1)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.reject)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

    # --- 数据 ---

    def _ensure_context(self):
        if self._context is None:
            self._context = reuse.load_context(self.project_root)
        return self._context

    def reload(self) -> None:
        try:
            library = reuse.load_library(self.project_root)
            payload = reuse.list_modules(library, query=self.search_input.text().strip())
        except Exception as exc:  # noqa: BLE001 - 库不可用时给出明确说明
            self.status_label.setText("模块库不可用：{0}".format(exc))
            self.module_list.clear()
            return
        self._rows = [row for row in (payload.get("modules") or []) if isinstance(row, dict)]
        self.module_list.clear()
        for row in self._rows:
            label = "{0}（{1}）".format(row.get("title") or row.get("moduleId"), row.get("version"))
            item = QListWidgetItem(label, self.module_list)
            item.setToolTip(str(row.get("description") or ""))
        self.status_label.setText("共 {0} 个模块".format(len(self._rows)))
        self._reload_variants()

    def _reload_variants(self) -> None:
        self.variant_combo.blockSignals(True)
        self.variant_combo.clear()
        self.variant_combo.addItem("（不使用变体）", "")
        try:
            context = self._ensure_context()
            for variant in getattr(context, "variants", None) or []:
                name = getattr(variant, "name", "") or getattr(variant, "variantId", "")
                variant_id = getattr(variant, "variantId", "") or name
                self.variant_combo.addItem(str(name), str(variant_id))
        except Exception:  # noqa: BLE001 - 无变体声明时保持空
            pass
        self.variant_combo.blockSignals(False)

    def _show_selected_module(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._rows):
            return
        row = self._rows[row_index]
        try:
            library = reuse.load_library(self.project_root)
            payload = reuse.show_module(
                library, str(row.get("moduleId") or ""), str(row.get("version") or ""),
                with_body=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.preview.setPlainText("无法读取模块：{0}".format(exc))
            return
        lines = [
            "模块：{0}（{1}）".format(payload.get("title") or row.get("moduleId"), payload.get("version")),
            "参数：{0}".format("、".join(payload.get("parameters") or []) or "无"),
            "资源：{0}".format("、".join(payload.get("resources") or []) or "无"),
            "",
        ]
        body = payload.get("body") or payload.get("preview") or ""
        lines.append(str(body))
        self.preview.setPlainText("\n".join(lines))

    # --- 报告与副本 ---

    def refresh_report(self) -> None:
        variant_id = str(self.variant_combo.currentData() or "")
        try:
            context = self._ensure_context()
            if variant_id:
                payload = reuse.variant_evidence(context, variant_id)
                if payload.get("ok"):
                    report = reuse.resolve_project(
                        context, variant_id=variant_id, record_instances=True,
                    )
                else:
                    report = payload
            else:
                # 面板解析同时把实例映射落盘并输出覆盖率（V3.0 4.3）
                report = reuse.resolve_project(context, record_instances=True)
            self.preview.setPlainText(reuse.render_report(report, output="human"))
            self.status_label.setText("已解析本项目引用（{0}）".format(
                "变体 " + variant_id if variant_id else "整份"
            ))
        except Exception as exc:  # noqa: BLE001 - 解析失败给明确原因
            self.preview.setPlainText("引用解析未完成：{0}".format(exc))
            self.status_label.setText("引用解析未完成")

    def export_expanded_copy(self) -> None:
        target = QFileDialog.getExistingDirectory(self, "选择展开副本目录")
        if not target:
            return
        variant_id = str(self.variant_combo.currentData() or "")
        try:
            context = self._ensure_context()
            result = reuse.write_expanded_copy(context, target, variant_id=variant_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "展开副本未生成", str(exc))
            return
        message = "已生成展开副本：{0}".format(result.get("path") or target)
        warnings = list(result.get("warnings") or [])[:3]
        if warnings:
            message += "\n提醒：" + "；".join(str(item) for item in warnings)
        self.status_label.setText(message.splitlines()[0])
        QMessageBox.information(self, "展开副本", message)


__all__ = ["ReuseDialog"]