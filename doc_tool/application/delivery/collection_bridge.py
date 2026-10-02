# -*- coding: utf-8 -*-
"""交付包/结果归档复用 V2.9 集合能力（V3.2 32-C 3.2 / 32-E 5.3）。

V2.9 已有集合基线：文件收集（跳过 `.git`/缓存/虚拟环境）、分类、清单构建、
原子登记与安全 ZIP 导出。本模块只做**桥接**，不复制那套实现：

- :func:`collection_manifest_for`：对一个目录生成集合格式清单（交付包内容索引）；
- :func:`export_collection_zip`：按集合清单导出安全 ZIP（越界/缺失/改动项跳过并记录）；
- :func:`register_collection`：把完整集合登记进 V2.9 集合存储（完整登记的唯一入口）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class CollectionBridgeOutcome:
    """桥接结果（清单摘要 + 跳过项 + 登记信息）。"""

    ok: bool = False
    fileCount: int = 0
    categories: Dict[str, int] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)
    complete: bool = False
    manifestPath: str = ""
    zipPath: str = ""
    registrationPath: str = ""
    registrationNote: str = ""
    warnings: List[str] = field(default_factory=list)
    message: str = ""

    def summary_lines(self) -> List[str]:
        lines = []
        if self.fileCount:
            lines.append("集合清单 {0} 个文件".format(self.fileCount))
        if self.categories:
            lines.append("· 分类：" + "、".join(
                "{0} {1}".format(name, count) for name, count in sorted(self.categories.items())
            ))
        if self.skipped:
            lines.append("· 跳过 {0} 项（越界/缺失/已改动）".format(len(self.skipped)))
        if self.registrationPath:
            lines.append("· 已登记集合基线：{0}".format(Path(self.registrationPath).name))
        for item in self.warnings[:3]:
            lines.append("提醒：{0}".format(item))
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "fileCount": self.fileCount,
            "categories": dict(self.categories),
            "skipped": list(self.skipped),
            "complete": self.complete,
            "manifestPath": self.manifestPath,
            "zipPath": self.zipPath,
            "registrationPath": self.registrationPath,
            "registrationNote": self.registrationNote,
            "warnings": list(self.warnings),
            "message": self.message,
        }


def collection_manifest_for(
    root,
    *,
    version: str = "1.0",
    label: str = "",
    manifest_name: str = "collection-manifest.yml",
    strict: bool = False,
):
    """为一个目录生成 V2.9 集合清单并落盘；返回 ``(清单, 路径)``。"""
    from doc_tool.application import collection

    base = Path(root)
    manifest = collection.build_manifest(base, version=version, label=label, strict=strict)
    target = base / manifest_name
    try:
        import yaml

        target.write_text(
            yaml.safe_dump(manifest.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except (OSError, ImportError):
        target = None
    return manifest, target


def manifest_summary(manifest) -> Tuple[Dict[str, int], List[str], bool]:
    """清单摘要：分类计数、缺失清单、是否完整。"""
    categories: Dict[str, int] = {}
    for item in getattr(manifest, "files", []) or []:
        key = str(getattr(item, "category", "") or "other")
        categories[key] = categories.get(key, 0) + 1
    missing = [str(item) for item in (getattr(manifest, "missing", []) or [])]
    return categories, missing, bool(getattr(manifest, "complete", False))


def export_collection_zip(root, manifest_path, destination) -> Tuple[Optional[Path], List[str]]:
    """按集合清单导出安全 ZIP（复用 V2.9 导出；越界/缺失/改动项跳过）。"""
    from doc_tool.application import collection_ops

    return collection_ops.export_package(root, manifest_path, destination)


def register_collection(
    root, manifest, *, allow_duplicate_version: bool = False,
) -> Tuple[Optional[Path], str]:
    """把完整集合登记进 V2.9 集合存储；失败不删除已有成果。"""
    from doc_tool.application import collection

    return collection.register_manifest(
        root, manifest, allow_duplicate_version=allow_duplicate_version,
    )


def bridge_directory(
    root,
    *,
    version: str = "1.0",
    label: str = "",
    register: bool = False,
    zip_target=None,
) -> CollectionBridgeOutcome:
    """对目录做一次完整桥接：清单 → （可选）登记 → （可选）安全 ZIP。"""
    outcome = CollectionBridgeOutcome()
    base = Path(root)
    if not base.is_dir():
        outcome.message = "目录不存在：{0}".format(base)
        return outcome
    try:
        manifest, manifest_path = collection_manifest_for(
            base, version=version, label=label,
        )
    except Exception as exc:  # noqa: BLE001 - 集合能力异常不改写已有产物
        outcome.message = "集合清单未生成：{0}".format(exc)
        return outcome
    categories, missing, complete = manifest_summary(manifest)
    outcome.fileCount = len(getattr(manifest, "files", []) or [])
    outcome.categories = categories
    outcome.skipped = missing
    outcome.complete = complete
    outcome.manifestPath = str(manifest_path or "")
    outcome.warnings.extend(str(item) for item in (getattr(manifest, "warnings", []) or [])[:3])
    if register and complete:
        path, note = register_collection(base, manifest)
        outcome.registrationPath = str(path or "")
        outcome.registrationNote = note
        if path is None:
            outcome.warnings.append("集合登记未完成：{0}".format(note or "未知原因"))
    elif register:
        outcome.warnings.append("集合不完整（缺 {0} 项）：按部分集合处理，未登记完整基线".format(len(missing)))
    if zip_target is not None and manifest_path is not None:
        zip_path, skipped = export_collection_zip(base, manifest_path, zip_target)
        outcome.zipPath = str(zip_path or "")
        outcome.skipped.extend(item for item in skipped if item not in outcome.skipped)
        if zip_path is None:
            outcome.warnings.append("集合 ZIP 未生成")
    outcome.ok = bool(outcome.fileCount) and (not missing or not outcome.complete)
    outcome.message = "集合桥接完成" if outcome.ok else "集合桥接部分完成"
    return outcome


__all__ = [
    "CollectionBridgeOutcome", "collection_manifest_for", "manifest_summary",
    "export_collection_zip", "register_collection", "bridge_directory",
]