# -*- coding: utf-8 -*-
"""Git UI 组件单元测试（无头模式运行）。"""

import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# 确保 QApplication 单例存在
app = QApplication.instance()
if app is None:
    app = QApplication(["--platform", "offscreen"])

from doc_tool.application.content.changes import ChangeItem
from doc_tool.application.content.vcs_changes import GitBranch
from doc_tool.ui.content.branch_popover import BranchPopover, NewBranchDialog
from doc_tool.ui.content.git_commit_dialog import GitCommitDialog


class BranchUITests(unittest.TestCase):
    def test_new_branch_dialog_validation(self):
        existing = ["master", "dev", "feature/login"]
        dlg = NewBranchDialog("master", existing)

        # 初始状态
        self.assertFalse(dlg._create_btn.isEnabled())

        # 空格非法
        dlg._input.setText("feature with space")
        self.assertFalse(dlg._create_btn.isEnabled())
        self.assertIn("非法特殊字符", dlg._tip_label.text())

        # 重名校验
        dlg._input.setText("dev")
        self.assertFalse(dlg._create_btn.isEnabled())
        self.assertIn("已存在", dlg._tip_label.text())

        # 包含 .. 非法
        dlg._input.setText("feat..test")
        self.assertFalse(dlg._create_btn.isEnabled())
        self.assertIn("Git 命名规则", dlg._tip_label.text())

        # 合法分支名
        dlg._input.setText("feature/new-branch")
        self.assertTrue(dlg._create_btn.isEnabled())
        self.assertEqual(dlg._tip_label.text(), "")

    def test_branch_popover_filtering(self):
        branches = [
            GitBranch(name="master", is_current=True, uncommitted_count=3),
            GitBranch(name="feature/user-auth", is_current=False),
            GitBranch(name="bugfix/issue-42", is_current=False),
        ]
        popover = BranchPopover(branches)
        self.assertEqual(popover._list_widget.count(), 3)

        # 过滤
        popover._filter_branches("user")
        self.assertEqual(popover._list_widget.count(), 1)
        item = popover._list_widget.item(0)
        b = item.data(Qt.ItemDataRole.UserRole)
        self.assertEqual(b.name, "feature/user-auth")

        # 清空过滤恢复全部
        popover._filter_branches("")
        self.assertEqual(popover._list_widget.count(), 3)

    def test_git_commit_dialog(self):
        items = [
            ChangeItem(rel_path="content/01.md", status="modified", baseline_rel_path="content/01.md"),
            ChangeItem(rel_path="content/02.md", status="added", baseline_rel_path="content/02.md"),
            ChangeItem(rel_path="content/03.md", status="deleted", baseline_rel_path="content/03.md"),
        ]
        dlg = GitCommitDialog(items, can_push=True)
        self.assertEqual(dlg._list_widget.count(), 3)
        self.assertTrue(dlg._commit_btn.isEnabled())
        self.assertIn("已选择 3 / 3 个改动文件", dlg._count_label.text())

        # 快捷前缀插入
        dlg._insert_prefix("docs:")
        self.assertTrue(dlg._msg_input.toPlainText().startswith("docs:"))

        # 取消全选
        dlg._select_all_cb.setChecked(False)
        self.assertFalse(dlg._commit_btn.isEnabled())
        self.assertIn("已选择 0 / 3 个改动文件", dlg._count_label.text())

        # 仅勾选一个
        dlg._list_widget.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dlg._commit_btn.isEnabled())
        self.assertIn("已选择 1 / 3 个改动文件", dlg._count_label.text())

    def test_branch_popover_show_anchored_none(self):
        branches = [GitBranch(name="master", is_current=True)]
        popover = BranchPopover(branches)
        # 测试 anchor 为 None 或隐藏控件时的容错与居中定位
        popover.show_anchored(None)
        self.assertTrue(popover.isVisible())
        popover.close()

    def test_new_branch_dialog_html_escaping(self):
        # 分支名含 HTML 特殊字符
        dlg = NewBranchDialog("feat<custom&name>", ["master"])
        self.assertIsNotNone(dlg)

    def test_git_commit_dialog_ctrl_enter_shortcut(self):
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent

        items = [ChangeItem(rel_path="content/01.md", status="modified", baseline_rel_path="content/01.md")]
        dlg = GitCommitDialog(items)
        dlg._msg_input.setPlainText("feat: test commit")

        # 模拟在输入框中按 Ctrl+Enter
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        handled = dlg.eventFilter(dlg._msg_input, event)
        self.assertTrue(handled)
        self.assertEqual(dlg.commit_message, "feat: test commit")
        self.assertEqual(dlg.selected_paths, ["content/01.md"])

    def test_rename_branch_dialog_validation(self):
        from doc_tool.ui.content.branch_popover import RenameBranchDialog

        existing = ["main", "dev", "feature/login"]
        dlg = RenameBranchDialog("dev", existing)

        # 初始状态（名字未变）不能重命名
        self.assertFalse(dlg._confirm_btn.isEnabled())

        # 空格非法
        dlg._input.setText("dev with space")
        self.assertFalse(dlg._confirm_btn.isEnabled())

        # 重名校验
        dlg._input.setText("main")
        self.assertFalse(dlg._confirm_btn.isEnabled())
        self.assertIn("已存在", dlg._tip_label.text())

        # 合法新名字
        dlg._input.setText("dev-v2")
        self.assertTrue(dlg._confirm_btn.isEnabled())

    def test_branch_popover_tabs_and_signals(self):
        branches = [
            GitBranch(name="main", is_current=True, is_remote=False, ahead_count=1, behind_count=2),
            GitBranch(name="feature/login", is_current=False, is_remote=False),
            GitBranch(name="origin/main", is_current=False, is_remote=True),
            GitBranch(name="origin/feature/login", is_current=False, is_remote=True),
        ]
        popover = BranchPopover(branches)
        self.assertEqual(popover._list_widget.count(), 4)

        # 切换到「本地」Tab
        popover._on_tab_changed("local")
        self.assertEqual(popover._list_widget.count(), 2)
        for i in range(popover._list_widget.count()):
            b = popover._list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            self.assertFalse(b.is_remote)

        # 切换到「远程」Tab
        popover._on_tab_changed("remote")
        self.assertEqual(popover._list_widget.count(), 2)
        for i in range(popover._list_widget.count()):
            b = popover._list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            self.assertTrue(b.is_remote)

        # 切换回全部
        popover._on_tab_changed("all")
        self.assertEqual(popover._list_widget.count(), 4)

        # 动态更新 set_branches
        new_branches = [GitBranch(name="main", is_current=True)]
        popover.set_branches(new_branches)
        self.assertEqual(popover._list_widget.count(), 1)

        # 信号测试
        refreshed = []
        fetched = []
        popover.refresh_requested.connect(lambda: refreshed.append(True))
        popover.fetch_requested.connect(lambda: fetched.append(True))
        popover._refresh_btn.click()
        popover._fetch_btn.click()
        self.assertTrue(refreshed)
        self.assertTrue(fetched)

    def test_project_loading_overlay(self):
        from PySide6.QtWidgets import QWidget
        from doc_tool.ui.project_loading_overlay import ProjectLoadingOverlay

        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        overlay = ProjectLoadingOverlay(parent, dark=False)
        self.assertTrue(overlay.isHidden())

        # 启动
        overlay.start("TestProject", "正在解析配置…")
        self.assertFalse(overlay.isHidden())
        self.assertIn("TestProject", overlay._title_label.text())
        self.assertEqual(overlay._stage_label.text(), "正在解析配置…")

        # 更新阶段
        overlay.show_stage("正在构建索引…")
        self.assertEqual(overlay._stage_label.text(), "正在构建索引…")

        # 主题切换
        overlay.set_dark(True)
        self.assertTrue(overlay._dark)
        self.assertTrue(overlay._spinner._dark)

        # 父容器改变大小联动
        parent.resize(1024, 768)
        self.assertEqual(overlay.geometry().size(), parent.rect().size())

        # 结束
        finished_called = []
        overlay.finish(on_finished=lambda: finished_called.append(True))
        # 强制动画结束
        overlay._on_animation_finished()
        self.assertTrue(overlay.isHidden())
        self.assertTrue(finished_called)

    def test_remote_ref_head_filtered(self):
        import subprocess
        from pathlib import Path
        from doc_tool.application.content.vcs_changes import list_git_branches

        def mock_runner(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "symbolic-ref" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout=b"main\n", stderr=b"")
            elif "refs/heads" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout=b"main|*|origin/main|ahead 1\n", stderr=b"")
            elif "refs/remotes" in cmd_str:
                # 模拟 Git 输出 refs/remotes/origin/HEAD 与 refs/remotes/origin/main
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=b"refs/remotes/origin/HEAD|origin\nrefs/remotes/origin/main|origin/main\n", stderr=b""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

        branches, err = list_git_branches(Path("."), runner=mock_runner)
        self.assertIsNone(err)
        names = [b.name for b in branches]
        self.assertIn("main", names)
        self.assertIn("origin/main", names)
        # 确保 origin 伪分支已被成功过滤
        self.assertNotIn("origin", names)


if __name__ == "__main__":
    unittest.main()
