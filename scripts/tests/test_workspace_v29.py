# -*- coding: utf-8 -*-
"""V2.9 29-A\uff1a\u5de5\u4f5c\u533a schema\u3001\u6210\u5458\u52a0\u5165\u4e0e\u6982\u89c8\uff081.1\uff5e1.4\uff09\u3002"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_project_build as T  # noqa: E402
from doc_tool.application.workspace import (  # noqa: E402
    WORKSPACE_NAME,
    add_project,
    create_workspace,
    load_workspace,
    workspace_overview,
)
from doc_tool.domain.errors import ProjectManifestError  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402


class WorkspaceSchemaTests(unittest.TestCase):
    """1.1\uff1aschema\u3001\u5730\u5740\u4e0e\u6821\u9a8c\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-ws-"))
        self.root = self.tmp / "workspace"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _member(self, name, *, role="requirement", schema=1, document_no="GX"):
        project = self.root / name
        T._setup_project(str(project))
        manifest = T._make_manifest(str(project))
        manifest.schemaVersion = schema
        manifest.documentNo = document_no
        manifest.save(str(project))
        return project

    def test_create_and_roundtrip(self):
        workspace = create_workspace(self.root, name="\u7814\u53d1\u4ea4\u4ed8", collection_version="2.1")
        workspace.save()
        self.assertTrue((self.root / WORKSPACE_NAME).is_file())
        loaded = load_workspace(self.root)
        self.assertEqual(loaded.name, "\u7814\u53d1\u4ea4\u4ed8")
        self.assertEqual(loaded.collection_version, "2.1")
        self.assertEqual(loaded.schema_version, 1)
        self.assertEqual(loaded.relations_path, "relations.yml")

    def test_unsupported_schema_rejected(self):
        import yaml

        (self.root / WORKSPACE_NAME).write_text(
            yaml.safe_dump({"schemaVersion": 9, "workspaceId": "x", "documents": []}),
            encoding="utf-8",
        )
        with self.assertRaises(ProjectManifestError):
            load_workspace(self.root)

    def test_missing_workspace_file_rejected(self):
        with self.assertRaises(ProjectManifestError):
            load_workspace(self.root)


