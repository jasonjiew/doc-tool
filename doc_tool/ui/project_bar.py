# -*- coding: utf-8 -*-
"""顶部项目条：文档身份 + 就绪状态 + 高频操作入口。

与菜单共享同一 ``derive_workbench_state`` 状态来源：按钮可用性直接来自
``WorkbenchState.actions``，避免项目条与菜单漂移。摘要细节（编号、指纹、
最后构建、路径）折叠到可展开区。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.ui.action_overflow import ActionOverflow
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
        on_quick_export: Optional[Callable[[], None]] = None,
        on_show_results: Optional[Callable[[], None]] = None,
        on_switch_branch: Optional[Callable[[], None]] = None,
        on_close_project: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_merge = on_merge
        self._on_diag_build = on_diag_build
        self._on_validate = on_validate
        self._on_quick_export = on_quick_export
        self._on_show_results = on_show_results
        self._on_switch_branch = on_switch_branch
        self._on_close_project = on_close_project
        self._summary_collapsed = False
        self._pending_edit_count = 0
        self._round_count = 0
        # UI2-A 1.2：次级动作共享 QAction，原地按钮与「更多」菜单同一行为/可用性。
        self._overflow_menu = None
        self._overflow = None
        self._project_path_text = ""
        self._document_name_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        main = QHBoxLayout()
        main.setSpacing(10)

        # 文档身份：长名称省略显示，完整值与项目路径可由提示/右键菜单取得。
        self._name_label = QLabel("未打开项目", self)
        self._name_label.setObjectName("barTitle")
        self._name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._name_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._name_label.customContextMenuRequested.connect(self._on_name_context_menu)
        self._name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._name_label.setMinimumWidth(80)
        main.addWidget(self._name_label, 2)

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
        self._readiness_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._readiness_label.setMinimumWidth(60)
        main.addWidget(self._readiness_label, 1)

        # 高频入口：日常「导出 Word」优先可见可点（与菜单 Ctrl+E 同一 handler）；
        # 项目检查 / 快速构建 / 正式出稿作为次级动作保留完整流水线语义。
        self._quick_export_btn = QPushButton("导出 Word", self)
        self._quick_export_btn.setObjectName("barQuickExportBtn")
        self._quick_export_btn.setProperty("btnRole", "primary")
        # 主要动作不参与溢出：按完整样式（QSS 生效后）的最小尺寸保留，不裁切文字。
        self._quick_export_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        self._quick_export_btn.setShortcut("Ctrl+E")
        self._quick_export_btn.setToolTip(
            "快速导出整份 Word（当前编辑内容优先，无需本机 Word） (Ctrl+E)"
        )
        self._quick_export_btn.clicked.connect(self._handle_quick_export)
        main.addWidget(self._quick_export_btn)

        # 「成果」：非模态逐文件结果入口（关闭后仍能从这里找回最近轮次）。
        self._results_btn = QPushButton("成果", self)
        self._results_btn.setObjectName("barResultsBtn")
        self._results_btn.setProperty("btnRole", "secondary")
        self._results_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        self._results_btn.setToolTip("查看本项目最近出稿轮次与逐文件结果")
        self._results_btn.clicked.connect(self._handle_show_results)
        main.addWidget(self._results_btn)

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
        self._merge_btn.setProperty("btnRole", "secondary")
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

        # 「更多 ▾」：窄窗口收纳放不下的次级动作；菜单项与原地按钮同一 QAction。
        self._more_btn = QToolButton(self)
        self._more_btn.setObjectName("barMoreBtn")
        self._more_btn.setText("更多 ▾")
        self._more_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more_btn.setToolTip("窗口较窄：放不下的检查/构建/出稿/分支/关闭动作都在这里")
        self._overflow_menu = QMenu(self._more_btn)
        self._more_btn.setMenu(self._overflow_menu)
        self._more_btn.setVisible(False)
        main.addWidget(self._more_btn)

        layout.addLayout(main)
        self._setup_action_overflow()

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

    # --- 动作溢出（UI2-A 1.2） ---

    def _setup_action_overflow(self) -> None:
        """把次级动作登记进溢出控制器（主要动作常驻、不参与溢出）。"""
        self._validate_action = QAction("项目检查", self)
        self._validate_action.setToolTip(
            "检查文档结构、引用与格式；若已生成 Word 则一并校验一致性 (F5)"
        )
        self._validate_action.triggered.connect(self._handle_validate)

        self._diag_action = QAction("快速构建", self)
        self._diag_action.setToolTip(
            "快速生成 DOCX 预览（无需本机 Word，跳过目录域刷新） (Ctrl+Shift+B)"
        )
        self._diag_action.triggered.connect(self._handle_diag_build)

        self._merge_action = QAction("正式出稿", self)
        self._merge_action.setToolTip(
            "完整生成、刷新目录域与页码并正式归档（需本机 Microsoft Word）"
        )
        self._merge_action.triggered.connect(self._handle_merge)

        self._branch_action = QAction("切换分支", self)
        self._branch_action.setToolTip("切换 Git 分支（点击当前分支标签也可切换）")
        self._branch_action.triggered.connect(self._handle_switch_branch)

        self._close_action = QAction("关闭项目", self)
        self._close_action.setToolTip("保存并关闭当前项目，返回主页 (Ctrl+Shift+W)")
        self._close_action.triggered.connect(self._handle_close_project)

        # 摘要详情折叠：次级动作，窄窗口时可进入「更多」。
        self._toggle_action = QAction("收起摘要", self)
        self._toggle_action.setToolTip("折叠/展开文档编号、指纹、路径等细节")
        self._toggle_action.triggered.connect(self.toggle_summary)

        self._overflow = ActionOverflow(
            self, self._overflow_menu, self._more_btn, spacing=6
        )
        self._overflow.register("validate", self._validate_btn, self._validate_action)
        self._overflow.register("diag_build", self._diag_btn, self._diag_action)
        self._overflow.register("merge", self._merge_btn, self._merge_action)
        # 分支按钮只在有分支时出现：原地控件常驻登记，可见性由渲染与溢出共同决定。
        self._overflow.register("branch", self._branch_btn, self._branch_action)
        self._overflow.register("toggle_summary", self._toggle_btn, self._toggle_action)
        self._overflow.register("close", self._close_btn, self._close_action)

    def refresh_action_overflow(self, available_width: Optional[int] = None) -> bool:
        """按当前可用宽度重排次级动作；返回是否有动作进入「更多」。

        可用宽度取主窗口（父控件）的真实宽度，扣除必须常驻的文档身份、就绪状态、
        主要动作与「更多」按钮本身；用于省略的名称/状态标签只按最小宽度计入，
        因此窄窗口优先压缩文字而不是裁切主动作。
        """
        if self._overflow is None:
            return False
        source = self.parentWidget() if self.parentWidget() is not None else self
        total = int(available_width) if available_width is not None else source.width()
        reserved = 16  # 项目条左右内边距
        for widget in (
            self._name_label,
            self._type_label,
            self._version_label,
        ):
            reserved += max(0, widget.minimumSizeHint().width()) + 10
        for widget in (self._quick_export_btn, self._results_btn, self._more_btn):
            reserved += max(0, widget.sizeHint().width()) + 10
        self._overflow.set_primary_width(reserved)
        # 主要动作不得被压缩：布局后被挤压时继续溢出次级动作。
        self._overflow.protect(self._quick_export_btn, self._results_btn)
        return self._overflow.refresh(max(0, total))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 首次显示时宽度才确定：此时必须重排一次，否则渲染阶段用的是旧宽度。
        self.refresh_action_overflow()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refresh_action_overflow()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # 主题/字体变化会改变完整样式后的 sizeHint：重新核对一次溢出。
        if event.type() in (
            QEvent.Type.StyleChange,
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
        ):
            self.refresh_action_overflow()

    def _on_name_context_menu(self, pos) -> None:
        """文档名右键：复制完整名称与项目路径（省略显示不丢信息）。"""
        menu = QMenu(self)
        name = self._name_label.text()
        copy_name = menu.addAction("复制文档名称")
        copy_name.setEnabled(bool(name))
        path = self._project_path_text
        copy_path = menu.addAction("复制项目路径")
        copy_path.setEnabled(bool(path))
        full = menu.addAction("完整路径：{0}".format(path or "—"))
        full.setEnabled(False)
        chosen = menu.exec(self._name_label.mapToGlobal(pos))
        if chosen is copy_name and name:
            QGuiApplication.clipboard().setText(name)
        elif chosen is copy_path and path:
            QGuiApplication.clipboard().setText(path)

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

        self._project_path_text = str(project_root or "")
        full_name = document_name or (project_root.name if project_root else "未打开项目")
        self._document_name_text = full_name
        self._name_label.setText(full_name)
        self._name_label.setToolTip(
            "{0}\n项目路径：{1}\n（右键可复制完整名称/路径）".format(
                full_name, self._project_path_text or "—"
            )
        )
        type_text = DOC_TYPE_LABELS.get(document_type, document_type)
        self._type_label.setText(type_text if type_text else "")
        self._version_label.setText(
            "v{0}".format(document_version) if document_version else ""
        )
        self._readiness_label.setText(state.readiness_text)
        self._readiness_label.setProperty("statusTone", state.status_tone)
        self._readiness_label.style().unpolish(self._readiness_label)
        self._readiness_label.style().polish(self._readiness_label)

        # 高频入口可用性来自同一状态来源（按钮/菜单/Ctrl+E 三者一致）
        actions = state.actions
        self._set_enabled(
            self._quick_export_btn,
            actions.get("quick_export", None),
            self._quick_export_tooltip(),
        )
        # 「成果」始终可点：没有轮次时给出明确空态说明，而不是禁用成死按钮。
        self._results_btn.setEnabled(True)
        self._results_btn.setToolTip(
            "查看本项目最近出稿轮次与逐文件结果（原轮补缺/新轮/换目录）"
        )
        self._results_btn.setText(
            "成果（{0}）".format(self._round_count) if self._round_count else "成果"
        )
        self._sync_action(
            self._validate_btn, self._validate_action, actions.get("validate", None),
            "检查文档结构、引用与格式；若已生成 Word 则一并校验一致性 (F5)",
        )
        self._sync_action(
            self._diag_btn, self._diag_action, actions.get("diag_build", None),
            "快速生成 DOCX 预览（无需本机 Word，跳过目录域刷新） (Ctrl+Shift+B)",
        )
        self._sync_action(
            self._merge_btn, self._merge_action, actions.get("merge", None),
            "完整生成、刷新目录域与页码并正式归档（需本机 Microsoft Word）",
        )
        self.refresh_action_overflow()

        has_project = bool(document_name or project_root)
        # 显隐统一交给溢出控制器：这里只登记该动作在当前状态下是否可用，
        # 由 refresh_action_overflow 决定它留在原地还是进入「更多」。
        self._toggle_action.setVisible(has_project)
        self._close_action.setVisible(has_project)
        if not has_project:
            self._toggle_btn.setVisible(False)
            self._close_btn.setVisible(False)
        from doc_tool.ui.workbench_state import WorkView
        is_running = (getattr(state, "view", None) == WorkView.RUNNING or getattr(state, "running", False))
        self._close_btn.setEnabled(not is_running)
        self._close_action.setEnabled(not is_running)
        if is_running:
            self._close_btn.setToolTip("任务正在执行中，请等待完成或取消后再关闭项目")
            self._close_action.setToolTip("任务正在执行中，请等待完成或取消后再关闭项目")
        else:
            self._close_btn.setToolTip("保存并关闭当前项目，返回主页 (Ctrl+Shift+W)")
            self._close_action.setToolTip("保存并关闭当前项目，返回主页 (Ctrl+Shift+W)")
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

    def _quick_export_tooltip(self) -> str:
        """快速导出按钮提示：显示实际来源与未保存数量，不隐瞒当前缓冲。"""
        pending = self._pending_edit_count
        source = "当前编辑内容" if pending else "整份已保存内容"
        return "快速导出整份 Word（本机无 Word 也可生成可读稿） (Ctrl+E)：本次来源＝{0}{1}".format(
            source,
            "，含 {0} 章未保存修改".format(pending) if pending else "",
        )

    def set_pending_edits(self, count: int) -> None:
        """由主窗口在渲染前注入未保存修改章节数（0 表示无未保存修改）。"""
        self._pending_edit_count = max(0, int(count or 0))

    def set_round_count(self, count: int) -> None:
        """由主窗口注入本项目已有出稿轮次数（用于「成果」入口提示）。"""
        self._round_count = max(0, int(count or 0))

    @staticmethod
    def _sync_action(button: QPushButton, qaction: QAction, action, default_tooltip: str = "") -> None:
        """把同一份可用性事实同步到原地按钮与其「更多」菜单动作。"""
        if action is None:
            button.setEnabled(False)
            button.setToolTip(default_tooltip)
            qaction.setEnabled(False)
            qaction.setToolTip(default_tooltip)
            return
        enabled = bool(action.enabled)
        button.setEnabled(enabled)
        qaction.setEnabled(enabled)
        if not enabled and getattr(action, "reason", ""):
            button.setToolTip(action.reason)
            qaction.setToolTip(action.reason)
        else:
            button.setToolTip(default_tooltip)
            qaction.setToolTip(default_tooltip)

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
        text = "展开摘要" if self._summary_collapsed else "收起摘要"
        self._toggle_btn.setText(text)
        if getattr(self, "_toggle_action", None) is not None:
            self._toggle_action.setText(text)

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
        self._quick_export_btn.setEnabled(False)
        self._results_btn.setEnabled(False)
        for action in (
            getattr(self, "_validate_action", None),
            getattr(self, "_diag_action", None),
            getattr(self, "_merge_action", None),
            getattr(self, "_branch_action", None),
            getattr(self, "_close_action", None),
        ):
            if action is not None:
                action.setEnabled(False)
        self._project_path_text = ""
        self._document_name_text = ""
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

    def _handle_quick_export(self) -> None:
        if self._on_quick_export is not None:
            self._on_quick_export()

    def _handle_show_results(self) -> None:
        if self._on_show_results is not None:
            self._on_show_results()

    def _handle_switch_branch(self) -> None:
        if self._on_switch_branch is not None:
            self._on_switch_branch()


    def _handle_close_project(self) -> None:
        if self._on_close_project is not None:
            self._on_close_project()
