# -*- coding: utf-8 -*-
"""内容创作工作台服务层自动测试（计划 3，组 1 服务层 + 组 5 单测）。

覆盖：
- 拼写检查：英文命中 / 中文跳过 / 代码块跳过 / 用户词典 / 建议候选
- 用户词典：load/add/save/contains 往返
- 代码片段：占位符解析 / 增删改 / 持久化回读
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-tool/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _words(*items):
    return set(items)


class SpellCheckTests(unittest.TestCase):
    """拼写检查：命中 / 跳过 / 词典 / 建议。"""

    def _checker(self, user=()):
        from doc_tool.application.content.spellcheck import SpellChecker

        builtin = _words("hello", "world", "system", "user", "dictionary",
                         "app", "data", "folder", "config", "project",
                         "document", "edit", "text", "word", "test")
        return SpellChecker(builtin_words=builtin, user_words=set(user))

    def test_unknown_english_word_flagged(self):
        checker = self._checker()
        hits = checker.check("hello worl")
        words = [hit.word for hit in hits]
        self.assertEqual(words, ["worl"])

    def test_known_words_not_flagged(self):
        checker = self._checker()
        self.assertEqual(checker.check("hello world system"), [])

    def test_offsets_are_absolute_in_full_text(self):
        checker = self._checker()
        text = "hello worl\nnext zzz"
        hits = checker.check(text)
        by_word = {hit.word: hit for hit in hits}
        # "worl" 在第 1 行偏移 6..10
        self.assertEqual(by_word["worl"].start, 6)
        self.assertEqual(by_word["worl"].end, 10)
        # "zzz" 在第 2 行：第 1 行 10 字符 + 换行（偏移 11），"next " 5 字符
        self.assertEqual(by_word["zzz"].start, 16)

    def test_crlf_line_endings_preserve_absolute_offsets(self):
        # CRLF 文件每行多一个 \r；偏移累计必须按真实行长（含 \r\n）计算，
        # 否则第 2 行起整体偏小 1，编辑器高亮/定位错位。
        checker = self._checker()
        text = "hello worl\r\nnext zzz\r\n"
        hits = checker.check(text)
        by_word = {hit.word: hit for hit in hits}
        # 第 1 行 "worl" 偏移不变（6..10）；行长为 10+2=12。
        self.assertEqual(by_word["worl"].start, 6)
        self.assertEqual(by_word["worl"].end, 10)
        # 第 2 行 "zzz"：12（首行全长含 \r\n）+ 5（"next "）= 17，而非 16。
        self.assertEqual(by_word["zzz"].start, 17)
        self.assertEqual(by_word["zzz"].end, 20)

    def test_chinese_text_not_flagged(self):
        checker = self._checker()
        self.assertEqual(checker.check("这是一个测试段落，包含中文内容。"), [])

    def test_english_embedded_in_chinese_without_space_skipped(self):
        """紧贴中文的英文无词边界，不参与检查（符合「跳过中文」约定）。"""
        checker = self._checker()
        self.assertEqual(checker.check("使用hello工具进行测试"), [])

    def test_fenced_code_block_skipped(self):
        checker = self._checker()
        text = (
            "hello\n"
            "```\n"
            "worl zzz notchecked\n"
            "```\n"
            "hello worl"
        )
        hits = [hit.word for hit in checker.check(text)]
        self.assertEqual(hits, ["worl"])  # 只有围栏外的

    def test_mermaid_fence_skipped(self):
        checker = self._checker()
        text = "```mermaid\nflowchart TD\n  A[zzz] --> B[worl]\n```\nhello"
        hits = [hit.word for hit in checker.check(text)]
        self.assertEqual(hits, [])

    def test_user_word_not_flagged(self):
        checker = self._checker(user=("termstore",))
        hits = [hit.word for hit in checker.check("termstore wrold")]
        self.assertEqual(hits, ["wrold"])

    def test_add_user_word_clears_flag(self):
        checker = self._checker()
        self.assertIn("wrold", [h.word for h in checker.check("wrold")])
        checker.add_user_word("wrold")
        self.assertEqual(checker.check("wrold"), [])

    def test_apostrophe_contraction_normalized(self):
        """don't 归一化为 dont 后命中词典（词典含收缩词去撇号形式）。"""
        checker = self._checker()
        checker.add_user_word("dont")
        self.assertEqual(checker.check("don't"), [])

    def test_suggest_returns_close_candidates(self):
        checker = self._checker()
        suggestions = checker.suggest("wrold")
        self.assertIn("world", suggestions)
        suggestions = checker.suggest("hallo")
        self.assertIn("hello", suggestions)

    def test_suggest_unknown_first_letter_empty(self):
        checker = self._checker()
        self.assertEqual(checker.suggest("zzzz"), [])

    def test_builtin_dict_resource_loads(self):
        from doc_tool.application.content.spellcheck import load_builtin_words

        words = load_builtin_words()
        self.assertGreater(len(words), 40000)
        self.assertIn("the", words)
        self.assertIn("system", words)

    def test_case_insensitive_match(self):
        checker = self._checker()
        self.assertEqual(checker.check("Hello WORLD"), [])


