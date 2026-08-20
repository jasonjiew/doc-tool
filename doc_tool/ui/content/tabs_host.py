# -*- coding: utf-8 -*-
"""中心多标签编辑器：每个打开的章节一个标签页。

标签页为 ``EditorPanel``（QPlainTextEdit 编辑 + Qt Markdown 预览），可同时
打开多个文件并切换编辑。保存经 ``ContentWriter``（备份 + 原子写），写回后
经 ``on_saved`` 回调由上层失效重建索引并刷新预览。标签切换时检测外部修改。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtGui import QKeySequence, QShortcut
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
        autosave=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._writer = writer
        self._on_saved = on_saved
        self._on_current_changed = on_current_changed
        self._assets_root = assets_root
        self._writable = writable
        self._autosave = autosave

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Ctrl+S 保存当前标签页（按钮文案已声明，此前未绑定）。
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.activated.connect(self.save_current)

        # Ctrl+H 文件内替换条（焦点在当前编辑器时激活）。
        self._replace_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        self._replace_shortcut.activated.connect(self.focus_replace_current)

        layout = self._make_layout()
        layout.addWidget(self._tabs)

        # rel_path -> EditorPanel
        self._editors: Dict[str, EditorPanel] = {}
        # rel_path -> 缓存文本（未打开编辑器的文件，如只读预览不适用，暂不缓存）
        self._tab_order: List[str] = []

    def focus_replace_current(self) -> None:
        """聚焦当前编辑器的文件内替换条（Ctrl+H）。"""
        editor = self.current_editor()
        if editor is not None:
            editor.focus_replace()

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
            on_dirty_changed=lambda dirty: self._on_editor_dirty(editor, dirty),
            autosave=self._autosave,
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

    def activate(self, rel_path: str) -> bool:
        """激活指定文件的已开标签（不打开新标签）。返回是否已打开。"""
        editor = self._editors.get(rel_path)
        if editor is None:
            return False
        index = self._tabs.indexOf(editor)
        if index >= 0:
            self._tabs.setCurrentIndex(index)
        return True

    def editors(self) -> List[EditorPanel]:
        """返回全部已打开编辑器（保持打开顺序，供未保存收集）。"""
        return list(self._editors.values())

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

    def save_all(self) -> List[str]:
        """保存全部脏标签；返回保存失败的 rel_path 列表（不中断其余标签）。

        只读（不可写）编辑器无法保存，跳过不计入失败——否则只读项目恢复出的
        脏草稿标签会让「退出/切换时保存」恒失败并中止。
        """
        failed: List[str] = []
        for rel_path, editor in self._editors.items():
            if editor.is_dirty() and editor.is_writable():
                if not editor.save():
                    failed.append(rel_path)
        return failed

    def open_draft(self, rel_path: str, text: str) -> bool:
        """以草稿内容打开标签（脏状态、不写正式文件）。

        已打开时切到该标签并重载为草稿；返回是否新开。正式 Markdown 不被
        写入，用户显式保存才落盘。
        """
        existing = self._editors.get(rel_path)
        if existing is not None:
            existing.load_draft(rel_path, text)
            index = self._tabs.indexOf(existing)
            if index >= 0:
                self._tabs.setCurrentIndex(index)
            return False
        editor = EditorPanel(
            self._writer,
            on_saved=self._on_saved,
            assets_root=self._assets_root,
            writable=self._writable,
            on_dirty_changed=lambda dirty: self._on_editor_dirty(editor, dirty),
            autosave=self._autosave,
        )
        editor.load_draft(rel_path, text)
        self._tabs.addTab(editor, self._tab_label(editor))
        self._tabs.setCurrentWidget(editor)
        self._editors[rel_path] = editor
        return True

    def check_external_change_current(self) -> None:
        """标签切换/激活时检测外部修改。"""
        editor = self.current_editor()
        if editor is not None:
            editor.check_external_change()

    def close_all(self) -> None:
        """关闭全部标签（项目切换时清理）。"""
        for rel_path in list(self._editors.keys()):
            self._close_tab_by_path(rel_path)

    def close_file(self, rel_path: str) -> None:
        """关闭指定文件的标签（删除文件时清理已打开标签）。"""
        self._close_tab_by_path(rel_path)

    # --- 内部 ---

    def _on_editor_dirty(self, editor: EditorPanel, dirty: bool) -> None:
        """脏状态变化 → 更新对应标签标题（● 前缀）。"""
        index = self._tabs.indexOf(editor)
        if index >= 0:
            self._tabs.setTabText(index, self._tab_label(editor))

    @staticmethod
    def _tab_label(editor: EditorPanel) -> str:
        name = (editor.current_rel_path() or "").rsplit("/", 1)[-1]
        return "● " + name if editor.is_dirty() else name

    def _close_tab(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if not isinstance(widget, EditorPanel):
            return
        was_dirty = widget.is_dirty()
        if was_dirty and not self._confirm_close_dirty(widget):
            return
        rel_path = widget.current_rel_path()
        if rel_path is not None:
            self._editors.pop(rel_path, None)
            if was_dirty and self._autosave is not None:
                # 关闭脏标签 = 显式放弃未保存编辑：清除其草稿，避免下次打开
                # 在崩溃恢复提示中复活已丢弃的内容。
                self._autosave.clear(rel_path)
        else:
            # 边界兜底：编辑器尚未加载路径（正常流程不可达）时按 widget
            # 身份清理，避免失效条目残留在 _editors 造成标签重建/泄漏。
            for key, editor in list(self._editors.items()):
                if editor is widget:
                    self._editors.pop(key, None)
                    break
        self._tabs.removeTab(index)
        widget.stop_autosave()
        widget.deleteLater()

    @staticmethod
    def _confirm_close_dirty(editor: EditorPanel) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            editor,
            "未保存的更改",
            "该文件有未保存的更改：\n{0}\n\n关闭将丢失这些更改，确认关闭？".format(
                editor.current_rel_path() or ""
            ),
        )
        return answer == QMessageBox.StandardButton.Yes

    def _close_tab_by_path(self, rel_path: str) -> None:
        editor = self._editors.pop(rel_path, None)
        if editor is None:
            return
        index = self._tabs.indexOf(editor)
        if index >= 0:
            self._tabs.removeTab(index)
        editor.stop_autosave()
        editor.deleteLater()

    def _on_tab_changed(self, _index: int) -> None:
        self.check_external_change_current()
        if self._on_current_changed is not None:
            self._on_current_changed(self.current_rel_path())
