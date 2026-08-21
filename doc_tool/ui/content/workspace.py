# -*- coding: utf-8 -*-
"""内容工作区协调器：把章节树、编辑器、底部面板交给主窗口摆放。

不把树与面板打包进同一父容器，而是暴露命名子容器（``tree_host`` /
``tabs_host`` / ``panels_host``），由主窗口放入左侧 Dock / 中央区 / 底部
面板。索引在后台线程构建（可取消），完成后填充章节树并接线各面板。
写操作（保存/替换/重命名）后经回调刷新索引并请求校验管线。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.issues import (
    IssueRecord,
    issues_from_lint,
    issues_from_pipeline,
    issues_from_validation_report,
)
from doc_tool.application.content.lint import ContentLinter, TermStore
from doc_tool.application.content.quality_rules import QualityRulesConfig
from doc_tool.application.content.refactor import RefactorService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.replace import ReplaceService
from doc_tool.application.content.search import SearchService
from doc_tool.application.content.autosave import AutoSaveStore
from doc_tool.application.content.changes import ChangeItem, build_change_items
from doc_tool.application.content.snapshot import (
    ContentSnapshot,
    overlay_rename_status,
)
from doc_tool.application.content.tree import build_tree
from doc_tool.application.content.vcs_changes import (
    ChangeDetectionService,
    PullResult,
    commit_all,
    pull_changes,
    rollback_all,
)
from doc_tool.application.content.unsaved import (
    UnsavedChoice,
    UnsavedResolver,
)
from doc_tool.application.content.workspace_state import (
    SessionState,
    WorkspaceStateStore,
)
from doc_tool.application.content.writer import (
    OP_CREATE,
    OP_DELETE,
    OP_RENAME,
    ContentWriter,
)
from doc_tool.domain.content_index import ContentIndex

from doc_tool.ui.content.changes_panel import ChangesPanel
from doc_tool.ui.content.lint_panel import LintPanel
from doc_tool.ui.content.image_assets_panel import ImageAssetsPanel
from doc_tool.ui.content.issues_panel import IssuesPanel
from doc_tool.ui.content.refactor_panel import RefactorPanel
from doc_tool.ui.content.replace_panel import ReplacePanel
from doc_tool.ui.content.search_panel import SearchPanel
from doc_tool.ui.content.tabs_host import TabsHost
from doc_tool.ui.content.tree_panel import ChapterTree
from doc_tool.ui.content.unsaved_prompt import confirm_unsaved_dialog


def build_content_context(
    content_root: Path,
    assets_root: Optional[Path] = None,
    cancel_token=None,
) -> ContentIndex:
    """后台任务：构建索引 + 引用扫描（供 TaskRunner 执行）。"""
    service = ContentIndexService(content_root)
    index = service.build(cancel_token=cancel_token)
    ReferenceScanner(index, assets_root=assets_root).scan_all()
    return index


class ContentWorkspace(QWidget):
    """内容工作区协调器。

    暴露子容器：``tree_host`` / ``tabs_host`` / ``panels_host``。

    ``on_status(message)``：向主窗口状态栏推送构建进度。
    ``on_open_file(rel_path)``：从树/结果打开文件时（主窗口可据此同步）。
    ``on_request_validate()``：替换/重命名写回后请求跑校验管线。
    ``on_index_ready()``：索引构建完成后回调（主窗口可启用菜单）。
    ``unsaved_resolver``：未保存确认决策函数（默认弹对话框；测试注入桩）。
    ``restore_drafts_choice``：崩溃草稿恢复决策（``list[str] -> bool``；
      默认弹「恢复/忽略」，测试注入桩）。
    """

    def __init__(
        self,
        content_root: Path,
        *,
        project_root: Optional[Path] = None,
        state_dir: Path,
        assets_root: Optional[Path] = None,
        writable: bool = True,
        on_status: Optional[Callable[[str], None]] = None,
        on_open_file: Optional[Callable[[str], None]] = None,
        on_request_validate: Optional[Callable[[], None]] = None,
        on_index_ready: Optional[Callable[[], None]] = None,
        unsaved_resolver: Optional[UnsavedResolver] = None,
        restore_drafts_choice=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._content_root = Path(content_root).resolve()
        self._state_dir = Path(state_dir).resolve()
        if project_root is None:
            project_root = self._content_root.parent
        self._project_root = Path(project_root).resolve()
        # 窗口级变更检测器：Git > SVN > 本地快照（Project Context 隔离）。
        self._vcs = ChangeDetectionService(
            self._project_root, self._content_root
        )
        self._change_source = "local"
        self._change_source_note = ""
        self._assets_root = Path(assets_root) if assets_root else None
        self._writable = writable
        self._on_status = on_status
        self._on_open_file = on_open_file
        self._on_request_validate = on_request_validate
        self._on_index_ready = on_index_ready
        self._closing = False
        self._unsaved_resolver = unsaved_resolver or confirm_unsaved_dialog
        self._restore_drafts_choice = (
            restore_drafts_choice or self._default_restore_drafts_choice
        )
        self._pending_session: Optional[SessionState] = None
        self._pipeline_issues: List[IssueRecord] = []
        self._validation_issues: List[IssueRecord] = []
        self._lint_issues: List[IssueRecord] = []

        self._index: Optional[ContentIndex] = None
        self._index_service = ContentIndexService(self._content_root)
        self._writer = ContentWriter(
            self._content_root, self._state_dir, assets_root=self._assets_root
        )
        # VCS 管理下的项目不生成 .md.bak（版本控制已提供恢复能力），
        # 避免 .bak 污染 git/svn 工作树；本地项目保持原备份/回滚行为。
        self._vcs_managed = False
        try:
            self._vcs_managed = self._vcs.detect().source in ("git", "svn")
        except Exception:  # noqa: BLE001  # 检测失败不阻断打开
            self._vcs_managed = False
        self._writer.set_backup_enabled(not self._vcs_managed)
        self._term_store = TermStore(self._state_dir)
        self._autosave = AutoSaveStore(self._state_dir)
        self._session_store = WorkspaceStateStore(self._state_dir)

        # 内容快照基线：首次打开打基线（此后徽标=相对基线的所有真实变动，含外部编辑）。
        self._snapshot = ContentSnapshot(self._state_dir)
        self._snapshot.load()
        if not self._snapshot.entries:
            self._snapshot.take(
                self._content_root,
                [rel for rel, _ in self._index_service.discover_files()],
            )
            self._snapshot.save()
        else:
            # 旧项目升级：元数据已有但基线内容副本缺失时补拷（供改动面板 diff）。
            self._snapshot.ensure_baseline_content(
                self._content_root,
                [rel for rel, _ in self._index_service.discover_files()],
            )

        from doc_tool.ui.task_bridge import TaskRunner

        self._runner = TaskRunner()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(80)
        self._poll_timer.timeout.connect(self._poll_index)

        # 命名子容器
        self.tree_host = QWidget(self)
        self._tree = ChapterTree(
            on_open=self._on_tree_open,
            on_refresh=self._rebuild_index,
            on_create_file=self._on_create_file,
            on_delete_file=self._on_delete_file,
            on_rename_file=self._on_rename_file,
            on_renumber_dir=self._on_renumber_dir,
            on_move_node=self._on_move_node,
            on_clear_markers=self._on_clear_markers,
            on_open_external=self._on_open_external,
            on_open_directory=self._on_open_directory,
            content_root=self._content_root,
            writable=self._writable,
        )
        tree_layout = QVBoxLayout(self.tree_host)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(self._tree)

        self.tabs_host = TabsHost(
            self._writer,
            on_saved=self._on_file_saved,
            on_current_changed=self._on_current_file_changed,
            assets_root=self._assets_root,
            writable=self._writable,
            autosave=self._autosave,
        )

        self.panels_host = QWidget(self)
        self._panels = QTabWidget(self.panels_host)
        panels_layout = QVBoxLayout(self.panels_host)
        panels_layout.setContentsMargins(0, 0, 0, 0)
        panels_layout.addWidget(self._panels)
        # 索引就绪前的占位
        self._placeholder_tabs: Dict[str, QWidget] = {}
        for name in ("搜索", "替换", "重命名/重编号", "检查", "问题", "图片", "改动"):
            placeholder = QWidget(self.panels_host)
            self._panels.addTab(placeholder, name)
            self._placeholder_tabs[name] = placeholder

        self._start_index_build()

    # --- 索引构建 ---

    def _start_index_build(self) -> None:
        from doc_tool.ui.task_bridge import TaskSpec

        if self._on_status is not None:
            self._on_status("正在构建内容索引…")
        self._runner.start(
            TaskSpec(
                name="content-index",
                target=build_content_context,
                kwargs={
                    "content_root": self._content_root,
                    "assets_root": self._assets_root,
                },
            ),
            on_done=self._on_index_done,
        )
        self._poll_timer.start()

    def shutdown(self) -> None:
        """项目切换/关闭时停止后台索引任务与轮询。

        旧工作区被 deleteLater 时若索引任务仍在运行，其迟到回调会重建
        控件并误把新项目标记为索引就绪；此方法停表、取消任务并置关闭
        标志，保证旧回调在新工作区就绪前不会生效。
        """
        self._closing = True
        self._poll_timer.stop()
        if self._runner.is_running:
            self._runner.cancel()

    def _poll_index(self) -> None:
        if self._closing:
            return
        self._runner.poll()
        if not self._runner.is_running:
            self._poll_timer.stop()

    def _on_index_done(self, result) -> None:
        if self._closing:
            # 项目切换/关闭后迟到的旧索引回调：不得重建控件或标记新项目就绪。
            return
        if result is None:
            if self._on_status is not None:
                self._on_status("内容索引构建失败或已取消")
            return
        self._index = result
        self._populate_panels()
        if self._on_status is not None:
            self._on_status(
                "内容索引就绪：{0} 个文件".format(len(self._index.files))
            )
        try:
            # 会话/草稿恢复失败不应阻断索引就绪，但必须提示用户，不能静默跳过。
            self._restore_drafts_and_session()
        except Exception as exc:  # noqa: BLE001
            if self._on_status is not None:
                self._on_status("会话/草稿恢复失败：{0}".format(str(exc)[:120]))
        if self._on_index_ready is not None:
            self._on_index_ready()

    def _populate_panels(self) -> None:
        assert self._index is not None
        items = build_tree(self._index.all_files())
        self._tree.set_items(items)
        self._apply_status_map()

        search = SearchPanel(
            SearchService(self._index),
            on_open=self._open_and_locate,
            # 通用单项目不展示类型筛选；仅旧版多类型布局保留兼容过滤（任务 6.2）。
            show_type_filter=len(self._index.document_types) > 1,
        )
        self._panels.addTab(search, "搜索")
        self._remove_placeholder("搜索")

        replace = ReplacePanel(
            ReplaceService(self._index),
            self._writer,
            on_applied=self._after_write,
            writable=self._writable,
            # 通用单项目不展示类型筛选；仅旧版多类型布局保留兼容过滤（任务 6.3）。
            show_type_filter=len(self._index.document_types) > 1,
        )
        self._panels.addTab(replace, "替换")
        self._remove_placeholder("替换")

        refactor = RefactorPanel(
            RefactorService(self._index),
            self._writer,
            on_applied=self._after_write,
            on_renamed=self._on_file_renamed,
            on_confirm_dirty=self._confirm_rename_dirty,
            writable=self._writable,
        )
        refactor.set_files(self._index.all_files())
        self._panels.addTab(refactor, "重命名/重编号")
        self._remove_placeholder("重命名/重编号")

        lint = LintPanel(
            ContentLinter(
                self._index,
                QualityRulesConfig(
                    self._state_dir,
                    next(iter(self._index.document_types), "general"),
                ),
            ),
            self._term_store,
            on_open=self._open_and_locate,
            on_issues=self._on_lint_issues,
            writable=self._writable,
        )
        self._panels.addTab(lint, "检查")
        self._remove_placeholder("检查")

        issues = IssuesPanel(
            on_open=self.open_file,
            on_status=self._on_status,
            # 通用单项目 documentType 固定为 general，不作为主要筛选维度（任务 6.3）。
            show_document_type=len(self._index.document_types) > 1,
        )
        self._panels.addTab(issues, "问题")
        self._remove_placeholder("问题")
        self._issues_panel = issues

        images = ImageAssetsPanel(
            self._index,
            assets_root=self._assets_root,
            writer=self._writer,
            on_changed=self._after_write,
            on_open=self._open_and_locate,
            writable=self._writable,
        )
        self._panels.addTab(images, "图片")
        self._remove_placeholder("图片")

        changes = ChangesPanel(
            snapshot=self._snapshot,
            writer=self._writer,
            content_root=self._content_root,
            on_restored=self._after_restore,
            writable=self._writable,
            rollback_all=self._rollback_all_changes,
            on_commit=self._commit_all_changes,
            on_pull=self._pull_changes,
        )
        self._panels.addTab(changes, "改动")
        self._remove_placeholder("改动")
        self._changes_panel = changes
        self._refresh_changes_panel()

        self._search_panel = search
        self._replace_panel = replace
        self._refactor_panel = refactor
        self._lint_panel = lint
        self._image_assets_panel = images

    def _remove_placeholder(self, name: str) -> None:
        placeholder = self._placeholder_tabs.pop(name, None)
        if placeholder is not None:
            index = self._panels.indexOf(placeholder)
            if index >= 0:
                self._panels.removeTab(index)
            placeholder.deleteLater()

    # --- 打开文件 ---

    def open_file(self, rel_path: str, line_no: Optional[int] = None) -> None:
        """打开文件到编辑器并定位到行；文件不在索引中则尝试直接读取。"""
        path = self._writer.resolve(rel_path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            if self._on_status is not None:
                self._on_status("无法读取文件：{0}".format(rel_path))
            return
        self.tabs_host.open_file(rel_path, text, line_no=line_no)
        # 先记录当前文件再定位树节点，避免树选中的延迟事件递归打开同一文件
        self._tree.set_current(rel_path)
        self._tree.select_file(rel_path)
        if self._on_open_file is not None:
            self._on_open_file(rel_path)

    def _on_tree_open(self, rel_path: str) -> None:
        self.open_file(rel_path)

    def _open_and_locate(self, rel_path: str, line_no: int) -> None:
        self.open_file(rel_path, line_no)

    # --- 菜单联动（面板选择） ---

    def focus_search(self) -> None:
        self._select_panel("搜索")
        panel = getattr(self, "_search_panel", None)
        if panel is not None:
            panel.focus_query()

    def focus_in_editor_find(self) -> None:
        """编辑器聚焦时的 Ctrl+F：聚焦当前文件的文件内查找条。"""
        editor = self.tabs_host.current_editor()
        if editor is not None:
            editor.focus_find()

    def show_replace(self) -> None:
        self._select_panel("替换")

    def show_refactor(self, target: Optional[str] = None) -> None:
        self._select_panel("重命名/重编号")
        panel = getattr(self, "_refactor_panel", None)
        if panel is not None and target:
            panel.set_target(target)

    def show_issues(self) -> None:
        """把「问题」面板推到前台（任务失败后由主窗口调用）。"""
        self._select_panel("问题")

    def run_lint(self) -> None:
        self._select_panel("检查")
        panel = getattr(self, "_lint_panel", None)
        if panel is not None:
            panel.run_check()

    def _on_lint_issues(self, issues) -> None:
        document_type = ""
        if self._index is not None and len(self._index.document_types) == 1:
            document_type = next(iter(self._index.document_types))
        self._lint_issues = issues_from_lint(issues, document_type)
        self._render_issues()

    def refresh_issues(
        self,
        *,
        pipeline_events=None,
        document_type: str = "",
        validation_report: Optional[Path] = None,
    ) -> None:
        """任务终态刷新管线/校验来源；lint 集合保持并入。"""
        if pipeline_events is not None:
            self._pipeline_issues = issues_from_pipeline(
                pipeline_events, document_type or "general"
            )
        if validation_report is not None:
            self._validation_issues = issues_from_validation_report(
                validation_report, document_type or "general"
            )
        self._render_issues()

    def _render_issues(self) -> None:
        panel = getattr(self, "_issues_panel", None)
        if panel is not None:
            panel.set_issues(
                self._pipeline_issues + self._validation_issues + self._lint_issues
            )

    def open_current_external(self) -> None:
        editor = self.tabs_host.current_editor()
        if editor is not None:
            editor.open_external()

    def current_file(self) -> Optional[str]:
        return self.tabs_host.current_rel_path()

    def _select_panel(self, name: str) -> None:
        for index in range(self._panels.count()):
            if self._panels.tabText(index) == name:
                self._panels.setCurrentIndex(index)
                return

    # --- 写后联动 ---

    def _status_map(self) -> Dict[str, str]:
        """Git > SVN > 本地快照 → 徽标状态（需索引已就绪）。

        Git/SVN 报告由窗口级检测器按 project_root 过滤后映射到内容路径；
        本地兜底沿用快照 diff。两种来源都会叠加改动清单 rename 语义，
        保证改动面板的恢复能力与展示一致。
        """
        self._writer.manifest.load()
        report = self._vcs.detect()
        if report.source in ("git", "svn"):
            status = self._vcs.status_map(
                report, self._index.all_files()
            )
            self._change_source = report.source
            self._change_source_note = ""
            self._vcs_managed = True
        else:
            status = self._snapshot.diff(
                self._content_root, self._index.all_files()
            )
            self._change_source = "local"
            # 为什么没用版本控制判断（未纳入 git / git 不可用…）：面板要说明。
            self._change_source_note = report.error or ""
            self._vcs_managed = False
        self._writer.set_backup_enabled(not self._vcs_managed)
        status = overlay_rename_status(status, self._writer.manifest.entries)
        # 资源不属于 content 快照，但软删除仍需出现在改动面板，供单项恢复。
        for entry in self._writer.manifest.entries:
            if entry.operation == OP_DELETE and entry.rel_path.startswith("assets/"):
                status[entry.rel_path] = "deleted"
        return status

    def _apply_status_map(self) -> None:
        """从内容快照对比当前真实变动并应用到章节树徽标与改动面板。"""
        if self._index is None:
            return
        status = self._status_map()
        self._tree.set_status_map(status)
        self._refresh_changes_panel(status)

    # --- 改动面板 ---

    def _change_items(self, status: Dict[str, str]) -> List[ChangeItem]:
        """快照状态 + 改动清单 rename/delete 映射 → 改动项列表。"""
        entries = self._writer.manifest.entries
        rename_map = {
            e.rel_path: e.original_path
            for e in entries
            if e.operation == OP_RENAME and e.original_path
        }
        trash_map = {
            e.rel_path: e.trash_path
            for e in entries
            if e.operation == OP_DELETE and e.trash_path
        }
        non_restorable = (
            ["project.yml"] if self._change_source in ("git", "svn") else []
        )
        return build_change_items(
            status,
            rename_map=rename_map,
            trash_map=trash_map,
            non_restorable=non_restorable,
        )

    def change_source(self) -> str:
        """当前变更检测来源（git/svn/local），供面板标注。"""
        return self._change_source

    def changed_chapters(self):
        """章节级变更列表（Git/SVN 来源），为后续影响分析预留接口。

        本地兜底（无版本控制）返回空列表——本地快照语义与版本控制变化
        不同，章节级变化仍由改动面板/树徽标表达。
        """
        if self._index is None:
            return []
        report = self._vcs.detect()
        if report.source not in ("git", "svn"):
            return []
        return self._vcs.chapters(report, self._index.all_files())

    def _rollback_all_changes(self) -> List[str]:
        """改动面板「回滚全部」：VCS 模式用版本控制恢复，否则本地清单回滚。

        VCS 模式下（git/svn）不再依赖 .bak：恢复被跟踪文件到 HEAD/BASE，
        仅删除本会话由工具创建（清单 OP_CREATE）的未跟踪文件，其它未跟踪
        文件保留并提示，避免误删用户手动新建的内容。
        """
        report = self._vcs.detect()
        if report.source not in ("git", "svn"):
            return self._writer.rollback()
        # 未跟踪文件不在此处删除：由下方按改动清单判定（只删本会话创建的）。
        failures = rollback_all(report, delete_untracked=False)
        notices: List[str] = []
        # 未跟踪新增文件：仅删除本会话工具创建的（清单 OP_CREATE），
        # 其它保留并提示（notices，不算失败），避免误删用户手动新建的文件。
        self._writer.manifest.load()
        created_abs = set()
        for entry in self._writer.manifest.entries:
            if entry.operation != OP_CREATE:
                continue
            try:
                created_abs.add(str(self._writer.resolve(entry.rel_path).resolve()))
            except Exception:  # noqa: BLE001
                continue
        for item in report.files:
            if not item.untracked:
                continue
            if item.abs_path and str(Path(item.abs_path).resolve()) in created_abs:
                try:
                    Path(item.abs_path).unlink(missing_ok=True)
                except OSError as exc:
                    failures.append("{0}：{1}".format(item.path, exc))
            else:
                notices.append(
                    "未跟踪文件（非本会话创建）已保留：{0}".format(item.path)
                )
        self._vcs.invalidate_cache()
        if not failures:
            # 版本控制已整体恢复：清空会话改动清单，避免陈旧条目影响徽标/面板。
            try:
                self._writer.manifest.load()
                self._writer.manifest.clear()
            except OSError:
                pass
        return failures + notices

    def _commit_all_changes(self, message: str) -> List[str]:
        """改动面板「提交改动」：VCS 模式提交项目内全部未提交改动。

        提交成功后清空会话改动清单（条目已入库，避免陈旧条目影响徽标/面板），
        并失效仓库缓存，使刷新立即反映提交后的干净状态。git > svn。
        """
        report = self._vcs.detect()
        if report.source not in ("git", "svn"):
            return ["当前项目不在版本控制内，无法提交"]
        failures = commit_all(report, message)
        if not failures:
            try:
                self._writer.manifest.load()
                self._writer.manifest.clear()
            except OSError:
                pass
        self._vcs.invalidate_cache()
        return failures

    def _pull_changes(self) -> PullResult:
        """改动面板「拉取更新」：git pull / svn update，返回带统计的结果。

        结果含成功摘要（更新了 N 个文件 / 已是最新版本）、带入文件清单与
        冲突文件；失败时含命令错误文本。缓存失效由本方法完成，界面刷新由
        面板经 ``on_restored`` 触发。
        """
        report = self._vcs.detect()
        if report.source not in ("git", "svn"):
            return PullResult(
                ok=False, summary="", error="当前项目不在版本控制内，无法拉取"
            )
        result = pull_changes(report)
        self._vcs.invalidate_cache()
        return result

    def _refresh_changes_panel(self, status: Optional[Dict[str, str]] = None) -> None:
        """刷新改动面板（status 缺省时重新推导）。"""
        panel = getattr(self, "_changes_panel", None)
        if panel is None or self._index is None:
            return
        if status is None:
            status = self._status_map()
        panel.set_source(self._change_source, self._change_source_note)
        panel.set_items(self._change_items(status))

    def _after_restore(self) -> None:
        """改动面板恢复单个文件后：重建索引与树并刷新徽标/面板。"""
        self._vcs.invalidate_cache()
        if self._index is None:
            return
        self._index_service.refresh(self._index)
        ReferenceScanner(self._index, assets_root=self._assets_root).scan_all()
        items = build_tree(self._index.all_files())
        self._tree.set_items(items)
        self._apply_status_map()
        panel = getattr(self, "_image_assets_panel", None)
        if panel is not None:
            panel.set_index(self._index)

    def _rebuild_index(self) -> None:
        """手动刷新：非破坏性重扫索引 + 重扫引用 + 重绘树。"""
        if self._index is None:
            self._start_index_build()
            return
        try:
            self._index_service.refresh(self._index)
            ReferenceScanner(self._index, assets_root=self._assets_root).scan_all()
            items = build_tree(self._index.all_files())
            self._tree.set_items(items)
            self._apply_status_map()
            if hasattr(self, "_refactor_panel"):
                self._refactor_panel.set_files(self._index.all_files())
            if self._on_status is not None:
                self._on_status(
                    "索引已刷新：{0} 个文件".format(len(self._index.files))
                )
        except Exception as exc:  # noqa: BLE001
            if self._on_status is not None:
                self._on_status("刷新索引失败：{0}".format(exc))

    def _on_file_saved(self, rel_path: str) -> None:
        """编辑器保存后失效并重建该文件索引，增量刷新徽标（不重建树模型）。"""
        self._vcs.invalidate_cache()
        if self._index is None:
            return
        self._index.invalidate(rel_path)
        self._index_service.rebuild_file(self._index, rel_path)
        self._tree.set_status(self._status_map())

    def _on_current_file_changed(self, rel_path: Optional[str]) -> None:
        if rel_path is not None and self._on_open_file is not None:
            self._on_open_file(rel_path)

    # --- 新增/删除/清除标记 ---

    def _on_create_file(self, dir_rel_path: str) -> None:
        """在指定目录自动编号新建章节文件并定位到编辑器。"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from doc_tool.application.content.tree import next_chapter_rel_path

        if self._index is None:
            return
        title, ok = QInputDialog.getText(self, "新增章节/文件", "章节标题：")
        if not ok or not title.strip():
            return
        title = title.strip()
        rel_path = next_chapter_rel_path(
            dir_rel_path, self._index.all_files(), title
        )
        result = self._writer.create_file(rel_path, "# {0}\n".format(title))
        if not result.written:
            QMessageBox.warning(
                self, "新增失败", result.error or "写入失败"
            )
            return
        self._vcs.invalidate_cache()
        self._index_service.rebuild_file(self._index, rel_path)
        items = build_tree(self._index.all_files())
        self._tree.set_items(items)
        self._apply_status_map()
        self.open_file(rel_path)

    def _on_delete_file(self, rel_path: str) -> None:
        """确认后把文件移入回收站并刷新树与索引。"""
        from PySide6.QtWidgets import QMessageBox

        if self._index is None:
            return
        # 目标文件有未保存编辑时先确认（放弃/取消），避免静默丢弃。
        if self._editor_is_dirty(rel_path):
            choice = self._unsaved_resolver([rel_path], "delete")
            if choice != UnsavedChoice.DISCARD:
                return  # 取消 → 中止删除
        else:
            answer = QMessageBox.question(
                self,
                "删除文件",
                "将删除并移入回收站（可回滚）：\n{0}\n\n确认？".format(rel_path),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        result = self._writer.delete_file(rel_path)
        if not result.written:
            QMessageBox.warning(
                self, "删除失败", result.error or "删除失败"
            )
            return
        self._vcs.invalidate_cache()
        # 文件已入回收站：清除其草稿（草稿无意义）。
        self._autosave.clear(rel_path)
        self.tabs_host.close_file(rel_path)
        if self._maybe_renumber_after_delete(rel_path):
            # 级联重编号改变了多个文件路径 → 全量刷新并自动校验
            self._after_write()
        else:
            self._index_service.rebuild_file(self._index, rel_path)
            items = build_tree(self._index.all_files())
            self._tree.set_items(items)
            self._apply_status_map()
        # 删除/重编号后同步评审意见关联状态（关联章节已变更标注）。
        self._mark_review_association()

    def _maybe_renumber_after_delete(self, rel_path: str) -> bool:
        """删除中间编号后询问并执行后续同级重编号；返回是否执行了重编号。

        对每个重编号目标：若其旧路径有未保存编辑，先按「先保存/放弃/取消」
        确认（取消中止整个重编号）。重命名成功后关闭旧路径标签并清除其草稿，
        避免旧路径标签后续保存时重建已改名的文件；重命名失败逐个汇总提示，
        不再静默忽略。
        """
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.content.refactor import RefactorService
        from doc_tool.application.content.tree import renumber_plan_after_delete

        if self._index is None:
            return False
        renames = renumber_plan_after_delete(rel_path, self._index.all_files())
        if not renames:
            return False
        preview = "\n".join(
            "  {0} → {1}".format(old, new) for old, new in renames
        )
        answer = QMessageBox.question(
            self,
            "重新编号后续章节",
            "已删除中间编号章节。检测到 {0} 个后续同级章节需重新编号：\n{1}\n\n"
            "将自动重命名并联动更新引用与标题。确认？".format(len(renames), preview),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        # 未保存保护：目标旧路径有未保存编辑时先确认，避免重编号静默丢弃编辑。
        for old, _new in renames:
            if self._editor_is_dirty(old):
                choice = self._unsaved_resolver([old], "rename")
                if choice == UnsavedChoice.CANCEL:
                    return False  # 取消 → 中止整个重编号
                if choice == UnsavedChoice.SAVE:
                    editor = self.tabs_host.editor_for(old)
                    if editor is not None and not editor.save():
                        QMessageBox.warning(
                            self, "重编号中止", "保存失败，已中止重编号：{0}".format(old)
                        )
                        return False
        service = RefactorService(self._index)
        # 批量计划 + staging 应用：让位链（同名标题 + 连续编号）下逐条
        # apply 会因索引尚未刷新而误判目标占用、抛 ValueError 且前面的
        # 重命名已实际应用；批量计划一次完成冲突校验，冲突时整体中止，
        # 不产生半迁移状态（与 _on_renumber_dir 一致）。
        plan = service.compute_batch_rename_plan(renames)
        if plan is None:
            QMessageBox.warning(
                self, "重编号失败", "目标文件不在内容索引中，请刷新后重试"
            )
            return True
        if plan.conflicts:
            QMessageBox.warning(
                self, "重编号冲突", "；".join(plan.conflicts)
            )
            return True
        try:
            results = service.apply_rename_plan(plan, self._writer)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, "重编号失败", "已中止并尝试回滚：{0}".format(exc)
            )
            return True
        if not all(r.written for r in results):
            QMessageBox.warning(
                self, "重编号失败", "部分写回失败，请查看备份与改动清单"
            )
            return True
        # 旧路径已改名：关闭其标签并清除草稿，避免旧路径标签保存时
        # 重建已改名的文件、或崩溃恢复复活旧路径的废弃内容。
        for old, _new in renames:
            self.tabs_host.close_file(old)
            self._autosave.clear(old)
        self._mark_review_association(dict(renames))
        return True

    def _on_renumber_dir(self, dir_rel_path: str) -> None:
        """一键把目录下已编号子节点重排为连续编号（预览确认后联动应用）。

        手动新增文件导致编号断档（如 4.7.1..4.7.24 后新增 4.7.28/29/30）时，
        右键章节目录选择本操作：预览全部 ``旧 → 新``，确认后经 RefactorService
        重命名并联动更新引用与标题。
        """
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.content.refactor import RefactorService
        from doc_tool.application.content.tree import (
            ChapterMoveError,
            renumber_plan,
        )

        if not self._writable:
            QMessageBox.information(self, "无法重编号", "当前项目为只读模式")
            return
        if self._index is None:
            QMessageBox.information(self, "无法重编号", "内容索引尚未就绪")
            return
        try:
            renames = renumber_plan(dir_rel_path, self._index.all_files())
        except ChapterMoveError as exc:
            QMessageBox.warning(self, "无法重编号", str(exc))
            return
        if not renames:
            QMessageBox.information(
                self, "重新编号", "该目录编号已连续，无需调整。"
            )
            return
        preview = "\n".join(
            "  {0} → {1}".format(old, new) for old, new in renames
        )
        answer = QMessageBox.question(
            self,
            "重新编号本目录",
            "将按自然顺序把 {0} 个已编号子节点重排为连续编号：\n{1}\n\n"
            "将自动重命名并联动更新引用与标题。确认？".format(
                len(renames), preview
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # 未保存保护：目标旧路径有未保存编辑时先确认，避免重编号静默丢弃编辑。
        for old, _new in renames:
            if self._editor_is_dirty(old):
                choice = self._unsaved_resolver([old], "rename")
                if choice == UnsavedChoice.CANCEL:
                    return  # 取消 → 中止整个重编号
                if choice == UnsavedChoice.SAVE:
                    editor = self.tabs_host.editor_for(old)
                    if editor is not None and not editor.save():
                        QMessageBox.warning(
                            self, "重编号中止", "保存失败，已中止重编号：{0}".format(old)
                        )
                        return
        service = RefactorService(self._index)
        plan = service.compute_batch_rename_plan(renames)
        if plan is None:
            QMessageBox.warning(
                self, "重编号失败", "目标文件不在内容索引中，请刷新后重试"
            )
            return
        if plan.conflicts:
            QMessageBox.warning(self, "重编号冲突", "\n".join(plan.conflicts))
            return
        results = service.apply_rename_plan(plan, self._writer)
        if not all(r.written for r in results):
            QMessageBox.warning(
                self, "重编号失败", "部分写回失败，请查看备份与改动清单"
            )
            return
        # 旧路径已改名：关闭其标签并清除草稿，避免旧路径标签保存时
        # 重建已改名的文件、或崩溃恢复复活旧路径的废弃内容。
        for old, _new in renames:
            self.tabs_host.close_file(old)
            self._autosave.clear(old)
        self._mark_review_association({old: new for old, new in renames})
        self._after_write()

    def _on_rename_file(self, rel_path: str) -> None:
        """内联重命名文件并联动更新引用（复用 RefactorService）。"""
        from pathlib import Path

        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from doc_tool.application.content.refactor import RefactorService

        if self._index is None:
            return
        # 目标文件有未保存编辑时先确认（先保存/放弃/取消），避免静默丢弃。
        if self._editor_is_dirty(rel_path):
            choice = self._unsaved_resolver([rel_path], "rename")
            if choice == UnsavedChoice.CANCEL:
                return  # 取消 → 中止重命名
            if choice == UnsavedChoice.SAVE:
                # 先把当前编辑保存到原路径，再执行重命名与引用联动。
                editor = self.tabs_host.editor_for(rel_path)
                if editor is not None and not editor.save():
                    return  # 保存失败 → 中止重命名，避免内容丢失
        new_name, ok = QInputDialog.getText(
            self,
            "重命名文件",
            "新文件名：",
            text=Path(rel_path).name,
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == Path(rel_path).name:
            return  # 未修改，无操作
        service = RefactorService(self._index)
        plan = service.compute_rename_plan(rel_path, new_name)
        if plan is None:
            QMessageBox.warning(
                self, "重命名失败", "目标文件不在内容索引中"
            )
            return
        if plan.new_rel_path in self._index.all_files():
            QMessageBox.warning(
                self,
                "重命名失败",
                "目标文件已存在：{0}".format(plan.new_rel_path),
            )
            return
        if plan.total > 0:
            answer = QMessageBox.question(
                self,
                "确认重命名",
                "将同步更新 {0} 处引用（{1} 个文件），并重命名文件为：\n{2}\n\n确认？".format(
                    plan.total, len(plan.affected_files), plan.new_rel_path
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        results = service.apply_rename_plan(plan, self._writer)
        if not all(r.written for r in results):
            QMessageBox.warning(
                self, "重命名失败", "部分写回失败，请查看备份"
            )
            return
        # 重命名后同步评审意见关联（旧路径意见更新到新路径并标注已变更）。
        self._mark_review_association({rel_path: plan.new_rel_path})
        self.tabs_host.close_file(rel_path)
        # 旧路径已改名（或被放弃的未保存编辑不再存在）：清除其草稿，
        # 避免下次打开在崩溃恢复提示中复活旧路径的废弃内容。
        self._autosave.clear(rel_path)
        self._after_write()

    def _on_move_node(
        self, source_node: str, target_parent: str, before_node: Optional[str]
    ) -> bool:
        """章节树拖放：生成 dry-run、确认、事务应用并恢复定位状态。"""
        from PySide6.QtWidgets import QMessageBox

        from doc_tool.application.content.refactor import RefactorService
        from doc_tool.application.content.tree import (
            ChapterMoveError,
            chapter_move_renumber_plan,
        )

        if not self._writable:
            QMessageBox.information(self, "无法移动", "当前项目为只读模式")
            return False
        if self._index is None:
            QMessageBox.information(self, "无法移动", "内容索引尚未就绪")
            return False
        try:
            renames = chapter_move_renumber_plan(
                source_node,
                target_parent,
                self._index.all_files(),
                before_node=before_node,
            )
        except ChapterMoveError as exc:
            QMessageBox.warning(self, "无法移动", str(exc))
            return False
        if not renames:
            if self._on_status is not None:
                self._on_status("拖放位置未产生编号或路径变化")
            return False
        plan = RefactorService(self._index).compute_batch_rename_plan(renames)
        if plan is None:
            QMessageBox.warning(self, "无法移动", "移动源已不在内容索引中，请刷新后重试")
            return False
        if plan.conflicts:
            QMessageBox.warning(
                self, "移动计划冲突", "\n".join(plan.conflicts)
            )
            return False
        preview_rows = ["  {0} → {1}".format(old, new) for old, new in plan.renames]
        warning_text = "\n警告：" + "；".join(plan.warnings) if plan.warnings else ""
        answer = QMessageBox.question(
            self,
            "确认章节移动",
            "将移动/重编号 {0} 个文件，更新 {1} 处引用（共影响 {2} 个文件）。{3}\n\n{4}\n\n确认应用？".format(
                len(plan.renames),
                plan.total,
                len(plan.affected_files),
                warning_text,
                "\n".join(preview_rows[:30]),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        dirty = [old for old, _new in plan.renames if self._editor_is_dirty(old)]
        if dirty:
            choice = self._unsaved_resolver(dirty, "rename")
            if choice == UnsavedChoice.CANCEL:
                return False
            if choice == UnsavedChoice.SAVE:
                for old in dirty:
                    editor = self.tabs_host.editor_for(old)
                    if editor is not None and not editor.save():
                        return False

        expanded = self._tree.expanded_node_ids()
        current = self.tabs_host.current_rel_path()
        relocation = dict(plan.renames)
        try:
            results = RefactorService(self._index).apply_rename_plan(plan, self._writer)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "章节移动失败", "已回滚本次操作：{0}".format(exc))
            return False
        if not all(result.written for result in results):
            QMessageBox.warning(self, "章节移动失败", "写入未完成，已尝试回滚")
            return False
        for old, _new in plan.renames:
            self.tabs_host.close_file(old)
            self._autosave.clear(old)
        self._after_write()
        self._tree.restore_expanded([relocation.get(node, node) for node in expanded])
        if current:
            new_current = relocation.get(current, current)
            if new_current in self._index.all_files():
                self.open_file(new_current)
                self._tree.select_file(new_current)
        return True

    def _on_clear_markers(self) -> None:
        """重新打基线：清空全部改动徽标（改动内容与回滚能力均保留）。"""
        from PySide6.QtWidgets import QMessageBox

        self._snapshot.load()
        if not self._snapshot.entries:
            return
        answer = QMessageBox.question(
            self,
            "清除标记",
            "将当前内容重新设为基线，全部改动徽标清空？\n（改动内容与回滚能力均保留）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._snapshot.take(
            self._content_root,
            [rel for rel, _ in self._index_service.discover_files()],
        )
        self._snapshot.save()
        self._vcs.invalidate_cache()
        self._apply_status_map()

    def _on_open_external(self, rel_path: str) -> None:
        """用系统默认程序在外部编辑器打开树中某文件。"""
        import os

        from PySide6.QtWidgets import QMessageBox

        target = self._writer.resolve(rel_path)
        if not target.exists():
            QMessageBox.warning(
                self, "无法打开", "文件不存在：{0}".format(rel_path)
            )
            return
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
        except OSError as exc:
            QMessageBox.warning(self, "无法打开", "打开失败：{0}".format(exc))

    def _on_open_directory(self, dir_rel_path: str) -> None:
        """在文件管理器打开树中某目录。"""
        import os

        from PySide6.QtWidgets import QMessageBox

        target = self._writer.resolve(dir_rel_path)
        if not target.is_dir():
            QMessageBox.warning(
                self, "无法打开", "目录不存在：{0}".format(dir_rel_path)
            )
            return
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
        except OSError as exc:
            QMessageBox.warning(self, "无法打开", "打开失败：{0}".format(exc))

    def _after_write(self) -> None:
        """替换/重命名写回后：刷新索引并请求校验管线。"""
        self._vcs.invalidate_cache()
        if self._index is not None:
            self._index_service.refresh(self._index)
            ReferenceScanner(self._index, assets_root=self._assets_root).scan_all()
            items = build_tree(self._index.all_files())
            self._tree.set_items(items)
            self._apply_status_map()
            if hasattr(self, "_refactor_panel"):
                self._refactor_panel.set_files(self._index.all_files())
            panel = getattr(self, "_image_assets_panel", None)
            if panel is not None:
                panel.set_index(self._index)
        # 批量写回直接落盘、绕过编辑器缓冲区：同步已打开标签的磁盘状态，
        # 避免用户基于过期内容保存、静默回退本次批量改动（双向数据丢失）。
        # 干净标签静默重载，脏标签弹确认（与 check_external_change 一致）。
        for rel_path in list(self.tabs_host.open_rel_paths()):
            editor = self.tabs_host.editor_for(rel_path)
            if editor is None:
                continue
            try:
                editor.check_external_change()
            except Exception:  # noqa: BLE001  # 刷新失败不阻断写后联动
                continue
        if self._on_request_validate is not None:
            self._on_request_validate()

    def _mark_review_association(self, renamed: Optional[Dict[str, str]] = None) -> None:
        """删除/重命名文件后同步评审意见的关联状态（保留并标注已变更）。

        spec「意见关联失效文件」：被删除章节的意见标记 association_changed，
        被重命名章节的意见更新 rel_path 并标记。仅在有评审存储时生效，失败
        不阻断文件操作。
        """
        try:
            from doc_tool.application.review.review_store import ReviewStore

            existing = list(self._index.all_files()) if self._index is not None else []
            ReviewStore(self._state_dir).mark_association_changes(existing, renamed)
        except Exception:
            pass

    def _confirm_rename_dirty(self, rel_paths) -> bool:
        """重命名/重编号（底部面板入口）执行前确认受影响旧路径的未保存编辑。

        与章节树入口（``_maybe_renumber_after_delete`` / ``_on_rename_file``）
        同一决策：先保存/放弃/取消；取消中止整个联动。返回 True 表示可继续。
        """
        dirty = [rel for rel in rel_paths if self._editor_is_dirty(rel)]
        if not dirty:
            return True
        choice = self._unsaved_resolver(dirty, "rename")
        if choice == UnsavedChoice.CANCEL:
            return False
        if choice == UnsavedChoice.SAVE:
            for rel in dirty:
                editor = self.tabs_host.editor_for(rel)
                if editor is not None and not editor.save():
                    return False
        return True  # DISCARD → 继续（编辑被放弃，旧标签关闭）

    def _on_file_renamed(self, old_rel_path: str) -> None:
        """重命名成功后关闭旧路径标签并清除其草稿（重命名面板联动）。

        旧路径标签若不关闭，用户在其上 Ctrl+S 会重建已改名的旧路径文件；
        旧路径草稿若不清理，崩溃恢复会在下次打开时复活废弃内容。
        """
        self.tabs_host.close_file(old_rel_path)
        self._autosave.clear(old_rel_path)

    # --- 未保存保护 / 崩溃恢复 / 会话 ---

    def _editor_is_dirty(self, rel_path: str) -> bool:
        """目标文件在编辑器中有未保存编辑。"""
        editor = self.tabs_host.editor_for(rel_path)
        return editor is not None and editor.is_dirty()

    def clear_drafts(self, rel_paths) -> None:
        """清除指定文件的草稿（退出/切换「不保存」时调用）。

        同时停掉对应编辑器的待触发草稿定时器——否则「不保存」后若事件循环
        继续运行（慢关闭/任务取消等），定时器仍会把已放弃的草稿重新写回。
        清除失败时提示，避免下次打开误弹「恢复自草稿」。
        """
        failed = []
        for rel in rel_paths:
            error = self._autosave.clear(rel)
            if error:
                failed.append(error)
            editor = self.tabs_host.editor_for(rel)
            if editor is not None:
                editor.stop_autosave()
        if failed and self._on_status is not None:
            self._on_status(
                "部分草稿清除失败，下次打开可能提示恢复：" + "；".join(failed)
            )

    def session_store(self) -> WorkspaceStateStore:
        return self._session_store

    def collect_session_state(
        self,
        *,
        theme: str,
        dock_visibility: dict,
        dock_state: str,
    ) -> SessionState:
        """收集当前工作区会话快照（标签/当前文件/滚动/预览）。

        Dock 显隐/布局与主题由主窗口提供（主窗口持有 Dock 与主题状态）。
        """
        open_tabs = self.tabs_host.open_rel_paths()
        scroll = {}
        preview = {}
        for rel in open_tabs:
            editor = self.tabs_host.editor_for(rel)
            if editor is None:
                continue
            scroll[rel] = editor.scroll_position()
            preview[rel] = editor.preview_enabled()
        return SessionState(
            dock_visibility=dict(dock_visibility),
            dock_state=dock_state,
            theme=theme,
            open_tabs=open_tabs,
            current_file=self.tabs_host.current_rel_path(),
            preview_enabled=preview,
            scroll_positions=scroll,
        )

    def _default_restore_drafts_choice(self, rels: List[str]) -> bool:
        """崩溃草稿恢复默认决策：弹「恢复 / 忽略」，返回是否恢复。"""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("未保存的草稿")
        box.setIcon(QMessageBox.Icon.Warning)
        body = "\n".join("  " + rel for rel in rels[:10])
        more = "" if len(rels) <= 10 else "\n  …共 {0} 个".format(len(rels))
        box.setText(
            "检测到 {0} 个未保存的恢复内容：\n{1}{2}\n\n"
            "恢复后内容保持未保存状态，正式文件不被覆盖。".format(
                len(rels), body, more
            )
        )
        restore_btn = box.addButton("恢复", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("忽略", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is restore_btn

    def _restore_drafts_and_session(self) -> None:
        """索引就绪后：恢复会话标签（正式内容），再提示草稿恢复。

        会话标签一律从磁盘正式内容恢复；任何自动草稿都经显式「恢复/忽略」
        确认后才加载。绝不静默用草稿替换正式视图——否则用户此前「忽略」的
        崩溃草稿会在会话恢复时复活，且后续一次保存就可能把正式文件覆盖成
        旧草稿内容。
        """
        session = self._session_store.load()
        if not session.empty:
            self._restore_session_tabs(session)
        drafts = self._autosave.list_drafts()
        if drafts:
            self._prompt_restore_drafts(drafts)

    def _restore_session_tabs(self, session: SessionState) -> None:
        """按会话恢复打开标签/当前文件/预览/滚动；缺失文件跳过不阻断。

        只从磁盘正式内容恢复；草稿一律走 `_prompt_restore_drafts` 的显式
        确认，避免把已忽略/废弃的草稿静默载入为未保存状态。
        """
        for rel in session.open_tabs:
            if self.tabs_host.editor_for(rel) is not None:
                continue  # 已打开
            text = self._session_tab_text(rel)
            if text is None:
                continue  # 文件缺失/不可读：跳过该标签
            self.tabs_host.open_file(rel, text)
        if session.current_file and self.tabs_host.editor_for(session.current_file):
            self.tabs_host.activate(session.current_file)
        for rel, enabled in session.preview_enabled.items():
            editor = self.tabs_host.editor_for(rel)
            if editor is not None:
                editor.set_preview_enabled(enabled)
        for rel, position in session.scroll_positions.items():
            editor = self.tabs_host.editor_for(rel)
            if editor is not None:
                editor.set_scroll_position(position)

    def _session_tab_text(self, rel: str) -> Optional[str]:
        """返回会话标签的磁盘正式内容；缺失/不可读返回 None。"""
        try:
            path = self._writer.resolve(rel)
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            # 文件缺失/不可读或会话路径越界：跳过该标签不阻断恢复。
            return None

    def _prompt_restore_drafts(self, rels: List[str]) -> None:
        """按恢复/忽略决策加载剩余草稿（恢复为脏状态；忽略则草稿保留）。"""
        if not self._restore_drafts_choice(rels):
            return  # 忽略：不加载、不删除草稿，正式内容保持原状
        for rel in rels:
            text = self._autosave.read(rel)
            if text is not None:
                self.tabs_host.open_draft(rel, text)

    # --- 状态 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._tree.set_writable(writable)
        self.tabs_host.set_writable(writable)
        for panel in (
            getattr(self, "_replace_panel", None),
            getattr(self, "_refactor_panel", None),
            getattr(self, "_lint_panel", None),
            getattr(self, "_changes_panel", None),
        ):
            if panel is not None:
                panel.set_writable(writable)

    def is_index_ready(self) -> bool:
        return self._index is not None

    def index_file_count(self) -> int:
        return len(self._index.files) if self._index is not None else 0

    def index(self) -> Optional[ContentIndex]:
        return self._index
