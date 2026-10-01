# -*- coding: utf-8 -*-
"""V2.8 28-C：规范包解析、安全验证、固定与通用示例包（3.1、3.2、3.3、3.4、3.5）。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.standard_pack import (  # noqa: E402
    STANDARDS_DIR,
    backup_pack,
    diff_packs,
    extract_pack_zip,
    install_pack,
    load_project_pack,
    pack_fingerprint,
    pack_resources,
    pack_skeleton_files,
    validate_pack_dir,
)

PACKS_DIR = REPO_ROOT / "standards"
SAMPLE_PACK = PACKS_DIR / "generic-requirement"


class PublicPackTests(unittest.TestCase):
    """3.4：三个可公开分发的包都必须合法。"""

    def test_all_three_packs_validate(self):
        index = json.loads((PACKS_DIR / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(index), {"generic-requirement", "generic-design", "generic-test"}
        )
        for name in index:
            validation = validate_pack_dir(PACKS_DIR / name)
            self.assertTrue(validation.ok, "{0}: {1}".format(name, validation.errors))
            self.assertFalse(validation.warnings, validation.warnings)

    def test_skeleton_and_variables_present(self):
        validation = validate_pack_dir(SAMPLE_PACK)
        pack = validation.pack
        self.assertIsNotNone(pack)
        self.assertEqual(pack.document_kind, "requirement")
        self.assertTrue(pack_skeleton_files(pack))
        resources = pack_resources(pack)
        self.assertIsNotNone(resources["variables"])
        self.assertIsNotNone(resources["rules"])

    def test_pack_contains_no_executable_files(self):
        for path in PACKS_DIR.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    path.suffix.lower(),
                    (".py", ".js", ".exe", ".dll", ".bat", ".ps1"),
                    str(path),
                )


class PackValidationTests(unittest.TestCase):
    """3.1：声明、类型、hash 与资源限制。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-pack-"))
        self.pack = self.tmp / "pack"
        shutil.copytree(SAMPLE_PACK, self.pack)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_required_fields_reported(self):
        (self.pack / "pack.yml").write_text("schemaVersion: 1", encoding="utf-8")
        validation = validate_pack_dir(self.pack)
        self.assertFalse(validation.ok)
        self.assertTrue(any("packId" in item for item in validation.errors))

    def test_unsupported_schema_version_rejected(self):
        text = (self.pack / "pack.yml").read_text(encoding="utf-8")
        (self.pack / "pack.yml").write_text(
            text.replace("schemaVersion: 1", "schemaVersion: 9"), encoding="utf-8"
        )
        validation = validate_pack_dir(self.pack)
        self.assertFalse(validation.ok)

    def test_hash_mismatch_warns_but_still_usable(self):
        variables = self.pack / "variables.yml"
        variables.write_text(
            variables.read_text(encoding="utf-8") + "\n# 人工修改\n",
            encoding="utf-8",
        )
        validation = validate_pack_dir(self.pack)
        self.assertTrue(validation.ok, validation.errors)
        self.assertTrue(any("hash" in item for item in validation.warnings))
        # 默认策略：hash 不匹配仍可使用（非严格）
        self.assertIsNotNone(validation.pack)

    def test_declared_file_missing_is_error(self):
        text = (self.pack / "pack.yml").read_text(encoding="utf-8")
        (self.pack / "pack.yml").write_text(
            text.replace("  variables.yml:", "  ghost.yml:"), encoding="utf-8"
        )
        validation = validate_pack_dir(self.pack)
        self.assertFalse(validation.ok)
        self.assertTrue(any("不存在" in item for item in validation.errors))

    def test_executable_entry_rejected(self):
        (self.pack / "evil.py").write_text("print(1)", encoding="utf-8")
        text = (self.pack / "pack.yml").read_text(encoding="utf-8")
        (self.pack / "pack.yml").write_text(
            text + "  evil.py: \"\"\n", encoding="utf-8"
        )
        validation = validate_pack_dir(self.pack)
        self.assertFalse(validation.ok)
        self.assertTrue(any("可执行" in item or "插件" in item for item in validation.errors))