class UserDictionaryTests(unittest.TestCase):
    """用户词典读写（可注入路径）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc-tool-udict-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = str(self.tmp / "user_dict.txt")

    def _store(self):
        from doc_tool.application.content.spellcheck import UserDictionary

        return UserDictionary(self.path)

    def test_add_and_persist_roundtrip(self):
        store = self._store()
        self.assertTrue(store.add("TermStore"))
        self.assertTrue(store.contains("termstore"))
        reloaded = self._store()
        self.assertTrue(reloaded.contains("TermStore"))

    def test_duplicate_add_returns_false(self):
        store = self._store()
        self.assertTrue(store.add("word"))
        self.assertFalse(store.add("WORD"))  # 归一化后重复

    def test_invalid_word_rejected(self):
        store = self._store()
        self.assertFalse(store.add(""))
        self.assertFalse(store.add("123"))
        self.assertFalse(store.add("a b c"))

    def test_missing_file_loads_empty(self):
        self.assertEqual(self._store().words, set())

    def test_corrupt_file_falls_back_to_empty(self):
        self.tmp.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text("坏行\nokword\n", encoding="utf-8")
        store = self._store()
        self.assertTrue(store.contains("okword"))
        self.assertFalse(store.contains("坏行"))


class SnippetPlaceholderTests(unittest.TestCase):
    """占位符解析。"""

    def test_placeholder_with_default(self):
        from doc_tool.application.content.snippets import expand_placeholders

        text, placeholders = expand_placeholders("${1:名称}")
        self.assertEqual(text, "名称")
        self.assertEqual(len(placeholders), 1)
        self.assertEqual(placeholders[0].number, 1)
        self.assertEqual(placeholders[0].start, 0)
        self.assertEqual(placeholders[0].end, 2)

    def test_placeholder_without_default(self):
        from doc_tool.application.content.snippets import expand_placeholders

        text, placeholders = expand_placeholders("[${1}](链接)")
        self.assertEqual(text, "[](链接)")
        self.assertEqual(placeholders[0].start, 1)
        self.assertEqual(placeholders[0].end, 1)  # 空区间

    def test_multiple_placeholders_sorted_by_number(self):
        from doc_tool.application.content.snippets import expand_placeholders

        text, placeholders = expand_placeholders("${2:乙} 与 ${1:甲}")
        self.assertEqual(text, "乙 与 甲")
        self.assertEqual([p.number for p in placeholders], [1, 2])
        self.assertEqual(placeholders[0].start, 4)  # 序号 1（甲）在后
        self.assertEqual(placeholders[1].start, 0)  # 序号 2（乙）在前

    def test_plain_text_no_placeholder(self):
        from doc_tool.application.content.snippets import expand_placeholders

        text, placeholders = expand_placeholders("普通文本")
        self.assertEqual(text, "普通文本")
        self.assertEqual(placeholders, [])


class SnippetStoreTests(unittest.TestCase):
    """片段存储：增删改 + 持久化回读。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc-tool-snippets-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = str(self.tmp / "snippets.json")

    def _store(self):
        from doc_tool.application.content.snippets import SnippetStore

        return SnippetStore(self.path)

    def test_add_find_remove(self):
        from doc_tool.application.content.snippets import Snippet

        store = self._store()
        self.assertTrue(store.add(Snippet("ref", "引用", "[${1:文本}](${2:链接})")))
        self.assertIsNotNone(store.find("ref"))
        self.assertFalse(store.add(Snippet("ref", "重复", "x")))  # 触发词去重
        self.assertTrue(store.remove("ref"))
        self.assertIsNone(store.find("ref"))
        self.assertFalse(store.remove("ref"))

    def test_update(self):
        from doc_tool.application.content.snippets import Snippet

        store = self._store()
        store.add(Snippet("t", "描述", "旧"))
        self.assertTrue(store.update("t", Snippet("t", "新描述", "新")))
        self.assertEqual(store.find("t").body, "新")
        self.assertFalse(store.update("不存在", Snippet("x", "", "y")))

    def test_persist_roundtrip(self):
        from doc_tool.application.content.snippets import Snippet

        store = self._store()
        store.add(Snippet("a", "描述A", "body A"))
        store.add(Snippet("b", "描述B", "body B"))
        reloaded = self._store()
        triggers = [s.trigger for s in reloaded.snippets()]
        self.assertEqual(triggers, ["a", "b"])
        self.assertEqual(reloaded.find("a").body, "body A")

    def test_missing_and_corrupt_fallback(self):
        from doc_tool.application.content.snippets import Snippet

        self.assertEqual(self._store().snippets(), [])
        Path(self.path).write_text("{ 损坏", encoding="utf-8")
        self.assertEqual(self._store().snippets(), [])
        # 损坏后仍可正常写回
        store = self._store()
        self.assertTrue(store.add(Snippet("x", "", "y")))


