# -*- coding: utf-8 -*-
"""结构化错误类型与稳定错误码。

任务 5.3 的基础：定义结构化错误类型、稳定错误码、用户说明和建议操作。
错误码格式 ``E<区域><三位序号>``，区域划分：
- ``E1xxx`` 导入预检与拆分
- ``E2xxx`` 构建与校验
- ``E3xxx`` Word 刷新
- ``E4xxx`` 项目模型与锁
- ``E5xxx`` 文件系统与资源
- ``E9xxx`` 内部错误
"""

from __future__ import annotations

from typing import Dict, Optional


class DocToolError(Exception):
    """所有文档工具错误的基类。

    Attributes:
        code: 稳定错误码，跨版本不变，用于日志、界面和用户反馈。
        user_message: 面向终端用户的简明说明（中文）。
        suggested_action: 建议的修复或下一步操作。
        details: 附加诊断键值对（脱敏，不含正文或凭据）。
    """

    code: str = "E9000"
    user_message: str = "发生未知错误。"
    suggested_action: str = "请查看日志并联系支持人员。"

    def __init__(
        self,
        user_message: Optional[str] = None,
        *,
        suggested_action: Optional[str] = None,
        details: Optional[Dict[str, str]] = None,
    ) -> None:
        self.user_message = user_message or self.user_message
        self.suggested_action = suggested_action or self.suggested_action
        self.details = details or {}
        super().__init__(self.user_message)

    def to_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "message": self.user_message,
            "suggestedAction": self.suggested_action,
            "details": dict(self.details),
        }


# --- 导入预检与拆分（E1xxx） ---


class InvalidDocxError(DocToolError):
    code = "E1001"
    user_message = "所选文件不是合法的 DOCX。"
    suggested_action = "请确认文件扩展名为 .docx 且未被加密或损坏。"


class MissingHeading1Error(DocToolError):
    code = "E1002"
    user_message = "源文档没有可识别的 Heading 1 标题样式。"
    suggested_action = "请在 Word 中为一级标题应用“标题 1”样式后重新导入。"


class HeadingHierarchyError(DocToolError):
    code = "E1003"
    user_message = "标题层级跳跃，无法构成可闭合的章节树。"
    suggested_action = "请检查标题样式层级（如 H1 后直接出现 H3），修正后重新导入。"


class BrokenRelationshipError(DocToolError):
    code = "E1004"
    user_message = "文档内部引用关系损坏或目标缺失。"
    suggested_action = "请在 Word 中检查图片、表格等引用是否完整，修复后重新导入。"


class TargetProjectExistsError(DocToolError):
    code = "E1005"
    user_message = "目标项目目录已存在。"
    suggested_action = "首次导入不会覆盖已有项目，请选择新的项目名称或目录。"


# --- 构建与校验（E2xxx） ---


class BuildError(DocToolError):
    code = "E2001"
    user_message = "Word 文档构建失败。"
    suggested_action = "请查看日志中的阶段和错误详情。"


class ValidationError(DocToolError):
    code = "E2002"
    user_message = "文档校验未通过。"
    suggested_action = "请根据校验报告修正对应章节或资源后重试。"


class NumberingGapError(ValidationError):
    code = "E2003"
    user_message = "章节编号不连续。"
    suggested_action = "请按提示的期望编号修正文件名。"


class RoundtripCheckError(DocToolError):
    code = "E2004"
    user_message = "往返差异门禁未通过。"
    suggested_action = "重建 Word 与源 Word 存在关键内容差异，导入已中止且未留下半成品项目；请检查源文档或重建规则后重试。"


# --- Word 刷新（E3xxx） ---


class WordNotAvailableError(DocToolError):
    code = "E3001"
    user_message = "未检测到可用的 Microsoft Word。"
    suggested_action = "正式合并需要本机安装 Microsoft Word；如需诊断可使用诊断构建。"


class WordRefreshTimeoutError(DocToolError):
    code = "E3002"
    user_message = "Word 字段刷新超时。"
    suggested_action = "请适当增大刷新超时或检查文档体积。"


class WordSaveFailedError(DocToolError):
    code = "E3003"
    user_message = "Word 保存失败。"
    suggested_action = "请关闭其他 Word 进程后重试；上次有效输出已保留。"


# --- 项目模型与锁（E4xxx） ---


class ProjectLockBusyError(DocToolError):
    code = "E4001"
    user_message = "项目正被另一个任务占用。"
    suggested_action = "请等待当前任务完成或查看锁诊断后清理陈旧锁。"


class IncompatibleSchemaError(DocToolError):
    code = "E4002"
    user_message = "项目模式版本与当前应用不兼容。"
    suggested_action = "请安装兼容的新版本应用，或恢复迁移前清单备份。"


class ProjectManifestError(DocToolError):
    code = "E4003"
    user_message = "项目清单读取或写入失败。"
    suggested_action = "请检查 project.yml 是否完整，或从备份恢复。"


# --- 文件系统与资源（E5xxx） ---


class PathEscapeError(DocToolError):
    code = "E5001"
    user_message = "资源路径越出项目根目录。"
    suggested_action = "请检查 Markdown 中的资源引用路径。"


class ResourceNotFoundError(DocToolError):
    code = "E5002"
    user_message = "引用的资源文件不存在。"
    suggested_action = "请确认图片或复杂表格资源已放入对应目录。"


class CancelledError(DocToolError):
    code = "E5003"
    user_message = "任务已被取消。"
    suggested_action = "可在安全阶段后重新启动任务。"
