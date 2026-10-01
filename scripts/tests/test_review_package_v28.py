# -*- coding: utf-8 -*-
"""V2.8 28-G：HTML 评审包与意见幂等回流（7.1～7.4）。"""

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

from doc_tool.application.export.review_package import (  # noqa: E402
    PACKAGE_SCHEMA,
    build_review_package,
    import_review_package,
    payload_with_comments,
)
from doc_tool.application.review.review_store import ReviewStore  # noqa: E402
from doc_tool.application.review.versioned_review import content_hash, legacy_status  # noqa: E402

NL = chr(10)


class PackageBuildTests(unittest.TestCase):
    """7.1：自足、无外链、有意见表单与下载。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-pack-"))
        self.assets = self.tmp / "assets"
        self.assets.mkdir()
        self.image = self.assets / "fig-1.png"
        self.image.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
                "00000049454e44ae426082"
            )
        )
        self.chapters = [
            (
                "1 概述",
                NL.join(
                    [
                        "# 1 概述",
                        "",
                        "![图](fig-1.png)",
                        "",
                        "| A | B |",
                        "| --- | --- |",
                        "| 1 | 2 |",
                        "",
                    ]
                ),
            )
        ]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_package_is_self_contained(self):
        result = build_review_package(
            self.tmp, self.chapters, output_dir=self.tmp / "out", asset_roots=[self.assets]
        )
        self.assertTrue(result.ok)
        text = result.html_path.read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", text)
        # 无外部资源引用：不得出现远程 src/href，图片必须为内联 data URI
        self.assertNotIn('src="http', text)
        self.assertNotIn("href=\"http", text)
        self.assertNotIn('src="fig-1.png"', text)
        self.assertNotIn("<img src=\"assets/", text)
        self.assertIn("review-form", text)
        self.assertIn("下载意见 JSON", text)

    def test_payload_contract_and_json_sidecar(self):
        result = build_review_package(
            self.tmp, self.chapters, output_dir=self.tmp / "out", asset_roots=[self.assets]
        )
        payload = json.loads(result.json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], PACKAGE_SCHEMA)
        for key in ("projectId", "packageId", "createdAt", "contentHashes", "comments"):
            self.assertIn(key, payload)
        self.assertIn("1 概述", payload["contentHashes"])

    def test_missing_image_only_warns(self):
        chapters = [("1", "![x](missing.png)")]
        result = build_review_package(
            self.tmp, chapters, output_dir=self.tmp / "out", asset_roots=[self.assets]
        )
        self.assertTrue(result.ok)
        self.assertTrue(any("未找到" in item for item in result.warnings))

    def test_scripts_and_html_are_escaped(self):
        chapters = [("1", "<script>alert(1)</script> & <b>x</b> {{a}}")]
        result = build_review_package(
            self.tmp, chapters, output_dir=self.tmp / "out", asset_roots=[self.assets]
        )
        text = result.html_path.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", text)
        self.assertIn("&lt;script&gt;", text)
        # 评审包自带的脚本仍在，但内容里的标签已转义
        self.assertIn('id="download"', text)

    def test_comparison_section_when_provided(self):
        result = build_review_package(
            self.tmp,
            self.chapters,
            output_dir=self.tmp / "out",
            asset_roots=[self.assets],
            compare_with=[("1 概述", "旧版内容")],
        )
        text = result.html_path.read_text(encoding="utf-8")
        self.assertIn("与上一版对照", text)
        self.assertIn("旧版内容", text)

    def test_existing_comment_count_reported(self):
        store = ReviewStore(self.tmp / ".state")
        store.add_comment("r1", "author", "a.md", 1)
        result = build_review_package(
            self.tmp,
            self.chapters,
            output_dir=self.tmp / "out",
            asset_roots=[self.assets],
            review_store=store,
        )
        self.assertEqual(result.comment_count, 1)
        self.assertIn("r1", result.html_path.read_text(encoding="utf-8"))


class ImportTests(unittest.TestCase):
    """7.2/7.3：验证、幂等、拒绝与回滚。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-import-"))
        self.store = ReviewStore(self.tmp / ".state")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data, name="in.json") -> Path:
        target = self.tmp / name
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return target

    def _payload(self, **overrides):
        data = {
            "schema": PACKAGE_SCHEMA,
            "projectId": "proj-1",
            "packageId": "pkg-1",
            "createdAt": "2026-10-01T00:00:00+00:00",
            "contentHashes": {},
            "comments": [],
        }
        data.update(overrides)
        return data

    def test_import_adds_comments(self):
        path = self._write(
            self._payload(
                comments=[
                    {"author": "a", "text": "第一条", "relPath": "a.md", "lineNo": 3, "chapterNo": "1"}
                ]
            )
        )
        result = import_review_package(path, self.store, project_id="proj-1")
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.added, 1)
        self.assertEqual(len(self.store.comments()), 1)

    def test_duplicate_import_is_idempotent(self):
        payload = self._payload(
            comments=[{"author": "a", "text": "第一条", "relPath": "a.md", "lineNo": 3}]
        )
        path = self._write(payload)
        import_review_package(path, self.store, project_id="proj-1")
        second = import_review_package(path, self.store, project_id="proj-1")
        self.assertTrue(second.success)
        self.assertEqual(second.added, 0)
        self.assertEqual(second.duplicates, 1)
        self.assertEqual(len(self.store.comments()), 1)

    def test_other_project_rejected(self):
        path = self._write(self._payload(projectId="other"))
        result = import_review_package(path, self.store, project_id="proj-1")
        self.assertFalse(result.success)
        self.assertIn("其他项目", result.rejected_reason)
        self.assertEqual(self.store.comments(), [])

    def test_wrong_schema_rejected(self):
        path = self._write(self._payload(schema="some-other/v9"))
        result = import_review_package(path, self.store, project_id="proj-1")
        self.assertFalse(result.success)
        self.assertEqual(self.store.comments(), [])

    def test_corrupt_file_rejected_without_write(self):
        target = self.tmp / "broken.json"
        target.write_text("{ not json", encoding="utf-8")
        result = import_review_package(target, self.store, project_id="proj-1")
        self.assertFalse(result.success)
        self.assertIn("损坏", result.rejected_reason)
        self.assertEqual(self.store.comments(), [])

    def test_old_hash_comment_enters_recheck(self):
        path = self._write(
            self._payload(
                comments=[
                    {
                        "author": "a",
                        "text": "基于旧版",
                        "relPath": "a.md",
                        "lineNo": 1,
                        "contentHash": content_hash("旧版"),
                    }
                ]
            )
        )
        result = import_review_package(
            path,
            self.store,
            project_id="proj-1",
            current_hashes={"a.md": content_hash("新版")},
        )
        self.assertTrue(result.success)
        self.assertEqual(result.pending_recheck, 1)
        self.assertEqual(legacy_status(self.store.comments()[0]), "待复核")

    def test_invalid_items_skipped(self):
        path = self._write(
            self._payload(
                comments=[
                    {"author": "", "text": "x"},
                    {"author": "a", "text": ""},
                    "not-a-dict",
                    {"author": "a", "text": "有效"},
                ]
            )
        )
        result = import_review_package(path, self.store, project_id="proj-1")
        self.assertTrue(result.success)
        self.assertEqual(result.added, 1)
        self.assertEqual(result.skipped, 3)

    def test_write_failure_rolls_back_and_reports(self):
        from unittest import mock

        path = self._write(
            self._payload(
                comments=[
                    {"author": "a", "text": "一", "relPath": "a.md", "lineNo": 1},
                    {"author": "b", "text": "二", "relPath": "a.md", "lineNo": 2},
                ]
            )
        )
        original = self.store.update_comment
        calls = {"n": 0}

        def _flaky(comment_id, **kwargs):
            calls["n"] += 1
            # 第二条意见写入时失败，验证会回滚已写入的第一条。
            if calls["n"] >= 2:
                raise RuntimeError("注入写入失败")
            return original(comment_id, **kwargs)

        with mock.patch.object(self.store, "update_comment", side_effect=_flaky):
            result = import_review_package(path, self.store, project_id="proj-1")
        self.assertFalse(result.success)
        self.assertIn("回滚", result.message)
        self.assertEqual(self.store.comments(), [], "失败必须回滚本次范围")

    def test_interrupted_write_leaves_no_partial(self):
        path = self._write(
            self._payload(
                comments=[{"author": "a", "text": "一", "relPath": "a.md", "lineNo": 1}]
            )
        )
        from unittest import mock

        # 中断场景拟合到真正写盘的内部方法（公开方法只是包装）。
        with mock.patch.object(
            self.store, "_save_comments", side_effect=OSError("磁盘错误")
        ):
            result = import_review_package(path, self.store, project_id="proj-1")
        self.assertFalse(result.success, result.message)
        self.assertEqual(result.added, 0)
        self.assertEqual(self.store.comments(), [])


if __name__ == "__main__":
    unittest.main()