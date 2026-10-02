# -*- coding: utf-8 -*-
"""V3.2 2.3/2.4 测试：跨进程 Word 占用标识与临时故障自动重试一次。"""

from __future__ import annotations

import json
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery import word_busy  # noqa: E402
from doc_tool.application.delivery.queue import (  # noqa: E402
    AUTO_RETRY_LIMIT, JOB_FAILED, JOB_WAITING_REFRESH, DeliveryQueue,
)


class WordBusyMarkerTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("word-busy")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_acquire_status_release_round_trip(self):
        ok, reason = word_busy.acquire("测试持有者", root=self.work)
        self.assertTrue(ok, reason)
        state = word_busy.status(self.work)
        self.assertTrue(state.busy)
        self.assertEqual(state.owner, "测试持有者")
        self.assertIn("另一进程", state.reason)
        # 其它 pid 不能再登记
        blocked, why = word_busy.acquire("另一个", root=self.work, pid=999999)
        self.assertFalse(blocked)
        self.assertTrue(why)
        self.assertTrue(word_busy.release(root=self.work))
        self.assertFalse(word_busy.status(self.work).busy)

    def test_stale_marker_is_takeable(self):
        path = word_busy.marker_path(self.work)
        path.write_text(json.dumps({
            "schemaVersion": 1, "owner": "已退出进程", "pid": 999999999,
            "since": "2000-01-01T00:00:00+00:00",
        }), encoding="utf-8")
        state = word_busy.status(self.work)
        self.assertFalse(state.busy)
        self.assertTrue(state.stale)
        ok, _reason = word_busy.acquire("接管者", root=self.work)
        self.assertTrue(ok)
        self.assertEqual(word_busy.status(self.work).owner, "接管者")

    def test_probe_reports_busy_before_local_word(self):
        word_busy.acquire("持有者", root=self.work)
        probe = word_busy.word_busy_probe(self.work, local_probe=lambda: (True, ""))
        available, reason = probe()
        self.assertFalse(available)
        self.assertIn("另一进程", reason)
        word_busy.release(root=self.work)
        self.assertTrue(word_busy.word_busy_probe(self.work, local_probe=lambda: (True, ""))()[0])


