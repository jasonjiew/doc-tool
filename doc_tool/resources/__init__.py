# -*- coding: utf-8 -*-
"""打包资源：默认配置、模板、图标、安装级说明。

通过 ``resource_root()`` 统一定位，开发态读取仓库资源，打包态读取
PyInstaller 资源目录（任务 8.2）。
"""

from __future__ import annotations

import os
import sys


def resource_root() -> str:
    """返回资源根目录的绝对路径。

    开发态：``doc_tool/resources/`` 所在的仓库目录。
    打包态（PyInstaller）：``sys._MEIPASS`` 下的 ``doc_tool/resources``。
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "doc_tool", "resources")
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    """拼接资源根下的子路径并返回绝对路径。"""
    return os.path.join(resource_root(), *parts)
