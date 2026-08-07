# -*- coding: utf-8 -*-
"""统一应用版本、提交标识、项目模式版本及构建信息。

任务 1.5：实现统一应用版本、提交标识、项目模式版本及构建信息模块。
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from functools import lru_cache
from typing import Dict


# 应用语义版本：正式发布前为 0.x，1.0.0 对应计划第 10 节的正式交付。
APP_VERSION = "0.1.0"

# 项目清单 ``project.yml`` 的模式版本。每次不兼容变更必须 +1 并实现迁移。
PROJECT_SCHEMA_VERSION = 1

# 当前应用支持读写的历史与当前模式版本集合。
SUPPORTED_PROJECT_SCHEMA_VERSIONS = (1,)


@lru_cache(maxsize=1)
def get_commit_id() -> str:
    """返回当前工作树来源的短提交标识，无法确定时返回 ``"dev"``。

    构建信息只用于诊断和发布追溯，不作为运行期逻辑分支条件。
    """
    repo_root = _find_repo_root()
    if repo_root is None:
        return "dev"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        commit = result.stdout.strip()
        if result.returncode == 0 and commit:
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if dirty.stdout.strip():
                commit += "-dirty"
            return commit
    except (OSError, subprocess.SubprocessError):
        pass
    return "dev"


def _find_repo_root() -> str | None:
    """从本文件位置向上查找 git 仓库根目录。"""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def get_build_info() -> Dict[str, str]:
    """返回可复制、脱敏的构建与环境诊断摘要。"""
    return {
        "appVersion": APP_VERSION,
        "commit": get_commit_id(),
        "projectSchemaVersion": str(PROJECT_SCHEMA_VERSION),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def is_supported_schema(version: int) -> bool:
    """判断项目模式版本是否被当前应用支持读写。"""
    return version in SUPPORTED_PROJECT_SCHEMA_VERSIONS


def can_read_schema(version: int) -> bool:
    """当前应用能否以只读方式打开该模式版本的项目。

    首版只支持 v1；未来更高版本由新版应用以只读方式兼容打开。
    """
    return version in SUPPORTED_PROJECT_SCHEMA_VERSIONS or version > PROJECT_SCHEMA_VERSION


def can_write_schema(version: int) -> bool:
    """当前应用能否写入该模式版本的项目。

    拒绝写入高于当前支持的更高模式版本，避免破坏性降级。
    """
    return version in SUPPORTED_PROJECT_SCHEMA_VERSIONS
