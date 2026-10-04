# -*- coding: utf-8 -*-
"""MAIN2-C 3.3：所选章节批量复制/移动的预览与逐项结果对话框。

第二个批量对话框（第一个是 ``refactor_panel`` 的单文件重命名/重编号预览）：
本对话框只负责**真实目标摘要 + 逐项结果**的展示与目标目录选择，实际写盘
全部交给 ``batch_chapter_ops``（内部复用 ``copy_chapter`` / ``RefactorService``）。
取消不写任何文件；应用后逐项结果就地可读，失败项不隐藏。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.content.batch_chapter_ops import (
    KIND_LABELS,
    BatchChapterItem,
    BatchChapterPlan,
    plan_batch_chapters,
)


def _normalized(value: str) -> str:
    """统一 POSIX 相对路径；与批量服务保持同一口径。"""
    return str(value or "").replace(chr(92), "/").strip("/")


def directory_options(sources: Sequence[str], files: Sequence[str]) -> List[str]:
    """可选目标目录：内容根 + 既有目录（排除所选章节自身子树）。"""
    excluded = {_normalized(source) for source in sources if source}
    roots = sorted(
        {""}
        | {
            str(Path(rel).parent.as_posix())
            for rel in files
            if Path(rel).parent.as_posix() != "."
        }
    )
    options: List[str] = []
    for candidate in roots:
        if candidate == "":
            options.append("")
            continue
        if any(
            candidate == node or candidate.startswith(node + "/")
            for node in excluded
        ):
            continue
        options.append(candidate)
    return options


class BatchChapterDialog(QDialog):
    """批量复制/移动：选定目标目录 → 预览真实目标 → 确认执行 → 逐项结果。"""

    def __init__(
        self,
        index,
        sources: Sequence[str],
        kind: str,
        *,
        writer,
        source_text=None,
        generation=None,
        refresh_index=None,
        apply: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._writer = writer
        self._sources = [str(source) for source in sources if source]
        self._kind = kind
        self._source_text = source_text
        self._generation = generation
        self._refresh_index = refresh_index
        self._apply = apply
        self._plan: Optional[BatchChapterPlan] = None
        self._results: List[BatchChapterItem] = []

        self.setWindowTitle("{0}（{1} 个章节）".format(
            KIND_LABELS.get(kind, kind), len(self._sources)
        ))
        self.resize(860, 480)

        outer = QVBoxLayout(self)

        picker = QHBoxLayout()
        picker.addWidget(QLabel("目标目录：", self))
        self._dir_box = QComboBox(self)
        self._dir_box.setEditable(False)
        self._files = list(index.all_files()) if index is not None else []
        for option in directory_options(self._sources, self._files):
            self._dir_box.addItem(option or "（内容根目录）", option)
        default = self._default_dir()
        index_of_default = self._dir_box.findData(default)
        self._dir_box.setCurrentIndex(index_of_default if index_of_default >= 0 else 0)
        self._dir_box.currentIndexChanged.connect(self.refresh_plan)
        picker.addWidget(self._dir_box, 1)
        outer.addLayout(picker)

        self._summary = QLabel("", self)
        self._summary.setObjectName("statusMuted")
        self._summary.setWordWrap(True)
        outer.addWidget(self._summary)

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["所选章节", "真实目标", "状态"])
        self._tree.setColumnWidth(0, 320)
        self._tree.setColumnWidth(1, 320)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        outer.addWidget(self._tree, 1)

        buttons = QDialogButtonBox(self)
        self._ok_btn = QPushButton("确认并执行", self)
        self._ok_btn.setProperty("btnRole", "primary")
        self._ok_btn.clicked.connect(self._on_confirm)
        buttons.addButton(self._ok_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = QPushButton("取消", self)
        cancel.setProperty("btnRole", "secondary")
        cancel.clicked.connect(self.reject)
        buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        outer.addWidget(buttons)

        self.refresh_plan()

    # --- 状态 ---

    def _default_dir(self) -> str:
        parents = {str(Path(_normalized(source)).parent.as_posix()) for source in self._sources}
        parents = {"" if parent == "." else parent for parent in parents}
        if len(parents) == 1:
            return next(iter(parents))
        return ""

    def _content_root(self):
        """内容根：优先取写入服务的解析根，取不到时退回 None（退化为前缀判定）。"""
        resolve = getattr(self._writer, "resolve", None)
        if callable(resolve):
            try:
                return resolve("")
            except Exception:  # noqa: BLE001 - 解析失败退化为前缀判定
                return None
        return None

    def current_dir(self) -> str:
        return str(self._dir_box.currentData() or "")

    def plan(self) -> Optional[BatchChapterPlan]:
        return self._plan

    def results(self) -> List[BatchChapterItem]:
        return list(self._results)

    def summary_text(self) -> str:
        return self._summary.text()

    def target_lines(self) -> List[str]:
        plan = self._plan
        return plan.target_lines() if plan is not None else []

    def result_lines(self) -> List[str]:
        return [item.summary_line() for item in self._results]

    # --- 行为 ---

    def refresh_plan(self, _index: int = 0) -> BatchChapterPlan:
        """按当前目标目录重算真实目标，并把每项写盘前摘要渲染出来。"""
        self._plan = plan_batch_chapters(
            self._index,
            self._sources,
            self._kind,
            dest_dir=self.current_dir(),
            content_root=self._content_root(),
            generation=self._generation() if self._generation is not None else None,
        )
        self._render_plan()
        return self._plan

    def _render_plan(self) -> None:
        plan = self._plan
        self._tree.clear()
        if plan is None:
            return
        for item in plan.items:
            status = "将写入" if item.ok else "跳过：{0}".format(item.message or "无效项")
            row = QTreeWidgetItem(
                [
                    item.source,
                    item.target if item.ok else "",
                    status,
                ]
            )
            if not item.ok:
                row.setForeground(2, Qt.GlobalColor.darkYellow)
            self._tree.addTopLevelItem(row)
        self._summary.setText(plan.summary_text())
        self._ok_btn.setEnabled(bool(plan.actionable()))
        self._ok_btn.setText(
            "确认并执行（{0} 项）".format(len(plan.actionable()))
            if plan.actionable()
            else "无可执行项"
        )

    def _on_confirm(self) -> None:
        if self._plan is None or not self._plan.actionable():
            return
        if self._apply:
            from doc_tool.application.content.batch_chapter_ops import apply_batch_plan

            self._results = apply_batch_plan(
                self._plan,
                self._index,
                self._writer,
                source_text=self._source_text,
                generation=self._generation,
                refresh_index=self._refresh_index,
            )
            self._render_results()
        self.accept()

    def _render_results(self) -> None:
        """应用后就地展示逐项结果（成功/跳过原因都真实可读）。"""
        self._tree.clear()
        for item in (self._plan.items if self._plan else []):
            row = QTreeWidgetItem(
                [
                    item.source,
                    item.target,
                    "已完成" if item.ok else "跳过：{0}".format(item.message or "未完成"),
                ]
            )
            if not item.ok:
                row.setForeground(2, Qt.GlobalColor.darkYellow)
            self._tree.addTopLevelItem(row)
        done = sum(1 for item in self._results if item.ok)
        self._summary.setText(
            "{0}：{1}/{2} 项成功".format(
                KIND_LABELS.get(self._kind, self._kind), done, len(self._plan.items)
            )
            if self._plan
            else ""
        )
        self._ok_btn.setEnabled(False)
        self._ok_btn.setText("已完成")
        self._apply = False