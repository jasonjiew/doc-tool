# -*- coding: utf-8 -*-
"""打开目录的智能寻址：中间层目录、工作区根、多候选父目录。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.project_service import (  # noqa: E402
    DISCOVERY_MAX_DEPTH,
    discover_project_dirs,
    resolve_open_target,
)


class ResolveOpenTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _project(self, relative: str) -> Path:
        target = self.root / relative
        target.mkdir(parents=True, exist_ok=True)
        (target / "project.yml").write_text("schemaVersion: 2\n", encoding="utf-8")
        return target

    def test_project_directory_resolves_to_itself(self) -> None:
        project = self._project("示例项目-1 需求")
        resolution = resolve_open_target(str(project))
        self.assertEqual(resolution.kind, "project")
        self.assertEqual(resolution.root, project)

    def test_manifest_file_resolves_to_parent(self) -> None:
        project = self._project("需求")
        resolution = resolve_open_target(str(project / "project.yml"))
        self.assertEqual(resolution.kind, "project")
        self.assertEqual(resolution.root, project)

    def test_middle_layer_directory_finds_single_project(self) -> None:
        expected = self._project("requirements/示例项目-1 软件需求说明书")
        self._project("design/示例项目-2 详细设计")
        resolution = resolve_open_target(str(self.root / "requirements"))
        self.assertEqual(resolution.kind, "project")
        self.assertEqual(resolution.root, expected)

    def test_parent_with_multiple_projects_is_ambiguous(self) -> None:
        first = self._project("requirements/示例项目-1")
        second = self._project("design/示例项目-2")
        resolution = resolve_open_target(str(self.root))
        self.assertEqual(resolution.kind, "ambiguous")
        self.assertEqual(set(resolution.candidates), {first, second})
        self.assertIn("2 个文档项目", resolution.message)

    def test_workspace_root_is_recognised(self) -> None:
        (self.root / "workspace.yml").write_text("members: []\n", encoding="utf-8")
        resolution = resolve_open_target(str(self.root))
        self.assertEqual(resolution.kind, "workspace")
        self.assertEqual(resolution.root, self.root)

    def test_unrelated_directory_reports_none(self) -> None:
        (self.root / "notes").mkdir()
        resolution = resolve_open_target(str(self.root))
        self.assertEqual(resolution.kind, "none")
        self.assertIn("project.yml", resolution.message)

    def test_output_and_state_directories_are_skipped(self) -> None:
        self._project("output/归档项目")
        self._project(".state/临时项目")
        self.assertEqual(discover_project_dirs(self.root), [])

    def test_depth_limit_is_respected(self) -> None:
        deep = "/".join(["a"] * (DISCOVERY_MAX_DEPTH + 1)) + "/深项目"
        self._project(deep)
        self.assertEqual(discover_project_dirs(self.root), [])

    def test_empty_path_is_rejected(self) -> None:
        resolution = resolve_open_target("")
        self.assertEqual(resolution.kind, "none")


if __name__ == "__main__":
    unittest.main()
