# -*- coding: utf-8 -*-
"""右侧常驻「任务 / 结果」Dock 容器。

三态：
- 空闲：最近结果卡片（成功提供打开产物/目录/报告；失败显示原因与建议）
  或引导卡片（校验 / 诊断构建入口）。
- 运行：步骤清单（图标+文字、当前步骤高亮、总体进度、已用时间）+ 当前
  步骤日志流 + 取消入口；心跳任务回退为单一步骤 + 已用时间。
- 终态：结果卡片 + 适用后续操作，失败提供可展开技术详情；步骤清单保留
  终态状态（成功/失败/跳过/取消）。

结果归属校验：项目切换后由主窗口调用 ``clear_result`` 清除不属于当前
项目的结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from doc_tool.ui.work_detail_pane import LogStream, ResultCard
from doc_tool.ui.work_step_list import StepListFooter, WorkStepList
from doc_tool.ui.workbench_state import ResultState, StepItem


class _IdleCard(QFrame):
    """空闲态卡片：最近结果（若有）或引导卡片。"""

    def __init__(
        self,
        *,
        on_validate: Optional[Callable[[], None]] = None,
        on_diag_build: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("cardClass", "result")
        self._on_validate = on_validate
        self._on_diag_build = on_diag_build
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._title = QLabel(self)
        self._title.setObjectName("resultTitle")
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._title)
        layout.addWidget(self._summary)
        layout.addLayout(self._actions)
        layout.addStretch(1)

    def render_recent(self, result: ResultState) -> None:
        """渲染最近一次结果卡片（路径存在性由调用方/ResultCard 语义保证）。"""
        for label in self.findChildren(QLabel):
            if label is not self._title and label is not self._summary:
                label.deleteLater()
        status = result.status
        self._title.setText(
            "✓ {0}".format(result.title or "最近结果")
            if status == "success"
            else "✗ {0}".format(result.title or "最近结果")
        )
        self._title.setProperty("statusTone", {
            "success": "success", "failure": "failure", "cancelled": "warning",
        }.get(status, "neutral"))
        self._summary.setText(result.summary or "")
        self._clear_actions()
        output = result.output_path
        if output and Path(output).is_file():
            self._add_action("打开产物", lambda p=str(output): self._open_output(p))
        report = result.report_path
        if report and Path(report).is_file():
            self._add_action("查看校验报告", lambda: self._open_report())

    def render_guide(self, project_open: bool) -> None:
        """无结果时的引导卡片。"""
        self._title.setText("开始工作")
        self._title.setProperty("statusTone", "neutral")
        self._summary.setText(
            "运行校验或诊断构建后，结果与后续操作会显示在这里。"
            if project_open
            else "打开项目后即可执行校验、构建与合并。"
        )
        self._clear_actions()
        if project_open:
            self._add_action("校验", lambda: self._on_validate())
            self._add_action("诊断构建", lambda: self._on_diag_build())

    def _clear_actions(self) -> None:
        while self._actions.count():
            item = self._actions.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_action(self, text: str, callback: Callable[[], None]) -> None:
        button = QPushButton(text, self)
        button.setProperty("btnRole", "compact")
        button.clicked.connect(callback)
        self._actions.addWidget(button)

    def _open_output(self, path: str) -> None:
        # 路径存在性已校验；由主窗口接线打开。
        from PySide6.QtWidgets import QMessageBox

        try:
            import os

            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        except OSError:
            QMessageBox.warning(self, "无法打开", "产物已不可用：{0}".format(path))

    def _open_report(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        report = self._current_report()
        if report and Path(report).is_file():
            try:
                import os

                os.startfile(report)  # type: ignore[attr-defined]  # noqa: S606
            except OSError:
                QMessageBox.warning(
                    self, "无法打开", "校验报告已不可用：{0}".format(report)
                )

    def _current_report(self) -> Optional[str]:
        return None


class TaskDock(QWidget):
    """右侧任务/结果 Dock。"""

    def __init__(
        self,
        *,
        on_cancel: Optional[Callable[[], None]] = None,
        on_validate: Optional[Callable[[], None]] = None,
        on_diag_build: Optional[Callable[[], None]] = None,
        on_open_output: Optional[Callable[[str], None]] = None,
        on_open_directory: Optional[Callable[[str], None]] = None,
        on_open_report: Optional[Callable[[], None]] = None,
        on_show_tech: Optional[Callable[[], None]] = None,
        on_copy_log: Optional[Callable[[], None]] = None,
        on_open_log_dir: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_cancel = on_cancel
        self._on_validate = on_validate
        self._on_diag_build = on_diag_build
        self._on_open_output = on_open_output
        self._on_open_directory = on_open_directory
        self._on_open_report = on_open_report
        self._on_show_tech = on_show_tech
        self._on_copy_log = on_copy_log
        self._on_open_log_dir = on_open_log_dir
        self._dark = False
        self._has_result = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 标题行
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        self._title = QLabel("任务 / 结果", self)
        self._title.setObjectName("dockTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._elapsed = QLabel("", self)
        self._elapsed.setObjectName("statusMuted")
        header.addWidget(self._elapsed)
        layout.addLayout(header)

        # 三态页面
        self._stack = QStackedWidget(self)

        self._idle_card = _IdleCard(
            on_validate=on_validate, on_diag_build=on_diag_build
        )
        self._stack.addWidget(self._idle_card)

        self._running_page = self._build_running_page()
        self._stack.addWidget(self._running_page)

        self._result_page = self._build_result_page()
        self._stack.addWidget(self._result_page)

        layout.addWidget(self._stack, 1)

    # --- 页面构建 ---

    def _build_running_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        self._step_list = WorkStepList(page)
        layout.addWidget(self._step_list, 3)
        self._step_footer = StepListFooter(page)
        layout.addWidget(self._step_footer)
        self._log_stream = LogStream(
            on_copy=self._on_copy_log,
            on_open_dir=self._on_open_log_dir,
            parent=page,
        )
        layout.addWidget(self._log_stream, 2)

        cancel_row = QHBoxLayout()
        cancel_row.setContentsMargins(0, 0, 0, 0)
        self._cancel_status = QLabel("", page)
        self._cancel_status.setObjectName("statusMuted")
        cancel_row.addWidget(self._cancel_status)
        cancel_row.addStretch(1)
        self._cancel_btn = QPushButton("取消", page)
        self._cancel_btn.setProperty("btnRole", "primary")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._handle_cancel)
        cancel_row.addWidget(self._cancel_btn)
        layout.addLayout(cancel_row)
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        self._result_card = ResultCard(
            on_open_output=self._on_open_output,
            on_open_directory=self._on_open_directory,
            on_open_report=self._on_open_report,
            on_show_tech=self._on_show_tech,
            parent=page,
        )
        layout.addWidget(self._result_card)
        self._result_steps = WorkStepList(page)
        self._result_steps.setMaximumHeight(220)
        layout.addWidget(self._result_steps)
        self._result_log = LogStream(
            on_copy=self._on_copy_log,
            on_open_dir=self._on_open_log_dir,
            parent=page,
        )
        layout.addWidget(self._result_log, 1)
        return page

    # --- 状态切换 ---

    def show_idle(self, result: Optional[ResultState], project_open: bool) -> None:
        """空闲态：渲染最近结果卡片（属于当前项目）或引导卡片。"""
        self._stack.setCurrentWidget(self._idle_card)
        self._title.setText("任务 / 结果")
        self._elapsed.setText("")
        if result is not None and result.project_root:
            self._idle_card.render_recent(result)
        else:
            self._idle_card.render_guide(project_open)
        self._has_result = bool(result)

    def show_running(
        self,
        task_label: str,
        steps: List[StepItem],
        current_stage: str = "",
        elapsed: int = 0,
    ) -> None:
        """运行态：步骤清单 + 日志流 + 取消入口。"""
        self._stack.setCurrentWidget(self._running_page)
        self._title.setText("正在运行：{0}".format(task_label))
        self._step_list.set_steps(steps, current_stage)
        done = sum(
            1
            for s in steps
            if s.status
            in ("success", "skipped", "failed", "cancelled")
        )
        self._step_footer.set_progress(done, len(steps))
        self._step_footer.set_elapsed(elapsed)
        self._cancel_btn.setEnabled(True)
        self._cancel_status.setText("")

    def show_result(self, task_label: str, result: ResultState, steps: List[StepItem]) -> None:
        """终态：结果卡片 + 后续操作 + 保留终态步骤清单。"""
        self._stack.setCurrentWidget(self._result_page)
        self._title.setText("任务结果：{0}".format(task_label))
        self._elapsed.setText("")
        self._result_card.render(result)
        self._result_steps.set_steps(steps)
        self._has_result = True

    # --- 运行期控件 ---

    def append_log(self, line: str) -> None:
        """追加日志到当前可见的日志视图。"""
        self._log_stream.append_line(line)
        self._result_log.append_line(line)

    def set_log_lines(self, lines: List[str]) -> None:
        self._log_stream.set_lines(lines)
        self._result_log.set_lines(lines)

    def clear_log(self) -> None:
        self._log_stream.clear()
        self._result_log.clear()

    def set_cancel_waiting(self, waiting: bool, stage_label: str = "") -> None:
        """取消请求已接收，等待安全阶段边界。"""
        self._cancel_btn.setEnabled(not waiting)
        if waiting:
            self._cancel_status.setText(
                "等待安全停止点（{0}）…".format(stage_label) if stage_label else "正在取消…"
            )
        else:
            self._cancel_status.setText("")

    def set_elapsed(self, seconds: int) -> None:
        self._elapsed.setText("已用时间 {0:02d}:{1:02d}".format(seconds // 60, seconds % 60))
        self._step_footer.set_elapsed(seconds)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._step_list.set_dark(dark)
        self._result_steps.set_dark(dark)

    def clear_result(self) -> None:
        """项目切换后清除不属于当前项目的结果（结果归属校验）。"""
        self._has_result = False
        self.show_idle(None, project_open=False)

    def has_result(self) -> bool:
        return self._has_result

    # --- 内部 ---

    def _handle_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()
