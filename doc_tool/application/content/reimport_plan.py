# -*- coding: utf-8 -*-
"""\u91cd\u5bfc\u5165\u8ba1\u5212/\u5e94\u7528\u4e0e Git \u51b2\u7a81\u4e09\u65b9\u5408\u5e76\uff08V2.8 28-H / 8.1\u30018.3\u30018.4\uff09\u3002

- ``plan_reimport``\uff1a**\u7eaf\u53ea\u8bfb**\u5730\u8f93\u51fa\u65b0\u589e/\u4fee\u6539/\u5220\u9664/\u51b2\u7a81\u4e0e\u6e90 hash\uff0c\u4e0d\u6c61\u67d3\u6b63\u5f0f\u7ae0\u8282\uff1b
- ``apply_plan``\uff1a\u53ea\u628a\u201c\u5df2\u9009\u4e14\u975e\u51b2\u7a81\u201d\u7684\u9879\u7ffb\u8bd1\u6210 ``reimport`` \u7684 ``choices``\uff0c\u51b2\u7a81\u4e0e\u672a\u9009\u9879\u4e00\u5f8b\u4fdd\u7559\u672c\u5730\uff1b
- ``resolve_git_conflict``\uff1a\u7528 base/ours/theirs \u4e09\u65b9\u5408\u5e76\uff0c\u786e\u8ba4\u540e\u6821\u9a8c\u5e76\u6807 resolved\uff1b\u4e8c\u8fdb\u5236\u4e0e SVN \u660e\u786e\u652f\u6301\u8fb9\u754c\u3002
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

#: \u4e09\u65b9\u5408\u5e76\u51b2\u7a81\u6807\u8bb0\u3002
MERGE_CONFLICT_MARKER = "<<<<<<<"

#: \u4e0d\u652f\u6301\u6587\u672c\u5408\u5e76\u7684\u4e8c\u8fdb\u5236\u6269\u5c55\u540d\u3002
BINARY_SUFFIXES = (
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".pdf", ".png", ".jpg", ".jpeg",
    ".gif", ".zip", ".7z", ".rar", ".exe", ".dll", ".bin",
)

#: SVN \u5de5\u4f5c\u526f\u672c\u6807\u8bc6\u76ee\u5f55\u3002
SVN_DIR = ".svn"


@dataclass
class PlanItem:
    """\u8ba1\u5212\u4e2d\u7684\u4e00\u9879\u7ae0\u8282\u53d8\u5316\u3002"""

    rel_path: str
    change: str
    conflict: bool = False
    selected: bool = False
    local_hash: str = ""
    source_hash: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "change": self.change,
            "conflict": self.conflict,
            "selected": self.selected,
            "localHash": self.local_hash,
            "sourceHash": self.source_hash,
            "reason": self.reason,
        }


@dataclass
class ReimportPlan:
    """\u91cd\u5bfc\u5165\u8ba1\u5212\uff08\u7eaf\u6570\u636e\uff0c\u53ef\u76f4\u63a5\u7ed9\u754c\u9762\u5c55\u793a\uff09\u3002"""

    source_path: str = ""
    source_hash: str = ""
    baseline_available: bool = False
    items: List[PlanItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        result = {
            "added": 0, "modified": 0, "deleted": 0, "unchanged": 0,
            "conflict": 0, "selected": 0,
        }
        for item in self.items:
            result[item.change] = result.get(item.change, 0) + 1
            if item.conflict:
                result["conflict"] += 1
            if item.selected:
                result["selected"] += 1
        return result

    @property
    def auto_applicable(self) -> List[PlanItem]:
        return [item for item in self.items if item.selected and not item.conflict]

    @property
    def skipped(self) -> List[PlanItem]:
        return [item for item in self.items if item.conflict or not item.selected]

    def choices(self) -> Dict[str, bool]:
        """\u7ffb\u8bd1\u6210 ``ReimportService.reimport`` \u9700\u8981\u7684 ``choices``\u3002"""
        mapping: Dict[str, bool] = {}
        for item in self.items:
            if item.change == "unchanged":
                continue
            mapping[item.rel_path] = bool(item.selected and not item.conflict)
        return mapping

    def to_dict(self) -> dict:
        return {
            "sourcePath": self.source_path,
            "sourceHash": self.source_hash,
            "baselineAvailable": self.baseline_available,
            "counts": self.counts(),
            "choices": self.choices(),
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
        }

    def markdown_text(self) -> str:
        counts = self.counts()
        lines = [
            "## \u91cd\u5bfc\u5165\u5dee\u5f02\u9884\u89c8",
            "",
            "- \u65b0\u589e {added}\uff0c\u4fee\u6539 {modified}\uff0c\u5220\u9664 {deleted}\uff0c"
            "\u672a\u53d8 {unchanged}\uff0c\u51b2\u7a81 {conflict}".format(**counts),
        ]
        if self.warnings:
            lines.append("")
            lines.extend("- \u63d0\u9192\uff1a{0}".format(item) for item in self.warnings)
        if self.items:
            lines.append("")
            lines.append("| \u7ae0\u8282 | \u53d8\u5316 | \u51b2\u7a81 | \u5c06\u5e94\u7528 |")
            lines.append("|------|------|------|--------|")
            for item in self.items:
                lines.append(
                    "| {0} | {1} | {2} | {3} |".format(
                        item.rel_path,
                        item.change,
                        "\u662f" if item.conflict else "\u5426",
                        "\u662f" if (item.selected and not item.conflict) else "\u5426",
                    )
                )
        return "\n".join(lines)


def plan_reimport(
    service,
    changes: Sequence[object],
    *,
    source_path: Union[str, Path] = "",
    baseline_available: Optional[bool] = None,
    selected: Optional[Sequence[str]] = None,
) -> ReimportPlan:
    """\u7e94\u4e00\u4efd\u91cd\u5bfc\u5165\u8ba1\u5212\uff08**\u4e0d\u5199\u5165**\u4efb\u4f55\u6b63\u5f0f\u7ae0\u8282\uff09\u3002

    ``changes`` \u662f ``compare_chapters`` \u7684\u8f93\u51fa\u3002\u4ec5\u201c\u975e\u51b2\u7a81\u4e14\u53d7\u9009\u201d\u7684\u9879\u4f1a\u88ab\u6807\u4e3a\u5c06\u5e94\u7528\uff1b
    ``selected`` \u7f3a\u7701\u65f6\u7528\u6bd4\u5bf9\u7ed3\u679c\u81ea\u5e26\u7684 ``use_new``\u3002
    """
    selected_set = {str(item) for item in (selected or [])}
    plan = ReimportPlan(source_path=str(source_path or ""))
    if plan.source_path and os.path.isfile(plan.source_path):
        plan.source_hash = file_sha256(Path(plan.source_path))
    if baseline_available is not None:
        plan.baseline_available = bool(baseline_available)
    local_hashes = _safe_hashes(service, "local_hashes")
    incoming_hashes = _safe_hashes(service, "incoming_hashes")

    for raw in changes:
        rel_path = str(getattr(raw, "rel_path", "") or "")
        change = str(getattr(raw, "status", "") or "")
        conflict = bool(getattr(raw, "conflict", False))
        default_use_new = bool(getattr(raw, "use_new", True))
        chosen = rel_path in selected_set if selected_set else default_use_new
        plan.items.append(
            PlanItem(
                rel_path=rel_path,
                change=change,
                conflict=conflict,
                selected=bool(chosen and not conflict and change != "unchanged"),
                local_hash=local_hashes.get(rel_path, ""),
                source_hash=incoming_hashes.get(rel_path, ""),
                reason=_reason_for(change, conflict),
            )
        )
    if not plan.baseline_available:
        plan.warnings.append(
            "\u7f3a\u5c11\u57fa\u7ebf\uff1a\u9996\u6b21\u91cd\u5bfc\u5165\u9ed8\u8ba4\u4fdd\u7559\u672c\u5730\u4fee\u6539\uff0c\u51b2\u7a81\u9879\u9700\u4eba\u5de5\u786e\u8ba4\u3002"
        )
    conflicts = [item for item in plan.items if item.conflict]
    if conflicts:
        plan.warnings.append(
            "\u6709 {0} \u9879\u51b2\u7a81\u5df2\u8df3\u8fc7\uff0c\u4e0d\u4f1a\u8986\u76d6\u672c\u5730\u5185\u5bb9\u3002".format(len(conflicts))
        )
    return plan


def apply_plan(service, plan: ReimportPlan, new_source: Union[str, Path]) -> dict:
    """\u628a\u8ba1\u5212\u4ea4\u7ed9 ``ReimportService.reimport``\uff08\u590d\u7528\u73b0\u6709\u4e8b\u52a1\u4e0e\u56de\u6eda\uff09\u3002

    \u8fd4\u56de ``{"applied", "skipped", "rolledBack", "success", "message"}``\u3002
    """
    applicable = plan.auto_applicable
    skipped = [item.rel_path for item in plan.skipped]
    if not applicable:
        return {
            "applied": [],
            "skipped": skipped,
            "rolledBack": False,
            "success": True,
            "message": "\u6ca1\u6709\u53ef\u5e94\u7528\u7684\u9879\uff08\u51b2\u7a81\u6216\u672a\u9009\u4e2d\u5747\u8df3\u8fc7\uff09\u3002",
        }
    try:
        outcome = service.reimport(Path(new_source), choices=plan.choices())
    except Exception as exc:  # noqa: BLE001 - \u5931\u8d25\u5fc5\u987b\u56de\u6eda
        return {
            "applied": [],
            "skipped": skipped,
            "rolledBack": True,
            "success": False,
            "message": "\u5e94\u7528\u5931\u8d25\u5df2\u56de\u6eda\uff1a{0}".format(exc),
        }
    success = bool(getattr(outcome, "success", False))
    if not success:
        return {
            "applied": [],
            "skipped": skipped,
            "rolledBack": bool(getattr(outcome, "conflicts", [])) or True,
            "success": False,
            "message": getattr(outcome, "message", "") or "\u91cd\u5bfc\u5165\u672a\u6210\u529f\u3002",
        }
    applied = [item.rel_path for item in applicable]
    return {
        "applied": applied,
        "skipped": skipped,
        "rolledBack": False,
        "success": True,
        "message": "\u5df2\u5e94\u7528 {0} \u9879\uff0c\u8df3\u8fc7 {1} \u9879\u3002".format(len(applied), len(skipped)),
    }


@dataclass
class ConflictResolution:
    """Git \u51b2\u7a81\u89e3\u51b3\u7ed3\u679c\u3002"""

    rel_path: str
    supported: bool = True
    merged_text: str = ""
    has_markers: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "relPath": self.rel_path,
            "supported": self.supported,
            "hasMarkers": self.has_markers,
            "reason": self.reason,
        }


def unsupported_reason(path: Union[str, Path]) -> str:
    """\u8fd4\u56de\u4e0d\u652f\u6301\u81ea\u52a8\u5408\u5e76\u7684\u539f\u56e0\uff08\u7a7a\u8868\u793a\u652f\u6301\uff09\u3002"""
    target = Path(path)
    if target.suffix.lower() in BINARY_SUFFIXES:
        return "\u4e8c\u8fdb\u5236\u6587\u4ef6\u4e0d\u652f\u6301\u6587\u672c\u5408\u5e76\uff0c\u8bf7\u7528\u5916\u90e8\u5de5\u5177\u5904\u7406\u540e\u6807\u8bb0\u5df2\u89e3\u51b3\u3002"
    for parent in [target] + list(target.parents):
        if (parent / SVN_DIR).is_dir():
            return "SVN \u5de5\u4f5c\u526f\u672c\u4e0d\u652f\u6301\u672c\u5de5\u5177\u7684 Git \u51b2\u7a81\u6d41\u7a0b\uff0c\u8bf7\u5728 SVN \u5ba2\u6237\u7aef\u89e3\u51b3\u540e\u624b\u52a8\u786e\u8ba4\u3002"
    return ""


def merge_versions(base_text: str, ours_text: str, theirs_text: str) -> Tuple[str, bool]:
    """\u4e09\u65b9\u5408\u5e76\uff1a\u4f18\u5148\u7528 ``git merge-file``\uff0c\u4e0d\u53ef\u7528\u65f6\u56de\u9000\u5230\u6807\u8bb0\u5408\u5e76\u3002

    \u8fd4\u56de ``(text, has_conflict_markers)``\u3002
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="doc-tool-merge-") as tmp:
        tmp_path = Path(tmp)
        base_file = tmp_path / "base.md"
        ours_file = tmp_path / "ours.md"
        theirs_file = tmp_path / "theirs.md"
        base_file.write_text(base_text, encoding="utf-8")
        ours_file.write_text(ours_text, encoding="utf-8")
        theirs_file.write_text(theirs_text, encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    "git", "merge-file",
                    "-L", "ours", "-L", "base", "-L", "theirs",
                    "--stdout", str(ours_file), str(base_file), str(theirs_file),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is not None and completed.returncode in (0, 1):
            text = completed.stdout or ""
            return text, (MERGE_CONFLICT_MARKER in text)
    # \u56de\u9000\uff1a\u4e09\u65b9\u4e0d\u4e00\u81f4\u65f6\u4fdd\u7559 ours \u5e76\u6807\u8bb0\u51b2\u7a81\u533a\u57df\u4f9b\u4eba\u5de5\u5904\u7406
    if ours_text == theirs_text:
        return ours_text, False
    if base_text == theirs_text:
        return ours_text, False
    if base_text == ours_text:
        return theirs_text, False
    merged = (
        MERGE_CONFLICT_MARKER + " ours\n" + ours_text
        + "\n=======\n" + theirs_text
        + "\n>>>>>>> theirs\n"
    )
    return merged, True


def resolve_git_conflict(
    rel_path: Union[str, Path],
    base_text: str,
    ours_text: str,
    theirs_text: str,
    *,
    confirmed: bool = False,
    result_text: Optional[str] = None,
    worktree_checker=None,
) -> Tuple[ConflictResolution, bool]:
    """\u89e3\u51b3\u4e00\u4e2a Markdown \u51b2\u7a81\uff0c\u8fd4\u56de ``(resolution, written)``\u3002

    - \u4e8c\u8fdb\u5236 / SVN \u76f4\u63a5\u4e0d\u652f\u6301\uff0c\u7ed9\u660e\u786e\u8bf4\u660e\uff1b
    - ``confirmed=False`` \u65f6\u53ea\u8fd4\u56de\u5408\u5e76\u7ed3\u679c\uff0c**\u4e0d\u5199\u76d8**\uff1b
    - \u786e\u8ba4\u540e\u5199\u5165\uff1b\u4ecd\u5b58\u5728\u51b2\u7a81\u6807\u8bb0\u5219\u62d2\u7edd\u5199\u5165\u5e76\u8bf4\u660e\uff1b
    - ``worktree_checker`` \u53ef\u4f20\u5165\u6821\u9a8c\u51fd\u6570\uff08\u9ed8\u8ba4\u7528 git status \u786e\u8ba4\u5de5\u4f5c\u6811\u72b6\u6001\uff09\u3002
    """
    target = Path(rel_path)
    resolution = ConflictResolution(rel_path=str(target))
    reason = unsupported_reason(target)
    if reason:
        resolution.supported = False
        resolution.reason = reason
        return resolution, False

    merged = result_text if result_text is not None else merge_versions(base_text, ours_text, theirs_text)[0]
    resolution.merged_text = merged
    resolution.has_markers = MERGE_CONFLICT_MARKER in merged
    if resolution.has_markers:
        resolution.reason = "\u4ecd\u5b58\u5728\u51b2\u7a81\u6807\u8bb0\uff0c\u8bf7\u5148\u5b8c\u6210\u4eba\u5de5\u5408\u5e76\u3002"
        return resolution, False
    if not confirmed:
        resolution.reason = "\u5f85\u786e\u8ba4\uff1a\u672a\u5199\u5165"
        return resolution, False
    if worktree_checker is not None:
        ok, why = worktree_checker(target)
        if not ok:
            resolution.reason = why
            return resolution, False
    try:
        from doc_tool.application.content.writer import atomic_write

        atomic_write(target, merged)
    except Exception as exc:  # noqa: BLE001
        resolution.reason = "\u5199\u5165\u5931\u8d25\uff1a{0}".format(exc)
        return resolution, False
    resolution.reason = "\u5df2\u5199\u5165\u5e76\u53ef\u6807\u8bb0 resolved"
    return resolution, True


def git_stage_resolved(rel_path: Union[str, Path], *, add: bool = True) -> bool:
    """\u628a\u786e\u8ba4\u540e\u7684\u6587\u4ef6\u6807\u8bb0\u4e3a\u5df2\u89e3\u51b3\uff08``git add``\uff09\uff1b\u4e0d\u6267\u884c\u4efb\u4f55\u63a8\u9001\u3002"""
    try:
        completed = subprocess.run(
            ["git", "add", "--", str(rel_path)] if add else ["git", "diff", "--check", "--", str(rel_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_hashes(service, name: str) -> Dict[str, str]:
    getter = getattr(service, name, None)
    if getter is None:
        return {}
    try:
        return dict(getter())
    except Exception:  # noqa: BLE001
        return {}


def _reason_for(change: str, conflict: bool) -> str:
    if conflict:
        return "\u53cc\u65b9\u5747\u5df2\u4fee\u6539\uff0c\u4fdd\u7559\u672c\u5730"
    return {
        "added": "\u65b0\u589e\u7ae0\u8282",
        "modified": "\u4ec5\u6e90\u53d8\u66f4\uff0c\u53ef\u81ea\u52a8\u5408\u5165",
        "deleted": "\u6e90\u5df2\u5220\u9664\uff0c\u9700\u786e\u8ba4\u540e\u624d\u5220",
        "unchanged": "\u65e0\u53d8\u5316",
    }.get(change, "")