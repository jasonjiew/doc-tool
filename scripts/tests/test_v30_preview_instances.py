# -*- coding: utf-8 -*-
"""V3.0 3.4/4.3 补测：预览与出稿同源；实例登记与覆盖率有产品写入路径。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

FENCE = chr(96) * 3
MODULE_BODY = "架构正文。"


def _project_with_reference(work: Path) -> Path:
    from doc_tool.application.content import reuse_commands as reuse
    from doc_tool.application.effective_snapshot import discover_chapters

    project = fixtures.two_chapter_project(work / "proj")
    content = project / "content" / "general"
    rels = [rel for rel, _path in discover_chapters(content)]
    context = reuse.load_context(project)
    result = reuse.extract_chapter_module(context, rels[1], module_id="m-arch", version="1.0.0")
    assert result.get("ok"), result
    target = content / rels[0]
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n{0}doc-module id=m-arch version=1.0.0 slot=s1\n{0}\n".format(FENCE),
        encoding="utf-8",
    )
    return project


class PreviewSameSourceTests(unittest.TestCase):
    """3.4：编辑器预览与只读 HTML 都使用展开后的内容。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v30-preview")
        cls.project = _project_with_reference(cls.work)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_editor_preview_uses_resolved_text(self):
        from doc_tool.application.content.reuse_hook import build_project_resolver
        from doc_tool.ui.content.editor_panel import EditorPanel
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(self.project)
        paths = ProjectPaths(self.project)
        writer = ContentWriter(paths.resolve(manifest.relative_content_root()), paths.state_dir)
        resolver = build_project_resolver(self.project)
        self.assertIsNotNone(resolver)

        raw = "# 目的\n\n{0}doc-module id=m-arch version=1.0.0 slot=s1\n{0}\n".format(FENCE)

        panel = EditorPanel(writer, writable=True, text_resolver=resolver)
        panel.load("第1章 引言/1.1 目的.md", raw)
        panel._refresh_preview(raw)
        document = panel._preview.document()
        rendered = document.toPlainText() if hasattr(document, "toPlainText") else ""
        html = document.toHtml() if hasattr(document, "toHtml") else rendered
        # Qt 会把文本拆进多个 <span>，因此正文断言用 toPlainText()，标记断言用 toHtml()
        self.assertIn(MODULE_BODY, rendered, "编辑器预览应含展开后的模块正文")
        self.assertNotIn("doc-module", html, "编辑器预览不应残留引用标记")
        self.assertNotIn("doc-module", rendered)

        plain = EditorPanel(writer, writable=True)
        plain.load("第1章 引言/1.1 目的.md", raw)
        plain._refresh_preview(raw)
        document_plain = plain._preview.document()
        rendered_plain = document_plain.toPlainText() if hasattr(document_plain, "toPlainText") else ""
        self.assertNotIn(MODULE_BODY, rendered_plain, "没有展开器时预览保持原样")

    def test_readonly_html_export_uses_resolver(self):
        from doc_tool.application.content.reuse_hook import build_project_resolver
        from doc_tool.application.export.readonly_html import export_readonly_html
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        manifest = ProjectManifest.load(self.project)
        paths = ProjectPaths(self.project)
        resolver = build_project_resolver(self.project)
        out = self.work / "html"
        outcome = export_readonly_html(
            paths.content_root, paths.assets_root, out, manifest.documentVersion,
            text_resolver=resolver,
        )
        target = (
            getattr(outcome, "directory", None)
            or getattr(outcome, "path", None)
            or (outcome.get("path") if isinstance(outcome, dict) else None)
        )
        self.assertTrue(target, outcome)
        page = (Path(target) / "index.html")
        if not page.is_file():
            pages = list(Path(target).rglob("*.html"))
            self.assertTrue(pages, target)
            page = pages[0]
        html = page.read_text(encoding="utf-8")
        self.assertIn(MODULE_BODY, html, "只读 HTML 应与出稿同源（含展开正文）")
        self.assertNotIn("doc-module", html)


class InstanceRecordingTests(unittest.TestCase):
    """4.3：实例映射落盘 + 覆盖率分母（此前无产品写入路径）。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v30-instances")
        cls.project = _project_with_reference(cls.work)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_record_instances_writes_file_and_reports_coverage(self):
        from doc_tool.application.content import reuse_commands as reuse

        context = reuse.load_context(self.project)
        payload = reuse.record_instances(context)
        self.assertTrue(payload.get("ok"), payload)
        marker = self.project / "reuse" / "instances.yml"
        self.assertTrue(marker.is_file(), "应写出 reuse/instances.yml")
        self.assertGreaterEqual(payload.get("instances", 0), 1)
        coverage = payload.get("coverage") or {}
        self.assertIn("included", coverage)
        self.assertGreaterEqual(payload.get("denominator", 0), 1, "覆盖率分母应有可用实例")

        # 幂等：重复登记不改变实例数
        again = reuse.record_instances(context)
        self.assertEqual(again.get("instances"), payload.get("instances"))
        self.assertEqual(again.get("denominator"), payload.get("denominator"))

    def test_resolve_project_can_record_and_expose_coverage(self):
        from doc_tool.application.content import reuse_commands as reuse

        context = reuse.load_context(self.project)
        report = reuse.resolve_project(context, record_instances=True)
        self.assertTrue(report.get("ok"), report.get("message"))
        self.assertIn("instances", report)
        self.assertIn("coverage", report)
        self.assertGreaterEqual((report.get("instances") or {}).get("denominator", 0), 1)
        # 不要求登记时保持旧行为（不写文件、无 coverage 字段）
        plain = reuse.resolve_project(context)
        self.assertNotIn("instances", plain)

    def test_slot_filter_limits_registration(self):
        from doc_tool.application.content import reuse_commands as reuse

        # 用独立项目，避免前一个用例写下的实例影响“未命中”断言
        fresh = _project_with_reference(self.work / "slot-filter")
        context = reuse.load_context(fresh)
        only = reuse.record_instances(context, slot_ids=["s1"])
        self.assertTrue(only.get("ok"), only)
        self.assertGreaterEqual(only.get("instances", 0), 1)

        other = _project_with_reference(self.work / "slot-filter-none")
        other_context = reuse.load_context(other)
        none = reuse.record_instances(other_context, slot_ids=["s-not-exist"])
        self.assertEqual(none.get("registered"), 0, none)
        self.assertEqual(none.get("instances"), 0, none)
        self.assertEqual(none.get("denominator"), 0, none)


if __name__ == "__main__":
    unittest.main(verbosity=2)