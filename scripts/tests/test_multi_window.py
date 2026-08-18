# -*- coding: utf-8 -*-
"""多窗口项目状态隔离自动测试（Qt offscreen）。

覆盖需求第八条核心场景：
- Window A 打开 Project A，Window B 打开 Project B：状态完全隔离
- A 修改 Markdown，B 不出现 dirty / Git 变化不串窗口
- 两个项目属于同一 Git Repository / 不同 Repository / 一个 Git 一个无版本控制
- 关闭 Window A 不影响 Window B；注册表不残留已关闭窗口
- 同一项目重复打开 → 激活已有窗口（不产生第二个可写窗口）
- draft / session / watcher / timer 等 per-window 资源隔离
"""

from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-tool/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

# 自包含：脱离 launcher 环境也能找到 .vendor 里的 PySide6
VENDOR = Path(REPO_ROOT) / ".vendor" / "site-packages"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtWidgets import QApplication  # noqa: E402

from doc_tool.application.content.vcs_changes import clear_vcs_cache  # noqa: E402
from doc_tool.application.project_service import open_project  # noqa: E402
from doc_tool.ui.window_registry import WindowRegistry  # noqa: E402

PROJECT_YML = (
    "schemaVersion: 1\n"
    "documentType: general\n"
    "documentNo: TEST-001\n"
    "documentName: {name}\n"
    "documentVersion: 1.0.0\n"
    "paths:\n"
    "  contentRoot: content\n"
    "  assetRoot: assets\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git"] + list(args), cwd=str(repo), capture_output=True, check=True
    )


def init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")


def make_project(root: Path, name: str, files: dict) -> Path:
    """在 root 下创建文档项目，返回项目根。"""
    project = root / name
    for rel, text in files.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (project / "project.yml").write_text(
        PROJECT_YML.format(name=name), encoding="utf-8"
    )
    return project


def commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def wait_index(ws, timeout: float = 15.0) -> bool:
    """轮询事件循环直到内容索引就绪（索引在后台线程构建）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if ws is not None and ws.is_index_ready():
            return True
        time.sleep(0.02)
    return bool(ws is not None and ws.is_index_ready())


class BaseWindowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        clear_vcs_cache()
        self._tmp = Path(tempfile.mkdtemp(prefix="doctool-mw-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.registry = WindowRegistry()

    def _factory(self):
        from doc_tool.ui.main_window import MainWindow

        def factory():
            window = MainWindow(
                window_registry=self.registry, window_factory=factory
            )
            self.registry.register(window)
            return window

        return factory


class WindowRegistryTests(BaseWindowCase):
    def test_register_unregister_and_count(self):
        factory = self._factory()
        w1 = factory()
        w2 = factory()
        self.assertEqual(self.registry.count(), 2)
        self.registry.unregister(w1)
        self.assertEqual(self.registry.count(), 1)
        self.registry.unregister(w2)
        self.assertEqual(self.registry.count(), 0)

    def test_strong_references_prevent_gc(self):
        factory = self._factory()
        w1 = factory()
        del w1
        gc.collect()
        # 注册表持有强引用：窗口不应被 GC 回收
        self.assertEqual(self.registry.count(), 1)
        self.assertIsNotNone(self.registry.primary())

    def test_window_for_project_resolve_normalization(self):
        project = self._tmp / "proj"
        (project / "content").mkdir(parents=True)
        (project / "content" / "a.md").write_text("a", encoding="utf-8")
        (project / "project.yml").write_text(
            PROJECT_YML.format(name="P"), encoding="utf-8"
        )
        factory = self._factory()
        w = factory()
        w.show_project(open_project(str(project)))
        QApplication.processEvents()
        # str/Path 与相对路径归一化后都能命中
        self.assertIs(self.registry.window_for_project(str(project)), w)
        self.assertIs(self.registry.window_for_project(project), w)
        # 未打开的项目 → None
        other = self._tmp / "not_open"
        self.assertIsNone(self.registry.window_for_project(other))

    def test_closed_window_removed_from_registry(self):
        project = self._tmp / "proj"
        (project / "content").mkdir(parents=True)
        (project / "content" / "a.md").write_text("a", encoding="utf-8")
        (project / "project.yml").write_text(
            PROJECT_YML.format(name="P"), encoding="utf-8"
        )
        factory = self._factory()
        w = factory()
        w.show_project(open_project(str(project)))
        QApplication.processEvents()
        self.assertIs(self.registry.window_for_project(project), w)
        w.close()
        QApplication.processEvents()
        self.assertEqual(self.registry.count(), 0)
        self.assertIsNone(self.registry.window_for_project(project))


class MultiWindowIsolationTests(BaseWindowCase):
    def _open_in_window(self, window, project_root: Path):
        window.show_project(open_project(str(project_root)))
        window.show()
        QApplication.processEvents()
        workspace = window._content_workspace
        self.assertTrue(
            wait_index(workspace), "内容索引未就绪：{0}".format(project_root)
        )
        return workspace

    def test_two_windows_two_projects_same_repo_fully_isolated(self):
        """同一 Git 仓库下两个项目：A 的改动不出现在 B（status/source/chapters）。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {
            "content/3.7.28 客户管理.md": "# 3.7.28 客户管理\nok",
        })
        pb = make_project(repo, "proj_b", {
            "content/4.7.28 设备管理.md": "# 4.7.28 设备管理\nok",
        })
        commit_all(repo, "init")

        factory = self._factory()
        wA = factory()
        wB = factory()
        wsA = self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)
        self.assertIsNot(wsA, wsB)

        # A 修改 Markdown + 新建未跟踪文件 + 修改 project.yml
        (pa / "content/3.7.28 客户管理.md").write_text(
            "# 3.7.28 客户管理\nchanged", encoding="utf-8"
        )
        (pa / "content/untracked.md").write_text("u", encoding="utf-8")
        (pa / "project.yml").write_text(
            PROJECT_YML.format(name="A改"), encoding="utf-8"
        )
        clear_vcs_cache()

        status_a = wsA._status_map()
        status_b = wsB._status_map()
        # A 看到自己的变化
        self.assertEqual(status_a["3.7.28 客户管理.md"], "modified")
        self.assertEqual(status_a["untracked.md"], "added")
        self.assertEqual(status_a["project.yml"], "modified")
        self.assertEqual(wsA.change_source(), "git")
        # B 完全不受影响
        self.assertEqual(status_b, {})
        self.assertEqual(wsB.change_source(), "git")
        # A 的 Git 变化不能出现在 B
        for rel in status_a:
            self.assertNotIn(rel, status_b)
        # 章节级输出只属于 A
        chapters_a = wsA.changed_chapters()
        self.assertEqual(
            [(c.chapter_id, c.title, c.change_type) for c in chapters_a
             if c.path != "project.yml"],
            [("3.7.28", "客户管理", "modified"), ("", "untracked", "added")],
        )
        self.assertEqual(wsB.changed_chapters(), [])

    def test_dirty_editor_state_does_not_cross_windows(self):
        """A 的编辑器脏状态不影响 B：B 没有 A 的文件标签，保存操作各写各的。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "# A\nok"})
        pb = make_project(repo, "proj_b", {"content/b.md": "# B\nok"})
        commit_all(repo, "init")
        factory = self._factory()
        wA = factory()
        wB = factory()
        wsA = self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)

        wsA.open_file("a.md")
        editor_a = wsA.tabs_host.editor_for("a.md")
        self.assertIsNotNone(editor_a)
        editor_a._editor.setPlainText("# A\nmodified in A")
        self.assertTrue(editor_a.is_dirty())

        # B 没有 A 的文件标签，也没有 dirty
        from doc_tool.application.content.unsaved import collect_unsaved

        self.assertIsNone(wsB.tabs_host.editor_for("a.md"))
        self.assertEqual(wsB.tabs_host.open_rel_paths(), [])
        self.assertEqual(collect_unsaved(wsB.tabs_host.editors()), [])

        # A 保存只写 A 的项目
        self.assertTrue(editor_a.save())
        self.assertEqual(
            (pa / "content/a.md").read_text(encoding="utf-8"), "# A\nmodified in A"
        )
        self.assertEqual(
            (pb / "content/b.md").read_text(encoding="utf-8"), "# B\nok"
        )

    def test_two_projects_in_different_repos(self):
        repo_a = self._tmp / "repo_a"
        repo_b = self._tmp / "repo_b"
        repo_a.mkdir()
        repo_b.mkdir()
        init_repo(repo_a)
        init_repo(repo_b)
        pa = make_project(repo_a, "proj_a", {"content/a.md": "a"})
        pb = make_project(repo_b, "proj_b", {"content/b.md": "b"})
        commit_all(repo_a, "init")
        commit_all(repo_b, "init")
        factory = self._factory()
        wA = factory()
        wB = factory()
        wsA = self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        (pb / "content/b.md").write_text("b2", encoding="utf-8")
        clear_vcs_cache()
        self.assertEqual(wsA._status_map(), {"a.md": "modified"})
        self.assertEqual(wsB._status_map(), {"b.md": "modified"})

    def test_git_project_and_no_vcs_project(self):
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        commit_all(repo, "init")
        # 无版本控制项目（独立目录，无 .git/.svn）
        pb = make_project(self._tmp, "proj_b", {"content/b.md": "b"})
        factory = self._factory()
        wA = factory()
        wB = factory()
        wsA = self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        (pb / "content/b.md").write_text("b2", encoding="utf-8")
        clear_vcs_cache()
        # A：Git 来源；B：本地快照兜底
        self.assertEqual(wsA._status_map(), {"a.md": "modified"})
        self.assertEqual(wsA.change_source(), "git")
        status_b = wsB._status_map()
        self.assertEqual(status_b, {"b.md": "modified"})
        self.assertEqual(wsB.change_source(), "local")

    def test_asset_change_marks_only_referencing_window(self):
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {
            "content/3.7.28 客户管理.md": (
                "# 3.7.28 客户管理\nok\n\n![x](../assets/images/a.png)\n"
            ),
        })
        pb = make_project(repo, "proj_b", {"content/b.md": "b"})
        commit_all(repo, "init")
        (pa / "assets/images").mkdir(parents=True, exist_ok=True)
        (pa / "assets/images/a.png").write_bytes(b"\x89PNG")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "asset")
        factory = self._factory()
        wA = factory()
        wB = factory()
        wsA = self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)
        (pa / "assets/images/a.png").write_bytes(b"\x89PNG2")
        clear_vcs_cache()
        status_a = wsA._status_map()
        # A：资源变化反查引用章节 → 章节标 modified
        self.assertEqual(status_a.get("3.7.28 客户管理.md"), "modified")
        # B：不受影响
        self.assertEqual(wsB._status_map(), {})

    def test_close_window_a_keeps_window_b_alive(self):
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        pb = make_project(repo, "proj_b", {"content/b.md": "b"})
        commit_all(repo, "init")
        factory = self._factory()
        wA = factory()
        wB = factory()
        self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)

        wA.close()
        QApplication.processEvents()
        self.assertEqual(self.registry.count(), 1)
        self.assertFalse(wA._closed is False)  # A 已标记关闭
        self.assertTrue(wB._closed is False)
        self.assertIsNotNone(wB._content_workspace)
        # B 仍可正常操作
        (pb / "content/b.md").write_text("b2", encoding="utf-8")
        clear_vcs_cache()
        self.assertEqual(wsB._status_map(), {"b.md": "modified"})
        wB.close()

    def test_duplicate_project_open_activates_existing_window(self):
        """同一项目重复打开：复用已有窗口，不产生第二个可写窗口。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        commit_all(repo, "init")
        factory = self._factory()
        wA = factory()
        wB = factory()
        self._open_in_window(wA, pa)
        before = self.registry.count()  # = 2（A + B）

        # 从 A 再次「在新窗口打开」同一项目 → 激活已有窗口，窗口数不变
        wA._open_project_in_new_window(str(pa))
        QApplication.processEvents()
        self.assertEqual(self.registry.count(), before)
        # 从另一个窗口 B 打开同一项目 → 激活 A，不新建
        wB._open_project_in_new_window(str(pa))
        QApplication.processEvents()
        self.assertEqual(self.registry.count(), before)
        self.assertIsNone(wB._project_summary)  # B 未加载任何项目

    def test_open_project_in_new_window_creates_window(self):
        """新项目在新窗口打开：注册表新增窗口并加载项目。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        commit_all(repo, "init")
        factory = self._factory()
        wA = factory()
        self._open_in_window(wA, pa)
        pb = make_project(repo, "proj_b", {"content/b.md": "b"})
        commit_all(repo, "init")

        wA._open_project_in_new_window(str(pb))
        QApplication.processEvents()
        self.assertEqual(self.registry.count(), 2)
        new_windows = [w for w in self.registry.windows() if w is not wA]
        self.assertEqual(len(new_windows), 1)
        self.assertIsNotNone(new_windows[0]._project_summary)
        self.assertEqual(
            new_windows[0]._project_summary.project_root.resolve(),
            pb.resolve(),
        )

    def test_session_drafts_autosave_stores_are_per_project(self):
        """draft/session/autosave 的 state_dir 按项目隔离。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "# A\nok"})
        pb = make_project(repo, "proj_b", {"content/b.md": "# B\nok"})
        commit_all(repo, "init")
        factory = self._factory()
        wA = factory()
        wB = factory()
        wsA = self._open_in_window(wA, pa)
        wsB = self._open_in_window(wB, pb)

        # A 写草稿
        wsA.tabs_host.open_file("a.md", "# A\nok")
        editor = wsA.tabs_host.editor_for("a.md")
        editor._editor.setPlainText("# A\n草稿内容")
        editor._write_draft()
        # B 不应读到 A 的草稿
        wsB.tabs_host.open_file("b.md", "# B\nok")
        self.assertIsNone(wsB._autosave.read("a.md"))
        self.assertIsNotNone(wsA._autosave.read("a.md"))
        # session store 路径不同
        self.assertNotEqual(
            str(wsA.session_store().file), str(wsB.session_store().file)
        )
        self.assertNotEqual(
            str(wsA._autosave.drafts_dir), str(wsB._autosave.drafts_dir)
        )
        # 保存全部只影响各自项目
        self.assertEqual(wsB.tabs_host.save_all(), [])
        self.assertEqual(
            (pb / "content/b.md").read_text(encoding="utf-8"), "# B\nok"
        )


