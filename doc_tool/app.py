# -*- coding: utf-8 -*-
"""GUI 入口（PySide6/Qt）。

主窗口已迁移到 PySide6（Qt Widgets）；高 DPI 由 Qt 原生处理。
业务层（domain/application/adapters）不引入 Qt 依赖。
"""

from __future__ import annotations

import sys


def main() -> int:
    # PyInstaller 冻结应用使用 spawn 子进程对 Word COM 探测施加真实超时。
    import multiprocessing

    multiprocessing.freeze_support()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover
        print(
            "当前环境缺少 PySide6，无法启动图形界面。"
            "请先安装：python -m pip install PySide6。",
            file=sys.stderr,
        )
        print("原始错误：{0}".format(exc), file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("康尚文档工具")
    app.setApplicationDisplayName("康尚文档工具")
    app.setOrganizationName("Konsung")

    from doc_tool.domain.version import APP_VERSION
    from doc_tool.ui.main_window import MainWindow
    from doc_tool.ui.styles import apply_theme, set_window_icon

    # 默认浅色主题（深色可经菜单「工具 → 切换深色主题」启用）。
    apply_theme(app, dark=False)

    window = MainWindow()
    set_window_icon(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
