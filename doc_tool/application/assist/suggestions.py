# -*- coding: utf-8 -*-
"""V3.3 33-B 确定性建议与修订摘要候选（无模型即可用）。

建议只来源于**已有事实**（design.md D2）：

- 规范/质量规则：``required_section``（已声明但未填写的要点）、
  ``field_completeness``、``todo_residual`` 复用既有 ``ContentLinter``。
- 术语库：``term_case`` 与显式别名映射，给出确定替代措辞。
- 引用事实：``ReferenceScanner`` 的悬空引用（不猜目标）。
- 复核事实：``ReviewRecordStore.pending()``（只提示，不改状态）。
- 本地改动：``build_change_items`` + ``build_revision_record`` 生成修订摘要候选。

每个 suggestion 都带 id/kind/证据/目标范围/baseHash/before-after/状态/origin/
coverage；``not_evidence`` 固定 True——建议永远不是需求满足、测试通过或正式
门禁证据。目标变化时 ``refresh`` 重算或标冲突，冲突项保留用户内容。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from doc_tool.application.content.changes import ChangeItem, build_change_items
from doc_tool.application.content.index import ContentIndexService, slugify_heading
from doc_tool.application.content.lint import ContentLinter, LintIssue
from doc_tool.application.content.quality_rules import QualityRulesConfig
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.revision_record import build_revision_record
from doc_tool.application.quality_location import load_terms_with_fallback
from doc_tool.application.assist.search_local import EvidenceSource, LocalEvidenceSearch
from doc_tool.domain.content_index import (
    ContentIndex, FileEntry, HeadingEntry, path_natural_sort_key,
)

from doc_tool.application.assist.models import (
    APPLY_INSERT, APPLY_NONE, APPLY_REPLACE,
    COVERAGE_FULL, COVERAGE_INSUFFICIENT, COVERAGE_LABELS, COVERAGE_PARTIAL,
    KIND_FILL, KIND_LABELS, KIND_REFERENCE, KIND_REVIEW, KIND_REVISION_SUMMARY,
    KIND_TERM, KINDS, ORIGIN_LABELS, ORIGIN_LOCAL, ORIGIN_RULE,
    STATUS_ACCEPTED, STATUS_CONFLICT, STATUS_IGNORED, STATUS_LABELS,
    STATUS_PROPOSED, STATUS_STALE, STATUS_UNAVAILABLE,
    display_path, hash_text, text_lines,
    KIND_MODULE_UPDATE,
)

#: 章节缺失提示中提取标题（与 lint.check_required_sections 的文案一致）。
_REQUIRED_TITLE_RE = re.compile(r"缺少必备章节：(.+?)(?:；|$)")
#: 术语大小写问题文案中提取（实际写法，规范写法）。
_TERM_CASE_RE = re.compile(r"不一致：(.+?)（应为\s*(.+?)）")
#: 标题行（与内容索引同一口径）。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

#: 填写提示占位文案：只提示待填写，不伪造实现/测试事实。
FILL_PROMPT = "> 待填写：{0}。请补充本节要点后再复核。"

#: 事实声明：所有建议共用（不构成通过证据）。
FACTS_NOTE = (
    "建议来自现有规则/术语/引用/复核/变更事实，不构成需求满足、测试通过或正式门禁证据。"
)

_KIND_ORDER = {
    KIND_FILL: 0, KIND_TERM: 1, KIND_REFERENCE: 2, KIND_REVIEW: 3,
    KIND_REVISION_SUMMARY: 4,
    KIND_MODULE_UPDATE: 5,
}


def _version_key(value: str):
    """把模块版本号转成可比较元组（非数字段退化为字符串）。"""
    parts = []
    for chunk in str(value or "").replace("-", ".").split("."):
        parts.append(int(chunk) if chunk.isdigit() else chunk)
    return tuple(parts)


@dataclass
class SuggestionEvidence:
    """一条依据（来源事实 + 定位）。"""

    kind: str
    label: str
    detail: str = ""
    source_ref: str = ""
    locator: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "sourceRef": self.source_ref,
            "locator": self.locator,
        }


@dataclass
class Suggestion:
    """一条可查看、可选择采纳/忽略的建议。"""

    suggestion_id: str
    kind: str
    title: str
    detail: str = ""
    rationale: str = ""
    evidence: List[SuggestionEvidence] = field(default_factory=list)
    target_rel_path: str = ""
    start_line: int = 0
    end_line: int = 0
    range_label: str = ""
    base_hash: str = ""
    before: str = ""
    after: str = ""
    apply_mode: str = APPLY_NONE
    status: str = STATUS_PROPOSED
    origin: str = ORIGIN_RULE
    coverage: str = COVERAGE_FULL
    editable: bool = True
    not_evidence: bool = True
    field_name: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return self.apply_mode != APPLY_NONE and bool(self.after) and self.status in (
            STATUS_PROPOSED, STATUS_STALE,
        )

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def origin_label(self) -> str:
        return ORIGIN_LABELS.get(self.origin, self.origin)

    @property
    def coverage_label(self) -> str:
        return COVERAGE_LABELS.get(self.coverage, self.coverage)

    def mark(self, status: str, note: str = "") -> "Suggestion":
        """更新状态并记录原因（冲突项保留用户内容，只标状态）。"""
        self.status = status
        if note and note not in self.notes:
            self.notes.append(note)
        return self

    def to_dict(self) -> dict:
        return {
            "suggestionId": self.suggestion_id,
            "kind": self.kind,
            "kindLabel": self.kind_label,
            "title": self.title,
            "detail": self.detail,
            "rationale": self.rationale,
            "evidence": [item.to_dict() for item in self.evidence],
            "targetRelPath": display_path(self.target_rel_path),
            "startLine": self.start_line,
            "endLine": self.end_line,
            "rangeLabel": self.range_label,
            "baseHash": self.base_hash,
            "before": self.before,
            "after": self.after,
            "applyMode": self.apply_mode,
            "applicable": self.applicable,
            "status": self.status,
            "statusLabel": self.status_label,
            "origin": self.origin,
            "originLabel": self.origin_label,
            "coverage": self.coverage,
            "coverageLabel": self.coverage_label,
            "editable": self.editable,
            "notEvidence": self.not_evidence,
            "field": self.field_name,
            "notes": list(self.notes),
        }


@dataclass
class SuggestionSet:
    """一次建议收集的结果（含覆盖度说明与事实声明）。"""

    suggestions: List[Suggestion] = field(default_factory=list)
    coverage_notes: List[str] = field(default_factory=list)
    facts_note: str = FACTS_NOTE

    def of_kind(self, kind: str) -> List[Suggestion]:
        return [item for item in self.suggestions if item.kind == kind]

    @property
    def applicable(self) -> List[Suggestion]:
        return [item for item in self.suggestions if item.applicable]

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.suggestions:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def summary_lines(self) -> List[str]:
        counts = self.counts()
        if not counts:
            lines = ["没有可用的本地建议（依据不足时不虚构内容）。"]
        else:
            lines = [
                "{0}：{1} 条".format(KIND_LABELS.get(kind, kind), counts[kind])
                for kind in sorted(counts, key=lambda item: _KIND_ORDER.get(item, 9))
            ]
        lines.extend(self.coverage_notes)
        return lines

    def to_dict(self) -> dict:
        return {
            "factsNote": self.facts_note,
            "coverageNotes": list(self.coverage_notes),
            "counts": self.counts(),
            "summary": self.summary_lines(),
            "suggestions": [item.to_dict() for item in self.suggestions],
        }

class SuggestionEngine:
    """用现有规则/术语/引用/复核/变更事实生成确定性建议。"""

    def __init__(
        self,
        *,
        index: Optional[ContentIndex] = None,
        rules_config=None,
        terms: Sequence[str] = (),
        term_aliases: Optional[Mapping[str, str]] = None,
        review_store=None,
        assets_root=None,
        project_root=None,
        document_type: str = "general",
        read_only: bool = False,
        change_items: Sequence[ChangeItem] = (),
        module_roots: Sequence[str] = (),
    ) -> None:
        self._index = index
        self._rules_config = rules_config
        self._terms: List[str] = [str(item).strip() for item in (terms or ()) if str(item).strip()]
        self._aliases: Dict[str, str] = {}
        for alias, canonical in (term_aliases or {}).items():
            key = str(alias).strip()
            value = str(canonical).strip()
            if key and value and key != value:
                self._aliases[key] = value
        self._review_store = review_store
        self._assets_root = Path(assets_root) if assets_root else None
        self._project_root = Path(project_root) if project_root else None
        self._document_type = document_type or "general"
        self._read_only = bool(read_only)
        self._change_items: List[ChangeItem] = list(change_items or ())
        self._references_scanned = False
        self._warnings: List[str] = []
        # 模块库（V3.0 模块来源的最小适配）：只作为建议依据，不自动复制内容。
        self._module_roots: List[str] = [str(item) for item in (module_roots or ()) if item]
        self._module_search: Optional[LocalEvidenceSearch] = None

    # --- 构造 ---

    @property
    def warnings(self) -> List[str]:
        return list(self._warnings)

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def index(self) -> Optional[ContentIndex]:
        return self._index

    @classmethod
    def from_project(
        cls,
        project_root,
        *,
        read_only: bool = False,
        terms: Sequence[str] = (),
        term_aliases: Optional[Mapping[str, str]] = None,
        buffers: Optional[Mapping[str, str]] = None,
        change_items: Sequence[ChangeItem] = (),
        module_roots: Sequence[str] = (),
    ) -> "SuggestionEngine":
        """按项目目录装配引擎（清单缺失时按 ``<root>/content`` 继续）。"""
        root = Path(project_root)
        content_root = root
        state_dir = root / ".state"
        assets_root = root / "assets"
        document_type = "general"
        warnings: List[str] = []
        try:
            from doc_tool.domain.manifest import ProjectManifest

            manifest = ProjectManifest.load(root)
            paths = manifest.resolve_paths(root)
            content_root = paths.content_root
            state_dir = paths.state_dir
            assets_root = paths.assets_root
            document_type = str(getattr(manifest, "documentType", "") or "general")
        except Exception as exc:  # noqa: BLE001 - 清单不可用仍给本地建议
            for candidate in (root / "content", root):
                if candidate.is_dir():
                    content_root = candidate
                    break
            warnings.append("项目清单不可用（{0}），已按内容目录继续。".format(exc))

        from doc_tool.application.content.impact import ReviewRecordStore

        engine = cls(
            index=ContentIndexService(content_root).build(),
            rules_config=QualityRulesConfig(state_dir, document_type),
            terms=terms,
            term_aliases=term_aliases,
            review_store=ReviewRecordStore(state_dir),
            assets_root=assets_root,
            project_root=root,
            document_type=document_type,
            read_only=read_only,
            change_items=change_items,
            module_roots=module_roots,
        )
        engine._warnings.extend(warnings)
        loaded_terms, term_warnings = load_terms_with_fallback(root)
        for term in loaded_terms:
            if term and term not in engine._terms:
                engine._terms.append(term)
        engine._warnings.extend(term_warnings)
        engine.apply_buffers(buffers)
        return engine

    # --- 缓冲叠加 ---

    def apply_buffers(self, buffers: Optional[Mapping[str, str]]) -> None:
        """把当前编辑缓冲叠加到索引，使建议基于作者正在看的内容。"""
        if not buffers or self._index is None:
            return
        for rel_path, content in buffers.items():
            rel = display_path(str(rel_path))
            if not rel:
                continue
            lines = text_lines(content or "")
            existing = self._index.files.get(rel)
            document_type = existing.document_type if existing is not None else self._document_type
            self._index.files[rel] = FileEntry(
                rel_path=rel, document_type=document_type, line_count=len(lines)
            )
            self._index.lines[rel] = lines
            self._index.headings[rel] = self._heading_entries(rel, lines)
            self._index.refresh(rel)
            self._index.document_types.add(document_type)

    @staticmethod
    def _heading_entries(rel_path: str, lines: Sequence[str]) -> List[HeadingEntry]:
        entries: List[HeadingEntry] = []
        for line_no, line in enumerate(lines, start=1):
            match = _HEADING_RE.match(line)
            if match is None:
                continue
            title = match.group(2)
            entries.append(HeadingEntry(
                rel_path=rel_path,
                line_no=line_no,
                level=len(match.group(1)),
                text=title,
                anchor_id=slugify_heading(title),
            ))
        return entries

    # --- 事实读取 ---

    def _text_of(self, rel_path: str) -> Optional[str]:
        if self._index is None or not rel_path:
            return None
        lines = self._index.lines.get(rel_path)
        if lines is None:
            return None
        return "\n".join(lines)

    def current_texts(self) -> Dict[str, str]:
        if self._index is None:
            return {}
        return {rel: "\n".join(lines) for rel, lines in self._index.lines.items()}

    def _insert_target(self) -> Tuple[str, int]:
        """缺失章节的建议插入位置：优先 ``_index.md``，否则第一个内容文件。"""
        index = self._index
        if index is None or not index.files:
            return "", 1
        files = index.all_files()
        preferred = [rel for rel in files if Path(rel).name == "_index.md"] or files
        target = preferred[0]
        return target, len(index.lines.get(target, [])) + 1

    def _issues(self) -> List[LintIssue]:
        if self._index is None:
            return []
        try:
            return ContentLinter(self._index, self._rules_config).check_all(list(self._terms))
        except Exception as exc:  # noqa: BLE001 - 规则不可用不阻断其余建议
            self._warnings.append("质量规则检查不可用（{0}），已跳过规则类建议。".format(exc))
            return []

    def _module_evidence(self, needle: str, *, limit: int = 2) -> List[SuggestionEvidence]:
        """在显式加入的模块库中查找可复用要点（只作依据，不自动复制）。"""
        if not needle or not self._module_roots:
            return []
        if self._module_search is None:
            sources = [
                EvidenceSource.from_module(root) for root in self._module_roots if root
            ]
            self._module_search = LocalEvidenceSearch(sources, cache_enabled=False)
        try:
            outcome = self._module_search.search(needle, limit=limit)
        except Exception as exc:  # noqa: BLE001 - 模块库不可用不影响其余建议
            self._warnings.append("模块库检索不可用（{0}），已跳过模块依据。".format(exc))
            return []
        evidence: List[SuggestionEvidence] = []
        for hit in outcome.hits[:limit]:
            evidence.append(SuggestionEvidence(
                kind="module",
                label="模块库可复用要点",
                detail="命中：{0}".format(hit.text.strip()[:80]),
                source_ref=hit.source_id,
                locator="{0} · {1}:{2}".format(hit.source_label, hit.rel_path, hit.line_no),
            ))
        return evidence

    def _ensure_references(self) -> None:
        if self._index is None or self._references_scanned:
            return
        try:
            ReferenceScanner(self._index, self._assets_root).scan_all()
        except Exception as exc:  # noqa: BLE001 - 引用扫描失败不阻断编辑
            self._warnings.append("引用扫描不可用（{0}），已跳过引用类建议。".format(exc))
        self._references_scanned = True
    # --- 收集：填写提示 / 遗漏清单 ---

    def collect_fill_suggestions(
        self, issues: Sequence[LintIssue], *, max_items: int = 20
    ) -> List[Suggestion]:
        result: List[Suggestion] = []
        for issue in issues or ():
            if len(result) >= max_items:
                break
            if issue.rule_id == "required_section":
                match = _REQUIRED_TITLE_RE.search(issue.message or "")
                title = match.group(1).strip() if match else "必备章节"
                target, insert_line = self._insert_target()
                current = self._text_of(target) or ""
                after = "## {0}\n\n{1}".format(title, FILL_PROMPT.format(title))
                evidence = [SuggestionEvidence(
                    kind="rule", label="质量规则 required_section",
                    detail=issue.message, source_ref="required_section",
                    locator=issue.rel_path or "(文档级)",
                )]
                module_evidence = self._module_evidence(title)
                evidence.extend(module_evidence)
                notes = ["插入位置为建议值，请确认章节顺序；内容仍需作者填写。"]
                if module_evidence:
                    notes.append("模块库存在同名要点，可核对后复用（不自动复制内容）。")
                result.append(Suggestion(
                    suggestion_id="fill:{0}".format(title),
                    kind=KIND_FILL,
                    title="缺少必备章节：{0}".format(title),
                    detail=issue.message,
                    rationale="规范声明了该章节，索引中尚未出现同名标题；只给填写提示与占位。",
                    evidence=evidence,
                    target_rel_path=target,
                    start_line=insert_line,
                    end_line=insert_line,
                    range_label="{0} 文件末尾（建议位置）".format(display_path(target)),
                    base_hash=hash_text(current),
                    before="",
                    after=after,
                    apply_mode=APPLY_INSERT,
                    origin=ORIGIN_RULE,
                    coverage=COVERAGE_PARTIAL,
                    notes=notes,
                ))
            elif issue.rule_id == "field_completeness":
                result.append(Suggestion(
                    suggestion_id="fill:field:{0}:{1}".format(issue.rel_path, issue.line_no),
                    kind=KIND_FILL,
                    title="字段待补全",
                    detail=issue.message,
                    rationale="规则声明了字段完整性要求；没有依据可自动填写取值。",
                    evidence=[SuggestionEvidence(
                        kind="rule", label="质量规则 field_completeness",
                        detail=issue.message, source_ref="field_completeness",
                        locator="{0}:{1}".format(issue.rel_path, issue.line_no),
                    )],
                    target_rel_path=issue.rel_path,
                    start_line=issue.line_no,
                    end_line=issue.line_no,
                    range_label="{0}:{1}".format(display_path(issue.rel_path), issue.line_no),
                    apply_mode=APPLY_NONE,
                    origin=ORIGIN_RULE,
                    coverage=COVERAGE_INSUFFICIENT,
                    notes=["没有依据可自动填写，请在正文中补充实际取值。"],
                ))
            elif issue.rule_id == "todo_residual":
                result.append(Suggestion(
                    suggestion_id="fill:todo:{0}:{1}".format(issue.rel_path, issue.line_no),
                    kind=KIND_FILL,
                    title="未完成项待处理",
                    detail=issue.message,
                    rationale="正文中仍有 TODO/待补充标记，属遗漏清单提示。",
                    evidence=[SuggestionEvidence(
                        kind="rule", label="质量规则 todo_residual",
                        detail=issue.message, source_ref="todo_residual",
                        locator="{0}:{1}".format(issue.rel_path, issue.line_no),
                    )],
                    target_rel_path=issue.rel_path,
                    start_line=issue.line_no,
                    end_line=issue.line_no,
                    range_label="{0}:{1}".format(display_path(issue.rel_path), issue.line_no),
                    apply_mode=APPLY_NONE,
                    origin=ORIGIN_RULE,
                    coverage=COVERAGE_INSUFFICIENT,
                    notes=["只提示待补内容，不自动改写正文。"],
                ))
        return result

    # --- 收集：术语措辞 ---

    def collect_term_suggestions(
        self, issues: Optional[Sequence[LintIssue]] = None, *, max_items: int = 50
    ) -> List[Suggestion]:
        result: List[Suggestion] = []
        seen = set()
        for issue in issues or ():
            if issue.rule_id != "term_case" or len(result) >= max_items:
                continue
            match = _TERM_CASE_RE.search(issue.message or "")
            if match is None:
                continue
            found = match.group(1).strip()
            canonical = match.group(2).strip()
            if not found or not canonical or found == canonical:
                continue
            key = ("case", issue.rel_path, issue.line_no, found)
            if key in seen:
                continue
            seen.add(key)
            current = self._text_of(issue.rel_path) or ""
            result.append(Suggestion(
                suggestion_id="term:{0}:{1}:{2}".format(issue.rel_path, issue.line_no, found),
                kind=KIND_TERM,
                title="术语写法：{0} -> {1}".format(found, canonical),
                detail=issue.message,
                rationale="术语库登记了规范写法；替换只改这一处措辞。",
                evidence=[SuggestionEvidence(
                    kind="term", label="术语库（大小写）",
                    detail="规范写法：{0}".format(canonical), source_ref="term_case",
                    locator="{0}:{1}".format(issue.rel_path, issue.line_no),
                )],
                target_rel_path=issue.rel_path,
                start_line=issue.line_no,
                end_line=issue.line_no,
                range_label="{0}:{1}".format(display_path(issue.rel_path), issue.line_no),
                base_hash=hash_text(current),
                before=found,
                after=canonical,
                apply_mode=APPLY_REPLACE,
                origin=ORIGIN_LOCAL,
                coverage=COVERAGE_FULL,
            ))
        if self._index is not None and len(result) < max_items:
            for alias in sorted(self._aliases):
                canonical = self._aliases[alias]
                for rel_path in self._index.all_files():
                    for line_no, line in enumerate(self._index.lines.get(rel_path, []), start=1):
                        if len(result) >= max_items:
                            break
                        if alias not in line:
                            continue
                        key = ("alias", rel_path, line_no, alias)
                        if key in seen:
                            continue
                        seen.add(key)
                        result.append(Suggestion(
                            suggestion_id="term-alias:{0}:{1}:{2}".format(rel_path, line_no, alias),
                            kind=KIND_TERM,
                            title="术语别名：{0} -> {1}".format(alias, canonical),
                            detail="第 {0} 行使用了别名“{1}”。".format(line_no, alias),
                            rationale="术语别名映射确定了规范写法；仅替换该处措辞。",
                            evidence=[SuggestionEvidence(
                                kind="term", label="术语别名映射",
                                detail="{0} -> {1}".format(alias, canonical),
                                source_ref="term-alias",
                                locator="{0}:{1}".format(rel_path, line_no),
                            )],
                            target_rel_path=rel_path,
                            start_line=line_no,
                            end_line=line_no,
                            range_label="{0}:{1}".format(display_path(rel_path), line_no),
                            base_hash=hash_text(self._text_of(rel_path) or ""),
                            before=alias,
                            after=canonical,
                            apply_mode=APPLY_REPLACE,
                            origin=ORIGIN_LOCAL,
                            coverage=COVERAGE_FULL,
                        ))
        return result[:max_items]

    # --- 收集：引用 / 复核 ---

    def collect_reference_suggestions(self, *, max_items: int = 50) -> List[Suggestion]:
        self._ensure_references()
        index = self._index
        if index is None:
            return []
        result: List[Suggestion] = []
        for rel_path in sorted(index.references.keys(), key=path_natural_sort_key):
            for ref in index.references.get(rel_path, []):
                if not ref.dangling or len(result) >= max_items:
                    continue
                locator = "{0}:{1}".format(rel_path, ref.source_line)
                severity = "确定缺失" if ref.dangling_kind == "confirmed" else "疑似（需人工确认）"
                result.append(Suggestion(
                    suggestion_id="ref:{0}:{1}:{2}".format(rel_path, ref.source_line, ref.target),
                    kind=KIND_REFERENCE,
                    title="引用待处理：{0}".format(ref.target),
                    detail="{0}（{1}）".format(ref.source_text.strip(), severity),
                    rationale="引用解析结果显示目标不存在；不猜测目标，只提示人工确认。",
                    evidence=[SuggestionEvidence(
                        kind="reference", label="引用事实（{0}）".format(severity),
                        detail="目标：{0}".format(ref.target), source_ref=ref.kind,
                        locator=locator,
                    )],
                    target_rel_path=rel_path,
                    start_line=ref.source_line,
                    end_line=ref.source_line,
                    range_label=locator,
                    apply_mode=APPLY_NONE,
                    origin=ORIGIN_LOCAL,
                    coverage=COVERAGE_PARTIAL,
                    notes=["引用目标需人工确认，工具不自动改写链接。"],
                ))
        return result[:max_items]

    def collect_module_update_suggestions(self, *, max_items: int = 50) -> List[Suggestion]:
        """固定引用的模块有新版本（或声明的版本不在库里）→ 只提示，不改装配。

        复用 V3.0 的装配与模块库身份/版本接口：``assembly.yml`` 的每个 slot 对照库中
        可用版本；升级仍由用户显式执行 ``reuse upgrade``（本建议 ``applyMode=none``）。
        """
        root = getattr(self, "_project_root", None)
        if root is None:
            return []
        try:
            from doc_tool.application.content import reuse_commands as reuse

            context = reuse.load_context(root)
        except Exception as exc:  # noqa: BLE001 - 复用能力不可用时跳过该类建议
            self._warnings.append("模块装配不可用（{0}），已跳过模块更新提示。".format(exc))
            return []
        assembly = getattr(context, "assembly", None)
        library = getattr(context, "library", None)
        if assembly is None or library is None:
            return []
        result: List[Suggestion] = []
        for slot in list(getattr(assembly, "slots", []) or []):
            if len(result) >= max_items:
                break
            module_id = str(slot.moduleId or "")
            current = str(slot.version or "")
            if not module_id:
                continue
            versions = [str(item) for item in (library.versions(module_id) or [])]
            if not versions:
                result.append(Suggestion(
                    suggestion_id="module:{0}:missing".format(slot.slotId),
                    kind=KIND_MODULE_UPDATE,
                    title="模块版本缺失：{0}@{1}".format(module_id, current or "未指定"),
                    detail="库中找不到该模块的任何版本；出稿将使用项目内固定副本或占位。",
                    rationale="先导入/发布该模块，或改指向已有版本；本提示不改装配。",
                    target_rel_path=str(slot.chapter or ""),
                    apply_mode=APPLY_NONE,
                    evidence=[SuggestionEvidence(
                        kind="module-assembly",
                        label="装配 slot {0}".format(slot.slotId),
                        detail="reuse/assembly.yml",
                        locator="reuse/assembly.yml",
                    )],
                ))
                continue
            latest = sorted(versions, key=lambda item: _version_key(item))[-1]
            if latest == current or _version_key(latest) <= _version_key(current):
                continue
            result.append(Suggestion(
                suggestion_id="module:{0}:{1}->{2}".format(
                    slot.slotId, current or "none", latest
                ),
                kind=KIND_MODULE_UPDATE,
                title="模块可升级：{0} {1} → {2}".format(module_id, current or "未指定", latest),
                detail="库中最新版本为 {0}；当前固定 {1}（slot {2}，章节 {3}）。".format(
                    latest, current or "未指定", slot.slotId, slot.chapter or "未记录",
                ),
                rationale=(
                    "升级是可选动作：确认后执行 reuse upgrade --module {0} --to {1} --slot {2}"
                    "（默认只预览，--apply 才写装配）。".format(module_id, latest, slot.slotId)
                ),
                target_rel_path=str(slot.chapter or ""),
                apply_mode=APPLY_NONE,
                evidence=[SuggestionEvidence(
                    kind="module-assembly",
                    label="装配 slot {0}（当前 {1}）".format(slot.slotId, current or "未指定"),
                    detail="模块库可用版本：{0}".format("、".join(versions)),
                    locator="reuse/assembly.yml",
                )],
            ))
        return result

    def collect_review_suggestions(self, *, max_items: int = 50) -> List[Suggestion]:
        store = self._review_store
        if store is None:
            return []
        try:
            pending = store.pending()
        except Exception as exc:  # noqa: BLE001 - 复核记录不可用不阻断编辑
            self._warnings.append("复核记录不可用（{0}），已跳过复核提示。".format(exc))
            return []
        result: List[Suggestion] = []
        for record in pending[:max_items]:
            source = "{0}/{1}".format(*record.source)
            target = "{0}/{1}".format(*record.target)
            result.append(Suggestion(
                suggestion_id="review:{0}".format(record.relation_id or "{0}->{1}".format(source, target)),
                kind=KIND_REVIEW,
                title="待复核关系：{0} -> {1}".format(source, target),
                detail="复核状态：{0}".format(record.status),
                rationale="复核记录显示该关系尚未通过；提示只读，不改复核状态。",
                evidence=[SuggestionEvidence(
                    kind="review", label="复核记录",
                    detail="status={0}；reviewer={1}".format(record.status, record.reviewer or "未登记"),
                    source_ref=record.relation_id, locator="{0} -> {1}".format(source, target),
                )],
                range_label="{0} -> {1}".format(source, target),
                apply_mode=APPLY_NONE,
                origin=ORIGIN_LOCAL,
                coverage=COVERAGE_INSUFFICIENT,
                notes=["采纳建议不会自动把该项标记为通过。"],
            ))
        return result

    # --- 收集：修订摘要候选 ---

    def revision_summary_candidates(
        self,
        *,
        change_items: Optional[Sequence[ChangeItem]] = None,
        status_map: Optional[Mapping[str, str]] = None,
        max_items: int = 2,
    ) -> List[Suggestion]:
        items = list(change_items if change_items is not None else self._change_items)
        if not items and status_map:
            items = build_change_items(dict(status_map))
        if not items:
            return [Suggestion(
                suggestion_id="summary:none",
                kind=KIND_REVISION_SUMMARY,
                title="修订摘要候选（未检测到本地改动）",
                detail="未提供本地改动或变更快照。",
                rationale="没有本地改动事实时不生成摘要，避免虚构修订内容。",
                apply_mode=APPLY_NONE,
                origin=ORIGIN_LOCAL,
                coverage=COVERAGE_INSUFFICIENT,
                field_name="revision-summary",
                notes=["摘要只填原修订框；无改动时保持空白。"],
            )][:max_items]
        counts: Dict[str, int] = {}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
        evidence = [SuggestionEvidence(
            kind="change",
            label="本地改动 {0} 项".format(len(items)),
            detail="新增 {0}／修改 {1}／删除 {2}".format(
                counts.get("added", 0), counts.get("modified", 0), counts.get("deleted", 0)
            ),
            source_ref="change-items",
            locator="、".join(display_path(item.rel_path) for item in items[:5]),
        )]
        candidates: List[Suggestion] = []
        text = build_revision_record(items)
        if text:
            candidates.append(Suggestion(
                suggestion_id="summary:sections",
                kind=KIND_REVISION_SUMMARY,
                title="修订摘要候选（章节定位）",
                detail=text,
                after=text,
                rationale="按当前选定变更的文件/条目事实生成，可编辑后进入现有修订对话框。",
                evidence=list(evidence),
                apply_mode=APPLY_NONE,
                origin=ORIGIN_LOCAL,
                coverage=COVERAGE_FULL,
                field_name="revision-summary",
                notes=["采纳只填原修订框；新增修订记录仍由原追加确认动作执行。"],
            ))
        stat_line = "本次修订：新增 {0} 项、修改 {1} 项、删除 {2} 项。".format(
            counts.get("added", 0), counts.get("modified", 0), counts.get("deleted", 0)
        )
        candidates.append(Suggestion(
            suggestion_id="summary:counts",
            kind=KIND_REVISION_SUMMARY,
            title="修订摘要候选（改动统计）",
            detail=stat_line,
            after=stat_line,
            rationale="统计口径为本地改动清单；正文语义由作者补写。",
            evidence=list(evidence),
            apply_mode=APPLY_NONE,
            origin=ORIGIN_LOCAL,
            coverage=COVERAGE_PARTIAL,
            field_name="revision-summary",
            notes=["只统计条目数量，不推断改动语义。"],
        ))
        return candidates[:max_items]
    # --- 汇总入口 ---

    def collect(
        self,
        *,
        kinds: Optional[Sequence[str]] = None,
        change_items: Optional[Sequence[ChangeItem]] = None,
        status_map: Optional[Mapping[str, str]] = None,
        buffers: Optional[Mapping[str, str]] = None,
        max_fill: int = 20,
        max_terms: int = 50,
        max_references: int = 50,
        max_reviews: int = 50,
    ) -> SuggestionSet:
        """按种类收集建议；未实现的种类不出现，也不影响其他种类。"""
        wanted = [kind for kind in (kinds or KINDS) if kind in KINDS]
        if buffers:
            self.apply_buffers(buffers)
        result = SuggestionSet()
        if self._index is None:
            result.coverage_notes.append(
                "未提供内容索引：规则/术语/引用类建议不可用，其余本地能力不受影响。"
            )
        issues: List[LintIssue] = []
        if {KIND_FILL, KIND_TERM} & set(wanted):
            issues = self._issues()
        if KIND_FILL in wanted:
            result.suggestions.extend(self.collect_fill_suggestions(issues, max_items=max_fill))
        if KIND_TERM in wanted:
            result.suggestions.extend(self.collect_term_suggestions(issues, max_items=max_terms))
        if KIND_REFERENCE in wanted:
            result.suggestions.extend(self.collect_reference_suggestions(max_items=max_references))
        if KIND_REVIEW in wanted:
            result.suggestions.extend(self.collect_review_suggestions(max_items=max_reviews))
        if KIND_MODULE_UPDATE in wanted:
            result.suggestions.extend(self.collect_module_update_suggestions(max_items=max_reviews))
        if KIND_REVISION_SUMMARY in wanted:
            result.suggestions.extend(
                self.revision_summary_candidates(change_items=change_items, status_map=status_map)
            )
        unique: Dict[str, Suggestion] = {}
        for item in result.suggestions:
            unique.setdefault(item.suggestion_id, item)
        result.suggestions = sorted(
            unique.values(),
            key=lambda item: (
                _KIND_ORDER.get(item.kind, 9),
                path_natural_sort_key(item.target_rel_path or ""),
                item.start_line,
                item.suggestion_id,
            ),
        )
        result.coverage_notes.extend(self._warnings)
        result.coverage_notes.append(
            "建议覆盖：{0} 条可采纳、{1} 条仅提示；采纳不改变复核/版本状态。".format(
                len(result.applicable), len(result.suggestions) - len(result.applicable)
            )
        )
        return result

    # --- 刷新（目标变化重算/跳过冲突） ---

    def refresh(
        self,
        suggestions: Sequence[Suggestion],
        *,
        change_items: Optional[Sequence[ChangeItem]] = None,
        status_map: Optional[Mapping[str, str]] = None,
        buffers: Optional[Mapping[str, str]] = None,
    ) -> List[Suggestion]:
        """重算 baseHash；目标变化的建议重定位或标冲突，冲突项保留用户内容。"""
        if buffers:
            self.apply_buffers(buffers)
        for item in suggestions or ():
            if item.status in (STATUS_ACCEPTED, STATUS_IGNORED):
                continue
            if item.kind == KIND_REVISION_SUMMARY:
                regenerated = self.revision_summary_candidates(
                    change_items=change_items, status_map=status_map
                )
                for candidate in regenerated:
                    if candidate.suggestion_id == item.suggestion_id:
                        if candidate.after != item.after:
                            item.after = candidate.after
                            item.detail = candidate.detail
                            item.mark(STATUS_PROPOSED, "已按最新本地改动重算摘要候选。")
                        else:
                            item.mark(STATUS_PROPOSED)
                        item.coverage = candidate.coverage
                        item.evidence = list(candidate.evidence)
                        break
                continue
            if item.apply_mode == APPLY_NONE:
                continue
            current = self._text_of(item.target_rel_path)
            if current is None:
                item.mark(STATUS_UNAVAILABLE, "目标文件不在当前范围，建议不可用（其余建议继续）。")
                item.coverage = COVERAGE_INSUFFICIENT
                continue
            current_hash = hash_text(current)
            if current_hash == item.base_hash:
                if item.status in (STATUS_STALE, STATUS_CONFLICT):
                    item.mark(STATUS_PROPOSED)
                continue
            if item.apply_mode == APPLY_REPLACE:
                occurrences = self._occurrences(current, item.before)
                total_matches = current.count(item.before) if item.before else 0
                if total_matches == 1 and occurrences:
                    item.start_line = occurrences[0]
                    item.end_line = occurrences[0]
                    item.range_label = "{0}:{1}".format(
                        display_path(item.target_rel_path), occurrences[0]
                    )
                    item.base_hash = current_hash
                    item.mark(STATUS_PROPOSED, "目标已变化，已按当前位置重算。")
                elif not total_matches:
                    item.mark(STATUS_CONFLICT, "目标内容已被修改，保留用户内容并跳过该建议。")
                else:
                    item.mark(STATUS_CONFLICT, "目标存在多处匹配，保留用户内容并跳过该建议。")
            else:  # APPLY_INSERT
                item.base_hash = current_hash
                if item.after and item.after.strip() and item.after.strip() in current:
                    item.mark(STATUS_CONFLICT, "目标中已存在同名内容，跳过该建议。")
                else:
                    item.mark(STATUS_PROPOSED, "目标已变化，插入位置已按当前内容重算。")
                lines = self._index.lines.get(item.target_rel_path, []) if self._index else []
                item.start_line = len(lines) + 1
                item.end_line = item.start_line
        return list(suggestions or ())

    @staticmethod
    def _occurrences(text: str, needle: str) -> List[int]:
        """返回 needle 出现的 1-based 行号（用于重定位/冲突判定）。"""
        if not needle:
            return []
        return [
            line_no
            for line_no, line in enumerate((text or "").splitlines(), start=1)
            if needle in line
        ]