# -*- coding: utf-8 -*-
"""V3.3 33-E 写作辅助门面：把搜索/建议/采纳/provider 接到既有入口。

``AuthoringAssistant`` 是 CLI 命令、编辑器面板与测试共用的单一入口：

- 显式范围搜索（项目 + 模块库 + 当前缓冲），带来源引用/复制正文文本；
- 确定性建议与修订摘要候选（无模型可用）；
- 选择采纳 → 编辑缓冲 → 一次撤销；保存仍调用既有 ``ContentWriter``；
- 可选 provider 增强只在显式 ``enhance()`` 时调用，默认禁用。

门面本身不写正文、不改复核/关系/版本；只读项目下采纳被拒绝但可查看/导出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from doc_tool.application.assist.adoption import AdoptionOutcome, AdoptionSession
from doc_tool.application.assist.models import (
    INSERT_MODE_CITATION, KIND_TERM, PURPOSE_REVISION_SUMMARY, PURPOSE_TERM,
    display_path,
)
from doc_tool.application.assist.provider import (
    EnhancementPreview, EnhancementResult, ProviderConfig, ProviderConfigStore, ProviderGateway, WritingProvider,
)
from doc_tool.application.assist.search_local import (
    BufferDocument, EvidenceSource, LocalEvidenceSearch, SearchHit, SearchOutcome,
)
from doc_tool.application.assist.suggestions import Suggestion, SuggestionEngine, SuggestionSet


@dataclass
class AuthoringAssistant:
    """写作辅助门面（搜索/建议/采纳/provider 的统一入口）。"""

    search_service: LocalEvidenceSearch
    suggestion_engine: Optional[SuggestionEngine] = None
    adoption_session: AdoptionSession = field(default_factory=AdoptionSession)
    gateway: ProviderGateway = field(default_factory=ProviderGateway)
    read_only: bool = False
    buffers: Dict[str, str] = field(default_factory=dict)
    project_source_id: str = ""
    notes: List[str] = field(default_factory=list)
    buffer_provider: Optional[Callable[[], Mapping[str, str]]] = field(default=None, repr=False)

    # --- 构造 ---

    @classmethod
    def from_project(
        cls,
        project_root,
        *,
        module_roots: Sequence[str] = (),
        cache_dir=None,
        cache_enabled: bool = True,
        read_only: bool = False,
        terms: Sequence[str] = (),
        term_aliases: Optional[Mapping[str, str]] = None,
        change_items: Sequence = (),
        buffers: Optional[Mapping[str, str]] = None,
        provider_config: Optional[ProviderConfig] = None,
        provider: Optional[WritingProvider] = None,
    ) -> "AuthoringAssistant":
        """按项目（可选模块库）装配辅助能力；缺配置时全部本地可用。"""
        root = Path(project_root)
        try:
            from doc_tool.domain.manifest import ProjectManifest
            read_only = bool(read_only or not ProjectManifest.load(root).is_writable())
        except Exception:
            pass  # plain readable folders retain the caller's explicit policy
        project_source = EvidenceSource.from_project(root, read_only=read_only)
        sources: List[EvidenceSource] = [project_source]
        for module_root in module_roots or ():
            if not module_root:
                continue
            sources.append(EvidenceSource.from_module(module_root))
        search_service = LocalEvidenceSearch(sources, cache_dir=cache_dir, cache_enabled=cache_enabled)
        engine = SuggestionEngine.from_project(
            root,
            read_only=read_only,
            terms=terms,
            term_aliases=term_aliases,
            buffers=buffers,
            change_items=change_items,
            module_roots=module_roots,
        )
        config = provider_config or ProviderConfigStore().load()
        gateway = ProviderGateway(config, provider=provider)
        assistant = cls(
            search_service=search_service,
            suggestion_engine=engine,
            adoption_session=AdoptionSession(
                read_only=read_only,
                read_only_reason="只读项目：可查看/导出建议与资料，不写原文。",
            ),
            gateway=gateway,
            read_only=read_only,
            project_source_id=project_source.source_id,
        )
        assistant.notes.extend(engine.warnings)
        if buffers:
            assistant.set_buffers(buffers)
        return assistant

    # --- 缓冲 ---

    def set_buffers(self, buffers: Optional[Mapping[str, str]]) -> None:
        """设置当前编辑缓冲（搜索与建议都基于缓冲内容，并标未保存）。"""
        self.buffers = {display_path(str(key)): str(value) for key, value in (buffers or {}).items()}
        documents = [
            BufferDocument(rel_path=rel_path, text=text, source_id=self.project_source_id)
            for rel_path, text in sorted(self.buffers.items())
        ]
        self.search_service.set_buffers(documents)
        if self.suggestion_engine is not None:
            self.suggestion_engine.apply_buffers(self.buffers)

    def sync_live_buffers(self) -> None:
        """Read the host's current overlay; a read failure never silently uses stale text."""
        if self.buffer_provider is not None:
            latest = self.buffer_provider()
            if latest is None:
                raise RuntimeError("无法读取当前编辑缓冲，未应用旧建议。")
            self.set_buffers(latest)

    # --- 检索 ---

    def search_evidence(
        self,
        query: str = "",
        *,
        terms: Sequence[str] = (),
        limit: int = 200,
        refresh_stale: bool = False,
        document_types: Optional[Sequence[str]] = None,
        cancel_token=None,
        **kwargs,
    ) -> SearchOutcome:
        self.sync_live_buffers()
        return self.search_service.search(
            query,
            terms=terms,
            limit=limit,
            refresh_stale=refresh_stale,
            document_types=document_types,
            cancel_token=cancel_token,
            **kwargs,
        )

    def citation_text(self, hit: SearchHit) -> str:
        return self.search_service.citation_text(hit)

    def insert_text(self, hit: SearchHit, mode: str = INSERT_MODE_CITATION, *, context_lines: int = 0) -> str:
        return self.search_service.insert_text(hit, mode, context_lines=context_lines)

    def scope_summary(self) -> List[dict]:
        return self.search_service.scope_summary()

    # --- 建议 ---

    def suggest(
        self,
        *,
        kinds: Optional[Sequence[str]] = None,
        change_items: Optional[Sequence] = None,
        status_map: Optional[Mapping[str, str]] = None,
    ) -> SuggestionSet:
        self.sync_live_buffers()
        if self.suggestion_engine is None:
            return SuggestionSet(coverage_notes=["未装配项目索引：本地建议不可用。"])
        return self.suggestion_engine.collect(
            kinds=kinds,
            change_items=change_items,
            status_map=status_map,
            buffers=self.buffers or None,
        )

    def revision_summary_texts(
        self,
        *,
        change_items: Optional[Sequence] = None,
        status_map: Optional[Mapping[str, str]] = None,
    ) -> List[str]:
        """本地修订摘要候选文本（也可作为 provider 的兜底候选）。"""
        if self.suggestion_engine is None:
            return []
        return [
            item.after
            for item in self.suggestion_engine.revision_summary_candidates(
                change_items=change_items, status_map=status_map
            )
            if item.after
        ]

    def term_candidate_texts(self) -> List[str]:
        """本地术语候选文本（供界面显示与 provider 兜底）。"""
        if self.suggestion_engine is None:
            return []
        set_ = self.suggestion_engine.collect(kinds=[KIND_TERM], buffers=self.buffers or None)
        return [
            "{0} -> {1}".format(item.before, item.after)
            for item in set_.suggestions
            if item.before and item.after
        ]

    # --- 采纳/撤销 ---

    def adopt(
        self,
        selected_ids: Sequence[str],
        *,
        texts: Optional[Mapping[str, str]] = None,
        suggestions: Optional[Sequence[Suggestion]] = None,
        refresh: bool = True,
        change_items: Optional[Sequence] = None,
        status_map: Optional[Mapping[str, str]] = None,
        include_ignored: bool = False,
    ) -> AdoptionOutcome:
        """采纳所选建议到编辑缓冲；返回可撤销事务与摘要候选。"""
        self.sync_live_buffers()
        if suggestions is None:
            collected = self.suggest(status_map=status_map)
            suggestions = collected.suggestions
        engine = self.suggestion_engine
        index_service = getattr(engine, "_index_service", None)
        targets = {s.target_rel_path for s in suggestions if s.suggestion_id in selected_ids}
        if index_service is not None and refresh:
            for rel in targets - set(self.buffers):
                if rel:
                    index_service.rebuild_file(engine.index, rel)
        if refresh and self.suggestion_engine is not None:
            self.suggestion_engine.refresh(
                suggestions,
                change_items=change_items,
                status_map=status_map,
                buffers=self.buffers or None,
            )
        working = dict(texts) if texts is not None else self.current_texts()
        if texts is None and index_service is not None and refresh:
            # Index lines omit the terminal newline; the editor comparison needs exact text.
            for rel in targets - set(self.buffers):
                path = index_service._resolve(rel) if rel else None
                if path is not None and path.is_file():
                    working[rel] = path.read_text(encoding="utf-8")
        outcome = self.adoption_session.adopt(
            suggestions, selected_ids, working, include_ignored=include_ignored
        )
        if outcome.buffer_updates:
            self.set_buffers({**self.buffers, **outcome.buffer_updates})
        self.notes.extend(outcome.notes)
        return outcome

    def undo(self, outcome: AdoptionOutcome) -> Tuple[bool, Dict[str, str], str]:
        """Undo only the still-current adopted text, never later author edits."""
        if outcome is None or outcome.transaction is None or outcome.transaction.undone:
            return self.adoption_session.undo(outcome)
        self.sync_live_buffers()
        current = self.current_texts()
        expected = outcome.buffer_updates
        index_service = getattr(self.suggestion_engine, "_index_service", None)
        if index_service is not None:
            for rel in set(expected) - set(self.buffers):
                path = index_service._resolve(rel)
                if path is not None and path.is_file():
                    current[rel] = path.read_text(encoding="utf-8")
        if any(current.get(rel) != text for rel, text in expected.items()):
            return False, {}, "采纳后正文已变化，未撤销也未覆盖新内容；可使用编辑器原生撤销。"
        done, restored, detail = self.adoption_session.undo(outcome)
        if done and restored:
            self.set_buffers({**self.buffers, **restored})
        return done, restored, detail

    def ignore(self, suggestion_id: str) -> str:
        return self.adoption_session.ignore(suggestion_id)

    def preview_diff(self, suggestions: Sequence[Suggestion], selected_ids: Sequence[str]) -> str:
        return self.adoption_session.preview_diff(suggestions, selected_ids)

    def export_suggestions(
        self, suggestions: Sequence[Suggestion], selected_ids: Optional[Sequence[str]] = None
    ) -> str:
        return self.adoption_session.export_text(suggestions, selected_ids)

    def current_texts(self) -> Dict[str, str]:
        texts = {}
        if self.suggestion_engine is not None and self.suggestion_engine.index is not None:
            texts.update(self.suggestion_engine.current_texts())
        texts.update(self.buffers)  # preserve the exact current text, including terminal newlines
        return texts

    # --- 保存（沿用既有写入路径） ---

    def save_buffers(self, writer, rel_paths: Optional[Sequence[str]] = None) -> List:
        """把缓冲交给既有 ``ContentWriter`` 保存（本门面不直接写盘）。"""
        targets = [display_path(path) for path in (rel_paths or sorted(self.buffers))]
        results = []
        for rel_path in targets:
            if rel_path not in self.buffers:
                continue
            results.append(writer.write_text(rel_path, self.buffers[rel_path], operation="save"))
        return results

    # --- 可选增强 ---

    def preview_enhance(self, purpose: str, *, context_text: str = "", evidence_ids: Sequence[str] = (),
                        scope_label: str = "") -> EnhancementPreview:
        self.sync_live_buffers()
        local: List[str] = []
        explicit_context = bool(context_text)
        if purpose == PURPOSE_REVISION_SUMMARY:
            local = self.revision_summary_texts()
            if not context_text:
                context_text = "\n".join(local)
            label = "本地变更摘要候选（不自动包含全文）"
        else:
            local = self.term_candidate_texts()
            if not context_text:
                context_text = "\n".join(self._term_context())
            label = "项目正文前50个非标题行（当前缓冲优先）"
        return self.gateway.prepare(purpose, context_text=context_text, local_candidates=local,
            evidence_ids=evidence_ids, scope_label=scope_label or (
                "调用方明确选定的文本" if explicit_context else label))

    def send_enhancement_preview(self, preview: EnhancementPreview, *, confirmed=False,
                                 cancel_token=None) -> EnhancementResult:
        if not confirmed:
            class Cancelled:
                is_cancelled = True
            cancel_token = Cancelled()
        return self.gateway.enhance(preview.purpose, context_text=preview.text,
                                   prepared=preview, cancel_token=cancel_token)

    def enhance(self, purpose: str, *, context_text: str = "", evidence_ids: Sequence[str] = (),
                scope_label: str = "", cancel_token=None) -> EnhancementResult:
        """Explicit API invocation, retained for CLI compatibility; GUI previews first."""
        preview = self.preview_enhance(purpose, context_text=context_text,
                                       evidence_ids=evidence_ids, scope_label=scope_label)
        return self.send_enhancement_preview(preview, confirmed=True, cancel_token=cancel_token)

    def _term_context(self) -> List[str]:
        """术语增强的默认上下文：术语库 + 当前范围的术语相关行。"""
        if self.suggestion_engine is None or self.suggestion_engine.index is None:
            return []
        lines: List[str] = []
        for rel_path in self.suggestion_engine.index.all_files():
            rel_lines = self.suggestion_engine.index.lines.get(rel_path, [])
            for line_no, line in enumerate(rel_lines, start=1):
                if line.startswith("#") or not line.strip():
                    continue
                lines.append("{0}:{1} {2}".format(rel_path, line_no, line.strip()))
                if len(lines) >= 50:
                    return lines
        return lines

    def provider_status(self) -> dict:
        config = self.gateway.config
        data = config.sanitized()
        data["requestLog"] = self.gateway.request_log_dicts()
        return data

    # --- 集中提示 ---

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        lines.extend(self.search_service.status.notes)
        lines.extend(self.notes)
        return lines


def build_assistant(project_root, **kwargs) -> AuthoringAssistant:
    """便捷构造（CLI/面板共用）。"""
    return AuthoringAssistant.from_project(project_root, **kwargs)
