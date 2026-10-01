# -*- coding: utf-8 -*-
"""共享规则/术语的项目内位置、旧格式迁移与容错回退（V2.8 28-D / 4.1、4.2）。

位置优先级（两者均可读，新位置优先）：

1. ``<project>/quality/rules.json``、``<project>/quality/terms.json``（可入版本控制，便于团队共享）
2. ``<project>/.state/quality_rules.json``、``<project>/.state/terms.json``（旧位置，兼容）

迁移为**一次性且保留备份**：仅在新位置不存在且旧位置存在时执行，
原文件先复制到 ``.state/quality-migration-backup/`` 再写入新位置；任何写入失败都不影响读取。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Union

from doc_tool.application.content.quality_rules import QUALITY_RULES_FILE  # .state/quality_rules.json

#: 新的项目内共享目录。
QUALITY_DIR = "quality"
#: 新位置文件名。
QUALITY_RULES_NAME = "rules.json"
QUALITY_TERMS_NAME = "terms.json"
#: 旧位置术语文件名（兼容）。
LEGACY_TERMS_NAME = "terms.json"
#: 迁移备份子目录。
MIGRATION_BACKUP_DIR = ".state/quality-migration-backup"


@dataclass(frozen=True)
class QualityLocation:
    """规则/术语的实际位置与来源。"""

    path: Path
    source: str  # "project" | "legacy" | "none"

    @property
    def exists(self) -> bool:
        return self.path.is_file()


def resolve_quality_location(
    project_root: Union[str, Path],
    name: str,
    *,
    legacy_name: Optional[str] = None,
) -> QualityLocation:
    """解析规则/术语的读取位置（不写盘）。"""
    root = Path(project_root)
    new_path = root / QUALITY_DIR / name
    if new_path.is_file():
        return QualityLocation(new_path, "project")
    legacy = root / ".state" / (legacy_name or name)
    if legacy.is_file():
        return QualityLocation(legacy, "legacy")
    return QualityLocation(new_path, "none")


def migrate_legacy_quality_files(
    project_root: Union[str, Path],
) -> List[Tuple[str, str]]:
    """把旧 ``.state`` 下的规则/术语迁移到 ``quality/``（一次性 + 备份）。

    返回 ``[(name, backup_path), ...]``；无需迁移时返回空列表。
    新位置已存在时**不覆盖**，避免把团队共享版本冲掉。
    """
    root = Path(project_root)
    moved: List[Tuple[str, str]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidates = (
        (QUALITY_RULES_NAME, QUALITY_RULES_FILE),
        (QUALITY_TERMS_NAME, LEGACY_TERMS_NAME),
    )
    for name, legacy_name in candidates:
        source = root / ".state" / legacy_name
        if not source.is_file():
            continue
        target = root / QUALITY_DIR / name
        if target.is_file():
            continue
        backup_dir = root / MIGRATION_BACKUP_DIR
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / "{0}.{1}.bak".format(legacy_name, stamp)
            shutil.copy2(source, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError:
            continue
        moved.append((name, str(backup)))
    return moved


def safe_read_json(path: Path) -> Tuple[object, Optional[str]]:
    """容错读取 JSON：损坏时返回 ``(None, 原因)``，不抛异常。"""
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "文件不存在"
    except (OSError, UnicodeError) as exc:
        return None, "读取失败：{0}".format(exc)
    except json.JSONDecodeError as exc:
        return None, "格式损坏：{0}".format(exc)


def load_terms_with_fallback(project_root: Union[str, Path]) -> Tuple[List[str], List[str]]:
    """读取术语表：损坏或非法项跳过并返回可读说明。

    支持两种形状：``{"terms": [...]}\frank`` 与直接列表；不会因损坏而拖垓检查。
    """
    warnings: List[str] = []
    location = resolve_quality_location(
        project_root, QUALITY_TERMS_NAME, legacy_name=LEGACY_TERMS_NAME
    )
    if not location.exists:
        return [], warnings
    data, error = safe_read_json(location.path)
    if error is not None:
        warnings.append("术语配置不可用（{0}），已回退空术语表继续。".format(error))
        return [], warnings
    items = data
    if isinstance(data, dict):
        items = data.get("terms")
    if items is None:
        warnings.append("术语配置缺少 terms 字段，已回退空术语表继续。")
        return [], warnings
    if not isinstance(items, list):
        warnings.append("术语配置格式不正确，已回退空术语表继续。")
        return [], warnings
    terms: List[str] = []
    skipped = 0
    for item in items:
        if isinstance(item, str) and item.strip():
            terms.append(item.strip())
        elif isinstance(item, dict):
            canonical = str(item.get("canonical", "") or "").strip()
            if canonical:
                terms.append(canonical)
            else:
                skipped += 1
        else:
            skipped += 1
    if skipped:
        warnings.append("术语配置中有 {0} 项无效已跳过。".format(skipped))
    return terms, warnings


def quality_files_state(project_root: Union[str, Path]) -> dict:
    """供设置页/诊断使用的位置摘要。"""
    root = Path(project_root)
    rules = resolve_quality_location(root, QUALITY_RULES_NAME, legacy_name=QUALITY_RULES_FILE)
    terms = resolve_quality_location(root, QUALITY_TERMS_NAME, legacy_name=LEGACY_TERMS_NAME)
    return {
        "qualityDir": str(root / QUALITY_DIR),
        "rules": {"path": str(rules.path), "source": rules.source, "exists": rules.exists},
        "terms": {"path": str(terms.path), "source": terms.source, "exists": terms.exists},
        "needsMigration": rules.source == "legacy" or terms.source == "legacy",
    }