# -*- coding: utf-8 -*-
"""渐进命令注册（V3.1 31-D）。

一个**轻量、无 Qt 依赖**的命令注册表，让同一动作在菜单、命令面板与 CLI 之间
共享同一个 handler 与同一份可用性判断：

- ``commandId`` 稳定并与别名解耦（别名可改，ID 不变）；
- 每条命令声明所需 ``contexts``：``project``/``writable``/``idle`` 等，缺条件时
  给出**面向用户的不可用原因与下一步动作**，不静默隐藏；
- 可降级条件（如无 Git）用 ``fallbacks`` 说明“仍可用但走兜底”；
- ``recent`` 只记录命令 ID 与时间，缓存损坏按注册顺序回退；
- 未迁移的旧菜单入口通过 :meth:`CommandRegistry.append_legacy` 保持可达，
  本版不重写 ``main_window``。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from doc_tool.application.content.writer import atomic_write, atomic_write_bytes

#: 最近命令缓存文件名（用户配置目录）。
RECENT_FILE_NAME = "recent-commands.json"
RECENT_SCHEMA_VERSION = 1
#: 最近命令最多保留条数。
RECENT_LIMIT = 20

#: 上下文条件键。
CONTEXT_PROJECT = "project"
CONTEXT_WRITABLE = "writable"
CONTEXT_IDLE = "idle"
CONTEXT_GIT = "git"
CONTEXT_SELECTION = "selection"
CONTEXT_BUFFER = "buffer"


def recent_file(root: Optional[Path] = None) -> Path:
    """最近命令缓存位置（可注入目录以便测试）。"""
    if root is not None:
        return Path(root) / RECENT_FILE_NAME
    try:
        from doc_tool.application.project_service import _config_dir

        return Path(_config_dir()) / RECENT_FILE_NAME
    except Exception:  # noqa: BLE001 - 配置目录不可用时退回用户主目录
        return Path.home() / ".doctool" / RECENT_FILE_NAME


@dataclass
class CommandContext:
    """调用命令时的界面/项目状态（界面与 CLI 各自填自己的事实）。"""

    projectOpen: bool = False
    writable: bool = False
    running: bool = False
    hasGit: bool = False
    hasSelection: bool = False
    hasBuffer: bool = False
    documentType: str = ""
    currentChapter: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    def supports(self, key: str) -> bool:
        mapping = {
            CONTEXT_PROJECT: self.projectOpen,
            CONTEXT_WRITABLE: self.writable,
            CONTEXT_IDLE: not self.running,
            CONTEXT_GIT: self.hasGit,
            CONTEXT_SELECTION: self.hasSelection,
            CONTEXT_BUFFER: self.hasBuffer,
        }
        return bool(mapping.get(key, self.extras.get(key, False)))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data


@dataclass
class CommandSpec:
    """一条命令声明。"""

    commandId: str
    title: str
    handler: Optional[Callable[..., Any]] = None
    aliases: List[str] = field(default_factory=list)
    category: str = "协作"
    shortcut: str = ""
    description: str = ""
    contexts: List[str] = field(default_factory=lambda: [CONTEXT_PROJECT])
    fallbacks: Dict[str, str] = field(default_factory=dict)
    requiresWrite: bool = False
    legacy: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commandId": self.commandId,
            "title": self.title,
            "aliases": list(self.aliases),
            "category": self.category,
            "shortcut": self.shortcut,
            "description": self.description,
            "contexts": list(self.contexts),
            "fallbacks": dict(self.fallbacks),
            "requiresWrite": self.requiresWrite,
            "legacy": self.legacy,
        }


@dataclass
class CommandAvailability:
    """可用性判断结果：不可用时必须给出原因与下一步。"""

    available: bool
    reason: str = ""
    nextAction: str = ""
    fallbackNote: str = ""
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CommandResult:
    """一次调用的结果（异常被包装为可展示结果，不向上抛）。"""

    ok: bool
    commandId: str = ""
    value: Any = None
    message: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "commandId": self.commandId,
            "message": self.message, "reason": self.reason,
            "value": self.value,
        }


_REASON_TEXT = {
    CONTEXT_PROJECT: ("当前没有打开项目", "先打开或新建一个项目"),
    CONTEXT_WRITABLE: ("当前项目为只读", "复制项目到可写位置后再执行"),
    CONTEXT_IDLE: ("已有任务正在运行", "等待当前任务完成或先取消"),
    CONTEXT_GIT: ("项目没有可用的 Git 记录", "将使用本地历史"),
    CONTEXT_SELECTION: ("当前没有选中内容", "先在章节树或编辑器中选择"),
    CONTEXT_BUFFER: ("当前没有未保存的编辑内容", "先修改正文再执行"),
}


class CommandRegistry:
    """命令注册表：注册、可用性判断、调用与最近使用。"""

    def __init__(self, recent_root: Optional[Path] = None) -> None:
        self._commands: Dict[str, CommandSpec] = {}
        self._order: List[str] = []
        self._legacy: List[CommandSpec] = []
        self.recent_path = recent_file(recent_root)
        self.warnings: List[str] = []
        self._recent: List[Dict[str, str]] = self._load_recent()

    # --- 注册 ---

    def register(self, spec: CommandSpec) -> CommandSpec:
        """注册命令；同 ID 覆盖（幂等），别名冲突报错。"""
        if not spec.commandId:
            raise ValueError("commandId 不能为空")
        for other in self._commands.values():
            if other.commandId == spec.commandId:
                continue
            clash = set(other.aliases) & set(spec.aliases)
            if clash:
                raise ValueError(
                    "别名冲突：{0} 已用于 {1}".format("、".join(sorted(clash)), other.commandId)
                )
        if spec.commandId not in self._commands:
            self._order.append(spec.commandId)
        self._commands[spec.commandId] = spec
        return spec

    def append_legacy(self, spec: CommandSpec) -> CommandSpec:
        """登记未迁移的旧入口：保持可达，但不进入新菜单/面板排序。"""
        spec.legacy = True
        self._legacy.append(spec)
        return spec

    def get(self, command_id: str) -> Optional[CommandSpec]:
        return self._commands.get(command_id)

    def resolve(self, name: str) -> Optional[CommandSpec]:
        """按 ID 或别名解析（大小写不敏感）。"""
        text = str(name or "").strip().lower()
        if not text:
            return None
        for spec in self._commands.values():
            if spec.commandId.lower() == text:
                return spec
        for spec in self._commands.values():
            if any(alias.lower() == text for alias in spec.aliases):
                return spec
        return None

    def commands(self) -> List[CommandSpec]:
        return [self._commands[key] for key in self._order]

    def legacy_commands(self) -> List[CommandSpec]:
        return list(self._legacy)

    # --- 可用性 ---

    def availability(self, spec: CommandSpec, context: CommandContext) -> CommandAvailability:
        missing: List[str] = []
        reason = ""
        next_action = ""
        fallback_note = ""
        for key in spec.contexts:
            if context.supports(key):
                continue
            if key == CONTEXT_WRITABLE and spec.requiresWrite:
                missing.append(key)
                reason, next_action = _REASON_TEXT[key]
                continue
            if key in spec.fallbacks:
                fallback_note = spec.fallbacks[key]
                continue
            missing.append(key)
            if not reason:
                reason, next_action = _REASON_TEXT.get(key, ("条件不满足：" + key, "检查当前项目状态"))
        return CommandAvailability(
            available=not missing, reason=reason, nextAction=next_action,
            fallbackNote=fallback_note, missing=missing,
        )

    # --- 调用 ---

    def invoke(
        self,
        name: str,
        context: Optional[CommandContext] = None,
        payload: Optional[Dict[str, Any]] = None,
        *,
        record: bool = True,
    ) -> CommandResult:
        """调用命令：不可用时返回原因，异常被包装（不抛出）。"""
        spec = self.resolve(name)
        if spec is None:
            return CommandResult(False, message="未知命令：{0}".format(name))
        ctx = context or CommandContext()
        availability = self.availability(spec, ctx)
        if not availability.available:
            return CommandResult(
                False, spec.commandId, message=availability.reason, reason=availability.nextAction,
            )
        if spec.handler is None:
            return CommandResult(False, spec.commandId, message="命令未接实现（待接线）")
        try:
            value = _call_handler(spec.handler, ctx, dict(payload or {}))
        except Exception as exc:  # noqa: BLE001 - 命令失败要作为结果返回，不崩界面
            return CommandResult(False, spec.commandId, message=str(exc) or type(exc).__name__)
        if record:
            self.record(spec.commandId)
        return CommandResult(True, spec.commandId, value=value, message=availability.fallbackNote)

    # --- 最近使用 ---

    def record(self, command_id: str) -> None:
        entry = {"commandId": str(command_id), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._recent = [item for item in self._recent if item.get("commandId") != command_id]
        self._recent.insert(0, entry)
        self._recent = self._recent[:RECENT_LIMIT]
        self._save_recent()

    def recent_ids(self, limit: int = 8) -> List[str]:
        return [item["commandId"] for item in self._recent[:limit] if item.get("commandId")]

    def ordered(self, limit: int = 0) -> List[CommandSpec]:
        """最近使用优先、其余按注册顺序（保证“最近使用”不丢其它命令）。"""
        recent = self.recent_ids(limit=RECENT_LIMIT)
        specs = self.commands()
        ranked = sorted(
            specs,
            key=lambda spec: recent.index(spec.commandId) if spec.commandId in recent else len(recent),
        )
        return ranked[:limit] if limit else ranked

    def _load_recent(self) -> List[Dict[str, str]]:
        path = self.recent_path
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schemaVersion") != RECENT_SCHEMA_VERSION:
                raise ValueError("schema 版本不受支持")
            items = data.get("recent")
            if not isinstance(items, list):
                raise ValueError("recent 必须是列表")
            result = []
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("commandId"), str):
                    raise ValueError("recent 条目格式不正确")
                result.append({"commandId": item["commandId"], "at": str(item.get("at") or "")})
            return result[:RECENT_LIMIT]
        except (OSError, ValueError, AttributeError) as exc:
            self.warnings.append("最近命令缓存损坏，已保留原文件并按默认顺序：{0}".format(exc))
            try:
                atomic_write_bytes(
                    path.with_name(path.name + ".damaged-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")),
                    path.read_bytes(),
                )
            except OSError:
                pass
            return []

    def _save_recent(self) -> None:
        try:
            atomic_write(
                self.recent_path,
                json.dumps(
                    {"schemaVersion": RECENT_SCHEMA_VERSION, "recent": self._recent},
                    ensure_ascii=False, indent=2,
                ),
            )
        except OSError as exc:
            self.warnings.append("最近命令写入失败（不影响使用）：{0}".format(exc))

    # --- 双入口同状态 ---

    def menu_items(self, context: CommandContext, *, query: str = "") -> List[Dict[str, Any]]:
        """菜单视图：**只给当前可用的正式入口**（不含旧入口与不可用项），按分类分组。

        与 :meth:`palette_items` 共用同一份命令/handler/可用性来源，但视图不同：
        菜单只放“能点的”，避免把不可用项混进菜单；搜索与旧入口交给命令面板。
        """
        return [
            row for row in self._entries(context, include_unavailable=False, query=query)
            if not row.get("legacy")
        ]

    def palette_items(self, context: CommandContext, *, query: str = "") -> List[Dict[str, Any]]:
        """面板视图：**全部命令**（含旧入口与不可用项，附原因/下一步）并带搜索关键字。

        与 :meth:`menu_items` 同源不同形：面板是菜单的超集，便于键盘用户搜到一切；
        不可用项在面板里显示原因而不是消失。
        """
        rows = self._entries(context, include_unavailable=True, query=query)
        for row in rows:
            row["keywords"] = self._keywords(row)
            row["searchText"] = " ".join(
                [
                    str(row.get("title") or ""),
                    str(row.get("commandId") or ""),
                    " ".join(row.get("aliases") or []),
                    str(row.get("keywords") or ""),
                    str(row.get("category") or ""),
                ]
            ).strip()
            row["paletteOnly"] = bool(row.get("legacy")) or not row.get("available")
        return rows

    def _keywords(self, row: Dict[str, Any]) -> str:
        """面板搜索关键字：命令 ID 片段 + 别名（空格分隔便于匹配）。"""
        parts = [str(row.get("commandId") or "").replace(".", " ")]
        parts.extend(str(item) for item in (row.get("aliases") or []))
        return " ".join(part for part in parts if part)

    def _entries(
        self, context: CommandContext, *, include_unavailable: bool, query: str = ""
    ) -> List[Dict[str, Any]]:
        needle = str(query or "").strip().lower()
        entries: List[Dict[str, Any]] = []
        for spec in self.ordered():
            if needle and needle not in spec.title.lower() and not any(
                needle in alias.lower() for alias in spec.aliases
            ):
                continue
            availability = self.availability(spec, context)
            if not availability.available and not include_unavailable:
                continue
            label = spec.title if availability.available else "{0}（{1}）".format(
                spec.title, availability.reason
            )
            entries.append({
                "commandId": spec.commandId,
                "title": label,
                "category": spec.category,
                "shortcut": spec.shortcut,
                "description": availability.fallbackNote or spec.description or availability.nextAction,
                "available": availability.available,
                "reason": availability.reason,
                "nextAction": availability.nextAction,
                "legacy": bool(spec.legacy),
                "payload": {"commandId": spec.commandId},
            })
        for spec in self._legacy:
            entries.append({
                "commandId": spec.commandId,
                "title": spec.title,
                "category": spec.category,
                "shortcut": spec.shortcut,
                "description": spec.description or "旧入口（未迁移，保持可达）",
                "available": True,
                "reason": "",
                "nextAction": "",
                "legacy": True,
                "payload": {"commandId": spec.commandId, "legacy": True},
            })
        return entries

    def handle_item(self, item: Dict[str, Any], context: Optional[CommandContext] = None,
                    payload: Optional[Dict[str, Any]] = None) -> CommandResult:
        """菜单/面板条目回调的统一入口（避免两处各写一份调用逻辑）。"""
        command_id = str((item or {}).get("commandId") or "")
        return self.invoke(command_id, context, payload)


def _call_handler(handler: Callable[..., Any], context: CommandContext, payload: Dict[str, Any]) -> Any:
    """按 handler 形参数量适配调用（支持 (ctx, payload) / (ctx) / ()）。"""
    try:
        signature = inspect.signature(handler)
        positional = [
            parameter for parameter in signature.parameters.values()
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        ]
        has_varargs = any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
    except (TypeError, ValueError):
        positional, has_varargs = [], True
    if has_varargs or len(positional) >= 2:
        return handler(context, payload)
    if len(positional) == 1:
        return handler(context)
    return handler()


__all__ = [
    "RECENT_FILE_NAME", "RECENT_SCHEMA_VERSION", "RECENT_LIMIT",
    "CONTEXT_PROJECT", "CONTEXT_WRITABLE", "CONTEXT_IDLE", "CONTEXT_GIT",
    "CONTEXT_SELECTION", "CONTEXT_BUFFER",
    "CommandContext", "CommandSpec", "CommandAvailability", "CommandResult",
    "CommandRegistry", "recent_file",
]