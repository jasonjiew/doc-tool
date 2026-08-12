# -*- coding: utf-8 -*-
"""内容工作区协调器：把章节树、编辑器、底部面板交给主窗口摆放。

不把树与面板打包进同一父容器，而是暴露命名子容器（``tree_host`` /
``tabs_host`` / ``panels_host``），由主窗口放入左侧 Dock / 中央区 / 底部
面板。索引在后台线程构建（可取消），完成后填充章节树并接线各面板。
写操作（保存/替换/重命名）后经回调刷新索引并请求校验管线。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.lint import ContentLinter, TermStore
from doc_tool.application.content.refactor import RefactorService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.replace import ReplaceService
from doc_tool.application.content.search import SearchService
from doc_tool.application.content.snapshot import (
    ContentSnapshot,
    overlay_rename_status,
)
from doc_tool.application.content.tree import build_tree
from doc_tool.application.content.writer import ContentWriter
from doc_tool.domain.content_index import ContentIndex

from doc_tool.ui.content.lint_panel import LintPanel
from doc_tool.ui.content.refactor_panel import RefactorPanel
from doc_tool.ui.content.replace_panel import ReplacePanel
from doc_tool.ui.content.search_panel import SearchPanel
from doc_tool.ui.content.tabs_host import TabsHost
from doc_tool.ui.content.tree_panel import ChapterTree


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
    """

    def __init__(
        self,
        content_root: Path,
        *,
        state_dir: Path,
        assets_root: Optional[Path] = None,
        writable: bool = True,
        on_status: Optional[Callable[[str], None]] = None,
        on_open_file: Optional[Callable[[str], None]] = None,
        on_request_validate: Optional[Callable[[], None]] = None,
        on_index_ready: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._content_root = Path(content_root).resolve()
        self._state_dir = Path(state_dir).resolve()
        self._assets_root = Path(assets_root) if assets_root else None
        self._writable = writable
        self._on_status = on_status
        self._on_open_file = on_open_file
        self._on_request_validate = on_request_validate
        self._on_index_ready = on_index_ready

        self._index: Optional[ContentIndex] = None
        self._index_service = ContentIndexService(self._content_root)
        self._writer = ContentWriter(self._content_root, self._state_dir)
        self._term_store = TermStore(self._state_dir)

        # 内容快照基线：首次打开打基线（此后徽标=相对基线的所有真实变动，含外部编辑）。
        self._snapshot = ContentSnapshot(self._state_dir)
        self._snapshot.load()
        if not self._snapshot.entries:
            self._snapshot.take(
                self._content_root,
                [rel for rel, _ in self._index_service.discover_files()],
            )
            self._snapshot.save()

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
            on_clear_markers=self._on_clear_markers,
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
        )

        self.panels_host = QWidget(self)
        self._panels = QTabWidget(self.panels_host)
        panels_layout = QVBoxLayout(self.panels_host)
        panels_layout.setContentsMargins(0, 0, 0, 0)
        panels_layout.addWidget(self._panels)
        # 索引就绪前的占位
        self._placeholder_tabs: Dict[str, QWidget] = {}
        for name in ("搜索", "替换", "重命名/重编号", "检查"):
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

    def _poll_index(self) -> None:
        self._runner.poll()
        if not self._runner.is_running:
            self._poll_timer.stop()

    def _on_index_done(self, result) -> None:
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
        )
        self._panels.addTab(search, "搜索")
        self._remove_placeholder("搜索")

        replace = ReplacePanel(
            ReplaceService(self._index),
            self._writer,
            on_applied=self._after_write,
            writable=self._writable,
        )
        self._panels.addTab(replace, "替换")
        self._remove_placeholder("替换")

        refactor = RefactorPanel(
            RefactorService(self._index),
            self._writer,
            on_applied=self._after_write,
            writable=self._writable,
        )
        refactor.set_files(self._index.all_files())
        self._panels.addTab(refactor, "重命名/重编号")
        self._remove_placeholder("重命名/重编号")

        lint = LintPanel(
            ContentLinter(self._index),
            self._term_store,
            on_open=self._open_and_locate,
            writable=self._writable,
        )
        self._panels.addTab(lint, "检查")
        self._remove_placeholder("检查")

        self._search_panel = search
        self._replace_panel = replace
        self._refactor_panel = refactor
        self._lint_panel = lint

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

    def show_replace(self) -> None:
        self._select_panel("替换")

    def show_refactor(self, target: Optional[str] = None) -> None:
        self._select_panel("重命名/重编号")
        panel = getattr(self, "_refactor_panel", None)
        if panel is not None and target:
            panel.set_target(target)

    def run_lint(self) -> None:
        self._select_panel("检查")
        panel = getattr(self, "_lint_panel", None)
        if panel is not None:
            panel.run_check()

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
        """快照 diff + 改动清单 rename 叠加 → 徽标状态（需索引已就绪）。"""
        self._writer.manifest.load()
        status = self._snapshot.diff(self._content_root, self._index.all_files())
        return overlay_rename_status(status, self._writer.manifest.entries)

    def _apply_status_map(self) -> None:
        """从内容快照对比当前真实变动并应用到章节树徽标。"""
        if self._index is None:
            return
        self._tree.set_status_map(self._status_map())

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
        self.tabs_host.close_file(rel_path)
        self._index_service.rebuild_file(self._index, rel_path)
        items = build_tree(self._index.all_files())
        self._tree.set_items(items)
        self._apply_status_map()

    def _on_rename_file(self, rel_path: str) -> None:
        """内联重命名文件并联动更新引用（复用 RefactorService）。"""
        from pathlib import Path

        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from doc_tool.application.content.refactor import RefactorService

        if self._index is None:
            return
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
        self.tabs_host.close_file(rel_path)
        self._after_write()

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
        self._apply_status_map()

    def _after_write(self) -> None:
        """替换/重命名写回后：刷新索引并请求校验管线。"""
        if self._index is not None:
            self._index_service.refresh(self._index)
            items = build_tree(self._index.all_files())
            self._tree.set_items(items)
            self._apply_status_map()
            if hasattr(self, "_refactor_panel"):
                self._refactor_panel.set_files(self._index.all_files())
        if self._on_request_validate is not None:
            self._on_request_validate()

    # --- 状态 ---

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._tree.set_writable(writable)
        self.tabs_host.set_writable(writable)
        for panel in (
            getattr(self, "_replace_panel", None),
            getattr(self, "_refactor_panel", None),
            getattr(self, "_lint_panel", None),
        ):
            if panel is not None:
                panel.set_writable(writable)

    def is_index_ready(self) -> bool:
        return self._index is not None

    def index_file_count(self) -> int:
        return len(self._index.files) if self._index is not None else 0

    def index(self) -> Optional[ContentIndex]:
        return self._index