class ZipSafetyTests(unittest.TestCase):
    """3.5：路径穿越/绝对路径/符号链接与超限。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-zip-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _zip_from_pack(self, target: Path, extra=None) -> Path:
        archive = self.tmp / "pack.zip"
        with zipfile.ZipFile(archive, "w") as package:
            for path in SAMPLE_PACK.rglob("*"):
                if path.is_file():
                    package.write(path, path.relative_to(SAMPLE_PACK).as_posix())
            for name, payload in (extra or {}).items():
                if payload is None:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (0xA1FF << 16)
                    package.writestr(info, "link")
                else:
                    package.writestr(name, payload)
        return archive

    def test_traversal_entry_rejected(self):
        archive = self._zip_from_pack(self.tmp, {"../evil.yml": "x"})
        result = extract_pack_zip(archive, self.tmp / "out")
        self.assertFalse(result.ok)
        self.assertTrue(any("越界" in item for item in result.errors))
        self.assertFalse((self.tmp / "evil.yml").exists())

    def test_absolute_entry_rejected(self):
        archive = self._zip_from_pack(self.tmp, {"/abs.yml": "x"})
        result = extract_pack_zip(archive, self.tmp / "out")
        self.assertFalse(result.ok)

    def test_symlink_entry_rejected(self):
        archive = self._zip_from_pack(self.tmp, {"link.yml": None})
        result = extract_pack_zip(archive, self.tmp / "out")
        self.assertFalse(result.ok)
        self.assertTrue(any("符号链接" in item for item in result.errors))

    def test_clean_zip_extracts_and_validates(self):
        archive = self._zip_from_pack(self.tmp)
        result = extract_pack_zip(archive, self.tmp / "out")
        self.assertTrue(result.ok, result.errors)
        self.assertIsNotNone(result.pack)


class InstallAndUpgradeTests(unittest.TestCase):
    """3.2/3.3：固定版本、项目内读取、升级差异与备份。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v28-install-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_install_pins_version_and_reuses_existing(self):
        target, result = install_pack(SAMPLE_PACK, self.tmp)
        self.assertTrue(result.ok, result.errors)
        self.assertIsNotNone(target)
        self.assertTrue(target.is_dir())
        self.assertEqual(
            target.relative_to(self.tmp).as_posix(),
            "{0}/generic-requirement/1.0.0".format(STANDARDS_DIR),
        )
        again, second = install_pack(SAMPLE_PACK, self.tmp)
        self.assertEqual(again, target)
        self.assertTrue(any("已在项目内固定" in item for item in second.warnings))

    def test_project_load_without_absolute_paths(self):
        install_pack(SAMPLE_PACK, self.tmp)
        pack, warnings = load_project_pack(
            self.tmp, {"id": "generic-requirement", "version": "1.0.0"}
        )
        self.assertIsNotNone(pack)
        self.assertFalse([w for w in warnings if "hash" in w])
        self.assertTrue(pack_fingerprint(pack))

    def test_hash_mismatch_reported_default_still_usable(self):
        install_pack(SAMPLE_PACK, self.tmp)
        pack, _ = load_project_pack(
            self.tmp, {"id": "generic-requirement", "version": "1.0.0"}
        )
        loaded, warnings = load_project_pack(
            self.tmp,
            {"id": "generic-requirement", "version": "1.0.0", "hash": "deadbeef"},
        )
        self.assertIsNotNone(loaded, "默认策略下 hash 不匹配仍可用")
        self.assertTrue(any("hash" in item for item in warnings))

    def test_missing_pack_falls_back_with_readable_reason(self):
        pack, warnings = load_project_pack(
            self.tmp, {"id": "nope", "version": "9.9.9"}
        )
        self.assertIsNone(pack)
        self.assertTrue(any("回退" in item for item in warnings))

    def test_upgrade_backups_and_reports_differences(self):
        install_pack(SAMPLE_PACK, self.tmp)
        current, _ = load_project_pack(
            self.tmp, {"id": "generic-requirement", "version": "1.0.0"}
        )
        candidate_dir = self.tmp / "candidate"
        shutil.copytree(SAMPLE_PACK, candidate_dir)
        text = (candidate_dir / "pack.yml").read_text(encoding="utf-8")
        (candidate_dir / "pack.yml").write_text(
            text.replace("version: 1.0.0", "version: 1.1.0"), encoding="utf-8"
        )
        validation = validate_pack_dir(candidate_dir)
        self.assertTrue(validation.ok, validation.errors)
        lines = diff_packs(current, validation.pack)
        self.assertTrue(any("1.0.0" in line and "1.1.0" in line for line in lines))
        self.assertTrue(any("不会被自动覆盖" in line for line in lines))
        backup = backup_pack(self.tmp, {"id": "generic-requirement", "version": "1.0.0"})
        self.assertIsNotNone(backup)
        self.assertTrue(Path(backup).is_dir())


if __name__ == "__main__":
    unittest.main()