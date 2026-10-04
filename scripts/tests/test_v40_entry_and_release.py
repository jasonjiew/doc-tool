# -*- coding: utf-8 -*-
"""V4.0 40-D 4.4：源码入口/冻结构建 helper、线程与 UI 分工、反复开关释放。"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from PySide6.QtWidgets import QApplication  # noqa: E402

SPEC_FILES = ("packaging/doc_tool.spec", "packaging/doc_tool_onefile.spec")


class FrozenSourceEntryTests(unittest.TestCase):
    """冻结条件不具备时，至少核对源码入口与 spec 指向真实存在的文件。"""

    def test_spec_entry_scripts_exist(self):
        for rel in SPEC_FILES:
            spec = REPO_ROOT / rel
            self.assertTrue(spec.is_file(), rel)
            text = spec.read_text(encoding="utf-8")
            referenced = re.findall(r'REPO_ROOT\s*/\s*"([^"]+)"', text)
            self.assertTrue(referenced, "{0} 未引用任何源码入口".format(rel))
            for item in referenced:
                # 只校验脚本/数据类入口；目录型引用允许不存在（构建期生成）
                if item.endswith(".py") or item.endswith(".spec"):
                    self.assertTrue(
                        (REPO_ROOT / item).is_file(),
                        "{0} 引用了不存在的入口：{1}".format(rel, item),
                    )

    def test_gui_and_cli_entrypoints_both_present(self):
        for rel in ("doc_tool/app.py", "doc_tool_cli.py"):
            self.assertTrue((REPO_ROOT / rel).is_file(), rel)
        spec = (REPO_ROOT / "packaging/doc_tool.spec").read_text(encoding="utf-8")
        self.assertIn("doc_tool/app.py", spec.replace('" / "', "/"))
        self.assertIn("doc_tool_cli.py", spec)
        self.assertIn('name="DocTool"', spec)
        self.assertIn('name="doc-tool-cli"', spec)
        # 运行时加固 hook 也必须真实存在
        self.assertTrue((REPO_ROOT / "packaging/rthook_hardened_runtime.py").is_file())

    def test_hardened_runtime_hook_does_not_require_gui(self):
        """runtime hook 必须能在无 GUI 环境下导入（CLI 入口共用）。"""
        source = (REPO_ROOT / "packaging/rthook_hardened_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("PySide6", source.split("import")[0] or "")
        self.assertFalse(
            re.search(r"^\s*from\s+PySide6", source, re.M),
            "运行时 hook 不得硬依赖 GUI 框架",
        )


class RepeatedOpenCloseReleaseTests(unittest.TestCase):
    """反复打开/关闭：对象不堆积，关闭后不留可继续使用的窗口。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v40-44-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_repeated_open_close_releases_windows_and_controller(self):
        import gc

        from doc_tool.ui.main_window import MainWindow

        created = []
        for index in range(3):
            window = MainWindow()
            created.append(window)
            self.assertFalse(window.runner.is_running, "新窗口不得处于运行态")
            window._persist_workspace_session = lambda *a, **k: None
            window._persist_geometry = lambda *a, **k: None
            window.close()
            QApplication.processEvents()
            # 关闭后不再有可用的内容工作区（控制器已释放）
            workspace = getattr(window, "_content_workspace", None)
            if workspace is not None:
                with self.assertRaises(RuntimeError):
                    workspace.isVisible()  # 已销毁的 Qt 对象
        for window in created:
            try:
                window.deleteLater()
            except RuntimeError:
                pass
        QApplication.processEvents()
        gc.collect()
        # 关闭的窗口不留运行中的任务（注册表接口若存在则必须为空）
        from doc_tool.ui.task_bridge import TaskRunner

        registry = getattr(TaskRunner, "running_instances", None)
        if callable(registry):
            for runner in registry() or []:
                self.assertFalse(getattr(runner, "is_running", False),
                                 "关闭后不得遗留运行中的任务")

    def test_background_tasks_are_owned_not_leaked(self):
        """后台任务必须有明确归属，且关闭后没有遗留运行中的 runner。"""
        from doc_tool.ui.task_bridge import TaskRunner

        runner = TaskRunner()
        self.assertFalse(runner.is_running)
        self.assertTrue(hasattr(runner, "is_running"))
        # 长操作必须经既有 runner 统一驱动（存在真实归属）
        source = (REPO_ROOT / "doc_tool/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("self.runner.", source, "长操作必须由 runner 统一驱动")
        # 界面不得自建 QThread / 多进程（会绕过安全取消与日志归属）
        for forbidden in ("QThread(", "multiprocessing.Process("):
            self.assertFalse(
                forbidden in source,
                "界面不得自建 QThread/多进程：{0}".format(forbidden),
            )
        # 已知遗留点（如实登记，不在本轮改）：发布前检查用 daemon 线程 + 主线程
        # processEvents/sleep 忙等；数量必须为 1，增量须显式说明。
        self.assertEqual(
            source.count("threading.Thread("), 1,
            "界面内自建线程的数量发生变化，请同步更新 40-D 4.4 的登记",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)