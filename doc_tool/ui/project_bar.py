# -*- coding: utf-8 -*-
"""顶部项目条：文档身份 + 就绪状态 + 高频操作入口。

与菜单共享同一 ``derive_workbench_state`` 状态来源：按钮可用性直接来自
``WorkbenchState.actions``，避免项目条与菜单漂移。摘要细节（编号、指纹、
最后构建、路径）折叠到可展开区。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.ui.workbench_state import WorkbenchState

# 文档类型中文映射（与章节树/搜索面板共用同一来源，避免文案漂移）。
from doc_tool.application.content.tree import DEFAULT_TYPE_LABELS as DOC_TYPE_LABELS


class ProjectBar(QWidget):
    """顶部项目条。"""

    def __init__(
        self,
        *,
        on_merge: Optional[Callable[[], None]] = None,
        on_diag_build: Optional[Callable[[], None]] = None,
        on_validate: Optional[Callable[[], None]] = None,
        on_switch_branch: Optional[Callable[[], None]] = None,
        on_close_project: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_merge = on_merge
        self._on_diag_build = on_diag_build
        self._on_validate = on_validate
        self._on_switch_branch = on_switch_branch
        self._on_close_project = on_close_project
        self._summary_collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        main = QHBoxLayout()
        main.setSpacing(10)

        # 文档身份
        self._name_label = QLabel("未打开项目", self)
        self._name_label.setObjectName("barTitle")
        main.addWidget(self._name_label)

        self._type_label = QLabel("", self)
        self._type_label.setObjectName("statusMuted")
        main.addWidget(self._type_label)

        self._version_label = QLabel("", self)
        self._version_label.setObjectName("statusMuted")
        main.addWidget(self._version_label)

        self._branch_btn = QPushButton("", self)
        self._branch_btn.setObjectName("barBranchBtn")
        self._branch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._branch_btn.setToolTip("当前 Git 分支（点击切换分支）")
        self._branch_btn.setVisible(False)
        self._branch_btn.clicked.connect(self._handle_switch_branch)
        main.addWidget(self._branch_btn)

        self._readiness_label = QLabel("请选择或新建项目", self)
        self._readiness_label.setProperty("statusTone", "neutral")
        self._readiness_label.setWordWrap(False)
        main.addWidget(self._readiness_label, 1)

        # 高频入口（顺序：项目检查 -> 快速构建 -> 正式出稿，符合标准流水线认知）
        self._validate_btn = QPushButton("项目检查", self)
        self._validate_btn.setProperty("btnRole", "secondary")
        self._validate_btn.setToolTip("检查文档结构、引用与格式；若已生成 Word 则一并校验一致性 (F5)")
        self._validate_btn.clicked.connect(self._handle_validate)
        main.addWidget(self._validate_btn)

        self._diag_btn = QPushButton("快速构建", self)
        self._diag_btn.setProperty("btnRole", "secondary")
        self._diag_btn.setToolTip("快速生成 DOCX 预览（无需本机 Word，跳过目录域刷新） (Ctrl+Shift+B)")
        self._diag_btn.clicked.connect(self._handle_diag_build)
        main.addWidget(self._diag_btn)

        self._merge_btn = QPushButton("正式出稿", self)
        self._merge_btn.setProperty("btnRole", "primary")
        self._merge_btn.setToolTip("完整生成、刷新目录域与页码并正式归档（需本机 Microsoft Word）")
        self._merge_btn.clicked.connect(self._handle_merge)
        main.addWidget(self._merge_btn)

        # 摘要折叠开关
        self._toggle_btn = QToolButton(self)
        self._toggle_btn.setText("收起摘要")
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toggle_btn.clicked.connect(self.toggle_summary)
        self._toggle_btn.setVisible(False)
        main.addWidget(self._toggle_btn)

        # 关闭项目入口
        self._close_btn = QPushButton("关闭项目", self)
        self._close_btn.setProperty("btnRole", "secondary")
        self._close_btn.setToolTip("保存并关闭当前项目，返回主页 (Ctrl+Shift+W)")
        self._close_btn.clicked.connect(self._handle_close_project)
        self._close_btn.setVisible(False)
        main.addWidget(self._close_btn)

        layout.addLayout(main)

        # 摘要细节（可折叠）
        self._summary_frame = QFrame(self)
        self._summary_frame.setProperty("card", True)
        summary_layout = QVBoxLayout(self._summary_frame)
        summary_layout.setContentsMargins(10, 8, 10, 8)
        summary_layout.setSpacing(2)
        self._detail_labels: list[QLabel] = []
        for key in (
            "document_no",
            "document_type",
            "source_hash",
            "last_build",
            "project_path",
        ):
            label = QLabel("", self._summary_frame)
            label.setObjectName("statusMuted")
            label.setWordWrap(False)
            self._detail_labels.append(label)
            summary_layout.addWidget(label)
        layout.addWidget(self._summary_frame)

        self._apply_summary_visibility()

    # --- 渲染 ---

    def render(self, summary, state: WorkbenchState) -> None:
        """用项目摘要与状态快照渲染项目条。"""
        manifest = getattr(summary, "manifest", None)
        project_root = getattr(summary, "project_root", None)

        document_name = getattr(manifest, "documentName", "") if manifest else ""
        document_type = getattr(manifest, "documentType", "") if manifest else ""
        document_version = getattr(manifest, "documentVersion", "") if manifest else ""
        document_no = getattr(manifest, "documentNo", "") if manifest else ""
        source_hash = getattr(manifest, "sourceSha256", "") if manifest else ""
        last_build = (
            getattr(manifest, "lastSuccessfulBuildVersion", "")
            if manifest
            else ""
        )

        self._name_label.setText(document_name or (project_root.name if project_root else "未打开项目"))
        type_text = DOC_TYPE_LABELS.get(document_type, document_type)
        self._type_label.setText(type_text if type_text else "")
        self._version_label.setText(
            "v{0}".format(document_version) if document_version else ""
        )
        self._readiness_label.setText(state.readiness_text)
        self._readiness_label.setProperty("statusTone", state.status_tone)
        self._readiness_label.style().unpolish(self._readiness_label)
        self._readiness_label.style().polish(self._readiness_label)

        # 高频入口可用性来自同一状态来源
        actions = state.actions
        self._set_enabled(
            self._validate_btn,
            actions.get("validate", None),
            "检查文档结构、引用与格式；若已生成 Word 则一并校验一致性 (F5)",
        )
        self._set_enabled(
            self._diag_build_btn(),
            actions.get("diag_build", None),
            "快速生成 DOCX 预览（无需本机 Word，跳过目录域刷新） (Ctrl+Shift+B)",
        )
        self._set_enabled(
            self._merge_btn,
            actions.get("merge", None),
            "完整生成、刷新目录域与页码并正式归档（需本机 Microsoft Word）",
        )

        self._toggle_btn.setVisible(bool(document_name or project_root))
        self._close_btn.setVisible(bool(document_name or project_root))
        from doc_tool.ui.workbench_state import WorkView
        is_running = (getattr(state, "view", None) == WorkView.RUNNING or getattr(state, "running", False))
        self._close_btn.setEnabled(not is_running)
        if is_running:
            self._close_btn.setToolTip("任务正在执行中，请等待完成或取消后再关闭项目")
        else:
            self._close_btn.setToolTip("保存并关闭当前项目，返回主页 (Ctrl+Shift+W)")
        # 摘要细节
        values = {
            "document_no": "文档编号：{0}".format(document_no or "—"),
            "document_type": "文档类型：{0}".format(type_text or "—"),
            "source_hash": "源文件指纹：{0}".format(
                (source_hash[:12] + "…") if source_hash else "—"
            ),
            "last_build": "最后构建版本：{0}".format(last_build or "尚未构建"),
            "project_path": "项目路径：{0}".format(project_root or "—"),
        }
        for label, value in zip(self._detail_labels, [
            values["document_no"],
            values["document_type"],
            values["source_hash"],
            values["last_build"],
            values["project_path"],
        ]):
            label.setText(value)

    def _diag_build_btn(self) -> QPushButton:
        return self._diag_btn

    @staticmethod
    def _set_enabled(button: QPushButton, action, default_tooltip: str = "") -> None:
        if action is None:
            button.setEnabled(False)
            button.setToolTip(default_tooltip)
            return
        button.setEnabled(bool(action.enabled))
        if not action.enabled and action.reason:
            button.setToolTip(action.reason)
        else:
            button.setToolTip(default_tooltip)

    def toggle_summary(self) -> None:
        """折叠/展开摘要细节区。"""
        self._summary_collapsed = not self._summary_collapsed
        self._apply_summary_visibility()

    def _apply_summary_visibility(self) -> None:
        self._summary_frame.setVisible(not self._summary_collapsed)
        self._toggle_btn.setText("展开摘要" if self._summary_collapsed else "收起摘要")

    def reset(self) -> None:
        """重设项目条展示为未打开项目状态。"""
        self._name_label.setText("未打开项目")
        self._type_label.setText("")
        self._version_label.setText("")
        self._branch_btn.setVisible(False)
        self._readiness_label.setText("请选择或新建项目")
        self._readiness_label.setProperty("statusTone", "neutral")
        self._merge_btn.setEnabled(False)
        self._diag_btn.setEnabled(False)
        self._validate_btn.setEnabled(False)
        self._toggle_btn.setVisible(False)
        self._close_btn.setVisible(False)
        for label in getattr(self, "_detail_labels", []):
            label.setText("")

    def set_branch(
        self,
        branch_name: str,
        uncommitted_count: int = 0,
        *,
        ahead_count: int = 0,
        behind_count: int = 0,
    ) -> None:
        """设置当前 Git 分支显示与改动角标。"""
        if not branch_name:
            self._branch_btn.setVisible(False)
            return
        badges = []
        if ahead_count > 0:
            badges.append(f"↑{ahead_count}")
        if behind_count > 0:
            badges.append(f"↓{behind_count}")
        sync_str = (" " + "".join(badges)) if badges else ""
        badge = f" ({uncommitted_count})" if uncommitted_count > 0 else ""
        self._branch_btn.setText(f"⎇ {branch_name}{sync_str}{badge} ▾")
        self._branch_btn.setToolTip(f"当前 Git 分支：{branch_name}{sync_str}{badge}（点击切换分支）")
        self._branch_btn.setVisible(True)

    def branch_anchor(self) -> QWidget:
        """返回供 Popover 锚定定位的控件。"""
        return self._branch_btn

    # --- 事件转发 ---

    def _handle_merge(self) -> None:
        if self._on_merge is not None:
            self._on_merge()

    def _handle_diag_build(self) -> None:
        if self._on_diag_build is not None:
            self._on_diag_build()

    def _handle_validate(self) -> None:
        if self._on_validate is not None:
            self._on_validate()

    def _handle_switch_branch(self) -> None:
        if self._on_switch_branch is not None:
            self._on_switch_branch()


    def _handle_close_project(self) -> None:
        if self._on_close_project is not None:
            self._on_close_project()
