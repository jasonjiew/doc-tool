# -*- coding: utf-8 -*-
"""构建期内容预处理（V2.7 27-C / 3.1、3.2、3.5 部分）。

覆盖 ``doc_tool.application.prepared_source`` 的硬约束：只写任务临时目录、
不改源文件、保留源位置、缓存复用、渲染失败与取消的兜底。
"""

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

def package_names(docx_path):
    """返回 DOCX 包内全部部件名（不解压到磁盘）。"""
    import zipfile

    with zipfile.ZipFile(docx_path) as package:
        return package.namelist()


from doc_tool.application.prepared_source import (  # noqa: E402
    PreparedSource,
    compute_cache_key,
    prepare_markdown,
)


class _StubResult:
    def __init__(self, ok=True, png=None, width=0, height=0, backend="stub", error=None):
        self.ok = ok
        self.png = png
        self.width = width
        self.height = height
        self.backend = backend
        self.error = error


def _png_bytes() -> bytes:
    from PIL import Image
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (250, 250, 250)).save(buffer, format="PNG")
    return buffer.getvalue()


class PrepareMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v27-prepare-"))
        self.source = self.root / "第1章 图.md"
        self.cache = self.root / "cache"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, text: str) -> None:
        self.source.write_text(text, encoding="utf-8")

    def test_no_fence_keeps_source_untouched(self):
        text = "# 标题\n\n正文。\n"
        self._write(text)
        prepared = prepare_markdown(str(self.source), cache_root=self.cache)
        self.assertEqual(prepared.prepared_path, str(self.source))
        self.assertEqual(prepared.prepared_text, text)
        self.assertFalse(prepared.temp_dir)
        self.assertEqual(self.source.read_text(encoding="utf-8"), text)

    def test_mermaid_rendered_into_temp_asset_dir(self):
        text = (
            "# 标题\n\n```mermaid\nflowchart TD\n  A --> B\n```\n\n尾巴。\n"
        )
        self._write(text)
        calls = []

        def renderer(source, kind):
            calls.append((source, kind))
            return _StubResult(png=_png_bytes(), width=40, height=30)

        with prepare_markdown(
            str(self.source), cache_root=self.cache, renderer=renderer
        ) as prepared:
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], "flowchart")
            self.assertTrue(prepared.asset_root)
            self.assertTrue(Path(prepared.asset_root).is_dir())
            images = list(Path(prepared.asset_root).glob("*.png"))
            self.assertEqual(len(images), 1)
            self.assertEqual(len(prepared.assets), 1)
            asset = prepared.assets[0]
            self.assertEqual(asset.location.path, str(self.source))
            self.assertEqual(asset.location.start_line, 3)
            self.assertTrue(asset.relative_path.endswith(".png"))
            self.assertFalse(asset.from_cache)
            # 预处理文本把围栏换成了图片引用，且不含围栏。
            self.assertNotIn("```", prepared.prepared_text)
            self.assertIn(asset.relative_path, prepared.prepared_text)
            self.assertIn("尾巴。", prepared.prepared_text)
            self.assertEqual(
                self.source.read_text(encoding="utf-8"), text, "源文件不得被改写"
            )
            temp_dir = prepared.temp_dir

        self.assertFalse(Path(temp_dir).exists(), "任务临时目录应被清理")

    def test_second_run_reuses_cache(self):
        text = "# 标题\n\n```mermaid\nflowchart TD\n  A --> B\n```\n"
        self._write(text)
        calls = []

        def renderer(source, kind):
            calls.append(kind)
            return _StubResult(png=_png_bytes(), width=40, height=30)

        first = prepare_markdown(str(self.source), cache_root=self.cache, renderer=renderer)
        first.cleanup()
        second = prepare_markdown(str(self.source), cache_root=self.cache, renderer=renderer)
        second.cleanup()
        self.assertEqual(len(calls), 2, "渲染器仍被调用（缓存用于失败兜底）")
        self.assertTrue(list(self.cache.glob("*.png")))
        self.assertTrue(list(self.cache.glob("*.json")))

    def test_render_failure_falls_back_to_source(self):
        text = "# 标题\n\n```mermaid\nflowchart TD\n  A --> B\n```\n\n后续。\n"
        self._write(text)

        def renderer(source, kind):
            return _StubResult(ok=False, error="模拟渲染失败")

        prepared = prepare_markdown(
            str(self.source), cache_root=self.cache, renderer=renderer
        )
        try:
            asset = prepared.assets[0]
            self.assertEqual(asset.fallback, "source")
            self.assertIn("```mermaid", prepared.prepared_text)
            self.assertIn("A --> B", prepared.prepared_text)
            rules = {item["rule"] for item in prepared.warnings}
            self.assertIn("mermaid_render_unavailable", rules)
        finally:
            prepared.cleanup()

    def test_render_failure_reuses_same_source_cache(self):
        text = "# 标题\n\n```mermaid\nflowchart TD\n  A --> B\n```\n"
        self._write(text)
        good = prepare_markdown(
            str(self.source),
            cache_root=self.cache,
            renderer=lambda source, kind: _StubResult(png=_png_bytes(), width=40, height=30),
        )
        good.cleanup()

        def failing(source, kind):
            return _StubResult(ok=False, error="网络不可用")

        prepared = prepare_markdown(
            str(self.source), cache_root=self.cache, renderer=failing
        )
        try:
            asset = prepared.assets[0]
            self.assertTrue(asset.from_cache)
            self.assertTrue(asset.image_path)
            # 命中同源码缓存时继续输出图片引用，而不是降级为源码说明。
            self.assertNotIn("```mermaid", prepared.prepared_text)
            self.assertIn(asset.relative_path, prepared.prepared_text)
            rules = {item["rule"] for item in prepared.warnings}
            self.assertIn("mermaid_render_failed", rules)
        finally:
            prepared.cleanup()

    def test_cancel_stops_without_touching_source(self):
        text = "# 标题\n\n```mermaid\nflowchart TD\n  A --> B\n```\n"
        self._write(text)
        prepared = prepare_markdown(
            str(self.source),
            cache_root=self.cache,
            renderer=lambda source, kind: _StubResult(png=_png_bytes(), width=40, height=30),
            cancel_check=lambda: True,
        )
        try:
            self.assertTrue(prepared.cancelled)
            self.assertEqual(prepared.prepared_text, text)
            self.assertEqual(prepared.prepared_path, str(self.source))
            self.assertEqual(self.source.read_text(encoding="utf-8"), text)
        finally:
            prepared.cleanup()

    def test_cache_key_depends_on_source_and_params(self):
        first = compute_cache_key("flowchart TD\n A --> B", "flowchart")
        second = compute_cache_key("flowchart TD\n A --> C", "flowchart")
        self.assertNotEqual(first, second)
        self.assertEqual(first, compute_cache_key("flowchart TD\n A --> B", "flowchart"))
        self.assertNotEqual(
            first, compute_cache_key("flowchart TD\n A --> B", "sequenceDiagram")
        )

    def test_read_prepared_text_falls_back_when_temp_missing(self):
        prepared = PreparedSource(
            source_path=str(self.source),
            prepared_path=str(self.root / "不存在.md"),
            prepared_text="回退文本",
        )
        self.assertEqual(prepared.read_prepared_text(), "回退文本")


