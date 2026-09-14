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

    def test_unclosed_fence_tail_still_checked(self):
        # 围栏未闭合时不得静默跳过后续全部行：围栏后的内容补检。
        checker = self._checker()
        hits = [hit.word for hit in checker.check("hello\n```\nworl zzz\n")]
        self.assertEqual(hits, ["worl", "zzz"])

    def test_unclosed_tilde_fence_tail_checked_with_offsets(self):
        checker = self._checker()
        text = "hello\n~~~\nhelloo\n"
        hits = checker.check(text)
        self.assertEqual([h.word for h in hits], ["helloo"])
        # 围栏起始行偏移 6（"hello\n"），"helloo" 相对围栏行偏移 4。
        self.assertEqual(hits[0].start, 10)

    def test_suggest_includes_user_words(self):
        checker = self._checker()
        checker.add_user_word("termstor")
        self.assertIn("termstor", checker.suggest("termsto"))

    def test_mermaid_fence_skipped(self):
        checker = self._checker()
        text = "```mermaid\nflowchart TD\n  A[zzz] --> B[worl]\n```\nhello"
        hits = [hit.word for hit in checker.check(text)]
        self.assertEqual(hits, [])

    def test_tilde_mermaid_fence_skipped(self):
        checker = self._checker()
        text = "~~~mermaid\nflowchart TD\n  A[zzz] --> B[worl]\n~~~\nhelloo"
        hits = [hit.word for hit in checker.check(text)]
        self.assertEqual(hits, ["helloo"])

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

    def test_save_atomic_no_tmp_left(self):
        store = self._store()
        store.add("alpha")
        self.assertFalse(Path(self.path + ".tmp").exists())
        reloaded = self._store()
        self.assertTrue(reloaded.contains("alpha"))

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

    def test_extracts_tilde_fenced_blocks(self):
        """CommonMark 波浪号围栏 ~~~mermaid 同样识别为围栏块。"""
        from doc_tool.application.content.mermaid import extract_blocks

        text = "前文\n~~~mermaid\n{0}\n~~~\n后文".format(self.FLOW)
        blocks = extract_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].fenced)
        self.assertEqual(blocks[0].kind, "flowchart")
        self.assertEqual(blocks[0].source, self.FLOW)

    def test_tilde_fenced_preview_renders_png(self):
        """~~~mermaid 围栏在 HTML 预览中渲染为 PNG 图片。"""
        from doc_tool.application.content.preview import render_markdown_html

        rendered = render_markdown_html(
            "# 标题\n\n~~~mermaid\n{0}\n~~~\n".format(self.FLOW),
            use_cli=False,
        )
        self.assertTrue(
            "data:image/svg+xml;base64," in rendered or "data:image/png;base64," in rendered
        )
        self.assertNotIn("Mermaid 渲染失败", rendered)

    def test_tilde_fenced_blocks_excluded_from_batch_convert(self):
        """~~~mermaid 围栏块与反引号围栏一致，不在裸源码批量转换范围。"""
        from doc_tool.application.content.mermaid import (
            batch_convert,
            image_reference,
        )

        def exporter(_block, result):
            return image_reference("images/mermaid_0001.png", result)

        text = "前文\n~~~mermaid\n{0}\n~~~\n".format(self.FLOW)
        converted = batch_convert(text, exporter, use_cli=False)
        self.assertEqual(converted.success_count, 0)
        self.assertEqual(converted.text, text)

    def test_validate_reports_line_for_unbalanced_and_illegal_edge(self):
        from doc_tool.application.content.mermaid import validate

        errors = validate("flowchart TD\n  A[未闭合 --> B\n  ???")
        self.assertEqual([error.line for error in errors], [2, 3])
        self.assertIn("未闭合", errors[0].message)

    def test_validate_supported_diagrams(self):
        from doc_tool.application.content.mermaid import validate

        self.assertEqual(validate(self.FLOW), [])
        self.assertEqual(validate(self.SEQUENCE), [])
        self.assertEqual(validate("gantt\n  title demo"), [])
        self.assertEqual(validate("classDiagram\n  Animal <|-- Duck"), [])
        self.assertEqual(validate("pie\n  \"A\" : 10"), [])
        errors = validate("unknownDiagram\n  title demo")
        self.assertTrue(len(errors) > 0)
        self.assertIn("无法识别", errors[0].message)

    def test_validate_arrow_edge_labels(self):
        """标准 Mermaid 边标签 ``-->|label|`` 应通过校验并渲染。"""
        from doc_tool.application.content.mermaid import render, validate

        source = (
            "flowchart LR\n"
            "  UI[共享日志页面] -->|分页/详情/概览/重推| API[前端API封装]\n"
            "  M -->|安全分页VO| UI\n"
            "  TARGET -->|响应或异常| RETRY\n"
            "  UI -->|已加载安全行| CSV[浏览器CSV生成]\n"
        )
        self.assertEqual(validate(source), [])
        result = render(source, use_cli=False)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.backend, "builtin")
        self.assertTrue(result.svg.startswith(b"<svg"))
        self.assertTrue(result.png.startswith(b"\x89PNG"))

    def test_validate_legacy_inline_label_and_other_arrow_styles(self):
        """旧式 ``--|label|>`` 及 ``-.->|label|``/``==>|label|`` 仍受支持。"""
        from doc_tool.application.content.mermaid import validate

        source = (
            "flowchart LR\n"
            "  A --|旧式|> B\n"
            "  B -.->|点线| C\n"
            "  C ==>|粗线| D\n"
        )
        self.assertEqual(validate(source), [])

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

    def test_flowchart_renders_cylinder_shape(self):
        """数据库节点 [(..)] 应渲染为圆柱（SVG 含 ellipse），而非普通矩形。"""
        from doc_tool.application.content.mermaid import render

        result = render(
            "flowchart LR\n  A[服务] --> P[(device_third_party)]", use_cli=False
        )
        self.assertTrue(result.ok, result.error)
        self.assertIn(b"<ellipse", result.svg)

    def test_flowchart_layered_layout_groups_ranks(self):
        """布局按最长路径分层：B/C 同级并排，D 在下一层。"""
        import re as _re
        from doc_tool.application.content.mermaid import render

        result = render(
            "flowchart TD\n  A --> B\n  A --> C\n  B --> D\n  C --> D",
            use_cli=False,
        )
        self.assertTrue(result.ok, result.error)
        svg = result.svg.decode("utf-8")
        rects = [
            tuple(float(g) for g in m.groups())
            for m in _re.finditer(
                r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="[\d.]+" fill="#eef6ff"',
                svg,
            )
        ]
        self.assertEqual(len(rects), 4)
        # 每层一行：A 单独一行，B/C 同层并排，D 单独一行
        rows = sorted({round(y + h / 2, 0) for x, y, w, h in rects})
        self.assertEqual(len(rows), 3)
        row_sizes = sorted(
            sum(1 for x, y, w, h in rects if round(y + h / 2, 0) == row)
            for row in rows
        )
        self.assertEqual(row_sizes, [1, 1, 2])

    def test_wrap_text_splits_long_labels(self):
        from doc_tool.application.content.mermaid import _wrap_text

        lines = _wrap_text("这是一个非常长的中文标签需要折行显示", 120)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), "这是一个非常长的中文标签需要折行显示")

    def test_flowchart_no_text_overflow(self):
        """长标签折行后必须落在节点框内；边标签不得压节点。"""
        import re as _re
        from doc_tool.application.content.mermaid import render

        result = render(
            "flowchart LR\n"
            "  UI[共享日志页面] -->|分页/详情/概览/重推| API[前端API封装]\n"
            "  S --> M[DeviceThirdLogMapper/XML]\n"
            "  M --> LOG[(device_third_log)]\n"
            "  LOG -->|完整日志| DETAIL[DeviceThirdLogVo详情映射]",
            use_cli=False,
        )
        self.assertTrue(result.ok, result.error)
        svg = result.svg.decode("utf-8")
        boxes = []
        for m in _re.finditer(
            r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="[\d.]+" fill="#eef6ff"',
            svg,
        ):
            boxes.append(tuple(float(g) for g in m.groups()))
        for m in _re.finditer(
            r'<path d="M ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+) A [\d.]+ [\d.]+ 0 0 0 ([\d.]+)',
            svg,
        ):
            x, top_y, _x2, bot_y, xw = (float(g) for g in m.groups())
            boxes.append((x, top_y, xw - x, bot_y - top_y))
        texts = [
            (float(m.group(1)), float(m.group(2)), m.group(3))
            for m in _re.finditer(
                r'<text x="([\d.]+)" y="([\d.]+)" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="14" fill="#172033">([^<]+)</text>',
                svg,
            )
        ]
        self.assertTrue(texts)
        for tx, ty, label in texts:
            inside = any(
                bx <= tx <= bx + bw and by - 4 <= ty <= by + bh + 4
                for bx, by, bw, bh in boxes
            )
            self.assertTrue(inside, "文本溢出节点框: {0}".format(label))

    def test_render_with_cli_falls_back_to_builtin(self):
        """use_cli=True 时，mmdc 缺失/失败自动回退内置渲染器，结果始终可用。"""
        from doc_tool.application.content.mermaid import cli_available, render

        result = render("flowchart LR\n  A --> B", use_cli=True)
        self.assertTrue(result.ok, result.error)
        self.assertIn(result.backend, ("builtin", "mermaid-cli"))
        self.assertTrue(result.png.startswith(b"\x89PNG"))
        self.assertIsInstance(cli_available(), bool)

    def test_mmdc_discovery_paths(self):
        """本地 mmdc 发现逻辑定位仓库根目录与 puppeteer 配置。"""
        from doc_tool.application.content.mermaid import (
            _cli_puppeteer_config,
            _repo_root,
        )

        root = _repo_root()
        self.assertTrue((root / "doc_tool" / "app.py").is_file())
        config = _cli_puppeteer_config()
        if config is not None:
            self.assertTrue(config.endswith("puppeteer-config.json"))

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

    def test_diamond_shape_polygon_is_symmetric(self):
        """菱形节点四个顶点必须是 上/右/下/左 的对称坐标。

        回归：旧实现把下顶点写成 (中心x, 中心x)、左顶点写成 (底y, 中心y)，
        导致菱形右偏/下移（左顶点 x 被画成 y+h）。这里用固定几何直接断言。
        """
        from doc_tool.application.content.mermaid import _shape_svg

        svg = _shape_svg("diamond", 30.0, 20.0, 160.0, 76.0)
        self.assertIn(
            '<polygon points="110.0,20.0 190.0,58.0 110.0,96.0 30.0,58.0"',
            svg,
        )
        # 左顶点 x 必须回到节点左缘（30），不得被画成底 y（96）。
        self.assertNotIn("110.0,20.0 190.0,58.0 110.0,110.0 96.0,58.0", svg)

    def test_diamond_render_vertices_centered(self):
        """整图渲染的菱形：上下顶点同 x、左右顶点同 y 且左 x 小于中心 x。"""
        import re as _re
        from doc_tool.application.content.mermaid import render

        result = render(
            "flowchart TD\n    A{是否继续?} --> B[结束]",
            use_cli=False,
        )
        self.assertTrue(result.ok, result.error)
        svg = result.svg.decode("utf-8")
        match = _re.search(r'<polygon points="([^"]+)"', svg)
        self.assertIsNotNone(match, "缺少菱形 polygon")
        points = [tuple(float(v) for v in pair.split(",")) for pair in match.group(1).split(" ")]
        self.assertEqual(len(points), 4)
        top, right, bottom, left = points
        self.assertAlmostEqual(top[0], bottom[0], places=3)  # 上下同 x
        self.assertAlmostEqual(right[1], left[1], places=3)  # 左右同 y
        self.assertLess(left[0], top[0])                     # 左顶点在中心左侧
        self.assertGreater(bottom[1], right[1])              # 下顶点在右顶点之下
    def test_reused_node_keeps_shape_and_label(self):
        """后续边用裸 id 引用节点时，不得把先定义的菱形退化成方框。

        回归：``B{校验通过?} --> C`` 之后的 ``B -->|是| C`` 会把 B 重新解析为
        裸 id（shape=box、标签=id）并覆盖原定义，导致菱形变方框、标签丢失。
        """
        import re as _re
        from doc_tool.application.content.mermaid import render

        result = render(
            "flowchart TD\n"
            "    A{启动} --> B{校验通过?}\n"
            "    B -->|是| C[继续]\n"
            "    B -->|否| D[报错]\n"
            "    D --> A",
            use_cli=False,
        )
        self.assertTrue(result.ok, result.error)
        svg = result.svg.decode("utf-8")
        polygons = _re.findall(r'<polygon points="([^"]+)"', svg)
        # A、B 两个菱形都必须保留为 polygon（此前全被退化成 rect）。
        self.assertEqual(len(polygons), 2, svg)
        for points in polygons:
            pts = [tuple(float(v) for v in pair.split(",")) for pair in points.split(" ")]
            self.assertEqual(len(pts), 4)
            top, right, bottom, left = pts
            self.assertAlmostEqual(top[0], bottom[0], places=3)
            self.assertAlmostEqual(right[1], left[1], places=3)
            self.assertLess(left[0], top[0])
        # 标签不得被裸 id 覆盖。
        self.assertIn("校验通过?", svg)
        self.assertIn("启动", svg)

    def test_graph_td_supported_and_renders(self):
        """支持 graph TD 别名，校验通过并能使用内置 SVG 渲染。"""
        from doc_tool.application.content.mermaid import detect_kind, render, validate

        source = "graph TD\n  A[开始] --> B[结束]"
        self.assertEqual(detect_kind(source), "flowchart")
        self.assertEqual(validate(source), [])
        result = render(source, use_cli=False)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.backend, "builtin")
        self.assertTrue(result.svg.startswith(b"<svg"))

    def test_extract_bare_blocks_with_interleaved_html_comments(self):
        """Word 导入产生的 <!-- P:... --> 注释与空行交错的裸流程图能被完整提取并清洗。"""
        from doc_tool.application.content.mermaid import extract_blocks, render, validate

        text = (
            "#### 数据接收处理流程图\n\n"
            "![img_0001](images/img_0001.png =184x500)\n\n"
            "<!-- P:line=285;lr=atLeast -->\n"
            "graph TD\n\n"
            "<!-- P:line=285;lr=atLeast -->\n"
            "A[开始] --> B[netty接收数据]\n\n"
            "<!-- P:line=285;lr=atLeast -->\n"
            "B --> C[提取帧数据]\n\n"
            "<!-- P:line=285;lr=atLeast -->\n"
            "C --> D{检查校验和是否通过}\n\n"
            "#### 下一章节\n"
        )
        blocks = extract_blocks(text)
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertFalse(block.fenced)
        self.assertEqual(block.kind, "flowchart")
        self.assertEqual(block.start_line, 5)  # 包含紧邻前一行的 <!-- P:... -->
        self.assertEqual(block.end_line, 15)
        self.assertNotIn("<!-- P:", block.source)
        self.assertIn("A[开始] --> B[netty接收数据]", block.source)
        self.assertEqual(validate(block.source), [])
        result = render(block.source, use_cli=False)
        self.assertTrue(result.ok, result.error)

    def test_batch_convert_word_imported_flowchart(self):
        """批量转换带有 Word 遗留段落注释的裸流程图，替换为图片引用。"""
        from doc_tool.application.content.mermaid import (
            batch_convert,
            image_reference,
        )

        counter = 0

        def exporter(_block, result):
            nonlocal counter
            counter += 1
            return image_reference("images/mermaid_{0:04d}.png".format(counter), result)

        text = (
            "#### 流程图\n\n"
            "<!-- P:line=240;lr=auto -->\n"
            "graph TD\n\n"
            "<!-- P:line=240;lr=auto -->\n"
            "Start[开始] --> Login[登录]\n\n"
            "<!-- P:line=240;lr=auto -->\n"
            "Login --> End[结束]\n\n"
            "#### 下节\n"
        )
        converted = batch_convert(text, exporter, use_cli=False)
        self.assertEqual(converted.success_count, 1)
        self.assertEqual(len(converted.failures), 0)
        self.assertIn("![图](images/mermaid_0001.png", converted.text)
        self.assertNotIn("graph TD", converted.text)
        self.assertNotIn("<!-- P:line=240;lr=auto -->", converted.text)
        self.assertIn("#### 流程图\n\n![图](images/mermaid_0001.png", converted.text)
        self.assertIn("#### 下节", converted.text)

    def test_preview_renders_fenced_graph_td(self):
        """HTML 预览对 ```mermaid 围栏中的 graph TD 能正常渲染。"""
        from doc_tool.application.content.preview import render_markdown_html

        md = "```mermaid\ngraph TD\n  A[开始] --> B[结束]\n```\n"
        rendered = render_markdown_html(md, use_cli=False)
        self.assertTrue(
            "data:image/svg+xml;base64," in rendered or "data:image/png;base64," in rendered
        )
        self.assertNotIn("Mermaid 渲染失败", rendered)

    def test_preview_renders_mermaid_with_size_attributes(self):
        """HTML 预览对 Mermaid 图输出逻辑宽高属性与 max-width CSS。"""
        from doc_tool.application.content.preview import render_markdown_html

        md = "```mermaid\nflowchart TD\n  A[开始] --> B[结束]\n```\n"
        rendered = render_markdown_html(md, use_cli=False)
        self.assertTrue(
            "data:image/svg+xml;base64," in rendered or "data:image/png;base64," in rendered
        )
        self.assertRegex(rendered, r'<img\s+width="\d+"\s+height="\d+"\s+src="data:image/(?:svg\+xml|png);base64,')
        self.assertIn("max-width: 100%", rendered)

    def test_mermaid_all_formats_detection_and_frontmatter(self):
        """验证所有主流 Mermaid 格式识别及跳过 YAML frontmatter/指令能力。"""
        from doc_tool.application.content.mermaid import detect_kind, validate

        samples = {
            "flowchart": "---\ntitle: 流程图\n---\nflowchart LR\n  A --> B",
            "sequenceDiagram": "%%{init: {'theme': 'default'}}%%\nsequenceDiagram\n  Alice->>Bob: Hi",
            "classDiagram": "classDiagram\n  class BankAccount{\n    +String owner\n  }",
            "stateDiagram": "stateDiagram-v2\n  [*] --> Still\n  Still --> [*]",
            "erDiagram": "erDiagram\n  CUSTOMER ||--o{ ORDER : places",
            "mindmap": "mindmap\n  root((中心主题))\n    分支1\n    分支2",
            "timeline": "timeline\n  title 历史发展\n  2020 : 事件A\n  2021 : 事件B",
            "gitGraph": "gitGraph\n  commit\n  branch develop\n  checkout develop",
        }
        for expected_kind, code in samples.items():
            kind = detect_kind(code)
            self.assertEqual(kind, expected_kind, f"检测类型失败: {expected_kind}")
            errs = validate(code, kind)
            self.assertEqual(errs, [], f"{expected_kind} 校验不应报错: {errs}")

    def test_mermaid_syntax_error_reporting(self):
        """验证各类 Mermaid 语法错误能精确定位行号与原因。"""
        from doc_tool.application.content.mermaid import validate

        # 1. 括号不匹配
        errs = validate("flowchart TD\n  A[开始) --> B")
        self.assertTrue(len(errs) > 0)
        self.assertEqual(errs[0].line, 2)
        self.assertIn("括号不匹配", errs[0].message)

        # 2. 引号未闭合
        errs = validate("flowchart TD\n  A[\"开始] --> B")
        self.assertTrue(len(errs) > 0)
        self.assertEqual(errs[0].line, 2)
        self.assertIn("引号未闭合", errs[0].message)

        # 3. 未知图类型
        errs = validate("randomGraph\n  A --> B")
        self.assertTrue(len(errs) > 0)
        self.assertEqual(errs[0].line, 1)
        self.assertIn("无法识别", errs[0].message)

    def test_flowchart_without_explicit_direction_renders_cleanly(self):
        """flowchart/graph 不带方向声明（flowchart / graph）默认 TD 且不抛异常。"""
        from doc_tool.application.content.mermaid import render

        # 之前 direction_match.group(1).upper() 会抛 AttributeError
        res1 = render("flowchart\n  A --> B", use_cli=False)
        self.assertTrue(res1.ok, f"渲染失败: {res1.error}")
        self.assertIn(b"<svg", res1.svg)

        res2 = render("graph\n  A --> B", use_cli=False)
        self.assertTrue(res2.ok, f"渲染失败: {res2.error}")
        self.assertIn(b"<svg", res2.svg)

    def test_flowchart_and_sequence_frontmatter_and_keywords(self):
        """测试带 frontmatter 与 subgraph/end 关键字的图渲染不生成假节点。"""
        from doc_tool.application.content.mermaid import render

        flow = (
            "---\ntitle: 系统拓扑\n---\n"
            "flowchart LR\n"
            "  subgraph 模块一\n"
            "    A --> B\n"
            "  end\n"
            "  style A fill:#fff\n"
        )
        res = render(flow, use_cli=False)
        self.assertTrue(res.ok, f"渲染失败: {res.error}")
        # 不应把 end / subgraph 误当成独立可渲染节点
        svg_text = res.svg.decode("utf-8")
        self.assertNotIn('>end<', svg_text)

        seq = (
            "---\ntitle: 时序图\n---\n"
            "sequenceDiagram\n"
            "  Alice->>Bob: Hello\n"
        )
        res_seq = render(seq, use_cli=False)
        self.assertTrue(res_seq.ok, f"渲染失败: {res_seq.error}")
        self.assertIn(b"Alice", res_seq.svg)
        self.assertIn(b"Bob", res_seq.svg)

    def test_word_diff_and_side_by_side_rendering(self):
        """测试字符/字级别差异高亮切片与分栏对比视图生成。"""
        from doc_tool.application.content.changes import (
            compute_word_diff_spans,
            render_side_by_side_diff,
        )

        # 字级别切片测试
        old_l = "系统支持导出 PDF 与 HTML 两种格式"
        new_l = "系统支持导出 Word 与 HTML 两种格式"
        old_spans, new_spans = compute_word_diff_spans(old_l, new_l)
        self.assertTrue(len(old_spans) > 0)
        self.assertTrue(len(new_spans) > 0)
        # 确认提取的差异词包含变化部分
        old_diff_text = "".join(old_l[span.start:span.end] for span in old_spans)
        new_diff_text = "".join(new_l[span.start:span.end] for span in new_spans)
        self.assertIn("PDF", old_diff_text)
        self.assertIn("Word", new_diff_text)

        # 统一 diff 转分栏测试
        old_doc = "常规行1\n系统支持导出 PDF 格式\n常规行2\n"
        new_doc = "常规行1\n系统支持导出 Word 格式\n常规行2\n"
        sbs_lines = render_side_by_side_diff(old_doc, new_doc)
        self.assertGreater(len(sbs_lines), 0)
        # 找到变动行并校验两边行号及 word_spans
        mod_line = next((l for l in sbs_lines if l.change_type == "replace"), None)
        self.assertIsNotNone(mod_line)
        self.assertEqual(mod_line.old_line_no, 2)
        self.assertEqual(mod_line.new_line_no, 2)
        self.assertIn("PDF", mod_line.old_text)
        self.assertIn("Word", mod_line.new_text)
        self.assertTrue(len(mod_line.old_spans) > 0)
        self.assertTrue(len(mod_line.new_spans) > 0)

    def test_lint_quick_fixes(self):
        """测试格式诊断一键修复：标题空格、代码块闭合、表格分隔线等。"""
        from doc_tool.application.content.lint import (
            LintIssue,
            apply_all_quick_fixes,
            apply_quick_fix,
            can_quick_fix,
        )

        # 1. 标题缺失空格修复
        c1 = "#一级标题\n##二级标题\n内容"
        issue_h1 = LintIssue("heading_format", "test.md", 1, "标题 '#' 后面必须有空格：'#一级标题'", "heading_format")
        issue_h2 = LintIssue("heading_format", "test.md", 2, "标题 '#' 后面必须有空格：'##二级标题'", "heading_format")
        self.assertTrue(can_quick_fix(issue_h1))
        self.assertTrue(can_quick_fix(issue_h2))

        fixed_all, count = apply_all_quick_fixes(c1, [issue_h1, issue_h2])
        self.assertEqual(count, 2)
        self.assertIn("# 一级标题", fixed_all)
        self.assertIn("## 二级标题", fixed_all)

        # 2. 未闭合代码块修复
        c2 = "```python\nprint('hello')\n"
        fence_issue = LintIssue("heading_format", "test.md", 1, "代码块未闭合，文档末尾缺少闭合标记 ```", "heading_format")
        self.assertTrue(can_quick_fix(fence_issue))
        fixed_fence, ok, _ = apply_quick_fix(c2, fence_issue)
        self.assertTrue(ok)
        self.assertTrue(fixed_fence.endswith("```\n") or "```" in fixed_fence)

        # 3. 表格缺失分隔行修复
        c3 = "| 姓名 | 年龄 |\n| 张三 | 18 |\n"
        sep_issue = LintIssue("markdown_structure", "test.md", 1, "表格缺少分隔行（形如 `| --- | --- |`）", "markdown_structure")
        self.assertTrue(can_quick_fix(sep_issue))
        fixed_sep, ok2, _ = apply_quick_fix(c3, sep_issue)
        self.assertTrue(ok2)
        self.assertIn("| --- | --- |", fixed_sep)

        # 4. 术语大小写修复（支持 check_terms 生成的标准格式与正文规范格式）
        c4 = "这里提到了 word 和 pdf。\n"
        term_issue = LintIssue("term_case", "test.md", 1, "术语大小写不一致：word（应为 Word）", "term_case")
        self.assertTrue(can_quick_fix(term_issue))
        fixed_term, ok3, _ = apply_quick_fix(c4, term_issue)
        self.assertTrue(ok3)
        self.assertIn("Word 和 pdf", fixed_term)

    def test_path_natural_sort_key_none_and_empty(self):
        """测试路径自然排序键对 None 和空字符串的防御能力。"""
        from doc_tool.domain.content_index import path_natural_sort_key

        k_none = path_natural_sort_key(None)
        k_empty = path_natural_sort_key("")
        self.assertEqual(k_none, k_empty)
        # 验证 1.2 在 1.10 前面
        self.assertLess(path_natural_sort_key("1.2_节.md"), path_natural_sort_key("1.10_节.md"))
        self.assertLess(path_natural_sort_key("第2章/2.1.md"), path_natural_sort_key("第10章/10.1.md"))

    def test_tree_filter_only_changed(self):
        """测试章节树「仅看改动」筛选模式：仅保留有改动节点及其各级祖先。"""
        from doc_tool.application.content.tree import TreeItem, filter_tree_items

        items = [
            TreeItem(node_id="c1", text="第一章", parent_id=None, rel_path=None, is_file=False),
            TreeItem(node_id="c1/1.1.md", text="1.1 小节", parent_id="c1", rel_path="c1/1.1.md", is_file=True),
            TreeItem(node_id="c1/1.2.md", text="1.2 小节", parent_id="c1", rel_path="c1/1.2.md", is_file=True),
            TreeItem(node_id="c2", text="第二章", parent_id=None, rel_path=None, is_file=False),
            TreeItem(node_id="c2/2.1.md", text="2.1 小节", parent_id="c2", rel_path="c2/2.1.md", is_file=True),
        ]
        status_map = {
            "c1/1.2.md": "modified",
        }
        # 仅看改动：c1 必须保留（作为 c1/1.2.md 的父节点），c1/1.2.md 必须保留，1.1 和 c2 应被过滤
        filtered = filter_tree_items(items, only_changed=True, status_map=status_map)
        filtered_ids = [item.node_id for item in filtered]
        self.assertIn("c1", filtered_ids)
        self.assertIn("c1/1.2.md", filtered_ids)
        self.assertNotIn("c1/1.1.md", filtered_ids)

        # 搜索命中目录时，仅保留该目录下有改动的文件及其各级祖先
        filtered_dir = filter_tree_items(items, query="第一章", only_changed=True, status_map=status_map)
        dir_ids = [item.node_id for item in filtered_dir]
        self.assertIn("c1", dir_ids)
        self.assertIn("c1/1.2.md", dir_ids)
        self.assertNotIn("c1/1.1.md", dir_ids)

    def test_renumber_plan_after_delete_same_depth_only(self):
        """测试删除编号章节后重排：严格限定相同编号层级，不跨层级误判。"""
        from doc_tool.application.content.tree import renumber_plan_after_delete

        files = [
            "doc/1 概述.md",
            "doc/2 架构.md",
            "doc/3 模块.md",
            "doc/1.1 背景.md",  # 同目录但更深层级，不应被当成同级误改
        ]
        plan = renumber_plan_after_delete("doc/1 概述.md", files)
        # 2 架构 -> 1 架构, 3 模块 -> 2 模块；1.1 背景 不应被修改
        expected = [
            ("doc/2 架构.md", "doc/1 架构.md"),
            ("doc/3 模块.md", "doc/2 模块.md"),
        ]
        self.assertEqual(plan, expected)

    def test_batch_convert_mermaid_preserves_crlf(self):
        """测试 batch_convert 保持原文档换行符（CRLF）。"""
        from doc_tool.application.content.mermaid import batch_convert

        text = "```mermaid\r\nflowchart TD\r\n  A --> B\r\n```\r\n\r\n普通段落\r\n"

        def mock_exporter(_block, _result):
            return "![图](images/test.png)"

        converted = batch_convert(text, mock_exporter, include_fenced=True, use_cli=False)
        self.assertEqual(converted.success_count, 1)
        self.assertIn("\r\n", converted.text)
        self.assertNotIn("![图](images/test.png)\n\r\n", converted.text)
        self.assertTrue(converted.text.startswith("![图](images/test.png)\r\n"))

    def test_revision_summary_cell_hyperlinks_with_parentheses(self):
        """测试修订摘要行包含括号备注时精准为小节标题添加内部超链接。"""
        from lxml import etree
        from scripts.build_docx import _set_revision_summary_cell, qn

        class MockExpressions:
            def find_bookmark_for_section(self, token):
                if token in ("4.8.4 APP 用户管理", "4.8.4"):
                    return "_bm_sec_4_8_4"
                return None

        cell = etree.Element(qn("tc"))
        text = "第 4 章 WEB 端功能设计 -> 4.8 Kmilight -> 4.8.4 APP 用户管理（Tab 复合标签页展现: 合并用户）"
        _set_revision_summary_cell(cell, text, MockExpressions())

        # 检查是否成功生成 w:hyperlink 且 anchor 对应书签
        hyperlinks = cell.findall(f".//{qn('hyperlink')}")
        self.assertEqual(len(hyperlinks), 1)
        self.assertEqual(hyperlinks[0].get(qn("anchor")), "_bm_sec_4_8_4")
        link_text = "".join(hyperlinks[0].itertext())
        self.assertEqual(link_text, "4.8.4 APP 用户管理")
        all_text = "".join(cell.itertext())
        self.assertEqual(all_text, text)

    def test_update_custom_properties_converts_r8_to_lpwstr(self):
        """测试 update_custom_properties 将模板原有 <vt:r8> 替换为 <vt:lpwstr>。"""
        from scripts.build_docx import update_custom_properties

        custom_xml = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
            b'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">\n'
            b'  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="\xe7\x89\x88\xe6\x9c\xac">\n'
            b'    <vt:r8>2.5</vt:r8>\n'
            b'  </property>\n'
            b'</Properties>'
        )
        items = {"docProps/custom.xml": custom_xml}
        config = {
            "documentNo": "DOC-0000-0-000",
            "documentVersion": "2.6.0",
            "documentName": "\xe5\xba\xb7\xe5\xb0\x9a\xe5\x81\xa5\xe5\xba\xb7\xe4\xba\x91",
        }
        update_custom_properties(items, config)
        updated_xml = items["docProps/custom.xml"].decode("utf-8")
        self.assertNotIn("vt:r8", updated_xml)
        self.assertIn("<vt:lpwstr>2.6.0</vt:lpwstr>", updated_xml)

    def test_update_custom_properties_registers_rels_and_content_types(self):
        """测试 update_custom_properties 自动将 custom.xml 注册至 [Content_Types].xml 与 _rels/.rels。"""
        from scripts.build_docx import update_custom_properties

        items = {
            "[Content_Types].xml": (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
            ),
            "_rels/.rels": (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
            ),
        }
        config = {
            "documentNo": "DOC-0000-0-000",
            "documentVersion": "2.6.0",
            "documentName": "测试文档",
        }
        update_custom_properties(items, config)
        self.assertIn("docProps/custom.xml", items)
        ct_text = items["[Content_Types].xml"].decode("utf-8")
        self.assertIn('/docProps/custom.xml"', ct_text)
        self.assertIn("custom-properties+xml", ct_text)

        rels_text = items["_rels/.rels"].decode("utf-8")
        self.assertIn('Target="docProps/custom.xml"', rels_text)
        self.assertIn("relationships/custom-properties", rels_text)

    def test_term_case_quick_fix_with_backslashes(self):
        """测试 term_case 一键修复在替换词包含反斜杠时不触发转义异常。"""
        from doc_tool.application.content.lint import LintIssue, apply_quick_fix

        issue = LintIssue(
            rule="term_case",
            rel_path="test.md",
            line_no=1,
            message="术语大小写不一致： OldTerm （应为 New\\1Term ）",
            rule_id="term_case",
            severity="warning",
        )
        content = "Here is OldTerm in text.\n"
        fixed, ok, _ = apply_quick_fix(content, issue)
        self.assertTrue(ok)
        self.assertIn("New\\1Term", fixed)


if __name__ == "__main__":
    unittest.main()


