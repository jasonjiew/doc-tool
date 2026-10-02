# -*- coding: utf-8 -*-
"""V3.2 批量交付服务层测试（32-B 队列 / 32-C 包 / 32-D 换机正式化 / 32-E 结果中心）。

覆盖：入队幂等与重复点击、串行部分失败保留其它、取消保留已完成、新实例 resume、
只重试未完成项、store 损坏隔离、Word 忙转待刷新、包搬目录后基于包内快照补格式、
源改动后历史包仍可用（仅提示）、结果索引状态/路径、选择归档部分范围与缺失清单。

真实 Word 刷新与两机器实机流程不在本文件覆盖（保留为无 Word 环境的待验收项）。
运行：python scripts\tests\test_v32_batch_delivery.py
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery.queue import (  # noqa: E402
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_INTERRUPTED,
    JOB_PARTIAL,
    JOB_WAITING_REFRESH,
    DeliveryQueue,
)
from doc_tool.application.delivery.result_index import (  # noqa: E402
    ARCHIVE_MANIFEST_NAME,
    ResultEntry,
    archive_selection,
    build_result_index,
)
from doc_tool.application.delivery.snapshot_package import (  # noqa: E402
    PACKAGE_MANIFEST_NAME,
    build_delivery_package,
    formalize_package,
    read_delivery_package,
    verify_delivery_package,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_PDF,
    FORMAT_SOURCE_ZIP,
    STATUS_FAILED,
    STATUS_PENDING_REFRESH,
    STATUS_READY,
    ExportRequest,
    ExportScope,
    FormatResult,
    sha256_file,
)
from doc_tool.application.project_export import ExportReport, run_project_export  # noqa: E402
from doc_tool.domain.output_state import is_formal_success, write_state  # noqa: E402

#: 本文件创建的全部夹具目录（模块结束时统一清理）。
_SCRATCH: list = []


def _scratch(prefix: str) -> Path:
    path = fixtures.scratch_dir(prefix)
    _SCRATCH.append(path)
    return path


def tearDownModule() -> None:
    for path in _SCRATCH:
        fixtures.cleanup(path)


_SHARED: dict = {"project": None}
_EXPORT: dict = {"dir": None}


def _shared_project() -> Path:
    """真实导入产出的两章项目：本文件只建一次，测试内复制使用。"""
    project = _SHARED.get("project")
    if project is None or not Path(project).is_dir():
        root = _scratch("v32-shared")
        project = fixtures.two_chapter_project(root / "proj")
        _SHARED["project"] = project
    return Path(project)


def _copy_project(name: str) -> Path:
    target = _scratch("v32-proj") / name
    shutil.copytree(str(_shared_project()), str(target))
    return target


def _shared_export_dir() -> Path:
    """真实出稿一轮（docx/html/pdf/source-zip；诊断构建不依赖 Word），多测试复用。"""
    current = _EXPORT.get("dir")
    if current is not None and (Path(current) / "export-result.json").is_file():
        return Path(current)
    out = _scratch("v32-out")
    run_project_export(
        ExportRequest(
            project_root=str(_shared_project()),
            formats=[FORMAT_DOCX, FORMAT_HTML, FORMAT_PDF, FORMAT_SOURCE_ZIP],
            destination=str(out),
        ),
        skip_word_refresh=True,
    )
    _EXPORT["dir"] = out
    return out


def _chapter_path(project: Path) -> Path:
    content = project / "content" / "general"
    candidates = sorted(content.rglob("*.md"))
    for path in candidates:
        if path.name not in ("_index.md", "_revision_record.md"):
            return path
    return candidates[0]


def _tree_state(project: Path) -> dict:
    state = {}
    for folder in ("content", "assets", "template"):
        base = Path(project) / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                state[path.relative_to(project).as_posix()] = sha256_file(path)
    return state


class _FakeRunner:
    """替身执行服务：按成员名计划给状态，行为对齐真实出稿的部分成功语义。"""

    def __init__(self, plan=None):
        self.plan = {key: dict(value) for key, value in (plan or {}).items()}
        self.calls: list = []

    def set_status(self, member: str, fmt: str, status: str) -> None:
        self.plan.setdefault(member, {})[fmt] = status

    def _status(self, member: str, fmt: str, skip_word_refresh: bool) -> str:
        planned = (self.plan.get(member) or {}).get(fmt)
        if planned:
            return planned
        if fmt == FORMAT_DOCX and skip_word_refresh:
            # 真实出稿：跳过 Word 刷新时 DOCX 只能是待刷新可读稿。
            return STATUS_PENDING_REFRESH
        return STATUS_READY

    def __call__(self, request, **kwargs):
        self.calls.append((str(request.project_root), dict(kwargs)))
        destination = Path(request.destination)
        destination.mkdir(parents=True, exist_ok=True)
        member = Path(request.project_root).name
        skip = bool(kwargs.get("skip_word_refresh"))
        prior = kwargs.get("prior")
        only = list(kwargs.get("only_formats") or [])
        results = []
        if prior is not None and only:
            results.extend(item for item in prior.results if item.format not in set(only))
        for fmt in request.formats:
            status = self._status(member, fmt, skip)
            if status == STATUS_FAILED:
                results.append(FormatResult(format=fmt, status=STATUS_FAILED, message="模拟失败"))
                continue
            target = destination / "{0}-{1}.out".format(member, fmt)
            target.parent.mkdir(parents=True, exist_ok=True)
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


def _queue(store: Path, runner=None, word_probe=None) -> DeliveryQueue:
    """构造队列：默认注入「Word 可用」探测，避免测试触发真实 Word 探测。"""
    return DeliveryQueue(
        str(store), runner=runner, word_probe=word_probe or (lambda: (True, "")),
    )


def _fake_refresh(project_root, prior, destination, manifest):
    """替身 Word 刷新：产出新 DOCX 并按既有输出状态定义写正式状态。"""
    source = Path(prior.docxPath)
    target = Path(destination) / (source.stem + "-refreshed.docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    write_state(
        target, formal=True, diagnostic=False, app_version="test",
        schema_version=1, stages=[{"stage": "word-refresh", "status": "succeeded"}],
    )
    return str(target)

class QueueTests(unittest.TestCase):
    """32-B：持久队列去重、串行、取消、中断恢复与只重试未完成项（替身执行服务）。"""

    def setUp(self):
        self.work = _scratch("v32-queue")
        self.store = self.work / "delivery-queue.json"
        self.proj_a = self.work / "项目A"
        self.proj_b = self.work / "项目B"
        self.proj_a.mkdir(parents=True, exist_ok=True)
        self.proj_b.mkdir(parents=True, exist_ok=True)
        self.out = self.work / "out"

    def _enqueue(self, queue, project, formats=None, **kwargs):
        return queue.enqueue(
            project_root=str(project),
            formats=formats or [FORMAT_HTML],
            destination=str(self.out),
            **kwargs
        )

    def test_enqueue_dedupes_unfinished_and_skips_completed(self):
        runner = _FakeRunner()
        queue = _queue(self.store, runner)
        first = self._enqueue(queue, self.proj_a)
        second = self._enqueue(queue, self.proj_a)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.jobId, first.jobId)
        self.assertIn("复用原登记", second.reason)
        self.assertEqual(len(queue.jobs), 1)
        # 不同格式是不同任务
        third = self._enqueue(queue, self.proj_a, formats=[FORMAT_HTML, FORMAT_DOCX])
        self.assertNotEqual(third.jobId, first.jobId)
        self.assertEqual(len(queue.jobs), 2)
        # 执行完成后重复点击默认跳过（不重复登记）
        queue.run_pending()
        self.assertEqual(queue.job(first.jobId).status, JOB_COMPLETED)
        again = self._enqueue(queue, self.proj_a)
        self.assertTrue(again.reused and again.skipped)
        self.assertEqual(len(queue.jobs), 2)
        # 同一次提交（requestId）幂等
        r1 = self._enqueue(queue, self.proj_b, request_id="req-1")
        r2 = self._enqueue(queue, self.proj_b, request_id="req-1")
        self.assertEqual(r1.jobId, r2.jobId)
        self.assertTrue(r2.reused)
        self.assertEqual(len(queue.jobs), 3)

    def test_serial_run_keeps_failed_members_and_records_attempts(self):
        runner = _FakeRunner({"项目B": {FORMAT_HTML: STATUS_FAILED}})
        queue = _queue(self.store, runner)
        first = self._enqueue(queue, self.proj_a).job
        second = self._enqueue(queue, self.proj_b).job
        outcomes = queue.run_pending()
        self.assertEqual([item.jobId for item in outcomes], [first.jobId, second.jobId])
        self.assertEqual(queue.job(first.jobId).status, JOB_COMPLETED)
        self.assertEqual(queue.job(second.jobId).status, JOB_FAILED)
        self.assertTrue(queue.job(second.jobId).error)
        self.assertEqual(queue.job(second.jobId).attemptCount, 1)
        self.assertTrue(queue.job(first.jobId).usable_results())
        # 落盘：新实例读到同样结论
        other = DeliveryQueue(str(self.store))
        self.assertEqual([job.status for job in other.jobs], [JOB_COMPLETED, JOB_FAILED])
        self.assertEqual(len(other.summary_lines()), 3)

    def test_cancel_keeps_completed_members(self):
        runner = _FakeRunner()
        queue = _queue(self.store, runner)
        done = self._enqueue(queue, self.proj_a).job
        queue.run_pending()
        queued = self._enqueue(queue, self.proj_b).job
        self.assertEqual(queue.cancel(), 1)
        self.assertEqual(queue.job(done.jobId).status, JOB_COMPLETED)
        self.assertTrue(queue.job(done.jobId).usable_results())
        self.assertEqual(queue.job(queued.jobId).status, JOB_CANCELLED)
        calls_before = len(runner.calls)
        queue.run_pending()
        self.assertEqual(len(runner.calls), calls_before)
        self.assertTrue(queue.job(done.jobId).usable_results())

    def test_cancel_token_stops_after_current_member(self):
        from doc_tool.domain.cancellation import CancellationToken

        runner = _FakeRunner()
        queue = _queue(self.store, runner)
        first = self._enqueue(queue, self.proj_a).job
        second = self._enqueue(queue, self.proj_b).job
        token = CancellationToken()

        def progress(job, stage, detail):
            if stage == "started" and job.jobId == first.jobId:
                token.request_cancel()

        queue.run_pending(cancel_token=token, progress=progress)
        self.assertTrue(queue.job(first.jobId).usable_results())
        self.assertEqual(queue.job(first.jobId).status, JOB_COMPLETED)
        self.assertEqual(queue.job(second.jobId).status, JOB_CANCELLED)

    def test_resume_in_new_instance_sees_results_and_continues(self):
        runner = _FakeRunner()
        queue = _queue(self.store, runner)
        first = self._enqueue(queue, self.proj_a).job
        second = self._enqueue(queue, self.proj_b).job
        queue.run_pending(only_job_ids=[first.jobId])
        other = _queue(self.store, runner)
        self.assertEqual(other.job(first.jobId).status, JOB_COMPLETED)
        self.assertTrue(other.job(first.jobId).usable_results())
        self.assertEqual(other.job(second.jobId).status, "queued")
        other.resume()
        self.assertEqual(other.job(second.jobId).status, JOB_COMPLETED)
        self.assertEqual(other.job(first.jobId).attemptCount, 1)

    def test_unknown_running_is_interrupted_and_can_continue(self):
        runner = _FakeRunner()
        queue = _queue(self.store, runner)
        job = self._enqueue(queue, self.proj_a).job
        payload = json.loads(self.store.read_text(encoding="utf-8"))
        payload["jobs"][0]["status"] = "running"
        self.store.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        other = _queue(self.store, runner)
        self.assertEqual(other.job(job.jobId).status, JOB_INTERRUPTED)
        other.resume()
        self.assertEqual(other.job(job.jobId).status, JOB_COMPLETED)

    def test_corrupt_store_is_quarantined_and_queue_still_usable(self):
        self.store.write_text("{ 这不是合法 JSON", encoding="utf-8")
        queue = _queue(self.store, _FakeRunner())
        self.assertEqual(queue.jobs, [])
        self.assertTrue(queue.warnings)
        result = self._enqueue(queue, self.proj_a)
        self.assertFalse(result.reused)
        self.assertTrue(self.store.is_file())
        self.assertTrue(list(self.work.glob("delivery-queue.json.corrupt*")))

    def test_retry_unfinished_only_retries_failed_items(self):
        runner = _FakeRunner()
        queue = _queue(self.store, runner)
        good = self._enqueue(queue, self.proj_a).job
        broken = self._enqueue(queue, self.proj_b).job
        runner.set_status(self.proj_b.name, FORMAT_HTML, STATUS_FAILED)
        queue.run_pending()
        self.assertEqual(queue.job(good.jobId).status, JOB_COMPLETED)
        self.assertEqual(queue.job(broken.jobId).status, JOB_FAILED)
        good_attempts = queue.job(good.jobId).attemptCount
        runner.set_status(self.proj_b.name, FORMAT_HTML, STATUS_READY)
        calls_before = len(runner.calls)
        outcomes = queue.retry_unfinished()
        self.assertEqual([item.jobId for item in outcomes], [broken.jobId])
        self.assertEqual(len(runner.calls), calls_before + 1)
        self.assertEqual(queue.job(broken.jobId).status, JOB_COMPLETED)
        self.assertEqual(queue.job(good.jobId).attemptCount, good_attempts)
        # 只补未完成格式：复用原轮快照（prior）并只带失败格式
        last_kwargs = runner.calls[-1][1]
        self.assertEqual(last_kwargs.get("only_formats"), [FORMAT_HTML])
        self.assertIsNotNone(last_kwargs.get("prior"))
        self.assertEqual(queue.job(broken.jobId).attemptCount, 2)

    def test_word_busy_turns_item_to_waiting_refresh(self):
        runner = _FakeRunner()
        queue = _queue(self.store, runner, word_probe=lambda: (False, "Word 正被其它任务占用"))
        first = self._enqueue(queue, self.proj_a, formats=[FORMAT_DOCX]).job
        second = self._enqueue(queue, self.proj_b, formats=[FORMAT_DOCX]).job
        queue.run_pending()
        waited = queue.job(first.jobId)
        self.assertEqual(waited.status, JOB_WAITING_REFRESH)
        self.assertIn("待刷新", waited.waitingReason)
        self.assertTrue(waited.usable_results())
        self.assertEqual(queue.job(second.jobId).status, JOB_WAITING_REFRESH)
        self.assertTrue(runner.calls[0][1].get("skip_word_refresh"))


class QueueIntegrationTests(unittest.TestCase):
    """真实统一出稿服务：三成员串行，个别失败不停止其它成员。"""

    def test_real_export_partial_failure_keeps_other_members(self):
        work = _scratch("v32-queue-real")
        store = work / "delivery-queue.json"
        good_one = _copy_project("proj-1")
        good_two = _copy_project("proj-2")
        missing = work / "不存在的成员"
        out = work / "out"
        queue = DeliveryQueue(str(store), word_probe=lambda: (True, ""))
        first = queue.enqueue(
            project_root=str(good_one), formats=[FORMAT_DOCX, FORMAT_HTML],
            destination=str(out),
        ).job
        bad = queue.enqueue(
            project_root=str(missing), formats=[FORMAT_DOCX, FORMAT_HTML],
            destination=str(out),
        ).job
        second = queue.enqueue(
            project_root=str(good_two), formats=[FORMAT_DOCX, FORMAT_HTML],
            destination=str(out),
        ).job
        outcomes = queue.run_pending(skip_word_refresh=True)
        self.assertEqual(len(outcomes), 3)
        self.assertEqual(queue.job(bad.jobId).status, JOB_FAILED)
        self.assertTrue(queue.job(bad.jobId).error)
        for job in (queue.job(first.jobId), queue.job(second.jobId)):
            self.assertTrue(job.usable_results(), job.error)
            for item in job.usable_results():
                self.assertTrue(Path(item.path).is_file(), item.path)
            self.assertIn(job.status, (JOB_WAITING_REFRESH, JOB_COMPLETED, JOB_PARTIAL))
            self.assertTrue(job.indexPath and Path(job.indexPath).is_file())
        # 落盘结果可被新实例读取，且逐项状态清楚
        other = DeliveryQueue(str(store))
        self.assertEqual(other.counts()["total"], 3)
        self.assertEqual(other.job(bad.jobId).status, JOB_FAILED)
        # 待刷新项与失败项都算未完成（可用「重试未完成项」继续）
        self.assertEqual(len(other.unfinished_jobs()), 3)
        report = other.machine_report()
        self.assertEqual(report["schemaVersion"], 1)
        self.assertEqual(len(report["jobs"]), 3)

class PackageTests(unittest.TestCase):
    """32-C/32-D：自足快照包、搬目录补格式、源改动提示与本地幂等登记。"""

    def setUp(self):
        self.work = _scratch("v32-package")
        self.out_dir = _shared_export_dir()

    def _build_zip(self, name: str = "pkg.zip", **kwargs):
        target = self.work / name
        outcome = build_delivery_package(self.out_dir, target=target, **kwargs)
        self.assertTrue(outcome.ok, outcome.message)
        return outcome

    def test_package_is_self_contained_with_relative_paths_only(self):
        outcome = self._build_zip("self-contained.zip", variant_id="variant-A")
        manifest = read_delivery_package(outcome.path)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["kind"], "doc-tool-delivery-package")
        self.assertEqual(manifest["origin"]["variantId"], "variant-A")
        self.assertIn("docx-refresh", manifest["pendingStages"])
        self.assertTrue(manifest["inputDigest"])
        self.assertTrue(manifest["chapterDigests"])
        for entry in manifest["files"]:
            self.assertFalse(Path(entry["path"]).is_absolute(), entry["path"])
        text = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn(str(self.out_dir), text)
        self.assertNotIn(":\\", text)
        with zipfile.ZipFile(outcome.path) as archive:
            names = archive.namelist()
            self.assertIn(PACKAGE_MANIFEST_NAME, names)
            self.assertTrue(any(name.startswith("docx/") for name in names))
            self.assertTrue(any(name.startswith("snapshot/content/") for name in names))
            self.assertTrue(any(name.startswith("snapshot/template/") for name in names))
            self.assertIn("reports/export-result.json", names)
            self.assertFalse(any(".git" in name for name in names))
            self.assertFalse(any("__pycache__" in name for name in names))
            self.assertFalse(any(name.startswith("snapshot/output/") for name in names))
            self.assertFalse(any("/logs/" in name for name in names))
            packaged = json.loads(archive.read("reports/export-result.json").decode("utf-8"))
            self.assertEqual(packaged["destination"], ".")
            self.assertEqual(packaged["snapshotWorkDir"], "snapshot")
        check = verify_delivery_package(outcome.path)
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.missingOptional, [])

    def test_package_moves_to_new_directory_and_formalizes_from_packaged_snapshot(self):
        outcome = self._build_zip("moved.zip")
        moved = self.work / "另一台机器" / "解压后的包"
        moved.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(outcome.path) as archive:
            archive.extractall(moved)
        self.assertIsNotNone(read_delivery_package(moved))
        result = formalize_package(moved, destination=self.work / "换机输出", word_available=False)
        self.assertEqual(result.status, "waiting-refresh", result.message)
        self.assertTrue(result.readableDocx and Path(result.readableDocx).is_file())
        self.assertIn(FORMAT_DOCX, result.pendingFormats)
        # PDF 是否仍待转换取决于本机转换能力（有 Word 时已随轮转换）：两种结论都必须明确
        pdf_entry = next((item for item in result.results if item.format == FORMAT_PDF), None)
        if pdf_entry is not None and pdf_entry.usable:
            self.assertNotIn(FORMAT_PDF, result.pendingFormats)
        else:
            self.assertIn(FORMAT_PDF, result.pendingFormats)
        self.assertIn("待刷新", result.message)
        # 基于包内快照继续：工作副本来自包，不依赖原机器路径
        self.assertTrue((Path(result.workRoot) / "snapshot" / "project.yml").is_file())
        # 原包不删除
        self.assertTrue(outcome.path.is_file())

    def test_formalize_registers_once_and_reprocess_is_idempotent(self):
        outcome = self._build_zip("register.zip")
        dest = self.work / "正式输出"
        first = formalize_package(
            outcome.path, destination=dest, word_available=True, refresh_adapter=_fake_refresh,
        )
        self.assertEqual(first.status, "registered", first.message)
        self.assertTrue(is_formal_success(first.registeredPath))
        registry = dest / "delivery-registry.json"
        entries = json.loads(registry.read_text(encoding="utf-8"))["entries"]
        self.assertEqual(len(entries), 1)
        second = formalize_package(
            outcome.path, destination=dest, word_available=True, refresh_adapter=_fake_refresh,
        )
        self.assertEqual(second.status, "already-registered")
        self.assertEqual(second.registeredPath, first.registeredPath)
        entries_again = json.loads(registry.read_text(encoding="utf-8"))["entries"]
        self.assertEqual(len(entries_again), 1)
        self.assertTrue(outcome.path.is_file())

    def test_registration_failure_keeps_new_docx_and_old_record(self):
        outcome = self._build_zip("register-fail.zip")
        dest = self.work / "登记失败输出"
        dest.mkdir(parents=True, exist_ok=True)
        registry = dest / "delivery-registry.json"
        registry.write_text(
            json.dumps({
                "schemaVersion": 1,
                "entries": [{"key": "old-key", "packageId": "pkg-old", "path": str(dest / "old.docx")}],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        before = registry.read_text(encoding="utf-8")

        def broken_writer(path, entry):
            raise OSError("模拟登记写入失败")

        result = formalize_package(
            outcome.path, destination=dest, word_available=True,
            refresh_adapter=_fake_refresh, registry_writer=broken_writer,
        )
        self.assertEqual(result.status, "registration-failed")
        self.assertTrue(Path(result.readableDocx).is_file())
        self.assertIn("待登记", result.readableDocx)
        self.assertEqual(registry.read_text(encoding="utf-8"), before)
        self.assertTrue(outcome.path.is_file())

    def test_source_change_only_notes_captured_snapshot(self):
        outcome = self._build_zip("history.zip")
        project = _copy_project("source-copy")
        chapter = _chapter_path(project)
        chapter.write_text("源项目后来改了。\n", encoding="utf-8")
        before = _tree_state(project)
        result = formalize_package(
            outcome.path, destination=self.work / "history-out",
            word_available=False, source_project_root=project,
        )
        self.assertTrue(result.sourceUpdated)
        self.assertTrue(any("捕获快照" in item for item in result.warnings), result.warnings)
        self.assertEqual(result.status, "waiting-refresh")
        self.assertTrue(outcome.path.is_file())
        # 不追当前源，也不改写当前项目正文/模板
        self.assertEqual(_tree_state(project), before)

    def test_invalid_package_and_hash_mismatch_are_rejected(self):
        broken = self.work / "broken.zip"
        broken.write_bytes(b"this-is-not-a-package")
        self.assertIsNone(read_delivery_package(broken))
        result = formalize_package(broken, destination=self.work / "nope", word_available=False)
        self.assertEqual(result.status, "invalid")
        outcome = self._build_zip("tampered.zip")
        tampered = self.work / "tampered-dir"
        with zipfile.ZipFile(outcome.path) as archive:
            archive.extractall(tampered)
        chapter = next((tampered / "snapshot" / "content").rglob("*.md"))
        chapter.write_text("内容被改。\n", encoding="utf-8")
        check = verify_delivery_package(tampered)
        self.assertFalse(check.ok)
        self.assertTrue(any("哈希不符" in item for item in check.problems), check.problems)
        result2 = formalize_package(tampered, destination=self.work / "nope2", word_available=False)
        self.assertEqual(result2.status, "invalid")

    def test_package_requires_readable_docx(self):
        report = ExportReport(
            projectRoot=str(self.work / "proj"),
            scope=ExportScope(),
            results=[FormatResult(format=FORMAT_DOCX, status=STATUS_FAILED, message="构建失败")],
            snapshotWorkDir=str(self.work),
        )
        outcome = build_delivery_package(report, target=self.work / "no-docx.zip")
        self.assertFalse(outcome.ok)
        self.assertIn("DOCX", outcome.message)

def _word_environment_reason() -> str:
    """本机 Word 不可用/被占用时给出跳过原因（否则返回空串）。"""
    try:
        from doc_tool.application.delivery import word_busy
        from doc_tool.application.word_check import check_word_available

        busy = word_busy.status()
        if getattr(busy, "busy", False):
            return "本机 Word 正被占用（{0}）：可读 DOCX 生成留待实机".format(
                getattr(busy, "owner", "") or "未知占用者"
            )
        report = check_word_available(dispatch_check=True, dispatch_timeout_seconds=30.0)
        if not report.available:
            return "本机 Word 不可用（{0}）：可读 DOCX 生成留待实机".format(
                "；".join(report.reasons[:2]) or "未探测到"
            )
    except Exception as exc:  # noqa: BLE001 - 探测失败按“环境不确定”处理
        return "Word 可用性探测失败（{0}）".format(exc)
    return ""


class ResultIndexTests(unittest.TestCase):
    """32-E：结果索引视图、缺失清单与选择归档的部分范围标注。"""

    def setUp(self):
        self.work = _scratch("v32-index")
        self.out_dir = _shared_export_dir()

    def test_index_lists_member_variant_format_status_and_paths(self):
        pkg = self.work / "pkg.zip"
        outcome = build_delivery_package(self.out_dir, target=pkg, variant_id="variant-B")
        if not outcome.ok and "可读 DOCX" in str(outcome.message):
            # 只有**确认**是环境问题（Word 被占用/不可用）才跳过；否则保持硬断言，
            # 避免把真实回归伪装成环境跳过。
            reason = _word_environment_reason()
            if reason:
                self.skipTest("{0}；原始信息：{1}".format(reason, outcome.message))
        self.assertTrue(outcome.ok, outcome.message)
        store = self.work / "queue.json"
        queue = _queue(store, _FakeRunner())
        queue.enqueue(
            project_root=str(self.work / "成员一"), formats=[FORMAT_HTML],
            destination=str(self.work / "queue-out"),
        )
        queue.run_pending()
        index = build_result_index([self.out_dir, pkg, store])
        self.assertTrue(index.entries)
        formats = {item.format for item in index.entries}
        self.assertIn(FORMAT_DOCX, formats)
        self.assertIn(FORMAT_HTML, formats)
        self.assertIn("variant-B", {item.variantId for item in index.entries})
        self.assertEqual(
            {item.sourceKind for item in index.entries},
            {"export-index", "delivery-package", "delivery-queue"},
        )
        packaged_docx = [
            item for item in index.entries
            if item.sourceKind == "delivery-package" and item.format == FORMAT_DOCX
        ][0]
        self.assertEqual(packaged_docx.status, STATUS_PENDING_REFRESH)
        self.assertIn("pkg.zip::docx/", packaged_docx.path)
        self.assertTrue(packaged_docx.exists)
        self.assertTrue(all(item.exists for item in index.entries if item.path))
        self.assertEqual(index.missing_paths(), [])
        # 部分完成绝不标 complete
        self.assertEqual(index.overall_status(), "partial")
        self.assertIn('"overallStatus": "partial"', index.to_json())
        self.assertTrue(any("待刷新" in line for line in index.summary_lines()))

    def test_missing_path_is_listed(self):
        copied = self.work / "copied-out"
        shutil.copytree(str(self.out_dir), str(copied))
        payload = json.loads((copied / "export-result.json").read_text(encoding="utf-8"))
        html_entry = next(item for item in payload["results"] if item["format"] == FORMAT_HTML)
        Path(html_entry["path"]).unlink()
        index = build_result_index([copied])
        self.assertEqual(index.missing_paths(), [html_entry["path"]])
        entry = [item for item in index.entries if item.format == FORMAT_HTML][0]
        self.assertFalse(entry.exists)
        self.assertFalse(entry.usable)
        self.assertEqual(index.overall_status(), "partial")
        self.assertTrue(any("缺失" in line for line in index.summary_lines()))

    def test_archive_selection_marks_partial_range(self):
        index = build_result_index([self.out_dir])
        docx_entry = next(
            item for item in index.entries if item.format == FORMAT_DOCX and item.exists
        )
        target = self.work / "selection.zip"
        outcome = archive_selection(index, target, selection=[docx_entry])
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(outcome.partial)
        self.assertFalse(outcome.complete)
        self.assertTrue(outcome.omitted)
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            self.assertIn(ARCHIVE_MANIFEST_NAME, names)
            manifest = json.loads(archive.read(ARCHIVE_MANIFEST_NAME).decode("utf-8"))
            self.assertTrue(manifest["partial"])
            self.assertFalse(manifest["complete"])
            self.assertIn("部分范围", manifest["selection"])
            self.assertTrue(manifest["omitted"])
            self.assertTrue(any(name.endswith(".docx") for name in names))
        self.assertTrue(any("部分范围" in line for line in outcome.summary_lines()))

    def test_archive_lists_missing_selected_paths(self):
        index = build_result_index([self.out_dir])
        missing_path = str(self.work / "不存在.docx")
        index.entries.append(ResultEntry(
            member="成员X", variantId="", format=FORMAT_DOCX, status=STATUS_READY,
            path=missing_path, sourceKind="export-index", sourceRef="手工构造",
            exists=False, usable=False,
        ))
        html_entry = next(item for item in index.entries if item.format == FORMAT_HTML and item.exists)
        target = self.work / "selection-missing.zip"
        outcome = archive_selection(index, target, selection=[missing_path, html_entry])
        self.assertIn(missing_path, outcome.missing)
        self.assertTrue(outcome.partial)
        with zipfile.ZipFile(target) as archive:
            manifest = json.loads(archive.read(ARCHIVE_MANIFEST_NAME).decode("utf-8"))
            self.assertIn(missing_path, manifest["missing"])
            self.assertTrue(manifest["partial"])

    def test_archive_can_take_results_out_of_package_zip(self):
        pkg = self.work / "archive-pkg.zip"
        outcome = build_delivery_package(self.out_dir, target=pkg)
        self.assertTrue(outcome.ok, outcome.message)
        index = build_result_index([pkg])
        entry = next(item for item in index.entries if item.format == FORMAT_DOCX and item.exists)
        target = self.work / "from-package.zip"
        archived = archive_selection(index, target, selection=[entry])
        self.assertTrue(archived.ok, archived.message)
        with zipfile.ZipFile(target) as archive:
            self.assertTrue(any(name.endswith(".docx") for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main(verbosity=2)