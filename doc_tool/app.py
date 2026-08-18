# -*- coding: utf-8 -*-
"""GUI 入口（PySide6/Qt）。

主窗口已迁移到 PySide6（Qt Widgets）；高 DPI 由 Qt 原生处理。
业务层（domain/application/adapters）不引入 Qt 依赖。

多窗口：``WindowRegistry`` 持有全部主窗口强引用（避免顶层窗口被 GC）；
「在新窗口打开项目」由主窗口经 ``window_factory`` 回调创建新窗口。
关闭最后一个窗口时应用退出（Qt 默认行为）。
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
    from doc_tool.domain.branding import (
        APP_DISPLAY_NAME,
        APP_SETTINGS_APPLICATION_KEY,
        ORGANIZATION_SETTINGS_KEY,
    )

    app.setApplicationName(APP_SETTINGS_APPLICATION_KEY)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORGANIZATION_SETTINGS_KEY)

    # 首次启动：把内部版旧命名空间中的非敏感偏好（窗口几何、最近项目）
    # 只读迁移到公共命名空间；旧值保留，已有公共设置则不覆盖。
    try:
        from doc_tool.application.settings_migration import migrate_legacy_settings

        migrate_legacy_settings()
    except Exception:  # pragma: no cover - 迁移失败不阻断启动
        pass

    from doc_tool.domain.version import APP_VERSION
    from doc_tool.ui.main_window import MainWindow
    from doc_tool.ui.styles import apply_theme, set_window_icon
    from doc_tool.ui.window_registry import WindowRegistry

    # 默认浅色主题（深色可经菜单「工具 → 切换深色主题」启用）。
    apply_theme(app, dark=False)

    registry = WindowRegistry()

    def create_window() -> MainWindow:
        """创建并注册一个主窗口（供「在新窗口打开项目」回调复用）。"""
        window = MainWindow(
            window_registry=registry,
            window_factory=create_window,
        )
        registry.register(window)
        set_window_icon(window)
        return window

    window = create_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
