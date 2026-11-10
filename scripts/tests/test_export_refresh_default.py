# -*- coding: utf-8 -*-
"""导出对话框：WPS 接管时默认关闭 Word 刷新（静态目录兜底）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from PySide6.QtWidgets import QApplication
except Exception:  # noqa: BLE001
    QApplication = None


@unittest.skipIf(QApplication is None, "当前环境没有 PySide6")
class ExportRefreshDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_defaults_on(self) -> None:
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog

        dialog = ExportSettingsDialog(project_root="")
        self.assertTrue(dialog._refresh_box.isChecked())

    def test_wps_machine_defaults_off_but_still_selectable(self) -> None:
        from doc_tool.ui.export_settings_dialog import ExportSettingsDialog

        dialog = ExportSettingsDialog(project_root="", refresh_default=False)
        self.assertFalse(dialog._refresh_box.isChecked())
        # 默认关闭只影响初始状态，用户仍可手动勾选。
        dialog._refresh_box.setChecked(True)
        self.assertTrue(dialog._refresh_box.isChecked())


if __name__ == "__main__":
    unittest.main()
