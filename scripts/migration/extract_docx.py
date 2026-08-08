# -*- coding: utf-8 -*-
"""Phase 3/4/5: 拆分 Word -> Markdown + 图片 + 复杂表格（薄壳）。

用法:
    python scripts/migration/extract_docx.py requirement
    python scripts/migration/extract_docx.py design

任务 4.2：实际逻辑已重构为 ``extract_content`` 无全局副作用纯函数（接收源 DOCX
与暂存工作区目录，不依赖固定文件名），本脚本仅作为旧 CLI 入口的兼容薄壳。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.dirname(BASE)

DOCS = {
    "requirement": {
        "src": "KF-2090-1-001 康尚健康云软件需求说明书(3.8).docx",
        "type": "requirement",
    },
    "design": {
        "src": "KF-2090-1-006 康尚健康云系统详细设计说明书(2.5).docx",
        "type": "design",
    },
}

sys.path.insert(0, BASE)
from doc_tool.adapters.importer import extract_content  # noqa: E402


def extract(key):
    cfg = DOCS[key]
    src = os.path.join(SRC_DIR, cfg["src"])
    if not os.path.exists(src):
        print("MISSING:", src)
        return False

    content_dir = os.path.join(BASE, "content", key)
    images_dir = os.path.join(BASE, "assets", key, "images")
    tables_dir = os.path.join(BASE, "assets", key, "tables")
    os.makedirs(content_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)
    # 清理旧文件（仅本类型目录），保持与旧入口行为一致
    for d in (content_dir, images_dir, tables_dir):
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                os.remove(p)

    result = extract_content(src, content_dir, images_dir, tables_dir, key)
    print("=" * 50)
    print("[%s] 章节数: %d" % (key, result.chapter_count))
    print("[%s] 图片: %d" % (key, result.image_count))
    print("[%s] 表格: %d (简单=%d 复杂=%d)" % (
        key, result.table_count, result.simple_table_count, result.complex_table_count))
    return True


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "requirement"
    extract(arg)
