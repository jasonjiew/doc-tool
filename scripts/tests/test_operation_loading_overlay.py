# -*- coding: utf-8 -*-
"""操作级加载遮罩与异步任务调度单元测试（无头模式运行）。"""

import os
import sys
import unittest
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

# 确保 QApplication 单例存在
app = QApplication.instance()
if app is None:
    app = QApplication(["--platform", "offscreen"])

from doc_tool.ui.operation_loading_overlay import (
    OperationLoadingOverlay,
    AsyncOperationWorker,
    run_async_operation,
)


class OperationLoadingOverlayTests(unittest.TestCase):
    def setUp(self):
        self.top_widget = QWidget()
        self.top_widget.resize(800, 600)
        self.top_widget.show()
        app.processEvents()

    def tearDown(self):
        self.top_widget.close()
        app.processEvents()

    def test_overlay_creation_and_theming(self):
        # 浅色模式
        overlay_light = OperationLoadingOverlay(self.top_widget, dark=False)
        self.assertFalse(overlay_light._dark)
        self.assertEqual(overlay_light.width(), self.top_widget.width())

        # 深色模式
        overlay_dark = OperationLoadingOverlay(self.top_widget, dark=True)
        self.assertTrue(overlay_dark._dark)

        # 切换深色模式
        overlay_light.set_dark(True)
        self.assertTrue(overlay_light._dark)

    def test_overlay_start_and_text_updates(self):
        overlay = OperationLoadingOverlay(self.top_widget, dark=True, cancellable=True, min_display_ms=0)
        overlay.start("正在测试…", "测试步骤 1", progress=25, cancellable=True)
        app.processEvents()

        self.assertTrue(overlay.isVisible())
        self.assertEqual(overlay._title_label.text(), "正在测试…")
        self.assertEqual(overlay._desc_label.text(), "测试步骤 1")
        self.assertEqual(overlay._progress_bar.value(), 25)
        self.assertTrue(overlay._close_btn.isVisible())

        # 更新文字
        overlay.update_text("更新后标题", "更新后描述")
        self.assertEqual(overlay._title_label.text(), "更新后标题")
        self.assertEqual(overlay._desc_label.text(), "更新后描述")

        # 更新进度
        overlay.update_progress(80, "即将完成…")
        self.assertEqual(overlay._progress_bar.value(), 80)
        self.assertEqual(overlay._desc_label.text(), "即将完成…")

        # 结束淡出
        done = []
        overlay.finish(lambda: done.append(True))
        # 等待淡出动画完成
        loop = QEventLoop()
        overlay._fade_anim.finished.connect(loop.quit)
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        app.processEvents()
        self.assertTrue(done)
        self.assertFalse(overlay.isVisible())

    def test_async_operation_worker_success(self):
        def _slow_task():
            time.sleep(0.02)
            return "ok_result"

        worker = AsyncOperationWorker(_slow_task)
        results = []
        worker.sig_finished.connect(lambda res: results.append(res))

        worker.start()
        worker.wait(2000)
        app.processEvents()
        self.assertEqual(results, ["ok_result"])

    def test_async_operation_worker_error(self):
        def _failing_task():
            raise ValueError("Something went wrong")

        worker = AsyncOperationWorker(_failing_task)
        errors = []
        worker.sig_error.connect(lambda err: errors.append(err))

        worker.start()
        worker.wait(2000)
        app.processEvents()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertIn("Something went wrong", str(errors[0]))

    def test_run_async_operation_integration(self):
        def _task():
            time.sleep(0.02)
            return 42

        success_results = []
        overlay, worker = run_async_operation(
            self.top_widget,
            _task,
            title="执行异步任务",
            description="计算中…",
            dark=False,
            min_display_ms=100,  # 测试中使用较短最小展示时间
            on_success=lambda r: success_results.append(r),
        )
        app.processEvents()

        self.assertTrue(overlay.isVisible())
        self.assertEqual(overlay._title_label.text(), "执行异步任务")

        # 等待任务与动画完成
        worker.wait(2000)
        app.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()
        app.processEvents()

        self.assertEqual(success_results, [42])
        self.assertFalse(overlay.isVisible())




from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from doc_tool.ui.project_loading_overlay import ProjectLoadingOverlay