class WorkspaceStateIsolationTests(BaseWindowCase):
    """两个 ContentWorkspace 实例（模拟两个窗口）的状态完全隔离。"""

    def _workspace(self, project_root: Path):
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            project_root / "content",
            project_root=project_root,
            state_dir=project_root / ".state",
        )
        self.assertTrue(wait_index(ws))
        return ws

    def test_workspaces_do_not_share_index_or_status(self):
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        pb = make_project(repo, "proj_b", {"content/b.md": "b"})
        commit_all(repo, "init")
        wsA = self._workspace(pa)
        wsB = self._workspace(pb)
        self.assertIsNot(wsA._index, wsB._index)
        self.assertIsNot(wsA._writer, wsB._writer)
        self.assertIsNot(wsA._snapshot, wsB._snapshot)
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        clear_vcs_cache()
        self.assertEqual(wsA._status_map(), {"a.md": "modified"})
        self.assertEqual(wsB._status_map(), {})

    def test_shutdown_of_one_workspace_does_not_affect_other(self):
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        pb = make_project(repo, "proj_b", {"content/b.md": "b"})
        commit_all(repo, "init")
        wsA = self._workspace(pa)
        wsB = self._workspace(pb)
        wsA.shutdown()  # 关闭 A 释放自己的 watcher/timer/task
        QApplication.processEvents()
        (pb / "content/b.md").write_text("b2", encoding="utf-8")
        clear_vcs_cache()
        # B 继续正常工作
        self.assertEqual(wsB._status_map(), {"b.md": "modified"})
        wsB.shutdown()


