# -*- coding: utf-8 -*-
"""项目清单 ``project.yml`` 的模式定义、加载、保存与版本兼容。

任务 1.2：定义 ``project.yml`` v1 模式、字段校验和示例项目清单。
任务 1.3：实现 ``ProjectManifest`` 的加载、保存、版本兼容和清单备份。

清单字段（v1）：
    schemaVersion: 1
    projectId: <稳定 UUID>
    documentType: requirement | design
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
from doc_tool.domain.paths import MANIFEST_NAME, ProjectPaths
from doc_tool.domain.version import (
    APP_VERSION,
    PROJECT_SCHEMA_VERSION,
    can_read_schema,
    can_write_schema,
)


DOCUMENT_TYPES = ("requirement", "design")

# 默认刷新超时（秒），与现有 config 保持一致。
DEFAULT_REFRESH_TIMEOUT_SECONDS = 900


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
    refreshTimeoutSeconds: int = DEFAULT_REFRESH_TIMEOUT_SECONDS
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    def __post_init__(self) -> None:
        if self.documentType not in DOCUMENT_TYPES:
            raise ProjectManifestError(
                "未知的文档类型：{0}。".format(self.documentType),
                details={"documentType": self.documentType},
            )
        if not self.documentNo or not self.documentName:
            raise ProjectManifestError("文档编号和名称不能为空。")
        if self.refreshTimeoutSeconds < 60:
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
            "refresh": {"timeoutSeconds": self.refreshTimeoutSeconds},
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    # --- 保存与备份 ---

    def save(self, project_root: Union[str, Path], *, backup: bool = True) -> Path:
        """写入 ``project.yml``，写入前对已存在清单做时间戳备份。"""
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
        os.replace(tmp_path, manifest_path)
        return manifest_path

    @staticmethod
    def _backup_manifest(manifest_path: Path) -> Path:
        backup_name = "{0}.{1}.bak".format(
            MANIFEST_NAME, datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
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
        except yaml.YAMLError as exc:
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
        schema_version = int(data.get("schemaVersion", 0))
        if schema_version == 0:
            raise ProjectManifestError("项目清单缺少 schemaVersion 字段。")
        if not can_read_schema(schema_version):
            raise IncompatibleSchemaError(
                "项目模式版本 {0} 不被当前应用支持。".format(schema_version),
                details={"schemaVersion": str(schema_version)},
            )
        paths_data = data.get("paths") or {}
        refresh_data = data.get("refresh") or {}
        manifest = cls(
            documentType=data["documentType"],
            documentNo=data["documentNo"],
            documentName=data["documentName"],
            documentVersion=str(data["documentVersion"]),
            sourceSha256=data.get("sourceSha256", ""),
            projectId=data.get("projectId", str(uuid.uuid4())),
            schemaVersion=schema_version,
            paths=dict(paths_data),
            createdWithVersion=data.get("createdWithVersion", APP_VERSION),
            lastSuccessfulBuildVersion=data.get("lastSuccessfulBuildVersion"),
            refreshTimeoutSeconds=int(refresh_data.get("timeoutSeconds", DEFAULT_REFRESH_TIMEOUT_SECONDS)),
            createdAt=data.get("createdAt"),
            updatedAt=data.get("updatedAt"),
        )
        if project_root is not None:
            manifest.resolve_paths(project_root)
        return manifest

    def is_writable(self) -> bool:
        """当前应用能否写入此项目（模式版本兼容）。"""
        return can_write_schema(self.schemaVersion)

    def mark_successful_build(self, version: str) -> None:
        self.lastSuccessfulBuildVersion = version
