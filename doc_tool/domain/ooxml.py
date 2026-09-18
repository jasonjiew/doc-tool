# -*- coding: utf-8 -*-
"""统一安全 OOXML 解析入口（纯 domain，无 Qt）。

模板生成、复杂表格读取、导入、构建与校验全部经本模块读取 DOCX 包与解析
XML 部件，消除各链路独立的包读取/解析实现，保证安全参数全链路一致：

- 解压前校验包体量：条目数、总展开体积、单条目体积、压缩比均不超过安全上限。
- ZIP 完整性 + CRC 校验：损坏条目在读取前被拒绝。
- XML 安全解析：拒绝 DTD/实体声明，禁用实体解析/网络/DTD/超大树，良构失败
  识别为解析失败而非崩溃。

本模块只抛中性 ``OOXMLSecurityError``（含部件名与原因），由各调用方映射为
自身的错误类型（导入侧 ``InvalidDocxError``/``BrokenRelationshipError`` 等
``DocToolError`` 子类，构建/校验侧 ``AutomationError``）。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from lxml import etree

# 解压前安全检查上限（明显高于当前真实基线文档）。
PARSE_LIMITS = {
    "max_entries": 20_000,
    "max_total_uncompressed_bytes": 512 * 1024 * 1024,
    "max_single_entry_bytes": 256 * 1024 * 1024,
    "max_xml_part_bytes": 64 * 1024 * 1024,
    "max_compression_ratio": 2_000,
}

# 解析前扫描的字节数：DTD/实体声明必须出现在文档头部。
_DECLARATION_SCAN_BYTES = 4096

# 加密 DOCX 在 ZIP 中的特征条目。
_ENCRYPTED_ENTRY = "EncryptedPackage"

# 核心部件（缺失即不是可用的 DOCX 包）。
_REQUIRED_PARTS = ("word/document.xml",)


class OOXMLSecurityError(Exception):
    """统一安全解析入口的中性解析异常。

    Attributes:
        part_name: 出问题的部件名（未知部件为空串）。
        reason: 失败原因分类（"limits" | "crc" | "dtd" | "wellformed" | "missing"）。
        cause: 底层异常（ZIP/读取/解析失败），供各调用方渲染自身错误消息。
    """

    def __init__(
        self,
        message: str,
        *,
        part_name: str = "",
        reason: str = "",
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.part_name = part_name
        self.reason = reason
        self.cause = cause


def _limit(name: str) -> int:
    return int(PARSE_LIMITS[name])


def parse_xml_safe(data: bytes, part_name: str = ""):
    """安全解析 XML 部件字节为 lxml 元素树。

    拒绝 DTD/实体声明（前缀扫描 + doctype 复查），以禁用实体/网络/DTD/超大
    树模式解析；良构失败抛 ``OOXMLSecurityError``（reason="wellformed"）而非
    裸 lxml 异常。
    """
    upper = data[:_DECLARATION_SCAN_BYTES].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise OOXMLSecurityError(
            "XML 部件包含不允许的 DTD/实体声明：{0}".format(part_name or "未知部件"),
            part_name=part_name,
            reason="dtd",
        )
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
    )
    try:
        root = etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise OOXMLSecurityError(
            "XML 部件解析失败：{0}（{1}）".format(part_name or "未知部件", exc),
            part_name=part_name,
            reason="wellformed",
        ) from exc
    if root.getroottree().docinfo.doctype:
        raise OOXMLSecurityError(
            "XML 部件包含不允许的 DTD 声明：{0}".format(part_name or "未知部件"),
            part_name=part_name,
            reason="dtd",
        )
    return root


@dataclass
class DocxPackage:
    """已通过安全检查的 DOCX 包（上下文管理器）。

    ``read_docx_package`` 打开并校验（扩展名、ZIP 完整性、CRC、上限）后返回
    本对象；``read(name)`` 按需读取单个部件，``read_xml_parts()`` 返回全部
    XML/rels 部件的字典。所有读路径共用同一安全入口。
    """

    _handle: zipfile.ZipFile
    path: Path

    @property
    def names(self) -> List[str]:
        return self._handle.namelist()

    @property
    def infolist(self) -> List[zipfile.ZipInfo]:
        return self._handle.infolist()

    def read(self, name: str) -> bytes:
        """读取单个部件字节（XML 部件超过安全上限时拒绝）。

        条目不存在抛 ``OOXMLSecurityError``（reason="missing"）而非裸
        ``KeyError``，保持「中性解析异常」契约。
        """
        try:
            if name.endswith((".xml", ".rels")):
                info = self._handle.getinfo(name)
                if info.file_size > _limit("max_xml_part_bytes"):
                    raise OOXMLSecurityError(
                        "XML 部件超过安全上限：{0}".format(name),
                        part_name=name,
                        reason="limits",
                    )
            return self._handle.read(name)
        except KeyError as exc:
            raise OOXMLSecurityError(
                "ZIP 条目不存在：{0}".format(name),
                part_name=name,
                reason="missing",
                cause=exc,
            ) from exc
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise OOXMLSecurityError(
                "读取 ZIP 条目失败：{0}".format(name),
                part_name=name,
                reason="crc",
                cause=exc,
            ) from exc

    def read_xml_parts(self) -> Dict[str, bytes]:
        """返回全部 XML/rels 部件字节（跳过目录与非 XML 部件）。"""
        parts: Dict[str, bytes] = {}
        for info in self._handle.infolist():
            name = info.filename
            if name.endswith("/") or not (name.endswith(".xml") or name.endswith(".rels")):
                continue
            parts[name] = self.read(name)
        return parts

    def read_all(self) -> Dict[str, bytes]:
        """返回全部部件字节（含媒体等二进制部件）。"""
        return {name: self.read(name) for name in self._handle.namelist()}

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "DocxPackage":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def read_docx_package(path: Union[str, Path]) -> DocxPackage:
    """打开 DOCX 包并执行统一安全检查（扩展名、ZIP、CRC、上限）。

    扩展名必须为 ``.docx``（不区分大小写）；非 ZIP、损坏 ZIP、CRC 失败或任一
    体量上限超限均抛 ``OOXMLSecurityError``，不创建可用的读取入口。
    """
    file_path = Path(path)
    if not file_path.name.lower().endswith(".docx"):
        raise OOXMLSecurityError(
            "文件扩展名不是 .docx：{0}".format(file_path.name),
            part_name="",
            reason="extension",
        )
    h = b""
    try:
        with open(str(file_path), "rb") as test_f:
            h = test_f.read(16)
        handle = zipfile.ZipFile(str(file_path), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        if h.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise OOXMLSecurityError(
                "文件实际为旧版 Word 97-2003 二进制格式（.doc），仅文件扩展名被修改为了 .docx（路径={0}）".format(file_path),
                part_name="",
                reason="doc_as_docx",
                cause=exc,
            ) from exc
        raise OOXMLSecurityError(
            "文件不是有效的 ZIP 包或不存在（路径={0}，前16字节={1!r}）：{2}".format(file_path, h, exc),
            part_name="",
            reason="zip",
            cause=exc,
        ) from exc
    try:
        _check_encryption(handle)
        _check_limits(handle)
        _check_required_parts(handle)
        bad = handle.testzip()
    except OOXMLSecurityError:
        handle.close()
        raise
    except Exception:
        handle.close()
        raise
    if bad is not None:
        handle.close()
        raise OOXMLSecurityError(
            "ZIP 包 CRC 校验失败：{0}".format(bad),
            part_name=bad,
            reason="crc",
        )
    return DocxPackage(handle, file_path)


def _check_encryption(handle: zipfile.ZipFile) -> None:
    """检测加密 DOCX（OOXML 加密后 ZIP 内仅含 ``EncryptedPackage``）。"""
    names = handle.namelist()
    if _ENCRYPTED_ENTRY in names and "word/document.xml" not in names:
        raise OOXMLSecurityError(
            "文件已加密或受密码保护。",
            part_name=_ENCRYPTED_ENTRY,
            reason="encrypted",
        )


def _check_limits(handle: zipfile.ZipFile) -> None:
    """解压前校验条目数、总展开体积、单条目体积与压缩比上限。"""
    infos = handle.infolist()
    if len(infos) > _limit("max_entries"):
        raise OOXMLSecurityError(
            "DOCX 包含过多 ZIP 条目：{0}".format(len(infos)),
            part_name="",
            reason="limits",
        )
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > _limit("max_single_entry_bytes"):
            raise OOXMLSecurityError(
                "DOCX 包含异常大的条目：{0}".format(info.filename),
                part_name=info.filename,
                reason="limits",
            )
        if (
            info.compress_size > 0
            and info.file_size / info.compress_size
            > _limit("max_compression_ratio")
        ):
            raise OOXMLSecurityError(
                "DOCX 包含异常压缩比的条目：{0}".format(info.filename),
                part_name=info.filename,
                reason="limits",
            )
    if total > _limit("max_total_uncompressed_bytes"):
        raise OOXMLSecurityError(
            "DOCX 解压后的总大小超过安全上限：{0}".format(total),
            part_name="",
            reason="limits",
        )


def _check_required_parts(handle: zipfile.ZipFile) -> None:
    """校验 DOCX 核心部件存在。"""
    names = set(handle.namelist())
    for part in _REQUIRED_PARTS:
        if part not in names:
            raise OOXMLSecurityError(
                "缺少核心部件：{0}".format(part),
                part_name=part,
                reason="missing",
            )


def is_xml_part(name: str) -> bool:
    """是否为应走安全解析的 XML/rels 部件。"""
    return name.endswith(".xml") or name.endswith(".rels")


# --- Heading 样式识别（全仓库唯一实现） ---------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{" + _W_NS + "}"

# 本工具只处理 Heading 1~6。
HEADING_LEVEL_MIN = 1
HEADING_LEVEL_MAX = 6

# 样式名 -> 级别。英文内置名（"heading 1"）先于本地化名（"标题1"）匹配：
# 两者可能同时存在，内置名是「这是真正的 Word Heading」更可靠的信号。
_HEADING_NAME_PATTERNS = (
    (re.compile(r"(?i)heading\s*(\d+)"), True),
    (re.compile(r"标题\s*(\d+)"), False),
)


def _qn(tag: str) -> str:
    """限定为 WordprocessingML 主命名空间的标签名。"""
    return _W + tag


@dataclass(frozen=True)
class HeadingStyleCandidate:
    """``styles.xml`` 中一个声称属于某 Heading 级别的段落样式。

    Word 允许用户基于内置 Heading 派生自定义样式并沿用相似名称（例如
    ``标题1`` 基于 ``heading 1``），此时同一级别会有多个候选。这里保留
    全部候选及其判定依据，由 :func:`resolve_heading_styles` 确定性择优。
    """

    style_id: str
    level: int
    name: str
    index: int
    custom: bool
    outline_level: Optional[int]
    based_on: str
    builtin_name: bool


def _style_outline_level(style) -> Optional[int]:
    """读取 ``w:pPr/w:outlineLvl`` 的大纲级别（0 基）；缺失返回 ``None``。"""
    properties = style.find(_qn("pPr"))
    if properties is None:
        return None
    outline = properties.find(_qn("outlineLvl"))
    if outline is None:
        return None
    try:
        return int(outline.get(_qn("val")))
    except (TypeError, ValueError):
        return None


def heading_style_candidates(styles_root) -> List[HeadingStyleCandidate]:
    """列出已解析 ``w:styles`` 根元素中全部 Heading 段落样式候选（按出现顺序）。"""
    if styles_root is None:
        return []
    candidates: List[HeadingStyleCandidate] = []
    for index, style in enumerate(styles_root.iter(_qn("style"))):
        if style.get(_qn("type")) != "paragraph":
            continue
        style_id = style.get(_qn("styleId"))
        name_elem = style.find(_qn("name"))
        if not style_id or name_elem is None:
            continue
        name = name_elem.get(_qn("val")) or ""
        level = 0
        builtin_name = False
        for pattern, is_builtin in _HEADING_NAME_PATTERNS:
            match = pattern.match(name)
            if match:
                level = int(match.group(1))
                builtin_name = is_builtin
                break
        if not HEADING_LEVEL_MIN <= level <= HEADING_LEVEL_MAX:
            continue
        based_on_elem = style.find(_qn("basedOn"))
        candidates.append(
            HeadingStyleCandidate(
                style_id=style_id,
                level=level,
                name=name,
                index=index,
                custom=style.get(_qn("customStyle")) == "1",
                outline_level=_style_outline_level(style),
                based_on=(based_on_elem.get(_qn("val")) or "") if based_on_elem is not None else "",
                builtin_name=builtin_name,
            )
        )
    return candidates


def heading_style_usage(document_root) -> Dict[str, int]:
    """统计 ``document.xml`` 中各段落样式（``w:pStyle``）被引用的次数。"""
    if document_root is None:
        return {}
    usage: Dict[str, int] = {}
    for style_ref in document_root.iter(_qn("pStyle")):
        style_id = style_ref.get(_qn("val"))
        if style_id:
            usage[style_id] = usage.get(style_id, 0) + 1
    return usage


def _candidate_rank(
    candidate: HeadingStyleCandidate,
    heading_ids: set,
    usage: Optional[Dict[str, int]] = None,
) -> tuple:
    """候选优先级排序键（元组越小越优先）。

    文档实际使用次数是最强信号：正文真的在用哪个样式，就应当继续用哪个。
    没有 usage 信息（或并列）时才退化为「哪个更像内置 Heading」。
    """
    count = usage.get(candidate.style_id, 0) if usage else 0
    return (
        -count,
        1 if candidate.custom else 0,
        0 if candidate.outline_level is not None else 1,
        1 if candidate.based_on in heading_ids else 0,
        0 if candidate.builtin_name else 1,
        candidate.index,
    )


def resolve_heading_styles(
    styles_root, usage: Optional[Dict[str, int]] = None
) -> Dict[int, str]:
    """建立 Heading 级别 -> styleId 映射，并确定性消解同级多候选冲突。

    这是「构建时要写哪个 styleId」的唯一决策点。同一级别出现多个候选时，
    依次比较：文档实际使用次数、是否自定义样式、是否显式声明大纲级别、
    是否基于其他 Heading 派生、是否英文内置样式名、``styles.xml`` 中的位置。

    缺省按出现顺序覆盖会让靠后的自定义样式（如基于 ``heading 1`` 派生的
    ``标题1``）顶掉真正的内置 Heading，构建出的章节标题因此丢掉内置样式
    语义（大纲级别、编号关联 ``numId``、TOC 归属），故必须显式择优。
    """
    candidates = heading_style_candidates(styles_root)
    if not candidates:
        return {}
    heading_ids = {candidate.style_id for candidate in candidates}
    best: Dict[int, HeadingStyleCandidate] = {}
    for candidate in candidates:
        current = best.get(candidate.level)
        if current is None or _candidate_rank(
            candidate, heading_ids, usage
        ) < _candidate_rank(current, heading_ids, usage):
            best[candidate.level] = candidate
    return {level: candidate.style_id for level, candidate in sorted(best.items())}


def resolve_heading_styles_from_xml(
    styles_xml: bytes, usage: Optional[Dict[str, int]] = None
) -> Dict[int, str]:
    """:func:`resolve_heading_styles` 的字节入口，内部安全解析 ``styles.xml``。"""
    if not styles_xml:
        return {}
    return resolve_heading_styles(
        parse_xml_safe(styles_xml, "word/styles.xml"), usage=usage
    )


def parse_heading_styles(styles_xml: bytes) -> Dict[str, int]:
    """从 ``styles.xml`` 建立 styleId -> Heading 级别（1~6）识别映射。

    识别映射刻意保留**全部**同级候选（不做择优）：正文里出现的任何一种
    标题样式都必须能被认出来，否则标题树会漏掉整章内容。择优只发生在
    :func:`resolve_heading_styles`（决定构建时写哪个 styleId）。
    """
    if not styles_xml:
        return {}
    root = parse_xml_safe(styles_xml, "word/styles.xml")
    return {candidate.style_id: candidate.level for candidate in heading_style_candidates(root)}


# 兼容性别名：旧调用方按 ``OOXMLSecurityError`` 或 ``is_*`` 辅助使用。
__all__ = [
    "OOXMLSecurityError",
    "PARSE_LIMITS",
    "DocxPackage",
    "HeadingStyleCandidate",
    "HEADING_LEVEL_MAX",
    "HEADING_LEVEL_MIN",
    "heading_style_candidates",
    "heading_style_usage",
    "parse_heading_styles",
    "resolve_heading_styles",
    "resolve_heading_styles_from_xml",
    "read_docx_package",
    "parse_xml_safe",
    "is_xml_part",
]