class ImageAssetTests(unittest.TestCase):
    """图片资源：命名、导入、引用差集、缺失与可回滚删除。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc-tool-assets-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.content = self.tmp / "content"
        self.assets = self.tmp / "assets"
        self.state = self.tmp / ".state"
        (self.content / "requirement").mkdir(parents=True)
        (self.content / "design").mkdir(parents=True)

    @staticmethod
    def _png_bytes(width=3, height=2):
        from io import BytesIO
        from PIL import Image

        stream = BytesIO()
        Image.new("RGB", (width, height), "red").save(stream, format="PNG")
        return stream.getvalue()

    def _index(self, requirement_line="", design_line=""):
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.references import ReferenceScanner

        (self.content / "requirement" / "a.md").write_text(
            requirement_line, encoding="utf-8"
        )
        (self.content / "design" / "b.md").write_text(design_line, encoding="utf-8")
        index = ContentIndexService(self.content).build()
        ReferenceScanner(index, assets_root=self.assets).scan_all()
        return index

    def test_unique_name_uses_directory_and_image_map_counter(self):
        from doc_tool.application.content.asset_manager import next_image_name

        images = self.assets / "requirement" / "images"
        images.mkdir(parents=True)
        (images / "img_0002.png").write_bytes(b"old")
        (self.assets / "requirement" / "image-map.yml").write_text(
            "images:\n  - file: images/img_0007.jpg\n", encoding="utf-8"
        )
        self.assertEqual(next_image_name(self.assets, "requirement", "png"), "img_0008.png")
        self.assertEqual(next_image_name(self.assets, "design", "jpg"), "img_0001.jpg")

    def test_import_writes_valid_image_and_reports_size(self):
        from doc_tool.application.content.asset_manager import import_image_data

        rel, width, height = import_image_data(
            self._png_bytes(7, 5), self.assets, "requirement", "png"
        )
        self.assertEqual((width, height), (7, 5))
        self.assertTrue((self.assets / "requirement" / rel).is_file())

    def test_invalid_image_leaves_no_file(self):
        from doc_tool.application.content.asset_manager import import_image_data

        with self.assertRaises(ValueError):
            import_image_data(b"not an image", self.assets, "requirement", "png")
        self.assertFalse((self.assets / "requirement" / "images").exists())

    def test_unused_is_scoped_by_document_type_and_lists_all_image_names(self):
        from doc_tool.application.content.asset_manager import scan_unused

        for doc_type in ("requirement", "design"):
            folder = self.assets / doc_type / "images"
            folder.mkdir(parents=True)
            (folder / "img_0001.png").write_bytes(self._png_bytes())
        (self.assets / "requirement" / "images" / "mermaid_0001.png").write_bytes(
            self._png_bytes()
        )
        index = self._index("![图](images/img_0001.png)\n", "")
        unused = [item[0] for item in scan_unused(self.assets, index)]
        self.assertNotIn("requirement/images/img_0001.png", unused)
        self.assertIn("design/images/img_0001.png", unused)
        self.assertIn("requirement/images/mermaid_0001.png", unused)

    def test_missing_list_reports_source_and_line(self):
        from doc_tool.application.content.asset_manager import list_missing

        index = self._index("标题\n![图](images/missing.png =7x5)\n", "")
        missing = list_missing(index, self.assets)
        self.assertEqual(len(missing), 1)
        self.assertEqual((missing[0].source, missing[0].line, missing[0].target),
                         ("requirement/a.md", 2, "images/missing.png"))

    def test_asset_delete_moves_to_trash_and_rollback_restores(self):
        from doc_tool.application.content.writer import ContentWriter

        target = self.assets / "requirement" / "images" / "img_0001.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(self._png_bytes())
        writer = ContentWriter(self.content, self.state, assets_root=self.assets)
        result = writer.delete_asset("requirement/images/img_0001.png")
        self.assertTrue(result.written)
        self.assertFalse(target.exists())
        writer.manifest.load()
        self.assertEqual(writer.manifest.entries[-1].rel_path,
                         "assets/requirement/images/img_0001.png")
        self.assertEqual(writer.rollback(), [])
        self.assertTrue(target.exists())

    def test_asset_delete_escape_rejected(self):
        from doc_tool.application.content.writer import ContentWriter

        writer = ContentWriter(self.content, self.state, assets_root=self.assets)
        result = writer.delete_asset("../outside.png")
        self.assertFalse(result.written)
        self.assertIn("越出", result.error)


class MermaidServiceTests(unittest.TestCase):
    """Mermaid 围栏/裸源码识别、校验、渲染、导出与批量转换。"""

    FLOW = "flowchart TD\n  A[开始] --> B{判断}\n  B --> C(完成)"
    SEQUENCE = "sequenceDiagram\n  participant U as 用户\n  participant S as 系统\n  U->>S: 请求\n  S-->>U: 响应"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc-tool-mermaid-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_extracts_fenced_and_bare_blocks_with_lines(self):
        from doc_tool.application.content.mermaid import extract_blocks

        text = "标题\n```mermaid\n{0}\n```\n正文\n\n{1}\n\n结尾".format(
            self.FLOW, self.SEQUENCE
        )
        blocks = extract_blocks(text)
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].fenced)
        self.assertEqual((blocks[0].start_line, blocks[0].kind), (2, "flowchart"))
        self.assertFalse(blocks[1].fenced)
        self.assertEqual(blocks[1].kind, "sequenceDiagram")

    def test_validate_reports_line_for_unbalanced_and_illegal_edge(self):
        from doc_tool.application.content.mermaid import validate

        errors = validate("flowchart TD\n  A[未闭合 --> B\n  ???")
        self.assertEqual([error.line for error in errors], [2, 3])
        self.assertIn("未闭合", errors[0].message)

    def test_validate_supported_diagrams(self):
        from doc_tool.application.content.mermaid import validate

        self.assertEqual(validate(self.FLOW), [])
        self.assertEqual(validate(self.SEQUENCE), [])
        errors = validate("gantt\n  title demo")
        self.assertIn("不支持", errors[0].message)

    def test_builtin_flowchart_and_sequence_render_png(self):
        from doc_tool.application.content.mermaid import render

        for source in (self.FLOW, self.SEQUENCE):
            result = render(source, use_cli=False)
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.backend, "builtin")
            self.assertTrue(result.svg.startswith(b"<svg"))
            self.assertTrue(result.png.startswith(b"\x89PNG"))
            self.assertGreater(result.width, 0)
            self.assertGreater(result.height, 0)

    def test_render_failure_is_explicit(self):
        from doc_tool.application.content.mermaid import render

        result = render("pie\n  title demo", use_cli=False)
        self.assertFalse(result.ok)
        self.assertIn("不支持", result.error)

    def test_export_name_is_unique_and_reference_has_size(self):
        from doc_tool.application.content.mermaid import (
            export_png,
            image_reference,
            render,
        )

        result = render(self.FLOW, use_cli=False)
        first = export_png(result, self.tmp, "design")
        second = export_png(result, self.tmp, "design")
        self.assertEqual(first, "images/mermaid_0001.png")
        self.assertEqual(second, "images/mermaid_0002.png")
        reference = image_reference(first, result)
        self.assertIn("={0}x{1}".format(result.width, result.height), reference)

    def test_batch_converts_bare_and_keeps_failed_source(self):
        from doc_tool.application.content.mermaid import batch_convert, image_reference

        text = "前文\n\n{0}\n\n后文\n\nflowchart TD\n  ???\n".format(self.FLOW)

        def exporter(_block, result):
            return image_reference("images/mermaid_0001.png", result)

        converted = batch_convert(text, exporter, use_cli=False)
        self.assertEqual(converted.success_count, 1)
        self.assertEqual(len(converted.failures), 1)
        self.assertIn("![图](images/mermaid_0001.png", converted.text)
        self.assertIn("flowchart TD\n  ???", converted.text)


if __name__ == "__main__":
    unittest.main()
