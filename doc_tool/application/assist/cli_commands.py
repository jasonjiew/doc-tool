# -*- coding: utf-8 -*-
"""V3.3 33-E 写作辅助 CLI 命令实现（结构化结果，打印由 cli.py 负责）。

命令与门面同源，未引入第二套逻辑：

- ``assist-search``：显式范围（项目 + 模块库）本地检索，含来源/版本/定位/陈旧。
- ``assist-suggest``：确定性建议（无模型）。
- ``assist-adopt``：采纳预览（只显示 before/after 与差异，CLI 不写正文）。
- ``assist-provider``：可选 provider 配置状态（只显示环境变量名，绝不显示凭据）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from doc_tool.application.assist.provider import ProviderConfigStore
from doc_tool.application.assist.search_local import EvidenceSource, LocalEvidenceSearch
from doc_tool.application.assist.service import AuthoringAssistant

COMMANDS = ("assist-search", "assist-suggest", "assist-adopt", "assist-provider")


def assist_search(
    projects: Sequence[str] = (),
    modules: Sequence[str] = (),
    *,
    query: str = "",
    terms: Sequence[str] = (),
    limit: int = 200,
    cache_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """在显式加入的项目/模块范围内检索（无项目时给出可读失败说明）。"""
    sources: List[EvidenceSource] = []
    for project in projects or ():
        if project:
            sources.append(EvidenceSource.from_project(project))
    for module in modules or ():
        if module:
            sources.append(EvidenceSource.from_module(module))
    if not sources:
        return {
            "success": False,
            "error": "未加入任何资料范围：请用 --project / --module 显式指定。",
            "hits": [],
        }
    service = LocalEvidenceSearch(
        sources, cache_dir=Path(cache_dir) if cache_dir else None
    )
    outcome = service.search(query, terms=terms, limit=limit)
    data = outcome.to_dict()
    data["success"] = outcome.ok
    data["command"] = "assist-search"
    return data


def assist_suggest(
    project: str,
    *,
    kinds: Sequence[str] = (),
    cache_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """生成确定性建议（不调用任何模型）。"""
    assistant = AuthoringAssistant.from_project(
        project, cache_dir=Path(cache_dir) if cache_dir else None
    )
    result = assistant.suggest(kinds=kinds or None)
    data = result.to_dict()
    data["success"] = True
    data["command"] = "assist-suggest"
    data["project"] = str(Path(project).resolve())
    data["providerCalls"] = assistant.gateway.provider_call_count
    return data


def assist_adopt_preview(
    project: str,
    *,
    suggestion_ids: Sequence[str] = (),
    kinds: Sequence[str] = (),
    cache_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """采纳预览：返回 before/after 与统一差异；CLI 不写正文。"""
    assistant = AuthoringAssistant.from_project(
        project, cache_dir=Path(cache_dir) if cache_dir else None
    )
    result = assistant.suggest(kinds=kinds or None)
    suggestions = result.suggestions
    selected = [item for item in suggestion_ids or () if item]
    if not selected:
        selected = [item.suggestion_id for item in suggestions if item.applicable]
    preview = assistant.adoption_session.preview_diff(suggestions, selected)
    return {
        "success": True,
        "command": "assist-adopt",
        "project": str(Path(project).resolve()),
        "selected": selected,
        "preview": preview,
        "note": "CLI 仅预览，不写正文；请在编辑器中采纳并沿用既有保存路径。",
        "summary": result.summary_lines(),
        "suggestions": [item.to_dict() for item in suggestions],
    }


def assist_provider(config_path: Optional[str] = None) -> Dict[str, Any]:
    """provider 配置状态（只显示凭据环境变量名）。"""
    store = ProviderConfigStore(config_path) if config_path else ProviderConfigStore()
    described = store.describe()
    described["success"] = True
    described["command"] = "assist-provider"
    return described


def run(command: str, args) -> Dict[str, Any]:
    """按 CLI 参数执行对应命令，返回结构化结果。"""
    if command == "assist-search":
        return assist_search(
            getattr(args, "project", None) or (),
            getattr(args, "module", None) or (),
            query=getattr(args, "query", "") or "",
            terms=getattr(args, "term", None) or (),
            limit=int(getattr(args, "limit", 200) or 200),
            cache_dir=getattr(args, "cache_dir", "") or None,
        )
    if command == "assist-suggest":
        return assist_suggest(
            args.project,
            kinds=getattr(args, "kind", None) or (),
            cache_dir=getattr(args, "cache_dir", "") or None,
        )
    if command == "assist-adopt":
        return assist_adopt_preview(
            args.project,
            suggestion_ids=getattr(args, "suggestion", None) or (),
            kinds=getattr(args, "kind", None) or (),
            cache_dir=getattr(args, "cache_dir", "") or None,
        )
    if command == "assist-provider":
        return assist_provider(getattr(args, "config", "") or None)
    return {"success": False, "error": "未知辅助命令：{0}".format(command)}


def render(payload: Dict[str, Any], *, output: str = "human") -> str:
    """渲染为 JSON 或人读文本。"""
    if output == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if not payload.get("success", True):
        return "未执行：{0}".format(payload.get("error", "未知原因"))
    lines: List[str] = []
    if payload.get("command") == "assist-search":
        lines.append("范围：{0}".format(
            "；".join(
                "{0}（{1}）".format(item.get("label"), item.get("kindLabel"))
                for item in payload.get("scope") or []
            ) or "（空）"
        ))
        for note in payload.get("summary") or []:
            lines.append(note)
        for hit in payload.get("hits") or []:
            flags = []
            if hit.get("unsaved"):
                flags.append("未保存")
            if hit.get("stale"):
                flags.append("陈旧")
            lines.append("- {0}｜{1}｜{2}{3}".format(
                hit.get("location"), hit.get("text", "").strip()[:120],
                hit.get("matchLabel", ""),
                "（{0}）".format("／".join(flags)) if flags else "",
            ))
    elif payload.get("command") == "assist-suggest":
        for note in payload.get("summary") or []:
            lines.append(note)
        for item in payload.get("suggestions") or []:
            lines.append("- [{0}] {1}｜{2}｜{3}{4}".format(
                item.get("kindLabel"), item.get("title"), item.get("statusLabel"),
                item.get("coverageLabel"),
                "｜目标 {0}:{1}".format(item.get("targetRelPath"), item.get("startLine"))
                if item.get("targetRelPath") else "",
            ))
        lines.append(payload.get("factsNote", ""))
    elif payload.get("command") == "assist-adopt":
        lines.append(payload.get("note", ""))
        lines.append(payload.get("preview", "") or "（无可预览差异）")
        for note in payload.get("summary") or []:
            lines.append(note)
    elif payload.get("command") == "assist-provider":
        config = payload.get("config") or {}
        lines.append("配置文件：{0}".format(payload.get("path", "")))
        lines.append("状态：{0}".format("已启用" if config.get("isEnabled") else "未启用（默认）"))
        lines.append("目标：{0}".format(config.get("target", "")))
        lines.append("长度上限：{0} 字符；凭据环境变量：{1}（{2}）".format(
            config.get("maxChars"),
            config.get("credentialEnv") or "未配置",
            "已设置" if config.get("credentialPresent") else "未设置",
        ))
        for warning in payload.get("warnings") or []:
            lines.append("提醒：{0}".format(warning))
    else:
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    return "\n".join(line for line in lines if line is not None)