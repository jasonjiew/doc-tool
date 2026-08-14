# -*- coding: utf-8 -*-
"""公共品牌与发行元数据（无 Qt 依赖）。

集中定义应用显示名、程序标识、组织设置键、CLI 名、可执行文件名、用户配置
目录名与公共 URL。GUI、CLI、日志、安装器生成、SBOM、CI 与测试均从此模块
读取，避免品牌字符串散落各处，也便于最终公共名称确定后一次性更名。

公共名称当前为 WORKING 占位值（见 ``docs/release/02-release-decisions.md``）；
正式公开前必须完成商标检索与权利人确认。

本模块 MUST NOT 导入 Qt 或任何 GUI 依赖。
"""

from __future__ import annotations

# --- 公共品牌占位值（WORKING） ---

# 面向用户的应用显示名。
APP_DISPLAY_NAME = "Doc Tool"

# 程序标识 / 可执行文件根名（PyInstaller EXE 名、进程名）。
APP_PROGRAM_ID = "DocTool"

# 可执行文件完整文件名（含 .exe）。
APP_EXECUTABLE_NAME = APP_PROGRAM_ID + ".exe"

# 命令行工具名（``argparse`` prog 与帮助文本）。
CLI_NAME = "doc-tool"

# Qt ``QApplication.setOrganizationName`` 使用的组织设置键。
# 中性且稳定；最终公共名称确定前可调整一次。
ORGANIZATION_SETTINGS_KEY = "DocToolProject"

# Qt ``QApplication.setApplicationName`` 使用的应用设置键。
APP_SETTINGS_APPLICATION_KEY = APP_PROGRAM_ID

# 用户级配置目录名（``Path.home() / (".", USER_CONFIG_DIR_NAME)``）。
# 最近项目、窗口几何等非敏感偏好存放在此。
USER_CONFIG_DIR_NAME = "doctool"

# 产品一句话定位（CLI 描述、空状态副标题等）。
PRODUCT_DESCRIPTION = "将大型 Word 文档转换为可维护的 Markdown 章节项目，并可靠重建为 Word。"
PRODUCT_DESCRIPTION_UI = "大型 Word 文档工作台"

# 公共 URL（仓库 / 主页）。公开托管仓库地址，已登记为发布决策。
PUBLIC_URL = "https://github.com/wangjie0721666-web/doc-tool"

# --- 内部版遗留标识（只读迁移/兼容用，禁止出现在公共产物面向用户处） ---

# 内部版 Qt 组织/应用键（旧 QSettings 命名空间）。
LEGACY_ORGANIZATION_KEY = "Konsung"
LEGACY_APP_DISPLAY_NAME = "康尚文档工具"

# 内部版用户配置目录名（``~/.konsung-doc-tool``）。
LEGACY_USER_CONFIG_DIR_NAME = "konsung-doc-tool"

# 内部版可执行文件名与安装目录段（用于品牌一致性扫描与升级检测）。
LEGACY_EXECUTABLE_NAME = "KonsungDocTool.exe"
LEGACY_INSTALL_DIR_SEGMENT = "Konsung\\DocTool"


def user_config_dir() -> str:
    """返回公共版用户配置目录的绝对路径字符串。"""
    import os

    return os.path.join(os.path.expanduser("~"), ".{0}".format(USER_CONFIG_DIR_NAME))


def legacy_user_config_dir() -> str:
    """返回内部版用户配置目录的绝对路径字符串（只读迁移来源）。"""
    import os

    return os.path.join(
        os.path.expanduser("~"), ".{0}".format(LEGACY_USER_CONFIG_DIR_NAME)
    )