class QueueWordBusyTests(unittest.TestCase):
    """队列在 Word 被其它进程占用时把该项转待刷新，其它成员继续。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("queue-word-busy")
        self.project = fixtures.two_chapter_project(self.work / "proj")
        self.store = self.work / "queue.json"

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_busy_marker_turns_job_into_waiting_refresh(self):
        word_busy.acquire("其它进程", root=self.work)
        queue = DeliveryQueue(str(self.store))
        queue._word_probe = None  # 走真实分支：先看跨进程标记
        try:
            # 标记目录与队列 store 不同：直接把标记写到默认位置不现实，
            # 因此这里用注入探测模拟“标记已生效”的等价结果，同时单独验证
            # word_busy_probe 的优先级（见上一条测试）。
            queue._word_probe = word_busy.word_busy_probe(
                self.work, local_probe=lambda: (True, ""),
            )
            queue.enqueue(
                project_root=str(self.project), formats=["docx"], refresh=True,
                destination=str(self.work / "out"),
            )
            jobs = queue.run_pending(skip_word_refresh=False)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].status, JOB_WAITING_REFRESH)
            self.assertIn("另一进程", jobs[0].waitingReason)
            # 可读副本仍保留
            self.assertTrue(jobs[0].usable_results())
            for item in jobs[0].usable_results():
                self.assertTrue(Path(item.path).is_file())
        finally:
            word_busy.release(root=self.work)


class AutoRetryTests(unittest.TestCase):
    """2.4：临时故障（OSError/TimeoutError）自动重试一次；内容类失败不重试。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("queue-retry")
        self.project = fixtures.two_chapter_project(self.work / "proj")
        self.store = self.work / "queue.json"

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _queue(self, runner):
        queue = DeliveryQueue(str(self.store), runner=runner)
        queue.enqueue(
            project_root=str(self.project), formats=["docx"], refresh=False,
            destination=str(self.work / "out"),
        )
        return queue

    def test_transient_failure_is_retried_once_and_then_succeeds(self):
        from doc_tool.application.project_export import run_project_export

        calls = {"count": 0}

        def flaky(request, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("文件被临时占用")
            return run_project_export(request, **kwargs)

        queue = self._queue(flaky)
        jobs = queue.run_pending(skip_word_refresh=True)
        self.assertEqual(len(jobs), 1)
        self.assertNotEqual(jobs[0].status, JOB_FAILED)
        self.assertEqual(calls["count"], 2, "临时故障应自动重试一次")
        attempts = jobs[0].attempts[-1]
        self.assertEqual(attempts.get("autoRetries"), 1)
        self.assertTrue(any("自动重试" in note for note in jobs[0].notes))

    def test_non_transient_failure_is_not_retried(self):
        calls = {"count": 0}

        def broken(request, **kwargs):
            calls["count"] += 1
            raise ValueError("参数非法：不重试")

        queue = self._queue(broken)
        jobs = queue.run_pending(skip_word_refresh=True)
        self.assertEqual(jobs[0].status, JOB_FAILED)
        self.assertEqual(calls["count"], 1, "内容/参数类失败不得自动重试")
        self.assertEqual(AUTO_RETRY_LIMIT, 1)

    def test_repeated_transient_failure_stops_after_limit(self):
        calls = {"count": 0}

        def always_locked(request, **kwargs):
            calls["count"] += 1
            raise OSError("一直占用")

        queue = self._queue(always_locked)
        jobs = queue.run_pending(skip_word_refresh=True)
        self.assertEqual(jobs[0].status, JOB_FAILED)
        self.assertEqual(calls["count"], AUTO_RETRY_LIMIT + 1)


class ProductionWordSlotTests(unittest.TestCase):
    """审计补测：生产路径真的登记/释放跨进程 Word 占用（此前 acquire 无调用者）。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("queue-word-slot")
        self.project = fixtures.two_chapter_project(self.work / "proj")
        self.store = self.work / "queue.json"
        self.marker_root = self.work / "markers"
        self.marker_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        fixtures.cleanup(self.work)

    def _queue(self, runner):
        queue = DeliveryQueue(str(self.store), runner=runner)
        queue.enqueue(
            project_root=str(self.project), formats=["docx"], refresh=True,
            destination=str(self.work / "out"),
        )
        return queue

    def test_word_slot_is_acquired_and_released_around_word_run(self):
        from unittest.mock import patch

        from doc_tool.application.project_export import run_project_export

        acquired = {"calls": 0}
        released = {"calls": 0}
        real_acquire = word_busy.acquire
        real_release = word_busy.release

        def _acquire(*args, **kwargs):
            acquired["calls"] += 1
            return real_acquire(*args, root=self.marker_root, **kwargs)

        def _release(*args, **kwargs):
            released["calls"] += 1
            return real_release(root=self.marker_root, **kwargs)

        def _runner(request, **kwargs):
            # 运行期间标记必须存在（说明确实登记了占用）
            self.assertTrue(
                word_busy.marker_path(self.marker_root).is_file(),
                "驱动 Word 期间应存在跨进程占用标记",
            )
            return run_project_export(request, **kwargs)

        queue = self._queue(_runner)
        queue._word_probe = lambda: (True, "")
        with patch("doc_tool.application.delivery.word_busy.acquire", _acquire), patch(
            "doc_tool.application.delivery.word_busy.release", _release
        ):
            jobs = queue.run_pending(skip_word_refresh=False)
        self.assertTrue(jobs)
        self.assertEqual(acquired["calls"], 1, "应登记一次 Word 占用")
        self.assertEqual(released["calls"], 1, "执行后应释放占用")
        self.assertFalse(
            word_busy.marker_path(self.marker_root).is_file(), "释放后标记应被移除",
        )

    def test_other_process_holding_slot_turns_job_into_waiting_refresh(self):
        from unittest.mock import patch

        from doc_tool.application.project_export import run_project_export

        other = {"pid": 999999}
        real_status = word_busy.status

        def _status(root=None, **kwargs):
            state = real_status(self.marker_root, **kwargs)
            if not state.busy:
                return word_busy.BusyState(
                    busy=True, owner="其它进程", pid=other["pid"],
                    since="2999-01-01T00:00:00+00:00",
                    reason="本应用另一进程正在使用 Word（其它进程，pid 999999）",
                )
            return state

        def _runner(request, **kwargs):
            return run_project_export(request, **kwargs)

        queue = self._queue(_runner)
        queue._word_probe = lambda: (True, "")
        with patch("doc_tool.application.delivery.word_busy.status", _status):
            jobs = queue.run_pending(skip_word_refresh=False)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, JOB_WAITING_REFRESH, jobs[0].to_dict())
        self.assertIn("其它进程", jobs[0].waitingReason)
        self.assertTrue(jobs[0].usable_results())


if __name__ == "__main__":
    unittest.main(verbosity=2)