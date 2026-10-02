# -*- coding: utf-8 -*-
"""写作辅助接入 V3.1 共享命令与项目概览（V3.3 31-E 5.3）。

把本地搜索、确定性建议、差异采纳/撤销与增强状态注册进
:mod:`doc_tool.application.command_registry`，使菜单、命令面板与 CLI 共享同一个
handler 与同一份可用性判断；并提供集中提示模型（覆盖范围 / 陈旧来源 /
增强未执行），避免把“模型没调用”包装成已增强。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from doc_tool.application.command_registry import (
    CONTEXT_IDLE,
    CONTEXT_PROJECT,
    CONTEXT_WRITABLE,
    CommandContext,
    CommandRegistry,
    CommandSpec,
)

CMD_ASSIST_SEARCH = "assist.search"
CMD_ASSIST_SUGGEST = "assist.suggest"
CMD_ASSIST_ADOPT = "assist.adopt"
CMD_ASSIST_UNDO = "assist.undo"
CMD_ASSIST_PROVIDER = "assist.provider"
CMD_ASSIST_OVERVIEW = "assist.overview"

#: 增强未执行时的集中提示（模型不是基础验收前置）。
ENHANCE_NOT_RUN = "增强未执行：未启用模型或未主动点击增强"


def _assistant(project_root, **kwargs):
    from doc_tool.application.assist.service import build_assistant

    return build_assistant(str(project_root), **kwargs)


def _to_dict(value: Any) -> Any:
    method = getattr(value, "to_dict", None)
    if callable(method):
        try:
            return method()
        except Exception:  # noqa: BLE001 - 序列化失败时退回字符串
            return str(value)
    if isinstance(value, (list, tuple)):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_dict(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class AssistOverview:
    """写作辅助概览（集中提示覆盖/陈旧/增强未执行）。"""

    projectRoot: str = ""
    scope: List[Dict[str, Any]] = field(default_factory=list)
    staleSources: int = 0
    suggestionCoverage: List[str] = field(default_factory=list)
    enhanceAvailable: bool = False
    enhanceReason: str = ""
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        lines.append("资料范围：{0} 个来源".format(len(self.scope)))
        if self.staleSources:
            lines.append("· {0} 个来源可能已陈旧，可刷新后再引用".format(self.staleSources))
        else:
            lines.append("· 当前没有标记为陈旧的来源")
        if self.enhanceAvailable:
            lines.append("· 可选增强：已配置，需主动点击才调用")
        else:
            lines.append("· " + (self.enhanceReason or ENHANCE_NOT_RUN))
        for note in self.notes[:5]:
            lines.append("说明：{0}".format(note))
        for item in self.warnings[:5]:
            lines.append("提醒：{0}".format(item))
        return lines

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": 1,
            "projectRoot": self.projectRoot,
            "scope": list(self.scope),
            "staleSources": self.staleSources,
            "suggestionCoverage": list(self.suggestionCoverage),
            "enhanceAvailable": self.enhanceAvailable,
            "enhanceReason": self.enhanceReason,
            "notes": list(self.notes),
            "warnings": list(self.warnings),
        }


def build_assist_overview(project_root, *, buffers: Optional[Dict[str, str]] = None) -> AssistOverview:
    """汇总写作辅助的覆盖范围、陈旧来源与增强状态（失败只记录，不抛）。"""
    root = Path(project_root)
    overview = AssistOverview(projectRoot=str(root))
    try:
        assistant = _assistant(root)
    except Exception as exc:  # noqa: BLE001 - 无项目/坏配置时给出明确原因
        overview.warnings.append("写作辅助不可用：{0}".format(exc))
        overview.enhanceReason = "增强未执行：写作辅助不可用"
        return overview
    if buffers:
        try:
            assistant.set_buffers(dict(buffers))
        except Exception as exc:  # noqa: BLE001
            overview.warnings.append("缓冲内容未纳入搜索：{0}".format(exc))
    try:
        overview.scope = [_to_dict(item) for item in assistant.scope_summary()]
    except Exception as exc:  # noqa: BLE001
        overview.warnings.append("资料范围读取失败：{0}".format(exc))
    try:
        outcome = assistant.search_evidence("")
        hits = list(getattr(outcome, "hits", []) or [])
        overview.staleSources = sum(
            1 for hit in hits if bool(getattr(hit, "stale", False) or getattr(hit, "sourceStale", False))
        )
        overview.notes.extend(str(item) for item in (getattr(outcome, "notes", []) or [])[:3])
    except Exception as exc:  # noqa: BLE001
        overview.warnings.append("资料检索未完成：{0}".format(exc))
    try:
        suggestions = assistant.suggest()
        overview.suggestionCoverage = [
            str(item) for item in (getattr(suggestions, "coverage_notes", []) or [])[:5]
        ]
    except Exception as exc:  # noqa: BLE001
        overview.warnings.append("建议未生成：{0}".format(exc))
    try:
        status = assistant.provider_status() or {}
        overview.enhanceAvailable = bool(status.get("enabled") and status.get("provider"))
        if not overview.enhanceAvailable:
            overview.enhanceReason = (
                "增强未执行：provider 未启用"
                if not status.get("enabled") else "增强未执行：provider 未配置完整"
            )
    except Exception as exc:  # noqa: BLE001
        overview.enhanceReason = ENHANCE_NOT_RUN
        overview.warnings.append("增强状态未知：{0}".format(exc))
    return overview


def register_assist_commands(
    registry: CommandRegistry,
    project_root,
    *,
    buffers: Optional[Dict[str, str]] = None,
) -> CommandRegistry:
    """注册写作辅助命令（与 CLI 同源；菜单/面板共用同一 handler）。"""
    root = Path(project_root)

    def _with_assistant():
        assistant = _assistant(root)
        if buffers:
            try:
                assistant.set_buffers(dict(buffers))
            except Exception:  # noqa: BLE001 - 缓冲不可用时仍用磁盘内容
                pass
        return assistant

    def _search(context: CommandContext, payload: Dict[str, Any]):
        assistant = _with_assistant()
        query = str(payload.get("query") or "")
        outcome = assistant.search_evidence(
            query,
            terms=tuple(payload.get("terms") or ()),
            limit=int(payload.get("limit") or 50),
        )
        hits = [_to_dict(item) for item in list(getattr(outcome, "hits", []) or [])[:50]]
        return {
            "query": query,
            "hits": hits,
            "scope": [_to_dict(item) for item in assistant.scope_summary()],
            "notes": [str(item) for item in (getattr(outcome, "notes", []) or [])[:5]],
            "stale": sum(1 for hit in hits if hit.get("stale")),
        }

    def _suggest(context: CommandContext, payload: Dict[str, Any]):
        assistant = _with_assistant()
        suggestions = assistant.suggest(kinds=payload.get("kinds") or None)
        return _to_dict(suggestions)

    def _adopt(context: CommandContext, payload: Dict[str, Any]):
        assistant = _with_assistant()
        selected = [str(item) for item in (payload.get("ids") or [])]
        if not selected:
            raise ValueError("请先选择要采纳的建议")
        outcome = assistant.adopt(selected, texts=dict(payload.get("texts") or {}) or None)
        return _to_dict(outcome)

    def _undo(context: CommandContext, payload: Dict[str, Any]):
        assistant = _with_assistant()
        outcome = payload.get("outcome")
        if outcome is None:
            raise ValueError("没有可撤销的采纳记录（撤销只在同一次采纳后可用）")
        done, restored, detail = assistant.undo(outcome)
        return {"undone": bool(done), "restored": dict(restored or {}), "detail": str(detail)}

    def _provider(context: CommandContext, payload: Dict[str, Any]):
        assistant = _with_assistant()
        return _to_dict(assistant.provider_status())

    def _overview(context: CommandContext, payload: Dict[str, Any]):
        return build_assist_overview(root, buffers=buffers).to_dict()

    specs = [
        CommandSpec(
            commandId=CMD_ASSIST_SEARCH, title="本地资料搜索", handler=_search,
            aliases=["assist-search", "local-search"], category="写作辅助", shortcut="Ctrl+Shift+F",
            description="在显式加入的项目/模块范围内检索，返回出处/版本/定位",
            contexts=[CONTEXT_PROJECT],
        ),
        CommandSpec(
            commandId=CMD_ASSIST_SUGGEST, title="生成写作建议", handler=_suggest,
            aliases=["assist-suggest"], category="写作辅助",
            description="用现有规则/术语/引用/复核事实生成确定性建议（无模型）",
            contexts=[CONTEXT_PROJECT],
        ),
        CommandSpec(
            commandId=CMD_ASSIST_ADOPT, title="采纳建议（可一次撤销）", handler=_adopt,
            aliases=["assist-adopt"], category="写作辅助",
            description="把选中的建议写入缓冲；现有保存路径不变",
            contexts=[CONTEXT_PROJECT, CONTEXT_WRITABLE, CONTEXT_IDLE],
        ),
        CommandSpec(
            commandId=CMD_ASSIST_UNDO, title="撤销本次采纳", handler=_undo,
            aliases=["assist-undo"], category="写作辅助",
            description="一次撤销本次采纳并恢复缓冲",
            contexts=[CONTEXT_PROJECT, CONTEXT_WRITABLE, CONTEXT_IDLE],
        ),
        CommandSpec(
            commandId=CMD_ASSIST_PROVIDER, title="增强（模型）状态", handler=_provider,
            aliases=["assist-provider"], category="写作辅助",
            description="查看可选增强是否可用（不含凭据；未启用时明确未执行）",
            contexts=[CONTEXT_PROJECT],
        ),
        CommandSpec(
            commandId=CMD_ASSIST_OVERVIEW, title="写作辅助概览", handler=_overview,
            aliases=["assist-overview"], category="写作辅助",
            description="集中提示资料范围、陈旧来源与增强未执行",
            contexts=[CONTEXT_PROJECT],
        ),
    ]
    for spec in specs:
        registry.register(spec)
    return registry


__all__ = [
    "CMD_ASSIST_SEARCH", "CMD_ASSIST_SUGGEST", "CMD_ASSIST_ADOPT",
    "CMD_ASSIST_UNDO", "CMD_ASSIST_PROVIDER", "CMD_ASSIST_OVERVIEW",
    "ENHANCE_NOT_RUN", "AssistOverview", "build_assist_overview", "register_assist_commands",
]