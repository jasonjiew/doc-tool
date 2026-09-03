# -*- coding: utf-8 -*-
"""PDF 工具箱服务：页面组织、格式转换、页面编辑与安全优化。

对标市面 PDF 工具箱（iLovePDF / PDF24 等）的离线高频功能集。
纯 Python / Qt 离线实现，不依赖本机 Microsoft Word 或 Office。

功能架构：
- 页面组织：合并、拆分、提取页面、删除页面、旋转页面
- 格式转换：PDF → 图片、图片 → PDF、PDF → 文本
- 页面编辑：添加水印（文字）、添加页码、元数据查看与修改
- 安全与优化：加密（密码与权限位）、解除密码、无损压缩

技术底座：
- pypdf 6.0.0：页面结构操作、加密解密、压缩去重、元数据与纯文本提取
- PySide6.QtPdf (QPdfDocument)：基于 QBuffer 的 PDF 页面栅格化渲染（PDF → 图片）
- PySide6.QtGui (QPdfWriter + QPainter)：内存构建矢量覆盖层 PDF（水印、页码）
- Pillow：图像格式解码、EXIF 转置与「图片 → PDF」合成
- cryptography：AES-256 PDF 加密（缺失时安全降级为 RC4-128）
"""

from __future__ import annotations

import argparse
import io
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from doc_tool.domain.errors import (
    ConversionTargetExistsError,
    DocToolError,
    PdfEncryptedError,
    PdfFileError,
    PdfImageError,
    PdfInputError,
    PdfPageSelectionError,
    PdfPasswordError,
    PdfRenderError,
    PdfWriteError,
)

TOOL_MERGE = "merge"
TOOL_SPLIT = "split"
TOOL_EXTRACT = "extract"
TOOL_DELETE = "delete"
TOOL_ROTATE = "rotate"
TOOL_TO_IMAGES = "to_images"
TOOL_IMAGES_TO_PDF = "images_to_pdf"
TOOL_TO_TEXT = "to_text"
TOOL_WATERMARK = "watermark"
TOOL_PAGE_NUMBERS = "page_numbers"
TOOL_METADATA = "metadata"
TOOL_ENCRYPT = "encrypt"
TOOL_DECRYPT = "decrypt"
TOOL_COMPRESS = "compress"

CATEGORY_PAGES = "页面组织"
CATEGORY_CONVERT = "转换"
CATEGORY_EDIT = "编辑"
CATEGORY_SECURITY = "安全与优化"

CATEGORIES = (CATEGORY_PAGES, CATEGORY_CONVERT, CATEGORY_EDIT, CATEGORY_SECURITY)

PDF_SUFFIXES = (".pdf",)
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")


@dataclass(frozen=True)
class PdfToolSpec:
    """PDF 工具的静态规范与元数据。"""

    id: str
    label: str
    category: str
    accepts: Tuple[str, ...]
    plural: bool = False
    description: str = ""
    hint: str = ""


TOOL_SPECS: Tuple[PdfToolSpec, ...] = (
    PdfToolSpec(
        id=TOOL_MERGE,
        label="合并 PDF",
        category=CATEGORY_PAGES,
        accepts=PDF_SUFFIXES,
        plural=True,
        description="按列表顺序将多个 PDF 文件合并为一个单一文档。",
        hint="至少添加 2 个 PDF 文件；可在列表中上下移动调整合并顺序。",
    ),
    PdfToolSpec(
        id=TOOL_SPLIT,
        label="拆分 PDF",
        category=CATEGORY_PAGES,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="将 PDF 拆分为单页文件、按固定页数拆分或提取指定范围。",
        hint="支持每页拆分、每 N 页拆分或自定义范围拆分（如 1-3,5-8）。",
    ),
    PdfToolSpec(
        id=TOOL_EXTRACT,
        label="提取页面",
        category=CATEGORY_PAGES,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="提取 PDF 中的指定页面另存为一个新文件。",
        hint="输入要提取的页码（如 1-5,8,11-13）。",
    ),
    PdfToolSpec(
        id=TOOL_DELETE,
        label="删除页面",
        category=CATEGORY_PAGES,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="从 PDF 中删除指定的页面，保留剩余页面。",
        hint="输入要删除的页码（如 2,4-6）；不能删除全部页面。",
    ),
    PdfToolSpec(
        id=TOOL_ROTATE,
        label="旋转页面",
        category=CATEGORY_PAGES,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="将 PDF 页面按顺时针或逆时针旋转 90°、180° 或 270°。",
        hint="选择旋转角度及要旋转的页面范围（留空表示全部页面）。",
    ),
    PdfToolSpec(
        id=TOOL_TO_IMAGES,
        label="PDF → 图片",
        category=CATEGORY_CONVERT,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="将 PDF 各页面逐页渲染并导出为高质量 PNG 或 JPG 图片。",
        hint="可设置分辨率 DPI（36~600，默认 150）与导出格式。",
    ),
    PdfToolSpec(
        id=TOOL_IMAGES_TO_PDF,
        label="图片 → PDF",
        category=CATEGORY_CONVERT,
        accepts=IMAGE_SUFFIXES,
        plural=True,
        description="将多张图片按顺序合并为一个 PDF 文档。",
        hint="支持 JPG/PNG/BMP/TIFF/WEBP；可选原尺寸或缩放居中至 A4 页面。",
    ),
    PdfToolSpec(
        id=TOOL_TO_TEXT,
        label="PDF → 文本",
        category=CATEGORY_CONVERT,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="提取 PDF 中的纯文本内容并保存为 UTF-8 TXT 文本文件。",
        hint="仅能提取基于文本图层的正文；扫描件图片无法提取文本。",
    ),
    PdfToolSpec(
        id=TOOL_WATERMARK,
        label="添加水印",
        category=CATEGORY_EDIT,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="在 PDF 页面上添加半透明文本水印（支持居中或全页平铺）。",
        hint="可自定义水印文字、字体大小、旋转角度、颜色与淡化透明度。",
    ),
    PdfToolSpec(
        id=TOOL_PAGE_NUMBERS,
        label="添加页码",
        category=CATEGORY_EDIT,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="在 PDF 页面四周边缘添加格式化页码编号。",
        hint="支持 6 种对齐位置、5 种编号样式、首页跳过与起始编号设置。",
    ),
    PdfToolSpec(
        id=TOOL_METADATA,
        label="元数据",
        category=CATEGORY_EDIT,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="查看或修改 PDF 的标题、作者、主题和关键字信息。",
        hint="全留空时为「查看」模式；填写任意项时将输出修改后的新文件。",
    ),
    PdfToolSpec(
        id=TOOL_ENCRYPT,
        label="加密",
        category=CATEGORY_SECURITY,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="为 PDF 设置打开密码、所有者密码及详细操作权限控制。",
        hint="支持 AES-256 加密；可分别控制是否允许打印、复制、修改与批注。",
    ),
    PdfToolSpec(
        id=TOOL_DECRYPT,
        label="解除密码",
        category=CATEGORY_SECURITY,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="输入密码解除 PDF 的加密限制，输出无密码的明文 PDF。",
        hint="需提供正确的打开密码；仅所有者锁定时可直接免密解锁。",
    ),
    PdfToolSpec(
        id=TOOL_COMPRESS,
        label="压缩",
        category=CATEGORY_SECURITY,
        accepts=PDF_SUFFIXES,
        plural=False,
        description="无损优化 PDF 体积：清理重复对象、压缩内容流并剥离冗余元数据。",
        hint="仅做无损结构精简，不降低图片画质；若本身已极致压缩则收益有限。",
    ),
)

TOOL_SPEC_BY_ID: Dict[str, PdfToolSpec] = {spec.id: spec for spec in TOOL_SPECS}
TOOL_IDS: Tuple[str, ...] = tuple(TOOL_SPEC_BY_ID)


