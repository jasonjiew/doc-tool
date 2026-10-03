# -*- coding: utf-8 -*-
"""规范包制作界面（V3.5 35-B～35-D）。

草稿、资源映射、冻结、导出与样例验证都在 ``application/pack_authoring.py``；
本模块只做表单、列表、结果展示与动作转发，沿用既有包 schema 1 与校验服务。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application import pack_authoring as authoring


class StandardPackDialog(QDialog):
    """本地规范包制作：草稿 → 资源 → 冻结 → 导出 → 样例验证。"""

    def __init__(self, host=None, *, draft_dir: str = "", project_root: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("standardPackDialog")
        self.setWindowTitle("规范包制作")
        self.setMinimumSize(880, 540)
        self._host = host
        self._draft_dir = str(draft_dir or "")
        self._project_root = str(project_root or "")
        self._draft: Optional[authoring.PackDraft] = None
        self._frozen: Dict[str, object] = {}
        self._listings: Dict[str, object] = {}
        #: 表单里无法解析的输入：保留内容并阻止冻结，直到修正。
        self._collect_errors: List[str] = []
        #: 填充表单期间禁止回写草稿（否则 setText 触发的信号会清空刚读出的资源）。
        self._loading = False
        from doc_tool.ui.task_bridge import TaskRunner
        self._sample_runner = TaskRunner()
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(80)
        self._sample_timer.timeout.connect(self._sample_runner.poll)

        self._build_ui()
        if not self._draft_dir:
            self._draft_dir = self._host_call("sp_default_draft_dir") or str(
                Path(self._project_root or Path.cwd()) / "pack-draft"
            )
        self.draft_dir_edit.setText(self._draft_dir)
        self._load_or_create_draft()

    # --- 宿主能力 ---

    def _host_call(self, name: str, *args, **kwargs):
        func = getattr(self._host, name, None)
        if not callable(func):
            return None
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 宿主异常不阻断制作界面
            self.set_status("{0} 调用失败：{1}".format(name, exc))
            return None

    def set_status(self, message: str) -> None:
        self.status_label.setText(str(message or ""))
        self._host_call("sp_status", str(message or ""))

    # --- 构建 ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("制作目录"))
        self.draft_dir_edit = QLineEdit()
        self.draft_dir_edit.setObjectName("packDraftDir")
        header.addWidget(self.draft_dir_edit, 1)
        self.choose_dir_btn = QPushButton("选择目录…")
        self.choose_dir_btn.clicked.connect(self._on_choose_dir)
        header.addWidget(self.choose_dir_btn)
        self.new_from_project_btn = QPushButton("从当前项目创建草稿")
        self.new_from_project_btn.setToolTip("复制底模、章节骨架、变量/术语/规则到草稿；不修改源项目")
        self.new_from_project_btn.clicked.connect(self._on_new_from_project)
        header.addWidget(self.new_from_project_btn)
        self.new_from_pack_btn = QPushButton("从已有规范包复制…")
        self.new_from_pack_btn.clicked.connect(self._on_new_from_pack)
        header.addWidget(self.new_from_pack_btn)
        self.save_draft_btn = QPushButton("保存草稿")
        self.save_draft_btn.setToolTip("允许不完整草稿；保存不等于已可安装")
        self.save_draft_btn.clicked.connect(self._on_save_draft)
        header.addWidget(self.save_draft_btn)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "基本信息")
        self.tabs.addTab(self._build_resources_tab(), "资源")
        self.tabs.addTab(self._build_freeze_tab(), "清单与冻结")
        self.tabs.addTab(self._build_sample_tab(), "样例验证")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("packStatus")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _build_basic_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.pack_id_edit = QLineEdit()
        self.version_edit = QLineEdit()
        self.kind_edit = QLineEdit()
        self.description_edit = QPlainTextEdit()
        self.description_edit.setMaximumHeight(80)
        for widget in (self.pack_id_edit, self.version_edit):
            widget.textChanged.connect(self._refresh_identity_hint)
        form.addRow("包标识 packId", self.pack_id_edit)
        form.addRow("版本 version", self.version_edit)
        form.addRow("文档类别 documentKind", self.kind_edit)
        form.addRow("说明", self.description_edit)
        layout.addLayout(form)
        self.identity_hint = QLabel("")
        self.identity_hint.setObjectName("packIdentityHint")
        self.identity_hint.setWordWrap(True)
        layout.addWidget(self.identity_hint)
        mapping = QGroupBox("资源映射（包内文件 ↔ 项目配置）")
        mapping_layout = QVBoxLayout(mapping)
        mapping_text = QPlainTextEdit()
        mapping_text.setReadOnly(True)
        mapping_text.setPlainText("\n".join(
            "{0}：{1}".format(key, value) for key, value in authoring.RESOURCE_MAPPING.items()
        ))
        mapping_layout.addWidget(mapping_text)
        layout.addWidget(mapping, 1)
        return page

    def _build_resources_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("authoringScroll")
        scroll.viewport().setObjectName("authoringScrollViewport")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._build_resources_form())
        return scroll

    def _build_resources_form(self) -> QWidget:
        page = QWidget()
        page.setObjectName("authoringScrollContent")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)

        template_box = QGroupBox("Word 底模（封面/页眉属于底模，正文变量不改变它们）")
        template_layout = QHBoxLayout(template_box)
        self.template_label = QLabel("未选择")
        self.template_label.setWordWrap(True)
        template_layout.addWidget(self.template_label, 1)
        self.choose_template_btn = QPushButton("选择 DOCX…")
        self.choose_template_btn.clicked.connect(self._on_choose_template)
        template_layout.addWidget(self.choose_template_btn)
        self.edit_template_btn = QPushButton("用系统 Word 打开")
        self.edit_template_btn.clicked.connect(self._on_edit_template)
        template_layout.addWidget(self.edit_template_btn)
        layout.addWidget(template_box)

        skeleton_box = QGroupBox("章节骨架")
        skeleton_layout = QHBoxLayout(skeleton_box)
        self.skeleton_list = QListWidget()
        self.skeleton_list.setMinimumHeight(100)
        self.skeleton_list.setMaximumHeight(140)
        self.skeleton_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        skeleton_layout.addWidget(self.skeleton_list, 1)
        skeleton_buttons = QVBoxLayout()
        self.add_skeleton_btn = QPushButton("添加 Markdown…")
        self.add_skeleton_btn.clicked.connect(self._on_add_skeleton)
        skeleton_buttons.addWidget(self.add_skeleton_btn)
        self.remove_skeleton_btn = QPushButton("移除选中")
        self.remove_skeleton_btn.clicked.connect(self._on_remove_skeleton)
        skeleton_buttons.addWidget(self.remove_skeleton_btn)
        skeleton_layout.addLayout(skeleton_buttons)
        layout.addWidget(skeleton_box, 2)

        variables_box = QGroupBox("变量（variables.yml）")
        variables_layout = QVBoxLayout(variables_box)
        self.variables_table = QTableWidget(0, 2)
        self.variables_table.setMinimumHeight(140)
        self.variables_table.setMaximumHeight(200)
        self.variables_table.setHorizontalHeaderLabels(["名称", "默认值"])
        self.variables_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.variables_table.itemChanged.connect(lambda _item: self._refresh_identity_hint())
        variables_layout.addWidget(self.variables_table, 1)
        variable_buttons = QHBoxLayout()
        self.add_variable_btn = QPushButton("添加变量")
        self.add_variable_btn.clicked.connect(lambda: self._add_variable_row("", ""))
        variable_buttons.addWidget(self.add_variable_btn)
        self.remove_variable_btn = QPushButton("删除选中变量")
        self.remove_variable_btn.clicked.connect(self._on_remove_variable)
        variable_buttons.addWidget(self.remove_variable_btn)
        variable_buttons.addStretch(1)
        variables_layout.addLayout(variable_buttons)
        layout.addWidget(variables_box, 2)

        text_box = QGroupBox("术语 / 支持规则（保留未知声明式原文）")
        text_layout = QVBoxLayout(text_box)
        self.terms_edit = QPlainTextEdit()
        self.terms_edit.setPlaceholderText('[{"canonical": "需求", "aliases": ["需求项"]}]')
        self.terms_edit.setMaximumHeight(110)
        self.terms_edit.setMinimumHeight(96)
        self.terms_edit.textChanged.connect(self._refresh_identity_hint)
        self.rules_edit = QPlainTextEdit()
        self.rules_edit.setPlaceholderText('[{"ruleId": "todo_residual", "severity": "warning", "enabled": true}]')
        self.rules_edit.setMaximumHeight(110)
        self.rules_edit.setMinimumHeight(96)
        self.rules_edit.textChanged.connect(self._refresh_identity_hint)
        text_layout.addWidget(QLabel("术语（JSON 列表）"))
        text_layout.addWidget(self.terms_edit)
        text_layout.addWidget(QLabel("支持规则（JSON 列表；未知字段原样保留）"))
        text_layout.addWidget(self.rules_edit)
        advanced = QHBoxLayout()
        self.extra_btn = QPushButton("查看保留的未知声明式内容")
        self.extra_btn.clicked.connect(self._show_extra)
        advanced.addWidget(self.extra_btn)
        advanced.addStretch(1)
        text_layout.addLayout(advanced)
        layout.addWidget(text_box, 2)
        return page

    def _build_freeze_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        self.freeze_btn = QPushButton("冻结规范包")
        self.freeze_btn.setToolTip("按 schema 1 生成 pack.yml 与实际文件摘要；不覆盖已有产物")
        self.freeze_btn.clicked.connect(self._on_freeze)
        buttons.addWidget(self.freeze_btn)
        self.export_zip_btn = QPushButton("导出 ZIP…")
        self.export_zip_btn.clicked.connect(self._on_export_zip)
        buttons.addWidget(self.export_zip_btn)
        self.open_frozen_btn = QPushButton("打开所在目录")
        self.open_frozen_btn.clicked.connect(self._on_open_frozen)
        buttons.addWidget(self.open_frozen_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.freeze_result = QLabel("")
        self.freeze_result.setObjectName("packFreezeResult")
        self.freeze_result.setWordWrap(True)
        layout.addWidget(self.freeze_result)
        layout.addWidget(QLabel("将包含的文件（导出前清单）"))
        self.file_list = QListWidget()
        self.file_list.setObjectName("packFileList")
        layout.addWidget(self.file_list, 1)
        self.excluded_label = QLabel("")
        self.excluded_label.setWordWrap(True)
        layout.addWidget(self.excluded_label)
        return page

    def _build_sample_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        self.sample_btn = QPushButton("生成最新样例")
        self.sample_btn.setToolTip("复制草稿资源生成隔离项目，调用既有建项/检查/CORE 出稿；不改源项目")
        self.sample_btn.clicked.connect(self._on_run_sample)
        buttons.addWidget(self.sample_btn)
        self.retry_sample_btn = QPushButton("补原样例 Word")
        self.retry_sample_btn.setToolTip("继续原样例的捕获，不混入最新草稿；无 Word 时保留可读成果")
        self.retry_sample_btn.clicked.connect(self._on_retry_sample)
        buttons.addWidget(self.retry_sample_btn)
        self.open_sample_btn = QPushButton("打开样例成果")
        self.open_sample_btn.clicked.connect(self._on_open_sample)
        buttons.addWidget(self.open_sample_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.sample_result = QLabel("")
        self.sample_result.setObjectName("packSampleResult")
        self.sample_result.setWordWrap(True)
        layout.addWidget(self.sample_result)
        self.sample_table = QTableWidget(0, 2)
        self.sample_table.setHorizontalHeaderLabels(["验证面", "结果"])
        self.sample_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sample_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.sample_table, 1)
        return page


    # --- 草稿加载与保存 ---

    def _load_or_create_draft(self) -> None:
        base = Path(self.draft_dir_edit.text().strip() or self._draft_dir)
        try:
            draft = authoring.PackDraft.load(base)
        except Exception as exc:  # noqa: BLE001 - 坏草稿只影响本界面
            self.set_status("草稿不可读：{0}；可另选目录重新创建".format(exc))
            draft = authoring.create_draft(base)
        self._draft = draft
        self._fill_form(draft)
        self._refresh_file_listing()

    def _fill_form(self, draft: authoring.PackDraft) -> None:
        self._loading = True
        try:
            self._fill_form_values(draft)
        finally:
            self._loading = False
        self._refresh_identity_hint()
        self._refresh_sample_view()

    def _fill_form_values(self, draft: authoring.PackDraft) -> None:
        self.pack_id_edit.setText(draft.pack_id)
        self.version_edit.setText(draft.version)
        self.kind_edit.setText(draft.document_kind)
        self.description_edit.setPlainText(draft.description)
        self.template_label.setText(
            "{0}（{1}）".format(draft.template, "存在" if (Path(draft.root) / draft.template).is_file() else "缺失")
            if draft.template else "未选择"
        )
        self.skeleton_list.clear()
        for item in draft.skeleton:
            self.skeleton_list.addItem(item)
        self.variables_table.blockSignals(True)
        try:
            self.variables_table.setRowCount(len(draft.variables))
            for index, (key, value) in enumerate(draft.variables.items()):
                self.variables_table.setItem(index, 0, QTableWidgetItem(str(key)))
                self.variables_table.setItem(index, 1, QTableWidgetItem(str(value)))
        finally:
            self.variables_table.blockSignals(False)
        self.terms_edit.setPlainText(json.dumps(list(draft.terms), ensure_ascii=False, indent=2) if draft.terms else "")
        self.rules_edit.setPlainText(json.dumps(list(draft.rules), ensure_ascii=False, indent=2) if draft.rules else "")
        for name, widget in (("terms", self.terms_edit), ("rules", self.rules_edit)):
            raw = draft.extra.get("pendingEditorInputs", {}).get(name)
            if isinstance(raw, str):
                widget.setPlainText(raw)
        self._refresh_identity_hint()
        self._refresh_sample_view()

    def _collect_draft(self) -> authoring.PackDraft:
        """把表单值收集回草稿（保留无法解析的输入原文并提示）。"""
        draft = self._draft
        if self._loading:
            return draft
        self._collect_errors = []
        draft.pack_id = self.pack_id_edit.text().strip()
        draft.version = self.version_edit.text().strip()
        draft.document_kind = self.kind_edit.text().strip()
        draft.description = self.description_edit.toPlainText().strip()
        draft.skeleton = [self.skeleton_list.item(index).text() for index in range(self.skeleton_list.count())]
        variables: Dict[str, str] = {}
        for row in range(self.variables_table.rowCount()):
            key = self.variables_table.item(row, 0)
            value = self.variables_table.item(row, 1)
            name = key.text().strip() if key is not None else ""
            if not name:
                continue
            variables[name] = value.text() if value is not None else ""
        draft.variables = variables
        pending = dict(draft.extra.get("pendingEditorInputs") or {})
        for field, widget, target in (
            ("terms", self.terms_edit, "terms"),
            ("rules", self.rules_edit, "rules"),
        ):
            raw = widget.toPlainText().strip()
            if not raw:
                setattr(draft, target, [])
                pending.pop(field, None)
                continue
            try:
                parsed = json.loads(raw)
            except ValueError:
                message = "「{0}」不是合法 JSON：输入已保留，请修正后再冻结".format(field)
                self._collect_errors.append(message)
                pending[field] = widget.toPlainText()
                self.set_status(message)
                continue
            setattr(draft, target, parsed if isinstance(parsed, list) else [parsed])
            pending.pop(field, None)
        if pending:
            draft.extra["pendingEditorInputs"] = pending
        else:
            draft.extra.pop("pendingEditorInputs", None)
        return draft

    def _refresh_identity_hint(self, *_args) -> None:
        if self._draft is None or self._loading:
            return
        validation = authoring.validate_draft(self._collect_draft())
        lines = []
        if validation["errors"]:
            lines.append("暂不可导出：" + "；".join(validation["errors"]))
        if validation["warnings"]:
            lines.append("提示：" + "；".join(validation["warnings"]))
        if not lines:
            lines.append("身份与资源齐备：可以冻结并导出。")
        self.identity_hint.setText("\n".join(lines))
        self._refresh_sample_view()

    def _on_choose_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择规范包制作目录")
        if not directory:
            return
        self.draft_dir_edit.setText(directory)
        self._draft_dir = directory
        self._load_or_create_draft()

    def _on_new_from_project(self) -> None:
        project_root = self._project_root or str(self._host_call("sp_project_root") or "")
        if not project_root or not Path(project_root).is_dir():
            self.set_status("没有可用的当前项目：请先打开一个项目，或选择已有规范包复制")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择草稿目录（可与项目不同）")
        if not directory:
            return
        try:
            draft = authoring.draft_from_project(project_root, directory)
        except Exception as exc:  # noqa: BLE001 - 来源不可读时保留原草稿
            self.set_status("从项目创建草稿失败：{0}".format(exc))
            return
        self._draft = draft
        self._draft_dir = directory
        self.draft_dir_edit.setText(directory)
        self._fill_form(draft)
        self._refresh_file_listing()
        self.set_status("已从项目创建草稿：{0}（源项目未修改）".format(directory))

    def _on_new_from_pack(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择已有规范包目录")
        if not directory:
            return
        destination = QFileDialog.getExistingDirectory(self, "选择草稿目录")
        if not destination:
            return
        try:
            draft = authoring.draft_from_pack(directory, destination)
        except Exception as exc:  # noqa: BLE001 - 源包不可用时保留原草稿
            self.set_status("从规范包复制草稿失败：{0}".format(exc))
            return
        self._draft = draft
        self._draft_dir = destination
        self.draft_dir_edit.setText(destination)
        self._fill_form(draft)
        self._refresh_file_listing()
        self.set_status("已从规范包复制草稿：{0}（原包未修改）".format(destination))

    def _on_save_draft(self) -> None:
        draft = self._collect_draft()
        try:
            path = draft.save()
        except Exception as exc:  # noqa: BLE001 - 保存失败保留输入
            self.set_status("草稿保存失败：{0}（输入已保留）".format(exc))
            return
        self._refresh_file_listing()
        self.set_status("草稿已保存：{0}（不完整草稿也可保存，未生成可安装包）".format(path))

    # --- 资源动作 ---

    def _on_choose_template(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择 Word 底模", "", "Word 文档 (*.docx)")
        if not path:
            return
        self._collect_draft()
        target = Path(self._draft.root) / "template.docx"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(path, target)
        except Exception as exc:  # noqa: BLE001 - 复制失败保留原底模
            self.set_status("复制底模失败：{0}".format(exc))
            return
        self._draft.template = "template.docx"
        self.template_label.setText("template.docx（存在）")
        self._refresh_file_listing()
        self.set_status("已选择底模：{0}（封面/页眉仍属于底模）".format(Path(path).name))

    def _on_edit_template(self) -> None:
        if self._draft is None or not self._draft.template:
            self.set_status("尚未选择底模")
            return
        target = Path(self._draft.root) / self._draft.template
        if not target.is_file():
            self.set_status("底模文件不存在：{0}".format(target))
            return
        opened = self._host_call("sp_open_path", str(target))
        self.set_status("已请求用系统 Word 打开底模" if opened is None else "已打开底模：{0}".format(target))

    def _on_add_skeleton(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "选择章节骨架 Markdown", "", "Markdown (*.md)")
        if not paths:
            return
        self._collect_draft()
        base = Path(self._draft.root)
        for path in paths:
            target = base / "skeleton" / Path(path).name
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(path, target)
            rel = target.relative_to(base).as_posix()
            if rel not in self._draft.skeleton:
                self._draft.skeleton.append(rel)
                self.skeleton_list.addItem(rel)
        self._refresh_file_listing()
        self.set_status("已添加 {0} 个章节骨架".format(len(paths)))

    def _on_remove_skeleton(self) -> None:
        for item in self.skeleton_list.selectedItems():
            self.skeleton_list.takeItem(self.skeleton_list.row(item))
        self._collect_draft()
        self._refresh_file_listing()
        self.set_status("已从草稿清单移除骨架（磁盘文件保留）")

    def _add_variable_row(self, key: str, value: str) -> None:
        row = self.variables_table.rowCount()
        self.variables_table.insertRow(row)
        self.variables_table.setItem(row, 0, QTableWidgetItem(key))
        self.variables_table.setItem(row, 1, QTableWidgetItem(value))

    def _on_remove_variable(self) -> None:
        rows = sorted({index.row() for index in self.variables_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.variables_table.removeRow(row)
        self._refresh_identity_hint()

    def _show_extra(self) -> None:
        if self._draft is None or not self._draft.extra:
            QMessageBox.information(self, "未知声明式内容", "当前草稿没有需要原样保留的未知字段。")
            return
        QMessageBox.information(
            self, "未知声明式内容",
            json.dumps(self._draft.extra, ensure_ascii=False, indent=2),
        )

    # --- 冻结、导出与样例 ---

    def _refresh_file_listing(self) -> None:
        if self._draft is None:
            return
        listing = authoring.file_listing(self._draft)
        self.file_list.clear()
        for name in listing["included"]:
            self.file_list.addItem(name)
        self.excluded_label.setText(
            "已排除：{0}".format("、".join(listing["excluded"])) if listing["excluded"]
            else "草稿目录未发现 Git/凭证/缓存/历史/产物目录。"
        )

    def _on_freeze(self) -> None:
        draft = self._collect_draft()
        if self._collect_errors:
            self.set_status("；".join(self._collect_errors))
            return
        try:
            result = authoring.freeze_draft(draft)
        except Exception as exc:  # noqa: BLE001 - 冻结失败保留草稿
            self.set_status("冻结失败：{0}（草稿已保留）".format(exc))
            return
        self._frozen = result
        lines = [str(result.get("message", ""))]
        if result.get("errors"):
            lines.append("结构问题：" + "；".join(result["errors"]))
        if result.get("warnings"):
            lines.append("提示：" + "；".join(result["warnings"]))
        self.freeze_result.setText("\n".join(line for line in lines if line))
        self._refresh_file_listing()
        self.set_status(str(result.get("message", "")))

    def _on_export_zip(self) -> None:
        # 以按钮触发时的表单冻结；服务会复用同内容产物，旧产物不会被覆盖。
        self._on_freeze()
        if self._collect_errors:
            return
        if not self._frozen or not self._frozen.get("ok"):
            self.set_status("包结构尚不可消费：未导出 ZIP（草稿与文件已保留，可修正后重试）")
            return
        destination = QFileDialog.getExistingDirectory(self, "选择 ZIP 输出目录")
        if not destination:
            return
        result = authoring.export_zip(self._frozen["packDir"], destination)
        self.set_status(str(result.get("message", "")))
        if result.get("skipped"):
            self.freeze_result.setText(
                "{0}\n跳过：{1}".format(self.freeze_result.text(), "；".join(result["skipped"]))
            )

    def _on_open_frozen(self) -> None:
        pack_dir = str((self._frozen or {}).get("packDir", ""))
        if not pack_dir:
            self.set_status("尚未冻结任何规范包")
            return
        self._host_call("sp_open_path", pack_dir)

    def _on_run_sample(self) -> None:
        self._start_sample_task(authoring.run_sample, latest=True)

    def _on_retry_sample(self) -> None:
        self._start_sample_task(authoring.retry_sample_word, latest=False)

    def _start_sample_task(self, target, *, latest: bool) -> None:
        from doc_tool.ui.task_bridge import TaskSpec
        if self._sample_runner.is_running:
            return
        draft = self._collect_draft()
        if self._collect_errors and latest:
            self.set_status("；".join(self._collect_errors))
            return
        try:
            draft.save()
        except Exception as exc:  # noqa: BLE001 - 样例失败保留草稿与旧证据
            self.set_status("草稿保存失败：{0}（输入已保留，可重试）".format(exc))
            return
        captured = authoring.PackDraft.from_dict(draft.to_dict(), Path(draft.root))
        self._set_sample_busy(True)
        self.set_status("正在隔离样例中建项、检查并出稿…" if latest else "正在补原样例 Word，其他成果可继续打开…")
        self._sample_runner.start(
            TaskSpec("pack-sample", target, args=(captured,),
                     kwargs={"sample_root": Path(captured.root) / "sample"} if latest else {}, timeout_seconds=1800),
            on_event=self._on_sample_event, on_done=self._on_sample_done,
        )
        self._sample_timer.start()

    def _set_sample_busy(self, busy: bool) -> None:
        for widget in (self.draft_dir_edit, self.choose_dir_btn, self.new_from_project_btn,
                       self.new_from_pack_btn, self.save_draft_btn):
            widget.setEnabled(not busy)
        for index in range(3):
            self.tabs.widget(index).setEnabled(not busy)
        self.sample_btn.setEnabled(not busy)
        self.retry_sample_btn.setEnabled(not busy and bool(self._draft.sample))

    def _on_sample_event(self, event) -> None:
        if event.kind == "failed":
            self.set_status("样例试用失败：{0}；草稿和旧成果仍可使用".format(event.detail))
        elif event.kind == "cancelled":
            self.set_status("样例试用已取消；草稿和旧成果仍可使用")

    def _on_sample_done(self, result) -> None:
        self._sample_timer.stop()
        self._set_sample_busy(False)
        if result is None:
            return
        self._draft.sample = dict(result)
        self._refresh_sample_view()
        self.set_status(str(result.get("message", "")))

    def _on_open_sample(self) -> None:
        sample = (self._draft.sample if self._draft is not None else {}) or {}
        path = str(sample.get("htmlPath") or sample.get("wordPath") or "")
        if not path:
            self.set_status("尚无可用样例成果：请先试用")
            return
        self._host_call("sp_open_path", path)

    def _refresh_sample_view(self) -> None:
        sample = (self._draft.sample if self._draft is not None else {}) or {}
        if not sample:
            self.retry_sample_btn.setEnabled(False)
            self.sample_result.setText("尚未试用：试用会在隔离目录建项、检查并出稿，不影响源项目。")
            self.sample_table.setRowCount(0)
            return
        self.retry_sample_btn.setEnabled(not self._sample_runner.is_running)
        stale = authoring.sample_is_stale(self._draft)
        self.sample_result.setText(
            "{0}草稿摘要 {1}｜captureId {2}".format(
                "⚠ 草稿已变化，旧样例结果过期（仍可打开）：" if stale else "",
                str(sample.get("draftDigest", ""))[:12],
                str(sample.get("captureId", "")) or "—",
            )
        )
        rows = [
            ("结构合法", "是" if sample.get("structureOk") else "否"),
            ("规则问题", "{0}（{1}）".format(sample.get("ruleIssues", 0), sample.get("ruleStatus", ""))),
            ("可读成果", sample.get("htmlPath") or "无"),
            ("Word 状态", "{0}（{1}）".format(sample.get("wordStatus", ""), sample.get("wordPath", ""))),
            ("正式成功", "是" if sample.get("formal") else "否（诊断构建不计正式）"),
            ("未验证", "；".join(sample.get("unverified") or [])),
            ("样例项目", sample.get("projectRoot", "")),
        ]
        self.sample_table.setRowCount(len(rows))
        for index, (key, value) in enumerate(rows):
            self.sample_table.setItem(index, 0, QTableWidgetItem(str(key)))
            self.sample_table.setItem(index, 1, QTableWidgetItem(str(value)))

    def done(self, result) -> None:
        """关闭按钮、Esc 和窗口关闭都保存草稿，包括未完成的 JSON 输入。"""
        if self._sample_runner.is_running:
            # 运行前已保存表单，关闭时不写旧 sample 覆盖后台即将完成的新结果。
            self._sample_runner.cancel()
            self._sample_timer.stop()
            super().done(result)
            return
        try:
            if self._draft is not None:
                self._collect_draft().save()
        except Exception as exc:  # noqa: BLE001 - 真实保存失败时保留可复制的输入
            self.set_status("草稿保存失败：{0}；输入仍在，可另存后关闭".format(exc))
            return
        super().done(result)
