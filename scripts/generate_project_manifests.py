# -*- coding: utf-8 -*-
"""从现有 config/<doc>.yml 生成项目清单 ``project.yml``。

任务 2.5：为现有两个文档生成项目清单。

用法::

    python scripts/generate_project_manifests.py

在 ``projects/<docType>/`` 下生成 ``project.yml``，包含从 ``config/<doc>.yml``
提取的文档元数据、标题样式和刷新超时。路径使用项目标准布局
（``template/template.docx``、``content/<docType>/`` 等），待任务 4 的导入
服务将源 DOCX、模板和内容写入后即可直接使用。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))  # scripts/
SCRIPTS = HERE
BASE = os.path.dirname(SCRIPTS)  # doc-automation/
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, BASE)

from docx_common import load_config  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402


def generate(doc_type: str) -> str:
    """从 ``config/<doc_type>.yml`` 生成项目清单，写入 ``projects/<doc_type>/``。"""
    config = load_config(doc_type)
    project_root = os.path.join(BASE, "projects", doc_type)
    paths = ProjectPaths(project_root)
    paths.ensure_directories(doc_type)

    manifest = ProjectManifest(
        documentType=config["documentType"],
        documentNo=config["documentNo"],
        documentName=config["documentName"],
        documentVersion=str(config["documentVersion"]),
        sourceSha256="",
        paths={
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content/{0}".format(doc_type),
            "assetRoot": "assets/{0}".format(doc_type),
            "tableRoot": "assets/{0}/tables".format(doc_type),
        },
        headingStyles=config["headingStyles"],
        bodyStyle=config.get("bodyStyle", ""),
        refreshTimeoutSeconds=int(config.get("refresh", {}).get("timeoutSeconds", 900)),
    )
    manifest_path = manifest.save(project_root, backup=False)
    return manifest_path


def main() -> int:
    for doc_type in ("requirement", "design"):
        path = generate(doc_type)
        print("[{0}] 项目清单已生成: {1}".format(doc_type, path))
    print("\n注意：这些清单使用标准项目布局路径。")
    print("待任务 4 导入服务将源 DOCX、模板和内容写入对应目录后即可用于构建。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
