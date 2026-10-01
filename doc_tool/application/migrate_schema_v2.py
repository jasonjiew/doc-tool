# -*- coding: utf-8 -*-
"""项目清单 schema v1 → v2 升级（V2.8 28-A / 1.2、1.3）。

设计要点（见 ``product-v28-team-standardization`` D2）：

- 默认保持 v1：只有用户显式选择才写入 v2；
- 升级前生成**完整备份**与**前后预览**（字段级差异）；
- 提交走「准备目录 + 原子替换」，中途失败回滚且不破坏原清单；
- 升级失败时保留用户在升级后又编辑的副本；
- 未知/不可写模式版本一律拒绝写入（只读）。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from doc_tool.domain.errors import IncompatibleSchemaError, ProjectManifestError
from doc_tool.domain.manifest import MANIFEST_NAME, ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.version import APP_VERSION


#: 升级产物目录（项目内，不在正式目录下）。
MIGRATION_DIR = ".state/migrations"
#: v2 新增字段的默认值（缺省时不写入，保持清单精简）。
V2_OPTIONAL_FIELDS = ("documentKind", "chapters", "variables", "standardPack", "qualitySource")


@dataclass
class MigrationPreview:
    """升级前后字段级差异。"""

    from_schema: int
    to_schema: int
    unchanged: List[str] = field(default_factory=list)
    added: List[Tuple[str, object]] = field(default_factory=list)
    changed: List[Tuple[str, object, object]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed)

    def markdown_text(self) -> str:
        lines = [
            "## 项目清单升级预览",
            "",
            "- 模式版本：{0} → {1}".format(self.from_schema, self.to_schema),
        ]
        if not self.has_changes:
            lines.append("- 字段无变化（仅模式版本升级）。")
            return "\n".join(lines)
        lines.append("")
        lines.append("| 字段 | 变化 | 旧值 | 新值 |")
        lines.append("|------|------|------|------|")
        for key, value in self.added:
            lines.append("| {0} | 新增 | — | {1} |".format(key, _short(value)))
        for key, before, after in self.changed:
            lines.append("| {0} | 修改 | {1} | {2} |".format(key, _short(before), _short(after)))
        return "\n".join(lines)


@dataclass
class MigrationResult:
    """升级执行结果。"""

    success: bool
    project_root: str
    from_schema: int = 0
    to_schema: int = 0
    backup_path: str = ""
    log_path: str = ""
    message: str = ""
    preview: Optional[MigrationPreview] = None
    preserved_edit_path: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "success": self.success,
            "projectRoot": self.project_root,
            "fromSchema": self.from_schema,
            "toSchema": self.to_schema,
            "backupPath": self.backup_path,
            "logPath": self.log_path,
            "message": self.message,
            "preservedEditPath": self.preserved_edit_path,
            "changedFields": (
                [key for key, _value in self.preview.added]
                + [key for key, _before, _after in self.preview.changed]
                if self.preview is not None
                else []
            ),
        }


def build_upgrade_dict(manifest: ProjectManifest) -> Dict[str, object]:
    """把 v1 清单转成 v2 字典（不写盘）。

    升级**不改变文档表达**：仅模式版本与可选 v2 字段变化。
    缺省的可选字段不写入，避免清单臆肿。
    """
    data = manifest.to_dict()
    data["schemaVersion"] = 2
    for key in V2_OPTIONAL_FIELDS:
        if not data.get(key):
            data.pop(key, None)
    return data


def preview_upgrade(manifest: ProjectManifest) -> MigrationPreview:
    """生成字段级前后预览（不写盘）。"""
    before = manifest.to_dict()
    after = build_upgrade_dict(manifest)
    added: List[Tuple[str, object]] = []
    changed: List[Tuple[str, object, object]] = []
    unchanged: List[str] = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            added.append((key, after[key]))
        elif key not in after:
            changed.append((key, before[key], None))
        elif before[key] != after[key]:
            changed.append((key, before[key], after[key]))
        else:
            unchanged.append(key)
    return MigrationPreview(
        from_schema=int(before.get("schemaVersion") or 0),
        to_schema=2,
        unchanged=unchanged,
        added=added,
        changed=changed,
    )


def migrate_project(
    project_root: Union[str, Path],
    *,
    apply: bool = False,
) -> MigrationResult:
    """把 v1 项目升级为 v2；``apply=False`` 时只做预览。

    失败时不修改原清单，并把已写的中间产物保留在 ``.state/migrations/`` 供诊断。
    """
    root = Path(project_root).resolve()
    paths = ProjectPaths(root)
    manifest_path = paths.manifest_file
    if not manifest_path.is_file():
        raise ProjectManifestError(
            "项目清单不存在：{0}".format(MANIFEST_NAME),
            suggested_action="请确认选择了正确的项目目录。",
        )
    manifest = ProjectManifest.load(root)
    preview = preview_upgrade(manifest)
    result = MigrationResult(
        success=True,
        project_root=str(root),
        from_schema=manifest.schemaVersion,
        to_schema=2,
        preview=preview,
    )
    if manifest.schemaVersion >= 2:
        result.message = "项目已是模式版本 {0}，无需升级。".format(manifest.schemaVersion)
        return result
    if not apply:
        result.message = "预览完成：将从 v{0} 升级到 v2（未写入）。".format(manifest.schemaVersion)
        return result

    migration_dir = root / MIGRATION_DIR
    migration_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_path = migration_dir / "project.v1.{0}.bak.yml".format(stamp)
    log_path = migration_dir / "migrate-{0}.log".format(stamp)
    staging = migration_dir / "project.v2.{0}.yml".format(stamp)
    try:
        shutil.copy2(manifest_path, backup_path)
        upgraded = build_upgrade_dict(manifest)
        import yaml

        staging.write_text(
            yaml.safe_dump(upgraded, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        # 先校验站站文件能被当前应用完整读回，再原子替换。
        ProjectManifest.from_dict(upgraded, root)
        os.replace(str(staging), str(manifest_path))
        log_path.write_text(
            "\n".join(
                [
                    "升级时间：{0}".format(datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    "应用版本：{0}".format(APP_VERSION),
                    "模式版本：v{0} → v2".format(manifest.schemaVersion),
                    "备份：{0}".format(backup_path.name),
                    "预览：",
                    preview.markdown_text(),
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - 升级失败必须保持原清单
        result.success = False
        result.message = "升级失败：{0}".format(exc)
        result.backup_path = str(backup_path) if backup_path.exists() else ""
        result.log_path = str(log_path) if log_path.exists() else ""
        _preserve_edited_copy(manifest_path, migration_dir, result)
        return result
    result.backup_path = str(backup_path)
    result.log_path = str(log_path)
    result.message = "已升级为模式版本 2，备份保留在 {0}。".format(
        backup_path.relative_to(root).as_posix()
    )
    return result


def _preserve_edited_copy(manifest_path: Path, migration_dir: Path, result: MigrationResult) -> None:
    """升级失败时保留当前清单副本，避免用户编辑丢失。"""
    try:
        preserved = migration_dir / "project.failed-upgrade.{0}.yml".format(
            datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        )
        shutil.copy2(manifest_path, preserved)
        result.preserved_edit_path = str(preserved)
    except OSError:
        return


def _short(value: object, limit: int = 60) -> str:
    text = " ".join(str(value).split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return text or "—"