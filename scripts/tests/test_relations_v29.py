# -*- coding: utf-8 -*-
"""V2.9 29-C\uff1a\u663e\u5f0f\u5173\u7cfb\u56fe\u7684\u8bfb\u5199\u3001\u6821\u9a8c\u4e0e\u8fc1\u79fb\uff083.1\uff5e3.4\uff09\u3002"""

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

from doc_tool.application.content.relations import (  # noqa: E402
    RELATION_TYPES,
    Endpoint,
    RelationGraph,
    add_relation,
    find_cycles,
    load_relations,
    migrate_legacy_graph,
    relation_sources,
    remove_relation,
    save_relations,
    validate_graph,
)

P1, P2 = "proj-req", "proj-design"
A, B, C = "item-a-0001", "item-b-0002", "item-c-0003"


class SchemaTests(unittest.TestCase):
    """3.1\uff1aschema\u3001\u7c7b\u578b\u4e0e\u7aef\u70b9\u8eab\u4efd\u3002"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v29-rel-"))
        self.file = self.tmp / "relations.yml"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip_and_types(self):
        graph = RelationGraph()
        for relation_type in RELATION_TYPES:
            add_relation(
                graph, relation_type=relation_type,
                source=Endpoint(P1, A), target=Endpoint(P2, B),
            )
        save_relations(self.file, graph)
        loaded = load_relations(self.file)
        self.assertEqual(len(loaded.relations), 3)
        self.assertEqual({item.type for item in loaded.relations}, set(RELATION_TYPES))
        self.assertTrue(all(item.relation_id for item in loaded.relations))
        self.assertFalse(loaded.issues)
        self.assertIn("schemaVersion", self.file.read_text(encoding="utf-8"))

    def test_unknown_type_rejected_on_load(self):
        self.file.write_text(
            "schemaVersion: 1\nrelations:\n  - relationId: r1\n    type: bogus\n"
            "    from: {projectId: p, itemId: i}\n    to: {projectId: p, itemId: j}\n",
            encoding="utf-8",
        )
        graph = load_relations(self.file)
        self.assertFalse(graph.relations)
        self.assertTrue(any("\u7c7b\u578b" in issue.reason for issue in graph.issues))

    def test_corrupt_file_rejected(self):
        self.file.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_relations(self.file)

    def test_unsupported_schema_rejected(self):
        self.file.write_text("schemaVersion: 9\nrelations: []\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_relations(self.file)

    def test_missing_file_is_empty_graph(self):
        graph = load_relations(self.tmp / "nope.yml")
        self.assertFalse(graph.relations)
        self.assertFalse(graph.issues)

    def test_add_rejects_same_endpoint(self):
        graph = RelationGraph()
        relation, error = add_relation(
            graph, relation_type="verifies", source=Endpoint(P1, A), target=Endpoint(P1, A)
        )
        self.assertIsNone(relation)
        self.assertIn("\u81ea\u73af", error or "")


class ValidationTests(unittest.TestCase):
    """3.2\uff1a\u91cd\u590d\u8fb9\u3001\u60ac\u7a7a\u3001\u73af\u8def\u4e0e\u5b89\u5168\u8fc1\u79fb\u3002"""

    def test_duplicate_edge_flagged_and_idempotent_add(self):
        graph = RelationGraph()
        first, _ = add_relation(graph, relation_type="satisfies", source=Endpoint(P1, A), target=Endpoint(P2, B))
        again, note = add_relation(graph, relation_type="satisfies", source=Endpoint(P1, A), target=Endpoint(P2, B))
        self.assertEqual(first.relation_id, again.relation_id)
        self.assertIn("\u5df2\u5b58\u5728", note or "")
        self.assertEqual(len(graph.relations), 1)

    def test_duplicate_lines_in_file_flagged(self):
        graph = RelationGraph()
        add_relation(graph, relation_type="satisfies", source=Endpoint(P1, A), target=Endpoint(P2, B))
        graph.relations.append(graph.relations[0].__class__(
            relation_id="dup-1", type="satisfies",
            source=Endpoint(P1, A), target=Endpoint(P2, B),
        ))
        validate_graph(graph)
        self.assertTrue(any("\u91cd\u590d\u5173\u7cfb" in issue.reason for issue in graph.issues))

    def test_dangling_endpoint_flagged(self):
        graph = RelationGraph()
        add_relation(graph, relation_type="satisfies", source=Endpoint(P1, A), target=Endpoint(P2, "ghost"))
        validate_graph(graph, known_items=[(P1, A), (P2, B)])
        self.assertEqual(len(graph.dangling), 1)
        self.assertIn("ghost", graph.dangling[0].reason)

    def test_cycle_detected_and_terminates(self):
        graph = RelationGraph()
        for source, target in ((A, B), (B, C), (C, A)):
            add_relation(
                graph, relation_type="depends_on",
                source=Endpoint(P1, source), target=Endpoint(P1, target),
            )
        cycles = find_cycles(graph)
        self.assertTrue(cycles)
        validate_graph(graph)
        self.assertTrue(graph.cycles)

    def test_no_cycle_for_chain(self):
        graph = RelationGraph()
        for source, target in ((A, B), (B, C)):
            add_relation(
                graph, relation_type="depends_on",
                source=Endpoint(P1, source), target=Endpoint(P1, target),
            )
        self.assertFalse(find_cycles(graph))

    def test_readonly_project_rejects_write(self):
        tmp = Path(tempfile.mkdtemp(prefix="v29-ro-"))
        try:
            with self.assertRaises(PermissionError):
                save_relations(tmp / "relations.yml", RelationGraph(), writable=False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_legacy_migration_requires_confirmed_pairs(self):
        graph = migrate_legacy_graph({}, pairs=None)
        self.assertFalse(graph.relations)
        self.assertTrue(any("\u4e0d\u81ea\u52a8\u63a8\u65ad" in issue.reason for issue in graph.issues))
        confirmed = migrate_legacy_graph(
            {}, pairs=[("satisfies", "{0}/{1}".format(P1, A), "{0}/{1}".format(P2, B))]
        )
        self.assertEqual(len(confirmed.relations), 1)
        self.assertEqual(confirmed.relations[0].source.key, (P1, A))


class ManyToManyTests(unittest.TestCase):
    """3.3\uff1a\u591a\u5bf9\u591a\u3001\u5220\u9664\u4e0e\u6765\u6e90\u5b9a\u4f4d\u3002"""

    def test_many_to_many_across_roles(self):
        graph = RelationGraph()
        # \u4e00\u4e2a\u8bbe\u8ba1\u6761\u76ee\u6ee1\u8db3\u591a\u6761\u9700\u6c42\uff0c\u4e00\u6761\u9700\u6c42\u88ab\u591a\u4e2a\u8bbe\u8ba1\u6ee1\u8db3
        for design in (B, C):
            add_relation(
                graph, relation_type="satisfies",
                source=Endpoint(P2, design), target=Endpoint(P1, A),
            )
        add_relation(
            graph, relation_type="satisfies",
            source=Endpoint(P2, B), target=Endpoint(P1, "item-d-0004"),
        )
        self.assertEqual(len(graph.by_source(Endpoint(P2, B))), 2)
        self.assertEqual(len(graph.by_target(Endpoint(P1, A))), 2)

    def test_remove_relation(self):
        graph = RelationGraph()
        relation, _ = add_relation(
            graph, relation_type="verifies", source=Endpoint(P2, B), target=Endpoint(P1, A)
        )
        self.assertTrue(remove_relation(graph, relation.relation_id))
        self.assertFalse(graph.relations)
        self.assertFalse(remove_relation(graph, relation.relation_id))

    def test_relation_sources_for_locating(self):
        graph = RelationGraph()
        relation, _ = add_relation(
            graph, relation_type="verifies", source=Endpoint(P2, B), target=Endpoint(P1, A)
        )
        sources = relation_sources(graph, relation.relation_id)
        self.assertEqual([item["role"] for item in sources], ["from", "to"])
        self.assertEqual(sources[0]["projectId"], P2)
        self.assertEqual(relation_sources(graph, "missing"), [])

    def test_aliases_do_not_affect_identity(self):
        """\u53ef\u8bfb\u522b\u540d\u4e0d\u53c2\u4e0e\u8eab\u4efd\uff1a\u540c\u4e00 (projectId, itemId) \u5373\u540c\u4e00\u7aef\u70b9\u3002"""
        graph = RelationGraph()
        left = Endpoint(P1, A)
        right = Endpoint(P1, A)
        self.assertEqual(left.key, right.key)
        add_relation(graph, relation_type="depends_on", source=left, target=Endpoint(P2, B))
        add_relation(graph, relation_type="depends_on", source=right, target=Endpoint(P2, B))
        self.assertEqual(len(graph.relations), 1)


if __name__ == "__main__":
    unittest.main()