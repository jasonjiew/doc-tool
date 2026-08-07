# -*- coding: utf-8 -*-
"""康尚文档工具：将公司 Word 文档自动化产品化为团队可安装的 Windows 桌面应用。

分层架构：
- ``domain``      项目清单、路径、版本与错误模型（纯逻辑，无 IO 副作用）
- ``adapters``    OOXML、Word COM、文件系统、日志适配
- ``application`` 导入、构建、校验、合并、打开目录等用例
- ``ui``          tkinter 桌面界面与后台任务桥接
- ``resources``   默认配置、图标、安装级说明
"""

from __future__ import annotations

from doc_tool.domain.version import (
    APP_VERSION,
    PROJECT_SCHEMA_VERSION,
    get_build_info,
    get_commit_id,
)

__all__ = [
    "APP_VERSION",
    "PROJECT_SCHEMA_VERSION",
    "get_build_info",
    "get_commit_id",
]

__version__ = APP_VERSION
