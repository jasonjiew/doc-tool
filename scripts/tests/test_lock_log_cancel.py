# -*- coding: utf-8 -*-
"""项目锁、轮转日志与取消令牌的破坏性测试。

任务 5.6：增加并发启动、陈旧锁、取消和失败不覆盖上次输出的破坏性测试。

覆盖范围：
- 并发启动：活动锁存在时第二次 acquire 被拒绝（E4001）。
- 陈旧锁：持有进程已退出时锁被受控清理，新任务可获取。
- 取消令牌：阶段边界取消生效，临界区内取消不中断。
- 失败不覆盖上次输出：构建失败时上次有效输出保留不变。
- 脱敏日志：日志记录阶段/计数/哈希指纹，但不包含正文或完整路径。
- 日志轮转：超过上限时自动轮转，保留历史文件。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)  # test_project_build 在 scripts/tests/

from doc_tool.domain.cancellation import CancellationToken  # noqa: E402
from doc_tool.domain.errors import (  # noqa: E402
    CancelledError,
    ProjectLockBusyError,
)
from doc_tool.domain.paths import ProjectPaths  # noqa: E402
from doc_tool.domain.project_lock import (  # noqa: E402
    TASK_BUILD,
    TASK_VALIDATE,
    acquire_lock,
    force_clean_stale_lock,
    inspect_lock,
    release_lock,
)
from doc_tool.domain.runtime_log import RuntimeLog  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ProjectLockTests(unittest.TestCase):
    """任务 5.1/5.2：项目锁获取、活动锁拒绝、陈旧锁清理。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-lock-")
        self.paths = ProjectPaths(self._tmp)
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_acquire_and_release_lock(self):
        """获取锁后可释放，释放后可再次获取。"""
        lock = acquire_lock(self.paths, TASK_BUILD, "1.0.0")
        self.assertEqual(lock.task_type, TASK_BUILD)
        self.assertTrue(self.paths.lock_file.exists())
        self.assertTrue(release_lock(self.paths))
        self.assertFalse(self.paths.lock_file.exists())
        # 释放后可再次获取
        acquire_lock(self.paths, TASK_VALIDATE, "1.0.0")
        self.assertTrue(self.paths.lock_file.exists())
        release_lock(self.paths)

    def test_concurrent_acquire_rejected(self):
        """活动锁存在时第二次获取被拒绝（E4001）。"""
        acquire_lock(self.paths, TASK_BUILD, "1.0.0")
        with self.assertRaises(ProjectLockBusyError) as ctx:
            acquire_lock(self.paths, TASK_VALIDATE, "1.0.0")
        self.assertIn("E4001", ctx.exception.code)
        # 锁文件仍存在，属于第一个任务
        lock = inspect_lock(self.paths)
        self.assertIsNotNone(lock)
        self.assertEqual(lock.task_type, TASK_BUILD)

    def test_stale_lock_cleaned_on_acquire(self):
        """陈旧锁（PID 已不存在）在获取时被自动清理。"""
        # 写入一个指向不存在 PID 的锁
        import json
        stale = {
            "host": os.environ.get("COMPUTERNAME", ""),
            "pid": 999999,
            "startTime": "2026-01-01T00:00:00+00:00",
            "taskType": TASK_BUILD,
            "appVersion": "0.9.0",
        }
        # 使用 socket.gethostname 保证主机名一致
        import socket
        stale["host"] = socket.gethostname()
        self.paths.lock_file.write_text(
            json.dumps(stale), encoding="utf-8"
        )
        # 获取时应自动清理陈旧锁
        lock = acquire_lock(self.paths, TASK_VALIDATE, "1.0.0")
        self.assertEqual(lock.task_type, TASK_VALIDATE)
        release_lock(self.paths)

    def test_force_clean_stale_lock(self):
        """force_clean_stale_lock 仅清理陈旧锁，不清理活动锁。"""
        # 活动锁不可强制清理
        acquire_lock(self.paths, TASK_BUILD, "1.0.0")
        self.assertFalse(force_clean_stale_lock(self.paths))
        release_lock(self.paths)

        # 陈旧锁可强制清理
        import json
        import socket
        stale = {
            "host": socket.gethostname(),
            "pid": 999999,
            "startTime": "2026-01-01T00:00:00+00:00",
            "taskType": TASK_BUILD,
            "appVersion": "0.9.0",
        }
        self.paths.lock_file.write_text(json.dumps(stale), encoding="utf-8")
        self.assertTrue(force_clean_stale_lock(self.paths))
        self.assertFalse(self.paths.lock_file.exists())

    def test_release_only_own_lock(self):
        """释放锁时仅删除自己持有的锁，不删除他人的。"""
        import json
        import socket
        foreign = {
            "host": socket.gethostname(),
            "pid": 999999,
            "startTime": "2026-01-01T00:00:00+00:00",
            "taskType": TASK_BUILD,
            "appVersion": "0.9.0",
        }
        self.paths.lock_file.write_text(json.dumps(foreign), encoding="utf-8")
        # 当前进程 PID 不是 999999，释放应失败
        self.assertFalse(release_lock(self.paths))
        self.assertTrue(self.paths.lock_file.exists())


