# -*- coding: utf-8 -*-
"""诊断：模板 DOCX 里的修订记录表能否被识别与回填。

用法：python scripts/diagnostics/diag_revision_table.py <项目路径> [<项目路径> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from doc_tool.adapters.kernel import ensure_kernel_importable  # noqa: E402

ensure_kernel_importable()

from docx_common import parse_xml_safe, read_docx_package  # noqa: E402
from extract_revision_record import (  # noqa: E402
    _cell_text,
    extract_revision_rows,
    find_revision_table,
    qn,
)

from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402


def dump(docx_path: Path, label: str) -> None:
    print("=" * 70)
    print("{0}: {1}".format(label, docx_path))
    if not docx_path.is_file():
        print("  !! 文件不存在")
        return
    with read_docx_package(str(docx_path)) as package:
        items = package.read_all()
    root = parse_xml_safe(items.get("word/document.xml", b""), "word/document.xml")
    body = root.find(qn("body"))
    tables = list(body.iter(qn("tbl"))) if body is not None else []
    print("  正文表格数: {0}".format(len(tables)))
    picked = find_revision_table(root)
    for index, tbl in enumerate(tables[:8]):
        rows = tbl.findall(qn("tr"))
        mark = "  <== find_revision_table 命中" if picked is not None and tbl is picked else ""
        print("  [表 {0}] 行数={1}{2}".format(index, len(rows), mark))
        for row_index, row in enumerate(rows[:3]):
            cells = [_cell_text(cell) for cell in row.findall(qn("tc"))]
            print("      行{0}: {1}".format(row_index, cells))
    if picked is None:
        print("  ** find_revision_table 未命中任何表 **")
    else:
        extracted = extract_revision_rows(str(docx_path))
        print("  extract_revision_rows 提取数据行: {0}".format(len(extracted)))
        if extracted:
            print("    首行: {0}".format(extracted[0]))
            print("    末行: {0}".format(extracted[-1]))


def main(argv) -> int:
    for project in argv:
        root = Path(project).resolve()
        manifest = ProjectManifest.load(root)
        paths = ProjectPaths(root)
        print()
        print("#" * 70)
        print("# 项目: {0}".format(root.name))
        print("# documentType={0} documentVersion={1}".format(
            manifest.documentType, manifest.documentVersion))
        dump(paths.resolve(manifest.relative_template_docx()), "模板")
        output_dir = paths.output_dir
        docs = sorted(output_dir.glob("*.docx")) if output_dir.is_dir() else []
        print("  output/ 下 docx: {0}".format([d.name for d in docs]))
        for doc in docs:
            dump(doc, "产物")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
