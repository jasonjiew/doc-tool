# -*- coding: utf-8 -*-
"""文档互转服务：方向注册表、批量编排与结果模型。

本模块不碰 COM，也不碰 Qt：真正的 Word 调用在
``doc_tool.adapters.word_convert``，由 ``converter`` 参数注入，因此方向判定、
命名、覆盖策略与错误映射都能在没有 Word 的机器上测试。

**方向注册表**：每个转换方向（源族 × 转出格式）的全部静态信息收在
``DIRECTIONS`` 一张表里，``KINDS``/``KIND_LABELS``/输出后缀/Word mode/合法源
后缀/缺省方向等全部由它派生——新增方向只需加一行注册数据 + 一个后端函数，
不再散落多张平行清单。方向分三类后端：

- ``word``：直接调 Word COM（``word_mode`` 给出适配器模式）；
- Word 组合方向（``_WORD_COMPOSITES``）：先由本模块生成中间 HTML/DOCX（临时
  目录，不在用户目录留中间文件），再交 Word 或纯 Python 后端完成；
- 离线后端（``_OFFLINE_BACKENDS``）：纯 Python，不装 Word 也能用。

与「项目出稿」的关系：这里处理的是任意单个文件，不读也不写 ``project.yml``，
所以未打开项目时同样可用；出稿流程要附带 PDF，只要把本服务的
``convert_paths`` 挂到 pipeline 末尾即可。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from doc_tool.domain.errors import (
    ConversionTargetExistsError,
    DocToolError,
    PageRangeError,
    TextEncodingError,
    UnsupportedConversionError,
    WordConvertError,
    WordConvertOutputMissingError,
    WordConvertTimeoutError,
)

KIND_DOCX_TO_PDF = "docx_to_pdf"
KIND_PDF_TO_DOCX = "pdf_to_docx"
KIND_MARKDOWN_TO_DOCX = "markdown_to_docx"
KIND_HTML_TO_DOCX = "html_to_docx"
KIND_DOCX_TO_MARKDOWN = "docx_to_markdown"
KIND_DOCX_TO_HTML = "docx_to_html"
KIND_MARKDOWN_TO_HTML = "markdown_to_html"
KIND_HTML_TO_PDF = "html_to_pdf"
KIND_TXT_TO_PDF = "txt_to_pdf"
KIND_XLSX_TO_CSV = "xlsx_to_csv"
KIND_XLSX_TO_HTML = "xlsx_to_html"
KIND_XLSX_TO_PDF = "xlsx_to_pdf"
KIND_CSV_TO_XLSX = "csv_to_xlsx"
KIND_CSV_TO_PDF = "csv_to_pdf"
KIND_RTF_TO_PDF = "rtf_to_pdf"
KIND_RTF_TO_DOCX = "rtf_to_docx"
KIND_RTF_TO_MARKDOWN = "rtf_to_markdown"
KIND_RTF_TO_TXT = "rtf_to_txt"
KIND_ODT_TO_PDF = "odt_to_pdf"
KIND_ODT_TO_DOCX = "odt_to_docx"

# 源扩展名按族分组（小写、带点）；.doc 与 .docx 同属 Word 族。
DOC_SUFFIXES = (".docx", ".doc")
PDF_SUFFIXES = (".pdf",)
MARKDOWN_SUFFIXES = (".md", ".markdown")
HTML_SUFFIXES = (".html", ".htm")
TEXT_SUFFIXES = (".txt",)
XLSX_SUFFIXES = (".xlsx",)
CSV_SUFFIXES = (".csv",)
RTF_SUFFIXES = (".rtf",)
ODT_SUFFIXES = (".odt",)

# 转出格式标识：``--to``/对话框下拉的取值。
TARGET_PDF = "pdf"
TARGET_MARKDOWN = "md"
TARGET_DOCX = "docx"
TARGET_HTML = "html"
TARGET_TEXT = "txt"
TARGET_CSV = "csv"
TARGET_XLSX = "xlsx"


@dataclass(frozen=True)
class Direction:
    """一个转换方向（源族 × 转出格式）的全部静态信息。

    同一源族的多行靠 ``is_default`` 标出未显式给转出格式时的缺省方向；
    ``backend`` 取 ``word``、``markdown``（注入的 markdown_writer）或
    ``_WORD_COMPOSITES``/``_OFFLINE_BACKENDS`` 里的键。
    """

    kind: str
    label: str
    suffixes: Tuple[str, ...]
    target_format: str
    target_suffix: str
    backend: str = "word"
    word_mode: str = ""
    is_default: bool = False
    # 产物带 <名字>_assets 资源目录：参与输出覆盖预检，成功后给资源落点说明。
    markdown_assets: bool = False
    # 纯 Python 方向的看门狗估值（秒）；Word 方向走 word_mode、Word 组合方向按
    # _COMPOSITE_TIMEOUT_MODES 查适配器表，都轮不到这个值。
    offline_timeout: int = 120


DIRECTIONS = (
    Direction(
        KIND_DOCX_TO_PDF, "Word → PDF", DOC_SUFFIXES, TARGET_PDF, ".pdf",
        word_mode="docx_to_pdf", is_default=True,
    ),
    Direction(
        KIND_DOCX_TO_MARKDOWN, "Word → Markdown", DOC_SUFFIXES, TARGET_MARKDOWN, ".md",
        backend="markdown", markdown_assets=True,
    ),
    Direction(
        KIND_DOCX_TO_HTML, "Word → HTML", DOC_SUFFIXES, TARGET_HTML, ".html",
        backend="docx_to_html", markdown_assets=True,
    ),
    Direction(
        KIND_PDF_TO_DOCX, "PDF → Word", PDF_SUFFIXES, TARGET_DOCX, ".docx",
        word_mode="pdf_to_docx", is_default=True,
    ),
    Direction(
        KIND_MARKDOWN_TO_DOCX, "Markdown → Word", MARKDOWN_SUFFIXES, TARGET_DOCX, ".docx",
        backend="md_via_html", word_mode="html_to_docx", is_default=True,
    ),
    Direction(
        KIND_MARKDOWN_TO_HTML, "Markdown → HTML", MARKDOWN_SUFFIXES, TARGET_HTML, ".html",
        backend="markdown_to_html",
    ),
    Direction(
        KIND_HTML_TO_DOCX, "HTML → Word", HTML_SUFFIXES, TARGET_DOCX, ".docx",
        word_mode="html_to_docx", is_default=True,
    ),
    Direction(
        KIND_HTML_TO_PDF, "HTML → PDF", HTML_SUFFIXES, TARGET_PDF, ".pdf",
        word_mode="html_to_pdf",
    ),
    Direction(
        KIND_TXT_TO_PDF, "文本 → PDF", TEXT_SUFFIXES, TARGET_PDF, ".pdf",
        backend="text_to_pdf", is_default=True,
    ),
    Direction(
        KIND_XLSX_TO_CSV, "Excel → CSV", XLSX_SUFFIXES, TARGET_CSV, ".csv",
        backend="xlsx_to_csv", is_default=True,
    ),
    Direction(
        KIND_XLSX_TO_HTML, "Excel → HTML", XLSX_SUFFIXES, TARGET_HTML, ".html",
        backend="xlsx_to_html",
    ),
    Direction(
        KIND_XLSX_TO_PDF, "Excel → PDF", XLSX_SUFFIXES, TARGET_PDF, ".pdf",
        backend="table_to_pdf",
    ),
    Direction(
        KIND_CSV_TO_XLSX, "CSV → Excel", CSV_SUFFIXES, TARGET_XLSX, ".xlsx",
        backend="csv_to_xlsx", is_default=True,
    ),
    Direction(
        KIND_CSV_TO_PDF, "CSV → PDF", CSV_SUFFIXES, TARGET_PDF, ".pdf",
        backend="table_to_pdf",
    ),
    Direction(
        KIND_RTF_TO_PDF, "RTF → PDF", RTF_SUFFIXES, TARGET_PDF, ".pdf",
        word_mode="import_to_pdf", is_default=True,
    ),
    Direction(
        KIND_RTF_TO_DOCX, "RTF → Word", RTF_SUFFIXES, TARGET_DOCX, ".docx",
        word_mode="import_to_docx",
    ),
    Direction(
        KIND_RTF_TO_MARKDOWN, "RTF → Markdown", RTF_SUFFIXES, TARGET_MARKDOWN, ".md",
        backend="import_to_markdown", markdown_assets=True,
    ),
    Direction(
        KIND_RTF_TO_TXT, "RTF → 文本", RTF_SUFFIXES, TARGET_TEXT, ".txt",
        backend="import_to_text",
    ),
    Direction(
        KIND_ODT_TO_PDF, "ODT → PDF", ODT_SUFFIXES, TARGET_PDF, ".pdf",
        word_mode="import_to_pdf", is_default=True,
    ),
    Direction(
        KIND_ODT_TO_DOCX, "ODT → Word", ODT_SUFFIXES, TARGET_DOCX, ".docx",
        word_mode="import_to_docx",
    ),
)

DIRECTION_BY_KIND: Dict[str, Direction] = {row.kind: row for row in DIRECTIONS}

KINDS = tuple(DIRECTION_BY_KIND)

KIND_LABELS = {row.kind: row.label for row in DIRECTIONS}

_TARGET_SUFFIX = {row.kind: row.target_suffix for row in DIRECTIONS}

SUPPORTED_SUFFIXES = tuple(
    dict.fromkeys(
        suffix for row in DIRECTIONS for suffix in row.suffixes
    )
)

_ROWS_BY_SUFFIX: Dict[str, Tuple[Direction, ...]] = {
    suffix: tuple(row for row in DIRECTIONS if suffix in row.suffixes)
    for suffix in SUPPORTED_SUFFIXES
}

# 「转换为」下拉的取值与中文标签（按注册表首次出现顺序）。
TARGET_FORMATS = tuple(dict.fromkeys(row.target_format for row in DIRECTIONS))
TARGET_LABELS = {
    TARGET_PDF: "PDF",
    TARGET_MARKDOWN: "Markdown",
    TARGET_HTML: "HTML",
    TARGET_DOCX: "Word 文档",
    TARGET_TEXT: "纯文本 (TXT)",
    TARGET_CSV: "CSV",
    TARGET_XLSX: "Excel 工作簿",
}

# 需要调用本机 Word 的方向；其余方向纯 Python 完成。
WORD_MODE_BY_KIND = {
    row.kind: row.word_mode for row in DIRECTIONS if row.word_mode
}

# Word 组合方向内部真正调用的 Word 模式：超时按它查适配器表。组合方向比
# 单跳更重，绝不能落到纯 Python 的看门狗估值上——XLSX/CSV/TXT → PDF 内部走
# html_to_pdf（300s），RTF → Markdown/文本内部走 import_to_docx（300s），
# 曾因全按 offline_timeout（120s）取值，Word 还在排版就被判超时。
_COMPOSITE_TIMEOUT_MODES = {
    "md_via_html": "html_to_docx",
    "table_to_pdf": "html_to_pdf",
    "text_to_pdf": "html_to_pdf",
    "import_to_markdown": "import_to_docx",
    "import_to_text": "import_to_docx",
}

# Word 产出 DOCX 的方向：成功后做标题结构核验（可导入章节树的信号）。
DOCX_PRODUCING_KINDS = tuple(
    row.kind for row in DIRECTIONS
    if row.word_mode and row.target_suffix == ".docx"
)

# 产物带 assets 资源目录的方向（Word → Markdown 系）。
MARKDOWN_ASSETS_KINDS = tuple(row.kind for row in DIRECTIONS if row.markdown_assets)


def default_timeout_for(kind: str) -> int:
    """该方向的默认单文件超时（秒）。

    Word 方向必须先经注册表把 kind 翻译成适配器的 ``word_mode`` 再查超时表——
    直接拿 kind 查适配器会静默落到兜底值（``markdown_to_docx`` 曾因两套键名
    不一致误用 DOCX→PDF 的兜底超时，这里是从根上修掉那类错位）；Word 组合
    方向按内部实际调用的模式取值（见 ``_COMPOSITE_TIMEOUT_MODES``）。
    """
    from doc_tool.adapters.word_convert import default_timeout_seconds

    direction = DIRECTION_BY_KIND.get(kind)
    if direction is None:
        return default_timeout_seconds(kind)
    if direction.word_mode:
        return default_timeout_seconds(direction.word_mode)
    composite_mode = _COMPOSITE_TIMEOUT_MODES.get(direction.backend)
    if composite_mode is not None:
        return default_timeout_seconds(composite_mode)
    return direction.offline_timeout


PathLike = Union[str, Path]


@dataclass(frozen=True)
class ConversionPlan:
    """一个待转换文件的方向与落点。"""

    source: Path
    target: Path
    kind: str

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


@dataclass
class ConversionRecord:
    """单个文件的转换结论（含失败），供界面与 CLI 直接展示。"""

    source: Path
    target: Path
    kind: str
    ok: bool = False
    reason: str = ""
    detail: str = ""
    error_code: Optional[str] = None
    elapsed_seconds: float = 0.0
    note: str = ""
    # 源文件在本次输入列表中的下标：计划失败与实转结果靠它归位成输入顺序。
    position: int = 0

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def status(self) -> str:
        return "成功" if self.ok else "失败"

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "target": str(self.target),
            "kind": self.kind,
            "label": self.label,
            "ok": self.ok,
            "reason": self.reason,
            "detail": self.detail,
            "errorCode": self.error_code,
            "elapsedSeconds": round(self.elapsed_seconds, 2),
            "note": self.note,
        }


@dataclass
class OfflineOutcome:
    """离线/组合后端的通用结果对象，字段与批量层读取的鸭子类型协议对齐。"""

    ok: bool
    reason: str = "ok"
    detail: str = ""
    error_code: Optional[str] = None
    elapsed_seconds: float = 0.0
    images: int = 0
    complex_tables: int = 0


@dataclass
class ConvertBatchResult:
    """一次批量互转的汇总。"""

    records: List[ConversionRecord] = field(default_factory=list)
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
            return "已取消：完成 {0} 个，剩余文件未转换。".format(self.succeeded)
        if self.total == 0:
            return "没有可转换的文件。"
        text = "成功 {0} 个，失败 {1} 个。".format(self.succeeded, self.failed)
        codes = sorted(
            {record.error_code for record in self.records if record.error_code}
        )
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


def available_targets_for(source: PathLike) -> List[Tuple[str, str]]:
    suffix = Path(source).suffix.lower()
    rows = _ROWS_BY_SUFFIX.get(suffix, ())
    targets: List[Tuple[str, str]] = []
    seen = set()
    for row in rows:
        if suffix == ".doc" and row.target_format != TARGET_PDF:
            continue
        if row.target_format not in seen:
            seen.add(row.target_format)
            label = TARGET_LABELS.get(row.target_format, row.target_format.upper())
            targets.append((row.target_format, label))
    return targets


def default_target_for(source: PathLike) -> str:
    suffix = Path(source).suffix.lower()
    rows = _ROWS_BY_SUFFIX.get(suffix, ())
    for row in rows:
        if row.is_default:
            return row.target_format
    return TARGET_DOCX if suffix == ".pdf" else TARGET_PDF


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"



def validate_source_signature(path: PathLike) -> Tuple[bool, str]:
    """校验源文件特征头与声明的扩展名是否一致，防范伪装或严重损坏的文件。

    返回 (is_valid, error_message)。
    """
    path = Path(path)
    if not path.is_file():
        return False, f"源文件不存在或不是文件：{path}"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"无法读取源文件信息（{exc}）：{path.name}"
    if size == 0:
        return False, f"源文件为空文件（0 字节），无内容可转换：{path.name}"

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return False, f"不支持的文件扩展名：{suffix or '无扩展名'}"

    try:
        with open(str(path), "rb") as f:
            header = f.read(1024)
    except OSError as exc:
        return False, f"无法读取文件头部特征（{exc}）：{path.name}"

    # 1. 拦截伪装成文档的 Windows PE 可执行程序 (MZ)
    if header.startswith(b"MZ"):
        return False, f"检测到可执行程序二进制特征（MZ），拒绝转换伪装程序：{path.name}"

    # 2. Office OpenXML 格式 (.docx, .xlsx, .odt) 必须为 ZIP 容器且以 PK 开头
    if suffix in (".docx", ".xlsx", ".odt"):
        if header.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM")):
            return False, f"文件扩展名为 {suffix}，但实际为图片文件（伪装扩展名）：{path.name}"
        if size < 22 or not header.startswith(b"PK"):
            return False, f"文件扩展名为 {suffix}，但缺少合法的 ZIP 压缩包头部标识（PK）：{path.name}"

    # 3. PDF 格式在其前 1024 字节内必须包含 %PDF-
    elif suffix == ".pdf":
        if header.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM")):
            return False, f"文件扩展名为 .pdf，但实际为图片文件（伪装扩展名）：{path.name}"
        if size < 20 or b"%PDF-" not in header:
            return False, f"文件扩展名为 .pdf，但未检测到合法的 PDF 文件头标识（%PDF-）：{path.name}"

    # 4. RTF 格式
    elif suffix == ".rtf":
        if size < 10 or not header.lstrip().startswith(b"{\\rtf"):
            return False, f"文件扩展名为 .rtf，但缺少 RTF 格式头部标识（{{\\rtf）：{path.name}"

    # 5. Word 97-2003 复合文档 (.doc)
    elif suffix == ".doc":
        if size < 512 or not header.startswith(b"\xd0\xcf\x11\xe0"):
            return False, f"文件扩展名为 .doc，但缺少复合二进制文档（OLE2）头部标识：{path.name}"

    # 6. 纯文本与表格源不得为 ELF/Mach-O 二进制，非 UTF-16 时不得包含 NUL 二进制字符
    elif suffix in (".txt", ".md", ".markdown", ".csv", ".html", ".htm"):
        if header.startswith((b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe")):
            return False, f"文件扩展名为纯文本/数据格式，但检测到二进制程序文件头，拒绝转换：{path.name}"
        if not header.startswith((b"\xff\xfe", b"\xfe\xff")) and b"\x00" in header[:512]:
            return False, f"纯文本/数据文件检测到二进制空字符（NUL），可能是二进制文件伪装或已损坏：{path.name}"

    return True, ""

def error_resolution_guide(error_code: Optional[str], detail: str = "") -> Tuple[str, str]:
    guides = {
        "E6001": ("格式或方向不支持", "支持格式：Word (.docx/.doc)、PDF、Markdown、Excel (.xlsx)、CSV、HTML、TXT、RTF、ODT，源文件须非空且未伪装。"),
        "E6002": ("目标文件已存在", "请勾选「覆盖同名文件」或更换输出目录。"),
        "E6003": ("Word 转换失败", "请确认文档能在 Word 中正常打开、未被加密或锁定，且没有被其他程序占用。"),
        "E6004": ("转换超时", "请在高级选项「单文件超时」中调大超时秒数（如 300 或 600 秒）后重试。"),
        "E6005": ("产物文件未找到", "请检查磁盘写入权限及可用空间，确认未被安全软件拦截。"),
        "E6006": ("表格文件异常", "请使用 Excel 打开并另存为标准 .xlsx 或 .csv 后重试。"),
        "E6007": ("字符编码无法识别", "请用文本编辑器打开并另存为 UTF-8 编码后重试。"),
        "E6008": ("页范围参数错误", "请按「起始页-结束页」（如 1-5）或单页（如 3）填写。"),
        "E3001": ("未检测到 Microsoft Word", "Word 互转与组合方向需要本机安装并激活 Microsoft Word，或选用纯 Python 离线格式。"),
        "E1001": ("DOCX 文档格式损坏", "请确认文件扩展名为 .docx 且未被加密或损坏。"),
        "E7001": ("PDF 文档格式损坏", "请确认文件扩展名为 .pdf 且能正常打开；损坏文件请先修复后重试。"),
        "E5003": ("任务已取消", "转换任务已被用户主动中止。"),
    }
    if error_code and error_code in guides:
        return guides[error_code]
    det_lower = (detail or "").lower()
    if any(k in det_lower for k in ("0x800706be", "rpc", "1722")):
        return ("Word COM 服务崩溃", "系统 COM 服务无响应或异常，请在任务管理器关闭 WINWORD.EXE 进程后重试。")
    if any(k in det_lower for k in ("permission", "denied", "拒绝访问", "1005")):
        return ("文件访问受限", "请确认文件未被其他程序独占打开，且当前用户具备该目录写入权限。")
    if any(k in det_lower for k in ("utf-8", "codec", "decode", "gbk")):
        return ("编码解析异常", "源文本包含无法识别的特殊编码，请另存为标准 UTF-8 编码后再转换。")
    if any(k in det_lower for k in ("timeout", "timed out", "超时")):
        return ("处理超时", "文档处理耗时超过预设阈值，请拆分大文件或在高级选项中增加超时时间。")
    if any(k in det_lower for k in ("disk", "space", "空间")):
        return ("存储空间不足", "目标驱动器可用磁盘空间不足，请清理空间后重试。")
    if any(k in det_lower for k in ("busy", "occupied", "lock", "占用")):
        return ("文件占用锁定", "源文件正在被其他编辑器或 Office 占用，请关闭相关程序后重试。")
    if any(k in det_lower for k in ("path too long", "206", "超长", "filename too long")):
        return ("路径或文件名超长", "Windows 限制路径长度不能超过 260 个字符，请缩短输出目录或文件名称后重试。")
    return (detail or "转换异常", "请检查源文件是否损坏或被占用后重试。")


def detect_kind(source: PathLike, target_format: Optional[str] = None) -> str:
    """按扩展名（必要时加转出格式）判定转换方向。

    显式给出的 ``target_format`` 只在该源族存在对应方向时生效；否则回落到源族
    的缺省方向——「转换为」下拉因此可以对不相关的源保持无害（如选 PDF 时
    .pdf 源仍按缺省转回 Word）。旧版 .doc 只支持出 PDF，显式要求其他格式时
    直接拒绝并给出两跳路径。
    """
    suffix = Path(source).suffix.lower()
    rows = _ROWS_BY_SUFFIX.get(suffix)
    if rows is None:
        raise UnsupportedConversionError(
            suggested_action="不支持 {0!r}。可选类型：{1}。".format(
                suffix or "无扩展名",
                "、".join(SUPPORTED_SUFFIXES),
            ),
            details={"source": Path(source).name},
        )
    if suffix == ".doc" and target_format not in (None, TARGET_PDF):
        raise UnsupportedConversionError(
            suggested_action=(
                "旧版 .doc 仅支持转出 PDF；如需 Markdown/HTML 等其他格式，"
                "请先转成 .docx（RTF 可直接转 Word 后再导出）。"
            ),
            details={"source": Path(source).name},
        )
    row = None
    if target_format:
        row = next((item for item in rows if item.target_format == target_format), None)
    if row is None:
        row = next(item for item in rows if item.is_default)
    return row.kind


def target_for(
    source: PathLike, kind: str, output_dir: Optional[PathLike] = None
) -> Path:
    """计算输出路径：默认与源文件同目录，同名换扩展名。"""
    source = Path(source)
    suffix = _TARGET_SUFFIX.get(kind)
    if suffix is None:
        raise UnsupportedConversionError(details={"kind": str(kind)})
    directory = Path(output_dir) if output_dir else source.parent
    return directory / (source.stem + suffix)


def assets_dir_for(target: PathLike) -> Path:
    """Word → Markdown 系的资源目录（图片与复杂表格），与输出文件同级。"""
    target = Path(target)
    return target.parent / (target.stem + "_assets")


def parse_page_range(text: Optional[str]) -> Optional[Tuple[int, int]]:
    """解析「1-5」/「3」形式的页范围；空值返回 None，非法值抛 E6008。"""
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)|(\d+)", text)
    if match is None:
        raise PageRangeError(details={"value": text})
    if match.group(3):
        first = last = int(match.group(3))
    else:
        first, last = int(match.group(1)), int(match.group(2))
    if first < 1 or last < first:
        raise PageRangeError(details={"value": text})
    return (first, last)


def build_plan(
    source: PathLike,
    output_dir: Optional[PathLike] = None,
    overwrite: bool = False,
    target_format: Optional[str] = None,
    validate_signature: bool = False,
) -> ConversionPlan:
    """构造单个文件的转换计划，顺带做输入输出可用性预检。"""
    source = Path(source)
    kind = detect_kind(source, target_format)
    if not source.is_file():
        raise UnsupportedConversionError(
            suggested_action="源文件不存在或不是文件：{0}".format(source),
            details={"source": source.name},
        )
    if validate_signature:
        is_valid, err_msg = validate_source_signature(source)
        if not is_valid:
            raise UnsupportedConversionError(
                suggested_action=err_msg,
                details={"source": source.name},
            )
    if output_dir:
        out_p = Path(output_dir)
        if out_p.is_file():
            raise UnsupportedConversionError(
                suggested_action="指定的输出目录是一个已有文件，无法作为输出文件夹：{0}".format(out_p),
                details={"target": str(out_p)},
            )
        try:
            out_p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise UnsupportedConversionError(
                suggested_action="无法创建或访问输出目录：{0}".format(exc),
                details={"target": str(out_p)},
            )
    target = target_for(source, kind, output_dir)
    if target.exists() and not overwrite:
        raise ConversionTargetExistsError(details={"target": str(target)})
    if kind in MARKDOWN_ASSETS_KINDS:
        assets = assets_dir_for(target)
        if assets.exists() and not overwrite:
            raise ConversionTargetExistsError(
                suggested_action="资源目录已存在，勾选「覆盖同名文件」或改用其他输出目录。",
                details={"target": str(assets)},
            )
    return ConversionPlan(source=source, target=target, kind=kind)


def expand_sources(inputs: Iterable[PathLike]) -> List[Path]:
    """展开输入：目录按扩展名收集其中的可转换文件，文件原样保留。"""
    collected: List[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES:
                    collected.append(child)
            continue
        collected.append(path)
    return collected


def heading_level_counts(docx_path: PathLike) -> Dict[int, int]:
    """统计 DOCX 中各层级 Heading 段落数（PDF 还原质量的可信信号）。

    走的是应用自己的 OOXML 读取器，不依赖 Word：Word 写出的 ``.docx`` 在本机
    仍以明文落盘，只有 PDF 会被透明加密。
    """
    from lxml import etree

    from doc_tool.adapters.importer import _parse_heading_styles
    from doc_tool.domain.ooxml import OOXMLSecurityError, parse_xml_safe, read_docx_package

    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with read_docx_package(Path(docx_path)) as package:
            styles_xml = package.read("word/styles.xml")
            root = parse_xml_safe(package.read("word/document.xml"), "word/document.xml")
        style_to_level = _parse_heading_styles(styles_xml)
    except Exception:
        # 只是一条界面提示：任何读取/解析问题都降级成「未核验到」，
        # 不能让异常将一次已经成功的转换标成失败。
        return {}
    counts: Dict[int, int] = {}
    for style_ref in root.iter(w + "pStyle"):
        level = style_to_level.get(style_ref.get(w + "val"))
        if level:
            counts[int(level)] = counts.get(int(level), 0) + 1
    return counts


def structure_hint(docx_path: PathLike, kind: str = KIND_PDF_TO_DOCX) -> str:
    """产物 DOCX 的标题结构说明（面向用户，按方向措辞不同）。"""
    counts = heading_level_counts(docx_path)
    levels = "、".join("{0} 级 {1} 个".format(level, counts[level]) for level in sorted(counts))
    if kind != KIND_PDF_TO_DOCX:
        # Markdown / HTML / RTF 等导入方向：标题层级是我们自己写进去的，这里是落地核验。
        if not counts:
            return "产物未含 Heading 样式：源文件里没有标题结构，出稿后无法生成目录或导入章节树。"
        return "产物标题：{0}。".format(levels)
    if not counts:
        return (
            "未核验到标题样式：Word 的 PDF 重排会丢失标题层级，"
            "直接「新建项目」导入会因缺少 Heading 结构被拒，请先在 Word 中补标题样式。"
        )
    return "已识别标题：{0}。层级与原文的对应关系仍需人工复核。".format(levels)


def error_for_reason(reason: str, timeout_seconds: Optional[float] = None) -> DocToolError:
    """把适配器原因键映射为稳定错误码（与管线的 ``_refresh_error`` 同思路）。"""
    from doc_tool.adapters import word_convert

    if reason == word_convert.REASON_TIMEOUT:
        details = {} if timeout_seconds is None else {
            "timeoutSeconds": str(int(timeout_seconds))
        }
        return WordConvertTimeoutError(details=details)
    if reason == word_convert.REASON_WORD_UNAVAILABLE:
        from doc_tool.domain.errors import WordNotAvailableError

        return WordNotAvailableError()
    if reason == word_convert.REASON_OUTPUT_MISSING:
        return WordConvertOutputMissingError()
    return WordConvertError()


def _call_converter(
    converter, source, target, mode: str, timeout_seconds: float, with_toc: bool,
    page_range: Optional[Tuple[int, int]],
):
    """调 Word 转换器；页范围仅在给出时以关键字下传，兼容既有 5 参注入实现。"""
    if page_range is None:
        return converter(source, target, mode, timeout_seconds, with_toc)
    return converter(
        source, target, mode, timeout_seconds, with_toc, page_range=page_range
    )


def _markdown_to_docx_via_word(
    plan: ConversionPlan, timeout_seconds: float, converter, with_toc: bool
):
    """Markdown → Word：先渲染成带排版样式的 HTML 落临时目录，再交 Word 导入。"""
    import tempfile

    from doc_tool.application.markdown_word import markdown_to_word_html, read_markdown_text

    source = Path(plan.source)
    try:
        text = read_markdown_text(source)
    except TextEncodingError as exc:
        return OfflineOutcome(
            ok=False, reason="encoding_failed", error_code=exc.code,
            detail=exc.user_message + " " + exc.suggested_action,
        )
    document = markdown_to_word_html(text, source.parent, title=source.stem)
    with tempfile.TemporaryDirectory(prefix="doc-tool-md2docx-") as workspace:
        # 图片已在 HTML 里改写成绝对 file URI，因此 HTML 可以放心待在临时目录，
        # 不在用户目录里留任何中间文件。
        html_path = Path(workspace) / (source.stem + ".html")
        with open(str(html_path), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
        return _call_converter(
            converter, html_path, plan.target, WORD_MODE_BY_KIND[plan.kind],
            timeout_seconds, with_toc, None,
        )


def _markdown_to_html(plan: ConversionPlan) -> OfflineOutcome:
    """Markdown → 单文件 HTML：复用 Markdown→Word 的渲染器与排版样式。"""
    from doc_tool.application.markdown_word import (
        markdown_to_word_html, markdown_word_summary, read_markdown_text,
    )

    source = Path(plan.source)
    try:
        text = read_markdown_text(source)
    except TextEncodingError as exc:
        return OfflineOutcome(
            ok=False, reason="encoding_failed", error_code=exc.code,
            detail=exc.user_message + " " + exc.suggested_action,
        )
    document = markdown_to_word_html(text, source.parent, title=source.stem)
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(plan.target), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(document)
    return OfflineOutcome(
        ok=True,
        detail=markdown_word_summary(text) + "，已生成可在浏览器直接打开的 HTML",
    )


def _docx_to_html(plan: ConversionPlan) -> OfflineOutcome:
    """Word → HTML：离线导出 Markdown 与 assets 后渲染成单文件 HTML。

    Markdown 中间产物留在临时目录，不落用户目录；assets 目录直接写到最终
    位置（``assets_dir_for``），渲染出的图片链接即指向最终路径，HTML 与
    assets 目录一起拷走也不会丢图。
    """
    import tempfile

    from doc_tool.application.docx_markdown import docx_to_markdown
    from doc_tool.application.markdown_word import markdown_to_word_html

    source = Path(plan.source)
    target = Path(plan.target)
    final_assets = assets_dir_for(target)
    with tempfile.TemporaryDirectory(prefix="doc-tool-docx2html-") as workspace:
        md_path = Path(workspace) / (target.stem + ".md")
        outcome = docx_to_markdown(source, md_path, assets_dir=final_assets)
        if not outcome.ok:
            return outcome
        md_text = md_path.read_text(encoding="utf-8")
    document = markdown_to_word_html(md_text, base_dir=target.parent, title=target.stem)
    with open(str(target), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(document)
    outcome.detail = str(outcome.detail) + "；HTML 已生成（浏览器可直接打开）"
    return outcome


def _table_to_pdf_via_word(
    plan: ConversionPlan, timeout_seconds: float, converter, markdown_writer,
    with_toc: bool, page_range: Optional[Tuple[int, int]],
):
    """XLSX/CSV → PDF：openpyxl 渲染成 HTML，临时文件交 Word 导出。"""
    import tempfile

    from doc_tool.application.table_convert import (
        TableConvertError, book_to_word_html, read_table_book,
    )

    source = Path(plan.source)
    try:
        book = read_table_book(source)
    except (TableConvertError, TextEncodingError) as exc:
        # CSV 编码解不出是 E6007，不能折进 WordConvertError 的兜底。
        return _table_error_outcome(exc)
    document = book_to_word_html(book, title=source.stem)
    with tempfile.TemporaryDirectory(prefix="doc-tool-tbl2pdf-") as workspace:
        html_path = Path(workspace) / (source.stem + ".html")
        with open(str(html_path), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
        outcome = _call_converter(
            converter, html_path, plan.target, WORD_MODE_BY_KIND[KIND_HTML_TO_PDF],
            timeout_seconds, with_toc, page_range,
        )
    if getattr(outcome, "ok", False):
        outcome.detail = "{0}；{1}".format(book.summary(), outcome.detail)
    return outcome


def _text_to_pdf_via_word(
    plan: ConversionPlan, timeout_seconds: float, converter, markdown_writer,
    with_toc: bool, page_range: Optional[Tuple[int, int]],
):
    """TXT → PDF：编码探测读取后包成 HTML，临时文件交 Word 导出。"""
    import tempfile

    from doc_tool.domain.errors import TextEncodingError
    from doc_tool.application.text_convert import plain_text_to_word_html, read_text_file

    source = Path(plan.source)
    try:
        text = read_text_file(source)
    except TextEncodingError as exc:
        return OfflineOutcome(
            ok=False, reason="encoding_failed", error_code=exc.code,
            detail=exc.user_message + " " + exc.suggested_action,
        )
    document = plain_text_to_word_html(text, title=source.stem)
    with tempfile.TemporaryDirectory(prefix="doc-tool-txt2pdf-") as workspace:
        html_path = Path(workspace) / (source.stem + ".html")
        with open(str(html_path), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
        outcome = _call_converter(
            converter, html_path, plan.target, WORD_MODE_BY_KIND[KIND_HTML_TO_PDF],
            timeout_seconds, with_toc, page_range,
        )
    if getattr(outcome, "ok", False):
        lines = len(text.replace("\r\n", "\n").splitlines())
        outcome.detail = "文本 {0} 行；{1}".format(lines, outcome.detail)
    return outcome


def _import_to_markdown(
    plan: ConversionPlan, timeout_seconds: float, converter, markdown_writer, with_toc: bool,
    page_range: Optional[Tuple[int, int]],
):
    """RTF → Markdown：Word 先导入成临时 DOCX，再走离线 Markdown 导出。"""
    import tempfile

    source = Path(plan.source)
    with tempfile.TemporaryDirectory(prefix="doc-tool-rtf2md-") as workspace:
        docx_path = Path(workspace) / (source.stem + ".docx")
        word_outcome = _call_converter(
            converter, source, docx_path, WORD_MODE_BY_KIND[KIND_RTF_TO_DOCX],
            timeout_seconds, with_toc, None,
        )
        if not getattr(word_outcome, "ok", False):
            return word_outcome
        outcome = markdown_writer(docx_path, plan.target)
        if getattr(outcome, "ok", False):
            outcome.detail = "{0}；{1}".format(word_outcome.detail, outcome.detail)
        return outcome


def _import_to_text(
    plan: ConversionPlan, timeout_seconds: float, converter, markdown_writer, with_toc: bool,
    page_range: Optional[Tuple[int, int]],
):
    """RTF → 纯文本：Word 先导入成临时 DOCX，再离线抽取正文。"""
    import tempfile

    from doc_tool.application.text_convert import docx_to_text

    source = Path(plan.source)
    with tempfile.TemporaryDirectory(prefix="doc-tool-rtf2txt-") as workspace:
        docx_path = Path(workspace) / (source.stem + ".docx")
        word_outcome = _call_converter(
            converter, source, docx_path, WORD_MODE_BY_KIND[KIND_RTF_TO_DOCX],
            timeout_seconds, with_toc, None,
        )
        if not getattr(word_outcome, "ok", False):
            return word_outcome
        outcome = docx_to_text(docx_path, plan.target)
        if outcome.ok:
            outcome.detail = "{0}；{1}".format(word_outcome.detail, outcome.detail)
        return outcome


# Word 组合方向：本模块先生成中间文件，再交 Word 或离线后端完成。
# 统一签名 (plan, timeout, converter, markdown_writer, with_toc, page_range)。
_WORD_COMPOSITES = {
    "md_via_html": lambda plan, timeout, converter, writer, with_toc, page_range:
        _markdown_to_docx_via_word(plan, timeout, converter, with_toc),
    "table_to_pdf": _table_to_pdf_via_word,
    "text_to_pdf": _text_to_pdf_via_word,
    "import_to_markdown": _import_to_markdown,
    "import_to_text": _import_to_text,
}


def _xlsx_to_csv(plan: ConversionPlan) -> OfflineOutcome:
    from doc_tool.application.table_convert import (
        TableConvertError, read_table_book, write_book_csv,
    )

    try:
        book = read_table_book(Path(plan.source))
    except (TableConvertError, TextEncodingError) as exc:
        return _table_error_outcome(exc)
    detail = write_book_csv(book, Path(plan.target))
    return OfflineOutcome(ok=True, detail=detail)


def _csv_to_xlsx(plan: ConversionPlan) -> OfflineOutcome:
    from doc_tool.application.table_convert import (
        TableConvertError, read_table_book, write_rows_xlsx,
    )

    try:
        book = read_table_book(Path(plan.source))
    except (TableConvertError, TextEncodingError) as exc:
        return _table_error_outcome(exc)
    sheet = book.sheets[0]
    detail = write_rows_xlsx(sheet.rows, Path(plan.target), sheet.name)
    return OfflineOutcome(ok=True, detail=detail)


def _xlsx_to_html(plan: ConversionPlan) -> OfflineOutcome:
    from doc_tool.application.table_convert import (
        TableConvertError, book_to_word_html, read_table_book,
    )

    try:
        book = read_table_book(Path(plan.source))
    except (TableConvertError, TextEncodingError) as exc:
        return _table_error_outcome(exc)
    document = book_to_word_html(book, title=Path(plan.source).stem)
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(plan.target), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(document)
    return OfflineOutcome(
        ok=True, detail=book.summary() + "，已生成可在浏览器直接打开的 HTML"
    )


def _table_error_outcome(exc) -> OfflineOutcome:
    """把表格后端的结构化异常折算成批量层认识的失败结果。"""
    return OfflineOutcome(
        ok=False, reason="table_failed", error_code=exc.code,
        detail=exc.user_message + " " + exc.suggested_action,
    )


# 纯 Python 离线方向：(plan) → outcome。
_OFFLINE_BACKENDS = {
    "markdown_to_html": _markdown_to_html,
    "docx_to_html": _docx_to_html,
    "xlsx_to_csv": _xlsx_to_csv,
    "csv_to_xlsx": _csv_to_xlsx,
    "xlsx_to_html": _xlsx_to_html,
}


def _assets_note(target: Path, outcome) -> str:
    """Word → Markdown 系的资源落点说明；无资源时返回空串。"""
    images = int(getattr(outcome, "images", 0) or 0)
    complex_tables = int(getattr(outcome, "complex_tables", 0) or 0)
    parts = []
    if images:
        parts.append("图片 {0} 张".format(images))
    if complex_tables:
        parts.append("复杂表格 {0} 个（OOXML 资源）".format(complex_tables))
    if not parts:
        return ""
    return "资源已导出到 {0}/：{1}。Word 的图片显示尺寸未保留（通用 Markdown 不认该方言）。".format(
        assets_dir_for(target).name, "、".join(parts)
    )


def convert_paths(
    sources: Sequence[PathLike],
    output_dir: Optional[PathLike] = None,
    *,
    overwrite: bool = False,
    target_format: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    with_toc: bool = False,
    page_range: Optional[str] = None,
    converter: Optional[Callable[..., object]] = None,
    markdown_writer: Optional[Callable[[Path, Path], object]] = None,
    on_progress: Optional[Callable[[int, int, ConversionRecord], None]] = None,
    cancel_token=None,
) -> ConvertBatchResult:
    """批量互转，按方向注册表路由到 Word COM 或纯 Python 后端。

    - ``converter``：Word COM 后端（默认 ``word_convert.convert_document``），签名为
      ``(source, target, mode, timeout_seconds, with_toc)``；测试可注入假实现。
      页范围仅在显式给出时以 ``page_range`` 关键字下传。
    - ``markdown_writer``：Word → Markdown 后端（默认 ``docx_markdown.docx_to_markdown``），
      纯 Python，不需要本机 Word。
    - ``target_format``：``pdf``/``md``/``html`` 等（见 ``TARGET_FORMATS``），只对
      存在该方向的源族生效，否则回落源族缺省方向。
    - ``page_range``：「1-5」/「3」，仅对 PDF 导出方向生效；非法值整批按 E6008 失败。
    - ``timeout_seconds`` 留空表示按每个文件的方向取默认值。

    单个文件失败不中断整批：每个文件各自记录结果与错误码，便于一次投递整摞
    文档后只重试失败项。
    """
    if converter is None:
        from doc_tool.adapters.word_convert import convert_document

        converter = convert_document
    if markdown_writer is None:
        from doc_tool.application.docx_markdown import docx_to_markdown

        markdown_writer = docx_to_markdown

    try:
        page_span = parse_page_range(page_range)
    except DocToolError as exc:
        # 页范围是整批参数：非法时逐文件落结构化失败，保持批量结果形状稳定。
        result = ConvertBatchResult()
        for position, source in enumerate(sources):
            result.records.append(
                ConversionRecord(
                    source=Path(source), target=Path(""), kind="",
                    position=position, ok=False, reason="planned_failed",
                    detail=exc.user_message + " " + exc.suggested_action,
                    error_code=exc.code,
                )
            )
        return result

    result = ConvertBatchResult()
    total = max(len(sources), 1)
    done = 0
    plans: List[tuple] = []
    ordered: Dict[int, ConversionRecord] = {}
    claimed: Dict[Path, str] = {}

    def _report(record: ConversionRecord) -> None:
        nonlocal done
        ordered[record.position] = record
        done += 1
        if on_progress is not None:
            on_progress(done, total, record)

    for position, source in enumerate(sources):
        path = Path(source)
        kind = ""
        target = Path("")
        try:
            if isinstance(target_format, dict):
                try:
                    resolved_path = path.resolve()
                except (OSError, RuntimeError):
                    resolved_path = path
                item_tf = (
                    target_format.get(path)
                    or target_format.get(str(path))
                    or target_format.get(resolved_path)
                    or target_format.get(str(resolved_path))
                )
            else:
                item_tf = target_format
            kind = detect_kind(path, item_tf)
            target = target_for(path, kind, output_dir)
            plan = build_plan(path, output_dir, overwrite, item_tf)
            # 同批次里两个源不能落到同一个输出：a.doc 与 a.docx 都指向 a.pdf 时，
            # 后一个会静默覆盖前一个的产物。
            try:
                resolved_target = plan.target.resolve()
            except (OSError, RuntimeError):
                resolved_target = plan.target
            owner = claimed.get(resolved_target)
            if owner is not None:
                raise ConversionTargetExistsError(
                    suggested_action="与同批次的 {0} 输出同名，请去掉其中一个或分开转换。".format(
                        Path(owner).name
                    ),
                    details={"target": str(plan.target)},
                )
        except DocToolError as exc:
            _report(
                ConversionRecord(
                    source=path,
                    target=target,
                    kind=kind,
                    position=position,
                    ok=False,
                    reason="planned_failed",
                    detail=exc.user_message + " " + exc.suggested_action,
                    error_code=exc.code,
                )
            )
            continue
        claimed[plan.target.resolve()] = str(plan.source)
        plans.append((position, plan))

    for position, plan in plans:
        if cancel_token is not None and cancel_token.is_cancelled:
            result.cancelled = True
            break
        direction = DIRECTION_BY_KIND[plan.kind]
        effective_timeout = (
            float(timeout_seconds)
            if timeout_seconds
            else float(default_timeout_for(plan.kind))
        )
        try:
            if direction.backend == "word":
                outcome = _call_converter(
                    converter, plan.source, plan.target, direction.word_mode,
                    effective_timeout, with_toc, page_span
                    if direction.target_suffix == ".pdf" else None,
                )
            elif direction.backend == "markdown":
                outcome = markdown_writer(plan.source, plan.target)
            elif direction.backend in _WORD_COMPOSITES:
                outcome = _WORD_COMPOSITES[direction.backend](
                    plan, effective_timeout, converter, markdown_writer,
                    with_toc, page_span if direction.target_suffix == ".pdf" else None,
                )
            else:
                outcome = _OFFLINE_BACKENDS[direction.backend](plan)
        except Exception as exc:  # 后端意外异常（源被删、产物被占用等）：落成单文件失败，不拖垮整批
            outcome = None
            crash_record = ConversionRecord(
                source=plan.source,
                target=plan.target,
                kind=plan.kind,
                position=position,
                ok=False,
                reason="convert_failed",
                detail=repr(exc)[:300],
                error_code=WordConvertError.code,
            )
        else:
            crash_record = None
        if crash_record is not None:
            _report(crash_record)
            continue
        ok = bool(getattr(outcome, "ok", False))
        reason = str(getattr(outcome, "reason", "") or "")
        provided_code = getattr(outcome, "error_code", None)
        record = ConversionRecord(
            source=plan.source,
            target=plan.target,
            kind=plan.kind,
            position=position,
            ok=ok,
            reason=reason,
            detail=str(getattr(outcome, "detail", "") or ""),
            elapsed_seconds=float(getattr(outcome, "elapsed_seconds", 0.0) or 0.0),
            error_code=(
                None
                if ok
                else (
                    str(provided_code)
                    if provided_code
                    else error_for_reason(reason, effective_timeout).code
                )
            ),
        )
        if ok and direction.word_mode and direction.target_suffix == ".docx":
            record.note = structure_hint(plan.target, plan.kind)
        elif ok and direction.markdown_assets:
            record.note = _assets_note(plan.target, outcome)
        _report(record)
    result.records = [ordered[position] for position in sorted(ordered)]
    return result
