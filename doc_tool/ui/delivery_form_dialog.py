# -*- coding: utf-8 -*-
"""批量交付首用表单：不写 JSON 也能建立首个可执行批次计划（UI 包 4.1）。

要点：
- 只收集成员项目/已有变体/目标格式/输出目录，生成**原 batch 格式**（schema 1）；
- 生成的计划必须经 ``delivery.contract.parse_plan`` 校验，校验结果直接显示：
  合法成员可执行，失效成员就地显示原因并可移除，全部无效时保留输入；
- 高级路径仍在：可打开已有 batch.json（主窗口入口保留），本表单不取代它。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.delivery import contract

#: 表单默认目标格式（与既有交付契约一致）。
DEFAULT_FORMATS = ["docx"]
ALL_FORMATS = ["docx", "html", "pdf"]


def build_plan_payload(
    *,
    batch_id: str,
    members: List[str],
    formats: List[str],
    destination: str = "",
    variant_id: str = "",
) -> Dict[str, object]:
    """按原 batch 格式构造计划字典（不做校验，校验交给 contract.parse_plan）。"""
    entries = []
    for index, member in enumerate(members, start=1):
        entry = {
            "entryId": "e{0}".format(index),
            "member": str(member),
            "kind": contract.ENTRY_KIND_PROJECT,
            "formats": list(formats),
            "scope": {"kind": "project", "chapters": [], "current": ""},
            "sourceMode": "saved",
        }
        if destination:
            entry["destination"] = str(destination)
        if variant_id:
            entry["variantId"] = str(variant_id)
        entries.append(entry)
    payload: Dict[str, object] = {
        "schemaVersion": contract.PLAN_SCHEMA_VERSION,
        "kind": contract.PLAN_KIND,
        "batchId": batch_id or "batch",
        "policy": {"strict": False, "refresh": True},
        "defaults": {
            "formats": list(formats),
            "destination": str(destination or ""),
        },
        "entries": entries,
    }
    return payload


def validate_payload(payload: Dict[str, object], *, plan_path: str = "") -> object:
    """用既有服务校验计划（返回 ``BatchPlan``，成员级问题按项记录）。"""
    return contract.parse_plan(payload, plan_path=plan_path)


def save_plan(payload: Dict[str, object], plan_path) -> Path:
    """把计划写成 batch.json（原子写，utf-8，保持原格式）。"""
    from doc_tool.application.content.writer import atomic_write

    target = Path(plan_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, json.dumps(payload, ensure_ascii=False, indent=2))
    return target


def default_plan_path(batch_id: str, directory: str = "") -> Path:
    from doc_tool.application.intake_entries import default_project_parent

    base = Path(directory) if directory else default_project_parent()
    name = "".join(ch for ch in (batch_id or "batch") if ch not in '<>:"/\\|?*').strip()
    return base / (name or "batch") / "batch.json"


def member_variants(project_root) -> List[str]:
    """读取成员项目已有变体 id（只提示，不阻断；无配置返回空列表）。"""
    try:
        from doc_tool.application.content.variants import VariantsConfig

        return list(VariantsConfig.load(Path(project_root)).ids())
    except Exception:  # noqa: BLE001 - 变体配置不可读按无变体处理
        return []


class DeliveryFormDialog(QDialog):
    """新建批次表单：成员 + 变体 + 格式 + 目录，提交时经 contract 校验。"""

    def __init__(
        self,
        *,
        initial_members: Optional[List[str]] = None,
        default_dir: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建批量交付批次")
        self.resize(680, 520)
        self._default_dir = default_dir
        self._plan_path: Optional[Path] = None
        self._plan = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("批次名称：", self))
        self._name_entry = QLineEdit(self)
        self._name_entry.setPlaceholderText("例如 2026Q4-交付批次")
        name_row.addWidget(self._name_entry, 1)
        layout.addLayout(name_row)

        layout.addWidget(QLabel("成员项目目录（每个成员一个项目，缺 project.yml 会就地提示）：", self))
        self._member_list = QListWidget(self)
        self._member_list.setObjectName("deliveryMemberList")
        layout.addWidget(self._member_list, 1)

        member_actions = QHBoxLayout()
        add_btn = QPushButton("添加成员项目…", self)
        add_btn.setProperty("btnRole", "secondary")
        add_btn.clicked.connect(self._add_member)
        member_actions.addWidget(add_btn)
        remove_btn = QPushButton("移除所选", self)
        remove_btn.setProperty("btnRole", "compact")
        remove_btn.clicked.connect(self._remove_selected)
        member_actions.addWidget(remove_btn)
        member_actions.addStretch(1)
        layout.addLayout(member_actions)

        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("目标格式：", self))
        self._format_boxes = {}
        for fmt in ALL_FORMATS:
            box = QCheckBox(fmt.upper(), self)
            box.setChecked(fmt in DEFAULT_FORMATS)
            box.toggled.connect(self._refresh_validation)
            self._format_boxes[fmt] = box
            format_row.addWidget(box)
        format_row.addStretch(1)
        layout.addLayout(format_row)

        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("已有变体（可选）：", self))
        self._variant_entry = QLineEdit(self)
        self._variant_entry.setPlaceholderText("留空＝项目当前内容；填写后仅登记该变体")
        self._variant_entry.textChanged.connect(self._refresh_validation)
        variant_row.addWidget(self._variant_entry, 1)
        layout.addLayout(variant_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("输出目录（可选）：", self))
        self._destination_entry = QLineEdit(self)
        self._destination_entry.setPlaceholderText("留空＝各项目自己的 output/")
        self._destination_entry.textChanged.connect(self._refresh_validation)
        dir_row.addWidget(self._destination_entry, 1)
        pick_btn = QPushButton("选择…", self)
        pick_btn.setProperty("btnRole", "compact")
        pick_btn.clicked.connect(self._pick_destination)
        dir_row.addWidget(pick_btn)
        layout.addLayout(dir_row)

        self._validation_label = QLabel("", self)
        self._validation_label.setObjectName("statusMuted")
        self._validation_label.setWordWrap(True)
        layout.addWidget(self._validation_label)

        self._buttons = QDialogButtonBox(self)
        self._submit_btn = self._buttons.addButton(
            "保存并开始交付", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._save_btn = self._buttons.addButton(
            "仅保存 batch.json", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._buttons.accepted.connect(self._on_submit)
        self._save_btn.clicked.connect(self._on_save_only)
        layout.addWidget(self._buttons)

        for member in initial_members or []:
            self._append_member(str(member))
        self._refresh_validation()

    # --- 成员管理 ---

    def _append_member(self, path: str) -> None:
        item = QListWidgetItem(path)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self._member_list.addItem(item)
        self._refresh_validation()

    def _add_member(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "选择成员项目目录", self._default_dir or ""
        )
        if chosen:
            self._append_member(chosen)

    def _remove_selected(self) -> None:
        for item in self._member_list.selectedItems():
            self._member_list.takeItem(self._member_list.row(item))
        self._refresh_validation()

    def _pick_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "选择输出目录", self._destination_entry.text() or self._default_dir or ""
        )
        if chosen:
            self._destination_entry.setText(chosen)

    # --- 表单状态 ---

    def members(self) -> List[str]:
        return [
            str(self._member_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self._member_list.count())
        ]

    def formats(self) -> List[str]:
        return [fmt for fmt, box in self._format_boxes.items() if box.isChecked()]

    def payload(self) -> Dict[str, object]:
        return build_plan_payload(
            batch_id=self._name_entry.text().strip(),
            members=self.members(),
            formats=self.formats() or list(DEFAULT_FORMATS),
            destination=self._destination_entry.text().strip(),
            variant_id=self._variant_entry.text().strip(),
        )

    def validated_plan(self):
        """当前表单经既有 contract 校验后的计划对象。"""
        return validate_payload(self.payload())

    def _refresh_validation(self, *_args) -> None:
        plan = self.validated_plan()
        self._plan = plan
        lines = []
        if not self.members():
            lines.append("请先添加至少一个成员项目。")
        lines.append(
            "可执行成员 {0} 个｜不可执行 {1} 个".format(
                len(plan.executable_entries()), len(plan.invalid_entries())
            )
        )
        for entry in plan.invalid_entries():
            lines.append(
                "· 无效：{0}（{1}）".format(
                    entry.projectRoot or entry.member, "；".join(entry.problems)
                )
            )
        for entry in plan.warning_entries():
            lines.append(
                "· 提醒：{0}（{1}）".format(
                    entry.projectRoot or entry.member, "；".join(entry.problems)
                )
            )
        for problem in plan.problems:
            lines.append("计划问题：{0}".format(problem))
        self._validation_label.setText("\n".join(lines[:8]))
        executable = bool(plan.executable_entries())
        self._submit_btn.setEnabled(executable)
        self._save_btn.setEnabled(bool(self.members()))

    # --- 提交 ---

    def _on_save_only(self) -> None:
        if not self.members():
            return
        self._plan_path = save_plan(
            self.payload(), default_plan_path(self._name_entry.text().strip(), self._default_dir)
        )

    def _on_submit(self) -> None:
        plan = self.validated_plan()
        if not plan.executable_entries():
            # 全部无效：保留输入并解释原因，不假报开始。
            self._refresh_validation()
            self._validation_label.setText(
                self._validation_label.text()
                + "\n全部成员不可执行：已保留表单输入，请修正或移除后重试。"
            )
            return
        self._plan = plan
        self._plan_path = save_plan(
            self.payload(), default_plan_path(self._name_entry.text().strip(), self._default_dir)
        )
        self.accept()

    def plan_path(self) -> Optional[Path]:
        return self._plan_path

    def validated(self):
        return self._plan


__all__ = [
    "ALL_FORMATS",
    "DEFAULT_FORMATS",
    "DeliveryFormDialog",
    "build_plan_payload",
    "default_plan_path",
    "member_variants",
    "save_plan",
    "validate_payload",
]