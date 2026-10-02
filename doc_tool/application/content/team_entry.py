# -*- coding: utf-8 -*-
"""团队协作入口与可解析报告（V3.1 31-D 4.2 / 31-E 5.3）。

把章节历史、负责人待办与交接包注册进 :mod:`doc_tool.application.command_registry`，
让菜单、命令面板与 CLI 使用**同一个 handler**（本版不重写 ``main_window``）。同时
提供纯服务、可 JSON 序列化的 :class:`TeamReport`，供结果页与后续 V3.2 队列直接
调用，不重复重建意见生命周期。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from doc_tool.application.command_registry import (
    CONTEXT_GIT,
    CONTEXT_IDLE,
    CONTEXT_PROJECT,
    CONTEXT_SELECTION,
    CONTEXT_WRITABLE,
    CommandContext,
    CommandRegistry,
    CommandSpec,
)
from doc_tool.application.content.assignments import (
    AssignmentStore,
    build_todo_board,
    load_team_config,
)
from doc_tool.application.content.chapter_history import ChapterHistoryService
from doc_tool.application.content.handoff import (
    apply_handoff_plan,
    export_handoff_package,
    plan_handoff_apply,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths

#: 稳定命令 ID（不随别名变化）。
CMD_CHAPTER_HISTORY = "team.chapter-history"
CMD_MY_TODOS = "team.my-todos"
CMD_ASSIGN = "team.assign"
CMD_HANDOFF_EXPORT = "team.handoff-export"
CMD_HANDOFF_APPLY = "team.handoff-apply"
CMD_TEAM_REPORT = "team.report"
CMD_TEAM_FLOW = "team.flow"


def _to_dict(value: Any) -> Dict[str, Any]:
    """尽量转成可 JSON 序列化的字典（模型自带 ``to_dict``）。"""
    method = getattr(value, "to_dict", None)
    if callable(method):
        try:
            data = method()
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001 - 模型拒绝序列化时退回字符串
            pass
    if isinstance(value, dict):
        return dict(value)
    return {"value": str(value)}


def _to_list(values: Sequence[Any]) -> List[Dict[str, Any]]:
    return [_to_dict(item) for item in list(values or [])]


def _value(obj: Any, name: str, default: Any = None) -> Any:
    """读取属性；同时兼容“属性”与“无参方法”两种暴露方式。"""
    member = getattr(obj, name, default)
    if callable(member):
        try:
            return member()
        except TypeError:
            return member
    return member


@dataclass
class TeamReport:
    """协作侧的服务级报告（JSON 可序列化，后续队列可直接消费）。"""

    projectRoot: str = ""
    documentType: str = ""
    gitAvailable: bool = False
    history: Dict[str, Any] = field(default_factory=dict)
    assignments: Dict[str, Any] = field(default_factory=dict)
    handoff: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    nextActions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": 1,
            "projectRoot": self.projectRoot,
            "documentType": self.documentType,
            "gitAvailable": self.gitAvailable,
            "history": dict(self.history),
            "assignments": dict(self.assignments),
            "handoff": dict(self.handoff),
            "warnings": list(self.warnings),
            "nextActions": list(self.nextActions),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def summary_lines(self) -> List[str]:
        lines = ["章节历史：{0}".format("Git 记录可用" if self.gitAvailable else "无 Git，使用本地历史")]
        total = self.history.get("total")
        if total is not None:
            lines.append("· {0} 条历史版本（{1}）".format(total, self.history.get("source") or "本地"))
        counts = self.assignments.get("counts") or {}
        if counts:
            lines.append("· 待办 {0} 项（我的 {1} / 未分配 {2}）".format(
                counts.get("pending", 0), counts.get("mine", 0), counts.get("unassigned", 0),
            ))
        if self.handoff.get("chapters") is not None:
            lines.append("· 可交接章节 {0} 个".format(self.handoff.get("chapters")))
        lines.extend("提醒：{0}".format(item) for item in self.warnings)
        lines.extend("下一步：{0}".format(item) for item in self.nextActions)
        return lines


def _services(project_root) -> Dict[str, Any]:
    root = Path(project_root)
    manifest = ProjectManifest.load(root)
    paths = ProjectPaths(root)
    content_root = paths.resolve(manifest.relative_content_root())
    return {
        "root": root,
        "manifest": manifest,
        "paths": paths,
        "content_root": content_root,
        "history": ChapterHistoryService(root, content_root, paths.state_dir),
        "team": load_team_config(root),
    }


def _chapter_list(content_root: Path) -> List[str]:
    from doc_tool.application.effective_snapshot import discover_chapters

    return [rel for rel, _path in discover_chapters(content_root)]


def build_team_report(project_root, *, chapter: str = "") -> TeamReport:
    """汇总历史/待办/交接可用性；任一子服务失败只记提醒，不影响其它部分。"""
    root = Path(project_root)
    report = TeamReport(projectRoot=str(root))
    try:
        services = _services(root)
    except Exception as exc:  # noqa: BLE001 - 清单不可读时给出明确原因
        report.warnings.append("项目清单不可读：{0}".format(exc))
        return report

    report.documentType = services["manifest"].documentType
    history = services["history"]
    try:
        report.gitAvailable = history.git_root() is not None
    except Exception as exc:  # noqa: BLE001
        report.warnings.append("Git 探测失败：{0}".format(exc))

    chapters = _chapter_list(services["content_root"])
    target = chapter or (chapters[0] if chapters else "")
    if target:
        try:
            collected = history.collect(target)
            data = _to_dict(collected)
            report.history = {
                "chapter": target,
                "total": data.get("total", 0),
                "source": data.get("source", ""),
                "truncated": data.get("truncated", False),
                "note": data.get("note", ""),
            }
            report.gitAvailable = report.gitAvailable or str(data.get("source")) == "git"
        except Exception as exc:  # noqa: BLE001 - 历史查询不阻断其它部分
            report.warnings.append("章节历史未完成：{0}".format(exc))
    else:
        report.history = {"chapter": "", "total": 0, "note": "项目还没有章节"}

    try:
        store = AssignmentStore(services["paths"].state_dir)
        board = build_todo_board(assignments=store, team=services["team"])
        report.assignments = {
            "counts": dict(_value(board, "counts", {}) or {}),
            "myName": _value(board, "my_name", ""),
            "members": len(getattr(services["team"], "members", []) or []),
        }
        report.warnings.extend(list(_value(board, "warnings", []) or [])[:3])
        if not getattr(services["team"], "members", None):
            report.warnings.append("未配置团队成员：新增意见默认归“未分配”")
    except Exception as exc:  # noqa: BLE001
        report.warnings.append("负责人/待办不可用：{0}".format(exc))

    try:
        report.handoff = {
            "chapters": len(chapters),
            "projectId": getattr(services["manifest"], "projectId", ""),
        }
    except Exception as exc:  # noqa: BLE001
        report.warnings.append("交接信息不可用：{0}".format(exc))

    if not report.gitAvailable:
        report.nextActions.append("无 Git：核对本地历史后仍可导出交接包")
    counts = report.assignments.get("counts") or {}
    if counts.get("mine"):
        report.nextActions.append("先处理我的 {0} 项待办再交接".format(counts["mine"]))
    else:
        report.nextActions.append("可直接导出交接包给外部作者")
    return report


def register_team_commands(registry: CommandRegistry, project_root) -> CommandRegistry:
    """把本版历史/待办/交接/报告注册进注册表（双入口共用同一 handler）。"""
    root = Path(project_root)

    def _history(context: CommandContext, payload: Dict[str, Any]):
        services = _services(root)
        chapters = _chapter_list(services["content_root"])
        target = str(payload.get("chapter") or context.currentChapter or (chapters[0] if chapters else ""))
        if not target:
            raise ValueError("项目还没有可查证的章节")
        buffer_text = str(payload.get("buffer_text") or "")
        collected = services["history"].collect(target)
        data = _to_dict(collected)
        # 与未保存缓冲比较（V3.1 spec）：取最新可得版本，用同一服务比较编辑器内容
        comparison = None
        if buffer_text:
            # 取最新一条章节提交作为比较对象（历史记录按新→旧返回）
            commits = _to_list(data.get("commits") or [])
            version_id = ""
            for item in commits:
                if isinstance(item, dict):
                    version_id = str(
                        item.get("versionId") or item.get("version_id") or item.get("commit") or ""
                    )
                    if version_id:
                        break
            if version_id:
                try:
                    result = services["history"].compare_current(
                        target, version_id, buffer_text=buffer_text,
                    )
                    comparison = _to_dict(result)
                except Exception as exc:  # noqa: BLE001 - 比较失败如实说明，不影响历史展示
                    comparison = {"error": str(exc) or type(exc).__name__}
        return {
            "chapter": target,
            "source": data.get("source", ""),
            "commits": _to_list(data.get("commits") or [])[:10],
            "total": int(data.get("total", 0) or 0),
            "bufferCompared": bool(comparison),
            "bufferComparison": comparison or {},
            "total": data.get("total", 0),
            "truncated": data.get("truncated", False),
            "versions": _to_list(data.get("versions") or []),
            "gitAvailable": services["history"].git_root() is not None,
        }

    def _todos(context: CommandContext, payload: Dict[str, Any]):
        services = _services(root)
        store = AssignmentStore(services["paths"].state_dir)
        board = build_todo_board(assignments=store, team=services["team"])
        return {
            "myName": _value(board, "my_name", ""),
            "counts": dict(_value(board, "counts", {}) or {}),
            "myTodos": _to_list(_value(board, "mine", []) or []),
            "unassigned": _to_list(_value(board, "unassigned", []) or []),
            "warnings": list(_value(board, "warnings", []) or [])[:5],
        }

    def _assign(context: CommandContext, payload: Dict[str, Any]):
        services = _services(root)
        store = AssignmentStore(services["paths"].state_dir)
        target = str(payload.get("target") or "")
        assignee = str(payload.get("assignee") or "")
        if not target:
            raise ValueError("请先选择要分配的意见或影响对象")
        record = store.assign(target, assignee, note=str(payload.get("note") or ""))
        return _to_dict(record)

    def _handoff_export(context: CommandContext, payload: Dict[str, Any]):
        services = _services(root)
        chapters = list(payload.get("chapters") or []) or _chapter_list(services["content_root"])
        if not chapters:
            raise ValueError("项目还没有可交接的章节")
        # 既有服务把 destination 当**目录**，在目录内生成交接包 ZIP；
        # 这里接受目录（outputDir/output），并在导出后回报真实产物路径。
        output_dir = Path(payload.get("outputDir") or payload.get("output") or (root / "output"))
        if output_dir.suffix.lower() == ".zip":
            output_dir = output_dir.parent
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 - 目录不可写时给出明确原因
            raise ValueError("交接包输出目录不可写：{0}".format(exc))
        package = export_handoff_package(root, output_dir, chapters=chapters)
        produced = None
        try:
            candidates = sorted(
                output_dir.glob("*.zip"),
                key=lambda item: item.stat().st_mtime, reverse=True,
            )
            produced = candidates[0] if candidates else None
        except OSError:
            produced = None
        data = _to_dict(package)
        return {
            "path": str(produced) if produced is not None else str(output_dir),
            "outputDir": str(output_dir),
            "chapters": list(chapters),
            "packageId": data.get("packageId", ""),
        }

    def _handoff_apply(context: CommandContext, payload: Dict[str, Any]):
        services = _services(root)
        package = payload.get("package")
        if not package:
            raise ValueError("请先选择要应用的交接包")
        plan = plan_handoff_apply(package, root)
        plan_data = _to_dict(plan)
        if not payload.get("apply"):
            return {"applied": False, "plan": plan_data}
        result = apply_handoff_plan(plan)
        return {"applied": True, "plan": plan_data, "result": _to_dict(result)}

    def _report(context: CommandContext, payload: Dict[str, Any]):
        chapter = str(payload.get("chapter") or context.currentChapter or "")
        return build_team_report(root, chapter=chapter).to_dict()

    def _flow(context: CommandContext, payload: Dict[str, Any]):
        """串联历史查证 → 待办分配 → 交接导出/应用，返回结果页（V3.1 5.1）。"""
        from doc_tool.application.content.team_flow import run_team_flow

        def _items(key: str) -> List[str]:
            value = payload.get(key)
            if isinstance(value, str):
                return [item for item in (part.strip() for part in value.split(",")) if item]
            if isinstance(value, (list, tuple)):
                return [str(item) for item in value if str(item).strip()]
            return []

        page = run_team_flow(
            root,
            chapters=_items("chapters"),
            handoff_dir=payload.get("handoffDir") or None,
            package=payload.get("package") or None,
            apply_selected=_items("apply") or None,
            assignee=str(payload.get("assignee") or ""),
            assign_targets=_items("assignTargets"),
        )
        data = page.to_dict()
        data["summary"] = list(page.summary_lines())
        data["blocked"] = bool(page.blocked)
        return data

    specs = [
        CommandSpec(
            commandId=CMD_CHAPTER_HISTORY, title="查看本章节历史", handler=_history,
            aliases=["chapter-history", "history"], category="协作", shortcut="Ctrl+Shift+H",
            description="查看可获取的 Git/重命名记录与本地历史，并与当前缓冲比较",
            contexts=[CONTEXT_PROJECT],
            fallbacks={CONTEXT_GIT: "无 Git 记录：改用本地历史，仍可查证"},
        ),
        CommandSpec(
            commandId=CMD_MY_TODOS, title="我的待办", handler=_todos,
            aliases=["my-todos", "todos"], category="协作", shortcut="Ctrl+Shift+T",
            description="按负责人筛选现有评审意见/影响对象（不新建另一套是否通过）",
            contexts=[CONTEXT_PROJECT],
        ),
        CommandSpec(
            commandId=CMD_ASSIGN, title="分配负责人", handler=_assign,
            aliases=["assign"], category="协作",
            description="给选中的意见或影响对象分配处理人",
            contexts=[CONTEXT_PROJECT, CONTEXT_WRITABLE, CONTEXT_IDLE, CONTEXT_SELECTION],
            fallbacks={CONTEXT_SELECTION: "未选中意见：可在待办列表中指定目标"},
        ),
        CommandSpec(
            commandId=CMD_HANDOFF_EXPORT, title="导出内容交接包", handler=_handoff_export,
            aliases=["handoff-export"], category="协作",
            description="打包所选正文/基准/资源，交给外部作者",
            contexts=[CONTEXT_PROJECT, CONTEXT_IDLE],
        ),
        CommandSpec(
            commandId=CMD_HANDOFF_APPLY, title="应用内容交接包", handler=_handoff_apply,
            aliases=["handoff-apply"], category="协作",
            description="查看差异后选择应用；冲突章节跳过，其余继续",
            contexts=[CONTEXT_PROJECT, CONTEXT_WRITABLE, CONTEXT_IDLE],
        ),
        CommandSpec(
            commandId=CMD_TEAM_FLOW,
            title="团队交接流程（历史→待办→交接→应用）", handler=_flow,
            aliases=["team-flow", "flow"], category="协作",
            description="一次串起历史查证/待办清点/交接导出或应用，并给出结果页与下一步",
            contexts=[CONTEXT_PROJECT, CONTEXT_IDLE],
            fallbacks={CONTEXT_WRITABLE: "只读项目：可查证与导出，应用交接包需要可写项目"},
        ),
        CommandSpec(
            commandId=CMD_TEAM_REPORT, title="协作状态报告", handler=_report,
            aliases=["team-report"], category="协作",
            description="一次拿到历史/待办/交接可用性与下一步",
            contexts=[CONTEXT_PROJECT],
        ),
    ]
    for spec in specs:
        registry.register(spec)
    return registry


__all__ = [
    "CMD_CHAPTER_HISTORY", "CMD_MY_TODOS", "CMD_ASSIGN",
    "CMD_HANDOFF_EXPORT", "CMD_HANDOFF_APPLY", "CMD_TEAM_REPORT",
    "TeamReport", "build_team_report", "register_team_commands",
]