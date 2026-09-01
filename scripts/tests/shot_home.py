# -*- coding: utf-8 -*-
"""渲染首页任务页（EmptyState）浅/深主题截图，供与视觉稿人工比对。

用法：python scripts/tests/shot_home.py [输出目录]
默认输出到仓库根：home_final_light.png / home_final_dark.png
示例数据为虚构条目，不读写真实「最近项目」列表。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from doc_tool.application.project_service import RecentEntry  # noqa: E402
from doc_tool.ui.empty_state import EmptyState  # noqa: E402
from doc_tool.ui.styles import apply_theme  # noqa: E402


def _sample_entries():
    now = datetime.now(timezone.utc)
    return [
        RecentEntry(
            path=str(REPO_ROOT / "examples" / "requirement"),
            name="requirement",
            document_name="需求说明书（示例）",
            document_type="requirement",
            last_opened=(now - timedelta(days=3, minutes=5)).isoformat(
                timespec="seconds"
            ),
        ),
        RecentEntry(
            path=str(REPO_ROOT / "examples" / "design"),
            name="design",
            document_name="详细设计说明书（示例）",
            document_type="design",
            last_opened=(now - timedelta(days=1, minutes=5)).isoformat(
                timespec="seconds"
            ),
        ),
    ]


def _shot(dark: bool, out: Path) -> None:
    app = QApplication.instance() or QApplication([])
    apply_theme(app, dark=dark)
    home = EmptyState(on_convert=lambda: None)
    home.set_recent_projects(_sample_entries())
    # 不在真实屏幕上闪窗：渲染到离屏窗口再抓图。
    home.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    home.resize(1120, 720)
    home.show()
    app.processEvents()
    home.grab().save(str(out))
    home.close()
    print("saved", out)


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT
    _shot(False, out_dir / "home_final_light.png")
    _shot(True, out_dir / "home_final_dark.png")


if __name__ == "__main__":
    main()
