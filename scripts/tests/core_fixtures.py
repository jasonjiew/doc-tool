# -*- coding: utf-8 -*-
"""CORE 主流程测试夹具：标准/无标题/跳级/复杂对象/缺图/坏包与两章缓冲项目。

夹具统一用 ``python-docx`` 生成合法 OOXML 包，再按需注入复杂对象标记，
避免手写 ZIP 造成的部件缺失；注入只影响 ``word/document.xml`` 的正文标记，
不新增关系与部件，保证预检的包结构校验仍然有效。
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from docx import Document
from docx.shared import Pt


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "{" + W_NS + "}"


REPO_ROOT = Path(__file__).resolve().parents[2]

#: 夹具根目录：放在仓库内 tmp/ 下，避免依赖系统 %TEMP% 的可写性
#: （部分企业 PC 的透明加密/沙箱会拒绝在系统临时目录下二次写入）。
SCRATCH_ROOT = REPO_ROOT / "tmp" / "core-scratch"


def scratch_dir(prefix: str = "case") -> Path:
    """创建一个仓库内可写的独立夹具目录（调用方负责清理）。"""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    for index in range(1, 1000):
        candidate = SCRATCH_ROOT / "{0}-{1}-{2}".format(prefix, os.getpid(), index)
        if candidate.exists():
            continue
        candidate.mkdir(parents=True)
        return candidate
    raise RuntimeError("无法在 {0} 下创建夹具目录".format(SCRATCH_ROOT))


def cleanup(path: Path) -> None:
    """删除夹具目录；失败不抛出（测试清理不应掩盖断言失败）。"""
    try:
        shutil.rmtree(str(path), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def _new_document():
    document = Document()
    style = document.styles["Normal"]
    style.font.size = Pt(10.5)
    return document


def build_docx(path: Path, blocks: Sequence[Tuple[str, str]]) -> Path:
    """按 (kind, text) 序列生成 DOCX；kind 取 h1..h6/p/raw。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _new_document()
    for kind, text in blocks:
        if kind.startswith("h") and kind[1:].isdigit():
            document.add_heading(text, level=int(kind[1:]))
        elif kind == "p":
            document.add_paragraph(text)
        elif kind == "raw":
            _append_raw(document, text)
        else:
            raise ValueError("未知块类型：{0}".format(kind))
    document.save(str(path))
    return path


def _append_raw(document, xml: str) -> None:
    """把一段原始 OOXML 追加为正文段落（用于注入复杂对象标记）。"""
    from lxml import etree

    body = document.element.body
    element = etree.fromstring(
        '<w:p xmlns:w="{0}" xmlns:m="{1}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">{2}</w:p>'.format(
            W_NS, M_NS, xml
        )
    )
    body.insert(len(body) - 1, element)


def standard_docx(path: Path) -> Path:
    """标准三级标题文档：可直接接管，无需任何调整。"""
    return build_docx(path, [
        ("h1", "引言"),
        ("p", "本文档说明导入主流程。"),
        ("h2", "目的"),
        ("p", "验证标准标题树直接接管。"),
        ("h2", "范围"),
        ("p", "覆盖导入、编辑与出稿。"),
        ("h1", "设计"),
        ("p", "设计章节正文。"),
    ])


def no_heading_docx(path: Path) -> Path:
    """没有任何标题样式的正文文档：普通模式应按单章接管。"""
    return build_docx(path, [
        ("p", "这是一份没有标题样式的说明文档。"),
        ("p", "第一段正文需要完整保留。"),
        ("p", "第二段正文同样需要保留。"),
    ])


def jump_level_docx(path: Path) -> Path:
    """跳级标题 + 标题前正文：需要层级整理并保留标题前内容。"""
    return build_docx(path, [
        ("p", "标题之前的封面说明文字。"),
        ("h1", "总述"),
        ("p", "总述正文。"),
        ("h3", "深层小节"),
        ("p", "深层小节正文。"),
        ("h1", "详述"),
        ("p", "详述正文。"),
    ])


def pre_title_body_docx(path: Path) -> Path:
    """仅有标题前正文 + 一个标题：验证标题前内容范围明确。"""
    return build_docx(path, [
        ("p", "前言：这份内容在第一级标题之前。"),
        ("h1", "正文"),
        ("p", "章节正文。"),
    ])


def complex_docx(path: Path) -> Path:
    """含公式/文本框/修订/批注/脚注引用的文档：复杂对象应留位置与原件。"""
    return build_docx(path, [
        ("h1", "复杂内容"),
        ("p", "正文第一段。"),
        ("raw", '<w:r><m:oMath><m:r><m:t>x=1</m:t></m:r></m:oMath></w:r>'),
        ("raw", '<w:r><w:txbxContent><w:p><w:r><w:t>文本框内容</w:t></w:r></w:p></w:txbxContent></w:r>'),
        ("raw", '<w:ins w:id="1" w:author="a" w:date="2026-10-01T00:00:00Z"><w:r><w:t>插入的修订文字</w:t></w:r></w:ins>'),
        ("raw", '<w:commentRangeStart w:id="1"/><w:r><w:t>被批注文字</w:t></w:r><w:commentRangeEnd w:id="1"/>'),
        ("raw", '<w:r><w:footnoteReference w:id="2"/></w:r>'),
        ("p", "正文最后一段。"),
    ])


