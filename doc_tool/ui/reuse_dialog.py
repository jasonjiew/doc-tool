# -*- coding: utf-8 -*-
"""正文模块库与引用解析入口（V3.0 30-F 6.1/6.2）。

界面只做入口与展示，能力全部复用既有服务：

- 模块库：列表 / 搜索 / 预览（``reuse_commands.list_modules`` / ``show_module``）；
- 本项目引用解析报告（``resolve_project`` + ``render_report``），来源、版本、定位都在报告里；
- 变体有效范围（``variant_evidence``）；
- 生成展开副本（``write_expanded_copy``），交给旧应用或外部作者。

不做新的编辑器，也不在界面上暴露内部 hash/schema 术语（技术细节留在报告文本里）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from doc_tool.application.content import reuse_commands as reuse


class ReuseDialog(QDialog):
    """模块库与引用解析对话框（只读展示 + 展开副本导出）。"""

    def __init__(
        self,
        project_root,
        parent: Optional[QWidget] = None,
        *,
        buffer_source=None,
        on_insert_module=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.setWindowTitle("正文模块库与引用解析")
        self.resize(980, 620)
        self._context = None
        self._rows: List[Dict[str, object]] = []
        # UI 包 4.2：当前章节缓冲快照回调 / 插入回调（由主窗口接线到真实编辑器）。
        self._buffer_source = buffer_source
        self._on_insert_module = on_insert_module
        self._build_ui()
        self.reload()

    # --- 构建 ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("搜索模块（名称 / 标识 / 标签）")
        self.search_input.textChanged.connect(lambda _text: self.reload())
        top.addWidget(self.search_input, 1)
        self.reload_button = QPushButton("刷新", self)
        self.reload_button.clicked.connect(self.reload)
        top.addWidget(self.reload_button)
        self.copy_button = QPushButton("生成展开副本…", self)
        self.copy_button.setToolTip("导出普通 Markdown 副本（不含模块引用标记），可搬目录打开")
        self.copy_button.clicked.connect(self.export_expanded_copy)
        top.addWidget(self.copy_button)

        # 空模块库/首次使用闭环（UI 包 4.2）：从当前章节创建模块。
        self.create_button = QPushButton("从当前章节创建模块…", self)
        self.create_button.setObjectName("reuseCreateModuleBtn")
        self.create_button.setToolTip(
            "把当前章节提取为模块并发布进库；有未保存修改时用内存缓冲快照，不读旧磁盘内容"
        )
        self.create_button.clicked.connect(self.create_module_from_chapter)
        top.addWidget(self.create_button)

        # 库目录未配置时可选已有库；选中后把明确版本固定复制进项目。
        self.library_button = QPushButton("选择已有模块库…", self)
        self.library_button.setObjectName("reusePickLibraryBtn")
        self.library_button.setToolTip("库目录未配置时选择一个已有模块库作为来源")
        self.library_button.clicked.connect(self.pick_library)
        top.addWidget(self.library_button)

        self.install_button = QPushButton("安装所选模块到项目", self)
        self.install_button.setObjectName("reuseInstallModuleBtn")
        self.install_button.setToolTip("把所选模块的明确版本固定复制进项目 reuse/modules")
        self.install_button.clicked.connect(self.install_selected_module)
        top.addWidget(self.install_button)

        self.insert_mode_combo = QComboBox(self)
        self.insert_mode_combo.setObjectName("reuseInsertModeCombo")
        self.insert_mode_combo.addItem("固定引用", "reference")
        self.insert_mode_combo.addItem("复制正文", "copy")
        self.insert_mode_combo.setToolTip("固定引用＝可解析来源；复制正文＝展开成普通 Markdown")
        top.addWidget(self.insert_mode_combo)

        self.insert_button = QPushButton("插入所选模块", self)
        self.insert_button.setObjectName("reuseInsertModuleBtn")
        self.insert_button.setToolTip("在当前章节插入固定引用或复制正文（一次撤销）")
        self.insert_button.clicked.connect(self.insert_selected_module)
        top.addWidget(self.insert_button)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.module_list = QListWidget(splitter)
        self.module_list.currentRowChanged.connect(self._show_selected_module)
        splitter.addWidget(self.module_list)
        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("变体：", right))
        self.variant_combo = QComboBox(right)
        self.variant_combo.currentIndexChanged.connect(lambda _index: self.refresh_report())
        variant_row.addWidget(self.variant_combo, 1)
        self.report_button = QPushButton("解析本项目引用", right)
        self.report_button.clicked.connect(self.refresh_report)
        variant_row.addWidget(self.report_button)
        right_layout.addLayout(variant_row)
        self.preview = QPlainTextEdit(right)
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("选择左侧模块查看预览，或点「解析本项目引用」查看展开报告")
        right_layout.addWidget(self.preview, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("", self)
        bottom.addWidget(self.status_label, 1)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.reject)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

    # --- 数据 ---

    def _ensure_context(self):
        """项目复用上下文；库目录未配置时回退到项目自己的模块库。

        创建模块会写进项目库（``reuse/library``），安装明确版本也要能从项目库
        复制，否则空库项目永远装不上自己的模块。用户显式选择的库优先。
        """
        if self._context is None:
            override = self._library_override()
            context = reuse.load_context(self.project_root, library_root=override)
            if context.library is None and override is None:
                from doc_tool.application.content import modules as module_lib

                project_library_root = module_lib.project_module_root(self.project_root)
                context = reuse.load_context(
                    self.project_root, library_root=project_library_root
                )
            self._context = context
        return self._context

    def _library_override(self):
        """用户显式选择的已有库目录（未选择返回 None，沿用项目配置）。"""
        value = getattr(self, "_library_root", "")
        return Path(value) if value else None

    def pick_library(self) -> None:
        """库目录未配置时选择已有库；只影响本次会话的来源，不改项目配置。"""
        chosen = QFileDialog.getExistingDirectory(self, "选择已有模块库目录")
        if not chosen:
            return
        self._library_root = chosen
        self._context = None
        self.reload()
        self.status_label.setText("已选择模块库：{0}".format(chosen))

    def create_module_from_chapter(self) -> None:
        """从当前章节创建模块：缓冲优先，标清来源；写入后刷新列表。"""
        rel_path, buffer_text = ("", "")
        if self._buffer_source is not None:
            try:
                rel_path, buffer_text = self._buffer_source()
            except Exception:  # noqa: BLE001 - 无缓冲按已保存内容创建
                rel_path, buffer_text = "", ""
        if not rel_path:
            rel_path = self._fallback_chapter()
        if not rel_path:
            self.status_label.setText("没有可用章节：请先打开一个章节再创建模块")
            return
        source_mode = "current-buffer" if str(buffer_text or "").strip() else "saved"
        try:
            context = self._ensure_context()
            result = reuse.extract_chapter_module(
                context, rel_path, buffer_text=buffer_text,
                library_root=self._library_override(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "创建模块失败", str(exc))
            return
        if not result.get("ok"):
            QMessageBox.warning(
                self, "创建模块未完成",
                str(result.get("message") or result.get("error") or "未知原因"),
            )
            return
        module = result.get("module") or {}
        module_id = str(module.get("moduleId") or result.get("moduleId") or "")
        version = str(module.get("version") or result.get("version") or "1.0.0")
        # 创建后必须让上下文重新解析库：缓存里的 library 对象看不到刚发布的模块，
        # 「安装所选模块」会误报「模块不存在」。
        self._context = None
        self.reload()
        self.status_label.setText(
            "已创建模块 {0}@{1}（来源：{2}）".format(
                module_id, version,
                "当前未保存缓冲" if source_mode == "current-buffer" else "已保存章节",
            )
        )
        QMessageBox.information(
            self, "模块已创建",
            "模块：{0}@{1}\n来源：{2}\n库：{3}".format(
                module_id, version,
                "当前未保存缓冲（未读旧磁盘内容）" if source_mode == "current-buffer" else "已保存章节",
                module.get("directory") or self._library_override() or "项目库",
            ),
        )

    def _fallback_chapter(self) -> str:
        """无编辑器缓冲时用工作区当前章节，其次第一个章节（只读来源，仍标 saved）。"""
        try:
            context = self._ensure_context()
            chapters = list(getattr(context, "chapters", None) or [])
        except Exception:  # noqa: BLE001
            return ""
        return str(chapters[0]) if chapters else ""

    def _selected_module(self):
        row = self.module_list.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def install_selected_module(self) -> None:
        """把所选模块的明确版本固定复制进项目；只读项目给明确原因。"""
        row = self._selected_module()
        if row is None:
            self.status_label.setText("请先在左侧选择一个模块版本")
            return
        module_id = str(row.get("moduleId") or "")
        version = str(row.get("version") or "")
        try:
            context = (
                self._ensure_context()
                if self._library_override() is None
                else self._context_with_library()
            )
            result = reuse.install_modules(context, [(module_id, version)])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "安装模块失败", str(exc))
            return
        if not result.get("ok"):
            QMessageBox.warning(
                self, "安装模块未完成",
                "；".join(result.get("problems") or []) or str(result.get("message") or "未知原因"),
            )
            return
        installed = (result.get("installed") or [{}])[0]
        installed_id = str(installed.get("moduleId") or module_id or "")
        installed_version = str(installed.get("version") or version or "")
        self.status_label.setText(
            "已安装 {0}@{1} 到项目（固定引用）".format(installed_id, installed_version)
        )

    def _context_with_library(self):
        """用用户选择的库重新加载上下文（不改项目配置，只影响本次会话）。"""
        return reuse.load_context(self.project_root, library_root=self._library_override())

    def insert_selected_module(self) -> None:
        """插入所选模块：默认固定引用；按住 Shift 语义由下拉选择复制正文。"""
        row = self._selected_module()
        if row is None:
            self.status_label.setText("请先在左侧选择一个模块版本")
            return
        if self._on_insert_module is None:
            self.status_label.setText("当前没有可插入的编辑器：请先打开一个章节")
            return
        module_id = str(row.get("moduleId") or "")
        version = str(row.get("version") or "")
        mode = str((self.insert_mode_combo.currentData() if hasattr(self, "insert_mode_combo") else "reference") or "reference")
        if mode == "copy":
            payload_text = self._module_body_for_copy(module_id, version)
        else:
            payload_text = '```doc-module id={0} version={1} slot=s1\n```'.format(
                module_id, version
            )
        if self._on_insert_module(payload_text, mode):
            self.status_label.setText(
                "已插入 {0}@{1}（{2}）".format(
                    module_id, version, "固定引用" if mode == "reference" else "正文副本",
                )
            )

    def _module_body_for_copy(self, module_id: str, version: str) -> str:
        try:
            library = reuse.load_library(self.project_root, library_root=self._library_override())
            payload = reuse.show_module(library, module_id, version, with_body=True)
        except Exception as exc:  # noqa: BLE001
            return ""
        return str(payload.get("body") or payload.get("preview") or "")

    def reload(self) -> None:
        try:
            library = reuse.load_library(
                self.project_root, library_root=self._library_override()
            )
            payload = reuse.list_modules(library, query=self.search_input.text().strip())
        except Exception as exc:  # noqa: BLE001 - 库不可用时给出明确说明
            self.status_label.setText("模块库不可用：{0}".format(exc))
            self.module_list.clear()
            return
        self._rows = [row for row in (payload.get("modules") or []) if isinstance(row, dict)]
        self.module_list.clear()
        for row in self._rows:
            label = "{0}（{1}）".format(row.get("title") or row.get("moduleId"), row.get("version"))
            item = QListWidgetItem(label, self.module_list)
            item.setToolTip(str(row.get("description") or ""))
        if self._rows and self.module_list.currentRow() < 0:
            # 刷新后默认选中首个模块，避免「安装/插入」需要用户额外点一次。
            self.module_list.setCurrentRow(0)
        self.status_label.setText("共 {0} 个模块".format(len(self._rows)))
        self._update_empty_state()
        self._reload_variants()

    def _update_empty_state(self) -> None:
        """空库说明：告诉用户下一步真实动作，而不是只显示「无数据」。"""
        if self._rows:
            return
        hint = (
            "当前库还没有模块。可点「从当前章节创建模块…」把正在写的章节存为模块；"
            "或点「选择已有模块库…」指定一个已有库后再安装到项目。"
        )
        self.preview.setPlainText(hint)

    def _reload_variants(self) -> None:
        self.variant_combo.blockSignals(True)
        self.variant_combo.clear()
        self.variant_combo.addItem("（不使用变体）", "")
        try:
            context = self._ensure_context()
            for variant in getattr(context, "variants", None) or []:
                name = getattr(variant, "name", "") or getattr(variant, "variantId", "")
                variant_id = getattr(variant, "variantId", "") or name
                self.variant_combo.addItem(str(name), str(variant_id))
        except Exception:  # noqa: BLE001 - 无变体声明时保持空
            pass
        self.variant_combo.blockSignals(False)

    def _show_selected_module(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._rows):
            return
        row = self._rows[row_index]
        try:
            library = reuse.load_library(self.project_root)
            payload = reuse.show_module(
                library, str(row.get("moduleId") or ""), str(row.get("version") or ""),
                with_body=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.preview.setPlainText("无法读取模块：{0}".format(exc))
            return
        lines = [
            "模块：{0}（{1}）".format(payload.get("title") or row.get("moduleId"), payload.get("version")),
            "参数：{0}".format("、".join(payload.get("parameters") or []) or "无"),
            "资源：{0}".format("、".join(payload.get("resources") or []) or "无"),
            "",
        ]
        body = payload.get("body") or payload.get("preview") or ""
        lines.append(str(body))
        self.preview.setPlainText("\n".join(lines))

    # --- 报告与副本 ---

    def refresh_report(self) -> None:
        variant_id = str(self.variant_combo.currentData() or "")
        try:
            context = self._ensure_context()
            if variant_id:
                payload = reuse.variant_evidence(context, variant_id)
                if payload.get("ok"):
                    report = reuse.resolve_project(
                        context, variant_id=variant_id, record_instances=True,
                    )
                else:
                    report = payload
            else:
                # 面板解析同时把实例映射落盘并输出覆盖率（V3.0 4.3）
                report = reuse.resolve_project(context, record_instances=True)
            self.preview.setPlainText(reuse.render_report(report, output="human"))
            self.status_label.setText("已解析本项目引用（{0}）".format(
                "变体 " + variant_id if variant_id else "整份"
            ))
        except Exception as exc:  # noqa: BLE001 - 解析失败给明确原因
            self.preview.setPlainText("引用解析未完成：{0}".format(exc))
            self.status_label.setText("引用解析未完成")

    def export_expanded_copy(self) -> None:
        target = QFileDialog.getExistingDirectory(self, "选择展开副本目录")
        if not target:
            return
        variant_id = str(self.variant_combo.currentData() or "")
        try:
            context = self._ensure_context()
            result = reuse.write_expanded_copy(context, target, variant_id=variant_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "展开副本未生成", str(exc))
            return
        message = "已生成展开副本：{0}".format(result.get("path") or target)
        warnings = list(result.get("warnings") or [])[:3]
        if warnings:
            message += "\n提醒：" + "；".join(str(item) for item in warnings)
        self.status_label.setText(message.splitlines()[0])
        QMessageBox.information(self, "展开副本", message)


__all__ = ["ReuseDialog"]