# -*- coding: utf-8 -*-
"""V3.3 2.3/3.4 补测：模块更新建议；摘要候选的真实取消路径。"""

from __future__ import annotations

import hashlib
import os
import shutil
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


def _project_with_outdated_module(work: Path) -> Path:
    """项目固定引用 m-arch@1.0.0，而库中已有 1.1.0。"""
    from doc_tool.application.content import reuse_commands as reuse
    from doc_tool.application.effective_snapshot import discover_chapters

    project = fixtures.two_chapter_project(work / "proj")
    content = project / "content" / "general"
    rels = [rel for rel, _path in discover_chapters(content)]
    context = reuse.load_context(project)
    result = reuse.extract_chapter_module(context, rels[1], module_id="m-arch", version="1.0.0")
    assert result.get("ok"), result
    # 发布 1.1.0（复制 1.0.0 并改版本），再显式声明装配 slot 固定 1.0.0
    library_root = Path(reuse.load_context(project).library.root)
    shutil.copytree(library_root / "m-arch" / "1.0.0", library_root / "m-arch" / "1.1.0")
    module_yml = library_root / "m-arch" / "1.1.0" / "module.yml"
    module_yml.write_text(
        module_yml.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.1.0"),
        encoding="utf-8",
    )
    assembly = project / "reuse" / "assembly.yml"
    assembly.parent.mkdir(parents=True, exist_ok=True)
    assembly.write_text(
        "schemaVersion: 1\nslots:\n  - slotId: s1\n    moduleId: m-arch\n    version: 1.0.0\n"
        "    chapter: {0}\n".format(rels[0]),
        encoding="utf-8",
    )
    return project


class ModuleUpdateSuggestionTests(unittest.TestCase):
    """2.3：模块更新接为建议（只提示、不写装配、不当证据）。"""

    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("v33-module-update")
        cls.project = _project_with_outdated_module(cls.work)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_outdated_module_yields_update_suggestion(self):
        from doc_tool.application.assist.models import KIND_MODULE_UPDATE
        from doc_tool.application.assist.suggestions import SuggestionEngine

        engine = SuggestionEngine.from_project(self.project)
        collected = engine.collect(kinds=[KIND_MODULE_UPDATE])
        items = collected.of_kind(KIND_MODULE_UPDATE)
        self.assertTrue(items, collected.counts())
        item = items[0]
        self.assertIn("模块可升级", item.title)
        self.assertIn("1.1.0", item.title)
        self.assertEqual(item.apply_mode, "none", "模块更新只提示，不得自动改装配")
        self.assertNotEqual(item.status, "conflict")
        self.assertTrue(item.evidence and item.evidence[0].label)
        self.assertTrue(item.not_evidence, "建议不得作为通过证据")
        assembly_before = (self.project / "reuse" / "assembly.yml").read_text(encoding="utf-8")
        self.assertIn("1.0.0", assembly_before)
        # 再次收集不改变装配（无副作用）
        engine.collect(kinds=[KIND_MODULE_UPDATE])
        self.assertEqual(
            (self.project / "reuse" / "assembly.yml").read_text(encoding="utf-8"),
            assembly_before,
        )

    def test_missing_module_version_is_reported(self):
        from doc_tool.application.assist.models import KIND_MODULE_UPDATE
        from doc_tool.application.assist.suggestions import SuggestionEngine

        project = _project_with_outdated_module(self.work / "missing")
        assembly = project / "reuse" / "assembly.yml"
        assembly.write_text(
            "schemaVersion: 1\nslots:\n  - slotId: s9\n    moduleId: not-in-library\n"
            "    version: 2.0.0\n    chapter: 第1章 引言/1.1 目的.md\n",
            encoding="utf-8",
        )
        engine = SuggestionEngine.from_project(project)
        items = engine.collect(kinds=[KIND_MODULE_UPDATE]).of_kind(KIND_MODULE_UPDATE)
        self.assertTrue(items, "库中没有任何版本时应给出提示")
        self.assertIn("模块版本缺失", items[0].title)


