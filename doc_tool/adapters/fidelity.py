# -*- coding: utf-8 -*-
"""导入保真扫描适配器。

任务 2.1-2.3：导入前对源 DOCX 做特性级保真扫描，识别导入 Markdown 化后可能
损失或降级的 Word 特性，按严重级别分级报告：

- BLOCK：明确会造成内容损失（批注/修订/脚注/尾注/公式/图表/文本框/OLE）。
- WARN：可能降级但通常可接受（超链接/书签/内容控件）。
- INFO：仅信息提示（域）。

统一树遍历（lxml 元素树）而非正则，跨行 ``w:ins``/``w:del`` 等边界不遗漏。
输入为统一安全入口读出的 XML/rels 部件字典；输出计数与位置采样，不读正文。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from lxml import etree

from doc_tool.domain.ooxml import parse_xml_safe

# wordprocessingml 命名空间（读取脚注/尾注的 w:type 属性）。
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{" + W_NS + "}"

# 严重级别。
SEVERITY_BLOCK = "BLOCK"
SEVERITY_WARN = "WARN"
SEVERITY_INFO = "INFO"

_SEVERITY_ORDER = (SEVERITY_BLOCK, SEVERITY_WARN, SEVERITY_INFO)

# 每个特性最多保留的位置采样数。
MAX_SAMPLES = 5

# 特性标识 -> (显示名, 严重级别)。
FEATURE_DEFS = {
    "hyperlink": ("超链接", SEVERITY_WARN),
    "bookmark": ("书签", SEVERITY_WARN),
    "comment": ("批注", SEVERITY_BLOCK),
    "revision": ("修订", SEVERITY_BLOCK),
    "footnote": ("脚注/尾注", SEVERITY_BLOCK),
    "formula": ("公式", SEVERITY_BLOCK),
    "chart": ("图表", SEVERITY_BLOCK),
    "textbox": ("文本框", SEVERITY_BLOCK),
    "ole": ("OLE 对象", SEVERITY_BLOCK),
    "sdt": ("内容控件", SEVERITY_WARN),
    "field": ("域", SEVERITY_INFO),
}

# 元素 localname（去命名空间）-> 特性标识。
_TAG_FEATURES = {
    "hyperlink": "hyperlink",
    "bookmarkStart": "bookmark",
    "commentRangeStart": "comment",
    "ins": "revision",
    "del": "revision",
    "rPrChange": "revision",
    "pPrChange": "revision",
    "footnoteReference": "footnote",
    "endnoteReference": "footnote",
    "oMath": "formula",
    "oMathPara": "formula",
    "txbxContent": "textbox",
    "OLEObject": "ole",
    "oleObject": "ole",
    "sdt": "sdt",
    "fldChar": "field",
    "instrText": "field",
}

# document.xml 的 body 标签 localname。
_BODY_LOCAL = "body"


@dataclass(frozen=True)
class FidelityFinding:
    """一项保真特性统计（计数 + 位置采样）。"""

    feature: str
    label: str
    severity: str
    count: int
    samples: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FidelityReport:
    """保真扫描报告。"""

    findings: Tuple[FidelityFinding, ...] = field(default_factory=tuple)

    @property
    def has_block(self) -> bool:
        return any(f.severity == SEVERITY_BLOCK for f in self.findings)

    @property
    def block_findings(self) -> Tuple[FidelityFinding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_BLOCK)

    @property
    def warn_findings(self) -> Tuple[FidelityFinding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_WARN)

    @property
    def info_findings(self) -> Tuple[FidelityFinding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_INFO)

    @property
    def block_count(self) -> int:
        return sum(f.count for f in self.block_findings)

    @property
    def warn_count(self) -> int:
        return sum(f.count for f in self.warn_findings)

    def summary_text(self) -> str:
        """一行摘要（用于日志与成功项目持久化）。"""
        if not self.findings:
            return "保真扫描：未发现损失性特性"
        parts = [
            "{0} {1}{2}{3}".format(
                finding.severity,
                finding.label,
                " {0}".format(finding.count),
                "" if not finding.samples else "（{0}）".format("、".join(finding.samples)),
            )
            for finding in self.findings
        ]
        return "保真扫描：" + "；".join(parts)

    def markdown_text(self) -> str:
        """Markdown 报告（写入成功项目 logs/）。"""
        lines = ["## 保真扫描报告", ""]
        if not self.findings:
            lines.append("未发现损失性特性。")
            return "\n".join(lines)
        lines.append("| 级别 | 特性 | 数量 | 位置采样 |")
        lines.append("|------|------|------|----------|")
        for finding in self.findings:
            lines.append(
                "| {0} | {1} | {2} | {3} |".format(
                    finding.severity,
                    finding.label,
                    finding.count,
                    "、".join(finding.samples) if finding.samples else "—",
                )
            )
        return "\n".join(lines)


def scan_fidelity(parts: Dict[str, bytes]) -> FidelityReport:
    """对 DOCX 的 XML/rels 部件执行统一树遍历保真扫描。

    Args:
        parts: ``read_docx_package(...).read_xml_parts()`` 返回的部件字节字典。

    Returns:
        ``FidelityReport`` 分级报告（无风险项时 findings 为空）。

    Raises:
        OOXMLSecurityError: 部件无法安全解析（预检已先校验良构，正常不会触发）。
    """
    counts: Counter = Counter()
    samples: Dict[str, List[str]] = defaultdict(list)

    for name in sorted(parts):
        # 图表部件按名称检测（DrawingML 部件本身不含 document.xml 的特性标签）。
        if name.startswith("word/charts/") and name.endswith(".xml"):
            counts["chart"] += 1
            _add_sample(samples, "chart", name)
        if not name.endswith(".xml") and not name.endswith(".rels"):
            continue
        root = parse_xml_safe(parts[name], name)
        if name == "word/document.xml":
            # document.xml 按 body 子元素定位采样，便于定位到具体段落/表格。
            _scan_document(root, counts, samples)
        else:
            _scan_part(name, root, counts, samples)

    # 批注/脚注部件存在但没有正文引用时仍应上报（如仅含批注引用无 rangeStart）。
    _ensure_part_backstop(parts, counts, samples, "word/comments.xml", "comment", "comment")
    _ensure_part_backstop(parts, counts, samples, "word/footnotes.xml", "footnote", "footnote")
    _ensure_part_backstop(parts, counts, samples, "word/endnotes.xml", "endnote", "footnote")

    return _build_report(counts, samples)


def _add_sample(samples: Dict[str, List[str]], feature: str, location: str) -> None:
    if len(samples[feature]) < MAX_SAMPLES:
        samples[feature].append(location)


def _scan_document(root, counts: Counter, samples: Dict[str, List[str]]) -> None:
    """遍历 document.xml 的 body 子元素，按 ``body[index]`` 记录采样位置。"""
    body = None
    for child in root.iterchildren():
        if etree.QName(child).localname == _BODY_LOCAL:
            body = child
            break
    if body is None:
        return
    for index, element in enumerate(body):
        for node in element.iter():
            feature = _TAG_FEATURES.get(etree.QName(node).localname)
            if feature is None:
                continue
            counts[feature] += 1
            _add_sample(samples, feature, "body[{0}]".format(index))


def _scan_part(part_name: str, root, counts: Counter, samples: Dict[str, List[str]]) -> None:
    """遍历非正文 XML 部件（页眉/页脚/批注/脚注等），采样为部件名。"""
    for node in root.iter():
        feature = _TAG_FEATURES.get(etree.QName(node).localname)
        if feature is None:
            continue
        counts[feature] += 1
        _add_sample(samples, feature, part_name)


def _ensure_part_backstop(
    parts: Dict[str, bytes],
    counts: Counter,
    samples: Dict[str, List[str]],
    part_name: str,
    element_local: str,
    feature: str,
) -> None:
    """部件存在但正文无引用时，以部件内元素计数兜底（避免漏报）。

    跳过 ``w:type="separator"/"continuationSeparator"`` 的分隔符脚注/尾注——
    Word 即使在文档完全没有脚注时也会在 ``footnotes.xml``/``endnotes.xml``
    留下这两个系统条目，把它们计入会让几乎所有文档被误报为「脚注 BLOCK」。
    """
    if counts.get(feature, 0) > 0 or part_name not in parts:
        return
    root = parse_xml_safe(parts[part_name], part_name)
    for node in root.iter():
        if etree.QName(node).localname != element_local:
            continue
        if element_local in ("footnote", "endnote") and node.get(
            _W + "type"
        ) in ("separator", "continuationSeparator"):
            # 分隔符/延续分隔符是 Word 自动维护的系统条目，非真实脚注内容。
            continue
        counts[feature] += 1
        _add_sample(samples, feature, part_name)


def _build_report(counts: Counter, samples: Dict[str, List[str]]) -> FidelityReport:
    findings: List[FidelityFinding] = []
    for feature, (label, severity) in FEATURE_DEFS.items():
        count = counts.get(feature, 0)
        if count == 0:
            continue
        findings.append(
            FidelityFinding(
                feature=feature,
                label=label,
                severity=severity,
                count=count,
                samples=tuple(samples.get(feature, ())),
            )
        )
    findings.sort(key=lambda f: (_SEVERITY_ORDER.index(f.severity), f.feature))
    return FidelityReport(findings=tuple(findings))
