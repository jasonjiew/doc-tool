# -*- coding: utf-8 -*-
"""模板填充向导：Word 底模 + 多个 Markdown（按列表顺序合并）→ 单个 Word。

与「文档互转」的关系：互转中心按「每个 Markdown 一个 Word」逐文件填充；
本对话框面向「一份底模、多份 Markdown 按顺序合并为同一文档」的成稿场景
（长文档分章编写后一次性合成正式交付物），调用同一离线服务
``template_fill.fill_markdown_with_template``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QInputDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc_tool.application.convert import error_resolution_guide
from doc_tool.domain.errors import DocToolError
from doc_tool.application.template_fill import (
    TemplateStyles,
    fill_markdown_with_template,
    load_last_template,
    parse_template_styles,
    save_last_template,
)
from doc_tool.ui.task_bridge import POLL_INTERVAL_MS, TaskRunner, TaskSpec
from doc_tool.ui.template_style_map_dialog import TemplateStyleMapDialog

MARKDOWN_FILTER = "Markdown 文档 (*.md *.markdown)"
_DOCX_FILTER = "Word 文档 (*.docx)"


class TemplateFillDialog(QDialog):
    """底模 + Markdown 列表 → 单个 Word（离线，无需本机 Word）。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        busy_check=None,
        paths: Optional[List[Path]] = None,
    ) -> None:
        super().__init__(parent)
        self._busy_check = busy_check
        self._runner = TaskRunner()
        self._style_map: Optional[Dict[str, int]] = None
        self._parsed_styles: Optional[TemplateStyles] = None
        self._parsed_source: Optional[str] = None
        self._name_edited = False
        self._last_output: Optional[Path] = None

        self.setWindowTitle("Markdown 模板填充（底模出稿）")
        self.resize(760, 560)
        self.setMinimumSize(640, 480)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        from doc_tool.application.template_fill_presets import TemplateFillPresets
        self._presets = TemplateFillPresets()
        preset_row = QHBoxLayout()
        self._recipe_combo = QComboBox()
        self._recipe_combo.addItem("上次设置 / 未命名", None)
        for recipe in self._presets.recipes:
            self._recipe_combo.addItem(recipe.get('name', '未命名'), recipe)
        preset_row.addWidget(self._recipe_combo, 1)
        for title, callback in [('保存/编辑预设', self._save_recipe), ('删除预设', self._delete_recipe), ('最近任务/再次生成', self._show_jobs)]:
            btn = QPushButton(title)
            btn.clicked.connect(callback)
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

        # 1. 底模选择
        template_row = QHBoxLayout()
        template_row.setSpacing(8)
        template_row.addWidget(QLabel("Word 底模：", self))
        self._template_edit = QLineEdit(self)
        self._template_edit.setClearButtonEnabled(True)
        self._template_edit.setPlaceholderText("选择 .docx 底模：样式、封面、页眉与标题编号将原样保留")
        self._template_edit.textChanged.connect(self._on_template_changed)
        template_row.addWidget(self._template_edit, 1)
        browse = QPushButton("选择底模…", self)
        browse.setProperty("btnRole", "secondary")
        browse.clicked.connect(self._on_choose_template)
        template_row.addWidget(browse)
        self._style_map_btn = QPushButton("样式映射…", self)
        self._style_map_btn.setProperty("btnRole", "secondary")
        self._style_map_btn.setEnabled(False)
        self._style_map_btn.clicked.connect(self._on_open_style_map)
        template_row.addWidget(self._style_map_btn)
        layout.addLayout(template_row)

        # 2. Markdown 文件列表（顺序即章节顺序）与操作按钮
        files_row = QHBoxLayout()
        self._file_list = QListWidget(self)
        self._file_list.setToolTip("按列表自上而下顺序合并为同一文档的连续章节")
        files_row.addWidget(self._file_list, 1)
        buttons = QVBoxLayout()
        self._add_btn = QPushButton("添加 Markdown…", self)
        self._add_btn.setProperty("btnRole", "secondary")
        self._add_btn.clicked.connect(self._on_add_files)
        self._remove_btn = QPushButton("移除选中", self)
        self._remove_btn.clicked.connect(self._on_remove_selected)
        self._up_btn = QPushButton("上移", self)
        self._up_btn.clicked.connect(lambda: self._on_move(-1))
        self._down_btn = QPushButton("下移", self)
        self._down_btn.clicked.connect(lambda: self._on_move(1))
        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.clicked.connect(self._on_clear_files)
        for button in (self._add_btn, self._remove_btn, self._up_btn, self._down_btn, self._clear_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        files_row.addLayout(buttons)
        layout.addLayout(files_row, 1)

        # 3. 输出目录与文件名
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        out_row.addWidget(QLabel("输出到：", self))
        self._output_edit = QLineEdit(self)
        self._output_edit.setClearButtonEnabled(True)
        self._output_edit.setPlaceholderText("留空 = 与第一个 Markdown 同目录")
        out_row.addWidget(self._output_edit, 1)
        out_browse = QPushButton("浏览…", self)
        out_browse.clicked.connect(self._on_choose_output)
        out_row.addWidget(out_browse)
        layout.addLayout(out_row)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(QLabel("输出文件名：", self))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("默认取第一个 Markdown 的文件名")
        self._name_edit.textEdited.connect(lambda: setattr(self, "_name_edited", True))
        name_row.addWidget(self._name_edit, 1)
        layout.addLayout(name_row)

        options_row = QHBoxLayout()
        self._clean_body = QCheckBox("清理底模正文（底模为现成文档时，从第一个标题 1 起移除旧正文）", self)
        self._clean_body.setToolTip(
            "底模里检测到正文标题段落时勾选：出稿前自动清掉旧正文，封面/页眉/样式原样保留。"
        )
        options_row.addWidget(self._clean_body)
        options_row.addStretch(1)
        self._refresh_fields = QCheckBox("出稿后用 Word 刷新目录/域（无 Word 时打开自动刷新）", self)
        options_row.addWidget(self._refresh_fields)
        self._strict = QCheckBox('严格检查（降级时停止）', self)
        options_row.addWidget(self._strict)
        layout.addLayout(options_row)

        # 4. 进度与详情
        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setAcceptDrops(False)
        self._details.setMaximumHeight(120)
        self._details.setPlaceholderText("底模样式解析结论、降级告警与生成结果会列在这里。")
        layout.addWidget(self._details)

        self._status = QLabel("就绪。选择底模并添加 Markdown 后开始生成。", self)
        self._status.setProperty("statusTone", "neutral")
        layout.addWidget(self._status)

        # 5. 底部按钮
        buttons_bar = QDialogButtonBox(self)
        self._run_btn = QPushButton("开始生成", self)
        self._run_btn.setProperty("btnRole", "primary")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        buttons_bar.addButton(self._run_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._open_btn = QPushButton("打开产物", self)
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open_output)
        buttons_bar.addButton(self._open_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._open_folder_btn = QPushButton("打开输出文件夹", self)
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._on_open_output_folder)
        buttons_bar.addButton(self._open_folder_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._cancel_btn = QPushButton("取消", self)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        buttons_bar.addButton(self._cancel_btn, QDialogButtonBox.ButtonRole.DestructiveRole)
        close = buttons_bar.addButton(QDialogButtonBox.StandardButton.Close)
        close.setText("关闭")
        buttons_bar.rejected.connect(self.reject)
        layout.addWidget(buttons_bar)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.setInterval(500)
        self._plan_timer.timeout.connect(self._update_plan)
        self._plan_label = QLabel('生成摘要：添加输入后自动更新。', self)
        self._plan_label.setWordWrap(True)
        layout.addWidget(self._plan_label)
        for edit in (self._template_edit, self._output_edit, self._name_edit):
            edit.textChanged.connect(lambda *_: self._plan_timer.start())
        self._file_list.model().rowsInserted.connect(lambda *_: self._plan_timer.start())
        self._file_list.model().rowsRemoved.connect(lambda *_: self._plan_timer.start())
        self._strict.toggled.connect(lambda *_: self._plan_timer.start())

        # 记忆底模：预填上次使用的 .docx（失效时解析警告会提示）。
        last_template = load_last_template()
        if last_template:
            self._template_edit.setText(last_template)
        self._recipe_combo.currentIndexChanged.connect(self._select_recipe)
        for warning in self._presets.warnings:
            self._details.appendPlainText(warning)

        if paths:
            self._add_files(paths)

    # --- 拖放 ---

    def _settings(self):
        return dict(template=str(self._template_path() or ''), mapping=self._style_map or {},
                    clean=self._clean_body.isChecked(), refresh=self._refresh_fields.isChecked(), strict=self._strict.isChecked(),
                    outputDir=self._output_edit.text(), outputName=self._name_edit.text())

    def _save_recipe(self):
        recipe = self._recipe_combo.currentData()
        name, ok = QInputDialog.getText(self, '预设名称', '名称：', text=recipe.get('name', '') if recipe else '')
        if not ok: return
        try:
            self._presets.save_recipe(name, self._settings(), recipe.get('recipeId') if recipe else None)
            self._reload_recipes()
        except (OSError, ValueError) as exc:
            self._details.appendPlainText('预设保存失败：' + str(exc))

    def _reload_recipes(self):
        self._recipe_combo.blockSignals(True)
        self._recipe_combo.clear()
        self._recipe_combo.addItem('上次设置 / 未命名', None)
        for recipe in self._presets.recipes:
            self._recipe_combo.addItem(recipe.get('name', '未命名'), recipe)
        self._recipe_combo.blockSignals(False)

    def _delete_recipe(self):
        recipe = self._recipe_combo.currentData()
        if recipe:
            try:
                self._presets.delete_recipe(recipe['recipeId'])
                self._reload_recipes()
            except OSError as exc: self._details.appendPlainText(str(exc))

    def _apply_settings(self, values):
        self._template_edit.setText(values.get('template', ''))
        try:
            self._parsed_styles = parse_template_styles(values.get('template', ''))
        except (OSError, ValueError, DocToolError): self._parsed_styles = None
        if self._parsed_styles:
            values = self._presets.resolve_recipe(values, self._parsed_styles)
        self._style_map = values.get('mapping') or None
        self._clean_body.setChecked(bool(values.get('clean')))
        self._refresh_fields.setChecked(bool(values.get('refresh')))
        self._strict.setChecked(bool(values.get('strict')))
        self._output_edit.setText(values.get('outputDir', ''))
        self._name_edit.setText(values.get('outputName', ''))

    def _select_recipe(self, index):
        recipe = self._recipe_combo.itemData(index)
        if recipe: self._apply_settings(recipe)

    def _show_jobs(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('最近 20 次填充任务（非项目正式历史）')
        layout = QVBoxLayout(dialog)
        items = QListWidget()
        items.addItems([job['time'] + ' · ' + job['status'] for job in self._presets.jobs])
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        def selected(row):
            if row >= 0:
                import json
                preview.setPlainText(json.dumps(self._presets.jobs[row], ensure_ascii=False, indent=2))
        items.currentRowChanged.connect(selected)
        layout.addWidget(items)
        layout.addWidget(preview)
        retry = QPushButton('回填选中任务（之后点击开始生成）')
        def refill():
            row = items.currentRow()
            if row < 0: return
            job = self._presets.jobs[row]
            self._apply_settings(job)
            self._file_list.clear()
            self._file_list.addItems([item['path'] for item in job['sources']])
            self._refresh_run_state()
            dialog.accept()
        retry.clicked.connect(refill)
        layout.addWidget(retry)
        dialog.resize(760, 550)
        dialog.exec()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and not self._runner.is_running:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and not self._runner.is_running:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if self._runner.is_running:
            event.ignore()
            return
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            event.acceptProposedAction()
            skipped = [path.name for path in paths if path.suffix.lower() not in (".md", ".markdown")]
            self._add_files(paths)
            if skipped:
                self._details.appendPlainText(
                    "ℹ️ 已忽略非 Markdown 文件：{0}".format("、".join(skipped[:5]))
                )

    # --- 底模 ---

    def _template_path(self) -> Optional[Path]:
        text = self._template_edit.text().strip()
        return Path(text) if text else None

    def _on_choose_template(self) -> None:
        picked, _ = QFileDialog.getOpenFileName(self, "选择 Word 底模", "", _DOCX_FILTER)
        if picked:
            self._template_edit.setText(picked)

    def _on_template_changed(self, text: str) -> None:
        self._style_map_btn.setEnabled(bool(text.strip()))
        self._style_map = None
        self._parsed_styles = None
        self._parsed_source = None
        template = self._template_path()
        if template is None:
            return
        if not template.is_file() or template.suffix.lower() != ".docx":
            self._details.appendPlainText(
                "⚠️ 底模无效（必须是一个存在的 .docx 文件）：{0}".format(template.name)
            )
            return
        try:
            styles = parse_template_styles(template)
        except Exception as exc:
            self._details.appendPlainText("⚠️ 底模无法解析：{0}".format(exc))
            self._clean_body.setChecked(False)
            return
        self._parsed_styles = styles
        self._parsed_source = str(template)
        save_last_template(str(template))
        if styles.raw_heading_styles:
            levels = "、".join(
                "{0} 级→{1}".format(level, style_id)
                for level, style_id in sorted(styles.raw_heading_styles.items())
            )
            self._details.appendPlainText(
                "✓ 底模样式解析成功：标题 {0}；正文样式：{1}。".format(
                    levels, styles.body_style or "（默认正文）"
                )
            )
        else:
            self._details.appendPlainText(
                "⚠️ 底模未识别到标题样式：默认自动匹配，亦可手动设置映射。"
            )
        if styles.body_heading_count > 0:
            self._clean_body.setChecked(True)
            self._details.appendPlainText(
                "⚠️ 底模正文含 {0} 个标题段落，更像一份完整文档：已自动勾选「清理底模正文」，"
                "否则旧正文会混进产物。".format(styles.body_heading_count)
            )
        else:
            self._clean_body.setChecked(False)
        self._refresh_run_state()

    def _on_open_style_map(self) -> None:
        template = self._template_path()
        if template is None:
            return
        if (
            self._parsed_styles is None
            or self._parsed_source != str(template)
        ):
            try:
                styles = parse_template_styles(template)
            except Exception as exc:
                QMessageBox.warning(self, "样式映射", "底模无法解析：{0}".format(exc))
                return
            self._parsed_styles = styles
            self._parsed_source = str(template)
        styles = self._parsed_styles
        if not styles.paragraph_styles:
            QMessageBox.information(self, "样式映射", "该模板没有可映射的段落样式。")
            return
        preset = dict(self._style_map or {})
        if not preset:
            preset = {
                style_id: level
                for level, style_id in styles.raw_heading_styles.items()
            }
        dialog = TemplateStyleMapDialog(styles.paragraph_styles, preset, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._style_map = dialog.mapping()
            if self._style_map:
                self._details.appendPlainText(
                    "✓ 已设置标题样式映射（{0} 个样式），仅对本次生成生效。".format(
                        len(self._style_map)
                    )
                )

    # --- Markdown 列表 ---

    def _md_paths(self) -> List[Path]:
        return [Path(self._file_list.item(i).text()) for i in range(self._file_list.count())]

    def _on_add_files(self) -> None:
        picked, _ = QFileDialog.getOpenFileNames(self, "添加 Markdown 文件", "", MARKDOWN_FILTER)
        self._add_files([Path(item) for item in picked])

    def _add_files(self, paths) -> None:
        added = 0
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in (".md", ".markdown"):
                continue
            if not path.is_file():
                self._details.appendPlainText("⚠️ 文件不存在，已跳过：{0}".format(path))
                continue
            if str(path) in {str(p) for p in self._md_paths()}:
                continue
            self._file_list.addItem(str(path))
            added += 1
        if added:
            self._refresh_output_defaults()
        self._refresh_run_state()

    def _on_remove_selected(self) -> None:
        for item in self._file_list.selectedItems():
            self._file_list.takeItem(self._file_list.row(item))
        self._refresh_output_defaults()
        self._refresh_run_state()

    def _on_move(self, delta: int) -> None:
        row = self._file_list.currentRow()
        if row < 0:
            return
        target = row + delta
        if not 0 <= target < self._file_list.count():
            return
        item = self._file_list.takeItem(row)
        self._file_list.insertItem(target, item)
        self._file_list.setCurrentRow(target)

    def _on_clear_files(self) -> None:
        self._file_list.clear()
        self._name_edited = False
        self._name_edit.clear()
        self._refresh_run_state()

    def _refresh_output_defaults(self) -> None:
        paths = self._md_paths()
        if not paths:
            return
        if not self._name_edited and not self._name_edit.text().strip():
            self._name_edit.setText(paths[0].stem + ".docx")

    def _refresh_run_state(self) -> None:
        self._run_btn.setEnabled(bool(self._md_paths()) and bool(self._template_edit.text().strip()))
        if not self._runner.is_running:
            count = len(self._md_paths())
            self._set_status(
                "已选 {0} 个 Markdown 文件。".format(count) if count else "就绪。选择底模并添加 Markdown 后开始生成。",
                "neutral",
            )

    def _update_plan(self):
        if not self._md_paths() or self._runner.is_running: return
        from doc_tool.application.template_fill_plan import plan_template_fill
        plan = plan_template_fill(self._md_paths(), self._template_path() or '', self._resolve_output(), mapping=self._style_map, strict=self._strict.isChecked())
        self._plan_label.setText(plan.report())

    def _on_choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self._output_edit.setText(folder)

    # --- 生成 ---

    def _resolve_output(self) -> Path:
        """计算产物落点：输出目录（默认第一个 Markdown 同目录）+ 文件名。"""
        files = self._md_paths()
        name = self._name_edit.text().strip() or (files[0].stem + ".docx")
        if not name.lower().endswith(".docx"):
            name += ".docx"
        out_dir = self._output_edit.text().strip() or str(files[0].parent)
        return Path(out_dir) / name

    def _on_run(self) -> None:
        if self._runner.is_running:
            return
        if self._busy_check is not None and self._busy_check():
            QMessageBox.warning(self, "开始生成", "主窗口已有任务正在运行，请等待其完成后再生成。")
            return
        files = self._md_paths()
        template = self._template_path()
        if not files:
            QMessageBox.information(self, "开始生成", "请先添加 Markdown 文件。")
            return
        from doc_tool.application.template_fill_plan import plan_template_fill, execute_template_fill
        plan = plan_template_fill(files, template or '', self._resolve_output(), mapping=self._style_map, strict=self._strict.isChecked())
        self._details.appendPlainText(plan.report())
        if not plan.viable:
            self._set_status('没有可行方案，请查看摘要。', 'failure')
            return
        template = Path(plan.template)
        output = self._resolve_output()
        from doc_tool.application.template_fill_presets import fresh_output
        output = fresh_output(output, files + [template])
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "开始生成", "无法创建输出目录：{0}".format(exc))
            return

        self._job_sources, self._job_settings = files, self._settings()
        self._job_state = 'failed'
        started = self._runner.start(
            TaskSpec(
                name="template_fill",
                target=execute_template_fill,
                args=(files, template, output),
                kwargs={
                    "heading_style_map": self._style_map,
                    "refresh_fields": self._refresh_fields.isChecked(),
                    "clean_body_from_first_heading": self._clean_body.isChecked(),
                    "on_warning": self._on_warning,
                    "strict": self._strict.isChecked(),
                },
                timeout_seconds=600 + 60 * len(files),
            ),
            on_event=self._on_task_event,
            on_done=self._on_done,
        )
        if not started:
            QMessageBox.warning(self, "开始生成", "已有生成任务正在运行。")
            return
        self._set_controls_enabled(False)
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._open_btn.setEnabled(False)
        self._set_status("生成中…（离线装配模板，无需 Word）", "warning")
        self._timer.start()

    def _on_warning(self, message: str) -> None:
        # 后台线程回调：只追加文本（QPlainTextEdit 跨线程 append 有风险，
        # 统一攒到完成后展示；此处静默收集进 result.warnings 即可）。
        return

    def _on_task_event(self, event) -> None:
        if event.kind == 'stage':
            self._set_status(event.stage + ' ' + (event.detail or ''), 'neutral')
        if event.kind in ('cancelled', 'failed'):
            self._job_state = event.kind
        if event.kind == "failed":
            code = getattr(event, "error_code", None)
            short_title, guide = error_resolution_guide(code, event.detail or "")
            prefix = "{0} · {1}".format(code, short_title) if code else short_title
            self._details.appendPlainText(
                "✗ 生成失败：{0}\n    💡 解决指引：{1}".format(prefix, guide)
            )

    def _on_done(self, result) -> None:
        if hasattr(self, '_job_sources'):
            status = (getattr(result, 'status', '待刷新' if result.refresh_state != 'ok' else '带提醒完成' if result.warnings else '完成') if result else self._job_state)
            warning = self._presets.record_job(self._job_sources, self._job_settings, status=status,
                output=result.output if result else '', warnings=result.warnings if result else ())
            if warning: self._details.appendPlainText(warning)
        self._set_controls_enabled(True)
        self._cancel_btn.setEnabled(False)
        self._timer.stop()
        if result is None:
            self._set_status("生成未完成，请查看详情。", "failure")
            self._refresh_run_state()
            return
        self._last_output = result.output
        summary = "生成完成：{0} 个章节".format(result.chapters)
        if result.images:
            summary += "、图片 {0} 张".format(result.images)
        if result.headless_intro:
            summary += "（文档以无标题正文开头）"
        if result.refresh_state == "ok":
            summary += "；目录域已用 Word 刷新"
        self._details.appendPlainText("✓ " + summary)
        self._details.appendPlainText("    产物：{0}".format(result.output))
        for warning in result.warnings:
            self._details.appendPlainText("    ⚠ {0}".format(warning))
        self._open_btn.setEnabled(True)
        self._open_folder_btn.setEnabled(True)
        self._set_status(summary, "success" if not result.warnings else "warning")
        self._refresh_run_state()

    def _on_cancel(self) -> None:
        self._runner.cancel()
        self._cancel_btn.setEnabled(False)
        self._set_status("正在取消…", "warning")

    def _on_open_output(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        if self._last_output and self._last_output.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output)))
        else:
            QMessageBox.information(self, "打开产物", "产物尚未生成或已被移动。")

    def _on_open_output_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        if self._last_output and self._last_output.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output.parent)))
        else:
            QMessageBox.information(self, "打开输出文件夹", "产物尚未生成或已被移动。")

    def _poll(self) -> None:
        self._runner.poll()
        if not self._runner.is_running:
            self._timer.stop()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._template_edit.setEnabled(enabled)
        self._style_map_btn.setEnabled(enabled and bool(self._template_edit.text().strip()))
        self._add_btn.setEnabled(enabled)
        self._remove_btn.setEnabled(enabled)
        self._up_btn.setEnabled(enabled)
        self._down_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        self._output_edit.setEnabled(enabled)
        self._name_edit.setEnabled(enabled)
        self._refresh_fields.setEnabled(enabled)
        self._clean_body.setEnabled(enabled)
        self._file_list.setEnabled(enabled)
        self._strict.setEnabled(enabled)
        self._recipe_combo.setEnabled(enabled)

    def _set_status(self, text: str, tone: str = "neutral") -> None:
        self._status.setText(text)
        self._status.setProperty("statusTone", tone)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def reject(self) -> None:
        if self._runner.is_running:
            reply = QMessageBox.question(
                self,
                "确认关闭",
                "当前有生成任务正在运行，确认取消并关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._runner.cancel()
        super().reject()
