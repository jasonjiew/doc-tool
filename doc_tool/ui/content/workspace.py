# -*- coding: utf-8 -*-
"""内容工作区：把章节树、编辑器、搜索/替换/重命名/检查面板整合为一个组件。

打开项目后由主窗口实例化。索引在后台线程构建（可取消），完成后填充
章节树并接线各面板。写操作（保存/替换/重命名）后经回调刷新索引。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.lint import ContentLinter, TermStore
from doc_tool.application.content.refactor import RefactorService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.replace import ReplaceService
from doc_tool.application.content.search import SearchService
from doc_tool.application.content.tree import build_tree
from doc_tool.application.content.writer import ContentWriter
from doc_tool.domain.content_index import ContentIndex


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


class ContentWorkspace(ttk.Frame):
    """内容工作区组件。

    ``on_status(message)``：向主窗口状态栏推送构建进度。
    ``on_open_file(rel_path)``：从树/结果打开文件时（主窗口可据此同步）。
    ``on_request_validate()``：替换/重命名写回后请求跑校验管线。
    ``on_index_ready()``：索引构建完成后回调（主窗口可启用菜单）。
    """

    def __init__(
        self,
        master,
        content_root: Path,
        *,
        state_dir: Path,
        assets_root: Optional[Path] = None,
        writable: bool = True,
        on_status: Optional[Callable[[str], None]] = None,
        on_open_file: Optional[Callable[[str], None]] = None,
        on_request_validate: Optional[Callable[[], None]] = None,
        on_index_ready: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
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

        # 后台索引构建
        from doc_tool.ui.task_bridge import TaskRunner, TaskSpec

        self._runner = TaskRunner()
        self._build_ui()
        self._start_index_build()

    # --- 构建 ---

    def _build_ui(self) -> None:
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True)

        # 标签 1：章节树 + 编辑器/预览
        from doc_tool.ui.content.editor_panel import EditorPanel
        from doc_tool.ui.content.tree_panel import ChapterTree

        tree_editor = ttk.Frame(self._notebook)
        self._tree = ChapterTree(
            tree_editor,
            on_open=self._on_tree_open,
            on_refresh=self._rebuild_index,
            writable=self._writable,
        )
        self._tree.pack(side="left", fill="y", padx=(0, 6))
        self._editor = EditorPanel(
            tree_editor,
            self._writer,
            on_saved=self._on_file_saved,
            writable=self._writable,
        )
        self._editor.pack(side="left", fill="both", expand=True)
        self._notebook.add(tree_editor, text="章节树 / 编辑器")

        # 标签 2-5：搜索 / 替换 / 重命名 / 检查（延迟到索引就绪后接线）
        self._search_placeholder = ttk.Label(
            self._notebook, text="索引构建中…", padding=24
        )
        self._notebook.add(self._search_placeholder, text="搜索")

        self._replace_placeholder = ttk.Label(
            self._notebook, text="索引构建中…", padding=24
        )
        self._notebook.add(self._replace_placeholder, text="替换")

        self._refactor_placeholder = ttk.Label(
            self._notebook, text="索引构建中…", padding=24
        )
        self._notebook.add(self._refactor_placeholder, text="重命名/重编号")

        self._lint_placeholder = ttk.Label(
            self._notebook, text="索引构建中…", padding=24
        )
        self._notebook.add(self._lint_placeholder, text="检查")

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
        self._poll_index()

    def _poll_index(self) -> None:
        if not self._runner.is_running:
            return
        self._runner.poll()
        if self._runner.is_running:
            try:
                self.after(80, self._poll_index)
            except Exception:
                pass

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

        # 搜索
        from doc_tool.ui.content.search_panel import SearchPanel

        search = SearchPanel(
            self._notebook,
            SearchService(self._index),
            on_open=self._open_and_locate,
            writable=self._writable,
        )
        self._notebook.add(search, text="搜索")
        self._notebook.forget(self._search_placeholder)

        # 替换
        from doc_tool.ui.content.replace_panel import ReplacePanel

        replace = ReplacePanel(
            self._notebook,
            ReplaceService(self._index),
            self._writer,
            on_applied=self._after_write,
            writable=self._writable,
        )
        self._notebook.add(replace, text="替换")
        self._notebook.forget(self._replace_placeholder)

        # 重命名/重编号
        from doc_tool.ui.content.refactor_panel import RefactorPanel

        refactor = RefactorPanel(
            self._notebook,
            RefactorService(self._index),
            self._writer,
            on_applied=self._after_write,
            writable=self._writable,
        )
        refactor.set_files(self._index.all_files())
        self._notebook.add(refactor, text="重命名/重编号")
        self._notebook.forget(self._refactor_placeholder)

        # 检查
        from doc_tool.ui.content.lint_panel import LintPanel

        lint = LintPanel(
            self._notebook,
            ContentLinter(self._index),
            self._term_store,
            on_open=self._open_and_locate,
            writable=self._writable,
        )
        self._notebook.add(lint, text="检查")
        self._notebook.forget(self._lint_placeholder)

        self._search_panel = search
        self._replace_panel = replace
        self._refactor_panel = refactor
        self._lint_panel = lint

    # --- 打开文件 ---

    def open_file(self, rel_path: str, line_no: Optional[int] = None) -> None:
        """打开文件到编辑器并定位到行；文件不在索引中则尝试直接读取。"""
        self._select_tab("章节树 / 编辑器")
        path = self._writer.resolve(rel_path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            if self._on_status is not None:
                self._on_status("无法读取文件：{0}".format(rel_path))
            return
        self._editor.load(rel_path, text)
        # 先记录当前文件再定位树节点，避免树选中的延迟事件递归打开同一文件
        self._tree.set_current(rel_path)
        self._tree.select_file(rel_path)
        if line_no is not None:
            self._editor.highlight_line(line_no)
        if self._on_open_file is not None:
            self._on_open_file(rel_path)

    def _on_tree_open(self, rel_path: str) -> None:
        self.open_file(rel_path)

    def _open_and_locate(self, rel_path: str, line_no: int) -> None:
        self.open_file(rel_path, line_no)

    def _select_tab(self, tab_text: str) -> None:
        for tab_id in self._notebook.tabs():
            if self._notebook.tab(tab_id, "text") == tab_text:
                self._notebook.select(tab_id)
                return

    # --- 写后联动 ---

    def _rebuild_index(self) -> None:
        """手动刷新：非破坏性重扫索引 + 重扫引用 + 重绘树。"""
        if self._index is None:
            self._start_index_build()
            return
        try:
            self._index_service.refresh(self._index)
            from doc_tool.application.content.references import ReferenceScanner

            ReferenceScanner(self._index, assets_root=self._assets_root).scan_all()
            items = build_tree(self._index.all_files())
            self._tree.set_items(items)
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
        """编辑器保存后失效并重建该文件索引。"""
        if self._index is None:
            return
        self._index.invalidate(rel_path)
        self._index_service.rebuild_file(self._index, rel_path)

    def _after_write(self) -> None:
        """替换/重命名写回后：刷新索引并请求校验管线。"""
        if self._index is not None:
            self._index_service.refresh_dirty(self._index)
            # 重命名可能新增/移除文件，重建整棵章节树
            items = build_tree(self._index.all_files())
            self._tree.set_items(items)
            if hasattr(self, "_refactor_panel"):
                self._refactor_panel.set_files(self._index.all_files())
        if self._on_request_validate is not None:
            self._on_request_validate()

    # --- 状态 ---

    def set_writable(self, writable: bool) -> None:
        """切换只读/可写，传播到各面板。"""
        self._writable = writable
        self._tree.set_writable(writable)
        self._editor.set_writable(writable)
        for panel in (
            getattr(self, "_search_panel", None),
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
