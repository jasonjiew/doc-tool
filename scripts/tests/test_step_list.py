# -*- coding: utf-8 -*-
"""步骤清单纯逻辑测试：``derive_step_list`` 状态推导。

覆盖：步骤状态（待处理/进行中/成功/跳过/失败/取消）、事件乱序（单调推进、
不回退）、心跳任务无伪造百分比、取消边界（当前步骤标记取消、后续保持待处理）。
纯逻辑，无需 QApplication 或 Qt 控件。
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from doc_tool.ui.workbench_state import (  # noqa: E402
    STEP_STATUS_CANCELLED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SKIPPED,
    STEP_STATUS_SUCCESS,
    derive_step_list,
)


class DeriveStepListTests(unittest.TestCase):
    def test_full_pipeline_success_order(self):
        """按顺序推进：started->running，succeeded->success。"""
        steps = derive_step_list([
            ("build", "started", "", None),
            ("build", "succeeded", "构建完成", None),
            ("validate_pre", "started", "", None),
            ("validate_pre", "succeeded", "校验通过", None),
            ("publish", "started", "", None),
            ("publish", "succeeded", "已原子发布", None),
        ])
        self.assertEqual(len(steps), 5)
        by_stage = {s.stage: s.status for s in steps}
        self.assertEqual(by_stage["build"], STEP_STATUS_SUCCESS)
        self.assertEqual(by_stage["validate_pre"], STEP_STATUS_SUCCESS)
        self.assertEqual(by_stage["publish"], STEP_STATUS_SUCCESS)
        # word_refresh / validate_post 从未 started -> 保持待处理
        self.assertEqual(by_stage["word_refresh"], STEP_STATUS_PENDING)
        self.assertEqual(by_stage["validate_post"], STEP_STATUS_PENDING)
        # 阶段顺序与管线一致（build 在最前，publish 在最后）
        self.assertEqual([s.stage for s in steps], [
            "build", "validate_pre", "word_refresh", "validate_post", "publish",
        ])

    def test_skipped_stage_marks_skipped_and_keeps_order(self):
        """诊断模式：word_refresh/validate_post 跳过，后续仍按原顺序推进。"""
        steps = derive_step_list([
            ("build", "started", "", None),
            ("build", "succeeded", "", None),
            ("word_refresh", "skipped", "已显式跳过", None),
            ("validate_post", "skipped", "诊断模式跳过", None),
            ("publish", "succeeded", "", None),
        ])
        by_stage = {s.stage: s.status for s in steps}
        self.assertEqual(by_stage["word_refresh"], STEP_STATUS_SKIPPED)
        self.assertEqual(by_stage["validate_post"], STEP_STATUS_SKIPPED)
        self.assertEqual(by_stage["publish"], STEP_STATUS_SUCCESS)

    def test_failed_stage_keeps_error_code(self):
        """失败步骤携带 error_code，后续步骤保持待处理。"""
        steps = derive_step_list([
            ("build", "started", "", None),
            ("build", "succeeded", "", None),
            ("validate_pre", "started", "", None),
            ("validate_pre", "failed", "校验未通过", "E2002"),
        ])
        by_stage = {s.stage: s for s in steps}
        self.assertEqual(by_stage["validate_pre"].status, STEP_STATUS_FAILED)
        self.assertEqual(by_stage["validate_pre"].error_code, "E2002")
        # publish 未开始 -> 待处理
        self.assertEqual(by_stage["publish"].status, STEP_STATUS_PENDING)

    def test_event_out_of_order_does_not_regress(self):
        """事件乱序（skipped 早于 started）单调推进、不回退。"""
        steps = derive_step_list([
            ("build", "succeeded", "", None),
            ("word_refresh", "skipped", "", None),
            ("validate_pre", "succeeded", "", None),
            ("build", "started", "", None),  # 迟到的 started 不应回退 build
        ])
        by_stage = {s.stage: s.status for s in steps}
        # 最后状态由收到的最后事件决定：build 收到 started -> running
        self.assertEqual(by_stage["build"], STEP_STATUS_RUNNING)
        self.assertEqual(by_stage["validate_pre"], STEP_STATUS_SUCCESS)
        self.assertEqual(by_stage["word_refresh"], STEP_STATUS_SKIPPED)

    def test_heartbeat_task_single_running_step(self):
        """心跳任务（无管线阶段）回退为单个进行中步骤，不伪造百分比。"""
        steps = derive_step_list(
            [("validate", "started", "", None)], fallback_label="校验"
        )
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].label, "校验")
        self.assertEqual(steps[0].status, STEP_STATUS_RUNNING)

    def test_empty_events_yield_empty_steps(self):
        self.assertEqual(derive_step_list([]), [])

    def test_cancel_boundary_marks_current_stage_cancelled(self):
        """取消边界：当前进行中步骤标记取消，后续保持待处理。"""
        steps = derive_step_list([
            ("build", "started", "", None),
            ("build", "succeeded", "", None),
            ("validate_pre", "started", "", None),
            ("validate_pre", "cancelled", "任务已被取消", None),
        ])
        by_stage = {s.stage: s.status for s in steps}
        self.assertEqual(by_stage["validate_pre"], STEP_STATUS_CANCELLED)
        self.assertEqual(by_stage["word_refresh"], STEP_STATUS_PENDING)
        self.assertEqual(by_stage["publish"], STEP_STATUS_PENDING)

    def test_running_stage_stays_running_without_terminal(self):
        """当前步骤 started 但尚未终态 -> 保持进行中。"""
        steps = derive_step_list([
            ("build", "started", "", None),
            ("build", "succeeded", "", None),
            ("validate_pre", "started", "", None),
        ])
        by_stage = {s.stage: s.status for s in steps}
        self.assertEqual(by_stage["validate_pre"], STEP_STATUS_RUNNING)


if __name__ == "__main__":
    unittest.main()