class CancellationTokenTests(unittest.TestCase):
    """任务 5.5：取消令牌阶段边界检查与临界区保护。"""

    def test_cancel_at_boundary(self):
        """取消在阶段边界生效。"""
        token = CancellationToken()
        token.check_cancel()  # 未取消，不抛
        token.request_cancel()
        self.assertTrue(token.is_cancelled)
        with self.assertRaises(CancelledError):
            token.check_cancel()

    def test_critical_section_protects(self):
        """临界区内 check_cancel 不抛出，退出后恢复。"""
        token = CancellationToken()
        token.request_cancel()
        with token.critical_section():
            # 临界区内不抛
            token.check_cancel()
            token.check_cancel()
        # 退出临界区后恢复
        with self.assertRaises(CancelledError):
            token.check_cancel()

    def test_nested_critical_sections(self):
        """嵌套临界区全部退出后才恢复取消检查。"""
        token = CancellationToken()
        token.request_cancel()
        with token.critical_section():
            token.check_cancel()
            with token.critical_section():
                token.check_cancel()
            # 内层退出，外层仍保护
            token.check_cancel()
        # 全部退出后恢复
        with self.assertRaises(CancelledError):
            token.check_cancel()

    def test_reset(self):
        """reset 清除取消状态。"""
        token = CancellationToken()
        token.request_cancel()
        self.assertTrue(token.is_cancelled)
        token.reset()
        self.assertFalse(token.is_cancelled)
        token.check_cancel()  # 不抛


