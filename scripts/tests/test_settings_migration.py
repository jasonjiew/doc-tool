# -*- coding: utf-8 -*-
"""用户偏好设置迁移测试。

任务 3.3：验证首次启动只读迁移的首次执行、幂等、字段过滤、损坏旧设置和无旧
设置行为。

覆盖范围：
- 首次执行：旧目录白名单字段复制到公共目录，旧值保留
- 幂等：重复执行结果一致，不重复覆盖
- 字段过滤：非白名单文件（密钥/缓存）不被迁移
- 损坏旧设置：跳过损坏文件，其余字段仍迁移
- 无旧设置：公共目录不受影响，无操作
- 公共设置已存在：整体跳过，不覆盖用户新设置
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from doc_tool.application.settings_migration import (  # noqa: E402
    ALLOWED_MIGRATION_FILES,
    migrate_legacy_settings,
)


class SettingsMigrationTests(unittest.TestCase):
    """任务 3.1-3.3：设置迁移行为。"""

    def _make_dirs(self):
        tmp = tempfile.TemporaryDirectory(prefix="doc-settings-")
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        public = base / "public"
        legacy = base / "legacy"
        legacy.mkdir(parents=True)
        return public, legacy

    def test_first_run_copies_allowed_fields_and_preserves_legacy(self):
        public, legacy = self._make_dirs()
        geometry = {"geometry": "900x700+10+20", "maximized": True}
        recent = [{"path": "C:/proj", "name": "proj"}]
        (legacy / "geometry.json").write_text(
            json.dumps(geometry, ensure_ascii=False), encoding="utf-8"
        )
        (legacy / "recent.json").write_text(
            json.dumps(recent, ensure_ascii=False), encoding="utf-8"
        )

        report = migrate_legacy_settings(str(public), str(legacy))

        self.assertFalse(report.already_present)
        self.assertEqual(sorted(report.copied), sorted(ALLOWED_MIGRATION_FILES))
        self.assertEqual(
            json.loads((public / "geometry.json").read_text(encoding="utf-8")),
            geometry,
        )
        self.assertEqual(
            json.loads((public / "recent.json").read_text(encoding="utf-8")),
            recent,
        )
        # 旧值保留，未被删除
        self.assertTrue((legacy / "geometry.json").exists())
        self.assertTrue((legacy / "recent.json").exists())

    def test_idempotent(self):
        public, legacy = self._make_dirs()
        (legacy / "geometry.json").write_text(
            json.dumps({"geometry": "A"}, ensure_ascii=False), encoding="utf-8"
        )
        first = migrate_legacy_settings(str(public), str(legacy))
        self.assertEqual(first.copied, ["geometry.json"])
        # 第二次：公共目录已有白名单字段 → already_present，不重复复制
        second = migrate_legacy_settings(str(public), str(legacy))
        self.assertTrue(second.already_present)
        self.assertEqual(second.copied, [])
        # 内容未被再次覆盖
        self.assertEqual(
            json.loads((public / "geometry.json").read_text(encoding="utf-8")),
            {"geometry": "A"},
        )

    def test_field_filtering_excludes_non_whitelist(self):
        public, legacy = self._make_dirs()
        (legacy / "geometry.json").write_text(
            json.dumps({"geometry": "B"}, ensure_ascii=False), encoding="utf-8"
        )
        # 非白名单：密钥与缓存不迁移
        (legacy / "secrets.key").write_text("secret", encoding="utf-8")
        (legacy / "cache.bin").write_bytes(b"\x00\x01")
        report = migrate_legacy_settings(str(public), str(legacy))
        self.assertEqual(report.copied, ["geometry.json"])
        self.assertFalse((public / "secrets.key").exists())
        self.assertFalse((public / "cache.bin").exists())

    def test_corrupt_legacy_setting_is_skipped(self):
        public, legacy = self._make_dirs()
        (legacy / "geometry.json").write_text(
            json.dumps({"geometry": "C"}, ensure_ascii=False), encoding="utf-8"
        )
        (legacy / "recent.json").write_text("{broken json", encoding="utf-8")
        report = migrate_legacy_settings(str(public), str(legacy))
        self.assertEqual(report.copied, ["geometry.json"])
        self.assertIn("recent.json", report.skipped)
        self.assertTrue(report.errors)
        self.assertFalse((public / "recent.json").exists())

    def test_no_legacy_settings_is_noop(self):
        public = Path(tempfile.mkdtemp(prefix="doc-settings-empty-"))
        self.addCleanup(shutil.rmtree, public, ignore_errors=True)
        report = migrate_legacy_settings(str(public), str(public / "absent"))
        self.assertEqual(report.copied, [])
        self.assertFalse(report.already_present)
        self.assertEqual(list(public.iterdir()), [])

    def test_existing_public_settings_not_overwritten(self):
        public, legacy = self._make_dirs()
        # 用户已在公共目录设置过
        public.mkdir(parents=True)
        (public / "recent.json").write_text(
            json.dumps([{"path": "C:/new", "name": "new"}]), encoding="utf-8"
        )
        (legacy / "recent.json").write_text(
            json.dumps([{"path": "C:/old", "name": "old"}]), encoding="utf-8"
        )
        report = migrate_legacy_settings(str(public), str(legacy))
        self.assertTrue(report.already_present)
        # 公共设置未被旧值覆盖
        data = json.loads((public / "recent.json").read_text(encoding="utf-8"))
        self.assertEqual(data[0]["path"], "C:/new")


if __name__ == "__main__":
    unittest.main()