class ProcessTreeCleanupTests(unittest.TestCase):
    """本任务进程树清理（V2.7 3.4）：只清理自己启动的进程。"""

    def test_kill_process_tree_terminates_child(self):
        import os as _os
        import subprocess as _subprocess
        import sys as _sys
        import time

        from doc_tool.application.content.mermaid import _kill_process_tree

        process = _subprocess.Popen(
            [_sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL,
        )
        try:
            self.assertIsNone(process.poll(), "子进程应仍在运行")
            _kill_process_tree(process)
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertIsNotNone(process.poll(), "子进程应被终止")
        finally:
            if process.poll() is None:
                process.kill()

    def test_kill_process_tree_is_safe_on_finished_process(self):
        import subprocess as _subprocess
        import sys as _sys

        from doc_tool.application.content.mermaid import _kill_process_tree

        process = _subprocess.Popen(
            [_sys.executable, "-c", "print('done')"],
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL,
        )
        process.wait(timeout=30)
        _kill_process_tree(process)  # 不得抛出


class BuildWithPreparedSourceTests(unittest.TestCase):
    """预处理结果接入正式构建：生成图进入 DOCX，源位置不变。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v27-prepare-build-"))
        project = self.root / "project"
        (project / "content").mkdir(parents=True)
        (project / "assets" / "tables").mkdir(parents=True)
        (project / "template").mkdir(parents=True)
        shutil.copy2(
            REPO_ROOT / "templates" / "requirement-template.docx",
            project / "template" / "template.docx",
        )
        self.source = project / "content" / "1 图示.md"
        self.source.write_text(
            "## 1.1 图示\n\n```mermaid\nflowchart TD\n  A --> B\n```\n\n结尾。\n",
            encoding="utf-8",
        )
        self.config = {
            "documentType": "requirement",
            "documentNo": "GX-V27-002",
            "documentName": "预处理图示",
            "documentVersion": "1.0",
            "paths": {
                "template": str(project / "template" / "template.docx"),
                "content_root": str(project / "content"),
                "asset_root": str(project / "assets"),
                "table_root": str(project / "assets" / "tables"),
                "output": str(project / "output" / "预处理(1.0).docx"),
            },
            "headingStyles": {1: "1", 2: "2", 3: "3"},
            "bodyStyle": "a",
        }

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_generated_image_lands_in_docx(self):
        from build_docx import build
        from docx_common import parse_xml_safe, read_docx_package

        prepared = prepare_markdown(
            str(self.source),
            cache_root=self.root / "cache",
            renderer=lambda source, kind: _StubResult(png=_png_bytes(), width=40, height=30),
        )
        try:
            output = build(config=dict(self.config), prepared=[prepared])
            with read_docx_package(output) as package:
                document = parse_xml_safe(package.read("word/document.xml"), "document.xml")
            W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
            # 模板本身可能带封面 LOGO，因此只断言“生成图实际内嵌”。
            media = [
                name
                for name in package_names(output)
                if name.startswith("word/media/")
            ]
            # 生成图由 ImageManager 以 “build_<sha16>.png” 内嵌，
            # 模板自带图则是 imageN.*。
            generated = [
                name for name in media if "build_" in name.lower()
            ]
            self.assertTrue(
                generated, "生成图应内嵌为图片媒体：{0}".format(media)
            )
            texts = "".join(node.text or "" for node in document.iter(W + "t"))
            self.assertIn("结尾。", texts)
            self.assertNotIn("flowchart", texts, "图源码不应出现在正文")
        finally:
            prepared.cleanup()

    def test_source_file_never_modified(self):
        original = self.source.read_text(encoding="utf-8")
        prepared = prepare_markdown(
            str(self.source),
            cache_root=self.root / "cache",
            renderer=lambda source, kind: _StubResult(png=_png_bytes(), width=40, height=30),
        )
        try:
            prepared.read_prepared_text()
            self.assertEqual(self.source.read_text(encoding="utf-8"), original)
        finally:
            prepared.cleanup()


if __name__ == "__main__":
    unittest.main()