# -*- coding: utf-8 -*-
"""PDF 工具箱测试套件：页面组织、格式转换、页面编辑与安全优化。

运行说明：
- 严禁设置 QT_QPA_PLATFORM=offscreen（默认 windows 平台，保证 QPdfWriter 字体与渲染正常）。
- 测试夹具与产物一律使用 tempfile.TemporaryDirectory()（落于 %TEMP%，DocGuard 豁免）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 确保不设 offscreen
os.environ.pop("QT_QPA_PLATFORM", None)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

SYS_PACKAGES = r"C:\Users\18098\AppData\Local\Programs\Python\Python313\Lib\site-packages"
if os.path.isdir(SYS_PACKAGES) and SYS_PACKAGES not in sys.path:
    sys.path.append(SYS_PACKAGES)

import pypdf
from PIL import Image

from doc_tool.application.pdf_tools import (
    TOOL_COMPRESS,
    TOOL_DECRYPT,
    TOOL_DELETE,
    TOOL_ENCRYPT,
    TOOL_EXTRACT,
    TOOL_IMAGES_TO_PDF,
    TOOL_MERGE,
    TOOL_METADATA,
    TOOL_PAGE_NUMBERS,
    TOOL_ROTATE,
    TOOL_SPLIT,
    TOOL_TO_IMAGES,
    TOOL_TO_TEXT,
    TOOL_WATERMARK,
    _ensure_qgui_application,
    expand_sources,
    parse_page_ranges,
    parse_page_selection,
    pdf_options_from_args,
    run_pdf_tool,
)
from doc_tool.cli import main as cli_main
from doc_tool.domain.errors import (
    CancelledError,
    ConversionTargetExistsError,
    PdfEncryptedError,
    PdfFileError,
    PdfInputError,
    PdfPageSelectionError,
    PdfPasswordError,
)


def _create_sample_pdf(target: Path, page_count: int = 3) -> Path:
    """在 %TEMP% 下生成测试用的标准 PDF 文件（包含中英文字符与不同页面尺寸）。"""
    _ensure_qgui_application()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)

    writer = QPdfWriter(buf)
    writer.setResolution(72)

    font = QFont("SimSun", 14)
    painter = None

    for i in range(page_count):
        # 尺寸：偶数页 595x842 (A4)，奇数页 842x595
        if i % 2 == 0:
            pw, ph = 595.0, 842.0
        else:
            pw, ph = 842.0, 595.0

        writer.setPageSize(QPageSize(QSizeF(pw, ph), QPageSize.Unit.Point))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)

        if i == 0:
            painter = QPainter(writer)
        else:
            writer.newPage()

        if painter is not None:
            painter.setFont(font)
            text = "页面内容 第 {0} 页 Hello PDF Test {0}".format(i + 1)
            painter.drawText(QRectF(50, 50, 400, 100), Qt.AlignmentFlag.AlignLeft, text)

    if painter is not None:
        painter.end()

    buf.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(ba.data()))
    return target


def _create_sample_image(target: Path, color: str = "blue", size: tuple = (200, 200)) -> Path:
    """生成测试用的图片文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=color)
    img.save(target)
    return target


class DummyCancelToken:
    def __init__(self, cancel_at: int = 1) -> None:
        self.count = 0
        self.cancel_at = cancel_at

    @property
    def is_cancelled(self) -> bool:
        self.count += 1
        return self.count >= self.cancel_at


class PdfToolboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp_dir.name)

    def tearDown(self) -> None:
        try:
            self._temp_dir.cleanup()
        except Exception:
            pass

    def test_01_parse_page_selection(self) -> None:
        """测试页码选择语法解析。"""
        self.assertIsNone(parse_page_selection(None))
        self.assertIsNone(parse_page_selection(""))
        self.assertIsNone(parse_page_selection("  all  "))

        res = parse_page_selection("1-3, 5, 8-10")
        self.assertEqual(res, [0, 1, 2, 4, 7, 8, 9])

        # 中文逗号与分号
        res_cn = parse_page_selection("1，3；5")
        self.assertEqual(res_cn, [0, 2, 4])

        # 越界检查
        with self.assertRaises(PdfPageSelectionError):
            parse_page_selection("1-5", page_count=3)
        with self.assertRaises(PdfPageSelectionError):
            parse_page_selection("0")
        with self.assertRaises(PdfPageSelectionError):
            parse_page_selection("5-2")
        with self.assertRaises(PdfPageSelectionError):
            parse_page_selection("abc")

    def test_02_parse_page_ranges(self) -> None:
        """测试拆分范围语法解析。"""
        ranges = parse_page_ranges("1-3, 5-8, 10")
        self.assertEqual(ranges, [(1, 3), (5, 8), (10, 10)])

        with self.assertRaises(PdfPageSelectionError):
            parse_page_ranges("")
        with self.assertRaises(PdfPageSelectionError):
            parse_page_ranges("5-2")
        with self.assertRaises(PdfPageSelectionError):
            parse_page_ranges("1-10", page_count=5)

    def test_03_merge(self) -> None:
        """测试 PDF 合并功能。"""
        pdf1 = _create_sample_pdf(self.temp_path / "a.pdf", page_count=2)
        pdf2 = _create_sample_pdf(self.temp_path / "b.pdf", page_count=3)

        res = run_pdf_tool(TOOL_MERGE, [pdf1, pdf2], output_dir=self.temp_path)
        self.assertTrue(res.success)
        self.assertEqual(len(res.records), 1)
        out_file = res.records[0].outputs[0]
        self.assertTrue(out_file.is_file())

        reader = pypdf.PdfReader(str(out_file))
        self.assertEqual(len(reader.pages), 5)

        # 单文件合并失败测试
        res_single = run_pdf_tool(TOOL_MERGE, [pdf1], output_dir=self.temp_path)
        self.assertFalse(res_single.success)
        self.assertEqual(res_single.error_code, "E7008")

    def test_04_split(self) -> None:
        """测试 PDF 拆分（单页、每 N 页、范围）。"""
        src = _create_sample_pdf(self.temp_path / "split_test.pdf", page_count=4)

        # 模式 1：each 单页拆分
        out_dir_each = self.temp_path / "out_each"
        res_each = run_pdf_tool(
            TOOL_SPLIT, [src], output_dir=out_dir_each, options={"mode": "each"}
        )
        self.assertTrue(res_each.success)
        self.assertEqual(len(res_each.records[0].outputs), 4)

        # 模式 2：every-n 拆分
        out_dir_n = self.temp_path / "out_n"
        res_n = run_pdf_tool(
            TOOL_SPLIT,
            [src],
            output_dir=out_dir_n,
            options={"mode": "every-n", "every": 3},
        )
        self.assertTrue(res_n.success)
        self.assertEqual(len(res_n.records[0].outputs), 2)  # 3页 + 1页

        # 模式 3：range 范围拆分
        out_dir_range = self.temp_path / "out_range"
        res_range = run_pdf_tool(
            TOOL_SPLIT,
            [src],
            output_dir=out_dir_range,
            options={"mode": "range", "ranges": "1-2, 4"},
        )
        self.assertTrue(res_range.success)
        self.assertEqual(len(res_range.records[0].outputs), 2)

    def test_05_extract_and_delete(self) -> None:
        """测试提取页面与删除页面。"""
        src = _create_sample_pdf(self.temp_path / "doc.pdf", page_count=4)

        # 提取第 1, 3 页
        res_extract = run_pdf_tool(
            TOOL_EXTRACT,
            [src],
            output_dir=self.temp_path,
            options={"pages": "1, 3"},
        )
        self.assertTrue(res_extract.success)
        out_extract = res_extract.records[0].outputs[0]
        self.assertEqual(len(pypdf.PdfReader(str(out_extract)).pages), 2)

        # 删除第 2 页
        res_delete = run_pdf_tool(
            TOOL_DELETE,
            [src],
            output_dir=self.temp_path,
            options={"pages": "2"},
        )
        self.assertTrue(res_delete.success)
        out_delete = res_delete.records[0].outputs[0]
        self.assertEqual(len(pypdf.PdfReader(str(out_delete)).pages), 3)

        # 删除全部页面应报错 E7008
        res_del_all = run_pdf_tool(
            TOOL_DELETE,
            [src],
            output_dir=self.temp_path,
            options={"pages": "1-4"},
        )
        self.assertFalse(res_del_all.success)
        self.assertEqual(res_del_all.error_code, "E7008")

    def test_06_rotate(self) -> None:
        """测试页面旋转。"""
        src = _create_sample_pdf(self.temp_path / "rot.pdf", page_count=2)
        res = run_pdf_tool(
            TOOL_ROTATE,
            [src],
            output_dir=self.temp_path,
            options={"degrees": 90, "pages": "1"},
        )
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(int(reader.pages[0].get("/Rotate", 0)), 90)
        self.assertEqual(int(reader.pages[1].get("/Rotate", 0)), 0)

    def test_07_to_images(self) -> None:
        """测试 PDF 转图片（PNG 与 JPG）。"""
        src = _create_sample_pdf(self.temp_path / "img_src.pdf", page_count=2)
        out_dir = self.temp_path / "imgs"
        res = run_pdf_tool(
            TOOL_TO_IMAGES,
            [src],
            output_dir=out_dir,
            options={"image_format": "png", "dpi": 72},
        )
        self.assertTrue(res.success)
        images = res.records[0].outputs
        self.assertEqual(len(images), 2)
        for img_path in images:
            self.assertTrue(img_path.is_file())
            with Image.open(img_path) as im:
                self.assertGreater(im.width, 100)
                self.assertGreater(im.height, 100)

    def test_08_images_to_pdf(self) -> None:
        """测试图片合成 PDF（原尺寸与 A4 适配）。"""
        img1 = _create_sample_image(self.temp_path / "img1.png", color="red", size=(300, 400))
        img2 = _create_sample_image(self.temp_path / "img2.jpg", color="green", size=(500, 200))

        res = run_pdf_tool(TOOL_IMAGES_TO_PDF, [img1, img2], output_dir=self.temp_path)
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 2)

        # 测试 A4 模式
        res_a4 = run_pdf_tool(
            TOOL_IMAGES_TO_PDF,
            [img1, img2],
            output_dir=self.temp_path,
            options={"a4": True, "output_name": "a4.pdf"},
        )
        self.assertTrue(res_a4.success)
        out_a4 = res_a4.records[0].outputs[0]
        reader_a4 = pypdf.PdfReader(str(out_a4))
        self.assertEqual(len(reader_a4.pages), 2)
        # 验证 A4 磅值约为 595 x 842
        self.assertAlmostEqual(float(reader_a4.pages[0].mediabox.width), 595.2, delta=2.0)
        self.assertAlmostEqual(float(reader_a4.pages[0].mediabox.height), 841.9, delta=2.0)

    def test_09_to_text(self) -> None:
        """测试提取 PDF 纯文本。"""
        src = _create_sample_pdf(self.temp_path / "text_src.pdf", page_count=2)
        res = run_pdf_tool(TOOL_TO_TEXT, [src], output_dir=self.temp_path)
        self.assertTrue(res.success)
        out_txt = res.records[0].outputs[0]
        content = out_txt.read_text(encoding="utf-8")
        self.assertIn("第 1 页", content)
        self.assertIn("Hello PDF Test", content)

    def test_10_watermark(self) -> None:
        """测试添加文字水印。"""
        src = _create_sample_pdf(self.temp_path / "wm_src.pdf", page_count=2)
        res = run_pdf_tool(
            TOOL_WATERMARK,
            [src],
            output_dir=self.temp_path,
            options={"text": "内部机密", "opacity": 50, "mode": "center"},
        )
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 2)
        extracted = reader.pages[0].extract_text()
        self.assertIn("内部机密", extracted)

    def test_11_page_numbers(self) -> None:
        """测试添加页码标记。"""
        src = _create_sample_pdf(self.temp_path / "pn_src.pdf", page_count=2)
        res = run_pdf_tool(
            TOOL_PAGE_NUMBERS,
            [src],
            output_dir=self.temp_path,
            options={"format": "第n页/共N页", "position": "bottom-center"},
        )
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 2)
        extracted = reader.pages[0].extract_text()
        # 探针 25 确认的提取格式
        self.assertIn("第 1 页", extracted)

    def test_12_metadata(self) -> None:
        """测试元数据查看与修改。"""
        src = _create_sample_pdf(self.temp_path / "meta_src.pdf", page_count=1)

        # 查看模式
        res_view = run_pdf_tool(TOOL_METADATA, [src])
        self.assertTrue(res_view.success)
        self.assertEqual(len(res_view.records[0].outputs), 0)
        self.assertIn("标题:", res_view.records[0].detail)

        # 修改模式
        res_edit = run_pdf_tool(
            TOOL_METADATA,
            [src],
            output_dir=self.temp_path,
            options={"title": "测试新标题", "author": "测试作者"},
        )
        self.assertTrue(res_edit.success)
        out_pdf = res_edit.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(reader.metadata.get("/Title"), "测试新标题")
        self.assertEqual(reader.metadata.get("/Author"), "测试作者")

    def test_13_encrypt_and_decrypt(self) -> None:
        """测试 PDF 加密与解除密码。"""
        src = _create_sample_pdf(self.temp_path / "enc_src.pdf", page_count=2)

        # 加密
        res_enc = run_pdf_tool(
            TOOL_ENCRYPT,
            [src],
            output_dir=self.temp_path,
            options={"user_password": "mypassword123", "allow_print": True},
        )
        self.assertTrue(res_enc.success)
        enc_pdf = res_enc.records[0].outputs[0]

        reader = pypdf.PdfReader(str(enc_pdf))
        self.assertTrue(reader.is_encrypted)

        # 密码错误解密测试
        res_fail = run_pdf_tool(
            TOOL_DECRYPT,
            [enc_pdf],
            output_dir=self.temp_path,
            options={"password": "wrongpassword"},
        )
        self.assertFalse(res_fail.success)
        self.assertEqual(res_fail.error_code, "E7004")

        # 密码正确解密测试
        res_dec = run_pdf_tool(
            TOOL_DECRYPT,
            [enc_pdf],
            output_dir=self.temp_path,
            options={"password": "mypassword123"},
        )
        self.assertTrue(res_dec.success)
        dec_pdf = res_dec.records[0].outputs[0]
        reader_dec = pypdf.PdfReader(str(dec_pdf))
        self.assertFalse(reader_dec.is_encrypted)

    def test_14_compress(self) -> None:
        """测试无损压缩。"""
        src = _create_sample_pdf(self.temp_path / "comp_src.pdf", page_count=2)
        res = run_pdf_tool(TOOL_COMPRESS, [src], output_dir=self.temp_path)
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        self.assertTrue(out_pdf.is_file())
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 2)

    def test_15_batch_isolation_and_cancel(self) -> None:
        """测试批量执行的单文件错误隔离与取消机制。"""
        valid_pdf = _create_sample_pdf(self.temp_path / "valid.pdf", page_count=1)
        bad_file = self.temp_path / "broken.pdf"
        bad_file.write_text("not a pdf at all", encoding="utf-8")

        # 1 个正常 + 1 个损坏，批量不应崩溃并隔离记录
        batch = run_pdf_tool(TOOL_ROTATE, [valid_pdf, bad_file], output_dir=self.temp_path)
        self.assertEqual(batch.total, 2)
        self.assertEqual(batch.succeeded, 1)
        self.assertEqual(batch.failed, 1)
        self.assertEqual(batch.records[1].error_code, "E7001")

        # 取消机制测试
        token = DummyCancelToken(cancel_at=1)
        batch_cancel = run_pdf_tool(
            TOOL_ROTATE, [valid_pdf, valid_pdf], output_dir=self.temp_path, cancel_token=token
        )
        self.assertTrue(batch_cancel.cancelled)
        self.assertEqual(batch_cancel.error_code, CancelledError.code)

    def test_16_conflict_preflight(self) -> None:
        """测试同名输出冲突预检（E6002）。"""
        src = _create_sample_pdf(self.temp_path / "conflict.pdf", page_count=1)
        target = self.temp_path / "conflict_提取.pdf"
        target.write_text("existing", encoding="utf-8")

        # 未传 overwrite 时预检失败
        res = run_pdf_tool(
            TOOL_EXTRACT,
            [src],
            output_dir=self.temp_path,
            overwrite=False,
            options={"pages": "1"},
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "E6002")

        # 传 overwrite 时成功覆盖
        res_ov = run_pdf_tool(
            TOOL_EXTRACT,
            [src],
            output_dir=self.temp_path,
            overwrite=True,
            options={"pages": "1"},
        )
        self.assertTrue(res_ov.success)

    def test_17_cli_execution(self) -> None:
        """测试 CLI pdf 子命令调用。"""
        p1 = _create_sample_pdf(self.temp_path / "cli_1.pdf", 1)
        p2 = _create_sample_pdf(self.temp_path / "cli_2.pdf", 1)
        out_dir = str(self.temp_path / "cli_out")

        # CLI 调用 merge，输出 json
        code = cli_main([
            "pdf", "merge", str(p1), str(p2),
            "--target-dir", out_dir,
            "--output", "json",
        ])
        self.assertEqual(code, 0)
        self.assertTrue((Path(out_dir) / "cli_1_合并.pdf").is_file())

    def test_18_dialog_smoke(self) -> None:
        """测试 GUI 对话框实例化与工具切换冒烟。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            self.assertEqual(dialog._table.rowCount(), 0)
            # 添加测试文件
            p1 = _create_sample_pdf(self.temp_path / "diag_1.pdf", 1)
            dialog._ingest_paths([p1])
            self.assertEqual(dialog._table.rowCount(), 1)
            self.assertEqual(len(dialog._sources), 1)

            # 切换工具
            dialog._tool_list.setCurrentRow(3)  # 选中某个工具
            self.assertTrue(bool(dialog._current_tool_id()))

            # 清空
            dialog._on_clear()
            self.assertEqual(dialog._table.rowCount(), 0)
            self.assertEqual(len(dialog._sources), 0)
        finally:
            dialog.close()


    def test_19_edge_cases_and_clean_handles(self) -> None:
        """测试中文分号解析、去重拆分范围、密码空白保留等边界。"""
        # 1. 中文分号解析
        ranges = parse_page_ranges("1-2；3-4")
        self.assertEqual(ranges, [(1, 2), (3, 4)])

        # 2. 重复范围拆分去重
        src = _create_sample_pdf(self.temp_path / "dedup.pdf", page_count=3)
        res = run_pdf_tool(
            TOOL_SPLIT,
            [src],
            output_dir=self.temp_path / "dedup_out",
            options={"mode": "range", "ranges": "1-2, 1-2"},
        )
        self.assertTrue(res.success)
        self.assertEqual(len(res.records[0].outputs), 1)

        # 3. 密码保留两端空格
        res_enc = run_pdf_tool(
            TOOL_ENCRYPT,
            [src],
            output_dir=self.temp_path,
            options={"user_password": "  pw_with_spaces  "},
        )
        self.assertTrue(res_enc.success)
        enc_file = res_enc.records[0].outputs[0]

        # 剥离空格的密码解密失败
        res_dec_fail = run_pdf_tool(
            TOOL_DECRYPT,
            [enc_file],
            output_dir=self.temp_path,
            options={"password": "pw_with_spaces"},
        )
        self.assertFalse(res_dec_fail.success)

        # 包含空格的准确密码解密成功
        res_dec_ok = run_pdf_tool(
            TOOL_DECRYPT,
            [enc_file],
            output_dir=self.temp_path,
            options={"password": "  pw_with_spaces  "},
        )
        self.assertTrue(res_dec_ok.success)


if __name__ == "__main__":
    unittest.main()
