"""V26-B recovery safety, quotas, corruption and writer integration."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_tool.application.content.local_history import LocalHistoryStore
from doc_tool.application.content.writer import ContentWriter, PathOutsideContentError


class LocalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.content = self.root / "content"
        self.content.mkdir()
        self.state = self.root / ".state"
        self.rel = "第1章/正文.md"
        self.path = self.content / self.rel
        self.path.parent.mkdir()
        self.path.write_bytes("初稿\r\n".encode("utf-8"))
        self.writer = ContentWriter(self.content, self.state)
        self.store = self.writer.local_history

    def entries(self):
        return self.store.list_entries(self.rel, include_backup=False)

    def test_three_saves_preview_diff_restore_and_restore_again(self):
        before = self.path.read_bytes()
        first = self.writer.write_text(self.rel, "第二版")
        self.writer.write_text(self.rel, "第三版")
        self.writer.write_text(self.rel, "第四版")
        self.assertEqual(len(self.entries()), 3)
        self.assertEqual(self.store.read_bytes(self.rel, first.history_id), before)
        self.assertIn("第四版", self.store.diff(self.rel, first.history_id))
        restored = self.store.restore(self.rel, first.history_id, self.writer, confirmed=True)
        self.assertTrue(restored.written)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.preview(self.rel, restored.history_id), "第四版")
        again = self.store.restore(self.rel, restored.history_id, self.writer, confirmed=True)
        self.assertTrue(again.written)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "第四版")

    def test_preview_and_open_do_not_write_or_create_history(self):
        self.store.list_entries(self.rel)
        self.assertFalse(self.state.exists())
        result = self.writer.write_text(self.rel, "第二版")
        before = {p: p.read_bytes() for p in self.state.rglob("*") if p.is_file()}
        for _ in range(3):
            LocalHistoryStore(self.content, self.state, writable=False).preview(self.rel, result.history_id)
            self.store.list_entries(self.rel)
            self.store.diff(self.rel, result.history_id)
        self.assertEqual(before, {p: p.read_bytes() for p in self.state.rglob("*") if p.is_file()})

    def test_history_failure_uses_fresh_backup_in_local_and_vcs_modes(self):
        for enabled in (True, False):
            self.path.write_bytes(b"current old")
            self.writer.set_backup_enabled(enabled)
            with patch.object(self.store, "capture", side_effect=OSError("history disk full")):
                result = self.writer.write_text(self.rel, "new")
            self.assertTrue(result.written, result.error)
            self.assertEqual(Path(result.backup_path).read_bytes(), b"current old")
            self.assertTrue(any("降级" in warning for warning in result.warnings))

    def test_stale_backup_is_not_a_recovery_point_when_all_writes_fail(self):
        backup = self.path.with_name(self.path.name + ".bak")
        backup.write_bytes(b"stale")
        before = self.path.read_bytes()
        with patch.object(self.store, "capture", side_effect=OSError("history failed")), \
             patch.object(self.writer, "_backup", return_value=(None, True)), \
             patch("doc_tool.application.content.writer.atomic_write_bytes", side_effect=OSError("backup failed")):
            result = self.writer.write_text(self.rel, "must not overwrite")
        self.assertFalse(result.written)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(backup.read_bytes(), b"stale")

    def test_failed_compatibility_backup_keeps_valid_snapshot_and_reports_warning(self):
        with patch.object(self.writer, "_backup", return_value=(None, True)):
            result = self.writer.write_text(self.rel, "new")
        self.assertTrue(result.written)
        self.assertTrue(result.history_id)
        self.assertTrue(result.warnings)
        self.assertEqual(self.store.preview(self.rel, result.history_id), "初稿\r\n")

    def test_index_write_failure_does_not_block_save_and_can_rebuild(self):
        with patch.object(self.store, "rebuild_index", side_effect=OSError("index full")):
            result = self.writer.write_text(self.rel, "new")
        self.assertTrue(result.written)
        self.assertTrue(any("索引" in w for w in result.warnings))
        self.assertEqual(len(self.entries()), 1)
        self.store.rebuild_index(self.rel)
        data = json.loads((self.store._folder(self.rel) / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(data["entries"][0]["snapshot_id"], result.history_id)

    def test_corrupt_index_is_readable_without_writing_then_explicit_rebuild(self):
        result = self.writer.write_text(self.rel, "new")
        index = self.store._folder(self.rel) / "index.json"
        index.write_text("broken", encoding="utf-8")
        self.assertEqual(self.entries()[0].snapshot_id, result.history_id)
        self.assertEqual(index.read_text(), "broken")
        self.store.rebuild_index(self.rel)
        self.assertEqual(json.loads(index.read_text())["schemaVersion"], 1)

    def test_count_quota_and_newest_are_preserved(self):
        for n in range(25):
            self.assertTrue(self.writer.write_text(self.rel, str(n)).written)
        entries = self.entries()
        self.assertEqual(len(entries), 20)
        self.assertEqual(self.store.preview(self.rel, entries[0].snapshot_id), "23")
        self.assertEqual(self.store.preview(self.rel, entries[-1].snapshot_id), "4")

    def test_byte_quota_oversized_required_snapshot_and_restore_protection(self):
        self.store.max_bytes = 4
        self.path.write_bytes(b"123456")
        result = self.writer.write_text(self.rel, "x")
        self.assertTrue(result.written)
        self.assertEqual(len(self.entries()), 1)
        self.assertTrue(any("上限" in w or "配额" in w for w in result.warnings))
        restored = self.store.restore(self.rel, result.history_id, self.writer, confirmed=True)
        self.assertTrue(restored.written)
        self.store.max_entries = 1
        self.writer.write_text(self.rel, "new")
        ids = {entry.snapshot_id for entry in self.entries()}
        self.assertIn(restored.history_id, ids)
        self.assertEqual(len(ids), 2)  # newest plus necessary pre-restore point

    def test_legacy_backup_read_and_restore_preserves_current(self):
        backup = self.path.with_name(self.path.name + ".bak")
        backup.write_bytes(b"legacy content")
        self.assertEqual(self.store.list_entries(self.rel)[0].snapshot_id, "legacy-bak")
        self.assertFalse(self.state.exists())
        result = self.store.restore(self.rel, "legacy-bak", self.writer, confirmed=True)
        self.assertTrue(result.written)
        self.assertEqual(self.path.read_bytes(), b"legacy content")
        self.assertEqual(self.store.preview(self.rel, result.history_id), "初稿\r\n")

    def test_cancel_readonly_stale_plan_and_cross_project_do_not_write(self):
        first = self.writer.write_text(self.rel, "current")
        before = self.path.read_bytes()
        count = len(self.entries())
        self.assertIsNone(self.store.restore(self.rel, first.history_id, self.writer))
        with self.assertRaises(ValueError):
            self.store.restore(self.rel, first.history_id, self.writer, confirmed=True, expected_sha256="stale")
        other = ContentWriter(self.content, self.root / "other-state")
        with self.assertRaises(ValueError):
            self.store.restore(self.rel, first.history_id, other, confirmed=True)
        self.writer.set_writable(False)
        self.assertFalse(self.writer.write_text(self.rel, "no").written)
        self.assertEqual(self.store.preview(self.rel, first.history_id), "初稿\r\n")
        with self.assertRaises(PermissionError):
            self.store.restore(self.rel, first.history_id, self.writer, confirmed=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.entries()), count)

    def test_broken_metadata_and_content_are_reported_and_not_deleted(self):
        first = self.writer.write_text(self.rel, "second")
        second = self.writer.write_text(self.rel, "third")
        damaged = self.store._snapshot_folder(self.rel, first.history_id) / "content.md"
        damaged.write_bytes(b"corrupt")
        self.assertEqual([e.snapshot_id for e in self.entries()], [second.history_id])
        self.assertTrue(self.store.warnings)
        with self.assertRaises(ValueError):
            self.store.restore(self.rel, first.history_id, self.writer, confirmed=True)
        self.assertTrue(damaged.exists())
        self.assertEqual(self.path.read_bytes(), b"third")

    def test_malicious_metadata_and_snapshot_identifiers_rejected(self):
        first = self.writer.write_text(self.rel, "second")
        metadata = self.store._snapshot_folder(self.rel, first.history_id) / "metadata.json"
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["rel_path"] = "../../outside.md"
        metadata.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.entries(), [])
        for rel, identifier in [("../../outside.md", first.history_id), (self.rel, "../../evil")]:
            with self.assertRaises(ValueError):
                self.store.preview(rel, identifier)
        self.assertEqual(self.path.read_text(), "second")

    def test_new_file_save_needs_no_old_recovery_point(self):
        with patch.object(self.store, "capture", side_effect=OSError("unavailable")):
            result = self.writer.write_text("new.md", "first version")
        self.assertTrue(result.written)
        self.assertIsNone(result.history_id)

    def test_locked_output_failure_retains_old_content_and_snapshot(self):
        before = self.path.read_bytes()
        with patch("doc_tool.application.content.writer.atomic_write", side_effect=OSError("sharing violation")):
            result = self.writer.write_text(self.rel, "new")
        self.assertFalse(result.written)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(Path(result.backup_path).read_bytes(), before)

    def test_vcs_snapshot_is_available_to_existing_rollback_transaction(self):
        self.writer.set_backup_enabled(False)
        self.writer.write_text(self.rel, "new")
        self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())
        self.assertEqual(self.writer.rollback(), [])
        self.assertEqual(self.path.read_bytes(), "初稿\r\n".encode("utf-8"))

    def test_symlinked_content_and_backup_cannot_read_or_write_outside(self):
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "secret.md"
            outside_file.write_bytes(b"untouched")
            link = self.content / "link.md"
            try:
                link.symlink_to(outside_file)
            except OSError:
                self.skipTest("symlink privilege unavailable")
            self.assertFalse(self.writer.write_text("link.md", "new").written)
            with self.assertRaises(PathOutsideContentError):
                self.store.list_entries("link.md")
            backup = self.path.with_name(self.path.name + ".bak")
            backup.symlink_to(outside_file)
            result = self.writer.write_text(self.rel, "new")
            self.assertTrue(result.written)  # safe snapshot allows .bak downgrade
            self.assertEqual(outside_file.read_bytes(), b"untouched")


    def test_per_file_quotas_and_protected_active_snapshot(self):
        self.store.max_entries = 1
        first = self.store.capture(self.rel, b"old")
        self.store.capture(self.rel, b"new")
        self.writer.write_text("other.md", "first")
        self.writer.write_text("other.md", "second")
        self.store.prune(self.rel, protected=[first.snapshot_id])
        self.assertEqual(len(self.entries()), 2)
        self.assertEqual(len(self.store.list_entries("other.md", include_backup=False)), 1)
        self.store.prune(self.rel)
        self.assertEqual(len(self.entries()), 1)

    def test_matching_content_hash_allows_restore(self):
        saved = self.writer.write_text(self.rel, "current")
        current_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        restored = self.store.restore(self.rel, saved.history_id, self.writer,
                                      confirmed=True, expected_sha256=current_hash)
        self.assertTrue(restored.written)

    def test_invalid_optional_backup_does_not_hide_verified_history(self):
        from doc_tool.application.content.writer import _resolve_inside
        saved = self.writer.write_text(self.rel, "current")

        def resolve(root, rel):
            if rel.endswith(".bak"):
                raise PathOutsideContentError("outside backup")
            return _resolve_inside(root, rel)

        with patch("doc_tool.application.content.local_history._resolve_inside", side_effect=resolve):
            entries = self.store.list_entries(self.rel)
        self.assertEqual([e.snapshot_id for e in entries], [saved.history_id])
        self.assertTrue(any("其他历史" in w for w in self.store.warnings))

    def test_replace_and_refactor_share_history_and_vcs_transaction_rollback(self):
        from doc_tool.application.content.replace import ReplaceMatch, ReplaceService
        from doc_tool.application.content.refactor import EditOp, RenamePlan, RefactorService
        from doc_tool.domain.content_index import ContentIndex

        self.writer.set_backup_enabled(False)
        self.path.write_text("old text", encoding="utf-8")
        index = ContentIndex()
        match = ReplaceMatch(self.rel, 1, "old text", 0, 3)
        replaced = ReplaceService(index).apply_matches([match], "new", self.writer)[0]
        self.assertTrue(replaced.written)
        self.assertEqual(self.entries()[0].operation, "replace")
        self.assertEqual(self.store.preview(self.rel, replaced.history_id), "old text")
        plan = RenamePlan(self.rel, "renamed.md", edits=[EditOp(self.rel, 1, "new", "changed")])
        with patch.object(self.writer, "rename", side_effect=OSError("move denied")):
            with self.assertRaises(OSError):
                RefactorService(index).apply_rename_plan(plan, self.writer)
        self.assertEqual(self.path.read_text(), "new text")
        self.assertEqual(self.entries()[0].operation, "refactor")


    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_history_junction_is_rejected_and_backup_fallback_stays_inside_project(self):
        import subprocess

        with tempfile.TemporaryDirectory() as outside:
            self.state.mkdir()
            env = os.environ.copy()
            env["V26_HISTORY_LINK"] = str(self.store.root)
            env["V26_HISTORY_TARGET"] = outside
            junction = subprocess.run(["powershell", "-NoProfile", "-Command",
                "New-Item -ItemType Junction -Path $env:V26_HISTORY_LINK -Target $env:V26_HISTORY_TARGET | Out-Null"],
                env=env, capture_output=True, timeout=15)
            self.assertEqual(junction.returncode, 0)
            try:
                with self.assertRaises(PathOutsideContentError):
                    self.store.list_entries(self.rel)
                result = self.writer.write_text(self.rel, "new")
                self.assertTrue(result.written)
                self.assertTrue(result.warnings)
                self.assertEqual(list(Path(outside).iterdir()), [])
                self.assertEqual(Path(result.backup_path).read_bytes(), "初稿\r\n".encode("utf-8"))
            finally:
                self.store.root.rmdir()

    def test_editor_preserves_dirty_buffer_on_failure_and_shows_history_downgrade(self):
        from PySide6.QtWidgets import QApplication
        from doc_tool.ui.content.editor_panel import EditorPanel

        app = QApplication.instance() or QApplication([])
        panel = EditorPanel(self.writer)
        self.addCleanup(panel.close)
        panel.load(self.rel, self.path.read_text(encoding="utf-8"))
        panel._editor.setPlainText("unsaved content")
        with patch.object(self.store, "capture", side_effect=OSError("history full")):
            self.assertTrue(panel.save())
        self.assertIn("降级", panel._status_label.text())
        panel._editor.setPlainText("must stay dirty")
        with patch.object(self.store, "capture", side_effect=OSError("history full")), \
             patch.object(self.writer, "_backup", return_value=(None, True)), \
             patch("doc_tool.application.content.writer.atomic_write_bytes", side_effect=OSError("backup full")):
            self.assertFalse(panel.save())
        self.assertTrue(panel._dirty)
        self.assertEqual(panel._editor.toPlainText(), "must stay dirty")
        self.assertEqual(self.path.read_text(), "unsaved content")


if __name__ == "__main__":
    unittest.main()
