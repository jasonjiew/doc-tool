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
    GitChangeDetector,
    SvnChangeDetector,
    clear_vcs_cache,
    find_git_repo_root,
    find_svn_wc_root,
    parse_git_name_status_z,
    parse_git_status_z,
    parse_svn_status_xml,
    rollback_all,
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
            self.assertEqual(find_git_repo_root(deep), repo)
            outside = Path(tmp) / "elsewhere"
            outside.mkdir()
            self.assertIsNone(find_git_repo_root(outside))

    def test_find_svn_wc_root_walks_up_parents(self):
        with tempfile.TemporaryDirectory(prefix="doctool-root-") as tmp:
            wc = Path(tmp) / "wc"
            (wc / ".svn").mkdir(parents=True)
            deep = wc / "x" / "y"
            deep.mkdir(parents=True)
            self.assertEqual(find_svn_wc_root(deep), wc)
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
        pa = make_project(self.repo, "需求 说明书 KF-2090-1-001", {
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
        def runner(args, cwd):
            xml = entries_by_wc.get(cwd, self._svn_xml([]))
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

    def test_rollback_all_local_returns_message(self):
        from doc_tool.application.content.vcs_changes import ChangeReport

        report = ChangeReport(source="local", project_root=str(self._tmp))
        failures = rollback_all(report)
        self.assertEqual(len(failures), 1)
        self.assertIn("版本控制", failures[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
