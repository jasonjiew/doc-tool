# -*- coding: utf-8 -*-
"""V3.2 3.4：包版本不符时回退为“只读/可导出可读产物”。

包清单的 ``schemaVersion`` 高于或低于当前实现时，不再一律判为不可用：
只要清单仍可读、``kind`` 匹配且可读产物存在，就标记 ``readableOnly``，允许
**阅读与导出可读产物**（DOCX/HTML），但拒绝在包内执行正式化/重新推导，
避免用未知版本语义覆盖当前项目。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class VersionFallback:
    """包版本回退事实。"""

    readableOnly: bool = False
    packageVersion: int = 0
    supportedVersion: int = 0
    reason: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "readableOnly": self.readableOnly,
            "packageVersion": self.packageVersion,
            "supportedVersion": self.supportedVersion,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


def version_fallback(package) -> VersionFallback:
    """判断包是否为“版本不符但可读/可导出”的回退情形。

    只读取清单本身，不解析包内其它内容；无法读取时必须返回不可回退（由调用方
    按不可用处理）。
    """
    from doc_tool.application.delivery import snapshot_package as pkg

    fallback = VersionFallback(supportedVersion=pkg.PACKAGE_SCHEMA_VERSION)
    path = Path(package)
    data = _read_manifest_lenient(path)
    if data is None:
        fallback.reason = "包清单不可读：不是本应用的交付包"
        return fallback
    if str(data.get("kind") or "") != pkg.PACKAGE_KIND:
        fallback.reason = "包类型不匹配：{0}".format(data.get("kind") or "未知")
        return fallback
    try:
        version = int(data.get("schemaVersion") or 0)
    except (TypeError, ValueError):
        version = 0
    fallback.packageVersion = version
    if version == pkg.PACKAGE_SCHEMA_VERSION:
        return fallback
    fallback.readableOnly = True
    if version > pkg.PACKAGE_SCHEMA_VERSION:
        fallback.reason = (
            "包版本 {0} 高于当前支持的 {1}：只回退阅读与导出可读产物，"
            "不在包内执行正式化".format(version, pkg.PACKAGE_SCHEMA_VERSION)
        )
    else:
        fallback.reason = (
            "包版本 {0} 低于当前支持的 {1}：按只读兼容处理，"
            "正式化请在原机器完成".format(version, pkg.PACKAGE_SCHEMA_VERSION)
        )
    fallback.warnings.append(fallback.reason)
    files = data.get("files") or []
    if isinstance(files, list) and not files:
        fallback.warnings.append("包清单没有文件记录：可读产物可能不完整")
    return fallback


def _read_manifest_lenient(path: Path) -> Optional[Dict[str, object]]:
    """宽松读取包清单（忽略 schemaVersion 校验，但保持路径与类型约束）。"""
    import json
    import zipfile

    name = "package-manifest.json"
    try:
        from doc_tool.application.delivery import snapshot_package as pkg

        name = pkg.PACKAGE_MANIFEST_NAME
    except Exception:  # noqa: BLE001
        pass
    try:
        if path.is_dir():
            target = path / name
            if not target.is_file():
                return None
            data = json.loads(target.read_text(encoding="utf-8"))
        elif path.is_file() and zipfile.is_zipfile(str(path)):
            with zipfile.ZipFile(str(path)) as archive:
                if name not in archive.namelist():
                    return None
                data = json.loads(archive.read(name).decode("utf-8"))
        else:
            return None
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return data if isinstance(data, dict) else None


def readable_artifacts(package) -> List[Dict[str, object]]:
    """列出包内可读产物（DOCX/HTML/源码包），供回退导出使用。"""
    out: List[Dict[str, object]] = []
    data = _read_manifest_lenient(Path(package))
    if data is None:
        return out
    for entry in data.get("files") or []:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path") or "")
        if rel.lower().endswith((".docx", ".html", ".zip")):
            out.append({
                "path": rel,
                "role": str(entry.get("role") or ""),
                "sha256": str(entry.get("sha256") or ""),
            })
    return out


__all__ = ["VersionFallback", "version_fallback", "readable_artifacts"]