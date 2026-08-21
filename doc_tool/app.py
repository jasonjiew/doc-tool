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


def _is_frozen() -> bool:
    """是否运行于 PyInstaller 冻结产物中。"""
    return bool(getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None))


def main() -> int:
    # PyInstaller 冻结应用使用 spawn 子进程对 Word COM 探测施加真实超时。
    try:
        import multiprocessing

        multiprocessing.freeze_support()
    except ImportError:
        # 缺 multiprocessing（如冻结环境下 _socket 被安全软件拦截）时跳过，
        # GUI 与常规文档构建不受影响；Word 预检降级为静态判定，见 word_check。
        pass
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover
        if _is_frozen():
            # 冻结态下扩展模块导入失败，最常见的根因是终端安全软件拦截未签名
            # exe 从当前目录加载 DLL。交给自愈模块：写日志并弹消息框给出处置指引
            # （不再静默退出；1.4.4 起不再复制到 %TEMP%，见 self_heal 模块说明）。
            from doc_tool.application import self_heal

            return self_heal.handle_blocked_import(exc)
        print(
            "当前环境缺少 PySide6，无法启动图形界面。"
            "请先安装：python -m pip install PySide6。",
            file=sys.stderr,
        )
        print("原始错误：{0}".format(exc), file=sys.stderr)
        return 1

    if _is_frozen():
        # 冻结 GUI 没有控制台，未捕获异常会被静默吞掉、成员机器上表现为
        # 「双击没反应」。冻结态兜底：显示消息框并落盘日志。
        try:
            return _run_gui(QApplication)
        except Exception as exc:  # noqa: BLE001 - 启动期兜底，必须兜住一切
            from doc_tool.application import self_heal

            return self_heal.report_startup_failure(exc)
    return _run_gui(QApplication)


def _run_gui(QApplication) -> int:
    """GUI 主体（原 main() 的后半段，独立出来便于启动期兜底）。"""

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
