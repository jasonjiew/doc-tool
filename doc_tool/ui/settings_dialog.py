# -*- coding: utf-8 -*-
"""Project settings editor."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from doc_tool.domain.manifest import ProjectManifest


class SettingsDialog(QDialog):
    def __init__(self, manifest: ProjectManifest, project_root: Path, *, writable: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("项目设置")
        self.manifest = manifest
        self.project_root = Path(project_root)
        self.document_no = QLineEdit(manifest.documentNo)
        self.document_name = QLineEdit(manifest.documentName)
        self.document_version = QLineEdit(manifest.documentVersion)
        self.refresh_timeout = QSpinBox()
        self.refresh_timeout.setRange(1, 86400)
        self.refresh_timeout.setValue(manifest.refreshTimeoutSeconds)
        self.template_path = QLineEdit(manifest.relative_template_docx())
        self.publish_notes = QPlainTextEdit(manifest.publishNotes)
        form = QFormLayout()
        form.addRow("文档编号", self.document_no)
        form.addRow("文档名称", self.document_name)
        form.addRow("文档版本", self.document_version)
        form.addRow("刷新超时（秒）", self.refresh_timeout)
        form.addRow("模板路径", self.template_path)
        form.addRow("发布说明", self.publish_notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(writable)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def validated_manifest(self) -> ProjectManifest:
        paths = dict(self.manifest.paths)
        paths["templateDocx"] = self.template_path.text().strip()
        candidate = replace(
            self.manifest,
            documentNo=self.document_no.text().strip(),
            documentName=self.document_name.text().strip(),
            documentVersion=self.document_version.text().strip(),
            refreshTimeoutSeconds=self.refresh_timeout.value(),
            publishNotes=self.publish_notes.toPlainText(),
            paths=paths,
        )
        candidate.resolve_paths(self.project_root)
        return candidate

    def save(self) -> None:
        try:
            candidate = self.validated_manifest()
            candidate.save(self.project_root, backup=True)
        except Exception as exc:  # validation error is user-facing
            QMessageBox.warning(self, "设置无效", str(exc))
            return
        self.manifest = candidate
        self.accept()
