# -*- coding: utf-8 -*-
"""图片资源面板：未使用资源清理与缺失引用修复。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.asset_manager import (
    _buffer_referenced_paths,
    import_image_data,
    list_missing,
    next_image_name,
    scan_unused,
)


def _image_target_pattern(target: str):
    """匹配指向 ``target`` 的图片引用前缀 ``![alt](``（保留 alt/尺寸）。"""
    return re.compile(
        r"(!\[[^\]]*\]\(\s*)" + re.escape(str(target)) + r"(?=[\s)=]|$)"
    )


def _image_expression_pattern(target: str):
    """匹配整段图片表达 ``![alt](target =WxH)``（移除所选引用时用）。"""
    return re.compile(
        r"!\[[^\]]*\]\(\s*" + re.escape(str(target)) + r"(?:\s+=\d+x\d+)?\s*\)"
    )


class ImageAssetsPanel(QWidget):
    """展示可安全清理图片与悬空图片引用（叠加活缓冲的当前引用）。

    ``buffer_texts``（映射或返回映射的可调用对象）给出未保存的编辑器正文，
    清单/缺失/未用扫描据此叠加“当前引用”；``live_text_provider`` 与
    ``buffer_applier`` 用于把单项修复写进已打开章节的编辑缓冲（一次撤销），
    未打开章节走原写入服务（ContentWriter）。
    """

    def __init__(
        self,
        index,
        *,
        assets_root,
        writer,
        on_changed: Optional[Callable[[], None]] = None,
        on_open: Optional[Callable[[str, int], None]] = None,
        writable: bool = True,
        is_dirty=None,
        buffer_texts=None,
        live_text_provider: Optional[Callable[[str], Optional[str]]] = None,
        buffer_applier: Optional[Callable[[str, str], bool]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._assets_root = Path(assets_root) if assets_root is not None else None
        self._writer = writer
        self._on_changed = on_changed
        self._on_open = on_open
        self._writable = writable
        self._is_dirty = is_dirty
        self._buffer_texts = buffer_texts
        self._live_text_provider = live_text_provider
        self._buffer_applier = buffer_applier

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)
        self._inventory = QTreeWidget(self)
        self._inventory.setHeaderLabels(['资源（不自动删除）', '尺寸 / 体积', '引用章节:行', '相同字节候选'])
        self._inventory.itemActivated.connect(lambda item, _: self._on_open(*item.data(0, Qt.UserRole)) if self._on_open and item.data(0, Qt.UserRole) else None)
        outer.addWidget(self._inventory, 1)

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
        self._batch_btn = QPushButton('同一缺图批量修复…', self)
        self._batch_btn.clicked.connect(self.batch_repair)
        missing_header.addWidget(self._batch_btn)
        self._remove_ref_btn = QPushButton("移除所选引用", self)
        self._remove_ref_btn.setProperty("btnRole", "compact")
        self._remove_ref_btn.clicked.connect(self.remove_reference_line)
        missing_header.addWidget(self._remove_ref_btn)
        outer.addLayout(missing_header)

        self._missing = QTreeWidget(self)
        self._missing.setHeaderLabels(["文件", "行", "缺失目标", "依据"])
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

    def _buffer_texts_map(self) -> dict:
        """当前未保存编辑器正文；provider 不可用时按无缓冲处理。"""
        source = self._buffer_texts
        if source is None:
            return {}
        try:
            data = source() if callable(source) else source
        except Exception:  # noqa: BLE001 - 读取缓冲失败不阻断清单
            return {}
        return {str(key): str(value) for key, value in dict(data or {}).items()}

    def _in_buffer_refs(self, rel_asset_path: str, buffer_refs) -> bool:
        """该资源是否被活缓冲引用（``<类型>/images/<名>``）。"""
        parts = str(rel_asset_path).split("/", 1)
        if len(parts) != 2:
            return False
        doc_type, target = parts
        return (doc_type, target) in buffer_refs or (doc_type, target.rsplit("/", 1)[-1]) in buffer_refs

    @staticmethod
    def _ref_is_live(ref, buffers) -> bool:
        """该缺失引用是否落在编辑器当前正文的同一行上。"""
        text = (buffers or {}).get(ref.source)
        if not text:
            return False
        lines = str(text).splitlines()
        if not 0 <= ref.line - 1 < len(lines):
            return False
        return bool(_image_target_pattern(ref.target).search(lines[ref.line - 1]))

    def _doc_type_for(self, rel_path: str) -> str:
        entry = self._index.files.get(rel_path)
        if entry is not None and getattr(entry, "document_type", ""):
            return entry.document_type
        return next(iter(self._index.document_types), "general")

    def refresh(self) -> None:
        self._unused.clear()
        self._missing.clear()
        self._inventory.clear()
        if self._assets_root is None:
            self._status.setText("资源目录未配置")
            self._set_actions(False)
            return
        # MAIN2-D 4.1：清单/缺失/未用扫描都叠加未保存编辑器正文的当前引用
        # （只读内存文本、不写盘）：磁盘尚无引用的新插图不得被列为可清理。
        buffers = self._buffer_texts_map()
        buffer_refs = _buffer_referenced_paths(self._index, buffers)
        unused = scan_unused(self._assets_root, self._index, buffer_texts=buffers)
        from doc_tool.application.content.asset_batch import asset_inventory
        for row in asset_inventory(self._assets_root, self._index):
            references = '; '.join(f'{rel}:{line}' for rel, line in row['references'])
            if not row['references'] and self._in_buffer_refs(row['path'], buffer_refs):
                references = '编辑器当前内容（未保存）'
            item = QTreeWidgetItem([row['path'], row['dimensions'] + ' / ' + self._format_size(row['bytes']),
                references, ', '.join(row['duplicates'])])
            item.setData(0, Qt.UserRole, row['references'][0] if row['references'] else None)
            self._inventory.addTopLevelItem(item)
        for rel_path, size in unused:
            item = QTreeWidgetItem([rel_path, self._format_size(size)])
            item.setData(0, Qt.ItemDataRole.UserRole, rel_path)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self._unused.addTopLevelItem(item)
        missing = list_missing(self._index, self._assets_root, buffer_texts=buffers)
        shown_missing = 0
        for ref in missing:
            # 已打开章节按编辑器当前正文判定：当前内容已不含该引用（例如刚在
            # 缓冲里改好）时不再显示磁盘旧行，避免误导重复修复。
            if ref.source in buffers and not self._ref_is_live(ref, buffers):
                continue
            origin = "编辑器当前内容" if self._ref_is_live(ref, buffers) else "磁盘索引"
            item = QTreeWidgetItem([ref.source, str(ref.line), ref.target, origin])
            item.setData(0, Qt.ItemDataRole.UserRole, ref)
            self._missing.addTopLevelItem(item)
            shown_missing += 1
        if buffers:
            basis = "依据：磁盘索引 + {0} 个未保存编辑器缓冲（当前引用已计入）".format(len(buffers))
        else:
            basis = "依据：磁盘索引（编辑器当前无未保存内容）"
        self._status.setText(
            "未使用 {0} 项 · 缺失引用 {1} 项 · {2}".format(len(unused), shown_missing, basis)
        )
        self._set_actions(self._writable)

    def _set_actions(self, enabled: bool) -> None:
        self._clean_btn.setEnabled(enabled)
        self._repoint_btn.setEnabled(enabled)
        self._remove_ref_btn.setEnabled(enabled)
        self._batch_btn.setEnabled(enabled)

    def batch_repair(self):
        ref = self._selected_missing()
        if ref is None or not self._writable: return
        selected, _ = QFileDialog.getOpenFileName(self, '选择正确图片（项目外图片将导入）', str(self._assets_root), '图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)')
        if not selected: return
        from doc_tool.application.content.asset_batch import AssetBatchService
        service = AssetBatchService(self._writer, self._index, is_dirty=self._is_dirty)
        chosen = Path(selected).resolve()
        rows, imported = [], {}
        try:
            for doc_type in self._index.document_types:
                base = (self._assets_root / doc_type).resolve()
                try: replacement = chosen.relative_to(base).as_posix()
                except ValueError:
                    replacement = 'images/' + next_image_name(self._assets_root, doc_type, chosen.suffix)
                    target = self._assets_root / doc_type / replacement
                    imported[target] = chosen.read_bytes()
                rows.extend(row for row in service.plan(ref.target, replacement) if self._index.files[row.source].document_type == doc_type)
            # MAIN2-D 4.3：预览按当前工作集（磁盘 + 活缓冲）列出将改动的实际
            # 引用；有未保存编辑的章节只列出并标为跳过，不写过期磁盘范围。
            plan_rows = self._batch_preview(rows, ref.target)
            if not plan_rows:
                self._status.setText('当前没有可修复的引用，请刷新后重试')
                return
            dialog = QDialog(self)
            dialog.setWindowTitle('预览具体引用替换（勾选应用）')
            layout = QVBoxLayout(dialog)
            tree = QTreeWidget()
            tree.setHeaderLabels(['章节:行', '将改动的实际引用（只改所选引用，保留同行其他内容）', '依据'])
            for row in plan_rows:
                item = QTreeWidgetItem([row['source'] + ':' + str(row['line']), row['label'], row['origin']])
                if row['edit'] is None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                else:
                    item.setCheckState(0, Qt.Checked)
                tree.addTopLevelItem(item)
            layout.addWidget(tree)
            buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Apply).clicked.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.resize(800, 500)
            if dialog.exec() != QDialog.Accepted: return
            edits, withheld = [], []
            for n, row in enumerate(plan_rows):
                if row['edit'] is None:
                    withheld.append(row['source'] + ':' + str(row['line']))
                    continue
                row['edit'].selected = tree.topLevelItem(n).checkState(0) == Qt.CheckState.Checked
                edits.append(row['edit'])
            result = service.apply(edits, confirmed=True, imported=imported)
            self._notify_changed()
            applied_refs = sum(1 for edit in edits if edit.selected and edit.source in result['applied'])
            skipped_refs = len(withheld) + sum(
                1 for edit in edits if edit.selected and edit.source not in result['applied'])
            detail = '；'.join(result['warnings']) if result['warnings'] else '脏编辑/外部变化项已保留'
            self._status.setText(
                '已处理 {0} 章 / {1} 处引用；跳过 {2} 处（{3}），刷新后可重试'.format(
                    len(result['applied']), applied_refs, skipped_refs, detail))
        except (OSError, ValueError) as exc: self._status.setText('批量修复失败，已回滚：' + str(exc))

    def _batch_preview(self, rows, missing_target):
        """按当前内容列出将改动的实际引用；有未保存编辑的源项标为跳过。"""
        from doc_tool.domain.markdown_structure import prose_lines
        buffers = self._buffer_texts_map()
        by_source = {}
        for row in rows:
            by_source.setdefault(row.source, []).append(row)
        plan = []
        for source in sorted(set(by_source) | set(buffers)):
            dirty = bool(self._is_dirty(source)) if callable(self._is_dirty) else False
            if dirty and buffers.get(source) is not None:
                pattern = _image_target_pattern(missing_target)
                for line_no, line in prose_lines(buffers[source]):
                    if not pattern.search(line):
                        continue
                    plan.append({
                        'source': source, 'line': line_no, 'edit': None,
                        'origin': '编辑器当前内容',
                        'label': '（跳过：当前章有未保存编辑；未保存引用请用「重新指向」单项修复）',
                    })
                continue
            for row in by_source.get(source, []):
                plan.append({
                    'source': source, 'line': row.line, 'edit': row, 'origin': '磁盘索引',
                    'label': row.old + ' → ' + row.replacement,
                })
        return plan

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

    def replace_missing_reference(self, ref, source_image) -> bool:
        """把一条缺失引用指向用户选定的图片（项目外图片按原服务入库，MAIN2-D 4.2）。

        打开中的章节写入编辑器缓冲（Ctrl+Z 一次撤销），未打开章节走原写入
        服务；只改所选引用，保留 alt/尺寸与同行其它内容。
        """
        if ref is None or not self._writable or self._assets_root is None:
            return False
        chosen = Path(source_image)
        try:
            chosen = chosen.resolve()
        except OSError as exc:  # noqa: BLE001 - 路径不可解析时给出原因
            self._status.setText('选择的图片不可读：{0}'.format(exc))
            return False
        if not chosen.is_file():
            self._status.setText('选择的图片不存在')
            return False
        doc_type = self._doc_type_for(ref.source)
        base = (self._assets_root / doc_type).resolve()
        try:
            replacement = chosen.relative_to(base).as_posix()
        except ValueError:
            replacement = self._import_external_image(chosen, doc_type)
            if replacement is None:
                return False
        return self._apply_reference_change(ref, replacement)

    def _import_external_image(self, chosen, doc_type):
        """项目外图片入库：复用 next_image_name/import_image_data 的命名与校验。"""
        ext = chosen.suffix.lstrip('.').lower() or 'png'
        try:
            data = chosen.read_bytes()
        except OSError as exc:
            self._status.setText('读取选择的图片失败：{0}'.format(exc))
            return None
        try:
            replacement, _width, _height = import_image_data(data, self._assets_root, doc_type, ext)
            return replacement
        except ValueError:
            if ext != 'svg':
                self._status.setText('选择的图片无法识别（支持 PNG/JPEG/GIF/BMP/WebP/SVG）')
                return None
        except OSError as exc:
            self._status.setText('导入图片失败：{0}'.format(exc))
            return None
        # SVG 等非位图沿用 next_image_name 原样入库（不做像素尺寸校验）。
        try:
            name = next_image_name(self._assets_root, doc_type, ext)
            images = self._assets_root / doc_type / 'images'
            images.mkdir(parents=True, exist_ok=True)
            (images / name).write_bytes(data)
        except OSError as exc:
            self._status.setText('导入图片失败：{0}'.format(exc))
            return None
        return 'images/' + name

    def repoint_selected(self) -> None:
        ref = self._selected_missing()
        if ref is None or not self._writable or self._assets_root is None:
            return
        doc_type = self._doc_type_for(ref.source)
        start_dir = self._assets_root / doc_type / "images"
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择替代图片（项目外图片将导入）",
            str(start_dir),
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg);;全部文件 (*)",
        )
        if not path:
            return
        self.replace_missing_reference(ref, Path(path))

    def remove_reference_line(self) -> None:
        """移除所选图片表达；同行其他正文/图片保留（MAIN2-D 4.3）。"""
        ref = self._selected_missing()
        if ref is not None and self._writable:
            self._apply_reference_change(ref, None)

    def _current_text(self, rel_path: str):
        """返回 ``(当前正文, 是否来自编辑器缓冲)``；未打开时读磁盘。"""
        provider = self._live_text_provider
        if provider is not None:
            try:
                text = provider(rel_path)
            except Exception:  # noqa: BLE001 - 编辑器不可读时退回磁盘正文
                text = None
            if isinstance(text, str):
                return text, True
        return self._writer.resolve(rel_path).read_text(encoding="utf-8"), False

    def _locate_reference(self, text: str, ref) -> Optional[int]:
        """在当前正文里定位引用行；行号漂移时只在唯一命中处修改。"""
        lines = str(text).splitlines(keepends=True)
        pattern = _image_target_pattern(ref.target)
        matches = [number for number, line in enumerate(lines) if pattern.search(line)]
        if not matches:
            return None
        preferred = ref.line - 1
        if preferred in matches:
            return preferred
        return matches[0] if len(matches) == 1 else None

    def _apply_reference_change(self, ref, replacement: Optional[str]) -> bool:
        """只改所选引用：保留 alt/尺寸与同行其它内容（MAIN2-D 4.2）。"""
        try:
            text, from_buffer = self._current_text(ref.source)
        except (OSError, UnicodeError) as exc:
            self._status.setText("读取失败：{0}".format(exc))
            return False
        lines = str(text).splitlines(keepends=True)
        position = self._locate_reference(text, ref)
        if position is None:
            self._status.setText("引用内容已变化，请刷新后重试")
            return False
        if replacement is None:
            updated, count = _image_expression_pattern(ref.target).subn("", lines[position], count=1)
        else:
            updated, count = _image_target_pattern(ref.target).subn(
                lambda match: match.group(1) + replacement, lines[position], count=1)
        if count == 0:
            self._status.setText("引用内容已变化，请刷新后重试")
            return False
        lines[position] = updated
        new_text = "".join(lines)
        if self._buffer_applier is not None:
            try:
                applied = bool(self._buffer_applier(ref.source, new_text))
            except Exception:  # noqa: BLE001 - 缓冲写入失败按未应用处理
                applied = False
            if applied:
                self._status.setText(
                    "已在编辑器缓冲中移除所选引用（Ctrl+Z 可一次撤销）" if replacement is None
                    else "已在编辑器缓冲中修复 1 处引用（Ctrl+Z 可一次撤销）")
                self._notify_changed()
                return True
            if from_buffer:
                # 缓冲是唯一真实内容：退回磁盘写会覆盖未保存正文，必须停手。
                self._status.setText("编辑器缓冲写入失败，未改动磁盘，请刷新后重试")
                return False
        result = self._writer.write_text(ref.source, new_text)
        if not result.written:
            self._status.setText("修复失败：{0}".format(result.error or "写入失败"))
            return False
        if getattr(result, "backup_failed", False):
            self._status.setText("缺失引用已修复（⚠ 备份失败，回滚不可用）")
        elif replacement is None:
            self._status.setText("已移除所选引用（同行其他内容保留）")
        else:
            self._status.setText("缺失引用已修复")
        self._notify_changed()
        return True

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
