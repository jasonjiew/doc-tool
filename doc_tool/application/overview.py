# -*- coding: utf-8 -*-
"""项目概览聚合（V2.8 28-E / 5.4）。

只读地把已有服务的结果聚合成一份「当前状态 + 下一步动作」：

- 当前版本、schema 与规范包引用；
- 检查报告是否已过期（相对内容与配置的最新修改时间）；
- 改动章节（章节顺序 + 未列入提醒）；
- 阻断问题（复用构建前检查与发布终审的发现）；
- 待评审数量（复用 ``ReviewStore``）；
- 最新交付记录与下一步动作建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union


@dataclass
class OverviewSection:
    """概览中的一个板块。"""

    key: str
    label: str
    value: str = ""
    detail: str = ""
    status: str = "ok"  # ok | warning | blocked
    items: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "detail": self.detail,
            "status": self.status,
            "items": list(self.items),
        }


@dataclass
class ProjectOverview:
    """项目概览结果（只读）。"""

    project_root: str = ""
    document_name: str = ""
    document_version: str = ""
    schema_version: int = 0
    standard_pack: str = ""
    sections: List[OverviewSection] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)

    @property
    def blocking_count(self) -> int:
        for section in self.sections:
            if section.key == "blocking":
                return len(section.items)
        return 0

    @property
    def pending_review_count(self) -> int:
        for section in self.sections:
            if section.key == "review":
                try:
                    return int(section.value)
                except (TypeError, ValueError):
                    return 0
        return 0

    @property
    def check_stale(self) -> bool:
        for section in self.sections:
            if section.key == "check":
                return section.status == "warning" and section.value == "已过期"
        return False

    def to_dict(self) -> dict:
        return {
            "projectRoot": self.project_root,
            "documentName": self.document_name,
            "documentVersion": self.document_version,
            "schemaVersion": self.schema_version,
            "standardPack": self.standard_pack,
            "blockingCount": self.blocking_count,
            "pendingReviewCount": self.pending_review_count,
            "checkStale": self.check_stale,
            "sections": [section.to_dict() for section in self.sections],
            "nextActions": list(self.next_actions),
        }

    def markdown_text(self) -> str:
        lines = [
            "## 项目概览",
            "",
            "- 文档：{0}（版本 {1}）".format(self.document_name, self.document_version),
            "- 模式版本：v{0}".format(self.schema_version),
        ]
        if self.standard_pack:
            lines.append("- 规范包：{0}".format(self.standard_pack))
        lines.append("")
        lines.append("| 项 | 结论 | 说明 |")
        lines.append("|------|------|------|")
        for section in self.sections:
            lines.append(
                "| {0} | {1} | {2} |".format(section.label, section.value or section.status, section.detail)
            )
        if self.next_actions:
            lines.append("")
            lines.append("**下一步：**")
            lines.extend("- {0}".format(action) for action in self.next_actions)
        return "\n".join(lines)


def build_overview(project_root: Union[str, Path]) -> ProjectOverview:
    """聚合项目概览（后台可调，不修改项目）。

    任一子服务失败都只降级该板块为“不可用”，不会让概览整体报错。
    """
    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root)
    manifest = ProjectManifest.load(root)
    paths = manifest.resolve_paths(root)
    overview = ProjectOverview(
        project_root=str(root),
        document_name=manifest.documentName,
        document_version=manifest.documentVersion,
        schema_version=manifest.schemaVersion,
    )
    pack = manifest.standardPack or {}
    if pack.get("id"):
        overview.standard_pack = "{0} {1}".format(pack.get("id"), pack.get("version", ""))

    overview.sections.append(_version_section(manifest))
    overview.sections.append(_check_section(manifest, paths, root))
    overview.sections.append(_content_section(manifest, paths, root))
    overview.sections.append(_blocking_section(manifest, paths))
    overview.sections.append(_review_section(paths))
    overview.sections.append(_delivery_section(paths))
    overview.next_actions = _next_actions(overview)
    return overview


def _version_section(manifest) -> OverviewSection:
    kind = manifest.documentKind or manifest.documentType
    detail = "类别：{0}".format(kind or "未声明")
    if manifest.standardPack:
        detail += "；规范包：{0}".format(manifest.standardPack.get("id", ""))
    return OverviewSection(
        key="version",
        label="当前版本",
        value=manifest.documentVersion or "未设置",
        detail=detail,
        status="ok",
    )


def _check_section(manifest, paths, root: Path) -> OverviewSection:
    """检查报告是否过期（新于报告的内容/配置修改即为过期）。"""
    report = _latest_check_report(paths.logs_dir)
    if report is None:
        return OverviewSection(
            key="check",
            label="质量检查",
            value="未检查",
            detail="尚未生成检查报告。",
            status="warning",
        )
    report_time = report.stat().st_mtime
    newest = _newest_source_mtime(root, manifest, paths)
    if newest and newest > report_time:
        return OverviewSection(
            key="check",
            label="质量检查",
            value="已过期",
            detail="内容或配置在检查之后已修改，请重新检查。",
            status="warning",
        )
    return OverviewSection(
        key="check",
        label="质量检查",
        value="有效",
        detail="报告：{0}".format(report.name),
        status="ok",
    )


def _content_section(manifest, paths, root: Path) -> OverviewSection:
    from doc_tool.application.chapter_order import resolve_chapter_order
    from doc_tool.application.pipeline import collect_chapter_markdown_paths

    files = collect_chapter_markdown_paths(paths.content_root)
    relative = []
    for path in files:
        try:
            relative.append(Path(path).relative_to(paths.content_root).as_posix())
        except ValueError:
            relative.append(Path(path).name)
    order = resolve_chapter_order(relative, manifest.chapters)
    detail_parts = ["章节 {0} 个".format(len(order.ordered))]
    if order.missing:
        detail_parts.append("缺失 {0}".format(len(order.missing)))
    if order.unlisted:
        detail_parts.append("未列入 {0}".format(len(order.unlisted)))
    return OverviewSection(
        key="content",
        label="内容改动",
        value="{0} 个章节".format(len(order.ordered)),
        detail="；".join(detail_parts),
        status="warning" if (order.missing or order.unlisted) else "ok",
        items=list(order.warnings),
    )


def _blocking_section(manifest, paths) -> OverviewSection:
    """阻断问题：复用构建前检查与发布终审的发现。"""
    items: List[str] = []
    try:
        from doc_tool.application.check import _collect_lint_issues, build_report

        issues = _collect_lint_issues(manifest, paths)
        items = [
            "{0}:{1} {2}".format(issue.rel_path or "—", issue.line_no or 0, issue.message)
            for issue in issues
            if issue.severity == "error"
        ]
        if not items:
            items = [
                "{0}:{1} {2}".format(issue.rel_path or "—", issue.line_no or 0, issue.message)
                for issue in issues
            ][:10]
    except Exception as exc:  # noqa: BLE001 - 概览不因子服务失败而报错
        return OverviewSection(
            key="blocking",
            label="阻断问题",
            value="不可用",
            detail="检查服务不可用：{0}".format(exc),
            status="warning",
        )
    return OverviewSection(
        key="blocking",
        label="阻断问题",
        value=str(len(items)),
        detail="无阻断项。" if not items else "请先处理以下项。",
        status="blocked" if items else "ok",
        items=items,
    )


def _review_section(paths) -> OverviewSection:
    try:
        from doc_tool.application.review.review_store import ReviewStore

        stats = ReviewStore(paths.state_dir).stats()
        pending = int(stats.get("unconfirmed", 0))
        detail = "共 {0} 条，已确认 {1}，遗留 {2}".format(
            stats.get("total", 0), stats.get("confirmed", 0), stats.get("open_issues", 0)
        )
        return OverviewSection(
            key="review",
            label="待评审",
            value=str(pending),
            detail=detail + "；默认带提醒继续出稿。",
            status="warning" if pending else "ok",
        )
    except Exception as exc:  # noqa: BLE001
        return OverviewSection(
            key="review",
            label="待评审",
            value="不可用",
            detail=str(exc),
            status="warning",
        )


def _delivery_section(paths) -> OverviewSection:
    output_dir = paths.output_dir
    latest: Optional[Path] = None
    if output_dir.is_dir():
        candidates = [
            item for item in output_dir.glob("*.docx") if item.is_file() and not item.name.startswith(".")
        ]
        if candidates:
            latest = max(candidates, key=lambda item: item.stat().st_mtime)
    if latest is None:
        return OverviewSection(
            key="delivery",
            label="最新交付",
            value="无",
            detail="尚未产生交付产物。",
            status="warning",
        )
    return OverviewSection(
        key="delivery",
        label="最新交付",
        value=latest.name,
        detail="最近修改：{0}".format(_format_time(latest.stat().st_mtime)),
        status="ok",
    )


def _next_actions(overview: ProjectOverview) -> List[str]:
    actions: List[str] = []
    if overview.blocking_count:
        actions.append("处理 {0} 项阻断问题后重新检查。".format(overview.blocking_count))
    if overview.check_stale:
        actions.append("内容或配置已变化，请重新运行质量检查。")
    if overview.pending_review_count:
        actions.append("处理 {0} 条待评审意见（默认不阻断出稿）。".format(overview.pending_review_count))
    for section in overview.sections:
        if section.key == "content" and section.status == "warning":
            actions.append("核对章节顺序：缺失或未列入的章节请确认。")
            break
    if not actions:
        actions.append("无阻断项，可直接出稿。")
    return actions


def _latest_check_report(logs_dir: Path) -> Optional[Path]:
    if not logs_dir.is_dir():
        return None
    candidates = [item for item in logs_dir.glob("*-validation.md") if item.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _newest_source_mtime(root: Path, manifest, paths) -> float:
    newest = 0.0
    for target in (
        paths.content_root,
        root / "quality",
        root / ".state" / "quality_rules.json",
        # V2.8：配置与规则变更后旧报告必须过期（含旧位置术语与关系文件）。
        root / ".state" / "terms.json",
        root / "relations.yml",
    ):
        if target.is_dir():
            for item in target.rglob("*"):
                if item.is_file():
                    newest = max(newest, item.stat().st_mtime)
        elif target.is_file():
            newest = max(newest, target.stat().st_mtime)
    template = paths.template_docx
    if template.is_file():
        newest = max(newest, template.stat().st_mtime)
    return newest


def _format_time(value: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def check_report_is_stale(
    project_root,
    *,
    report_path=None,
    manifest=None,
    paths=None,
) -> bool:
    """判定质量检查报告是否已过期（供 GUI/概览复用）。

    过期语义：**内容、配置或底模在报告之后又被修改**。
    无报告时返回 True（“尚未检查”也不能当作有效结论）。
    """
    from pathlib import Path

    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root)
    if manifest is None:
        manifest = ProjectManifest.load(root)
    if paths is None:
        paths = manifest.resolve_paths(root)
    report = Path(report_path) if report_path is not None else _latest_check_report(paths.logs_dir)
    if report is None or not report.is_file():
        return True
    newest = _newest_source_mtime(root, manifest, paths)
    return bool(newest and newest > report.stat().st_mtime)
