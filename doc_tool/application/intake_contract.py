# -*- coding: utf-8 -*-
"""主流程契约：导入计划、策略、章节范围与统一出稿最小模型（CORE-A 1.2）。

本模块只定义**跨批次共享的最小模型与默认策略适配**，不含 GUI、不调用 Word：

- ``IntakePolicy``：普通/严格策略，负责适配既有
  ``ImportRequest`` 的旧标志（``ignore_roundtrip_block`` /
  ``require_exact_roundtrip`` / ``allow_missing_headings``）。
- ``PlannedTarget``：文档名/目录/编号/版本的默认值决定，附一行摘要。
- ``HeadingDecision`` / ``SectionCandidate``：章节识别与范围决定，保证
  “预览调整”与“最终提取”使用同一份决定（1.2 / 4.1）。
- ``PreservationFinding``：复杂内容处理事实（3.1-3.4 复用）。
- ``IntakePlan``：一次导入的完整计划，可序列化、可预览、可核对。
- ``ExportScope`` / ``SOURCE_MODE_*`` / ``FORMAT_*`` / ``ExportRequest`` /
  ``FormatResult``：固定 scope/sourceMode/captureId 契约，供 CORE-E/F 复用。

设计约束（design.md D2/D5/D6）：普通模式不以内容损失严重程度作为强制确认门槛；
只有源不可解析、无有效项目或无可用产物时才判定失败。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --- 策略 -------------------------------------------------------------------

POLICY_NORMAL = "normal"
POLICY_STRICT = "strict"

#: 处理事实的严重程度（不直接等于是否阻断）。
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_BLOCK = "block"

_SEVERITY_ORDER = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_BLOCK: 2}

# --- 处理方式（原件账本用词，界面按此措辞展示） -----------------------------

HANDLING_EDITABLE = "editable"              #: 可编辑保留（已进入正文）
HANDLING_TEXT_FALLBACK = "text-fallback"    #: 参考文本降级（读了文本，丢了结构）
HANDLING_ORIGINAL_ONLY = "original-only"     #: 原件留存（正文只有占位）
HANDLING_PLACEHOLDER = "placeholder"        #: 缺资源占位（图片/资源不可读）
HANDLING_SKIPPED = "skipped"                #: 未执行（本轮未处理，原因需说明）

# --- 来源模式 ---------------------------------------------------------------

SOURCE_MODE_CURRENT_BUFFER = "current-buffer"
SOURCE_MODE_SAVED = "saved"
SOURCE_MODES = (SOURCE_MODE_CURRENT_BUFFER, SOURCE_MODE_SAVED)

# --- 出稿范围 ---------------------------------------------------------------

SCOPE_PROJECT = "project"
SCOPE_CURRENT_CHAPTER = "current-chapter"
SCOPE_CHAPTERS = "chapters"
SCOPE_KINDS = (SCOPE_PROJECT, SCOPE_CURRENT_CHAPTER, SCOPE_CHAPTERS)

# --- 出稿格式 ---------------------------------------------------------------

FORMAT_DOCX = "docx"
FORMAT_PDF = "pdf"
FORMAT_HTML = "html"
FORMAT_SOURCE_ZIP = "source-zip"
FORMATS = (FORMAT_DOCX, FORMAT_PDF, FORMAT_HTML, FORMAT_SOURCE_ZIP)
FORMAT_ALIASES = {
    "word": FORMAT_DOCX,
    "doc": FORMAT_DOCX,
    "离线html": FORMAT_HTML,
    "离线-html": FORMAT_HTML,
    "html-offline": FORMAT_HTML,
    "zip": FORMAT_SOURCE_ZIP,
    "source": FORMAT_SOURCE_ZIP,
    "源码包": FORMAT_SOURCE_ZIP,
    "源码zip": FORMAT_SOURCE_ZIP,
}


def normalize_format(value: str) -> str:
    """把用户/CLI 写法归一为 FORMATS 中的规范名；未知值原样返回。"""
    text = str(value or "").strip().lower()
    if text in FORMATS:
        return text
    return FORMAT_ALIASES.get(text, text)


def normalize_formats(values: Iterable[str]) -> List[str]:
    """归一化格式列表：保序、去重。"""
    result: List[str] = []
    for item in values or ():
        name = normalize_format(item)
        if name and name not in result:
            result.append(name)
    return result


# --- 格式结果状态 -----------------------------------------------------------

STATUS_READY = "ready"                        #: 已生成可打开产物
STATUS_PENDING_REFRESH = "pending-refresh"    #: 可读稿已有，字段/页码待刷新
STATUS_PENDING_CONVERT = "pending-convert"    #: 待转换（如缺 Word 的 PDF）
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_SKIPPED = "skipped"

#: 视为“有可用产物”的状态：可打开、可交付。
USABLE_STATUSES = (STATUS_READY, STATUS_PENDING_REFRESH, STATUS_PENDING_CONVERT)


# --- 通用工具 ---------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_capture_id() -> str:
    """生成一次内容捕获的稳定标识（时间前缀便于人工排序）。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return "{0}-{1}".format(stamp, uuid.uuid4().hex[:8])


