# -*- coding: utf-8 -*-
"""V3.3 33-A 本地资料检索：显式范围、可定位出处、坏索引兜底。

范围与口径（design.md D1）：

- **只搜调用方显式加入的范围**：项目内容根、模块库目录/文件、当前编辑缓冲；
  不做全磁盘扫描、不联网、不以向量库/embedding 为前置。
- 结果带来源身份、相对定位（``rel_path`` + 行号）、版本/hash 与匹配原因；
  当前缓冲命中标 ``unsaved``，来源已变化命中标 ``stale``。
- 索引缓存是**用户级可重建数据**（默认 ``LOCALAPPDATA%/doc-tool/assist``）；
  缓存不可解析时直接读取可读文本继续搜索，非法/不可读条目跳过不阻断其余结果。
- 大范围按批构建（``batch_size``/``progress``/``cancel_token``），可在后台线程
  运行而不阻塞编辑。

检索先走文本与术语/别名（无 embedding）；正则复用既有
``doc_tool.application.content.search.compile_pattern``，保持同一套边界语义。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.content.search import SearchQueryError, compile_pattern
from doc_tool.application.content.writer import atomic_write
from doc_tool.domain.content_index import path_natural_sort_key
from doc_tool.application.content.index import MD_SUFFIXES, ContentIndexService

from doc_tool.application.assist.models import (
    CACHE_DISABLED, CACHE_FRESH, CACHE_MISSING, CACHE_REBUILT, CACHE_REFRESHED,
    CACHE_STATUS_LABELS, INSERT_MODE_CITATION, INSERT_MODE_COPY_TEXT, INSERT_MODES,
    MATCH_REASON_LABELS, MATCH_REASON_REGEX, MATCH_REASON_TERM, MATCH_REASON_TEXT,
    SOURCE_KIND_BUFFER, SOURCE_KIND_LABELS, SOURCE_KIND_MODULE, SOURCE_KIND_PROJECT,
    SOURCE_KINDS, UNKNOWN_VERSION, display_path, hash_text, short_hash, text_lines,
    user_cache_dir,
)

#: 单次搜索默认命中上限（超大范围下保证面板响应）。
DEFAULT_LIMIT = 200
#: 索引构建默认批大小（每批结束回报进度并检查取消）。
DEFAULT_BATCH_SIZE = 32
#: 用户级索引缓存文件名与结构版本。
CACHE_FILE_NAME = "evidence-index.json"
CACHE_SCHEMA_VERSION = 1
#: 缓存中保留行文本的体积上限：超过只记 hash，命中时再按需读取。
CACHE_TEXT_LIMIT_BYTES = 1_000_000

ProgressCallback = Callable[[int, int], None]


@dataclass
class EvidenceSource:
    """一个显式加入的检索来源（项目 / 模块库 / 当前缓冲）。"""

    source_id: str
    kind: str = SOURCE_KIND_PROJECT
    label: str = ""
    root: str = ""
    document_type: str = ""
    version: str = ""
    project_id: str = ""
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_KINDS:
            self.kind = SOURCE_KIND_PROJECT
        self.root = str(self.root or "")
        if not self.label:
            self.label = Path(self.root).name or self.source_id or "未命名来源"
        if not self.source_id:
            self.source_id = self.label

    @property
    def path(self) -> Path:
        return Path(self.root)

    @property
    def exists(self) -> bool:
        return bool(self.root) and self.path.exists()

    @property
    def kind_label(self) -> str:
        return SOURCE_KIND_LABELS.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {
            "sourceId": self.source_id,
            "kind": self.kind,
            "kindLabel": self.kind_label,
            "label": self.label,
            "root": self.root,
            "documentType": self.document_type,
            "version": self.version or UNKNOWN_VERSION,
            "projectId": self.project_id,
            "readOnly": self.read_only,
        }

    @classmethod
    def from_project(
        cls,
        project_root,
        *,
        source_id: str = "",
        label: str = "",
        read_only: bool = False,
    ) -> "EvidenceSource":
        """从项目目录解析内容根与版本（清单缺失时回退 ``<root>/content``）。"""
        root = Path(project_root)
        content_root = root
        version = ""
        document_type = ""
        project_id = ""
        try:
            from doc_tool.domain.manifest import ProjectManifest

            manifest = ProjectManifest.load(root)
            paths = manifest.resolve_paths(root)
            content_root = paths.content_root
            version = str(getattr(manifest, "documentVersion", "") or "")
            document_type = str(getattr(manifest, "documentType", "") or "")
            project_id = str(getattr(manifest, "projectId", "") or "")
            label = label or str(getattr(manifest, "documentName", "") or "") or root.name
        except Exception:  # noqa: BLE001 - 清单不可用时仍按目录检索
            for candidate in (root / "content", root):
                if candidate.is_dir():
                    content_root = candidate
                    break
            label = label or root.name
        return cls(
            source_id=source_id or "project:{0}".format(root.resolve()),
            kind=SOURCE_KIND_PROJECT,
            label=label,
            root=str(content_root),
            document_type=document_type,
            version=version,
            project_id=project_id,
            read_only=read_only,
        )

    @classmethod
    def from_module(
        cls,
        module_root,
        *,
        module_id: str = "",
        label: str = "",
        version: str = "",
    ) -> "EvidenceSource":
        """模块库来源：目录（递归 ``*.md``）或单个模块文件。"""
        path = Path(module_root)
        return cls(
            source_id=module_id or "module:{0}".format(path.resolve()),
            kind=SOURCE_KIND_MODULE,
            label=label or path.name,
            root=str(path),
            version=version,
        )

@dataclass
class BufferDocument:
    """当前编辑缓冲中的一份文档（未保存内容按来源标 ``unsaved``）。"""

    rel_path: str
    text: str
    source_id: str = ""
    document_type: str = ""
    label: str = ""


@dataclass
class EvidenceDocument:
    """检索快照中的一份文档（含缓存记录字段）。"""

    source_id: str
    source_kind: str
    source_label: str
    rel_path: str
    document_type: str = ""
    version: str = ""
    content_hash: str = ""
    line_count: int = 0
    origin: str = "saved"          #: saved | module | buffer
    unsaved: bool = False
    stale: bool = False
    stat_key: str = ""             #: "size:mtime_ns"，空表示不可用（每次重读）
    text_cached: bool = False
    lines: List[str] = field(default_factory=list)
    size_bytes: int = 0

    @property
    def key(self) -> Tuple[str, str]:
        return (self.source_id, self.rel_path)

    @property
    def location_label(self) -> str:
        return "{0} · {1}".format(self.source_label, display_path(self.rel_path))

    def cache_dict(self) -> dict:
        data = {
            "sourceId": self.source_id,
            "sourceKind": self.source_kind,
            "sourceLabel": self.source_label,
            "relPath": self.rel_path,
            "documentType": self.document_type,
            "version": self.version,
            "contentHash": self.content_hash,
            "lineCount": self.line_count,
            "statKey": self.stat_key,
            "sizeBytes": self.size_bytes,
            "textCached": bool(self.text_cached),
        }
        if self.text_cached:
            data["lines"] = list(self.lines)
        return data

    @classmethod
    def from_cache_dict(cls, raw: dict) -> "EvidenceDocument":
        if not isinstance(raw, dict):
            raise ValueError("缓存条目不是对象")
        source_id = str(raw.get("sourceId") or "").strip()
        rel_path = display_path(str(raw.get("relPath") or "").strip())
        if not source_id or not rel_path:
            raise ValueError("缓存条目缺少来源或路径")
        raw_lines = raw.get("lines")
        lines = [str(item) for item in raw_lines] if isinstance(raw_lines, list) else []
        text_cached = bool(raw.get("textCached")) and bool(lines)
        return cls(
            source_id=source_id,
            source_kind=str(raw.get("sourceKind") or SOURCE_KIND_PROJECT),
            source_label=str(raw.get("sourceLabel") or source_id),
            rel_path=rel_path,
            document_type=str(raw.get("documentType") or ""),
            version=str(raw.get("version") or ""),
            content_hash=str(raw.get("contentHash") or ""),
            line_count=int(raw.get("lineCount") or len(lines) or 0),
            origin="module" if str(raw.get("sourceKind")) == SOURCE_KIND_MODULE else "saved",
            stale=False,
            stat_key=str(raw.get("statKey") or ""),
            text_cached=text_cached,
            lines=lines,
            size_bytes=int(raw.get("sizeBytes") or 0),
        )


@dataclass
class IndexStatus:
    """一次索引准备/刷新的状态（供界面集中提示）。"""

    cache_status: str = CACHE_MISSING
    fallback_reason: str = ""
    document_count: int = 0
    source_count: int = 0
    skipped: List[str] = field(default_factory=list)
    stale_documents: List[str] = field(default_factory=list)
    cancelled: bool = False
    from_cache: bool = False
    text_bytes_read: int = 0
    batches: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def cache_label(self) -> str:
        return CACHE_STATUS_LABELS.get(self.cache_status, self.cache_status)

    def to_dict(self) -> dict:
        return {
            "cacheStatus": self.cache_status,
            "cacheLabel": self.cache_label,
            "fallbackReason": self.fallback_reason,
            "documentCount": self.document_count,
            "sourceCount": self.source_count,
            "skipped": list(self.skipped),
            "staleDocuments": list(self.stale_documents),
            "cancelled": self.cancelled,
            "fromCache": self.from_cache,
            "textBytesRead": self.text_bytes_read,
            "batches": self.batches,
            "notes": list(self.notes),
        }


@dataclass
class SearchHit:
    """一条可定位的检索结果。"""

    source_id: str
    source_kind: str
    source_label: str
    rel_path: str
    line_no: int
    text: str
    match_reason: str = MATCH_REASON_TEXT
    matched_term: str = ""
    content_hash: str = ""
    version: str = ""
    document_type: str = ""
    #: 物理文件路径（跨来源去重与定位用；缓冲文档为空）。
    file_path: str = ""
    stale: bool = False
    unsaved: bool = False
    origin: str = "saved"

    @property
    def location_label(self) -> str:
        return "{0} · {1}:{2}".format(
            self.source_label, display_path(self.rel_path), self.line_no
        )

    @property
    def match_label(self) -> str:
        label = MATCH_REASON_LABELS.get(self.match_reason, self.match_reason)
        if self.matched_term and self.match_reason == MATCH_REASON_TERM:
            label = "{0}（{1}）".format(label, self.matched_term)
        return label

    def to_dict(self) -> dict:
        return {
            "sourceId": self.source_id,
            "sourceKind": self.source_kind,
            "sourceLabel": self.source_label,
            "relPath": display_path(self.rel_path),
            "line": self.line_no,
            "text": self.text,
            "matchReason": self.match_reason,
            "matchLabel": self.match_label,
            "matchedTerm": self.matched_term,
            "contentHash": self.content_hash,
            "version": self.version or UNKNOWN_VERSION,
            "documentType": self.document_type,
            "stale": self.stale,
            "unsaved": self.unsaved,
            "location": self.location_label,
        }


@dataclass
class SearchOutcome:
    """一次检索的结果与状态（先给可用结果，再集中说明兜底）。"""

    query: str = ""
    terms: List[str] = field(default_factory=list)
    hits: List[SearchHit] = field(default_factory=list)
    total: int = 0
    truncated: bool = False
    file_count: int = 0
    cache_status: str = CACHE_MISSING
    fallback_reason: str = ""
    skipped: List[str] = field(default_factory=list)
    stale_count: int = 0
    unsaved_count: int = 0
    cancelled: bool = False
    error: str = ""
    limit: int = DEFAULT_LIMIT
    scope: List[dict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    #: V3.3 1.4：因同一文件出现在多个来源而被去重的命中数。
    deduped: int = 0

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def cache_label(self) -> str:
        return CACHE_STATUS_LABELS.get(self.cache_status, self.cache_status)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        if self.error:
            lines.append("检索未执行：{0}".format(self.error))
            return lines
        lines.append(
            "命中 {0} 条（{1} 个文件{2}）".format(
                self.total, self.file_count, "，已截断" if self.truncated else ""
            )
        )
        if self.unsaved_count:
            lines.append("{0} 条来自当前未保存缓冲。".format(self.unsaved_count))
        if self.stale_count:
            lines.append("{0} 条来源已变化，标记为陈旧结果。".format(self.stale_count))
        if self.skipped:
            lines.append("{0} 个条目不可读已跳过，其余结果继续。".format(len(self.skipped)))
        if self.fallback_reason:
            lines.append(self.fallback_reason)
        lines.extend(self.notes)
        return lines

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "terms": list(self.terms),
            "total": self.total,
            "truncated": self.truncated,
            "fileCount": self.file_count,
            "cacheStatus": self.cache_status,
            "cacheLabel": self.cache_label,
            "fallbackReason": self.fallback_reason,
            "skipped": list(self.skipped),
            "staleCount": self.stale_count,
            "unsavedCount": self.unsaved_count,
            "cancelled": self.cancelled,
            "error": self.error,
            "limit": self.limit,
            "scope": list(self.scope),
            "notes": list(self.notes),
            "summary": self.summary_lines(),
            "hits": [item.to_dict() for item in self.hits],
        }

class LocalEvidenceSearch:
    """在显式来源范围内做本地文本/术语检索（无 embedding、无网络）。"""

    def __init__(
        self,
        sources: Sequence[EvidenceSource] = (),
        *,
        cache_dir=None,
        cache_enabled: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._sources: Dict[str, EvidenceSource] = {}
        self._buffers: Dict[Tuple[str, str], BufferDocument] = {}
        self._documents: Dict[Tuple[str, str], EvidenceDocument] = {}
        self._cache_dir = Path(cache_dir) if cache_dir else user_cache_dir()
        self._cache_enabled = bool(cache_enabled)
        self._batch_size = max(1, int(batch_size))
        self._indexed = False
        self._status = IndexStatus()
        for source in sources or ():
            self.add_source(source)

    # --- 范围 ---

    @property
    def sources(self) -> List[EvidenceSource]:
        return list(self._sources.values())

    @property
    def buffers(self) -> List[BufferDocument]:
        return list(self._buffers.values())

    @property
    def documents(self) -> List[EvidenceDocument]:
        return self._sorted_documents()

    @property
    def status(self) -> IndexStatus:
        return self._status

    @property
    def cache_file(self) -> Path:
        return self._cache_dir / CACHE_FILE_NAME

    def add_source(self, source: EvidenceSource) -> EvidenceSource:
        """显式加入一个来源（重复 id 覆盖旧定义）。"""
        self._sources[source.source_id] = source
        self._indexed = False
        return source

    def remove_source(self, source_id: str) -> None:
        self._sources.pop(source_id, None)
        for key in [key for key in self._documents if key[0] == source_id]:
            self._documents.pop(key, None)
        for key in [key for key in self._buffers if key[0] == source_id]:
            self._buffers.pop(key, None)
        self._indexed = False

    def set_buffers(self, buffers: Iterable[BufferDocument]) -> None:
        """设置当前编辑缓冲（覆盖同路径的已保存文本，命中标未保存）。"""
        self._buffers = {}
        default_source = self._buffers_default_source()
        default_source_id = default_source.source_id if default_source is not None else ""
        for buffer in buffers or ():
            source_id = buffer.source_id or default_source_id
            if not source_id:
                continue
            rel_path = display_path(buffer.rel_path)
            if not rel_path:
                continue
            self._buffers[(source_id, rel_path)] = BufferDocument(
                rel_path=rel_path,
                text=buffer.text or "",
                source_id=source_id,
                document_type=buffer.document_type,
                label=buffer.label,
            )
        self._indexed = False

    def _buffers_default_source(self) -> Optional[EvidenceSource]:
        for source in self._sources.values():
            if source.kind == SOURCE_KIND_PROJECT:
                return source
        for source in self._sources.values():
            return source
        return None

    def scope_summary(self) -> List[dict]:
        """显式范围的可展示摘要（来源身份 + 未保存缓冲）。"""
        summary = [source.to_dict() for source in self._sources.values()]
        for (source_id, rel_path), buffer in sorted(self._buffers.items()):
            parent = self._sources.get(source_id)
            summary.append({
                "sourceId": source_id,
                "kind": SOURCE_KIND_BUFFER,
                "kindLabel": SOURCE_KIND_LABELS[SOURCE_KIND_BUFFER],
                "label": buffer.label or (parent.label if parent else rel_path),
                "root": "",
                "relPath": rel_path,
                "documentType": buffer.document_type or (parent.document_type if parent else ""),
                "version": parent.version if parent and parent.version else UNKNOWN_VERSION,
                "projectId": parent.project_id if parent else "",
                "readOnly": bool(parent.read_only) if parent else False,
                "unsaved": True,
            })
        return summary

    # --- 索引 ---

    def ensure_index(
        self,
        *,
        refresh: bool = False,
        refresh_stale: bool = False,
        cancel_token=None,
        progress: Optional[ProgressCallback] = None,
        batch_size: Optional[int] = None,
    ) -> IndexStatus:
        """准备索引快照；缓存不可解析时直接读取可读文本（不阻塞编辑）。"""
        size = max(1, int(batch_size or self._batch_size))
        if refresh:
            self._documents.clear()
            self._indexed = False
        if self._indexed and not refresh_stale:
            return self._status

        cached: Dict[Tuple[str, str], EvidenceDocument] = {}
        cache_status = CACHE_REFRESHED if refresh else (CACHE_DISABLED if not self._cache_enabled else CACHE_MISSING)
        cache_reason = ""
        if self._cache_enabled and not refresh:
            cached, cache_status, cache_reason = self._load_cache()

        documents: Dict[Tuple[str, str], EvidenceDocument] = {} if refresh else dict(self._documents)
        skipped: List[str] = []
        stale_documents: List[str] = []
        notes: List[str] = []
        pending: List[Tuple[EvidenceSource, str, Path]] = []
        for source in self._sources.values():
            files, source_skipped = self._discover(source)
            skipped.extend(source_skipped)
            for rel_path, file_path in files:
                pending.append((source, rel_path, file_path))

        total = len(pending)
        processed = 0
        read_bytes = 0
        read_count = 0
        cancelled = False
        for source, rel_path, file_path in pending:
            if self._cancelled(cancel_token):
                cancelled = True
                break
            key = (source.source_id, rel_path)
            stat_key = self._stat_key(file_path)
            existing = documents.get(key)
            if existing is not None and existing.stat_key and existing.stat_key == stat_key:
                processed += 1
                continue
            record = cached.get(key)
            if (
                record is not None and record.text_cached and record.stat_key
                and record.stat_key == stat_key and existing is None
            ):
                documents[key] = record
                processed += 1
                continue
            if (
                record is not None and record.text_cached and record.stat_key
                and record.stat_key != stat_key and not refresh_stale
            ):
                # 来源已变化：先返回缓存文本并标陈旧，按需再刷新（不阻塞编辑）。
                record.stale = True
                documents[key] = record
                stale_documents.append("{0}/{1}".format(source.label, rel_path))
                processed += 1
                continue
            document, error = self._read_document(source, rel_path, file_path, stat_key)
            if error is not None:
                skipped.append("{0}/{1}：{2}".format(source.label, rel_path, error))
                processed += 1
                continue
            read_bytes += document.size_bytes
            read_count += 1
            document.stale = False
            documents[key] = document
            processed += 1
            if progress is not None and read_count % size == 0:
                progress(processed, total)
        if progress is not None and total:
            progress(processed, total)

        if cancelled:
            notes.append(
                "索引构建已取消：已处理 {0}/{1} 条，可稍后在后台继续，不阻塞编辑。".format(
                    processed, total
                )
            )
            self._indexed = False
        documents = self._merge_buffers(documents)
        if stale_documents:
            notes.append(
                "有 {0} 个来源自上次索引后发生变化，命中已标“陈旧”。".format(len(stale_documents))
            )
        if cache_status == CACHE_REBUILT:
            notes.append(cache_reason or "索引缓存已重建，本次直接搜索可读文本。")

        status = IndexStatus(
            cache_status=cache_status,
            fallback_reason=cache_reason,
            document_count=len(documents),
            source_count=len(self._sources) + (1 if self._buffers else 0),
            skipped=skipped,
            stale_documents=stale_documents,
            cancelled=cancelled,
            from_cache=cache_status == CACHE_FRESH,
            text_bytes_read=read_bytes,
            batches=max(1, (processed + size - 1) // size) if processed else 0,
            notes=notes,
        )
        if self._cache_enabled and not cancelled and documents:
            saved, save_note = self._save_cache(documents)
            if save_note:
                status.notes.append(save_note)
            if saved and cache_status in (CACHE_MISSING, CACHE_REBUILT):
                status.notes.append("索引缓存已写入用户目录（可随时重建）。")
        self._documents = documents
        self._indexed = not cancelled
        self._status = status
        return status

    # --- 检索 ---

    def search(
        self,
        query: str = "",
        *,
        terms: Sequence[str] = (),
        regex: bool = False,
        case_sensitive: bool = False,
        whole_word: bool = False,
        document_types: Optional[Sequence[str]] = None,
        limit: int = DEFAULT_LIMIT,
        refresh_stale: bool = False,
        include_buffers: bool = True,
        cancel_token=None,
        progress: Optional[ProgressCallback] = None,
    ) -> SearchOutcome:
        """在显式范围内检索；返回结果与集中兜底说明。"""
        text = (query or "").strip()
        term_list = [str(item).strip() for item in (terms or ()) if str(item).strip()]
        outcome = SearchOutcome(query=text, terms=term_list, limit=max(1, int(limit or DEFAULT_LIMIT)))
        if not text and not term_list:
            outcome.error = "请输入检索词或术语。"
            return outcome
        pattern = None
        if text:
            try:
                pattern = compile_pattern(
                    text, regex=regex, case_sensitive=case_sensitive, whole_word=whole_word
                )
            except SearchQueryError as exc:
                outcome.error = str(exc)
                outcome.notes.append("检索式无效，本次未执行搜索；其余编辑不受影响。")
                return outcome

        status = self.ensure_index(
            refresh_stale=refresh_stale, cancel_token=cancel_token, progress=progress
        )
        if not refresh_stale:
            # 长会话里来源可能随时变化：每次检索前做一次廉价 stat 检查，陈旧结果明示。
            self.mark_stale()
        outcome.cache_status = status.cache_status
        outcome.fallback_reason = status.fallback_reason
        outcome.skipped = list(status.skipped)
        outcome.scope = self.scope_summary()

        allowed = {str(item) for item in (document_types or ())}
        cancelled = status.cancelled
        total = 0
        hits: List[SearchHit] = []
        files: set = set()
        # 同一份文件可能既在项目内容里、又通过模块根被扫到：按“来源种类 + 路径 + 行号 + 内容”
        # 去重，避免同一处内容被报两次（V3.3 1.4）。
        seen_hits: set = set()
        deduped = 0
        for document in self._sorted_documents():
            if document.origin == "buffer" and not include_buffers:
                continue
            if allowed and document.document_type not in allowed:
                continue
            if self._cancelled(cancel_token):
                cancelled = True
                break
            for line_no, line in enumerate(document.lines, start=1):
                reason, matched = self._match_line(line, pattern, term_list, regex=regex)
                if reason is None:
                    continue
                identity = (
                    str(self._document_file_path(document) or document.rel_path),
                    line_no,
                    document.content_hash,
                )
                if identity in seen_hits:
                    deduped += 1
                    continue
                seen_hits.add(identity)
                total += 1
                files.add(document.key)
                if len(hits) < outcome.limit:
                    hits.append(SearchHit(
                        source_id=document.source_id,
                        source_kind=document.source_kind,
                        source_label=document.source_label,
                        rel_path=document.rel_path,
                        file_path=str(self._document_file_path(document) or ""),
                        line_no=line_no,
                        text=line,
                        match_reason=reason,
                        matched_term=matched,
                        content_hash=document.content_hash,
                        version=document.version,
                        document_type=document.document_type,
                        stale=document.stale,
                        unsaved=document.unsaved,
                        origin=document.origin,
                    ))
        outcome.hits = hits
        outcome.total = total
        outcome.deduped = deduped
        if deduped:
            outcome.notes.append(
                "已按来源去重 {0} 条（同一文件出现在多个来源）".format(deduped)
            )
        outcome.truncated = total > outcome.limit
        outcome.file_count = len(files)
        outcome.stale_count = sum(1 for hit in hits if hit.stale)
        outcome.unsaved_count = sum(1 for hit in hits if hit.unsaved)
        outcome.cancelled = cancelled or status.cancelled
        if outcome.truncated:
            outcome.notes.append(
                "命中超过上限，已截断显示前 {0} 条（可缩小范围或提高上限）。".format(outcome.limit)
            )
        if outcome.stale_count:
            outcome.notes.append(
                "有 {0} 条命中来自已变化的来源（标陈旧），可刷新后重查。".format(outcome.stale_count)
            )
        if outcome.cancelled:
            outcome.notes.append("检索被取消：返回已扫描到的 {0} 条结果。".format(total))
        if not status.skipped and not status.notes:
            outcome.notes.append(status.cache_label + "。")
        else:
            outcome.notes.extend(status.notes)
        return outcome

    # --- 引用/复制 ---

    def citation_text(self, hit: SearchHit) -> str:
        """带来源引用的普通文字（不产生任意文件 INCLUDE）。"""
        flags = []
        if hit.unsaved:
            flags.append("当前缓冲未保存")
        if hit.stale:
            flags.append("来源已变化，结果可能陈旧")
        return "- 来源：{0}（{1}）｜{2}:{3}｜版本：{4}｜hash：{5}｜{6}".format(
            hit.source_label,
            SOURCE_KIND_LABELS.get(hit.source_kind, hit.source_kind),
            display_path(hit.rel_path),
            hit.line_no,
            hit.version or UNKNOWN_VERSION,
            short_hash(hit.content_hash) or "未登记",
            "；".join(flags) if flags else "来源未变化",
        )

    def copy_text(self, hit: SearchHit, *, context_lines: int = 0) -> str:
        """复制正文（可选上下若干行），不带引用标记。"""
        if context_lines <= 0:
            return hit.text
        document = self._documents.get((hit.source_id, hit.rel_path))
        if document is None or not document.lines:
            return hit.text
        start = max(1, hit.line_no - context_lines)
        end = min(len(document.lines), hit.line_no + context_lines)
        return "\n".join(document.lines[start - 1:end])

    def insert_text(self, hit: SearchHit, mode: str = INSERT_MODE_CITATION, *, context_lines: int = 0) -> str:
        """按模式生成插入文本：带来源引用或复制正文。"""
        if mode == INSERT_MODE_COPY_TEXT:
            return self.copy_text(hit, context_lines=context_lines)
        if mode not in INSERT_MODES:
            mode = INSERT_MODE_CITATION
        return self.citation_text(hit)

    # --- 内部：陈旧检查 ---

    def invalidate(self) -> None:
        """索引文件已被外部更新（如后台构建完成）：下次检索重新载入缓存。

        只清内存视图，不触发同步重建，因此不会阻塞编辑线程。
        """
        self._documents.clear()
        self._indexed = False

    def mark_stale(self) -> List[str]:
        """按当前文件状态标记陈旧文档（长会话中不必等整库重建）。"""
        stale: List[str] = []
        for document in self._documents.values():
            if document.origin == "buffer" or not document.stat_key:
                continue
            path = self._document_file_path(document)
            if path is None:
                continue
            if not path.exists():
                document.stale = True
                stale.append("{0}/{1}".format(document.source_label, document.rel_path))
                continue
            current = self._stat_key(path)
            if current and current != document.stat_key:
                document.stale = True
                stale.append("{0}/{1}".format(document.source_label, document.rel_path))
            else:
                document.stale = False
        if stale:
            self._status.stale_documents = sorted(
                set(self._status.stale_documents) | set(stale)
            )
        return stale

    def _document_file_path(self, document: EvidenceDocument):
        source = self._sources.get(document.source_id)
        if source is None or not source.root:
            return None
        root = Path(source.root)
        if root.is_file():
            return root
        return root / document.rel_path

    # --- 内部：发现/读取 ---

    def _discover(self, source: EvidenceSource) -> Tuple[List[Tuple[str, Path]], List[str]]:
        if source.kind == SOURCE_KIND_BUFFER or not source.root:
            return [], []
        root = Path(source.root)
        if root.is_file():
            if root.suffix.lower() in MD_SUFFIXES:
                return [(root.name, root)], []
            return [], ["{0}：不是 Markdown 文件，已跳过。".format(source.label)]
        if not root.is_dir():
            return [], ["{0}：来源目录不存在或不可读（{1}），已跳过。".format(source.label, root)]
        try:
            if source.kind == SOURCE_KIND_PROJECT:
                files = ContentIndexService(root).discover_files()
            else:
                files = self._discover_module(root)
        except OSError as exc:
            return [], ["{0}：读取失败（{1}），已跳过。".format(source.label, exc)]
        return list(files), []

    @staticmethod
    def _discover_module(root: Path) -> List[Tuple[str, Path]]:
        result: List[Tuple[str, Path]] = []
        for suffix in MD_SUFFIXES:
            for path in root.rglob("*" + suffix):
                rel_parts = path.relative_to(root).parts[:-1]
                if any(
                    part.startswith(".") or part in ("node_modules", "output", "logs")
                    for part in rel_parts
                ):
                    continue
                result.append((path.relative_to(root).as_posix(), path))
        result.sort(key=lambda item: path_natural_sort_key(item[0]))
        return result

    @staticmethod
    def _stat_key(file_path: Path) -> str:
        try:
            stat = file_path.stat()
        except OSError:
            return ""
        return "{0}:{1}".format(stat.st_size, stat.st_mtime_ns)

    @staticmethod
    def _cancelled(cancel_token) -> bool:
        if cancel_token is None:
            return False
        value = getattr(cancel_token, "is_cancelled", False)
        if isinstance(value, bool):
            return value
        if callable(value):
            try:
                return bool(value())
            except Exception:  # noqa: BLE001 - 取消检查不应影响检索
                return False
        return bool(value)

    def _read_document(
        self,
        source: EvidenceSource,
        rel_path: str,
        file_path: Path,
        stat_key: str,
    ) -> Tuple[Optional[EvidenceDocument], Optional[str]]:
        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            return None, "读取失败（{0}）".format(exc)
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return None, "非 UTF-8 文本，已跳过（{0}）".format(exc)
        lines = text_lines(content)
        document_type = source.document_type
        if source.kind == SOURCE_KIND_PROJECT:
            document_type = self._document_type_of(rel_path, source)
        document = EvidenceDocument(
            source_id=source.source_id,
            source_kind=source.kind,
            source_label=source.label,
            rel_path=rel_path,
            document_type=document_type,
            version=source.version or UNKNOWN_VERSION,
            content_hash=hash_text(content),
            line_count=len(lines),
            origin="module" if source.kind == SOURCE_KIND_MODULE else "saved",
            stat_key=stat_key,
            text_cached=len(raw) <= CACHE_TEXT_LIMIT_BYTES,
            lines=lines,
            size_bytes=len(raw),
        )
        return document, None

    @staticmethod
    def _document_type_of(rel_path: str, source: EvidenceSource) -> str:
        from doc_tool.application.content.index import infer_document_type

        first = display_path(rel_path).split("/", 1)[0]
        if first in ("requirement", "design", "general"):
            return first
        return source.document_type or infer_document_type(rel_path)

    def _merge_buffers(
        self, documents: Dict[Tuple[str, str], EvidenceDocument]
    ) -> Dict[Tuple[str, str], EvidenceDocument]:
        for (source_id, rel_path), buffer in self._buffers.items():
            parent = self._sources.get(source_id)
            lines = text_lines(buffer.text)
            label = buffer.label or (parent.label if parent else rel_path)
            documents[(source_id, rel_path)] = EvidenceDocument(
                source_id=source_id,
                source_kind=SOURCE_KIND_BUFFER,
                source_label="{0}（当前缓冲）".format(label),
                rel_path=rel_path,
                document_type=buffer.document_type or (parent.document_type if parent else ""),
                version=(parent.version if parent and parent.version else UNKNOWN_VERSION),
                content_hash=hash_text(buffer.text),
                line_count=len(lines),
                origin="buffer",
                unsaved=True,
                stale=False,
                stat_key="",
                text_cached=False,
                lines=lines,
                size_bytes=len((buffer.text or "").encode("utf-8")),
            )
        return documents

    def _sorted_documents(self) -> List[EvidenceDocument]:
        order = {source_id: index for index, source_id in enumerate(self._sources)}
        return sorted(
            self._documents.values(),
            key=lambda doc: (
                order.get(doc.source_id, len(order)),
                1 if doc.origin == "buffer" else 0,
                path_natural_sort_key(doc.rel_path),
            ),
        )

    @staticmethod
    def _match_line(
        line: str,
        pattern,
        terms: Sequence[str],
        *,
        regex: bool,
    ) -> Tuple[Optional[str], str]:
        lowered = line.lower()
        for term in terms:
            if term and term.lower() in lowered:
                return MATCH_REASON_TERM, term
        if pattern is not None:
            match = pattern.search(line)
            if match is not None:
                return (MATCH_REASON_REGEX if regex else MATCH_REASON_TEXT), match.group(0) or ""
        return None, ""

    # --- 内部：用户级缓存 ---

    def _load_cache(self) -> Tuple[Dict[Tuple[str, str], EvidenceDocument], str, str]:
        if not self._cache_enabled:
            return {}, CACHE_DISABLED, ""
        path = self.cache_file
        if not path.is_file():
            return {}, CACHE_MISSING, ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            return {}, CACHE_REBUILT, (
                "索引缓存不可解析（{0}），已直接搜索可读文本；缓存可随时重建。".format(exc)
            )
        if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
            return {}, CACHE_REBUILT, "索引缓存结构不正确，已直接搜索可读文本；缓存可随时重建。"
        records: Dict[Tuple[str, str], EvidenceDocument] = {}
        for raw in data.get("documents") or []:
            try:
                document = EvidenceDocument.from_cache_dict(raw)
            except (ValueError, TypeError):
                continue  # 非法缓存项跳过，不影响其余来源
            if document.source_id not in self._sources:
                continue  # 已移出显式范围的旧记录不再使用
            records[document.key] = document
        if not records:
            return {}, CACHE_MISSING, ""
        return records, CACHE_FRESH, ""

    def _save_cache(
        self, documents: Dict[Tuple[str, str], EvidenceDocument]
    ) -> Tuple[bool, str]:
        payload = {
            "schemaVersion": CACHE_SCHEMA_VERSION,
            "documents": [
                doc.cache_dict()
                for doc in self._sorted_documents_of(documents)
                if doc.origin != "buffer"
            ],
        }
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            atomic_write(self.cache_file, json.dumps(payload, ensure_ascii=False))
        except OSError as exc:
            return False, "索引缓存写入失败（{0}），不影响本次检索；下次会重建。".format(exc)
        return True, ""

    def _sorted_documents_of(
        self, documents: Dict[Tuple[str, str], EvidenceDocument]
    ) -> List[EvidenceDocument]:
        order = {source_id: index for index, source_id in enumerate(self._sources)}
        return sorted(
            documents.values(),
            key=lambda doc: (
                order.get(doc.source_id, len(order)),
                path_natural_sort_key(doc.rel_path),
            ),
        )