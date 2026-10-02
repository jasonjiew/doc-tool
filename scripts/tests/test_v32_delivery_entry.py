# -*- coding: utf-8 -*-
"""V3.2 批次交付入口测试（32-A 契约 / 32-E 界面服务层 / 32-F 批次 CLI）。

覆盖：

- 32-A：批次计划 schema 1 解析（项目/工作区/变体/格式/默认值）、非法成员只影响
  该项、旧入口标志 → 新模型默认值（默认策略逐字段固定）。
- 32-E：纯服务层界面模型（逐成员/变体/格式/状态/路径 + 动作模型 + 打开路径解析），
  不导入 PySide6。
- 32-F：``delivery-plan/run/status/retry/package/promote`` 的真实 CLI 行为与退出码
  契约（0=有可用结果、1=无可用结果或严格未满足、2=参数/输入非法），覆盖部分成功、
  取消保留、中断继续、只重试未完成项、换目录补刷新、JSON 单一文档。

真实出稿命令在本文件里用真实两章项目夹具执行（``--no-refresh`` 明确跳过 Word
刷新，逐项按待刷新记录），不驱动真实 Word。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import uuid
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery import gui_hooks  # noqa: E402
from doc_tool.application.delivery.contract import (  # noqa: E402
    DEFAULT_POLICY,
    ENTRY_INVALID,
    ENTRY_READY,
    ENTRY_WARNING,
    legacy_flag_notes,
    load_plan_file,
    parse_plan,
    plan_report,
    policy_from_legacy_flags,
)
from doc_tool.application.delivery.queue import (  # noqa: E402
    COMPLETED_JOB_STATUSES,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_WAITING_REFRESH,
    DeliveryQueue,
)
from doc_tool.application.delivery.result_index import build_result_index  # noqa: E402
from doc_tool.application.delivery.snapshot_package import (  # noqa: E402
    build_delivery_package,
    formalize_package,
    read_delivery_package,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    ExportRequest,
    FORMAT_HTML,
    STATUS_FAILED,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
    USABLE_STATUSES,
    FormatResult,
    sha256_file,
)
from doc_tool.application.project_export import ExportReport, run_project_export  # noqa: E402

CLI = str(REPO_ROOT / "doc_tool_cli.py")
EXAMPLE_PLAN = REPO_ROOT / "examples" / "delivery" / "batch.json"
EXAMPLE_README = REPO_ROOT / "examples" / "delivery" / "README.md"

#: 本文件创建的全部夹具目录（模块结束时统一清理）。
_SCRATCH: list = []
_SHARED: dict = {"project": None}


def _scratch(prefix: str) -> Path:
    path = fixtures.scratch_dir(prefix)
    _SCRATCH.append(path)
    return path


def tearDownModule() -> None:
    for path in _SCRATCH:
        fixtures.cleanup(path)


def _shared_project() -> Path:
    """真实导入产出的两章项目：整个模块只建一次，测试内复制使用。"""
    project = _SHARED.get("project")
    if project is None or not Path(project).is_dir():
        root = _scratch("v32-entry-shared")
        project = fixtures.two_chapter_project(root / "proj")
        _SHARED["project"] = project
    return Path(project)


def _copy_project(name: str) -> Path:
    target = _scratch("v32-entry-proj") / name
    shutil.copytree(str(_shared_project()), str(target))
    return target


def _run_cli(*args, cwd=None):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", ""))))
    return subprocess.run(
        [sys.executable, CLI, *args], cwd=str(cwd or REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", check=False,
    )


def _json(result):
    """stdout 必须是单一 JSON 文档（过程日志在 stderr）。"""
    return json.loads(result.stdout)


def _broken_project(root: Path) -> Path:
    """可被计划接受、但出稿时必定失败的成员（清单校验失败 → 该项 failed）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yml").write_text(
        'schemaVersion: 1\ndocumentType: general\ndocumentName: ""\n', encoding="utf-8",
    )
    return root


def _reassign_project_id(project: Path, new_id: str) -> None:
    """复制出来的成员项目共用同一 projectId，会让工作区按身份去重：改成唯一值。"""
    manifest = project / "project.yml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        re.sub(r"(?m)^projectId:.*$", "projectId: {0}".format(new_id), text, count=1),
        encoding="utf-8",
    )


