# -*- coding: utf-8 -*-
"""项目清单 ``project.yml`` 的模式定义、加载、保存与版本兼容。

任务 1.2：定义 ``project.yml`` v1 模式、字段校验和示例项目清单。
任务 1.3：实现 ``ProjectManifest`` 的加载、保存、版本兼容和清单备份。

清单字段（v1）：
    schemaVersion: 1
    projectId: <稳定 UUID>
    documentType: general | requirement | design
    documentNo: <公司文档编号>
    documentName: <文档名称>
    documentVersion: <版本字符串>
    paths:
      sourceDocx: original/source.docx
      templateDocx: template/template.docx
      contentRoot: content/<documentType>
      assetRoot: assets/<documentType>
      tableRoot: assets/<documentType>/tables
    sourceSha256: <源 DOCX 的 SHA-256>
    createdWithVersion: <创建时的应用版本>
    lastSuccessfulBuildVersion: <最近成功构建的应用版本或 null>
    refresh:
      timeoutSeconds: 900

所有路径必须相对项目根，并经过 ``ProjectPaths`` 包含校验。
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from doc_tool.domain.errors import IncompatibleSchemaError, ProjectManifestError
from doc_tool.domain.paths import MANIFEST_NAME, ProjectPaths, build_output_filename
from doc_tool.domain.version import (
    APP_VERSION,
    PROJECT_SCHEMA_VERSION,
    can_read_schema,
    can_write_schema,
)


DOCUMENT_TYPES = ("general", "requirement", "design")

# 默认刷新超时（秒），与现有 config 保持一致。
DEFAULT_REFRESH_TIMEOUT_SECONDS = 900


def _parse_heading_level(value) -> int:
    """严格把 ``headingStyles`` 键解析为正整数。

    YAML 键常以字符串（``"1"``）或整型出现；浮点（``1.5``）或布尔必须被拒绝
    而非静默截断成 ``1``——否则项目会按错误的标题层级映射构建，往返门禁与
    校验产生难以定位的差异。
    """
    if isinstance(value, bool):
        raise ValueError("headingStyles 级别不能是布尔值")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("headingStyles 级别必须是整数，实际为 {0}".format(value))
    level = int(value)
    if level < 1:
        raise ValueError("headingStyles 级别必须 ≥ 1，实际为 {0}".format(value))
    return level


@dataclass
class ProjectManifest:
    """项目清单：可移植、版本化的项目元数据。

    所有路径相对项目根存储，复制到另一台机器后无需修改即可打开。
    """

    documentType: str
    documentNo: str
    documentName: str
    documentVersion: str
    sourceSha256: str
    projectId: str = field(default_factory=lambda: str(uuid.uuid4()))
    schemaVersion: int = PROJECT_SCHEMA_VERSION
    paths: Dict[str, str] = field(default_factory=dict)
    createdWithVersion: str = APP_VERSION
    lastSuccessfulBuildVersion: Optional[str] = None
    publishNotes: str = ""
    refreshTimeoutSeconds: int = DEFAULT_REFRESH_TIMEOUT_SECONDS
    # 模板相关的构建样式（v1 附加字段，向后兼容：旧清单无此字段时为空）。
    # 由导入服务根据源文档类型从默认配置写入，构建时由适配层消费。
    headingStyles: Dict[int, str] = field(default_factory=dict)
    bodyStyle: str = ""
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    def __post_init__(self) -> None:
        try:
            self.schemaVersion = int(self.schemaVersion)
            self.refreshTimeoutSeconds = int(self.refreshTimeoutSeconds)
        except (TypeError, ValueError) as exc:
            raise ProjectManifestError(
                "schemaVersion 和刷新超时必须是整数。",
                details={"errorType": type(exc).__name__},
            ) from exc
        self.documentNo = str(self.documentNo)
        self.documentName = str(self.documentName)
        self.documentVersion = str(self.documentVersion)
        if self.documentType not in DOCUMENT_TYPES and can_write_schema(self.schemaVersion):
            raise ProjectManifestError(
                "未知的文档类型：{0}。".format(self.documentType),
                details={"documentType": self.documentType},
            )
        if not self.documentName:
            raise ProjectManifestError("文档名称不能为空。")
        if self.documentType != "general" and not self.documentNo:
            raise ProjectManifestError("需求/详细设计文档的文档编号不能为空。")
        if can_write_schema(self.schemaVersion):
            build_output_filename(
                self.documentNo,
                self.documentName,
                self.documentVersion,
                self.documentType,
            )
        if can_write_schema(self.schemaVersion) and self.refreshTimeoutSeconds < 60:
            raise ProjectManifestError(
                "刷新超时不能小于 60 秒。",
                details={"timeout": str(self.refreshTimeoutSeconds)},
            )

    # --- 路径访问（经 ProjectPaths 解析与包含校验） ---

    def resolve_paths(self, project_root: Union[str, Path]) -> ProjectPaths:
        """返回绑定到指定项目根的 ``ProjectPaths``，并校验清单内路径。"""
        paths = ProjectPaths(project_root)
        for key, relative in self.paths.items():
            if relative:
                paths.resolve(relative)  # 越界时抛 PathEscapeError
        return paths

    def relative_source_docx(self) -> str:
        return self.paths.get("sourceDocx", "original/source.docx")

    def relative_template_docx(self) -> str:
        return self.paths.get("templateDocx", "template/template.docx")

    def relative_content_root(self) -> str:
        return self.paths.get("contentRoot", "content/{0}".format(self.documentType))

    def relative_asset_root(self) -> str:
        return self.paths.get("assetRoot", "assets/{0}".format(self.documentType))

    def relative_table_root(self) -> str:
        return self.paths.get("tableRoot", "assets/{0}/tables".format(self.documentType))

    # --- 序列化 ---

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "projectId": self.projectId,
            "documentType": self.documentType,
            "documentNo": self.documentNo,
            "documentName": self.documentName,
            "documentVersion": self.documentVersion,
            "paths": dict(self.paths),
            "sourceSha256": self.sourceSha256,
            "createdWithVersion": self.createdWithVersion,
            "lastSuccessfulBuildVersion": self.lastSuccessfulBuildVersion,
            "publishNotes": self.publishNotes,
            "headingStyles": {str(k): v for k, v in self.headingStyles.items()},
            "bodyStyle": self.bodyStyle,
            "refresh": {"timeoutSeconds": self.refreshTimeoutSeconds},
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    # --- 保存与备份 ---

    def save(self, project_root: Union[str, Path], *, backup: bool = True) -> Path:
        """写入 ``project.yml``，写入前对已存在清单做时间戳备份。"""
        if not self.is_writable():
            raise IncompatibleSchemaError(
                "当前应用不能写入项目模式版本 {0}。".format(self.schemaVersion),
                suggested_action="请使用创建或升级该项目的兼容版本应用。",
                details={"schemaVersion": str(self.schemaVersion)},
            )
        paths = ProjectPaths(project_root)
        manifest_path = paths.manifest_file
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.updatedAt = now
        if self.createdAt is None:
            self.createdAt = now
        if backup and manifest_path.exists():
            self._backup_manifest(manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = manifest_path.with_suffix(".yml.tmp")
        tmp_path.write_text(self.to_yaml(), encoding="utf-8")
        try:
            os.replace(tmp_path, manifest_path)
        except OSError:
            # 跨卷/挂载点场景（如部分 D 盘配置）os.replace 会失败，回退到 shutil.move。
            shutil.move(str(tmp_path), str(manifest_path))
        return manifest_path

    @staticmethod
    def _backup_manifest(manifest_path: Path) -> Path:
        backup_name = "{0}.{1}.bak".format(
            MANIFEST_NAME, datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        )
        backup_path = manifest_path.parent / ".state" / backup_name
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path, backup_path)
        return backup_path

    # --- 加载与版本兼容 ---

    @classmethod
    def load(cls, project_root: Union[str, Path]) -> "ProjectManifest":
        """从项目根读取 ``project.yml`` 并校验模式版本。"""
        paths = ProjectPaths(project_root)
        manifest_path = paths.manifest_file
        if not manifest_path.exists():
            raise ProjectManifestError(
                "项目清单不存在：{0}".format(MANIFEST_NAME),
                suggested_action="请确认选择了正确的项目目录，或使用导入功能创建项目。",
                details={"path": str(manifest_path)},
            )
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeError, OSError) as exc:
            raise ProjectManifestError(
                "项目清单 YAML 解析失败。",
                details={"error": str(exc)},
            ) from exc
        if not isinstance(data, dict):
            raise ProjectManifestError("项目清单格式不正确：根节点应为映射。")
        return cls.from_dict(data, project_root)

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], project_root: Optional[Union[str, Path]] = None
    ) -> "ProjectManifest":
        """从字典构造清单并校验字段与模式版本。"""
        try:
            schema_version = int(data.get("schemaVersion", 0))
        except (TypeError, ValueError) as exc:
            raise ProjectManifestError(
                "项目清单 schemaVersion 必须是整数。",
                details={"field": "schemaVersion"},
            ) from exc
        if schema_version == 0:
            raise ProjectManifestError("项目清单缺少 schemaVersion 字段。")
        if not can_read_schema(schema_version):
            raise IncompatibleSchemaError(
                "项目模式版本 {0} 不被当前应用支持。".format(schema_version),
                details={"schemaVersion": str(schema_version)},
            )
        paths_data = data.get("paths") or {}
        refresh_data = data.get("refresh") or {}
        heading_styles_data = data.get("headingStyles") or {}
        if (
            not isinstance(paths_data, dict)
            or not isinstance(refresh_data, dict)
            or not isinstance(heading_styles_data, dict)
        ):
            raise ProjectManifestError(
                "项目清单 paths、refresh 和 headingStyles 字段必须是映射。",
                details={"field": "paths/refresh/headingStyles"},
            )
        try:
            manifest = cls(
                documentType=str(data["documentType"]),
                documentNo=str(data["documentNo"]),
                documentName=str(data["documentName"]),
                documentVersion=str(data["documentVersion"]),
                sourceSha256=str(data.get("sourceSha256", "")),
                projectId=str(data.get("projectId", str(uuid.uuid4()))),
                schemaVersion=schema_version,
                paths={str(key): str(value) for key, value in paths_data.items()},
                createdWithVersion=str(data.get("createdWithVersion", APP_VERSION)),
                lastSuccessfulBuildVersion=data.get("lastSuccessfulBuildVersion"),
                publishNotes=str(data.get("publishNotes", "") or ""),
                headingStyles={
                    _parse_heading_level(level): str(style_id)
                    for level, style_id in heading_styles_data.items()
                },
                bodyStyle=str(data.get("bodyStyle", "") or ""),
                refreshTimeoutSeconds=int(
                    refresh_data.get("timeoutSeconds", DEFAULT_REFRESH_TIMEOUT_SECONDS)
                ),
                createdAt=data.get("createdAt"),
                updatedAt=data.get("updatedAt"),
            )
        except KeyError as exc:
            raise ProjectManifestError(
                "项目清单缺少必填字段：{0}。".format(exc.args[0]),
                details={"field": str(exc.args[0])},
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ProjectManifestError(
                "项目清单字段类型不正确。",
                details={"errorType": type(exc).__name__},
            ) from exc
        if project_root is not None:
            manifest.resolve_paths(project_root)
        return manifest

    def is_writable(self) -> bool:
        """当前应用能否写入此项目（模式版本兼容）。"""
        return can_write_schema(self.schemaVersion)

    def mark_successful_build(self, version: str) -> None:
        self.lastSuccessfulBuildVersion = version


def increment_version(current: str, kind: str) -> str:
    """Increment a semantic version, accepting one to three numeric components."""
    if kind not in ("patch", "minor", "major"):
        raise ValueError("版本递增类型必须是 patch、minor 或 major。")
    parts = str(current).strip().split(".")
    if not parts or len(parts) > 3 or any(not part.isdigit() for part in parts):
        raise ValueError("版本号必须由 1 至 3 个点分十进制数字组成。")
    values = [int(part) for part in parts] + [0] * (3 - len(parts))
    if kind == "major":
        values = [values[0] + 1, 0, 0]
    elif kind == "minor":
        values = [values[0], values[1] + 1, 0]
    else:
        values[2] += 1
    return ".".join(str(value) for value in values)
