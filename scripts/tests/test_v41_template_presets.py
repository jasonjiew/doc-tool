# -*- coding: utf-8 -*-
"""V4.1 41-B：受支持的模板/映射/版式预设（保存/重开/重命名/删除与回退）。"""

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

from doc_tool.application.template_fill_presets import (  # noqa: E402
    SUPPORTED_LAYOUT_FIELDS,
    TemplateFillPresets,
    collect_layout_fields,
    preset_payload,
    validate_layout_fields,
    validate_style_mapping,
)


def _docx(path: Path, payload: bytes = b"PK\x03\x04stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class LayoutFieldTests(unittest.TestCase):
    """只列真实消费者支持的字段；未知声明保留但不声称生效。"""

    def test_supported_field_list_matches_consumer(self):
        from doc_tool.application.export.layout_profile import LayoutProfile

        known = set(LayoutProfile.__dataclass_fields__)  # type: ignore[attr-defined]
        for field_name in SUPPORTED_LAYOUT_FIELDS:
            self.assertIn(field_name, known, field_name)

    def test_unknown_fields_are_kept_but_not_supported(self):
        supported, unsupported = collect_layout_fields({
            "mode": "body-adaptive", "cover": "企业封面", "header": "页眉占位",
        })
        self.assertEqual(supported, {"mode": "body-adaptive"})
        self.assertEqual(sorted(unsupported), ["cover", "header"])

    def test_invalid_values_are_dropped_with_reason(self):
        valid, problems = validate_layout_fields({
            "mode": "fancy", "image_width": "auto-width",
            "table_width": "diagonal", "repeat_header": "yes",
            "landscape_chapters": ["第2章"], "page_break_before_chapter": True,
        })
        self.assertEqual(valid, {
            "image_width": "auto-width",
            "landscape_chapters": ["第2章"],
            "page_break_before_chapter": True,
        })
        self.assertEqual(len(problems), 3, problems)

    def test_valid_values_round_trip_through_consumer(self):
        valid, problems = validate_layout_fields({
            "mode": "body-adaptive", "image_width": "auto-width", "table_width": "equal",
            "repeat_header": True, "allow_row_split": False,
            "landscape_chapters": ["第3章"], "page_break_before_chapter": True,
        })
        self.assertEqual(problems, [])
        from doc_tool.application.export.layout_profile import LayoutProfile

        profile = LayoutProfile.from_dict(valid)
        self.assertEqual(profile.mode, "body-adaptive")
        self.assertEqual(profile.table_width, "equal")
        self.assertTrue(profile.repeat_header)
        self.assertFalse(profile.allow_row_split)
        self.assertEqual(profile.landscape_chapters, ["第3章"])
        self.assertTrue(profile.page_break_before_chapter)


class StyleMappingTests(unittest.TestCase):
    def test_invalid_mapping_is_dropped_with_summary(self):
        valid, dropped, summary = validate_style_mapping(
            {"Heading1": 1, "OldStyle": 2, "Weird": 9, "Bad": "x"},
            known_style_ids=["Heading1", "OldStyle"],
        )
        self.assertEqual(valid, {"Heading1": 1, "OldStyle": 2})
        self.assertEqual(len(dropped), 2)
        self.assertIn("保留 2 项有效映射", summary)
        self.assertTrue(any("Weird" in item for item in dropped), dropped)
        self.assertTrue(any("Bad" in item for item in dropped), dropped)

    def test_all_valid_has_no_summary(self):
        valid, dropped, summary = validate_style_mapping(
            {"Heading1": 1}, known_style_ids=["Heading1"],
        )
        self.assertEqual(valid, {"Heading1": 1})
        self.assertEqual(dropped, [])
        self.assertEqual(summary, "")


class PresetPayloadTests(unittest.TestCase):
    """预设与正文来源/范围严格分开。"""

    def test_scope_and_source_are_not_stored_in_preset(self):
        payload = preset_payload({
            "template": "t.docx", "mapping": {"Heading1": 1},
            "scope": {"kind": "chapters", "chapters": ["a.md"]},
            "sourceMode": "current-buffer", "captureId": "cap-1",
            "layout": {"mode": "body-adaptive"},
        }, known_style_ids=["Heading1"])
        for key in ("scope", "sourceMode", "source_mode", "captureId", "capture_id"):
            self.assertNotIn(key, payload, "预设不得携带正文来源/范围：{0}".format(key))
        self.assertEqual(payload["mapping"], {"Heading1": 1})
        self.assertEqual(payload["layout"], {"mode": "body-adaptive"})

    def test_unsupported_declarations_are_preserved(self):
        payload = preset_payload({
            "template": "t.docx",
            "layout": {"mode": "template", "fonts": {"body": "宋体"}, "cover": "封面"},
        })
        self.assertEqual(payload["layout"], {"mode": "template"})
        self.assertEqual(sorted(payload["unsupportedLayout"]), ["cover", "fonts"])


class PresetStoreTests(unittest.TestCase):
    """保存/重开/重命名/删除与损坏配置回退。"""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="v41-presets-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.root = self.work / "presets"
        self.root.mkdir()
        self.template = _docx(self.work / "t.docx")

    def _store(self) -> TemplateFillPresets:
        return TemplateFillPresets(root=self.root)

    def test_save_then_reopen_keeps_supported_facts(self):
        store = self._store()
        saved = store.save_recipe(
            "需求说明书企业版",
            {
                "template": str(self.template), "outputDir": str(self.work / "out"),
                "mapping": {"Heading1": 1, "Heading2": 2, "Gone": 3},
                "layout": {"mode": "body-adaptive", "table_width": "equal", "cover": "封面"},
            },
            known_style_ids=["Heading1", "Heading2"],
        )
        self.assertTrue(saved["templateHash"])
        self.assertEqual(saved["mapping"], {"Heading1": 1, "Heading2": 2})
        self.assertEqual(saved["layout"], {"mode": "body-adaptive", "table_width": "equal"})
        self.assertEqual(saved["unsupportedLayout"], {"cover": "封面"})
        self.assertIn("保留 2 项有效映射", saved["mappingSummary"])

        reopened = self._store()
        item = reopened.get_recipe(saved["recipeId"])
        self.assertIsNotNone(item, "重开后必须能读到同一条预设")
        self.assertEqual(item["name"], "需求说明书企业版")
        self.assertEqual(item["mapping"], {"Heading1": 1, "Heading2": 2})
        self.assertEqual(item["layout"], {"mode": "body-adaptive", "table_width": "equal"})
        self.assertEqual(item["unsupportedLayout"], {"cover": "封面"})
        self.assertEqual(reopened.warnings, [])

    def test_rename_keeps_identity_and_settings(self):
        store = self._store()
        saved = store.save_recipe("旧名", {"template": str(self.template)}, known_style_ids=[])
        renamed = store.rename_recipe(saved["recipeId"], "新名")
        self.assertEqual(renamed["recipeId"], saved["recipeId"], "重命名不得换身份")
        self.assertEqual(renamed["name"], "新名")
        reopened = self._store()
        self.assertEqual(len(reopened.recipes), 1)
        self.assertEqual(reopened.recipes[0]["name"], "新名")

    def test_delete_removes_only_that_preset(self):
        store = self._store()
        first = store.save_recipe("甲", {"template": str(self.template)})
        second = store.save_recipe("乙", {"template": str(self.template)})
        store.delete_recipe(first["recipeId"])
        names = [item["name"] for item in store.recipes]
        self.assertEqual(names, ["乙"])
        self.assertIsNone(store.get_recipe(first["recipeId"]))
        self.assertIsNotNone(self._store().get_recipe(second["recipeId"]))

    def test_corrupt_config_falls_back_and_is_preserved(self):
        target = self.root / "template-fill-recipes.json"
        target.write_text("{ this is not json", encoding="utf-8")
        original = target.read_text(encoding="utf-8")
        store = self._store()
        self.assertEqual(store.recipes, [], "损坏配置回退为空而不是崩溃")
        self.assertTrue(store.warnings, "必须给出可读提醒")
        self.assertEqual(target.read_text(encoding="utf-8"), original, "损坏原文件必须保留")
        # 显式写入时先备份损坏文件
        store.save_recipe("恢复后的预设", {"template": str(self.template)})
        backups = list(self.root.glob("template-fill-recipes.json.damaged-*"))
        self.assertTrue(backups, "覆盖损坏配置前必须另存 .damaged 备份")

    def test_stale_style_ids_are_reported_on_resolve(self):
        store = self._store()
        saved = store.save_recipe(
            "含失效样式", {"template": str(self.template), "mapping": {"Heading1": 1, "Gone": 2}},
            known_style_ids=["Heading1", "Gone"],
        )
        class _Style:
            def __init__(self, style_id):
                self.style_id = style_id

        class _Styles:
            paragraph_styles = [_Style("Heading1")]

        resolved = store.resolve_recipe(saved, _Styles())
        self.assertEqual(resolved["mapping"], {"Heading1": 1}, "失效样式不得留在生效映射里")
        # 底模内容变化会给出提醒（不改写原配方）
        self.template.write_bytes(b"PK\x03\x04changed")
        store.resolve_recipe(saved, _Styles())
        self.assertTrue(any("底模已变化" in item for item in store.warnings))
        self.assertEqual(saved["mapping"], {"Heading1": 1, "Gone": 2}, "原配方不被隐式改写")

    def test_reload_recovers_after_external_fix(self):
        store = self._store()
        store.save_recipe("甲", {"template": str(self.template)})
        # 外部把文件改成坏内容后 reload 应回退并告警，原文件保留
        (self.root / "template-fill-recipes.json").write_text("[]", encoding="utf-8")
        store.reload()
        self.assertTrue(store.warnings)
        # 修好后 reload 恢复
        self._store().save_recipe("乙", {"template": str(self.template)})
        store.reload()
        self.assertEqual([item["name"] for item in store.recipes], ["乙"])


if __name__ == "__main__":
    unittest.main(verbosity=2)