def image_docx(path: Path, image_path: Path) -> Path:
    """含一张嵌入图片的文档。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _new_document()
    document.add_heading("图示", level=1)
    document.add_paragraph("下图说明流程。")
    document.add_picture(str(image_path))
    document.add_paragraph("图后正文。")
    document.save(str(path))
    return path


def tiny_png(path: Path) -> Path:
    """生成 8x8 的合法 PNG（供图片夹具使用）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image

        Image.new("RGB", (8, 8), (200, 30, 30)).save(str(path))
    except Exception:  # noqa: BLE001 - 无 Pillow 时写最小 PNG 字节
        path.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000080000000808020000004b6d"
                "29dc0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
            )
        )
    return path


def drop_media_parts(docx_path: Path) -> Path:
    """删除包内 word/media/* 部件，制造“正文引用但资源缺失”的缺图文档。"""
    docx_path = Path(docx_path)
    buffer_path = docx_path.with_suffix(".rebuild.docx")
    with zipfile.ZipFile(docx_path, "r") as source:
        names = source.namelist()
        with zipfile.ZipFile(buffer_path, "w", zipfile.ZIP_DEFLATED) as target:
            for name in names:
                if name.startswith("word/media/"):
                    continue
                target.writestr(name, source.read(name))
    shutil.move(str(buffer_path), str(docx_path))
    return docx_path


def broken_docx(path: Path, *, kind: str = "zip") -> Path:
    """损坏包夹具：kind=zip 为随机字节，kind=empty 为空文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "empty":
        path.write_bytes(b"")
    else:
        path.write_bytes(b"this-is-not-a-zip-package")
    return path


def two_chapter_project(root: Path, document_type: str = "general") -> Path:
    """两章项目（真实导入产出，结构与 Word 内核一致）+ 可再编辑的章节正文。

    导出/快照夹具必须能真正构建：因此优先用真实的首次导入服务生成项目
    （含模板样式映射、_index.md 与章节顺序）。导入不可用（例如本机无 Word）
    时回退到合成项目，保证无 Word 环境下仍可验证快照与源码包。
    """
    root = Path(root).resolve()
    try:
        source = build_docx(
            root.parent / (root.name + "-源.docx"),
            [
                ("h1", "引言"),
                ("p", "第一轮正文。"),
                ("h2", "目的"),
                ("p", "目的正文。"),
                ("h1", "设计"),
                ("p", "第二轮正文。"),
                ("h2", "架构"),
                ("p", "架构正文。"),
            ],
        )
        from doc_tool.application.intake_entries import run_intake

        outcome = run_intake(source, parent_dir=root.parent, target_name=root.name)
        if outcome.ok and outcome.project_root is not None:
            return Path(outcome.project_root)
    except Exception:  # noqa: BLE001 - 无 Word 等环境缺少时回退合成项目
        pass

    from scripts.tests.fixture_factory import create_project

    create_project(root, document_type=document_type)
    content = root / "content" / document_type
    chapter_one = content / "第1章 引言"
    chapter_two = content / "第2章 设计"
    chapter_one.mkdir(parents=True, exist_ok=True)
    chapter_two.mkdir(parents=True, exist_ok=True)
    (chapter_one / "_index.md").write_text("本章说明。\n", encoding="utf-8")
    (chapter_one / "1.1 目的.md").write_text("第一轮正文。\n", encoding="utf-8")
    (chapter_two / "_index.md").write_text("本章说明。\n", encoding="utf-8")
    (chapter_two / "2.1 架构.md").write_text("第二轮正文。\n", encoding="utf-8")
    _install_valid_template(root)
    from doc_tool.domain.manifest import ProjectManifest

    manifest = ProjectManifest.load(root)
    manifest.headingStyles = {level: "Heading{0}".format(level) for level in range(1, 7)}
    manifest.bodyStyle = "Normal"
    manifest.chapters = ["第1章 引言/1.1 目的.md", "第2章 设计/2.1 架构.md"]
    manifest.save(root)
    return root


def _install_valid_template(root: Path) -> None:
    """回退路径用 python-docx 生成含 settings.xml 的合法底模。"""
    from docx import Document

    document = Document()
    document.add_heading("底模", level=1)
    document.add_paragraph("正文样式占位。")
    for name in ("template/template.docx", "original/source.docx"):
        target = Path(root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(target))


def buffer_texts(root: Path, document_type: str = "general") -> dict:
    """返回“未保存缓冲”映射（相对 contentRoot 的 POSIX 路径 -> 文本）。"""
    content = Path(root) / "content" / document_type
    texts = {}
    for path in sorted(content.rglob("*.md")):
        texts[path.relative_to(content).as_posix()] = path.read_text(encoding="utf-8")
    return texts


__all__ = [
    "REPO_ROOT", "SCRATCH_ROOT", "scratch_dir", "cleanup",
    "build_docx", "standard_docx", "no_heading_docx", "jump_level_docx",
    "pre_title_body_docx", "complex_docx", "image_docx", "tiny_png",
    "drop_media_parts", "broken_docx", "two_chapter_project", "buffer_texts",
]