class RuntimeLogTests(unittest.TestCase):
    """任务 5.4：脱敏轮转日志。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-log-")
        self.paths = ProjectPaths(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_log_records_stage_and_metrics(self):
        """日志记录阶段、状态、版本和计数。"""
        log = RuntimeLog(self.paths, app_version="1.0.0")
        log.info("build", "started")
        log.info("build", "succeeded", {"elements": 11, "tables": 1})
        records = log.read_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["stage"], "build")
        self.assertEqual(records[0]["status"], "started")
        self.assertEqual(records[0]["appVersion"], "1.0.0")
        self.assertEqual(records[1]["metrics"]["elements"], 11)

    def test_log_sanitizes_hash_and_path(self):
        """哈希截断为指纹，路径仅保留文件名。"""
        log = RuntimeLog(self.paths, app_version="1.0.0")
        long_hash = "a" * 64
        full_path = str(self.paths.root / "deep" / "secret" / "chapter.md")
        log.info("import", "succeeded", {
            "sourceSha256": long_hash,
            "outputPath": full_path,
        })
        records = log.read_records()
        metrics = records[0]["metrics"]
        # 哈希被截断
        self.assertEqual(metrics["sourceSha256"], "aaaaaaaaaaaa...")
        self.assertNotIn(full_path, metrics["outputPath"])
        self.assertEqual(metrics["outputPath"], "chapter.md")

    def test_log_truncates_long_strings(self):
        """超长字符串被截断，防止意外记录正文。"""
        log = RuntimeLog(self.paths, app_version="1.0.0")
        long_text = "X" * 500
        log.info("build", "failed", {"detail": long_text})
        records = log.read_records()
        detail = records[0]["metrics"]["detail"]
        self.assertLess(len(detail), 250)
        self.assertIn("[truncated]", detail)

    def test_log_error_records_exception_type(self):
        """error 级别记录异常类型和用户消息，不含堆栈。"""
        log = RuntimeLog(self.paths, app_version="1.0.0")
        from doc_tool.domain.errors import BuildError
        exc = BuildError("构建失败：模板损坏")
        log.error("build", exception=exc)
        records = log.read_records()
        self.assertEqual(records[0]["level"], "error")
        self.assertEqual(records[0]["exceptionType"], "BuildError")
        self.assertEqual(records[0]["exceptionMessage"], "构建失败：模板损坏")

    def test_log_rotation(self):
        """超过上限时日志轮转，保留历史文件。"""
        log = RuntimeLog(
            self.paths, app_version="1.0.0", max_bytes=200, backup_count=2
        )
        # 写入足够多记录触发轮转
        for i in range(20):
            log.info("build", "started", {"index": i})
        # 当前日志文件存在
        self.assertTrue(log.log_file.exists())
        # 至少有一个历史文件
        rotated = log.log_file.with_suffix(".log.1")
        self.assertTrue(rotated.exists())
        # 当前文件不超过上限太多（单条记录约 100 字节，轮转后新文件较小）
        self.assertLess(log.log_file.stat().st_size, 200 + 200)

    def test_log_no_body_content(self):
        """日志绝不包含完整的 Markdown 正文内容（超长被截断）。"""
        log = RuntimeLog(self.paths, app_version="1.0.0")
        # 即使 metrics 中意外包含正文，也应被截断
        body_text = "# 第一章\n\n这是正文内容，不应该出现在日志中。" * 10
        log.info("build", "succeeded", {"body": body_text})
        records = log.read_records()
        line = json.dumps(records[0], ensure_ascii=False)
        # 完整正文不应出现
        self.assertNotIn(body_text, line)
        # 应被截断标记
        self.assertIn("[truncated]", line)


class PipelineLockAndCancelTests(unittest.TestCase):
    """任务 5.6：管线集成的锁与取消破坏性测试。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-pipe-lock-")
        self.project_root = self._tmp
        # 复用 test_project_build 的项目夹具
        from test_project_build import _setup_project, _make_manifest
        _setup_project(self.project_root)
        self._make_manifest = _make_manifest

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_pipeline_acquires_and_releases_lock(self):
        """管线执行后锁被释放，可再次执行。"""
        from doc_tool.application.pipeline import run_pipeline
        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        result = run_pipeline(manifest, paths, skip_word_refresh=True)
        # 执行后锁应已释放
        self.assertFalse(paths.lock_file.exists())
        # 可再次执行（锁已释放）
        result2 = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertIsNotNone(result2.output_path)

    def test_pipeline_rejects_concurrent_run(self):
        """活动锁存在时管线拒绝执行并返回 E4001。"""
        from doc_tool.application.pipeline import run_pipeline
        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        # 预先获取锁模拟另一个任务
        acquire_lock(paths, TASK_BUILD, "1.0.0")
        try:
            result = run_pipeline(manifest, paths, skip_word_refresh=True)
            self.assertFalse(result.success)
            self.assertEqual(result.error_code, "E4001")
        finally:
            release_lock(paths)

    def test_pipeline_cancellation_between_stages(self):
        """在构建阶段前取消，管线返回 cancelled 状态。"""
        from doc_tool.application.pipeline import run_pipeline
        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        token = CancellationToken()
        token.request_cancel()  # 预先取消
        result = run_pipeline(
            manifest, paths, skip_word_refresh=True, cancel_token=token
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E5003")
        # 锁应已释放
        self.assertFalse(paths.lock_file.exists())

    def test_pipeline_failure_preserves_previous_output(self):
        """构建失败时不覆盖上次有效输出。"""
        from doc_tool.application.pipeline import STAGE_BUILD, run_pipeline
        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        # 第一次构建（构建阶段必须成功，校验可能因模板孤立关系失败）
        result1 = run_pipeline(manifest, paths, skip_word_refresh=True)
        build_ok = any(
            e.stage == STAGE_BUILD and e.status == "succeeded" for e in result1.events
        )
        self.assertTrue(build_ok)
        self.assertIsNotNone(result1.output_path)
        output1 = result1.output_path
        self.assertTrue(os.path.isfile(output1))
        hash1 = _sha256(output1)
        # 删除模板制造构建失败
        os.remove(str(paths.template_docx))
        result2 = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertFalse(result2.success)
        # 上次输出仍存在且未被修改
        self.assertTrue(os.path.isfile(output1))
        self.assertEqual(_sha256(output1), hash1)


def _sha256(path: str) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main(verbosity=2)
