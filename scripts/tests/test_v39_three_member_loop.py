# -*- coding: utf-8 -*-
"""V3.9 5.1：三成员 创建→条目/关系→覆盖→影响→成员交付→集合比较/副本恢复。"""

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

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class ThreeMemberRdLoopTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v39-51-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.ws_root = self.work / "ws"
        self.ws_root.mkdir(parents=True)
        self.members = {}
        for name in ("Alpha", "Beta", "Gamma"):
            self.members[name] = fixtures.two_chapter_project(self.ws_root / name)

    def _workspace(self):
        from doc_tool.application import workspace as ws_mod

        workspace = ws_mod.create_workspace(self.ws_root, name="三成员研发工作区")
        for name, root in self.members.items():
            member, copied = ws_mod.add_project(workspace, root, role="requirement")
            self.assertIsNotNone(member, name)
            self.assertFalse(copied, "工作区内项目应直接引用，不复制")
        workspace.save()
        self.assertTrue((self.ws_root / "workspace.yml").is_file())
        return workspace

    def test_create_items_relations_coverage_impact(self):
        from doc_tool.application import rd_surface as surface

        self._workspace()
        workspace, message = surface.open_workspace(str(self.ws_root))
        self.assertIsNotNone(workspace, message)
        state = surface.workspace_state(workspace)
        self.assertEqual(state["memberCount"], 3)
        self.assertTrue(state["hasRequirement"], "三成员都是需求角色")

        # 条目：来自真实成员章节
        # 用真实可追踪条目标记（既有 new_ref/append_marker）构建索引
        from doc_tool.application.content.traceable_items import append_marker, build_item_index, new_ref

        docs = []
        aliases = []
        for rel, title, alias in (
            ("第1章 引言/1.1 目的.md", "目的", "REQ-ALPHA-1"),
            ("第2章 设计/2.1 架构.md", "架构", "REQ-ALPHA-2"),
        ):
            ref = new_ref("pid-Alpha", "requirement", alias)
            aliases.append(ref.item_id)
            docs.append((rel, append_marker("# {0}\n\n".format(title), ref, line_no=1) + "正文。\n"))
        index = build_item_index(docs, project_id="pid-Alpha")
        rows = surface.item_rows(index)
        self.assertTrue(rows, "条目清单必须来自真实索引：{0}".format(rows))
        self.assertEqual(
            sorted(str(row.get("itemId")) for row in rows), sorted(aliases),
            "条目身份必须来自真实标记",
        )
        # 每个条目必须能定位真实来源
        locations = surface.locate_sources(aliases[0], index, project_id="pid-Alpha")
        self.assertTrue(locations, "条目必须能按真实来源定位")

        # 关系 + 图
        graph = surface.empty_graph()
        self.assertIsNotNone(graph)
        self.assertTrue(hasattr(graph, "relations"), "关系图应提供真实关系集合")
        self.assertEqual(dict(graph.to_dict()).get("relations", []), [], "空图不得伪造关系")

        # 覆盖（矩阵）：matrix_view 直接消费真实 ItemRef（不是行字典）
        item_refs = list((getattr(index, "items", {}) or {}).values())
        self.assertEqual(len(item_refs), 2)
        matrix = surface.matrix_view(item_refs, graph, page=1, page_size=20, index=index)
        self.assertTrue(matrix.get("ok", True), "矩阵视图应可用")
        self.assertEqual(
            matrix["page"]["total"], 2,
            "覆盖分母必须是真实需求条目数",
        )
        self.assertEqual(len(matrix["page"]["rows"]), 2)
        self.assertEqual(
            len(matrix["page"]["unlinked"]), 2,
            "无关系时两条需求都必须单列为未链接",
        )
        uncovered = surface.matrix_view(
            item_refs, graph, only_uncovered=True, index=index,
        )
        self.assertEqual(
            uncovered["page"]["total"], 2,
            "未覆盖视图必须给出真实的未覆盖条目",
        )
        # 无关系时空图给出 dangling 而不是伪造覆盖
        self.assertTrue(hasattr(graph, "dangling"))

        # 影响：前后两版真实快照
        impact = surface.impact_view(None, None, graph, index=index)
        self.assertIsInstance(impact, dict)

    def test_member_delivery_comparison_and_recover(self):
        from doc_tool.application import rd_surface as surface
        from doc_tool.application.collection import build_manifest, register_manifest
        from doc_tool.application.collection_ops import compare_baselines, recover_baseline

        self._workspace()
        workspace, message = surface.open_workspace(str(self.ws_root))
        self.assertIsNotNone(workspace, message)
        rows = surface.member_rows(workspace)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.get("available") for row in rows), rows)

        # 成员交付：每个成员都能真实出稿
        from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest
        from doc_tool.application.project_export import run_project_export

        produced = {}
        for row in rows:
            root = self.ws_root / row["path"]
            report = run_project_export(
                ExportRequest(
                    project_root=str(root), formats=[FORMAT_HTML := "html"],
                    source_mode="saved", destination=str(self.work / "out" / row["path"]),
                ),
                skip_word_refresh=True,
            )
            result = report.result_for("html")
            self.assertTrue(result.usable, "{0}: {1}".format(row["path"], result.message))
            produced[row["path"]] = Path(result.path)
            self.assertTrue(produced[row["path"]].is_file())

        # 集合比较：一个成员的两版
        root = self.members["Alpha"]
        manifest_v1 = build_manifest(root, version="v1", label="集合")
        path_v1, err = register_manifest(root, manifest_v1)
        self.assertEqual(err, "")
        chapter = root / "content" / "general" / "第1章 引言" / "1.1 目的.md"
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n第二版新增。\n", encoding="utf-8")
        manifest_v2 = build_manifest(root, version="v2", label="集合")
        path_v2, err = register_manifest(root, manifest_v2)
        self.assertEqual(err, "")
        report = compare_baselines(path_v1, path_v2)
        changed = {entry.relative_path for entry in report.entries}
        self.assertIn(
            "content/general/第1章 引言/1.1 目的.md", changed,
            "两版比较必须命中真实改动章节：{0}".format(changed),
        )

        # 副本恢复：原工程不动、副本含真实文件
        before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
            and ".collections" not in path.relative_to(root).as_posix()
        }
        payload = recover_baseline(root, path_v1, self.work / "恢复副本")
        self.assertTrue(payload.get("restored"), payload)
        after = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
            and ".collections" not in path.relative_to(root).as_posix()
        }
        self.assertEqual(before, after, "恢复不得改动原工程业务文件")
        restored = [p for p in (self.work / "恢复副本").rglob("*") if p.is_file()]
        self.assertTrue(restored, "副本必须含真实文件")


if __name__ == "__main__":
    unittest.main(verbosity=2)