class SummaryCancelTests(unittest.TestCase):
    """3.4：摘要候选可被**真实取消**——不新增修订记录、不改评审状态。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])
        cls.work = fixtures.scratch_dir("v33-summary-cancel")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        content = cls.project / "content" / "general"
        cls.revision_rel = "_revision_record.md"
        cls.revision_path = content / cls.revision_rel
        if not cls.revision_path.is_file():
            cls.revision_path.write_text(
                "# 修订记录 - general\n\n| 版本 | 修改摘要 | 修改时间 | 修改人 |\n"
                "|------|----------|----------|--------|\n",
                encoding="utf-8",
            )
        reviews = cls.project / ".state" / "relation_reviews.json"
        reviews.parent.mkdir(parents=True, exist_ok=True)
        reviews.write_text('{"reviews": [{"relationId": "rel-1", "status": "待复核"}]}', encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _window(self):
        from doc_tool.application.project_service import load_recent_projects  # noqa: F401
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths
        from doc_tool.ui.content.unsaved_prompt import UnsavedChoice
        from doc_tool.ui.main_window import MainWindow

        self._recent = patch("doc_tool.application.project_service.load_recent_projects", return_value=[])
        self._recent.start()
        window = MainWindow(unsaved_resolver=lambda rel, ctx: UnsavedChoice.DISCARD)
        summary = SimpleNamespace(
            project_root=self.project,
            is_writable=True,
            manifest=ProjectManifest.load(self.project),
            paths=ProjectPaths(self.project),
        )
        window._project_summary = summary
        window._init_content_workspace(summary)
        self.assertTrue(window._open_chapter_in_workspace(self.revision_rel), "应能打开修订记录")
        return window

    def _editor(self, window):
        tabs = window._content_workspace.tabs_host
        for key in ("general/" + self.revision_rel, self.revision_rel):
            editor = tabs.editor_for(key)
            if editor is not None:
                return editor
        self.fail("修订记录未在工作区打开")

    def test_cancel_discards_candidate_without_writing(self):
        window = self._window()
        try:
            editor = self._editor(window)
            target = editor._editor
            before_disk = self.revision_path.read_text(encoding="utf-8")
            reviews_path = self.project / ".state" / "relation_reviews.json"
            before_reviews = hashlib.sha256(reviews_path.read_bytes()).hexdigest()
            before_text = target.toPlainText()

            window._on_assist_summary_candidate("候选摘要：本轮补充离线出稿说明。")
            self.assertIn("候选摘要", target.toPlainText())
            self.assertTrue(editor.is_dirty(), "候选只是未保存编辑")
            self.assertEqual(self.revision_path.read_text(encoding="utf-8"), before_disk,
                             "填入候选不得立刻写盘")
            self.assertTrue(window._discard_summary_action.isEnabled())

            # 真实取消：撤销这次插入
            self.assertTrue(window._discard_assist_summary_candidate())
            self.assertEqual(target.toPlainText(), before_text, "取消后编辑器应回到原文")
            self.assertEqual(self.revision_path.read_text(encoding="utf-8"), before_disk,
                             "取消后磁盘修订记录不得变化")
            self.assertEqual(hashlib.sha256(reviews_path.read_bytes()).hexdigest(), before_reviews,
                             "取消不得改动评审状态")
            self.assertFalse(window._discard_summary_action.isEnabled())

            # 对照：填入并保存才会写盘（且仍不改评审状态）
            window._on_assist_summary_candidate("候选摘要：本轮补充离线出稿说明。")
            self.assertTrue(editor.save())
            on_disk = self.revision_path.read_text(encoding="utf-8")
            self.assertIn("候选摘要", on_disk)
            self.assertEqual(hashlib.sha256(reviews_path.read_bytes()).hexdigest(), before_reviews)
        finally:
            self._recent.stop()
            window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)