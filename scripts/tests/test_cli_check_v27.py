# -*- coding: utf-8 -*-
"""V2.7 27-G：统一 ``check`` 入口的退出码与可解析输出（7.2、7.3、7.4）。"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_project_build as T  # noqa: E402
from doc_tool.cli import main  # noqa: E402


def _project(root: Path) -> str:
    """建一个含 ``project.yml`` 的可检查项目。"""
    T._setup_project(str(root))
    manifest = T._make_manifest(str(root))
    manifest.save(str(root))
    return str(root)


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class CheckCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v27-check-"))
        self.project = _project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_is_single_document_with_required_keys(self):
        code, out, err = _run(
            ["check", "--project", self.project, "--output", "json"]
        )
        data = json.loads(out)
        for key in (
            "schemaVersion",
            "command",
            "projectId",
            "status",
            "issues",
            "stages",
            "artifacts",
            "exitCode",
        ):
            self.assertIn(key, data, key)
        self.assertEqual(data["command"], "check")
        self.assertEqual(data["exitCode"], code)
        self.assertIn(data["status"], ("ok", "warning", "failed"))
        self.assertIn("lint", {stage["stage"] for stage in data["stages"]})
        # 未请求构建时必须如实标记 skipped，不当通过。
        build_stage = [s for s in data["stages"] if s["stage"] == "build"][0]
        self.assertEqual(build_stage["status"], "skipped")

    def test_warning_threshold_exit_codes(self):
        from unittest import mock

        from doc_tool.application import check as check_module
        from doc_tool.application.issues import IssueRecord

        def _issues(*_args, **_kwargs):
            return [
                IssueRecord(
                    source="lint",
                    issue_type="todo_residual",
                    document_type="requirement",
                    severity="warning",
                    rel_path="a.md",
                    line_no=2,
                    error_code=None,
                    message="待办残留",
                )
            ]

        with mock.patch.object(check_module, "_collect_lint_issues", _issues):
            code_error, out_error, _err = _run(
                ["check", "--project", self.project, "--output", "json"]
            )
            code_warn, out_warn, _err2 = _run(
                [
                    "check", "--project", self.project,
                    "--fail-on", "warning", "--output", "json",
                ]
            )
        self.assertEqual(json.loads(out_error)["status"], "warning")
        self.assertEqual(code_error, 0, "fail-on error 时仅 warning 应退出 0")
        self.assertEqual(json.loads(out_warn)["status"], "failed")
        self.assertEqual(code_warn, 1, "fail-on warning 且有 warning 应退出 1")

    def test_unrelated_warning_threshold_placeholder(self):
        chapter = next(Path(self.project).rglob("content/**/*.md"))
        chapter.write_text(
            chapter.read_text(encoding="utf-8") + "\nTODO：待补充\n",
            encoding="utf-8",
        )
        code_default, out_default, _err = _run(
            ["check", "--project", self.project, "--output", "json"]
        )
        data_default = json.loads(out_default)
        if data_default["issues"] and data_default["exitCode"] == 0:
            self.assertEqual(code_default, 0, "fail-on error 时仅 warning 应退出 0")
        code_strict, out_strict, _err2 = _run(
            ["check", "--project", self.project, "--fail-on", "warning", "--output", "json"]
        )
        if json.loads(out_strict)["issues"]:
            self.assertEqual(code_strict, 1, "fail-on warning 且有 warning 时应退出 1")

    def test_missing_project_exits_two_with_stderr_reason(self):
        code, out, err = _run(
            ["check", "--project", str(self.tmp / "不存在"), "--output", "json"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "", "stdout 不得混入错误说明")
        self.assertTrue(err.strip())

    def test_sarif_export_is_parseable_with_rule_ids(self):
        chapter = next(Path(self.project).rglob("content/**/*.md"))
        chapter.write_text(
            chapter.read_text(encoding="utf-8") + "\nTODO：待补充\n",
            encoding="utf-8",
        )
        code, out, _err = _run(
            ["check", "--project", self.project, "--output", "sarif"]
        )
        data = json.loads(out)
        self.assertEqual(data["version"], "2.1.0")
        results = data["runs"][0]["results"]
        self.assertTrue(results, "有发现时 SARIF 应包含 result")
        rule_id = results[0]["ruleId"]
        self.assertTrue(rule_id)

    def test_text_output_lists_status_and_stages(self):
        code, out, err = _run(["check", "--project", self.project])
        self.assertIn("结论：", out)
        self.assertIn("阶段：", out)
        self.assertIn("lint", out)
        self.assertIn("exitCode={0}".format(code), out)
        self.assertIn(code, (0, 1))
        # 输出必须是单文档：不得把进度日志混进 stdout。
        self.assertNotIn("[requirement]", out)
        self.assertTrue(out.strip())
        if code == 0:
            self.assertTrue(("通过" in out) or ("带提醒" in out))
        else:
            self.assertIn("未通过", out)
        del err

    def test_build_flag_runs_pipeline_and_audit(self):
        code, out, err = _run(
            ["check", "--project", self.project, "--build", "--output", "json"]
        )
        data = json.loads(out)
        stages = {stage["stage"]: stage["status"] for stage in data["stages"]}
        self.assertIn("build", stages)
        self.assertNotEqual(stages["build"], "skipped")
        # 构建未成功时不强求审查阶段，但必须如实列出产物状态。
        if stages["build"] == "succeeded":
            self.assertIn("audit", stages)
            self.assertTrue(data["artifacts"], "构建后应列出产物路径")
        else:
            self.assertTrue(err.strip(), "构建失败必须在 stderr 给出原因")
        self.assertEqual(data["exitCode"], code)

    def test_invalid_options_are_rejected_by_parser(self):
        with self.assertRaises(SystemExit):
            _run(["check", "--project", self.project, "--fail-on", "boom"])


if __name__ == "__main__":
    unittest.main()