@dataclass
class PdfToolOutcome:
    """单个工具操作的底层执行结果。"""

    ok: bool
    reason: str = "ok"
    detail: str = ""
    error_code: Optional[str] = None
    outputs: List[Path] = field(default_factory=list)
    note: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class PdfToolRecord:
    """批量或单次处理中，单个源文件（或一组源文件）的结构化执行记录。"""

    tool: str
    source: Path
    outputs: List[Path] = field(default_factory=list)
    ok: bool = True
    reason: str = "ok"
    detail: str = ""
    error_code: Optional[str] = None
    elapsed_seconds: float = 0.0
    position: int = 0
    note: str = ""

    @property
    def label(self) -> str:
        spec = TOOL_SPEC_BY_ID.get(self.tool)
        return spec.label if spec else self.tool

    @property
    def status(self) -> str:
        return "成功" if self.ok else "失败"

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "label": self.label,
            "source": str(self.source),
            "outputs": [str(p) for p in self.outputs],
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "errorCode": self.error_code,
            "elapsedSeconds": round(self.elapsed_seconds, 2),
            "note": self.note,
        }


@dataclass
class PdfToolBatchResult:
    """PDF 工具批量调用的最终汇总。"""

    records: List[PdfToolRecord] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def succeeded(self) -> int:
        return sum(1 for record in self.records if record.ok)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    @property
    def success(self) -> bool:
        return not self.cancelled and self.total > 0 and self.failed == 0

    @property
    def error_code(self) -> Optional[str]:
        if self.cancelled:
            from doc_tool.domain.errors import CancelledError

            return CancelledError.code
        for record in self.records:
            if not record.ok and record.error_code:
                return record.error_code
        return None

    def summary(self) -> str:
        if self.cancelled:
            return "已取消：完成 {0} 个，剩余文件未处理。".format(self.succeeded)
        if self.total == 0:
            return "没有可处理的文件。"
        text = "成功 {0} 个，失败 {1} 个。".format(self.succeeded, self.failed)
        codes = sorted({record.error_code for record in self.records if record.error_code})
        if codes:
            text += " 涉及错误码：{0}。".format("、".join(codes))
        return text

    def to_dict(self) -> dict:
        return {
            "records": [record.to_dict() for record in self.records],
            "cancelled": self.cancelled,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "success": self.success,
            "errorCode": self.error_code,
            "summary": self.summary(),
        }


# --- 页码与语法解析 ---


def parse_page_selection(
    text: Optional[str], page_count: Optional[int] = None
) -> Optional[List[int]]:
    """解析「1-5,8,10-12」形式的页码选择字符串。

    返回值：0 基升序、去重的页面索引列表。
    若 text 为空、None 或 'all'（不区分大小写），返回 None 表示全部页面。
    若存在语法错误、起始大于结束、起始小于 1 或越界（给定 page_count 时），抛出 PdfPageSelectionError。
    """
    if text is None:
        return None
    raw = text.strip()
    if not raw or raw.lower() == "all":
        return None

    # 分隔符支持英文逗号、中文逗号、分号、空白字符
    tokens = re.split(r"[,，;；\s]+", raw)
    selected_pages: Set[int] = set()

    for token in tokens:
        if not token:
            continue
        range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", token)
        if range_match:
            start_num = int(range_match.group(1))
            end_num = int(range_match.group(2))
            if start_num < 1 or start_num > end_num:
                raise PdfPageSelectionError(
                    suggested_action="页码范围「{0}」无效，起始页码必须大于等于 1 且不大于结束页码。".format(
                        token
                    ),
                    details={"token": token, "text": text},
                )
            if page_count is not None and end_num > page_count:
                raise PdfPageSelectionError(
                    suggested_action="页码「{0}」超出文档总页数（共 {1} 页）。".format(
                        end_num, page_count
                    ),
                    details={"token": token, "page_count": page_count},
                )
            for num in range(start_num, end_num + 1):
                selected_pages.add(num - 1)
        elif re.match(r"^\d+$", token):
            num = int(token)
            if num < 1:
                raise PdfPageSelectionError(
                    suggested_action="页码必须从 1 开始。",
                    details={"token": token, "text": text},
                )
            if page_count is not None and num > page_count:
                raise PdfPageSelectionError(
                    suggested_action="页码「{0}」超出文档总页数（共 {1} 页）。".format(
                        num, page_count
                    ),
                    details={"token": token, "page_count": page_count},
                )
            selected_pages.add(num - 1)
        else:
            raise PdfPageSelectionError(
                suggested_action="无法解析页码片段「{0}」，格式应如「1-5」或「8」。".format(token),
                details={"token": token, "text": text},
            )

    return sorted(selected_pages)


def parse_page_ranges(
    text: Optional[str], page_count: Optional[int] = None
) -> List[Tuple[int, int]]:
    """解析用于拆分的页码范围字符串（1 基，含首尾），保留用户指定的顺序。

    例如 '1-3,5-8,10' 返回 [(1,3), (5,8), (10,10)]。
    """
    if not text or not text.strip():
        raise PdfPageSelectionError(
            suggested_action="请提供要拆分的页码范围，例如「1-3,5-8」。"
        )
    tokens = re.split(r"[,，;；\s]+", text.strip())
    ranges: List[Tuple[int, int]] = []
    for token in tokens:
        if not token:
            continue
        range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", token)
        if range_match:
            start_num = int(range_match.group(1))
            end_num = int(range_match.group(2))
            if start_num < 1 or start_num > end_num:
                raise PdfPageSelectionError(
                    suggested_action="页码范围「{0}」无效，起始页码必须从 1 开始且起始不大于结束。".format(
                        token
                    ),
                    details={"token": token},
                )
            if page_count is not None and end_num > page_count:
                raise PdfPageSelectionError(
                    suggested_action="页码范围「{0}」超出文档总页数（共 {1} 页）。".format(
                        token, page_count
                    ),
                    details={"token": token, "page_count": page_count},
                )
            ranges.append((start_num, end_num))
        elif re.match(r"^\d+$", token):
            num = int(token)
            if num < 1:
                raise PdfPageSelectionError(
                    suggested_action="页码必须从 1 开始。", details={"token": token}
                )
            if page_count is not None and num > page_count:
                raise PdfPageSelectionError(
                    suggested_action="页码「{0}」超出文档总页数（共 {1} 页）。".format(
                        num, page_count
                    ),
                    details={"token": token, "page_count": page_count},
                )
            ranges.append((num, num))
        else:
            raise PdfPageSelectionError(
                suggested_action="无法解析页码范围「{0}」。".format(token),
                details={"token": token},
            )
    if not ranges:
        raise PdfPageSelectionError(suggested_action="未解析到有效页码范围。")
    return ranges


# --- Qt 图形与覆盖层辅助 ---

_QT_APP_INITIALIZED = False


def _ensure_qgui_application() -> None:
    """确保当前进程存在 QApplication 上下文。

    在 CLI 与无头测试环境下创建默认实例。创建 QApplication（它是 QGuiApplication 子类），
    既能保证 QPdfWriter/QPainter 字体与矢量渲染，也能支持 UI 控件正常构造。
    严禁设置 QT_QPA_PLATFORM=offscreen。
    """
    global _QT_APP_INITIALIZED
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        _QT_APP_INITIALIZED = True
        QApplication([])


def _ui_font(point_size: float = 10.0, bold: bool = False) -> Any:
    """获取系统中可用的中文字体，优先匹配常见中文字体名。"""
    from PySide6.QtGui import QFont, QFontDatabase

    candidate_families = (
        "SimSun",
        "宋体",
        "NSimSun",
        "SimHei",
        "黑体",
        "Microsoft YaHei",
        "微软雅黑",
        "PingFang SC",
        "Arial",
    )
    available = set(QFontDatabase.families())
    matched_family = "Arial"
    for fam in candidate_families:
        if fam in available:
            matched_family = fam
            break
    font = QFont(matched_family)
    font.setPointSizeF(point_size)
    font.setBold(bold)
    return font


def _hex_color(text: Optional[str], fallback: str = "#000000") -> Any:
    """将颜色字符串解析为 QColor，无效时使用 fallback。"""
    from PySide6.QtGui import QColor

    if text:
        c = QColor(text.strip())
        if c.isValid():
            return c
    return QColor(fallback)


