# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET

from doc_tool.application.cli_commands import CommandResult, ProjectCommandResult
from doc_tool.application.issues import IssueRecord
from doc_tool.cli import main
from doc_tool.cli_serializers import serialize_junit, serialize_sarif


def _issue(severity="error"):
    return IssueRecord(
        source="lint", issue_type="todo_residual", document_type="requirement",
        severity=severity, rel_path="chapter.md", line_no=3, error_code="E2002",
        message="待办残留", suggested_action="修正", generated_at="2026-08-12T00:00:00+00:00",
    )


class MachineCliTests(unittest.TestCase):
    def test_json_schema_and_stdout_is_single_document(self):
        result = CommandResult("status", [ProjectCommandResult("p", True, data={"ok": True})])
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("doc_tool.application.cli_commands.status_command", return_value=result), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["status", "--project", ".", "--output", "json"])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(set(data), {"schemaVersion", "command", "success", "errorCode", "results"})
        self.assertEqual(data["command"], "status")

    def test_sarif_and_junit_are_parseable(self):
        result = CommandResult("validate", [
            ProjectCommandResult(".", False, "E2002", issues=[_issue()]),
        ])
        sarif = json.loads(serialize_sarif(result))
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"], 3)
        junit = ET.fromstring(serialize_junit(result))
        self.assertEqual(junit.attrib["failures"], "1")
        self.assertIsNotNone(junit.find("./testsuite/testcase/failure"))

    def test_batch_partial_success_exit_code(self):
        result = CommandResult("status", [
            ProjectCommandResult("a", True), ProjectCommandResult("b", False, "E4003"),
        ])
        self.assertEqual(result.exit_code, 3)

    def test_invalid_arguments_exit_two_and_usage_on_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            main(["validate"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("usage:", err.getvalue().lower())

    def test_real_status_search_and_lint_commands(self):
        from doc_tool.domain.manifest import ProjectManifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content" / "requirement"
            content.mkdir(parents=True)
            (content / "1.1 intro.md").write_text("# 标题\nTODO GXPC\n", encoding="utf-8")
            manifest = ProjectManifest(
                documentType="requirement", documentNo="REQ-1", documentName="测试",
                documentVersion="1.0", sourceSha256="x",
                paths={"contentRoot": "content/requirement"},
            )
            manifest.save(root, backup=False)
            for argv in (
                ["status", "--project", str(root), "--output", "json"],
                ["search", "--project", str(root), "--query", "TODO", "--output", "json"],
                ["lint", "--project", str(root), "--format", "sarif"],
            ):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    code = main(argv)
                self.assertIn(code, (0, 1))
                json.loads(out.getvalue())

    def test_renumber_dry_run_then_apply(self):
        from doc_tool.domain.manifest import ProjectManifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content" / "requirement"
            prefix = "第3章/3.7 GXOA"
            for number, title in ((1, "甲"), (2, "乙"), (5, "丙"), (6, "丁")):
                path = content / prefix / "3.7.{0} {1}.md".format(number, title)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "# 3.7.{0} {1}\n".format(number, title), encoding="utf-8"
                )
            manifest = ProjectManifest(
                documentType="requirement", documentNo="REQ-1", documentName="测试",
                documentVersion="1.0", sourceSha256="x",
                paths={"contentRoot": "content/requirement"},
            )
            manifest.save(root, backup=False)
            # dry-run：预览且不写盘
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main(["renumber", "--project", str(root), "--output", "json"])
            self.assertEqual(code, 0)
            data = json.loads(out.getvalue())
            item = data["results"][0]
            self.assertFalse(item["data"]["applied"])
            self.assertEqual(item["data"]["renamed"], 2)
            self.assertTrue(
                (content / prefix / "3.7.5 丙.md").exists(), "dry-run 不应写盘"
            )
            # human 模式必须能看到 old → new 清单
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main(["renumber", "--project", str(root)])
            self.assertEqual(code, 0)
            self.assertIn(
                "第3章/3.7 GXOA/3.7.5 丙.md → 第3章/3.7 GXOA/3.7.3 丙.md",
                out.getvalue(),
            )
            # apply：写盘并联动更新
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    ["renumber", "--project", str(root), "--apply", "--output", "json"]
                )
            self.assertEqual(code, 0)
            data = json.loads(out.getvalue())
            self.assertTrue(data["results"][0]["data"]["applied"])
            self.assertTrue((content / prefix / "3.7.3 丙.md").exists())
            self.assertTrue((content / prefix / "3.7.4 丁.md").exists())
            self.assertFalse((content / prefix / "3.7.5 丙.md").exists())
            self.assertFalse((content / prefix / "3.7.6 丁.md").exists())
            # 再次运行：已连续 → 0 项
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main(["renumber", "--project", str(root), "--output", "json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["results"][0]["data"]["renamed"], 0)

    def test_renumber_dir_no_match_fails(self):
        from doc_tool.domain.manifest import ProjectManifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content" / "requirement"
            content.mkdir(parents=True)
            (content / "1.1 a.md").write_text("# 1.1 a\n", encoding="utf-8")
            manifest = ProjectManifest(
                documentType="requirement", documentNo="REQ-1", documentName="测试",
                documentVersion="1.0", sourceSha256="x",
                paths={"contentRoot": "content/requirement"},
            )
            manifest.save(root, backup=False)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    ["renumber", "--project", str(root), "--dir", "不存在的目录", "--output", "json"]
                )
            self.assertEqual(code, 1)
            data = json.loads(out.getvalue())
            self.assertFalse(data["results"][0]["success"])
            self.assertEqual(data["results"][0]["errorCode"], "E2003")

    def test_import_name_with_separator_rejected(self):
        # 项目名含路径分隔符/.. 时在进入导入流程前拒绝，防止逃逸 target_dir。
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(["import", "--docx", "x.docx", "--name", "a/b", "--output", "json"])
        self.assertEqual(code, 1)
        data = json.loads(out.getvalue())
        self.assertEqual(data["results"][0]["errorCode"], "E5001")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(["import", "--docx", "x.docx", "--name", "..", "--output", "json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["results"][0]["errorCode"], "E5001")

    def _run_build(self, extra_args):
        """跑一次 `build --project`，返回传给 run_pipeline 的关键字参数。"""
        from unittest.mock import Mock, patch

        import doc_tool.cli as cli

        pipeline_result = types.SimpleNamespace(events=[], success=True)
        run_pipeline = Mock(return_value=pipeline_result)
        manifest = Mock()
        manifest.resolve_paths.return_value = object()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("doc_tool.adapters.kernel.ensure_kernel_importable"), \
                 patch("doc_tool.application.pipeline.run_pipeline", run_pipeline), \
                 patch("doc_tool.domain.manifest.ProjectManifest.load", return_value=manifest):
                code = cli.main(["build", "--project", tmp] + list(extra_args))
        self.assertEqual(code, 0)
        run_pipeline.assert_called_once()
        return run_pipeline.call_args.kwargs

    def test_build_passes_no_revision_arguments(self):
        """修订记录只由 _revision_record.md 维护：build 不再有 --revision-* 参数。"""
        kwargs = self._run_build([])
        self.assertEqual(sorted(kwargs), ["skip_word_refresh"])
        self.assertFalse(kwargs["skip_word_refresh"])

    def test_build_rejects_removed_revision_flags(self):
        """旧脚本传 --revision-summary 时以用法错误退出，不静默忽略。"""
        from doc_tool.cli import build_parser

        parser = build_parser()
        for flag in (
            "--revision-version",
            "--revision-summary",
            "--revision-summary-file",
            "--revision-author",
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args(["build", "--project", ".", flag, "x"])
            self.assertEqual(raised.exception.code, 2)

    def test_import_parser_rejects_legacy_document_type(self):
        """任务 4.4/4.7：公共 CLI import 只接受 general，旧类型参数被拒绝。"""
        from doc_tool.cli import build_parser

        parser = build_parser()
        # 显式旧类型参数 → argparse 拒绝（invalid choice），不进入导入流程。
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(
                ["import", "--docx", "x.docx", "--name", "n", "--document-type", "requirement"]
            )
        self.assertEqual(raised.exception.code, 2)
        # 省略或显式 general 均可解析，且默认版本/编号为空（可选元数据）。
        args = parser.parse_args(["import", "--docx", "x.docx", "--name", "n"])
        self.assertEqual(args.document_type, "general")
        self.assertEqual(args.document_version, "")
        args2 = parser.parse_args(
            ["import", "--docx", "x.docx", "--name", "n", "--document-type", "general"]
        )
        self.assertEqual(args2.document_type, "general")

    def test_cli_help_does_not_list_legacy_document_types(self):
        """任务 4.4：import 帮助不再把 requirement/design 列为可创建类型。"""
        from doc_tool.cli import build_parser

        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            build_parser().parse_args(["import", "--help"])
        import_help = out.getvalue()
        self.assertIn("--document-type", import_help)
        self.assertNotIn("requirement", import_help)
        self.assertNotIn("design", import_help)


if __name__ == "__main__":
    unittest.main()
