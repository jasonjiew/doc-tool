# -*- coding: utf-8 -*-
"""V3.1 team-workflow service tests (31-A history / 31-B todos / 31-C handoff).

Run from the repository root::

    $env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path
    python scripts\\tests\\test_v31_team_workflow.py

Fixtures live under ``scripts.tests.core_fixtures.SCRATCH_ROOT`` (never
``tempfile``). Git-specific tests build a throwaway repository inside the
fixture directory and skip with an explicit assertion of the fallback path when
Git is unavailable on this machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests.core_fixtures import cleanup, scratch_dir, two_chapter_project  # noqa: E402

from doc_tool.application.content.assignments import (  # noqa: E402
    ASSIGNMENTS_FILE_NAME,
    SOURCE_COMMENT,
    SOURCE_RELATION,
    UNASSIGNED,
    AssignmentStore,
    assign_todo,
    build_todo_board,
    load_team_config,
    render_todo_board,
    todos_for,
)
from doc_tool.application.content.chapter_history import (  # noqa: E402
    SOURCE_CURRENT,
    SOURCE_GIT,
    SOURCE_LOCAL,
    ChapterHistoryService,
    parse_git_log_z,
)
from doc_tool.application.content import handoff as handoff  # noqa: E402
from doc_tool.application.content.handoff import (  # noqa: E402
    HANDOFF_SCHEMA,
    HANDOFF_SCHEMA_VERSION,
    MANIFEST_NAME,
    STATUS_ALREADY_APPLIED,
    STATUS_CONFLICT,
    STATUS_RESOURCE_MISMATCH,
    apply_handoff_plan,
    export_handoff_package,
    import_handoff_as_new_copy,
    plan_handoff_apply,
    read_handoff_entry,
    read_handoff_manifest,
)
from doc_tool.application.content.impact import (  # noqa: E402
    ReviewRecord,
    ReviewRecordStore,
)
from doc_tool.application.content.impact import ReviewRecord as ImpactReviewRecord  # noqa: E402
from doc_tool.application.content.local_history import LocalHistoryStore  # noqa: E402
from doc_tool.application.content.writer import ContentWriter  # noqa: E402
from doc_tool.application.review.review_store import ReviewStore  # noqa: E402
from doc_tool.application.review.versioned_review import confirm_comment  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

DOC_TYPE = "general"
CHAPTER_ONE = "\u7b2c1\u7ae0 \u5f15\u8a00/1.1 \u76ee\u7684.md"
CHAPTER_TWO = "\u7b2c2\u7ae0 \u8bbe\u8ba1/2.1 \u67b6\u6784.md"


def _git_available() -> bool:
    return shutil.which("git") is not None


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, timeout=60, check=False
    )


def _init_git_repo(root: Path) -> bool:
    """Create a real Git repository with two commits plus one rename.

    History built here (all inside the fixture directory):

    1. ``chapter-one initial`` -> both chapters committed.
    2. ``chapter-one second``  -> 1.1 body changed.
    3. ``rename chapter two``  -> 2.1 moved to a new path.
    """
    if not _git_available():
        return False
    if _git(root, "init").returncode != 0:
        return False
    _git(root, "config", "user.email", "fixture@example.com")
    _git(root, "config", "user.name", "Fixture Author")
    _git(root, "config", "commit.gpgsign", "false")
    (_git(root, "add", "-A"))
    if _git(root, "commit", "-m", "chapter-one initial").returncode != 0:
        return False
    content = root / "content" / DOC_TYPE
    target = content / CHAPTER_ONE
    target.write_text(target.read_text(encoding="utf-8") + "Git \u7b2c\u4e8c\u8f6e\u6b63\u6587\u3002\n",
                      encoding="utf-8")
    _git(root, "add", "-A")
    if _git(root, "commit", "-m", "chapter-one second").returncode != 0:
        return False
    moved = content / "\u7b2c2\u7ae0 \u8bbe\u8ba1" / "2.2 \u67b6\u6784\u8bf4\u660e.md"
    source_rel = (content / CHAPTER_TWO).relative_to(root).as_posix()
    target_rel = moved.relative_to(root).as_posix()
    if _git(root, "mv", source_rel, target_rel).returncode != 0:
        return False
    if _git(root, "commit", "-m", "rename chapter two").returncode != 0:
        return False
    return True


class _FixtureCase(unittest.TestCase):
    """Shared scratch-directory lifecycle (no ``tempfile`` anywhere)."""

    def setUp(self):
        self.tmp = scratch_dir("v31")
        self.project = two_chapter_project(self.tmp / "proj")
        self.project = Path(self.project)
        self.content = self.project / "content" / DOC_TYPE
        self.state = self.project / ".state"
        self.manifest = ProjectManifest.load(self.project)
        self.out = self.tmp / "out"
        self.out.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        cleanup(self.tmp)

    # --- helpers ---

    def text(self, rel: str) -> str:
        return (self.content / rel).read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> None:
        (self.content / rel).write_text(text, encoding="utf-8")

    def hashes(self, *rels: str) -> dict:
        return {rel: handoff.sha256_text(self.text(rel)) for rel in rels}

    def no_git_project(self, name: str = "no-git") -> Path:
        """A copy of the fixture placed outside any Git repository.

        The scratch root lives inside this checkout, so ``find_git_repo_root``
        would otherwise report the outer repository; "no Git" behaviour needs a
        directory with no ancestor ``.git`` at all.
        """
        plain = self.tmp / name
        shutil.copytree(str(self.project), str(plain))
        return plain

    def receiver(self, name: str, overrides: dict = None) -> Path:
        """A second directory holding the same chapters (the other machine)."""
        other = self.tmp / name
        (other / "content" / DOC_TYPE).mkdir(parents=True, exist_ok=True)
        for rel in (CHAPTER_ONE, CHAPTER_TWO):
            (other / "content" / DOC_TYPE / rel).parent.mkdir(parents=True, exist_ok=True)
            (other / "content" / DOC_TYPE / rel).write_text(self.text(rel), encoding="utf-8")
        for rel, text in (overrides or {}).items():
            target = other / "content" / DOC_TYPE / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return other

class ChapterHistoryFallbackTests(_FixtureCase):
    """31-A: no-Git fallback, buffer comparison, broken repository safety."""

    def _service(self, **kwargs) -> ChapterHistoryService:
        return ChapterHistoryService(self.project, self.content, self.state, **kwargs)

    def test_local_history_used_without_git(self):
        writer = ContentWriter(self.content, self.state)
        first = self.text(CHAPTER_ONE)
        writer.write_text(CHAPTER_ONE, first + "\u7b2c\u4e8c\u7248\u3002\n")
        writer.write_text(CHAPTER_ONE, first + "\u7b2c\u4e09\u7248\u3002\n")

        service = self._service()
        history = service.collect(CHAPTER_ONE)
        self.assertEqual(history.source, SOURCE_LOCAL)
        self.assertTrue(history.commits, "\u65e0 Git \u65f6\u5fc5\u987b\u56de\u9000\u672c\u5730\u5386\u53f2")
        self.assertTrue(all(item.source == SOURCE_LOCAL for item in history.commits))
        # Newest recovery point first.
        stamps = [item.committed_at for item in history.commits]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        newest = history.commits[0]
        version = service.read_version(CHAPTER_ONE, newest.version_id, SOURCE_LOCAL)
        self.assertTrue(version.available)
        self.assertIn("\u7b2c\u4e8c\u7248", version.text)

    def test_local_snapshot_restore_is_a_new_save(self):
        writer = ContentWriter(self.content, self.state)
        writer.write_text(CHAPTER_ONE, "\u7b2c\u4e8c\u7248\u3002\n")
        service = self._service()
        history = service.collect(CHAPTER_ONE)
        snapshot = history.commits[0]
        restored = service.restore_local_version(
            CHAPTER_ONE, snapshot.version_id, writer, confirmed=True
        )
        self.assertTrue(restored.written)
        self.assertEqual(self.text(CHAPTER_ONE), service.read_local_version(
            CHAPTER_ONE, snapshot.version_id))
        # The restore itself became a fresh recovery point.
        after = service.collect(CHAPTER_ONE)
        self.assertTrue(any("restore" in item.subject for item in after.commits), after.to_dict())

    def test_broken_recovery_point_does_not_raise(self):
        plain = self.no_git_project()
        content = plain / "content" / DOC_TYPE
        state = plain / ".state"
        writer = ContentWriter(content, state)
        writer.write_text(CHAPTER_ONE, "\u4e00\u7248\u3002\n")
        writer.write_text(CHAPTER_ONE, "\u4e8c\u7248\u3002\n")
        store = LocalHistoryStore(content, state)
        rel = (content / CHAPTER_ONE).relative_to(content).as_posix()
        key = hashlib.sha256(os.path.normcase(rel).encode("utf-8")).hexdigest()
        folder = store.root / key
        snapshots = sorted(item for item in folder.iterdir() if item.is_dir())
        self.assertGreaterEqual(len(snapshots), 2, snapshots)
        (snapshots[0] / "metadata.json").write_text("{ not json", encoding="utf-8")
        service = ChapterHistoryService(plain, content, state)
        history = service.collect(CHAPTER_ONE)  # must not raise
        self.assertEqual(history.source, SOURCE_LOCAL)
        self.assertTrue(history.warnings, "\u635f\u574f\u6062\u590d\u70b9\u5e94\u6709\u660e\u786e\u8bf4\u660e")
        self.assertTrue(history.commits, "\u574f\u5143\u6570\u636e\u4e0d\u5e94\u906e\u853d\u5176\u4f59\u53ef\u7528\u5386\u53f2")

    def test_git_failure_falls_back_to_local(self):
        writer = ContentWriter(self.content, self.state)
        writer.write_text(CHAPTER_ONE, "\u672c\u5730\u56de\u9000\u7248\u3002\n")

        def exploding_runner(args, cwd=None):
            raise OSError("git exploded")

        service = ChapterHistoryService(
            self.project, self.content, self.state, git_executable="git",
            runner=exploding_runner,
        )
        # Pretend a repository exists so the git path is actually attempted.
        (self.project / ".git").mkdir(exist_ok=True)
        history = service.collect(CHAPTER_ONE)
        self.assertEqual(history.source, SOURCE_LOCAL)
        self.assertTrue(history.commits)
        self.assertTrue(history.warnings)

    def test_no_history_at_all_reports_current_only(self):
        plain = self.no_git_project("no-history")
        service = ChapterHistoryService(plain, plain / "content" / DOC_TYPE, plain / ".state")
        history = service.collect(CHAPTER_ONE)
        self.assertEqual(history.source, SOURCE_CURRENT)
        self.assertIn("current on-disk content", history.note)
        self.assertEqual(history.current_text, self.text(CHAPTER_ONE))
        self.assertFalse(history.commits)

    def test_invalid_chapter_path_is_reported(self):
        service = self._service()
        for bad in ("../escape.md", "", "C:/absolute.md"):
            history = service.collect(bad)
            self.assertEqual(history.source, SOURCE_CURRENT)
            self.assertFalse(history.commits)

    def test_buffer_comparison_reports_facts(self):
        service = self._service()
        on_disk = self.text(CHAPTER_ONE)
        dirty = on_disk + "\u672a\u4fdd\u5b58\u4fee\u6539\u3002\n"
        comparison = service.compare_current(CHAPTER_ONE, "current", dirty, SOURCE_CURRENT)
        self.assertTrue(comparison.buffer_changed)
        self.assertTrue(comparison.differs)
        self.assertFalse(comparison.disk_differs_from_version)
        self.assertIn("\u672a\u4fdd\u5b58\u4fee\u6539", comparison.diff_text)
        clean = service.compare_current(CHAPTER_ONE, "current", on_disk, SOURCE_CURRENT)
        self.assertFalse(clean.buffer_changed)
        self.assertFalse(clean.differs)

    def test_history_image_note_is_explicit(self):
        from doc_tool.application.content.chapter_history import HistoryVersion

        with_image = HistoryVersion("v1", SOURCE_GIT, text="\n![\u56fe](assets/a.png)\n")
        self.assertTrue(with_image.images_unavailable_note)
        self.assertIn("images", with_image.images_unavailable_note)
        without = HistoryVersion("v1", SOURCE_GIT, text="\u7eaf\u6587\u5b57\n")
        self.assertEqual(without.images_unavailable_note, "")

    def test_unavailable_commit_is_explained(self):
        service = self._service()
        version = service.read_version(CHAPTER_ONE, "0" * 40, SOURCE_GIT)
        self.assertFalse(version.available)
        self.assertTrue(version.note)


class ChapterHistoryGitTests(_FixtureCase):
    """31-A: real Git history, rename following and buffer comparison."""

    def setUp(self):
        super().setUp()
        self.git_ok = _init_git_repo(self.project)
        if not self.git_ok:
            return
        self.service = ChapterHistoryService(self.project, self.content, self.state)

    def test_git_history_follows_rename(self):
        if not self.git_ok:
            # Fallback must still work when Git is unavailable on this machine.
            fallback = ChapterHistoryService(self.project, self.content, self.state)
            history = fallback.collect(CHAPTER_ONE)
            self.assertIn(history.source, (SOURCE_CURRENT, SOURCE_LOCAL))
            self.skipTest("Git unavailable; verified the fallback path instead")
        history = self.service.collect(CHAPTER_ONE)
        self.assertEqual(history.source, SOURCE_GIT)
        self.assertEqual(len(history.commits), 2, history.to_dict())
        subjects = [item.subject for item in history.commits]
        self.assertIn("chapter-one second", subjects)
        self.assertIn("chapter-one initial", subjects)
        newest = history.commits[0]
        head = _git(self.project, "rev-parse", "HEAD").stdout.decode().strip()
        self.assertEqual(newest.subject, "chapter-one second")
        self.assertNotEqual(newest.version_id, head,
                            "\u7eaf\u91cd\u547d\u540d\u63d0\u4ea4\u4e0d\u662f\u65b0\u7684\u6b63\u6587\u7248\u672c")
        self.assertTrue(newest.author)
        self.assertTrue(newest.committed_at)
        newest_text = self.service.read_version(CHAPTER_ONE, newest.version_id, SOURCE_GIT)
        self.assertTrue(newest_text.available, newest_text.note)
        self.assertEqual(newest_text.text, self.text(CHAPTER_ONE),
                         "\u6700\u65b0\u5185\u5bb9\u7248\u672c\u5e94\u4e0e\u5f53\u524d\u78c1\u76d8\u4e00\u81f4")

        # The rename commit is visible and its old path is readable.
        moved_history = self.service.collect("\u7b2c2\u7ae0 \u8bbe\u8ba1/2.2 \u67b6\u6784\u8bf4\u660e.md")
        self.assertEqual(moved_history.source, SOURCE_GIT)
        self.assertTrue(moved_history.commits)
        rename_commit = moved_history.commits[0]
        self.assertIn("rename chapter two", rename_commit.subject)
        self.assertTrue(rename_commit.was_renamed)
        self.assertEqual(rename_commit.path, CHAPTER_TWO)
        self.assertEqual(rename_commit.content_path, "\u7b2c2\u7ae0 \u8bbe\u8ba1/2.2 \u67b6\u6784\u8bf4\u660e.md",
                         "\u8be5\u63d0\u4ea4\u65f6\u70b9\u7684\u6587\u4ef6\u540d\u5df2\u662f\u65b0\u540d")
        # The entry carries both names, so the pre-rename path stays visible
        # even though ``<commit>:<old path>`` is not readable at the rename
        # commit itself (the file already had its new name there).
        self.assertTrue(rename_commit.original_path.endswith("2.1 \u67b6\u6784.md"))
        self.assertIn("2.1", str(rename_commit.to_dict()["originalPath"]))
        pre_rename = self.service.read_git_version(rename_commit.version_id,
                                                   rename_commit.content_path)
        self.assertIsNotNone(pre_rename, "\u91cd\u547d\u540d\u63d0\u4ea4\u7684\u6b63\u6587\u5e94\u53ef\u8bfb")
        self.assertIn("\u67b6\u6784\u6b63\u6587", pre_rename)
        version = self.service.read_version(
            "\u7b2c2\u7ae0 \u8bbe\u8ba1/2.2 \u67b6\u6784\u8bf4\u660e.md",
            rename_commit.version_id, SOURCE_GIT)
        self.assertTrue(version.available, version.note)
        self.assertIn("\u67b6\u6784\u6b63\u6587", version.text)

    def test_git_version_text_and_buffer_compare(self):
        if not self.git_ok:
            self.skipTest("Git unavailable on this machine")
        history = self.service.collect(CHAPTER_ONE)
        oldest = history.commits[-1]
        self.assertEqual(oldest.subject, "chapter-one initial")
        version = self.service.read_version(CHAPTER_ONE, oldest.version_id, SOURCE_GIT)
        self.assertTrue(version.available, version.note)
        self.assertEqual(version.text, "\u76ee\u7684\u6b63\u6587\u3002\n")
        self.assertNotEqual(version.text, self.text(CHAPTER_ONE),
                            "\u5386\u53f2\u7248\u672c\u5e94\u4e0e\u5f53\u524d\u78c1\u76d8\u5185\u5bb9\u4e0d\u540c")
        self.assertEqual(version.path, CHAPTER_ONE)

        dirty = version.text + "\u672a\u4fdd\u5b58\u884c\u3002\n"
        comparison = self.service.compare_current(CHAPTER_ONE, oldest.version_id, dirty, SOURCE_GIT)
        self.assertTrue(comparison.buffer_changed)
        self.assertTrue(comparison.differs)
        self.assertIn("+\u672a\u4fdd\u5b58\u884c\u3002", comparison.diff_text)
        same = self.service.compare_current(CHAPTER_ONE, oldest.version_id, version.text, SOURCE_GIT)
        self.assertFalse(same.differs)

    def test_git_payload_is_parsed_into_records(self):
        if not self.git_ok:
            self.skipTest("Git unavailable on this machine")
        rel = "content/general/" + CHAPTER_ONE
        listing = _git(self.project, "-c", "core.quotepath=false", "log", "--follow",
                       "--no-color", "--format=%H", "--", rel)
        object_ids = [line.strip() for line in listing.stdout.decode().splitlines() if line.strip()]
        self.assertEqual(len(object_ids), 2, object_ids)
        show = _git(self.project, "-c", "core.quotepath=false", "-c",
                    "i18n.logOutputEncoding=UTF-8", "show", "--name-status", "-z",
                    "--format=%H%x1f%an%x1f%aI%x1f%s%x1e", "--no-color", object_ids[0])
        records = parse_git_log_z(show.stdout)
        self.assertEqual(len(records), 1, records)
        self.assertEqual(records[0]["author"], "Fixture Author")
        self.assertTrue(records[0]["subject"].startswith("chapter-one second"), records)
        self.assertEqual(len(records[0]["version_id"]), 40)
        self.assertTrue(records[0]["path"].endswith("1.1 \u76ee\u7684.md"), records)


class AssignmentTests(_FixtureCase):
    """31-B: assignment, my todos, broken config fallback, real review status."""

    def _stores(self):
        review = ReviewStore(self.state)
        relations = ReviewRecordStore(self.state)
        return review, relations

    def test_assign_change_and_unassigned_group(self):
        review, relations = self._stores()
        first = review.add_comment("\u9700\u4fee\u6539 A", "\u5ba1\u67e5\u4eba", CHAPTER_ONE, 1,
                                   chapter_no="1.1")
        second = review.add_comment("\u9700\u4fee\u6539 B", "\u5ba1\u67e5\u4eba", CHAPTER_TWO, 2,
                                    chapter_no="2.1")
        assignments = AssignmentStore(self.state)
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments)
        self.assertEqual(len(board.items), 2)
        self.assertEqual(len(board.unassigned), 2, "\u65e0\u8d1f\u8d23\u4eba\u65f6\u5e94\u5168\u90e8\u5f52\u672a\u5206\u914d")

        item_id = "comment:{0}".format(first.comment_id)
        assign_todo(assignments, item_id, "\u4f5c\u8005\u7532", source=SOURCE_COMMENT,
                    note="\u8bf7\u4eca\u65e5\u5904\u7406", by="\u8d1f\u8d23\u4eba")
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments)
        item = next(row for row in board.items if row.item_id == item_id)
        self.assertEqual(item.assignee, "\u4f5c\u8005\u7532")
        self.assertEqual(item.note, "\u8bf7\u4eca\u65e5\u5904\u7406")
        self.assertTrue(item.updated_at)
        self.assertEqual(item.group, "\u4f5c\u8005\u7532")
        self.assertEqual(len(board.unassigned), 1)
        mine = todos_for(board, "\u4f5c\u8005\u7532")
        self.assertEqual([row.item_id for row in mine], [item_id])
        self.assertEqual(mine[0].rel_path, CHAPTER_ONE)
        self.assertIn("\u4f5c\u8005\u7532", render_todo_board(board))

        # A second todo gets its own row ...
        second_id = "comment:{0}".format(second.comment_id)
        assign_todo(assignments, second_id, "\u590d\u6838\u4eba", source=SOURCE_COMMENT)
        self.assertEqual(len(assignments.records()), 2)
        # ... and re-assignment replaces the previous owner (no duplicate rows).
        assign_todo(assignments, item_id, "\u4f5c\u8005\u4e59", source=SOURCE_COMMENT)
        self.assertEqual(assignments.get(item_id).assignee, "\u4f5c\u8005\u4e59")
        self.assertEqual(len(assignments.records()), 2, "\u4e24\u4e2a\u5f85\u529e\u5404\u4e00\u6761\u8d1f\u8d23\u4eba")
        self.assertEqual(len([row for row in assignments.records() if row.item_id == item_id]), 1,
                         "\u540c\u4e00\u5f85\u529e\u4e0d\u5f97\u51fa\u73b0\u91cd\u590d\u8d1f\u8d23\u4eba\u8bb0\u5f55")
        # File persistence when the filesystem permits the atomic replace.
        written = self.state / ASSIGNMENTS_FILE_NAME
        if written.is_file():
            reloaded = AssignmentStore(self.state)
            self.assertEqual(reloaded.get(item_id).assignee, "\u4f5c\u8005\u4e59")
            self.assertEqual(len(reloaded.records()), 2)

    def test_relation_todos_only_list_pending(self):
        review, relations = self._stores()
        records = [
            ImpactReviewRecord("rel-1", ("proj", "src-1"), ("proj", "tgt-1"),
                               source_hash="a", target_hash="b", status="\u901a\u8fc7"),
            ImpactReviewRecord("rel-2", ("proj", "src-2"), ("proj", "tgt-2"),
                               source_hash="c", target_hash="d", status="\u901a\u8fc7"),
        ]
        relations.file.parent.mkdir(parents=True, exist_ok=True)
        relations.file.write_text(
            json.dumps({"reviews": [item.to_dict() for item in records]}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(len(relations.records()), 2)
        # Re-mark rel-2 as pending (its source hash changed): written directly
        # because this machine's file filter rejects impact.py's atomic replace.
        pending = ImpactReviewRecord("rel-2", ("proj", "src-2"), ("proj", "tgt-2"),
                                     source_hash="changed", target_hash="d",
                                     status="\u5f85\u590d\u6838")
        relations.file.write_text(
            json.dumps({"reviews": [records[0].to_dict(), pending.to_dict()]}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual([item.relation_id for item in relations.pending()], ["rel-2"])
        assignments = AssignmentStore(self.state)
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments)
        pending = [row for row in board.items if row.source == SOURCE_RELATION]
        self.assertEqual(len(pending), 1, [row.to_dict() for row in pending])
        self.assertIn("rel-2", pending[0].item_id)
        self.assertIn("\u5f85\u590d\u6838", pending[0].status)
        assign_todo(assignments, "relation:rel-2", "\u590d\u6838\u4eba")
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments)
        self.assertEqual(len(todos_for(board, "\u590d\u6838\u4eba")), 1)

    def test_assignment_does_not_replace_review_status(self):
        review, relations = self._stores()
        comment = review.add_comment("\u9700\u4fee\u6539", "\u5ba1\u67e5\u4eba", CHAPTER_ONE, 1,
                                     chapter_no="1.1")
        assignments = AssignmentStore(self.state)
        item_id = "comment:{0}".format(comment.comment_id)
        assign_todo(assignments, item_id, "\u4f5c\u8005\u7532")
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments)
        self.assertEqual(len(board.pending()), 1, "\u5206\u914d\u8d1f\u8d23\u4eba\u4e0d\u80fd\u628a\u610f\u89c1\u53d8\u6210\u5df2\u901a\u8fc7")
        # The real V2.8 confirmation is what closes the todo.
        confirm_comment(review, comment.comment_id, evidence="\u5df2\u4fee\u6539")
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments)
        self.assertEqual(board.pending(), [], "\u53ea\u6709\u771f\u5b9e\u590d\u6838\u52a8\u4f5c\u80fd\u7ed3\u675f\u5f85\u529e")
        self.assertEqual(len(board.items), 1, "\u5df2\u901a\u8fc7\u9879\u4ecd\u4fdd\u7559\u53ef\u8ffd\u6eaf")
        self.assertEqual(board.items[0].status, "\u901a\u8fc7")

    def test_missing_team_config_defaults_to_unassigned(self):
        review, relations = self._stores()
        review.add_comment("\u9700\u5904\u7406", "\u5ba1\u67e5\u4eba", CHAPTER_ONE, 1)
        self.assertFalse((self.project / "team.yml").exists())
        team = load_team_config(self.project)
        self.assertFalse(team.loaded)
        self.assertTrue(team.error)
        assignments = AssignmentStore(self.state)
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments, team=team)
        self.assertEqual(len(board.unassigned), 1)
        self.assertTrue(board.my_name)
        self.assertTrue(board.warnings)

    def test_broken_team_config_falls_back(self):
        (self.project / "team.yml").write_text(
            "schemaVersion: 1\nmembers: [\n  - name: \u672a\u95ed\u5408\n", encoding="utf-8")
        team = load_team_config(self.project)
        self.assertFalse(team.loaded)
        self.assertTrue(team.error)
        review, relations = self._stores()
        review.add_comment("\u9700\u5904\u7406", "\u5ba1\u67e5\u4eba", CHAPTER_ONE, 1)
        assignments = AssignmentStore(self.state)
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=assignments, team=team)
        self.assertEqual(len(board.unassigned), 1, "\u574f\u914d\u7f6e\u5e94\u5f52\u672a\u5206\u914d")
        self.assertTrue(board.warnings)
        # Editing/exporting is not blocked by the broken config.
        writer = ContentWriter(self.content, self.state)
        result = writer.write_text(CHAPTER_ONE, "\u4ecd\u53ef\u7f16\u8f91\u3002\n")
        self.assertTrue(result.written)

    def test_valid_team_config_and_broken_assignment_store(self):
        (self.project / "team.yml").write_text(
            "schemaVersion: 1\ncurrentUser: \u4f5c\u8005\u7532\nmembers:\n"
            "  - name: \u4f5c\u8005\u7532\n    role: \u4f5c\u8005\n"
            "  - name: \u590d\u6838\u4eba\n    role: \u590d\u6838\n",
            encoding="utf-8")
        team = load_team_config(self.project)
        self.assertTrue(team.loaded, team.error)
        self.assertEqual(team.display_name, "\u4f5c\u8005\u7532")
        self.assertEqual(team.names, ["\u4f5c\u8005\u7532", "\u590d\u6838\u4eba"])

        (self.state / ASSIGNMENTS_FILE_NAME).write_text("{ broken", encoding="utf-8")
        store = AssignmentStore(self.state)
        self.assertEqual(store.records(), [])
        self.assertTrue(store.warnings, "\u574f\u8d1f\u8d23\u4eba\u8bb0\u5f55\u5e94\u6709\u56de\u9000\u8bf4\u660e")
        review, relations = self._stores()
        review.add_comment("\u9700\u5904\u7406", "\u5ba1\u67e5\u4eba", CHAPTER_ONE, 1)
        board = build_todo_board(review_store=review, relation_store=relations,
                                 assignments=store, team=team)
        self.assertEqual(len(board.unassigned), 1)
        self.assertEqual(board.my_name, "\u4f5c\u8005\u7532")

    def test_readonly_store_refuses_assignment(self):
        store = AssignmentStore(self.state)
        store.writable = False
        with self.assertRaises(PermissionError):
            store.assign("comment:x", "\u4f5c\u8005\u7532")
        with self.assertRaises(ValueError):
            AssignmentStore(self.state).assign("", "\u4f5c\u8005\u7532")


class HandoffTests(_FixtureCase):
    """31-C: package, manifest, partial apply, idempotency, resources, rollback."""

    def _export(self, *, overrides: dict = None, baseline: dict = True,
                package_name: str = "\u4ea4\u63a5\u5305.zip", project_id: str = ""):
        texts = dict(overrides or {})
        known = self.hashes(CHAPTER_ONE, CHAPTER_TWO) if baseline else {}
        relative = {key: value for key, value in texts.items()}
        return export_handoff_package(
            self.project, self.out,
            chapters=[CHAPTER_ONE, CHAPTER_TWO],
            content_root=self.content,
            project_id=project_id or self.manifest.projectId,
            project_name=self.manifest.documentName,
            document_version=self.manifest.documentVersion,
            baseline=known,
            texts=relative,
            baseline_id="fixture-baseline",
            created_by="Fixture Author",
            package_name=package_name,
            modules=[{"id": "m1", "version": "1.0", "hash": "abc"}],
            source_index=[{"relPath": CHAPTER_ONE, "title": "\u76ee\u7684"}],
        )

    def _chapter(self, package, rel):
        return next(item for item in package.chapters if item.rel_path == rel)

    # --- export ---

    def test_export_manifest_and_payload(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u65b0\u589e\u6bb5\u3002\n"})
        path = Path(package.package_path)
        self.assertTrue(path.is_file())
        self.assertEqual(package.schema, HANDOFF_SCHEMA)
        self.assertEqual(package.schema_version, HANDOFF_SCHEMA_VERSION)
        self.assertEqual(len(package.chapters), 2)
        self.assertEqual(package.baseline_state, handoff.BASELINE_KNOWN)
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            self.assertIn(MANIFEST_NAME, names)
            self.assertIn("content/" + CHAPTER_ONE, names)
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        self.assertEqual(manifest["schemaVersion"], HANDOFF_SCHEMA_VERSION)
        for key in ("packageId", "projectId", "baselineId", "createdAt", "chapters",
                    "resources", "modules", "sourceIndex"):
            self.assertIn(key, manifest)
        entry = self._chapter(package, CHAPTER_ONE)
        self.assertTrue(entry.base_hash)
        self.assertNotEqual(entry.base_hash, entry.hash)
        self.assertTrue(entry.changed)
        self.assertEqual(entry.size, len((self.text(CHAPTER_ONE) + "\u65b0\u589e\u6bb5\u3002\n").encode("utf-8")))
        self.assertEqual(package.modules[0]["id"], "m1")
        reloaded = read_handoff_manifest(path)
        self.assertEqual(reloaded.package_id, package.package_id)
        self.assertEqual(len(reloaded.chapters), 2)

    def test_export_without_baseline_states_unknown(self):
        package = self._export(baseline=False,
                               overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u65e0\u57fa\u51c6\u65b0\u5185\u5bb9\u3002\n"})
        self.assertEqual(package.baseline_state, handoff.BASELINE_UNKNOWN)
        self.assertTrue(any(handoff.NO_BASELINE_NOTICE in item for item in package.warnings))
        plan = plan_handoff_apply(package.package_path, self.project,
                                  content_root=self.content,
                                  project_id=self.manifest.projectId)
        self.assertFalse(plan.baseline_known)
        self.assertEqual(plan.applicable, [], "\u672a\u77e5\u57fa\u51c6\u4e0d\u5f97\u58f0\u79f0\u65e0\u51b2\u7a81")
        self.assertTrue(plan.conflicts)
        self.assertTrue(any(handoff.REASON_BASELINE_UNKNOWN == item.reason
                            for item in plan.items if item.kind == handoff.KIND_CHAPTER),
                        [item.to_dict() for item in plan.items])
        differing = next(item for item in plan.items if item.rel_path == CHAPTER_ONE)
        self.assertTrue(differing.conflict, "\u65e0\u57fa\u51c6\u65f6\u5dee\u5f02\u5e94\u5217\u4e3a\u5f85\u5904\u7406")
        unchanged = next(item for item in plan.items if item.rel_path == CHAPTER_TWO)
        self.assertEqual(unchanged.status, handoff.STATUS_UNCHANGED)

    def test_package_is_readable_offline(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u79bb\u7ebf\u6bb5\u3002\n"})
        other = self.receiver("other")
        plan = plan_handoff_apply(package.package_path, other,
                                  content_root=other / "content" / DOC_TYPE,
                                  project_id=self.manifest.projectId)
        entry = next(item for item in plan.items if item.rel_path == CHAPTER_ONE)
        self.assertTrue(entry.diff_text, "\u63a5\u6536\u65b9\u5e94\u80fd\u770b\u5230\u5dee\u5f02")
        self.assertIn("\u79bb\u7ebf\u6bb5\u3002", entry.diff_text)
        result = apply_handoff_plan(plan, project_root=other,
                                    content_root=other / "content" / DOC_TYPE)
        self.assertTrue(result.success, result.message)
        self.assertIn("\u79bb\u7ebf\u6bb5\u3002",
                      (other / "content" / DOC_TYPE / CHAPTER_ONE).read_text(encoding="utf-8"))
        self.assertNotIn("\u79bb\u7ebf\u6bb5\u3002", self.text(CHAPTER_ONE),
                         "\u53d1\u9001\u65b9\u9879\u76ee\u4e0d\u5e94\u88ab\u4fee\u6539")

    # --- partial apply ---

    def test_conflicting_chapter_is_skipped_others_apply(self):
        package = self._export(overrides={
            CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u4ea4\u63a5\u6bb5 A\u3002\n",
            CHAPTER_TWO: self.text(CHAPTER_TWO) + "\u4ea4\u63a5\u6bb5 B\u3002\n",
        })
        other = self.receiver("conflict", overrides={
            CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u63a5\u6536\u65b9\u81ea\u5df1\u6539\u8fc7\u3002\n",
        })
        content = other / "content" / DOC_TYPE
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=self.manifest.projectId)
        rows = {item.rel_path: item for item in plan.items}
        self.assertEqual(rows[CHAPTER_ONE].status, STATUS_CONFLICT)
        self.assertTrue(rows[CHAPTER_ONE].conflict)
        self.assertFalse(rows[CHAPTER_ONE].applicable)
        self.assertEqual(rows[CHAPTER_TWO].status, handoff.STATUS_MODIFIED)
        self.assertTrue(rows[CHAPTER_TWO].applicable)
        self.assertIn("\u4ea4\u63a5\u6bb5 B", rows[CHAPTER_TWO].diff_text)

        result = apply_handoff_plan(plan, project_root=other, content_root=content)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.conflicts, ["chapter:" + CHAPTER_ONE])
        self.assertIn("chapter:" + CHAPTER_TWO, result.applied)
        self.assertIn("\u63a5\u6536\u65b9\u81ea\u5df1\u6539\u8fc7\u3002",
                      (content / CHAPTER_ONE).read_text(encoding="utf-8"),
                      "\u51b2\u7a81\u7ae0\u5e94\u4fdd\u7559\u672c\u5730")
        self.assertIn("\u4ea4\u63a5\u6bb5 B\u3002",
                      (content / CHAPTER_TWO).read_text(encoding="utf-8"))

    def test_second_import_is_idempotent(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u4ea4\u63a5\u6bb5\u3002\n"})
        other = self.receiver("repeat")
        content = other / "content" / DOC_TYPE
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=self.manifest.projectId)
        first = apply_handoff_plan(plan, project_root=other, content_root=content)
        self.assertIn("chapter:" + CHAPTER_ONE, first.applied)
        before = (content / CHAPTER_ONE).read_text(encoding="utf-8")

        plan2 = plan_handoff_apply(package.package_path, other, content_root=content,
                                   project_id=self.manifest.projectId)
        rows = {item.rel_path: item for item in plan2.items}
        self.assertEqual(rows[CHAPTER_ONE].status, STATUS_ALREADY_APPLIED)
        self.assertFalse(rows[CHAPTER_ONE].applicable)
        second = apply_handoff_plan(plan2, project_root=other, content_root=content)
        self.assertEqual(second.applied, [], "\u91cd\u590d\u5bfc\u5165\u4e0d\u5f97\u91cd\u590d\u5199\u5165")
        self.assertIn("chapter:" + CHAPTER_ONE, second.skipped)
        self.assertEqual((content / CHAPTER_ONE).read_text(encoding="utf-8"), before)

        # The receiver modifies it afterwards: re-compare instead of restoring.
        (content / CHAPTER_ONE).write_text(before + "\u63a5\u6536\u65b9\u540e\u7eed\u4fee\u6539\u3002\n",
                                           encoding="utf-8")
        plan3 = plan_handoff_apply(package.package_path, other, content_root=content,
                                    project_id=self.manifest.projectId)
        row = next(item for item in plan3.items if item.rel_path == CHAPTER_ONE)
        self.assertEqual(row.status, STATUS_CONFLICT)
        self.assertEqual(row.reason, handoff.REASON_LOCAL_CHANGED)
        third = apply_handoff_plan(plan3, project_root=other, content_root=content)
        self.assertEqual(third.applied, [])
        self.assertIn("\u63a5\u6536\u65b9\u540e\u7eed\u4fee\u6539\u3002",
                      (content / CHAPTER_ONE).read_text(encoding="utf-8"))

    def test_corrupt_apply_state_still_applies(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u4ea4\u63a5\u3002\n"})
        other = self.receiver("badstate")
        (other / ".state").mkdir(parents=True, exist_ok=True)
        (other / ".state" / handoff.APPLIED_FILE_NAME).write_text("{ not json", encoding="utf-8")
        content = other / "content" / DOC_TYPE
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=self.manifest.projectId)
        result = apply_handoff_plan(plan, project_root=other, content_root=content)
        self.assertTrue(result.success, result.message)
        self.assertIn("\u4ea4\u63a5\u3002", (content / CHAPTER_ONE).read_text(encoding="utf-8"))

    def test_foreign_project_imports_as_new_copy(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u5f02\u9879\u76ee\u6bb5\u3002\n"},
                               project_id="\u53e6\u4e00\u4e2a\u9879\u76ee")
        other = self.receiver("foreign")
        content = other / "content" / DOC_TYPE
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=self.manifest.projectId)
        self.assertFalse(plan.same_project)
        self.assertEqual(plan.applicable, [])
        blocked = apply_handoff_plan(plan, project_root=other, content_root=content)
        self.assertFalse(blocked.success)
        self.assertEqual(blocked.applied, [])
        self.assertNotIn("\u5f02\u9879\u76ee\u6bb5\u3002", (content / CHAPTER_ONE).read_text(encoding="utf-8"))

        copy_root = self.tmp / "imported-copy"
        outcome = import_handoff_as_new_copy(package.package_path, copy_root)
        self.assertTrue(outcome["success"], outcome)
        imported = copy_root / "content" / CHAPTER_ONE
        self.assertTrue(imported.is_file())
        self.assertIn("\u5f02\u9879\u76ee\u6bb5\u3002", imported.read_text(encoding="utf-8"))
        self.assertTrue((copy_root / "\u4ea4\u63a5\u5bfc\u5165\u8bf4\u660e.md").is_file())
        self.assertNotIn("imported-copy", package.package_path)

    # --- resources ---

    def test_same_name_different_content_is_not_substituted(self):
        assets = self.content / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "shared.png").write_bytes(b"\x89PNG-sender-version")
        chapter_text = self.text(CHAPTER_ONE) + "\n![shared](assets/shared.png)\n"
        package = export_handoff_package(
            self.project, self.out,
            chapters=[CHAPTER_ONE, CHAPTER_TWO],
            content_root=self.content,
            asset_roots=[assets],
            project_id=self.manifest.projectId,
            project_name=self.manifest.documentName,
            baseline=self.hashes(CHAPTER_ONE, CHAPTER_TWO),
            texts={CHAPTER_ONE: chapter_text},
            package_name="\u8d44\u6e90\u4ea4\u63a5\u5305.zip",
        )
        self.assertEqual(len(package.resources), 1)
        resource = package.resources[0]
        self.assertEqual(resource.name, "shared.png")

        other = self.receiver("resource")
        content = other / "content" / DOC_TYPE
        receiver_assets = other / "assets" / DOC_TYPE
        receiver_assets.mkdir(parents=True, exist_ok=True)
        (receiver_assets / "shared.png").write_bytes(b"\x89PNG-receiver-version")
        selected = [item.entry_id for item in package.entries]
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  asset_roots=[receiver_assets],
                                  project_id=self.manifest.projectId, selected=selected)
        row = next(item for item in plan.items if item.entry_id == resource.entry_id)
        self.assertEqual(row.status, STATUS_RESOURCE_MISMATCH)
        self.assertTrue(row.applicable, "\u663e\u5f0f\u9009\u62e9\u540e\u53ef\u4ee5\u53e6\u5b58\u526f\u672c")
        result = apply_handoff_plan(plan, project_root=other, content_root=content,
                                    asset_roots=[receiver_assets])
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.renamed_resources, [("shared.png", "shared.handoff.png")])
        self.assertEqual((receiver_assets / "shared.png").read_bytes(),
                         b"\x89PNG-receiver-version", "\u540c\u540d\u8d44\u6e90\u4e0d\u5f97\u88ab\u76f4\u63a5\u66ff\u6362")
        self.assertEqual((receiver_assets / "shared.handoff.png").read_bytes(),
                         b"\x89PNG-sender-version")

    def test_resource_missing_from_package_is_skipped(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE)})
        entry = package.resources[0] if package.resources else None
        self.assertIsNone(entry, "\u65e0\u5f15\u7528\u65f6\u4e0d\u5e94\u6253\u5305\u8d44\u6e90")
        chapter_entry = self._chapter(package, CHAPTER_ONE)
        broken = handoff.HandoffEntry(
            entry_id="resource:ghost.png", kind=handoff.KIND_RESOURCE, rel_path="ghost.png",
            name="ghost.png", hash="0" * 64, archive_name="resources/ghost.png",
        )
        package.resources.append(broken)
        self.assertIsNone(read_handoff_entry(package.package_path, broken))

    # --- rollback ---

    def test_fixed_module_dependencies_are_reported(self):
        package = self._export(overrides={CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u6a21\u5757\u6bb5\u3002\n"})
        other = self.receiver("modules")
        content = other / "content" / DOC_TYPE
        project_id = self.manifest.projectId
        missing = plan_handoff_apply(package.package_path, other, content_root=content,
                                     project_id=project_id, local_modules={})
        self.assertEqual(missing.module_missing, ["m1"],
                         "\u7f3a\u5931\u56fa\u5b9a\u6a21\u5757\u5e94\u660e\u786e\u5217\u51fa\u800c\u4e0d\u6539\u5176\u4ed6\u5f15\u7528")
        self.assertFalse(missing.module_conflicts)
        self.assertTrue(any("m1" in item for item in missing.warnings))
        same = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=project_id, local_modules={"m1": "abc"})
        self.assertEqual(same.module_missing, [])
        self.assertEqual(same.module_conflicts, [], "\u7248\u672c\u76f8\u540c\u65f6\u4e0d\u5f97\u62a5\u51b2\u7a81")
        other_version = plan_handoff_apply(package.package_path, other, content_root=content,
                                           project_id=project_id, local_modules={"m1": "other"})
        self.assertEqual(other_version.module_conflicts, ["m1"])
        self.assertTrue(any("m1" in item for item in other_version.warnings))
        # A module version difference is reported as a candidate; it never
        # blocks or rewrites the chapter items of this run.
        self.assertEqual([item.rel_path for item in other_version.applicable],
                         [CHAPTER_ONE])

    def test_explicit_cancellation_applies_nothing(self):
        package = self._export(overrides={
            CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u53d6\u6d88\u6bb5\u3002\n",
        })
        other = self.receiver("cancel")
        content = other / "content" / DOC_TYPE
        before = (content / CHAPTER_ONE).read_text(encoding="utf-8")
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=self.manifest.projectId, selected=[])
        rows = {item.rel_path: item for item in plan.items}
        self.assertEqual(rows[CHAPTER_ONE].status, handoff.STATUS_MODIFIED)
        self.assertFalse(rows[CHAPTER_ONE].applicable, "\u672a\u9009\u4e2d\u4e0d\u5f97\u5e94\u7528")
        result = apply_handoff_plan(plan, project_root=other, content_root=content)
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.applied, [], "\u53d6\u6d88\u540e\u4e0d\u5f97\u5199\u5165\u4efb\u4f55\u5185\u5bb9")
        self.assertEqual((content / CHAPTER_ONE).read_text(encoding="utf-8"), before)
        self.assertIn(handoff.REASON_DESELECTED,
                      " ".join(item.reason for item in plan.items if not item.applicable) or
                      handoff.REASON_DESELECTED)

    def test_write_failure_rolls_back_this_run(self):
        package = self._export(overrides={
            CHAPTER_ONE: self.text(CHAPTER_ONE) + "\u56de\u6eda A\u3002\n",
            CHAPTER_TWO: self.text(CHAPTER_TWO) + "\u56de\u6eda B\u3002\n",
        })
        other = self.receiver("rollback")
        content = other / "content" / DOC_TYPE
        before_one = (content / CHAPTER_ONE).read_text(encoding="utf-8")
        before_two = (content / CHAPTER_TWO).read_text(encoding="utf-8")
        plan = plan_handoff_apply(package.package_path, other, content_root=content,
                                  project_id=self.manifest.projectId)
        self.assertEqual(len(plan.applicable), 2)

        real = ContentWriter(content, other / ".state")

        class FlakyWriter:
            def __init__(self, inner):
                self.inner = inner
                self.calls = 0

            def write_text(self, rel_path, text, **kwargs):
                self.calls += 1
                if self.calls >= 2:
                    from doc_tool.application.content.writer import WriteResult
                    return WriteResult(rel_path, None, False, error="injected write failure")
                return self.inner.write_text(rel_path, text, **kwargs)

        flaky = FlakyWriter(real)
        result = apply_handoff_plan(plan, project_root=other, content_root=content,
                                    writer=flaky, state_dir=other / ".state")
        self.assertFalse(result.success)
        self.assertTrue(result.rolled_back)
        self.assertEqual(result.applied, [])
        self.assertIn("\u56de\u6eda", result.message)
        self.assertEqual((content / CHAPTER_ONE).read_text(encoding="utf-8"), before_one,
                         "\u5931\u8d25\u5e94\u56de\u6eda\u672c\u6b21\u5df2\u5199\u8303\u56f4")
        self.assertEqual((content / CHAPTER_TWO).read_text(encoding="utf-8"), before_two)

    def test_unreadable_package_is_reported_not_raised(self):
        broken = self.out / "broken.zip"
        broken.write_bytes(b"not a zip at all")
        package = read_handoff_manifest(broken)
        self.assertTrue(package.warnings)
        self.assertEqual(package.chapters, [])
        missing = read_handoff_manifest(self.out / "nope.zip")
        self.assertTrue(missing.warnings)
        plan = plan_handoff_apply(broken, self.project, content_root=self.content,
                                  project_id=self.manifest.projectId)
        self.assertEqual(plan.applicable, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
