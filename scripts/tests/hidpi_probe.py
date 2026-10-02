# -*- coding: utf-8 -*-
"""高 DPI 布局探针（子进程内运行，输出机器可读度量）。

用法（父进程/测试调用）：
    QT_SCALE_FACTOR=1.25 python scripts\\tests\\hidpi_probe.py --size 1280x720

说明：这是 Qt 缩放因子**模拟**（离屏），用于回归布局不变式（控件不越界、不为零尺寸、
滚动区可容纳内容）；物理 125%/150% 缩放仍需实机验收。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _rect_inside(inner, outer, tolerance: int = 2) -> bool:
    return (
        inner.left() >= outer.left() - tolerance
        and inner.top() >= outer.top() - tolerance
        and inner.right() <= outer.right() + tolerance
        and inner.bottom() <= outer.bottom() + tolerance
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="1280x720")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    width, height = (int(part) for part in args.size.lower().split("x"))

    from PySide6.QtWidgets import QApplication

    from doc_tool.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(width, height)
    # 离屏也要 show() 才会真正跑布局（否则拿到的是占位尺寸）
    window.show()
    for _ in range(3):
        app.processEvents()

    payload = {
        "scaleFactorEnv": os.environ.get("QT_SCALE_FACTOR", ""),
        "devicePixelRatio": float(window.devicePixelRatioF()),
        "logicalSize": {"width": window.width(), "height": window.height()},
        "physicalSize": {
            "width": int(round(window.width() * window.devicePixelRatioF())),
            "height": int(round(window.height() * window.devicePixelRatioF())),
        },
        "widgets": [],
        "issues": [],
    }
    outer = window.rect()
    checks = [
        ("menuBar", window.menuBar()),
        ("statusBar", window.statusBar()),
        ("stack", getattr(window, "_stack", None)),
        ("home", getattr(window, "_empty_state", None)),
        ("taskDock", getattr(window, "_task_dock", None)),
    ]
    for name, widget in checks:
        if widget is None:
            continue
        size = widget.size()
        visible = bool(widget.isVisibleTo(window))
        entry = {
            "name": name, "width": size.width(), "height": size.height(),
            "visible": visible, "insideWindow": _rect_inside(widget.geometry(), outer, 4),
        }
        payload["widgets"].append(entry)
        if size.width() <= 0 or size.height() <= 0:
            payload["issues"].append("{0} 尺寸为零".format(name))
        if not entry["insideWindow"]:
            payload["issues"].append("{0} 超出窗口范围".format(name))

    # 首页最近项目区：滚动区必须可容纳内容（允许出现纵向滚动条，不允许内容被截断丢失）
    home = getattr(window, "_empty_state", None)
    scroll = getattr(home, "_scroll_area", None) if home is not None else None
    if scroll is not None:
        inner = scroll.widget()
        payload["scroll"] = {
            "viewport": {"width": scroll.viewport().width(), "height": scroll.viewport().height()},
            "content": {
                "width": inner.width() if inner is not None else 0,
                "height": inner.height() if inner is not None else 0,
            },
            "verticalScrollBarVisible": bool(scroll.verticalScrollBar().isVisible()),
            "horizontalScrollBarVisible": bool(scroll.horizontalScrollBar().isVisible()),
        }
        if scroll.horizontalScrollBar().isVisible():
            payload["issues"].append("首页出现横向滚动条（缩放后布局溢出）")

    payload["ok"] = not payload["issues"]
    window.close()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("scale={0} dpr={1} size={2}x{3} issues={4}".format(
            payload["scaleFactorEnv"], payload["devicePixelRatio"],
            payload["logicalSize"]["width"], payload["logicalSize"]["height"], payload["issues"],
        ))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())