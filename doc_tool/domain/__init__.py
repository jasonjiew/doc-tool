# -*- coding: utf-8 -*-
"""项目领域模型：清单、路径、版本与错误。"""

from __future__ import annotations

from doc_tool.domain.errors import (
    BrokenRelationshipError,
    BuildError,
    CancelledError,
    DocToolError,
    HeadingHierarchyError,
    IncompatibleSchemaError,
    InvalidDocxError,
    MissingHeading1Error,
    NumberingGapError,
    PathEscapeError,
    ProjectLockBusyError,
    ProjectManifestError,
    ResourceNotFoundError,
    TargetProjectExistsError,
    ValidationError,
    WordNotAvailableError,
    WordRefreshTimeoutError,
    WordSaveFailedError,
)
from doc_tool.domain.manifest import (
    DEFAULT_REFRESH_TIMEOUT_SECONDS,
    DOCUMENT_TYPES,
    ProjectManifest,
)
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.version import (
    APP_VERSION,
    PROJECT_SCHEMA_VERSION,
    get_build_info,
    get_commit_id,
)

__all__ = [
    "APP_VERSION",
    "PROJECT_SCHEMA_VERSION",
    "DEFAULT_REFRESH_TIMEOUT_SECONDS",
    "DOCUMENT_TYPES",
    "BrokenRelationshipError",
    "BuildError",
    "CancelledError",
    "DocToolError",
    "HeadingHierarchyError",
    "IncompatibleSchemaError",
    "InvalidDocxError",
    "MissingHeading1Error",
    "NumberingGapError",
    "PathEscapeError",
    "ProjectLockBusyError",
    "ProjectManifest",
    "ProjectManifestError",
    "ProjectPaths",
    "ResourceNotFoundError",
    "TargetProjectExistsError",
    "ValidationError",
    "WordNotAvailableError",
    "WordRefreshTimeoutError",
    "WordSaveFailedError",
    "get_build_info",
    "get_commit_id",
]
