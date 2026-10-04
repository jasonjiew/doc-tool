# -*- coding: utf-8 -*-
"""V3.7 2.4：跨成员打开/激活/返回与缺成员重定位（真实项目身份 projectId/relPath）。"""

from __future__ import annotations

import os
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

from scripts.tests import core_fixtures as fixtures  # noqa: E402


def _norm_path(path) -> str:
    """路径比较前的归一化。

    CI 的临时目录是 8.3 短名（RUNNER~1），与夹具产出的长名指向同一目录，
    两边都必须归一化后再比较，否则同一路径会被判成不同。
    """
    return os.path.realpath(str(path))


class _Host:
    """最小宿主：记录真实打开的成员根路径顺序。"""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.opened: list = []
        self.statuses: list = []
        self.projects: dict = {}

    def ws_state_dir(self):
        return self.work / ".state"

    def rd_open_project(self, root):
        self.opened.append(str(root))
        return True

    def rd_status(self, message):
        self.statuses.append(str(message))

    def rd_project_writable(self, root):
        return True

    def rd_project_summary(self, root):
        return self.projects.get(str(root), {})


class CrossMemberNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v37-24-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        # 工作区根目录；成员路径必须是**工作区内相对路径**（越界/绝对路径会被拒）
        self.workspace_root = self.work / "工作区"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.members = {}
        for name in ("Alpha", "Beta", "Gamma"):
            self.members[name] = fixtures.two_chapter_project(self.workspace_root / name)
        self.host = _Host(self.work)
        self.workspace_path = self.workspace_root / "workspace.yml"
        self._write_workspace()

    def _write_workspace(self):
        import yaml

        payload = {
            "schemaVersion": 1,
            "workspaceId": "ws-37-24",
            "name": "三成员工作区",
            "documents": [
                {"path": name, "role": "requirement", "projectId": "pid-{0}".format(name)}
                for name in self.members
            ],
        }
        self.workspace_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )

    def _dialog(self):
        from doc_tool.ui.rd_workspace import RdWorkspaceDialog

        dialog = RdWorkspaceDialog(self.host, root=str(self.workspace_root))

        def _dispose():
            # 同进程内后续测试会再次操作全局 QApplication：必须显式释放本对话框
            # 及其派生的 Qt 对象，否则 setStyleSheet 会命中已销毁对象（访问冲突）。
            try:
                dialog.close()
                dialog.deleteLater()
                dialog._workspace = None
                dialog._index = None
                dialog._graph = None
                dialog._members = []
                dialog._member_documents = []
                QApplication.processEvents()
            except RuntimeError:
                pass

        self.addCleanup(_dispose)
        self.addCleanup(dialog.close)
        dialog.show()
        QApplication.processEvents()
        return dialog

    def test_open_activate_return_keeps_other_members(self):
        dialog = self._dialog()
        self.assertTrue(dialog._members, "工作区应读出真实成员")
        names = [item["name"] for item in dialog._members]
        self.assertEqual(sorted(names), ["Alpha", "Beta", "Gamma"])

        # 依次打开每个成员（真实按钮路径）
        for index, name in enumerate(names):
            dialog.member_table.setCurrentCell(index, 0)
            QApplication.processEvents()
            dialog.open_member_btn.click()
            QApplication.processEvents()
        self.assertEqual(len(self.host.opened), len(names), self.host.statuses)
        for name in names:
            self.assertIn(
                _norm_path(self.members[name]),
                [_norm_path(item) for item in self.host.opened],
                "每个成员必须按真实路径打开",
            )

        # 身份用真实 projectId / relPath，不用显示名代替
        for item in dialog._members:
            self.assertTrue(item.get("projectId") or item.get("identity"),
                            "成员必须有真实身份：{0}".format(item))
        # 打开是「激活」而非「搬走」：成员列表保持完整
        self.assertEqual(len(dialog._members), 3, "打开成员不得移除其他成员")

    def test_missing_member_reports_and_others_stay_usable(self):
        import yaml

        payload = yaml.safe_load(self.workspace_path.read_text(encoding="utf-8"))
        # 缺成员：把 Beta 指向工作区内一个不存在的相对目录（越界/绝对路径会被拒）
        payload["documents"][1]["path"] = "不存在的成员"
        self.workspace_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        dialog = self._dialog()
        rows = {item.get("path", ""): item for item in dialog._members}
        self.assertIn("不存在的成员", rows, "缺成员必须仍出现在成员列表：{0}".format(list(rows)))
        missing = rows["不存在的成员"]
        self.assertFalse(missing.get("available", True), "缺成员必须标不可用")
        missing_index = [item.get("path", "") for item in dialog._members].index("不存在的成员")
        dialog.member_table.setCurrentCell(missing_index, 0)
        QApplication.processEvents()
        dialog.open_member_btn.click()
        QApplication.processEvents()
        self.assertNotIn(
            _norm_path(self.workspace_root / "不存在的成员"),
            [_norm_path(item) for item in self.host.opened],
            "不可用成员不得被打开",
        )
        self.assertTrue(
            any("不可用" in item or "不存在" in item for item in
                list(self.host.statuses) + [dialog._status_label.text()]),
            "必须给出可读原因：{0}".format(list(self.host.statuses) + [dialog._status_label.text()]),
        )

        # 其他成员仍可打开
        alpha_index = [item.get("path", "") for item in dialog._members].index("Alpha")
        dialog.member_table.setCurrentCell(alpha_index, 0)
        QApplication.processEvents()
        dialog.open_member_btn.click()
        QApplication.processEvents()
        self.assertIn(
            _norm_path(self.members["Alpha"]),
            [_norm_path(item) for item in self.host.opened],
            "合法成员必须继续可用",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)