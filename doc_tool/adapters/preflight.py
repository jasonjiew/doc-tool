# -*- coding: utf-8 -*-
"""Word 导入预检适配器。

任务 3.1-3.6：在写入正式项目前，对任意文件名的 DOCX 执行完整预检，
任何检查失败均抛出 ``DocToolError`` 子类（fail-closed），不创建项目目录。

预检内容：
- 3.1 包结构校验：扩展名、ZIP 完整性（CRC）、XML 良构、加密/损坏检测。
- 3.2 关系目标完整性及正文资源引用预检。
- 3.3 ``styles.xml`` 的 styleId 到 Heading 1~6 映射和标题树解析。
- 3.4 无 Heading 1、标题层级跳跃和无法闭合树的 fail-closed 校验。
- 3.5 通用模式为默认，需求/详细设计只作为可选的公司文档预设。
- 3.6 导入预览模型：标题级别计数、首尾标题、图片/表格数量和告警。
"""

from __future__ import annotations

import os
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from lxml import etree

from doc_tool.domain.errors import (
    BrokenRelationshipError,
    HeadingHierarchyError,
    InvalidDocxError,
    MissingHeading1Error,
)


# --- OOXML 命名空间 ---

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

W = "{" + W_NS + "}"
R = "{" + R_NS + "}"
A = "{" + A_NS + "}"

# 预览中首尾标题各展示的数量。
PREVIEW_HEADING_LIMIT = 5

# 支持的标题级别范围。
MIN_HEADING_LEVEL = 1
MAX_HEADING_LEVEL = 6

# 加密 DOCX 在 ZIP 中的特征条目。
ENCRYPTED_ENTRY = "EncryptedPackage"

# DOCX 包中必须存在的核心部件。
REQUIRED_PARTS = ("word/document.xml",)

# 不受信任的 DOCX 本质上是 ZIP。先检查目录元数据，再做 CRC/解压，避免压缩
# 炸弹或异常巨大的 XML 在预检阶段耗尽内存。上限明显高于当前真实基线文档。
MAX_PACKAGE_ENTRIES = 20_000
MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_SINGLE_ENTRY_BYTES = 256 * 1024 * 1024
MAX_XML_PART_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 2_000

# 关系类型常量（仅取末尾片段用于分类）。
REL_TYPE_IMAGE = "/image"
REL_TYPE_HYPERLINK = "/hyperlink"


def _qn(tag: str) -> str:
    """返回带 wordprocessingml 命名空间的完整标签名。"""
    return W + tag


# --- 数据模型 ---


@dataclass(frozen=True)
class HeadingInfo:
    """标题段落信息。"""

    level: int
    style_id: str
    text: str
    body_index: int


@dataclass
class DocumentTypeSuggestion:
    """文档类型建议。

    低置信度时 ``confidence`` 为 ``"low"``，调用方不得据此自动决定类型。
    """

    document_type: str
    confidence: str  # "high" | "low"
    reason: str


@dataclass
class ImportPreview:
    """导入预览模型（任务 3.6）。

    汇总源 DOCX 的结构摘要，供界面在导入确认页展示。
    不含正文内容，仅含计数、标题文本片段和告警。
    """

    file_name: str
    file_size_bytes: int
    package_entry_count: int
    heading_style_map: Dict[str, int] = field(default_factory=dict)
    headings: List[HeadingInfo] = field(default_factory=list)
    heading_level_counts: Dict[int, int] = field(default_factory=dict)
    first_headings: List[HeadingInfo] = field(default_factory=list)
    last_headings: List[HeadingInfo] = field(default_factory=list)
    image_count: int = 0
    table_count: int = 0
    media_count: int = 0
    relationship_count: int = 0
    warnings: List[str] = field(default_factory=list)
    document_type_suggestion: Optional[DocumentTypeSuggestion] = None

    @property
    def has_heading1(self) -> bool:
        return self.heading_level_counts.get(1, 0) > 0


# --- 预检主入口 ---


