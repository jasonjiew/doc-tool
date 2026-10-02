# -*- coding: utf-8 -*-
"""V3.3 本地写作辅助与可选模型测试（33-A～33-F）。

覆盖（对应用户要求的最小集合）：

- 33-A：来源/版本/定位、当前缓冲未保存标记、陈旧与按需刷新、坏索引兜底、
  非法条目跳过、分批与取消不阻塞、引用/复制文本。
- 33-B：无模型确定性建议（填写/术语/引用/复核/摘要）、依据与覆盖度、
  目标变化重算或冲突跳过、不自动标通过。
- 33-C：采纳进缓冲 + 一次撤销、沿用既有 ContentWriter 保存、冲突跳过其余继续、
  只读可看/导出不写源、摘要只填候选框且取消不新增修订记录。
- 33-D：provider 默认禁用且日常流程不调用、超时/坏响应/无凭据/断网回本地且不重试、
  范围与截断可见、凭据不入文件/日志、响应不执行命令、命令 adapter 结构校验。
- 33-E：门面 + GUI 面板离屏 + CLI 命令 + 本地流程到离线出稿。

无真实模型/网络依赖：provider 用 ``FakeWritingProvider`` 与注入 transport。
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
for candidate in (REPO_ROOT, SCRIPTS, HERE):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.tests.core_fixtures import cleanup, scratch_dir  # noqa: E402
from scripts.tests.fixture_factory import create_project  # noqa: E402

from doc_tool.application.assist.adoption import AdoptionSession  # noqa: E402
from doc_tool.application.assist.models import (  # noqa: E402
    APPLY_INSERT, APPLY_NONE, APPLY_REPLACE, CACHE_FRESH, CACHE_REBUILT,
    COVERAGE_INSUFFICIENT, COVERAGE_PARTIAL, ENHANCE_BAD_RESPONSE, ENHANCE_COMMAND_MISSING,
    ENHANCE_CANCELLED, ENHANCE_DISABLED, ENHANCE_NETWORK, ENHANCE_NO_CREDENTIAL, ENHANCE_OK,
    ENHANCE_TIMEOUT, INSERT_MODE_CITATION, INSERT_MODE_COPY_TEXT,
    KIND_FILL, KIND_REFERENCE, KIND_REVIEW, KIND_REVISION_SUMMARY, KIND_TERM,
    PURPOSE_REVISION_SUMMARY, PURPOSE_TERM, STATUS_CONFLICT, STATUS_PROPOSED,
)
from doc_tool.application.assist.provider import (  # noqa: E402
    FakeWritingProvider, HttpProvider, LocalCommandProvider, ProviderBadResponse, ProviderCommandMissing,
    ProviderConfig, ProviderConfigStore, ProviderGateway, ProviderNetworkError,
    ProviderTimeout, validate_provider_response,
)
from doc_tool.application.assist.search_local import (  # noqa: E402
    BufferDocument, EvidenceSource, LocalEvidenceSearch,
)
from doc_tool.application.assist.service import AuthoringAssistant  # noqa: E402
from doc_tool.application.assist.suggestions import SuggestionEngine  # noqa: E402
from doc_tool.application.content.changes import build_change_items  # noqa: E402
from doc_tool.application.content.writer import ContentWriter  # noqa: E402
from doc_tool.domain.cancellation import CancellationToken  # noqa: E402

#: 夹具中的共享术语（跨项目/模块）。
TERM_PACS = "PACS"
TERM_UPGRADE = "呼吸机应用升级"
PACS_FILE_TEXT = (
    "# 目的\n\n"
    "本项目对接 PACS 接口，使用 pacs 编码。\n\n"
    "## 范围\n\n覆盖导入与离线出稿。\n"
)
DESIGN_FILE_TEXT = (
    "# 概述\n\n"
    "设计侧引用呼吸机应用升级与 PACS 约定，接口说明沿用现有定义。\n"
)
REFERENCE_FILE_TEXT = "# 接口约定\n\n接口说明见 [缺失文档](9.9 不存在.md)。\n"


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_project(scratch: Path, name: str, document_type: str = "requirement") -> Path:
    """两项目夹具之一：标准项目 + 章节内容。"""
    root = create_project(scratch / name, document_type=document_type)
    from doc_tool.domain.manifest import ProjectManifest

    manifest = ProjectManifest.load(root)
    manifest.documentName = "需求文档A" if document_type == "requirement" else "设计文档B"
    manifest.save(root, backup=False)
    content = root / "content" / document_type
    if document_type == "requirement":
        write_text(content / "第1章 引言" / "1.1 目的.md", PACS_FILE_TEXT)
        write_text(content / "第2章 设计" / "2.1 接口.md", REFERENCE_FILE_TEXT)
    else:
        write_text(content / "第1章 概述" / "1.1 概述.md", DESIGN_FILE_TEXT)
    return root


def build_modules(scratch: Path) -> list:
    """三模块资料夹具（模块库 = 目录，内含各自条目）。"""
    modules = []
    for name, body in (
        ("module-interface", "# 接口约定\n\nPACS 接口约定：帧率 30fps，超时 3s。\n"),
        ("module-terms", "# 术语\n\n呼吸机应用升级 = 呼吸机应用软件升级包。\n"),
        ("module-notes", "# 记录\n\n模块更新来源：呼吸机应用升级说明。\n"),
    ):
        root = scratch / "modules" / name
        write_text(root / "内容.md", body)
        modules.append(root)
    return modules


def project_paths(root: Path):
    from doc_tool.domain.manifest import ProjectManifest

    return ProjectManifest.load(root).resolve_paths(root)


class AssistTestCase(unittest.TestCase):
    """公共夹具：两项目 + 三模块 + 仓库内可写缓存目录。"""

    def setUp(self) -> None:
        self.scratch = scratch_dir("v33")
        self.project_a = build_project(self.scratch, "proj-a", "requirement")
        self.project_b = build_project(self.scratch, "proj-b", "design")
        self.modules = build_modules(self.scratch)
        self.cache_dir = self.scratch / "cache"

    def tearDown(self) -> None:
        cleanup(self.scratch)

    # --- 常用构造 ---

    def sources(self):
        return [
            EvidenceSource.from_project(self.project_a),
            EvidenceSource.from_project(self.project_b),
        ] + [EvidenceSource.from_module(path) for path in self.modules]

    def search_service(self):
        return LocalEvidenceSearch(self.sources(), cache_dir=self.cache_dir)

    def assistant(self, **kwargs) -> AuthoringAssistant:
        kwargs.setdefault("cache_dir", self.cache_dir)
        return AuthoringAssistant.from_project(self.project_a, **kwargs)

    def rel_a(self) -> str:
        return "requirement/第1章 引言/1.1 目的.md"

    def text_a(self) -> str:
        return PACS_FILE_TEXT

class EvidenceSearchTests(AssistTestCase):
    """33-A：显式范围检索、出处/版本/定位、缓冲/陈旧标记、坏索引兜底。"""

    def test_search_returns_source_version_location_and_distinguishes_projects(self):
        service = self.search_service()
        outcome = service.search(TERM_PACS)
        self.assertTrue(outcome.ok, outcome.error)
        self.assertGreaterEqual(outcome.total, 3)
        source_ids = {hit.source_id for hit in outcome.hits}
        self.assertGreaterEqual(len(source_ids), 3, "至少覆盖两个项目与一个模块来源")
        labels = {hit.source_label for hit in outcome.hits}
        self.assertGreaterEqual(len(labels), 3, "不同出处不合并为无来源结论")
        for hit in outcome.hits:
            self.assertTrue(hit.rel_path)
            self.assertGreater(hit.line_no, 0)
            self.assertGreaterEqual(len(hit.content_hash), 8)
            self.assertIn(hit.match_reason, ("text", "term-alias", "regex"))
        project_hits = [hit for hit in outcome.hits if hit.source_kind == "project"]
        self.assertTrue(project_hits)
        self.assertTrue(any(hit.version == "1.0" for hit in project_hits), "项目版本来自清单")
        module_hits = [hit for hit in outcome.hits if hit.source_kind == "module"]
        self.assertTrue(module_hits)
        self.assertTrue(all(hit.version == "未登记" for hit in module_hits))

    def test_chinese_term_search_and_location(self):
        service = self.search_service()
        outcome = service.search("", terms=[TERM_UPGRADE])
        self.assertTrue(outcome.ok)
        self.assertGreaterEqual(outcome.total, 2, "中文术语应命中项目与模块资料")
        self.assertTrue(all(hit.match_reason == "term-alias" for hit in outcome.hits))
        self.assertTrue(all(hit.matched_term == TERM_UPGRADE for hit in outcome.hits))
        module_hit = [hit for hit in outcome.hits if hit.source_kind == "module"][0]
        self.assertIn("内容.md", module_hit.rel_path)

    def test_buffer_hits_marked_unsaved_and_override_saved_text(self):
        service = self.search_service()
        service.set_buffers([
            BufferDocument(
                rel_path=self.rel_a(),
                text=self.text_a() + "\n## 缓冲新增\n\n缓冲专用标记 ZZBUF。\n",
                source_id=EvidenceSource.from_project(self.project_a).source_id,
            )
        ])
        outcome = service.search("ZZBUF")
        self.assertEqual(outcome.total, 1)
        hit = outcome.hits[0]
        self.assertTrue(hit.unsaved, "当前缓冲命中必须标未保存")
        self.assertEqual(hit.origin, "buffer")
        self.assertIn("当前缓冲", hit.source_label)
        self.assertGreaterEqual(outcome.unsaved_count, 1)
        self.assertTrue(any("未保存" in note for note in outcome.notes + outcome.summary_lines()))

    def test_stale_source_flagged_then_refreshed_on_demand(self):
        target = project_paths(self.project_a).content_root / self.rel_a()
        target.write_text(self.text_a(), encoding="utf-8")
        service = self.search_service()
        first = service.search("ZZSTALE")
        self.assertEqual(first.total, 0)
        self.assertIn(first.cache_status, (CACHE_FRESH, "missing", "rebuilt"))
        # 来源变化后：默认先给缓存文本并标陈旧（不阻塞编辑）
        target.write_text(self.text_a() + "\n## 新增\n\nZZSTALE 标记。\n", encoding="utf-8")
        stale_outcome = service.search("ZZSTALE")
        self.assertEqual(stale_outcome.total, 0, "陈旧缓存不包含新文本")
        stale_hit_outcome = service.search(TERM_PACS)
        self.assertGreaterEqual(stale_hit_outcome.stale_count, 1, "来源变化后的命中标陈旧")
        self.assertTrue(any(hit.stale for hit in stale_hit_outcome.hits))
        self.assertTrue(stale_hit_outcome.summary_lines())
        # 按需刷新：重新读取文本并清掉陈旧
        refreshed = service.search("ZZSTALE", refresh_stale=True)
        self.assertEqual(refreshed.total, 1)
        self.assertFalse(refreshed.hits[0].stale)
        self.assertTrue(all(not hit.stale for hit in refreshed.hits))

    def test_corrupt_cache_falls_back_to_readable_text_and_skips_illegal_entries(self):
        service = self.search_service()
        service.search(TERM_PACS)  # 建立缓存
        cache_file = service.cache_file
        self.assertTrue(cache_file.is_file())
        cache_file.write_text("{ this is not json", encoding="utf-8")
        broken = project_paths(self.project_a).content_root / "requirement/第1章 引言/1.2 坏文件.md"
        broken.write_bytes(b"\xff\xfe not utf8 \x80\x81")
        fresh_service = LocalEvidenceSearch(self.sources(), cache_dir=self.cache_dir)
        outcome = fresh_service.search(TERM_PACS)
        self.assertTrue(outcome.ok)
        self.assertGreaterEqual(outcome.total, 2, "坏缓存仍能查可读文本")
        self.assertEqual(outcome.cache_status, CACHE_REBUILT)
        self.assertTrue(outcome.fallback_reason)
        self.assertTrue(any("坏文件" in item for item in outcome.skipped))
        illegal_only = fresh_service.search("not-utf8-marker")
        self.assertEqual(illegal_only.total, 0, "非法条目只跳过、不阻断其余结果")
        self.assertTrue(illegal_only.skipped)

    def test_batched_index_with_progress_and_cancel_does_not_block(self):
        service = LocalEvidenceSearch(self.sources(), cache_dir=self.cache_dir, batch_size=1)
        progress_calls = []
        status = service.ensure_index(batch_size=1, progress=lambda done, total: progress_calls.append((done, total)))
        self.assertGreater(status.document_count, 0)
        self.assertTrue(progress_calls)
        self.assertEqual(progress_calls[-1][0], progress_calls[-1][1])
        token = CancellationToken()
        token.request_cancel()
        cancelled_service = LocalEvidenceSearch(self.sources(), cache_dir=self.scratch / "cache2")
        outcome = cancelled_service.search(TERM_PACS, cancel_token=token)
        self.assertTrue(outcome.cancelled)
        self.assertEqual(outcome.total, 0)
        self.assertTrue(any("取消" in note for note in outcome.notes), outcome.notes)

    def test_citation_and_copy_text_carry_provenance(self):
        service = self.search_service()
        outcome = service.search(TERM_PACS, limit=1)
        hit = outcome.hits[0]
        citation = service.citation_text(hit)
        self.assertIn(hit.source_label, citation)
        self.assertIn("{0}:{1}".format(hit.rel_path, hit.line_no), citation)
        self.assertIn("版本", citation)
        self.assertIn(hit.content_hash[:8], citation)
        self.assertEqual(service.copy_text(hit), hit.text)
        self.assertEqual(service.insert_text(hit, INSERT_MODE_CITATION), citation)
        self.assertEqual(service.insert_text(hit, INSERT_MODE_COPY_TEXT), hit.text)

    def test_invalid_search_expression_reports_error_without_crash(self):
        service = self.search_service()
        outcome = service.search("([", regex=True)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.hits, [])
        self.assertIn("检索式无效", "；".join(outcome.notes))

    def test_declared_scope_is_explicit_and_reflected(self):
        service = LocalEvidenceSearch([EvidenceSource.from_project(self.project_a)], cache_dir=self.cache_dir)
        summary = service.scope_summary()
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["kind"], "project")
        self.assertNotIn("module", json.dumps(summary))
        outcome = service.search(TERM_UPGRADE)
        self.assertEqual(outcome.total, 0, "未加入的模块不会被扫描")

class SuggestionTests(AssistTestCase):
    """33-B：确定性建议、依据/覆盖度、刷新重算或冲突跳过。"""

    def _engine(self, **kwargs) -> SuggestionEngine:
        # 术语库登记规范写法；别名映射给出确定替代。
        write_text(self.project_a / "quality" / "terms.json", json.dumps(
            {"terms": [TERM_PACS, TERM_UPGRADE]}, ensure_ascii=False
        ))
        write_text(self.project_a / ".state" / "relation_reviews.json", json.dumps({
            "reviews": [{
                "relationId": "rel-1",
                "source": "proj-a/req-1",
                "target": "proj-a/design-1",
                "status": "待复核",
                "reviewer": "",
            }]
        }, ensure_ascii=False))
        kwargs.setdefault("term_aliases", {"接口说明": "接口约定"})
        kwargs.setdefault("change_items", build_change_items({
            "requirement/第1章 引言/1.1 目的.md": "modified",
        }))
        return SuggestionEngine.from_project(self.project_a, **kwargs)

    def test_deterministic_suggestions_without_model(self):
        collected = self._engine().collect()
        kinds = set(collected.counts())
        for kind in (KIND_FILL, KIND_TERM, KIND_REFERENCE, KIND_REVIEW, KIND_REVISION_SUMMARY):
            self.assertIn(kind, kinds, "无模型也应产出 {0}".format(kind))
        for item in collected.suggestions:
            self.assertTrue(item.not_evidence, "建议不得作为通过证据")
            self.assertTrue(item.suggestion_id)
            self.assertTrue(item.status_label)
            self.assertTrue(item.coverage_label)
            if item.kind != KIND_REVISION_SUMMARY:
                self.assertTrue(item.evidence, "{0} 必须有依据".format(item.suggestion_id))
                self.assertTrue(all(entry.label for entry in item.evidence))
        blob = json.dumps(
            [item.to_dict() for item in collected.suggestions], ensure_ascii=False
        )
        for forbidden in ("测试通过", "已通过验收", "需求已满足", "门禁通过"):
            self.assertNotIn(forbidden, blob)
        self.assertIn("不构成需求满足", collected.facts_note)

    def test_prompt_only_items_keep_coverage_insufficient_and_no_invented_text(self):
        collected = self._engine().collect()
        prompts = [item for item in collected.suggestions if item.apply_mode == APPLY_NONE
                   and item.kind != KIND_REVISION_SUMMARY]
        self.assertTrue(prompts)
        for item in prompts:
            self.assertEqual(item.after, "", "没有依据时不生成可写内容")
            self.assertIn(item.coverage, (COVERAGE_INSUFFICIENT, COVERAGE_PARTIAL))
            self.assertFalse(item.applicable)
        insufficient = [item for item in prompts if item.coverage == COVERAGE_INSUFFICIENT]
        self.assertTrue(insufficient, "没有依据的遗漏项应标范围不足")
        fills = collected.of_kind(KIND_FILL)
        self.assertTrue(fills)
        insert_fills = [item for item in fills if item.apply_mode == APPLY_INSERT]
        self.assertTrue(insert_fills)
        for item in insert_fills:
            self.assertIn("待填写", item.after, "只给填写占位，不虚构实现事实")
            self.assertTrue(item.target_rel_path)
            self.assertIn(item.coverage, ("partial", "full"))

    def test_revision_summary_candidates_come_from_local_change_facts(self):
        engine = self._engine()
        candidates = engine.revision_summary_candidates()
        self.assertTrue(candidates)
        text = "\n".join(item.after for item in candidates if item.after)
        self.assertIn("目的", text, "按章节定位清单生成")
        self.assertTrue(all(item.apply_mode == APPLY_NONE for item in candidates))
        self.assertTrue(all(item.field_name == "revision-summary" for item in candidates))
        empty_engine = SuggestionEngine.from_project(self.project_a)
        none_candidate = empty_engine.revision_summary_candidates()
        self.assertEqual(none_candidate[0].after, "")
        self.assertEqual(none_candidate[0].coverage, COVERAGE_INSUFFICIENT)

    def test_refresh_recomputes_or_marks_conflict_and_keeps_others_usable(self):
        engine = self._engine(terms=[TERM_PACS])
        collected = engine.collect(kinds=[KIND_TERM])
        term_items = collected.of_kind(KIND_TERM)
        self.assertTrue(term_items)
        changed_rel = term_items[0].target_rel_path
        reverted = self.text_a().replace("pacs", "PACS")
        engine.refresh(term_items, buffers={changed_rel: reverted})
        conflicted = [item for item in term_items if item.status == STATUS_CONFLICT]
        self.assertTrue(conflicted, "目标内容被改掉后应标冲突")
        self.assertTrue(all("保留用户内容" in note for item in conflicted for note in item.notes))
        # 其余未受影响建议仍可采纳
        engine.refresh(term_items)
        still_proposed = [item for item in term_items if item.status == STATUS_PROPOSED]
        self.assertTrue(still_proposed or conflicted)

    def test_module_source_is_attached_as_evidence_not_copied_content(self):
        module_root = self.scratch / "modules" / "module-fill"
        write_text(module_root / "要点.md", "# 要点\n\n总体描述：模块侧填写要点，覆盖范围与边界。\n")
        engine = self._engine(terms=[TERM_PACS], module_roots=[module_root])
        collected = engine.collect(kinds=[KIND_FILL])
        fills = [item for item in collected.of_kind(KIND_FILL) if item.apply_mode == APPLY_INSERT]
        self.assertTrue(fills)
        fill = fills[0]
        module_evidence = [entry for entry in fill.evidence if entry.kind == "module"]
        self.assertTrue(module_evidence, "模块库要点应作为依据附上")
        self.assertIn("要点.md", module_evidence[0].locator)
        self.assertIn("不自动复制", "；".join(fill.notes))
        self.assertNotIn("模块侧填写要点", fill.after, "不把模块原文当成本次填写内容")

    def test_existing_lint_facts_are_reused_and_ids_are_unique(self):
        engine = self._engine(terms=[TERM_PACS])
        issues = engine._issues()
        term_issues = [issue for issue in issues if issue.rule_id == "term_case"]
        collected = engine.collect(kinds=[KIND_TERM])
        from_lint = [item for item in collected.of_kind(KIND_TERM) if item.suggestion_id.startswith("term:")]
        self.assertEqual(len(from_lint), len(term_issues),
                         "复用既有检查结果，不重复造事实")
        ids = [item.suggestion_id for item in collected.suggestions]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(item.status == STATUS_PROPOSED for item in collected.suggestions))


class AdoptionTests(AssistTestCase):
    """33-C：采纳进缓冲、一次撤销、沿用保存路径、冲突跳过、只读、摘要候选。"""

    def _assistant_with_suggestions(self, kinds=None, status_map=None):
        assistant = self.assistant(terms=[TERM_PACS])
        collected = assistant.suggest(kinds=kinds, status_map=status_map)
        return assistant, collected

    def test_adopt_into_buffer_then_single_undo(self):
        assistant, collected = self._assistant_with_suggestions([KIND_TERM, KIND_FILL])
        ids = [item.suggestion_id for item in collected.suggestions if item.applicable]
        self.assertTrue(ids)
        before_disk = (project_paths(self.project_a).content_root / self.rel_a()).read_text(encoding="utf-8")
        outcome = assistant.adopt(ids, suggestions=collected.suggestions)
        self.assertTrue(outcome.applied)
        self.assertTrue(outcome.buffer_updates)
        self.assertTrue(outcome.diff_text())
        for change in outcome.applied:
            self.assertIn(change.mode, (APPLY_REPLACE, APPLY_INSERT))
            self.assertTrue(change.title)
        self.assertEqual(
            (project_paths(self.project_a).content_root / self.rel_a()).read_text(encoding="utf-8"),
            before_disk, "采纳不写原文件",
        )
        self.assertEqual(outcome.side_effects, [])
        self.assertFalse(outcome.changed_review_state)
        done, restored, detail = assistant.undo(outcome)
        self.assertTrue(done)
        self.assertTrue(restored)
        self.assertIn("恢复", detail)
        again, _, detail2 = assistant.undo(outcome)
        self.assertFalse(again, "只支持一次撤销")
        self.assertIn("已经撤销过", detail2)

    def test_save_uses_existing_writer_and_leaves_review_version_untouched(self):
        assistant, collected = self._assistant_with_suggestions([KIND_TERM, KIND_FILL])
        ids = [item.suggestion_id for item in collected.suggestions if item.applicable]
        outcome = assistant.adopt(ids, suggestions=collected.suggestions)
        self.assertTrue(outcome.buffer_updates, "采纳应先进入编辑缓冲")
        paths = project_paths(self.project_a)
        manifest_before = (self.project_a / "project.yml").read_text(encoding="utf-8")
        review_file = paths.state_dir / "relation_reviews.json"
        review_before = review_file.read_text(encoding="utf-8") if review_file.is_file() else ""
        writer = ContentWriter(content_root=paths.content_root, state_dir=paths.state_dir)
        results = assistant.save_buffers(writer)
        self.assertTrue(results)
        self.assertTrue(all(result.written for result in results), [r.error for r in results])
        saved = (paths.content_root / self.rel_a()).read_text(encoding="utf-8")
        self.assertIn(TERM_PACS, saved)
        self.assertNotIn("pacs 编码", saved)
        self.assertTrue((paths.content_root / self.rel_a()).with_name("1.1 目的.md.bak").is_file())
        self.assertEqual((self.project_a / "project.yml").read_text(encoding="utf-8"), manifest_before)
        review_after = review_file.read_text(encoding="utf-8") if review_file.is_file() else ""
        self.assertEqual(review_after, review_before)

    def test_conflicting_target_is_skipped_and_others_continue(self):
        assistant, collected = self._assistant_with_suggestions([KIND_TERM, KIND_FILL])
        term_items = collected.of_kind(KIND_TERM)
        fill_items = [item for item in collected.of_kind(KIND_FILL) if item.applicable]
        self.assertTrue(term_items and fill_items)
        conflicting = term_items[0]
        assistant.suggestion_engine.refresh(
            [conflicting], buffers={conflicting.target_rel_path: self.text_a().replace("pacs", "PACS")}
        )
        self.assertEqual(conflicting.status, STATUS_CONFLICT)
        ids = [conflicting.suggestion_id] + [item.suggestion_id for item in fill_items]
        outcome = assistant.adopt(ids, suggestions=collected.suggestions, refresh=False)
        self.assertTrue(outcome.conflicts)
        self.assertTrue(outcome.applied, "其余已选合法建议继续采纳")
        self.assertNotIn(conflicting.suggestion_id, [change.suggestion_id for change in outcome.applied])
        self.assertIn("使用 PACS 编码", outcome.buffer_updates[self.rel_a()], "冲突项保留用户内容")
        self.assertNotIn("pacs ", outcome.buffer_updates[self.rel_a()])

    def test_read_only_session_can_view_and_export_but_not_write(self):
        assistant, collected = self._assistant_with_suggestions([KIND_TERM])
        session = AdoptionSession(read_only=True)
        ids = [collected.suggestions[0].suggestion_id]
        outcome = session.adopt(collected.suggestions, ids, {self.rel_a(): self.text_a()})
        self.assertTrue(outcome.read_only)
        self.assertEqual(outcome.applied, [])
        self.assertEqual(outcome.buffer_updates, {})
        self.assertTrue(outcome.read_only_reason)
        exported = session.export_text(collected.suggestions)
        self.assertIn("写作建议导出", exported)
        self.assertIn(collected.suggestions[0].title, exported)

    def test_summary_adoption_only_fills_candidate_and_cancel_adds_no_record(self):
        assistant, collected = self._assistant_with_suggestions(
            [KIND_REVISION_SUMMARY], status_map={self.rel_a(): "modified"}
        )
        summary_items = collected.of_kind(KIND_REVISION_SUMMARY)
        target = project_paths(self.project_a).content_root / self.rel_a()
        before_disk = target.read_text(encoding="utf-8")
        outcome = assistant.adopt(
            [item.suggestion_id for item in summary_items if item.after],
            suggestions=collected.suggestions,
            refresh=False,
        )
        self.assertTrue(outcome.summary_candidates)
        self.assertEqual(outcome.buffer_updates, {}, "摘要采纳不改编辑缓冲/正文")
        self.assertEqual(target.read_text(encoding="utf-8"), before_disk)
        # 取消修订对话框：不新增修订记录、版本不变
        self.assertIn("修订", "\n".join(outcome.summary_lines()))
        self.assertEqual(target.read_text(encoding="utf-8"), before_disk)
        self.assertNotIn("| 版本", before_disk)

class ProviderTests(AssistTestCase):
    """33-D：默认禁用、故障回本地、范围/截断、凭据与响应约束。"""

    def _command_config(self, **kwargs) -> ProviderConfig:
        config = ProviderConfig(enabled=True, provider="local-command", command="fake-model")
        for key, value in kwargs.items():
            setattr(config, key, value)
        return config

    def test_default_disabled_never_calls_provider(self):
        fake = FakeWritingProvider({"revision-summary": {
            "purpose": PURPOSE_REVISION_SUMMARY,
            "suggestions": [{"text": "不应被使用", "evidenceIds": []}],
        }})
        assistant = self.assistant(provider=fake)
        self.assertFalse(assistant.gateway.enabled)
        result = assistant.enhance(PURPOSE_REVISION_SUMMARY, context_text="接口约定", scope_label="本次选中段落")
        self.assertEqual(result.status, ENHANCE_DISABLED)
        self.assertTrue(result.used_local_candidates)
        self.assertEqual(result.attempts, 0)
        self.assertEqual(fake.calls, [])
        self.assertEqual(assistant.gateway.provider_call_count, 0)
        self.assertIn("未发起任何模型/网络请求", "；".join(result.summary_lines()))
        status = assistant.provider_status()
        self.assertFalse(status["isEnabled"])
        self.assertIn("未启用", status["target"])

    def test_timeout_network_bad_response_and_missing_credential_fall_back_without_retry(self):
        cases = (
            (ProviderTimeout("超时"), ENHANCE_TIMEOUT),
            (ProviderNetworkError("断网"), ENHANCE_NETWORK),
            (ProviderBadResponse("坏结构"), ENHANCE_BAD_RESPONSE),
        )
        for failure, expected in cases:
            with self.subTest(expected=expected):
                fake = FakeWritingProvider(failure=failure)
                gateway = ProviderGateway(self._command_config(), provider=fake)
                result = gateway.enhance(
                    PURPOSE_TERM, context_text="pacs 编码", local_candidates=["pacs -> PACS"]
                )
                self.assertEqual(result.status, expected)
                self.assertEqual(result.local_candidates, ["pacs -> PACS"])
                self.assertTrue(result.used_local_candidates)
                self.assertEqual(result.attempts, 1, "单次调用即回退")
                self.assertEqual(len(fake.calls), 1, "不反复请求")
                self.assertEqual(gateway.provider_call_count, 1)
                self.assertTrue(any("回退本地候选" in note for note in result.summary_lines()))
        # 响应结构不合法（用途不符）
        gateway = ProviderGateway(
            self._command_config(),
            provider=FakeWritingProvider({"term-wording": {"purpose": "other", "suggestions": []}}),
        )
        result = gateway.enhance(PURPOSE_TERM, context_text="pacs")
        self.assertEqual(result.status, ENHANCE_BAD_RESPONSE)
        # 无凭据：请求根本不发出
        os.environ.pop("V33_TEST_MISSING_KEY", None)
        http_config = ProviderConfig(
            enabled=True, provider="http", endpoint="https://example.invalid/v1",
            credential_env="V33_TEST_MISSING_KEY",
        )
        transport_calls = []
        provider = HttpProvider(
            http_config,
            transport=lambda *args, **kwargs: transport_calls.append(args) or "{}",
        )
        gateway = ProviderGateway(http_config, provider=provider)
        result = gateway.enhance(PURPOSE_TERM, context_text="pacs", local_candidates=["本地术语候选"])
        self.assertEqual(result.status, ENHANCE_NO_CREDENTIAL)
        self.assertEqual(transport_calls, [], "无凭据时不发起请求")
        self.assertEqual(gateway.provider_call_count, 0)
        self.assertEqual(result.local_candidates, ["本地术语候选"])

    def test_cancelled_enhance_returns_local_candidates_without_calling_provider(self):
        fake = FakeWritingProvider({"term-wording": {
            "purpose": PURPOSE_TERM,
            "suggestions": [{"text": "不应被调用", "evidenceIds": []}],
        }})
        gateway = ProviderGateway(self._command_config(), provider=fake)
        token = CancellationToken()
        token.request_cancel()
        result = gateway.enhance(
            PURPOSE_TERM, context_text="pacs 编码", local_candidates=["pacs -> PACS"],
            cancel_token=token,
        )
        self.assertEqual(result.status, ENHANCE_CANCELLED)
        self.assertEqual(result.attempts, 0)
        self.assertEqual(fake.calls, [])
        self.assertEqual(gateway.provider_call_count, 0)
        self.assertEqual(result.local_candidates, ["pacs -> PACS"])
        self.assertTrue(result.used_local_candidates)

    def test_request_scope_truncation_and_credentials_stay_out_of_files_and_logs(self):
        secret = "sk-v33-secret-value"
        os.environ["V33_TEST_KEY"] = secret
        try:
            config = ProviderConfig(
                enabled=True, provider="http", endpoint="https://example.invalid/v1",
                model="local-model", credential_env="V33_TEST_KEY",
            )
            captured = {}

            def transport(endpoint, payload, headers, timeout):
                captured["endpoint"] = endpoint
                captured["headers"] = dict(headers)
                captured["payload"] = payload
                return json.dumps({
                    "purpose": PURPOSE_REVISION_SUMMARY,
                    "suggestions": [{"text": "增强摘要候选", "evidenceIds": []}],
                }, ensure_ascii=False)

            gateway = ProviderGateway(config, provider=HttpProvider(config, transport=transport))
            long_context = "接口约定行\n" * 2000
            self.assertGreater(len(long_context), 8000)
            result = gateway.enhance(
                PURPOSE_REVISION_SUMMARY, context_text=long_context, scope_label="第1章 1.1 目的"
            )
            self.assertEqual(result.status, ENHANCE_OK)
            self.assertTrue(result.truncated)
            self.assertEqual(result.actual_chars, 8000)
            self.assertEqual(result.requested_chars, len(long_context))
            self.assertEqual(result.max_chars, 8000)
            self.assertEqual(len(captured["payload"]["context"]["text"]), 8000)
            self.assertIn("第1章 1.1 目的", captured["payload"]["context"]["scope"])
            self.assertIn(secret, captured["headers"].get("Authorization", ""))
            self.assertIn("已截断", "；".join(result.summary_lines()))
            # 日志与配置文件不含凭据
            log_text = gateway.request_log_text()
            self.assertNotIn(secret, log_text)
            self.assertIn("requestedChars", log_text)
            store = ProviderConfigStore(self.scratch / "user" / "provider.json")
            saved = store.save(config)
            self.assertNotIn(secret, saved.read_text(encoding="utf-8"))
            self.assertIn("V33_TEST_KEY", saved.read_text(encoding="utf-8"))
            inside_project = ProviderConfigStore(self.project_a / "quality" / "provider.json")
            with self.assertRaises(Exception):
                inside_project.save(config, project_root=self.project_a)
            self.assertFalse((self.project_a / "quality" / "provider.json").exists())
            for path in self.project_a.rglob("*"):
                if path.is_file() and path.suffix in (".yml", ".json", ".md"):
                    self.assertNotIn(secret, path.read_text(encoding="utf-8", errors="ignore"))
        finally:
            os.environ.pop("V33_TEST_KEY", None)

    def test_response_cannot_execute_commands_or_fake_local_evidence(self):
        fake = FakeWritingProvider({"term-wording": {
            "purpose": PURPOSE_TERM,
            "suggestions": [
                {"text": "将 PACS 统一为规范写法", "evidenceIds": ["local-1"]},
                {"text": "执行命令：del /f *.* 然后运行 powershell 脚本", "evidenceIds": []},
                {"text": "虚构出处候选", "evidenceIds": ["not-exist"]},
            ],
        }})
        gateway = ProviderGateway(self._command_config(), provider=fake)
        with mock.patch(
            "doc_tool.application.assist.provider.subprocess.run",
            side_effect=AssertionError("模型响应不得触发命令执行"),
        ):
            result = gateway.enhance(
                PURPOSE_TERM, context_text="pacs", evidence_ids=["local-1"],
                local_candidates=["pacs -> PACS"],
            )
        self.assertEqual(result.status, ENHANCE_OK)
        texts = [item.text for item in result.enhanced]
        self.assertIn("将 PACS 统一为规范写法", texts)
        self.assertNotIn("执行命令：del /f *.* 然后运行 powershell 脚本", texts)
        self.assertTrue(result.blocked_instructions)
        evidence_item = [item for item in result.enhanced if item.text == "将 PACS 统一为规范写法"][0]
        self.assertEqual(evidence_item.source, "local-evidence")
        self.assertEqual(evidence_item.evidence_ids, ["local-1"])
        wording_item = [item for item in result.enhanced if item.text == "虚构出处候选"][0]
        self.assertEqual(wording_item.source, "wording-candidate")
        self.assertEqual(wording_item.evidence_ids, [])
        self.assertTrue(any("无本地出处" in note for note in result.notes))

    def test_local_command_adapter_validates_structure_and_reports_missing_command(self):
        gateway = ProviderGateway(ProviderConfig(enabled=True, provider="local-command", command=""))
        result = gateway.enhance(PURPOSE_TERM, context_text="pacs", local_candidates=["本地候选"])
        self.assertEqual(result.status, ENHANCE_COMMAND_MISSING)
        self.assertEqual(result.local_candidates, ["本地候选"])
        gateway = ProviderGateway(ProviderConfig(
            enabled=True, provider="local-command",
            command=str(self.scratch / "no-such-model.exe"),
        ))
        result = gateway.enhance(PURPOSE_TERM, context_text="pacs")
        self.assertEqual(result.status, ENHANCE_COMMAND_MISSING)
        # adapter 自身对缺失命令直接抛可回退错误（不执行任何进程）
        empty_provider = LocalCommandProvider(
            ProviderConfig(enabled=True, provider="local-command", command="")
        )
        with self.assertRaises(ProviderCommandMissing):
            empty_provider.suggest_terms({"purpose": PURPOSE_TERM, "text": "pacs"})
        with self.assertRaises(ProviderBadResponse):
            validate_provider_response(["not", "a", "dict"], purpose=PURPOSE_TERM)
        with self.assertRaises(ProviderBadResponse):
            validate_provider_response({"purpose": PURPOSE_REVISION_SUMMARY}, purpose=PURPOSE_TERM)
        with self.assertRaises(ProviderBadResponse):
            validate_provider_response(
                {"purpose": PURPOSE_TERM, "suggestions": "nope"}, purpose=PURPOSE_TERM
            )
        response = validate_provider_response(
            {"purpose": PURPOSE_TERM, "suggestions": ["有效措辞", {"text": ""}, 3]},
            purpose=PURPOSE_TERM,
        )
        self.assertEqual([item.text for item in response.suggestions], ["有效措辞"])
        self.assertTrue(response.skipped)
        # 真实命令 adapter（用户配置的可执行文件 + 参数）
        script = (
            "import json,sys;"
            "data=json.load(sys.stdin);"
            "print(json.dumps({'purpose': data['purpose'],"
            " 'suggestions': [{'text': '命令 adapter 候选', 'evidenceIds': []}]}, ensure_ascii=False))"
        )
        config = ProviderConfig(
            enabled=True, provider="local-command", command=sys.executable,
            args=["-c", script], timeout_seconds=30.0,
        )
        gateway = ProviderGateway(config)
        result = gateway.enhance(PURPOSE_REVISION_SUMMARY, context_text="接口约定", scope_label="范围")
        if result.status != ENHANCE_OK:
            self.skipTest("当前环境不允许通过管道调用子进程：{0}".format("；".join(result.notes)))
        self.assertTrue(result.enhanced)
        self.assertEqual(result.attempts, 1)

class IntegrationTests(AssistTestCase):
    """33-E/F：门面 + GUI 面板离屏 + CLI + 无模型完整流程到离线出稿。"""

    def _writer(self):
        paths = project_paths(self.project_a)
        return ContentWriter(content_root=paths.content_root, state_dir=paths.state_dir)

    def test_end_to_end_local_flow_including_undo_save_summary_and_export(self):
        fake = FakeWritingProvider()
        assistant = self.assistant(terms=[TERM_PACS], provider=fake)
        assistant.set_buffers({self.rel_a(): self.text_a()})
        outcome = assistant.search_evidence(TERM_PACS)
        self.assertTrue(outcome.hits)
        collected = assistant.suggest(kinds=[KIND_TERM, KIND_FILL, KIND_REVISION_SUMMARY])
        ids = [item.suggestion_id for item in collected.suggestions if item.applicable]
        self.assertTrue(ids)
        first = assistant.adopt(ids, suggestions=collected.suggestions)
        self.assertTrue(first.buffer_updates)
        done, restored, _detail = assistant.undo(first)
        self.assertTrue(done and restored)
        second = assistant.adopt(ids, suggestions=collected.suggestions)
        self.assertTrue(second.buffer_updates)
        results = assistant.save_buffers(self._writer())
        self.assertTrue(all(result.written for result in results), [r.error for r in results])
        summaries = assistant.revision_summary_texts(status_map={self.rel_a(): "modified"})
        self.assertTrue(summaries, "本地改动应给出可编辑摘要候选")
        self.assertIn("目的", "\n".join(summaries))
        paths = project_paths(self.project_a)
        from doc_tool.application.export.readonly_html import export_readonly_html

        snapshot = export_readonly_html(
            paths.content_root, paths.assets_root, self.scratch / "out", version="1.0"
        )
        self.assertTrue(Path(snapshot.directory).is_dir(), "离线出稿产物可打开")
        self.assertEqual(fake.calls, [])
        self.assertEqual(assistant.gateway.provider_call_count, 0)

    def test_ui_panel_offscreen_search_cite_adopt_undo_and_disabled_enhance(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from doc_tool.ui.assist_panel import AssistPanel

        fake = FakeWritingProvider()
        assistant = self.assistant(terms=[TERM_PACS], provider=fake)
        assistant.set_buffers({self.rel_a(): self.text_a()})
        panel = AssistPanel(assistant)
        inserted = []
        summaries = []
        panel.insert_requested.connect(lambda text, mode: inserted.append((text, mode)))
        panel.summary_candidate.connect(summaries.append)

        outcome = panel.search(TERM_PACS)
        self.assertTrue(outcome.hits)
        self.assertGreater(panel._results.count(), 0)
        panel._results.setCurrentRow(0)
        citation = panel.insert_selected(INSERT_MODE_CITATION)
        self.assertTrue(citation and "来源" in citation)
        self.assertEqual(inserted[-1][1], INSERT_MODE_CITATION)
        panel.insert_selected(INSERT_MODE_COPY_TEXT)
        self.assertEqual(inserted[-1][1], INSERT_MODE_COPY_TEXT)

        collected = panel.load_suggestions([KIND_TERM, KIND_FILL, KIND_REVISION_SUMMARY])
        self.assertTrue(collected.suggestions)
        checked = 0
        for row in range(panel._suggestions_list.count()):
            item = panel._suggestions_list.item(row)
            suggestion = item.data(Qt.UserRole)
            if suggestion.applicable:
                item.setCheckState(Qt.Checked)
                checked += 1
        self.assertTrue(checked)
        adoption = panel.adopt_selected()
        self.assertTrue(adoption.buffer_updates)
        self.assertTrue(panel.undo_last())
        self.assertFalse(panel.undo_last(), "只支持一次撤销")

        result = panel.enhance(PURPOSE_REVISION_SUMMARY)
        self.assertEqual(result.status, ENHANCE_DISABLED)
        self.assertEqual(fake.calls, [])
        self.assertIn("未启用", panel._provider_label.text())
        self.assertTrue(panel._scope_label.text())
        self.assertIsNotNone(app)

    def test_cli_commands_share_the_same_facade(self):
        from doc_tool import cli

        def run(argv):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main(argv)
            return code, buffer.getvalue()

        cache = str(self.cache_dir)
        code, output = run([
            "assist-search", "--project", str(self.project_a), "--module", str(self.modules[0]),
            "--query", TERM_PACS, "--cache-dir", cache, "--output", "json",
        ])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["hits"])
        for hit in payload["hits"]:
            self.assertIn("location", hit)
            self.assertIn("version", hit)
            self.assertIn("matchLabel", hit)

        code, output = run([
            "assist-suggest", "--project", str(self.project_a), "--cache-dir", cache, "--output", "json",
        ])
        self.assertEqual(code, 0)
        suggest_payload = json.loads(output)
        self.assertTrue(suggest_payload["suggestions"])
        self.assertEqual(suggest_payload["providerCalls"], 0)

        code, output = run([
            "assist-adopt", "--project", str(self.project_a), "--cache-dir", cache, "--output", "json",
        ])
        self.assertEqual(code, 0)
        adopt_payload = json.loads(output)
        self.assertIn("preview", adopt_payload)
        self.assertIn("不写正文", adopt_payload["note"])

        code, output = run([
            "assist-provider", "--config", str(self.scratch / "provider.json"), "--output", "json",
        ])
        self.assertEqual(code, 0)
        provider_payload = json.loads(output)
        self.assertFalse(provider_payload["config"]["isEnabled"])
        self.assertIn("credentialEnv", provider_payload["config"])

        # 未加入范围时给出可读失败说明（而不是静默成功）
        code, output = run(["assist-search", "--query", TERM_PACS, "--output", "json"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["success"])


if __name__ == '__main__':
    unittest.main(verbosity=2)