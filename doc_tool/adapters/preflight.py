# -*- coding: utf-8 -*-
"""Word 导入预检适配器。

任务 3.1-3.6：在写入正式项目前，对任意文件名的 DOCX 执行完整预检，
任何检查失败均抛出 ``DocToolError`` 子类（fail-closed），不创建项目目录。

预检内容：
- 3.1 包结构校验：扩展名、ZIP 完整性（CRC）、XML 良构、加密/损坏检测。
- 3.2 关系目标完整性及正文资源引用预检。
- 3.3 ``styles.xml`` 的 styleId 到 Heading 1~6 映射和标题树解析。
- 3.4 无 Heading 1、标题层级跳跃和无法闭合树的 fail-closed 校验。
- 3.6 导入预览模型：标题级别计数、首尾标题、图片/表格数量和告警。

公共版只创建通用大文档项目；预检不再基于「需求/详细设计」关键词给出文档
类型建议。业务关键词不影响项目类型（任务 4.3）。
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from lxml import etree

from doc_tool.adapters.fidelity import FidelityReport, scan_fidelity
from doc_tool.domain.errors import (
    BrokenRelationshipError,
    DocToolError,
    HeadingHierarchyError,
    InvalidDocxError,
    MissingHeading1Error,
)
from doc_tool.domain.ooxml import (
    OOXMLSecurityError,
    parse_heading_styles,
    parse_xml_safe,
    read_docx_package,
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

# DOCX 包中必须存在的核心部件。
REQUIRED_PARTS = ("word/document.xml",)

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


@dataclass(frozen=True)
class StyleCensus:
    """一个段落样式的普查信息（供样式映射向导展示）。"""

    style_id: str
    name: str
    usage_count: int
    suspected_heading: bool
    sample_text: str = ""


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
    fidelity: Optional[FidelityReport] = None
    style_census: Dict[str, StyleCensus] = field(default_factory=dict)

    @property
    def has_heading1(self) -> bool:
        return self.heading_level_counts.get(1, 0) > 0


# --- 预检主入口 ---


def preflight(
    path: Union[str, Path],
    heading_style_map: Optional[Dict[str, int]] = None,
    allow_missing_headings: bool = False,
) -> ImportPreview:
    """对任意文件名的 DOCX 执行完整预检，返回预览模型。

    任何检查失败均抛出 ``DocToolError`` 子类，调用方应据此向用户显示
    稳定错误码和修复建议，且不创建项目目录。

    Args:
        path: 用户选择的 DOCX 文件路径，文件名任意。
        heading_style_map: 可选的用户样式映射覆盖（styleId -> 级别 1~6）。
            传入时不再自动解析 styles.xml 的 Heading 样式，标题树按该映射构建。
        allow_missing_headings: 为 True 时跳过标题层级 fail-closed 校验，
            供向导在进入「样式映射」步骤前扫描用；结构性错误仍会抛出。

    Returns:
        ``ImportPreview`` 预览模型。

    Raises:
        InvalidDocxError: 扩展名、ZIP、CRC、XML 或加密检查失败。
        BrokenRelationshipError: 关系目标缺失或正文引用的资源不存在。
        MissingHeading1Error: 没有可识别的 Heading 1（未传映射且未宽松扫描时）。
        HeadingHierarchyError: 标题层级跳跃，无法构成可闭合章节树。
    """
    file_path = Path(path)
    file_name = file_path.name
    file_size = file_path.stat().st_size if file_path.exists() else 0

    # --- 3.1 包结构校验（统一安全入口） ---
    _check_extension(file_name)
    try:
        with read_docx_package(file_path) as package:
            parts = package.read_xml_parts()
            _check_xml_wellformed(parts)
            _check_required_parts(parts)

            # --- 3.2 关系目标完整性 ---
            rel_map = _parse_relationships(parts)
            _check_relationship_targets(rel_map, set(package.names))

            # --- 3.3 标题样式映射与标题树 ---
            if heading_style_map is None:
                heading_style_map = _parse_heading_styles(parts)
            else:
                heading_style_map = dict(heading_style_map)
            headings = _build_heading_tree(parts, heading_style_map)

            # --- 3.4 层级校验（fail-closed；样式映射/宽松扫描时由调用方负责） ---
            if not allow_missing_headings:
                _validate_heading_hierarchy(headings)

            # --- 3.2 续：正文资源引用预检 ---
            body_resource_warnings = _check_body_resource_references(parts, rel_map)

            # --- 2.1 保真扫描（分级报告，随预览返回） ---
            fidelity_report = scan_fidelity(parts)

            # --- 3.1 段落样式普查（供样式映射页展示） ---
            style_census = census_paragraph_styles(parts)

            # --- 3.6 预览统计 ---
            image_count = _count_images(parts)
            table_count = _count_tables(parts)
            all_names = package.names
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

            # --- 3.5 文档类型建议：公共版不再做基于业务关键词的类型建议 ---

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
                fidelity=fidelity_report,
                style_census=style_census,
            )
    except OOXMLSecurityError as exc:
        raise _map_security_error(exc) from exc


# --- 3.1 包结构校验 ---


def _check_extension(file_name: str) -> None:
    """校验文件扩展名为 ``.docx``（不区分大小写）。"""
    if not file_name.lower().endswith(".docx"):
        raise InvalidDocxError(
            "文件扩展名不是 .docx：{0}".format(file_name),
            suggested_action="请选择扩展名为 .docx 的 Word 文档。",
            details={"fileName": file_name},
        )


def _map_security_error(exc: OOXMLSecurityError) -> DocToolError:
    """把统一安全入口的中性异常映射为 ``InvalidDocxError``（含稳定错误码）。"""
    if exc.reason == "dtd":
        return InvalidDocxError(
            "XML 部件包含不允许的 DTD/实体声明：{0}".format(
                exc.part_name or "未知部件"
            ),
            details={"part": exc.part_name},
        )
    if exc.reason == "wellformed":
        return InvalidDocxError(
            "XML 部件解析失败：{0}".format(exc.part_name or "未知部件"),
            suggested_action="文件可能已损坏，请在 Word 中尝试打开并另存后重新导入。",
            details={"part": exc.part_name, "error": str(exc)},
        )
    if exc.reason == "encrypted":
        return InvalidDocxError(
            "文件已加密或受密码保护。",
            suggested_action="请先在 Word 中解除文档密码保护后重新导入。",
            details={"entry": exc.part_name},
        )
    if exc.reason == "limits":
        return InvalidDocxError(
            "DOCX 包大小超过安全上限：{0}".format(exc),
            details={"reason": str(exc)},
        )
    if exc.reason == "crc":
        return InvalidDocxError(
            "ZIP 包 CRC 校验失败：{0}".format(exc.part_name),
            suggested_action="文件可能在传输中损坏，请重新获取原始 DOCX。",
            details={"badEntry": exc.part_name},
        )
    if exc.reason == "doc_as_docx":
        return InvalidDocxError(
            "文件实际为旧版 Word 97-2003 二进制格式（.doc），仅文件扩展名被修改为了 .docx",
            suggested_action="请在 Word 或 WPS 中打开该文件，通过【另存为】将保存类型选择为【Word 文档 (*.docx)】后重新导入。",
            details={"magic": "d0cf11e0", "originalFormat": "doc"},
        )
    if exc.reason == "zip":
        return InvalidDocxError(
            "文件不是有效的 DOCX 压缩包（可能损坏或格式不符）：{0}".format(exc),
            suggested_action="请确认文件是标准 Word .docx 格式并在 Word 中尝试重新另存。",
            details={"error": str(exc)},
        )
    if exc.reason == "missing":
        return InvalidDocxError(
            "缺少核心部件：{0}".format(exc.part_name),
            suggested_action="文件结构不完整，请确认是标准的 Word .docx 文件。",
            details={"missingPart": exc.part_name},
        )
    return InvalidDocxError(str(exc))


def _check_xml_wellformed(parts: Dict[str, bytes]) -> None:
    """校验所有 XML 部件良构（统一安全解析，DTD/实体/良构失败均映射）。"""
    for name, data in parts.items():
        if not name.endswith(".xml") and not name.endswith(".rels"):
            continue
        try:
            parse_xml_safe(data, name)
        except OOXMLSecurityError as exc:
            raise _map_security_error(exc) from exc


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
    rels_root = parse_xml_safe(parts[rels_name], rels_name)
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
    rel_map: Dict[str, Dict[str, str]], names: set
) -> None:
    """校验每条关系的 Target 在包内存在（外部链接除外）。"""
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
    root = parse_xml_safe(document_xml, "word/document.xml")
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
    """从 ``styles.xml`` 建立 styleId -> Heading 级别（1~6）识别映射。

    实现统一在 :mod:`doc_tool.domain.ooxml`（全仓库唯一事实源）。识别映射
    保留同级全部候选：正文里出现的任何标题样式都必须能被认出来，否则标题
    树会整章漏掉。
    """
    styles_xml = parts.get("word/styles.xml")
    if styles_xml is None:
        return {}
    return parse_heading_styles(styles_xml)


def census_paragraph_styles(parts: Dict[str, bytes]) -> Dict[str, StyleCensus]:
    """普查段落样式：显示名 + 正文实际使用次数 + 疑似标题标记（任务 3.1）。

    从 ``styles.xml`` 枚举全部段落样式，从 ``document.xml`` 统计每个样式在正文
    段落中的实际使用次数。已被自动识别为 Heading 的样式不重复标记为疑似标题。
    """
    styles_xml = parts.get("word/styles.xml")
    if styles_xml is None:
        return {}
    sroot = parse_xml_safe(styles_xml, "word/styles.xml")
    style_names: Dict[str, str] = {}
    for style in sroot.iter(_qn("style")):
        if style.get(_qn("type")) != "paragraph":
            continue
        style_id = style.get(_qn("styleId"))
        name_elem = style.find(_qn("name"))
        if style_id and name_elem is not None:
            style_names[style_id] = name_elem.get(_qn("val")) or ""

    document_xml = parts.get("word/document.xml", b"")
    usage: Dict[str, int] = {}
    sample_texts: Dict[str, str] = {}
    if document_xml:
        root = parse_xml_safe(document_xml, "word/document.xml")
        for paragraph in root.iter(_qn("p")):
            pPr = paragraph.find(_qn("pPr"))
            if pPr is None:
                continue
            pStyle = pPr.find(_qn("pStyle"))
            if pStyle is None:
                continue
            style_id = pStyle.get(_qn("val"))
            if style_id:
                usage[style_id] = usage.get(style_id, 0) + 1
                if style_id not in sample_texts:
                    p_text = _para_text(paragraph).strip()
                    if p_text:
                        sample_texts[style_id] = p_text[:40]

    census: Dict[str, StyleCensus] = {}
    for style_id, name in style_names.items():
        census[style_id] = StyleCensus(
            style_id=style_id,
            name=name,
            usage_count=usage.get(style_id, 0),
            suspected_heading=_looks_like_heading(name),
            sample_text=sample_texts.get(style_id, ""),
        )
    return census


def _looks_like_heading(name: str) -> bool:
    """判断样式名是否疑似标题（非标准 Heading 命名，但含层级/章节特征）。"""
    lowered = (name or "").strip().lower()
    if re.match(r"(?i)heading\s*\d", lowered) or re.match(r"标题\s*\d", lowered):
        return False  # 已是标准 Heading 样式，由自动识别处理
    return bool(
        re.search(r"(章|节|篇|部分|标题|heading|h[1-9])", lowered, re.I)
        or re.match(r"^[\d\.]+\s*$", lowered)
        or re.fullmatch(r"[一二三四五六七八九十百]+", lowered)
    )


def validate_heading_mapping(path: Union[str, Path], heading_style_map: Dict[str, int]) -> str:
    """按用户样式映射重建标题树并校验层级；返回错误文本（空串表示通过）。

    供向导「样式映射」页在用户完成映射后即时校验：至少一个样式映射到级别 1，
    且映射后正文标题序列不存在层级跳跃。
    """
    if not heading_style_map:
        return "请至少把一个段落样式映射到级别 1（Heading 1）。"
    if 1 not in heading_style_map.values():
        return "请至少把一个段落样式映射到级别 1（Heading 1）。"
    try:
        with read_docx_package(path) as package:
            parts = package.read_xml_parts()
    except OOXMLSecurityError as exc:
        # 源文件在向导预检后可能被删除/占用/损坏：映射校验必须返回稳定错误
        # 文本而非把内部异常传播进向导页面（否则页面导航异常、错误不可读）。
        return "源文档无法读取：{0}".format(_map_security_error(exc).user_message)
    headings = _build_heading_tree(parts, heading_style_map)
    try:
        _validate_heading_hierarchy(headings)
    except HeadingHierarchyError as exc:
        return exc.user_message
    except MissingHeading1Error:
        if not headings:
            return "映射到级别 1 的样式在正文中没有被使用，无法构成章节树。"
        return "按当前映射未找到可识别的 Heading 1 标题。"
    return ""


def _build_heading_tree(
    parts: Dict[str, bytes], heading_style_map: Dict[str, int]
) -> List[HeadingInfo]:
    """遍历 ``document.xml`` 正文段落，按样式提取标题树。"""
    document_xml = parts.get("word/document.xml", b"")
    root = parse_xml_safe(document_xml, "word/document.xml")
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


# --- 3.6 统计辅助 ---


def _count_images(parts: Dict[str, bytes]) -> int:
    """统计正文中的图片数量（drawing + pict）。"""
    document_xml = parts.get("word/document.xml", b"")
    if not document_xml:
        return 0
    root = parse_xml_safe(document_xml, "word/document.xml")
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
    root = parse_xml_safe(document_xml, "word/document.xml")
    count = 0
    body = root.find(_qn("body"))
    if body is None:
        return 0
    for elem in body:
        if etree.QName(elem).localname == "tbl":
            count += 1
    return count


def generate_preview_heading_tree(
    path_or_parts: Union[str, Path, Dict[str, bytes]],
    heading_style_map: Dict[str, int],
) -> Tuple[List[HeadingInfo], str]:
    if not heading_style_map or 1 not in heading_style_map.values():
        return [], "未包含级别 1（章标题）"
    try:
        if isinstance(path_or_parts, (str, Path)):
            with read_docx_package(path_or_parts) as package:
                parts = package.read_xml_parts()
        else:
            parts = path_or_parts
    except Exception as exc:
        return [], f"读取文档失败: {exc}"

    headings = _build_heading_tree(parts, heading_style_map)
    error = ""
    try:
        _validate_heading_hierarchy(headings)
    except HeadingHierarchyError as exc:
        error = exc.user_message
    except MissingHeading1Error as exc:
        if not headings:
            error = "映射到级别 1 的样式在正文中未被使用"
        else:
            error = getattr(exc, "user_message", None) or "第一个标题不是级别 1（章标题）"
    return headings, error