def preflight(path: Union[str, Path]) -> ImportPreview:
    """对任意文件名的 DOCX 执行完整预检，返回预览模型。

    任何检查失败均抛出 ``DocToolError`` 子类，调用方应据此向用户显示
    稳定错误码和修复建议，且不创建项目目录。

    Args:
        path: 用户选择的 DOCX 文件路径，文件名任意。

    Returns:
        ``ImportPreview`` 预览模型。

    Raises:
        InvalidDocxError: 扩展名、ZIP、CRC、XML 或加密检查失败。
        BrokenRelationshipError: 关系目标缺失或正文引用的资源不存在。
        MissingHeading1Error: 没有可识别的 Heading 1。
        HeadingHierarchyError: 标题层级跳跃，无法构成可闭合章节树。
    """
    file_path = Path(path)
    file_name = file_path.name
    file_size = file_path.stat().st_size if file_path.exists() else 0

    # --- 3.1 包结构校验 ---
    _check_extension(file_name)
    with _open_and_check_zip(file_path) as zip_handle:
        _check_encryption(zip_handle)
        parts = _read_parts(zip_handle)
        _check_xml_wellformed(parts)
        _check_required_parts(parts)

        # --- 3.2 关系目标完整性 ---
        rel_map = _parse_relationships(parts)
        _check_relationship_targets(rel_map, zip_handle)

        # --- 3.3 标题样式映射与标题树 ---
        heading_style_map = _parse_heading_styles(parts)
        headings = _build_heading_tree(parts, heading_style_map)

        # --- 3.4 层级校验（fail-closed） ---
        _validate_heading_hierarchy(headings)

        # --- 3.2 续：正文资源引用预检 ---
        body_resource_warnings = _check_body_resource_references(parts, rel_map)

        # --- 3.6 预览统计 ---
        image_count = _count_images(parts)
        table_count = _count_tables(parts)
        all_names = zip_handle.namelist()
        media_names = [n for n in all_names if n.startswith("word/media/")]
        entry_count = len(all_names)

        level_counts: Dict[int, int] = {}
        for h in headings:
            level_counts[h.level] = level_counts.get(h.level, 0) + 1

        warnings: List[str] = []
        if not heading_style_map:
            warnings.append("未在 styles.xml 中找到任何 Heading 样式定义。")
        warnings.extend(body_resource_warnings)
        if len(media_names) == 0 and image_count > 0:
            warnings.append("正文引用了图片但 media 目录为空。")

        # --- 3.5 文档类型建议 ---
        suggestion = _suggest_document_type(headings, parts)

        return ImportPreview(
            file_name=file_name,
            file_size_bytes=file_size,
            package_entry_count=entry_count,
            heading_style_map=heading_style_map,
            headings=headings,
            heading_level_counts=level_counts,
            first_headings=headings[:PREVIEW_HEADING_LIMIT],
            last_headings=(
                headings[-PREVIEW_HEADING_LIMIT:]
                if len(headings) > PREVIEW_HEADING_LIMIT else []
            ),
            image_count=image_count,
            table_count=table_count,
            media_count=len(media_names),
            relationship_count=len(rel_map),
            warnings=warnings,
            document_type_suggestion=suggestion,
        )


# --- 3.1 包结构校验 ---


def _check_extension(file_name: str) -> None:
    """校验文件扩展名为 ``.docx``（不区分大小写）。"""
    if not file_name.lower().endswith(".docx"):
        raise InvalidDocxError(
            "文件扩展名不是 .docx：{0}".format(file_name),
            suggested_action="请选择扩展名为 .docx 的 Word 文档。",
            details={"fileName": file_name},
        )


