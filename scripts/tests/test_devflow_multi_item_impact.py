# -*- coding: utf-8 -*-
"""回归测试：多条目章节快照提取、整文件删除与移动不变性影响分析。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_tool.application.content.impact import (
    diff_snapshots,
    extract_snapshots,
)
from doc_tool.cli import _detect_changes
from doc_tool.application.content.traceable_items import new_ref


class DevFlowMultiItemImpactTests(unittest.TestCase):
    def test_multi_item_single_chapter_extraction(self):
        doc = (
            "chapter1.md",
            "# 1. 用户管理\n\n"
            "<!-- DOC-ITEM: projectId=p1 kind=requirement id=11111111-1111-1111-1111-111111111111 alias=REQ-U1 -->\n"
            "用户注册正文内容。\n\n"
            "<!-- DOC-ITEM: projectId=p1 kind=requirement id=22222222-2222-2222-2222-222222222222 alias=REQ-U2 -->\n"
            "用户注销正文内容，附带图表：\n![注销流](assets/cancel.png)\n",
        )
        snaps = extract_snapshots([doc])
        self.assertEqual(len(snaps), 2)

        s1 = snaps[("p1", "11111111-1111-1111-1111-111111111111")]
        s2 = snaps[("p1", "22222222-2222-2222-2222-222222222222")]

        self.assertIn("注册正文内容", s1.body)
        self.assertNotIn("注销", s1.body)
        self.assertEqual(len(s1.resources), 0)

        self.assertIn("注销正文内容", s2.body)
        self.assertNotIn("注册", s2.body)
        self.assertIn("assets/cancel.png", s2.resources)

    def test_single_item_modification_in_multi_item_chapter(self):
        before_doc = (
            "ch.md",
            "# 1. 模块\n\n"
            "<!-- DOC-ITEM: projectId=p1 id=11111111-1111-1111-1111-111111111111 -->\n正文 1\n\n"
            "<!-- DOC-ITEM: projectId=p1 id=22222222-2222-2222-2222-222222222222 -->\n正文 2\n",
        )
        # 仅修改正文 2，正文 1 不变
        after_doc = (
            "ch.md",
            "# 1. 模块\n\n"
            "<!-- DOC-ITEM: projectId=p1 id=11111111-1111-1111-1111-111111111111 -->\n正文 1\n\n"
            "<!-- DOC-ITEM: projectId=p1 id=22222222-2222-2222-2222-222222222222 -->\n正文 2 已修改！\n",
        )
        before = extract_snapshots([before_doc])
        after = extract_snapshots([after_doc])

        changed, _spec = diff_snapshots(before, after)
        # 仅项 2 报告正文语义变化，项 1 绝不误报
        self.assertEqual(len(changed), 1)
        self.assertIn(("p1", "22222222-2222-2222-2222-222222222222"), changed)
        self.assertEqual(changed[("p1", "22222222-2222-2222-2222-222222222222")], "正文语义变化")

    def test_whole_file_deletion_detection(self):
        # 基线有两个文件
        base_doc1 = ("ch1.md", "<!-- DOC-ITEM: projectId=p1 id=11111111-1111-1111-1111-111111111111 -->\n文件1内容")
        base_doc2 = ("ch2.md", "<!-- DOC-ITEM: projectId=p1 id=22222222-2222-2222-2222-222222222222 -->\n文件2内容")
        # 当前删除了 ch2.md
        after_docs = [base_doc1]

        before = extract_snapshots([base_doc1, base_doc2])
        after = extract_snapshots(after_docs)

        changed, _spec = diff_snapshots(before, after)
        self.assertIn(("p1", "22222222-2222-2222-2222-222222222222"), changed)
        self.assertEqual(changed[("p1", "22222222-2222-2222-2222-222222222222")], "条目已删除")

    def test_inline_heading_marker_renumber_preserves_semantics(self):
        # 标记放在标题行内：## 2.1 登录功能 <!-- DOC-ITEM: ... -->
        from doc_tool.application.content.traceable_items import new_ref
        ref = new_ref("p1", alias="REQ-01")
        marker = ref.render()

        v1 = [("01.md", f"## 2.1 登录功能 {marker}\n用户在登录页输入用户名和密码\n")]
        v2 = [("01.md", f"## 2.2 登录功能 {marker}\n用户在登录页输入用户名和密码\n")]

        s1 = extract_snapshots(v1)[ref.key]
        s2 = extract_snapshots(v2)[ref.key]

        self.assertEqual(s1.semantic_hash(), s2.semantic_hash())
        changed, _spec = diff_snapshots({ref.key: s1}, {ref.key: s2})
        self.assertEqual(len(changed), 0)

    def test_detect_changes_with_version_and_snapshot_dir(self):
        with tempfile.TemporaryDirectory() as td:
            p_dir = Path(td) / "my_project"
            p_dir.mkdir()
            (p_dir / "project.yml").write_text(
                "schemaVersion: 1\nprojectId: p1\ndocumentName: 测试文档\ndocumentVersion: '1.0'\npaths:\n  contentRoot: content\n",
                encoding="utf-8",
            )
            c_dir = p_dir / "content"
            c_dir.mkdir()
            ref = new_ref("p1", alias="REQ-A")
            (c_dir / "a.md").write_text(f"# 1. 功能\n\n{ref.render()}\n初始正文\n", encoding="utf-8")

            # 建立基线快照目录（无 project.yml）
            base_content = p_dir / ".state" / "baselines" / "1.0" / "content"
            base_content.mkdir(parents=True)
            (base_content / "a.md").write_text(f"# 1. 功能\n\n{ref.render()}\n旧正文\n", encoding="utf-8")

            # 通过版本号 "1.0" 比对，应能自动解析并检测到变更，且不崩溃
            changed = _detect_changes(p_dir, "1.0")
            self.assertIn(ref.key, changed)
            self.assertEqual(changed[ref.key], "正文语义变化")

    def test_item_movement_or_renumber_preserves_semantics(self):
        # 基线：在 3.1 节，文件 03_a.md
        base_doc = (
            "03_a.md",
            "# 3.1 模块 A\n\n<!-- DOC-ITEM: projectId=p1 id=11111111-1111-1111-1111-111111111111 -->\n功能说明文本\n",
        )
        # 当前：移动到了 04_b.md，并且章节编号变成了 4.2 模块 A
        after_doc = (
            "04_b.md",
            "# 4.2 模块 A\n\n<!-- DOC-ITEM: projectId=p1 id=11111111-1111-1111-1111-111111111111 -->\n功能说明文本\n",
        )
        before = extract_snapshots([base_doc])
        after = extract_snapshots([after_doc])

        changed, _spec = diff_snapshots(before, after)
        # 语义与标题名一致，位置移动不触发变更
        self.assertEqual(len(changed), 0)


if __name__ == "__main__":
    unittest.main()
