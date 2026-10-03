# -*- coding: utf-8 -*-
"""研发工作区界面（RD-B～RD-E）。

一个可选入口集中五类视图：工作区成员与概览、条目与关系、矩阵与影响、
版本集合与成果。所有算法都在既有服务里，本模块只负责行渲染、来源跳转与
动作转发；没有工作区时普通单文档编辑与出稿完全不受影响。

来源可信：列表同时显示身份（projectId/itemId）、成员与实际来源（已保存 /
当前缓冲）；补原轮、正式成功等语义不在此处重新定义。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application import rd_surface as surface
from doc_tool.application.workspace import (
    DOCUMENT_ROLES,
    add_project,
    create_workspace,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths


def _item(text: str, *, tooltip: str = "") -> QTableWidgetItem:
    cell = QTableWidgetItem(str(text if text is not None else ""))
    if tooltip:
        cell.setToolTip(tooltip)
    return cell


class RdWorkspaceDialog(QDialog):
    """研发工作区对话框：成员/概览与设置、条目与关系、矩阵与影响、集合与成果。"""

    def __init__(self, host=None, *, root: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("研发工作区")
        self.setObjectName("rdWorkspaceDialog")
        self.setMinimumSize(900, 540)
        self._host = host
        self._root = str(root or "")
        self._workspace = None
        self._members: List[dict] = []
        self._settings_model = None
        self._settings_widgets: Dict[str, QWidget] = {}
        self._index = None
        self._graph = None
        self._member_documents: List[Tuple[str, List[dict]]] = []
        self._matrix: dict = {}
        self._matrix_page = 1
        self._matrix_page_size = 20
        self._matrix_rows: List[dict] = []
        self._collections: List[dict] = []
        self._item_rows: List[dict] = []
        self._relation_rows: List[dict] = []
        self._impact: dict = {}
        self._impact_rows: List[dict] = []
        self._review_rows: List[dict] = []
        self._after_snapshots: Dict[Tuple[str, str], object] = {}
        self._saved_index = None
        self._stale_review_ids: set = set()
        self._workspace_message = ""

        self._build_ui()
        if not self._root:
            self._root = self._host_project_root()
        self.refresh_all()

    # ------------------------------------------------------------------
    # 宿主能力（缺任何一项只禁用对应动作，不影响其他视图）
    # ------------------------------------------------------------------

    def _host_call(self, name: str, *args, **kwargs):
        func = getattr(self._host, name, None)
        if not callable(func):
            return None
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 宿主异常不阻断工作区视图
            self.set_status("{0} 调用失败：{1}".format(name, exc))
            return None

    def _host_project_root(self) -> str:
        return str(self._host_call("rd_project_root") or "")

    def _host_buffers(self) -> Dict[str, str]:
        return dict(self._host_call("rd_collect_buffers") or {})

    def set_status(self, message: str) -> None:
        self._status_label.setText(str(message or ""))
        self._host_call("rd_status", str(message or ""))

    # ------------------------------------------------------------------
    # 界面骨架
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.workspace_label = QLabel("未打开工作区")
        self.workspace_label.setObjectName("rdWorkspaceLabel")
        self.workspace_label.setWordWrap(True)
        header.addWidget(self.workspace_label, 1)
        self.new_workspace_btn = QPushButton("新建工作区…")
        self.new_workspace_btn.setToolTip("在一个目录中创建 workspace.yml；不修改任何成员项目内容")
        self.new_workspace_btn.clicked.connect(self._on_new_workspace)
        header.addWidget(self.new_workspace_btn)
        self.open_workspace_btn = QPushButton("打开工作区…")
        self.open_workspace_btn.clicked.connect(self._on_open_workspace)
        header.addWidget(self.open_workspace_btn)
        self.save_workspace_btn = QPushButton("保存工作区")
        self.save_workspace_btn.setToolTip("把当前成员与角色写入 workspace.yml（复用既有工作区服务）")
        self.save_workspace_btn.clicked.connect(self._on_save_workspace)
        header.addWidget(self.save_workspace_btn)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_all)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_members_tab(), "成员与概览")
        self.tabs.addTab(self._build_items_tab(), "条目与关系")
        self.tabs.addTab(self._build_matrix_tab(), "矩阵与影响")
        self.tabs.addTab(self._build_collection_tab(), "集合与成果")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setObjectName("rdStatusLabel")
        self._status_label.setWordWrap(True)
        footer.addWidget(self._status_label, 1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    # ------------------------------------------------------------------
    # RD-B：成员、概览与设置
    # ------------------------------------------------------------------

    def _build_members_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("工作区成员（角色是元数据，不改通用项目类型）"))
        self.member_table = QTableWidget(0, 6)
        self.member_table.setHorizontalHeaderLabels(
            ["角色", "文档", "项目路径", "版本", "模式", "状态"]
        )
        self.member_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.member_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.member_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.member_table.itemSelectionChanged.connect(self._on_member_selected)
        left_layout.addWidget(self.member_table, 1)

        buttons = QHBoxLayout()
        self.open_member_btn = QPushButton("打开成员")
        self.open_member_btn.setToolTip("在新窗口打开/激活该成员项目；其他项目未保存缓冲保持")
        self.open_member_btn.clicked.connect(self._on_open_member)
        buttons.addWidget(self.open_member_btn)
        self.add_ref_btn = QPushButton("引用加入…")
        self.add_ref_btn.setToolTip("引用已在工作区目录内的项目；不复制、不改写源项目")
        self.add_ref_btn.clicked.connect(lambda: self._on_add_member(copy_external=False))
        buttons.addWidget(self.add_ref_btn)
        self.add_copy_btn = QPushButton("复制加入…")
        self.add_copy_btn.setToolTip("把外部项目复制进工作区并生成新的 projectId")
        self.add_copy_btn.clicked.connect(lambda: self._on_add_member(copy_external=True))
        buttons.addWidget(self.add_copy_btn)
        self.relocate_member_btn = QPushButton("重新定位…")
        self.relocate_member_btn.clicked.connect(self._on_relocate_member)
        buttons.addWidget(self.relocate_member_btn)
        self.remove_member_btn = QPushButton("移除成员")
        self.remove_member_btn.setToolTip("只从工作区清单移除；不删除成员项目文件")
        self.remove_member_btn.clicked.connect(self._on_remove_member)
        buttons.addWidget(self.remove_member_btn)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        overview_box = QGroupBox("项目概览与下一步（服务真值）")
        overview_layout = QVBoxLayout(overview_box)
        self.overview_target = QComboBox()
        self.overview_target.setToolTip("概览按选定成员的真实项目计算；缺成员时只影响该成员")
        self.overview_target.currentIndexChanged.connect(self.refresh_overview)
        overview_layout.addWidget(self.overview_target)
        self.overview_text = QPlainTextEdit()
        self.overview_text.setReadOnly(True)
        self.overview_text.setObjectName("rdOverviewText")
        overview_layout.addWidget(self.overview_text, 3)
        overview_layout.addWidget(QLabel("可执行下一步"))
        self.next_actions = QListWidget()
        self.next_actions.setObjectName("rdNextActions")
        overview_layout.addWidget(self.next_actions, 1)
        right_layout.addWidget(overview_box, 3)

        settings_box = QGroupBox("当前项目设置（按分组保存，字段错误就地显示）")
        settings_layout = QVBoxLayout(settings_box)
        row = QHBoxLayout()
        self.settings_group = QComboBox()
        self.settings_group.currentIndexChanged.connect(self._refresh_settings_group)
        row.addWidget(self.settings_group, 1)
        self.save_settings_btn = QPushButton("保存当前分组")
        self.save_settings_btn.clicked.connect(self._on_save_settings_group)
        row.addWidget(self.save_settings_btn)
        settings_layout.addLayout(row)
        self.settings_form_host = QWidget()
        self.settings_form_host.setObjectName("authoringScrollContent")
        self.settings_form_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.settings_form = QFormLayout(self.settings_form_host)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("authoringScroll")
        self.settings_scroll.viewport().setObjectName("authoringScrollViewport")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.settings_scroll.setWidget(self.settings_form_host)
        settings_layout.addWidget(self.settings_scroll, 1)
        self.settings_error = QLabel("")
        self.settings_error.setObjectName("rdSettingsError")
        self.settings_error.setWordWrap(True)
        settings_layout.addWidget(self.settings_error)
        right_layout.addWidget(settings_box, 4)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        return page

    # ------------------------------------------------------------------
    # RD-C：稳定条目与关系
    # ------------------------------------------------------------------

    def _build_items_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.items_source_label = QLabel("")
        self.items_source_label.setObjectName("rdItemsSourceLabel")
        self.items_source_label.setWordWrap(True)
        layout.addWidget(self.items_source_label)

        actions = QHBoxLayout()
        self.item_kind = QComboBox()
        for kind, label in sorted(surface.KIND_LABELS.items()):
            self.item_kind.addItem(label, kind)
        actions.addWidget(self.item_kind)
        self.declare_btn = QPushButton("声明条目")
        self.declare_btn.setToolTip("在光标所在行插入稳定条目标记；一次撤销可还原")
        self.declare_btn.clicked.connect(self._on_declare_item)
        actions.addWidget(self.declare_btn)
        self.copy_item_btn = QPushButton("复制条目")
        self.copy_item_btn.setToolTip("按既有 item_actions 规则生成新 ID，写入当前缓冲")
        self.copy_item_btn.clicked.connect(self._on_copy_item)
        actions.addWidget(self.copy_item_btn)
        self.renumber_btn = QPushButton("改编号…")
        self.renumber_btn.setToolTip("只改展示编号，稳定 ID 不变")
        self.renumber_btn.clicked.connect(self._on_renumber_item)
        actions.addWidget(self.renumber_btn)
        self.locate_item_btn = QPushButton("定位来源")
        self.locate_item_btn.clicked.connect(self._on_locate_item)
        actions.addWidget(self.locate_item_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.item_table = QTableWidget(0, 5)
        self.item_table.setHorizontalHeaderLabels(["类型", "编号", "别名", "位置", "状态"])
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.item_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.item_table, 3)

        relation_box = QGroupBox("显式关系（两端为真实条目；重复建立保持幂等）")
        relation_layout = QVBoxLayout(relation_box)
        pick = QHBoxLayout()
        self.rel_source = QComboBox()
        self.rel_source.setEditable(True)
        self.rel_source.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.rel_source.setToolTip("来源端：可输入成员/章节/编号检索真实条目")
        pick.addWidget(QLabel("来源"))
        pick.addWidget(self.rel_source, 1)
        pick.addWidget(QLabel("目标"))
        self.rel_target = QComboBox()
        self.rel_target.setEditable(True)
        self.rel_target.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        pick.addWidget(self.rel_target, 1)
        self.rel_type = QComboBox()
        for option in surface.relation_type_options():
            self.rel_type.addItem(option["label"], option["type"])
        pick.addWidget(self.rel_type)
        self.rel_note = QLineEdit()
        self.rel_note.setPlaceholderText("备注（可选）")
        pick.addWidget(self.rel_note, 1)
        relation_layout.addLayout(pick)

        rel_buttons = QHBoxLayout()
        self.add_relation_btn = QPushButton("建立关系")
        self.add_relation_btn.clicked.connect(self._on_add_relation)
        rel_buttons.addWidget(self.add_relation_btn)
        self.save_endpoints_btn = QPushButton("仅保存相关两端并建立")
        self.save_endpoints_btn.setToolTip("只保存关系两端所在章节，不隐式保存整个工作区")
        self.save_endpoints_btn.clicked.connect(self._on_save_endpoints_and_add)
        rel_buttons.addWidget(self.save_endpoints_btn)
        self.remove_relation_btn = QPushButton("删除关系")
        self.remove_relation_btn.clicked.connect(self._on_remove_relation)
        rel_buttons.addWidget(self.remove_relation_btn)
        self.relation_draft_label = QLabel("")
        self.relation_draft_label.setObjectName("rdRelationDraft")
        self.relation_draft_label.setWordWrap(True)
        rel_buttons.addWidget(self.relation_draft_label, 1)
        relation_layout.addLayout(rel_buttons)

        self.relation_table = QTableWidget(0, 4)
        self.relation_table.setHorizontalHeaderLabels(["类型", "来源", "目标", "状态"])
        self.relation_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.relation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.relation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.relation_table.itemSelectionChanged.connect(self._on_relation_selected)
        relation_layout.addWidget(self.relation_table, 2)
        layout.addWidget(relation_box, 2)
        return page

    def _current_document(self) -> Tuple[str, str, str]:
        """当前章节的 ``(rel_path, text, projectId)``；没有打开章节时为空。"""
        rel_path = str(self._host_call("rd_current_chapter") or "")
        project_id = ""
        try:
            project_id = str(self._host_call("rd_project_id") or "")
        except Exception:  # noqa: BLE001
            project_id = ""
        if not project_id and self._root:
            manifest = self._load_manifest(Path(self._root))
            project_id = str(getattr(manifest, "projectId", "") or "") if manifest else ""
        buffers = self._host_buffers()
        text = buffers.get(rel_path)
        if text is None and rel_path:
            try:
                text = (Path(self._current_content_root()) / rel_path).read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 - 读不到就按无内容处理
                text = None
        return rel_path, text or "", project_id

    def _current_content_root(self) -> Path:
        root = Path(self._root or ".")
        manifest = self._load_manifest(root)
        if manifest is not None:
            return root / manifest.relative_content_root()
        return root / "content"

    @staticmethod
    def _load_manifest(root: Optional[Path]):
        if root is None:
            return None
        try:
            return ProjectManifest.load(Path(root))
        except Exception:  # noqa: BLE001 - 不可读项目按无清单处理
            return None

    def _apply_edit(self, rel_path: str, text: str, message: str) -> bool:
        """把条目动作结果写回编辑缓冲（一次事务，可一次撤销）。"""
        if not rel_path:
            self.set_status("没有打开的章节：请先在编辑器中打开要修改的章节")
            return False
        applied = self._host_call("rd_apply_item_edit", rel_path, text, message)
        if applied is None:
            self.set_status("当前环境不支持写回编辑缓冲：{0}".format(message))
            return False
        self.set_status(message)
        self.refresh_items()
        return True

    def _on_declare_item(self) -> None:
        from doc_tool.application.content.item_actions import insert_item

        rel_path, text, project_id = self._current_document()
        if not rel_path:
            self.set_status("请先打开要声明条目的章节")
            return
        line_no = int(self._host_call("rd_cursor_line") or 0)
        kind = self.item_kind.currentData() or "requirement"
        result = insert_item(text, project_id=project_id, kind=kind, line_no=line_no)
        if not result.ok:
            self.set_status("声明条目失败：{0}".format(result.message))
            return
        self._apply_edit(rel_path, result.text, "已在第 {0} 行声明条目".format(result.line_no))

    def _on_copy_item(self) -> None:
        from doc_tool.application.content.item_actions import duplicate_item

        row = self.item_table.currentRow()
        if row < 0 or row >= len(self._item_rows):
            self.set_status("请先选择要复制的条目")
            return
        target = self._item_rows[row]
        rel_path, text, project_id = self._current_document()
        source_line = 0
        if target["projectId"] == project_id:
            for place in target.get("locations") or []:
                if place.get("relPath") == rel_path:
                    source_line = int(place.get("lineNo") or 0)
                    break
        if not source_line:
            self.set_status("该条目不在当前章节中：请先打开它所在章节再复制")
            return
        result = duplicate_item(text, source_line=source_line, project_id=project_id or target["projectId"])
        if not result.ok:
            self.set_status("复制条目失败：{0}".format(result.message))
            return
        self._apply_edit(rel_path, result.text, "已复制条目 {0}".format(getattr(result.item, "item_id", "")))

    def _on_renumber_item(self) -> None:
        from doc_tool.application.content.item_actions import renumber_item

        row = self.item_table.currentRow()
        if row < 0 or row >= len(self._item_rows):
            self.set_status("请先选择要改编号的条目")
            return
        target = self._item_rows[row]
        rel_path, text, project_id = self._current_document()
        line_no = 0
        if target["projectId"] == project_id:
            for place in target.get("locations") or []:
                if place.get("relPath") == rel_path:
                    line_no = int(place.get("lineNo") or 0)
                    break
        if not line_no:
            self.set_status("该条目不在当前章节中：请先打开它所在章节")
            return
        new_number, ok = QInputDialog.getText(self, "改编号", "新的展示编号（稳定 ID 不变）：")
        if not ok or not str(new_number).strip():
            return
        result = renumber_item(text, line_no=line_no, new_number=str(new_number).strip())
        if not result.ok:
            self.set_status("改编号失败：{0}".format(result.message))
            return
        self._apply_edit(rel_path, result.text, "已改编号为 {0}".format(new_number))

    def _on_locate_item(self) -> None:
        row = self.item_table.currentRow()
        if row < 0 or row >= len(self._item_rows):
            self.set_status("请先选择要定位的条目")
            return
        target = self._item_rows[row]
        locations = surface.locate_sources(
            target["itemId"], self._index, project_id=target["projectId"],
            members=self._member_lookup(), source=self._row_source(target),
        )
        if not locations:
            self.set_status("定位失败：条目 {0} 不在当前索引中（可能已删除或只在未保存缓冲）".format(target["itemId"]))
            return
        self.locate_source(locations[0])

    def locate_source(self, location: surface.SourceLocation) -> bool:
        """跳转到真实来源：跨项目先激活成员，再定位文件与行。"""
        if not location.ok:
            self.set_status("无法定位：{0}".format(location.reason or "来源不可用"))
            return False
        opened = self._host_call("rd_open_source", location.relPath, location.lineNo, location.source)
        self.set_status("已定位：{0}".format(location.describe()))
        return bool(opened)

    def _on_relation_selected(self) -> None:
        row = self.relation_table.currentRow()
        if row < 0 or row >= len(self._relation_rows):
            self.relation_draft_label.setText("")
            return
        target = self._relation_rows[row]
        self.relation_draft_label.setText(
            "{0}：{1} → {2}".format(target["typeLabel"], target["sourceLabel"], target["targetLabel"])
        )

    def _selected_endpoint(self, combo: QComboBox):
        data = combo.currentData()
        if isinstance(data, (list, tuple)) and len(data) == 2:
            return (str(data[0]), str(data[1]))
        return None

    def _on_add_relation(self) -> None:
        self._add_relation(save_endpoints=False)

    def _on_save_endpoints_and_add(self) -> None:
        self._add_relation(save_endpoints=True)

    def _add_relation(self, *, save_endpoints: bool) -> None:
        from doc_tool.application.content.relations import Endpoint, add_relation, save_relations

        source_key = self._selected_endpoint(self.rel_source)
        target_key = self._selected_endpoint(self.rel_target)
        if source_key is None or target_key is None:
            self.set_status("请先选择关系的两端真实条目")
            return
        if source_key == target_key:
            self.set_status("关系两端不能是同一个条目")
            return
        graph = self._graph if self._graph is not None else surface.empty_graph()
        pending = surface.endpoints_needing_save(
            self._saved_index if self._saved_index is not None else self._index, source_key, target_key,
        ) if self._index else []
        if pending and not save_endpoints:
            names = "、".join("{0}/{1}".format(item["projectId"], item["itemId"]) for item in pending)
            self.relation_draft_label.setText(
                "关系草稿已保留：端点 {0} 只在未保存缓冲中；可点“仅保存相关两端并建立”。".format(names)
            )
            self.set_status("关系草稿已保留，未写入 relations.yml")
            return
        if pending and save_endpoints:
            saved = self._save_endpoints(pending)
            if not saved:
                self.set_status("保存关系两端失败：关系草稿保留，未写入 relations.yml")
                return
            self.rebuild_index()
            graph = self._graph if self._graph is not None else graph
        relation, error = add_relation(
            graph, relation_type=str(self.rel_type.currentData() or "satisfies"),
            source=Endpoint(source_key[0], source_key[1]),
            target=Endpoint(target_key[0], target_key[1]),
            note=self.rel_note.text().strip(),
        )
        if relation is None:
            self.set_status("建立关系失败：{0}".format(error or "未知原因"))
            return
        path = self._relations_write_path()
        if path is None:
            self.set_status("工作区/项目关系文件位置未知：关系草稿保留，未写入磁盘")
            return
        try:
            save_relations(path, graph)
        except Exception as exc:  # noqa: BLE001 - 只读项目等失败保留草稿
            self.set_status("关系未写入（{0}）：可稍后重试或改用“仅保存相关两端”".format(exc))
            return
        self.rel_note.clear()
        self.refresh_relations()
        self.set_status("关系已保存：{0} → {1}".format(source_key[1], target_key[1]))

    def _saved_paths(self) -> List[str]:
        """当前以磁盘内容为准的章节路径（多成员合并）。"""
        paths: List[str] = []
        for _project_id, docs in self._member_documents:
            paths.extend(doc["relPath"] for doc in docs if doc["source"] == surface.SOURCE_SAVED)
        return paths

    def _save_endpoints(self, pending: Sequence[dict]) -> bool:
        """只保存关系两端所在章节；其他成员的端点请在对应窗口保存。"""
        current_id = str(self._host_call("rd_project_id") or "")
        rel_paths = set()
        foreign = []
        for item in pending:
            if current_id and item["projectId"] and item["projectId"] != current_id:
                foreign.append(item)
                continue
            for location in surface.locate_sources(item["itemId"], self._index, project_id=item["projectId"]):
                rel_paths.add(location.relPath)
        if foreign:
            self.set_status(
                "端点属于其他成员项目（{0}）：请在对应窗口保存后重试；关系草稿保留。".format(
                    "、".join(item["itemId"] for item in foreign),
                )
            )
            return False
        if not rel_paths:
            self.set_status("找不到端点的真实文件：无法只保存相关两端")
            return False
        saved = self._host_call("rd_save_chapters", sorted(rel_paths))
        return bool(saved)

    def _on_remove_relation(self) -> None:
        from doc_tool.application.content.relations import remove_relation, save_relations

        row = self.relation_table.currentRow()
        if row < 0 or row >= len(self._relation_rows):
            self.set_status("请先选择要删除的关系")
            return
        target = self._relation_rows[row]
        graph = self._graph if self._graph is not None else surface.empty_graph()
        if not remove_relation(graph, target["relationId"]):
            self.set_status("关系不存在或已被删除：{0}".format(target["relationId"]))
            return
        path = self._relations_write_path()
        if path is None:
            self.set_status("关系文件位置未知：未写入磁盘")
            return
        try:
            save_relations(path, graph)
        except Exception as exc:  # noqa: BLE001 - 写入失败保留原文件
            self.set_status("删除未写入：{0}".format(exc))
            return
        self.refresh_relations()
        self.set_status("已删除关系 {0}".format(target["relationId"]))

    def _relations_write_path(self) -> Optional[Path]:
        if self._workspace is not None and self._root:
            existing = surface.relations_path_for(self._workspace, self._root)
            if existing is not None:
                return existing
            rel = str(getattr(self._workspace, "relations_path", "") or "relations.yml")
            if rel and not rel.startswith("/") and ".." not in rel.split("/"):
                return Path(self._root) / rel
        if self._root:
            return Path(self._root) / "relations.yml"
        return None

    # ------------------------------------------------------------------
    # RD-D：矩阵与影响复核
    # ------------------------------------------------------------------

    def _build_matrix_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        metrics = QHBoxLayout()
        self.metric_labels: Dict[str, QLabel] = {}
        for key, text in (("total", "需求条目"), ("design", "设计覆盖"), ("test", "测试覆盖"), ("direct", "直接测试"), ("review", "已复核")):
            box = QVBoxLayout()
            box.addWidget(QLabel(text))
            label = QLabel("—")
            label.setObjectName("rdMetric_{0}".format(key))
            box.addWidget(label)
            self.metric_labels[key] = label
            metrics.addLayout(box)
        layout.addLayout(metrics)

        controls = QHBoxLayout()
        self.only_uncovered = QCheckBox("只看未覆盖")
        self.only_uncovered.stateChanged.connect(self._on_matrix_filter_changed)
        controls.addWidget(self.only_uncovered)
        self.prev_page_btn = QPushButton("上一页")
        self.prev_page_btn.clicked.connect(lambda: self._change_page(-1))
        controls.addWidget(self.prev_page_btn)
        self.next_page_btn = QPushButton("下一页")
        self.next_page_btn.clicked.connect(lambda: self._change_page(1))
        controls.addWidget(self.next_page_btn)
        self.page_label = QLabel("第 1/1 页")
        self.page_label.setObjectName("rdMatrixPageLabel")
        controls.addWidget(self.page_label)
        self.matrix_locate_btn = QPushButton("定位需求来源")
        self.matrix_locate_btn.clicked.connect(self._on_locate_matrix_row)
        controls.addWidget(self.matrix_locate_btn)
        self.matrix_source_label = QLabel("")
        self.matrix_source_label.setWordWrap(True)
        controls.addWidget(self.matrix_source_label, 1)
        layout.addLayout(controls)

        self.matrix_table = QTableWidget(0, 5)
        self.matrix_table.setHorizontalHeaderLabels(["需求", "设计覆盖", "直接测试", "间接测试", "来源"])
        self.matrix_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.matrix_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.matrix_table, 3)

        impact_box = QGroupBox("变化与影响（已保存版本 ↔ 当前缓冲）")
        impact_layout = QVBoxLayout(impact_box)
        impact_buttons = QHBoxLayout()
        self.calc_impact_btn = QPushButton("计算影响")
        self.calc_impact_btn.setToolTip("比较已保存内容与当前缓冲，标明来源；不写入任何评审状态")
        self.calc_impact_btn.clicked.connect(self.refresh_impact)
        impact_buttons.addWidget(self.calc_impact_btn)
        self.impact_locate_btn = QPushButton("定位影响来源")
        self.impact_locate_btn.clicked.connect(self._on_locate_impact_row)
        impact_buttons.addWidget(self.impact_locate_btn)
        self.impact_summary = QLabel("")
        self.impact_summary.setObjectName("rdImpactSummary")
        self.impact_summary.setWordWrap(True)
        impact_buttons.addWidget(self.impact_summary, 1)
        impact_layout.addLayout(impact_buttons)

        self.impact_table = QTableWidget(0, 4)
        self.impact_table.setHorizontalHeaderLabels(["来源条目", "受影响条目", "类型", "说明"])
        self.impact_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.impact_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.impact_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        impact_layout.addWidget(self.impact_table, 2)

        review_buttons = QHBoxLayout()
        review_buttons.addWidget(QLabel("复核记录（绑定已保存摘要，不自动升级为通过）"))
        self.confirm_review_btn = QPushButton("确认当前摘要复核")
        self.confirm_review_btn.setToolTip("只有当前已保存摘要与界面一致时才可确认；内容再变会重新变为待复核")
        self.confirm_review_btn.clicked.connect(self._on_confirm_review)
        review_buttons.addWidget(self.confirm_review_btn)
        self.recheck_review_btn = QPushButton("重检选中关系")
        self.recheck_review_btn.clicked.connect(self._on_recheck_review)
        review_buttons.addWidget(self.recheck_review_btn)
        review_buttons.addStretch(1)
        impact_layout.addLayout(review_buttons)

        self.review_table = QTableWidget(0, 4)
        self.review_table.setHorizontalHeaderLabels(["关系", "状态", "复核时间", "说明"])
        self.review_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.review_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        impact_layout.addWidget(self.review_table, 2)
        layout.addWidget(impact_box, 3)
        return page

    def _change_page(self, delta: int) -> None:
        self._matrix_page = max(1, int(self._matrix_page) + int(delta))
        self.refresh_matrix()

    def _on_matrix_filter_changed(self, *_args) -> None:
        self._matrix_page = 1
        self.refresh_matrix()

    def _on_locate_matrix_row(self) -> None:
        row = self.matrix_table.currentRow()
        if row < 0 or row >= len(self._matrix_rows):
            self.set_status("请先选择矩阵中的需求行")
            return
        target = self._matrix_rows[row]
        location = (target.get("sourceLocation") or {})
        if not location or not location.get("ok"):
            self.set_status("定位失败：{0}".format((location or {}).get("reason") or "来源不可用"))
            return
        self.locate_source(surface.SourceLocation(**{
            key: location.get(key) for key in (
                "projectId", "itemId", "relPath", "lineNo", "headingNo", "memberRole",
                "memberName", "memberPath", "memberVersion", "source", "ok", "reason",
            )
        }))

    def _on_locate_impact_row(self) -> None:
        row = self.impact_table.currentRow()
        if row < 0 or row >= len(self._impact_rows):
            self.set_status("请先选择影响行")
            return
        target = self._impact_rows[row]
        location = target.get("targetLocation") or target.get("sourceLocation") or {}
        if not location or not location.get("ok"):
            self.set_status("定位失败：{0}".format((location or {}).get("reason") or "来源不可用"))
            return
        self.locate_source(surface.SourceLocation(**{
            key: location.get(key) for key in (
                "projectId", "itemId", "relPath", "lineNo", "headingNo", "memberRole",
                "memberName", "memberPath", "memberVersion", "source", "ok", "reason",
            )
        }))

    def _review_store(self):
        if not self._root:
            return None
        try:
            from doc_tool.application.content.impact import ReviewRecordStore

            return ReviewRecordStore(Path(self._root) / ".state")
        except Exception:  # noqa: BLE001 - 记录不可用只影响复核视图
            return None

    def _snapshot_hashes(self, snapshots) -> Dict[Tuple[str, str], str]:
        result: Dict[Tuple[str, str], str] = {}
        for key, item in (snapshots or {}).items():
            try:
                result[key] = item.semantic_hash()
            except Exception:  # noqa: BLE001 - 单条摘要失败不影响其它条目
                continue
        return result

    def _review_keys(self):
        store = self._review_store()
        if store is None:
            return None, None
        try:
            pending = [record.source for record in store.pending()] + [record.target for record in store.pending()]
            confirmed = [record.source for record in store.records() if str(getattr(record, "status", "")) == "confirmed"]
        except Exception:  # noqa: BLE001 - 坏记录不阻断矩阵
            return None, None
        return pending, confirmed

    def _on_confirm_review(self) -> None:
        row = self.review_table.currentRow()
        if row < 0 or row >= len(self._review_rows):
            self.set_status("请先选择要确认的复核记录")
            return
        record = self._review_rows[row]
        store = self._review_store()
        if store is None:
            self.set_status("复核记录不可用：未确认任何记录")
            return
        hashes = self._snapshot_hashes(self._after_snapshots)
        source_hash = hashes.get(tuple(record.get("source") or ()))
        target_hash = hashes.get(tuple(record.get("target") or ()))
        if not source_hash or not target_hash:
            self.set_status("当前已保存摘要不完整：保留待复核，未标记为通过")
            return
        try:
            store.confirm(
                record["relationId"], tuple(record["source"]), tuple(record["target"]),
                source_hash=source_hash, target_hash=target_hash,
            )
        except Exception as exc:  # noqa: BLE001 - 失败保留待复核
            self.set_status("确认复核失败：{0}".format(exc))
            return
        self.refresh_impact()
        self.refresh_matrix()
        self.set_status("已按当前已保存摘要确认复核：{0}".format(record["relationId"]))

    def _on_recheck_review(self) -> None:
        row = self.review_table.currentRow()
        if row < 0 or row >= len(self._review_rows):
            self.set_status("请先选择要重检的复核记录")
            return
        record = self._review_rows[row]
        store = self._review_store()
        if store is None:
            self.set_status("复核记录不可用：未重检任何记录")
            return
        try:
            from doc_tool.application.review.versioned_review import request_recheck

            request_recheck(store, record["relationId"], note="界面重检")
        except Exception as exc:  # noqa: BLE001 - 重检失败保留原状态
            self.set_status("重检请求失败：{0}".format(exc))
            return
        self.refresh_impact()
        self.set_status("已请求重检：{0}".format(record["relationId"]))

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------

    def refresh_all(self) -> None:
        if not self._root:
            self._root = self._host_project_root()
        self.refresh_members()
        self.refresh_overview()
        self.refresh_settings()
        self.rebuild_index()
        self.refresh_items()
        self.refresh_relations()
        self.refresh_matrix()
        self.refresh_impact()
        self.refresh_collections()

    def refresh_members(self) -> None:
        buffers = self._host_buffers()
        self._workspace = None
        self._workspace_message = ""
        if self._root:
            workspace, message = surface.open_workspace(self._root)
            if workspace is not None:
                self._workspace = workspace
            else:
                self._workspace_message = message
        if self._workspace is not None:
            self._members = surface.member_rows(
                self._workspace, buffers=buffers if self._buffers_for(Path(self._root)) is not None else {}
            )
            state = surface.workspace_state(self._workspace)
            self.workspace_label.setText(
                "工作区：{0}（集合版本 {1}｜成员 {2}｜覆盖率 {3}）".format(
                    state["name"], state["collectionVersion"], state["memberCount"], state["coverage"]
                )
            )
        else:
            self._members = self._single_project_member(buffers)
            self.workspace_label.setText(
                "未打开工作区：{0}".format(self._workspace_message or "单文档可直接编辑与出稿")
            )
        self._fill_member_table()

    def _single_project_member(self, buffers: Mapping[str, str]) -> List[dict]:
        root = Path(self._root) if self._root else None
        manifest = self._load_manifest(root)
        if root is None or manifest is None:
            return []
        schema = int(getattr(manifest, "schemaVersion", 0) or 0)
        writable = bool(manifest.is_writable())
        return [{
            "key": ".",
            "role": "other",
            "roleLabel": "当前项目",
            "name": manifest.documentName or root.name,
            "path": ".",
            "projectId": str(getattr(manifest, "projectId", "") or ""),
            "documentVersion": manifest.documentVersion,
            "schemaVersion": schema,
            "available": True,
            "readonly": not writable,
            "canRead": True,
            "unsavedChapters": sorted(buffers.keys()),
            "hasUnsaved": bool(buffers),
            "status": surface.STATUS_OK if writable else surface.STATUS_WARNING,
            "reason": "" if writable else "模式版本高于当前可写版本：只读打开",
            "nextAction": "打开成员",
            "location": surface.SourceLocation(
                projectId=str(getattr(manifest, "projectId", "") or ""), relPath="",
                memberName=manifest.documentName, ok=True,
            ).to_dict(),
        }]

    def _fill_member_table(self) -> None:
        self.member_table.setRowCount(len(self._members))
        for index, row in enumerate(self._members):
            self.member_table.setItem(index, 0, _item(row["roleLabel"]))
            self.member_table.setItem(index, 1, _item(row["name"]))
            self.member_table.setItem(index, 2, _item(row["path"], tooltip=row["projectId"]))
            self.member_table.setItem(index, 3, _item(row["documentVersion"] or "—"))
            self.member_table.setItem(index, 4, _item(row["schemaVersion"] or "—"))
            status = row["status"]
            if row["hasUnsaved"]:
                status = surface.STATUS_PENDING
            text = {"ok": "可用", "warning": "只读/待确认", "error": "不可用", "pending": "有未保存缓冲"}.get(status, status)
            if row["reason"]:
                text = "{0}（{1}）".format(text, row["reason"])
            self.member_table.setItem(index, 5, _item(text, tooltip=row["reason"]))
        if self._members and self.member_table.currentRow() < 0:
            self.member_table.selectRow(0)
        self._refresh_buffers_hint()

    def _refresh_buffers_hint(self) -> None:
        pending = sum(1 for row in self._members if row["hasUnsaved"])
        if pending:
            self.set_status("有 {0} 个成员存在未保存缓冲：出稿可选“当前内容”，源文件不会被写回".format(pending))

    def _on_member_selected(self) -> None:
        row = self.member_table.currentRow()
        if row < 0 or row >= len(self._members):
            return
        target = self._members[row]
        self.overview_target.blockSignals(True)
        self.overview_target.clear()
        for item in self._members:
            self.overview_target.addItem("{0}｜{1}".format(item["roleLabel"], item["name"]), item["key"])
        self.overview_target.setCurrentIndex(row)
        self.overview_target.blockSignals(False)
        self.refresh_overview()

    def _member_root(self, row: dict) -> Optional[Path]:
        if not self._root:
            return None
        if self._workspace is None or row.get("path") in (".", ""):
            return Path(self._root)
        return Path(self._root) / row["path"]

    def _buffers_for(self, member_root: Optional[Path]) -> Optional[Dict[str, str]]:
        if member_root is None:
            return {}
        current = self._host_project_root() or self._root
        try:
            if Path(current).resolve() == Path(member_root).resolve():
                return self._host_buffers()
        except Exception:  # noqa: BLE001 - 路径异常按无缓冲处理
            return {}
        return {}

    def _member_lookup(self) -> Dict[str, dict]:
        return {row["projectId"]: row for row in self._members if row.get("projectId")}

    def _all_documents(self) -> List[Tuple[str, List[dict]]]:
        """[(projectId, [{relPath,text,source}])]，缺成员不影响其他成员。"""
        entries: List[Tuple[str, List[dict]]] = []
        for row in self._members:
            if not row.get("canRead"):
                continue
            root = self._member_root(row)
            if root is None:
                continue
            docs = surface.documents_with_buffers(
                surface.project_documents(root), self._buffers_for(root),
            )
            entries.append((row["projectId"], docs))
        return entries

    def rebuild_index(self) -> None:
        self._member_documents = self._all_documents()
        entries = [
            (project_id, [(doc["relPath"], doc["text"]) for doc in docs])
            for project_id, docs in self._member_documents
        ]
        self._index = surface.combined_index(entries) if entries else None
        # 只用磁盘内容建立“已保存索引”：判断端点是否真的落盘。
        saved_entries = [
            (project_id, [(doc["relPath"], doc["text"]) for doc in docs if doc["source"] == surface.SOURCE_SAVED])
            for project_id, docs in self._member_documents
        ]
        saved_entries = [(project_id, docs) for project_id, docs in saved_entries if docs]
        self._saved_index = surface.combined_index(saved_entries) if saved_entries else None
        if self._root:
            try:
                graph, _documents = surface.collect_graph(
                    Path(self._root), workspace=self._workspace is not None,
                )
            except Exception:  # noqa: BLE001 - 图不可读时按空图处理，不阻断条目/矩阵
                graph = surface.empty_graph()
        else:
            graph = surface.empty_graph()
        self._graph = graph

    def _row_source(self, row: dict) -> str:
        for project_id, docs in self._member_documents:
            if project_id != row.get("projectId"):
                continue
            for doc in docs:
                for place in row.get("locations") or []:
                    if place.get("relPath") == doc["relPath"]:
                        return doc["source"]
        return surface.SOURCE_SAVED

    def refresh_items(self) -> None:
        self._item_rows = surface.item_rows(self._index) if self._index is not None else []
        self.item_table.setRowCount(len(self._item_rows))
        for index, row in enumerate(self._item_rows):
            self.item_table.setItem(index, 0, _item(row["kindLabel"]))
            self.item_table.setItem(index, 1, _item(row["itemId"]))
            self.item_table.setItem(index, 2, _item(row["alias"] or "—"))
            place = (row["locations"] or [{}])[0]
            position = "{0}:{1}".format(place.get("relPath", "—"), place.get("lineNo", ""))
            self.item_table.setItem(index, 3, _item(position, tooltip=row["marker"]))
            source = surface.source_label(self._row_source(row))
            state = "重复 ID" if row["duplicate"] else "正常"
            self.item_table.setItem(index, 4, _item("{0}｜{1}".format(state, source)))
        buffers = self._host_buffers()
        issues = surface.item_issues(self._index) if self._index is not None else []
        self.items_source_label.setText(
            "索引来源：{0} 个成员；未保存缓冲章节 {1}；条目 {2} 条；索引问题 {3} 条".format(
                len(self._member_documents), len(buffers), len(self._item_rows), len(issues),
            )
        )

    def refresh_relations(self) -> None:
        if self._index is not None and self._graph is not None:
            self._relation_rows = surface.relation_rows(self._graph, self._index, members=self._member_lookup())
        else:
            self._relation_rows = []
        self.relation_table.setRowCount(len(self._relation_rows))
        for index, row in enumerate(self._relation_rows):
            self.relation_table.setItem(index, 0, _item(row["typeLabel"]))
            self.relation_table.setItem(index, 1, _item(row["sourceLabel"]))
            self.relation_table.setItem(index, 2, _item(row["targetLabel"]))
            self.relation_table.setItem(index, 3, _item(row["reason"] or "有效", tooltip=row["reason"]))
        self._fill_endpoint_combos()

    def _fill_endpoint_combos(self) -> None:
        options = surface.endpoint_options(self._index, members=self._member_lookup()) if self._index is not None else []
        for combo in (self.rel_source, self.rel_target):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for option in options:
                combo.addItem(
                    "{0}｜{1} {2}{3}".format(
                        option["memberName"], option["kindLabel"], option["itemId"],
                        "（{0}）".format(option["alias"]) if option["alias"] else "",
                    ),
                    [option["projectId"], option["itemId"]],
                )
                combo.setItemData(
                    combo.count() - 1,
                    "{0} {1} {2} {3}".format(
                        option["searchText"], option["relPath"], option["headingNo"], option["sourceLabel"],
                    ),
                    Qt.ItemDataRole.ToolTipRole,
                )
            if previous is not None:
                for index in range(combo.count()):
                    if combo.itemData(index) == previous:
                        combo.setCurrentIndex(index)
                        break
            combo.blockSignals(False)

    def refresh_matrix(self) -> None:
        items = list(self._index.items.values()) if self._index is not None else []
        pending, confirmed = self._review_keys()
        self._matrix = surface.matrix_view(
            items, self._graph if self._graph is not None else surface.empty_graph(),
            page=self._matrix_page, page_size=self._matrix_page_size,
            only_uncovered=bool(self.only_uncovered.isChecked()),
            pending_review_items=pending, confirmed_items=confirmed,
            index=self._index, members=self._member_lookup(),
            source=surface.SOURCE_CAPTURE if self._index is not None else surface.SOURCE_SAVED,
        )
        for metric in self._matrix.get("metrics", []):
            label = self.metric_labels.get(metric["key"])
            if label is not None:
                label.setText(metric["value"])
        page = self._matrix.get("page", {})
        self._matrix_page = int(page.get("page", 1))
        self._matrix_rows = list(page.get("rows") or [])
        self.matrix_table.setRowCount(len(self._matrix_rows))
        for index, row in enumerate(self._matrix_rows):
            self.matrix_table.setItem(index, 0, _item(row["sourceLabel"], tooltip=row["item"]["itemId"]))
            self.matrix_table.setItem(index, 1, _item(", ".join(ref["itemId"] for ref in row["designs"]) or "—"))
            self.matrix_table.setItem(index, 2, _item(", ".join(ref["itemId"] for ref in row["directTests"]) or "—"))
            self.matrix_table.setItem(index, 3, _item(", ".join(ref["itemId"] for ref in row["indirectTests"]) or "—"))
            source = (row.get("sourceLocation") or {}).get("sourceLabel") or "—"
            self.matrix_table.setItem(index, 4, _item(source))
        self.page_label.setText(
            "第 {0}/{1} 页（共 {2} 行）".format(
                page.get("page", 1), page.get("pageCount", 1), page.get("total", 0),
            )
        )
        problems = []
        if self._matrix.get("message"):
            problems.append(self._matrix["message"])
        if self._matrix.get("orphans"):
            problems.append("孤立条目 {0} 条".format(len(self._matrix["orphans"])))
        if self._matrix.get("dangling"):
            problems.append("悬空关系 {0} 条".format(len(self._matrix["dangling"])))
        self.matrix_source_label.setText("；".join(problems))

    def refresh_impact(self) -> None:
        if self._index is None or self._graph is None:
            self._after_snapshots = {}
            self.impact_summary.setText("索引不可用：无法计算影响")
            return
        saved_documents: List[dict] = []
        buffered_documents: List[dict] = []
        for row in self._members:
            if not row.get("canRead"):
                continue
            root = self._member_root(row)
            if root is None:
                continue
            saved = surface.project_documents(root)
            saved_documents.extend(
                {"relPath": rel, "text": text, "source": surface.SOURCE_SAVED} for rel, text in saved
            )
            buffered_documents.extend(
                surface.documents_with_buffers(saved, self._buffers_for(root))
            )
        before = surface.snapshots_from_documents(saved_documents)
        after = surface.snapshots_from_documents(buffered_documents)
        self._after_snapshots = after
        store = self._review_store()
        self._impact = surface.impact_view(
            before, after, self._graph, store=store,
            hashes=self._snapshot_hashes(after),
            index=self._index, members=self._member_lookup(),
            source=surface.SOURCE_BUFFER if self._host_buffers() else surface.SOURCE_SAVED,
        )
        self._impact_rows = list(self._impact.get("entries") or [])
        self.impact_table.setRowCount(len(self._impact_rows))
        for index, row in enumerate(self._impact_rows):
            self.impact_table.setItem(index, 0, _item(row.get("sourceLabel") or row.get("source", "")))
            self.impact_table.setItem(index, 1, _item(row.get("targetLabel") or row.get("target", "")))
            self.impact_table.setItem(index, 2, _item("{0}/{1}".format(row.get("impactType", ""), row.get("path", ""))))
            self.impact_table.setItem(index, 3, _item(row.get("reason", "")))
        review = self._impact.get("review") or {}
        self._review_rows = list(review.get("records") or [])
        # 已保存摘要再变化时，旧复核不得继续显示为通过。
        stale_ids = {item.get("relationId") for item in (review.get("stale") or [])}
        self._stale_review_ids = stale_ids
        self.review_table.setRowCount(len(self._review_rows))
        for index, row in enumerate(self._review_rows):
            changed = row.get("relationId") in stale_ids
            status = "待重检（内容已变化）" if changed else row.get("status", "")
            self.review_table.setItem(index, 0, _item(row.get("relationId", "")))
            self.review_table.setItem(index, 1, _item(status))
            self.review_table.setItem(index, 2, _item(row.get("reviewedAt", "") or "—"))
            self.review_table.setItem(
                index, 3,
                _item("对应已保存条目已变化，需重新复核" if changed else row.get("note", "")),
            )
        changed = len(self._impact.get("changed") or {})
        self.impact_summary.setText(
            "{0}来源：{1}；变化条目 {2}；直接影响 {3}；传递影响 {4}；{5}".format(
                "" if self._impact.get("message") else "",
                self._impact.get("sourceLabel", ""),
                changed,
                len(self._impact.get("direct") or []),
                len(self._impact.get("transitive") or []),
                review.get("message", ""),
            ).strip()
        )

    # ------------------------------------------------------------------
    # RD-E：版本集合与成果
    # ------------------------------------------------------------------

    def _build_collection_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("版本集合（来自已有清单；不按目录名推断正式成功）"))
        self.collection_table = QTableWidget(0, 4)
        self.collection_table.setHorizontalHeaderLabels(["集合版本", "创建时间", "文件数", "状态"])
        self.collection_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.collection_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.collection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.collection_table.itemSelectionChanged.connect(self._on_collection_selected)
        layout.addWidget(self.collection_table, 2)

        buttons = QHBoxLayout()
        self.collection_detail_btn = QPushButton("查看详情")
        self.collection_detail_btn.clicked.connect(self._on_collection_detail)
        buttons.addWidget(self.collection_detail_btn)
        self.compare_btn = QPushButton("比较两份集合…")
        self.compare_btn.clicked.connect(self._on_compare_collections)
        buttons.addWidget(self.compare_btn)
        self.export_package_btn = QPushButton("导出集合包…")
        self.export_package_btn.clicked.connect(self._on_export_package)
        buttons.addWidget(self.export_package_btn)
        self.recover_btn = QPushButton("恢复为副本…")
        self.recover_btn.setToolTip("只在新目录生成副本；不覆盖当前工作区或未保存缓冲")
        self.recover_btn.clicked.connect(self._on_recover_copy)
        buttons.addWidget(self.recover_btn)
        self.delivery_btn = QPushButton("成员交付（复用批量队列）…")
        self.delivery_btn.setToolTip("复用既有 V3.2 持久队列、串行 Word 与逐成员 OutputState")
        self.delivery_btn.clicked.connect(self._on_member_delivery)
        buttons.addWidget(self.delivery_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        artifact_row = QHBoxLayout()
        artifact_row.addWidget(QLabel("成果/清单"))
        self.artifact_combo = QComboBox()
        artifact_row.addWidget(self.artifact_combo, 1)
        self.open_artifact_btn = QPushButton("打开成果")
        self.open_artifact_btn.clicked.connect(self._on_open_artifact)
        artifact_row.addWidget(self.open_artifact_btn)
        layout.addLayout(artifact_row)

        self.collection_detail = QPlainTextEdit()
        self.collection_detail.setReadOnly(True)
        self.collection_detail.setObjectName("rdCollectionDetail")
        layout.addWidget(self.collection_detail, 3)
        self.delivery_status = QLabel("")
        self.delivery_status.setObjectName("rdDeliveryStatus")
        self.delivery_status.setWordWrap(True)
        layout.addWidget(self.delivery_status)
        return page

    def refresh_collections(self) -> None:
        """集合列表：工作区根与每个可读成员项目的已登记清单汇总。"""
        self._collections = []
        roots: List[Tuple[str, Path]] = []
        if self._root:
            roots.append(("工作区", Path(self._root)))
        for row in self._members:
            if not row.get("canRead"):
                continue
            root = self._member_root(row)
            if root is not None:
                roots.append((row.get("name") or row.get("path") or "成员", root))
        messages: List[str] = []
        seen = set()
        for label, root in roots:
            try:
                key = str(Path(root).resolve())
            except Exception:  # noqa: BLE001 - 路径异常按原值去重
                key = str(root)
            if key in seen:
                continue
            seen.add(key)
            payload = surface.collection_rows(root)
            for row in payload.get("rows") or []:
                row = dict(row)
                row["root"] = str(root)
                row["memberLabel"] = label
                self._collections.append(row)
            if payload.get("message"):
                messages.append(payload["message"])
        message = "" if self._collections else (messages[0] if messages else "未指定工作区/项目目录")
        self.collection_table.setRowCount(len(self._collections))
        for index, row in enumerate(self._collections):
            self.collection_table.setItem(index, 0, _item("{0}｜{1}".format(row.get("memberLabel", ""), row.get("version", "")), tooltip=row.get("path", "")))
            self.collection_table.setItem(index, 1, _item(row.get("createdAt", "") or "—"))
            self.collection_table.setItem(index, 2, _item(row.get("fileCount", 0)))
            state = row.get("statusLabel", "")
            if row.get("problems"):
                state = "{0}（问题 {1}）".format(state, len(row["problems"]))
            self.collection_table.setItem(index, 3, _item(state))
        if self._collections and self.collection_table.currentRow() < 0:
            self.collection_table.selectRow(0)
        if message:
            self.set_status(message)

    def _selected_collection(self) -> Optional[dict]:
        row = self.collection_table.currentRow()
        if row < 0 or row >= len(self._collections):
            return None
        return self._collections[row]

    def _on_collection_selected(self) -> None:
        target = self._selected_collection()
        if target is None:
            return
        self._show_collection_detail(target)

    def _on_collection_detail(self) -> None:
        target = self._selected_collection()
        if target is None:
            self.set_status("请先选择一个版本集合")
            return
        self._show_collection_detail(target)

    def _show_collection_detail(self, target: dict) -> None:
        detail = surface.collection_detail(target.get("root") or self._root, target.get("path", ""))
        if not detail.get("ok"):
            self.collection_detail.setPlainText(detail.get("message", "详情不可用"))
            return
        lines = [
            "版本：{0}".format(target.get("version", "")),
            "清单：{0}".format(target.get("path", "")),
            "完整性：{0}".format("完整" if target.get("complete") else "部分/历史清单"),
        ]
        categories = detail.get("categories") or {}
        if categories:
            lines.append("分类：" + "，".join("{0}={1}".format(key, value) for key, value in sorted(categories.items())))
        if detail.get("missing"):
            lines.append("缺失文件 {0}：{1}".format(len(detail["missing"]), "、".join(detail["missing"][:8])))
        if detail.get("problems"):
            lines.append("校验问题 {0}：{1}".format(len(detail["problems"]), "；".join(str(item) for item in detail["problems"][:5])))
        if detail.get("warnings"):
            lines.append("提示：" + "；".join(str(item) for item in detail["warnings"][:5]))
        self.collection_detail.setPlainText("\n".join(lines))
        self.artifact_combo.clear()
        for artifact in detail.get("artifacts") or []:
            if isinstance(artifact, dict):
                relative = str(artifact.get("relativePath") or artifact.get("path") or "")
                if relative:
                    self.artifact_combo.addItem(
                        "{0}（{1}）".format(relative, artifact.get("category", "")), relative,
                    )
            elif artifact:
                # 现有服务用相对路径字符串列出成果/清单。
                self.artifact_combo.addItem(str(artifact), str(artifact))
        self.set_status("已加载集合详情：{0}".format(target.get("version", "")))

    def _on_compare_collections(self) -> None:
        if len(self._collections) < 2:
            self.set_status("至少需要两份集合才能比较")
            return
        versions = [str(row.get("version", "")) for row in self._collections]
        left, ok = QInputDialog.getItem(self, "比较集合", "左侧集合：", versions, 0, False)
        if not ok:
            return
        right, ok = QInputDialog.getItem(self, "比较集合", "右侧集合：", versions, 1, False)
        if not ok:
            return
        left_row = next(row for row in self._collections if str(row.get("version")) == left)
        right_row = next(row for row in self._collections if str(row.get("version")) == right)
        report = surface.collection_compare(left_row.get("path"), right_row.get("path"))
        if not report.get("ok"):
            self.collection_detail.setPlainText(report.get("message", "比较失败"))
            return
        lines = ["比较 {0} → {1}".format(left, right)]
        for group, entries in sorted((report.get("groups") or {}).items()):
            lines.append("{0}：{1} 项".format(group, len(entries)))
            for entry in entries[:10]:
                lines.append("  - {0}：{1}".format(entry.get("change", ""), entry.get("relativePath", "")))
        self.collection_detail.setPlainText("\n".join(lines))
        self.set_status("已比较两份集合（变化 {0} 项）".format(len(report.get("entries") or [])))

    def _on_export_package(self) -> None:
        target = self._selected_collection()
        if target is None:
            self.set_status("请先选择要导出包的集合")
            return
        destination = QFileDialog.getExistingDirectory(self, "选择集合包输出目录")
        if not destination:
            return
        result = surface.collection_export_package(target.get("root") or self._root, target.get("path", ""), destination)
        self.collection_detail.setPlainText(
            "导出包：{0}\n{1}".format(result.get("path", "（未生成）"), "\n".join(result.get("warnings") or []))
        )
        self.set_status(result.get("message", ""))

    def _on_recover_copy(self) -> None:
        target = self._selected_collection()
        if target is None:
            self.set_status("请先选择要恢复的集合")
            return
        destination = QFileDialog.getExistingDirectory(self, "选择恢复副本的目标目录")
        if not destination:
            return
        result = surface.collection_recover(target.get("root") or self._root, target.get("path", ""), destination)
        lines = [result.get("message", "")]
        for key in ("restored", "renamed", "skipped"):
            values = result.get(key) or []
            if values:
                lines.append("{0}：{1}".format(key, "、".join(str(item) for item in list(values)[:10])))
        self.collection_detail.setPlainText("\n".join(line for line in lines if line))
        self.set_status("恢复为副本完成（当前工作区与缓冲未被覆盖）")

    def _on_open_artifact(self) -> None:
        target = self._selected_collection()
        if target is None:
            self.set_status("请先选择集合")
            return
        relative = self.artifact_combo.currentData()
        if not relative:
            self.set_status("该集合没有可打开的成果或清单")
            return
        from doc_tool.application.collection_ops import open_artifact

        try:
            path = open_artifact(target.get("root") or self._root, target.get("path", ""), str(relative))
        except Exception as exc:  # noqa: BLE001 - 打开失败只影响该动作
            self.set_status("打开成果失败：{0}".format(exc))
            return
        if not path:
            self.set_status("成果不在集合中或已缺失：{0}".format(relative))
            return
        opened = self._host_call("rd_open_path", str(path))
        self.set_status("已打开成果：{0}".format(path) if opened is not False else "已在系统中打开：{0}".format(path))

    def _on_member_delivery(self) -> None:
        """成员交付：直接复用已有批量交付入口（不新建协调器/队列）。"""
        result = self._host_call("rd_member_delivery", self._root)
        if result is None:
            self.delivery_status.setText(
                "成员交付依赖既有“批量交付（持久队列）”入口；当前环境未接线，"
                "可用菜单「操作 → 批量交付」并选择包含各成员的计划。"
            )
            return
        self.delivery_status.setText(str(result))

    # ------------------------------------------------------------------
    # 工作区管理动作
    # ------------------------------------------------------------------

    def _member_role_choice(self) -> Optional[str]:
        labels = [surface.role_label(role) for role in DOCUMENT_ROLES]
        label, ok = QInputDialog.getItem(self, "成员角色", "角色（元数据，不改项目类型）：", labels, 0, False)
        if not ok:
            return None
        for role in DOCUMENT_ROLES:
            if surface.role_label(role) == label:
                return role
        return None

    def _on_new_workspace(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择工作区目录（建议空目录）")
        if not directory:
            return
        from doc_tool.domain.errors import ProjectManifestError

        try:
            workspace = create_workspace(directory, name=Path(directory).name)
        except ProjectManifestError as exc:
            self.set_status("新建工作区失败：{0}".format(exc))
            return
        try:
            workspace.save(directory)
        except Exception as exc:  # noqa: BLE001 - 保存失败保留目录状态
            self.set_status("工作区未保存：{0}".format(exc))
            return
        self._root = directory
        self._host_call("rd_workspace_root_changed", directory)
        self.refresh_all()
        host_root = self._host_project_root()
        if host_root:
            self._offer_add_current_project(host_root)
        self.set_status("已新建工作区：{0}（成员 0）".format(directory))

    def _offer_add_current_project(self, project_root: str) -> None:
        if not self._workspace or not self._root:
            return
        try:
            inside = Path(project_root).resolve().is_relative_to(Path(self._root).resolve())
        except Exception:  # noqa: BLE001 - 路径异常按外部项目处理
            inside = False
        role = self._member_role_choice()
        if role is None:
            return
        self._add_project_path(project_root, role=role, copy_external=not inside)

    def _on_open_workspace(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择包含 workspace.yml 的目录")
        if not directory:
            return
        workspace, message = surface.open_workspace(directory)
        if workspace is None:
            self.set_status("打开工作区失败：{0}".format(message))
            return
        self._root = directory
        self._host_call("rd_workspace_root_changed", directory)
        self.refresh_all()
        self.set_status("已打开工作区：{0}".format(workspace.name or directory))

    def _on_save_workspace(self) -> None:
        if self._workspace is None:
            self.set_status("当前没有工作区：可先“新建工作区”，单文档编辑与出稿不受影响")
            return
        try:
            path = self._workspace.save(self._root)
        except Exception as exc:  # noqa: BLE001 - 保存失败保留现有清单
            self.set_status("工作区保存失败：{0}".format(exc))
            return
        self.set_status("工作区已保存：{0}".format(path))

    def _on_add_member(self, *, copy_external: bool) -> None:
        if self._workspace is None:
            self.set_status("请先新建或打开工作区")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择要加入的成员项目目录")
        if not directory:
            return
        role = self._member_role_choice()
        if role is None:
            return
        self._add_project_path(directory, role=role, copy_external=copy_external)

    def _add_project_path(self, directory: str, *, role: str, copy_external: bool) -> None:
        try:
            member, copied = add_project(
                self._workspace, directory, role=role, copy_external=copy_external,
            )
        except Exception as exc:  # noqa: BLE001 - 加入失败保留原工作区
            self.set_status("加入成员失败：{0}".format(exc))
            return
        if member is None:
            self.set_status("成员未加入（重复或无效）：{0}".format(
                "；".join(issue.reason for issue in self._workspace.issues[-2:])
            ))
            return
        try:
            self._workspace.save(self._root)
        except Exception as exc:  # noqa: BLE001 - 保存失败保留内存成员
            self.set_status("成员已加入但工作区未保存：{0}".format(exc))
            return
        self.refresh_all()
        self.set_status(
            "已加入成员 {0}（{1}）".format(
                member.relative_path, "复制导入并生成新 projectId" if copied else "引用已有项目",
            )
        )

    def _on_remove_member(self) -> None:
        row = self.member_table.currentRow()
        if self._workspace is None or row < 0 or row >= len(self._members):
            self.set_status("请先选择要移除的成员")
            return
        target = self._members[row]
        if target.get("path") in (".", ""):
            self.set_status("当前项目不是工作区成员：无需移除")
            return
        confirmed = QMessageBox.question(
            self, "移除成员",
            "只从工作区清单移除「{0}」？成员项目文件不会被删除。".format(target["name"]),
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._workspace.members = [
            member for member in self._workspace.members if member.relative_path != target["path"]
        ]
        try:
            self._workspace.save(self._root)
        except Exception as exc:  # noqa: BLE001 - 保存失败保留原清单
            self.set_status("移除未保存：{0}".format(exc))
            return
        self.refresh_all()
        self.set_status("已从工作区移除成员：{0}（文件保留）".format(target["name"]))

    def _on_relocate_member(self) -> None:
        row = self.member_table.currentRow()
        if self._workspace is None or row < 0 or row >= len(self._members):
            self.set_status("请先选择要重新定位的成员")
            return
        target = self._members[row]
        directory = QFileDialog.getExistingDirectory(self, "选择成员项目的新位置")
        if not directory:
            return
        root = Path(self._root).resolve()
        try:
            relative = Path(directory).resolve().relative_to(root).as_posix()
        except ValueError:
            self.set_status("新位置在工作区之外：请用“复制加入”把项目复制进工作区")
            return
        try:
            manifest = ProjectManifest.load(directory)
        except Exception as exc:  # noqa: BLE001 - 无法读取则保持原记录
            self.set_status("新位置不是可读项目：{0}".format(exc))
            return
        for member in self._workspace.members:
            if member.relative_path == target["path"]:
                member.relative_path = relative
                member.project_id = manifest.projectId
                member.name = manifest.documentName
                member.document_version = manifest.documentVersion
                member.schema_version = manifest.schemaVersion
        try:
            self._workspace.save(self._root)
        except Exception as exc:  # noqa: BLE001 - 保存失败保留原记录
            self.set_status("重新定位未保存：{0}".format(exc))
            return
        self.refresh_all()
        self.set_status("已重新定位成员：{0} → {1}".format(target["name"], relative))

    def _on_open_member(self) -> None:
        row = self.member_table.currentRow()
        if row < 0 or row >= len(self._members):
            self.set_status("请先选择成员")
            return
        target = self._members[row]
        if not target.get("available"):
            self.set_status("成员不可用：{0}；可用“重新定位”或“移除成员”".format(target.get("reason", "")))
            return
        root = self._member_root(target)
        if root is None:
            self.set_status("成员路径未知：无法打开")
            return
        opened = self._host_call("rd_open_project", str(root))
        if opened is None:
            self.set_status("当前环境不支持打开成员项目：请在“打开项目”中选择 {0}".format(root))
            return
        if target.get("readonly"):
            self.set_status("已只读打开成员：{0}（模式版本 {1} 高于可写版本）".format(target["name"], target["schemaVersion"]))
        else:
            self.set_status("已打开成员：{0}".format(target["name"]))

    # ------------------------------------------------------------------
    # 概览与设置刷新
    # ------------------------------------------------------------------

    def _overview_root(self) -> Optional[Path]:
        row = self.member_table.currentRow()
        if 0 <= row < len(self._members):
            root = self._member_root(self._members[row])
            if root is not None and root.is_dir():
                return root
        if self._root and Path(self._root).is_dir():
            return Path(self._root)
        return None

    def refresh_overview(self) -> None:
        root = self._overview_root()
        if root is None:
            self.overview_text.setPlainText("未指定项目：单文档可直接编辑与出稿。")
            self.next_actions.clear()
            return
        payload = surface.overview_view(root)
        if not payload.get("ok"):
            self.overview_text.setPlainText(payload.get("message", "概览不可用"))
            self.next_actions.clear()
            return
        lines = [
            "文档：{0}".format(payload.get("documentName", "")),
            "版本：{0}".format(payload.get("documentVersion", "")),
            "模式版本：v{0}".format(payload.get("schemaVersion", "")),
            "规范来源：{0}".format(payload.get("standardPack", "") or "未声明"),
        ]
        for section in payload.get("sections", []):
            lines.append("{0}：{1}{2}".format(
                section.get("label", ""), section.get("value", ""),
                "（{0}）".format(section.get("detail", "")) if section.get("detail") else "",
            ))
        if payload.get("checkStale"):
            lines.append("校验报告已过期：建议重新检查后再出稿。")
        if payload.get("blockingCount"):
            lines.append("阻断问题：{0} 项".format(payload["blockingCount"]))
        self.overview_text.setPlainText("\n".join(lines))
        self.next_actions.clear()
        for action in payload.get("nextActions", []):
            self.next_actions.addItem(str(action))

    def refresh_settings(self) -> None:
        root = self._overview_root()
        self._settings_model = None
        self._clear_settings_form()
        self.settings_group.blockSignals(True)
        self.settings_group.clear()
        self.settings_group.blockSignals(False)
        self.settings_error.setText("")
        if root is None:
            return
        from doc_tool.application.settings import load_settings

        try:
            model = load_settings(root)
        except Exception as exc:  # noqa: BLE001 - 坏配置只影响设置分组
            self.settings_error.setText("设置不可用：{0}".format(exc))
            return
        self._settings_model = model
        for group in surface.settings_groups(model):
            writable = "" if group["writable"] else "（只读）"
            self.settings_group.addItem("{0}{1}".format(group["section"], writable), group["section"])
        if self.settings_group.count():
            self._refresh_settings_group()
        if getattr(model, "warnings", None):
            self.settings_error.setText("；".join(str(item) for item in model.warnings))

    def _clear_settings_form(self) -> None:
        while self.settings_form.rowCount():
            self.settings_form.removeRow(0)
        self._settings_widgets = {}

    def _refresh_settings_group(self) -> None:
        self._clear_settings_form()
        self.settings_error.setText("")
        if self._settings_model is None:
            return
        section = self.settings_group.currentData()
        if not section:
            return
        for field in surface.settings_field_rows(self._settings_model, section):
            widget = self._field_widget(field)
            self._settings_widgets[field["key"]] = widget
            label = field["label"] + ("" if field.get("editable", True) else "（只读）")
            if field.get("hint"):
                label += "\n" + str(field["hint"])
            self.settings_form.addRow(label, widget)

    def _field_widget(self, field: dict):
        kind = field.get("kind", "text")
        editable = bool(field.get("editable", True))
        value = field.get("value", "")
        if kind == "choice":
            combo = QComboBox()
            for option in field.get("options") or []:
                combo.addItem(str(option) if str(option) else "（留空）", str(option))
            index = combo.findData(str(value or ""))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setEnabled(editable)
            return combo
        if kind == "list":
            widget = QPlainTextEdit()
            import json as _json

            widget.setPlainText(_json.dumps(value or [], ensure_ascii=False, indent=2))
            widget.setEnabled(editable)
            widget.setMaximumHeight(120)
            return widget
        widget = QLineEdit(str(value if value is not None else ""))
        widget.setEnabled(editable)
        return widget

    def _collect_group_values(self, section: str) -> Tuple[Dict[str, object], Dict[str, str]]:
        import json as _json

        values: Dict[str, object] = {}
        errors: Dict[str, str] = {}
        fields = {field["key"]: field for field in surface.settings_field_rows(self._settings_model, section)}
        for key, widget in self._settings_widgets.items():
            field = fields.get(key, {})
            if not field.get("editable", True):
                continue
            if isinstance(widget, QComboBox):
                values[key] = widget.currentData() or ""
            elif isinstance(widget, QPlainTextEdit):
                raw = widget.toPlainText()
                try:
                    values[key] = _json.loads(raw) if raw.strip() else []
                except ValueError:
                    errors[key] = "不是合法 JSON 列表（内容已保留）"
            else:
                values[key] = widget.text()
        return values, errors

    def _on_save_settings_group(self) -> None:
        from doc_tool.application.settings import save_settings

        section = self.settings_group.currentData()
        root = self._overview_root()
        if not section or root is None or self._settings_model is None:
            self.set_status("没有可保存的设置分组")
            return
        values, errors = self._collect_group_values(section)
        if errors:
            self._mark_field_errors(errors)
            self.settings_error.setText("；".join("{0}：{1}".format(key, value) for key, value in errors.items()))
            self.set_status("设置未保存：请先修正标出的字段（输入已保留）")
            return
        payload = surface.settings_group_payload(section, values)
        outcome = save_settings(root, payload)
        if not outcome.ok:
            self._mark_field_errors(outcome.errors)
            self.settings_error.setText("；".join("{0}：{1}".format(key, value) for key, value in outcome.errors.items()))
            self.set_status(outcome.message)
            return
        self.settings_error.setText("")
        self.set_status("已保存「{0}」分组：{1}".format(section, outcome.message))
        self.refresh_settings()
        self.refresh_overview()

    def _mark_field_errors(self, errors: Dict[str, str]) -> None:
        for key, message in (errors or {}).items():
            widget = self._settings_widgets.get(key)
            if widget is None:
                continue
            widget.setStyleSheet("border: 1px solid #d9534f;")
            widget.setToolTip(str(message))
