# -*- coding: utf-8 -*-
"""协作流程串联与结果页模型（V3.1 31-E 5.1/5.2）。

一次调用把“历史查证 → 待办分配 → 交接导出 → 选择应用”串起来，并给出结果页模型：
**已处理 / 待处理 / 产物 / 提醒**。默认尽力完成：个别章节冲突、无 Git、缺模块都
只记录并继续；只有“没有任何可用产物且没有任何可继续动作”才算整批阻断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.handoff import (
    apply_handoff_plan,
    export_handoff_package,
    plan_handoff_apply,
)
from doc_tool.application.content.team_entry import build_team_report, _chapter_list, _services, _to_dict


@dataclass
class TeamStep:
    """流程一步的执行事实。"""

    name: str
    status: str = "done"          #: done / skipped / failed / partial
    detail: str = ""
    artifacts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "artifacts": list(self.artifacts)}


@dataclass
class TeamResultPage:
    """结果页模型：已处理 / 待处理 / 产物，以及是否整批阻断。"""

    projectRoot: str = ""
    processed: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    steps: List[TeamStep] = field(default_factory=list)
    gitAvailable: bool = False
    moduleSources: List[str] = field(default_factory=list)
    variantScope: List[str] = field(default_factory=list)
    nextActions: List[str] = field(default_factory=list)
    blocked: bool = False

    @property
    def hasUsableOutcome(self) -> bool:
        return bool(self.artifacts) or bool(self.processed)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        lines.append("已处理 {0} 项，待处理 {1} 项，产物 {2} 个".format(
            len(self.processed), len(self.pending), len(self.artifacts),
        ))
        if not self.gitAvailable:
            lines.append("· 无 Git：使用本地历史，结果不受影响")
        for item in self.processed[:5]:
            lines.append("· 已处理：{0}".format(item))
        for item in self.pending[:5]:
            lines.append("· 待处理：{0}".format(item))
        for item in self.skipped[:5]:
            lines.append("· 已跳过：{0}".format(item))
        for item in self.artifacts[:5]:
            lines.append("· 产物：{0}".format(item))
        for item in self.warnings[:5]:
            lines.append("提醒：{0}".format(item))
        for item in self.nextActions[:3]:
            lines.append("下一步：{0}".format(item))
        if self.blocked:
            lines.append("本次没有可用结果，且没有可继续的动作")
        return lines

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": 1,
            "projectRoot": self.projectRoot,
            "processed": list(self.processed),
            "pending": list(self.pending),
            "artifacts": list(self.artifacts),
            "conflicts": list(self.conflicts),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "steps": [item.to_dict() for item in self.steps],
            "gitAvailable": self.gitAvailable,
            "moduleSources": list(self.moduleSources),
            "variantScope": list(self.variantScope),
            "nextActions": list(self.nextActions),
            "blocked": self.blocked,
        }


def run_team_flow(
    project_root,
    *,
    chapters: Sequence[str] = (),
    handoff_dir=None,
    package=None,
    apply_selected: Optional[Sequence[str]] = None,
    assignee: str = "",
    assign_targets: Sequence[str] = (),
    baseline_texts: Optional[Dict[str, str]] = None,
    texts: Optional[Dict[str, str]] = None,
    created_by: str = "",
    package_name: str = "",
) -> TeamResultPage:
    """串联一次协作流程；每步失败只记录并继续，不整批阻断。"""
    root = Path(project_root)
    page = TeamResultPage(projectRoot=str(root))
    try:
        services = _services(root)
    except Exception as exc:  # noqa: BLE001 - 清单不可读才是真正的阻断
        page.warnings.append("项目清单不可读：{0}".format(exc))
        page.blocked = True
        return page

    selected = list(chapters or []) or _chapter_list(services["content_root"])

    # 1. 历史查证（无 Git 走本地历史，不算失败）
    try:
        report = build_team_report(root, chapter=selected[0] if selected else "")
        page.gitAvailable = report.gitAvailable
        page.steps.append(TeamStep(
            "chapter-history", "done",
            "Git 记录可用" if report.gitAvailable else "无 Git：已使用本地历史",
        ))
        if not report.gitAvailable:
            page.warnings.append("项目没有 Git 记录：历史来自本地恢复点")
    except Exception as exc:  # noqa: BLE001
        page.steps.append(TeamStep("chapter-history", "failed", str(exc)))
        page.warnings.append("历史查证未完成：{0}".format(exc))

    # 2. 待办分配（未指定目标时只读展示，不算失败）
    try:
        from doc_tool.application.content.assignments import AssignmentStore, build_todo_board

        store = AssignmentStore(services["paths"].state_dir)
        board = build_todo_board(assignments=store, team=services["team"])
        counts = board.counts() if callable(getattr(board, "counts", None)) else {}
        page.processed.append("待办清点：待处理 {0} 项".format(counts.get("pending", 0)))
        if assign_targets:
            for target in assign_targets:
                store.assign(str(target), assignee, note="团队流程分配")
                page.processed.append("已分配：{0} → {1}".format(target, assignee or "未分配"))
        page.steps.append(TeamStep("assignments", "done", "待办 {0} 项".format(counts.get("pending", 0))))
    except Exception as exc:  # noqa: BLE001
        page.steps.append(TeamStep("assignments", "failed", str(exc)))
        page.warnings.append("待办/分配未完成：{0}".format(exc))

    # 3. 交接导出
    package_path = package
    if package_path is None:
        output_dir = Path(handoff_dir or (root / "output"))
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            if not selected:
                raise ValueError("项目还没有可交接的章节")
            baseline = _baseline_map(services, selected, baseline_texts)
            package_obj = export_handoff_package(
                root, output_dir,
                chapters=selected,
                content_root=services["content_root"],
                asset_roots=(services["paths"].assets_root,),
                project_id=getattr(services["manifest"], "projectId", ""),
                project_name=services["manifest"].documentName,
                document_version=services["manifest"].documentVersion,
                baseline=baseline or None,
                texts=dict(texts or {}),
                baseline_id="project-baseline" if baseline else "",
                created_by=created_by or "项目作者",
                **({"package_name": package_name} if package_name else {}),
            )
            package_path = getattr(package_obj, "package_path", None)
            if package_path is None:
                candidates = sorted(
                    output_dir.glob("*.zip"),
                    key=lambda item: item.stat().st_mtime, reverse=True,
                )
                package_path = candidates[0] if candidates else None
            if package_path is None:
                raise ValueError("交接包未生成")
            if not baseline:
                page.warnings.append(
                    "没有双方共同基准：交接包已标为“无基准”，接收方需人工确认后再应用"
                )
            page.artifacts.append(str(package_path))
            page.processed.append("交接包已导出：{0}".format(Path(package_path).name))
            page.steps.append(TeamStep("handoff-export", "done", "交接 {0} 章".format(len(selected)),
                                       [str(package_path)]))
        except Exception as exc:  # noqa: BLE001
            page.steps.append(TeamStep("handoff-export", "failed", str(exc)))
            page.warnings.append("交接导出未完成：{0}".format(exc))
    else:
        page.steps.append(TeamStep("handoff-export", "skipped", "使用已有交接包", [str(package_path)]))
        page.artifacts.append(str(package_path))

    # 4. 选择应用（冲突章节跳过，其余继续）
    if package_path is not None:
        try:
            plan = plan_handoff_apply(
                package_path, root,
                content_root=services["content_root"],
                project_id=getattr(services["manifest"], "projectId", ""),
                selected=apply_selected,
            )
            plan_data = _to_dict(plan)
            baseline_known = bool(
                plan_data.get("baselineKnown", getattr(plan, "baseline_known", True))
            )
            if not baseline_known:
                page.warnings.append("缺少双方共同基准：需人工确认后再应用（不宣称无冲突）")
            applicable = [str(item) for item in (getattr(plan, "applicable", []) or [])]
            page.pending.extend(
                "{0}（待应用）".format(item) for item in applicable
            )
            result = apply_handoff_plan(
                plan, project_root=root,
                content_root=services["content_root"],
                asset_roots=(services["paths"].assets_root,),
            )
            applied = [str(item) for item in (getattr(result, "applied", []) or [])]
            skipped = [str(item) for item in (getattr(result, "skipped", []) or [])]
            conflicts = [str(item) for item in (getattr(result, "conflicts", []) or [])]
            page.processed.extend("已应用：{0}".format(item) for item in applied)
            page.skipped.extend(skipped)
            page.conflicts.extend(conflicts)
            page.warnings.extend(str(item) for item in (getattr(result, "warnings", []) or [])[:3])
            if conflicts:
                page.warnings.append(
                    "{0} 个章节有冲突：保留本地内容并跳过，其余已选章节继续".format(len(conflicts))
                )
            if not getattr(result, "success", True):
                page.warnings.append(
                    str(getattr(result, "message", "")) or "部分章节未应用（本地内容已保留）"
                )
            status = "partial" if (applied and (skipped or conflicts)) else (
                "done" if applied else ("partial" if conflicts else "done")
            )
            page.steps.append(TeamStep("handoff-apply", status,
                                       "应用 {0} 项，跳过 {1} 项".format(len(applied), len(skipped))))
        except Exception as exc:  # noqa: BLE001
            page.steps.append(TeamStep("handoff-apply", "failed", str(exc)))
            page.warnings.append("交接应用未完成（可稍后重试）：{0}".format(exc))

    # 5. 模块来源 / 变体范围标记（V3.0 能力存在时补充，否则明确未启用）
    page.moduleSources, page.variantScope = _module_and_variant_marks(services, selected)

    if not page.hasUsableOutcome:
        page.blocked = True
        page.nextActions.append("检查项目章节与输出目录后重试")
    else:
        page.nextActions.append("核对已应用章节后继续编辑或复核")
    if page.skipped:
        page.nextActions.append("冲突章节保留本地内容，处理后可再次应用")
    return page


def _baseline_map(
    services: Dict[str, Any],
    chapters: Sequence[str],
    baseline_texts: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """交接基准：优先用调用方给出的共同版本文本；否则尝试本地历史最早恢复点。"""
    from doc_tool.application.content.handoff import sha256_text

    if baseline_texts:
        return {rel: sha256_text(str(text)) for rel, text in baseline_texts.items() if rel in set(chapters)}
    baseline: Dict[str, str] = {}
    history = services.get("history")
    if history is None:
        return baseline
    for rel in chapters:
        try:
            commits = history.local_commits(rel)
        except Exception:  # noqa: BLE001 - 无本地恢复点时按无基准处理
            continue
        if not commits:
            continue
        oldest = commits[-1]
        try:
            text = history.read_local_version(rel, getattr(oldest, "version_id", ""))
        except Exception:  # noqa: BLE001
            text = None
        if isinstance(text, str):
            baseline[rel] = sha256_text(text)
    return baseline


def _module_and_variant_marks(services: Dict[str, Any], chapters: Sequence[str]) -> Tuple[List[str], List[str]]:
    """读取 V3.0 模块/变体信息（能力缺失时不报错，标为未启用）。"""
    modules: List[str] = []
    variants: List[str] = []
    try:
        from doc_tool.application.content.module_refs import list_module_references  # type: ignore

        modules = [str(item) for item in list_module_references(services["content_root"])]
    except Exception:  # noqa: BLE001 - V3.0 能力未就绪时明确留空
        modules = []
    try:
        from doc_tool.application.content.variants import load_variants  # type: ignore

        data = load_variants(services["root"])
        variants = [str(item) for item in (data or [])]
    except Exception:  # noqa: BLE001
        variants = []
    return modules, variants


__all__ = ["TeamStep", "TeamResultPage", "run_team_flow"]