# -*- coding: utf-8 -*-
"""中心多标签编辑器：每个打开的章节一个标签页。

标签页为 ``EditorPanel``（QPlainTextEdit 编辑 + Qt Markdown 预览），可同时
打开多个文件并切换编辑。保存经 ``ContentWriter``（备份 + 原子写），写回后
经 ``on_saved`` 回调由上层失效重建索引并刷新预览。标签切换时检测外部修改。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import QTabWidget, QWidget

from doc_tool.ui.content.editor_panel import EditorPanel


class TabsHost(QWidget):
    """多标签编辑器宿主。"""

    def __init__(
        self,
        writer,
        *,
        on_saved: Optional[Callable[[str], None]] = None,
        on_current_changed: Optional[Callable[[Optional[str]], None]] = None,
        assets_root=None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._writer = writer
        self._on_saved = on_saved
        self._on_current_changed = on_current_changed
        self._assets_root = assets_root
        self._writable = writable

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        layout = self._make_layout()
        layout.addWidget(self._tabs)

        # rel_path -> EditorPanel
        self._editors: Dict[str, EditorPanel] = {}
        # rel_path -> 缓存文本（未打开编辑器的文件，如只读预览不适用，暂不缓存）
        self._tab_order: List[str] = []

    def _make_layout(self):
        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        return layout

    # --- 打开 / 切换 ---

    def open_file(
        self,
        rel_path: str,
        text: str,
        line_no: Optional[int] = None,
    ) -> bool:
        """在标签页打开文件；已打开则切换到该标签。返回是否新开。"""
        existing = self._editors.get(rel_path)
        if existing is not None:
            index = self._tabs.indexOf(existing)
            if index >= 0:
                self._tabs.setCurrentIndex(index)
            if line_no is not None:
                existing.highlight_line(line_no)
            return False
        editor = EditorPanel(
            self._writer,
            on_saved=self._on_saved,
            assets_root=self._assets_root,
            writable=self._writable,
        )
        editor.load(rel_path, text)
        self._tabs.addTab(editor, rel_path.rsplit("/", 1)[-1])
        self._tabs.setCurrentWidget(editor)
        self._editors[rel_path] = editor
        if line_no is not None:
            editor.highlight_line(line_no)
        return True

    def current_editor(self) -> Optional[EditorPanel]:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, EditorPanel) else None

    def current_rel_path(self) -> Optional[str]:
        editor = self.current_editor()
        return editor.current_rel_path() if editor is not None else None

    def editor_for(self, rel_path: str) -> Optional[EditorPanel]:
        return self._editors.get(rel_path)

    def open_rel_paths(self) -> List[str]:
        return list(self._editors.keys())

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        for editor in self._editors.values():
            editor.set_writable(writable)

    def save_current(self) -> bool:
        """保存当前标签页。"""
        editor = self.current_editor()
        return editor.save() if editor is not None else False

    def check_external_change_current(self) -> None:
        """标签切换/激活时检测外部修改。"""
        editor = self.current_editor()
        if editor is not None:
            editor.check_external_change()

    def close_all(self) -> None:
        """关闭全部标签（项目切换时清理）。"""
        for rel_path in list(self._editors.keys()):
            self._close_tab_by_path(rel_path)

    # --- 内部 ---

    def _close_tab(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if not isinstance(widget, EditorPanel):
            return
        rel_path = widget.current_rel_path()
        if rel_path is not None:
            self._editors.pop(rel_path, None)
        self._tabs.removeTab(index)
        widget.deleteLater()

    def _close_tab_by_path(self, rel_path: str) -> None:
        editor = self._editors.pop(rel_path, None)
        if editor is None:
            return
        index = self._tabs.indexOf(editor)
        if index >= 0:
            self._tabs.removeTab(index)
        editor.deleteLater()

    def _on_tab_changed(self, _index: int) -> None:
        self.check_external_change_current()
        if self._on_current_changed is not None:
            self._on_current_changed(self.current_rel_path())
