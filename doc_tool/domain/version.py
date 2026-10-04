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


# 应用语义版本：3.0.0 研发工作区与主流程可用性——Word 导入结果页与重导入差异预览
# （按章选择）、批量章节复制/移动与跨目录引用重写、资产面板实时缓冲校验、
# 质量工作台分组修正与规则试跑、模板库与小样试出稿、交付准备与接收人包
# （版本比较/修订说明/离线入口/副本恢复）、Word 运行可靠性与阶段诊断
# （进程归属清理、停止预算、LAST_REPORT 阶段事实）。
# 2.9.0 变更可追溯——研发文档工作区（多文档角色与集合版本）、
# 稳定条目 DOC-ITEM 与旧编号迁移、显式关系图（satisfies/verifies/depends_on）、
# 需求—设计—测试矩阵与可解释覆盖率（N/A 不报 0%）、变更影响与复核记录、
# 完整集合基线事务（逐文件 SHA-256、租约、部分集合）与基线查询/比较/安全恢复；
# CLI 新增 ``trace`` 与 ``impact``。
# 2.8.0 面向团队标准化——项目 schema v2（显式章节与变量、
# 默认保持 v1）、声明式规范包（解析/安全解压/固定版本/升级差异）与三个通用示例包、
# 项目内共享规则/术语（quality/ 位置 + 旧 .state 迁移）、项目概览聚合、
# 内容版本评审生命周期与修订记录预填、离线 HTML 评审包与幂等回流、
# 重导入计划/应用与 Git 三方冲突合并。
# 2.7.0 建立跨入口共享表达契约与可靠交付——
# 共享块模型/代码容器、离线 Mermaid 构建预处理与缓存、题注与交叉引用（SEQ/REF 域 + 静态缓存值）、
# 显式横向节与分页、内置结构预览统一（停用 WebEngine 分支）、发布质量门禁（构建前检查 + STAGE_AUDIT）、
# 统一 ``check`` 命令与结构化报告、无 Word/刷新失败的可打开待刷新产物与安全登记回滚。
# 2.6.1 补齐本地历史/回收站、交付历史、预设预检、创作辅助及只读 HTML。
# 2.6.0 为模板填充——Word 底模 + Markdown 离线出稿（互转模板方向、专属向导、
# CLI template-fill 子命令）、样式映射兜底、完整文档底模正文清理、内容保真降级（行内图片/引用块/
# 代码块/Setext/任务列表/front matter）；
# 2.5.2 为全仓代码审计与缺陷修复、路径与清单规范化、Windows 大小写去重、修订表提取鲁棒性及回归测试套件加固；
# 2.5.1 为格式检查分类检索与一键批量修复、项目加载遮罩穿透防假死、后台预热 VCS 消除冻结；
# 2.5.0 为 Word 导入向导大纲树实时预览与 .doc 格式安全拦截、离线 PDF 工具箱新增页面重排（15项工具）与高级参数增强、文档互转交互升级与可执行文件防呆、首页 Docs-as-Code 流水线引导与最近项目快速检索；
# 2.4.0 为 Mermaid 极速矢量预览与沉浸式大图查看器、现代 Web 预览与双向定位、异步操作加载遮罩、版本控制与改动比对、文档质检自然排序与一键修复、Word 排版优化；
# 2.3.2 为修复独立校验模式错配（自适应已刷新正式产物与未刷新草稿门禁）并增强时效与产物提醒；
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
APP_VERSION = "3.0.0"

# 项目清单 ``project.yml`` 的模式版本。每次不兼容变更必须 +1 并实现迁移。
# v2（V2.8）新增可选 ``documentKind`` / ``chapters`` / ``variables`` / ``standardPack``；
# v1 继续可读可写，升级必须由用户显式选择（默认保持 v1）。
PROJECT_SCHEMA_VERSION = 2

# 当前应用支持读写的历史与当前模式版本集合。
SUPPORTED_PROJECT_SCHEMA_VERSIONS = (1, 2)


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
