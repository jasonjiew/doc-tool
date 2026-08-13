# -*- coding: utf-8 -*-
"""自包含测试项目工厂；不读取仓库 content/ 示例文档。"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from doc_tool.domain.manifest import ProjectManifest


_CONTENT_TYPES = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def _minimal_docx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="{0}"/>'
            '</Types>'.format(_CONTENT_TYPES),
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>fixture</w:t></w:r></w:p><w:sectPr/></w:body></w:document>',
        )


def create_project(root: Path, document_type: str = "requirement") -> Path:
    """在指定空目录合成清单、编号章节、模板和必要资源。"""
    root = Path(root).resolve()
    paths = {
        "sourceDocx": "original/source.docx",
        "templateDocx": "template/template.docx",
        "contentRoot": "content/{0}".format(document_type),
        "assetRoot": "assets/{0}".format(document_type),
        "tableRoot": "assets/{0}/tables".format(document_type),
    }
    manifest = ProjectManifest(
        documentType=document_type,
        documentNo="" if document_type == "general" else "FIXTURE-001",
        documentName="自包含测试项目",
        documentVersion="1.0",
        sourceSha256="fixture",
        paths=paths,
    )
    resolved = manifest.resolve_paths(root)
    resolved.ensure_directories(document_type)
    _minimal_docx(resolved.source_docx)
    _minimal_docx(resolved.template_docx)
    content = resolved.resolve(paths["contentRoot"])
    (content / "第1章 引言").mkdir(parents=True, exist_ok=True)
    (content / "第1章 引言" / "1.1 目的.md").write_text(
        "# 目的\n\n本项目用于隔离测试。\n", encoding="utf-8"
    )
    assets = resolved.resolve(paths["assetRoot"])
    (assets / "images").mkdir(parents=True, exist_ok=True)
    (assets / "tables").mkdir(parents=True, exist_ok=True)
    manifest.save(root, backup=False)
    return root


@contextmanager
def temporary_project(document_type: str = "requirement") -> Iterator[Path]:
    """每次调用创建独立临时项目，并在退出时自动清理。"""
    with tempfile.TemporaryDirectory(prefix="doc-tool-fixture-") as tmp:
        yield create_project(Path(tmp), document_type)
