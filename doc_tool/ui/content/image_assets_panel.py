# -*- coding: utf-8 -*-
"""图片资源面板：未使用资源清理与缺失引用修复。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.asset_manager import list_missing, scan_unused


class ImageAssetsPanel(QWidget):
    """展示可安全清理图片与悬空图片引用。"""

    def __init__(
        self,
        index,
        *,
        assets_root,
        writer,
        on_changed: Optional[Callable[[], None]] = None,
        on_open: Optional[Callable[[str, int], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._assets_root = Path(assets_root) if assets_root is not None else None
        self._writer = writer
        self._on_changed = on_changed
        self._on_open = on_open
        self._writable = writable

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        unused_header = QHBoxLayout()
        unused_header.addWidget(QLabel("未使用图片（勾选后移入可回滚回收站）", self))
        unused_header.addStretch(1)
        self._clean_btn = QPushButton("清理勾选", self)
        self._clean_btn.setProperty("btnRole", "secondary")
        self._clean_btn.clicked.connect(self.clean_checked)
        unused_header.addWidget(self._clean_btn)
        outer.addLayout(unused_header)

        self._unused = QTreeWidget(self)
        self._unused.setHeaderLabels(["资源", "大小"])
        self._unused.setRootIsDecorated(False)
        outer.addWidget(self._unused, 1)

        missing_header = QHBoxLayout()
        missing_header.addWidget(QLabel("缺失图片引用", self))
        missing_header.addStretch(1)
        self._repoint_btn = QPushButton("重新指向", self)
        self._repoint_btn.setProperty("btnRole", "compact")
        self._repoint_btn.clicked.connect(self.repoint_selected)
        missing_header.addWidget(self._repoint_btn)
        self._remove_ref_btn = QPushButton("删除引用行", self)
        self._remove_ref_btn.setProperty("btnRole", "compact")
        self._remove_ref_btn.clicked.connect(self.remove_reference_line)
        missing_header.addWidget(self._remove_ref_btn)
        outer.addLayout(missing_header)

        self._missing = QTreeWidget(self)
        self._missing.setHeaderLabels(["文件", "行", "缺失目标"])
        self._missing.setRootIsDecorated(False)
        self._missing.itemActivated.connect(self._open_missing)
        outer.addWidget(self._missing, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("statusMuted")
        outer.addWidget(self._status)
        self.refresh()

    def set_index(self, index) -> None:
        self._index = index
        self.refresh()

    def refresh(self) -> None:
        self._unused.clear()
        self._missing.clear()
        if self._assets_root is None:
            self._status.setText("资源目录未配置")
            self._set_actions(False)
            return
        unused = scan_unused(self._assets_root, self._index)
        for rel_path, size in unused:
            item = QTreeWidgetItem([rel_path, self._format_size(size)])
            item.setData(0, Qt.ItemDataRole.UserRole, rel_path)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self._unused.addTopLevelItem(item)
        missing = list_missing(self._index, self._assets_root)
        for ref in missing:
            item = QTreeWidgetItem([ref.source, str(ref.line), ref.target])
            item.setData(0, Qt.ItemDataRole.UserRole, ref)
            self._missing.addTopLevelItem(item)
        self._status.setText(
            "未使用 {0} 项 · 缺失引用 {1} 项".format(len(unused), len(missing))
        )
        self._set_actions(self._writable)

    def _set_actions(self, enabled: bool) -> None:
        self._clean_btn.setEnabled(enabled)
        self._repoint_btn.setEnabled(enabled)
        self._remove_ref_btn.setEnabled(enabled)

    def clean_checked(self) -> None:
        selected = []
        for row in range(self._unused.topLevelItemCount()):
            item = self._unused.topLevelItem(row)
            if item.checkState(0) == Qt.CheckState.Checked:
                selected.append(item.data(0, Qt.ItemDataRole.UserRole))
        if not selected or not self._writable:
            return
        answer = QMessageBox.question(
            self,
            "清理未使用图片",
            "将 {0} 个未使用图片移入回收站（可在改动面板回滚），确认？".format(
                len(selected)
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        failures = []
        for rel_path in selected:
            result = self._writer.delete_asset(rel_path)
            if not result.written:
                failures.append("{0}: {1}".format(rel_path, result.error or "删除失败"))
        self._notify_changed()
        if failures:
            # _notify_changed → on_changed → workspace._after_write → set_index
            # → refresh() 会把状态覆盖为「未使用 N 项…」：失败明细必须在其后
            # 重新写入，否则用户看不到哪些图片删除失败。
            self._status.setText("部分失败：" + "; ".join(failures))
        else:
            self._status.setText("清理完成")

    def repoint_selected(self) -> None:
        ref = self._selected_missing()
        if ref is None or not self._writable or self._assets_root is None:
            return
        entry = self._index.files.get(ref.source)
        doc_type = entry.document_type if entry is not None else "general"
        start_dir = self._assets_root / doc_type / "images"
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择替代图片",
            str(start_dir),
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg);;全部文件 (*)",
        )
        if not path:
            return
        selected = Path(path).resolve()
        base = (self._assets_root / doc_type).resolve()
        try:
            replacement = selected.relative_to(base).as_posix()
        except ValueError:
            QMessageBox.warning(self, "重新指向失败", "请选择当前文档类型资源目录内的图片。")
            return
        self._rewrite_reference(ref, replacement=replacement)

    def remove_reference_line(self) -> None:
        ref = self._selected_missing()
        if ref is not None and self._writable:
            self._rewrite_reference(ref, replacement=None)

    def _rewrite_reference(self, ref, replacement: Optional[str]) -> None:
        try:
            path = self._writer.resolve(ref.source)
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self._status.setText("读取失败：{0}".format(exc))
            return
        lines = text.splitlines(keepends=True)
        index = ref.line - 1
        if not 0 <= index < len(lines):
            self._status.setText("引用行已变化，请刷新后重试")
            return
        if replacement is None:
            del lines[index]
        else:
            # 仅替换图片目标，保留 alt 文本与尺寸后缀。
            pattern = re.compile(r"(!\[[^\]]*\]\()" + re.escape(ref.target) + r"(?=[\s)])")
            updated, count = pattern.subn(r"\1" + replacement, lines[index], count=1)
            if count == 0:
                self._status.setText("引用内容已变化，请刷新后重试")
                return
            lines[index] = updated
        result = self._writer.write_text(ref.source, "".join(lines))
        if not result.written:
            self._status.setText("修复失败：{0}".format(result.error or "写入失败"))
            return
        if getattr(result, "backup_failed", False):
            self._status.setText("缺失引用已修复（⚠ 备份失败，回滚不可用）")
        else:
            self._status.setText("缺失引用已修复")
        self._notify_changed()

    def _notify_changed(self) -> None:
        if self._on_changed is not None:
            self._on_changed()
        else:
            self.refresh()

    def _selected_missing(self):
        item = self._missing.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def _open_missing(self, item, _column=0) -> None:
        if item is None or self._on_open is None:
            return
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if ref is not None:
            self._on_open(ref.source, ref.line)

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return "{0} B".format(size)
        if size < 1024 * 1024:
            return "{0:.1f} KB".format(size / 1024.0)
        return "{0:.1f} MB".format(size / (1024.0 * 1024.0))
