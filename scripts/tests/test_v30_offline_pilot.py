# -*- coding: utf-8 -*-
"""V3.0 7.2 离线/换目录试点：三公开模块 × 两文档 × 两型号（实机项单列）。

本用例只做**可自动化**的部分：模块库共享、两文档各自两型号出稿、排除章节生效、
模块展开进入产物、整棵树换目录后仍可解析与再构建、展开副本可搬目录。
实机 Word 版式与冻结包检查按约定单列待验收（不在自动用例中断言）。
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.content import reuse_commands as reuse  # noqa: E402
from doc_tool.application.content.variants import verify_portable_copy  # noqa: E402

MODULES = (("m-alpha", "Alpha 模块正文。"), ("m-beta", "Beta 模块正文。"), ("m-gamma", "Gamma 模块正文。"))
FENCE = chr(96) * 3


def _three_chapter_docx(path: Path, prefix: str) -> Path:
    """三章文档；每章带一个小节，保证章节树里有可提取的正文文件。"""
    blocks = []
    for index, (_module_id, body) in enumerate(MODULES, start=1):
        blocks.append(("h1", "{0}第{1}章".format(prefix, index)))
        blocks.append(("h2", "{0}第{1}节".format(prefix, index)))
        blocks.append(("p", body))
    return fixtures.build_docx(path, blocks)


def _new_project(name: str, prefix: str) -> Path:
    source = _three_chapter_docx(Path(name).parent / (Path(name).name + "-源.docx"), prefix)
    from doc_tool.application.intake_entries import run_intake

    outcome = run_intake(source, parent_dir=Path(name).parent, target_name=Path(name).name)
    assert outcome.ok, outcome.errors
    return Path(outcome.project_root)


class OfflineTwoDocumentPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v30-pilot")
        cls.doc_a = _new_project(str(cls.work / "文档一"), "甲")
        cls.doc_b = _new_project(str(cls.work / "文档二"), "乙")
        cls.chapters = {}
        for label, project in (("A", cls.doc_a), ("B", cls.doc_b)):
            content = project / "content" / "general"
            from doc_tool.application.effective_snapshot import discover_chapters

            cls.chapters[label] = [rel for rel, _path in discover_chapters(content)]

        # 三个公共模块：从文档一提取后作为“公共库”复制给文档二
        context_a = reuse.load_context(cls.doc_a)
        for index, (module_id, _body) in enumerate(MODULES):
            result = reuse.extract_chapter_module(
                context_a, cls.chapters["A"][index], module_id=module_id, version="1.0.0",
            )
            assert result.get("ok"), result
        reuse_src = cls.doc_a / "reuse"
        reuse_dst = cls.doc_b / "reuse"
        if reuse_dst.exists():
            shutil.rmtree(reuse_dst)
        shutil.copytree(reuse_src, reuse_dst)  # 公共库（含库配置）整份共享

        # 文档二通过固定引用使用这三个公共模块（模板继承/共享正文的典型形态）
        content_b = cls.doc_b / "content" / "general"
        for index, (module_id, _body) in enumerate(MODULES):
            target = content_b / cls.chapters["B"][index]
            reference = "{0}doc-module id={1} version=1.0.0 slot=s{2}\n{0}\n".format(
                FENCE, module_id, index + 1,
            )
            target.write_text(target.read_text(encoding="utf-8") + "\n" + reference, encoding="utf-8")

        # 两型号：变量不同；乙型号额外排除第二章
        for label, project in (("A", cls.doc_a), ("B", cls.doc_b)):
            excluded = cls.chapters[label][1]
            (project / "variants.yml").write_text(
                "schemaVersion: 1\n"
                "variants:\n"
                "  - variantId: model-a\n"
                "    name: 甲型号\n"
                "    variables:\n"
                "      productName: 甲型号\n"
                "  - variantId: model-b\n"
                "    name: 乙型号\n"
                "    variables:\n"
                "      productName: 乙型号\n"
                "    exclude:\n"
                "      - '{0}'\n".format(excluded),
                encoding="utf-8",
            )

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _runs(self, payload):
        for key in ("runs", "variants", "outputs"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                return value
        return []

    def test_two_documents_two_models_build_offline(self):
        for label, project in (("A", self.doc_a), ("B", self.doc_b)):
            context = reuse.load_context(project)
            out_dir = self.work / ("out-" + label)
            payload = reuse.build_variant_documents(
                context, variant_ids=["model-a", "model-b"], output_dir=out_dir,
            )
            self.assertTrue(payload.get("ok"), payload.get("message") or payload)
            runs = self._runs(payload)
            self.assertEqual(len(runs), 2, payload)
            variables = [
                dict((run.get("scope") or {}).get("variables") or {}) for run in runs
            ]
            self.assertEqual(
                sorted(str(item.get("productName")) for item in variables),
                ["乙型号", "甲型号"],
            )
            for run in runs:
                output = Path(str(run.get("outputDir") or run.get("output_dir") or ""))
                self.assertTrue(output.is_dir(), run)
                chapters = [
                    path for path in output.rglob("*.md")
                    if "展开副本说明" not in path.read_text(encoding="utf-8", errors="replace")
                ]
                self.assertTrue(chapters, "变体产物应包含普通 Markdown 章节")
                markdown = "".join(path.read_text(encoding="utf-8") for path in chapters)
                self.assertNotIn("doc-module", markdown, "变体产物不应残留引用标记")
                if run.get("variantId") == "model-b":
                    scope = dict(run.get("scope") or {})
                    self.assertTrue(
                        scope.get("excluded"),
                        "乙型号应记录被排除章节：{0}".format(scope),
                    )
                    excluded_stem = Path(self.chapters[label][1]).stem.split()[0]
                    self.assertFalse(
                        any(excluded_stem in path.name for path in output.rglob("*.md")),
                        "被排除章节不应出现在乙型号产物中",
                    )
                if label == "B":
                    # 文档二通过公共模块出稿：纳入的章节正文必须展开；
                    # 被排除章节对应的模块正文不应出现（范围真的生效）。
                    if run.get("variantId") == "model-a":
                        expected = [body for _module_id, body in MODULES]
                        absent = []
                    else:
                        expected = [MODULES[0][1], MODULES[2][1]]
                        absent = [MODULES[1][1]]
                    for body in expected:
                        self.assertIn(body.strip(), markdown, "公共模块正文应展开进入产物")
                    for body in absent:
                        self.assertNotIn(
                            body.strip(), markdown, "被排除章节的模块正文不应出现",
                        )

    def test_directory_move_keeps_building_and_copy_is_portable(self):
        moved = self.work / "换目录-文档二"
        if moved.exists():
            shutil.rmtree(str(moved))
        shutil.copytree(str(self.doc_b), str(moved))  # 换目录=另一份独立副本
        context = reuse.load_context(moved)
        payload = reuse.build_variant_documents(
            context, variant_ids=["model-a"], output_dir=self.work / "out-moved",
        )
        self.assertTrue(payload.get("ok"), payload.get("message") or payload)
        runs = self._runs(payload)
        self.assertEqual(len(runs), 1, payload)

        # 展开副本：普通 Markdown + 资源，搬到另一目录后自检通过
        copy_dir = moved / "output" / "expanded"
        copy_payload = reuse.write_expanded_copy(context, copy_dir, variant_id="model-a")
        self.assertTrue(copy_payload.get("ok"), copy_payload.get("message") or copy_payload)
        relocated = self.work / "展开副本-搬家后"
        if relocated.exists():
            shutil.rmtree(str(relocated))
        shutil.move(str(copy_dir), str(relocated))
        shutil.rmtree(str(moved), ignore_errors=True)
        issues = verify_portable_copy(relocated)
        self.assertEqual(issues, [], [getattr(item, "message", str(item)) for item in issues])
        chapters = [
            path for path in relocated.rglob("*.md")
            if "展开副本说明" not in path.read_text(encoding="utf-8", errors="replace")
        ]
        self.assertTrue(chapters, "展开副本应包含普通 Markdown 章节")
        markdown = "".join(path.read_text(encoding="utf-8") for path in chapters)
        self.assertNotIn("doc-module", markdown)
        self.assertIn(MODULES[0][1].strip(), markdown)

    def test_public_library_shared_by_both_documents(self):
        library_a = reuse.load_library(self.doc_a)
        self.assertIsNotNone(library_a)
        ids_a = {module.moduleId for module in library_a.modules()}
        for module_id, _body in MODULES:
            self.assertIn(module_id, ids_a)
        # 文档二在换目录前也持有同一份公共库
        library_b = reuse.load_library(self.doc_b)
        self.assertIsNotNone(library_b)
        self.assertEqual({module.moduleId for module in library_b.modules()}, ids_a)


if __name__ == "__main__":
    unittest.main(verbosity=2)