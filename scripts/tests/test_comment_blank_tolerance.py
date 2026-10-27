# -*- coding: utf-8 -*-
import unittest
from doc_tool.domain.blocks import parse_blocks, Paragraph, TableBlock


class CommentBlankToleranceTests(unittest.TestCase):
    def test_paragraph_comment_allows_one_to_two_blank_lines(self):
        # 1 blank line
        md1 = "<!-- P:line=360;lr=auto;first=420 -->\n\n这是正文第一段。"
        doc1 = parse_blocks(md1)
        pars1 = [b for b in doc1.blocks if isinstance(b, Paragraph)]
        self.assertEqual(len(pars1), 1)
        self.assertEqual(pars1[0].paragraph_format, "line=360;lr=auto;first=420")
        self.assertEqual(pars1[0].text, "这是正文第一段。")

        # 2 blank lines
        md2 = "<!-- P:line=360;lr=auto;first=420 -->\n\n\n这是正文第二段。"
        doc2 = parse_blocks(md2)
        pars2 = [b for b in doc2.blocks if isinstance(b, Paragraph)]
        self.assertEqual(len(pars2), 1)
        self.assertEqual(pars2[0].paragraph_format, "line=360;lr=auto;first=420")
        self.assertEqual(pars2[0].text, "这是正文第二段。")

        # 3 blank lines exceeds tolerance, format dropped
        md3 = "<!-- P:line=360;lr=auto;first=420 -->\n\n\n\n这是正文第三段。"
        doc3 = parse_blocks(md3)
        pars3 = [b for b in doc3.blocks if isinstance(b, Paragraph)]
        self.assertEqual(len(pars3), 1)
        self.assertIsNone(pars3[0].paragraph_format)

    def test_table_comment_allows_one_to_two_blank_lines(self):
        # 1 blank line between <!-- TBL:... --> and table
        md1 = "<!-- TBL:style=Normal cols=1000,2000 -->\n\n| 列A | 列B |\n|---|---|\n| 1 | 2 |\n"
        doc1 = parse_blocks(md1)
        tbls1 = [b for b in doc1.blocks if isinstance(b, TableBlock)]
        self.assertEqual(len(tbls1), 1)
        self.assertIsNotNone(tbls1[0].meta)
        self.assertEqual(tbls1[0].meta[0], "Normal")

        # 2 blank lines
        md2 = "<!-- TBL:style=Custom cols=1000,2000 -->\n\n\n| 列A | 列B |\n|---|---|\n| 1 | 2 |\n"
        doc2 = parse_blocks(md2)
        tbls2 = [b for b in doc2.blocks if isinstance(b, TableBlock)]
        self.assertEqual(len(tbls2), 1)
        self.assertIsNotNone(tbls2[0].meta)
        self.assertEqual(tbls2[0].meta[0], "Custom")


if __name__ == "__main__":
    unittest.main()
