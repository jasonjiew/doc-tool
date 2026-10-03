# -*- coding: utf-8 -*-
"""38-B 2.1：规范包骨架默认不含业务正文，正文副本必须显式选择。"""

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

from doc_tool.application import pack_authoring as authoring  # noqa: E402

NL = chr(10)
CHAPTER = NL.join([
    "## 1.1 目的",
    "",
    "这段是来源项目的业务正文，默认不应进入规范包。",
    "",
    "## 1.2 范围",
    "",
    "另一段业务正文。",
    "",
])


class PackSkeletonModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v38-pack-"))
        self.project = self.tmp / "项目"
        content = self.project / "content" / "general" / "第1章 概述"
        content.mkdir(parents=True)
        (content / "_index.md").write_text(CHAPTER, encoding="utf-8")
        (self.project / "template").mkdir(parents=True)
        (self.project / "template" / "template.docx").write_bytes(b"PK\x03\x04fake")
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION

        ProjectManifest(
            documentType="general",
            documentNo="V38-1",
            documentName="骨架模式测试",
            documentVersion="1.0",
            sourceSha256="",
            schemaVersion=PROJECT_SCHEMA_VERSION,
            paths={
                "templateDocx": "template/template.docx",
                "contentRoot": "content/general",
                "assetRoot": "assets/general",
                "tableRoot": "assets/general/tables",
            },
        ).save(self.project)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _draft(self, **kwargs):
        directory = self.tmp / "草稿-{0}".format(len(list(self.tmp.glob("草稿-*"))))
        return authoring.draft_from_project(self.project, directory, **kwargs)

    def test_default_skeleton_has_headings_only(self):
        draft = self._draft()
        self.assertTrue(draft.skeleton)
        self.assertEqual(draft.extra.get("skeletonMode"), "headings")
        self.assertEqual(draft.extra.get("skeletonBodyCopies"), 0)
        for rel in draft.skeleton:
            text = (Path(draft.root) / rel).read_text(encoding="utf-8")
            self.assertIn("1.1 目的", text)
            self.assertNotIn("业务正文", text, text)
            for line in text.splitlines():
                if line.strip():
                    self.assertTrue(line.strip().startswith("#"), line)

    def test_explicit_body_copy_is_recorded_and_distinguishable(self):
        draft = self._draft(include_body=True)
        self.assertEqual(draft.extra.get("skeletonMode"), "full")
        self.assertEqual(draft.extra.get("skeletonBodyCopies"), len(draft.skeleton))
        for rel in draft.skeleton:
            text = (Path(draft.root) / rel).read_text(encoding="utf-8")
            self.assertIn("业务正文", text)

    def test_source_project_is_not_modified(self):
        before = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        self._draft()
        self._draft(include_body=True)
        after = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_skeleton_outline_helper_keeps_only_headings(self):
        outline = authoring.skeleton_outline(CHAPTER)
        self.assertEqual(outline, "## 1.1 目的" + NL + "## 1.2 范围" + NL)
        self.assertEqual(authoring.skeleton_outline("没有标题的正文。"), "")


if __name__ == "__main__":
    unittest.main()