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
            dialog.deleteLater()
            app.processEvents()


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



    def test_20_reorder(self) -> None:
        """测试页面重排功能：reverse 与自定义顺序。"""
        from doc_tool.application.pdf_tools import TOOL_REORDER

        src = _create_sample_pdf(self.temp_path / "reorder_src.pdf", page_count=3)

        # 1. 倒序反转全部页面
        res_rev = run_pdf_tool(
            TOOL_REORDER,
            [src],
            output_dir=self.temp_path,
            options={"order": "reverse"},
        )
        self.assertTrue(res_rev.success)
        out_pdf = res_rev.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 3)
        self.assertIn("第 3 页", reader.pages[0].extract_text())
        self.assertIn("第 1 页", reader.pages[2].extract_text())

        # 2. 自定义顺序 "2, 1" (截取前2页并颠倒)
        res_custom = run_pdf_tool(
            TOOL_REORDER,
            [src],
            output_dir=self.temp_path,
            options={"order": "2, 1"},
            overwrite=True,
        )
        self.assertTrue(res_custom.success)
        out_custom = res_custom.records[0].outputs[0]
        reader_c = pypdf.PdfReader(str(out_custom))
        self.assertEqual(len(reader_c.pages), 2)
        self.assertIn("第 2 页", reader_c.pages[0].extract_text())
        self.assertIn("第 1 页", reader_c.pages[1].extract_text())

        # 3. 越界异常校验
        res_bad = run_pdf_tool(
            TOOL_REORDER,
            [src],
            output_dir=self.temp_path,
            options={"order": "1, 99"},
        )
        self.assertFalse(res_bad.success)
        self.assertEqual(res_bad.error_code, "E7002")

    def test_21_compress_levels(self) -> None:
        """测试压缩等级选择（standard / lossless / aggressive）。"""
        src = _create_sample_pdf(self.temp_path / "comp_lvl_src.pdf", page_count=2)
        for lvl in ("lossless", "standard", "aggressive"):
            res = run_pdf_tool(
                TOOL_COMPRESS,
                [src],
                output_dir=self.temp_path / f"out_{lvl}",
                options={"level": lvl},
            )
            self.assertTrue(res.success)
            self.assertTrue(res.records[0].outputs[0].is_file())
            self.assertIn("KB", res.records[0].detail)

    def test_22_watermark_image_and_positions(self) -> None:
        """测试图片水印与不同定位模式。"""
        src = _create_sample_pdf(self.temp_path / "wm_pos_src.pdf", page_count=1)
        # 创建一张临时测试印章图片
        from PIL import Image
        stamp_img = self.temp_path / "stamp.png"
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 180))
        img.save(stamp_img)

        # 图片水印测试
        res_img = run_pdf_tool(
            TOOL_WATERMARK,
            [src],
            output_dir=self.temp_path,
            options={
                "watermark_type": "image",
                "image_path": str(stamp_img),
                "mode": "top-right",
                "opacity": 50,
                "scale": 25,
            },
        )
        self.assertTrue(res_img.success)
        self.assertTrue(res_img.records[0].outputs[0].is_file())

        # 多方位文字水印测试
        for mode in ("top-left", "bottom-right", "tiled"):
            res_mode = run_pdf_tool(
                TOOL_WATERMARK,
                [src],
                output_dir=self.temp_path / f"out_{mode}",
                options={"text": "TEST_POS", "mode": mode},
            )
            self.assertTrue(res_mode.success)

    def test_23_images_to_pdf_layout(self) -> None:
        """测试图片转 PDF 版面尺寸、方向与边距。"""
        from PIL import Image
        img_p1 = self.temp_path / "p1.jpg"
        img_p2 = self.temp_path / "p2.png"
        Image.new("RGB", (200, 300), (100, 150, 200)).save(img_p1)
        Image.new("RGB", (400, 200), (200, 100, 150)).save(img_p2)

        res = run_pdf_tool(
            TOOL_IMAGES_TO_PDF,
            [img_p1, img_p2],
            output_dir=self.temp_path,
            options={
                "page_size": "a4",
                "orientation": "portrait",
                "margin": 18,
            },
        )
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        reader = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(reader.pages), 2)

    def test_24_helpers_and_password_strength(self) -> None:
        """测试 get_pdf_info 与 evaluate_password_strength 辅助能力。"""
        from doc_tool.application.pdf_tools import (
            evaluate_password_strength,
            get_pdf_info,
        )

        src = _create_sample_pdf(self.temp_path / "info_src.pdf", page_count=2)
        info = get_pdf_info(src)
        self.assertTrue(info["exists"])
        self.assertEqual(info["type"], "pdf")
        self.assertEqual(info["page_count"], 2)
        self.assertFalse(info["is_encrypted"])

        # 密码强度评估
        eval_weak = evaluate_password_strength("12345")
        self.assertEqual(eval_weak["score"], 1)

        eval_mid = evaluate_password_strength("abc12345")
        self.assertGreaterEqual(eval_mid["score"], 2)

        eval_strong = evaluate_password_strength("Abc@2026!Strong")
        self.assertGreaterEqual(eval_strong["score"], 3)



    def test_25_dialog_portal_and_filtering(self) -> None:
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            self.assertEqual(len(dialog._cards_list), len(pt.TOOL_SPECS) + 1)
            dialog._portal_search.setText(pt.TOOL_WATERMARK)
            dialog._filter_portal_cards()
            wm_cards = [c for c in dialog._cards_list if not c.isHidden()]
            self.assertGreaterEqual(len(wm_cards), 1)
            self.assertEqual(wm_cards[0]._tool_id, pt.TOOL_WATERMARK)

            dialog._portal_search.setText('')
            dialog._filter_portal_cards()

            dialog.select_tool(pt.TOOL_WATERMARK)
            self.assertEqual(dialog._current_tool_id(), pt.TOOL_WATERMARK)
            self.assertEqual(dialog._view_stack.currentIndex(), 1)

            dialog._show_portal_view()
            self.assertEqual(dialog._view_stack.currentIndex(), 0)
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_26_dialog_options_collection_validation(self) -> None:
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt
        from doc_tool.domain.errors import PdfInputError

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            dialog.select_tool(pt.TOOL_ENCRYPT)
            dialog._enc_user_pw.setText('pass123')
            dialog._enc_confirm_pw.setText('pass456')
            with self.assertRaises(PdfInputError):
                dialog._collect_options(pt.TOOL_ENCRYPT)

            dialog._enc_confirm_pw.setText('pass123')
            opts_enc = dialog._collect_options(pt.TOOL_ENCRYPT)
            self.assertEqual(opts_enc['user_password'], 'pass123')

            dialog.select_tool(pt.TOOL_EXTRACT)
            dialog._extract_pages.setText('')
            with self.assertRaises(PdfInputError):
                dialog._collect_options(pt.TOOL_EXTRACT)

            dialog._extract_pages.setText('1-3')
            opts_ext = dialog._collect_options(pt.TOOL_EXTRACT)
            self.assertEqual(opts_ext['pages'], '1-3')

            dialog.select_tool(pt.TOOL_WATERMARK)
            dialog._wm_type.setCurrentIndex(1)
            dialog._wm_img_path.setText('')
            with self.assertRaises(PdfInputError):
                dialog._collect_options(pt.TOOL_WATERMARK)
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_27_edge_cases_and_error_handling(self) -> None:
        import doc_tool.application.pdf_tools as pt

        src = _create_sample_pdf(self.temp_path / 'edge_src.pdf', page_count=2)

        res_split_bad = run_pdf_tool(
            pt.TOOL_SPLIT,
            [src],
            output_dir=self.temp_path / 'bad_split',
            options={'mode': 'invalid_mode'},
        )
        self.assertFalse(res_split_bad.success)

        res_merge_one = run_pdf_tool(
            pt.TOOL_MERGE,
            [src],
            output_dir=self.temp_path / 'bad_merge',
        )
        self.assertFalse(res_merge_one.success)
        self.assertEqual(res_merge_one.error_code, 'E7008')

        res_dec_unenc = run_pdf_tool(
            pt.TOOL_DECRYPT,
            [src],
            output_dir=self.temp_path / 'dec_unenc',
            options={'password': ''},
        )
        self.assertTrue(res_dec_unenc.success)
        self.assertTrue(bool(res_dec_unenc.records[0].note))


    def test_28_cli_mode_and_scale_quality_args(self) -> None:
        """测试 CLI 参数解析支持扩展水印位置、缩放比例与质量。"""
        import argparse
        from doc_tool.application.pdf_tools import (
            TOOL_TO_IMAGES,
            TOOL_WATERMARK,
            add_pdf_tool_arguments,
            pdf_options_from_args,
        )

        parser = argparse.ArgumentParser()
        add_pdf_tool_arguments(parser)

        for mode in ("top-left", "top-right", "bottom-left", "bottom-right", "tiled", "center"):
            args = parser.parse_args([TOOL_WATERMARK, "dummy.pdf", "--mode", mode, "--scale", "45", "--quality", "85"])
            opts = pdf_options_from_args(args)
            self.assertEqual(opts["mode"], mode)
            self.assertEqual(opts["scale"], 45.0)
            self.assertEqual(opts["quality"], 85)

    def test_29_tool_to_images_quality_support(self) -> None:
        """测试 PDF 转图片质量设置真实生效。"""
        from doc_tool.application.pdf_tools import TOOL_TO_IMAGES
        src = _create_sample_pdf(self.temp_path / "img_q_src.pdf", page_count=1)

        res_q30 = run_pdf_tool(
            TOOL_TO_IMAGES,
            [src],
            output_dir=self.temp_path / "out_q30",
            options={"image_format": "jpg", "quality": 30, "dpi": 150},
        )
        self.assertTrue(res_q30.success)
        self.assertIn("质量: 30", res_q30.records[0].detail)
        f_q30 = res_q30.records[0].outputs[0]

        res_q95 = run_pdf_tool(
            TOOL_TO_IMAGES,
            [src],
            output_dir=self.temp_path / "out_q95",
            options={"image_format": "jpg", "quality": 95, "dpi": 150},
        )
        self.assertTrue(res_q95.success)
        self.assertIn("质量: 95", res_q95.records[0].detail)
        f_q95 = res_q95.records[0].outputs[0]

        self.assertLess(f_q30.stat().st_size, f_q95.stat().st_size)

    def test_30_aggressive_compress_image_reduction(self) -> None:
        """测试强力压缩对高分辨率图片流的下采样与重压缩降容。"""
        from PIL import Image
        from doc_tool.application.pdf_tools import TOOL_COMPRESS
        import io

        im = Image.new("RGB", (2000, 2000), (180, 120, 60))
        pdf_path = self.temp_path / "img_heavy.pdf"
        im.save(pdf_path, format="PDF")

        res_lossless = run_pdf_tool(
            TOOL_COMPRESS,
            [pdf_path],
            output_dir=self.temp_path / "out_lossless",
            options={"level": "lossless"},
        )
        self.assertTrue(res_lossless.success)
        size_lossless = res_lossless.records[0].outputs[0].stat().st_size

        res_aggr = run_pdf_tool(
            TOOL_COMPRESS,
            [pdf_path],
            output_dir=self.temp_path / "out_aggr",
            options={"level": "aggressive"},
        )
        self.assertTrue(res_aggr.success)
        size_aggr = res_aggr.records[0].outputs[0].stat().st_size

        self.assertLess(size_aggr, size_lossless)

    def test_31_get_pdf_info_dimensions_and_metadata(self) -> None:
        """测试 get_pdf_info 提取尺寸、主题、关键字及异常防护。"""
        from doc_tool.application.pdf_tools import get_pdf_info
        p = self.temp_path / "meta_dim.pdf"
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_metadata({
            "/Title": "测试报告",
            "/Author": "测试作者",
            "/Subject": "质量检验",
            "/Keywords": "PDF, 压缩, 测试",
        })
        with open(p, "wb") as f:
            writer.write(f)

        info = get_pdf_info(p)
        self.assertTrue(info["exists"])
        self.assertEqual(info["title"], "测试报告")
        self.assertEqual(info["author"], "测试作者")
        self.assertEqual(info["subject"], "质量检验")
        self.assertEqual(info["keywords"], "PDF, 压缩, 测试")
        self.assertIn("595 × 842", info["dimensions"])

        # 空损坏文件防护
        p_corrupt = self.temp_path / "corrupt_empty.pdf"
        p_corrupt.write_bytes(b"")
        info_c = get_pdf_info(p_corrupt)
        self.assertIn("error", info_c)

    def test_32_dialog_password_confirmation_enforced(self) -> None:
        """测试加密密码确认强制校验及拆分范围必填校验。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt
        from doc_tool.domain.errors import PdfInputError

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            dialog.select_tool(pt.TOOL_ENCRYPT)
            dialog._enc_user_pw.setText("mysecret")
            dialog._enc_confirm_pw.setText("")
            with self.assertRaises(PdfInputError):
                dialog._collect_options(pt.TOOL_ENCRYPT)

            dialog._enc_confirm_pw.setText("mysecret")
            opts = dialog._collect_options(pt.TOOL_ENCRYPT)
            self.assertEqual(opts["user_password"], "mysecret")

            # 拆分模式范围必填
            dialog.select_tool(pt.TOOL_SPLIT)
            dialog._split_mode.setCurrentIndex(2)  # range 模式
            dialog._split_ranges.setText("")
            with self.assertRaises(PdfInputError):
                dialog._collect_options(pt.TOOL_SPLIT)

            dialog._split_ranges.setText("1-3")
            opts_split = dialog._collect_options(pt.TOOL_SPLIT)
            self.assertEqual(opts_split["ranges"], "1-3")
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_33_dialog_format_incompatibility_and_retry_batch(self) -> None:
        """测试文件格式不兼容提示与整批工具重试逻辑。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt
        from PIL import Image

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            pdf_file = _create_sample_pdf(self.temp_path / "compat.pdf")
            img_file = self.temp_path / "compat.png"
            Image.new("RGB", (50, 50)).save(img_file)

            dialog.select_tool(pt.TOOL_MERGE)
            dialog._sources = [pdf_file, img_file]
            dialog._refresh_table()

            # 第二行格式不符
            item_stat_img = dialog._table.item(1, 4)
            self.assertIsNotNone(item_stat_img)
            self.assertEqual(item_stat_img.text(), "格式不符")

            # 重试合并调用全量 sources
            called_with = []
            dialog._start_processing = lambda targets: called_with.append(targets)
            dialog._on_retry_single(pdf_file)
            self.assertEqual(called_with[0], dialog._sources)
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_34_portal_compact_reflow_and_responsive_columns(self) -> None:
        """测试首页卡片紧凑重排、无结果提示与响应式列计算。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            dialog.resize(600, 600)
            self.assertEqual(dialog._get_responsive_col_count(), 1)
            dialog.resize(900, 600)
            self.assertEqual(dialog._get_responsive_col_count(), 2)
            dialog.resize(1200, 600)
            self.assertEqual(dialog._get_responsive_col_count(), 3)

            # 搜索无结果时触发空状态提示
            dialog._portal_search.setText("non_existing_keyword_xyz")
            dialog._filter_portal_cards()
            self.assertFalse(dialog._no_results_lbl.isHidden())
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_35_keyboard_events_and_accessibility(self) -> None:
        """测试键盘操作（Esc 返回导航大厅）与无障碍语义标记。"""
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            self.assertTrue(bool(dialog._table.accessibleName()))
            self.assertTrue(bool(dialog._cards_list[0].accessibleName()))

            # 进入工作区后按 Escape 键平滑返回首页
            dialog.select_tool(pt.TOOL_MERGE)
            self.assertEqual(dialog._view_stack.currentIndex(), 1)

            key_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
            dialog.keyPressEvent(key_event)
            self.assertEqual(dialog._view_stack.currentIndex(), 0)
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

    def test_36_table_selection_preview_and_metadata_autofill(self) -> None:
        """测试选中表格行展示元信息摘要并自动填充元数据编辑表单。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            pdf_path = self.temp_path / "autofill.pdf"
            w = pypdf.PdfWriter()
            w.add_blank_page(width=200, height=300)
            w.add_metadata({
                "/Title": "自动填充标题",
                "/Author": "自动填充作者",
                "/Subject": "自动填充主题",
                "/Keywords": "关键词A, 关键词B",
            })
            with open(pdf_path, "wb") as f:
                w.write(f)

            dialog.select_tool(pt.TOOL_METADATA)
            dialog._sources = [pdf_path]
            dialog._refresh_table()

            dialog._table.selectRow(0)
            dialog._on_table_selection_changed()

            self.assertIn("自动填充标题", dialog._preview_banner.text())
            self.assertEqual(dialog._meta_title.text(), "自动填充标题")
            self.assertEqual(dialog._meta_author.text(), "自动填充作者")
            self.assertEqual(dialog._meta_subject.text(), "自动填充主题")
            self.assertEqual(dialog._meta_keywords.text(), "关键词A, 关键词B")
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()


    def test_37_reorder_edge_cases_and_out_of_bounds(self) -> None:
        """测试页面重排边界条件：倒序合法范围、越界范围与含0异常。"""
        import doc_tool.application.pdf_tools as pt
        from doc_tool.domain.errors import PdfPageSelectionError

        pdf_path = self.temp_path / "three_pages.pdf"
        writer = pypdf.PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=100, height=100)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        # 合法倒序 3-1
        res = pt.run_pdf_tool(
            pt.TOOL_REORDER,
            [pdf_path],
            output_dir=self.temp_path / "out_reorder",
            options={"order": "3-1"},
        )
        self.assertTrue(res.success)
        out_pdf = res.records[0].outputs[0]
        r = pypdf.PdfReader(str(out_pdf))
        self.assertEqual(len(r.pages), 3)

        # 倒序越界 10-1（总共 3 页）
        with self.assertRaises(PdfPageSelectionError):
            pt._tool_reorder(pdf_path, None, True, {"order": "10-1"})

        # 包含 0 异常 3-0
        with self.assertRaises(PdfPageSelectionError):
            pt._tool_reorder(pdf_path, None, True, {"order": "3-0"})

    def test_38_dialog_row_actions_deleted_on_clear_and_reject_gating(self) -> None:
        """测试 PdfToolboxDialog 的行级操作组件生命周期追踪与清空安全释放。"""
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.pdf_toolbox_dialog import PdfToolboxDialog
        import doc_tool.application.pdf_tools as pt

        app = QApplication.instance() or QApplication([])
        dialog = PdfToolboxDialog()
        try:
            p1 = _create_sample_pdf(self.temp_path / "del_1.pdf", 1)
            p2 = _create_sample_pdf(self.temp_path / "del_2.pdf", 1)
            dialog.select_tool(pt.TOOL_MERGE)
            dialog._ingest_paths([p1, p2])
            self.assertEqual(len(dialog._row_actions), 2)

            # 清空表格应清空行级组件字典并释放
            dialog._on_clear()
            self.assertEqual(len(dialog._row_actions), 0)
            self.assertEqual(dialog._table.rowCount(), 0)

            # 再次加入并测试未运行状态下直接正常 reject
            dialog._ingest_paths([p1])
            self.assertEqual(len(dialog._row_actions), 1)
            dialog.reject()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
