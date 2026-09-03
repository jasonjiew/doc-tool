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

import os
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


# 兼容性别名：旧调用方按 ``OOXMLSecurityError`` 或 ``is_*`` 辅助使用。
__all__ = [
    "OOXMLSecurityError",
    "PARSE_LIMITS",
    "DocxPackage",
    "read_docx_package",
    "parse_xml_safe",
    "is_xml_part",
]
