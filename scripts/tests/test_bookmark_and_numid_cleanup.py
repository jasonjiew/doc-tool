# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from lxml import etree

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from docx_common import cleanup_element_bookmarks, is_internal_bookmark_name, _wqn
from validate_docx import DocxPackage, _expected_table_xml
from build_docx import _clone_revision_row, _render_complex_table_block

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class BookmarkAndNumIdCleanupTests(unittest.TestCase):
    def test_is_internal_bookmark_name(self):
        self.assertTrue(is_internal_bookmark_name("OLE_LINK88"))
        self.assertTrue(is_internal_bookmark_name("ole_link1"))
        self.assertTrue(is_internal_bookmark_name("_Toc186596109"))
        self.assertTrue(is_internal_bookmark_name("_toc40689350"))
        self.assertTrue(is_internal_bookmark_name("_Hlt12345"))
        self.assertTrue(is_internal_bookmark_name("_GoBack"))
        self.assertFalse(is_internal_bookmark_name("doc_sec1"))
        self.assertFalse(is_internal_bookmark_name("cap_tbl_01"))
        self.assertFalse(is_internal_bookmark_name("user_anchor"))
        self.assertFalse(is_internal_bookmark_name(None))
        self.assertFalse(is_internal_bookmark_name(""))

    def test_cleanup_element_bookmarks_strips_internal_and_orphan_ends(self):
        xml_text = (
            f'<w:tbl xmlns:w="{W_NS[1:-1]}">'
            f'<w:tr>'
            f'<w:tc>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="1" w:name="OLE_LINK88"/>'
            f'<w:r><w:t>Cell 1</w:t></w:r>'
            f'<w:bookmarkEnd w:id="1"/>'
            f'<w:bookmarkStart w:id="2" w:name="_Toc186596109"/>'
            f'<w:r><w:t>Cell 2</w:t></w:r>'
            f'<w:bookmarkEnd w:id="2"/>'
            f'<w:bookmarkStart w:id="3" w:name="doc_valid_anchor"/>'
            f'<w:r><w:t>Cell 3</w:t></w:r>'
            f'<w:bookmarkEnd w:id="3"/>'
            f'<w:bookmarkEnd w:id="999"/>'
            f'</w:p>'
            f'</w:tc>'
            f'</w:tr>'
            f'</w:tbl>'
        )
        element = etree.fromstring(xml_text.encode("utf-8"))
        removed = cleanup_element_bookmarks(element)
        self.assertEqual(removed, 2)

        remaining_starts = [(node.get(W_NS + "id"), node.get(W_NS + "name")) for node in element.iter(W_NS + "bookmarkStart")]
        remaining_ends = [node.get(W_NS + "id") for node in element.iter(W_NS + "bookmarkEnd")]

        self.assertEqual(remaining_starts, [("3", "doc_valid_anchor")])
        self.assertEqual(remaining_ends, ["3"])

    def test_cleanup_element_bookmarks_strips_orphan_starts(self):
        xml_text = (
            f'<w:body xmlns:w="{W_NS[1:-1]}">'
            f'<w:p>'
            f'<w:bookmarkStart w:id="1" w:name="doc_valid_paired"/>'
            f'<w:r><w:t>Paired</w:t></w:r>'
            f'<w:bookmarkEnd w:id="1"/>'
            f'<w:bookmarkStart w:id="888" w:name="doc_orphan_start"/>'
            f'<w:r><w:t>Orphan</w:t></w:r>'
            f'</w:p>'
            f'</w:body>'
        )
        element = etree.fromstring(xml_text.encode("utf-8"))
        removed = cleanup_element_bookmarks(element)
        self.assertEqual(removed, 1)

        remaining_starts = [(node.get(W_NS + "id"), node.get(W_NS + "name")) for node in element.iter(W_NS + "bookmarkStart")]
        remaining_ends = [node.get(W_NS + "id") for node in element.iter(W_NS + "bookmarkEnd")]

        self.assertEqual(remaining_starts, [("1", "doc_valid_paired")])
        self.assertEqual(remaining_ends, ["1"])

    def test_cleanup_element_bookmarks_deduplicates(self):
        xml_text = (
            f'<w:body xmlns:w="{W_NS[1:-1]}">'
            f'<w:p>'
            f'<w:bookmarkStart w:id="10" w:name="dup_anchor"/>'
            f'<w:r><w:t>First</w:t></w:r>'
            f'<w:bookmarkEnd w:id="10"/>'
            f'</w:p>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="20" w:name="dup_anchor"/>'
            f'<w:r><w:t>Second</w:t></w:r>'
            f'<w:bookmarkEnd w:id="20"/>'
            f'</w:p>'
            f'</w:body>'
        )
        element = etree.fromstring(xml_text.encode("utf-8"))
        removed = cleanup_element_bookmarks(element, deduplicate=True)
        self.assertEqual(removed, 1)

        remaining_starts = [(node.get(W_NS + "id"), node.get(W_NS + "name")) for node in element.iter(W_NS + "bookmarkStart")]
        remaining_ends = [node.get(W_NS + "id") for node in element.iter(W_NS + "bookmarkEnd")]

        self.assertEqual(remaining_starts, [("10", "dup_anchor")])
        self.assertEqual(remaining_ends, ["10"])

    def test_cleanup_element_bookmarks_deduplicates_case_insensitive(self):
        xml_text = (
            f'<w:body xmlns:w="{W_NS[1:-1]}">'
            f'<w:p>'
            f'<w:bookmarkStart w:id="10" w:name="MyAnchor"/>'
            f'<w:r><w:t>Upper First</w:t></w:r>'
            f'<w:bookmarkEnd w:id="10"/>'
            f'</w:p>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="20" w:name="myanchor"/>'
            f'<w:r><w:t>Lower Duplicate</w:t></w:r>'
            f'<w:bookmarkEnd w:id="20"/>'
            f'</w:p>'
            f'</w:body>'
        )
        element = etree.fromstring(xml_text.encode("utf-8"))
        removed = cleanup_element_bookmarks(element, deduplicate=True)
        self.assertEqual(removed, 1)

        remaining_starts = [(node.get(W_NS + "id"), node.get(W_NS + "name")) for node in element.iter(W_NS + "bookmarkStart")]
        remaining_ends = [node.get(W_NS + "id") for node in element.iter(W_NS + "bookmarkEnd")]

        self.assertEqual(remaining_starts, [("10", "MyAnchor")])
        self.assertEqual(remaining_ends, ["10"])

    def test_cleanup_element_bookmarks_duplicate_start_ids(self):
        xml_text = (
            f'<w:body xmlns:w="{W_NS[1:-1]}">'
            f'<w:p>'
            f'<w:bookmarkStart w:id="5" w:name="bmA"/>'
            f'<w:r><w:t>First ID 5</w:t></w:r>'
            f'<w:bookmarkEnd w:id="5"/>'
            f'</w:p>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="5" w:name="bmB"/>'
            f'<w:r><w:t>Second ID 5 duplicate</w:t></w:r>'
            f'<w:bookmarkEnd w:id="5"/>'
            f'</w:p>'
            f'</w:body>'
        )
        element = etree.fromstring(xml_text.encode("utf-8"))
        removed = cleanup_element_bookmarks(element, deduplicate=True)
        self.assertEqual(removed, 1)

        remaining_starts = [(node.get(W_NS + "id"), node.get(W_NS + "name")) for node in element.iter(W_NS + "bookmarkStart")]
        remaining_ends = [node.get(W_NS + "id") for node in element.iter(W_NS + "bookmarkEnd")]

        self.assertEqual(remaining_starts, [("5", "bmA")])
        self.assertEqual(remaining_ends, ["5"])

    def test_clone_revision_row_strips_prototype_bookmarks(self):
        proto_xml = (
            f'<w:tr xmlns:w="{W_NS[1:-1]}">'
            f'<w:tc>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="5" w:name="_Toc40689350"/>'
            f'<w:r><w:t>V1.0</w:t></w:r>'
            f'<w:bookmarkEnd w:id="5"/>'
            f'</w:p>'
            f'</w:tc>'
            f'</w:tr>'
        )
        proto = etree.fromstring(proto_xml.encode("utf-8"))
        row1 = _clone_revision_row(proto, ["V1.1"])
        row2 = _clone_revision_row(proto, ["V1.2"])

        self.assertEqual(list(row1.iter(W_NS + "bookmarkStart")), [])
        self.assertEqual(list(row1.iter(W_NS + "bookmarkEnd")), [])
        self.assertEqual(list(row2.iter(W_NS + "bookmarkStart")), [])
        self.assertEqual(list(row2.iter(W_NS + "bookmarkEnd")), [])

    def test_expected_table_xml_strips_internal_bookmarks(self):
        tbl_xml = (
            f'<w:tbl xmlns:w="{W_NS[1:-1]}">'
            f'<w:tr>'
            f'<w:tc>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="101" w:name="OLE_LINK88"/>'
            f'<w:r><w:t>Complex Cell</w:t></w:r>'
            f'<w:bookmarkEnd w:id="101"/>'
            f'</w:p>'
            f'</w:tc>'
            f'</w:tr>'
            f'</w:tbl>'
        )
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
            tf.write(tbl_xml.encode("utf-8"))
            tf_path = tf.name

        try:
            expected_root = _expected_table_xml(tf_path)
            starts = list(expected_root.iter(W_NS + "bookmarkStart"))
            ends = list(expected_root.iter(W_NS + "bookmarkEnd"))
            self.assertEqual(starts, [])
            self.assertEqual(ends, [])
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_expected_table_xml_neutralizes_hyperlinks_pointing_to_internal_bookmarks(self):
        tbl_xml = (
            f'<w:tbl xmlns:w="{W_NS[1:-1]}">'
            f'<w:tr>'
            f'<w:tc>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="101" w:name="OLE_LINK88"/>'
            f'<w:hyperlink w:anchor="OLE_LINK88">'
            f'<w:r><w:t>Linked Text</w:t></w:r>'
            f'</w:hyperlink>'
            f'<w:bookmarkEnd w:id="101"/>'
            f'</w:p>'
            f'</w:tc>'
            f'</w:tr>'
            f'</w:tbl>'
        )
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
            tf.write(tbl_xml.encode("utf-8"))
            tf_path = tf.name

        try:
            expected_root = _expected_table_xml(tf_path)
            self.assertEqual(list(expected_root.iter(W_NS + "bookmarkStart")), [])
            self.assertEqual(list(expected_root.iter(W_NS + "bookmarkEnd")), [])
            self.assertEqual(list(expected_root.iter(W_NS + "hyperlink")), [])
            t_nodes = list(expected_root.iter(W_NS + "t"))
            self.assertEqual(len(t_nodes), 1)
            self.assertEqual(t_nodes[0].text, "Linked Text")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_render_complex_table_block_cleans_internal_bookmarks(self):
        tbl_xml = (
            f'<w:tbl xmlns:w="{W_NS[1:-1]}">'
            f'<w:tr>'
            f'<w:tc>'
            f'<w:p>'
            f'<w:bookmarkStart w:id="102" w:name="OLE_LINK89"/>'
            f'<w:r><w:t>Complex Content</w:t></w:r>'
            f'<w:bookmarkEnd w:id="102"/>'
            f'</w:p>'
            f'</w:tc>'
            f'</w:tr>'
            f'</w:tbl>'
        )
        with tempfile.TemporaryDirectory() as td:
            tbl_path = os.path.join(td, "tbl_test.xml")
            with open(tbl_path, "wb") as f:
                f.write(tbl_xml.encode("utf-8"))

            class DummyBlock:
                filename = "tbl_test.xml"
                ident = ""
                proxy_rows = None

            class DummyLoc:
                path = "dummy.md"
                start_line = 1

            parent = etree.Element(W_NS + "body")
            insert_before = etree.SubElement(parent, W_NS + "p")
            config = {"paths": {"table_root": td}}

            inserted = _render_complex_table_block(
                DummyBlock(), insert_before, {}, [], config
            )
            self.assertEqual(inserted, 1)

            tbl = parent.find(W_NS + "tbl")
            self.assertIsNotNone(tbl)
            starts = list(tbl.iter(W_NS + "bookmarkStart"))
            ends = list(tbl.iter(W_NS + "bookmarkEnd"))
            self.assertEqual(starts, [])
            self.assertEqual(ends, [])

    def test_validate_docx_numid_zero_allowed(self):
        doc_xml = (
            f'<w:document xmlns:w="{W_NS[1:-1]}">'
            f'<w:body>'
            f'<w:p>'
            f'<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr>'
            f'<w:r><w:t>Normal paragraph with list disabled</w:t></w:r>'
            f'</w:p>'
            f'</w:body>'
            f'</w:document>'
        ).encode("utf-8")
        num_xml = (
            f'<w:numbering xmlns:w="{W_NS[1:-1]}">'
            f'<w:num w:numId="1"><w:abstractNumId w:val="10"/></w:num>'
            f'</w:numbering>'
        ).encode("utf-8")

        pkg = DocxPackage.__new__(DocxPackage)
        pkg.items = {"word/document.xml": doc_xml, "word/numbering.xml": num_xml}
        pkg.xml_roots = {
            "word/document.xml": etree.fromstring(doc_xml),
            "word/numbering.xml": etree.fromstring(num_xml),
        }
        pkg.document = pkg.xml_roots["word/document.xml"]
        pkg.relationship_map = {}

        errors = pkg.expression_errors()
        self.assertEqual(errors, [])

    def test_validate_docx_numid_missing_nonzero_reported(self):
        doc_xml = (
            f'<w:document xmlns:w="{W_NS[1:-1]}">'
            f'<w:body>'
            f'<w:p>'
            f'<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="999"/></w:numPr></w:pPr>'
            f'<w:r><w:t>Paragraph with broken list</w:t></w:r>'
            f'</w:p>'
            f'</w:body>'
            f'</w:document>'
        ).encode("utf-8")
        num_xml = (
            f'<w:numbering xmlns:w="{W_NS[1:-1]}">'
            f'<w:num w:numId="1"><w:abstractNumId w:val="10"/></w:num>'
            f'</w:numbering>'
        ).encode("utf-8")

        pkg = DocxPackage.__new__(DocxPackage)
        pkg.items = {"word/document.xml": doc_xml, "word/numbering.xml": num_xml}
        pkg.xml_roots = {
            "word/document.xml": etree.fromstring(doc_xml),
            "word/numbering.xml": etree.fromstring(num_xml),
        }
        pkg.document = pkg.xml_roots["word/document.xml"]
        pkg.relationship_map = {}

        errors = pkg.expression_errors()
        self.assertTrue(any("999" in e and "numId" in e for e in errors), f"Expected numId 999 error, got {errors}")


if __name__ == "__main__":
    unittest.main()
