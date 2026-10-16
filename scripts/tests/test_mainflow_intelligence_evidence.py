# -*- coding: utf-8 -*-
"""Evidence ranking and complete cause-based import follow-up regressions."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtWidgets import QApplication
from doc_tool.application.assist.search_local import EvidenceSource, LocalEvidenceSearch
from doc_tool.application.assist.models import SOURCE_KIND_PROJECT
from doc_tool.application.intake_contract import (
    HANDLING_EDITABLE, HANDLING_ORIGINAL_ONLY, HANDLING_PLACEHOLDER, HANDLING_SKIPPED,
)
from doc_tool.application.intake_result_page import IntakeResultPage, summarize_followups
APP = QApplication.instance() or QApplication([])


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mainflow-rank-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")

    def searcher(self):
        return LocalEvidenceSearch([EvidenceSource(source_id="project-a", kind=SOURCE_KIND_PROJECT,
            label="离线样例", root=str(self.root))], cache_enabled=False)

    def test_heading_after_the_limit_is_not_lost(self):
        self.write("a.md", "\n".join("这里说明接口" for _ in range(200)))
        self.write("z.md", "# 接口指南\n")
        result = self.searcher().search("接口", limit=1)
        self.assertEqual(result.total, 201)
        self.assertEqual(result.file_count, 2)
        self.assertTrue(result.truncated)
        self.assertEqual(result.hits[0].rel_path, "z.md")
        self.assertIn("标题命中", result.hits[0].rank_reasons)

    def test_exact_identifier_outranks_prefix_matches(self):
        self.write("a.md", "# REQ-1234 的内容\n")
        self.write("z.md", "稳定条目 REQ-123 定义\n")
        result = self.searcher().search("REQ-123", limit=1)
        self.assertEqual(result.hits[0].rel_path, "z.md")
        self.assertIn("完整标识符匹配", result.hits[0].rank_reasons)

    def test_two_character_chinese_search_and_regex_are_preserved(self):
        self.write("a.md", "# 接口\n这里接入服务\n接口正文\n")
        search = self.searcher()
        self.assertEqual(search.search("接口").total, 2)
        self.assertEqual(search.search(r"接[口入]", regex=True).total, 3)
        self.assertTrue(search.search("[", regex=True).error)

    def test_equal_scores_have_stable_natural_path_order(self):
        self.write("2.md", "接口正文\n")
        self.write("10.md", "接口正文\n")
        search = self.searcher()
        first = [h.rel_path for h in search.search("接口").hits]
        second = [h.rel_path for h in search.search("接口").hits]
        self.assertEqual(first, second)
        self.assertEqual(first, ["2.md", "10.md"])

    def test_changed_source_remains_marked_and_does_not_rank_as_latest(self):
        self.write("a.md", "# 接口\n")
        self.write("z.md", "接口正文\n")
        search = self.searcher()
        search.search("接口")
        self.write("a.md", "# 源内容已经改变，旧命中不能当最新\n")
        result = search.search("接口", refresh_stale=False)
        self.assertEqual(result.hits[0].rel_path, "z.md")
        stale = next(h for h in result.hits if h.rel_path == "a.md")
        self.assertTrue(stale.stale)
        self.assertEqual(stale.to_dict()["freshness"], "stale")

    def test_fenced_code_is_not_given_a_heading_bonus(self):
        self.write("a.md", "```python\n# 接口\n```\n")
        self.write("z.md", "# 接口\n")
        result = self.searcher().search("接口", limit=1)
        self.assertEqual(result.hits[0].rel_path, "z.md")

    def test_file_target_resolution_is_per_document_not_per_matching_line(self):
        from unittest.mock import patch
        self.write("a.md", "接口正文\n" * 1000)
        search = self.searcher()
        search.ensure_index()
        with patch.object(search, "_document_file_path", wraps=search._document_file_path) as resolver:
            result = search.search("接口", limit=5)
        self.assertEqual(result.total, 1000)
        self.assertLessEqual(resolver.call_count, 3)

    def test_cancel_is_observed_inside_a_single_large_document(self):
        self.write("a.md", "接口正文\n" * 10000)
        search = self.searcher()
        search.ensure_index()
        class Token:
            checks = 0
            @property
            def is_cancelled(self):
                self.checks += 1
                return self.checks >= 3
        result = search.search("接口", limit=5, cancel_token=Token())
        self.assertTrue(result.cancelled)
        self.assertGreater(result.total, 0)
        self.assertLessEqual(result.total, 128)

    def test_ranking_is_explained_in_gui_tooltip(self):
        from doc_tool.ui.assist_panel import AssistPanel
        self.write("a.md", "# 接口\n")
        hit = self.searcher().search("接口").hits[0]
        self.assertIn("标题", AssistPanel._hit_item(hit).toolTip())
        self.assertIn("rankReasons", hit.to_dict())


class ImportFollowupTests(unittest.TestCase):
    def rows(self):
        return ([{"feature": "image", "handling": HANDLING_PLACEHOLDER,
                  "target_chapter": "第1章", "target_rel_path": "a.md", "detail": "缺图 {0}".format(i)}
                 for i in range(65)] +
                [{"feature": "formula", "handling": HANDLING_ORIGINAL_ONLY, "detail": "仅原件"} for _ in range(3)] +
                [{"feature": "comment", "handling": HANDLING_SKIPPED, "detail": "范围之外未执行"} for _ in range(4)])

    def test_counts_use_all_findings_not_first_forty_or_action_limit(self):
        groups = summarize_followups(self.rows(), retained_available=True)
        self.assertEqual(sum(g["count"] for g in groups), 72)
        self.assertEqual(next(g["count"] for g in groups if g["handling"] == HANDLING_PLACEHOLDER), 65)

    def test_original_only_and_skipped_are_not_called_editable(self):
        groups = summarize_followups(self.rows(), retained_available=True)
        original = next(g for g in groups if g["handling"] == HANDLING_ORIGINAL_ONLY)
        skipped = next(g for g in groups if g["handling"] == HANDLING_SKIPPED)
        self.assertEqual(original["action"], "view-original")
        self.assertIn("不是可编辑保留", original["nextStep"])
        self.assertIn("未执行", skipped["nextStep"])

    def test_missing_original_is_not_offered_as_readable(self):
        groups = summarize_followups(self.rows(), retained_available=False)
        original = next(g for g in groups if g["handling"] == HANDLING_ORIGINAL_ONLY)
        self.assertNotEqual(original["action"], "view-original")
        self.assertIn("不可用", original["nextStep"])

    def test_editable_items_do_not_create_a_new_required_review(self):
        self.assertEqual(summarize_followups([{"feature": "table", "handling": HANDLING_EDITABLE}]), [])

    def test_window_keeps_all_rows_paged_and_filters_handling(self):
        from doc_tool.ui.intake_result_window import IntakeResultWindow, PAGE_SIZE
        rows = self.rows()
        page = IntakeResultPage(projectRoot="offline-fixture", details=rows,
            followUps=summarize_followups(rows, retained_available=False))
        window = IntakeResultWindow(page, host=Mock())
        self.addCleanup(window.close)
        self.assertEqual(len(window._filtered), 72)
        self.assertEqual(window._table.rowCount(), PAGE_SIZE)
        self.assertIn("65", window._followups.text())
        window._handling_combo.setCurrentIndex(window._handling_combo.findData(HANDLING_SKIPPED))
        self.assertEqual(len(window._filtered), 4)
        self.assertTrue(all(r["handling"] == HANDLING_SKIPPED for r in window._filtered))

    def test_after_page_one_items_still_reach_the_same_host_locator(self):
        from doc_tool.ui.intake_result_window import IntakeResultWindow
        rows = self.rows()
        page = IntakeResultPage(projectRoot="project-a", details=rows)
        host = Mock()
        window = IntakeResultWindow(page, host=host)
        self.addCleanup(window.close)
        window._turn_page(1)
        window._table.selectRow(0)
        window._on_locate()
        host._locate_intake_finding.assert_called_once()
        args = host._locate_intake_finding.call_args.args
        self.assertIs(args[0], page)
        self.assertEqual(args[1]["detail"], "缺图 50")

    def test_new_followups_are_additive_in_the_page_contract(self):
        page = IntakeResultPage(details=self.rows(), followUps=summarize_followups(self.rows()))
        result = page.to_dict()
        self.assertEqual(len(result["details"]), 72)
        self.assertTrue(result["followUps"])


class ImageRepairIntegrityTests(unittest.TestCase):
    """A single repair is not permission to clear a chapter's whole ledger."""

    def setUp(self):
        from scripts.tests import core_fixtures as fixtures
        from doc_tool.application.import_record import ImportRecord, write_import_record
        from doc_tool.application.intake_contract import PreservationFinding, PLACEHOLDER_PREFIX
        from doc_tool.domain.manifest import ProjectManifest
        self.tmp = tempfile.TemporaryDirectory(prefix="mainflow-image-integrity-")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.project = fixtures.two_chapter_project(self.work / "project")
        self.manifest = ProjectManifest.load(self.project)
        self.content = self.project / self.manifest.relative_content_root()
        self.rel = "第1章 引言/1.1 目的.md"
        self.other = "第2章 设计/2.1 架构.md"
        self.target = self.content / self.rel
        self.target.write_text("# 引言\n" + PLACEHOLDER_PREFIX + " 图片一]]\n中间正文\n"
                               + PLACEHOLDER_PREFIX + " 图片二]]\n", encoding="utf-8")
        self.replacement = fixtures.tiny_png(self.work / "replacement.png")
        record = ImportRecord(findings=[
            PreservationFinding("image", HANDLING_PLACEHOLDER, target_chapter="第1章 引言",
                target_path=self.rel, target_line=2, detail="first"),
            PreservationFinding("image", HANDLING_PLACEHOLDER, target_chapter="第1章 引言",
                target_path=self.rel, target_line=4, detail="second"),
            PreservationFinding("image", HANDLING_PLACEHOLDER, target_chapter="第2章 设计",
                target_path=self.other, target_line=2, detail="other chapter"),
        ])
        write_import_record(self.project, record)

    def repair(self, **kwargs):
        from doc_tool.application.intake_result_page import replace_placeholder_image
        return replace_placeholder_image(self.project, self.rel, self.replacement, **kwargs)

    def digest(self):
        import hashlib
        return {p.relative_to(self.project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.project.rglob("*") if p.is_file()}

    def host(self, *, writable=True, buffers=None):
        from types import SimpleNamespace
        return SimpleNamespace(
            _project_summary=SimpleNamespace(project_root=self.project, is_writable=writable),
            _content_workspace=None,
            _collect_assist_buffer_texts=Mock(return_value=buffers or {}),
            _show_status_message=Mock(),
        )

    def test_existing_relative_original_is_available_from_project_not_process_cwd(self):
        from doc_tool.application.import_record import read_import_record, write_import_record
        from doc_tool.application.intake_contract import PreservationFinding
        from doc_tool.application.intake_result_page import build_result_page
        original = self.project / "original" / "source.docx"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"synthetic retained original; not opened by Word")
        record = read_import_record(self.project)
        record.retainedPath = "original/source.docx"
        record.findings = [PreservationFinding("formula", HANDLING_ORIGINAL_ONLY)]
        write_import_record(self.project, record)
        page = build_result_page(self.project)
        self.assertEqual(page.followUps[0]["action"], "view-original")

    def test_only_exact_repaired_finding_is_resolved(self):
        from doc_tool.application.import_record import read_import_record
        result = self.repair(line=2)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.updatedFindings, 1)
        rows = read_import_record(self.project).findings
        self.assertEqual([r.handling for r in rows],
                         [HANDLING_EDITABLE, HANDLING_PLACEHOLDER, HANDLING_PLACEHOLDER])
        self.assertIn("图片二", self.target.read_text(encoding="utf-8"))

    def test_stale_explicit_line_never_falls_through_to_another_placeholder(self):
        before = self.digest()
        result = self.repair(line=3)
        self.assertFalse(result.ok)
        self.assertEqual(self.digest(), before)

    def test_ambiguous_missing_line_requires_location_not_first_image_guess(self):
        before = self.digest()
        result = self.repair()
        self.assertFalse(result.ok)
        self.assertEqual(self.digest(), before)

    def test_readonly_manifest_is_rejected_before_assets_or_body_writes(self):
        from doc_tool.domain.manifest import ProjectManifest
        from unittest.mock import patch
        before = self.digest()
        with patch.object(ProjectManifest, "is_writable", return_value=False):
            result = self.repair(line=2)
        self.assertFalse(result.ok)
        self.assertEqual(self.digest(), before)

    def test_host_readonly_stops_before_file_dialog(self):
        from doc_tool.ui.main_window import MainWindow
        from unittest.mock import patch
        host = self.host(writable=False)
        with patch("doc_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(self.replacement), "")) as picker:
            result = MainWindow._replace_intake_image(host, IntakeResultPage(projectRoot=str(self.project)),
                {"target_path": self.rel, "target_line": 2})
        self.assertFalse(result)
        picker.assert_not_called()

    def test_host_dirty_target_stops_without_saving_or_overwriting(self):
        from doc_tool.ui.main_window import MainWindow
        from unittest.mock import patch
        host = self.host(buffers={self.rel: "later unsaved author text"})
        before = self.digest()
        with patch("doc_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(self.replacement), "")) as picker:
            result = MainWindow._replace_intake_image(host, IntakeResultPage(projectRoot=str(self.project)),
                {"target_path": self.rel, "target_line": 2})
        self.assertFalse(result)
        picker.assert_not_called()
        self.assertEqual(self.digest(), before)

    def test_host_rechecks_dirty_target_after_file_picker_returns(self):
        from doc_tool.ui.main_window import MainWindow
        from unittest.mock import patch
        host = self.host()
        host._collect_assist_buffer_texts.side_effect = [{}, {self.rel: "editing continued"}]
        before = self.digest()
        with patch("doc_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(self.replacement), "")) as picker:
            result = MainWindow._replace_intake_image(host, IntakeResultPage(projectRoot=str(self.project)),
                {"target_path": self.rel, "target_line": 2})
        self.assertFalse(result)
        picker.assert_called_once()
        self.assertEqual(self.digest(), before)

    def test_host_old_project_result_cannot_write_after_project_switch(self):
        from doc_tool.ui.main_window import MainWindow
        from unittest.mock import patch
        host = self.host()
        with patch("doc_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(self.replacement), "")) as picker:
            result = MainWindow._replace_intake_image(host,
                IntakeResultPage(projectRoot=str(self.work / "old-project")),
                {"target_path": self.rel, "target_line": 2})
        self.assertFalse(result)
        picker.assert_not_called()

    def test_ledger_write_failure_keeps_body_readable_and_does_not_claim_all_resolved(self):
        from doc_tool.application.import_record import read_import_record
        from unittest.mock import patch
        with patch("doc_tool.application.intake_result_page.write_import_record", side_effect=OSError("owned fixture disk failure")):
            result = self.repair(line=2)
        self.assertTrue(result.ok)
        self.assertIn("images/", self.target.read_text(encoding="utf-8"))
        self.assertEqual(result.updatedFindings, 0)
        self.assertIn("记录", result.summary_line())
        self.assertEqual(read_import_record(self.project).to_fix_count(), 3)


if __name__ == "__main__":
    unittest.main()
