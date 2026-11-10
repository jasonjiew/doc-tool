# -*- coding: utf-8 -*-
"""高保真预览诊断：结论、逐项检查与兼容模式（不依赖 Qt）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application import preview_diagnostic as diag  # noqa: E402


class CompatSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "preview.json"

    def test_roundtrip_writes_compat_flag(self) -> None:
        self.assertFalse(diag.compat_mode_enabled(self.path))
        self.assertTrue(diag.set_compat_mode(True, self.path))
        self.assertTrue(diag.compat_mode_enabled(self.path))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(payload["compatMode"])
        self.assertIn("updatedAt", payload)

    def test_corrupt_file_is_tolerated(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(diag.load_preview_settings(self.path), {})
        self.assertFalse(diag.compat_mode_enabled(self.path))

    def test_compat_environment_keeps_user_flags(self) -> None:
        with mock.patch.dict(
            os.environ, {diag.COMPAT_FLAGS_VAR: "--enable-logging"}, clear=False
        ):
            values = diag.compat_environment()
        self.assertEqual(values[diag.COMPAT_ENV_KEY], "1")
        self.assertIn("--enable-logging", values[diag.COMPAT_FLAGS_VAR])
        self.assertIn(diag.COMPAT_FLAG, values[diag.COMPAT_FLAGS_VAR])
        # 幂等：重复计算不会重复追加同一个参数。
        with mock.patch.dict(
            os.environ, {diag.COMPAT_FLAGS_VAR: values[diag.COMPAT_FLAGS_VAR]}, clear=False
        ):
            again = diag.compat_environment()
        self.assertEqual(
            again[diag.COMPAT_FLAGS_VAR].count(diag.COMPAT_FLAG),
            1,
        )

    def test_apply_only_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(
            os.environ, {diag.HOME_ENV_OVERRIDE: home}, clear=False
        ):
            os.environ.pop(diag.COMPAT_ENV_KEY, None)
            self.assertEqual(diag.apply_compat_environment(), {})
            diag.set_compat_mode(True)
            applied = diag.apply_compat_environment()
            self.assertEqual(applied[diag.COMPAT_ENV_KEY], "1")
            self.assertEqual(os.environ[diag.COMPAT_ENV_KEY], "1")


class DiagnosticCollectionTests(unittest.TestCase):
    def _resources(self) -> tempfile.TemporaryDirectory:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in diag.REQUIRED_RESOURCES:
            (Path(tmp.name) / name).write_text("x", encoding="utf-8")
        return tmp

    def test_missing_module_offers_source_install(self) -> None:
        with mock.patch.object(
            diag, "_module_status", side_effect=lambda name: (False, "不可用（ImportError）")
        ):
            report = diag.collect_diagnostic("ImportError: no QtWebEngine")
        self.assertFalse(report.frozen)
        self.assertTrue(report.can_install)
        self.assertIn(diag.PINNED_PYSIDE, report.install_command)
        self.assertIn("QtWebEngine", report.summary)
        self.assertTrue(any("一键安装" in item for item in report.actions))

    def test_frozen_missing_module_points_to_package(self) -> None:
        with mock.patch.object(diag.sys, "frozen", True, create=True), mock.patch.object(
            diag, "_module_status", side_effect=lambda name: (False, "不可用")
        ), mock.patch.object(diag, "_package_components", return_value=[]):
            report = diag.collect_diagnostic("DLL load failed")
        self.assertTrue(report.frozen)
        self.assertFalse(report.can_install)
        self.assertTrue(any("重新完整解压" in item for item in report.actions))

    def test_missing_resources_reported(self) -> None:
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with mock.patch.object(diag, "_module_status", side_effect=lambda name: (True, "可导入")), \
                mock.patch.object(diag, "resource_directory", return_value=Path(empty.name)):
            report = diag.collect_diagnostic()
        self.assertIn("资源", report.summary)
        self.assertTrue(any("preview.html" in name for name, _ in report.checks))

    def test_component_ok_suggests_compat_mode(self) -> None:
        resources = self._resources()
        with mock.patch.object(diag, "_module_status", side_effect=lambda name: (True, "可导入")), \
                mock.patch.object(diag, "resource_directory", return_value=Path(resources.name)), \
                mock.patch.object(diag, "compat_mode_enabled", return_value=False):
            report = diag.collect_diagnostic()
        self.assertIn("运行环境", report.summary)
        self.assertTrue(any("兼容模式" in item for item in report.actions))

    def test_transient_module_error_is_reported_as_retry(self) -> None:
        """初始化报过 ImportError、但此刻复测通过时，不能归因成纯环境问题。"""
        resources = self._resources()
        with mock.patch.object(diag, "_module_status", side_effect=lambda name: (True, "可导入")), \
                mock.patch.object(diag, "resource_directory", return_value=Path(resources.name)), \
                mock.patch.object(diag, "compat_mode_enabled", return_value=False):
            report = diag.collect_diagnostic(
                "ImportError: No module named 'PySide6.QtWebEngineWidgets'"
            )
        self.assertIn("复测", report.summary)

    def test_report_text_contains_checks_and_traceback(self) -> None:
        with mock.patch.object(diag, "_module_status", side_effect=lambda name: (True, "可导入")):
            report = diag.collect_diagnostic("boom", "Traceback: line 1")
        text = report.to_text()
        self.assertIn("高保真预览诊断", text)
        self.assertIn("结论：", text)
        self.assertIn("Traceback: line 1", text)
        self.assertIn("PySide6 版本", text)


if __name__ == "__main__":
    unittest.main()
