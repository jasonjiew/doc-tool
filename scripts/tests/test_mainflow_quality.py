# -*- coding: utf-8 -*-
"""主流程质量回归：合成临时项目，不修改真实需求/详设项目，不启动 Word。"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.lint import ContentLinter, TermStore, reset_lint_result_cache
from doc_tool.application.content.quality_rules import (
    QualityRule, QualityRulesConfig, default_rules, validate_rule_payload,
)

SECTIONS = ["功能描述", "流程图", "时序图", "数据流图", "方法设计", "核心逻辑"]


def module_text(titles=None):
    return "\n\n".join("#### " + title + "\n说明。" for title in (SECTIONS if titles is None else titles))


def section_rule(**changes):
    params = {"paths": ["modules/*.md"], "sections": list(SECTIONS), "mode": "file", "section_level": 4}
    params.update(changes)
    return QualityRule("module_sections", True, "error", params)


def table_rule(**changes):
    params = {"paths": ["modules/*.md"], "schemas": [{
        "name": "功能明细", "match_headers": ["需求标识", "描述", "验收标准"],
        "required_headers": ["需求标识", "描述", "验收标准"],
        "required_cells": ["需求标识", "描述", "验收标准"],
        "aliases": {"需求标识": ["需求编号"], "描述": ["需求描述"]}, "min_rows": 1,
    }]}
    params.update(changes)
    return QualityRule("table_schema", True, "error", params)


class QualityFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mainflow-quality-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = self.root / "content" / "design"
        self.content.mkdir(parents=True)
        self.config = QualityRulesConfig(self.root / ".state", "design")
        reset_lint_result_cache()

    def put(self, name, text):
        path = self.content / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def raw_rules(self, value, *, legacy=False):
        path = self.root / (".state/quality_rules.json" if legacy else "quality/rules.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def run_rules(self, rules, text, name="modules/a.md"):
        self.put(name, text)
        self.config.save(rules)
        return ContentLinter(ContentIndexService(self.content).build(), self.config).check_report([])


class ConfigurationTests(QualityFixture):
    def test_shared_precedes_legacy(self):
        self.raw_rules({"rules": [QualityRule("todo_residual", True).to_dict()]}, legacy=True)
        shared = self.raw_rules({"rules": [QualityRule("todo_residual", False).to_dict()]})
        before = shared.read_bytes()
        loaded = self.config.load_result()
        self.assertEqual(loaded.source, "project")
        self.assertFalse(loaded.rules[0].enabled)
        self.assertEqual(shared.read_bytes(), before)

    def test_legacy_read_does_not_migrate(self):
        legacy = self.raw_rules({"rules": [QualityRule("todo_residual").to_dict()]}, legacy=True)
        original = legacy.read_bytes()
        self.assertEqual(self.config.load_result().source, "legacy")
        self.assertFalse((self.root / "quality").exists())
        self.assertEqual(legacy.read_bytes(), original)

    def test_save_shared_preserves_legacy(self):
        legacy = self.raw_rules({"rules": []}, legacy=True)
        before = legacy.read_bytes()
        self.config.save([QualityRule("todo_residual")])
        self.assertTrue((self.root / "quality/rules.json").is_file())
        self.assertEqual(legacy.read_bytes(), before)

    def test_shared_corrupt_does_not_silently_use_legacy(self):
        self.raw_rules({"rules": []}, legacy=True)
        path = self.raw_rules({"rules": []})
        path.write_text("{ broken", encoding="utf-8")
        result = self.config.load_result()
        self.assertEqual(result.source, "project")
        self.assertFalse(result.valid)
        self.assertTrue(result.fallback)
        self.assertTrue(result.diagnostics[0].line_no)

    def test_missing_config_uses_defaults_without_writes(self):
        self.assertEqual(self.config.load_result().source, "builtin")
        self.assertFalse((self.root / ".state").exists())
        self.assertFalse((self.root / "quality").exists())

    def test_empty_configuration_is_explicitly_not_run(self):
        report = self.run_rules([], "正文。")
        self.assertEqual(report.to_dict()["executedCount"], 0)
        self.assertFalse(report.to_dict()["complete"])
        self.assertEqual(report.issues, [])

    def test_unknown_enabled_rule_not_discarded(self):
        self.put("modules/a.md", "正文。")
        self.raw_rules({"rules": [{"rule_id": "not-installed", "enabled": True}]})
        report = ContentLinter(ContentIndexService(self.content).build(), self.config).check_report([])
        self.assertTrue(report.configuration_failed)
        self.assertTrue(any(x["ruleId"] == "not-installed" and x["status"] == "invalid" for x in report.rules))
        self.assertTrue(any(x.rule_id == "rule_configuration" for x in report.issues))

    def test_disabled_unknown_rule_is_retained_but_not_executed(self):
        self.raw_rules({"rules": [{"rule_id": "future-rule", "enabled": False}]})
        result = self.config.load_result()
        self.assertTrue(result.valid)
        self.assertFalse(result.rules[0].enabled)
        self.assertEqual(result.diagnostics[0].code, "unknown_rule")

    def test_bad_scalar_types_and_counts_are_diagnostics(self):
        for count in ("oops", "²", True, 0, -1, 1.5):
            with self.subTest(count=count):
                errors = validate_rule_payload([QualityRule("field_completeness", True, "error", {"fields": {"编号": {"count": count}}}).to_dict()])
                self.assertTrue(any(x.code == "field_count" for x in errors))
        for changes in ({"enabled": "false"}, {"enabled": 0}, {"severity": "fatal"}, {"params": []}):
            raw = {"rule_id": "todo_residual", **changes}
            self.assertTrue(any(x.severity == "error" for x in validate_rule_payload([raw])))

    def test_bad_regex_is_error_not_an_empty_pass(self):
        self.put("modules/a.md", "正文。")
        self.raw_rules({"rules": [QualityRule("field_completeness", True, "error", {"fields": {"编号": {"regex": "["}}}).to_dict()]})
        report = ContentLinter(ContentIndexService(self.content).build(), self.config).check_report([])
        self.assertTrue(report.configuration_failed)
        self.assertFalse(report.to_dict()["complete"])
        self.assertTrue(any("正则无效" in issue.message for issue in report.issues))

    def test_duplicates_do_not_choose_last_value(self):
        result = validate_rule_payload([QualityRule("todo_residual", True).to_dict(), QualityRule("todo_residual", False).to_dict()])
        self.assertTrue(any(x.code == "duplicate_rule" for x in result))
        path = self.raw_rules({"rules": []})
        path.write_text('{"rules": [], "rules": []}', encoding="utf-8")
        self.assertFalse(self.config.load_result().valid)

    def test_save_rejects_invalid_before_creating_files(self):
        with self.assertRaises(ValueError):
            self.config.save([QualityRule("todo_residual", True), QualityRule("field_completeness", True, params={"fields": {"编号": {"regex": "["}}})])
        self.assertFalse((self.root / "quality").exists())
        with self.assertRaises(PermissionError):
            QualityRulesConfig(self.root / ".state", "design", writable=False).save([])

    def test_cache_tracks_config_failures_and_repairs(self):
        self.put("modules/a.md", "正文。")
        index = ContentIndexService(self.content).build()
        linter = ContentLinter(index, self.config)
        first = linter.check_report([])
        self.assertTrue(linter.check_report([]).cache_hit)
        path = self.raw_rules({"rules": []})
        path.write_text("{", encoding="utf-8")
        broken = linter.check_report([])
        self.assertFalse(broken.cache_hit)
        self.assertTrue(broken.configuration_failed)
        self.config.save([QualityRule("todo_residual")])
        repaired = linter.check_report([])
        self.assertFalse(repaired.configuration_failed)
        self.assertFalse(repaired.cache_hit)
        self.assertNotEqual(first.configuration["fingerprint"], repaired.configuration["fingerprint"])

    def test_directory_save_target_is_rejected_without_false_success(self):
        self.config.file.mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.config.save([QualityRule("todo_residual")])
        self.assertEqual(list(self.config.file.iterdir()), [])
        terms = TermStore(self.root / ".state")
        terms.file.mkdir()
        self.assertIsNotNone(terms.save(["NEW"]))
        self.assertEqual(list(terms.file.iterdir()), [])

    def test_existing_pack_ruleId_is_supported_without_rewriting_resource(self):
        raw = [{"ruleId": "todo_residual", "enabled": True, "severity": "warning", "origin": "synthetic-pack"}]
        self.raw_rules({"rules": raw})
        loaded = self.config.load_result()
        self.assertTrue(loaded.valid)
        self.assertEqual(loaded.rules[0].rule_id, "todo_residual")
        self.config.save_payload(raw)
        self.assertEqual(json.loads(self.config.file.read_text(encoding="utf-8"))["rules"], raw)
        errors = validate_rule_payload([{"rule_id": "todo_residual", "ruleId": "term_case"}])
        self.assertTrue(any(x.code == "rule_id_conflict" for x in errors))

    def test_disabled_semantic_parameters_are_not_executed(self):
        report = self.run_rules([QualityRule("field_completeness", False, params={"fields": {"x": {"regex": "["}}})], "正文。")
        self.assertFalse(report.configuration_failed)
        self.assertEqual(report.rules[0]["status"], "disabled")
        self.assertEqual(report.issues, [])


class ModuleContractTests(QualityFixture):
    def test_file_module_accepts_real_fourth_level_sections(self):
        self.put("legacy/old.md", "历史模块，不适用本次规范。")
        report = self.run_rules([section_rule()], module_text())
        self.assertEqual(report.issues, [])
        self.assertEqual(report.rules[0]["status"], "executed")

    def test_missing_duplicate_wrong_order_and_extra_are_located(self):
        cases = [
            (SECTIONS[:2] + SECTIONS[3:], "缺少"),
            (SECTIONS + ["核心逻辑"], "重复"),
            ([SECTIONS[1], SECTIONS[0]] + SECTIONS[2:], "顺序"),
            (SECTIONS + ["额外同级"], "规范外"),
        ]
        for titles, expected in cases:
            with self.subTest(expected=expected):
                report = self.run_rules([section_rule()], module_text(titles))
                self.assertTrue(any(expected in x.message and x.line_no >= 1 and x.rel_path == "modules/a.md" for x in report.issues))

    def test_modules_cannot_borrow_sections_from_each_other(self):
        text = "### 模块A\n" + module_text() + "\n### 模块B\n" + module_text(SECTIONS[:-1])
        report = self.run_rules([section_rule(mode="heading", module_level=3)], text)
        failures = [x for x in report.issues if "缺少" in x.message]
        self.assertEqual(len(failures), 1)
        self.assertIn("模块B", failures[0].message)
        self.assertIn("核心逻辑", failures[0].message)

    def test_fenced_examples_do_not_supply_missing_sections(self):
        text = module_text(SECTIONS[:-1]) + "\n~~~markdown\n#### 核心逻辑\n~~~\n"
        report = self.run_rules([section_rule()], text)
        self.assertTrue(any("缺少" in x.message for x in report.issues))

    def test_inline_markers_and_numbered_titles_do_not_hide_headings(self):
        text = module_text().replace("#### 功能描述", "#### 4.7.25.1 功能描述 <!-- DOC-ITEM: sample -->")
        self.assertEqual(self.run_rules([section_rule()], text).issues, [])

    def test_no_matching_paths_is_not_a_pass(self):
        report = self.run_rules([section_rule(paths=["other/*.md"])], module_text())
        self.assertEqual(report.rules[0]["status"], "not-applicable")
        self.assertEqual(report.to_dict()["executedCount"], 0)
        self.assertFalse(report.to_dict()["complete"])

    def test_invalid_selectors_and_levels_are_rejected(self):
        for kwargs in ({"paths": ["../outside.md"]}, {"section_level": 0}, {"mode": "heading", "module_level": 4, "section_level": 4}, {"ordered": "true"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.config.save([section_rule(**kwargs)])

    def test_new_contracts_are_opt_in_for_all_document_types(self):
        for kind in ("general", "requirement", "design"):
            contracts = [r for r in default_rules(kind) if r.rule_id in ("module_sections", "table_schema")]
            self.assertEqual(len(contracts), 2)
            self.assertTrue(all(not r.enabled for r in contracts))


class TableContractTests(QualityFixture):
    def test_valid_alias_headers_and_escaped_pipes(self):
        text = "| 需求编号 | 需求描述 | 验收标准 |\n|---|---|---|\n| R-1 | A\\|B | 成功后可见 |\n"
        self.assertEqual(self.run_rules([table_rule()], text).issues, [])

    def test_metadata_and_overview_tables_are_not_requirement_rows(self):
        text = "| 功能编号 | F-1 |\n|---|---|\n| 功能描述 | 示例 |\n\n| 需求标识 | 描述 | 验收标准 |\n|---|---|---|\n| R-1 | 查询 | 显示结果 |\n"
        self.assertEqual(self.run_rules([table_rule()], text).issues, [])

    def test_missing_columns_empty_cells_and_zero_rows(self):
        cases = [("|需求标识|描述|\n|---|---|\n|R-1|说明|", "缺少必需列"),
                 ("|需求标识|描述|验收标准|\n|---|---|---|\n|R-1||可观察结果|", "必填字段"),
                 ("|需求标识|描述|验收标准|\n|---|---|---|", "数据行不足")]
        for text, message in cases:
            with self.subTest(message=message):
                report = self.run_rules([table_rule()], text)
                self.assertTrue(any(message in x.message and x.line_no >= 1 for x in report.issues))

    def test_fenced_tables_cannot_satisfy_contract(self):
        text = "```markdown\n|需求标识|描述|验收标准|\n|---|---|---|\n|R|D|A|\n```"
        self.assertTrue(any("未发现匹配" in x.message for x in self.run_rules([table_rule()], text).issues))

    def test_inline_markers_do_not_drop_required_data_rows(self):
        text = "|需求标识|描述|验收标准|\n|---|---|---|\n|R-1|说明<!-- DOC-ITEM: sample -->|可观察结果|"
        self.assertEqual(self.run_rules([table_rule()], text).issues, [])

    def test_legal_variants_choose_specific_schema(self):
        rule = table_rule()
        rule.params["schemas"].append({"name": "第三方能力", "match_headers": ["产品需求", "需求标识", "验收标准"],
                                      "required_headers": ["需求标识", "产品需求", "验收标准"], "min_rows": 1})
        text = "|需求标识|产品需求|验收标准|\n|---|---|---|\n|R-1|对接|可观察结果|"
        self.assertEqual(self.run_rules([rule], text).issues, [])

    def test_alias_cannot_make_two_required_columns_use_one_real_column(self):
        rule = table_rule()
        rule.params["schemas"][0]["aliases"] = {"描述": ["需求标识"]}
        with self.assertRaises(ValueError):
            self.config.save([rule])

    def test_required_cells_must_refer_to_configured_columns(self):
        rule = table_rule()
        rule.params["schemas"][0]["required_cells"] = ["拼错的列"]
        with self.assertRaises(ValueError):
            self.config.save([rule])


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        from scripts.tests import test_project_build as T
        self.temp = tempfile.TemporaryDirectory(prefix="mainflow-app-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(T._setup_project(self.temp.name))
        self.manifest = T._make_manifest(str(self.project))
        self.manifest.save(self.project)
        self.paths = self.manifest.resolve_paths(self.project)
        self.config = QualityRulesConfig(self.paths.state_dir, self.manifest.documentType)

    def test_readonly_check_emits_execution_facts_without_project_writes(self):
        from doc_tool.application.check import run_check
        self.config.save([QualityRule("todo_residual", True), QualityRule("term_case", False)])
        before = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        report = run_check(self.project)
        after = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(report.quality["configuration"]["source"], "project")
        self.assertEqual(report.quality["disabledCount"], 1)
        self.assertIn("quality", report.to_dict())

    def test_zero_rule_check_is_not_reported_as_passed(self):
        from doc_tool.application.check import run_check
        self.config.save([])
        report = run_check(self.project)
        self.assertEqual(report.stages[0].status, "skipped")
        self.assertEqual(report.status, "warning")
        self.assertFalse(report.quality["complete"])
        self.assertEqual(run_check(self.project, strict=True).exit_code, 1)

    def test_bad_settings_are_rejected_before_any_file_write(self):
        from doc_tool.application.settings import save_settings
        before = (self.project / "project.yml").read_bytes()
        outcome = save_settings(self.project, {"documentName": "不应保存", "rules": [{"rule_id": "unknown-enabled"}]})
        self.assertFalse(outcome.ok)
        self.assertIn("rules", outcome.errors)
        self.assertEqual((self.project / "project.yml").read_bytes(), before)
        self.assertFalse((self.project / "quality").exists())

    def test_rule_only_settings_save_does_not_touch_manifest(self):
        from doc_tool.application.settings import save_settings, load_settings
        before = (self.project / "project.yml").read_bytes()
        outcome = save_settings(self.project, {"rules": [QualityRule("todo_residual", False).to_dict()]})
        self.assertTrue(outcome.ok, outcome.errors)
        self.assertEqual((self.project / "project.yml").read_bytes(), before)
        self.assertEqual(load_settings(self.project).field("规则", "rules").value[0]["enabled"], False)

    def test_real_cli_process_preserves_json_and_failure_exit_codes(self):
        import os, subprocess, sys
        self.config.save([QualityRule("todo_residual")])
        command = [sys.executable, "-c", "import sys; from doc_tool.cli import main; raise SystemExit(main(sys.argv[1:]))",
                   "check", "--project", str(self.project), "--output", "json"]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", GIT_OPTIONAL_LOCKS="0", QT_QPA_PLATFORM="offscreen")
        def invoke():
            return subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        valid = invoke()
        self.assertEqual(valid.returncode, 0, valid.stderr)
        payload = json.loads(valid.stdout)
        self.assertEqual(payload["quality"]["configuration"]["source"], "project")
        self.assertEqual(payload["quality"]["executedCount"], 1)
        self.config.file.write_text(json.dumps({"rules": [{"rule_id": "not-installed", "enabled": True}]}), encoding="utf-8")
        invalid = invoke()
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        payload = json.loads(invalid.stdout)
        self.assertFalse(payload["quality"]["configuration"]["valid"])
        self.assertTrue(any(item["type"] == "rule_configuration" for item in payload["issues"]))

    def test_bad_shared_configuration_remains_editable_with_warning(self):
        from doc_tool.application.settings import load_settings
        path = self.project / "quality/rules.json"
        path.parent.mkdir(exist_ok=True)
        raw = {"rules": [{"rule_id": "todo_residual", "enabled": "false"}]}
        path.write_text(json.dumps(raw), encoding="utf-8")
        model = load_settings(self.project)
        self.assertTrue(model.warnings)
        self.assertEqual(model.field("规则", "rules").value, raw["rules"])

    def test_invalid_configuration_stops_build_and_preserves_existing_output(self):
        from doc_tool.application.pipeline import run_pipeline, STAGE_LINT
        from doc_tool.adapters.kernel import config_from_project
        self.manifest.documentVersion = "3.8"
        previous = Path(config_from_project(self.manifest, self.paths)["paths"]["output"])
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(b'previous-output')
        self.config.file.parent.mkdir(parents=True, exist_ok=True)
        self.config.file.write_text("{ broken", encoding="utf-8")
        with mock.patch("doc_tool.adapters.kernel.build_with_project") as builder:
            result = run_pipeline(self.manifest, self.paths, skip_word_refresh=True)
        self.assertFalse(result.success)
        self.assertTrue(any(e.stage == STAGE_LINT and e.status == "failed" for e in result.events))
        builder.assert_not_called()
        self.assertEqual(previous.read_bytes(), b'previous-output')

    def test_lint_exception_is_not_an_empty_success(self):
        from doc_tool.application.pipeline import run_pipeline, STAGE_LINT
        with mock.patch("doc_tool.application.pipeline._run_prebuild_lint", side_effect=RuntimeError("synthetic fault")), mock.patch("doc_tool.adapters.kernel.build_with_project") as builder:
            result = run_pipeline(self.manifest, self.paths, skip_word_refresh=True)
        self.assertFalse(result.success)
        self.assertTrue(any(e.stage == STAGE_LINT and e.status == "failed" for e in result.events))
        builder.assert_not_called()

    def test_failed_build_cannot_yield_successful_check(self):
        from doc_tool.application.check import run_check
        from doc_tool.application.pipeline import PipelineResult
        self.config.save([QualityRule("todo_residual")])
        with mock.patch("doc_tool.application.pipeline.run_pipeline", return_value=PipelineResult(success=False)):
            report = run_check(self.project, build=True)
        self.assertEqual(report.exit_code, 1)
        self.assertTrue(any(x.issue_type == "build_failed" for x in report.issues))

    def test_legacy_cli_lint_also_exposes_execution_report(self):
        from doc_tool.application.cli_commands import lint_command
        self.config.save([QualityRule("todo_residual", False)])
        report = lint_command([str(self.project)])
        self.assertIn("quality", report.results[0].data)

    def test_terms_use_shared_location_without_migration_on_load(self):
        legacy = self.paths.state_dir / "terms.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text('["OLD"]', encoding="utf-8")
        shared = self.project / "quality/terms.json"
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text('{"terms":["NEW"]}', encoding="utf-8")
        store = TermStore(self.paths.state_dir)
        self.assertEqual(store.load(), ["NEW"])
        self.assertIsNone(store.save(["NEW", "NEXT"]))
        self.assertEqual(legacy.read_text(encoding="utf-8"), '["OLD"]')
        self.assertEqual(store.load(), ["NEW", "NEXT"])

    def test_shared_term_edit_keeps_existing_metadata(self):
        shared = self.project / "quality/terms.json"
        shared.parent.mkdir(parents=True, exist_ok=True)
        original = {"schemaVersion": 1, "owner": "synthetic-team", "terms": [
            {"canonical": "WiFi", "note": "must-keep"}, "API"]}
        shared.write_text(json.dumps(original), encoding="utf-8")
        store = TermStore(self.paths.state_dir)
        self.assertEqual(store.load(), ["WiFi", "API"])
        self.assertIsNone(store.save(["WiFi", "API", "NEW"]))
        current = json.loads(shared.read_text(encoding="utf-8"))
        self.assertEqual(current["owner"], "synthetic-team")
        self.assertEqual(current["terms"][0], original["terms"][0])
        self.assertIn("NEW", current["terms"])

    def test_settings_preserve_rich_resources_across_save(self):
        from doc_tool.application.settings import load_settings, save_settings
        shared = self.project / "quality/terms.json"
        shared.parent.mkdir(parents=True, exist_ok=True)
        data = {"owner": "synthetic-team", "terms": [{"canonical": "需求", "aliases": ["需求项"], "note": "keep"}]}
        shared.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        raw_rules = [{"ruleId": "todo_residual", "enabled": True, "severity": "warning", "origin": "synthetic-pack"}]
        self.config.save_payload(raw_rules)
        before = (self.project / "project.yml").read_bytes()
        model = load_settings(self.project)
        self.assertEqual(model.field("术语", "terms").value, data["terms"])
        outcome = save_settings(self.project, {"terms": model.field("术语", "terms").value, "rules": raw_rules})
        self.assertTrue(outcome.ok, outcome.errors)
        self.assertEqual(json.loads(shared.read_text(encoding="utf-8")), data)
        self.assertEqual(json.loads(self.config.file.read_text(encoding="utf-8"))["rules"], raw_rules)
        self.assertEqual((self.project / "project.yml").read_bytes(), before)

    def test_bad_terms_cannot_look_like_a_passed_enabled_rule(self):
        from doc_tool.application.check import run_check
        self.config.save([QualityRule("term_case", True)])
        shared = self.project / "quality/terms.json"
        shared.write_text("{ broken", encoding="utf-8")
        report = run_check(self.project)
        self.assertEqual(report.exit_code, 1)
        self.assertTrue(any(x.issue_type == "rule_configuration" for x in report.issues))


class GuiReadOnlyTests(QualityFixture):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_check_button_does_not_persist_terms(self):
        from doc_tool.ui.content.lint_panel import LintPanel
        self.put("modules/a.md", "正文。")
        self.config.save([QualityRule("todo_residual")])
        terms = TermStore(self.root / ".state")
        linter = ContentLinter(ContentIndexService(self.content).build(), self.config)
        panel = LintPanel(linter, terms, writable=False)
        self.addCleanup(panel.close)
        with mock.patch.object(terms, "save", side_effect=AssertionError("检查不应保存配置")):
            panel.run_check()
        self.assertIn("规则来源", panel._status_label.text())
        self.assertFalse((self.root / "quality/terms.json").exists())

    def test_current_chapter_filter_does_not_hide_config_error(self):
        from doc_tool.ui.content.lint_panel import LintPanel
        self.put("modules/a.md", "正文。")
        self.raw_rules({"rules": [{"rule_id": "invalid-enabled"}]})
        linter = ContentLinter(ContentIndexService(self.content).build(), self.config)
        panel = LintPanel(linter, TermStore(self.root / ".state"), scope_provider=lambda: ("current", "modules/a.md", []))
        self.addCleanup(panel.close)
        panel._scope_combo.setCurrentIndex(1)
        panel.run_check()
        self.assertTrue(any(x.rule_id == "rule_configuration" for x in panel._issues))


if __name__ == '__main__':
    unittest.main()
