# -*- coding: utf-8 -*-
"""多规则标题识别与目录树打散策略（Split Rules & Policies）。

将 Word 导入拆树解耦为两层可配置能力：
1. **标题与边界识别规则链（Recognition Rules）**：
   - ``style``：显式段落样式映射（Heading 1~6 / 自定义映射）；
   - ``outline``：段落大纲级别（``w:outlineLvl``）；
   - ``skeleton``：规范包/底模章节骨架标题对齐；
   - ``numbering_pattern``：正文编号正则簇（工程章节 ``第N章 / 1.1 / 1.1.1``、
     中文公文 ``一、 / （一）``、附录 ``附录A / A.1``）+ 排版特征（字数上限、禁句末标点、加粗/字号）；
   - ``numpr_list``：Word 自动多级列表（``w:numPr/w:ilvl``）+ 加粗/字号强调特征；
   - ``item_anchor``：业务条目边界（``[REQ-001]`` / ``SRS-01`` / ``TC-01`` / ``IF-01``）。
2. **目录打散策略档位（SplitPolicy）**：
   - ``standard``：标准三级章节树（H1 目录、H2 目录/文件、H3 文件，默认）；
   - ``compact``：轻量两级结构 + 防碎片内聚（适合短文档，避免碎片小文件）；
   - ``chapter_only``：单层按章切分（仅 H1 建章，子标题保留在章内）；
   - ``deep_item``：四级深拆 + 业务条目切分（适合大型需求/详设规格书）；
   - ``preserve_numbering``：保留原文公文/附录/条目编号前缀语义；
   - ``auto_rules``：开启多信号启发式识别 + 自适应跳级承接与防碎片打散。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lxml import etree

from doc_tool.domain.ooxml import (
    infer_heading_level_from_style_id,
    parse_xml_safe,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"


def _qn(tag: str) -> str:
    return W + tag


# --- 识别规则标识 -----------------------------------------------------------

RULE_STYLE = "style"
RULE_OUTLINE = "outline"
RULE_SKELETON = "skeleton"
RULE_NUMBERING = "numbering_pattern"
RULE_NUMPR = "numpr_list"
RULE_ITEM_ANCHOR = "item_anchor"

ALL_RECOGNITION_RULES: Tuple[str, ...] = (
    RULE_STYLE,
    RULE_OUTLINE,
    RULE_SKELETON,
    RULE_NUMBERING,
    RULE_NUMPR,
    RULE_ITEM_ANCHOR,
)

STYLE_ONLY_RULES: Tuple[str, ...] = (RULE_STYLE, RULE_OUTLINE)

# --- 编号正则簇标识 ---------------------------------------------------------

CLUSTER_CHAPTER_NUMERIC = "chapter_numeric"
CLUSTER_ENGINEERING = CLUSTER_CHAPTER_NUMERIC
CLUSTER_CHINESE_OFFICIAL = "chinese_official"
CLUSTER_OFFICIAL_CN = CLUSTER_CHINESE_OFFICIAL
CLUSTER_APPENDIX = "appendix"
CLUSTER_ITEM_ANCHOR = "item_anchor"

ALL_NUMBERING_CLUSTERS: Tuple[str, ...] = (
    CLUSTER_CHAPTER_NUMERIC,
    CLUSTER_CHINESE_OFFICIAL,
    CLUSTER_APPENDIX,
    CLUSTER_ITEM_ANCHOR,
)

# --- 打散策略档位标识 -------------------------------------------------------

PROFILE_STANDARD = "standard"
PROFILE_COMPACT = "compact"
PROFILE_CHAPTER_ONLY = "chapter_only"
PROFILE_DEEP_ITEM = "deep_item"
PROFILE_PRESERVE_NUMBERING = "preserve_numbering"
PROFILE_AUTO_RULES = "auto_rules"

VALID_PROFILES = (
    PROFILE_STANDARD,
    PROFILE_COMPACT,
    PROFILE_CHAPTER_ONLY,
    PROFILE_DEEP_ITEM,
    PROFILE_PRESERVE_NUMBERING,
    PROFILE_AUTO_RULES,
)

# --- 编号重写模式 -----------------------------------------------------------

NUMBERING_AUTO_STANDARD = "auto_standard"
NUMBERING_PRESERVE_SEMANTIC = "preserve_semantic"
NUMBERING_CLEAN_TITLE = "clean_title"


@dataclass(frozen=True)
class RuleHeadingMatch:
    """单段或多规则识别出的一条标题命中记录。"""

    body_index: int
    level: int
    text: str
    rule_id: str = RULE_STYLE
    cluster: str = ""
    confidence: float = 1.0
    style_id: str = ""
    prefix_token: str = ""
    clean_title: str = ""

    @property
    def rule(self) -> str:
        return self.rule_id

    @property
    def is_heuristic(self) -> bool:
        return self.rule_id not in (RULE_STYLE, RULE_OUTLINE)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleHeadingMatch":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class SplitPolicy:
    """目录树打散与多规则识别策略配置。"""

    profile: str = PROFILE_STANDARD
    #: 最大拆文件深度（1~4）：1=仅按章，2=到节，3=到三级小节（默认），4=深拆到四级/条目。
    max_split_depth: int = 3
    #: 防碎片最小正文字数阈值：>0 时，若父节下所有子叶子正文均不足该字数且无图表，则内聚回父文件。
    min_leaf_chars: int = 0
    #: 跳级标题桥接：章内遇到 # -> ### 等跳级时自动承接为下一级子文件而非静默吞入正文。
    bridge_jumped_levels: bool = True
    #: 编号命名模式：auto_standard（标准第N章/N.M）或 preserve_semantic（保留公文/附录/条目原前缀）。
    numbering_mode: str = NUMBERING_AUTO_STANDARD
    #: 是否启用非样式的多信号启发式识别（编号簇/numPr/骨架/条目锚点）。
    enable_heuristic_rules: bool = False
    #: 启用的识别规则链（按优先级排列）。
    recognition_rules: Tuple[str, ...] = ALL_RECOGNITION_RULES
    #: 启用的编号识别簇。
    numbering_clusters: Tuple[str, ...] = ALL_NUMBERING_CLUSTERS
    #: 可选的规范包/模板章节骨架标题列表，用于骨架对齐识别。
    skeleton_titles: Tuple[str, ...] = ()
    #: 是否将业务条目锚点（如 [REQ-001] 标题）切分为独立子节。
    split_item_anchors: bool = False
    #: 启发式识别时单行标题的最大字符数上限（防误判长句正文）。
    max_heading_chars: int = 60

    def __post_init__(self) -> None:
        self.max_split_depth = max(1, min(4, int(self.max_split_depth or 3)))
        self.min_leaf_chars = max(0, int(self.min_leaf_chars or 0))
        self.max_heading_chars = max(15, int(self.max_heading_chars or 60))
        if self.numbering_mode not in (NUMBERING_AUTO_STANDARD, NUMBERING_PRESERVE_SEMANTIC, NUMBERING_CLEAN_TITLE):
            self.numbering_mode = NUMBERING_AUTO_STANDARD
        self.recognition_rules = tuple(str(r) for r in (self.recognition_rules or ALL_RECOGNITION_RULES))
        self.numbering_clusters = tuple(str(c) for c in (self.numbering_clusters or ALL_NUMBERING_CLUSTERS))
        self.skeleton_titles = tuple(str(t).strip() for t in (self.skeleton_titles or ()) if str(t).strip())

    @classmethod
    def from_profile(cls, profile: str = PROFILE_STANDARD, **overrides: Any) -> "SplitPolicy":
        p = str(profile or PROFILE_STANDARD).strip().lower()
        if p == PROFILE_COMPACT:
            base = cls(
                profile=PROFILE_COMPACT,
                max_split_depth=2,
                min_leaf_chars=120,
                bridge_jumped_levels=True,
                numbering_mode=NUMBERING_AUTO_STANDARD,
                enable_heuristic_rules=False,
            )
        elif p == PROFILE_CHAPTER_ONLY:
            base = cls(
                profile=PROFILE_CHAPTER_ONLY,
                max_split_depth=1,
                min_leaf_chars=0,
                bridge_jumped_levels=True,
                numbering_mode=NUMBERING_AUTO_STANDARD,
                enable_heuristic_rules=False,
            )
        elif p == PROFILE_DEEP_ITEM:
            base = cls(
                profile=PROFILE_DEEP_ITEM,
                max_split_depth=4,
                min_leaf_chars=0,
                bridge_jumped_levels=True,
                numbering_mode=NUMBERING_PRESERVE_SEMANTIC,
                enable_heuristic_rules=True,
                split_item_anchors=True,
            )
        elif p == PROFILE_PRESERVE_NUMBERING:
            base = cls(
                profile=PROFILE_PRESERVE_NUMBERING,
                max_split_depth=3,
                min_leaf_chars=0,
                bridge_jumped_levels=True,
                numbering_mode=NUMBERING_PRESERVE_SEMANTIC,
                enable_heuristic_rules=True,
            )
        elif p == PROFILE_AUTO_RULES:
            base = cls(
                profile=PROFILE_AUTO_RULES,
                max_split_depth=3,
                min_leaf_chars=80,
                bridge_jumped_levels=True,
                numbering_mode=NUMBERING_PRESERVE_SEMANTIC,
                enable_heuristic_rules=True,
                split_item_anchors=True,
            )
        else:
            base = cls(profile=PROFILE_STANDARD)
        if overrides:
            data = base.to_dict()
            for k, v in overrides.items():
                if v is not None and k in data:
                    data[k] = v
            return cls.from_dict(data)
        return base

    @classmethod
    def recommend(
        cls,
        *,
        headings_count: int = 0,
        level_counts: Optional[Dict[int, int]] = None,
        rule_matches: Sequence[RuleHeadingMatch] = (),
        total_paragraphs: int = 0,
    ) -> "SplitPolicy":
        """根据文档实际结构特征推荐最匹配的打散策略档位。"""
        counts = dict(level_counts or {})
        heuristic_matches = [m for m in (rule_matches or ()) if m.is_heuristic]
        has_style_h1 = counts.get(1, 0) > 0

        # 1. 无标准样式标题但命中了启发式章节规则 -> 推荐 auto_rules 或 deep_item
        if not has_style_h1 and heuristic_matches:
            has_items = any(m.cluster == CLUSTER_ITEM_ANCHOR for m in heuristic_matches)
            max_lvl = max((m.level for m in heuristic_matches), default=3)
            if has_items or max_lvl >= 4:
                return cls.from_profile(PROFILE_DEEP_ITEM)
            return cls.from_profile(PROFILE_AUTO_RULES)

        # 2. 含较多四级标题或业务条目锚点 -> 推荐 deep_item
        if counts.get(4, 0) >= 3 or any(m.cluster == CLUSTER_ITEM_ANCHOR for m in heuristic_matches):
            return cls.from_profile(PROFILE_DEEP_ITEM)

        # 3. 含公文/附录编号特征 -> 推荐 preserve_numbering
        if any(m.cluster in (CLUSTER_CHINESE_OFFICIAL, CLUSTER_APPENDIX) for m in rule_matches):
            return cls.from_profile(PROFILE_PRESERVE_NUMBERING)

        # 4. 短文档（总标题少且段落少） -> 推荐 compact
        if 0 < headings_count <= 6 and (total_paragraphs <= 40 or counts.get(3, 0) <= 2):
            return cls.from_profile(PROFILE_COMPACT)

        return cls.from_profile(PROFILE_STANDARD)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "max_split_depth": self.max_split_depth,
            "min_leaf_chars": self.min_leaf_chars,
            "bridge_jumped_levels": self.bridge_jumped_levels,
            "numbering_mode": self.numbering_mode,
            "enable_heuristic_rules": self.enable_heuristic_rules,
            "recognition_rules": list(self.recognition_rules),
            "numbering_clusters": list(self.numbering_clusters),
            "skeleton_titles": list(self.skeleton_titles),
            "split_item_anchors": self.split_item_anchors,
            "max_heading_chars": self.max_heading_chars,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SplitPolicy":
        if not data:
            return cls()
        if isinstance(data, cls):
            return data
        profile = str(data.get("profile") or PROFILE_STANDARD)
        base = cls.from_profile(profile)
        merged = base.to_dict()
        for key in list(merged.keys()):
            if key in data and data[key] is not None:
                merged[key] = data[key]
        return cls(
            profile=str(merged["profile"]),
            max_split_depth=int(merged["max_split_depth"]),
            min_leaf_chars=int(merged["min_leaf_chars"]),
            bridge_jumped_levels=bool(merged["bridge_jumped_levels"]),
            numbering_mode=str(merged["numbering_mode"]),
            enable_heuristic_rules=bool(merged["enable_heuristic_rules"]),
            recognition_rules=tuple(merged["recognition_rules"]),
            numbering_clusters=tuple(merged["numbering_clusters"]),
            skeleton_titles=tuple(merged["skeleton_titles"]),
            split_item_anchors=bool(merged["split_item_anchors"]),
            max_heading_chars=int(merged["max_heading_chars"]),
        )


# --- 正则与文本特征工具 -----------------------------------------------------

_SENTENCE_END_RE = re.compile(r"[。！？；.!?;，,]$")
_TOC_DOT_LINE_RE = re.compile(r"(?:\.{3,}|…{2,}|\t)\s*\d+\s*$")
_MEASUREMENT_UNIT_RE = re.compile(
    r"^(?:倍|元|万元|亿元|秒|毫秒|分钟|小时|天|年|月|日|米|厘米|毫米|公里|千克|克|吨|"
    r"个|条|项|次|人|台|套|张|页|行|列|章|节|步|版|期|"
    r"mm|cm|km|kg|mg|ms|us|ns|s|min|h|Hz|kHz|MHz|GHz|KB|MB|GB|TB|bps|Mbps|Gbps|%|℃|°)"
    r"(?:[\s，,。、]|$)",
    re.IGNORECASE,
)

# 1. 工程章节编号簇
_CHAPTER_H1_RE = re.compile(
    r"^(第\s*[一二三四五六七八九十百零\d]+\s*[章节篇部])(?:[\s、.．:：\u3000]+(.*)|$)"
)
_DOTTED_NUMBER_RE = re.compile(
    r"^(\d{1,2}(?:\.\d{1,3}){1,3})(?:[\s、\u3000]+|\s*(?=[\u4e00-\u9fa5A-Za-z\[]))(\S.*)$"
)

# 2. 中文公文编号簇
_OFFICIAL_H1_RE = re.compile(r"^([一二三四五六七八九十百]+、)\s*(\S.*)$")
_OFFICIAL_H2_RE = re.compile(r"^([（(][一二三四五六七八九十百]+[)）])\s*(\S.*)$")
_OFFICIAL_H3_RE = re.compile(r"^(\d{1,2}、)\s*(\S.*)$")
_OFFICIAL_H4_RE = re.compile(r"^([（(]\d{1,2}[)）])\s*(\S.*)$")

# 3. 附录编号簇
_APPENDIX_H1_RE = re.compile(
    r"^(附录\s*[A-Z一二三四五六七八九十\d]+)(?:[\s、.．:：\u3000]+(\S.*)|$)"
)
_APPENDIX_SUB_RE = re.compile(
    r"^([A-Z]\.\d{1,2}(?:\.\d{1,2})?)(?:[\s、\u3000]+|\s*(?=[\u4e00-\u9fa5A-Za-z]))(\S.*)$"
)

# 4. 业务条目锚点簇（需求/设计/接口/测试用例）
_ITEM_ANCHOR_RE = re.compile(
    r"^(\[?(?:REQ|SRS|SDS|SYS|ARCH|MOD|IF|API|TC|UC|CASE)-[A-Za-z0-9_.-]+\]?)"
    r"(?:[\s:：、\u3000]+)(\S.*)$",
    re.IGNORECASE,
)


def strip_heading_prefix(text: str, *, mode: str = NUMBERING_AUTO_STANDARD) -> str:
    """按指定模式剥离标题前导编号，供目录/文件命名使用。

    - ``auto_standard``：剥离标准章节号（``第1章`` / ``1.2.3``），使其与重生成的标准编号不重复；
    - ``preserve_semantic``：剥离会被 ``_assign_numbers`` 重复叠加的标准 ``第N章`` / ``N.M``，
      但保留 ``附录A``、``一、``、``（一）``、``[REQ-001]`` 等业务/公文前缀语义。
    """
    s = (text or "").strip()
    if not s:
        return s
    s_std = re.sub(r"^第\s*[0-9一二三四五六七八九十百零]+\s*[章节篇部]\s*", "", s)
    s_std = re.sub(r"^\d+(?:\.\d+)*\s*(?:[、.．]\s*)?", "", s_std)
    if mode == NUMBERING_PRESERVE_SEMANTIC:
        if (
            _APPENDIX_H1_RE.match(s)
            or _APPENDIX_SUB_RE.match(s)
            or _OFFICIAL_H1_RE.match(s)
            or _OFFICIAL_H2_RE.match(s)
            or _ITEM_ANCHOR_RE.match(s)
        ):
            return s
    if mode == NUMBERING_CLEAN_TITLE:
        s_clean = re.sub(r"^[一二三四五六七八九十百]+[、.．]\s*", "", s_std)
        s_clean = re.sub(r"^[（(][一二三四五六七八九十百\d]+[)）]\s*", "", s_clean)
        s_clean = re.sub(r"^附录\s*[A-Z一二三四五六七八九十\d]+[\s、.．:：\u3000]*", "", s_clean)
        s_clean = re.sub(r"^[A-Z]\.\d+(?:\.\d+)*[\s、.．:：\u3000]*", "", s_clean)
        return s_clean.strip() or s
    return s_std.strip() or s


def _normalize_skeleton_title(text: str) -> str:
    """归一化标题文本用于骨架比对（去除前导编号与空白）。"""
    s = (text or "").strip()
    s = re.sub(r"^#{1,6}\s+", "", s)
    s = re.sub(r"^第\s*[0-9一二三四五六七八九十百零]+\s*[章节篇部][\s、.．:：\u3000]*", "", s)
    s = re.sub(r"^[一二三四五六七八九十百]+[、.．]\s*", "", s)
    s = re.sub(r"^[（(][一二三四五六七八九十百\d]+[)）]\s*", "", s)
    s = re.sub(r"^[A-Z]?\d+(?:\.\d+)*[\s、.．:：\u3000]*", "", s)
    return re.sub(r"\s+", "", s).lower()


def _build_skeleton_lookup(skeleton_titles: Sequence[str]) -> Dict[str, int]:
    """从骨架标题列表构建 {归一化标题: 级别} 查找表。"""
    lookup: Dict[str, int] = {}
    for raw in skeleton_titles or ():
        s = str(raw or "").strip()
        if not s:
            continue
        lvl = 1
        m_md = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m_md:
            lvl = len(m_md.group(1))
            s = m_md.group(2).strip()
        else:
            m_dot = re.match(r"^(\d+(?:\.\d+)+)\s+", s)
            if m_dot:
                lvl = min(4, m_dot.group(1).count(".") + 1)
            elif re.match(r"^[（(][一二三四五六七八九十百]+[)）]", s):
                lvl = 2
        norm = _normalize_skeleton_title(s)
        if norm and norm not in lookup:
            lookup[norm] = lvl
    return lookup


def match_text_heading_rule(
    text: str,
    *,
    body_index: int = 0,
    style_id: str = "",
    rules: Sequence[str] = ALL_RECOGNITION_RULES,
    clusters: Sequence[str] = ALL_NUMBERING_CLUSTERS,
    skeleton_titles: Sequence[str] = (),
    max_chars: int = 60,
    is_bold: bool = False,
    font_half_pt: int = 0,
    parent_level: int = 1,
    split_item_anchors: bool = True,
) -> Optional[RuleHeadingMatch]:
    """对单行纯文本执行多规则标题识别（不含样式/outlineLvl，供段落与 Markdown 行共用）。"""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s:
        return None
    if len(s) > max_chars:
        return None
    if _TOC_DOT_LINE_RE.search(s):
        return None

    rule_set = set(rules or ())
    cluster_set = set(clusters or ())
    emphasized = is_bold or (font_half_pt >= 24)

    # P2: 规范包/底模章节骨架对齐
    if RULE_SKELETON in rule_set and skeleton_titles:
        lookup = _build_skeleton_lookup(skeleton_titles)
        norm = _normalize_skeleton_title(s)
        if norm and norm in lookup and not _SENTENCE_END_RE.search(s):
            lvl = lookup[norm]
            return RuleHeadingMatch(
                body_index=body_index,
                level=lvl,
                text=s,
                rule_id=RULE_SKELETON,
                cluster=RULE_SKELETON,
                confidence=0.92 if emphasized else 0.88,
                style_id=style_id,
                prefix_token="",
                clean_title=s,
            )

    # P3: 多级编号与文本前缀正则簇
    if RULE_NUMBERING in rule_set:
        if CLUSTER_CHAPTER_NUMERIC in cluster_set:
            m_ch = _CHAPTER_H1_RE.match(s)
            if m_ch and not _SENTENCE_END_RE.search(s):
                prefix = m_ch.group(1).strip()
                rest = (m_ch.group(2) or "").strip()
                if rest or len(s) <= 12:
                    return RuleHeadingMatch(
                        body_index=body_index,
                        level=1,
                        text=s,
                        rule_id=RULE_NUMBERING,
                        cluster=CLUSTER_CHAPTER_NUMERIC,
                        confidence=0.92 if emphasized else 0.88,
                        style_id=style_id,
                        prefix_token=prefix,
                        clean_title=rest or prefix,
                    )
            m_dot = _DOTTED_NUMBER_RE.match(s)
            if m_dot and not _SENTENCE_END_RE.search(s):
                num_token = m_dot.group(1)
                rest = m_dot.group(2).strip()
                parts = [int(p) for p in num_token.split(".")]
                if (
                    1 <= parts[0] <= 50
                    and all(0 <= p <= 99 for p in parts[1:])
                    and not _MEASUREMENT_UNIT_RE.match(rest)
                    and re.search(r"[\u4e00-\u9fa5A-Za-z]", rest)
                ):
                    lvl = min(4, len(parts))
                    return RuleHeadingMatch(
                        body_index=body_index,
                        level=lvl,
                        text=s,
                        rule_id=RULE_NUMBERING,
                        cluster=CLUSTER_CHAPTER_NUMERIC,
                        confidence=0.90 if emphasized else 0.85,
                        style_id=style_id,
                        prefix_token=num_token,
                        clean_title=rest,
                    )

        if CLUSTER_CHINESE_OFFICIAL in cluster_set and not _SENTENCE_END_RE.search(s):
            m_off1 = _OFFICIAL_H1_RE.match(s)
            if m_off1:
                return RuleHeadingMatch(
                    body_index=body_index,
                    level=1,
                    text=s,
                    rule_id=RULE_NUMBERING,
                    cluster=CLUSTER_CHINESE_OFFICIAL,
                    confidence=0.90 if emphasized else 0.86,
                    style_id=style_id,
                    prefix_token=m_off1.group(1),
                    clean_title=m_off1.group(2).strip(),
                )
            m_off2 = _OFFICIAL_H2_RE.match(s)
            if m_off2:
                return RuleHeadingMatch(
                    body_index=body_index,
                    level=2,
                    text=s,
                    rule_id=RULE_NUMBERING,
                    cluster=CLUSTER_CHINESE_OFFICIAL,
                    confidence=0.88 if emphasized else 0.84,
                    style_id=style_id,
                    prefix_token=m_off2.group(1),
                    clean_title=m_off2.group(2).strip(),
                )
            m_off3 = _OFFICIAL_H3_RE.match(s)
            if m_off3 and len(m_off3.group(2).strip()) <= 36:
                return RuleHeadingMatch(
                    body_index=body_index,
                    level=3,
                    text=s,
                    rule_id=RULE_NUMBERING,
                    cluster=CLUSTER_CHINESE_OFFICIAL,
                    confidence=0.84 if emphasized else 0.80,
                    style_id=style_id,
                    prefix_token=m_off3.group(1),
                    clean_title=m_off3.group(2).strip(),
                )
            m_off4 = _OFFICIAL_H4_RE.match(s)
            if m_off4 and len(m_off4.group(2).strip()) <= 36:
                return RuleHeadingMatch(
                    body_index=body_index,
                    level=4,
                    text=s,
                    rule_id=RULE_NUMBERING,
                    cluster=CLUSTER_CHINESE_OFFICIAL,
                    confidence=0.82 if emphasized else 0.78,
                    style_id=style_id,
                    prefix_token=m_off4.group(1),
                    clean_title=m_off4.group(2).strip(),
                )

        if CLUSTER_APPENDIX in cluster_set and not _SENTENCE_END_RE.search(s):
            m_app1 = _APPENDIX_H1_RE.match(s)
            if m_app1:
                prefix = m_app1.group(1).strip()
                rest = (m_app1.group(2) or "").strip()
                return RuleHeadingMatch(
                    body_index=body_index,
                    level=1,
                    text=s,
                    rule_id=RULE_NUMBERING,
                    cluster=CLUSTER_APPENDIX,
                    confidence=0.90,
                    style_id=style_id,
                    prefix_token=prefix,
                    clean_title=rest or prefix,
                )
            m_appsub = _APPENDIX_SUB_RE.match(s)
            if m_appsub:
                num_token = m_appsub.group(1)
                rest = m_appsub.group(2).strip()
                lvl = min(4, num_token.count(".") + 1)
                return RuleHeadingMatch(
                    body_index=body_index,
                    level=lvl,
                    text=s,
                    rule_id=RULE_NUMBERING,
                    cluster=CLUSTER_APPENDIX,
                    confidence=0.86,
                    style_id=style_id,
                    prefix_token=num_token,
                    clean_title=rest,
                )

    # P4: 业务条目锚点（[REQ-001] / SRS-001 / TC-001）
    if (
        (RULE_ITEM_ANCHOR in rule_set or CLUSTER_ITEM_ANCHOR in cluster_set)
        and split_item_anchors
        and not _SENTENCE_END_RE.search(s)
    ):
        m_item = _ITEM_ANCHOR_RE.match(s)
        if m_item:
            tag = m_item.group(1).strip()
            rest = m_item.group(2).strip()
            lvl = min(4, max(2, int(parent_level or 1) + 1))
            return RuleHeadingMatch(
                body_index=body_index,
                level=lvl,
                text=s,
                rule_id=RULE_ITEM_ANCHOR,
                cluster=CLUSTER_ITEM_ANCHOR,
                confidence=0.86 if emphasized else 0.82,
                style_id=style_id,
                prefix_token=tag,
                clean_title=rest,
            )

    return None


def _para_typography(p_elem) -> Tuple[bool, int, Optional[int], bool]:
    """提取段落的视觉强调特征：(是否加粗, 最大字号半点值, numPr的ilvl, 是否居中)。"""
    is_bold = False
    max_sz = 0
    ilvl: Optional[int] = None
    is_centered = False

    pPr = p_elem.find(_qn("pPr"))
    if pPr is not None:
        jc = pPr.find(_qn("jc"))
        if jc is not None and jc.get(_qn("val"), "") == "center":
            is_centered = True
        numPr = pPr.find(_qn("numPr"))
        if numPr is not None:
            ilvl_el = numPr.find(_qn("ilvl"))
            if ilvl_el is not None:
                try:
                    ilvl = int(ilvl_el.get(_qn("val"), "0"))
                except (ValueError, TypeError):
                    ilvl = None
        rPr = pPr.find(_qn("rPr"))
        if rPr is not None:
            b = rPr.find(_qn("b"))
            if b is not None and b.get(_qn("val"), "1") not in ("0", "false"):
                is_bold = True
            sz = rPr.find(_qn("sz"))
            if sz is not None:
                try:
                    max_sz = max(max_sz, int(sz.get(_qn("val"), "0")))
                except (ValueError, TypeError):
                    pass

    run_texts = 0
    bold_runs = 0
    for r in p_elem.findall(_qn("r")):
        t_nodes = r.findall(_qn("t"))
        txt = "".join((t.text or "") for t in t_nodes).strip()
        if not txt:
            continue
        run_texts += 1
        rPr = r.find(_qn("rPr"))
        if rPr is not None:
            b = rPr.find(_qn("b"))
            if b is not None and b.get(_qn("val"), "1") not in ("0", "false"):
                bold_runs += 1
            sz = rPr.find(_qn("sz"))
            if sz is not None:
                try:
                    max_sz = max(max_sz, int(sz.get(_qn("val"), "0")))
                except (ValueError, TypeError):
                    pass
    if run_texts > 0 and bold_runs == run_texts:
        is_bold = True

    return is_bold, max_sz, ilvl, is_centered


def _para_plain_text(p_elem) -> str:
    parts: List[str] = []
    for node in p_elem.iter():
        tag = etree.QName(node).localname
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def recognize_document_headings(
    parts: Dict[str, bytes],
    heading_style_map: Optional[Dict[str, int]] = None,
    *,
    policy: Optional[SplitPolicy] = None,
) -> List[RuleHeadingMatch]:
    """扫描 ``word/document.xml``，按规则链识别全部候选标题（含样式与多规则启发式）。"""
    document_xml = parts.get("word/document.xml", b"")
    if not document_xml:
        return []
    root = parse_xml_safe(document_xml, "word/document.xml")
    body = root.find(_qn("body"))
    if body is None:
        return []

    effective_policy = policy or SplitPolicy.from_profile(PROFILE_AUTO_RULES)
    style_map = dict(heading_style_map or {})
    rule_set = set(effective_policy.recognition_rules or ALL_RECOGNITION_RULES)
    matches: List[RuleHeadingMatch] = []
    current_parent_level = 1

    for index, elem in enumerate(body):
        if etree.QName(elem).localname != "p":
            continue
        pPr = elem.find(_qn("pPr"))
        style_id = ""
        style_level: Optional[int] = None
        outline_level: Optional[int] = None

        if pPr is not None:
            pStyle = pPr.find(_qn("pStyle"))
            if pStyle is not None:
                style_id = pStyle.get(_qn("val")) or ""
                if RULE_STYLE in rule_set:
                    style_level = style_map.get(style_id)
                    if style_level is None and style_id:
                        style_level = infer_heading_level_from_style_id(style_id)
            if style_level is None and RULE_OUTLINE in rule_set:
                otl = pPr.find(_qn("outlineLvl"))
                if otl is not None:
                    try:
                        val = int(otl.get(_qn("val"), "-1"))
                        if 0 <= val <= 5:
                            outline_level = val + 1
                    except (ValueError, TypeError):
                        pass

        text = _para_plain_text(elem)
        has_img = bool(
            elem.find(".//" + _qn("drawing")) is not None
            or elem.find(".//" + _qn("pict")) is not None
            or any(etree.QName(n).localname == "imagedata" for n in elem.iter())
        )
        if not text and not has_img:
            continue

        # P1: 显式样式或 outlineLvl
        if style_level is not None or outline_level is not None:
            lvl = int(style_level if style_level is not None else outline_level)
            rule_id = RULE_STYLE if style_level is not None else RULE_OUTLINE
            matches.append(
                RuleHeadingMatch(
                    body_index=index,
                    level=lvl,
                    text=text,
                    rule_id=rule_id,
                    cluster=rule_id,
                    confidence=1.0 if style_level is not None else 0.95,
                    style_id=style_id or "Heading{0}".format(lvl),
                    clean_title=strip_heading_prefix(text, mode=effective_policy.numbering_mode),
                )
            )
            if 1 <= lvl <= 3:
                current_parent_level = lvl
            continue

        if not text:
            continue

        is_bold, max_sz, ilvl, is_centered = _para_typography(elem)

        # P2 ~ P4: 文本骨架、多级编号簇、业务条目锚点
        text_match = match_text_heading_rule(
            text,
            body_index=index,
            style_id=style_id,
            rules=effective_policy.recognition_rules,
            clusters=effective_policy.numbering_clusters,
            skeleton_titles=effective_policy.skeleton_titles,
            max_chars=effective_policy.max_heading_chars,
            is_bold=is_bold,
            font_half_pt=max_sz,
            parent_level=current_parent_level,
            split_item_anchors=effective_policy.split_item_anchors,
        )
        if text_match is not None:
            matches.append(text_match)
            if 1 <= text_match.level <= 3:
                current_parent_level = text_match.level
            continue

        # P3b: Word numPr 多级自动编号 + 强调排版特征（加粗或大字号）
        if (
            RULE_NUMPR in rule_set
            and ilvl is not None
            and 0 <= ilvl <= 3
            and (is_bold or max_sz >= 24)
            and len(text) <= min(45, effective_policy.max_heading_chars)
            and not _SENTENCE_END_RE.search(text)
        ):
            lvl = min(4, ilvl + 1)
            matches.append(
                RuleHeadingMatch(
                    body_index=index,
                    level=lvl,
                    text=text,
                    rule_id=RULE_NUMPR,
                    cluster=RULE_NUMPR,
                    confidence=0.82 if is_bold else 0.78,
                    style_id=style_id,
                    clean_title=strip_heading_prefix(text, mode=effective_policy.numbering_mode),
                )
            )
            if 1 <= lvl <= 3:
                current_parent_level = lvl
            continue

        # P3c: 显著排版视觉强调（加粗 + 大字号/居中 + 短标题无句末标点）
        if (
            is_bold
            and (max_sz >= 28 or (is_centered and max_sz >= 24))
            and len(text) <= min(32, effective_policy.max_heading_chars)
            and not _SENTENCE_END_RE.search(text)
        ):
            lvl = 1 if (max_sz >= 30 or is_centered) else 2
            matches.append(
                RuleHeadingMatch(
                    body_index=index,
                    level=lvl,
                    text=text,
                    rule_id="typography_emphasis",
                    cluster="typography_emphasis",
                    confidence=0.80 if is_centered else 0.76,
                    style_id=style_id,
                    clean_title=strip_heading_prefix(text, mode=effective_policy.numbering_mode),
                )
            )
            if 1 <= lvl <= 3:
                current_parent_level = lvl

    # 若全部命中结果里没有任何 1 级标题，但有 2~4 级标题，平移顶层到 1 级以闭合章节树
    if matches and not any(m.level == 1 for m in matches):
        min_lvl = min(m.level for m in matches)
        if min_lvl > 1:
            offset = min_lvl - 1
            matches = [
                RuleHeadingMatch(
                    body_index=m.body_index,
                    level=max(1, m.level - offset),
                    text=m.text,
                    rule_id=m.rule_id,
                    cluster=m.cluster,
                    confidence=m.confidence,
                    style_id=m.style_id,
                    prefix_token=m.prefix_token,
                    clean_title=m.clean_title,
                )
                for m in matches
            ]

    return matches


def build_paragraph_level_map(matches: Sequence[RuleHeadingMatch]) -> Dict[int, int]:
    """将标题识别结果转换为 ``{body_index: level}`` 段落级映射。"""
    return {int(m.body_index): int(m.level) for m in (matches or ()) if 1 <= int(m.level) <= 6}


__all__ = [
    "RULE_STYLE",
    "RULE_OUTLINE",
    "RULE_SKELETON",
    "RULE_NUMBERING",
    "RULE_NUMPR",
    "RULE_ITEM_ANCHOR",
    "ALL_RECOGNITION_RULES",
    "STYLE_ONLY_RULES",
    "CLUSTER_CHAPTER_NUMERIC",
    "CLUSTER_CHINESE_OFFICIAL",
    "CLUSTER_APPENDIX",
    "CLUSTER_ITEM_ANCHOR",
    "ALL_NUMBERING_CLUSTERS",
    "PROFILE_STANDARD",
    "PROFILE_COMPACT",
    "PROFILE_CHAPTER_ONLY",
    "PROFILE_DEEP_ITEM",
    "PROFILE_PRESERVE_NUMBERING",
    "PROFILE_AUTO_RULES",
    "VALID_PROFILES",
    "NUMBERING_AUTO_STANDARD",
    "NUMBERING_PRESERVE_SEMANTIC",
    "NUMBERING_CLEAN_TITLE",
    "RuleHeadingMatch",
    "SplitPolicy",
    "strip_heading_prefix",
    "match_text_heading_rule",
    "recognize_document_headings",
    "build_paragraph_level_map",
]
