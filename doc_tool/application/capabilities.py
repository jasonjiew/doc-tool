# -*- coding: utf-8 -*-
"""能力自省与环境契约服务（capabilities）。"""

from __future__ import annotations

import platform
import sys
from typing import Any, Dict

from doc_tool.domain.branding import CLI_NAME, PRODUCT_DESCRIPTION
from doc_tool.domain.version import (
    APP_VERSION,
    PROJECT_SCHEMA_VERSION,
    SUPPORTED_PROJECT_SCHEMA_VERSIONS,
    get_build_info,
)


def get_capabilities_report() -> Dict[str, Any]:
    """返回免安装 CLI 的完整能力清单、构建来源与命令契约。"""
    info = get_build_info()
    return {
        "schemaVersion": 1,
        "command": "capabilities",
        "tool": {
            "name": CLI_NAME,
            "description": PRODUCT_DESCRIPTION,
            "appVersion": info.get("appVersion", APP_VERSION),
            "commit": info.get("commit", "dev"),
            "buildSource": info.get("buildSource", "source-tree"),
            "buildTime": info.get("buildTime", "unspecified"),
            "frozen": info.get("frozen") == "true",
            "python": info.get("python", sys.version.split()[0]),
            "platform": info.get("platform", platform.platform()),
            "machine": info.get("machine", platform.machine()),
        },
        "projectSchema": {
            "current": PROJECT_SCHEMA_VERSION,
            "supported": list(SUPPORTED_PROJECT_SCHEMA_VERSIONS),
        },
        "commands": [
            {
                "name": "capabilities",
                "description": "显示工具版本、固化构建来源、支持命令与环境契约",
                "readOnly": True,
                "options": ["--format", "--report-file"],
                "exitCodes": {"0": "正常完成", "2": "参数非法"},
            },
            {
                "name": "baseline-check",
                "description": "核对清单、修订记录、指定版本声明、冻结基线与已有确认来源",
                "readOnly": True,
                "options": ["--project", "--workspace", "--declare-file", "--format", "--report-file"],
                "exitCodes": {"0": "基线一致且确认有效", "1": "发现版本冲突、基线缺失或确认失效", "2": "参数或项目路径错误"},
            },
            {
                "name": "item-list",
                "description": "按项目/章节查询稳定需求与设计条目（DOC-ITEM），支持分页与摘要",
                "readOnly": True,
                "options": ["--project", "--workspace", "--chapter", "--query", "--page", "--page-size", "--format", "--report-file"],
                "exitCodes": {"0": "查询成功", "1": "条目存在重复或严重缺失", "2": "参数或路径错误"},
            },
            {
                "name": "item-show",
                "description": "查看单个条目的详细内容、原子正文、关联资源与关系",
                "readOnly": True,
                "options": ["--project", "--workspace", "--item", "--format", "--report-file"],
                "exitCodes": {"0": "成功定位", "1": "未找到条目或条目歧义", "2": "参数错误"},
            },
            {
                "name": "review-status",
                "description": "查询与指定内容/基线绑定的评审意见、复核及签审失效状态",
                "readOnly": True,
                "options": ["--project", "--workspace", "--baseline", "--format", "--report-file"],
                "exitCodes": {"0": "查询成功且无待复核/失效项", "1": "存在待复核关系或失效确认", "2": "参数错误"},
            },
            {
                "name": "trace-plan",
                "description": "预览旧编号迁移至稳定条目（DOC-ITEM）的建议与歧义项（只读）",
                "readOnly": True,
                "options": ["--project", "--workspace", "--format", "--report-file"],
                "exitCodes": {"0": "成功生成稳定迁移计划", "1": "发现不可消解的歧义项", "2": "参数错误"},
            },
            {
                "name": "trace",
                "description": "需求—设计—测试矩阵与可解释覆盖率（保留原契约）",
                "readOnly": True,
                "options": ["--project", "--workspace", "--format", "--fail-on-uncovered"],
                "exitCodes": {"0": "矩阵完成", "1": "存在未覆盖需求且要求门禁", "2": "执行失败"},
            },
            {
                "name": "impact",
                "description": "变更影响与待复核计算（支持同章多条目与基线快照比对）",
                "readOnly": True,
                "options": ["--project", "--workspace", "--baseline", "--item", "--format", "--fail-on-pending"],
                "exitCodes": {"0": "影响计算完成且无待复核", "1": "存在待复核关系且要求门禁", "2": "执行失败"},
            },
            {
                "name": "change-report",
                "description": "接收多仓库 Git 元数据、测试与人工证据，生成 MR 附件与机器报告",
                "readOnly": True,
                "options": ["--manifest", "--git-evidence", "--junit", "--manual-test", "--project", "--baseline", "--change-id", "--openspec", "--format", "--report-file"],
                "exitCodes": {"0": "全部门禁满足且证据充分", "1": "测试未通过、证据不齐或信息受阻", "2": "参数或解析错误"},
            },
            {
                "name": "check",
                "description": "统一质量门禁检查（源校验/可选构建）",
                "readOnly": True,
                "options": ["--project", "--output", "--fail-on", "--build", "--strict"],
                "exitCodes": {"0": "未达阈值", "1": "达到检查阈值", "2": "参数或执行失败"},
            },
        ],
        "legacyCommandContracts": {
            "validate": {
                "outputOption": "--output (choices: human, json)",
                "formatOption": "--format (choices: sarif, junit)",
                "note": "旧版多项目校验入口，支持 SARIF/JUnit 输出",
            },
            "check": {
                "outputOption": "--output (choices: text, json, sarif)",
                "note": "统一检查入口，默认做源检查，--strict 提升约定为阻断",
            },
            "trace": {
                "formatOption": "--format (choices: markdown, json, csv)",
                "note": "显式矩阵输出，stdout 仅输出单一文档",
            },
            "impact": {
                "formatOption": "--format (choices: markdown, json)",
                "note": "直接/传递影响与复核状态，--baseline 用于快照比对",
            },
            "project-export": {
                "outputOption": "--output (choices: human, json)",
                "note": "出稿机器报告，0=有可用产物，1=全失败，2=参数非法/严格失败",
            },
        },
        "environment": {
            "pythonRequired": False,
            "sourceCodeRequired": False,
            "wordRequiredForBasicQueries": False,
            "wordRequiredForFullTOCRefresh": True,
            "portableZeroInstall": True,
        },
        "status": "passed",
        "issues": [],
    }
