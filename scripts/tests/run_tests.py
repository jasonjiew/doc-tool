# -*- coding: utf-8 -*-
"""自定义测试运行器：隔离运行测试文件并生成 JUnit/coverage 产物。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DEFAULT_TESTS = [
    "test_docx_common.py", "test_ooxml_security.py", "test_validator_negative.py",
    "test_iteration_scenarios.py", "test_project_model.py", "test_import_preflight.py",
    "test_fidelity.py", "test_project_build.py", "test_import_project.py",
    "test_roundtrip.py", "test_style_mapping.py", "test_authoring_services.py",
    "test_issues.py", "test_format_check_search.py", "test_markdown_structure.py",
    "test_cli_machine.py", "test_quality_gates.py", "test_quality_traceability.py",
    "test_gui_services.py", "test_content_operations.py", "test_safety_recovery.py",
    "test_vcs_changes.py", "test_revision_record.py", "test_multi_window.py",
    "test_lock_log_cancel.py", "test_word_release.py", "test_convert.py",
    "test_template_fill.py", "test_pdf_toolbox.py", "test_packaging.py",
    "test_installer.py", "test_brand_consistency.py", "test_settings_migration.py",
    "test_migration.py", "test_self_heal.py", "test_public_export.py",
    "test_review_docx.py", "test_table_format.py", "test_command_palette.py",
    "test_validate_adaptation.py", "test_branch_ui.py", "test_action_positioning.py",
    "test_changes_refresh.py", "test_diagram_viewer_interaction.py", "test_operation_loading_overlay.py",
    "test_expression_contract.py", "test_prepared_source.py", "test_quality_gates_v27.py",
    "test_pipeline_gates_v27.py", "test_cli_check_v27.py", "test_contract_fidelity_v27.py",
    "test_schema_v2_migration.py", "test_chapter_order_variables_v28.py", "test_standard_pack_v28.py",
    "test_quality_location_v28.py", "test_overview_v28.py", "test_versioned_review_v28.py",
    "test_review_package_v28.py", "test_reimport_plan_v28.py", "test_project_from_pack_v28.py",
    "test_workspace_v29.py", "test_traceable_items_v29.py", "test_relations_v29.py",
    "test_trace_matrix_v29.py", "test_impact_v29.py", "test_collection_v29.py",
    "test_collection_ops_v29.py", "test_item_actions_v29.py", "test_asset_batch.py",
    "test_audit_fixes.py", "test_authoring_outline.py", "test_convert_ux.py",
    "test_delivery_history_ui.py", "test_frozen_smoke.py", "test_home_experience_iteration.py",
    "test_local_history.py", "test_project_loading_vcs_stability.py", "test_readonly_html.py",
    "test_recovery_entries.py", "test_revision_compatibility.py", "test_snippet_library.py",
    "test_step_list.py", "test_template_fill_plan.py", "test_template_fill_presets.py",
    "test_v26_ui_workflows.py", "test_word_compatibility_audit.py", "test_heading_style_collision.py",
    "test_intake_word_v28.py", "test_project_from_markdown_v28.py", "test_reimport_preview_v28.py",
    "test_matrix_page_v29.py", "test_stale_report_v28.py", "test_chapter_reorder_v28.py",
    "test_settings_v28.py", "test_bundled_standards_v28.py",
    "test_core_intake_contract.py", "test_core_intake_fallback.py",
    "test_core_intake_presets.py",
    "test_core_intake_presets_gui.py",
    "test_env_probe.py",
    "test_core_unsupported_objects.py",
    "test_core_unsupported_classification.py",
    "test_core_entries_ui.py", "test_core_export_snapshot.py", "test_export_round_recovery.py",
    "test_rd_workspace_surface.py", "test_rd_workspace_entry.py",
    "test_v34_table_authoring.py", "test_v35_standard_pack.py", "test_v36_large_document.py",
    "test_v34_v35_entries.py",
    "test_product_post_implementation_review.py",
    "test_core_scope_presets_batch.py", "test_core_layout_package.py",
    "test_core_cli_export.py", "test_core_result_page.py", "test_core_gui_loop.py",
    "test_core_hidpi_layout.py",
    "test_release_archive_runner.py",
    "test_acceptance_runbook.py",
    "test_runbook_verifier.py",
    "test_final_handover_report.py",
    "test_spec_gap_entries.py",
    "test_release_review_bundle.py",
    "test_core_export_ui.py",
    "test_v30_content_reuse.py", "test_v31_team_workflow.py",
    "test_v32_batch_delivery.py", "test_v33_authoring_assistance.py",
    "test_v31_command_registry.py",
    "test_v31_registry_integration.py",
    "test_v31_team_flow.py",
    "test_v31_flow_entry.py",
    "test_v31_registry_display.py",
    "test_v31_real_document_handoff.py",
    "test_v33_editor_wiring.py",
    "test_v33_adoption_editor.py",
    "test_v33_registry.py",
    "test_v33_three_document_pilot.py",
    "test_v33_background_index.py",
    "test_v33_panel_reachability.py",
    "test_v33_module_update_cancel.py",
    "test_v30_reuse_entry.py",
    "test_v30_pipeline_wiring.py",
    "test_v30_reuse_ui.py",
    "test_v30_offline_pilot.py",
    "test_v30_preview_instances.py",
    "test_v32_delivery_ui.py",
    "test_v32_delivery_progress.py",
    "test_v32_variant_export.py",
    "test_v32_word_busy_retry.py",
    "test_v32_package_version.py",
    "test_v32_collection_bridge.py",
    "test_v32_entry_points.py",
    "test_v32_real_word_formalize.py",
    "test_v32_cross_process_promote.py",
    "test_v32_delivery_entry.py",
    # UI 包 product-ui-interaction-polish（20 项）新增控件/接线用例。
    "test_ui_polish_entry_drop.py",
    "test_ui2_visual_hierarchy.py",
    "test_ui2_home_continue.py",
    "test_ui2_navigation.py",
    "test_ui2_reading_view.py",
    "test_ui2_export_settings.py",
    "test_ui2_panel_productivity.py",
    "test_ui2_acceptance.py",
    "test_ui_polish_quick_export.py",
    "test_ui_polish_layout_session.py",
    "test_ui_polish_toolbar.py",
    "test_ui_polish_geometry.py",
    "test_ui_polish_results.py",
    "test_ui_polish_advanced.py",
    "test_ui_polish_acceptance.py",
    "test_code_review_regressions.py",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", default=str(ROOT / "test-results.xml"))
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--coverage-min", type=float, default=0.0)
    parser.add_argument("--coverage-xml", default=str(ROOT / "coverage.xml"))
    parser.add_argument("--coverage-json", default=str(ROOT / "coverage.json"))
    parser.add_argument("tests", nargs="*")
    # 显式环境覆盖（如 UI 包 5.2 的离屏缩放证据需要 QT_SCALE_FACTOR）。
    parser.add_argument(
        "--env", action="append", default=[], metavar="KEY=VALUE",
        help="在子进程中覆盖的环境变量，可重复",
    )
    return parser.parse_args()


def run_one(name: str, coverage: bool, extra_env: dict | None = None) -> dict:
    print("\n== {0} ==".format(name), flush=True)
    command = [sys.executable]
    if coverage:
        command.extend(["-m", "coverage", "run", "--parallel-mode", "--source=doc_tool,scripts"])
    command.append(str(HERE / name))
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_pythonpath = env.get("PYTHONPATH", "")
    # 与启动脚本保持一致：若 PySide6 以 .vendor/site-packages 内嵌提供
    # （部分公司 PC 的 DLP 阻止 pip 原子重命名），把它前置到 PYTHONPATH，
    # 仓库根保持在路径中保证 doc_tool 可导入。
    paths = [str(ROOT)]
    vendor = ROOT / ".vendor" / "site-packages"
    if vendor.is_dir():
        paths.insert(0, str(vendor))
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    # 只补充与当前解释器同版本的第三方目录；混入其它版本的 site-packages
    # 会让纯 Python 包走对、二进制扩展（lxml/PySide6）因 ABI 不符导入失败。
    tag = "Python{0}{1}".format(*sys.version_info[:2])
    for candidate in [
        Path.home() / "AppData" / "Roaming" / "Python" / tag / "site-packages",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / tag / "Lib" / "site-packages",
    ]:
        if candidate.is_dir() and str(candidate) not in paths:
            paths.append(str(candidate))
    env["PYTHONPATH"] = os.pathsep.join(paths)
    for key, value in (extra_env or {}).items():
        env[str(key)] = str(value)
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", check=False,
    )
    duration = time.monotonic() - started
    print(completed.stdout, end="", flush=True)
    return {"name": name, "code": completed.returncode, "duration": duration, "output": completed.stdout}


def write_junit(path: Path, results: list[dict]) -> None:
    suite = ET.Element("testsuite", {
        "name": "doc-tool", "tests": str(len(results)),
        "failures": str(sum(1 for result in results if result["code"] != 0)),
        "time": "{0:.3f}".format(sum(result["duration"] for result in results)),
    })
    for result in results:
        case = ET.SubElement(suite, "testcase", {
            "name": result["name"], "classname": "scripts.tests",
            "time": "{0:.3f}".format(result["duration"]),
        })
        if result["code"] != 0:
            failure = ET.SubElement(case, "failure", {
                "message": "exit code {0}".format(result["code"]), "type": "TestFailure",
            })
            failure.text = result["output"][-12000:]
        output = ET.SubElement(case, "system-out")
        output.text = result["output"][-12000:]
    root = ET.Element("testsuites", {
        "tests": suite.attrib["tests"], "failures": suite.attrib["failures"],
        "time": suite.attrib["time"],
    })
    root.append(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def finish_coverage(args) -> int:
    subprocess.run([sys.executable, "-m", "coverage", "combine"], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, "-m", "coverage", "xml", "-o", args.coverage_xml], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, "-m", "coverage", "json", "-o", args.coverage_json], cwd=str(ROOT), check=True)
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "report", "--fail-under", str(args.coverage_min)],
        cwd=str(ROOT), check=False,
    )
    return report.returncode


def main() -> int:
    args = parse_args()
    tests = args.tests or DEFAULT_TESTS
    extra_env = {}
    for item in args.env:
        key, _, value = str(item).partition("=")
        if key:
            extra_env[key] = value
    results = [run_one(name, args.coverage, extra_env) for name in tests]
    write_junit(Path(args.junit), results)
    test_code = 1 if any(result["code"] != 0 for result in results) else 0
    coverage_code = finish_coverage(args) if args.coverage else 0
    return test_code or coverage_code


if __name__ == "__main__":
    sys.exit(main())
