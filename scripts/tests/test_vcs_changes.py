# -*- coding: utf-8 -*-
"""版本控制变更检测自动测试（纯应用层，无 Qt 依赖）。

覆盖：
- Git：仓库根查找、modified/added/deleted/renamed、staged/unstaged/untracked
- 同一 Git 仓库下多文档项目隔离（含共享缓存的窗口 A/B 场景）
- 中文、空格 Windows 路径
- SVN：M/A/D/R/? 识别（注入假 svn 输出，环境无需安装 svn）
- 无版本控制 → local 兜底
- Git 命令不可用/执行异常 → 回退
- 章节级映射（ChangedChapter）与资源反查引用章节
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# scripts/tests/ -> scripts/ -> doc-tool/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from doc_tool.application.content.vcs_changes import (  # noqa: E402
    ChangeDetectionService,
    ChangedFile,
    ChangeReport,
    GitBranch,
    GitChangeDetector,
    PushResult,
    SvnChangeDetector,
    clear_vcs_cache,
    commit_all as vcs_commit_all,
    commit_files as vcs_commit_files,
    find_git_repo_root,
    find_svn_wc_root,
    git_stash_pop,
    git_stash_save,
    list_git_branches,
    parse_git_name_status_z,
    parse_git_status_z,
    parse_svn_status_xml,
    pull_changes as vcs_pull_changes,
    push_changes as vcs_push_changes,
    rollback_all,
    rollback_single_file,
    switch_git_branch,
)

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


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        capture_output=True,
        check=True,
    )


def init_repo(repo: Path) -> None:
    """初始化 git 仓库并配置用户。"""
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "t@t.t")
    _run_git(repo, "config", "user.name", "t")


def make_project(repo: Path, name: str, files: dict) -> Path:
    """在 repo 下创建文档项目（project.yml + content/…），返回项目根。"""
    root = repo / name
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "project.yml").write_text(
        PROJECT_YML.format(name=name), encoding="utf-8"
    )
    return root


def commit_all(repo: Path, message: str) -> None:
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-qm", message)


class RepoFixtureMixin:
    """临时 git 仓库夹具。"""

    def setUp(self) -> None:
        clear_vcs_cache()
        self._tmp = Path(tempfile.mkdtemp(prefix="doctool-vcs-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.repo = self._tmp / "repo"
        self.repo.mkdir()
        init_repo(self.repo)

    def service(self, project_root: Path) -> ChangeDetectionService:
        content_root = project_root / "content"
        return ChangeDetectionService(project_root, content_root)


class GitRepoRootTests(unittest.TestCase):
    def test_find_git_repo_root_walks_up_parents(self):
        with tempfile.TemporaryDirectory(prefix="doctool-root-") as tmp:
            repo = Path(tmp) / "repo"
            (repo / ".git").mkdir(parents=True)
            deep = repo / "a" / "b" / "c"
            deep.mkdir(parents=True)
            self.assertEqual(
                os.path.realpath(find_git_repo_root(deep)),
                os.path.realpath(repo),
            )
            outside = Path(tmp) / "elsewhere"
            outside.mkdir()
            self.assertIsNone(find_git_repo_root(outside))

    def test_find_svn_wc_root_walks_up_parents(self):
        with tempfile.TemporaryDirectory(prefix="doctool-root-") as tmp:
            wc = Path(tmp) / "wc"
            (wc / ".svn").mkdir(parents=True)
            deep = wc / "x" / "y"
            deep.mkdir(parents=True)
            self.assertEqual(
                os.path.realpath(find_svn_wc_root(deep)),
                os.path.realpath(wc),
            )
            outside = Path(tmp) / "no"
            outside.mkdir()
            self.assertIsNone(find_svn_wc_root(outside))


class GitDetectionTests(RepoFixtureMixin, unittest.TestCase):
    def test_detects_modified_added_and_deleted(self):
        pa = make_project(self.repo, "proj_a", {
            "content/3.7.28 客户管理.md": "# 3.7.28 客户管理\nok",
            "content/3.7.29 客户授权.md": "# 3.7.29 客户授权\nok",
            "content/3.7.30 已删除.md": "# 3.7.30 已删除\nok",
        })
        commit_all(self.repo, "init")
        (pa / "content/3.7.28 客户管理.md").write_text(
            "# 3.7.28 客户管理\nchanged", encoding="utf-8"
        )
        (pa / "content/3.7.31 新增.md").write_text(
            "# 3.7.31 新增\nnew", encoding="utf-8"
        )
        (pa / "content/3.7.30 已删除.md").unlink()

        report = self.service(pa).detect()
        self.assertEqual(report.source, "git")
        by_path = {f.path: f for f in report.files}
        self.assertEqual(
            by_path["proj_a/content/3.7.28 客户管理.md"].change_type, "modified"
        )
        self.assertEqual(
            by_path["proj_a/content/3.7.31 新增.md"].change_type, "added"
        )
        self.assertTrue(by_path["proj_a/content/3.7.31 新增.md"].untracked)
        self.assertEqual(
            by_path["proj_a/content/3.7.30 已删除.md"].change_type, "deleted"
        )

    def test_staged_and_unstaged_flags(self):
        pa = make_project(self.repo, "proj_a", {
            "content/a.md": "a",
            "content/b.md": "b",
        })
        commit_all(self.repo, "init")
        # a.md: staged + unstaged（先改再 add 再改）
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        _run_git(self.repo, "add", "proj_a/content/a.md")
        (pa / "content/a.md").write_text("a3", encoding="utf-8")
        # b.md: 仅 unstaged
        (pa / "content/b.md").write_text("b2", encoding="utf-8")

        report = self.service(pa).detect()
        by_path = {f.path: f for f in report.files}
        a = by_path["proj_a/content/a.md"]
        self.assertTrue(a.staged)
        self.assertTrue(a.unstaged)
        b = by_path["proj_a/content/b.md"]
        self.assertFalse(b.staged)
        self.assertTrue(b.unstaged)

    def test_rename_detected_with_old_path(self):
        pa = make_project(self.repo, "proj_a", {
            "content/3.7.28 客户管理.md": "# 3.7.28 客户管理\n同一内容保留\n",
        })
        commit_all(self.repo, "init")
        _run_git(
            self.repo,
            "mv",
            "proj_a/content/3.7.28 客户管理.md",
            "proj_a/content/3.7.28 客户管理v2.md",
        )
        report = self.service(pa).detect()
        files = [f for f in report.files if f.change_type == "renamed"]
        self.assertEqual(len(files), 1)
        self.assertEqual(
            files[0].old_path, "proj_a/content/3.7.28 客户管理.md"
        )
        self.assertEqual(
            files[0].path, "proj_a/content/3.7.28 客户管理v2.md"
        )

    def test_two_projects_one_repo_are_isolated_even_with_warm_cache(self):
        """窗口 A/B 打开同一仓库下两个项目：A 的 Git 变化绝不能出现在 B。

        缓存以 repository_root 为 key 且存未过滤原始变更；每个窗口按自己的
        project_root 过滤。先 A 后 B（B 命中 A 写入的缓存）是关键场景。
        """
        pa = make_project(self.repo, "proj_a", {
            "content/3.7.28 客户管理.md": "# 3.7.28 客户管理\nok",
        })
        pb = make_project(self.repo, "proj_b", {
            "content/4.7.28 设备管理.md": "# 4.7.28 设备管理\nok",
        })
        commit_all(self.repo, "init")
        # A 的项目变化
        (pa / "content/3.7.28 客户管理.md").write_text(
            "# 3.7.28 客户管理\nchanged", encoding="utf-8"
        )
        (pa / "content/untracked.md").write_text("u", encoding="utf-8")
        # B 的项目变化
        (pb / "content/4.7.29 新增.md").write_text(
            "# 4.7.29 新增\nnew", encoding="utf-8"
        )

        sa = self.service(pa)
        ra = sa.detect()
        self.assertEqual(ra.source, "git")
        a_paths = {f.path for f in ra.files}
        self.assertTrue(a_paths)
        self.assertTrue(
            all(p.startswith("proj_a/") for p in a_paths),
            "A 只能看到自己的变化：{0}".format(sorted(a_paths)),
        )
        # B 命中 A 写入的仓库级缓存，仍必须只看到 proj_b 的变化。
        sb = self.service(pb)
        rb = sb.detect()
        b_paths = {f.path for f in rb.files}
        self.assertTrue(b_paths)
        self.assertTrue(
            all(p.startswith("proj_b/") for p in b_paths),
            "B 绝不能看到 A 的变化：{0}".format(sorted(b_paths)),
        )
        # A 再次检测（缓存共享）仍只看到自己的变化。
        ra2 = sa.detect()
        self.assertEqual(
            {f.path for f in ra2.files}, a_paths, "A 的过滤不能被 B 污染"
        )

    def test_two_projects_in_different_repos(self):
        repo_b = self._tmp / "repo_b"
        repo_b.mkdir()
        init_repo(repo_b)
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a"})
        pb = make_project(repo_b, "proj_b", {"content/b.md": "b"})
        commit_all(self.repo, "init")
        commit_all(repo_b, "init")
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        (pb / "content/b.md").write_text("b2", encoding="utf-8")

        ra = self.service(pa).detect()
        rb = ChangeDetectionService(pb, pb / "content").detect()
        self.assertEqual(
            [f.path for f in ra.files], ["proj_a/content/a.md"]
        )
        self.assertEqual(
            [f.path for f in rb.files], ["proj_b/content/b.md"]
        )

    def test_chinese_and_space_paths(self):
        pa = make_project(self.repo, "需求 说明书 FIXTURE-001", {
            "content/第3章 功能/3.7.28 客户管理.md": "# 3.7.28 客户管理\nok",
        })
        commit_all(self.repo, "init")
        (pa / "content/第3章 功能/3.7.28 客户管理.md").write_text(
            "# 3.7.28 客户管理\n改动", encoding="utf-8"
        )
        report = self.service(pa).detect()
        self.assertEqual(report.source, "git")
        self.assertEqual(len(report.files), 1)
        self.assertIn("3.7.28 客户管理.md", report.files[0].path)

    def test_project_at_repo_root(self):
        pa = make_project(self.repo, ".", {"content/a.md": "a"})
        commit_all(self.repo, "init")
        (self.repo / "content/a.md").write_text("a2", encoding="utf-8")
        report = self.service(pa).detect()
        self.assertEqual(report.source, "git")
        self.assertEqual([f.path for f in report.files], ["content/a.md"])

    def test_no_commit_repo_untracked_only(self):
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a"})
        # 无提交：所有文件 untracked
        report = self.service(pa).detect()
        self.assertEqual(report.source, "git")
        self.assertEqual(len(report.files), 2)  # content/a.md + project.yml
        self.assertTrue(all(f.untracked for f in report.files))

    def test_git_unavailable_falls_back_to_local(self):
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a"})
        commit_all(self.repo, "init")
        detector = GitChangeDetector(git_executable="definitely-not-a-git-bin")
        report = detector.detect(pa)
        self.assertEqual(report.source, "local")
        self.assertIsNotNone(report.error)

    def test_git_command_failure_falls_back_to_local(self):
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a"})
        commit_all(self.repo, "init")

        def bad_runner(args, cwd):
            return subprocess.CompletedProcess(
                args, returncode=128, stdout=b"", stderr=b"fatal: corrupt"
            )

        service = ChangeDetectionService(
            pa, pa / "content", git_runner=bad_runner
        )
        report = service.detect()
        self.assertEqual(report.source, "local")
        self.assertIn("git", report.error or "")

    def test_status_map_maps_to_content_and_project_yml(self):
        pa = make_project(self.repo, "proj_a", {
            "content/3.7.28 客户管理.md": "# 3.7.28 客户管理\nok",
        })
        commit_all(self.repo, "init")
        (pa / "content/3.7.28 客户管理.md").write_text(
            "# 3.7.28 客户管理\nchanged", encoding="utf-8"
        )
        (pa / "project.yml").write_text(
            PROJECT_YML.format(name="改名"), encoding="utf-8"
        )
        service = self.service(pa)
        report = service.detect()
        status = service.status_map(report)
        self.assertEqual(status["3.7.28 客户管理.md"], "modified")
        self.assertEqual(status["project.yml"], "modified")

    def test_chapters_mapping_and_asset_reference(self):
        pa = make_project(self.repo, "proj_a", {
            "content/3.7.28 客户管理.md": (
                "# 3.7.28 客户管理\nok\n\n![截图](../assets/images/a.png)\n"
            ),
        })
        commit_all(self.repo, "init")
        (pa / "content/3.7.28 客户管理.md").write_text(
            "# 3.7.28 客户管理\nok\n\n![截图](../assets/images/a.png)\n改\n",
            encoding="utf-8",
        )
        service = self.service(pa)
        report = service.detect()
        chapters = service.chapters(report, ["3.7.28 客户管理.md"])
        by_path = {c.path: c for c in chapters}
        chapter = by_path["3.7.28 客户管理.md"]
        self.assertEqual(chapter.chapter_id, "3.7.28")
        self.assertEqual(chapter.title, "客户管理")
        self.assertEqual(chapter.change_type, "modified")
        self.assertEqual(chapter.source, "git")

        # 资源变化 → 反查引用它的章节
        (pa / "assets/images").mkdir(parents=True, exist_ok=True)
        (pa / "assets/images/a.png").write_bytes(b"\x89PNG")
        _run_git(self.repo, "add", "-A")
        _run_git(self.repo, "commit", "-qm", "asset")
        (pa / "assets/images/a.png").write_bytes(b"\x89PNG2")
        clear_vcs_cache()
        report2 = service.detect()
        chapters2 = service.chapters(report2, ["3.7.28 客户管理.md"])
        asset_hits = [c for c in chapters2 if c.is_asset]
        self.assertEqual(
            [(c.chapter_id, c.path) for c in asset_hits],
            [("3.7.28", "3.7.28 客户管理.md")],
        )

    def test_asset_change_marks_chapter_modified_not_added(self):
        """新增/删除被引用的资源：章节标 modified，绝不继承 added/deleted。

        继承会让一个真实存在、未被改动的章节在改动面板显示为「新增」，
        而「撤销新增」会把它删掉（数据丢失）。
        """
        pa = make_project(self.repo, "proj_a", {
            "content/3.7.28 客户管理.md": (
                "# 3.7.28 客户管理\nok\n\n"
                "![新图](../assets/images/new.png)\n"
                "![旧图](../assets/images/old.png)\n"
            ),
        })
        (pa / "assets/images").mkdir(parents=True, exist_ok=True)
        (pa / "assets/images/old.png").write_bytes(b"\x89PNGold")
        commit_all(self.repo, "init")
        # 章节自身未改：只新增一张它引用的图片 + 删除另一张
        (pa / "assets/images/new.png").write_bytes(b"\x89PNGnew")
        (pa / "assets/images/old.png").unlink()

        service = self.service(pa)
        report = service.detect()
        all_files = ["3.7.28 客户管理.md"]
        status = service.status_map(report, all_files)
        self.assertEqual(status["3.7.28 客户管理.md"], "modified")
        chapters = service.chapters(report, all_files)
        self.assertEqual(len(chapters), 1)
        self.assertTrue(chapters[0].is_asset)
        self.assertEqual(chapters[0].change_type, "modified")
        self.assertIsNone(chapters[0].old_path)

    def test_chapter_own_status_wins_over_asset_reverse_lookup(self):
        """章节自身的真实状态优先于资源反查（不被反查结果覆盖或抹平）。"""
        pa = make_project(self.repo, "proj_a", {"content/keep.md": "keep"})
        commit_all(self.repo, "init")
        # 章节本身是新增的，并且引用了一张同样新增的图片
        (pa / "content/3.7.31 新增.md").write_text(
            "# 3.7.31 新增\n![图](../assets/images/new.png)\n", encoding="utf-8"
        )
        (pa / "assets/images").mkdir(parents=True, exist_ok=True)
        (pa / "assets/images/new.png").write_bytes(b"\x89PNGnew")

        service = self.service(pa)
        report = service.detect()
        all_files = ["keep.md", "3.7.31 新增.md"]
        status = service.status_map(report, all_files)
        self.assertEqual(status["3.7.31 新增.md"], "added")
        # 章节只出现一次（自身条目），不再追加资源反查的重复条目
        paths = [c.path for c in service.chapters(report, all_files)]
        self.assertEqual(paths.count("3.7.31 新增.md"), 1)

    def test_content_root_asset_also_maps_to_chapter(self):
        """content_root 内的资源（如 general/images/x.png）同样反查引用章节。"""
        pa = make_project(self.repo, "proj_a", {
            "content/general/1.1 概述.md": (
                "# 1.1 概述\n![图](images/shot.png)\n"
            ),
        })
        commit_all(self.repo, "init")
        (pa / "content/general/images").mkdir(parents=True, exist_ok=True)
        (pa / "content/general/images/shot.png").write_bytes(b"\x89PNG")

        service = self.service(pa)
        report = service.detect()
        status = service.status_map(report, ["general/1.1 概述.md"])
        # 资源自身仍以 added 出现（可在面板撤销新增），章节标 modified
        self.assertEqual(status["general/images/shot.png"], "added")
        self.assertEqual(status["general/1.1 概述.md"], "modified")

    def test_gitignored_project_falls_back_to_local(self):
        """项目被 .gitignore 忽略：git 永远沉默 → 必须回退本地快照。"""
        (self.repo / ".gitignore").write_text("proj_ig/\n", encoding="utf-8")
        pig = make_project(self.repo, "proj_ig", {"content/a.md": "a"})
        commit_all(self.repo, "init")
        (pig / "content/a.md").write_text("changed", encoding="utf-8")
        (pig / "content/new.md").write_text("new", encoding="utf-8")

        report = self.service(pig).detect()
        self.assertEqual(report.source, "local")
        self.assertIn("Git", report.error or "")
        # 低层检测器（不带缓存）行为一致
        self.assertEqual(GitChangeDetector().detect(pig).source, "local")

    def test_clean_tracked_project_stays_git(self):
        """已跟踪但无改动的项目仍是 git 模式（不能被未跟踪兜底误判）。"""
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a"})
        commit_all(self.repo, "init")
        report = self.service(pa).detect()
        self.assertEqual(report.source, "git")
        self.assertEqual(report.files, ())

    def test_cache_invalidation_after_write(self):
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a"})
        commit_all(self.repo, "init")
        service = self.service(pa)
        report = service.detect()
        self.assertEqual(len(report.files), 0)
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        # 不清缓存直接 detect：TTL 内命中旧缓存 → 仍为 0（写后必须 invalidate）
        self.assertEqual(len(service.detect().files), 0)
        service.invalidate_cache()
        report = service.detect()
        self.assertEqual(len(report.files), 1)
        self.assertEqual(report.files[0].change_type, "modified")


class GitParserTests(unittest.TestCase):
    def test_parse_git_status_z_rename_new_first(self):
        output = (
            "D  proj_a/a.md\0"
            "R  proj_a/renamed.md\0proj_a/a.md\0"
            "?? proj_a/untracked.md\0"
            " M proj_a/modified.md\0"
        ).encode("utf-8")
        parsed = parse_git_status_z(output)
        self.assertEqual(parsed["proj_a/a.md"], ("D", " ", None))
        self.assertEqual(
            parsed["proj_a/renamed.md"], ("R", " ", "proj_a/a.md")
        )
        self.assertEqual(
            parsed["proj_a/untracked.md"], ("?", "?", None)
        )
        self.assertEqual(
            parsed["proj_a/modified.md"], (" ", "M", None)
        )

    def test_parse_git_name_status_z_rename(self):
        output = (
            "M\0proj_a/a.md\0"
            "R100\0proj_a/old.md\0proj_a/new.md\0"
            "A\0proj_a/added.md\0"
        ).encode("utf-8")
        parsed = parse_git_name_status_z(output)
        self.assertEqual(parsed["proj_a/a.md"], ("modified", None))
        self.assertEqual(
            parsed["proj_a/new.md"], ("renamed", "proj_a/old.md")
        )
        self.assertEqual(parsed["proj_a/added.md"], ("added", None))


class SvnDetectionTests(unittest.TestCase):
    """注入假 svn 输出，无需安装 svn。"""

    def setUp(self) -> None:
        clear_vcs_cache()
        self._tmp = Path(tempfile.mkdtemp(prefix="doctool-svn-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.wc = self._tmp / "wc"
        (self.wc / ".svn").mkdir(parents=True)
        self.project_a = self.wc / "proj_a"
        self.project_b = self.wc / "proj_b"
        (self.project_a / "content").mkdir(parents=True)
        (self.project_b / "content").mkdir(parents=True)
        (self.project_a / "project.yml").write_text(
            PROJECT_YML.format(name="A"), encoding="utf-8"
        )
        (self.project_b / "project.yml").write_text(
            PROJECT_YML.format(name="B"), encoding="utf-8"
        )

    def _svn_xml(self, entries: list) -> bytes:
        q = '"'
        body = "".join(
            "<entry path={0}{1}{0}><wc-status item={0}{2}{0} props={0}none{0}{3}/></entry>".format(
                q,
                path,
                item,
                ' copied=' + q + 'true' + q if copied else '',
            )
            for path, item, copied in ((e[0], e[1], len(e) > 2 and e[2]) for e in entries)
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<status><target path=" + q + "." + q + ">" + body + "</target></status>"
        )
        return xml.encode("utf-8")

    def _runner_for(self, entries_by_wc: dict):
        # cwd 可能以 Windows 短路径（8.3）形式传入，与构造夹具时的长路径
        # 字符串不同；按 realpath 归一化后再查表，避免误判为无变更。
        normalized = {
            os.path.realpath(str(key)): value
            for key, value in entries_by_wc.items()
        }

        def runner(args, cwd):
            xml = normalized.get(
                os.path.realpath(str(cwd)), self._svn_xml([])
            )
            return subprocess.CompletedProcess(
                args, returncode=0, stdout=xml, stderr=b""
            )
        return runner

    def test_svn_detects_m_a_d_replaced_and_untracked(self):
        runner = self._runner_for({
            str(self.wc): self._svn_xml([
                ("proj_a/content/3.7.28 客户管理.md", "modified"),
                ("proj_a/content/new.md", "unversioned"),
                ("proj_a/content/old.md", "deleted"),
                ("proj_a/content/replaced.md", "replaced"),
                ("proj_a/content/copied.md", "added", True),
            ]),
        })
        service = ChangeDetectionService(
            self.project_a, self.project_a / "content", svn_runner=runner
        )
        report = service.detect()
        self.assertEqual(report.source, "svn")
        by_path = {f.path: f for f in report.files}
        self.assertEqual(
            by_path["proj_a/content/3.7.28 客户管理.md"].change_type, "modified"
        )
        self.assertEqual(
            by_path["proj_a/content/new.md"].change_type, "added"
        )
        self.assertTrue(by_path["proj_a/content/new.md"].untracked)
        self.assertEqual(
            by_path["proj_a/content/old.md"].change_type, "deleted"
        )
        self.assertEqual(
            by_path["proj_a/content/replaced.md"].change_type, "renamed"
        )
        self.assertEqual(
            by_path["proj_a/content/copied.md"].change_type, "renamed"
        )

    def test_svn_two_projects_isolated(self):
        runner = self._runner_for({
            str(self.wc): self._svn_xml([
                ("proj_a/content/a.md", "modified"),
                ("proj_b/content/b.md", "modified"),
            ]),
        })
        sa = ChangeDetectionService(
            self.project_a, self.project_a / "content", svn_runner=runner
        )
        sb = ChangeDetectionService(
            self.project_b, self.project_b / "content", svn_runner=runner
        )
        ra = sa.detect()  # 先 A：写入缓存
        rb = sb.detect()  # B 命中缓存
        self.assertEqual(
            [f.path for f in ra.files], ["proj_a/content/a.md"]
        )
        self.assertEqual(
            [f.path for f in rb.files], ["proj_b/content/b.md"]
        )

    def test_svn_status_map(self):
        runner = self._runner_for({
            str(self.wc): self._svn_xml([
                ("proj_a/content/3.7.28 客户管理.md", "modified"),
                ("proj_a/project.yml", "modified"),
            ]),
        })
        service = ChangeDetectionService(
            self.project_a, self.project_a / "content", svn_runner=runner
        )
        report = service.detect()
        status = service.status_map(report)
        self.assertEqual(status["3.7.28 客户管理.md"], "modified")
        self.assertEqual(status["project.yml"], "modified")

    def test_svn_missing_returns_local(self):
        service = ChangeDetectionService(
            self.project_a, self.project_a / "content"
        )
        report = service.detect()
        self.assertEqual(report.source, "local")

    def test_svn_command_failure_returns_local(self):
        def bad_runner(args, cwd):
            return subprocess.CompletedProcess(
                args, returncode=1, stdout=b"", stderr=b"svn: E155007"
            )
        service = ChangeDetectionService(
            self.project_a, self.project_a / "content", svn_runner=bad_runner
        )
        report = service.detect()
        self.assertEqual(report.source, "local")
        self.assertIn("svn", report.error or "")

    def test_parse_svn_status_xml_items(self):
        parsed = parse_svn_status_xml(
            self._svn_xml([
                ("a.md", "modified"),
                ("b.md", "unversioned"),
                ("c.md", "deleted"),
                ("d.md", "replaced"),
                ("e.md", "added"),
            ])
        )
        self.assertEqual(parsed["a.md"], ("modified", False))
        self.assertEqual(parsed["b.md"], ("added", True))
        self.assertEqual(parsed["c.md"], ("deleted", False))
        self.assertEqual(parsed["d.md"], ("renamed", False))
        self.assertEqual(parsed["e.md"], ("added", False))


class FallbackAndPrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_vcs_cache()
        self._tmp = Path(tempfile.mkdtemp(prefix="doctool-fallback-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_no_vcs_returns_local(self):
        project = self._tmp / "proj_a"
        (project / "content").mkdir(parents=True)
        (project / "content" / "a.md").write_text("a", encoding="utf-8")
        service = ChangeDetectionService(project, project / "content")
        report = service.detect()
        self.assertEqual(report.source, "local")
        self.assertEqual(report.files, ())
        # 状态映射走调用方本地快照：服务本身不产出内容状态
        self.assertEqual(service.status_map(report), {})

    def test_git_precedes_svn(self):
        """项目同时位于 git 仓库与假 svn 工作副本时，Git 优先。"""
        repo = self._tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        pa = make_project(repo, "proj_a", {"content/a.md": "a"})
        commit_all(repo, "init")
        (pa / "content/a.md").write_text("a2", encoding="utf-8")

        def svn_runner(args, cwd):
            return subprocess.CompletedProcess(
                args, returncode=0, stdout=b"", stderr=b""
            )

        service = ChangeDetectionService(
            pa, pa / "content", svn_runner=svn_runner
        )
        report = service.detect()
        self.assertEqual(report.source, "git")

    def test_change_item_non_restorable_marker(self):
        from doc_tool.application.content.changes import build_change_items

        items = build_change_items(
            {"a.md": "modified", "project.yml": "modified"},
            non_restorable=["project.yml"],
        )
        by_path = {i.rel_path: i for i in items}
        self.assertTrue(by_path["a.md"].restorable)
        self.assertFalse(by_path["project.yml"].restorable)
        # 不传 non_restorable 时全部可恢复（默认行为不变）
        items2 = build_change_items({"a.md": "modified"})
        self.assertTrue(items2[0].restorable)

    def test_changed_file_serialization_roundtrip(self):
        item = ChangedFile(
            path="a/b.md",
            change_type="renamed",
            source="git",
            project_root="C:/p",
            abs_path="C:/p/content/b.md",
            old_path="a/b_old.md",
            staged=True,
            unstaged=False,
            untracked=False,
        )
        restored = ChangedFile.from_dict(item.to_dict())
        self.assertEqual(restored, item)


class BackupPolicyTests(unittest.TestCase):
    """ContentWriter 的 .bak 备份开关：VCS 模式下不再生成 .md.bak。"""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="doctool-bak-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.content = self._tmp / "content"
        (self.content / "第1章").mkdir(parents=True)
        self.rel = "第1章/1.1 目的.md"
        target = self.content / self.rel
        target.write_text("v1", encoding="utf-8")

    def _writer(self, backup_enabled: bool):
        from doc_tool.application.content.writer import ContentWriter

        return ContentWriter(
            self.content, self._tmp / ".state", backup_enabled=backup_enabled
        )

    def test_vcs_mode_disables_bak_creation(self):
        """backup_enabled=False（VCS 管理）→ 写入不产生 .md.bak。"""
        writer = self._writer(backup_enabled=False)
        result = writer.write_text(self.rel, "v2")
        self.assertTrue(result.written)
        self.assertIsNone(result.backup_path)
        self.assertEqual(
            list(self.content.rglob("*.bak")), [],
            "VCS 模式下不应生成 .bak 文件",
        )
        # 清单仍记录 edit 条目（供面板展示），但无备份路径
        writer.manifest.load()
        entries = [e for e in writer.manifest.entries if e.rel_path == self.rel]
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].backup_path)

    def test_local_mode_keeps_bak_creation(self):
        """backup_enabled=True（默认/本地项目）→ 仍生成 .md.bak。"""
        writer = self._writer(backup_enabled=True)
        result = writer.write_text(self.rel, "v2")
        self.assertTrue(result.written)
        self.assertIsNotNone(result.backup_path)
        self.assertTrue((self.content / (self.rel + ".bak")).exists())

    def test_set_backup_enabled_toggle(self):
        """运行中切换开关立即生效。"""
        writer = self._writer(backup_enabled=True)
        writer.set_backup_enabled(False)
        result = writer.write_text(self.rel, "v3")
        self.assertIsNone(result.backup_path)
        self.assertEqual(list(self.content.rglob("*.bak")), [])

    def test_local_mode_rollback_restores_from_bak(self):
        """本地模式回滚仍用 .bak 恢复内容（原行为不变）。"""
        writer = self._writer(backup_enabled=True)
        writer.write_text(self.rel, "v2")
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertEqual(
            (self.content / self.rel).read_text(encoding="utf-8"), "v1"
        )
        self.assertEqual(list(self.content.rglob("*.bak")), [])

    def test_vcs_mode_rollback_reports_missing_backup(self):
        """VCS 模式无 .bak：本地清单回滚给出明确失败提示而非静默成功。"""
        writer = self._writer(backup_enabled=False)
        writer.write_text(self.rel, "v2")
        failures = writer.rollback()
        self.assertEqual(len(failures), 1)
        self.assertIn(self.rel, failures[0])
        # 文件保持 v2（未被错误回滚）
        self.assertEqual(
            (self.content / self.rel).read_text(encoding="utf-8"), "v2"
        )

    def test_vcs_mode_create_then_edit_rollback_delete_only(self):
        """VCS 模式新建文件再编辑：回滚删除该文件（create 条目生效）。"""
        writer = self._writer(backup_enabled=False)
        writer.create_file("第1章/1.2 新增.md", "n")
        writer.write_text("第1章/1.2 新增.md", "n2")
        failures = writer.rollback()
        # edit 条目无可恢复备份 → 报失败；create 条目删除文件
        self.assertFalse((self.content / "第1章/1.2 新增.md").exists())


class VcsRollbackTests(RepoFixtureMixin, unittest.TestCase):
    """rollback_all：git restore / svn revert 恢复未提交改动。"""

    def test_git_rollback_all_restores_tracked_and_removes_untracked(self):
        pa = make_project(self.repo, "proj_a", {
            "content/a.md": "v1",
            "content/old.md": "old",
        })
        commit_all(self.repo, "init")
        # 被跟踪：modified（staged+unstaged）
        (pa / "content/a.md").write_text("v2", encoding="utf-8")
        _run_git(self.repo, "add", "proj_a/content/a.md")
        (pa / "content/a.md").write_text("v3", encoding="utf-8")
        # 被跟踪：rename
        _run_git(self.repo, "mv", "proj_a/content/old.md", "proj_a/content/renamed.md")
        # 未跟踪（新增）
        (pa / "content/untracked.md").write_text("u", encoding="utf-8")

        report = self.service(pa).detect()
        failures = rollback_all(report)
        self.assertEqual(failures, [])
        self.assertEqual(
            (pa / "content/a.md").read_text(encoding="utf-8"), "v1"
        )
        self.assertTrue((pa / "content/old.md").exists())
        self.assertFalse((pa / "content/renamed.md").exists())
        self.assertFalse((pa / "content/untracked.md").exists())
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(self.repo),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(status, "", "回滚后工作树应干净")

    def test_git_rollback_single_file_restores_target_file_only(self):
        pa = make_project(self.repo, "proj_a", {
            "content/a.md": "v1",
            "content/b.md": "b1",
        })
        commit_all(self.repo, "init")
        (pa / "content/a.md").write_text("v2", encoding="utf-8")
        (pa / "content/b.md").write_text("b2", encoding="utf-8")

        report = self.service(pa).detect()
        err = rollback_single_file(report, "a.md", content_root=pa / "content")
        self.assertIsNone(err)
        self.assertEqual((pa / "content/a.md").read_text(encoding="utf-8"), "v1")
        self.assertEqual((pa / "content/b.md").read_text(encoding="utf-8"), "b2")

    def test_git_rollback_all_keeps_staged_added_when_not_deleting_untracked(self):
        """delete_untracked=False（改动面板 VCS 模式）时，staged 新增文件
        不得被 git restore 直接删除：撤出暂存后作为未跟踪文件保留，交由
        上层按改动清单判定是否删除（只删本会话工具创建的）。

        旧实现把 staged 新增路径也交给 git restore，git 会把工作树文件一并
        删除，即使上层明确要求不删除未跟踪文件——用户手动 git add 的文件
        会在「回滚全部」时被静默删除。
        """
        pa = make_project(self.repo, "proj_a", {"content/a.md": "v1"})
        commit_all(self.repo, "init")
        # 被跟踪：modified
        (pa / "content/a.md").write_text("v2", encoding="utf-8")
        _run_git(self.repo, "add", "proj_a/content/a.md")
        # staged 新增（用户手动 git add 的新章节）
        (pa / "content/new.md").write_text("n", encoding="utf-8")
        _run_git(self.repo, "add", "proj_a/content/new.md")

        report = self.service(pa).detect()
        failures = rollback_all(report, delete_untracked=False)
        self.assertEqual(failures, [])
        # 修改被恢复；staged 新增文件保留为未跟踪（不被静默删除）。
        self.assertEqual(
            (pa / "content/a.md").read_text(encoding="utf-8"), "v1"
        )
        self.assertTrue((pa / "content/new.md").exists())
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(self.repo),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertIn("proj_a/content/new.md", status)

    def test_git_rollback_all_does_not_touch_other_projects(self):
        """回滚只影响当前项目：同一仓库另一项目的未提交改动保持不变。"""
        pa = make_project(self.repo, "proj_a", {"content/a.md": "a1"})
        pb = make_project(self.repo, "proj_b", {"content/b.md": "b1"})
        commit_all(self.repo, "init")
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        (pb / "content/b.md").write_text("b2", encoding="utf-8")
        report_a = self.service(pa).detect()
        failures = rollback_all(report_a)
        self.assertEqual(failures, [])
        self.assertEqual(
            (pa / "content/a.md").read_text(encoding="utf-8"), "a1"
        )
        # B 项目不受影响
        self.assertEqual(
            (pb / "content/b.md").read_text(encoding="utf-8"), "b2"
        )

    def test_svn_rollback_all_with_injected_runner(self):
        """svn revert 命令参数正确 + 未版本化文件被删除。"""
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)
        pa = wc / "proj_a"
        (pa / "content").mkdir(parents=True)
        (pa / "project.yml").write_text(PROJECT_YML.format(name="A"), encoding="utf-8")
        (pa / "content/modified.md").write_text("m", encoding="utf-8")
        (pa / "content/new.md").write_text("n", encoding="utf-8")
        calls = []

        def runner(args, cwd):
            calls.append((list(args), cwd))
            if args[:2] == ["svn", "status"]:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=(
                        '<?xml version="1.0"?><status><target path=".">'
                        '<entry path="proj_a/content/modified.md"><wc-status item="modified" props="none"/></entry>'
                        '<entry path="proj_a/content/new.md"><wc-status item="unversioned" props="none"/></entry>'
                        "</target></status>"
                    ).encode("utf-8"),
                    stderr=b"",
                )
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

        service = ChangeDetectionService(pa, pa / "content", svn_runner=runner)
        report = service.detect()
        self.assertEqual(report.source, "svn")
        failures = rollback_all(report, runner=runner)
        self.assertEqual(failures, [])
        revert_call = [c for c in calls if c[0][:2] == ["svn", "revert"]]
        self.assertEqual(len(revert_call), 1)
        self.assertIn("proj_a/content/modified.md", revert_call[0][0])
        self.assertNotIn("proj_a/content/new.md", revert_call[0][0])
        self.assertFalse((pa / "content/new.md").exists())
        self.assertTrue((pa / "content/modified.md").exists())

    def test_svn_rollback_all_deletes_versioned_added_when_untracked_removal_on(self):
        """svn add 过的文件在 delete_untracked=True 时回滚必须删除：revert 只
        撤出版本控制、文件仍以未版本化留在工作副本（与 git staged 新增同源）。"""
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)
        pa = wc / "proj_a"
        (pa / "content").mkdir(parents=True)
        (pa / "project.yml").write_text(PROJECT_YML.format(name="A"), encoding="utf-8")
        (pa / "content/modified.md").write_text("m", encoding="utf-8")
        (pa / "content/added.md").write_text("n", encoding="utf-8")

        def runner(args, cwd):
            if args[:2] == ["svn", "status"]:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=(
                        '<?xml version="1.0"?><status><target path=".">'
                        '<entry path="proj_a/content/modified.md"><wc-status item="modified" props="none"/></entry>'
                        '<entry path="proj_a/content/added.md"><wc-status item="added" props="none"/></entry>'
                        "</target></status>"
                    ).encode("utf-8"),
                    stderr=b"",
                )
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

        service = ChangeDetectionService(pa, pa / "content", svn_runner=runner)
        report = service.detect()
        failures = rollback_all(report, runner=runner, delete_untracked=True)
        self.assertEqual(failures, [])
        self.assertFalse((pa / "content/added.md").exists(), "added 文件回滚后应被删除")
        self.assertTrue((pa / "content/modified.md").exists())

    def test_svn_rollback_all_keeps_versioned_added_when_not_deleting_untracked(self):
        """delete_untracked=False（改动面板 VCS 模式）时 added 文件保留为未版本化，
        交由上层按改动清单判定（只删本会话创建的），不静默删除。"""
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)
        pa = wc / "proj_a"
        (pa / "content").mkdir(parents=True)
        (pa / "project.yml").write_text(PROJECT_YML.format(name="A"), encoding="utf-8")
        (pa / "content/added.md").write_text("n", encoding="utf-8")

        def runner(args, cwd):
            if args[:2] == ["svn", "status"]:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=(
                        '<?xml version="1.0"?><status><target path=".">'
                        '<entry path="proj_a/content/added.md"><wc-status item="added" props="none"/></entry>'
                        "</target></status>"
                    ).encode("utf-8"),
                    stderr=b"",
                )
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

        service = ChangeDetectionService(pa, pa / "content", svn_runner=runner)
        report = service.detect()
        failures = rollback_all(report, runner=runner, delete_untracked=False)
        self.assertEqual(failures, [])
        self.assertTrue((pa / "content/added.md").exists(), "不删未跟踪时 added 文件应保留")

    def test_rollback_all_local_returns_message(self):
        from doc_tool.application.content.vcs_changes import ChangeReport

        report = ChangeReport(source="local", project_root=str(self._tmp))
        failures = rollback_all(report)
        self.assertEqual(len(failures), 1)
        self.assertIn("版本控制", failures[0])


class VcsCommitPullTests(RepoFixtureMixin, unittest.TestCase):
    """提交（commit_all）与拉取（pull_changes）：git > svn。"""

    def _git_out(self, repo: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git"] + list(args), cwd=str(repo), capture_output=True, check=True
        )
        # 逐行 strip：整体 strip 会吞掉首行前导空格（porcelain 第一列 XY）。
        text = proc.stdout.decode("utf-8", errors="replace")
        return "\n".join(line.rstrip() for line in text.splitlines())

    def _make_project(self, name: str, files: dict) -> Path:
        project = make_project(self.repo, name, files)
        commit_all(self.repo, "init {0}".format(name))
        return project

    # --- git 提交 ---

    def test_git_commit_all_commits_project_changes(self):
        pa = self._make_project(
            "proj_a",
            {
                "content/a.md": "a",
                "content/c.md": "c",
            },
        )
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        (pa / "content/new.md").write_text("new", encoding="utf-8")
        (pa / "content/c.md").unlink()
        service = self.service(pa)
        report = service.detect()
        self.assertEqual(report.source, "git")
        self.assertEqual(len(report.files), 3)
        failures = vcs_commit_all(report, "feat: update a, add new, drop c")
        self.assertEqual(failures, [])
        # 仓库干净 + 提交信息正确
        self.assertEqual(self._git_out(self.repo, "status", "--porcelain"), "")
        self.assertEqual(
            self._git_out(self.repo, "log", "-1", "--format=%s"),
            "feat: update a, add new, drop c",
        )
        # 提交后再检测：无变化（清缓存避免命中旧仓库级缓存）
        clear_vcs_cache()
        self.assertEqual(service.detect().files, ())

    def test_git_commit_all_scopes_to_project(self):
        self._make_project("proj_a", {"content/a.md": "a"})
        self._make_project("proj_b", {"content/b.md": "b"})
        pa = self.repo / "proj_a"
        pb = self.repo / "proj_b"
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        (pb / "content/b.md").write_text("b2", encoding="utf-8")
        report = self.service(pa).detect()
        failures = vcs_commit_all(report, "feat: a only")
        self.assertEqual(failures, [])
        # proj_b 的改动必须原样保留（未暂存、未提交）
        self.assertEqual(
            self._git_out(self.repo, "status", "--porcelain"),
            " M proj_b/content/b.md",
        )
        self.assertEqual(
            self._git_out(self.repo, "diff", "--cached", "--name-only"), ""
        )
        self.assertEqual(
            self._git_out(self.repo, "log", "-1", "--format=%s"), "feat: a only"
        )

    def test_git_commit_all_empty_message(self):
        pa = self._make_project("proj_a", {"content/a.md": "a"})
        (pa / "content/a.md").write_text("a2", encoding="utf-8")
        report = self.service(pa).detect()
        failures = vcs_commit_all(report, "   ")
        self.assertEqual(failures, ["提交信息不能为空"])
        # 未发生提交
        self.assertNotEqual(self._git_out(self.repo, "status", "--porcelain"), "")

    def test_git_commit_all_command_failure_reports_error(self):
        pa = self._make_project("proj_a", {"content/a.md": "a"})
        (pa / "content/a.md").write_text("a2", encoding="utf-8")

        def bad_runner(args, cwd):
            return subprocess.CompletedProcess(
                args, returncode=128, stdout=b"", stderr=b"fatal: not a git repository"
            )

        report = self.service(pa).detect()
        failures = vcs_commit_all(report, "msg", runner=bad_runner)
        self.assertTrue(failures)
        self.assertIn("git add", failures[0])

    def test_git_commit_all_no_repo_root(self):
        report = ChangeReport(
            source="git", repository_root="", project_root=str(self._tmp)
        )
        self.assertEqual(vcs_commit_all(report, "msg"), ["Git 仓库根不可用"])

    # --- svn 提交（注入假 svn） ---

    def _svn_project(self):
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)
        project = wc / "proj_a"
        (project / "content").mkdir(parents=True)
        (project / "project.yml").write_text(
            PROJECT_YML.format(name="A"), encoding="utf-8"
        )
        return wc, project

    @staticmethod
    def _svn_status_runner(wc: Path, entries: list):
        def runner(args, cwd):
            body = "".join(
                "<entry path={0}{1}{0}><wc-status item={0}{2}{0} props={0}none{0}/></entry>".format(
                    '"', path, item
                )
                for path, item in entries
            )
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<status><target path="
                + '"'
                + "."
                + '"'
                + ">"
                + body
                + "</target></status>"
            )
            return subprocess.CompletedProcess(
                args, returncode=0, stdout=xml.encode("utf-8"), stderr=b""
            )

        return runner

    class _Recorder:
        def __init__(self) -> None:
            self.calls: list = []

        def __call__(self, args, cwd):
            self.calls.append((list(args), str(cwd)))
            return subprocess.CompletedProcess(
                args, returncode=0, stdout=b"", stderr=b""
            )

    def test_svn_commit_all_registers_and_commits(self):
        wc, project = self._svn_project()
        status_runner = self._svn_status_runner(
            wc,
            [
                ("proj_a/content/a.md", "modified"),
                ("proj_a/content/new.md", "unversioned"),
                ("proj_a/content/old.md", "deleted"),
            ],
        )
        service = ChangeDetectionService(
            project, project / "content", svn_runner=status_runner
        )
        report = service.detect()
        self.assertEqual(report.source, "svn")
        recorder = self._Recorder()
        failures = vcs_commit_all(report, "feat: svn", runner=recorder)
        self.assertEqual(failures, [])
        commands = [args for args, _ in recorder.calls]
        self.assertIn(
            ["svn", "add", "--parents", "--force", "proj_a/content/new.md"],
            commands,
        )
        self.assertIn(
            ["svn", "rm", "--force", "proj_a/content/old.md"], commands
        )
        self.assertIn(
            [
                "svn",
                "commit",
                "-m",
                "feat: svn",
                "--",
                "proj_a/content/a.md",
                "proj_a/content/new.md",
                "proj_a/content/old.md",
            ],
            commands,
        )

    def test_svn_commit_all_aborts_when_add_fails(self):
        wc, project = self._svn_project()
        status_runner = self._svn_status_runner(
            wc, [("proj_a/content/new.md", "unversioned")]
        )
        service = ChangeDetectionService(
            project, project / "content", svn_runner=status_runner
        )
        report = service.detect()
        calls: list = []

        def failing_runner(args, cwd):
            calls.append(list(args))
            if args[1] == "add":
                return subprocess.CompletedProcess(
                    args, returncode=1, stdout=b"", stderr=b"E155010"
                )
            return subprocess.CompletedProcess(
                args, returncode=0, stdout=b"", stderr=b""
            )

        failures = vcs_commit_all(report, "msg", runner=failing_runner)
        self.assertTrue(failures)
        self.assertIn("svn add", failures[0])
        self.assertFalse(
            any(args[1] == "commit" for args in calls),
            "svn add 失败后不应继续 commit",
        )

    def test_svn_commit_all_empty_message(self):
        wc, project = self._svn_project()
        report = ChangeReport(
            source="svn", repository_root=str(wc), project_root=str(project)
        )
        self.assertEqual(vcs_commit_all(report, " "), ["提交信息不能为空"])

    # --- 拉取 ---

    def test_pull_git_invokes_git_pull(self):
        pa = self._make_project("proj_a", {"content/a.md": "a"})
        recorder = self._Recorder()
        report = ChangeReport(
            source="git",
            repository_root=str(self.repo),
            project_root=str(pa),
        )
        result = vcs_pull_changes(report, runner=recorder)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary, "已是最新版本")
        self.assertEqual(result.changed_files, ())
        self.assertEqual(result.conflicts, ())
        # 记录里必须包含 git pull（前面还有 rev-parse 探测）
        self.assertTrue(any(args[1:] == ["pull"] for args, _ in recorder.calls))

    def test_pull_git_updates_worktree(self):
        """真实 git：origin 新增提交，工作仓库 pull 后文件出现。"""
        origin = self._tmp / "origin"
        origin.mkdir()
        init_repo(origin)
        (origin / "base.txt").write_text("base", encoding="utf-8")
        commit_all(origin, "base")
        work = self._tmp / "work"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(work)],
            check=True,
            capture_output=True,
        )
        _run_git(work, "config", "user.email", "t@t.t")
        _run_git(work, "config", "user.name", "t")
        project = work / "proj_a"
        (project / "content").mkdir(parents=True)
        (project / "project.yml").write_text(
            PROJECT_YML.format(name="A"), encoding="utf-8"
        )
        (project / "content/a.md").write_text("a", encoding="utf-8")
        commit_all(work, "project")
        # origin 新增远端提交
        (origin / "remote.txt").write_text("remote", encoding="utf-8")
        commit_all(origin, "remote")
        report = ChangeReport(
            source="git", repository_root=str(work), project_root=str(project)
        )
        result = vcs_pull_changes(report)
        self.assertTrue(result.ok)
        self.assertTrue((work / "remote.txt").exists())
        self.assertIn("remote.txt", result.changed_files)
        self.assertEqual(result.conflicts, ())
        self.assertIn("1 个文件", result.summary)
        # 本地项目提交保留（git pull 可能产生 merge 提交，检查历史而非 HEAD）
        self.assertIn(
            "project", self._git_out(work, "log", "--format=%s", "-5")
        )

    def test_pull_git_autostash_when_dirty(self):
        """本地存在未提交修改但与远端不冲突时，自动带 --autostash 拉取并无缝还原本地改动。"""
        origin = self._tmp / "origin_autostash"
        origin.mkdir()
        init_repo(origin)
        (origin / "remote_file.txt").write_text("v1\n", encoding="utf-8")
        (origin / "local_file.txt").write_text("v1\n", encoding="utf-8")
        commit_all(origin, "init")

        work = self._tmp / "work_autostash"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(work)],
            check=True,
            capture_output=True,
        )
        _run_git(work, "config", "user.email", "t@t.t")
        _run_git(work, "config", "user.name", "t")

        # 远端修改 remote_file.txt
        (origin / "remote_file.txt").write_text("v2 remote\n", encoding="utf-8")
        commit_all(origin, "remote update")

        # 本地修改 local_file.txt（未提交，如果直接 pull 会因 dirty tree 提示 stash）
        (work / "local_file.txt").write_text("v1 dirty local\n", encoding="utf-8")

        report = ChangeReport(
            source="git", repository_root=str(work), project_root=str(work)
        )
        result = vcs_pull_changes(report)
        self.assertTrue(result.ok)
        self.assertEqual(result.conflicts, ())
        self.assertIn("1 个文件", result.summary)
        # 本地未提交修改被安全还原
        self.assertEqual((work / "local_file.txt").read_text(encoding="utf-8"), "v1 dirty local\n")
        # 远端修改已合并
        self.assertEqual((work / "remote_file.txt").read_text(encoding="utf-8"), "v2 remote\n")

    def test_pull_git_autostash_conflicting(self):
        """本地未提交修改与远端发生冲突时，autostash 产生冲突并在 result.conflicts 中准确报告。"""
        origin = self._tmp / "origin_autostash_conflict"
        origin.mkdir()
        init_repo(origin)
        (origin / "shared.txt").write_text("v1\n", encoding="utf-8")
        commit_all(origin, "init")

        work = self._tmp / "work_autostash_conflict"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(work)],
            check=True,
            capture_output=True,
        )
        _run_git(work, "config", "user.email", "t@t.t")
        _run_git(work, "config", "user.name", "t")

        (origin / "shared.txt").write_text("v2 remote conflict\n", encoding="utf-8")
        commit_all(origin, "remote update")

        (work / "shared.txt").write_text("v1 local dirty conflict\n", encoding="utf-8")

        report = ChangeReport(
            source="git", repository_root=str(work), project_root=str(work)
        )
        result = vcs_pull_changes(report)
        self.assertTrue(result.ok)
        self.assertIn("shared.txt", result.conflicts)
        self.assertIn("冲突", result.summary)

    def test_pull_git_untracked_conflict_and_stash_recovery(self):
        """本地未跟踪文件与远端冲突时，给出明确未跟踪提示，并可通过 include_untracked 暂存后成功拉取。"""
        origin = self._tmp / "origin_untracked"
        origin.mkdir()
        init_repo(origin)
        (origin / "init.txt").write_text("init\n", encoding="utf-8")
        commit_all(origin, "init")

        work = self._tmp / "work_untracked"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(work)],
            check=True,
            capture_output=True,
        )
        _run_git(work, "config", "user.email", "t@t.t")
        _run_git(work, "config", "user.name", "t")

        # 远端新增 new_file.txt
        (origin / "new_file.txt").write_text("remote new\n", encoding="utf-8")
        commit_all(origin, "add new_file")

        # 本地创建同名未跟踪文件
        (work / "new_file.txt").write_text("local untracked\n", encoding="utf-8")

        report = ChangeReport(
            source="git", repository_root=str(work), project_root=str(work)
        )
        result = vcs_pull_changes(report)
        self.assertFalse(result.ok)
        self.assertIn("未跟踪", result.error or "")

        # 使用 include_untracked 暂存
        st_ok, st_err = git_stash_save(work, "stash untracked", include_untracked=True)
        self.assertTrue(st_ok)
        self.assertFalse((work / "new_file.txt").exists())

        # 重新拉取成功
        result2 = vcs_pull_changes(report)
        self.assertTrue(result2.ok)
        self.assertEqual((work / "new_file.txt").read_text(encoding="utf-8"), "remote new\n")

    def test_pull_svn_invokes_svn_update(self):
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)
        recorder = self._Recorder()
        report = ChangeReport(
            source="svn", repository_root=str(wc), project_root=str(wc)
        )
        result = vcs_pull_changes(report, runner=recorder)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary, "已是最新版本")
        self.assertEqual(recorder.calls[0][0][1:], ["update"])

    def test_pull_failure_reports_error(self):
        pa = self._make_project("proj_a", {"content/a.md": "a"})

        def bad_runner(args, cwd):
            return subprocess.CompletedProcess(
                args, returncode=1, stdout=b"", stderr=b"fatal: no upstream configured"
            )

        report = ChangeReport(
            source="git", repository_root=str(self.repo), project_root=str(pa)
        )
        result = vcs_pull_changes(report, runner=bad_runner)
        self.assertFalse(result.ok)
        self.assertIn("git pull", result.error or "")
        self.assertEqual(result.conflicts, ())

    def test_pull_local_report_rejected(self):
        report = ChangeReport(source="local", project_root=str(self._tmp))
        self.assertEqual(
            vcs_commit_all(report, "m"), ["当前项目不在版本控制内，无法提交"]
        )
        result = vcs_pull_changes(report)
        self.assertFalse(result.ok)
        self.assertIn("无法拉取", result.error or "")

    def test_pull_git_reports_changed_files(self):
        """git pull 快进更新：报告带入的文件清单与数量。"""
        pa = self._make_project("proj_a", {"content/a.md": "a"})

        class Fake:
            def __init__(self):
                self.calls = []
                self._rev_count = 0

            def __call__(self, args, cwd):
                self.calls.append(list(args))
                name = args[1] if len(args) > 1 else ""
                if name == "rev-parse":
                    self._rev_count += 1
                    out = b"abc123\n" if self._rev_count == 1 else b"def456\n"
                    return subprocess.CompletedProcess(args, 0, out, b"")
                if name == "pull":
                    return subprocess.CompletedProcess(
                        args, 0, b"Updating abc123..def456\nFast-forward\n", b""
                    )
                if name == "diff":
                    return subprocess.CompletedProcess(
                        args, 0, b"content/a.md\ncontent/new.md\n", b""
                    )
                return subprocess.CompletedProcess(args, 0, b"", b"")

        report = ChangeReport(
            source="git", repository_root=str(self.repo), project_root=str(pa)
        )
        result = vcs_pull_changes(report, runner=Fake())
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_files, ("content/a.md", "content/new.md"))
        self.assertEqual(result.conflicts, ())
        self.assertIn("2", result.summary)
        self.assertIn("更新了", result.summary)

    def test_pull_git_conflict_reports_unmerged_files(self):
        """git pull 合并冲突：ok=False 且列出未合并文件。"""
        pa = self._make_project("proj_a", {"content/a.md": "a"})

        def fake(args, cwd):
            name = args[1] if len(args) > 1 else ""
            if name == "rev-parse":
                return subprocess.CompletedProcess(args, 0, b"abc123\n", b"")
            if name == "pull":
                return subprocess.CompletedProcess(
                    args,
                    1,
                    b"",
                    b"CONFLICT (content): Merge conflict in content/a.md\n"
                    b"Automatic merge failed; fix conflicts and then commit the result.",
                )
            if name == "ls-files":
                return subprocess.CompletedProcess(
                    args,
                    0,
                    b"100644 111 1\tcontent/a.md\n"
                    b"100644 222 2\tcontent/a.md\n"
                    b"100644 333 3\tcontent/a.md\n",
                    b"",
                )
            return subprocess.CompletedProcess(args, 0, b"", b"")

        report = ChangeReport(
            source="git", repository_root=str(self.repo), project_root=str(pa)
        )
        result = vcs_pull_changes(report, runner=fake)
        self.assertFalse(result.ok)
        self.assertEqual(result.conflicts, ("content/a.md",))
        self.assertIn("git pull", result.error or "")

    def test_pull_svn_parses_changes_and_conflicts(self):
        """svn update：解析 U/A 变更与 C 冲突并统计。"""
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)

        def fake(args, cwd):
            return subprocess.CompletedProcess(
                args,
                0,
                b"Updating '.':\n"
                b"U    content/a.md\n"
                b"A    content/b.md\n"
                b"C    content/c.md\n"
                b"Updated to revision 42.\n",
                b"",
            )

        report = ChangeReport(
            source="svn", repository_root=str(wc), project_root=str(wc)
        )
        result = vcs_pull_changes(report, runner=fake)
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_files, ("content/a.md", "content/b.md"))
        self.assertEqual(result.conflicts, ("content/c.md",))
        self.assertIn("2 个文件更新", result.summary)
        self.assertIn("1 个冲突", result.summary)

    def test_pull_svn_failure_reports_error(self):
        wc = self._tmp / "wc"
        (wc / ".svn").mkdir(parents=True)

        def fake(args, cwd):
            return subprocess.CompletedProcess(
                args, 1, b"", b"svn: E170000: Unable to connect to a repository"
            )

        report = ChangeReport(
            source="svn", repository_root=str(wc), project_root=str(wc)
        )
        result = vcs_pull_changes(report, runner=fake)
        self.assertFalse(result.ok)
        self.assertIn("svn update", result.error or "")


class GitBranchAndWorkflowTests(RepoFixtureMixin, unittest.TestCase):
    """Git 分支管理、暂存、部分提交与推送测试。"""

    def test_list_git_branches_and_current(self):
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")
        _run_git(self.repo, "branch", "feature/awesome")
        _run_git(self.repo, "branch", "release-1.0")

        # 修改文件制造未提交改动
        (project / "content" / "a.md").write_text("v2\n", encoding="utf-8")

        branches, err = list_git_branches(self.repo, uncommitted_count=1)
        self.assertIsNone(err)
        self.assertTrue(len(branches) >= 3)

        current = next(b for b in branches if b.is_current)
        self.assertEqual(current.uncommitted_count, 1)

        names = [b.name for b in branches]
        self.assertIn("feature/awesome", names)
        self.assertIn("release-1.0", names)

    def test_switch_git_branch_existing(self):
        make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")
        _run_git(self.repo, "branch", "dev")

        ok, err = switch_git_branch(self.repo, "dev")
        self.assertTrue(ok)
        self.assertIsNone(err)

        branches, _ = list_git_branches(self.repo)
        cur = next(b for b in branches if b.is_current)
        self.assertEqual(cur.name, "dev")

    def test_create_and_checkout_branch(self):
        make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")

        ok, err = switch_git_branch(self.repo, "feature/new-topic", create=True)
        self.assertTrue(ok)
        self.assertIsNone(err)

        branches, _ = list_git_branches(self.repo)
        cur = next(b for b in branches if b.is_current)
        self.assertEqual(cur.name, "feature/new-topic")

    def test_switch_git_branch_invalid_names(self):
        ok, err = switch_git_branch(self.repo, "bad name with spaces", create=True)
        self.assertFalse(ok)
        self.assertIn("非法字符", err or "")

        ok, err = switch_git_branch(self.repo, "bad..double.dot", create=True)
        self.assertFalse(ok)
        self.assertIn("不合法", err or "")

        ok, err = switch_git_branch(self.repo, "", create=True)
        self.assertFalse(ok)
        self.assertIn("不能为空", err or "")

    def test_git_stash_and_pop(self):
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")

        target_file = project / "content" / "a.md"
        target_file.write_text("v2 modified\n", encoding="utf-8")

        # 暂存
        ok, err = git_stash_save(self.repo, "save changes before checkout")
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 工作区应恢复干净（v1）
        self.assertEqual(target_file.read_text(encoding="utf-8"), "v1\n")

        # 恢复暂存
        ok, err = git_stash_pop(self.repo)
        self.assertTrue(ok)
        self.assertIsNone(err)
        # 改动被恢复
        self.assertEqual(target_file.read_text(encoding="utf-8"), "v2 modified\n")

    def test_git_stash_clean_and_empty_pop(self):
        # 无初始提交时应明确提示
        ok, err = git_stash_save(self.repo)
        self.assertFalse(ok)
        self.assertIn("尚未创建初始提交", err or "")

        # 创建初始提交后
        make_project(self.repo, "doc", {"content/init.md": "v1\n"})
        commit_all(self.repo, "init")

        # 干净工作区暂存应提示无需暂存
        ok, err = git_stash_save(self.repo)
        self.assertFalse(ok)
        self.assertIn("没有需要暂存", err or "")

        # 空暂存区 pop 应提示无暂存
        ok, err = git_stash_pop(self.repo)
        self.assertFalse(ok)
        self.assertIn("没有可恢复的暂存改动", err or "")

    def test_git_stash_include_untracked(self):
        make_project(self.repo, "doc", {"content/init.md": "v1\n"})
        commit_all(self.repo, "init")

        untracked_file = self.repo / "doc" / "content" / "new_untracked.md"
        untracked_file.write_text("new untracked\n", encoding="utf-8")

        # Without include_untracked, stash should report no local changes
        ok, err = git_stash_save(self.repo, "no untracked", include_untracked=False)
        self.assertFalse(ok)
        self.assertIn("没有需要暂存", err or "")
        self.assertTrue(untracked_file.exists())

        # With include_untracked, stash should succeed and file should disappear
        ok, err = git_stash_save(self.repo, "with untracked", include_untracked=True)
        self.assertTrue(ok)
        self.assertFalse(untracked_file.exists())

        # Pop should restore the untracked file
        ok, err = git_stash_pop(self.repo)
        self.assertTrue(ok)
        self.assertTrue(untracked_file.exists())
        self.assertEqual(untracked_file.read_text(encoding="utf-8"), "new untracked\n")

    def test_git_stash_pop_conflict(self):
        project = make_project(self.repo, "doc", {"content/c.md": "base\n"})
        commit_all(self.repo, "init c")

        target_file = project / "content" / "c.md"
        target_file.write_text("local edit\n", encoding="utf-8")
        ok, err = git_stash_save(self.repo, "stash local")
        self.assertTrue(ok)

        target_file.write_text("commit edit\n", encoding="utf-8")
        commit_all(self.repo, "remote edit")

        ok, err = git_stash_pop(self.repo)
        self.assertFalse(ok)
        self.assertIn("conflict", (err or "").lower())

    def test_commit_files_selective(self):
        project = make_project(
            self.repo, "doc", {"content/a.md": "a1\n", "content/b.md": "b1\n"}
        )
        commit_all(self.repo, "init")

        # 修改两个文件
        (project / "content" / "a.md").write_text("a2\n", encoding="utf-8")
        (project / "content" / "b.md").write_text("b2\n", encoding="utf-8")

        svc = self.service(project)
        report = svc.detect()
        self.assertEqual(len(report.files), 2)

        # 仅勾选并提交 a.md
        failures = vcs_commit_files(report, ["content/a.md", "doc/content/a.md"], "commit only a")
        self.assertEqual(failures, [])

        # 再次检测，a.md 已入库，只剩下 b.md
        svc.invalidate_cache()
        report_after = svc.detect()
        self.assertEqual(len(report_after.files), 1)
        self.assertIn("b.md", report_after.files[0].path)

    def test_push_changes_with_fake_runner(self):
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        svc = self.service(project)
        report = svc.detect()

        commands_run = []

        def fake_git(args, cwd):
            commands_run.append(args)
            if "rev-parse" in args:
                if "@{u}" in args:
                    return subprocess.CompletedProcess(args, 0, b"origin/master\n", b"")
                return subprocess.CompletedProcess(args, 0, b"master\n", b"")
            if "push" in args:
                return subprocess.CompletedProcess(args, 0, b"Everything up-to-date\n", b"")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        res = vcs_push_changes(report, runner=fake_git)
        self.assertTrue(res.ok)
        self.assertIn("已成功推送", res.summary)
        self.assertTrue(any("push" in cmd for cmd in commands_run))

    def test_service_branches_and_switch_integration(self):
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")

        svc = self.service(project)
        branches, err = svc.branches()
        self.assertIsNone(err)
        self.assertTrue(len(branches) >= 1)

        ok, err = svc.switch_branch("test-svc-branch", create=True)
        self.assertTrue(ok)
        self.assertIsNone(err)

        branches_after, _ = svc.branches()
        cur = next(b for b in branches_after if b.is_current)
        self.assertEqual(cur.name, "test-svc-branch")

    def test_list_git_branches_detached_head(self):
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")
        # 游离头指针
        _run_git(self.repo, "checkout", "--detach", "HEAD")

        branches, err = list_git_branches(self.repo)
        self.assertIsNone(err)
        self.assertTrue(any(b.is_current for b in branches), "游离状态下必须包含 is_current=True 分支")
        cur = next(b for b in branches if b.is_current)
        self.assertTrue(cur.name.startswith("HEAD"), f"分支名应为 HEAD 标识，实际为: {cur.name}")

    def test_push_changes_detached_head_blocked(self):
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n"})
        commit_all(self.repo, "init")
        _run_git(self.repo, "checkout", "--detach", "HEAD")

        svc = self.service(project)
        report = svc.detect()
        res = vcs_push_changes(report)
        self.assertFalse(res.ok)
        self.assertIn("游离头指针", res.error or "")

    def test_commit_files_with_nested_project_and_relative_paths(self):
        project = make_project(self.repo, "sub/my_doc", {"content/page.md": "v1\n"})
        commit_all(self.repo, "init")

        # 修改页面
        (project / "content" / "page.md").write_text("v2 updated\n", encoding="utf-8")

        svc = self.service(project)
        report = svc.detect()
        self.assertEqual(len(report.files), 1)

        # 传递相对 content 或相对 project 的路径（如 UI 传过来的 "page.md"）
        failures = vcs_commit_files(report, ["page.md"], "nested commit test")
        self.assertEqual(failures, [])

        svc.invalidate_cache()
        report_after = svc.detect()
        self.assertEqual(len(report_after.files), 0, "提交后工作区应干净")

    def test_commit_files_with_both_reported_and_unreported_files(self):
        """同时包含 report 内与 report 缓存外文件时，两者均正确入库，不丢文件。"""
        project = make_project(self.repo, "doc", {"content/a.md": "v1\n", "content/b.md": "v1\n"})
        commit_all(self.repo, "init")

        (project / "content" / "a.md").write_text("v2\n", encoding="utf-8")
        svc = self.service(project)
        # report 此时只包含了 a.md
        report = svc.detect()
        self.assertEqual(len(report.files), 1)

        # 此时磁盘上新建了 c.md（不在之前的 report.files 中）
        (project / "content" / "c.md").write_text("v1 new\n", encoding="utf-8")

        # 同时勾选 a.md 与 c.md 提交：两者均应被成功 commit，c.md 不会被丢弃
        failures = vcs_commit_files(report, ["content/a.md", "content/c.md"], "commit both a and c")
        self.assertEqual(failures, [])

        svc.invalidate_cache()
        report_after = svc.detect()
        # a.md 和 c.md 都已入库，工作区干净
        self.assertEqual(len(report_after.files), 0)


    def test_pull_git_chinese_locale_conflict_messages(self):
        """中文 Git 环境下的未提交冲突与未跟踪冲突应被正确识别并提示暂存。"""
        import subprocess
        from doc_tool.application.content.vcs_changes import ChangeReport, _git_pull_changes

        report = ChangeReport(
            source="git", repository_root=str(self._tmp), project_root=str(self._tmp)
        )

        # 1. 模拟中文环境下的工作区修改将被覆盖
        def mock_runner_dirty(*args, **kwargs):
            cmd = args[0]
            if "pull" in cmd:
                out = "错误：您对以下文件的本地修改将被合并操作覆盖：\n\ttest.txt\n请在合并前暂存或提交您的修改。"
                return subprocess.CompletedProcess(cmd, 1, stdout=out.encode("utf-8"), stderr=b"")
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

        res_dirty = _git_pull_changes(report, timeout=5.0, runner=mock_runner_dirty)
        self.assertFalse(res_dirty.ok)
        self.assertIn("本地存在未提交的改动与远端冲突", res_dirty.error)

        # 2. 模拟中文环境下的未跟踪文件将被覆盖
        def mock_runner_untracked(*args, **kwargs):
            cmd = args[0]
            if "pull" in cmd:
                out = "错误：以下未跟踪的工作区文件将被覆盖：\n\tnew_untracked.txt\n请在合并前移动或删除。"
                return subprocess.CompletedProcess(cmd, 1, stdout=out.encode("utf-8"), stderr=b"")
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

        res_untracked = _git_pull_changes(report, timeout=5.0, runner=mock_runner_untracked)
        self.assertFalse(res_untracked.ok)
        self.assertIn("本地存在未跟踪的新增文件与远端冲突", res_untracked.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