def new_round_id() -> str:
    """生成一轮出稿的标识（与 captureId 同源但独立，便于重试区分）。"""
    return "r-" + uuid.uuid4().hex[:10]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


def sanitize_name_part(value: str) -> str:
    """清理 Windows 非法文件名字符；保留中文与常规符号。"""
    cleaned = "".join(
        "_" if char in _INVALID_FILENAME_CHARS or ord(char) < 32 else char
        for char in str(value or "")
    )
    return cleaned.strip().rstrip(" .")


def default_document_name(source: Path, trusted_name: str = "") -> str:
    """可信元数据名称优先，否则用文件名（去扩展名）；清理非法字符。"""
    candidate = sanitize_name_part(trusted_name)
    if not candidate:
        candidate = sanitize_name_part(Path(source).stem)
    return candidate or "未命名文档"


def unique_directory(parent: Path, name: str) -> Path:
    """在 parent 下取未占用的目录（同名自动后缀 -2、-3）。"""
    parent = Path(parent)
    base = sanitize_name_part(name) or "未命名文档"
    candidate = parent / base
    index = 2
    while candidate.exists():
        candidate = parent / "{0}-{1}".format(base, index)
        index += 1
    return candidate


def resolve_export_directory(
    preferred: Optional[Path],
    fallbacks: Sequence[Optional[Path]],
) -> Tuple[Path, Optional[str]]:
    """返回第一个可写的导出目录，以及回退说明（未回退时为 None）。

    目录失效或不可写时按顺序回退；调用方负责保留用户已选的输入与格式。
    """
    candidates: List[Optional[Path]] = [preferred]
    candidates.extend(fallbacks)
    first = True
    for candidate in candidates:
        if candidate is None:
            first = False
            continue
        try:
            path = Path(candidate)
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".doctool-write-probe"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError:
            first = False
            continue
        if first:
            return path, None
        return path, "原导出目录不可用，已改用 {0}".format(path)
    raise OSError("没有可写的导出目录，请选择新的目录。")


def fresh_output_path(path: Path, protected: Iterable[Path] = ()) -> Path:
    """同名冲突采用可辨识的新文件名（name-2.docx），不覆盖已有结果。"""
    path = Path(path)
    blocked = {Path(item).resolve() for item in protected if item is not None}
    base = path
    index = 2
    while path.exists() or path.resolve() in blocked:
        path = base.with_name("{0}-{1}{2}".format(base.stem, index, base.suffix))
        index += 1
    return path


def relative_display(path: Path, root: Optional[Path]) -> str:
    """尽量给出相对项目根的展示路径；失败退回文件名。"""
    if root is None:
        return Path(path).name
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).name


# --- 策略 -------------------------------------------------------------------