class VcsBackupPolicyTests(BaseWindowCase):
    """VCS 管理的项目不再生成 .md.bak；本地项目保持原行为。"""

    def test_git_project_write_creates_no_bak(self):
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "v1"})
        commit_all(repo, "init")
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            pa / "content", project_root=pa, state_dir=pa / ".state"
        )
        self.assertTrue(wait_index(ws))
        self.assertTrue(ws._vcs_managed)
        self.assertFalse(ws._writer._backup_enabled)
        result = ws._writer.write_text("a.md", "v2")
        self.assertTrue(result.written)
        self.assertIsNone(result.backup_path)
        self.assertEqual(
            list((pa / "content").rglob("*.bak")), [],
            "git 管理项目不应生成 .md.bak",
        )
        ws.shutdown()

    def test_local_project_write_still_creates_bak(self):
        pb = make_project(self._tmp, "proj_b", {"content/b.md": "v1"})
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            pb / "content", project_root=pb, state_dir=pb / ".state"
        )
        self.assertTrue(wait_index(ws))
        self.assertFalse(ws._vcs_managed)
        self.assertTrue(ws._writer._backup_enabled)
        result = ws._writer.write_text("b.md", "v2")
        self.assertTrue(result.written)
        self.assertIsNotNone(result.backup_path)
        self.assertTrue((pb / "content/b.md.bak").exists())
        ws.shutdown()

    def test_rollback_all_restores_via_git_and_preserves_user_files(self):
        """改动面板「回滚全部」在 git 项目：恢复被跟踪文件，删除本会话
        创建的文件，保留用户手动新建的未跟踪文件并提示。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "v1"})
        commit_all(repo, "init")
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            pa / "content", project_root=pa, state_dir=pa / ".state"
        )
        self.assertTrue(wait_index(ws))
        # 被跟踪文件被工具改写（无 .bak）
        ws._writer.write_text("a.md", "v2")
        # 本会话工具新建文件（清单 OP_CREATE）
        ws._writer.create_file("tool_new.md", "t")
        # 用户手动新建的未跟踪文件（不在清单中）
        (pa / "content/user_new.md").write_text("u", encoding="utf-8")
        clear_vcs_cache()

        failures = ws._rollback_all_changes()
        # 用户文件被保留并提示；其余全部恢复
        self.assertEqual(len(failures), 1)
        self.assertIn("user_new.md", failures[0])
        self.assertIn("已保留", failures[0])
        self.assertEqual(
            (pa / "content/a.md").read_text(encoding="utf-8"), "v1"
        )
        self.assertFalse((pa / "content/tool_new.md").exists())
        self.assertTrue((pa / "content/user_new.md").exists())
        # 会话改动清单已清空
        ws._writer.manifest.load()
        self.assertTrue(ws._writer.manifest.empty)
        ws.shutdown()

    def test_local_rollback_all_uses_manifest(self):
        """本地（无 VCS）项目「回滚全部」仍走 .bak 清单恢复。"""
        pb = make_project(self._tmp, "proj_b", {"content/b.md": "v1"})
        from doc_tool.ui.content.workspace import ContentWorkspace

        ws = ContentWorkspace(
            pb / "content", project_root=pb, state_dir=pb / ".state"
        )
        self.assertTrue(wait_index(ws))
        ws._writer.write_text("b.md", "v2")
        clear_vcs_cache()
        failures = ws._rollback_all_changes()
        self.assertEqual(failures, [])
        self.assertEqual(
            (pb / "content/b.md").read_text(encoding="utf-8"), "v1"
        )
        ws.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
