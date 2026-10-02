# -*- coding: utf-8 -*-
"""CORE-E 5.3：预览/检查/出稿共用同一份有效快照。

预览与检查都在**快照工作目录**上执行，因此看到的内容、范围与出稿完全一致：
- 预览：既有离线 HTML 渲染器（同一份 Markdown 与资源）；
- 检查：既有 :class:`ContentLinter`（纯服务，不需要 Word）；
- 出稿：Word/HTML/PDF 同一 ``captureId``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from doc_tool.application.effective_snapshot import EffectiveSnapshot


@dataclass
class SnapshotViews:
    """一次快照上的预览与检查结果。"""

    captureId: str = ""
    workDir: str = ""
    previewIndex: str = ""
    previewStatus: str = ""
    previewWarnings: List[Dict[str, object]] = field(default_factory=list)
    lintIssues: List[Dict[str, object]] = field(default_factory=list)
    lintCount: int = 0
    warnings: List[str] = field(default_factory=list)
    ok: bool = False

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        if self.previewIndex:
            lines.append("预览已更新（与本轮出稿同一份内容）")
        for item in self.previewWarnings[:3]:
            lines.append("预览提醒：{0}".format(item.get("message", "")))
        if self.lintCount:
            lines.append("检查发现 {0} 处待处理项".format(self.lintCount))
        for item in self.warnings:
            lines.append("提醒：{0}".format(item))
        return lines or ["预览与检查已基于本轮快照完成"]


def build_snapshot_views(
    snapshot: EffectiveSnapshot,
    output_dir,
    *,
    cancel_token=None,
    run_lint: bool = True,
) -> SnapshotViews:
    """在快照工作目录上生成预览并运行一致性检查（不触碰源项目）。"""
    work = Path(snapshot.workDir)
    views = SnapshotViews(captureId=snapshot.captureId, workDir=str(work))
    content_root = work / "content"
    assets_root = work / "assets"
    if not content_root.is_dir():
        views.warnings.append("快照工作目录缺少 content，无法预览")
        return views

    try:
        from doc_tool.application.export.readonly_html import export_readonly_html

        result = export_readonly_html(
            content_root, assets_root, Path(output_dir) / "preview", "",
            omitted_unsaved=tuple(snapshot.unsavedChapters), cancel_token=cancel_token,
            document_assets=True,
        )
        index = Path(result.directory) / "index.html"
        views.previewIndex = str(index)
        views.previewStatus = result.status
        views.previewWarnings = [
            item if isinstance(item, dict) else {"message": str(item)}
            for item in list(result.warnings)[:10]
        ]
    except Exception as exc:  # noqa: BLE001 - 预览失败不影响其它视图
        views.warnings.append("预览生成失败：{0}".format(exc))

    if run_lint:
        try:
            from doc_tool.application.content.index import ContentIndexService
            from doc_tool.application.content.lint import ContentLinter

            service = ContentIndexService(content_root)
            index = service.build(cancel_token=cancel_token)
            linter = ContentLinter(index)
            issues = linter.check_all([])
            views.lintCount = len(issues)
            views.lintIssues = [
                {
                    "relPath": getattr(item, "rel_path", ""),
                    "line": getattr(item, "line", 0),
                    "message": getattr(item, "message", ""),
                    "severity": getattr(item, "severity", ""),
                    "rule": getattr(item, "rule_id", ""),
                }
                for item in list(issues)[:50]
            ]
        except Exception as exc:  # noqa: BLE001 - 检查失败不影响出稿
            views.warnings.append("一致性检查未完成：{0}".format(exc))

    views.ok = bool(views.previewIndex)
    return views


__all__ = ["SnapshotViews", "build_snapshot_views"]
