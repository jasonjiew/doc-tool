# -*- coding: utf-8 -*-
"""V3.3 写作辅助共享契约：来源、索引状态、建议、采纳与 provider 的公共模型。

本模块只放**跨批次共享的最小数据模型与常量**，不含 GUI、不写正文。批次分工：

- 33-A ``search_local.py``：本地资料检索（来源/版本/定位/陈旧/未保存）。
- 33-B ``suggestions.py``：确定性建议与修订摘要候选。
- 33-C ``adoption.py``：差异采纳与一次撤销（只改编辑缓冲）。
- 33-D ``provider.py``：可选摘要/术语增强 provider（默认禁用）。

设计约束（design.md D1～D4）：

- 建议永远不是“需求已满足/测试已通过”证据，``Suggestion.not_evidence`` 固定为 True。
- 采纳只改编辑缓冲，保存仍走既有 ``ContentWriter``；本模块不写正文。
- 凭据只从用户级环境读取，绝不进入项目目录、包或日志。
- 用户级缓存/配置缺失或损坏都可重建，不阻塞编辑与出稿。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

# 复用主流程契约的时间戳与哈希工具，避免另造一套口径。
from doc_tool.application.intake_contract import sha256_text

# --- 来源类型 ---------------------------------------------------------------

SOURCE_KIND_PROJECT = "project"
SOURCE_KIND_MODULE = "module"
SOURCE_KIND_BUFFER = "buffer"
SOURCE_KINDS = (SOURCE_KIND_PROJECT, SOURCE_KIND_MODULE, SOURCE_KIND_BUFFER)

SOURCE_KIND_LABELS = {
    SOURCE_KIND_PROJECT: "项目",
    SOURCE_KIND_MODULE: "模块库",
    SOURCE_KIND_BUFFER: "当前缓冲",
}

#: 未登记来源时的版本占位（不伪称已知版本）。
UNKNOWN_VERSION = "未登记"

# --- 索引/缓存状态 -----------------------------------------------------------

CACHE_FRESH = "fresh"            #: 命中可重建用户缓存，来源未变化
CACHE_MISSING = "missing"        #: 无缓存（首次），已直接读可读文本
CACHE_REBUILT = "rebuilt"        #: 缓存损坏/不可解析，已直接读可读文本
CACHE_REFRESHED = "refreshed"    #: 按需刷新后重建
CACHE_DISABLED = "disabled"      #: 调用方显式禁用缓存

CACHE_STATUS_LABELS = {
    CACHE_FRESH: "索引缓存可用",
    CACHE_MISSING: "首次建立索引（无需先修缓存）",
    CACHE_REBUILT: "索引缓存不可解析，已直接搜索可读文本",
    CACHE_REFRESHED: "已按需刷新索引",
    CACHE_DISABLED: "本次未使用缓存",
}

# --- 匹配原因 ---------------------------------------------------------------

MATCH_REASON_TEXT = "text"
MATCH_REASON_TERM = "term-alias"
MATCH_REASON_REGEX = "regex"

MATCH_REASON_LABELS = {
    MATCH_REASON_TEXT: "文本命中",
    MATCH_REASON_TERM: "术语/别名命中",
    MATCH_REASON_REGEX: "正则命中",
}

# --- 引用/复制模式（插入正文复用普通文字，不产生任意文件 INCLUDE） ----------

INSERT_MODE_CITATION = "citation"
INSERT_MODE_COPY_TEXT = "copy-text"
INSERT_MODES = (INSERT_MODE_CITATION, INSERT_MODE_COPY_TEXT)

# --- 建议种类 ---------------------------------------------------------------

KIND_FILL = "fill-required"          #: 规范已声明但未填写的要点 / 遗漏清单
KIND_TERM = "term-wording"           #: 术语库确定的替代措辞
KIND_REFERENCE = "reference-issue"   #: 失效引用/待处理引用
KIND_REVIEW = "review-pending"       #: 待复核关系（只提示，不改状态）
KIND_REVISION_SUMMARY = "revision-summary"  #: 修订摘要候选
KIND_MODULE_UPDATE = "module-update"        #: 固定引用的模块有新版本/版本缺失（只提示，不改装配）

KINDS = (
    KIND_FILL, KIND_TERM, KIND_REFERENCE, KIND_REVIEW, KIND_REVISION_SUMMARY, KIND_MODULE_UPDATE,
)

KIND_LABELS = {
    KIND_FILL: "填写提示",
    KIND_TERM: "术语建议",
    KIND_REFERENCE: "引用提示",
    KIND_REVIEW: "复核提示",
    KIND_REVISION_SUMMARY: "修订摘要候选",
    KIND_MODULE_UPDATE: "模块更新提示",
}

# --- 建议状态 ---------------------------------------------------------------

STATUS_PROPOSED = "proposed"
STATUS_STALE = "stale"          #: 目标已变化，需重算
STATUS_CONFLICT = "conflict"    #: 目标冲突，保留用户内容并跳过
STATUS_ACCEPTED = "accepted"
STATUS_IGNORED = "ignored"
STATUS_UNAVAILABLE = "unavailable"

STATUS_LABELS = {
    STATUS_PROPOSED: "待选择",
    STATUS_STALE: "待刷新",
    STATUS_CONFLICT: "冲突待处理",
    STATUS_ACCEPTED: "已采纳",
    STATUS_IGNORED: "已忽略",
    STATUS_UNAVAILABLE: "不可用",
}

# --- 建议来源（origin）与覆盖度（coverage） ---------------------------------

ORIGIN_RULE = "rule"
ORIGIN_LOCAL = "local"
ORIGIN_PROVIDER = "provider"

ORIGIN_LABELS = {
    ORIGIN_RULE: "规则/规范",
    ORIGIN_LOCAL: "本地数据",
    ORIGIN_PROVIDER: "可选模型",
}

COVERAGE_FULL = "full"                  #: 依据与目标范围都确定
COVERAGE_PARTIAL = "partial"            #: 目标位置为建议值，需作者确认
COVERAGE_INSUFFICIENT = "insufficient"  #: 范围不足，只给填写提示

COVERAGE_LABELS = {
    COVERAGE_FULL: "依据完整",
    COVERAGE_PARTIAL: "部分依据",
    COVERAGE_INSUFFICIENT: "范围不足（仅提示）",
}

# --- 建议应用方式 -----------------------------------------------------------

APPLY_REPLACE = "replace"   #: 在目标行替换 before -> after
APPLY_INSERT = "insert"     #: 在目标文件末尾插入 after
APPLY_NONE = "none"         #: 只提示/只填候选框，不改正文
# --- provider 状态 -----------------------------------------------------------

PURPOSE_REVISION_SUMMARY = "revision-summary"
PURPOSE_TERM = "term-wording"
PURPOSES = (PURPOSE_REVISION_SUMMARY, PURPOSE_TERM)

PROVIDER_DISABLED = "disabled"
PROVIDER_LOCAL_COMMAND = "local-command"
PROVIDER_HTTP = "http"
PROVIDER_KINDS = (PROVIDER_DISABLED, PROVIDER_LOCAL_COMMAND, PROVIDER_HTTP)

ENHANCE_OK = "ok"
ENHANCE_DISABLED = "disabled"
ENHANCE_NO_CREDENTIAL = "no-credential"
ENHANCE_TIMEOUT = "timeout"
ENHANCE_NETWORK = "network"
ENHANCE_BAD_RESPONSE = "bad-response"
ENHANCE_CANCELLED = "cancelled"
ENHANCE_COMMAND_MISSING = "command-missing"
ENHANCE_ERROR = "error"
ENHANCE_UNAVAILABLE = "unavailable"

ENHANCE_STATUS_LABELS = {
    ENHANCE_OK: "增强完成",
    ENHANCE_DISABLED: "未启用模型（使用本地候选）",
    ENHANCE_NO_CREDENTIAL: "无可用凭据，已回退本地候选",
    ENHANCE_TIMEOUT: "模型请求超时，已回退本地候选",
    ENHANCE_NETWORK: "模型请求失败（断网/端点不可达），已回退本地候选",
    ENHANCE_BAD_RESPONSE: "模型响应结构非法，已忽略并回退本地候选",
    ENHANCE_CANCELLED: "增强已取消，已回退本地候选",
    ENHANCE_COMMAND_MISSING: "本地模型命令不可用，已回退本地候选",
    ENHANCE_ERROR: "增强失败，已回退本地候选",
    ENHANCE_UNAVAILABLE: "本次增强未执行",
}

#: 视为“没有增强结果”的状态：这些情况下展示的都是已有本地候选。
FALLBACK_STATUSES = (
    ENHANCE_DISABLED, ENHANCE_NO_CREDENTIAL, ENHANCE_TIMEOUT, ENHANCE_NETWORK,
    ENHANCE_BAD_RESPONSE, ENHANCE_CANCELLED, ENHANCE_COMMAND_MISSING,
    ENHANCE_ERROR, ENHANCE_UNAVAILABLE,
)

#: 默认请求总长度上限（字符）：超过即截断并明示实际范围。
DEFAULT_MAX_REQUEST_CHARS = 8000

#: 模型响应中的可执行指令特征：命中即不作为可执行动作，只记录说明。
COMMAND_HINTS = (
    "执行命令", "运行命令", "执行以下", "shell", "powershell", "cmd.exe",
    "rm -rf", "del /f", "subprocess", "os.system", "sudo ",
)

# --- 路径：用户级缓存/配置（绝不放在项目目录） ------------------------------


def user_cache_dir() -> Path:
    """用户级可重建缓存目录（索引缓存、建议记录）。"""
    override = os.environ.get("DOC_TOOL_ASSIST_CACHE")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "doc-tool" / "assist"
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "doc-tool" / "assist"
    return Path.home() / ".cache" / "doc-tool" / "assist"


def user_config_dir() -> Path:
    """用户级配置目录（provider 设置；凭据本身仍只来自用户环境变量）。"""
    override = os.environ.get("DOC_TOOL_ASSIST_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "doc-tool" / "assist"
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "doc-tool" / "assist"
    return Path.home() / ".config" / "doc-tool" / "assist"


# --- 通用工具 ---------------------------------------------------------------


def hash_text(text: str) -> str:
    """文本哈希（复用主流程契约的 sha256 口径）。"""
    return sha256_text(text or "")


def short_hash(value: str, length: int = 8) -> str:
    return (value or "")[:length]


def truncate_context(text: str, max_chars: int = DEFAULT_MAX_REQUEST_CHARS) -> Tuple[str, bool, int]:
    """按上限截断请求上下文：返回 (截断后文本, 是否截断, 原始字符数)。

    截断只影响本次请求内容，不修改任何正文/缓冲；调用方负责把实际范围与
    截断状态展示给用户。
    """
    value = text or ""
    limit = max(1, int(max_chars or DEFAULT_MAX_REQUEST_CHARS))
    if len(value) <= limit:
        return value, False, len(value)
    return value[:limit], True, len(value)


def has_command_instruction(text: str) -> bool:
    """响应文本是否含“可执行指令”特征（命中只记录，绝不执行）。"""
    lowered = (text or "").lower()
    return any(hint.lower() in lowered for hint in COMMAND_HINTS)


def text_lines(text: str) -> List[str]:
    """与内容索引一致的行切分口径。"""
    return (text or "").splitlines()


def display_path(rel_path: str) -> str:
    return (rel_path or "").replace("\\", "/")


class AssistError(Exception):
    """写作辅助的可预期失败（调用方据此回退/提示，不阻断编辑）。"""

    code = "E3300"

    def __init__(self, message: str, *, code: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.detail = detail


class SourceUnavailableError(AssistError):
    """来源目录/文件不可读（跳过该来源，其余来源继续）。"""

    code = "E3301"