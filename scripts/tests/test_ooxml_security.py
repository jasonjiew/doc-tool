# -*- coding: utf-8 -*-
"""统一安全 OOXML 解析入口自动测试（计划 2，任务 4.1）。

覆盖：DTD/实体拒绝、条目/体积/压缩比超限拒绝、CRC 失败、良构失败、错误映射、
加密检测、缺核心部件、按需读部件。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_DOC = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p/></w:body></w:document>"
)


def _make_docx(parts: dict, *, name="sample.docx", stored=False) -> Path:
    """构造临时 .docx（zip），parts: name -> bytes。"""
    tmp = Path(tempfile.mkdtemp(prefix="doc-tool-ooxml-"))
    path = tmp / name
    compression = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(str(path), "w", compression) as z:
        if "word/document.xml" not in parts:
            parts = dict(parts)
            parts["word/document.xml"] = _DOC
        for n, data in parts.items():
            z.writestr(n, data)
    return path


class ParseXmlSafeTests(unittest.TestCase):
    """parse_xml_safe：DTD/实体拒绝、良构失败、正常解析。

    本类测试全部使用内存字节，不创建临时文件，因此不做任何临时目录清理——
    绝不可删除整个系统 temp 目录（会破坏同进程其他测试的 mkdtemp 目录）。
    """

    def test_normal_xml_parsed(self):
        from doc_tool.domain.ooxml import parse_xml_safe

        root = parse_xml_safe(_DOC, "word/document.xml")
        self.assertEqual(root.tag, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document")

    def test_doctype_declaration_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe

        data = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY x "y">]><foo/>'
        with self.assertRaises(OOXMLSecurityError) as ctx:
            parse_xml_safe(data, "word/document.xml")
        self.assertEqual(ctx.exception.reason, "dtd")
        self.assertIn("word/document.xml", str(ctx.exception))

    def test_entity_declaration_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe

        data = b'<?xml version="1.0"?><foo>&xxe;</foo><!ENTITY xxe "boom">'
        with self.assertRaises(OOXMLSecurityError) as ctx:
            parse_xml_safe(data, "bad.xml")
        self.assertEqual(ctx.exception.reason, "dtd")

    def test_malformed_xml_reported_not_crash(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe

        data = b"<foo><bar></foo>"
        with self.assertRaises(OOXMLSecurityError) as ctx:
            parse_xml_safe(data, "broken.xml")
        self.assertEqual(ctx.exception.reason, "wellformed")
        self.assertIn("broken.xml", str(ctx.exception))

    def test_empty_bytes_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe

        with self.assertRaises(OOXMLSecurityError):
            parse_xml_safe(b"", "empty.xml")


class ReadPackageTests(unittest.TestCase):
    """read_docx_package：扩展名、ZIP、CRC、上限、加密、缺核心部件。"""

    def _docx(self, **parts) -> Path:
        return _make_docx(parts)

    def _cleanup(self, path: Path):
        shutil.rmtree(path.parent, ignore_errors=True)

    def test_reads_docx_package(self):
        from doc_tool.domain.ooxml import read_docx_package

        path = _make_docx({"word/styles.xml": b"<w:styles/>"})
        with read_docx_package(path) as package:
            self.assertIn("word/document.xml", package.names)
            self.assertIn("word/styles.xml", package.names)
        self._cleanup(path)

    def test_read_single_part(self):
        from doc_tool.domain.ooxml import read_docx_package

        path = _make_docx({"word/styles.xml": b"<w:styles/>"})
        with read_docx_package(path) as package:
            self.assertEqual(package.read("word/styles.xml"), b"<w:styles/>")
        self._cleanup(path)

    def test_read_xml_parts_returns_only_xml(self):
        from doc_tool.domain.ooxml import read_docx_package

        path = _make_docx({"word/media/a.png": b"aaaa"})
        with read_docx_package(path) as package:
            parts = package.read_xml_parts()
        self.assertIn("word/document.xml", parts)
        self.assertNotIn("word/media/a.png", parts)
        self._cleanup(path)

    def test_extension_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

        path = _make_docx({}, name="sample.txt")
        with self.assertRaises(OOXMLSecurityError) as ctx:
            read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "extension")
        self._cleanup(path)

    def test_not_a_zip_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

        path = Path(tempfile.mkdtemp(prefix="doc-tool-ooxml-")) / "sample.docx"
        path.write_bytes(b"this is not a zip at all")
        with self.assertRaises(OOXMLSecurityError) as ctx:
            read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "zip")
        self._cleanup(path)

    def test_encrypted_docx_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

        # 加密 DOCX：仅含 EncryptedPackage、不含 document.xml
        tmp = Path(tempfile.mkdtemp(prefix="doc-tool-ooxml-"))
        path = tmp / "enc.docx"
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("EncryptedPackage", b"ciphertext")
        with self.assertRaises(OOXMLSecurityError) as ctx:
            read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "encrypted")
        self._cleanup(path)

    def test_missing_core_part_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

        tmp = Path(tempfile.mkdtemp(prefix="doc-tool-ooxml-"))
        path = tmp / "empty.docx"
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/styles.xml", b"<w:styles/>")
        with self.assertRaises(OOXMLSecurityError) as ctx:
            read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "missing")
        self._cleanup(path)


class PackageLimitTests(unittest.TestCase):
    """体量/压缩比超限拒绝（monkeypatch PARSE_LIMITS 以构造小样本）。"""

    def _docx(self, **parts) -> Path:
        return _make_docx(parts)

    def _cleanup(self, path: Path):
        shutil.rmtree(path.parent, ignore_errors=True)

    def test_entry_count_limit(self):
        from unittest import mock

        from doc_tool.domain.ooxml import PARSE_LIMITS, OOXMLSecurityError, read_docx_package

        tmp = Path(tempfile.mkdtemp(prefix="doc-tool-ooxml-"))
        path = tmp / "many.docx"
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_STORED) as z:
            for i in range(5):
                z.writestr("extra_{0}.xml".format(i), b"<x/>")
        # 上限校验在核心部件校验之前，缺 document.xml 不影响超限判定
        with mock.patch.dict(PARSE_LIMITS, {"max_entries": 3}):
            with self.assertRaises(OOXMLSecurityError) as ctx:
                read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "limits")
        self._cleanup(path)

    def test_single_entry_size_limit(self):
        from unittest import mock

        from doc_tool.domain.ooxml import PARSE_LIMITS, OOXMLSecurityError, read_docx_package

        path = self._docx(big=b"x" * 4096)
        with mock.patch.dict(PARSE_LIMITS, {"max_single_entry_bytes": 1024}):
            with self.assertRaises(OOXMLSecurityError) as ctx:
                read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "limits")
        self._cleanup(path)

    def test_compression_ratio_limit(self):
        from unittest import mock

        from doc_tool.domain.ooxml import PARSE_LIMITS, OOXMLSecurityError, read_docx_package

        # 高可压缩数据：压缩比远超阈值
        path = self._docx(big=b"A" * 200_000)
        with mock.patch.dict(PARSE_LIMITS, {"max_compression_ratio": 10}):
            with self.assertRaises(OOXMLSecurityError) as ctx:
                read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "limits")
        self._cleanup(path)

    def test_total_uncompressed_limit(self):
        from unittest import mock

        from doc_tool.domain.ooxml import PARSE_LIMITS, OOXMLSecurityError, read_docx_package

        path = self._docx(big=b"A" * 3000)
        with mock.patch.dict(PARSE_LIMITS, {"max_total_uncompressed_bytes": 1000}):
            with self.assertRaises(OOXMLSecurityError) as ctx:
                read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "limits")
        self._cleanup(path)

    def test_crc_failure_rejected(self):
        from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

        # STORED 条目：篡改数据字节使 CRC 不匹配
        tmp = Path(tempfile.mkdtemp(prefix="doc-tool-ooxml-"))
        path = tmp / "crc.docx"
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_STORED) as z:
            z.writestr("word/document.xml", _DOC)
            z.writestr("word/extra.bin", b"payload-data")
        # 直接改写 extra.bin 条目字节（同长度替换，仅破坏 CRC 语义）
        data = path.read_bytes()
        marker = b"payload-data"
        idx = data.find(marker)
        self.assertGreater(idx, -1)
        corrupted = data[:idx] + b"PAYLOAD-DATA" + data[idx + len(marker):]
        self.assertEqual(len(corrupted), len(data))
        path.write_bytes(corrupted)
        with self.assertRaises(OOXMLSecurityError) as ctx:
            read_docx_package(path)
        self.assertEqual(ctx.exception.reason, "crc")
        self._cleanup(path)


if __name__ == "__main__":
    unittest.main()
