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


# 应用语义版本：2.3.2 为修复独立校验模式错配（自适应已刷新正式产物与未刷新草稿门禁）并增强时效与产物提醒；
# 2.3.1 为原生支持 graph TD 语法与 Word 遗留段落注释裸流程图自愈提取；
# 2.3.0 为全局命令面板（Ctrl+K/Ctrl+P 秒级直达）、Markdown 表格智能编辑与等宽对齐、
# 预览区轻量代码语法高亮、以及改动评审稿导出与闭环；
# 2.2.0 为 PDF 工具箱集成上线、首页高定视觉重构与 COM 进程假死防护自愈；
# 2.1.0 为文档互转——Word/PDF/Markdown/HTML/TXT/表格/RTF/ODT 任意互转
# （首页任务页、工具菜单与 CLI convert 子命令）；2.0.0 为公司内部维护基线，
# 统一安装版与免安装便携版分发，发布说明使用中文；
# 1.4.4 启动不再复制到 %TEMP%（透明加密客户端如亿赛通 DocGuard 会加密复制
# 出的 .pyd 导致启动失败），已签名产物原地启动；扩展模块导入失败时写日志+弹窗报错；
# 1.4.3 分发产物全量 PE 代码签名（公司自签名证书，scripts/cert-out 可复用），
# 便携包/安装器随附信任证书与成员引导说明；
# 1.4.2 冻结启动自愈（安全软件拦截扩展模块加载时自动迁移到
# %TEMP% 稳定目录重启；彻底失败时弹窗报错并写日志）与随包诊断脚本；
# 1.4.0 为修订记录以 _revision_record.md 为唯一维护点，并修复修订表
# 回填、排版与换行；1.3.0 的 mermaid 官方网页渲染后端已撤销（ad5c1fd），未发布；
# 1.2.0 为多窗口、版本控制变更、mermaid-cli 渲染与机器可读 CLI 发布。
APP_VERSION = "2.3.2"

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