@dataclass
class IntakePolicy:
    """导入策略：普通模式默认给可用项目，严格模式按阈值拒绝发布。"""

    mode: str = POLICY_NORMAL
    allow_missing_headings: bool = True
    block_severity: str = SEVERITY_BLOCK
    strict_min_severity: str = SEVERITY_WARNING

    def __post_init__(self) -> None:
        if self.mode not in (POLICY_NORMAL, POLICY_STRICT):
            self.mode = POLICY_NORMAL
        if self.mode == POLICY_STRICT:
            # 严格模式：往返差异与警告级缺口都进入门禁，且不再放行无标题。
            self.allow_missing_headings = False

    @property
    def is_strict(self) -> bool:
        return self.mode == POLICY_STRICT

    @classmethod
    def normal(cls) -> "IntakePolicy":
        return cls(mode=POLICY_NORMAL)

    @classmethod
    def strict(cls) -> "IntakePolicy":
        return cls(mode=POLICY_STRICT)

    def to_legacy_flags(self) -> Dict[str, bool]:
        """适配既有 ImportRequest 标志（不能成为 UI 隐藏状态）。"""
        return {
            "allow_missing_headings": bool(self.allow_missing_headings),
            "ignore_roundtrip_block": not self.is_strict,
            "require_exact_roundtrip": bool(self.is_strict),
        }

    @classmethod
    def from_legacy_flags(
        cls,
        *,
        ignore_roundtrip_block: bool,
        require_exact_roundtrip: bool,
        allow_missing_headings: bool,
    ) -> "IntakePolicy":
        strict = bool(require_exact_roundtrip) and not bool(ignore_roundtrip_block)
        policy = cls(mode=POLICY_STRICT if strict else POLICY_NORMAL)
        if not strict:
            policy.allow_missing_headings = bool(allow_missing_headings)
        return policy

    def should_block(self, findings: Sequence["PreservationFinding"]) -> Tuple[bool, str]:
        """按策略判断是否阻止发布新项目；返回 (blocked, reason)。"""
        if not self.is_strict:
            return False, ""
        threshold = _SEVERITY_ORDER.get(self.strict_min_severity, 1)
        offenders = [
            item for item in findings
            if _SEVERITY_ORDER.get(item.severity, 0) >= threshold
        ]
        if not offenders:
            return False, ""
        return True, "严格模式命中 {0} 项内容问题（阈值：{1}）".format(
            len(offenders), self.strict_min_severity
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "IntakePolicy":
        data = data or {}
        return cls(
            mode=str(data.get("mode") or POLICY_NORMAL),
            allow_missing_headings=bool(data.get("allow_missing_headings", True)),
            block_severity=str(data.get("block_severity") or SEVERITY_BLOCK),
            strict_min_severity=str(data.get("strict_min_severity") or SEVERITY_WARNING),
        )


# --- 目标 -------------------------------------------------------------------


@dataclass
class PlannedTarget:
    """拟建项目的名称与位置决定，每一项都有一行来源说明。"""

    directory: str = ""
    document_name: str = ""
    document_no: str = ""
    document_version: str = ""
    document_type: str = "general"
    name_source: str = "文件名"
    directory_source: str = "默认目录"
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = ["名称：{0}（{1}）".format(self.document_name, self.name_source)]
        parts.append("位置：{0}（{1}）".format(self.directory, self.directory_source))
        parts.append("编号：{0}".format(self.document_no or "（空）"))
        parts.append("版本：{0}".format(self.document_version or "（空）"))
        return "；".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlannedTarget":
        data = data or {}
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# --- 章节决定 ---------------------------------------------------------------


@dataclass
class HeadingDecision:
    """一条标题识别决定：明确样式与弱推断候选分开记录。"""

    title: str
    level: int = 1
    style_id: str = ""
    source: str = "style"        #: style / outline / heuristic / single-chapter
    action: str = "kept"         #: kept / remapped / flattened / promoted / single
    confidence: float = 1.0
    note: str = ""
    source_index: int = 0

    @property
    def is_weak(self) -> bool:
        return self.source in ("heuristic", "single-chapter") or self.confidence < 0.6

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeadingDecision":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class SectionCandidate:
    """一个可勾选的导入章节（含祖先结构与依赖说明）。"""

    chapter_id: str
    title: str
    level: int = 1
    parent_id: str = ""
    order: int = 0
    selected: bool = True
    required_by_selection: bool = False
    dependency_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SectionCandidate":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# --- 处理事实 ---------------------------------------------------------------


@dataclass
class PreservationFinding:
    """复杂内容/缺资源的一条处理事实（导入记录与结果页共用）。"""

    feature: str                      #: formula / footnote / textbox / revision / comment / image / table ...
    handling: str = HANDLING_ORIGINAL_ONLY
    editable: bool = False
    severity: str = SEVERITY_WARNING
    source_part: str = ""             #: 源部件，如 word/document.xml
    element_index: Optional[int] = None
    retained_path: str = ""           #: 原件位置（项目相对路径优先）
    target_chapter: str = ""          #: 能映射到的目标章节
    target_line: Optional[int] = None
    detail: str = ""
    action: str = ""                  #: 直接动作提示（定位/查原件/替换图片）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreservationFinding":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def data_sort_key(self) -> Tuple[str, int]:
        return (self.target_chapter or "", self.target_line or 0)

    @property
    def kind_label(self) -> str:
        return FEATURE_LABELS.get(self.feature, self.feature or "复杂内容")

    @property
    def handling_label(self) -> str:
        return HANDLING_LABELS.get(self.handling, self.handling or "未处理")


FEATURE_LABELS = {
    "formula": "公式",
    "footnote": "脚注",
    "endnote": "尾注",
    "textbox": "文本框",
    "revision": "修订",
    "comment": "批注",
    "image": "图片",
    "table": "复杂表格",
    "field": "域/目录",
    "object": "嵌入对象",
    "placeholder": "占位",
}

HANDLING_LABELS = {
    HANDLING_EDITABLE: "可编辑保留",
    HANDLING_TEXT_FALLBACK: "参考文本降级",
    HANDLING_ORIGINAL_ONLY: "原件留存",
    HANDLING_PLACEHOLDER: "占位提醒",
    HANDLING_SKIPPED: "未执行",
}

#: 默认最多直接展开的可行动问题数（U-7 / 3.3）。
DEFAULT_ACTIONABLE_LIMIT = 3

#: 缺图占位在正文中的可识别前缀（导出与源码包据此保留缺口位置）。
PLACEHOLDER_PREFIX = "[["
PLACEHOLDER_TEMPLATE = "[[待完善：{0}｜来源：{1}]]"


def placeholder_text(feature: str, source: str = "") -> str:
    """生成正文可见占位；不伪造页码、不执行嵌入对象。"""
    return PLACEHOLDER_TEMPLATE.format(
        FEATURE_LABELS.get(feature, feature or "复杂内容"),
        source or "原件",
    )


def is_placeholder_line(line: str) -> bool:
    return PLACEHOLDER_PREFIX in (line or "")


# --- 导入计划 ---------------------------------------------------------------


@dataclass
class IntakePlan:
    """一次导入的完整计划（预览、提取、结果页共用同一份决定）。"""

    source: str = ""
    sourceHash: str = ""
    sourceKind: str = "docx"          #: docx / doc / markdown
    documentType: str = "general"
    policy: IntakePolicy = field(default_factory=IntakePolicy.normal)
    target: PlannedTarget = field(default_factory=PlannedTarget)
    headingDecisions: List[HeadingDecision] = field(default_factory=list)
    sections: List[SectionCandidate] = field(default_factory=list)
    preservationFindings: List[PreservationFinding] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unavailableComparisons: List[str] = field(default_factory=list)
    mappingPresetId: str = ""
    mappingMatched: List[str] = field(default_factory=list)
    mappingUnmatched: List[str] = field(default_factory=list)
    strictBlocked: bool = False
    strictReason: str = ""
    createdAt: str = field(default_factory=utc_now_iso)

    # --- 范围 ---

    def ordered_sections(self) -> List[SectionCandidate]:
        """按源文档顺序返回章节（不按点击顺序）。"""
        return sorted(self.sections, key=lambda item: item.order)

    def selected_sections(self) -> List[SectionCandidate]:
        return [item for item in self.ordered_sections() if item.selected]

    def scope_is_full(self) -> bool:
        return all(item.selected for item in self.sections) if self.sections else True

    def apply_selection(
        self,
        selected_ids: Iterable[str],
        *,
        include_ancestors: bool = True,
    ) -> List[str]:
        """设置选中章节，自动补入祖先结构；返回被依赖补入的章节 id。"""
        wanted = {str(item) for item in selected_ids}
        by_id = {item.chapter_id: item for item in self.sections}
        added: List[str] = []
        if include_ancestors:
            pending = list(wanted)
            while pending:
                current = pending.pop()
                parent_id = by_id.get(current).parent_id if by_id.get(current) else ""
                if parent_id and parent_id not in wanted:
                    wanted.add(parent_id)
                    added.append(parent_id)
                    pending.append(parent_id)
        for item in self.sections:
            item.selected = item.chapter_id in wanted
            item.required_by_selection = item.chapter_id in added
            if item.required_by_selection and not item.dependency_note:
                item.dependency_note = "作为所选章节的上级结构保留"
        return added

    # --- 缺口 ---

    def actionable_findings(self, limit: int = DEFAULT_ACTIONABLE_LIMIT) -> List[PreservationFinding]:
        """默认最多展开若干条有直接行动价值的问题（U-7）。"""
        ordered = sorted(
            self.preservationFindings,
            key=lambda item: (-_SEVERITY_ORDER.get(item.severity, 0), item.data_sort_key()),
        )
        return ordered[: max(0, int(limit))]

    def gap_counts(self) -> Dict[str, int]:
        """按处理方式统计，供结果页“N 项待完善 / M 项已自动处理”。"""
        counts: Dict[str, int] = {}
        for item in self.preservationFindings:
            counts[item.handling] = counts.get(item.handling, 0) + 1
        return counts

    def to_fix_count(self) -> int:
        return sum(
            1 for item in self.preservationFindings
            if item.handling in (
                HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER,
                HANDLING_TEXT_FALLBACK, HANDLING_SKIPPED,
            )
        )

    def auto_handled_count(self) -> int:
        return sum(
            1 for item in self.preservationFindings
            if item.handling == HANDLING_EDITABLE
        )

    # --- 展示 ---

    def summary_lines(self, max_actions: int = DEFAULT_ACTIONABLE_LIMIT) -> List[str]:
        """结果页/CLI 的稳定摘要行（先给可用结果，再列待完善）。"""
        lines: List[str] = []
        selected = self.selected_sections()
        top_level = [item for item in selected if item.level <= 1]
        chapter_count = len(top_level) or len(selected) or 1
        lines.append("将创建 {0} 个章节的可编辑项目（{1}）".format(
            chapter_count,
            "整份" if self.scope_is_full() else "部分范围",
        ))
        if self.target.document_name:
            lines.append(self.target.summary())
        to_fix = self.to_fix_count()
        if to_fix:
            lines.append("{0} 处内容待完善，{1} 项已自动处理".format(to_fix, self.auto_handled_count()))
        actions = self.actionable_findings(max_actions)
        for item in actions:
            where = item.target_chapter or item.source_part or "正文"
            lines.append(
                "· {0}：{1}（{2}）{3}".format(
                    item.kind_label, item.handling_label, where,
                    ("｜" + item.action) if item.action else "",
                )
            )
        remaining = len(self.preservationFindings) - len(actions)
        if remaining > 0:
            lines.append("其余 {0} 项见详情".format(remaining))
        for warning in self.warnings:
            lines.append("提醒：{0}".format(warning))
        for missing in self.unavailableComparisons:
            lines.append("对照未完成：{0}".format(missing))
        if self.strictBlocked:
            lines.append("严格模式未通过：{0}".format(self.strictReason))
        return lines

    # --- 序列化 ---

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": 1,
            "source": self.source,
            "sourceHash": self.sourceHash,
            "sourceKind": self.sourceKind,
            "documentType": self.documentType,
            "policy": self.policy.to_dict(),
            "target": self.target.to_dict(),
            "headingDecisions": [item.to_dict() for item in self.headingDecisions],
            "sections": [item.to_dict() for item in self.sections],
            "preservationFindings": [item.to_dict() for item in self.preservationFindings],
            "warnings": list(self.warnings),
            "unavailableComparisons": list(self.unavailableComparisons),
            "mappingPresetId": self.mappingPresetId,
            "mappingMatched": list(self.mappingMatched),
            "mappingUnmatched": list(self.mappingUnmatched),
            "strictBlocked": self.strictBlocked,
            "strictReason": self.strictReason,
            "createdAt": self.createdAt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntakePlan":
        data = data or {}
        return cls(
            source=str(data.get("source") or ""),
            sourceHash=str(data.get("sourceHash") or ""),
            sourceKind=str(data.get("sourceKind") or "docx"),
            documentType=str(data.get("documentType") or "general"),
            policy=IntakePolicy.from_dict(data.get("policy")),
            target=PlannedTarget.from_dict(data.get("target")),
            headingDecisions=[HeadingDecision.from_dict(item) for item in data.get("headingDecisions") or []],
            sections=[SectionCandidate.from_dict(item) for item in data.get("sections") or []],
            preservationFindings=[PreservationFinding.from_dict(item) for item in data.get("preservationFindings") or []],
            warnings=[str(item) for item in data.get("warnings") or []],
            unavailableComparisons=[str(item) for item in data.get("unavailableComparisons") or []],
            mappingPresetId=str(data.get("mappingPresetId") or ""),
            mappingMatched=[str(item) for item in data.get("mappingMatched") or []],
            mappingUnmatched=[str(item) for item in data.get("mappingUnmatched") or []],
            strictBlocked=bool(data.get("strictBlocked", False)),
            strictReason=str(data.get("strictReason") or ""),
            createdAt=str(data.get("createdAt") or utc_now_iso()),
        )


# --- 出稿契约 ---------------------------------------------------------------


@dataclass
class ExportScope:
    """出稿范围：整项目 / 当前章 / 勾选章节（按项目顺序）。"""

    kind: str = SCOPE_PROJECT
    chapters: List[str] = field(default_factory=list)
    current: str = ""

    def __post_init__(self) -> None:
        if self.kind not in SCOPE_KINDS:
            self.kind = SCOPE_PROJECT
        if self.kind != SCOPE_CHAPTERS:
            self.chapters = []

    @property
    def is_full(self) -> bool:
        return self.kind == SCOPE_PROJECT

    def describe(self, total_chapters: int = 0) -> str:
        if self.kind == SCOPE_PROJECT:
            return "整份文档{0}".format(
                "（{0} 章）".format(total_chapters) if total_chapters else ""
            )
        if self.kind == SCOPE_CURRENT_CHAPTER:
            return "当前章：{0}".format(self.current or "（未指定）")
        return "所选 {0} 章：{1}".format(
            len(self.chapters), "、".join(self.chapters) or "（未选择）"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "chapters": list(self.chapters), "current": self.current}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExportScope":
        data = data or {}
        return cls(
            kind=str(data.get("kind") or SCOPE_PROJECT),
            chapters=[str(item) for item in data.get("chapters") or []],
            current=str(data.get("current") or ""),
        )


@dataclass
class ExportRequest:
    """统一出稿请求（最小契约；CORE-F 在此基础上补执行细节）。"""

    project_root: str = ""
    formats: List[str] = field(default_factory=lambda: [FORMAT_DOCX])
    scope: ExportScope = field(default_factory=ExportScope)
    source_mode: str = SOURCE_MODE_CURRENT_BUFFER
    destination: str = ""
    output_name: str = ""
    layout_profile: str = "template"
    #: 排版明细（CORE-G）：见 ``export.layout_profile.LayoutProfile``。
    layout: Dict[str, Any] = field(default_factory=dict)
    refresh: bool = True
    strict: bool = False
    include_original: bool = False
    capture_id: str = ""
    #: V3.2 4.2：产品变体（空=项目当前内容）；出稿按变体的有效章节/变量/模块版本展开。
    variant_id: str = ""

    def __post_init__(self) -> None:
        self.formats = normalize_formats(self.formats) or [FORMAT_DOCX]
        if self.source_mode not in SOURCE_MODES:
            self.source_mode = SOURCE_MODE_SAVED

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.to_dict()
        return data

    @property
    def variantId(self) -> str:
        return self.variant_id

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExportRequest":
        data = data or {}
        return cls(
            variant_id=str(data.get("variant_id") or data.get("variantId") or ""),
            project_root=str(data.get("project_root") or ""),
            formats=[str(item) for item in data.get("formats") or [FORMAT_DOCX]],
            scope=ExportScope.from_dict(data.get("scope")),
            source_mode=str(data.get("source_mode") or SOURCE_MODE_SAVED),
            destination=str(data.get("destination") or ""),
            output_name=str(data.get("output_name") or ""),
            layout_profile=str(data.get("layout_profile") or "template"),
            layout=dict(data.get("layout") or {}),
            refresh=bool(data.get("refresh", True)),
            strict=bool(data.get("strict", False)),
            include_original=bool(data.get("include_original", False)),
            capture_id=str(data.get("capture_id") or ""),
        )


@dataclass
class FormatResult:
    """单格式结果；status 复用统一状态词，不自行提升正式状态。"""

    format: str
    status: str = STATUS_FAILED
    path: str = ""
    sha256: str = ""
    backend: str = ""
    formal: bool = False
    warnings: List[str] = field(default_factory=list)
    error_code: str = ""
    message: str = ""
    attempts: int = 1

    @property
    def usable(self) -> bool:
        return self.status in USABLE_STATUSES and bool(self.path)

    def label(self) -> str:
        return FORMAT_STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormatResult":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


FORMAT_STATUS_LABELS = {
    STATUS_READY: "已生成",
    STATUS_PENDING_REFRESH: "待刷新",
    STATUS_PENDING_CONVERT: "待转换",
    STATUS_FAILED: "失败",
    STATUS_CANCELLED: "已取消",
    STATUS_SKIPPED: "未执行",
}

FORMAT_LABELS = {
    FORMAT_DOCX: "Word",
    FORMAT_PDF: "PDF",
    FORMAT_HTML: "离线 HTML",
    FORMAT_SOURCE_ZIP: "源码包",
}


def format_label(value: str) -> str:
    return FORMAT_LABELS.get(normalize_format(value), value)