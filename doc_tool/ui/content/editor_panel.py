# -*- coding: utf-8 -*-
"""内置 .md 编辑器 + Markdown 阅读预览（PySide6）。

UTF-8 纯文本编辑，保存经 ``ContentWriter``（备份 + 原子写）。右侧使用 Qt
原生 Markdown 文档渲染器，编辑去抖后即时更新；项目自定义图片尺寸后缀会在
预览前转换为标准 Markdown。提供"在外部编辑器打开"兜底与外部修改检测。
"""

from __future__ import annotations

import os
import re
import time
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.preview import (
    preview_summary,
    render_markdown_html,
)
from doc_tool.application.content.snippets import (
    SnippetStore,
    expand_placeholders,
)
from doc_tool.application.content.spellcheck import (
    SpellChecker,
    UserDictionary,
    load_builtin_words,
)
from doc_tool.ui.content.editor_highlight import (
    MarkdownHighlighter,
    _LineNumberedEdit,
)

_PREVIEW_DEBOUNCE_MS = 300
_SPELL_DEBOUNCE_MS = 300

# 围栏代码块起始/结束（拼写可见行扫描跳过围栏内英文）。
_FENCE_RE = re.compile(r"^```")

# 草稿去抖窗口：编辑停止约 1.5s 后写入 .state/autosave/（独立于预览去抖）。
_DRAFT_DEBOUNCE_MS = 1500


