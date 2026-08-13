# -*- coding: utf-8 -*-
"""用户偏好设置迁移（内部版 → 公共版，只读、幂等）。

内部版把非敏感用户偏好存放在旧用户配置目录（见品牌元数据
``LEGACY_USER_CONFIG_DIR_NAME``）；公共版改用公共用户配置目录。为不丢失用户
偏好，公共版首次启动时把「允许迁移的字段」从旧目录复制到新目录。

规则（对应任务 3.1/3.2）：
- 字段白名单：``ALLOWED_MIGRATION_FILES``（窗口几何、最近项目）。
  主题/Dock/标签状态按项目存放在项目内 ``.state/workspace.json``，不在此迁移。
- 首次启动：仅当公共目录中「任何白名单字段」都不存在时，才从旧目录复制；
  公共目录已有任一白名单文件 → 判定已迁移/已被用户设置，整体跳过（不覆盖）。
- 只读：绝不删除、修改旧目录中的任何文件。
- 幂等：重复执行与首次执行结果一致。
- 健壮：旧文件 JSON 损坏或缺失时跳过该文件，不中断其它字段；无旧目录时无操作。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from doc_tool.domain.branding import legacy_user_config_dir, user_config_dir

# 允许从旧命名空间迁移的文件（相对用户配置目录）。
# 只迁移非敏感偏好；密钥、缓存、诊断数据不迁移。
ALLOWED_MIGRATION_FILES = ("geometry.json", "recent.json")


@dataclass
class SettingsMigrationReport:
    """一次迁移的审计报告。"""

    public_dir: str
    legacy_dir: str
    already_present: bool = False  # 公共目录已有白名单字段 → 未执行
    copied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary_text(self) -> str:
        if self.already_present:
            return "公共设置已存在，跳过迁移（不覆盖用户设置）。"
        if not self.copied and not self.skipped:
            return "未发现可迁移的旧设置。"
        parts = ["已迁移: {0}".format(", ".join(self.copied) if self.copied else "无")]
        if self.skipped:
            parts.append("跳过(损坏): {0}".format(", ".join(self.skipped)))
        return "；".join(parts)


def _is_valid_json(path: Path) -> bool:
    """宽松 JSON 校验：损坏文件不迁移，避免把损坏状态带入新命名空间。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return False
    return isinstance(data, (dict, list))


def migrate_legacy_settings(
    public_dir: Optional[str] = None,
    legacy_dir: Optional[str] = None,
) -> SettingsMigrationReport:
    """首次启动只读迁移。

    Args:
        public_dir: 公共用户配置目录（默认从品牌元数据推导）。
        legacy_dir: 内部版用户配置目录（默认从品牌元数据推导）。

    Returns:
        ``SettingsMigrationReport`` 审计报告，永不抛出。
    """
    public = Path(public_dir or user_config_dir())
    legacy = Path(legacy_dir or legacy_user_config_dir())

    public_exists = public.exists()
    # 公共目录已有任一白名单字段 → 已迁移或用户已设置，整体跳过（不覆盖）。
    existing_public = [
        name
        for name in ALLOWED_MIGRATION_FILES
        if public_exists and (public / name).is_file()
    ]
    if existing_public:
        return SettingsMigrationReport(
            public_dir=str(public),
            legacy_dir=str(legacy),
            already_present=True,
            skipped=existing_public,
        )

    report = SettingsMigrationReport(public_dir=str(public), legacy_dir=str(legacy))
    if not legacy.is_dir():
        return report

    for name in ALLOWED_MIGRATION_FILES:
        src = legacy / name
        if not src.is_file():
            continue
        if not _is_valid_json(src):
            report.skipped.append(name)
            report.errors.append("旧设置损坏，未迁移: {0}".format(name))
            continue
        try:
            public.mkdir(parents=True, exist_ok=True)
            dst = public / name
            # 复制而非移动：保留旧值便于回滚。
            dst.write_bytes(src.read_bytes())
            report.copied.append(name)
        except OSError as exc:
            report.errors.append("{0}: {1}".format(name, exc))
    return report