def _write_plan(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class _FakeRunner:
    """替身执行服务：按成员给状态，保留真实出稿的部分成功语义。"""

    def __init__(self, plan=None):
        self.plan = {key: dict(value) for key, value in (plan or {}).items()}
        self.calls: list = []

    def __call__(self, request, **kwargs):
        self.calls.append((str(request.project_root), dict(kwargs)))
        destination = Path(request.destination)
        destination.mkdir(parents=True, exist_ok=True)
        member = Path(request.project_root).name
        skip = bool(kwargs.get("skip_word_refresh"))
        planned = self.plan.get(member) or {}
        results = []
        for fmt in request.formats:
            status = planned.get(fmt)
            if status is None:
                status = STATUS_PENDING_REFRESH if (fmt == FORMAT_DOCX and skip) else STATUS_READY
            if status == STATUS_FAILED:
                results.append(FormatResult(format=fmt, status=STATUS_FAILED, message="模拟失败"))
                continue
            target = destination / "{0}-{1}.out".format(member, fmt)
            target.write_text("产物 {0} {1}".format(member, fmt), encoding="utf-8")
            results.append(FormatResult(
                format=fmt, status=status, path=str(target), sha256=sha256_file(target),
            ))
        return ExportReport(
            captureId="cap-{0}".format(member),
            scope=request.scope,
            sourceMode=request.source_mode,
            destination=str(destination),
            outputName=member,
            projectRoot=str(request.project_root),
            documentType="general",
            documentVersion="1.0",
            results=results,
            snapshotWorkDir=str(destination),
        )


# --- 32-A：契约与默认策略 ---


class ContractTests(unittest.TestCase):
    """批次契约：默认策略/旧标志适配/计划解析（成员级问题只影响该项）。"""

    @classmethod
    def setUpClass(cls):
        cls.work = _scratch("v32-entry-contract")
        members = cls.work / "members"
        members.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(_shared_project()), str(members / "Alpha"))
        shutil.copytree(str(_shared_project()), str(members / "Beta"))
        cls.alpha = members / "Alpha"
        (members / "NoProject").mkdir(parents=True, exist_ok=True)
        # 工作区：两个合法成员（用既有工作区 API 保证 workspace.yml 合法）。
        from doc_tool.application.workspace import add_project, create_workspace

        cls.ws_root = cls.work / "ws"
        (cls.ws_root / "A").parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(cls.alpha), str(cls.ws_root / "A"))
        shutil.copytree(str(cls.alpha), str(cls.ws_root / "B"))
        _reassign_project_id(cls.ws_root / "B", "p-batch-{0}".format(uuid.uuid4().hex[:8]))
        workspace = create_workspace(cls.ws_root, name="批次演示工作区")
        add_project(workspace, cls.ws_root / "A", role="other")
        add_project(workspace, cls.ws_root / "B", role="other")
        workspace.save()

    def test_default_policy_and_legacy_flag_adapter_are_pinned(self):
        self.assertEqual(
            DEFAULT_POLICY.to_dict(),
            {
                "execution": "serial",
                "wordBusy": "waiting-refresh",
                "onPartial": "keep-useful",
                "strict": False,
                "refresh": True,
                "autoRetryLimit": 0,
                "idempotencyScope": "local-common-registry",
                "sourceMode": "saved",
            },
        )
        self.assertEqual(policy_from_legacy_flags().to_dict(), DEFAULT_POLICY.to_dict())
        strict = policy_from_legacy_flags(strict=True, no_refresh=True)
        self.assertTrue(strict.strict)
        self.assertFalse(strict.refresh)
        self.assertEqual(strict.execution, "serial")
        self.assertEqual(
            legacy_flag_notes(source_mode="current-buffer", strict=True, no_refresh=True),
            [
                "命令行没有界面缓冲：sourceMode=current-buffer 不可用，已按 saved 处理。",
                "--no-refresh：逐项不做 Word 刷新，按待刷新记录，可在有 Word 的环境补。",
                "--strict：严格阈值场景单独返回 1，可读参考产物仍保留。",
            ],
        )

    def test_plan_parses_members_defaults_and_isolates_invalid_items(self):
        plan = parse_plan(
            {
                "schemaVersion": 1,
                "batchId": "batch-contract",
                "defaults": {"formats": ["docx", "html"], "destination": "out"},
                "entries": [
                    {"id": "alpha", "member": "members/Alpha"},
                    {"id": "ws", "kind": "workspace", "member": "ws"},
                    {"id": "missing", "member": "members/Ghost"},
                    {"id": "noproject", "member": "members/NoProject"},
                    {"id": "nofmt", "member": "members/Alpha", "formats": ["unknown-format"]},
                    {"id": "needchapter", "member": "members/Alpha",
                     "scope": {"kind": "current-chapter"}},
                ],
            },
            plan_path=str(self.work / "batch.json"),
        )
        self.assertEqual(plan.problems, [])
        self.assertTrue(plan.ok)
        by_id = {entry.entryId: entry for entry in plan.all_entries()}
        self.assertEqual(by_id["alpha"].status, ENTRY_READY)
        self.assertEqual(by_id["alpha"].formats, [FORMAT_DOCX, FORMAT_HTML])
        self.assertTrue(by_id["alpha"].destination.endswith("out"), by_id["alpha"].destination)
        # 工作区展开为两个成员项（保留来源 entryId/workspaceId/角色）
        ws_rows = [entry for entry in plan.all_entries() if entry.originEntryId == "ws"]
        self.assertEqual(len(ws_rows), 2)
        self.assertTrue(all(row.workspaceId for row in ws_rows))
        self.assertTrue(all(row.projectId for row in ws_rows))
        self.assertEqual([row.status for row in ws_rows], [ENTRY_READY, ENTRY_READY])
        # 非法成员只影响该项，其余照常可执行
        self.assertEqual(by_id["missing"].status, ENTRY_INVALID)
        self.assertIn("成员目录不存在", by_id["missing"].problems[0])
        self.assertEqual(by_id["noproject"].status, ENTRY_INVALID)
        self.assertIn("project.yml", by_id["noproject"].problems[0])
        self.assertEqual(by_id["nofmt"].status, ENTRY_INVALID)
        self.assertIn("未知目标格式", by_id["nofmt"].problems[0])
        self.assertEqual(by_id["needchapter"].status, ENTRY_INVALID)
        self.assertIn("current", by_id["needchapter"].problems[0])
        self.assertEqual(len(plan.executable_entries()), 3)
        self.assertEqual(len(plan.invalid_entries()), 4)
        report = plan_report(plan)
        self.assertEqual(report["command"], "delivery-plan")
        self.assertEqual(report["executableCount"], 3)
        # 汇总格式含非法成员声明的格式（集中提示），但该成员本身不可执行
        self.assertEqual(report["formats"], [FORMAT_DOCX, FORMAT_HTML, "unknown-format"])

    def test_plan_overrides_force_strict_and_destination(self):
        plan = parse_plan(
            {"schemaVersion": 1, "entries": [{"id": "a", "member": "members/Alpha"}]},
            plan_path=str(self.work / "batch.json"),
        )
        target = self.work / "override-out"
        plan.apply_overrides(strict=True, destination=str(target), formats=["pdf"])
        entry = plan.entries[0]
        self.assertTrue(entry.strict)
        self.assertEqual(entry.destination, str(target))
        self.assertEqual(entry.formats, ["pdf"])

    def test_unknown_variant_is_item_warning_not_blocking(self):
        project = self.work / "members" / "VariantProject"
        shutil.copytree(str(self.alpha), str(project))
        (project / "variants.yml").write_text(
            json.dumps(
                {"schemaVersion": 1, "variants": [{"variantId": "v1", "name": "变体一"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        plan = parse_plan(
            {
                "schemaVersion": 1,
                "entries": [
                    {"id": "known", "member": "members/VariantProject", "variantId": "v1"},
                    {"id": "unknown", "member": "members/VariantProject", "variantId": "v9"},
                ],
            },
            plan_path=str(self.work / "batch.json"),
        )
        by_id = {entry.entryId: entry for entry in plan.all_entries()}
        self.assertEqual(by_id["known"].status, ENTRY_READY)
        self.assertEqual(by_id["unknown"].status, ENTRY_WARNING)
        self.assertIn("未知变体", by_id["unknown"].problems[0])
        self.assertEqual(len(plan.executable_entries()), 2)

    def test_plan_file_level_problems_are_reported(self):
        missing = load_plan_file(self.work / "nope.json")
        self.assertFalse(missing.ok)
        self.assertIn("不存在", missing.problems[0])
        bad_schema = _write_plan(
            self.work / "schema2.json",
            {"schemaVersion": 2, "entries": [{"member": "members/Alpha"}]},
        )
        plan = load_plan_file(bad_schema)
        self.assertFalse(plan.ok)
        self.assertIn("schema", plan.problems[0])
        no_entries = _write_plan(self.work / "empty.json", {"schemaVersion": 1, "entries": []})
        self.assertFalse(load_plan_file(no_entries).ok)

    def test_plan_parses_yaml_plan(self):
        plan_file = self.work / "batch.yml"
        plan_file.write_text(
            "schemaVersion: 1\n"
            "batchId: batch-yaml\n"
            "defaults:\n"
            "  formats: [docx]\n"
            "entries:\n"
            "  - id: alpha\n"
            "    member: members/Alpha\n",
            encoding="utf-8",
        )
        plan = load_plan_file(plan_file)
        self.assertTrue(plan.ok, plan.problems)
        self.assertEqual(plan.batchId, "batch-yaml")
        self.assertEqual(plan.executable_entries()[0].member, "members/Alpha")


# --- 32-E：界面服务层模型（纯服务层，不导入 PySide6）---


class GuiHookTests(unittest.TestCase):
    """把队列/索引转成界面状态与动作模型，并解析打开路径。"""

    def setUp(self):
        self.work = _scratch("v32-entry-gui")
        self.store = self.work / "queue.json"
        self.runner = _FakeRunner({
            "Broken": {FORMAT_DOCX: STATUS_FAILED, FORMAT_HTML: STATUS_FAILED},
        })
        self.queue = DeliveryQueue(
            str(self.store), runner=self.runner, word_probe=lambda: (True, ""),
        )

    def _enqueue(self, name: str, formats=(FORMAT_DOCX, FORMAT_HTML)):
        return self.queue.enqueue(
            project_root=str(self.work / name),
            formats=list(formats),
            destination=str(self.work / "out" / name),
        ).job

    def test_batch_view_exposes_rows_cells_actions_and_open_targets(self):
        good = self._enqueue("Alpha")
        bad = self._enqueue("Broken")
        self.queue.run_pending(skip_word_refresh=True)
        view = gui_hooks.batch_view(self.queue)
        self.assertEqual(view.overallStatus, gui_hooks.VIEW_PARTIAL)
        self.assertEqual(len(view.rows), 2)
        row = view.row(good.jobId)
        self.assertIsNotNone(row)
        self.assertEqual(row.status, JOB_WAITING_REFRESH)
        self.assertEqual(row.statusLabel, "待刷新")
        self.assertEqual(row.memberName, "Alpha")
        self.assertEqual(row.usableCount, 2)
        self.assertEqual([cell.format for cell in row.cells], [FORMAT_DOCX, FORMAT_HTML])
        self.assertTrue(all(cell.openTarget.available for cell in row.cells))
        self.assertTrue(all(cell.openTarget.kind == gui_hooks.OPEN_KIND_FILE for cell in row.cells))

        def action(row_obj, action_id):
            return next(item for item in row_obj.actions if item.actionId == action_id)

        self.assertTrue(action(row, gui_hooks.ACTION_OPEN_RESULT).enabled)
        self.assertTrue(action(row, gui_hooks.ACTION_REFRESH).enabled)
        retry = view.action(gui_hooks.ACTION_RETRY)
        self.assertIsNotNone(retry)
        self.assertTrue(retry.enabled)
        self.assertEqual(set(retry.detail["jobIds"]), {good.jobId, bad.jobId})
        self.assertTrue(view.action(gui_hooks.ACTION_REFRESH).enabled)
        # 批次级动作里没有「打开」类；打开动作按行给出
        self.assertIsNone(view.action(gui_hooks.ACTION_OPEN_RESULT))
        bad_row = view.row(bad.jobId)
        self.assertEqual(bad_row.status, JOB_FAILED)
        self.assertEqual(bad_row.usableCount, 0)
        self.assertTrue(bad_row.error)
        self.assertFalse(action(bad_row, gui_hooks.ACTION_OPEN_RESULT).enabled)
        self.assertTrue(action(bad_row, gui_hooks.ACTION_OPEN_RESULT).reason)
        payload = view.to_dict()
        self.assertEqual(payload["counts"]["total"], 2)
        self.assertEqual(payload["rows"][0]["actions"][0]["kind"], "open")
        self.assertEqual({row["jobId"] for row in payload["rows"]}, {good.jobId, bad.jobId})
        self.assertTrue(view.summary_lines())

    def test_run_action_retries_unfinished_items_only(self):
        good = self._enqueue("Alpha")
        bad = self._enqueue("Broken")
        self.queue.run_pending(skip_word_refresh=True)
        view = gui_hooks.batch_view(self.queue)
        calls_before = len(self.runner.calls)
        outcomes = gui_hooks.run_action(self.queue, view.action(gui_hooks.ACTION_RETRY))
        self.assertEqual([job.jobId for job in outcomes], [good.jobId, bad.jobId])
        self.assertEqual(len(self.runner.calls), calls_before + 2)
        self.assertEqual(self.queue.job(good.jobId).attemptCount, 2)
        self.assertEqual(self.queue.job(bad.jobId).attemptCount, 2)
        # 打开类动作不在服务层执行（由界面按 OpenTarget 打开）
        self.assertEqual(gui_hooks.run_action(self.queue, gui_hooks.ACTION_OPEN_RESULT), [])
        # 取消动作只改未完成项，已完成结果保留
        completed = self._enqueue("Done", formats=(FORMAT_HTML,))
        self.queue.run_pending(skip_word_refresh=True, only_job_ids=[completed.jobId])
        self.assertEqual(self.queue.job(completed.jobId).status, JOB_COMPLETED)
        gui_hooks.run_action(self.queue, gui_hooks.ACTION_CANCEL)
        self.assertEqual(self.queue.job(completed.jobId).status, JOB_COMPLETED)
        self.assertEqual(self.queue.job(bad.jobId).status, JOB_CANCELLED)

    def test_open_target_resolves_file_package_member_directory_and_missing(self):
        self.work.mkdir(parents=True, exist_ok=True)
        local = self.work / "结果.docx"
        local.write_text("x", encoding="utf-8")
        file_target = gui_hooks.resolve_open_target(str(local))
        self.assertEqual(file_target.kind, gui_hooks.OPEN_KIND_FILE)
        self.assertTrue(file_target.available)
        self.assertEqual(gui_hooks.resolve_open_target("").kind, gui_hooks.OPEN_KIND_NONE)
        missing = gui_hooks.resolve_open_target(str(self.work / "nope.docx"))
        self.assertEqual(missing.kind, gui_hooks.OPEN_KIND_MISSING)
        self.assertFalse(missing.available)
        self.assertTrue(missing.reason)
        self.assertEqual(
            gui_hooks.resolve_open_target(str(self.work)).kind,
            gui_hooks.OPEN_KIND_DIRECTORY,
        )
        package = self.work / "pkg.zip"
        with zipfile.ZipFile(str(package), "w") as archive:
            archive.writestr("docx/Alpha.docx", "x")
        inside = gui_hooks.resolve_open_target("{0}::docx/Alpha.docx".format(package))
        self.assertEqual(inside.kind, gui_hooks.OPEN_KIND_PACKAGE_MEMBER)
        self.assertTrue(inside.available)
        self.assertEqual(inside.member, "docx/Alpha.docx")
        self.assertEqual(inside.path, str(package))
        gone = gui_hooks.resolve_open_target("{0}::docx/Alpha.docx".format(self.work / "no.zip"))
        self.assertEqual(gone.kind, gui_hooks.OPEN_KIND_MISSING)
        self.assertFalse(gone.available)

    def test_result_view_maps_queue_store_index(self):
        self._enqueue("Alpha")
        self._enqueue("Broken")
        self.queue.run_pending(skip_word_refresh=True)
        index = build_result_index([str(self.store)])
        view = gui_hooks.result_view(index)
        self.assertEqual(view.overallStatus, gui_hooks.VIEW_PARTIAL)
        self.assertEqual(len(view.rows), 4)
        self.assertTrue(view.by_member())
        usable = [row for row in view.rows if row.usable]
        self.assertEqual(len(usable), 2)
        self.assertTrue(all(row.openTarget.available for row in usable))
        self.assertIn("overallStatus", view.to_dict())
        self.assertTrue(view.summary_lines())

    def test_plan_view_marks_invalid_rows(self):
        project = self.work / "proj"
        project.mkdir(parents=True, exist_ok=True)
        (project / "project.yml").write_text("schemaVersion: 1\n", encoding="utf-8")
        plan = parse_plan(
            {
                "schemaVersion": 1,
                "batchId": "b",
                "entries": [
                    {"id": "alpha", "member": "proj"},
                    {"id": "ghost", "member": "Ghost"},
                ],
            },
            plan_path=str(self.work / "batch.json"),
            base_dir=str(self.work),
        )
        view = gui_hooks.plan_view(plan)
        self.assertEqual(len(view.rows), 2)
        self.assertEqual(len(view.executable_rows()), 1)
        self.assertEqual(len(view.invalid_rows()), 1)
        self.assertEqual(view.overallStatus, gui_hooks.VIEW_PARTIAL)
        self.assertTrue(view.action(gui_hooks.ACTION_RUN_PENDING).enabled)

    def test_gui_hooks_is_pure_service_layer(self):
        source = Path(gui_hooks.__file__).read_text(encoding="utf-8")
        self.assertNotIn("PySide6", source)
        self.assertNotIn("doc_tool.ui", source)
        self.assertNotIn("QWidget", source)
        self.assertTrue(hasattr(gui_hooks, "batch_view"))
        self.assertTrue(hasattr(gui_hooks, "resolve_open_target"))


# --- 32-F：批次 CLI 与示例 ---


class DeliveryCliTests(unittest.TestCase):
    """真实两章项目 + 真实出稿服务：CLI 全链路与退出码契约。"""

    @classmethod
    def setUpClass(cls):
        cls.work = _scratch("v32-entry-cli")
        members = cls.work / "members"
        members.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(_shared_project()), str(members / "Alpha"))
        shutil.copytree(str(_shared_project()), str(members / "Beta"))
        _broken_project(members / "Broken")
        cls.plan = _write_plan(
            cls.work / "batch.json",
            {
                "schemaVersion": 1,
                "batchId": "batch-cli-entry",
                "policy": {"execution": "serial", "autoRetryLimit": 0},
                "defaults": {"formats": ["docx", "html"], "destination": "out"},
                "entries": [
                    {"id": "alpha", "member": "members/Alpha", "variantId": "standard"},
                    {"id": "beta", "member": "members/Beta", "formats": ["docx"]},
                    {"id": "broken", "member": "members/Broken"},
                ],
            },
        )
        cls.store = cls.work / "run-store.json"
        cls.plan_result = _run_cli("delivery-plan", "--plan", str(cls.plan), "--json")
        cls.run_result = _run_cli(
            "delivery-run", "--plan", str(cls.plan), "--store", str(cls.store),
            "--no-refresh", "--json",
        )
        cls.run_payload = _json(cls.run_result) if cls.run_result.stdout.strip() else {}

    # --- 参数/输出契约 ---

    def test_help_exposes_delivery_contract_options(self):
        for command, tokens in (
            ("delivery-plan", ("--plan", "--base-dir", "--destination", "--formats",
                               "--strict", "--no-refresh", "--json")),
            ("delivery-run", ("--store", "--continue", "--retry-failed", "--cancel-after",
                              "--strict", "--json")),
            ("delivery-status", ("--store", "--index", "--plan", "--json")),
            ("delivery-retry", ("--store", "--job-id", "--no-refresh", "--json")),
            ("delivery-package", ("--from", "--store", "--target", "--include-original")),
            ("delivery-promote", ("--destination", "--word-available", "--registry")),
        ):
            result = _run_cli(command, "--help")
            self.assertEqual(result.returncode, 0, command)
            for token in tokens:
                self.assertIn(token, result.stdout, "{0} 缺少 {1}".format(command, token))

    def test_example_plan_and_readme_are_runnable_against_base_dir(self):
        self.assertTrue(EXAMPLE_PLAN.is_file())
        self.assertTrue(EXAMPLE_README.is_file())
        self.assertIn("members/Alpha", EXAMPLE_PLAN.read_text(encoding="utf-8"))
        # 示例成员是占位相对路径：用 --base-dir 指向真实成员目录即可预览（不执行）
        result = _run_cli(
            "delivery-plan", "--plan", str(EXAMPLE_PLAN), "--base-dir", str(self.work), "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        payload = _json(result)
        self.assertEqual(payload["plan"]["executableCount"], 2)
        for entry in payload["plan"]["entries"]:
            self.assertTrue(entry["destination"].startswith(str(self.work)), entry["destination"])
        readme = EXAMPLE_README.read_text(encoding="utf-8")
        for token in ("delivery-run", "delivery-package", "delivery-promote", "--base-dir"):
            self.assertIn(token, readme)
        self.assertIn("没有", readme)  # 明确声明不含上传/通知/发布步骤

    def test_plan_preview_does_not_write_queue_or_execute(self):
        work = _scratch("v32-entry-cli-plan")
        result = _run_cli(
            "delivery-plan", "--plan", str(self.plan), "--base-dir", str(self.work),
            "--output", "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        payload = _json(result)
        self.assertEqual(payload["command"], "delivery-plan")
        self.assertEqual(payload["exitCode"], 0)
        self.assertNotIn("jobs", payload)
        self.assertTrue(payload["plan"]["entryCount"] >= 1)
        self.assertFalse((self.work / "delivery-queue.json").exists())
        self.assertEqual(list(work.iterdir()), [])

    # --- 部分成功 / 状态 / 严格阈值 ---

    def test_run_partial_success_defaults_to_zero_with_per_item_exit_codes(self):
        self.assertEqual(self.run_result.returncode, 0, self.run_result.stderr[-600:])
        payload = self.run_payload
        self.assertEqual(payload["exitCode"], 0)
        self.assertEqual(payload["overallStatus"], "partial")
        self.assertEqual(payload["mode"], "run")
        jobs = {job["jobId"]: job for job in payload["jobs"]}
        self.assertEqual(len(jobs), 3)
        self.assertEqual(sorted(job["exitCode"] for job in jobs.values()), [0, 0, 1])
        failed = [job for job in jobs.values() if job["exitCode"] == 1]
        self.assertEqual(failed[0]["status"], JOB_FAILED)
        self.assertTrue(failed[0]["error"])
        for job in jobs.values():
            if job["exitCode"] != 0:
                continue
            self.assertIn(job["status"], (JOB_WAITING_REFRESH, "completed-with-warnings"))
            self.assertTrue(job["usableFormats"])
            for cell in job["results"]:
                if cell["status"] in USABLE_STATUSES and cell["path"]:
                    self.assertTrue(Path(cell["path"]).is_file(), cell["path"])
        # 共用目标目录已按成员分目录（避免 export-result.json 互相覆盖）
        self.assertTrue(payload["destinationNotes"])
        for note in payload["destinationNotes"]:
            self.assertIn("分目录", note)
        entries = {row["entryId"]: row for row in payload["entries"]}
        for entry_id in ("alpha", "beta", "broken"):
            self.assertTrue(entries[entry_id]["jobId"], entry_id)
        # 该成员通过计划校验（project.yml 存在），失败发生在执行阶段
        self.assertEqual(entries["broken"]["status"], "ready")
        self.assertTrue(entries["broken"]["problems"] == [])
        self.assertIn("view", payload)
        self.assertEqual(payload["view"]["counts"]["total"], 3)

    def test_status_is_read_only_and_reports_failures_inside(self):
        result = _run_cli("delivery-status", "--store", str(self.store), "--output", "json")
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        payload = _json(result)
        self.assertEqual(payload["exitCode"], 0)
        self.assertTrue(payload["storeExists"])
        self.assertEqual(payload["counts"]["failed"], 1)
        self.assertEqual(payload["counts"]["waiting-refresh"], 2)
        self.assertEqual(payload["overallStatus"], "partial")
        self.assertTrue(payload["index"]["entries"])
        # 只读：再次查询不改变 store 内容
        before = self.store.read_bytes()
        self.assertEqual(_run_cli("delivery-status", "--store", str(self.store)).returncode, 0)
        self.assertEqual(self.store.read_bytes(), before)

    def test_strict_threshold_returns_one_but_keeps_readable_results(self):
        result = _run_cli(
            "delivery-run", "--plan", str(self.plan), "--store", str(self.store),
            "--no-refresh", "--strict", "--continue", "--json",
        )
        self.assertEqual(result.returncode, 1, result.stdout[-400:])
        payload = _json(result)
        self.assertEqual(payload["exitCode"], 1)
        self.assertTrue(payload["strict"])
        self.assertEqual(payload["overallStatus"], "partial")
        usable = [job for job in payload["jobs"] if job["usableFormats"]]
        self.assertTrue(usable)  # 严格未满足仍保留可读参考产物

    def test_conflicting_modes_return_two_without_touching_store(self):
        before = self.store.read_bytes()
        result = _run_cli(
            "delivery-run", "--plan", str(self.plan), "--store", str(self.store),
            "--continue", "--retry-failed", "--json",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(_json(result)["exitCode"], 2)
        self.assertEqual(self.store.read_bytes(), before)

    # --- 取消 / 中断继续 / 只重试未完成项 ---

    def test_cancel_after_keeps_first_item_and_cancel_rest(self):
        work = _scratch("v32-entry-cli-cancel")
        store = work / "cancel-store.json"
        result = _run_cli(
            "delivery-run", "--plan", str(self.plan), "--store", str(store),
            "--no-refresh", "--cancel-after", "1", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        payload = _json(result)
        ran = [job for job in payload["jobs"] if job["attemptCount"]]
        cancelled = [job for job in payload["jobs"] if job["status"] == JOB_CANCELLED]
        self.assertEqual(len(ran), 1)
        self.assertEqual(len(cancelled), 2)
        self.assertTrue(all(job["exitCode"] == 2 for job in cancelled))
        self.assertTrue(all(not job["usableFormats"] for job in cancelled))

        # 模拟程序中断：把一项未落定任务标记为 running，重启核对后应转 interrupted 并继续
        data = json.loads(store.read_text(encoding="utf-8"))
        target_id = cancelled[0]["jobId"]
        for row in data["jobs"]:
            if row["jobId"] == target_id:
                row["status"] = "running"
                row["finishedAt"] = ""
        store.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        continued = _run_cli(
            "delivery-run", "--plan", str(self.plan), "--store", str(store),
            "--no-refresh", "--continue", "--json",
        )
        self.assertEqual(continued.returncode, 0, continued.stderr[-500:])
        payload = _json(continued)
        jobs = {job["jobId"]: job for job in payload["jobs"]}
        self.assertEqual(jobs[target_id]["exitCode"], 0)
        self.assertTrue(jobs[target_id]["usableFormats"])
        self.assertGreaterEqual(jobs[target_id]["attemptCount"], 1)
        # 已完成项不被重跑，attempt 历史不变
        self.assertEqual(jobs[ran[0]["jobId"]]["attemptCount"], ran[0]["attemptCount"])
        still_cancelled = [job for job in payload["jobs"] if job["status"] == JOB_CANCELLED]
        self.assertEqual([job["jobId"] for job in still_cancelled], [cancelled[1]["jobId"]])

    def test_retry_unfinished_only_retries_unfinished_items(self):
        work = _scratch("v32-entry-cli-retry")
        members = work / "members"
        members.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(_shared_project()), str(members / "Alpha"))
        _broken_project(members / "Broken")
        plan = _write_plan(
            work / "retry.json",
            {
                "schemaVersion": 1,
                "batchId": "batch-retry",
                "defaults": {"formats": ["html"], "destination": "out"},
                "entries": [
                    {"id": "alpha", "member": "members/Alpha"},
                    {"id": "broken", "member": "members/Broken"},
                ],
            },
        )
        store = work / "retry-store.json"
        first = _run_cli(
            "delivery-run", "--plan", str(plan), "--store", str(store),
            "--no-refresh", "--json",
        )
        self.assertEqual(first.returncode, 0, first.stderr[-500:])
        initial = _json(first)
        done = next(
            job for job in initial["jobs"] if job["status"] in COMPLETED_JOB_STATUSES
        )
        failed = next(job for job in initial["jobs"] if job["status"] == JOB_FAILED)
        self.assertNotIn(done["status"], (JOB_FAILED, JOB_WAITING_REFRESH))

        retried = _run_cli("delivery-retry", "--store", str(store), "--no-refresh", "--json")
        self.assertEqual(retried.returncode, 1, retried.stdout[-400:])
        payload = _json(retried)
        self.assertEqual(payload["retried"], [failed["jobId"]])
        self.assertEqual([job["jobId"] for job in payload["jobs"]], payload["retried"])
        self.assertEqual(payload["overallStatus"], "failed")
        after = _json(_run_cli("delivery-status", "--store", str(store), "--json"))
        counts = {job["jobId"]: job["attemptCount"] for job in after["jobs"]}
        self.assertEqual(counts[done["jobId"]], done["attemptCount"])
        self.assertEqual(counts[failed["jobId"]], 2)
        # 未知 jobId → 参数非法
        unknown = _run_cli(
            "delivery-retry", "--store", str(store), "--job-id", "j-not-exist", "--json",
        )
        self.assertEqual(unknown.returncode, 2)

    # --- 交付包 → 换目录补刷新 ---

    def test_package_then_promote_in_new_directory(self):
        package = self.work / "cli-package.zip"
        result = _run_cli(
            "delivery-package", "--store", str(self.store), "--target", str(package), "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        payload = _json(result)
        self.assertTrue(payload["package"]["ok"], payload["package"]["message"])
        manifest = read_delivery_package(package)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["kind"], "doc-tool-delivery-package")
        for entry in manifest["files"]:
            self.assertFalse(Path(entry["path"]).is_absolute(), entry["path"])
        self.assertNotIn(str(self.work), json.dumps(manifest, ensure_ascii=False))

        destination = self.work / "formalized"
        promoted = _run_cli(
            "delivery-promote", str(package), "--destination", str(destination),
            "--word-available", "no", "--json",
        )
        self.assertEqual(promoted.returncode, 0, promoted.stdout[-400:])
        data = _json(promoted)
        self.assertEqual(data["formalize"]["status"], "waiting-refresh")
        readable = Path(data["formalize"]["readableDocx"])
        self.assertTrue(readable.is_file(), data["formalize"]["readableDocx"])
        self.assertTrue(readable.is_relative_to(destination), str(readable))
        self.assertTrue(package.is_file())  # 原包不删除
        # 无 Word 时不会写正式登记（不冒充正式成功）
        self.assertFalse((destination / "delivery-registry.json").exists())

    # --- 参数/输入非法 ---

    def test_invalid_inputs_return_two(self):
        work = _scratch("v32-entry-cli-invalid")
        bad_schema = _write_plan(
            work / "schema2.json",
            {"schemaVersion": 2, "entries": [{"member": "members/Alpha"}]},
        )
        invalid_only = _write_plan(
            work / "invalid.json",
            {"schemaVersion": 1, "entries": [{"id": "x", "member": "members/Ghost"}]},
        )
        cases = [
            ("delivery-run", "--plan", str(work / "missing.json"), "--json"),
            ("delivery-run", "--plan", str(bad_schema), "--json"),
            ("delivery-run", "--plan", str(invalid_only), "--json"),
            ("delivery-status", "--index", str(work / "missing-index"), "--json"),
            ("delivery-status", "--store", str(work / "missing-store.json"), "--json"),
            ("delivery-retry", "--store", str(work / "missing-store.json"), "--json"),
            ("delivery-promote", str(work / "missing-package.zip"), "--json"),
        ]
        for args in cases:
            result = _run_cli(*args)
            self.assertEqual(result.returncode, 2, "{0} → {1}".format(args, result.stdout[-200:]))
            self.assertEqual(_json(result)["exitCode"], 2, str(args))
        # argparse 层拒绝的参数（choices 校验）同样是 2：用法在 stderr，stdout 为空
        rejected = _run_cli(
            "delivery-promote", str(invalid_only), "--word-available", "maybe", "--json",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(rejected.stdout.strip(), "")
        self.assertIn("--word-available", rejected.stderr)


class PackageFormalizeTests(unittest.TestCase):
    """32-D/4.4/4.5 自动部分：补刷新失败仍保留待刷新可读稿，原包不删除。"""

    @classmethod
    def setUpClass(cls):
        cls.work = _scratch("v32-entry-formalize")
        project = _copy_project("Alpha")
        cls.out = cls.work / "out"
        run_project_export(
            ExportRequest(
                project_root=str(project),
                formats=[FORMAT_DOCX, FORMAT_HTML],
                destination=str(cls.out),
            ),
            skip_word_refresh=True,
        )
        cls.package = cls.work / "package.zip"
        cls.package_outcome = build_delivery_package(cls.out, target=cls.package)

    def test_package_is_self_contained_and_marks_pending_refresh(self):
        self.assertTrue(self.package_outcome.ok, self.package_outcome.message)
        manifest = read_delivery_package(self.package)
        self.assertIsNotNone(manifest)
        self.assertIn("docx-refresh", manifest["pendingStages"])

    def test_refresh_failure_keeps_waiting_refresh_and_original_package(self):
        def broken_adapter(**kwargs):
            raise RuntimeError("模拟 Word 刷新失败")

        destination = self.work / "formalized"
        outcome = formalize_package(
            self.package, destination=destination, word_available=True,
            refresh_adapter=broken_adapter,
        )
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.status, "waiting-refresh")
        self.assertTrue(outcome.readableDocx)
        self.assertTrue(Path(outcome.readableDocx).is_file(), outcome.readableDocx)
        self.assertTrue(self.package.is_file())  # 原包不删除
        # 未形成正式结果时不写正式登记
        self.assertFalse((destination / "delivery-registry.json").exists())
        self.assertTrue(any("刷新" in item for item in outcome.warnings), outcome.warnings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
