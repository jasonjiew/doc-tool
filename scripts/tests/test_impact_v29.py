# -*- coding: utf-8 -*-
"""V2.9 29-E\uff1a\u53d8\u66f4\u5f71\u54cd\u4e0e\u590d\u6838\uff085.1\uff5e5.5\uff09\u3002"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.content.impact import (  # noqa: E402
    SPEC_FACTORS,
    ItemSnapshot,
    ReviewRecordStore,
    compute_impact,
    diff_snapshots,
    item_semantic_hash,
    spec_factor_hash,
)
from doc_tool.application.content.relations import RelationGraph, add_relation  # noqa: E402
from doc_tool.application.content.trace_matrix import endpoint_for  # noqa: E402
from doc_tool.application.content.traceable_items import ItemRef  # noqa: E402

P = "proj-req"
PD = "proj-design"
PT = "proj-test"


def _ref(kind, name):
    return ItemRef(project_id={"requirement": P, "design": PD, "test": PT}[kind], item_id=name, kind=kind)


def _snap(kind, name, title="\u6807\u9898", body="\u6b63\u6587", resources=()):
    ref = _ref(kind, name)
    return ref.key, ItemSnapshot(key=ref.key, title=title, body=body, resources=tuple(resources))


def _link(graph, relation_type, source, target):
    add_relation(
        graph, relation_type=relation_type,
        source=endpoint_for(source), target=endpoint_for(target),
    )


class SemanticHashTests(unittest.TestCase):
    """5.1\uff1a\u8bed\u4e49 hash \u6392\u9664\u4f4d\u7f6e/\u7f16\u53f7\uff0c\u89c4\u8303\u53d8\u5316\u5355\u5217\u3002"""

    def test_position_and_numbering_do_not_change_hash(self):
        first = ItemSnapshot(key=(P, "a"), title="1.1 \u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f", body="\u6b63\u6587")
        moved = ItemSnapshot(key=(P, "a"), title="3.2.1 \u7cfb\u7edf\u5e94\u652f\u6301\u79bb\u7ebf\u51fa\u7a3f", body="\u6b63\u6587")
        self.assertEqual(item_semantic_hash(first), item_semantic_hash(moved))

    def test_body_change_changes_hash(self):
        before = ItemSnapshot(key=(P, "a"), title="\u6807\u9898", body="v1")
        after = ItemSnapshot(key=(P, "a"), title="\u6807\u9898", body="v2")
        self.assertNotEqual(item_semantic_hash(before), item_semantic_hash(after))

    def test_trailing_whitespace_ignored(self):
        before = ItemSnapshot(key=(P, "a"), title="\u6807\u9898", body="a  \nb")
        after = ItemSnapshot(key=(P, "a"), title="\u6807\u9898", body="a\nb")
        self.assertEqual(item_semantic_hash(before), item_semantic_hash(after))

    def test_resource_change_changes_hash(self):
        before = ItemSnapshot(key=(P, "a"), title="t", body="b", resources=("fig-1.png",))
        after = ItemSnapshot(key=(P, "a"), title="t", body="b", resources=("fig-2.png",))
        self.assertNotEqual(item_semantic_hash(before), item_semantic_hash(after))

    def test_spec_hash_tracks_template_and_rules(self):
        base = {factor: "x" for factor in SPEC_FACTORS}
        self.assertEqual(spec_factor_hash(base), spec_factor_hash(dict(base)))
        changed = dict(base)
        changed["template"] = "y"
        self.assertNotEqual(spec_factor_hash(base), spec_factor_hash(changed))

    def test_diff_detects_add_delete_and_spec(self):
        before = dict([_snap("requirement", "a", body="v1")])
        after = dict([_snap("requirement", "a", body="v2"), _snap("requirement", "b")])
        changed, spec = diff_snapshots(
            before, after,
            spec_before={"template": "t1", "rules": "r", "terms": ""},
            spec_after={"template": "t2", "rules": "r", "terms": ""},
        )
        self.assertIn((P, "a"), changed)
        self.assertIn("v2", after[(P, "a")].body)
        self.assertIn((P, "b"), changed)
        self.assertEqual(spec, ["template"])

    def test_moved_only_is_not_a_change(self):
        before = dict([_snap("requirement", "a", title="1.1 \u6807\u9898")])
        after = dict([_snap("requirement", "a", title="9.9 \u6807\u9898")])
        changed, spec = diff_snapshots(before, after)
        self.assertFalse(changed)
        self.assertFalse(spec)


class ImpactTests(unittest.TestCase):
    """5.2\uff1a\u76f4\u63a5/\u4f20\u9012\u8def\u5f84\u3001\u5220\u9664/\u60ac\u7a7a\u3001\u73af\u8def\u7ec8\u6b62\u3002"""

    def setUp(self):
        self.r1 = _ref("requirement", "req-1")
        self.d1 = _ref("design", "des-1")
        self.t1 = _ref("test", "tst-1")

    def test_direct_and_transitive_paths(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)   # design satisfies requirement
        _link(graph, "verifies", self.t1, self.d1)    # test verifies design
        report = compute_impact({self.r1.key: "正文语义变化"}, graph)
        sources = [entry.source for entry in report.entries]
        self.assertIn(self.d1.key, sources)
        self.assertIn(self.t1.key, sources)
        self.assertTrue(report.transitive)
        self.assertTrue(report.affected)

    def test_deleted_item_listed(self):
        report = compute_impact({self.r1.key: "\u6761\u76ee\u5df2\u5220\u9664"}, RelationGraph())
        self.assertTrue(any(entry.impact_type == "deleted" for entry in report.entries))

    def test_dangling_endpoint_reported(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        report = compute_impact({self.r1.key: "x"}, graph, known_items=[self.r1.key])
        self.assertTrue(any(entry.impact_type == "dangling" for entry in report.entries))

    def test_cycle_terminates(self):
        graph = RelationGraph()
        a = _ref("design", "des-a")
        b = _ref("design", "des-b")
        _link(graph, "depends_on", a, b)
        _link(graph, "depends_on", b, a)
        report = compute_impact({b.key: "x"}, graph, known_items=[a.key, b.key])
        self.assertTrue(report.entries)
        self.assertTrue(any("\u73af\u8def" in entry.reason for entry in report.entries))

    def test_no_downstream_warns(self):
        report = compute_impact({self.r1.key: "x"}, RelationGraph())
        self.assertTrue(report.warnings)

    def test_markdown_and_json_export(self):
        graph = RelationGraph()
        _link(graph, "satisfies", self.d1, self.r1)
        report = compute_impact({self.r1.key: "x"}, graph, known_items=[self.r1.key, self.d1.key])
        md = report.markdown_text()
        data = json.loads(report.export("json"))
        self.assertIn("\u53d8\u66f4\u5f71\u54cd", md)
        self.assertIn("direct", data)
        with self.assertRaises(ValueError):
            report.export("xml")


class ReviewRecordTests(unittest.TestCase):
    """5.3\uff1a\u590d\u6838\u8bb0\u5f55\u4e0e\u518d\u6b21\u4fee\u6539\u5931\u6548\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-impact-"))
        self.store = ReviewRecordStore(self.tmp / ".state")
        self.source = (PD, "des-1")
        self.target = (P, "req-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_confirm_saves_current_hashes(self):
        record = self.store.confirm(
            "rel-1", self.source, self.target,
            source_hash="h1", target_hash="h2", reviewer="a", note="ok",
        )
        self.assertEqual(record.status, "\u901a\u8fc7")
        loaded = self.store.records()[0]
        self.assertEqual(loaded.source_hash, "h1")
        self.assertEqual(loaded.target_hash, "h2")
        self.assertFalse(self.store.pending())

    def test_change_makes_review_stale(self):
        self.store.confirm("rel-1", self.source, self.target, source_hash="h1", target_hash="h2")
        stale = self.store.stale_relations({self.source: "h1-new", self.target: "h2"})
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].status, "\u5f85\u590d\u6838")
        self.assertTrue(self.store.pending())

    def test_missing_endpoint_makes_review_stale(self):
        self.store.confirm("rel-1", self.source, self.target, source_hash="h1", target_hash="h2")
        stale = self.store.stale_relations({}, missing=[self.target])
        self.assertEqual(len(stale), 1)

    def test_repeat_confirm_replaces_previous(self):
        self.store.confirm("rel-1", self.source, self.target, source_hash="h1", target_hash="h2")
        self.store.confirm("rel-1", self.source, self.target, source_hash="h9", target_hash="h8")
        records = self.store.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_hash, "h9")

    def test_corrupt_store_reads_empty(self):
        self.store.file.parent.mkdir(parents=True, exist_ok=True)
        self.store.file.write_text("{ broken", encoding="utf-8")
        self.assertEqual(self.store.records(), [])

    def test_impact_does_not_modify_documents(self):
        """5.4\uff1a\u5f71\u54cd\u8ba1\u7b97**\u4e0d\u81ea\u52a8\u6539\u4e0b\u6e38**\uff08\u8fd9\u91cc\u65ad\u8a00\u5b58\u50a8\u672a\u88ab\u5199\u5165\uff09\u3002"""
        graph = RelationGraph()
        _link(graph, "satisfies", _ref("design", "d"), _ref("requirement", "r"))
        before = list(self.store.records())
        compute_impact({(P, "r"): "x"}, graph)
        self.assertEqual(self.store.records(), before)


if __name__ == "__main__":
    unittest.main()