class EditorPanel(QWidget):
    """单文件 .md 编辑器。

    ``writer``：``ContentWriter``（写入安全）。
    ``on_saved(rel_path)``：保存成功后回调（主窗口据此失效索引）。
    ``writable``：只读时禁用编辑与保存。
    ``autosave``：``AutoSaveStore``；提供时编辑去抖后写草稿、保存后清除，
      只读项目不写草稿。
    ``snippet_store`` / ``user_dict`` / ``spellchecker``：创作服务注入点；
      缺省时按用户级配置（AppData）自建。
    """

    def __init__(
        self,
        writer,
        *,
        on_saved: Optional[Callable[[str], None]] = None,
        assets_root=None,
        writable: bool = True,
        on_dirty_changed: Optional[Callable[[bool], None]] = None,
        autosave=None,
        snippet_store=None,
        user_dict=None,
        spellchecker=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._writer = writer
        self._on_saved = on_saved
        self._assets_root = assets_root
        self._writable = writable
        self._on_dirty_changed = on_dirty_changed
        self._autosave = autosave
        self._rel_path: Optional[str] = None
        self._mtime: Optional[float] = None
        self._dirty = False
        self._draft_loaded = False  # 内容来自草稿（尚未落盘到正式文件）
        self._draft_failed = False  # 最近一次草稿写入是否失败（用于去重提示）

        # 创作服务：拼写检查、用户词典、代码片段（测试可注入）。
        self._user_dict = user_dict if user_dict is not None else UserDictionary()
        self._spell_checker = spellchecker if spellchecker is not None else SpellChecker(
            load_builtin_words(), self._user_dict.words
        )
        self._snippet_store = (
            snippet_store if snippet_store is not None else SnippetStore()
        )

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._schedule_preview)
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.timeout.connect(self._write_draft)
        self._spell_timer = QTimer(self)
        self._spell_timer.setSingleShot(True)
        self._spell_timer.timeout.connect(self._scan_spelling)
        # 行锚点闪烁定时器必须挂在本面板（QTimer(self)）而非无父 singleShot：
        # 否则面板 deleteLater 后回调访问已销毁的 _editor，抛 RuntimeError。
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        # 已提示过「外部修改」的 (rel_path, mtime) 集合：用户拒绝重载后，
        # 同一外部变更不再重复弹框；save() 仍独立做 mtime 校验，不削弱
        self._dismissed_external: set = set()
        self._dark = False
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            from doc_tool.ui.styles import is_dark_theme
            self._dark = is_dark_theme(app)

        self._build_toolbar()
        self._build_panes()

    # --- 构建 ---

    def _build_toolbar(self) -> None:
        bar = QWidget(self)
        bar.setObjectName("editorToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        # Markdown 常用格式快捷操作组（单行工具栏左侧）
        self._md_toolbar = QWidget(bar)
        md_layout = QHBoxLayout(self._md_toolbar)
        md_layout.setContentsMargins(0, 0, 0, 0)
        md_layout.setSpacing(2)

        def md_btn(text: str, slot: Callable, tip: str) -> QPushButton:
            btn = QPushButton(text, self._md_toolbar)
            btn.setProperty("btnRole", "compact")
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            md_layout.addWidget(btn)
            return btn

        md_btn("H2", self._toolbar_heading, "标题（当前行前置 ## ）")
        md_btn("B", lambda: self.wrap_selection("**", "**"), "粗体 (**)")
        md_btn("I", lambda: self.wrap_selection("*", "*"), "斜体 (*)")
        md_btn("代码", lambda: self.wrap_selection("`", "`"), "行内代码 (`)")
        md_btn("•列表", lambda: self._prefix_lines("- "), "无序列表 (- )")
        md_btn("1.列表", lambda: self._prefix_lines("1. "), "有序列表 (1. )")
        md_btn("引用", lambda: self._prefix_lines("> "), "引用 (> )")
        md_btn("表格", self._insert_table, "插入表格骨架")
        md_btn("美化表", self.format_table_at_cursor, "美化对齐当前表格 (Ctrl+Alt+T)")
        md_btn("链接", self._insert_link, "插入链接")
        md_btn("图片", self._on_insert_image, "插入图片（粘贴/选择文件）")
        md_btn("Mermaid", self.open_mermaid_workbench, "Mermaid 图形工作台")
        md_btn("批量转图", self.batch_convert_mermaid, "转换当前文档中的历史 Mermaid 源码")
        md_btn("片段", self.open_snippet_manager, "代码片段管理器")

        layout.addWidget(self._md_toolbar)

        # 竖向微分隔线
        sep = QFrame(bar)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # 中部：文件名/相对路径 + 未保存状态 + 结构摘要
        self._file_label = QLabel("未打开文件", bar)
        self._file_label.setObjectName("statusMuted")
        layout.addWidget(self._file_label)

        self._dirty_label = QLabel("", bar)
        self._dirty_label.setProperty("statusTone", "warning")
        layout.addWidget(self._dirty_label)

        self._status_label = QLabel("", bar)
        self._status_label.setObjectName("statusMuted")
        layout.addWidget(self._status_label)

        layout.addStretch(1)

        # 右侧快捷动作组：回滚、外部打开、隐藏/显示预览、保存
        self._rollback_btn = QPushButton("回滚", bar)
        self._rollback_btn.setProperty("btnRole", "compact")
        self._rollback_btn.setToolTip("回滚上次保存（用 .bak 恢复）")
        self._rollback_btn.clicked.connect(self.rollback_last)
        layout.addWidget(self._rollback_btn)

        self._ext_btn = QPushButton("外部打开", bar)
        self._ext_btn.setProperty("btnRole", "compact")
        self._ext_btn.setToolTip("在系统外部编辑器中打开当前文件")
        self._ext_btn.clicked.connect(self.open_external)
        layout.addWidget(self._ext_btn)

        self._preview_btn = QPushButton("隐藏预览", bar)
        self._preview_btn.setProperty("btnRole", "compact")
        self._preview_btn.setToolTip("切换双栏实时预览显示/隐藏")
        self._preview_btn.clicked.connect(self._toggle_preview)
        layout.addWidget(self._preview_btn)

        self._save_btn = QPushButton("保存 (Ctrl+S)", bar)
        self._save_btn.setProperty("btnRole", "primary")
        self._save_btn.setToolTip("保存修改并原子写入磁盘 (Ctrl+S)")
        self._save_btn.clicked.connect(self.save)
        layout.addWidget(self._save_btn)

        self._toolbar = bar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 4)
        outer.setSpacing(2)
        outer.addWidget(bar)
        self._find_bar = self._build_find_bar()
        outer.addWidget(self._find_bar)
        self._replace_bar = self._build_replace_bar()
        outer.addWidget(self._replace_bar)
        self._body_host = QWidget(self)
        outer.addWidget(self._body_host, 1)

    def _build_markdown_toolbar(self) -> QWidget:
        """向后兼容：返回已集成在单行工具栏中的 Markdown 快捷操作部件。"""
        return self._md_toolbar

    def _build_find_bar(self) -> QWidget:
        """文件内查找条：输入 + 上/下导航 + 关闭。默认隐藏。"""
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)
        layout.addWidget(QLabel("查找：", bar))
        self._find_entry = QLineEdit(bar)
        self._find_entry.setPlaceholderText("在文件中查找…")
        self._find_entry.textChanged.connect(self._on_find_changed)
        self._find_entry.returnPressed.connect(self._find_next)
        layout.addWidget(self._find_entry, 1)
        prev_btn = QPushButton("上一个", bar)
        prev_btn.setProperty("btnRole", "compact")
        prev_btn.clicked.connect(self._find_prev)
        layout.addWidget(prev_btn)
        next_btn = QPushButton("下一个", bar)
        next_btn.setProperty("btnRole", "compact")
        next_btn.clicked.connect(self._find_next)
        layout.addWidget(next_btn)
        close_btn = QPushButton("关闭", bar)
        close_btn.setProperty("btnRole", "compact")
        close_btn.clicked.connect(self.hide_find)
        layout.addWidget(close_btn)
        bar.hide()
        return bar

    def _build_replace_bar(self) -> QWidget:
        """文件内替换条：替换为 + 替换一个/全部替换/关闭。默认隐藏。"""
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)
        layout.addWidget(QLabel("替换为：", bar))
        self._replace_entry = QLineEdit(bar)
        self._replace_entry.setPlaceholderText("替换为…")
        layout.addWidget(self._replace_entry, 1)
        prev_btn = QPushButton("上一个", bar)
        prev_btn.setProperty("btnRole", "compact")
        prev_btn.clicked.connect(self._find_prev)
        layout.addWidget(prev_btn)
        next_btn = QPushButton("下一个", bar)
        next_btn.setProperty("btnRole", "compact")
        next_btn.clicked.connect(self._find_next)
        layout.addWidget(next_btn)
        replace_btn = QPushButton("替换", bar)
        replace_btn.setProperty("btnRole", "compact")
        replace_btn.clicked.connect(self._replace_one)
        layout.addWidget(replace_btn)
        replace_all_btn = QPushButton("全部替换", bar)
        replace_all_btn.setProperty("btnRole", "compact")
        replace_all_btn.clicked.connect(self._replace_all)
        layout.addWidget(replace_all_btn)
        close_btn = QPushButton("关闭", bar)
        close_btn.setProperty("btnRole", "compact")
        close_btn.clicked.connect(self.hide_replace)
        layout.addWidget(close_btn)
        bar.hide()
        return bar

    def _build_panes(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self._body_host)
        body = QVBoxLayout(self._body_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(splitter)

        edit_frame = QWidget(splitter)
        edit_layout = QVBoxLayout(edit_frame)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        self._editor = _LineNumberedEdit(edit_frame)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._editor.textChanged.connect(self._on_edit)
        self._editor.verticalScrollBar().valueChanged.connect(
            self._sync_preview_scroll
        )
        self._editor.set_spellchecker(self._spell_checker)
        self._editor.addWordRequested.connect(self._on_add_word_to_dict)
        self._editor.set_image_import_callback(self.import_image)
        self._editor.mermaidEditRequested.connect(self._open_mermaid_at_position)
        self._editor.formatTableRequested.connect(self.format_table_at_cursor)
        self._format_table_shortcut = QShortcut(
            QKeySequence("Ctrl+Alt+T"), self, self.format_table_at_cursor
        )
        self._highlighter = MarkdownHighlighter(self._editor.document())
        self._find_selections: List[QTextEdit.ExtraSelection] = []
        self._spell_selections: List[QTextEdit.ExtraSelection] = []
        self._flash_selection: Optional[QTextEdit.ExtraSelection] = None
        edit_layout.addWidget(self._editor)
        splitter.addWidget(edit_frame)

        preview_frame = QWidget(splitter)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = QTextBrowser(preview_frame)
        self._preview.setReadOnly(True)
        # 关闭外部链接自动打开：http(s) 链接改由 anchorClicked 处理器用系统浏览器
        # 打开；line-N 锚点用于预览点击定位到源行。
        self._preview.setOpenExternalLinks(False)
        self._preview.anchorClicked.connect(self._on_preview_anchor_clicked)
        preview_layout.addWidget(self._preview)
        splitter.addWidget(preview_frame)
        self._preview_frame = preview_frame

        splitter.setSizes([600, 400])
        self._splitter = splitter

        self._apply_edit_state()

    # --- 加载 / 保存 ---

    def load(self, rel_path: str, text: str) -> None:
        """加载文件内容到编辑器并刷新预览（干净状态，不写草稿）。"""
        self._rel_path = rel_path
        self._mtime = self._file_mtime(rel_path)
        self._dismissed_external.clear()
        self._draft_timer.stop()
        self._editor.setPlainText(text)
        self._dirty = False
        self._draft_loaded = False
        short_name = rel_path.split("/")[-1] if "/" in rel_path else rel_path
        self._file_label.setText(short_name)
        self._file_label.setToolTip("完整相对路径：" + rel_path)
        summary = preview_summary(text)
        self._status_label.setText(summary)
        self._status_label.setToolTip("当前文档：{0}\n统计：{1}".format(rel_path, summary))
        self._refresh_preview(text)
        self._update_dirty()
        self._update_save_state()

    def load_draft(self, rel_path: str, text: str) -> None:
        """以草稿内容加载（保持未保存状态；正式 Markdown 不被写入）。

        恢复自草稿的标签显示「● 恢复自草稿」，用户显式保存才落盘正式文件。
        """
        self._rel_path = rel_path
        self._mtime = self._file_mtime(rel_path)
        self._draft_timer.stop()
        self._editor.setPlainText(text)
        self._dirty = True
        self._draft_loaded = True
        short_name = rel_path.split("/")[-1] if "/" in rel_path else rel_path
        self._file_label.setText(short_name)
        self._file_label.setToolTip("完整相对路径：" + rel_path)
        summary = preview_summary(text)
        self._status_label.setText(summary)
        self._status_label.setToolTip("当前文档：{0}\n统计：{1}".format(rel_path, summary))
        self._refresh_preview(text)
        self._update_dirty()
        self._update_save_state()

    def save(self) -> bool:
        """保存当前内容（备份 + 原子写）。成功返回 True。"""
        if not self._writable or self._rel_path is None:
            return False
        if not self._dirty:
            # 无未保存更改时不重写：避免覆盖上次备份（.bak）并给改动清单
            # 追加无意义的 edit 条目，破坏「回滚上次保存」的备份点。
            return True
        # 外部修改保护：磁盘 mtime 与编辑器加载基准不一致（全局替换/重命名
        # 写盘、外部编辑器修改等）时，先确认再写，避免静默覆盖外部改动
        # （lost update）。与 check_external_change 的提示语义一致。
        current_mtime = self._file_mtime(self._rel_path)
        if (
            current_mtime is not None
            and self._mtime is not None
            and current_mtime != self._mtime
        ):
            from PySide6.QtWidgets import QMessageBox

            answer = QMessageBox.question(
                self,
                "文件已在外部被修改",
                "文件已在外部被修改：\n{0}\n\n"
                "保存将覆盖外部修改，是否继续保存？".format(self._rel_path),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._status_label.setText("已取消保存，保留外部修改")
                return False
        text = self._editor.toPlainText()
        result = self._writer.write_text(self._rel_path, text)
        if not result.written:
            self._status_label.setText("保存失败：{0}".format(result.error))
            return False
        self._mtime = self._file_mtime(self._rel_path)
        self._dismissed_external.clear()
        self._dirty = False
        self._draft_loaded = False
        self._draft_failed = False
        self._draft_timer.stop()
        if self._autosave is not None and self._rel_path is not None:
            # 保存成功即清除草稿，避免草稿与正式内容混淆。
            self._autosave.clear(self._rel_path)
        if result.error:
            self._status_label.setText("已保存（改动清单保存失败：{0}）".format(result.error))
        elif getattr(result, "backup_failed", False):
            self._status_label.setText("已保存（⚠ 备份失败，回滚不可用）")
        else:
            self._status_label.setText("已保存")
        if self._on_saved is not None:
            self._on_saved(self._rel_path)
        self._update_dirty()
        self._update_save_state()
        return True

    def rollback_last(self) -> bool:
        """回滚本文件最近一次保存（用 .bak 恢复）。"""
        if not self._writable or self._rel_path is None:
            return False
        from doc_tool.application.content.writer import (
            OP_EDIT,
            _backup_path_for,
        )

        target = self._writer_abs(self._rel_path)
        backup = _backup_path_for(target)
        if not backup.exists():
            self._status_label.setText("无可用备份")
            return False
        import shutil

        try:
            shutil.copy2(str(backup), str(target))
        except OSError as exc:
            # 复制被拦截（如安全软件）/IO 失败时明确提示，避免静默的半完成回滚。
            self._status_label.setText("回滚失败：{0}".format(exc))
            return False
        # 已恢复到保存前状态：丢弃备份，并从改动清单移除该文件 edit 条目，
        # 避免 .bak 残留在 contentRoot 阻断构建、徽标仍显示"已修改"。
        try:
            backup.unlink()
        except OSError:
            pass
        try:
            self._writer.manifest.load()
            self._writer.manifest.drop(
                OP_EDIT, self._rel_path
            )
        except OSError:
            pass
        # 回滚必须把编辑器内容同步回磁盘状态：不重载则编辑器仍显示已保存内容
        # 却被标为干净，用户继续输入任意字符再保存，会把刚回滚的改动整体写回，
        # 回滚被静默撤销；切换标签时 check_external_change 也会误报/重载。
        try:
            restored_text = target.read_text(encoding="utf-8")
        except OSError:
            self._status_label.setText("回滚失败：无法读取恢复的文件")
            return False
        if self._autosave is not None and self._rel_path is not None:
            # 回滚丢弃了未保存草稿：一并清除，避免下次打开恢复已废弃内容。
            self._autosave.clear(self._rel_path)
        self.load(self._rel_path, restored_text)
        self._status_label.setText("已回滚到备份")
        if self._on_saved is not None:
            self._on_saved(self._rel_path)
        return True

    def open_external(self) -> bool:
        """用系统默认程序在外部编辑器打开当前文件。"""
        if self._rel_path is None:
            return False
        target = self._writer_abs(self._rel_path)
        if not target.exists():
            self._status_label.setText("文件不存在")
            return False
        try:
            if os.name == "nt":
                os.startfile(str(target))  # noqa: S606
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(target)])
            self._status_label.setText("已在外部编辑器打开（请记得回工具刷新）")
            return True
        except OSError as exc:
            self._status_label.setText("打开外部编辑器失败：{0}".format(exc))
            return False

    def check_external_change(self) -> bool:
        """检测文件是否被外部修改；是则提示并刷新内容。返回是否发生了刷新。

        编辑器有未保存更改时不静默重载——先弹确认框，避免外部写盘后
        标签切换把用户正在编辑的内容无声清空。
        """
        if self._rel_path is None:
            return False
        current = self._file_mtime(self._rel_path)
        if current is not None and self._mtime is not None and current != self._mtime:
            key = (self._rel_path, current)
            if key in self._dismissed_external:
                # 同一外部变更已提示过且用户选择保留未保存编辑：不再重复弹框。
                return False
            if self._dirty:
                from PySide6.QtWidgets import QMessageBox

                answer = QMessageBox.question(
                    self,
                    "外部修改检测",
                    "文件已在外部被修改：\n{0}\n\n"
                    "重载将丢弃未保存的更改，是否重载？".format(self._rel_path),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    # 记录本次外部变更已提示：切换标签不再重复弹框（save()
                    # 仍独立做 mtime 校验，覆盖保护不受影响）。
                    self._dismissed_external.add(key)
                    self._status_label.setText("保留未保存更改，未重载外部版本")
                    return False
                # 用户确认丢弃未保存编辑：清除其草稿，避免下次打开恢复已废弃内容。
                if self._autosave is not None and self._rel_path is not None:
                    self._autosave.clear(self._rel_path)
            try:
                text = self._writer_abs(self._rel_path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return False
            self.load(self._rel_path, text)
            self._status_label.setText("检测到外部修改，已刷新")
            return True
        return False

    def highlight_line(self, line_no: int) -> None:
        """高亮并滚动到指定行（用于搜索结果/检查结果定位）。"""
        cursor = self._editor.textCursor()
        block = self._editor.document().findBlockByNumber(max(0, line_no - 1))
        if block.isValid():
            cursor.setPosition(block.position())
            self._editor.setTextCursor(cursor)
            self._editor.centerCursor()
            self._editor.setFocus(Qt.FocusReason.OtherFocusReason)

    # --- 文件内查找 ---

    def focus_find(self) -> None:
        """显示查找条并聚焦输入框（Ctrl+F 且编辑器聚焦时调用）。"""
        self._find_bar.show()
        self._find_entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._find_entry.selectAll()

    def hide_find(self) -> None:
        self._find_bar.hide()
        self._clear_highlights()

    def _find_text(self) -> str:
        return self._find_entry.text()

    def _on_find_changed(self, _text: str) -> None:
        self._update_highlights()

    def _clear_highlights(self) -> None:
        self._find_selections = []
        self._apply_extra_selections()

    def _update_highlights(self) -> None:
        """高亮全部命中；最后一个命中用更深的颜色表示当前匹配。"""
        query = self._find_text()
        if not query:
            self._find_selections = []
            self._apply_extra_selections()
            return
        doc = self._editor.document()
        selections = []
        cursor = QTextCursor(doc)
        base_fmt = QTextCharFormat()
        base_fmt.setBackground(QColor("#ffe08a"))
        current_fmt = QTextCharFormat()
        current_fmt.setBackground(QColor("#ffb84d"))
        while True:
            cursor = doc.find(query, cursor)
            if cursor.isNull():
                break
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = base_fmt
            selections.append(selection)
        if selections:
            selections[-1].format = current_fmt
        self._find_selections = selections
        self._apply_extra_selections()

    def _apply_extra_selections(self) -> None:
        """合并查找 + 拼写 + 临时高亮三组 ExtraSelections（避免互相覆盖）。"""
        combined = self._find_selections + self._spell_selections
        if getattr(self, "_flash_selection", None) is not None:
            combined = combined + [self._flash_selection]
        self._editor.setExtraSelections(combined)

    def _find_next(self) -> None:
        query = self._find_text()
        if not query:
            return
        if not self._editor.find(query):
            # 到末尾未命中 → 循环回开头
            self._editor.moveCursor(QTextCursor.MoveOperation.Start)
            self._editor.find(query)

    def _find_prev(self) -> None:
        query = self._find_text()
        if not query:
            return
        flags = QTextDocument.FindFlag.FindBackward
        if not self._editor.find(query, flags):
            self._editor.moveCursor(QTextCursor.MoveOperation.End)
            self._editor.find(query, flags)

    # --- 文件内替换（Ctrl+H） ---

    def focus_replace(self) -> None:
        """显示替换条并聚焦替换输入框（Ctrl+H 且编辑器聚焦时调用）。"""
        self._find_bar.show()
        self._replace_bar.show()
        self._replace_entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._replace_entry.selectAll()

    def hide_replace(self) -> None:
        self._replace_bar.hide()
        self.hide_find()

    def _replace_text(self) -> str:
        return self._replace_entry.text()

    def _replace_one(self) -> None:
        """替换当前选中命中的一处并跳到下一处命中；无匹配时给出提示。"""
        query = self._find_text()
        replace = self._replace_text()
        if not query:
            self._status_label.setText("无匹配")
            return
        editor = self._editor
        cursor = editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == query:
            cursor.beginEditBlock()
            cursor.insertText(replace)
            cursor.endEditBlock()
            self._status_label.setText("已替换 1 处")
        elif not self._document_contains(query):
            # 查找词在文件中不存在：提示且不产生任何替换（spec 无命中提示）。
            self._status_label.setText("无匹配")
        self._find_next()

    def _document_contains(self, query: str) -> bool:
        """查询是否在当前文档中存在至少一处命中（不移动光标）。"""
        return not self._editor.document().find(query).isNull()

    def _replace_all(self) -> None:
        """替换全部命中（单次撤销单元）；汇总替换数量。"""
        query = self._find_text()
        replace = self._replace_text()
        if not query:
            self._status_label.setText("无匹配")
            return
        doc = self._editor.document()
        count = 0
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        while True:
            found = doc.find(query, cursor)
            if found.isNull():
                break
            found.insertText(replace)
            count += 1
            cursor = found
        cursor.endEditBlock()
        if count == 0:
            self._status_label.setText("无匹配")
        else:
            self._status_label.setText("已替换 {0} 处".format(count))
        self._update_highlights()

    # --- 拼写检查 ---

    def _scan_spelling(self) -> None:
        """按可见行重扫拼写错误并画红色波浪下划线（去抖 + 只扫可见行）。"""
        if self._spell_checker is None:
            return
        doc = self._editor.document()
        first_block = self._editor.firstVisibleBlock()
        if not first_block.isValid():
            self._spell_selections = []
            self._apply_extra_selections()
            return
        # 围栏状态：从文档首行推进到首个可见行（围栏内的英文不检查）。
        in_code = False
        block = doc.firstBlock()
        while block.isValid() and block != first_block:
            if _FENCE_RE.match(block.text().strip()):
                in_code = not in_code
            block = block.next()
        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        fmt.setUnderlineColor(QColor("#d64541"))
        selections = []
        base_top = self._editor.blockBoundingGeometry(first_block).translated(
            self._editor.contentOffset()
        ).top()
        block = first_block
        while block.isValid():
            top = self._editor.blockBoundingGeometry(block).translated(
                self._editor.contentOffset()
            ).top()
            if top > base_top + self._editor.viewport().height():
                break
            line_text = block.text()
            if _FENCE_RE.match(line_text.strip()):
                in_code = not in_code
            elif not in_code:
                base_offset = block.position()
                for hit in self._spell_checker.check_line(line_text, base_offset):
                    cursor = QTextCursor(doc)
                    cursor.setPosition(hit.start)
                    cursor.setPosition(hit.end, QTextCursor.MoveMode.KeepAnchor)
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    selection.format = fmt
                    selections.append(selection)
            block = block.next()
        self._spell_selections = selections
        self._apply_extra_selections()

    def _on_add_word_to_dict(self, word: str) -> None:
        """「加入词典」：写入用户词典并立即重扫，该词不再被标记。"""
        if self._user_dict is not None:
            self._user_dict.add(word)
        self._spell_checker.add_user_word(word)
        self._status_label.setText("已加入词典：{0}".format(word))
        self._spell_timer.start(0)

    # --- 代码片段 ---

    def insert_snippet(self, snippet) -> bool:
        """把片段模板写入光标处，选中第一个占位符并激活 Tab 跳转。"""
        if not self._writable:
            return False
        text, placeholders = expand_placeholders(snippet.body)
        if not text:
            return False
        editor = self._editor
        cursor = editor.textCursor()
        start = cursor.position()
        cursor.beginEditBlock()
        cursor.insertText(text)
        cursor.endEditBlock()
        specs = [(start + p.start, start + p.end, p.default) for p in placeholders]
        editor.begin_snippet(specs)
        if specs:
            sel = editor.textCursor()
            sel.setPosition(specs[0][0])
            sel.setPosition(specs[0][1], QTextCursor.MoveMode.KeepAnchor)
            editor.setTextCursor(sel)
        self._status_label.setText("已插入片段：{0}".format(snippet.trigger))
        return True

    def open_snippet_manager(self) -> None:
        """打开代码片段管理器对话框（增删改 + 预览）。"""
        from doc_tool.ui.content.snippet_dialog import SnippetDialog

        dialog = SnippetDialog(self._snippet_store, parent=self)
        dialog.insert_requested.connect(self.insert_snippet)
        dialog.exec()

    # --- Markdown 工具栏 ---

    def wrap_selection(self, prefix: str, suffix: str) -> None:
        """包裹选中文本（无选中则在光标处插入前后缀，光标停中间）；进撤销栈。"""
        if not self._writable:
            return
        editor = self._editor
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            cursor.setPosition(end)
            cursor.insertText(suffix)
            cursor.setPosition(start)
            cursor.insertText(prefix)
            cursor.setPosition(end + len(prefix) + len(suffix))
        else:
            cursor.insertText(prefix + suffix)
            cursor.setPosition(cursor.position() - len(suffix))
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def insert_template(self, text: str, cursor_offset: int = 0) -> None:
        """在光标处插入模板并把光标移动到 ``cursor_offset`` 处；进撤销栈。"""
        if not self._writable:
            return
        editor = self._editor
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        start = cursor.position()
        cursor.insertText(text)
        if cursor_offset:
            cursor.setPosition(start + cursor_offset)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _prefix_lines(self, prefix: str) -> None:
        """给选区覆盖的每一行（无选区则当前行）行首加前缀。"""
        if not self._writable:
            return
        editor = self._editor
        cursor = editor.textCursor()
        doc = editor.document()
        start_block = doc.findBlock(cursor.selectionStart())
        end_block = doc.findBlock(cursor.selectionEnd())
        cursor.beginEditBlock()
        block = start_block
        while True:
            block_cursor = QTextCursor(block)
            block_cursor.insertText(prefix)
            if block == end_block:
                break
            block = block.next()
        cursor.endEditBlock()

    def _toolbar_heading(self) -> None:
        self._prefix_lines("## ")

    def _insert_table(self) -> None:
        """插入管道表格骨架并定位到首单元格。"""
        self.insert_template(
            "| 列1 | 列2 |\n| --- | --- |\n|  |  |",
            cursor_offset=2,
        )

    def format_table_at_cursor(self) -> bool:
        """格式化光标所在的连续表格并接入撤销栈（Ctrl+Alt+T）。"""
        if not self._writable:
            return False
        cursor = self._editor.textCursor()
        block_idx = cursor.blockNumber()
        doc = self._editor.document()
        lines = [doc.findBlockByNumber(i).text() for i in range(doc.blockCount())]
        from doc_tool.application.content.table_format import (
            find_table_range_at_line,
            format_markdown_table,
        )

        rng = find_table_range_at_line(lines, block_idx)
        if rng is None:
            self._status_label.setText("光标所在行未检测到连续表格")
            return False

        start, end = rng
        sub_lines = lines[start:end + 1]
        formatted = format_markdown_table(sub_lines)

        start_block = doc.findBlockByNumber(start)
        end_block = doc.findBlockByNumber(end)

        start_pos = start_block.position()
        end_pos = end_block.position() + len(end_block.text())

        c = QTextCursor(doc)
        c.setPosition(start_pos)
        c.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        c.beginEditBlock()
        c.insertText(formatted)
        c.endEditBlock()
        self._editor.setTextCursor(c)

        self._status_label.setText("已美化表格（第 {0} ~ {1} 行）".format(start + 1, end + 1))
        return True

    def _insert_link(self) -> None:
        if self._editor.textCursor().hasSelection():
            self.wrap_selection("[", "](链接)")
        else:
            self.insert_template("[文本](链接)")

    def _on_insert_image(self) -> None:
        """图片按钮：打开文件选择并导入资源（复用 asset_manager）。"""
        if not self._writable:
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "插入图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;全部文件 (*)",
        )
        if path:
            self.import_image(path)

    # --- 图片资源导入（粘贴/拖放/按钮共用） ---

    def import_image(self, image_data) -> bool:
        """导入图片到资源目录并插入 Markdown 引用；只读项目拒绝。

        ``image_data`` 可为 QImage（剪贴板）、图片文件路径（拖放）或图片字节。
        """
        if not self._writable:
            self._status_label.setText("只读项目无法导入图片")
            return False
        if self._assets_root is None:
            self._status_label.setText("无法导入图片：资源目录未配置")
            return False
        try:
            data, ext = self._image_bytes(image_data)
            from doc_tool.application.content.asset_manager import import_image_data

            doc_type = self._document_type()
            rel_target, width_px, height_px = import_image_data(
                data, self._assets_root, doc_type, ext
            )
        except Exception as exc:  # noqa: BLE001
            self._status_label.setText("导入图片失败：{0}".format(exc))
            return False
        size_suffix = ""
        if width_px and height_px:
            size_suffix = " ={0}x{1}".format(width_px, height_px)
        self.insert_template("![图]({0}{1})".format(rel_target, size_suffix))
        self._status_label.setText("已导入图片：{0}".format(rel_target))
        return True

    @staticmethod
    def _image_bytes(image_data):
        """把 QImage / 路径 / 字节归一化为 (data, ext)。"""
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage

        if isinstance(image_data, (bytes, bytearray)):
            return bytes(image_data), "png"
        if isinstance(image_data, str):
            with open(image_data, "rb") as handle:
                data = handle.read()
            ext = os.path.splitext(image_data)[1].lstrip(".") or "png"
            return data, ext
        if isinstance(image_data, QImage):
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image_data.save(buffer, "PNG")
            return bytes(buffer.data()), "png"
        raise TypeError("不支持的图片数据：{0}".format(type(image_data).__name__))

    def _document_type(self) -> str:
        """从当前文件 rel_path 首段推导文档类型（与预览 base url 一致）。"""
        if self._rel_path:
            first = self._rel_path.replace("\\", "/").split("/", 1)[0]
            if first in ("requirement", "design", "general"):
                return first
        return "general"

    # --- Mermaid 图形工作台 ---

    def open_mermaid_workbench(self, source: Optional[str] = None, block=None) -> bool:
        """打开工作台；成功导出后插入引用或替换原源码块。"""
        if not self._writable or self._assets_root is None:
            self._status_label.setText("只读项目或资源目录未配置，无法导出 Mermaid")
            return False
        from PySide6.QtWidgets import QDialog
        from doc_tool.application.content.mermaid import export_png, image_reference
        from doc_tool.ui.content.mermaid_dialog import MermaidDialog

        dialog = MermaidDialog(source or "flowchart TD\n  A[开始] --> B[结束]", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.action:
            return False
        try:
            target = export_png(dialog.render_result, self._assets_root, self._document_type())
            reference = image_reference(target, dialog.render_result)
        except (OSError, ValueError) as exc:
            self._status_label.setText("Mermaid 导出失败：{0}".format(exc))
            return False
        if dialog.action == "replace" and block is not None:
            doc = self._editor.document()
            start = doc.findBlockByNumber(block.start_line - 1).position()
            end_block = doc.findBlockByNumber(block.end_line - 1)
            end = end_block.position() + max(0, end_block.length() - 1)
            cursor = self._editor.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(reference)
            self._editor.setTextCursor(cursor)
        else:
            self.insert_template(reference)
        self._status_label.setText("Mermaid 已导出：{0}".format(target))
        return True

    def _open_mermaid_at_position(self, position: int) -> None:
        from doc_tool.application.content.mermaid import extract_blocks

        line = self._editor.document().findBlock(position).blockNumber() + 1
        blocks = extract_blocks(self._editor.toPlainText())
        block = next((item for item in blocks if item.start_line <= line <= item.end_line), None)
        if block is None:
            self.open_mermaid_workbench()
        else:
            self.open_mermaid_workbench(block.source, block)

    def batch_convert_mermaid(self) -> None:
        """转换当前文档中既有 Mermaid 源码，保留失败项并汇总。"""
        if not self._writable or self._assets_root is None:
            return
        from doc_tool.application.content.mermaid import (
            batch_convert,
            export_png,
            image_reference,
        )

        def exporter(_block, result):
            target = export_png(result, self._assets_root, self._document_type())
            return image_reference(target, result)

        # 仅转换历史遗留的裸 flowchart/sequenceDiagram 源码（围栏块属现代写法，
        # 阅读预览已渲染，不在批量转换范围内）。批量优先 mermaid-cli（若已安装，
        # 单块约 1~3s，用户主动触发可接受）；未安装 mmdc 时自动回退内置渲染器，
        # 行为与之前完全一致。
        converted = batch_convert(
            self._editor.toPlainText(), exporter, include_fenced=False, use_cli=True
        )
        if converted.success_count:
            cursor = self._editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(converted.text)
            cursor.endEditBlock()
            self._editor.setTextCursor(cursor)
        if converted.failures:
            details = "；".join(
                "第 {0} 行 {1}".format(item.line, item.message)
                for item in converted.failures[:3]
            )
            self._status_label.setText(
                "Mermaid 批量转换：成功 {0}，失败 {1}（{2}）".format(
                    converted.success_count, len(converted.failures), details
                )
            )
        else:
            self._status_label.setText(
                "Mermaid 批量转换完成：成功 {0}".format(converted.success_count)
            )

    # --- 预览双向定位 ---

    def _on_preview_anchor_clicked(self, url: QUrl) -> None:
        """预览点击：line-N → 定位源行并临时高亮；http(s) → 系统浏览器。"""
        href = url.toString()
        if href.startswith("line-"):
            try:
                line_no = int(href[len("line-"):])
            except ValueError:
                return
            self.highlight_line(line_no)
            self._flash_line(line_no)
        elif href.startswith(("http://", "https://", "mailto:")):
            QDesktopServices.openUrl(url)

    def _flash_line(self, line_no: int) -> None:
        """给指定源行加短暂黄色背景高亮（500ms 后清除）。"""
        block = self._editor.document().findBlockByNumber(max(0, line_no - 1))
        if not block.isValid():
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#fff3b0"))
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(block)
        selection.cursor.setPosition(block.position())
        selection.cursor.setPosition(
            block.position() + block.length() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        selection.format = fmt
        self._flash_selection = selection
        self._apply_extra_selections()
        self._flash_timer.start(500)

    def _clear_flash(self) -> None:
        self._flash_selection = None
        self._apply_extra_selections()

    # --- 预览折叠 / 同步滚动 ---

    def _toggle_preview(self) -> None:
        """切换预览区显示/隐藏。"""
        visible = self._preview_frame.isHidden()
        self._preview_frame.setVisible(visible)
        self._preview_btn.setText("隐藏预览" if visible else "显示预览")

    def _sync_preview_scroll(self) -> None:
        """编辑滚动时按当前光标所在标题把预览滚动到对应源行（单向 best-effort）。"""
        if self._preview_frame.isHidden():
            return
        heading_line = self._current_heading_line()
        if heading_line is not None:
            self._scroll_preview_to_anchor("line-{0}".format(heading_line))
        # 兼容旧文档/旧 Qt HTML 中锚点定位不稳定的情形：按标题文本再定位一次。
        heading_text = self._current_heading_text()
        if heading_text:
            cursor = self._preview.document().find(heading_text)
            if not cursor.isNull():
                self._preview.setTextCursor(cursor)
                self._preview.ensureCursorVisible()

    def _current_heading_line(self) -> Optional[int]:
        """从光标所在块向上找最近的 Markdown 标题，返回其源行号（1-based）。"""
        block = self._editor.textCursor().block()
        while block.isValid():
            text = block.text().strip()
            if text.startswith("#"):
                return block.blockNumber() + 1
            block = block.previous()
        return None

    def _current_heading_text(self) -> Optional[str]:
        """返回光标上方最近标题的纯文本（兼容标题定位与既有调用方）。"""
        block = self._editor.textCursor().block()
        while block.isValid():
            text = block.text().strip()
            match = re.match(r"^#{1,6}\s+(.*?)\s*$", text)
            if match is not None:
                return match.group(1)
            block = block.previous()
        return None

    def _scroll_preview_to_anchor(self, anchor: str) -> None:
        """在预览中滚动到指定块锚点（line-N）并定位光标。"""
        self._preview.scrollToAnchor(anchor)

    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._apply_edit_state()
        self._update_save_state()
        if not writable:
            # 只读项目不写草稿：停掉待触发的草稿定时器。
            self._draft_timer.stop()

    def is_writable(self) -> bool:
        return self._writable

    def current_rel_path(self) -> Optional[str]:
        return self._rel_path

    def is_dirty(self) -> bool:
        return self._dirty

    # --- 会话状态读写（供会话快照/恢复） ---

    def scroll_position(self) -> int:
        """当前编辑器的垂直滚动位置。"""
        return self._editor.verticalScrollBar().value()

    def set_scroll_position(self, position: int) -> None:
        self._editor.verticalScrollBar().setValue(max(0, int(position)))

    def preview_enabled(self) -> bool:
        """预览区是否可见。"""
        return not self._preview_frame.isHidden()

    def set_preview_enabled(self, enabled: bool) -> None:
        visible = bool(enabled)
        self._preview_frame.setVisible(visible)
        self._preview_btn.setText("隐藏预览" if visible else "显示预览")

    def stop_autosave(self) -> None:
        """停止待触发的草稿写入（标签关闭/清理时调用，防止对已销毁控件写入）。"""
        self._draft_timer.stop()

    def showEvent(self, event) -> None:
        """显示时（标签切换/首次打开）重扫拼写，确保波浪线在可见后出现。"""
        super().showEvent(event)
        self._spell_timer.start(0)

    # --- 内部 ---

    def _on_edit(self) -> None:
        self._dirty = True
        self._update_dirty()
        self._update_save_state()
        if self._find_bar.isVisible():
            self._update_highlights()
        self._preview_timer.stop()
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)
        # 拼写检查独立去抖（只扫可见行，控制大文档开销）。
        self._spell_timer.stop()
        self._spell_timer.start(_SPELL_DEBOUNCE_MS)
        # 草稿写入独立去抖：编辑停止一段时间后落盘最近内容。
        self._draft_timer.stop()
        self._draft_timer.start(_DRAFT_DEBOUNCE_MS)

    def _write_draft(self) -> None:
        """草稿去抖触发：writable 且脏时把当前文本写入 .state/autosave/。

        草稿写入失败不阻断编辑/保存，但必须提示用户——自动草稿是崩溃恢复的
        唯一保护，静默失败会让用户在崩溃后丢失未保存内容而毫无预警。
        """
        if not self._writable or self._rel_path is None or not self._dirty:
            return
        if self._autosave is None:
            return
        try:
            self._autosave.write(self._rel_path, self._editor.toPlainText())
            if self._draft_failed:
                self._draft_failed = False
                self._status_label.setText("自动草稿已恢复写入")
        except Exception:  # noqa: BLE001  # 草稿写入失败不影响编辑/保存
            if not self._draft_failed:
                self._draft_failed = True
                self._status_label.setText("⚠ 自动草稿保存失败，请手动保存以防丢失")

    def _update_dirty(self) -> None:
        if self._dirty:
            self._dirty_label.setText(
                "● 恢复自草稿" if self._draft_loaded else "● 未保存"
            )
        else:
            self._dirty_label.setText("")
        if self._on_dirty_changed is not None:
            self._on_dirty_changed(self._dirty)

    def _schedule_preview(self) -> None:
        self._refresh_preview(self._editor.toPlainText())

    def _refresh_preview(self, text: str) -> None:
        document = self._preview.document()
        document.setBaseUrl(self._preview_base_url())
        document.setHtml(render_markdown_html(text, dark=self._dark))
        self._preview.moveCursor(QTextCursor.MoveOperation.Start)

    def set_dark(self, dark: bool) -> None:
        """更新暗黑模式状态并刷新当前预览。"""
        if self._dark != dark:
            self._dark = dark
            self._refresh_preview(self._editor.toPlainText())

    def _preview_base_url(self) -> QUrl:
        """返回当前文档图片等相对资源的解析目录。"""
        if self._rel_path is not None and self._assets_root is not None:
            document_type = self._rel_path.replace("\\", "/").split("/", 1)[0]
            base = self._assets_root / document_type
        elif self._rel_path is not None:
            base = self._writer_abs(self._rel_path).parent
        else:
            base = self._writer.resolve(".")
        return QUrl.fromLocalFile(str(base) + os.sep)

    def _apply_edit_state(self) -> None:
        self._editor.setReadOnly(not self._writable)
        if hasattr(self, "_md_toolbar"):
            self._md_toolbar.setEnabled(self._writable)

    def _update_save_state(self) -> None:
        can = self._writable and self._rel_path is not None
        self._save_btn.setEnabled(can and self._dirty)
        self._rollback_btn.setEnabled(can)
        self._ext_btn.setEnabled(self._rel_path is not None)

    def _file_mtime(self, rel_path: str) -> Optional[float]:
        target = self._writer_abs(rel_path)
        try:
            return target.stat().st_mtime
        except OSError:
            return None

    def _writer_abs(self, rel_path: str):
        return self._writer.resolve(rel_path)