def _watermark_color(hex_color: str, opacity_pct: int) -> Any:
    """计算向白色淡化模拟透明度的实色 QColor。

    Qt 6.8 PDF 引擎输出实色忽略画笔 alpha，因此通过向白色按比例插值计算模拟透明度。
    """
    from PySide6.QtGui import QColor

    base = _hex_color(hex_color, "#ff0000")
    ratio = max(1, min(100, opacity_pct)) / 100.0
    r = int(round(base.red() * ratio + 255 * (1.0 - ratio)))
    g = int(round(base.green() * ratio + 255 * (1.0 - ratio)))
    b = int(round(base.blue() * ratio + 255 * (1.0 - ratio)))
    return QColor(r, g, b)


def _apply_orientation(painter: Any, pw: float, ph: float, rot: int) -> Tuple[float, float]:
    """根据页面原始旋转角度（90/180/270）在未旋转画布上建立变换，返回显示空间的宽高 (lw, lh)。

    探针勘误（第三会话实测修正）：
    rot=90: translate(0, ph); rotate(-90); 逻辑宽高 (ph, pw)
    rot=180: translate(pw, ph); rotate(180); 逻辑宽高 (pw, ph)
    rot=270: translate(pw, 0); rotate(90); 逻辑宽高 (ph, pw)
    """
    rot = rot % 360
    if rot == 90:
        painter.translate(0, ph)
        painter.rotate(-90)
        return ph, pw
    elif rot == 180:
        painter.translate(pw, ph)
        painter.rotate(180)
        return pw, ph
    elif rot == 270:
        painter.translate(pw, 0)
        painter.rotate(90)
        return ph, pw
    return pw, ph


def _create_overlay_pdf_bytes(
    pages_meta: List[Tuple[float, float, int]],
    painter_callback: Callable[[Any, int, float, float], None],
) -> bytes:
    """内存中生成同等页数的覆盖层 PDF 字节。

    pages_meta: 每页的 (mediabox.width, mediabox.height, /Rotate%360)
    painter_callback: (painter, page_idx, lw, lh) -> 在正立的显示空间 (lw, lh) 绘制
    """
    _ensure_qgui_application()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)

    writer = QPdfWriter(buf)
    writer.setResolution(72)

    painter: Optional[QPainter] = None

    if not pages_meta:
        return b""

    for idx, (pw, ph, rot) in enumerate(pages_meta):
        # 页面尺寸必须使用未旋转的原始 mediabox 尺寸
        page_size = QPageSize(QSizeF(pw, ph), QPageSize.Unit.Point)
        writer.setPageSize(page_size)
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)

        if idx == 0:
            painter = QPainter(writer)
        else:
            writer.newPage()

        if painter is not None:
            painter.save()
            lw, lh = _apply_orientation(painter, pw, ph, rot)
            painter_callback(painter, idx, lw, lh)
            painter.restore()

    if painter is not None:
        painter.end()

    buf.close()
    return bytes(ba.data())


# --- 底层文件与 Reader 辅助 ---


def _open_reader(source: Path, password: str = "") -> Any:
    """以只读方式打开并解密 PDF 文件，返回 pypdf.PdfReader。"""
    import pypdf
    from pypdf.errors import DependencyError, FileNotDecryptedError, PdfReadError

    if not source.is_file():
        raise PdfFileError(
            suggested_action="文件不存在：{0}".format(source.name),
            details={"source": str(source)},
        )

    try:
        reader = pypdf.PdfReader(str(source))
    except (PdfReadError, Exception) as exc:
        if isinstance(exc, DependencyError):
            raise PdfEncryptedError(
                suggested_action="该 PDF 使用了高级加密算法，当前环境缺少解密支持组件。",
                details={"source": str(source), "error": str(exc)},
            )
        raise PdfFileError(
            suggested_action="无法解析 PDF 文件，文件可能损坏或格式不规范：{0}".format(
                source.name
            ),
            details={"source": str(source), "error": str(exc)},
        )

    if reader.is_encrypted:
        try:
            if password:
                status = reader.decrypt(password)
                if int(status) == 0:
                    raise PdfPasswordError(
                        suggested_action="密码不正确，无法打开已加密的 PDF：{0}".format(
                            source.name
                        ),
                        details={"source": str(source)},
                    )
            else:
                status = reader.decrypt("")
                if int(status) == 0:
                    raise PdfEncryptedError(
                        suggested_action="该 PDF 已加密，需要提供密码才能操作：{0}".format(
                            source.name
                        ),
                        details={"source": str(source)},
                    )
        except DependencyError as exc:
            raise PdfEncryptedError(
                suggested_action="解密该 PDF 需要额外依赖库（如 cryptography）。",
                details={"source": str(source), "error": str(exc)},
            )

    try:
        _ = len(reader.pages)
    except FileNotDecryptedError:
        raise PdfEncryptedError(
            suggested_action="该 PDF 已加密，需先输入正确密码。",
            details={"source": str(source)},
        )
    except Exception as exc:
        raise PdfFileError(
            suggested_action="读取 PDF 页面失败，文件可能已损坏。",
            details={"source": str(source), "error": str(exc)},
        )

    return reader


def _check_target_conflict(targets: Sequence[Path], overwrite: bool) -> None:
    """预检产物同名冲突。若存在已存在的文件且未设置 overwrite，抛出 E6002。"""
    if overwrite:
        return
    for t in targets:
        if t.exists():
            raise ConversionTargetExistsError(
                suggested_action="输出文件「{0}」已存在。如需覆盖，请勾选「覆盖同名文件」或使用 --overwrite 参数。".format(
                    t.name
                ),
                details={"target": str(t)},
            )