def _open_and_check_zip(file_path: Path) -> zipfile.ZipFile:
    """打开 ZIP 并校验完整性和 CRC。

    非 ZIP 文件、损坏 ZIP 或 CRC 校验失败均视为非法 DOCX。
    """
    try:
        zf = zipfile.ZipFile(str(file_path), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidDocxError(
            "文件不是有效的 ZIP 包或不存在。",
            suggested_action="请确认选择了正确的 .docx 文件且文件未损坏。",
            details={"error": str(exc)},
        ) from exc
    try:
        _check_zip_limits(zf)
        # CRC 校验：testzip() 返回第一个损坏条目名，None 表示全部通过。
        bad = zf.testzip()
    except Exception:
        zf.close()
        raise
    if bad is not None:
        zf.close()
        raise InvalidDocxError(
            "ZIP 包 CRC 校验失败：{0}".format(bad),
            suggested_action="文件可能在传输中损坏，请重新获取原始 DOCX。",
            details={"badEntry": bad},
        )
    return zf


def _check_zip_limits(zf: zipfile.ZipFile) -> None:
    """在解压前限制条目数、展开体积、单条目体积和压缩比。"""
    infos = zf.infolist()
    if len(infos) > MAX_PACKAGE_ENTRIES:
        raise InvalidDocxError(
            "DOCX 包含过多 ZIP 条目。",
            details={"entryCount": str(len(infos))},
        )
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > MAX_SINGLE_ENTRY_BYTES:
            raise InvalidDocxError(
                "DOCX 包含异常大的条目：{0}".format(info.filename),
                details={"entry": info.filename, "size": str(info.file_size)},
            )
        if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise InvalidDocxError(
                "DOCX 包含异常压缩比的条目：{0}".format(info.filename),
                details={"entry": info.filename},
            )
    if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise InvalidDocxError(
            "DOCX 解压后的总大小超过安全上限。",
            details={"uncompressedBytes": str(total)},
        )


def _check_encryption(zf: zipfile.ZipFile) -> None:
    """检测加密 DOCX（OOXML 加密后 ZIP 内仅含 ``EncryptedPackage``）。"""
    names = zf.namelist()
    if ENCRYPTED_ENTRY in names and "word/document.xml" not in names:
        raise InvalidDocxError(
            "文件已加密或受密码保护。",
            suggested_action="请先在 Word 中解除文档密码保护后重新导入。",
            details={"entry": ENCRYPTED_ENTRY},
        )


def _read_parts(zf: zipfile.ZipFile) -> Dict[str, bytes]:
    """只读取预检需要的 XML/关系部件，避免把全部图片载入内存。"""
    parts: Dict[str, bytes] = {}
    for info in zf.infolist():
        name = info.filename
        # 跳过目录条目
        if name.endswith("/") or not (name.endswith(".xml") or name.endswith(".rels")):
            continue
        if info.file_size > MAX_XML_PART_BYTES:
            raise InvalidDocxError(
                "XML 部件超过安全上限：{0}".format(name),
                details={"part": name, "size": str(info.file_size)},
            )
        try:
            parts[name] = zf.read(name)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise InvalidDocxError(
                "读取 ZIP 条目失败：{0}".format(name),
                details={"error": str(exc)},
            ) from exc
    return parts


def _check_xml_wellformed(parts: Dict[str, bytes]) -> None:
    """校验所有 XML 部件良构。"""
    for name, data in parts.items():
        if not name.endswith(".xml") and not name.endswith(".rels"):
            continue
        try:
            _parse_xml(data, name)
        except etree.XMLSyntaxError as exc:
            raise InvalidDocxError(
                "XML 部件解析失败：{0}".format(name),
                suggested_action="文件可能已损坏，请在 Word 中尝试打开并另存后重新导入。",
                details={"part": name, "error": str(exc)},
            ) from exc


def _parse_xml(data: bytes, part_name: str = ""):
    """使用禁用 DTD、实体解析和网络访问的解析器读取 OOXML。"""
    upper = data[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise InvalidDocxError(
            "XML 部件包含不允许的 DTD/实体声明：{0}".format(part_name or "unknown"),
            details={"part": part_name or "unknown"},
        )
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
    )
    root = etree.fromstring(data, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise InvalidDocxError(
            "XML 部件包含不允许的 DTD 声明：{0}".format(part_name or "unknown"),
            details={"part": part_name or "unknown"},
        )
    return root


def _check_required_parts(parts: Dict[str, bytes]) -> None:
    """校验 DOCX 核心部件存在。"""
    for part in REQUIRED_PARTS:
        if part not in parts:
            raise InvalidDocxError(
                "缺少核心部件：{0}".format(part),
                suggested_action="文件结构不完整，请确认是标准的 Word .docx 文件。",
                details={"missingPart": part},
            )


# --- 3.2 关系目标完整性 ---


def _parse_relationships(parts: Dict[str, bytes]) -> Dict[str, Dict[str, str]]:
    """解析 ``word/_rels/document.xml.rels``，返回 rid -> {target, type} 映射。"""
    rels_name = "word/_rels/document.xml.rels"
    if rels_name not in parts:
        return {}
    rels_root = _parse_xml(parts[rels_name], rels_name)
    rel_map: Dict[str, Dict[str, str]] = {}
    for rel in rels_root:
        rid = rel.get("Id")
        target = rel.get("Target")
        rtype = rel.get("Type", "")
        target_mode = rel.get("TargetMode", "")
        if not rid or not target:
            continue
        rel_map[rid] = {"target": target, "type": rtype, "targetMode": target_mode}
    return rel_map


def _check_relationship_targets(
    rel_map: Dict[str, Dict[str, str]], zf: zipfile.ZipFile
) -> None:
    """校验每条关系的 Target 在包内存在（外部链接除外）。"""
    names = set(zf.namelist())
    for rid, info in rel_map.items():
        target = info["target"]
        # TargetMode 是 OOXML 判断外部关系的事实来源；URL 前缀仅作兼容。
        if _is_external_relationship(info):
            continue
        if info.get("targetMode", "").lower() == "internal":
            # 文档内书签/锚点关系（如 hyperlink Target="_Toc123"）：目标是
            # 文档内位置而非包内部件，跳过部件存在性校验。
            continue
        # 相对 word/ 目录的目标
        if target.startswith("/"):
            full = target.lstrip("/")
        else:
            full = posixpath.normpath("word/" + target)
        # 标准化路径分隔符
        full = full.replace("\\", "/")
        if full not in names:
            raise BrokenRelationshipError(
                "关系目标不存在：rId={0} target={1}".format(rid, target),
                details={"rId": rid, "target": target, "resolved": full},
            )


def _is_external_relationship(info: Dict[str, str]) -> bool:
    """兼容识别显式 TargetMode 和缺失 TargetMode 的 URI 目标。"""
    target = info.get("target", "").lstrip().lower()
    return info.get("targetMode", "").lower() == "external" or target.startswith(
        ("http://", "https://", "mailto:", "file:", "ftp://")
    )


def _check_body_resource_references(
    parts: Dict[str, bytes], rel_map: Dict[str, Dict[str, str]]
) -> List[str]:
    """校验正文引用的图片/超链接 rId 在关系表中存在，返回告警列表。"""
    warnings: List[str] = []
    document_xml = parts.get("word/document.xml")
    if document_xml is None:
        return warnings
    root = _parse_xml(document_xml, "word/document.xml")
    body = root.find(_qn("body"))
    if body is None:
        return warnings

    # 收集正文引用的所有 rId
    referenced_rids: set = set()
    for blip in root.iter(A + "blip"):
        rid = blip.get(R + "embed") or blip.get(R + "link")
        if rid:
            referenced_rids.add(rid)
    for hyperlink in root.iter(_qn("hyperlink")):
        rid = hyperlink.get(R + "id")
        if rid:
            referenced_rids.add(rid)
    # 旧版 Word/VML 图片使用 v:imagedata r:id。
    for node in root.iter():
        if etree.QName(node).localname == "imagedata":
            rid = node.get(R + "id")
            if rid:
                referenced_rids.add(rid)

    for rid in referenced_rids:
        if rid not in rel_map:
            raise BrokenRelationshipError(
                "正文引用的关系不存在：rId={0}".format(rid),
                suggested_action="请在 Word 中检查图片或超链接引用是否完整。",
                details={"rId": rid},
            )
        info = rel_map[rid]
        if info.get("type", "").endswith(REL_TYPE_IMAGE) and _is_external_relationship(info):
            raise BrokenRelationshipError(
                "正文图片使用外部链接，无法生成自包含项目：rId={0}".format(rid),
                suggested_action="请在 Word 中把链接图片转换为嵌入图片后重新导入。",
                details={"rId": rid},
            )
    return warnings


# --- 3.3 标题样式映射与标题树解析 ---


def _parse_heading_styles(parts: Dict[str, bytes]) -> Dict[str, int]:
    """从 ``styles.xml`` 建立 styleId -> Heading 级别（1~6）映射。"""
    styles_xml = parts.get("word/styles.xml")
    if styles_xml is None:
        return {}
    sroot = _parse_xml(styles_xml, "word/styles.xml")
    heading_map: Dict[str, int] = {}
    for style in sroot.iter(_qn("style")):
        if style.get(_qn("type")) != "paragraph":
            continue
        style_id = style.get(_qn("styleId"))
        name_elem = style.find(_qn("name"))
        if name_elem is None:
            continue
        name_val = name_elem.get(_qn("val")) or ""
        # 匹配 "heading 1"、"Heading 2"、"标题 1" 等
        m = re.match(r"(?i)heading\s*(\d+)", name_val)
        if not m:
            m = re.match(r"标题\s*(\d+)", name_val)
        if m:
            level = int(m.group(1))
            if MIN_HEADING_LEVEL <= level <= MAX_HEADING_LEVEL and style_id:
                heading_map[style_id] = level
    return heading_map


def _build_heading_tree(
    parts: Dict[str, bytes], heading_style_map: Dict[str, int]
) -> List[HeadingInfo]:
    """遍历 ``document.xml`` 正文段落，按样式提取标题树。"""
    document_xml = parts.get("word/document.xml", b"")
    root = _parse_xml(document_xml, "word/document.xml")
    body = root.find(_qn("body"))
    if body is None:
        return []

    headings: List[HeadingInfo] = []
    for index, elem in enumerate(body):
        if etree.QName(elem).localname != "p":
            continue
        pPr = elem.find(_qn("pPr"))
        if pPr is None:
            continue
        pStyle = pPr.find(_qn("pStyle"))
        if pStyle is None:
            continue
        style_id = pStyle.get(_qn("val"))
        if not style_id:
            continue
        level = heading_style_map.get(style_id)
        if level is None:
            continue
        text = _para_text(elem)
        headings.append(
            HeadingInfo(
                level=level,
                style_id=style_id,
                text=text,
                body_index=index,
            )
        )
    return headings


def _para_text(p_elem) -> str:
    """提取段落纯文本（含 tab/br/cr）。"""
    parts: List[str] = []
    for node in p_elem.iter():
        tag = etree.QName(node).localname
        if tag == "t":
            parts.append(node.text or "")
        elif tag in ("tab",):
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts).strip()


# --- 3.4 层级校验（fail-closed） ---


def _validate_heading_hierarchy(headings: List[HeadingInfo]) -> None:
    """校验标题层级：至少一个 H1，且层级不跳跃。"""
    if not headings:
        raise MissingHeading1Error(
            "文档中没有使用 Heading 样式的标题。",
            suggested_action='请在 Word 中为一级标题应用「标题 1」样式后重新导入。',
        )
    if not any(h.level == 1 for h in headings):
        raise MissingHeading1Error(
            "源文档没有可识别的 Heading 1 标题样式。",
            suggested_action='请在 Word 中确认至少有一个段落使用「标题 1」样式。',
        )
    # 校验层级不跳跃：第一个标题必须是 H1，后续标题的级别不能比前一标题高超过 1。
    previous_level = 0
    for heading in headings:
        if heading.level == 1:
            previous_level = 1
            continue
        if previous_level == 0:
            # 第一个标题不是 H1（已被上面拦截，此处防御性）
            raise MissingHeading1Error(
                "第一个标题不是 Heading 1。",
                details={"firstHeading": heading.text[:80]},
            )
        if heading.level > previous_level + 1:
            raise HeadingHierarchyError(
                "标题层级跳跃：H{0} 之后直接出现 H{1}（标题：{2}）".format(
                    previous_level, heading.level, heading.text[:80]
                ),
                suggested_action="请修正标题样式层级，确保层级递增不超过 1。",
                details={
                    "previousLevel": str(previous_level),
                    "currentLevel": str(heading.level),
                    "heading": heading.text[:80],
                },
            )
        previous_level = heading.level


# --- 3.5 文档类型建议 ---


def _suggest_document_type(
    headings: List[HeadingInfo], parts: Dict[str, bytes]
) -> DocumentTypeSuggestion:
    """根据标题和封面关键字给出文档预设建议。

    低置信度时返回 ``confidence="low"``，调用方不得自动决定类型。
    """
    # 检查标题文本中是否包含"需求"/"设计"关键字
    all_text = " ".join(h.text for h in headings[:20])
    has_requirement = bool(re.search(r"需求", all_text))
    has_design = bool(re.search(r"(详细设计|系统设计|设计说明书)", all_text))

    # 检查封面文本（document.xml 前 2000 字符的纯文本）
    document_xml = parts.get("word/document.xml", b"")
    cover_text = ""
    try:
        root = _parse_xml(document_xml, "word/document.xml")
        body = root.find(_qn("body"))
        if body is not None:
            for elem in list(body)[:30]:
                cover_text += _para_text(elem) + " "
    except etree.XMLSyntaxError:
        pass
    cover_has_requirement = bool(re.search(r"需求", cover_text))
    cover_has_design = bool(re.search(r"(详细设计|系统设计|设计说明书)", cover_text))

    requirement_score = (1 if has_requirement else 0) + (1 if cover_has_requirement else 0)
    design_score = (1 if has_design else 0) + (1 if cover_has_design else 0)

    if design_score > requirement_score and design_score >= 1:
        confidence = "high" if design_score >= 2 else "low"
        return DocumentTypeSuggestion(
            document_type="design",
            confidence=confidence,
            reason='标题和封面关键字倾向「详细设计说明书」。' if confidence == "high"
            else '封面或标题中检测到「设计」关键字，但置信度不足，请用户确认。',
        )
    if requirement_score > design_score and requirement_score >= 1:
        confidence = "high" if requirement_score >= 2 else "low"
        return DocumentTypeSuggestion(
            document_type="requirement",
            confidence=confidence,
            reason='标题和封面关键字倾向「需求说明书」。' if confidence == "high"
            else '封面或标题中检测到「需求」关键字，但置信度不足，请用户确认。',
        )
    # 不是可明确识别的公司需求/设计文档时，安全地回落到通用模式。
    return DocumentTypeSuggestion(
        document_type="general",
        confidence="high",
        reason="未检测到需求/详细设计特征，建议使用「通用大文档」模式。",
    )


# --- 3.6 统计辅助 ---


def _count_images(parts: Dict[str, bytes]) -> int:
    """统计正文中的图片数量（drawing + pict）。"""
    document_xml = parts.get("word/document.xml", b"")
    if not document_xml:
        return 0
    root = _parse_xml(document_xml, "word/document.xml")
    count = 0
    for _ in root.iter(A + "blip"):
        count += 1
    for _ in root.iter(_qn("pict")):
        count += 1
    return count


def _count_tables(parts: Dict[str, bytes]) -> int:
    """统计正文中的表格数量。"""
    document_xml = parts.get("word/document.xml", b"")
    if not document_xml:
        return 0
    root = _parse_xml(document_xml, "word/document.xml")
    count = 0
    body = root.find(_qn("body"))
    if body is None:
        return 0
    for elem in body:
        if etree.QName(elem).localname == "tbl":
            count += 1
    return count
