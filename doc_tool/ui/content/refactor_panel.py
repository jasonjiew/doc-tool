# -*- coding: utf-8 -*-
"""章节重命名/重编号联动面板（底部工具面板）。

选择文件 + 输入新文件名 -> "预览影响"生成 dry-run 清单（文件内位置 ×
旧→新）-> 确认后批量更新引用并重命名文件。写回经 ``ContentWriter``
备份与改动清单，可回滚；完成后回调 ``on_applied`` 触发校验。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.refactor import RefactorService


class RefactorPanel(QWidget):
    """重命名/重编号联动面板。

    ``writer``：``ContentWriter``；``on_applied``：执行成功后回调。
    ``set_target(rel_path)``：由章节树/编辑器选中文件预填。
    """

    def __init__(
        self,
        service: RefactorService,
        writer,
        *,
        on_applied: Optional[Callable[[], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._writer = writer
        self._on_applied = on_applied
        self._writable = writable
        self._plan = None
        self._all_files: List[str] = []
        # 「回滚本次联动」的起点：本次操作开始前的清单条目数，避免把同会话
        # 更早的编辑/保存一并回滚。
        self._rollback_marker: Optional[int] = None

        # 唯一外层布局：输入卡片 + 影响清单 + 操作行。原先各 _build_*
        # 各自创建 QVBoxLayout(self)，只有第一个会被安装，影响清单因此不可见。
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(4, 4, 4, 4)
        self._outer.setSpacing(4)
        self._build_inputs()
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
        row1.addWidget(QLabel("章节文件：", inputs))
        self._file_box = QComboBox(inputs)
        self._file_box.setEditable(True)
        row1.addWidget(self._file_box, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.addWidget(QLabel("新文件名：", inputs))
        self._new_name_entry = QLineEdit(inputs)
        row2.addWidget(self._new_name_entry, 1)
        self._preview_btn = QPushButton("预览影响", inputs)
        self._preview_btn.setProperty("btnRole", "secondary")
        self._preview_btn.clicked.connect(self.preview)
        row2.addWidget(self._preview_btn)
        layout.addLayout(row2)

        self._outer.addWidget(inputs)

    def _build_results(self) -> None:
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["文件", "行", "旧文本", "新文本"])
        self._tree.setColumnWidth(0, 220)
        self._tree.setColumnWidth(1, 48)
        self._tree.setColumnWidth(2, 220)
        self._tree.setColumnWidth(3, 220)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._apply_btn = QPushButton("确认并执行", self)
        self._apply_btn.setProperty("btnRole", "primary")
        self._apply_btn.clicked.connect(self.apply_plan)
        actions.addWidget(self._apply_btn)
        self._rollback_btn = QPushButton("回滚本次联动", self)
        self._rollback_btn.setProperty("btnRole", "compact")
        self._rollback_btn.clicked.connect(self.rollback)
        actions.addWidget(self._rollback_btn)
        actions.addStretch(1)
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("statusMuted")
        self._status_label.setWordWrap(True)
        actions.addWidget(self._status_label)

        self._outer.addWidget(self._tree, 1)
        self._outer.addLayout(actions)
        self._update_action_state()

    # --- 数据 ---

    def set_files(self, files: List[str]) -> None:
        """设置可选择的文件列表。"""
        self._all_files = list(files)
        self._file_box.clear()
        self._file_box.addItems(self._all_files)

    def set_target(self, rel_path: str) -> None:
        """预填目标文件（由章节树/编辑器选中触发）。"""
        self._file_box.setCurrentText(rel_path)
        self._new_name_entry.setText(Path(rel_path).name)
        self.clear()

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._update_action_state()

    # --- 行为 ---

    def preview(self) -> None:
        rel_path = self._file_box.currentText().strip()
        new_name = self._new_name_entry.text().strip()
        if not rel_path or not new_name:
            self._set_status("请选择文件并填写新文件名")
            return
        try:
            plan = self._service.compute_rename_plan(rel_path, new_name)
        except Exception as exc:  # noqa: BLE001
            self._set_status("计算失败：{0}".format(exc))
            return
        if plan is None:
            self._set_status("目标文件不在内容索引中")
            return
        self._plan = plan
        # 捕获回滚起点：本次联动开始前已存在的改动清单条目数。
        self._rollback_marker = self._writer.manifest.entry_count()
        self._tree.clear()
        for i, edit in enumerate(plan.edits):
            item = QTreeWidgetItem(
                [
                    edit.rel_path,
                    str(edit.line_no),
                    edit.old_substr,
                    edit.new_substr,
                ]
            )
            self._tree.addTopLevelItem(item)
        if plan.total == 0:
            self._set_status("无受影响引用（仅重命名文件本身）")
        else:
            self._set_status(
                "受影响引用 {0} 处（{1} 个文件）+ 重命名文件本身".format(
                    plan.total, len(plan.affected_files)
                )
            )
        self._update_action_state()

    def apply_plan(self) -> None:
        if self._plan is None:
            return
        plan = self._plan
        confirmed = QMessageBox.question(
            self,
            "确认执行",
            "将更新 {0} 处引用，并把文件重命名为：\n{1}\n"
            "每文件保留 .md.bak 备份，可回滚。确认执行？".format(
                plan.total, plan.new_rel_path
            ),
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._service.apply_rename_plan(plan, self._writer)
        self._set_status("已执行：{0} 处引用更新 + 文件重命名".format(plan.total))
        self._plan = None
        self._tree.clear()
        if self._on_applied is not None:
            self._on_applied()
        self._update_action_state()

    def rollback(self) -> None:
        failures = self._writer.rollback(since=self._rollback_marker)
        if failures:
            self._set_status("回滚失败：{0}".format(", ".join(failures)))
        else:
            self._set_status("已回滚本次联动")
            if self._on_applied is not None:
                self._on_applied()

    def clear(self) -> None:
        self._plan = None
        self._tree.clear()
        self._update_action_state()

    def _update_action_state(self) -> None:
        self._apply_btn.setEnabled(self._writable and self._plan is not None)
        self._rollback_btn.setEnabled(self._writable)

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)