class ProjectLoadingOverlayTests(unittest.TestCase):
    def setUp(self):
        self.top_widget = QWidget()
        self.top_widget.resize(800, 600)
        self.top_widget.show()
        app.processEvents()

    def tearDown(self):
        self.top_widget.close()
        app.processEvents()

    def test_project_overlay_theming(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        self.assertFalse(overlay._dark)
        overlay.set_dark(True)
        self.assertTrue(overlay._dark)

    def test_project_overlay_start_and_stage_stepping(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        overlay.start("my_project", "正在解析项目元数据…")
        app.processEvents()

        self.assertTrue(overlay.isVisible())
        self.assertIn("my_project", overlay._title_label.text())
        self.assertEqual(overlay._current_step, 0)
        self.assertEqual(overlay._progress_bar.value(), 15)
        self.assertTrue(overlay._spinner._timer.isActive())

        # 步进：全文索引
        overlay.show_stage("正在构建全文索引…")
        self.assertEqual(overlay._current_step, 1)
        self.assertEqual(overlay._progress_bar.value(), 55)

        # 步进：准备工作区
        overlay.show_stage("正在准备工作区视图…")
        self.assertEqual(overlay._current_step, 2)
        self.assertEqual(overlay._progress_bar.value(), 75)

        # 步进：恢复标签
        overlay.show_stage("正在恢复标签…")
        self.assertEqual(overlay._current_step, 3)
        self.assertEqual(overlay._progress_bar.value(), 90)

        # 步进：就绪（关键词包含准备时，必须优先匹配就绪，不回退进度）
        overlay.show_stage("准备就绪")
        self.assertEqual(overlay._current_step, 4)
        self.assertEqual(overlay._progress_bar.value(), 100)

    def test_project_overlay_finish_keeps_spinner_during_fadeout(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        overlay.start("test_proj")
        app.processEvents()
        self.assertTrue(overlay._spinner._timer.isActive())

        done = []
        overlay.finish(lambda: done.append(True))
        # 验证在动画执行期间，spinner 依然处于运行状态，没有被提前停止冻结
        self.assertTrue(overlay._is_finishing)
        self.assertTrue(overlay._spinner._timer.isActive(), "Spinner 必须在淡出动画期间继续旋转，不可冻结")
        self.assertEqual(overlay._stage_label.text(), "就绪")
        self.assertEqual(overlay._progress_bar.value(), 100)

        # 等待动画完成
        loop = QEventLoop()
        overlay._anim.finished.connect(loop.quit)
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        app.processEvents()

        self.assertTrue(done)
        self.assertFalse(overlay.isVisible())
        self.assertFalse(overlay._spinner._timer.isActive(), "动画结束后 Spinner 应该停止")
        self.assertFalse(overlay._is_finishing)

    def test_project_overlay_reentry_guard(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        overlay.start("test_proj")
        app.processEvents()

        cb_calls = []
        overlay.finish(lambda: cb_calls.append(1))
        # 再次调用 finish
        overlay.finish(lambda: cb_calls.append(2))
        self.assertEqual(cb_calls, [2], "重入时应直接触发新回调，不重置正在执行的淡出动画")

        loop = QEventLoop()
        overlay._anim.finished.connect(loop.quit)
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        app.processEvents()
        self.assertEqual(cb_calls, [2, 1])

    def test_project_overlay_esc_key(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        overlay.start("test_proj")
        app.processEvents()

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        overlay.keyPressEvent(event)
        self.assertTrue(overlay._is_finishing, "按 Esc 键应触发 finish")



    def test_project_overlay_finish_immediately(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        overlay.start("test_proj")
        app.processEvents()
        self.assertTrue(overlay.isVisible())

        done = []
        overlay.finish_immediately(lambda: done.append(True))
        app.processEvents()
        self.assertFalse(overlay.isVisible())
        self.assertFalse(overlay._is_finishing)
        self.assertFalse(overlay._spinner._timer.isActive())
        self.assertEqual(done, [True])

    def test_project_overlay_safety_hide(self):
        overlay = ProjectLoadingOverlay(self.top_widget, dark=False)
        overlay.start("test_proj")
        app.processEvents()
        self.assertTrue(overlay.isVisible())

        # 调用 _safety_hide
        overlay._safety_hide()
        app.processEvents()
        self.assertFalse(overlay.isVisible())

    def test_build_content_context_vcs_preheat(self):
        import tempfile
        from pathlib import Path
        from doc_tool.ui.content.workspace import build_content_context

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "01-intro.md").write_text("# Intro\nhello", encoding="utf-8")
            mock_calls = []
            class DummyVCS:
                def detect(self):
                    mock_calls.append("detect")
                def branches(self):
                    mock_calls.append("branches")

            vcs = DummyVCS()
            idx = build_content_context(p, vcs_service=vcs)
            self.assertIn("01-intro.md", idx.all_files())
            self.assertEqual(mock_calls, ["detect", "branches"])

if __name__ == "__main__":
    unittest.main()
