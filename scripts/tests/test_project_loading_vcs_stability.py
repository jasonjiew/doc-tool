# -*- coding: utf-8 -*-
"""项目打开加载与 VCS 缓存预热稳定性测试。

覆盖：
1. ChangeDetectionService 在无 Git 仓库、脏仓库、大仓库冷启动下的缓存稳定性；
2. build_content_context 后台任务取消令牌与预热保护；
3. ProjectLoadingOverlay 完整生命周期（start, stage, finish, finish_immediately, Esc, 按钮点击, 防重入, 兜底隐藏）。
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance()
if app is None:
    app = QApplication(["--platform", "offscreen"])

from doc_tool.application.content.vcs_changes import (
    ChangeDetectionService,
    ChangeReport,
    GitBranch,
    clear_vcs_cache,
)
from doc_tool.domain.cancellation import CancellationToken
from doc_tool.ui.content.workspace import (
    build_content_context,
    ContentWorkspace,
)
from doc_tool.ui.project_loading_overlay import ProjectLoadingOverlay


class VcsCacheStabilityTests(unittest.TestCase):
    """测试 VCS 缓存与预热在各种边界场景下的稳定性。"""

    def setUp(self):
        clear_vcs_cache()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.content_root = self.project_root / "content"
        self.content_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        clear_vcs_cache()
        self._temp_dir.cleanup()

    def test_non_git_repo_branches_caching(self):
        """无 Git 仓库冷启动：branches() 应缓存结果，避免主线程反复扫描。"""
        svc = ChangeDetectionService(self.project_root, self.content_root)

        # 初始状态无缓存
        branches, has_cache = svc.get_cached_branches()
        self.assertEqual(branches, [])
        self.assertFalse(has_cache)

        # 第一次调用：探测并返回不在 Git 仓库内
        with patch.object(svc, "detect", wraps=svc.detect) as mock_detect:
            branches1, err1 = svc.branches()
            self.assertEqual(branches1, [])
            self.assertIn("不在 Git 仓库内", err1)
            self.assertEqual(mock_detect.call_count, 1)

            # 现在应已缓存
            cached_b, has_cache_now = svc.get_cached_branches()
            self.assertEqual(cached_b, [])
            self.assertTrue(has_cache_now)

            # 第二次调用：直接命中 _branches_cache，不得再次调用 detect
            branches2, err2 = svc.branches()
            self.assertEqual(branches2, [])
            self.assertIn("不在 Git 仓库内", err2)
            self.assertEqual(mock_detect.call_count, 1)

    def test_cache_invalidation_clears_tracked_and_branches(self):
        """invalidate_cache 应同时清理 _branches_cache 与 _tracked_cache。"""
        svc = ChangeDetectionService(self.project_root, self.content_root)
        svc._branches_cache = (time.monotonic(), [GitBranch(name="main", is_current=True)], None)
        svc._tracked_cache = (time.monotonic(), True)

        svc.invalidate_cache()
        self.assertIsNone(svc._branches_cache)
        self.assertIsNone(svc._tracked_cache)

    def test_dirty_repo_branches_and_uncommitted_count(self):
        """脏仓库：有多个未提交/未跟踪文件时，当前分支应准确反映 uncommitted_count。"""
        mock_runner = MagicMock()

        def fake_run(args, cwd=None, **kwargs):
            cmd = " ".join(args)
            proc = MagicMock()
            proc.returncode = 0
            if "symbolic-ref" in cmd:
                proc.stdout = b"feature/test-dirty\n"
            elif "for-each-ref" in cmd and "refs/heads" in cmd:
                proc.stdout = b"feature/test-dirty|*|origin/feature/test-dirty|ahead 2, behind 1\nmain||origin/main|\n"
            elif "for-each-ref" in cmd and "refs/remotes" in cmd:
                proc.stdout = b"origin/feature/test-dirty|\norigin/main|\n"
            elif "status --porcelain" in cmd:
                # 模拟脏工作区：1 个修改，1 个未跟踪，1 个暂存新增（全在 project_root 下）
                proc.stdout = b" M doc.md\x00?? new.md\x00A  staged.md\x00"
            elif "diff --cached" in cmd:
                proc.stdout = b"A\x00staged.md\x00"
            elif "diff --name-status" in cmd:
                proc.stdout = b"M\x00doc.md\x00"
            elif "ls-files" in cmd:
                proc.stdout = b"doc.md\x00staged.md\x00"
            else:
                proc.stdout = b""
            proc.stderr = b""
            return proc

        mock_runner.side_effect = fake_run

        # 伪造 .git 目录使之识别为 git 仓库
        git_dir = self.project_root / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        svc = ChangeDetectionService(
            self.project_root, self.content_root, git_runner=mock_runner
        )

        branches, err = svc.branches()
        self.assertIsNone(err)
        # 包含本地分支与远程分支
        self.assertTrue(len(branches) >= 2)

        cur = next(b for b in branches if b.is_current)
        self.assertEqual(cur.name, "feature/test-dirty")
        self.assertEqual(cur.ahead_count, 2)
        self.assertEqual(cur.behind_count, 1)
        self.assertEqual(cur.uncommitted_count, 3)

        # 缓存有效性验证
        cached_b, has_cache = svc.get_cached_branches()
        self.assertTrue(has_cache)
        self.assertEqual(len(cached_b), len(branches))

    def test_build_content_context_cancel_token_stops_vcs(self):
        """若任务在构建或快照期间已被取消，应跳过后续耗时的 VCS 预热。"""
        token = CancellationToken()
        token.request_cancel()

        mock_vcs = MagicMock()

        # 执行后台任务
        index = build_content_context(
            self.content_root,
            cancel_token=token,
            vcs_service=mock_vcs,
        )
        self.assertIsNotNone(index)
        # 取消后 VCS 预热方法不得被调用
        mock_vcs.detect.assert_not_called()
        mock_vcs.branches.assert_not_called()

    def test_corrupt_git_head_branches_cache(self):
        """损坏的 .git/HEAD 目录：branches() 应优雅捕获异常并缓存错误，避免反复抛错卡死主线程。"""
        git_dir = self.project_root / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "HEAD").write_text("invalid garbage ref", encoding="utf-8")

        svc = ChangeDetectionService(self.project_root, self.content_root)
        branches, err = svc.branches()
        self.assertEqual(branches, [])
        self.assertIsNotNone(err)

        # 验证已缓存
        cached_b, has_cache = svc.get_cached_branches()
        self.assertTrue(has_cache)
        self.assertEqual(cached_b, [])

    def test_build_content_context_prewarms_vcs_successfully(self):
        """正常流程下 build_content_context 应顺利并发预热 VCS detect 与 branches。"""
        mock_vcs = MagicMock()
        mock_vcs.detect.return_value = ChangeReport(source="git", project_root=str(self.project_root))
        mock_vcs.branches.return_value = ([], None)

        index = build_content_context(
            self.content_root,
            vcs_service=mock_vcs,
        )
        self.assertIsNotNone(index)
        mock_vcs.detect.assert_called_once()
        mock_vcs.branches.assert_called_once()


class ProjectLoadingOverlayLifecycleTests(unittest.TestCase):
    """测试 ProjectLoadingOverlay 的生命周期与用户交互。"""

    def setUp(self):
        self.top_widget = QWidget()
        self.top_widget.resize(800, 600)
        self.top_widget.show()
        app.processEvents()
        self.overlay = ProjectLoadingOverlay(self.top_widget, dark=False)

    def tearDown(self):
        self.overlay.finish_immediately()
        self.top_widget.close()
        app.processEvents()

    def test_start_and_stage_stepping(self):
        """测试 start 与各阶段进度步进匹配。"""
        self.overlay.start("TestProj", "正在解析配置与元数据…")
        self.assertTrue(self.overlay.isVisible())
        self.assertEqual(self.overlay._current_step, 0)
        self.assertEqual(self.overlay._progress_bar.value(), 15)

        # 步进到索引
        self.overlay.show_stage("正在构建内容索引…")
        self.assertEqual(self.overlay._current_step, 1)
        self.assertEqual(self.overlay._progress_bar.value(), 55)

        # 步进到工作区视图准备
        self.overlay.show_stage("正在准备工作区视图…")
        self.assertEqual(self.overlay._current_step, 2)
        self.assertEqual(self.overlay._progress_bar.value(), 75)

        # 终态就绪
        self.overlay.show_stage("就绪")
        self.assertEqual(self.overlay._current_step, 4)
        self.assertEqual(self.overlay._progress_bar.value(), 100)

    def test_finish_smooth_fade_out(self):
        """测试 finish 平滑淡出与完成回调触发。"""
        self.overlay.start("TestProj")
        app.processEvents()

        callback_called = False

        def on_done():
            nonlocal callback_called
            callback_called = True

        self.overlay.finish(on_finished=on_done)
        self.assertTrue(self.overlay._is_finishing)
        self.assertEqual(self.overlay._stage_label.text(), "就绪")

        # 触发动画结束或安全兜底隐藏
        self.overlay._on_animation_finished()
        self.assertFalse(self.overlay.isVisible())
        self.assertFalse(self.overlay._is_finishing)
        self.assertTrue(callback_called)

    def test_finish_immediately(self):
        """测试 finish_immediately 立即隐藏且无需等待动画。"""
        self.overlay.start("TestProj")
        app.processEvents()

        callback_called = False

        def on_done():
            nonlocal callback_called
            callback_called = True

        self.overlay.finish_immediately(on_finished=on_done)
        self.assertFalse(self.overlay.isVisible())
        self.assertFalse(self.overlay._is_finishing)
        self.assertTrue(callback_called)

    def test_key_press_escape_triggers_finish(self):
        """按 Esc 键应触发 finish 进入淡出状态。"""
        self.overlay.start("TestProj")
        app.processEvents()
        self.assertTrue(self.overlay.isVisible())

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.overlay.keyPressEvent(event)
        app.processEvents()

        self.assertTrue(self.overlay._is_finishing)
        self.overlay._on_animation_finished()
        self.assertFalse(self.overlay.isVisible())

    def test_close_and_skip_buttons_trigger_finish(self):
        """点击卡片右上角关闭按钮或跳过按钮应触发 finish。"""
        # 1. 关闭按钮
        self.overlay.start("TestProj")
        app.processEvents()
        self.assertTrue(self.overlay.isVisible())
        self.overlay._close_btn.click()
        app.processEvents()
        self.assertTrue(self.overlay._is_finishing)
        self.overlay.finish_immediately()
        self.assertFalse(self.overlay.isVisible())

        # 2. 跳过按钮
        self.overlay.start("TestProj")
        app.processEvents()
        self.assertTrue(self.overlay.isVisible())
        self.overlay._skip_btn.click()
        app.processEvents()
        self.assertTrue(self.overlay._is_finishing)
        self.overlay.finish_immediately()
        self.assertFalse(self.overlay.isVisible())

    def test_overlay_transparent_for_mouse_during_finish(self):
        """淡出动画期间应开启 WA_TransparentForMouseEvents，让用户能直接点击底层界面。"""
        self.overlay.start("TestProj")
        app.processEvents()
        self.assertFalse(self.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

        self.overlay.finish()
        self.assertTrue(self.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.overlay.finish_immediately()
        self.assertFalse(self.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_start_cancels_previous_safety_hide_timer(self):
        """多次打开/切换项目时，前一个 finish 的 safety_hide 定时器不得误杀新启动的遮罩。"""
        self.overlay.start("Proj1")
        app.processEvents()
        self.overlay.finish()
        gen_before = self.overlay._anim_generation

        # 立即启动新项目
        self.overlay.start("Proj2")
        self.assertTrue(self.overlay.isVisible())
        self.assertNotEqual(self.overlay._anim_generation, gen_before)

        # 模拟旧定时器带旧 generation 迟到触发
        self.overlay._safety_hide(gen_before)
        # 新遮罩必须依然可见，未被误杀
        self.assertTrue(self.overlay.isVisible())
        self.assertFalse(self.overlay._is_finishing)

    def test_overlay_non_callable_callback_safety(self):
        """传入非 callable 回调（如 Qt clicked 信号的 checked 布尔值）时不应抛出异常。"""
        self.overlay.start("TestProj")
        app.processEvents()
        self.overlay.finish(True)  # checked=True
        self.overlay._on_animation_finished()
        self.assertFalse(self.overlay.isVisible())

    def test_reentrancy_finish_protection(self):
        """连续多次调用 finish 时不应重发动效，且应保证回调执行。"""
        self.overlay.start("TestProj")
        app.processEvents()

        called1 = False
        called2 = False

        self.overlay.finish(on_finished=lambda: globals().update(called1=True))
        # 第二次调用（带回调）
        self.overlay.finish(on_finished=lambda: globals().update(called2=True))

        self.assertTrue(self.overlay._is_finishing)
        self.overlay.finish_immediately()
        self.assertFalse(self.overlay.isVisible())

    def test_start_resets_previous_state(self):
        """多次 start 应清理旧的回调与 finishing 状态。"""
        self.overlay._on_finished_callback = lambda: None
        self.overlay._is_finishing = True

        self.overlay.start("NewProj")
        self.assertIsNone(self.overlay._on_finished_callback)
        self.assertFalse(self.overlay._is_finishing)
        self.assertTrue(self.overlay.isVisible())

    def test_safety_hide(self):
        """安全兜底隐藏测试：当动画因异常未触发结束时，_safety_hide 能可靠关闭。"""
        self.overlay.start("TestProj")
        app.processEvents()
        self.assertTrue(self.overlay.isVisible())

        self.overlay._safety_hide()
        self.assertFalse(self.overlay.isVisible())
        self.assertFalse(self.overlay._is_finishing)


if __name__ == "__main__":
    unittest.main()
