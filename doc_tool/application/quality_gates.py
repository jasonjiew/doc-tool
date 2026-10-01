# -*- coding: utf-8 -*-
"""发布质量门禁与产物终审（V2.7 27-F / 6.1、6.3、6.4）。

设计取舍：不新建审批模型。结论只用两种稳定词汇：

- 每个发现是 :class:`AuditFinding`（稳定 ``rule`` + 可定位 ``line`` + 严重级），
  可直接转成现有的 ``IssueRecord`` 对接入问题中心。
- 是否拦截由 :class:`GatePolicy` 决定：默认（``strict=False``）warning 继续出稿，
  只有用户显式选择严格交付时才把约定规则提升为阻断。
- 不改写不可变历史：本模块只读 DOCX 与报告，不动源文件与正式记录。

STAGE_AUDIT 检查的是“真实 Word 域错误 / 正文占位 / 超宽表 / 异常空段”。
代码示例不参与占位检查（代码容器整体跳过），避免把示例字符串当成作者遗留。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.application.issues import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    IssueRecord,
    utc_now,
)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: 稳定规则 ID（CLI/JSON/SARIF 与问题中心共用）。
RULE_FIELD_ERROR = "audit_field_error"
RULE_BODY_PLACEHOLDER = "audit_body_placeholder"
RULE_TABLE_OVERWIDE = "audit_table_overwide"
RULE_EMPTY_PARAGRAPH = "audit_empty_paragraph"

RULE_LABELS = {
    RULE_FIELD_ERROR: "真实 Word 域错误",
    RULE_BODY_PLACEHOLDER: "正文占位未完成",
    RULE_TABLE_OVERWIDE: "表格超出版心",
    RULE_EMPTY_PARAGRAPH: "异常空段",
}

#: 默认严重级：三类提醒默认 warning 继续出稿。
RULE_SEVERITIES = {
    RULE_FIELD_ERROR: SEVERITY_WARNING,
    RULE_BODY_PLACEHOLDER: SEVERITY_WARNING,
    RULE_TABLE_OVERWIDE: SEVERITY_WARNING,
    RULE_EMPTY_PARAGRAPH: SEVERITY_INFO,
}

#: 严格交付时提升为阻断的规则（真实域错误必须先修，
#: 超宽表与占位由作者确认）。
STRICT_BLOCKING_RULES = (RULE_FIELD_ERROR, RULE_BODY_PLACEHOLDER, RULE_TABLE_OVERWIDE)

#: Word 域缓存结果里的真实错误文本。
_FIELD_ERROR_RE = re.compile(
    r"Error!\s*(?:未定义书签|书签未定义|未找到引用源|Bookmark not defined|Reference source not found|unable to find)",
    re.IGNORECASE,
)
_FIELD_ERROR_HINT_RE = re.compile(r"请更新域|update the field|press F9", re.IGNORECASE)

#: 正文占位（中英文与常见变体）。
_PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|XXX)\b|待定|待补充|待确认|此处待|略。",
    re.IGNORECASE,
)

#: 版心宽度与表格 dxa 宽度的换算（twips -> EMU）。
_EMU_PER_TWIP = 635
#: 超出版心多少比例才报（避免取整误差）。
_OVERWIDE_TOLERANCE = 1.02
#: 超宽表判定：平均每列低于这个宽度（0.5cm 左右）即难以阅读。
_MIN_READABLE_COLUMN_TWIPS = 300
#: 多少个连续空段才算异常（企业模板自带空段不得误报）。
_MAX_TOLERATED_BLANK_RUN = 4


@dataclass(frozen=True)
class GatePolicy:
    """质量门禁策略。

    ``strict`` 默认 False：发现问题也不拦截，带提醒出稿；
    只有调用方（GUI 选项 / CLI ``--strict``）显式打开时，才把
    :data:`STRICT_BLOCKING_RULES` 提升为阻断。
    """

    strict: bool = False
    #: 可选：额外上报的规则集（默认上报全部发现）。
    report_rules: Optional[Tuple[str, ...]] = None

    def severity_for(self, rule: str) -> str:
        severity = RULE_SEVERITIES.get(rule, SEVERITY_INFO)
        if self.strict and rule in STRICT_BLOCKING_RULES:
            return SEVERITY_ERROR
        return severity

    def blocks(self, rule: str) -> bool:
        return self.severity_for(rule) == SEVERITY_ERROR


@dataclass(frozen=True)
class AuditFinding:
    """一条终审发现。"""

    rule: str
    message: str
    severity: str = SEVERITY_WARNING
    line: Optional[int] = None
    location: str = ""
    hint: str = ""

    @property
    def label(self) -> str:
        return RULE_LABELS.get(self.rule, self.rule)

    def to_dict(self) -> Dict[str, object]:
        return {
            "rule": self.rule,
            "label": self.label,
            "severity": self.severity,
            "line": self.line,
            "location": self.location,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass
class AuditReport:
    """产物终审报告（仅读）。"""

    document: str = ""
    findings: List[AuditFinding] = field(default_factory=list)
    policy: GatePolicy = field(default_factory=GatePolicy)

    @property
    def blocked(self) -> bool:
        return any(finding.severity == SEVERITY_ERROR for finding in self.findings)

    @property
    def worst_severity(self) -> str:
        if self.blocked:
            return SEVERITY_ERROR
        if any(finding.severity == SEVERITY_WARNING for finding in self.findings):
            return SEVERITY_WARNING
        return SEVERITY_INFO

    @property
    def status(self) -> str:
        if self.blocked:
            return "blocked"
        if self.findings:
            return "warning"
        return "ok"

    def by_rule(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in self.findings:
            counts[finding.rule] = counts.get(finding.rule, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, object]:
        return {
            "document": self.document,
            "status": self.status,
            "strict": self.policy.strict,
            "counts": self.by_rule(),
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def markdown_text(self) -> str:
        lines = ["## 发布终审报告", ""]
        if not self.findings:
            lines.append("未发现问题（默认策略）。")
            return "\n".join(lines)
        lines.append("| 级别 | 规则 | 位置 | 说明 |")
        lines.append("|------|------|------|------|")
        for finding in self.findings:
            where = finding.location or ("行 {0}".format(finding.line) if finding.line else "—")
            lines.append(
                "| {0} | {1} | {2} | {3} |".format(
                    finding.severity, finding.label, where, finding.message
                )
            )
        if not self.policy.strict:
            lines.append("")
            lines.append("当前为默认策略：以上问题不阻断出稿，仲产物可打开。")
        return "\n".join(lines)

    def issues(self, document_type: str = "", generated_at: str = "") -> List[IssueRecord]:
        """转成问题中心记录（复用现有 ``IssueRecord``）。"""
        generated = generated_at or utc_now()
        records: List[IssueRecord] = []
        for finding in self.findings:
            records.append(
                IssueRecord(
                    source="audit",
                    issue_type=finding.rule,
                    document_type=document_type,
                    severity=finding.severity,
                    rel_path="",
                    line_no=finding.line,
                    error_code=None,
                    message="{0}：{1}".format(finding.label, finding.message),
                    suggested_action=finding.hint or "请核对该位置后重新生成。",
                    generated_at=generated,
                )
            )
        return records


def audit_policy(strict: bool = False) -> GatePolicy:
    """构造策略；保留函数形式便于 GUI/CLI 同源调用。"""
    return GatePolicy(strict=bool(strict))
def audit_docx(
    docx_path,
    *,
    policy: Optional[GatePolicy] = None,
    body_width_twips: Optional[int] = None,
    template_path=None,
) -> AuditReport:
    """对生成的 DOCX 执行 STAGE_AUDIT（只读，不改写任何文件）。

    检查项：真实 Word 域错误、正文占位、超宽表、异常空段。
    代码容器内的文本不参与占位检查，避免把示例当成作者遗留。
    """
    from docx_common import parse_xml_safe, read_docx_package
    from doc_tool.kernel_shared.code_marker import is_code_container

    active_policy = policy or GatePolicy()
    report = AuditReport(document=str(docx_path), policy=active_policy)

    with read_docx_package(str(docx_path)) as package:
        document = parse_xml_safe(package.read("word/document.xml"), "word/document.xml")
    body = document.find(_W + "body")
    if body is None:
        report.findings.append(
            AuditFinding(
                rule=RULE_FIELD_ERROR,
                message="产物 document.xml 缺少 w:body，无法终审。",
                severity=SEVERITY_ERROR,
            )
        )
        return report

    section_widths = _section_width_map(body)
    # 模板自带的空段与宽表是产品设计的一部分（封面/修订表），
    # 不应在每次出稿时被当成作者问题；只审查本次生成的内容。
    template_shape = _template_shape(template_path) if template_path else None
    # 模板元素只能出现在生成内容之前：一旦命中第一个偏离模板形状的元素，
    # 之后的同类元素一律当作作者内容。
    template_limit = _template_prefix_length(body, template_shape)
    empty_run = 0
    empty_start = 0
    for index, element in enumerate(body):
        location = "body[{0}]".format(index)
        is_template_element = (
            template_shape is not None and index < template_limit
        )
        if element.tag == _W + "tbl":
            if is_code_container(element):
                # 代码容器：内文是代码示例（可能含“Error! 未定义书签”这种
                # 说明性字符串），不参与域错误、占位与超宽表检查。
                empty_run = 0
                continue
            if is_template_element:
                # 模板自带宽表（如封面表）：不是本次生成的内容。
                continue
            available = max(section_widths.values()) if section_widths else None
            _audit_table_width(element, available, active_policy, report, location)
            continue
        if element.tag != _W + "p":
            continue
        text = visible_text(element)
        _audit_field_errors(element, active_policy, report, location)
        if _PLACEHOLDER_RE.search(text):
            report.findings.append(
                AuditFinding(
                    rule=RULE_BODY_PLACEHOLDER,
                    severity=active_policy.severity_for(RULE_BODY_PLACEHOLDER),
                    message="正文仍有占位未完成：{0}".format(_excerpt(text)),
                    location=location,
                    hint="请补充该处内容，或删除占位提示。",
                )
            )
            continue
        # 空段按「连续跑」计：企业模板本身就有大量版式空段，
        # 单个空段不值得告警；连续大量才是作者误操作或模板污染。
        if not text and _is_anomalous_empty(element):
            empty_run += 1
            if empty_run == 1:
                empty_start = index
            continue
        if is_template_element and empty_run:
            # 模板自带空段不计入跑长。
            empty_run = 0
            continue
        if empty_run >= _MAX_TOLERATED_BLANK_RUN:
            report.findings.append(
                AuditFinding(
                    rule=RULE_EMPTY_PARAGRAPH,
                    severity=active_policy.severity_for(RULE_EMPTY_PARAGRAPH),
                    message="出现 {0} 个连续空段（无文本且无图片/分页/分节）。".format(
                        empty_run
                    ),
                    location="body[{0}]".format(empty_start),
                    hint="如非刻意留白，请删除多余空段。",
                )
            )
        empty_run = 0
    if empty_run >= _MAX_TOLERATED_BLANK_RUN:
        report.findings.append(
            AuditFinding(
                rule=RULE_EMPTY_PARAGRAPH,
                severity=active_policy.severity_for(RULE_EMPTY_PARAGRAPH),
                message="末尾出现 {0} 个连续空段。".format(empty_run),
                location="body[{0}]".format(empty_start),
                hint="如非刻意留白，请删除多余空段。",
            )
        )
    return report
def visible_text(element) -> str:
    """元素可见文本：跳过域指令，保留缓存结果与换行/制表符。"""
    parts: List[str] = []
    in_instruction = False
    saw_instruction = False
    for node in element.iter():
        if node.tag == _W + "fldChar":
            kind = node.get(_W + "fldCharType")
            if kind == "begin":
                in_instruction = True
                saw_instruction = False
            elif kind in ("separate", "end"):
                in_instruction = False
                saw_instruction = False
            continue
        if node.tag == _W + "instrText":
            saw_instruction = True
            continue
        if node.tag == _W + "t":
            if in_instruction:
                if saw_instruction:
                    in_instruction = False
                    saw_instruction = False
                else:
                    continue
            parts.append(node.text or "")
        elif node.tag in (_W + "br", _W + "cr"):
            parts.append("\n")
        elif node.tag == _W + "tab":
            parts.append("\t")
    return "".join(parts).strip()


def _section_width_map(body) -> Dict[int, int]:
    """每个正文元素索引 -> 它所属节的版心宽度（twips）。

    节边界由带 ``sectPr`` 的段落（或末尾 ``sectPr``）划分；封面节与正文
    节的版心不同，必须各自取自己的节，否则模板封面表会被误报超宽。
    """
    widths: Dict[int, int] = {}
    default_dxa = 12240 - 1440 - 1440
    pending: List[int] = []
    for index, element in enumerate(body):
        section = _section_of(element)
        if section is None:
            pending.append(index)
            continue
        available = _content_width_twips(section) or default_dxa
        for item in pending:
            widths[item] = available
        widths[index] = available
        pending = []
    for item in pending:
        widths[item] = default_dxa
    return widths


def _section_of(element):
    if element.tag == _W + "p":
        properties = element.find(_W + "pPr")
        return properties.find(_W + "sectPr") if properties is not None else None
    if element.tag == _W + "sectPr":
        return element
    return None


def _content_width_twips(section) -> Optional[int]:
    page_size = section.find(_W + "pgSz")
    if page_size is None:
        return None
    margins = section.find(_W + "pgMar")
    try:
        width = int(page_size.get(_W + "w", "12240"))
        left = int(margins.get(_W + "left", "1440")) if margins is not None else 1440
        right = int(margins.get(_W + "right", "1440")) if margins is not None else 1440
    except (TypeError, ValueError):
        return None
    available = width - left - right
    return available if available > 0 else None


def _audit_field_errors(element, policy: GatePolicy, report: AuditReport, location: str) -> None:
    """检查域缓存结果里的真实 Word 错误（如“错误！未定义书签”）。

    只看域缓存结果与普通文本；代码示例中的同名字符串不在此判定（调用方传入的
    元素若为代码容器内容，文本仍可命中——因此本函数只在已排除代码容器的地方调用）。
    """
    text = visible_text(element)
    if not text:
        return
    if _FIELD_ERROR_RE.search(text):
        report.findings.append(
            AuditFinding(
                rule=RULE_FIELD_ERROR,
                severity=policy.severity_for(RULE_FIELD_ERROR),
                message="域结果出现真实错误：{0}".format(_excerpt(text)),
                location=location,
                hint="已优先回退为可读静态引用；请确认书签目标存在后重新生成。",
            )
        )


def _audit_table_width(
    table, available: Optional[int], policy: GatePolicy, report: AuditReport, location: str
) -> None:
    """表格实际宽度超出所在节版心时报超宽（按本元素所属节判定）。"""
    widths = _table_declared_widths(table)
    if not widths:
        return
    actual = sum(widths)
    if available and actual > available * _OVERWIDE_TOLERANCE:
        report.findings.append(
            AuditFinding(
                rule=RULE_TABLE_OVERWIDE,
                severity=policy.severity_for(RULE_TABLE_OVERWIDE),
                message="表格宽度 {0} twips 超出版心 {1} twips。".format(actual, available),
                location=location,
                hint="请减少列数或收窄列宽，也可放到樫向节内。",
            )
        )
        return
    # 构建内核会把超宽表按版心缩放，因此“实际宽度超版心”很难出现；
    # 真正会伤可读性的是列数过多导致每列被压到读不清。
    if available and len(widths) > 1:
        per_column = actual / float(len(widths))
        if per_column < _MIN_READABLE_COLUMN_TWIPS:
            report.findings.append(
                AuditFinding(
                    rule=RULE_TABLE_OVERWIDE,
                    severity=policy.severity_for(RULE_TABLE_OVERWIDE),
                    message="表格 {0} 列在版心内平均每列 {1:.0f} twips，已难以阅读。".format(
                        len(widths), per_column
                    ),
                    location=location,
                    hint="请减少列数，或把该表放到樫向节内。",
                )
            )


def _table_declared_widths(table) -> List[int]:
    """取表格列宽：优先 ``tblGrid``，其次第一行单元格 ``tcW``。"""
    grid = table.find(_W + "tblGrid")
    widths: List[int] = []
    if grid is not None:
        for column in grid.findall(_W + "gridCol"):
            try:
                widths.append(int(column.get(_W + "w", "0")))
            except (TypeError, ValueError):
                continue
    if any(widths):
        return widths
    row = table.find(_W + "tr")
    if row is None:
        return []
    for cell in row.findall(_W + "tc"):
        properties = cell.find(_W + "tcPr")
        cell_width = properties.find(_W + "tcW") if properties is not None else None
        if cell_width is None:
            return []
        try:
            widths.append(int(cell_width.get(_W + "w", "0")))
        except (TypeError, ValueError):
            return []
    return widths


def _is_anomalous_empty(paragraph) -> bool:
    """空段是否异常：既无内容，也不承载图片/分页/分节等合法职责。"""
    for node in paragraph.iter():
        if node.tag in (
            _W + "drawing",
            _W + "pict",
            _W + "object",
            _W + "sectPr",
        ):
            return False
        if node.tag == _W + "br" and node.get(_W + "type") == "page":
            return False
        if node.tag == _W + "bookmarkStart":
            return False
    properties = paragraph.find(_W + "pPr")
    if properties is not None:
        if properties.find(_W + "numPr") is not None:
            return False
        style = properties.find(_W + "pStyle")
        if style is not None and (style.get(_W + "val") or ""):
            return False
    return True


def _excerpt(text: str, limit: int = 60) -> str:
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[:limit] + "…"


def twips_to_emu(twips: int) -> int:
    """twips -> EMU（与内核 ``usable_page_width_emu`` 同一换算）。"""
    return int(twips) * _EMU_PER_TWIP
def _template_prefix_length(body, template_shape) -> int:
    """返回产物中仍属于模板前缀的元素个数。

    模板元素在产物中保持原顺序；遇到第一个既不符合模板形状、
    也不是空段作者内容的元素时停止。这样后面的作者新表就不会被
    误判为模板原表。
    """
    if template_shape is None:
        return 0
    length = 0
    for index, element in enumerate(body):
        if template_shape.matches(body, index):
            length = index + 1
            continue
        if element.tag == _W + "p" and not visible_text(element):
            # 模板自带的""空段""（无文本）可能因为模板形状
            # 在建构后发生微小变化而未命中，不应因此提前截断前缀。
            length = index + 1
            continue
        break
    return length


class _TemplateShape:
    """模板自带元素的识别器（形状 + 文本指纹）。

    模板元素会被构建原样保留（或只替换文本），因此按位置粗对齐即可：
    第 N 个模板元素对应产物中尚未命中的同类元素。此外只需要能回答“这个位置是否仍属于模板区”。
    """

    def __init__(self, signature) -> None:
        self._signature = list(signature)

    def matches(self, body, index: int) -> bool:
        if index >= len(self._signature):
            return False
        element = body[index]
        expected = self._signature[index]
        actual = _element_signature(element)
        if actual != expected:
            return False
        if expected.startswith("tbl|"):
            # 同位置可能已被作者内容占据：只有列宽也一致才算模板原表。
            return expected == _table_shape(element)
        return True


def _element_signature(element) -> str:
    """元素形状指纹：种类 + 样式/属性（不含文本）。"""
    name = element.tag
    if name == _W + "p":
        properties = element.find(_W + "pPr")
        style = ""
        if properties is not None:
            style_node = properties.find(_W + "pStyle")
            if style_node is not None:
                style = style_node.get(_W + "val") or ""
        return "p|{0}".format(style)
    if name == _W + "tbl":
        return _table_shape(element)
    return name


def _table_shape(table) -> str:
    """表格指纹：行数 + 列宽（用于区分模板原表与作者新表）。"""
    widths = _table_declared_widths(table)
    return "tbl|{0}|{1}".format(len(table.findall(_W + "tr")), sum(widths))


def _template_shape(template_path):
    """读模板正文形状；不可读时返回 None（不过滤）。"""
    from docx_common import parse_xml_safe, read_docx_package

    try:
        with read_docx_package(str(template_path)) as package:
            document = parse_xml_safe(
                package.read("word/document.xml"), "word/document.xml"
            )
    except Exception:  # noqa: BLE001 - 模板不可读时不做过滤
        return None
    body = document.find(_W + "body")
    if body is None:
        return None
    return _TemplateShape([_element_signature(element) for element in body])