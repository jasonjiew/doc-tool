# -*- coding: utf-8 -*-
"""MAIN-B 2.3：章节复制产生独立条目身份，重命名/移动保持原身份。"""

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

from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.refactor import (  # noqa: E402
    RefactorService,
    copy_chapter,
    copy_chapter_markdown,
)
from doc_tool.application.content.traceable_items import (  # noqa: E402
    build_item_index,
)
from doc_tool.application.content.writer import ContentWriter  # noqa: E402

NL = chr(10)
ITEM_A = "<!-- DOC-ITEM: projectId=P1 | id=11111111-1111-1111-1111-111111111111 | kind=requirement | alias=A -->"
ITEM_B = "<!-- DOC-ITEM: projectId=P1 | id=22222222-2222-2222-2222-222222222222 | kind=requirement | alias=B -->"


class ChapterCopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="main-b-copy-"))
        self.content = self.tmp / "content" / "general"
        self.content.mkdir(parents=True)
        (self.content / "1 概述.md").write_text(
            "# 1 概述" + NL + NL + "要求甲 " + ITEM_A + NL, encoding="utf-8"
        )
        (self.content / "2 设计.md").write_text(
            "# 2 设计" + NL + NL + "要求乙 " + ITEM_B + NL, encoding="utf-8"
        )
        self.state = self.tmp / ".state"
        self.state.mkdir()
        self.writer = ContentWriter(self.content, self.state)
        self.index = ContentIndexService(self.content).build()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copy_chapter_markdown_regenerates_item_ids(self):
        text = (self.content / "1 概述.md").read_text(encoding="utf-8")
        copied, mapping = copy_chapter_markdown(text, title="1.1 概述副本")
        self.assertIn("1.1 概述副本", copied)
        self.assertEqual(
            list(mapping),
            ["11111111-1111-1111-1111-111111111111"],
        )
        self.assertNotIn("11111111-1111-1111-1111-111111111111", copied)
        self.assertIn(mapping["11111111-1111-1111-1111-111111111111"], copied)
        # 原文本不被改写
        self.assertIn("11111111-1111-1111-1111-111111111111", text)

    def test_copy_chapter_writes_new_file_and_keeps_source(self):
        result = copy_chapter(self.index, "1 概述.md", self.writer, title="1.1 副本")
        self.assertTrue(result.ok, result.message)
        self.assertTrue((self.content / result.target).is_file())
        self.assertNotEqual(result.target, "1 概述.md")
        source_text = (self.content / "1 概述.md").read_text(encoding="utf-8")
        copy_text = (self.content / result.target).read_text(encoding="utf-8")
        self.assertIn("11111111-1111-1111-1111-111111111111", source_text)
        self.assertNotIn("11111111-1111-1111-1111-111111111111", copy_text)

    def test_copy_produces_independent_identity_in_index(self):
        result = copy_chapter(self.index, "1 概述.md", self.writer, title="1.1 副本")
        self.assertTrue(result.ok, result.message)
        documents = [
            (path.relative_to(self.content).as_posix(), path.read_text(encoding="utf-8"))
            for path in sorted(self.content.rglob("*.md"))
        ]
        index = build_item_index(documents, project_id="P1")
        self.assertEqual(index.duplicates, [], index.to_dict())
        keys = sorted(index.items)
        self.assertEqual(len(keys), 3)
        self.assertIn(("P1", "11111111-1111-1111-1111-111111111111"), keys)
        self.assertIn(("P1", result.item_ids["11111111-1111-1111-1111-111111111111"]), keys)

    def test_rename_keeps_item_identity(self):
        service = RefactorService(self.index)
        plan = service.compute_rename_plan("1 概述.md", "1 概述（改名）.md")
        self.assertTrue(plan.can_apply, plan.conflicts)
        results = service.apply_rename_plan(plan, self.writer)
        self.assertTrue(all(getattr(item, "written", True) for item in results))
        new_text = (self.content / "1 概述（改名）.md").read_text(encoding="utf-8")
        self.assertIn("11111111-1111-1111-1111-111111111111", new_text)


if __name__ == "__main__":
    unittest.main()