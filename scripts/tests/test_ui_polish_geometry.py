# -*- coding: utf-8 -*-
"""UI 包 2.4 / 5.2：固定实际窗口下的控件几何、字体与 DPR 证据记录。

用真实 Qt 窗口（离屏）把 1280×720 与 1024×640 的正文矩形、关键动作几何、
字体与设备像素比写入 ``analysis/ui-polish-B-geometry.txt``，并对可验收的
阈值做强断言。离屏证据单独标识，绝不当作真实 DPI/实机验收（归 5.3）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from doc_tool.application.content.unsaved import UnsavedChoice  # noqa: E402
from doc_tool.ui.main_window import MainWindow  # noqa: E402

#: 几何证据文件（与执行台账里的记录路径一致）。
EVIDENCE_PATH = REPO_ROOT / "analysis" / "ui-polish-B-geometry.txt"

#: 正文控件目标（逻辑像素）：1280×720 默认单栏。
BODY_TARGET = (560, 320)


class GeometryEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._shared = fixtures.scratch_dir("ui-polish-geometry")
        cls._project = fixtures.two_chapter_project(cls._shared / "proj")
        cls._records = []

    @classmethod
    def tearDownClass(cls):
        if cls._records:
            lines = [
                "# UI-B/5.2 控件几何证据（离屏 Qt，仅结构证据；实机 DPI 见 5.3）",
                "# 记录时间：{0}".format(time.strftime("%Y-%m-%d %H:%M:%S")),
                "# 每一行是一个逻辑窗口尺寸下的实测值（JSON）",
            ]
            lines.extend(json.dumps(item, ensure_ascii=False) for item in cls._records)
            EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
            EVIDENCE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fixtures.cleanup(cls._shared)

    def setUp(self):
        self.work = fixtures.scratch_dir("ui-polish-geometry-case")
        self.project = self.work / "proj"
        shutil.copytree(str(self._project), str(self.project))
        leftover = self.project / ".state" / "workspace.json"
        if leftover.exists():
            leftover.unlink()
        self._patches = [
            patch("doc_tool.application.project_service.load_recent_projects", return_value=[]),
            patch("doc_tool.application.project_service.add_recent_project", return_value=None),
            patch("doc_tool.ui.main_window.QMessageBox.information", lambda *a, **k: None),
            patch("doc_tool.ui.main_window.QMessageBox.warning", lambda *a, **k: None),
            patch.object(QMessageBox, "exec", lambda self: None),
        ]
        for item in self._patches:
            item.start()
        self.window = MainWindow(
            unsaved_resolver=lambda rel_paths, context: UnsavedChoice.DISCARD
        )
        self.window.show()

    def tearDown(self):
        try:
            self.window.close()
        except Exception:  # noqa: BLE001
            pass
        for item in self._patches:
            item.stop()
        fixtures.cleanup(self.work)

    def _measure(self, width: int, height: int) -> dict:
        self.window.resize(width, height)
        self.window._open_project_path(str(self.project))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._app.processEvents()
            if getattr(self.window, "_content_index_ready", False):
                break
            time.sleep(0.05)
        self.window._stack.setCurrentWidget(self.window._ide_page)
        self._app.processEvents()

        from doc_tool.application.effective_snapshot import discover_chapters

        content_root = self.project / "content" / "general"
        rels = [rel for rel, _path in discover_chapters(content_root)]
        self.assertTrue(rels)
        self.assertTrue(self.window._open_chapter_in_workspace(rels[0]))
        self._app.processEvents()

        editor = self.window._content_workspace.current_editor()
        self.assertIsNotNone(editor, "编辑器必须就绪才能记录几何")
        body = editor._editor
        screen = self._app.primaryScreen()
        font = body.font()
        record = {
            "windowLogical": [width, height],
            "actualWindow": [self.window.width(), self.window.height()],
            "devicePixelRatio": screen.devicePixelRatio() if screen else None,
            "logicalDpi": screen.logicalDotsPerInch() if screen else None,
            "fontFamily": font.family(),
            "fontPointSize": font.pointSizeF(),
            "bodyRect": [body.width(), body.height()],
            "centerHostRect": [
                self.window._ide_center_host.width(),
                self.window._ide_center_host.height(),
            ],
            "treeDockWidth": self.window._tree_dock.width(),
            "panelsDockVisible": self.window._panels_dock.isVisible(),
            "taskDockVisible": self.window._task_dock_widget.isVisible(),
            "saveRect": list(editor._save_btn.geometry().getRect()),
            "moreRect": list(editor._overflow_btn.geometry().getRect()),
            "previewRect": list(editor._preview_btn.geometry().getRect()),
            "outlineRect": list(editor._outline_btn.geometry().getRect()),
            "overflowVisible": editor._overflow_btn.isVisible(),
            "saveText": editor._save_btn.text(),
        }
        self.__class__._records.append(record)
        print("[geometry] {0}".format(json.dumps(record, ensure_ascii=False)), flush=True)
        return record

    def test_geometry_at_1280x720_meets_body_target(self):
        record = self._measure(1280, 720)
        self.assertGreaterEqual(
            record["bodyRect"][0], BODY_TARGET[0],
            "1280×720 正文宽度不足：{0}".format(record["bodyRect"]),
        )
        self.assertGreaterEqual(
            record["bodyRect"][1], BODY_TARGET[1],
            "1280×720 正文高度不足：{0}".format(record["bodyRect"]),
        )
        self.assertFalse(record["panelsDockVisible"], "默认应收起空闲工具面板")
        self.assertFalse(record["taskDockVisible"], "默认应收起空闲任务/结果面板")
        self.assertIn("保存", record["saveText"])
        self.assertGreater(record["saveRect"][2], 0)
        self.assertGreater(record["saveRect"][3], 0)

    def test_geometry_at_1024x640_keeps_key_actions_usable(self):
        record = self._measure(1024, 640)
        for key in ("saveRect", "previewRect", "outlineRect"):
            rect = record[key]
            self.assertGreater(rect[2], 0, "{0} 宽度必须非零".format(key))
            self.assertGreater(rect[3], 0, "{0} 高度必须非零".format(key))
        # 1024 宽下必须有溢出入口（否则格式动作会被压成不可辨认的竖条）。
        self.assertTrue(record["overflowVisible"], "1024×640 需要「更多 ▾」溢出入口")
        self.assertGreater(record["moreRect"][2], 0)

    def test_text_is_readable_after_opening_project(self):
        """首页非零尺寸不算数：打开项目后正文与关键文字必须有真实高度。"""
        record = self._measure(1280, 720)
        editor = self.window._content_workspace.current_editor()
        font_metrics = editor._editor.fontMetrics()
        self.assertGreater(font_metrics.height(), 8, "正文字体行高过小，文字不可读")
        self.assertGreaterEqual(record["bodyRect"][1], 3 * font_metrics.height(), (
            "正文高度不足 3 行文字：{0} vs 行高 {1}".format(
                record["bodyRect"][1], font_metrics.height()
            )
        ))
        for widget in (editor._save_btn, editor._preview_btn, editor._outline_btn):
            width = widget.fontMetrics().horizontalAdvance(widget.text())
            self.assertGreater(
                widget.width(), width,
                "按钮文字被裁切：{0}（控件 {1}px / 文字 {2}px）".format(
                    widget.text(), widget.width(), width
                ),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)