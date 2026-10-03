# -*- coding: utf-8 -*-
"""全局替换面板（底部工具面板）。

默认逐项确认：命中列表 + 选中行的"前/后"diff 预览，"替换此项/跳过此条"
逐条处理。"全部替换"为显式选项，先汇总再经确认对话框批量写回。

写回经 ``ReplaceService.apply_matches``（每文件 .md.bak + 改动清单），
完成后回调 ``on_applied`` 由主窗口触发校验管线检测悬空引用。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.replace import (
    ReplaceMatch,
    ReplacePreview,
    ReplaceService,
    diff_line,
)

# 文档类型过滤下拉（与搜索面板一致）；仅旧版多类型布局展示。
_TYPE_FILTERS = (
    ("全部", None),
    ("需求文档（旧版专用）", "requirement"),
    ("详细设计文档（旧版专用）", "design"),
    ("通用大文档", "general"),
)

#: MAIN-B 2.1 替换范围：范围是用户显式动作，默认整份文档（与既有行为一致）。
SCOPE_DOCUMENT = "document"
SCOPE_CURRENT = "current"
SCOPE_SELECTED = "selected"
_SCOPE_LABELS = (
    ("整份文档", SCOPE_DOCUMENT),
    ("当前章", SCOPE_CURRENT),
    ("所选章", SCOPE_SELECTED),
)


class ReplaceTreeItem(QTreeWidgetItem):
    """支持按自然路径与数值行号排序的替换树条目。"""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree is not None else 0
        if col < 0:
            col = 0
        if col == 0:
            from doc_tool.domain.content_index import path_natural_sort_key
            k1 = path_natural_sort_key(self.text(0))
            k2 = path_natural_sort_key(other.text(0))
            if k1 != k2:
                return k1 < k2
            try:
                return int(self.text(1)) < int(other.text(1))
            except ValueError:
                return self.text(1) < other.text(1)
        if col == 1:
            try:
                return int(self.text(1)) < int(other.text(1))
            except ValueError:
                pass
        return self.text(col) < other.text(col)


class ReplacePanel(QWidget):
    """全局替换面板。

    ``writer``：``ContentWriter``；``on_applied``：一批替换写回后回调
    （主窗口据此触发校验管线）。
    """

    def __init__(
        self,
        service: ReplaceService,
        writer,
        *,
        on_applied: Optional[Callable[[], None]] = None,
        writable: bool = True,
        show_type_filter: bool = True,
        scope_provider: Optional[Callable[[], Tuple[str, Optional[str], List[str]]]] = None,
        live_text_provider: Optional[Callable[[str], Optional[str]]] = None,
        buffer_applier: Optional[Callable[[str, str], bool]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._writer = writer
        self._on_applied = on_applied
        self._writable = writable
        # MAIN-B 2.1：范围与活缓冲接入。
        # - ``scope_provider`` 返回 (范围种类, 当前章, 所选章)；
        # - ``live_text_provider`` 返回某章未保存的缓冲正文（None 表示无缓冲）；
        # - ``buffer_applier`` 把替换结果写回活缓冲（失败时保留磁盘与缓冲）。
        self._scope_provider = scope_provider
        self._live_text_provider = live_text_provider
        self._buffer_applier = buffer_applier
        self._scope_paths: Optional[List[str]] = None
        self._text_overrides: Dict[str, str] = {}
        self._scope_note = "整份文档"
        # 通用单项目不展示需求/设计类型筛选；仅旧版多类型布局保留兼容过滤。
        self._show_type_filter = show_type_filter
        self._matches: List[ReplaceMatch] = []
        self._preview: Optional[ReplacePreview] = None
        # 「回滚本次替换」的起点：本次会话开始前的清单条目数，避免把同会话
        # 更早的编辑/保存一并回滚。
        # 「回滚本次替换」：armed 表示已执行过查找；_replaced_files 记录
        # 本次替换会话实际写过的文件（回滚只恢复这些文件到写前内容，
        # 不受改动清单去重移动条目位置的影响）。
        self._rollback_armed = False
        self._replaced_files: set = set()

        # 唯一外层布局：输入卡片 + diff 卡片 + 命中表 + 操作行。原先各
        # _build_* 各自创建 QVBoxLayout(self)，只有第一个会被安装，diff
        # 预览与命中表因此不可见。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 4, 4, 4)
        self._outer.setSpacing(4)
        self._build_inputs()
        self._build_diff()
        self._build_results()

    # --- 构建 ---

    def _build_inputs(self) -> None:
        inputs = QFrame(self)
        inputs.setProperty("card", True)
        layout = QVBoxLayout(inputs)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(QLabel("查找：", inputs))
        self._find_entry = QLineEdit(inputs)
        row1.addWidget(self._find_entry, 1)
        row1.addWidget(QLabel("替换为：", inputs))
        self._replace_entry = QLineEdit(inputs)
        row1.addWidget(self._replace_entry, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        self._regex_cb = QCheckBox("正则", inputs)
        self._case_cb = QCheckBox("区分大小写", inputs)
        self._word_cb = QCheckBox("整词", inputs)
        row2.addWidget(self._regex_cb)
        row2.addWidget(self._case_cb)
        row2.addWidget(self._word_cb)
        row2.addWidget(QLabel("范围：", inputs))
        self._scope_box = QComboBox(inputs)
        for label, value in _SCOPE_LABELS:
            self._scope_box.addItem(label, value)
        self._scope_box.setToolTip(
            "查找替换范围；当前章/所选章包含未保存正文，替换落在编辑缓冲（可撤销）"
        )
        row2.addWidget(self._scope_box)
        self._type_box = QComboBox(inputs)
        self._type_box.addItems([label for label, _ in _TYPE_FILTERS])
        self._type_box.setVisible(self._show_type_filter)
        row2.addWidget(self._type_box)
        row2.addStretch(1)
        self._find_btn = QPushButton("查找全部", inputs)
        self._find_btn.setProperty("btnRole", "secondary")
        self._find_btn.clicked.connect(self.find_all)
        row2.addWidget(self._find_btn)
        layout.addLayout(row2)

        self._outer.addWidget(inputs)

    def _build_diff(self) -> None:
        diff_frame = QFrame(self)
        diff_frame.setProperty("card", True)
        layout = QVBoxLayout(diff_frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self._before_text = self._make_readonly()
        layout.addWidget(self._before_text)
        arrow = QLabel("↓ 替换为", diff_frame)
        arrow.setObjectName("statusMuted")
        layout.addWidget(arrow)
        self._after_text = self._make_readonly()
        layout.addWidget(self._after_text)

        self._outer.addWidget(diff_frame)

    def _build_results(self) -> None:
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["文件", "行", "原文"])
        self._tree.setColumnWidth(0, 260)
        self._tree.setColumnWidth(1, 48)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tree.currentItemChanged.connect(lambda _a, _b: self._update_diff())

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._replace_one_btn = QPushButton("替换此项", self)
        self._replace_one_btn.setProperty("btnRole", "primary")
        self._replace_one_btn.clicked.connect(self.replace_one)
        actions.addWidget(self._replace_one_btn)
        self._skip_btn = QPushButton("跳过此条", self)
        self._skip_btn.setProperty("btnRole", "secondary")
        self._skip_btn.clicked.connect(self.skip_one)
        actions.addWidget(self._skip_btn)
        self._replace_all_btn = QPushButton("全部替换…", self)
        self._replace_all_btn.setProperty("btnRole", "secondary")
        self._replace_all_btn.clicked.connect(self.replace_all)
        actions.addWidget(self._replace_all_btn)
        actions.addStretch(1)
        self._rollback_btn = QPushButton("回滚本次替换", self)
        self._rollback_btn.setProperty("btnRole", "compact")
        self._rollback_btn.clicked.connect(self.rollback)
        actions.addWidget(self._rollback_btn)
        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.setProperty("btnRole", "compact")
        self._clear_btn.clicked.connect(self.clear)
        actions.addWidget(self._clear_btn)

        self._outer.addWidget(self._tree, 1)
        self._outer.addLayout(actions)
        self._update_action_state()

    @staticmethod
    def _make_readonly() -> QPlainTextEdit:
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setMaximumHeight(40)
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        return text

    # --- 行为 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    def _resolve_scope(self) -> Tuple[Optional[List[str]], Dict[str, str], str]:
        """空的章节范围保持为空；整份范围也读取已打开的活缓冲。"""
        kind = self._scope_box.currentData() if hasattr(self, "_scope_box") else SCOPE_DOCUMENT
        current, selected = None, []
        if self._scope_provider is not None and kind != SCOPE_DOCUMENT:
            try:
                _kind, current, selected = self._scope_provider()
            except Exception as exc:
                raise ValueError("无法读取章节范围：{0}".format(exc)) from exc
        if kind == SCOPE_DOCUMENT:
            scope_paths, paths, note = None, self._service.all_files(), "整份文档"
        elif kind == SCOPE_CURRENT:
            paths = [current] if current else []
            scope_paths, note = paths, "当前章"
        else:
            paths = [item for item in (selected or []) if item]
            scope_paths, note = paths, "所选章"
        overrides = {}
        if self._live_text_provider is not None:
            for rel_path in paths:
                try:
                    text = self._live_text_provider(rel_path)
                except Exception as exc:
                    raise ValueError("无法读取编辑缓冲：{0}".format(exc)) from exc
                if text is not None:
                    overrides[rel_path] = text
        return scope_paths, overrides, note

    def _sync_live_overrides(self, paths) -> None:
        """应用时重新读取活缓冲，避免查找后的编辑被旧快照覆盖。"""
        if self._live_text_provider is None:
            return
        for rel_path in set(paths):
            try:
                text = self._live_text_provider(rel_path)
            except Exception as exc:
                raise ValueError("无法读取编辑缓冲，请重新查找：{0}".format(exc)) from exc
            if text is None:
                self._text_overrides.pop(rel_path, None)
            else:
                self._text_overrides[rel_path] = text

    def _apply_buffer_replacement(self, rel_path: str, text: str) -> bool:
        if self._buffer_applier is None or not self._buffer_applier(rel_path, text):
            return False
        self._text_overrides[rel_path] = text
        return True

    def find_all(self) -> None:
        try:
            scope_paths, overrides, note = self._resolve_scope()
            preview = self._service.build_preview(
                self._find_entry.text().strip(),
                regex=self._regex_cb.isChecked(),
                case_sensitive=self._case_cb.isChecked(),
                whole_word=self._word_cb.isChecked(),
                document_types=self._selected_types(),
                scope_paths=scope_paths,
                text_overrides=overrides,
            )
        except ValueError as exc:
            self._set_status("查询无效：{0}".format(exc))
            return
        self._scope_paths = scope_paths
        self._text_overrides = overrides
        self._scope_note = note
        self._preview = preview
        self._matches = list(preview.matches)
        # 重扫用本次成功的查询参数：用户随后修改查找框（含改成非法正则）
        # 不应破坏逐项替换后的剩余命中重扫。
        self._last_query = (
            self._find_entry.text().strip(),
            self._regex_cb.isChecked(),
            self._case_cb.isChecked(),
            self._word_cb.isChecked(),
        )
        # 武装「回滚本次替换」：回滚目标是本会话实际写过的文件（其清单
        # 条目经 record 去重后备份仍指向写前内容，与操作前是否已保存无关），
        # 而不是按操作前条目数/键集合做位置切片——后者在文件本会话已保存过
        # 时会漏掉这些文件的替换写回。
        self._rollback_armed = True
        self._replaced_files = set()
        self._render_matches()
        buffer_note = "，含未保存正文" if overrides else ""
        if preview.total == 0:
            self._set_status("无匹配（范围：{0}）".format(note + buffer_note))
        else:
            self._set_status(
                "共 {0} 处（{1} 个文件），范围：{2}，逐项确认后写回".format(
                    preview.total, preview.file_count, note + buffer_note
                )
            )

    def replace_one(self) -> None:
        match = self._selected_match()
        if match is None:
            return
        try:
            self._sync_live_overrides([match.rel_path])
            results = self._service.apply_matches(
                [match], self._replace_entry.text(), self._writer,
                text_overrides=self._text_overrides,
                buffer_applier=self._apply_buffer_replacement,
            )
        except (OSError, ValueError, KeyError, IndexError, UnicodeError) as exc:
            # 写回中途异常（如文件在预览后被外部改动）：清空命中要求重新
            # 查找，避免在陈旧偏移上重试造成替换错位。
            self._matches = []
            self._preview = None
            self._render_matches()
            self._set_status("替换失败：文件已变化，请重新查找。{0}".format(exc))
            return
        if not all(getattr(r, "written", False) for r in results):
            error = next(
                (r.error for r in results if not getattr(r, "written", False)),
                "写回失败",
            )
            # 写回失败时保留该命中供重试，不谎报成功。
            self._set_status("替换失败：{0}".format(error or "未知原因"))
            self._update_action_state()
            return
        self._matches.remove(match)
        # 落在活缓冲的替换不进改动清单：它的恢复走编辑器撤销栈，
        # 记进 _replaced_files 只会让「回滚本次替换」找不到条目而误报。
        if any(
            getattr(r, "written", False) and getattr(r, "backup_path", None)
            for r in results
        ):
            self._replaced_files.add(match.rel_path)
        # 先触发上层写后联动（索引同步刷新），再重扫受影响文件：逐项替换后
        # 同一文件其余命中仍基于旧内容的列偏移，直接复用会把后续替换写错位。
        self._after_applied(results)
        self._refresh_file_matches(match.rel_path)
        self._render_matches()
        history_warnings = [message for result in results for message in getattr(result, "warnings", [])]
        if history_warnings:
            self._set_status("已替换 1 处（{0}）".format("；".join(dict.fromkeys(history_warnings))))
        elif any(getattr(r, "backup_failed", False) for r in results):
            self._set_status("已替换 1 处（⚠ 备份失败，回滚不可用）")
        else:
            self._set_status("已替换 1 处")

    def skip_one(self) -> None:
        match = self._selected_match()
        if match is None:
            return
        self._matches.remove(match)
        self._render_matches()
        self._set_status("已跳过 1 处")

    def replace_all(self) -> None:
        if not self._matches:
            self._set_status("无命中可替换")
            return
        replacement = self._replace_entry.text()
        total = len(self._matches)
        files = {m.rel_path for m in self._matches}
        confirmed = QMessageBox.question(
            self,
            "全部替换",
            "将替换 {0} 处命中，涉及 {1} 个文件。\n"
            "每文件会保留 .md.bak 备份，可一键回滚。\n"
            "确认执行？".format(total, len(files)),
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._sync_live_overrides(m.rel_path for m in self._matches)
            results = self._service.apply_matches(
                self._matches, replacement, self._writer,
                text_overrides=self._text_overrides,
                buffer_applier=self._apply_buffer_replacement,
            )
        except (OSError, ValueError, KeyError, IndexError, UnicodeError) as exc:
            # 批量写回中途异常：失败文件保持未写状态，清空命中要求重新查找，
            # 避免用户基于陈旧列表重试把已写文件再次按旧偏移切片。
            self._matches = []
            self._preview = None
            self._render_matches()
            self._set_status("批量替换失败：文件已变化，请重新查找。{0}".format(exc))
            return
        self._replaced_files.update(
            r.rel_path for r in results
            if getattr(r, "written", False) and getattr(r, "backup_path", None)
        )
        failed = [r for r in results if not getattr(r, "written", False)]
        if failed:
            if any(getattr(r, "written", False) for r in results):
                self._after_applied(results)
            errors = "；".join(
                r.error for r in failed if getattr(r, "error", None)
            ) or "写回失败"
            # 失败文件的命中保留供重试；成功文件从列表移除。
            failed_files = {getattr(r, "rel_path", "") for r in failed}
            self._matches = [m for m in self._matches if m.rel_path in failed_files]
            self._preview = None
            self._render_matches()
            self._set_status("部分替换失败：{0}".format(errors))
            return
        self._matches = []
        self._preview = None
        self._render_matches()
        no_backup = [
            r.rel_path for r in results if getattr(r, "backup_failed", False)
        ]
        history_warnings = [message for result in results for message in getattr(result, "warnings", [])]
        if history_warnings:
            self._set_status("已批量替换 {0} 处（{1} 个文件）；{2}".format(
                total, len(files), "；".join(dict.fromkeys(history_warnings))))
        elif no_backup:
            self._set_status(
                "已批量替换 {0} 处（{1} 个文件）；以下文件备份失败，回滚不可用：{2}".format(
                    total, len(files), "、".join(no_backup)
                )
            )
        else:
            self._set_status("已批量替换 {0} 处（{1} 个文件）".format(total, len(files)))
        self._after_applied(results)

    def rollback(self) -> None:
        if not self._rollback_armed:
            # 双保险：按钮禁用之外，直接调用也拒绝——回滚全部会话改动
            # 会把本次替换前更早的独立编辑/保存一并回滚，非「本次替换」。
            self._set_status("请先执行查找，再回滚本次替换")
            return
        from doc_tool.application.content.writer import OP_EDIT

        current = self._writer.manifest.keys()
        target = {(OP_EDIT, rel) for rel in self._replaced_files} & current
        if not target:
            self._set_status("本次替换没有产生需要回滚的改动")
            return
        failures = self._writer.rollback_keys(target)
        if failures:
            self._set_status("回滚失败：{0}".format(", ".join(failures)))
        else:
            self._set_status("已回滚本次替换")
            # 成功回滚后解除武装：防止用户继续保存后再次点击，把与本次
            # 替换无关的新保存一并回滚。
            self._rollback_armed = False
            self._replaced_files = set()
            self._update_action_state()
            if self._on_applied is not None:
                self._on_applied()

    def clear(self) -> None:
        self._matches = []
        self._preview = None
        self._render_matches()
        self._set_status("")

    # --- 内部 ---

    def _after_applied(self, results) -> None:
        if self._on_applied is not None:
            self._on_applied()
        self._update_action_state()

    def _render_matches(self) -> None:
        self._tree.clear()
        for i, match in enumerate(self._matches):
            preview_text = match.line_text.strip()
            if len(preview_text) > 160:
                preview_text = preview_text[:160] + "…"
            item = ReplaceTreeItem(
                [match.rel_path, str(match.line_no), preview_text]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._update_diff()
        self._update_action_state()

    def _selected_match(self) -> Optional[ReplaceMatch]:
        item = self._tree.currentItem()
        if item is None:
            return None
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= index < len(self._matches)):
            return None
        return self._matches[index]

    def _update_diff(self) -> None:
        match = self._selected_match()
        if match is None:
            self._before_text.clear()
            self._after_text.clear()
            return
        before, after = diff_line(match, self._replace_entry.text())
        self._before_text.setPlainText(before)
        self._after_text.setPlainText(after)

    def _update_action_state(self) -> None:
        can_write = self._writable
        has_matches = bool(self._matches)
        self._replace_one_btn.setEnabled(can_write and has_matches)
        self._skip_btn.setEnabled(has_matches)
        self._replace_all_btn.setEnabled(can_write and has_matches)
        # 未执行过查找（无回滚起点）时禁用「回滚本次替换」：旧逻辑在可写时
        # 恒启用，用户未查找直接点回滚会以 since=None 回滚整个会话改动。
        self._rollback_btn.setEnabled(can_write and self._rollback_armed)
        self._clear_btn.setEnabled(has_matches)

    def _selected_types(self) -> Optional[List[str]]:
        # 通用单项目默认替换当前项目全部内容，不应用类型过滤。
        if not self._show_type_filter:
            return None
        label = self._type_box.currentText()
        value = next((v for l, v in _TYPE_FILTERS if l == label), None)
        return [value] if value else None

    def refresh_live_text(self, rel_path: str) -> None:
        """编辑器缓冲变化后刷新该章命中（保持范围与缓冲口径一致）。"""
        if not self._matches:
            return
        self._refresh_file_matches(rel_path)

    def _refresh_file_matches(self, rel_path: str) -> None:
        """用当前内容重扫已写回文件，替换该文件的陈旧命中。

        逐项替换每次只应用一个缓存 match，写回后其余命中仍基于搜索时的
        列偏移；直接复用会把后续替换写到错位位置（同一行多处命中尤其明显）。
        此处经上层写后联动同步刷新索引后，用最新行重建该文件的命中。
        重扫使用 find_all 时的查询参数：查找框被用户随后改掉（甚至改成
        非法正则）不应破坏本次替换会话的剩余命中。
        """
        query = self._last_query or (
            self._find_entry.text().strip(),
            self._regex_cb.isChecked(),
            self._case_cb.isChecked(),
            self._word_cb.isChecked(),
        )
        try:
            self._sync_live_overrides([rel_path])
            fresh = self._service.find_in_file(
                rel_path,
                query[0],
                regex=query[1],
                case_sensitive=query[2],
                whole_word=query[3],
                text_overrides=self._text_overrides,
            )
        except ValueError:
            # 查询参数已失效：保留该文件其余命中并提示重新查找，
            # 不再抛出中断替换流程。
            self._set_status("查询参数已变化，请重新执行查找后继续替换")
            return
        self._matches = [m for m in self._matches if m.rel_path != rel_path] + fresh

    def _set_status(self, text: str) -> None:
        if not hasattr(self, "_status_label"):
            self._status_label = QLabel(self)
            self._status_label.setObjectName("statusMuted")
            self._status_label.setWordWrap(True)
            self._status_label.setMaximumHeight(32)
            self.layout().addWidget(self._status_label)
        self._status_label.setText(text)
