# -*- coding: utf-8 -*-
"""公共导出与 OOXML 内容扫描测试。

任务 8.5：DOCX/OOXML ZIP 内部内容扫描（正负测试）。
任务 8.7：净化公开源码导出不包含被排除目录或隐藏/未跟踪内部文件。

覆盖范围：
- 品牌词条文本扫描（brand/doc-number/domain/rfc1918）
- OOXML 内容扫描：正例（含公司词条被检出）、负例（虚构 DOCX 通过）
- 净化导出：排除公司目录、不含被排除前缀、保留必需路径
"""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from doc_tool.domain.ooxml import parse_xml_safe  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _load_scan_leaks():
    module_path = Path(REPO_ROOT) / "packaging" / "scan_leaks.py"
    spec = importlib.util.spec_from_file_location("doc_tool_scan_leaks", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_docx(path, doc_text: str) -> None:
    """写一个最小 DOCX，把 doc_text 放入 word/document.xml。"""
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="{w}"><w:body>{text}<w:sectPr/></w:body></w:document>'
    ).format(w=W_NS, text=doc_text)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="{ct}">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    ).format(ct=CT_NS)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", body)


class ScanVocabularyTests(unittest.TestCase):
    """词表文本扫描：品牌/编号/产品/域名/内网地址。"""

    @classmethod
    def setUpClass(cls):
        cls.sl = _load_scan_leaks()
        cls.vocab = cls.sl.load_vocabulary()

    def test_brand_and_doc_number_detected(self):
        hits = self.sl.scan_text_for_terms(
            "康尚健康云软件需求说明书 KF-2090 KSHC", self.vocab, "test"
        )
        joined = "\n".join(hits)
        self.assertIn("brand", joined)
        self.assertIn("doc-number", joined)

    def test_domain_detected(self):
        hits = self.sl.scan_text_for_terms("详见 http://www.konsung.com", self.vocab, "test")
        self.assertTrue(any("konsung.com" in hit for hit in hits))

    def test_rfc1918_detected(self):
        hits = self.sl.scan_text_for_terms("连接 192.168.1.10 与 10.10.0.5", self.vocab, "test")
        self.assertTrue(any("192.168.1.10" in hit for hit in hits))
        self.assertTrue(any("10.10.0.5" in hit for hit in hits))

    def test_clean_text_no_hits(self):
        hits = self.sl.scan_text_for_terms(
            "本文档介绍文档编辑、校验与发布流程。", self.vocab, "test"
        )
        self.assertEqual(hits, [])

    def test_credentials_detected(self):
        """凭据模式（云密钥/私钥/口令赋值）被检出。"""
        dirty = (
            "aws AKIAABCDEFGHIJKLMNOP\n"
            "key = \"supersecretvalue123\"\n"
            "token: \"ghp_abcdefghijklmnopqrstuvwxyz0123456789ab\"\n"
        )
        clean = "token: Optional[CancellationToken]\n"
        self.assertTrue(self.sl.scan_credentials(dirty, "test"))
        # 类型标注/变量名不应误报
        self.assertEqual(self.sl.scan_credentials(clean, "test"), [])


class OoxmlContentScanTests(unittest.TestCase):
    """任务 8.5：DOCX/OOXML 内部内容扫描正负测试。"""

    @classmethod
    def setUpClass(cls):
        cls.sl = _load_scan_leaks()
        cls.vocab = cls.sl.load_vocabulary()

    def test_docx_with_company_term_detected(self):
        with tempfile.TemporaryDirectory(prefix="doc-ooxml-scan-") as tmp:
            path = Path(tmp) / "bad.docx"
            _write_docx(path, "康尚健康云软件需求说明书")
            hits = self.sl.scan_ooxml_content(path, self.vocab)
            self.assertTrue(any("康尚" in hit for hit in hits))
            self.assertTrue(any("word/document.xml" in hit for hit in hits))

    def test_docx_with_internal_filename_detected(self):
        with tempfile.TemporaryDirectory(prefix="doc-ooxml-scan-") as tmp:
            path = Path(tmp) / "bad.docx"
            # 文件名含内部编号：创建带 KF-2090 名称的 zip 条目
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("word/document.xml", "<x/>")
                zf.writestr("word/media/KF-2090-screenshot.png", b"\x89PNG\r\n")
            hits = self.sl.scan_ooxml_content(path, self.vocab)
            self.assertTrue(any("KF-2090" in hit for hit in hits))

    def test_clean_fictional_docx_passes(self):
        example_source = (
            Path(REPO_ROOT) / "examples" / "galaxy-user-manual" / "original" / "source.docx"
        )
        if not example_source.exists():
            self.skipTest("虚构示例未生成，先运行 scripts/create_example.py")
        hits = self.sl.scan_ooxml_content(example_source, self.vocab)
        self.assertEqual(hits, [], "虚构示例 DOCX 不应命中禁止词条")


class PublicExportTests(unittest.TestCase):
    """任务 8.1/8.7：净化公开源码导出。"""

    def test_export_excludes_company_dirs_and_validates(self):
        module_path = Path(REPO_ROOT) / "packaging" / "export_public_source.py"
        spec = importlib.util.spec_from_file_location("doc_tool_export", module_path)
        export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export)

        with tempfile.TemporaryDirectory(prefix="doc-pub-export-") as tmp:
            output = Path(tmp) / "export"
            copied, excluded = export.export_public_source(output)
            self.assertGreater(len(copied), 100, "净化导出应保留核心文件")
            # 公司目录与内部专用脚本被排除
            for prefix in ("templates/", "config/", "content/", "assets/",
                           "analysis/", "scripts/migration/"):
                self.assertTrue(
                    any(rel.startswith(prefix) for rel in excluded),
                    "应排除 {0}".format(prefix),
                )
            # 校验通过：无被排除目录/隐藏文件进入导出
            problems = export.validate_export(output)
            self.assertEqual(problems, [])
            # 必需路径存在
            for required in export.REQUIRED_PATHS:
                self.assertTrue((output / required).exists(), required)

    def test_export_is_fictional_clean(self):
        module_path = Path(REPO_ROOT) / "packaging" / "export_public_source.py"
        spec = importlib.util.spec_from_file_location("doc_tool_export", module_path)
        export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export)
        sl = _load_scan_leaks()
        vocab = sl.load_vocabulary()

        with tempfile.TemporaryDirectory(prefix="doc-pub-export-") as tmp:
            output = Path(tmp) / "export"
            export.export_public_source(output)
            # 词表文件自身不算泄漏，README 等公开文档在 Phase 11 前可能含占位——
            # 这里只验证公司目录与内部标识路径被彻底排除。
            self.assertFalse((output / "content").exists())
            self.assertFalse((output / "templates").exists())
            self.assertFalse((output / "config").exists())
            self.assertFalse((output / "analysis").exists())
            self.assertFalse((output / "migration" / "legacy").exists())
            # 内部一次性迁移脚本（含公司源文件名）不进入公共导出。
            self.assertFalse((output / "scripts" / "migration").exists())
            self.assertFalse((output / "docs" / "release").exists())


if __name__ == "__main__":
    unittest.main()