def _safe_write_pdf(writer: Any, target: Path) -> None:
    """安全将 pypdf.PdfWriter 内容写入目标文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "wb") as f:
            writer.write(f)
    except PermissionError as exc:
        raise PdfWriteError(
            suggested_action="无法写入目标文件「{0}」，可能被其他程序独占打开或缺乏写入权限。".format(
                target.name
            ),
            details={"target": str(target), "error": str(exc)},
        )
    except Exception as exc:
        raise PdfWriteError(
            suggested_action="写入文件「{0}」时发生错误。".format(target.name),
            details={"target": str(target), "error": str(exc)},
        )


# --- 14 个核心工具实现 ---


def _tool_merge(
    sources: Sequence[Path],
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """合并多个 PDF 为一个单文档。"""
    import pypdf

    if len(sources) < 2:
        raise PdfInputError(
            suggested_action="合并操作至少需要提供 2 个 PDF 文件。",
            details={"count": len(sources)},
        )

    out_dir = output_dir or sources[0].parent
    custom_name = options.get("output_name")
    if custom_name and custom_name.strip():
        name = custom_name.strip()
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
    else:
        name = "{0}_合并.pdf".format(sources[0].stem)
    target = out_dir / name

    _check_target_conflict([target], overwrite)

    writer = pypdf.PdfWriter()
    total_pages = 0
    readers = []
    try:
        for src in sources:
            reader = _open_reader(src, options.get("password", ""))
            readers.append(reader)
            writer.append(reader)
            total_pages += len(reader.pages)

        _safe_write_pdf(writer, target)
    finally:
        for r in readers:
            try:
                r.close()
            except Exception:
                pass

    return PdfToolOutcome(
        ok=True,
        outputs=[target],
        detail="已将 {0} 个文件合并为 1 个文档，共 {1} 页".format(len(sources), total_pages),
    )


def _tool_split(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """拆分 PDF：按单页、按每 N 页或按页码范围。"""
    import pypdf

    reader = _open_reader(source, options.get("password", ""))
    try:
        total_pages = len(reader.pages)
        if total_pages == 0:
            raise PdfFileError(suggested_action="该 PDF 没有页面可拆分。")

        mode = options.get("mode", "each")
        out_dir = output_dir or (source.parent / "{0}_拆分".format(source.stem))

        ranges: List[Tuple[int, int]] = []
        if mode == "each":
            ranges = [(i, i) for i in range(1, total_pages + 1)]
        elif mode == "every-n":
            every = int(options.get("every", 1))
            if every < 1:
                raise PdfInputError(suggested_action="按页数拆分时，每组页数必须大于等于 1。")
            for start in range(1, total_pages + 1, every):
                end = min(start + every - 1, total_pages)
                ranges.append((start, end))
        elif mode == "range":
            ranges = parse_page_ranges(options.get("ranges", ""), total_pages)
        else:
            raise PdfInputError(
                suggested_action="未知的拆分模式「{0}」（支持 each / every-n / range）。".format(
                    mode
                )
            )

        # 保持顺序去重，防止重复区间导致同名覆盖
        seen_ranges: Set[Tuple[int, int]] = set()
        deduped_ranges: List[Tuple[int, int]] = []
        for r in ranges:
            if r not in seen_ranges:
                seen_ranges.add(r)
                deduped_ranges.append(r)
        ranges = deduped_ranges

        # 计算目标产物路径并做同名预检
        targets_and_slices: List[Tuple[Path, int, int]] = []
        for start, end in ranges:
            if start == end:
                t_name = "{0}_第{1:03d}页.pdf".format(source.stem, start)
            else:
                t_name = "{0}_第{1:03d}-{2:03d}页.pdf".format(source.stem, start, end)
            targets_and_slices.append((out_dir / t_name, start - 1, end))

        _check_target_conflict([item[0] for item in targets_and_slices], overwrite)

        out_dir.mkdir(parents=True, exist_ok=True)
        generated: List[Path] = []
        for target_path, slice_start, slice_end in targets_and_slices:
            writer = pypdf.PdfWriter()
            for p_idx in range(slice_start, slice_end):
                writer.add_page(reader.pages[p_idx])
            _safe_write_pdf(writer, target_path)
            generated.append(target_path)

        return PdfToolOutcome(
            ok=True,
            outputs=generated,
            detail="已将文档拆分为 {0} 个 PDF 文件".format(len(generated)),
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_extract(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """提取选定页面生成新文档。"""
    import pypdf

    reader = _open_reader(source, options.get("password", ""))
    total_pages = len(reader.pages)
    pages_spec = options.get("pages")
    if not pages_spec or not str(pages_spec).strip():
        raise PdfInputError(
            suggested_action="请指定要提取的页码（如「1-3,5」），提取操作不能留空。"
        )

    selected = parse_page_selection(pages_spec, total_pages)
    if not selected:
        raise PdfInputError(suggested_action="未选定任何有效页面进行提取。")

    out_dir = output_dir or source.parent
    target = out_dir / "{0}_提取.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    try:
        writer = pypdf.PdfWriter()
        writer.append(reader, pages=selected)
        _safe_write_pdf(writer, target)

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已成功提取 {0} 页到新文档".format(len(selected)),
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_delete(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """删除选定页面后保存新文档。"""
    import pypdf

    reader = _open_reader(source, options.get("password", ""))
    total_pages = len(reader.pages)
    pages_spec = options.get("pages")
    if not pages_spec or not str(pages_spec).strip():
        raise PdfInputError(
            suggested_action="请指定要删除的页码（如「2,4」），删除操作不能留空。"
        )

    to_delete = set(parse_page_selection(pages_spec, total_pages) or [])
    if not to_delete:
        raise PdfInputError(suggested_action="未指定有效删除页码。")
    if len(to_delete) >= total_pages:
        raise PdfInputError(
            suggested_action="不能删除全部页面，必须至少保留 1 个页面。"
        )

    kept = [i for i in range(total_pages) if i not in to_delete]

    out_dir = output_dir or source.parent
    target = out_dir / "{0}_删除后.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    try:
        writer = pypdf.PdfWriter()
        writer.append(reader, pages=kept)
        _safe_write_pdf(writer, target)

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已删除 {0} 页，保留剩余 {1} 页".format(len(to_delete), len(kept)),
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_rotate(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """旋转页面角度。"""
    import pypdf
    from pypdf.generic import NumberObject

    reader = _open_reader(source, options.get("password", ""))
    total_pages = len(reader.pages)

    deg = int(options.get("degrees", 90)) % 360
    if deg not in (90, 180, 270):
        raise PdfInputError(suggested_action="旋转角度必须为 90°、180° 或 270°。")

    selected = parse_page_selection(options.get("pages"), total_pages)
    target_indices = set(selected if selected is not None else range(total_pages))

    out_dir = output_dir or source.parent
    target = out_dir / "{0}_旋转.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    try:
        writer = pypdf.PdfWriter(clone_from=reader)
        for idx in target_indices:
            page = writer.pages[idx]
            current_rot = int(page.get("/Rotate", 0))
            new_rot = (current_rot + deg) % 360
            page[pypdf.generic.NameObject("/Rotate")] = NumberObject(new_rot)

        _safe_write_pdf(writer, target)

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已将 {0} 个页面顺时针旋转 {1}°".format(len(target_indices), deg),
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_to_images(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """将 PDF 渲染并导出为图片（基于 QBuffer 载入 QPdfDocument 规避锁与黑底）。"""
    _ensure_qgui_application()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtPdf import QPdfDocument

    raw_bytes = source.read_bytes()
    qba = QByteArray(raw_bytes)
    qbuf = QBuffer()
    qbuf.setData(qba)
    qbuf.open(QIODevice.OpenModeFlag.ReadOnly)

    doc = QPdfDocument()
    doc.load(qbuf)
    try:
        status_err = doc.error()
        if status_err in (
            QPdfDocument.Error.IncorrectPassword,
            QPdfDocument.Error.UnsupportedSecurityScheme,
        ):
            raise PdfEncryptedError(
                suggested_action="该 PDF 已加密，需先解密后才能转为图片。"
            )
        if status_err in (
            QPdfDocument.Error.FileNotFound,
            QPdfDocument.Error.InvalidFileFormat,
        ):
            raise PdfFileError(
                suggested_action="无法通过 Qt 渲染引擎解析该 PDF，文件可能已损坏。"
            )

        total_pages = doc.pageCount()
        if total_pages == 0:
            raise PdfFileError(suggested_action="该 PDF 没有可渲染的页面。")

        selected = parse_page_selection(options.get("pages"), total_pages)
        target_indices = selected if selected is not None else list(range(total_pages))

        img_format = str(options.get("image_format", "png")).lower()
        if img_format not in ("png", "jpg", "jpeg"):
            img_format = "png"
        save_format = "JPG" if img_format in ("jpg", "jpeg") else "PNG"
        file_ext = ".jpg" if save_format == "JPG" else ".png"

        dpi = int(options.get("dpi", 150))
        dpi = max(36, min(600, dpi))
        scale = dpi / 72.0

        out_dir = output_dir or (source.parent / "{0}_图片".format(source.stem))

        target_files: List[Tuple[Path, int]] = []
        for p_idx in target_indices:
            t_path = out_dir / "{0}_第{1:03d}页{2}".format(source.stem, p_idx + 1, file_ext)
            target_files.append((t_path, p_idx))

        _check_target_conflict([item[0] for item in target_files], overwrite)
        out_dir.mkdir(parents=True, exist_ok=True)

        generated: List[Path] = []
        skipped: int = 0
        note_msg = ""

        for target_path, p_idx in target_files:
            page_size = doc.pagePointSize(p_idx)
            raw_w = max(1.0, page_size.width())
            raw_h = max(1.0, page_size.height())

            pixel_w = int(round(raw_w * scale))
            pixel_h = int(round(raw_h * scale))

            max_dim = max(pixel_w, pixel_h)
            if max_dim > 12000:
                downscale = 12000.0 / max_dim
                pixel_w = int(round(pixel_w * downscale))
                pixel_h = int(round(pixel_h * downscale))
                note_msg = "部分页面分辨率超出 12000px 上限，已自动按比例缩放"

            rendered_img = doc.render(p_idx, QSize(pixel_w, pixel_h))
            if rendered_img.isNull():
                skipped += 1
                continue

            # 白底展平，防止透明区域转 JPG/RGB 时变成黑色背景
            flattened = QImage(rendered_img.size(), QImage.Format.Format_RGB32)
            flattened.fill(Qt.GlobalColor.white)
            p = QPainter(flattened)
            p.drawImage(0, 0, rendered_img)
            p.end()

            if save_format == "JPG":
                flattened.save(str(target_path), "JPG", quality=90)
            else:
                flattened.save(str(target_path), "PNG")
            generated.append(target_path)

        if not generated:
            raise PdfRenderError(suggested_action="全部页面渲染失败，无法导出图片。")

        detail = "已成功渲染并导出 {0} 张图片（DPI: {1}）".format(len(generated), dpi)
        if skipped > 0:
            detail += "，{0} 页渲染失败已跳过".format(skipped)

        return PdfToolOutcome(
            ok=True,
            outputs=generated,
            detail=detail,
            note=note_msg,
        )
    finally:
        try:
            doc.close()
        except Exception:
            pass
        try:
            qbuf.close()
        except Exception:
            pass


def _tool_images_to_pdf(
    sources: Sequence[Path],
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """将多张图片合成一个 PDF 文档。"""
    from PIL import Image, ImageOps

    if not sources:
        raise PdfInputError(suggested_action="请至少添加一张图片。")

    out_dir = output_dir or sources[0].parent
    custom_name = options.get("output_name")
    if custom_name and custom_name.strip():
        name = custom_name.strip()
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
    else:
        name = "{0}_图片.pdf".format(sources[0].stem)
    target = out_dir / name

    _check_target_conflict([target], overwrite)

    a4_mode = bool(options.get("a4", False))
    processed_images: List[Image.Image] = []

    for src in sources:
        try:
            with Image.open(src) as raw_im:
                im = ImageOps.exif_transpose(raw_im)
                if im.mode in ("RGBA", "LA") or (
                    im.mode == "P" and "transparency" in im.info
                ):
                    im_rgba = im.convert("RGBA")
                    bg = Image.new("RGB", im_rgba.size, (255, 255, 255))
                    bg.paste(im_rgba, mask=im_rgba.split()[3])
                    rgb_im = bg
                elif im.mode != "RGB":
                    rgb_im = im.convert("RGB")
                else:
                    rgb_im = im.copy()

                if a4_mode:
                    # A4 标准尺寸（150 DPI）：1240 x 1754 像素
                    a4_w, a4_h = 1240, 1754
                    canvas = Image.new("RGB", (a4_w, a4_h), (255, 255, 255))
                    im_ratio = rgb_im.width / float(rgb_im.height)
                    canvas_ratio = a4_w / float(a4_h)
                    if im_ratio > canvas_ratio:
                        nw = a4_w
                        nh = int(round(a4_w / im_ratio))
                    else:
                        nh = a4_h
                        nw = int(round(a4_h * im_ratio))
                    resized = rgb_im.resize(
                        (max(1, nw), max(1, nh)), Image.Resampling.LANCZOS
                    )
                    ox = (a4_w - nw) // 2
                    oy = (a4_h - nh) // 2
                    canvas.paste(resized, (ox, oy))
                    processed_images.append(canvas)
                else:
                    processed_images.append(rgb_im)
        except Exception as exc:
            raise PdfImageError(
                suggested_action="读取图片「{0}」失败，请确认格式是否支持且文件未损坏。".format(
                    src.name
                ),
                details={"source": str(src), "error": str(exc)},
            )

    resolution = 150.0 if a4_mode else 72.0
    first = processed_images[0]
    rest = processed_images[1:]
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        try:
            first.save(
                str(target),
                "PDF",
                save_all=True,
                append_images=rest,
                resolution=resolution,
            )
        except Exception as exc:
            raise PdfWriteError(
                suggested_action="将图片保存为 PDF 失败。",
                details={"target": str(target), "error": str(exc)},
            )

        detail = "已将 {0} 张图片合并为 PDF".format(len(sources))
        if a4_mode:
            detail += "（A4 居中适应版面）"

        return PdfToolOutcome(ok=True, outputs=[target], detail=detail)
    finally:
        for im in processed_images:
            try:
                im.close()
            except Exception:
                pass


def _tool_to_text(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """提取 PDF 文本并保存为 TXT 文本。"""
    reader = _open_reader(source, options.get("password", ""))
    try:
        total_pages = len(reader.pages)
        selected = parse_page_selection(options.get("pages"), total_pages)
        target_indices = selected if selected is not None else list(range(total_pages))

        out_dir = output_dir or source.parent
        target = out_dir / "{0}_文本.txt".format(source.stem)
        _check_target_conflict([target], overwrite)

        chunks: List[str] = []
        total_chars = 0
        for idx in target_indices:
            text = reader.pages[idx].extract_text() or ""
            total_chars += len(text)
            chunks.append("--- 第 {0} 页 ---\n{1}\n".format(idx + 1, text))

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text("\n".join(chunks), encoding="utf-8")
        except Exception as exc:
            raise PdfWriteError(
                suggested_action="写入文本文件失败。",
                details={"target": str(target), "error": str(exc)},
            )

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已提取 {0} 页文本，共 {1} 个字符".format(len(target_indices), total_chars),
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_watermark(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """添加全页平铺或居中文本水印。"""
    import pypdf
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF

    wm_text = str(options.get("text", "")).strip()
    if not wm_text:
        raise PdfInputError(
            suggested_action="请填写水印文字内容，水印文字不能为空。"
        )

    font_size = float(options.get("font_size", 48.0))
    if font_size <= 0:
        font_size = 48.0
    opacity = int(options.get("opacity", 30))
    angle = float(options.get("angle", 45.0))
    mode = str(options.get("mode", "center")).lower()
    color_hex = str(options.get("color", "#ff0000"))

    reader = _open_reader(source, options.get("password", ""))
    total_pages = len(reader.pages)
    if total_pages == 0:
        try:
            reader.close()
        except Exception:
            pass
        raise PdfFileError(suggested_action="该 PDF 没有页面可添加水印。")
    selected = parse_page_selection(options.get("pages"), total_pages)
    target_indices = set(selected if selected is not None else range(total_pages))

    out_dir = output_dir or source.parent
    target = out_dir / "{0}_水印.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    pages_meta: List[Tuple[float, float, int]] = []
    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        rot = int(page.get("/Rotate", 0)) % 360
        pages_meta.append((w, h, rot))

    sim_color = _watermark_color(color_hex, opacity)
    font = _ui_font(font_size, bold=True)

    def _draw_wm(painter: Any, idx: int, lw: float, lh: float) -> None:
        if idx not in target_indices:
            return
        painter.setFont(font)
        painter.setPen(sim_color)
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(wm_text)
        text_h = fm.height()

        if mode == "tiled":
            cols, rows = 3, 4
            cell_w = lw / cols
            cell_h = lh / rows
            for c in range(cols):
                for r in range(rows):
                    cx = (c + 0.5) * cell_w
                    cy = (r + 0.5) * cell_h
                    painter.save()
                    painter.translate(cx, cy)
                    painter.rotate(-angle)
                    painter.drawText(
                        QRectF(-text_w / 2.0, -text_h / 2.0, text_w, text_h),
                        Qt.AlignmentFlag.AlignCenter,
                        wm_text,
                    )
                    painter.restore()
        else:
            painter.save()
            painter.translate(lw / 2.0, lh / 2.0)
            painter.rotate(-angle)
            painter.drawText(
                QRectF(-text_w / 2.0, -text_h / 2.0, text_w, text_h),
                Qt.AlignmentFlag.AlignCenter,
                wm_text,
            )
            painter.restore()

    overlay_bytes = _create_overlay_pdf_bytes(pages_meta, _draw_wm)
    overlay_reader = pypdf.PdfReader(io.BytesIO(overlay_bytes))

    writer = pypdf.PdfWriter()
    for i, orig_page in enumerate(reader.pages):
        if i in target_indices:
            over_page = overlay_reader.pages[i]
            mb_left = float(orig_page.mediabox.left)
            mb_bottom = float(orig_page.mediabox.bottom)
            if mb_left != 0 or mb_bottom != 0:
                orig_page.merge_transformed_page(
                    over_page,
                    pypdf.Transformation().translate(mb_left, mb_bottom),
                    over=True,
                )
            else:
                orig_page.merge_page(over_page, over=True)
        writer.add_page(orig_page)

    try:
        _safe_write_pdf(writer, target)

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已为 {0} 个页面添加文字水印「{1}」".format(len(target_indices), wm_text),
            note="水印透明度以颜色向白色减淡模拟呈现",
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass
        try:
            overlay_reader.close()
        except Exception:
            pass


def _tool_page_numbers(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """为 PDF 页面添加标准页码标记。"""
    import pypdf
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF

    reader = _open_reader(source, options.get("password", ""))
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise PdfFileError(suggested_action="该 PDF 没有页面可添加页码。")

    pos = str(options.get("position", "bottom-center")).lower()
    fmt_type = str(options.get("format", "第n页/共N页"))
    start_num = int(options.get("start", 1))
    skip_first = bool(options.get("skip_first", False))
    font_size = float(options.get("font_size", 10.0))
    if font_size <= 0:
        font_size = 10.0
    margin = float(options.get("margin", 24.0))
    color = _hex_color(options.get("color"), "#000000")
    font = _ui_font(font_size)

    out_dir = output_dir or source.parent
    target = out_dir / "{0}_页码.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    pages_meta: List[Tuple[float, float, int]] = []
    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        rot = int(page.get("/Rotate", 0)) % 360
        pages_meta.append((w, h, rot))

    display_total = max(1, total_pages - 1 if skip_first else total_pages)

    def _draw_pn(painter: Any, idx: int, lw: float, lh: float) -> None:
        if skip_first and idx == 0:
            return
        curr_num = start_num + (idx - 1 if skip_first else idx)

        # 格式化文本（汉字短语带空格以利于探针与提取断言）
        if fmt_type == "n":
            text = "{0}".format(curr_num)
        elif fmt_type == "-n-":
            text = "- {0} -".format(curr_num)
        elif fmt_type == "n/N":
            text = "{0} / {1}".format(curr_num, display_total)
        elif fmt_type == "第n页":
            text = "第 {0} 页".format(curr_num)
        else:  # 第n页/共N页
            text = "第 {0} 页 / 共 {1} 页".format(curr_num, display_total)

        painter.setFont(font)
        painter.setPen(color)
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(text) + 20.0
        text_h = fm.height() + 6.0

        if pos == "top-left":
            rect = QRectF(margin, margin, text_w, text_h)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif pos == "top-right":
            rect = QRectF(lw - margin - text_w, margin, text_w, text_h)
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif pos == "top-center":
            rect = QRectF((lw - text_w) / 2.0, margin, text_w, text_h)
            align = Qt.AlignmentFlag.AlignCenter
        elif pos == "bottom-left":
            rect = QRectF(margin, lh - margin - text_h, text_w, text_h)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif pos == "bottom-right":
            rect = QRectF(lw - margin - text_w, lh - margin - text_h, text_w, text_h)
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:  # bottom-center
            rect = QRectF((lw - text_w) / 2.0, lh - margin - text_h, text_w, text_h)
            align = Qt.AlignmentFlag.AlignCenter

        painter.drawText(rect, align, text)

    overlay_bytes = _create_overlay_pdf_bytes(pages_meta, _draw_pn)
    overlay_reader = pypdf.PdfReader(io.BytesIO(overlay_bytes))

    writer = pypdf.PdfWriter()
    for i, orig_page in enumerate(reader.pages):
        over_page = overlay_reader.pages[i]
        mb_left = float(orig_page.mediabox.left)
        mb_bottom = float(orig_page.mediabox.bottom)
        if mb_left != 0 or mb_bottom != 0:
            orig_page.merge_transformed_page(
                over_page,
                pypdf.Transformation().translate(mb_left, mb_bottom),
                over=True,
            )
        else:
            orig_page.merge_page(over_page, over=True)
        writer.add_page(orig_page)

    try:
        _safe_write_pdf(writer, target)

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已为 {0} 页添加页码（格式：{1}，位置：{2}）".format(
                total_pages - (1 if skip_first else 0), fmt_type, pos
            ),
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass
        try:
            overlay_reader.close()
        except Exception:
            pass


def _tool_metadata(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """查看或编辑 PDF 元数据（标题、作者、主题、关键字）。"""
    import pypdf

    reader = _open_reader(source, options.get("password", ""))
    meta = reader.metadata or {}

    t = options.get("title")
    a = options.get("author")
    s = options.get("subject")
    k = options.get("keywords")

    is_edit_mode = any(val is not None for val in (t, a, s, k))

    try:
        if not is_edit_mode:
            # 查看模式：无输出文件，detail 返回元数据详情
            lines = [
                "标题: {0}".format(meta.get("/Title") or "（未设置）"),
                "作者: {0}".format(meta.get("/Author") or "（未设置）"),
                "主题: {0}".format(meta.get("/Subject") or "（未设置）"),
                "关键字: {0}".format(meta.get("/Keywords") or "（未设置）"),
            ]
            return PdfToolOutcome(ok=True, outputs=[], detail="\n".join(lines))

        out_dir = output_dir or source.parent
        target = out_dir / "{0}_元数据.pdf".format(source.stem)
        _check_target_conflict([target], overwrite)

        writer = pypdf.PdfWriter(clone_from=reader)
        new_meta: Dict[str, Any] = dict(writer.metadata or {})
        if t is not None:
            new_meta["/Title"] = str(t)
        if a is not None:
            new_meta["/Author"] = str(a)
        if s is not None:
            new_meta["/Subject"] = str(s)
        if k is not None:
            new_meta["/Keywords"] = str(k)

        writer.add_metadata(new_meta)
        _safe_write_pdf(writer, target)

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已更新文档元数据（标题/作者/主题/关键字）",
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_encrypt(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """为 PDF 文件设置密码与权限控制。"""
    import pypdf
    from pypdf.constants import UserAccessPermissions

    user_pw = str(options.get("user_password", ""))
    if not user_pw:
        raise PdfInputError(
            suggested_action="加密操作必须设置打开密码（user_password）。"
        )
    owner_pw = str(options.get("owner_password", "")) or user_pw

    allow_print = bool(options.get("allow_print", True))
    allow_copy = bool(options.get("allow_copy", False))
    allow_modify = bool(options.get("allow_modify", False))
    allow_annotate = bool(options.get("allow_annotate", False))

    # 从完整权限出发逐个关闭被禁用的权限位
    perms = UserAccessPermissions.all()
    if not allow_print:
        perms &= ~(
            UserAccessPermissions.PRINT
            | UserAccessPermissions.PRINT_TO_REPRESENTATION
        )
    if not allow_copy:
        perms &= ~(
            UserAccessPermissions.EXTRACT
            | UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS
        )
    if not allow_modify:
        perms &= ~(
            UserAccessPermissions.MODIFY | UserAccessPermissions.ASSEMBLE_DOC
        )
    if not allow_annotate:
        perms &= ~(
            UserAccessPermissions.ADD_OR_MODIFY
            | UserAccessPermissions.FILL_FORM_FIELDS
        )

    # 算法探测：cryptography 在位时使用 AES-256，否则降级为 RC4-128
    has_crypto = False
    try:
        import cryptography  # noqa: F401

        has_crypto = True
    except ImportError:
        pass

    algorithm = "AES-256" if has_crypto else "RC4-128"
    note_msg = "" if has_crypto else "未安装 cryptography，已自动降级为 RC4-128 加密"

    reader = _open_reader(source, options.get("password", ""))
    out_dir = output_dir or source.parent
    target = out_dir / "{0}_加密.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    writer = pypdf.PdfWriter(clone_from=reader)
    writer.encrypt(
        user_password=user_pw,
        owner_password=owner_pw,
        permissions_flag=perms,
        algorithm=algorithm,
    )
    try:
        _safe_write_pdf(writer, target)

        detail = "已使用 {0} 算法加密文档（打印:{1} 复制:{2} 修改:{3} 批注:{4}）".format(
            algorithm,
            "允许" if allow_print else "禁止",
            "允许" if allow_copy else "禁止",
            "允许" if allow_modify else "禁止",
            "允许" if allow_annotate else "禁止",
        )
        return PdfToolOutcome(
            ok=True, outputs=[target], detail=detail, note=note_msg
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_decrypt(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """解除 PDF 的打开密码与编辑限制。"""
    import pypdf

    reader = _open_reader(source, options.get("password", ""))
    out_dir = output_dir or source.parent
    target = out_dir / "{0}_解密.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    try:
        writer = pypdf.PdfWriter(clone_from=reader)
        _safe_write_pdf(writer, target)

        note_msg = ""
        if not reader.is_encrypted:
            note_msg = "该文件本身未加密，已生成解密副本"

        return PdfToolOutcome(
            ok=True,
            outputs=[target],
            detail="已成功解除密码限制并输出未加密 PDF",
            note=note_msg,
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _tool_compress(
    source: Path,
    output_dir: Optional[Path],
    overwrite: bool,
    options: Dict[str, Any],
) -> PdfToolOutcome:
    """无损优化 PDF 体积。"""
    import pypdf

    reader = _open_reader(source, options.get("password", ""))
    before_size = source.stat().st_size

    out_dir = output_dir or source.parent
    target = out_dir / "{0}_压缩.pdf".format(source.stem)
    _check_target_conflict([target], overwrite)

    writer = pypdf.PdfWriter(clone_from=reader)
    writer.compress_identical_objects(
        remove_identicals=True, remove_orphans=True
    )

    for page in writer.pages:
        page.compress_content_streams()

    strip_meta = bool(options.get("strip_metadata", True))
    if strip_meta:
        # 清理 Producer 和 Creator 冗余项，保留业务属性
        orig_meta = dict(writer.metadata or {})
        cleaned_meta = {
            k: v
            for k, v in orig_meta.items()
            if k not in ("/Producer", "/Creator")
        }
        writer.metadata = None
        if cleaned_meta:
            writer.add_metadata(cleaned_meta)

    try:
        _safe_write_pdf(writer, target)
        after_size = target.stat().st_size

        before_kb = before_size / 1024.0
        after_kb = after_size / 1024.0
        saved_bytes = before_size - after_size
        saved_pct = (
            (saved_bytes / float(before_size)) * 100.0 if before_size > 0 else 0.0
        )

        detail = "{0:.1f} KB → {1:.1f} KB".format(before_kb, after_kb)
        note_msg = ""
        if saved_bytes > 0:
            detail += "（减少 {0:.1f}%）".format(saved_pct)
        else:
            detail += "（体积无显著变化）"
            note_msg = "该文件结构已高度优化，无损压缩收益有限"

        return PdfToolOutcome(
            ok=True, outputs=[target], detail=detail, note=note_msg
        )
    finally:
        try:
            reader.close()
        except Exception:
            pass


# --- 批量与调度层 ---


def expand_sources(
    sources: Sequence[Union[str, Path]], tool_id: Optional[str] = None
) -> List[Path]:
    """展开源路径列表：目录内按该工具允许的后缀收集一层，去重并保持顺序。"""
    spec = TOOL_SPEC_BY_ID.get(tool_id or "")
    accepts = spec.accepts if spec else (PDF_SUFFIXES + IMAGE_SUFFIXES)

    collected: List[Path] = []
    seen: Set[str] = set()

    for item in sources:
        p = Path(item).resolve()
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in accepts:
                    key = str(child).lower()
                    if key not in seen:
                        seen.add(key)
                        collected.append(child)
        elif p.is_file():
            key = str(p).lower()
            if key not in seen:
                seen.add(key)
                collected.append(p)
    return collected


def run_pdf_tool(
    tool_id: str,
    sources: Sequence[Union[str, Path]],
    *,
    output_dir: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    options: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[int, int, PdfToolRecord], None]] = None,
    cancel_token: Optional[Any] = None,
) -> PdfToolBatchResult:
    """PDF 工具箱主入口：执行单个工具或对多个源执行批处理。

    plural 工具（merge、images_to_pdf）整批聚合执行，产生 1 条汇总记录；
    单文件工具逐个源执行，单个失败记录错误码并不中断其余任务。
    """
    spec = TOOL_SPEC_BY_ID.get(tool_id)
    if not spec:
        raise PdfInputError(
            suggested_action="未知的 PDF 工具 ID「{0}」。可用工具：{1}。".format(
                tool_id, "、".join(TOOL_IDS)
            )
        )

    opts = dict(options or {})
    out_dir = Path(output_dir) if output_dir else None
    resolved_sources = [Path(s).resolve() for s in sources]

    batch = PdfToolBatchResult()
    total_count = 1 if spec.plural else len(resolved_sources)

    if total_count == 0:
        return batch

    # 整批单产物工具（merge / images_to_pdf）
    if spec.plural:
        if cancel_token and getattr(cancel_token, "is_cancelled", False):
            batch.cancelled = True
            return batch

        started = time.monotonic()
        primary_source = (
            resolved_sources[0] if resolved_sources else Path("未指定")
        )
        try:
            # 校验后缀合法性
            for s in resolved_sources:
                if not s.is_file():
                    raise PdfInputError(
                        suggested_action="文件不存在：{0}".format(s.name)
                    )
                if s.suffix.lower() not in spec.accepts:
                    raise PdfInputError(
                        suggested_action="文件格式不支持「{0}」：仅支持 {1}。".format(
                            s.name, "、".join(spec.accepts)
                        )
                    )

            if tool_id == TOOL_MERGE:
                outcome = _tool_merge(resolved_sources, out_dir, overwrite, opts)
            elif tool_id == TOOL_IMAGES_TO_PDF:
                outcome = _tool_images_to_pdf(
                    resolved_sources, out_dir, overwrite, opts
                )
            else:
                raise PdfInputError(
                    suggested_action="未实现的整批工具：{0}".format(tool_id)
                )

            elapsed = time.monotonic() - started
            rec = PdfToolRecord(
                tool=tool_id,
                source=primary_source,
                outputs=outcome.outputs,
                ok=True,
                reason="ok",
                detail=outcome.detail,
                elapsed_seconds=elapsed,
                position=1,
                note=outcome.note,
            )
        except DocToolError as exc:
            elapsed = time.monotonic() - started
            rec = PdfToolRecord(
                tool=tool_id,
                source=primary_source,
                ok=False,
                reason="error",
                detail=exc.suggested_action or exc.user_message,
                error_code=exc.code,
                elapsed_seconds=elapsed,
                position=1,
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            rec = PdfToolRecord(
                tool=tool_id,
                source=primary_source,
                ok=False,
                reason="internal_error",
                detail=repr(exc)[:300],
                error_code="E9000",
                elapsed_seconds=elapsed,
                position=1,
            )

        batch.records.append(rec)
        if on_progress:
            on_progress(1, 1, rec)
        return batch

    # 逐文件处理工具
    for idx, src in enumerate(resolved_sources, 1):
        if cancel_token and getattr(cancel_token, "is_cancelled", False):
            batch.cancelled = True
            break

        started = time.monotonic()
        try:
            if not src.is_file():
                raise PdfInputError(
                    suggested_action="文件不存在：{0}".format(src.name)
                )
            if src.suffix.lower() not in spec.accepts:
                raise PdfInputError(
                    suggested_action="文件类型不匹配「{0}」：需要 {1}。".format(
                        src.name, "、".join(spec.accepts)
                    )
                )

            if tool_id == TOOL_SPLIT:
                outcome = _tool_split(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_EXTRACT:
                outcome = _tool_extract(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_DELETE:
                outcome = _tool_delete(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_ROTATE:
                outcome = _tool_rotate(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_TO_IMAGES:
                outcome = _tool_to_images(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_TO_TEXT:
                outcome = _tool_to_text(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_WATERMARK:
                outcome = _tool_watermark(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_PAGE_NUMBERS:
                outcome = _tool_page_numbers(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_METADATA:
                outcome = _tool_metadata(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_ENCRYPT:
                outcome = _tool_encrypt(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_DECRYPT:
                outcome = _tool_decrypt(src, out_dir, overwrite, opts)
            elif tool_id == TOOL_COMPRESS:
                outcome = _tool_compress(src, out_dir, overwrite, opts)
            else:
                raise PdfInputError(
                    suggested_action="未知工具操作：{0}".format(tool_id)
                )

            elapsed = time.monotonic() - started
            rec = PdfToolRecord(
                tool=tool_id,
                source=src,
                outputs=outcome.outputs,
                ok=True,
                reason="ok",
                detail=outcome.detail,
                elapsed_seconds=elapsed,
                position=idx,
                note=outcome.note,
            )
        except DocToolError as exc:
            elapsed = time.monotonic() - started
            rec = PdfToolRecord(
                tool=tool_id,
                source=src,
                ok=False,
                reason="error",
                detail=exc.suggested_action or exc.user_message,
                error_code=exc.code,
                elapsed_seconds=elapsed,
                position=idx,
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            rec = PdfToolRecord(
                tool=tool_id,
                source=src,
                ok=False,
                reason="internal_error",
                detail=repr(exc)[:300],
                error_code="E9000",
                elapsed_seconds=elapsed,
                position=idx,
            )

        batch.records.append(rec)
        if on_progress:
            on_progress(idx, total_count, rec)

    return batch


# --- CLI 参数配置与解析适配 ---


def add_pdf_tool_arguments(parser: Any) -> None:
    """为 argparse 的 pdf 子命令注册所有参数。"""
    parser.add_argument(
        "tool",
        choices=list(TOOL_IDS),
        help="PDF 工具名称（{0}）".format("/".join(TOOL_IDS)),
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="待处理的文件或文件夹路径",
    )
    parser.add_argument(
        "--target-dir",
        default="",
        help="产物输出目录；缺省与源文件同级",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖同名输出文件",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="合并或图片转 PDF 时的自定义输出文件名",
    )

    # 选项参数
    parser.add_argument(
        "--pages",
        default="",
        help="页码选择（如 1-5,8 或 all）",
    )
    parser.add_argument(
        "--mode",
        choices=["each", "every-n", "range", "center", "tiled"],
        default="",
        help="拆分模式（each/every-n/range）或水印排版（center/tiled）",
    )
    parser.add_argument(
        "--every",
        type=int,
        default=1,
        help="拆分时每组页数（every-n 模式）",
    )
    parser.add_argument(
        "--ranges",
        default="",
        help="拆分时的页码范围（如 1-3,5-8）",
    )
    parser.add_argument(
        "--degrees",
        type=int,
        default=90,
        help="旋转角度（90/180/270）",
    )
    parser.add_argument(
        "--image-format",
        choices=["png", "jpg"],
        default="png",
        help="PDF 转图片格式（png/jpg）",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="PDF 转图片分辨率 DPI（36~600，默认 150）",
    )
    parser.add_argument(
        "--a4",
        action="store_true",
        help="图片转 PDF 时按 A4 版面缩放居中",
    )
    parser.add_argument(
        "--text",
        default="",
        help="水印文字内容",
    )
    parser.add_argument(
        "--font-size",
        type=float,
        default=0.0,
        help="文字大小（水印默认 48，页码默认 10）",
    )
    parser.add_argument(
        "--opacity",
        type=int,
        default=30,
        help="水印不透明度（1~100，默认 30，向白色减淡模拟）",
    )
    parser.add_argument(
        "--angle",
        type=float,
        default=45.0,
        help="水印旋转角度（默认 45°）",
    )
    parser.add_argument(
        "--color",
        default="",
        help="文字颜色十六进制代码（如 #ff0000）",
    )
    parser.add_argument(
        "--position",
        choices=[
            "bottom-center",
            "bottom-left",
            "bottom-right",
            "top-center",
            "top-left",
            "top-right",
        ],
        default="bottom-center",
        help="页码对齐位置（默认 bottom-center）",
    )
    parser.add_argument(
        "--format",
        choices=["n", "-n-", "n/N", "第n页", "第n页/共N页"],
        default="第n页/共N页",
        help="页码编号格式（默认「第n页/共N页」）",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="页码起始序号（默认 1）",
    )
    parser.add_argument(
        "--skip-first",
        action="store_true",
        help="添加页码时跳过第一页（封面）",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=24.0,
        help="页码页边距（默认 24 磅）",
    )
    parser.add_argument(
        "--user-password",
        default="",
        help="加密时的打开密码",
    )
    parser.add_argument(
        "--owner-password",
        default="",
        help="加密时的所有者/权限密码",
    )
    parser.add_argument(
        "--password",
        default="",
        help="读取已加密文档或解除密码时的密码",
    )
    parser.add_argument(
        "--allow-print",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="加密权限：是否允许打印（默认允许）",
    )
    parser.add_argument(
        "--allow-copy",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="加密权限：是否允许复制（默认禁止）",
    )
    parser.add_argument(
        "--allow-modify",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="加密权限：是否允许修改内容（默认禁止）",
    )
    parser.add_argument(
        "--allow-annotate",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="加密权限：是否允许批注与表单（默认禁止）",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="设置元数据：标题",
    )
    parser.add_argument(
        "--author",
        default=None,
        help="设置元数据：作者",
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="设置元数据：主题",
    )
    parser.add_argument(
        "--keywords",
        default=None,
        help="设置元数据：关键字",
    )
    parser.add_argument(
        "--strip-metadata",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="压缩时剥离冗余元数据（Producer/Creator，默认开启）",
    )


def pdf_options_from_args(args: Any) -> Dict[str, Any]:
    """从 CLI 解析出的 Namespace 转换为服务层可接受的 options 字典。"""
    opts: Dict[str, Any] = {}
    if getattr(args, "pages", None):
        opts["pages"] = args.pages
    if getattr(args, "mode", None):
        opts["mode"] = args.mode
    if getattr(args, "every", None) is not None:
        opts["every"] = args.every
    if getattr(args, "ranges", None):
        opts["ranges"] = args.ranges
    if getattr(args, "degrees", None) is not None:
        opts["degrees"] = args.degrees
    if getattr(args, "image_format", None):
        opts["image_format"] = args.image_format
    if getattr(args, "dpi", None) is not None:
        opts["dpi"] = args.dpi
    if getattr(args, "a4", False):
        opts["a4"] = args.a4
    if getattr(args, "text", None):
        opts["text"] = args.text
    if getattr(args, "font_size", 0.0) > 0:
        opts["font_size"] = args.font_size
    if getattr(args, "opacity", None) is not None:
        opts["opacity"] = args.opacity
    if getattr(args, "angle", None) is not None:
        opts["angle"] = args.angle
    if getattr(args, "color", None):
        opts["color"] = args.color
    if getattr(args, "position", None):
        opts["position"] = args.position
    if getattr(args, "format", None):
        opts["format"] = args.format
    if getattr(args, "start", None) is not None:
        opts["start"] = args.start
    if getattr(args, "skip_first", False):
        opts["skip_first"] = args.skip_first
    if getattr(args, "margin", None) is not None:
        opts["margin"] = args.margin
    if getattr(args, "user_password", None):
        opts["user_password"] = args.user_password
    if getattr(args, "owner_password", None):
        opts["owner_password"] = args.owner_password
    if getattr(args, "password", None):
        opts["password"] = args.password
    if getattr(args, "allow_print", None) is not None:
        opts["allow_print"] = args.allow_print
    if getattr(args, "allow_copy", None) is not None:
        opts["allow_copy"] = args.allow_copy
    if getattr(args, "allow_modify", None) is not None:
        opts["allow_modify"] = args.allow_modify
    if getattr(args, "allow_annotate", None) is not None:
        opts["allow_annotate"] = args.allow_annotate
    if getattr(args, "title", None) is not None:
        opts["title"] = args.title
    if getattr(args, "author", None) is not None:
        opts["author"] = args.author
    if getattr(args, "subject", None) is not None:
        opts["subject"] = args.subject
    if getattr(args, "keywords", None) is not None:
        opts["keywords"] = args.keywords
    if getattr(args, "strip_metadata", None) is not None:
        opts["strip_metadata"] = args.strip_metadata
    if getattr(args, "output_name", None):
        opts["output_name"] = args.output_name
    return opts
