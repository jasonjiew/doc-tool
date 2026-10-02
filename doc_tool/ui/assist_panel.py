# -*- coding: utf-8 -*-
"""V3.3 33-E 写作辅助面板（资料搜索 / 建议收件区 / 可选增强）。

设计约束：

- 面板只调用 ``AuthoringAssistant`` 门面，不直接写文件；正文插入通过
  ``insert_requested`` 信号交给编辑器既有的插入/撤销路径，摘要候选通过
  ``summary_candidate`` 信号交给原修订对话框（不自动追加修订记录）。
- provider 未启用时增强按钮仍然可见可用，点击后展示本地候选与“未启用”说明。
- 没有模型/网络/账户时，搜索与建议全部可用。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from doc_tool.ui.flow_row import FlowRow
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from doc_tool.application.assist.adoption import AdoptionOutcome
from doc_tool.application.assist.models import (
    INSERT_MODE_CITATION, INSERT_MODE_COPY_TEXT, PURPOSE_REVISION_SUMMARY, PURPOSE_TERM,
)
from doc_tool.application.assist.provider import EnhancementResult
from doc_tool.application.assist.search_local import SearchHit, SearchOutcome
from doc_tool.application.assist.suggestions import Suggestion, SuggestionSet


class AssistPanel(QWidget):
    """写作辅助面板（可嵌入编辑器/项目概览的独立控件）。"""

    insert_requested = Signal(str, str)     # (插入文本, 模式：citation | copy-text)
    summary_candidate = Signal(str)         # 修订摘要候选（只填原修订框）
    status_message = Signal(str)
    buffers_changed = Signal(dict)           # 采纳/撤销后的全文缓冲（relPath -> 文本）

    def __init__(
        self,
        assistant=None,
        *,
        project_root=None,
        on_scope_changed=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        # UI 包 4.3：``on_scope_changed(roots)`` 让主窗口按新资料范围重装助手。
        self._on_scope_changed = on_scope_changed
        self._extra_module_roots: List[str] = []
        self._assistant = assistant
        self._project_root = project_root
        self._index_runner = None
        self._index_result = None
        self._outcome: Optional[SearchOutcome] = None
        self._suggestion_set: Optional[SuggestionSet] = None
        self._suggestions: List[Suggestion] = []
        self._last_adoption: Optional[AdoptionOutcome] = None
        self._build_ui()
        if assistant is not None:
            self.set_assistant(assistant)

    # --- 后台索引（V3.3 1.3）---

    def index_in_background(self, *, refresh: bool = False, batch_size: int = 40) -> bool:
        """用既有 TaskRunner 在后台分批建索引；返回是否已启动。

        检索本身在无索引时也能读可读文本（回退），因此这里只负责“尽快把索引建好”，
        绝不在编辑线程里同步重建。
        """
        root = self._project_root
        if root is None and self._assistant is not None:
            root = getattr(self._assistant, "project_root", None)
        if root is None:
            self.set_status("缺少项目路径，无法在后台建立资料索引。")
            return False
        runner = self._index_runner
        if runner is None:
            from doc_tool.ui.task_bridge import TaskRunner

            runner = TaskRunner()
            self._index_runner = runner
        # 真实界面必须轮询 runner：否则完成回调（状态提示 + 失效缓存）永不触发。
        try:
            from PySide6.QtCore import QTimer

            timer = getattr(self, "_index_timer", None)
            if timer is None:
                timer = QTimer(self)
                timer.setInterval(250)
                timer.timeout.connect(lambda: self._poll_background_index())
                self._index_timer = timer
            timer.start()
        except Exception:  # noqa: BLE001 - 无 Qt 事件循环时退化为测试用等待
            self._index_timer = None
        if getattr(runner, "is_running", False):
            return True
        from doc_tool.application.assist.worker import build_index_task
        from doc_tool.ui.task_bridge import TaskSpec

        def _done(result):
            self._index_result = result
            if isinstance(result, dict) and result.get("ok"):
                # 后台已写好缓存：让本面板的检索下次重新载入（不阻塞编辑）
                service = getattr(self._assistant, "search_service", None)
                invalidate = getattr(service, "invalidate", None)
                if callable(invalidate):
                    try:
                        invalidate()
                    except Exception:  # noqa: BLE001 - 失效失败不影响检索回退
                        pass
                self.set_status("资料索引已更新（{0} 份文档，分批 {1} 次）".format(
                    result.get("documents", 0), result.get("batches", 0),
                ))
            else:
                self.set_status("资料索引未完成，检索仍使用可读文本回退。")

        started = runner.start(
            TaskSpec(
                name="assist-index",
                target=build_index_task,
                args=(str(root),),
                kwargs={"refresh": bool(refresh), "batch_size": int(batch_size)},
                timeout_seconds=900,
            ),
            on_done=_done,
        )
        if started:
            self.set_status("正在后台建立资料索引（编辑不受影响，可继续检索）…")
        return bool(started)

    def _poll_background_index(self) -> None:
        """定时轮询后台索引（进入事件循环时生效）。"""
        runner = getattr(self, "_index_runner", None)
        if runner is None:
            return
        try:
            runner.poll()
        except Exception:  # noqa: BLE001 - 轮询失败不打断编辑
            pass
        if not getattr(runner, "is_running", False):
            timer = getattr(self, "_index_timer", None)
            if timer is not None:
                timer.stop()

    def has_background_index(self) -> bool:
        return self._index_runner is not None

    def background_index_result(self):
        return self._index_result

    def wait_background_index(self, timeout: float = 120.0) -> None:
        """测试/收尾用：等待后台索引结束（界面正常使用不需要调用）。"""
        runner = self._index_runner
        if runner is None:
            return
        runner.join(timeout)
        runner.poll()

    # --- UI ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._scope_label = QLabel("资料范围：（未加入任何项目/模块）")
        self._scope_label.setWordWrap(True)
        layout.addWidget(self._scope_label)

        # UI 包 4.3：资料与建议切页；出处/差异详情为两页共用，放在切页下方。
        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("assistTabs")

        materials = QWidget(self._tabs)
        materials_layout = QVBoxLayout(materials)
        materials_layout.setContentsMargins(0, 4, 0, 0)

        search_row = FlowRow(stack_below=380, parent=materials)
        self._query = QLineEdit()
        self._query.setPlaceholderText("在已加入的项目/模块/当前缓冲中搜索")
        self._query.returnPressed.connect(self.search)
        self._search_button = QPushButton("搜索")
        self._search_button.clicked.connect(self.search)
        self._include_buffer = QCheckBox("含当前缓冲")
        self._include_buffer.setChecked(True)
        search_row.add(self._query)
        search_row.add(self._include_buffer)
        search_row.add(self._search_button)
        self._search_row = search_row
        materials_layout.addWidget(search_row)

        # 无资料范围时的真实设置动作（不是说明性空状态）。
        self._scope_actions = FlowRow(stack_below=380, parent=materials)
        self._add_scope_button = QPushButton("添加资料范围…")
        self._add_scope_button.setObjectName("assistAddScopeBtn")
        self._add_scope_button.setToolTip(
            "选择已有模块库目录作为资料范围；只读加入，不修改该库内容"
        )
        self._add_scope_button.clicked.connect(self.add_scope_manually)
        self._scope_actions.add(self._add_scope_button)
        self._scope_actions.add_stretch()
        materials_layout.addWidget(self._scope_actions)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        materials_layout.addWidget(self._summary)

        self._results = QListWidget()
        self._results.currentRowChanged.connect(lambda _row: self._update_diff_preview())
        materials_layout.addWidget(self._results, 2)

        hit_row = QHBoxLayout()
        self._cite_button = QPushButton("插入来源引用")
        self._cite_button.clicked.connect(lambda: self.insert_selected(INSERT_MODE_CITATION))
        self._copy_button = QPushButton("复制正文")
        self._copy_button.clicked.connect(lambda: self.insert_selected(INSERT_MODE_COPY_TEXT))
        hit_row.addWidget(self._cite_button)
        hit_row.addWidget(self._copy_button)
        hit_row.addStretch(1)
        materials_layout.addLayout(hit_row)
        self._tabs.addTab(materials, "资料")

        suggestions = QWidget(self._tabs)
        suggestions_layout = QVBoxLayout(suggestions)
        suggestions_layout.setContentsMargins(0, 4, 0, 0)
        suggest_row = QHBoxLayout()
        self._load_suggestions_button = QPushButton("刷新建议")
        self._load_suggestions_button.setToolTip("按当前规则/术语/引用/复核/变更事实与模块装配重新收集建议")
        self._load_suggestions_button.clicked.connect(lambda: self.load_suggestions())
        suggest_row.addWidget(self._load_suggestions_button)
        suggest_row.addStretch(1)
        suggestions_layout.addLayout(suggest_row)
        self._suggestions_list = QListWidget()
        self._suggestions_list.currentRowChanged.connect(lambda _row: self._update_diff_preview())
        suggestions_layout.addWidget(self._suggestions_list, 2)
        adopt_row = FlowRow(stack_below=380, parent=suggestions)
        self._adopt_button = QPushButton("采纳所选")
        self._adopt_button.clicked.connect(self.adopt_selected)
        self._ignore_button = QPushButton("忽略所选")
        self._ignore_button.clicked.connect(self.ignore_selected)
        self._undo_button = QPushButton("撤销上次采纳")
        self._undo_button.clicked.connect(self.undo_last)
        self._export_button = QPushButton("导出建议…")
        self._export_button.setToolTip("把当前建议集合导出为审阅用文件（只读项目同样可用）")
        self._export_button.clicked.connect(self.export_suggestions_to_file)
        adopt_row.add(self._adopt_button)
        adopt_row.add(self._ignore_button)
        adopt_row.add(self._undo_button)
        adopt_row.add(self._export_button)
        adopt_row.add_stretch()
        self._adopt_row = adopt_row
        suggestions_layout.addWidget(adopt_row)
        self._tabs.addTab(suggestions, "建议")
        layout.addWidget(self._tabs, 3)

        self._diff_view = QPlainTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setPlaceholderText("选择一条结果/建议查看 before-after 差异")
        layout.addWidget(self._diff_view, 2)

        enhance_row = QHBoxLayout()
        self._provider_label = QLabel("可选增强：未启用（本地候选可用）")
        self._provider_label.setWordWrap(True)
        self._enhance_summary_button = QPushButton("增强摘要")
        self._enhance_summary_button.clicked.connect(lambda: self.enhance(PURPOSE_REVISION_SUMMARY))
        self._enhance_term_button = QPushButton("增强术语")
        self._enhance_term_button.clicked.connect(lambda: self.enhance(PURPOSE_TERM))
        enhance_row.addWidget(self._provider_label, 1)
        enhance_row.addWidget(self._enhance_summary_button)
        enhance_row.addWidget(self._enhance_term_button)
        layout.addLayout(enhance_row)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = int(event.size().width()) - 12
        for row in (
            getattr(self, "_search_row", None),
            getattr(self, "_scope_actions", None),
            getattr(self, "_adopt_row", None),
        ):
            if row is not None:
                row.apply_width(width)

    def current_page(self) -> str:
        """当前切页标识：``materials``（资料）或 ``suggestions``（建议）。"""
        return "suggestions" if self._tabs.currentIndex() == 1 else "materials"

    def show_page(self, page: str) -> None:
        """切换资料/建议页；共用下方的出处/差异详情不随页面重置。"""
        self._tabs.setCurrentIndex(1 if str(page) == "suggestions" else 0)

    def add_scope_manually(self) -> None:
        """无资料范围时的真实设置动作：选择一个已有模块库作为资料范围。"""
        from PySide6.QtWidgets import QFileDialog

        chosen = QFileDialog.getExistingDirectory(self, "选择资料范围（已有模块库目录）")
        if not chosen:
            self.set_status("已取消添加资料范围")
            return
        roots = list(getattr(self, "_extra_module_roots", []) or [])
        if chosen not in roots:
            roots.append(chosen)
        self._extra_module_roots = roots
        self.set_status("已加入资料范围：{0}".format(chosen))
        if self._on_scope_changed is not None:
            self._on_scope_changed(roots)
        self.refresh_scope()
    # --- 装配 ---

    def load_all_suggestions(self) -> Optional[SuggestionSet]:
        """按全部种类收集建议（含模块更新提示），供面板与命令入口共用。"""
        return self.load_suggestions()

    def set_assistant(self, assistant) -> None:
        self._assistant = assistant
        self.refresh_scope()
        self.refresh_provider_label()
        # 打开/切换项目后立即给出建议（含模块更新提示），无需先手动点按钮
        try:
            self.load_suggestions()
        except Exception:  # noqa: BLE001 - 建议不可用不影响检索
            pass

    @property
    def assistant(self):
        return self._assistant

    def refresh_scope(self) -> None:
        if self._assistant is None:
            self._scope_label.setText("资料范围：（未加入任何项目/模块）")
            return
        entries = self._assistant.scope_summary()
        labels = []
        for item in entries:
            suffix = "（当前缓冲）" if item.get("unsaved") else ""
            labels.append("{0}：{1}{2}".format(
                item.get("kindLabel", item.get("kind", "")), item.get("label", ""), suffix
            ))
        self._scope_label.setText("资料范围：{0}".format("；".join(labels) or "（空）"))

    def refresh_provider_label(self) -> None:
        if self._assistant is None:
            return
        status = self._assistant.provider_status()
        self._provider_label.setText(
            "可选增强：{0}｜上限 {1} 字符".format(
                status.get("target", "未启用"), status.get("maxChars", "")
            )
        )

    # --- 搜索 ---

    def search(self, query: Optional[str] = None) -> Optional[SearchOutcome]:
        if self._assistant is None:
            self.set_status("尚未装配项目上下文，无法搜索。")
            return None
        text = query if query is not None else self._query.text()
        outcome = self._assistant.search_evidence(text)
        self.show_search_outcome(outcome)
        # 无缓存/索引陈旧时顺手在后台建索引：本次结果照常返回，编辑不被阻塞。
        from doc_tool.application.assist.models import CACHE_DISABLED, CACHE_FRESH

        status_text = str(getattr(outcome, "cache_status", "") or "")
        if status_text not in (CACHE_FRESH, CACHE_DISABLED):
            self.index_in_background()
        if getattr(outcome, "deduped", 0):
            self.set_status("检索完成：{0} 条命中（按来源去重 {1} 条）".format(
                len(outcome.hits), outcome.deduped,
            ))
        return outcome

    def show_search_outcome(self, outcome: SearchOutcome) -> None:
        self._outcome = outcome
        self._results.clear()
        for hit in outcome.hits:
            self._results.addItem(self._hit_item(hit))
        self._summary.setText("；".join(outcome.summary_lines()) or "")
        self.set_status("；".join(outcome.summary_lines()) or "")

    @staticmethod
    def _hit_item(hit: SearchHit) -> QListWidgetItem:
        flags = []
        if hit.unsaved:
            flags.append("未保存")
        if hit.stale:
            flags.append("陈旧")
        text = "{0}｜{1}{2}".format(
            hit.location_label, hit.text.strip()[:80],
            "（{0}）".format("／".join(flags)) if flags else "",
        )
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, hit)
        return item

    def selected_hit(self) -> Optional[SearchHit]:
        item = self._results.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def insert_selected(self, mode: str = INSERT_MODE_CITATION) -> Optional[str]:
        hit = self.selected_hit()
        if hit is None or self._assistant is None:
            self.set_status("请先选择一条检索结果。")
            return None
        text = self._assistant.insert_text(hit, mode)
        self.insert_requested.emit(text, mode)
        self.set_status("已生成{0}，交由编辑器既有插入/撤销路径。".format(
            "来源引用" if mode == INSERT_MODE_CITATION else "正文副本"
        ))
        return text

    # --- 建议 ---

    def load_suggestions(self, kinds: Optional[Sequence[str]] = None) -> Optional[SuggestionSet]:
        if self._assistant is None:
            return None
        result = self._assistant.suggest(kinds=kinds)
        self.set_suggestions(result)
        return result

    def suggestions_export_text(self) -> str:
        """当前建议集合的审阅文本（服务层同一实现，只读项目同样可用）。"""
        if self._assistant is None:
            return ""
        exporter = getattr(self._assistant, "export_suggestions", None)
        if not callable(exporter):
            return ""
        items = self._suggestions or None
        try:
            return str(exporter(items) if items is not None else exporter([]))
        except TypeError:
            return str(exporter(self._suggestions))
        except Exception as exc:  # noqa: BLE001 - 导出失败如实提示
            self.set_status("导出建议失败：{0}".format(exc))
            return ""

    def export_suggestions_to_file(self):
        """界面入口：选择文件后写盘（此前 export_suggestions 无任何生产调用方）。"""
        from pathlib import Path as _Path

        from PySide6.QtWidgets import QFileDialog

        text = self.suggestions_export_text()
        if not text:
            self.set_status("没有可导出的建议：请先刷新建议。")
            return None
        default_name = "建议清单.md"
        if self._assistant is not None and getattr(self._assistant, "read_only", False):
            default_name = "建议清单（只读项目）.md"
        target, _selected = QFileDialog.getSaveFileName(
            self, "导出建议", default_name, "Markdown (*.md);;文本 (*.txt);;所有文件 (*)",
        )
        if not target:
            return None
        path = _Path(target)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            self.set_status("导出建议失败：{0}".format(exc))
            return None
        self.set_status("建议已导出：{0}".format(path))
        return str(path)

    def set_suggestions(self, suggestion_set: SuggestionSet) -> None:
        self._suggestion_set = suggestion_set
        self._suggestions = list(suggestion_set.suggestions)
        self._suggestions_list.clear()
        for item in self._suggestions:
            widget_item = QListWidgetItem("{0}｜{1}｜{2}｜{3}".format(
                item.status_label, item.kind_label, item.title, item.coverage_label
            ))
            widget_item.setData(Qt.UserRole, item)
            widget_item.setFlags(widget_item.flags() | Qt.ItemIsUserCheckable)
            widget_item.setCheckState(Qt.Unchecked)
            if item.notes:
                widget_item.setToolTip("\n".join(item.notes))
            self._suggestions_list.addItem(widget_item)
        self.set_status("；".join(suggestion_set.summary_lines()) or "")

    def checked_suggestion_ids(self) -> List[str]:
        ids: List[str] = []
        for row in range(self._suggestions_list.count()):
            item = self._suggestions_list.item(row)
            if item.checkState() == Qt.Checked:
                suggestion = item.data(Qt.UserRole)
                if suggestion is not None:
                    ids.append(suggestion.suggestion_id)
        return ids

    def adopt_selected(self) -> Optional[AdoptionOutcome]:
        if self._assistant is None:
            return None
        ids = self.checked_suggestion_ids()
        if not ids:
            self.set_status("请先勾选要采纳的建议。")
            return None
        outcome = self._assistant.adopt(ids)
        self._last_adoption = outcome
        for suggestion_id in outcome.summary_candidates:
            self.summary_candidate.emit(outcome.summary_candidates[suggestion_id])
        if outcome.buffer_updates:
            # 采纳结果同步给宿主编辑器（应用内可达；服务层仍只写缓冲）
            self.buffers_changed.emit(dict(self._assistant.current_texts()))
        self.set_status("；".join(outcome.summary_lines()))
        return outcome

    def ignore_selected(self) -> List[str]:
        if self._assistant is None:
            return []
        ids = self.checked_suggestion_ids()
        for suggestion_id in ids:
            self._assistant.ignore(suggestion_id)
        self.set_status("已忽略 {0} 条建议（不写入正文）。".format(len(ids)))
        return ids

    def undo_last(self) -> bool:
        if self._assistant is None or self._last_adoption is None:
            self.set_status("没有可撤销的采纳记录。")
            return False
        done, _restored, detail = self._assistant.undo(self._last_adoption)
        if done:
            # 撤销同样回写到编辑器（宿主侧同样是一个撤销步）
            self.buffers_changed.emit(dict(self._assistant.current_texts()))
        self.set_status(detail)
        return done

    # --- 增强 ---

    def enhance(self, purpose: str = PURPOSE_REVISION_SUMMARY) -> Optional[EnhancementResult]:
        if self._assistant is None:
            return None
        result = self._assistant.enhance(purpose)
        self.set_status("；".join(result.summary_lines()))
        for item in result.enhanced:
            if purpose == PURPOSE_REVISION_SUMMARY:
                self.summary_candidate.emit(item.text)
        return result

    # --- 差异预览/状态 ---

    def _update_diff_preview(self) -> None:
        suggestion = self._current_suggestion()
        if suggestion is None:
            hit = self.selected_hit()
            if hit is not None and self._assistant is not None:
                self._diff_view.setPlainText(
                    "{0}\n\n{1}".format(self._assistant.citation_text(hit), hit.text)
                )
            return
        self._diff_view.setPlainText(self._assistant.preview_diff([suggestion], [suggestion.suggestion_id]))

    def _current_suggestion(self) -> Optional[Suggestion]:
        item = self._suggestions_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def set_status(self, text: str) -> None:
        self.status_message.emit(text or "")

    @property
    def last_adoption(self) -> Optional[AdoptionOutcome]:
        return self._last_adoption