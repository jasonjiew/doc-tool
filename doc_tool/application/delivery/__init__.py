# -*- coding: utf-8 -*-
"""V3.2 批量交付服务层（32-B/32-C/32-D/32-E）。

三个服务模块共用同一批持久事实：

- :mod:`doc_tool.application.delivery.queue`：用户级持久批次队列（schema 1），
  串行调用既有统一出稿服务，支持去重、取消、中断继续与只重试未完成项。
- :mod:`doc_tool.application.delivery.snapshot_package`：自足快照交付包
  （schema 1）与换机补刷新/正式化，包内一律相对路径。
- :mod:`doc_tool.application.delivery.result_index`：结果索引视图与选择归档。

正式状态只由 :mod:`doc_tool.domain.output_state` 判定；本包不重新定义「正式成功」，
也不提升任何格式/文档的正式级别。
"""

from __future__ import annotations

from doc_tool.application.delivery.queue import (
    STORE_NAME,
    STORE_SCHEMA_VERSION,
    BatchJob,
    DeliveryQueue,
    EnqueueResult,
)
from doc_tool.application.delivery.result_index import (
    ARCHIVE_MANIFEST_NAME,
    ArchiveOutcome,
    ResultEntry,
    ResultIndex,
    archive_selection,
    build_result_index,
)
from doc_tool.application.delivery.snapshot_package import (
    PACKAGE_KIND,
    PACKAGE_MANIFEST_NAME,
    PACKAGE_SCHEMA_VERSION,
    FormalizeOutcome,
    PackageOutcome,
    build_delivery_package,
    formalize_package,
    read_delivery_package,
    verify_delivery_package,
)

__all__ = [
    "STORE_NAME", "STORE_SCHEMA_VERSION", "BatchJob", "DeliveryQueue", "EnqueueResult",
    "PACKAGE_KIND", "PACKAGE_MANIFEST_NAME", "PACKAGE_SCHEMA_VERSION",
    "PackageOutcome", "FormalizeOutcome", "build_delivery_package",
    "read_delivery_package", "verify_delivery_package", "formalize_package",
    "ARCHIVE_MANIFEST_NAME", "ArchiveOutcome", "ResultEntry", "ResultIndex",
    "build_result_index", "archive_selection",
]