class MemberValidationTests(unittest.TestCase):
    """1.4\uff1a\u4e0d\u5408\u6cd5\u6210\u5458\u8df3\u8fc7\u4e14\u5176\u4ed6\u6210\u5458\u7ee7\u7eed\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-member-"))
        self.root = self.tmp / "workspace"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _project(self, name):
        """创建带 project.yml 的合法成员项目。"""
        project = self.root / name
        T._setup_project(str(project))
        T._make_manifest(str(project)).save(str(project))
        return project

    def _write_workspace(self, documents, name="\u5de5\u4f5c\u533a"):
        import yaml

        payload = {
            "schemaVersion": 1,
            "workspaceId": "ws-1",
            "name": name,
            "collectionVersion": "1.0",
            "documents": documents,
        }
        (self.root / WORKSPACE_NAME).write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return self.root

    def test_unknown_role_skipped_others_continue(self):
        self._project("req")
        self._project("design")
        self._write_workspace(
            [
                {"role": "requirement", "projectId": "", "path": "req"},
                {"role": "bogus", "projectId": "", "path": "design"},
            ]
        )
        workspace = load_workspace(self.root)
        self.assertEqual(len(workspace.valid_members), 1)
        self.assertEqual(workspace.valid_members[0].role, "requirement")
        self.assertTrue(any("\u89d2\u8272" in issue.reason for issue in workspace.issues))

    def test_escaping_path_skipped(self):
        self._project("req")
        self._write_workspace(
            [
                {"role": "requirement", "projectId": "", "path": "req"},
                {"role": "design", "projectId": "", "path": "../outside"},
                {"role": "test", "projectId": "", "path": "C:/abs"},
            ]
        )
        workspace = load_workspace(self.root)
        self.assertEqual(len(workspace.valid_members), 1)
        self.assertEqual(len([i for i in workspace.issues if i.severity == "error"]), 2)

    def test_missing_member_skipped(self):
        self._project("req")
        self._write_workspace(
            [
                {"role": "requirement", "projectId": "", "path": "req"},
                {"role": "design", "projectId": "", "path": "\u4e0d\u5b58\u5728"},
            ]
        )
        workspace = load_workspace(self.root)
        self.assertEqual(len(workspace.valid_members), 1)
        self.assertTrue(any("\u4e0d\u5b58\u5728" in issue.reason for issue in workspace.issues))

    def test_duplicate_path_and_project_id_deduplicated(self):
        project = self._project("req")
        project_id = ProjectManifest.load(project).projectId
        self._write_workspace(
            [
                {"role": "requirement", "projectId": project_id, "path": "req"},
                {"role": "design", "projectId": project_id, "path": "req"},
            ]
        )
        workspace = load_workspace(self.root)
        self.assertEqual(len(workspace.members), 1)
        self.assertTrue(any("\u53bb\u91cd" in issue.reason for issue in workspace.issues))

    def test_same_role_twice_is_allowed(self):
        for name in ("design-a", "design-b"):
            self._project(name)
        self._write_workspace(
            [
                {"role": "design", "projectId": "", "path": "design-a"},
                {"role": "design", "projectId": "", "path": "design-b"},
            ]
        )
        workspace = load_workspace(self.root)
        self.assertEqual(len(workspace.valid_members), 2)
        self.assertEqual(workspace.roles().get("design"), 2)


class AddProjectTests(unittest.TestCase):
    """1.2\uff1a\u6839\u5185\u5f15\u7528\u4e0e\u5916\u90e8\u590d\u5236\u5bfc\u5165\uff08\u65b0 projectId\uff09\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-add-"))
        self.root = self.tmp / "workspace"
        self.root.mkdir()
        self.external = self.tmp / "external"
        T._setup_project(str(self.external))
        T._make_manifest(str(self.external)).save(str(self.external))
        self.original_id = ProjectManifest.load(self.external).projectId

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_internal_project_referenced_in_place(self):
        inside = self.root / "req"
        T._setup_project(str(inside))
        T._make_manifest(str(inside)).save(str(inside))
        workspace = create_workspace(self.root, name="ws")
        member, copied = add_project(workspace, inside, role="requirement")
        self.assertIsNotNone(member)
        self.assertFalse(copied)
        self.assertEqual(member.relative_path, "req")

    def test_external_project_copied_with_new_project_id(self):
        workspace = create_workspace(self.root, name="ws")
        member, copied = add_project(workspace, self.external, role="design")
        self.assertTrue(copied)
        self.assertIsNotNone(member)
        self.assertNotEqual(member.project_id, self.original_id)
        copied_root = self.root / member.relative_path
        self.assertTrue(copied_root.is_dir())
        self.assertNotEqual(ProjectManifest.load(copied_root).projectId, self.original_id)
        # \u539f\u9879\u76ee\u4e0d\u53d7\u5f71\u54cd
        self.assertEqual(ProjectManifest.load(self.external).projectId, self.original_id)

    def test_external_without_copy_is_rejected(self):
        workspace = create_workspace(self.root, name="ws")
        with self.assertRaises(ProjectManifestError):
            add_project(workspace, self.external, role="design", copy_external=False)

    def test_unreadable_project_rejected(self):
        broken = self.tmp / "broken"
        broken.mkdir()
        workspace = create_workspace(self.root, name="ws")
        with self.assertRaises(ProjectManifestError):
            add_project(workspace, broken, role="design")

    def test_unknown_role_rejected(self):
        workspace = create_workspace(self.root, name="ws")
        with self.assertRaises(ProjectManifestError):
            add_project(workspace, self.external, role="whatever")

    def test_duplicate_add_is_reported_not_duplicated(self):
        inside = self.root / "req"
        T._setup_project(str(inside))
        T._make_manifest(str(inside)).save(str(inside))
        workspace = create_workspace(self.root, name="ws")
        add_project(workspace, inside, role="requirement")
        member, _copied = add_project(workspace, inside, role="requirement")
        self.assertIsNone(member)
        self.assertEqual(len(workspace.members), 1)
        self.assertTrue(workspace.issues)


