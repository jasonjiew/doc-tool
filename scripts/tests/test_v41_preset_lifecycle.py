# -*- coding: utf-8 -*-
"""V4.1 41-B 2.4：预设全生命周期与「不被隐式改写」验证。"""

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

from doc_tool.application.template_fill_presets import TemplateFillPresets  # noqa: E402

TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"


class PresetLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-24-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.root = self.work / "presets"
        self.root.mkdir()
        self.template = self.work / "t.docx"
        shutil.copy2(TEMPLATE, self.template)

    def _store(self) -> TemplateFillPresets:
        return TemplateFillPresets(root=self.root)

    def test_save_reopen_rename_delete_full_cycle(self):
        store = self._store()
        saved = store.save_recipe(
            "初始名称",
            {"template": str(self.template), "mapping": {"Heading1": 1, "Gone": 2},
             "layout": {"mode": "body-adaptive", "cover": "封面"}},
            known_style_ids=["Heading1"],
        )
        self.assertEqual(saved["mapping"], {"Heading1": 1}, "失效样式不进入生效映射")
        self.assertEqual(saved["unsupportedLayout"], {"cover": "封面"})

        reopened = self._store()
        self.assertEqual(len(reopened.recipes), 1)
        self.assertEqual(reopened.get_recipe(saved["recipeId"])["name"], "初始名称")

        renamed = reopened.rename_recipe(saved["recipeId"], "改名后")
        self.assertEqual(renamed["recipeId"], saved["recipeId"], "改名不换身份")
        self.assertEqual(renamed["mapping"], {"Heading1": 1}, "改名保留生效映射")
        self.assertEqual(self._store().get_recipe(saved["recipeId"])["name"], "改名后")

        reopened.delete_recipe(saved["recipeId"])
        self.assertEqual(self._store().recipes, [], "删除后重开不得复活")

    def test_stale_style_and_damaged_config_fallback(self):
        store = self._store()
        saved = store.save_recipe(
            "含失效样式",
            {"template": str(self.template), "mapping": {"Heading1": 1, "Gone": 2}},
            known_style_ids=["Heading1", "Gone"],
        )
        self.assertEqual(saved["mapping"], {"Heading1": 1, "Gone": 2}, "当时都有效")

        class _Style:
            def __init__(self, style_id):
                self.style_id = style_id

        class _Styles:
            paragraph_styles = [_Style("Heading1")]

        store.resolve_recipe(saved, _Styles())
        # 底模内容变化 → 给出提醒，但原配方不被改写
        self.template.write_bytes(self.template.read_bytes() + b"changed")
        store.resolve_recipe(saved, _Styles())
        self.assertTrue(any("底模已变化" in item for item in store.warnings))
        self.assertEqual(saved["mapping"], {"Heading1": 1, "Gone": 2}, "原 recipe 不被隐式改写")

        # 损坏配置回退：保留原文件、给提醒、不阻断后续写入
        target = self.root / "template-fill-recipes.json"
        target.write_text("{broken", encoding="utf-8")
        damaged_store = self._store()
        self.assertEqual(damaged_store.recipes, [])
        self.assertTrue(damaged_store.warnings)
        self.assertEqual(target.read_text(encoding="utf-8"), "{broken", "损坏原文件保留")
        damaged_store.save_recipe("恢复预设", {"template": str(self.template)})
        self.assertTrue(list(self.root.glob("template-fill-recipes.json.damaged-*")))

    def test_live_buffer_and_capture_are_not_implicitly_changed(self):
        """保存/重开预设不得改写当前活缓冲或历史捕获文件。"""
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.application.effective_snapshot import capture_snapshot

        from scripts.tests import core_fixtures as fixtures

        project = fixtures.two_chapter_project(self.work / "proj")
        chapter = project / "content" / "general" / "第1章 引言" / "1.1 目的.md"
        self.assertTrue(chapter.is_file(), chapter)
        rel = "第1章 引言/1.1 目的.md"

        buffer_text = "# 目的\n\n未保存的活缓冲正文。\n"
        snapshot = capture_snapshot(
            project, source_mode="current-buffer",
            buffer_texts={rel: buffer_text},
        )
        capture_before = Path(snapshot.workDir) / "content" / rel
        capture_bytes = capture_before.read_bytes() if capture_before.is_file() else b""
        disk_before = chapter.read_bytes()

        store = self._store()
        saved = store.save_recipe(
            "会话预设", {"template": str(self.template), "mapping": {"Heading1": 1}},
            known_style_ids=["Heading1"],
        )
        store.rename_recipe(saved["recipeId"], "改过的会话预设")
        self._store().delete_recipe(saved["recipeId"])

        self.assertEqual(chapter.read_bytes(), disk_before, "预设操作不得改写磁盘正文")
        if capture_before.is_file():
            self.assertEqual(capture_before.read_bytes(), capture_bytes,
                             "预设操作不得改写历史捕获")
        # 活缓冲仍只有本进程持有（源文件未变）
        self.assertNotIn("未保存的活缓冲正文", chapter.read_text(encoding="utf-8"))

    def test_old_record_without_new_fields_still_reads(self):
        """旧记录（没有 layout/unsupportedLayout 字段）必须仍可读、可解析。"""
        payload = {
            "schemaVersion": 1,
            "recipes": [
                {"recipeId": "old-1", "name": "旧预设", "template": str(self.template),
                 "mapping": {"Heading1": 1}, "outputDir": "", "outputName": ""},
            ],
        }
        (self.root / "template-fill-recipes.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        store = self._store()
        self.assertEqual(len(store.recipes), 1)
        self.assertEqual(store.recipes[0]["name"], "旧预设")
        self.assertEqual(store.warnings, [])
        # 未知/缺失字段保持缺省，不伪造
        self.assertNotIn("layout", store.recipes[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)