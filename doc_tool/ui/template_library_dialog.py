# -*- coding: utf-8 -*-
"""本地企业模板目录界面（V4.1 41-A 1.4）。

把 ``application/template_library.py`` 的本地目录接进现有入口：
用途筛选（骨架建项/模板填充/项目出稿）+ 搜索 + 列表 + 详情（真实来源、版本、
内容摘要、文档类别、用途与未知声明原文），并按用途转发到既有真实动作：

- 骨架建项 → 原规范包建项 ``create_project_from_pack``；
- 项目出稿 → 用规范包自带的 ``template.docx`` 走既有底模出稿（``TemplateFillDialog``）；
- 模板填充 → 既有 ``TemplateFillDialog``，并带上 ``recipe_for(entry)``。

本模块只做表单、列表、详情与动作转发，不新建第二套目录/任务/结果模型；
加载、空目录、无结果、来源缺失、只读项目与坏索引回退都在本地给出下一步，
打开/关闭本对话框既不改动当前项目，也不关闭已打开的编辑器缓冲。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application import template_library as service
from doc_tool.application.standard_pack import (
    STANDARDS_DIR,
    bundled_standards_root,
    validate_pack_dir,
)
from doc_tool.ui.template_fill_dialog import TemplateFillDialog

#: 界面状态：只为就地给出下一步，不是业务事实。
STATE_LOADING = "loading"
STATE_OK = "ok"
STATE_EMPTY = "empty"
STATE_NO_RESULT = "no-result"
STATE_MISSING = "missing"
STATE_UNREADABLE = "unreadable"

#: 用途筛选的「全部」取值（服务层用空串表示不筛选）。
USE_ALL = ""

_PRIMARY_LABELS = {
    service.USE_SKELETON: "用此规范建项…",
    service.USE_FILL: "模板填充…",
    service.USE_EXPORT: "用此底模出稿…",
}


def default_state_dir() -> Path:
    """默认用户配置目录（与 template-fill 预设/最近任务同一目录约定）。"""
    from doc_tool.application.template_fill import _last_template_file

    return _last_template_file().parent


def default_templates_root(state_dir: Optional[object] = None) -> Path:
    """模板填充条目的本地底模目录（``<用户配置>/templates``，由扫描服务读取）。"""
    return (Path(state_dir) if state_dir else default_state_dir()) / "templates"


def default_roots(project_root: object = "") -> List[str]:
    """默认扫描目录：内置固定包 + 项目内已固定的 ``standards/``。"""
    roots: List[str] = []
    bundled = bundled_standards_root()
    if bundled is not None:
        roots.append(str(bundled))
    text = str(project_root or "").strip()
    if text:
        standards = Path(text) / STANDARDS_DIR
        if standards.is_dir():
            roots.append(str(standards))
    return roots


def directory_writable(path: object) -> bool:
    """写入目标目录探测（只用于用户明确选择的写入目录，不探测项目正文目录）。"""
    target = Path(path)
    if not target.is_dir():
        return False
    probe = target / ".doctool-template-library-probe.tmp"
    try:
        probe.write_text("probe", encoding="utf-8")
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def _inside(child: Path, parent: Path) -> bool:
    """child 是否位于 parent 之内（不要求路径存在，只做字符串归一化）。"""
    try:
        child_abs = os.path.normcase(os.path.abspath(str(child)))
        parent_abs = os.path.normcase(os.path.abspath(str(parent)))
    except (OSError, ValueError):
        return False
    if child_abs == parent_abs:
        return True
    return child_abs.startswith(parent_abs.rstrip("\\/") + os.sep)


class TemplateLibraryDialog(QDialog):
    """本地模板目录：用途/搜索 → 列表 → 详情 → 按用途的真实动作。"""

    def __init__(
        self,
        host=None,
        *,
        roots: Optional[List[object]] = None,
        templates_root: Optional[object] = None,
        state_dir: Optional[object] = None,
        project_root: object = "",
        project_chapters: Optional[List[object]] = None,
        project_writable: Optional[bool] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        if parent is None and isinstance(host, QWidget):
            parent = host
        super().__init__(parent)
        self.setObjectName("templateLibraryDialog")
        self.setWindowTitle("本地模板目录（规范 / 模板 / 出稿）")
        self.setMinimumSize(880, 560)
        self._host = host
        self._project_root = str(project_root or "")
        self._state_dir = Path(state_dir) if state_dir else default_state_dir()
        self._roots = [
            str(item) for item in (roots if roots is not None else default_roots(self._project_root))
        ]
        self._templates_root = (
            Path(templates_root) if templates_root else default_templates_root(self._state_dir)
        )
        self._project_chapters = [str(item) for item in (project_chapters or [])]
        self._requested_writable = project_writable
        self._project_writable = True
        self._library: Optional[service.TemplateLibrary] = None
        self._filtered: List[service.TemplateEntry] = []
        self._state = STATE_LOADING
        self._notes: List[str] = []
        self._fill_dialog = None
        #: 本会话的试用/出稿成果（真实路径），供「最近成果」读取。
        self._recent_results: List[Dict[str, object]] = []
        self._last_sample = None

        self._build_ui()
        self._project_writable = self._resolve_project_writable()
        self.state_label.setText("本地模板目录加载中…")
        self.status_label.setText("正在加载本地模板目录…")
        QTimer.singleShot(0, self.reload)

    # --- 宿主能力 ---

    def _host_call(self, name: str, *args, **kwargs):
        func = getattr(self._host, name, None)
        if not callable(func):
            return None
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 宿主异常不阻断目录界面
            if hasattr(self, "status_label"):
                self.status_label.setText("{0} 调用失败：{1}".format(name, exc))
            return None

    def _resolve_project_writable(self) -> bool:
        if self._requested_writable is not None:
            return bool(self._requested_writable)
        host_value = self._host_call("tl_project_writable")
        if isinstance(host_value, bool):
            return host_value
        if self._project_root:
            return directory_writable(self._project_root)
        return True

    def set_status(self, message: str) -> None:
        text = str(message or "")
        if hasattr(self, "status_label"):
            self.status_label.setText(text)
        self._host_call("tl_status", text)

    # --- 构建 ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("用途"))
        self.use_combo = QComboBox()
        self.use_combo.setObjectName("templateLibraryUse")
        self.use_combo.addItem("全部用途", USE_ALL)
        for use in (service.USE_SKELETON, service.USE_FILL, service.USE_EXPORT):
            self.use_combo.addItem(service.USE_LABELS.get(use, use), use)
        self.use_combo.currentIndexChanged.connect(lambda *_: self.apply_filter())
        header.addWidget(self.use_combo)
        header.addWidget(QLabel("搜索"))
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("templateLibrarySearch")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("按名称 / 用途 / 类别 / 版本 / 来源搜索")
        self.search_edit.textChanged.connect(lambda *_: self.apply_filter())
        header.addWidget(self.search_edit, 1)
        self.rebuild_btn = QPushButton("重建本地目录")
        self.rebuild_btn.setObjectName("templateLibraryRebuild")
        self.rebuild_btn.setToolTip("按真实目录重新扫描并重写可重建索引；原规范/模板不会被改写")
        self.rebuild_btn.clicked.connect(self._on_rebuild)
        header.addWidget(self.rebuild_btn)
        self.add_template_btn = QPushButton("添加底模…")
        self.add_template_btn.setObjectName("templateLibraryAddTemplate")
        self.add_template_btn.setToolTip("把 .docx 底模复制到本地模板目录（原文件不动）")
        self.add_template_btn.clicked.connect(self._on_add_template)
        header.addWidget(self.add_template_btn)
        self.copy_pack_btn = QPushButton("从规范包制作副本…")
        self.copy_pack_btn.setObjectName("templateLibraryCopyPack")
        self.copy_pack_btn.setToolTip("从已有规范包复制成可编辑草稿；源包与固定包不原地修改")
        self.copy_pack_btn.clicked.connect(self._on_copy_pack)
        header.addWidget(self.copy_pack_btn)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.entry_list = QListWidget()
        self.entry_list.setObjectName("templateLibraryList")
        self.entry_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.entry_list.currentItemChanged.connect(lambda *_: self._on_selection_changed())
        splitter.addWidget(self.entry_list)
        self.details_view = QPlainTextEdit()
        self.details_view.setObjectName("templateLibraryDetails")
        self.details_view.setReadOnly(True)
        self.details_view.setPlaceholderText("选中条目后显示真实来源、版本、内容摘要与未知声明。")
        splitter.addWidget(self.details_view)
        splitter.setSizes([260, 300])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.primary_btn = QPushButton("使用此条目…")
        self.primary_btn.setObjectName("templateLibraryPrimary")
        self.primary_btn.setEnabled(False)
        self.primary_btn.clicked.connect(self._on_primary)
        actions.addWidget(self.primary_btn)
        # V4.1 41-D 4.2：试用小样（可选动作）与最近成果；试用只写隔离目录。
        self.sample_btn = QPushButton("试用小样…")
        self.sample_btn.setObjectName("templateLibrarySample")
        self.sample_btn.setToolTip("用该底模生成隔离小样（默认通用内容，不改当前项目与旧样例）")
        self.sample_btn.setEnabled(False)
        self.sample_btn.clicked.connect(self._on_try_sample)
        actions.addWidget(self.sample_btn)
        self.recent_btn = QPushButton("最近成果")
        self.recent_btn.setObjectName("templateLibraryRecent")
        self.recent_btn.setToolTip("查看本次会话试用/出稿的可打开成果")
        self.recent_btn.setEnabled(False)
        self.recent_btn.clicked.connect(self._on_show_recent)
        actions.addWidget(self.recent_btn)
        self.relocate_btn = QPushButton("重新定位来源…")
        self.relocate_btn.setObjectName("templateLibraryRelocate")
        self.relocate_btn.setEnabled(False)
        self.relocate_btn.clicked.connect(self._on_relocate)
        actions.addWidget(self.relocate_btn)
        self.copy_selected_btn = QPushButton("制作可编辑副本…")
        self.copy_selected_btn.setObjectName("templateLibraryCopySelected")
        self.copy_selected_btn.setToolTip("固定包只生成制作副本，不原地修改原包")
        self.copy_selected_btn.setEnabled(False)
        self.copy_selected_btn.clicked.connect(self._on_copy_selected)
        actions.addWidget(self.copy_selected_btn)
        self.open_source_btn = QPushButton("打开来源位置")
        self.open_source_btn.setObjectName("templateLibraryOpenSource")
        self.open_source_btn.setEnabled(False)
        self.open_source_btn.clicked.connect(self._on_open_source)
        actions.addWidget(self.open_source_btn)
        actions.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.state_label = QLabel("")
        self.state_label.setObjectName("templateLibraryState")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.status_label = QLabel("")
        self.status_label.setObjectName("templateLibraryStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # --- 加载与状态 ---

    @property
    def library(self) -> Optional[service.TemplateLibrary]:
        return self._library

    def entries(self) -> List[service.TemplateEntry]:
        return list(self._library.entries) if self._library is not None else []

    def filtered_entries(self) -> List[service.TemplateEntry]:
        return list(self._filtered)

    def reload(self, *, force: bool = False, note: str = "") -> None:
        """加载本地目录；``force`` 时按真实目录重建（坏索引/外部变化都走这里）。"""
        index_file = service.index_path(self._state_dir)
        broken = False
        if not force and index_file.is_file() and service.read_index(self._state_dir) is None:
            broken = True
            try:
                shutil.copy2(str(index_file), str(index_file.with_name(index_file.name + ".damaged")))
            except OSError:
                pass
        load_note = ""
        try:
            if force:
                library = service.build_library(
                    self._roots, templates_root=self._templates_root, state_dir=self._state_dir
                )
            else:
                library = service.load_library(
                    self._roots, templates_root=self._templates_root, state_dir=self._state_dir
                )
        except Exception as exc:  # noqa: BLE001 - 索引不可写/坏目录不阻断使用
            load_note = "本地目录索引不可写（{0}）".format(exc)
            try:
                entries = service.scan_roots(
                    self._roots, templates_root=self._templates_root, warnings=None
                )
                library = service.TemplateLibrary(
                    roots=[str(item) for item in self._roots], entries=entries,
                    warnings=["{0}；本轮按真实目录只读加载，原规范/模板未改写".format(load_note)],
                )
            except Exception as exc2:  # noqa: BLE001 - 彻底不可读时给出下一步
                self._library = None
                self._notes = ["本地目录读取失败：{0}".format(exc2)]
                self.apply_filter()
                return
        self._library = library
        notes: List[str] = []
        if broken:
            notes.append("本地目录索引不可读（原文件已保留为 .damaged 副本），本轮按真实目录重建")
        if load_note:
            notes.append(load_note)
        notes.extend(str(item) for item in list(library.warnings or []))
        for message in service.relocate_warning(library):
            notes.append(message)
        if self._project_root and not self._project_writable:
            notes.append(
                "当前项目为只读：本轮不向项目内写入任何文件；草稿/副本/出稿请另选可写目录"
            )
        self._notes = notes
        self.apply_filter()
        if note:
            self.set_status(note)

    def apply_filter(self) -> None:
        """按用途与关键字刷新列表（列表只展示，不改动任何真实资源）。"""
        library = self._library
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        if library is not None:
            use = str(self.use_combo.currentData() or USE_ALL)
            entries = library.search(self.search_edit.text(), use=use)
            for entry in entries:
                label = "{0}｜{1}{2}{3}".format(
                    entry.name,
                    entry.useLabel,
                    "（来源缺失）" if entry.missing else "",
                    "（固定包）" if entry.fixed else "",
                )
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, entry.entryId)
                item.setToolTip(entry.identity)
                self.entry_list.addItem(item)
            self._filtered = entries
            if entries:
                self.entry_list.setCurrentRow(0)
        else:
            self._filtered = []
        self.entry_list.blockSignals(False)
        self._refresh_selection()
        self._update_state()

    def _update_state(self) -> None:
        library = self._library
        if library is None:
            self._state = STATE_UNREADABLE
        elif not library.entries:
            self._state = STATE_EMPTY
        elif not self._filtered:
            self._state = STATE_NO_RESULT
        elif any(item.missing for item in library.entries):
            self._state = STATE_MISSING
        else:
            self._state = STATE_OK
        parts: List[str] = []
        if self._state == STATE_LOADING:
            parts.append("本地模板目录加载中…")
        elif library is None:
            parts.append("本地模板目录不可读")
        else:
            parts.append(library.summary_line())
            parts.append("当前筛选 {0} 条".format(len(self._filtered)))
        parts.extend(self._notes)
        self.state_label.setText("；".join(part for part in parts if part))
        self.set_status(self._state_next_step())

    def _state_next_step(self) -> str:
        """当前状态的可执行下一步（就地反馈，不弹窗阻断）。"""
        if self._state == STATE_LOADING:
            return "正在加载本地模板目录…"
        if self._library is None:
            return "本地目录不可读：点「重建本地目录」按真实目录重试；其他编辑与项目不受影响。"
        if self._state == STATE_EMPTY:
            return (
                "本地模板目录为空：点「添加底模…」把 .docx 放进 {0}，"
                "或「从规范包制作副本…」从已有规范包生成条目；空目录仍可用内置通用规范建项。"
            ).format(self._templates_root)
        if self._state == STATE_NO_RESULT:
            return "没有匹配的条目：清空搜索或把用途切回「全部用途」；也可「重建本地目录」确认真实目录。"
        entry = self.selected_entry()
        if self._state == STATE_MISSING and (entry is None or not entry.missing):
            count = len([item for item in self._library.entries if item.missing])
            return "有 {0} 个条目来源缺失：选中该条目后点「重新定位来源…」；其他条目照常可用。".format(count)
        if entry is None:
            return "已加载 {0} 个条目：选中一行查看真实来源、版本与内容摘要。".format(
                len(self._library.entries)
            )
        if entry.missing:
            return "该条目来源已不存在：点「重新定位来源…」或改用其他条目；原模板/规范包未被改写。"
        if entry.fixed:
            return "固定包只能制作副本：需要修改请点「制作可编辑副本…」，内置包不会被原地改写。"
        return "可执行：{0}（详情里的来源与摘要来自真实文件）。".format(self._primary_label(entry))

    def selected_entry(self) -> Optional[service.TemplateEntry]:
        item = self.entry_list.currentItem()
        if item is None or self._library is None:
            return None
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        return self._library.get(str(entry_id))

    def _primary_label(self, entry: service.TemplateEntry) -> str:
        return _PRIMARY_LABELS.get(entry.use, "使用此条目…")

    def _on_selection_changed(self) -> None:
        self._refresh_selection()
        self.set_status(self._state_next_step())

    def _refresh_selection(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.details_view.setPlainText(
                "未选择条目：本地目录为空，或当前筛选没有结果；按上方提示继续。"
            )
            self.primary_btn.setEnabled(False)
            self.primary_btn.setText("使用此条目…")
            self.relocate_btn.setEnabled(False)
            self.copy_selected_btn.setEnabled(False)
            self.open_source_btn.setEnabled(False)
            self._sync_sample_buttons()
            return
        self.details_view.setPlainText(self._details_text(entry))
        self.primary_btn.setText(self._primary_label(entry))
        self.primary_btn.setEnabled(not entry.missing)
        self.relocate_btn.setEnabled(bool(entry.missing))
        self.copy_selected_btn.setEnabled(bool(entry.packRoot) and not entry.missing)
        self.open_source_btn.setEnabled(
            Path(entry.templatePath or entry.packRoot or entry.source).exists()
        )
        self._sync_sample_buttons()

    def _details_text(self, entry: service.TemplateEntry) -> str:
        """详情只读真实字段；读不出的不猜，未知声明原样保留。"""
        lines = [
            "名称：{0}".format(entry.name),
            "用途：{0}（{1}）".format(entry.useLabel, entry.use),
            "真实来源：{0}".format(entry.source),
            "来源类型：{0}".format(entry.sourceKind or "—"),
            "版本：{0}".format(entry.version or "—"),
            "内容摘要（sha256）：{0}".format(entry.summary or "—"),
            "文档类别 documentKind：{0}".format(entry.documentKind or "—"),
            "身份（来源#摘要）：{0}".format(entry.identity),
            "固定包：{0}".format(
                "是（内置固定包；需要修改请「制作可编辑副本…」，不原地改写）"
                if entry.fixed else "否"
            ),
            "规范包目录：{0}".format(entry.packRoot or "—"),
            "底模：{0}".format(entry.templatePath or "—"),
            "recipe：{0}".format(entry.recipePath or "（无，按受支持字段默认）"),
            "来源状态：{0}".format("缺失（原文件已不存在）" if entry.missing else "存在"),
            "说明：{0}".format(entry.description or "—"),
        ]
        if entry.missing:
            lines.append("下一步：点「重新定位来源…」选择新的规范包/底模目录，或用「重建本地目录」。")
        lines.append("未知声明（原样保留，未声称已生效）：")
        lines.append(
            json.dumps(entry.unknown, ensure_ascii=False, indent=2) if entry.unknown else "（无）"
        )
        return "\n".join(lines)

    def state_text(self) -> str:
        return self.state_label.text()

    def status_text(self) -> str:
        return self.status_label.text()

    # --- 写入目标守卫 ---

    def _target_writable(self, path: object) -> bool:
        target = Path(path)
        if (
            self._project_root
            and not self._project_writable
            and _inside(target, Path(self._project_root))
        ):
            self.set_status(
                "当前项目为只读（模式版本不兼容）：不能把草稿/底模写入 {0}；"
                "请另选可写目录，项目内不会新增写入。".format(self._project_root)
            )
            return False
        check = target if target.is_dir() else target.parent
        if not directory_writable(check):
            self.set_status(
                "目标目录不可写：{0}；请另选可写目录（原有文件未改动）。".format(target)
            )
            return False
        return True

    # --- 动作 ---

    def _on_primary(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.set_status("请先选择一条模板/规范条目。")
            return
        if entry.use == service.USE_SKELETON:
            self._create_project(entry)
        elif entry.use == service.USE_EXPORT:
            self._open_template_fill(entry, with_project_chapters=True)
        else:
            self._open_template_fill(entry, with_project_chapters=False)

    def _create_project(self, entry: service.TemplateEntry) -> None:
        """骨架建项：调用原规范包建项服务（不替换当前项目正文）。"""
        source = Path(entry.source)
        if entry.missing or not source.is_dir():
            self.set_status("该规范条目的来源已不存在：请先「重新定位来源…」，或改用其他条目。")
            return
        from doc_tool.application.intake_entries import default_project_parent, plan_target
        from doc_tool.application.project_from_pack import create_project_from_pack

        parent = QFileDialog.getExistingDirectory(
            self, "选择新项目所在目录", str(default_project_parent())
        )
        if not parent:
            return
        if not self._target_writable(parent):
            return
        target = plan_target(source, parent_dir=parent, trusted_name=entry.name)
        try:
            result = create_project_from_pack(
                entry.source, target.directory, document_name=target.document_name
            )
        except Exception as exc:  # noqa: BLE001 - 建项失败保留当前项目与缓冲
            self.set_status("建项失败：{0}（当前项目与打开中的章节未改动）".format(exc))
            return
        if not result.ok or result.project_root is None:
            self.set_status(
                "建项未完成：{0}".format("；".join(result.errors or result.warnings) or "未知原因")
            )
            return
        self.set_status(
            "已按规范骨架建立项目：{0}（当前项目与打开中的章节未改动；新项目在新窗口打开）".format(
                Path(result.project_root).name
            )
        )
        self._host_call("tl_project_created", str(result.project_root))

    def _open_template_fill(self, entry: service.TemplateEntry, *, with_project_chapters: bool) -> None:
        """出稿/填充：沿用既有底模出稿流程；出稿用途用规范包自带 template.docx。"""
        template_text = str(entry.templatePath or "")
        if not template_text and entry.use == service.USE_EXPORT and entry.packRoot:
            candidate = Path(entry.packRoot) / "template.docx"
            template_text = str(candidate) if candidate.is_file() else ""
        template = Path(template_text) if template_text else None
        if template is None or not template.is_file():
            self.set_status(
                "该条目的底模文件不存在：请先「重新定位来源…」，或改用其他条目；当前项目未改动。"
            )
            return
        paths: List[Path] = []
        if with_project_chapters:
            chapters = self._project_chapters or list(
                self._host_call("tl_project_chapters") or []
            )
            paths = [Path(item) for item in chapters if Path(item).is_file()]
        recipe = service.recipe_for(entry)
        busy = getattr(self._host, "tl_busy_check", None)
        dialog = TemplateFillDialog(
            parent=self,
            busy_check=busy if callable(busy) else None,
            paths=paths or None,
            template=str(template),
            recipe=recipe or None,
        )
        self._fill_dialog = dialog
        dialog.exec()
        self.set_status(
            "已打开既有底模出稿流程：底模 {0}{1}（当前项目未改动）。".format(
                template.name, "；已带上目录 recipe" if recipe else ""
            )
        )

    def _sync_sample_buttons(self) -> None:
        """试用/最近成果按钮状态：有可解析底模才允许试用。"""
        has_sample_btn = getattr(self, "sample_btn", None) is not None
        if has_sample_btn:
            entry = self.selected_entry()
            template = self._template_path_for(entry) if entry is not None else None
            self.sample_btn.setEnabled(bool(template and template.is_file()))
        recent_btn = getattr(self, "recent_btn", None)
        if recent_btn is not None:
            recent_btn.setEnabled(bool(self._recent_results))

    def _template_path_for(self, entry) -> Optional[Path]:
        """所选条目的真实底模路径（项目出稿用规范包自带 template.docx）。"""
        if entry is None:
            return None
        text = str(getattr(entry, "templatePath", "") or "")
        if not text and getattr(entry, "packRoot", ""):
            candidate = Path(entry.packRoot) / "template.docx"
            text = str(candidate) if candidate.is_file() else ""
        target = Path(text) if text else None
        return target if target is not None and target.is_file() else None

    def _sample_base_dir(self) -> Path:
        """小样隔离目录：项目/状态目录下的 ``template-samples``（不写业务正文）。"""
        root = str(self._project_root or "") or ""
        if root:
            return Path(root) / ".state" / "template-samples"
        return Path(self._state_dir) / "template-samples"

    def _on_try_sample(self) -> None:
        """试用小样：隔离目录、默认通用内容、不改当前项目与旧样例。"""
        entry = self.selected_entry()
        template = self._template_path_for(entry)
        if entry is None or template is None:
            self.set_status(
                "该条目没有可用的底模文件：请先「重新定位来源…」，或改用其他条目；"
                "普通出稿不受影响。"
            )
            return
        from doc_tool.application.template_sample import run_sample

        base = self._sample_base_dir()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.set_status("无法创建小样目录：{0}（当前项目未改动）".format(exc))
            return
        previous = self._last_sample
        outcome = run_sample(
            template, base,
            existing_key=str(getattr(previous, "reuseKey", "") or "") if previous else "",
            existing_dir=str(getattr(previous, "directory", "") or "") if previous else "",
            project_root=str(self._project_root or ""),
        )
        self._last_sample = outcome
        self._notes = [line for line in outcome.summary_lines()]
        if outcome.ok:
            self._recent_results.insert(0, {
                "kind": "sample", "label": "试用小样：{0}".format(entry.name),
                "path": str(outcome.docxPath),
                "preview": str(outcome.htmlPreview or ""),
                "reused": bool(outcome.reused),
            })
            self.set_status(
                "已生成隔离小样：{0}（默认通用内容；HTML 为内容预览，Word 分页需真实 Word）"
                "。当前项目与旧样例未被修改。".format(Path(outcome.docxPath).name)
            )
            opened = self._host_call("tl_open_path", outcome.docxPath)
            if opened is None:
                pass
        else:
            self.set_status("小样未生成：{0}".format(
                "；".join(outcome.warnings) or "未知原因"
            ))
        self._refresh_selection()
        self._sync_sample_buttons()

    def _on_show_recent(self) -> None:
        """最近成果：列出本会话可打开的真实路径（不伪造）。"""
        if not self._recent_results:
            self.set_status("本次会话还没有可打开的试用/出稿成果。")
            return
        lines = ["最近成果（本会话，真实路径）："]
        for item in self._recent_results[:5]:
            suffix = "（复用同模板小样）" if item.get("reused") else ""
            lines.append("· {0}｜{1}{2}".format(item.get("label"), item.get("path"), suffix))
        self._notes = lines
        self._refresh_selection()
        self.set_status(lines[0] + " 共 {0} 项".format(len(self._recent_results)))

    def _make_editable_copy(self, pack_source: str, name: str) -> None:
        """固定/已有规范包的唯一修改路径：复制成制作副本，源包不原地改写。"""
        from doc_tool.application import pack_authoring as authoring

        destination = QFileDialog.getExistingDirectory(
            self, "选择制作副本目录（源包不会被修改）"
        )
        if not destination:
            return
        if not self._target_writable(destination):
            return
        copy_dir = Path(destination) / "{0}-副本".format(name or "规范包")
        try:
            authoring.draft_from_pack(pack_source, copy_dir)
        except Exception as exc:  # noqa: BLE001 - 复制失败保留源包
            self.set_status("制作副本失败：{0}（源包未被修改）".format(exc))
            return
        message = "已生成可编辑副本：{0}（源包/固定包未被修改）".format(copy_dir)
        opened = self._host_call("tl_open_pack_draft", str(copy_dir))
        if opened is None:
            message += "；可用菜单「规范包制作…」打开该目录继续编辑。"
        self.set_status(message)

    def _on_copy_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None or not entry.packRoot:
            self.set_status("请选择有规范包来源的条目；固定包只能通过制作副本修改。")
            return
        if entry.missing or not Path(entry.packRoot).is_dir():
            self.set_status("该规范包来源已不存在：请先「重新定位来源…」。")
            return
        self._make_editable_copy(entry.packRoot, entry.name)

    def _on_copy_pack(self) -> None:
        pack_dir = QFileDialog.getExistingDirectory(self, "选择已有规范包目录")
        if not pack_dir:
            return
        validation = validate_pack_dir(pack_dir)
        if not validation.ok or validation.pack is None:
            self.set_status(
                "该目录不是可用规范包：{0}；请选择含 pack.yml（schema 1）的目录。".format(
                    "；".join(validation.errors) or "缺少 pack.yml"
                )
            )
            return
        self._make_editable_copy(pack_dir, validation.pack.pack_id)

    def _on_add_template(self) -> None:
        picked, _filter = QFileDialog.getOpenFileName(
            self, "选择 Word 底模（复制到本地模板目录）", "", "Word 文档 (*.docx)"
        )
        if not picked:
            return
        source = Path(picked)
        if not source.is_file():
            self.set_status("所选底模不存在：{0}（未复制任何文件）".format(source))
            return
        root = Path(self._templates_root)
        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)
        if not self._target_writable(root):
            return
        try:
            shutil.copy2(str(source), str(root / source.name))
        except OSError as exc:
            self.set_status("复制底模失败：{0}（原文件未被修改）".format(exc))
            return
        self.reload(force=True)
        self.set_status(
            "已添加底模：{0}（原文件未被修改）；可在「模板填充」用途下使用。".format(source.name)
        )

    def _on_rebuild(self) -> None:
        self.reload(force=True)
        count = len(self.entries())
        self.set_status(
            "已按真实目录重建本地目录：{0} 条（原规范/模板与项目正文未改写）。".format(count)
        )

    def _on_relocate(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.set_status("请先选择来源缺失的条目。")
            return
        picked = QFileDialog.getExistingDirectory(
            self, "重新定位来源（选择包含该规范包或底模的目录）"
        )
        if not picked:
            return
        base = Path(picked)
        if base.is_file():
            base = base.parent
        if not base.is_dir():
            self.set_status("所选位置不是目录：{0}".format(base))
            return
        known = {os.path.normcase(os.path.abspath(item)) for item in self._roots}
        if os.path.normcase(os.path.abspath(str(base))) not in known:
            self._roots.append(str(base))
        self.reload(force=True)
        match = next(
            (
                item
                for item in self.entries()
                if item.use == entry.use and item.name == entry.name
            ),
            None,
        )
        if match is not None and not match.missing:
            self.set_status(
                "已重新定位：{0} → {1}（新内容摘要 {2}）；原固定包未被原地修改。".format(
                    match.name, match.source, match.summary[:12]
                )
            )
        else:
            self.set_status(
                "已把目录加入本地目录并重建，但未找到同名条目：请确认该目录含 pack.yml 或 .docx 底模。"
            )

    def _on_open_source(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.set_status("请先选择条目。")
            return
        target = entry.templatePath or entry.packRoot or entry.source
        if not Path(target).exists():
            self.set_status("来源已不存在：请点「重新定位来源…」。")
            return
        opened = self._host_call("tl_open_path", target)
        if opened is None:
            self.set_status("已定位来源：{0}（当前宿主未提供打开能力）".format(target))
        else:
            self.set_status("已请求打开来源：{0}".format(target))