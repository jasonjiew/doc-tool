# -*- coding: utf-8 -*-
"""单元测试：自升级领域模型、运行形态识别与 latest.json 生成校验。

覆盖 REQ-01, REQ-03。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve()
DOC_TOOL_ROOT = HERE.parents[2]
if str(DOC_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(DOC_TOOL_ROOT))

from doc_tool.domain.update import (
    ReleaseManifest,
    UpdateState,
    detect_install_mode,
    is_newer_version,
    parse_semver,
)

import importlib.util

_gen_spec = importlib.util.spec_from_file_location(
    "generate_latest_json_module",
    DOC_TOOL_ROOT / "packaging" / "generate_latest_json.py",
)
_gen_module = importlib.util.module_from_spec(_gen_spec)
_gen_spec.loader.exec_module(_gen_module)
generate_latest_json = _gen_module.generate_latest_json


class TestUpdateDomain(unittest.TestCase):
    """测试语义版本解析、比较与运行形态探测。"""

    def test_parse_semver_valid(self):
        self.assertEqual(parse_semver("3.0.1"), (3, 0, 1, ""))
        self.assertEqual(parse_semver("v3.0.1"), (3, 0, 1, ""))
        self.assertEqual(parse_semver("V1.2.3-rc.1"), (1, 2, 3, "rc.1"))
        self.assertEqual(parse_semver("2.1"), (2, 1, 0, ""))
        self.assertEqual(parse_semver("4"), (4, 0, 0, ""))

    def test_parse_semver_invalid(self):
        self.assertEqual(parse_semver(""), (0, 0, 0, ""))
        self.assertEqual(parse_semver(None), (0, 0, 0, ""))
        self.assertEqual(parse_semver("invalid_version"), (0, 0, 0, "invalid_version"))

    def test_is_newer_version_numeric(self):
        self.assertTrue(is_newer_version("3.1.0", "3.0.1"))
        self.assertTrue(is_newer_version("4.0.0", "3.99.99"))
        self.assertTrue(is_newer_version("3.0.2", "3.0.1"))
        self.assertFalse(is_newer_version("3.0.1", "3.0.1"))
        self.assertFalse(is_newer_version("3.0.0", "3.0.1"))
        self.assertFalse(is_newer_version("2.9.9", "3.0.0"))

    def test_is_newer_version_prerelease(self):
        # 正式版高于预发布版
        self.assertTrue(is_newer_version("3.1.0", "3.1.0-rc1"))
        self.assertFalse(is_newer_version("3.1.0-rc1", "3.1.0"))

        # 预发布版比较
        self.assertTrue(is_newer_version("3.1.0-rc2", "3.1.0-rc1"))
        self.assertTrue(is_newer_version("3.1.0-beta.2", "3.1.0-beta.1"))
        self.assertFalse(is_newer_version("3.1.0-beta.1", "3.1.0-beta.2"))

    def test_detect_install_mode_source(self):
        # sys.frozen 为 False 时一律判定为 source
        mode = detect_install_mode(frozen=False)
        self.assertEqual(mode, "source")

    def test_detect_install_mode_installer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "DocTool.exe"
            exe_path.touch()

            # 情况 1：根目录下有 unins000.exe
            unins_root = Path(temp_dir) / "unins000.exe"
            unins_root.touch()
            self.assertEqual(
                detect_install_mode(frozen=True, executable_path=str(exe_path)),
                "installer",
            )
            unins_root.unlink()

            # 情况 2：uninst 子目录下有 unins000.exe
            uninst_dir = Path(temp_dir) / "uninst"
            uninst_dir.mkdir()
            (uninst_dir / "unins000.exe").touch()
            self.assertEqual(
                detect_install_mode(frozen=True, executable_path=str(exe_path)),
                "installer",
            )

    def test_detect_install_mode_portable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "DocTool.exe"
            exe_path.touch()
            # 冻结打包但没有卸载程序
            self.assertEqual(
                detect_install_mode(frozen=True, executable_path=str(exe_path)),
                "portable",
            )

    def test_release_manifest_serialization(self):
        manifest = ReleaseManifest(
            tag_name="v3.1.0",
            version="3.1.0",
            published_at="2026-10-28T00:00:00Z",
            release_notes="Bug fixes and upgrades",
            installer_url="https://example.com/Setup.exe",
            installer_sha256="abc123def456",
            portable_url="https://example.com/Portable.zip",
            portable_sha256="7890abcdef12",
        )
        data = manifest.to_dict()
        self.assertEqual(data["version"], "3.1.0")
        self.assertEqual(data["installer_sha256"], "abc123def456")

        restored = ReleaseManifest.from_dict(data)
        self.assertEqual(restored.version, manifest.version)
        self.assertEqual(restored.portable_sha256, manifest.portable_sha256)

    def test_update_state_serialization(self):
        state = UpdateState(
            last_checked_at="2026-10-28T12:00:00Z",
            skipped_version="3.0.2",
            auto_check=False,
            custom_endpoint="https://internal-repo/releases",
        )
        data = state.to_dict()
        restored = UpdateState.from_dict(data)
        self.assertEqual(restored.skipped_version, "3.0.2")
        self.assertFalse(restored.auto_check)
        self.assertEqual(restored.custom_endpoint, "https://internal-repo/releases")

    def test_generate_latest_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            td = Path(temp_dir)
            setup_exe = td / "DocTool-Setup-3.1.0.exe"
            setup_exe.write_bytes(b"dummy setup executable content")

            portable_zip = td / "DocTool-3.1.0-portable.zip"
            portable_zip.write_bytes(b"dummy portable zip content")

            notes_file = td / "release-notes.md"
            notes_file.write_text("## Release 3.1.0\n- Online update feature", encoding="utf-8")

            output_file = td / "latest.json"

            data = generate_latest_json(
                output_path=output_file,
                version="3.1.0",
                setup_exe=setup_exe,
                portable_zip=portable_zip,
                release_notes=notes_file,
                repo_url="https://github.com/test-org/doc-tool",
            )

            self.assertTrue(output_file.is_file())
            loaded = json.loads(output_file.read_text(encoding="utf-8"))

            self.assertEqual(loaded["version"], "3.1.0")
            self.assertEqual(loaded["tag_name"], "v3.1.0")
            self.assertIn("Online update feature", loaded["release_notes"])
            self.assertTrue(loaded["installer_sha256"])
            self.assertTrue(loaded["portable_sha256"])
            self.assertEqual(
                loaded["installer_url"],
                "https://github.com/test-org/doc-tool/releases/download/v3.1.0/DocTool-Setup-3.1.0.exe",
            )
            self.assertEqual(
                loaded["portable_url"],
                "https://github.com/test-org/doc-tool/releases/download/v3.1.0/DocTool-3.1.0-portable.zip",
            )


if __name__ == "__main__":
    unittest.main()
