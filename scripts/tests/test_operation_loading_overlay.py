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


if __name__ == "__main__":
    unittest.main()