class OverviewTests(unittest.TestCase):
    """1.3\uff1a\u805a\u5408\u4e0e\u65e0\u9700\u6c42\u65f6\u7684 N/A\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-ov-"))
        self.root = self.tmp / "workspace"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, name, role, version="1.0"):
        project = self.root / name
        T._setup_project(str(project))
        manifest = T._make_manifest(str(project))
        manifest.documentVersion = version
        manifest.save(str(project))
        return project

    def test_overview_lists_independent_versions(self):
        workspace = create_workspace(self.root, name="ws", collection_version="3.0")
        self._add("req", "requirement", "1.2")
        self._add("design", "design", "1.4")
        self._add("test", "test", "1.1")
        for name, role in (("req", "requirement"), ("design", "design"), ("test", "test")):
            add_project(workspace, self.root / name, role=role)
        overview = workspace_overview(workspace)
        versions = {item["role"]: item["documentVersion"] for item in overview["documents"]}
        self.assertEqual(versions["requirement"], "1.2")
        self.assertEqual(versions["design"], "1.4")
        self.assertEqual(versions["test"], "1.1")
        self.assertEqual(overview["collectionVersion"], "3.0")
        self.assertEqual(overview["coverage"], "applicable")
        self.assertTrue(overview["independentOpenAllowed"])

    def test_without_requirement_coverage_is_na(self):
        workspace = create_workspace(self.root, name="ws")
        self._add("design", "design")
        add_project(workspace, self.root / "design", role="design")
        overview = workspace_overview(workspace)
        self.assertEqual(overview["coverage"], "N/A")
        self.assertFalse(overview["hasRequirement"])
        self.assertIn("N/A", workspace.markdown_text())

    def test_markdown_lists_skipped_members(self):
        workspace = create_workspace(self.root, name="ws")
        self._add("req", "requirement")
        add_project(workspace, self.root / "req", role="requirement")
        from doc_tool.application.workspace import WorkspaceIssue

        workspace.issues.append(WorkspaceIssue("ghost", "\u6210\u5458\u76ee\u5f55\u4e0d\u5b58\u5728\uff0c\u5df2\u8df3\u8fc7\u3002", "error"))
        text = workspace.markdown_text()
        self.assertIn("\u8df3\u8fc7\u7684\u6210\u5458", text)
        self.assertIn("ghost", text)


class CopyWorkspaceTests(unittest.TestCase):
    """1.4\uff1a\u5de5\u4f5c\u533a\u6574\u4f53\u590d\u5236\u540e\u4ecd\u53ef\u89e3\u6790\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-copy-"))
        self.root = self.tmp / "workspace"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copy_has_no_absolute_path_dependency(self):
        workspace = create_workspace(self.root, name="ws")
        project = self.root / "req"
        T._setup_project(str(project))
        T._make_manifest(str(project)).save(str(project))
        add_project(workspace, project, role="requirement")
        workspace.save()

        clone = self.tmp / "\u53e6\u4e00\u53f0\u673a\u5668" / "workspace"
        shutil.copytree(self.root, clone)
        loaded = load_workspace(clone)
        self.assertEqual(len(loaded.valid_members), 1)
        self.assertEqual(loaded.valid_members[0].relative_path, "req")
        self.assertFalse(loaded.issues)
        self.assertIsNotNone(loaded.member_project_root(loaded.valid_members[0]))
        # \u6587\u4ef6\u5185\u4e0d\u5f97\u51fa\u73b0\u7edd\u5bf9\u8def\u5f84
        text = (clone / WORKSPACE_NAME).read_text(encoding="utf-8")
        self.assertNotIn(str(self.tmp), text)


if __name__ == "__main__":
    unittest.main()