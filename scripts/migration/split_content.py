# -*- coding: utf-8 -*-
"""Phase 10: 将「大章节 Markdown」重新拆分为「章节目录树」（薄壳）。

用法:
    python scripts/migration/split_content.py [requirement|design|all]

拆分规则(以原 Word 标题层级为最终依据):
    一级标题  -> 文件夹           第N章 标题/
    二级标题  -> 有三级子节点则文件夹, 否则独立 MD   N.M 标题/ 或 N.M 标题.md
    三级标题  -> 独立 MD          N.M.K 标题.md
    四级及以上-> 保留在所属三级(或二级) MD 内(标题行原样)

任务 4.3：实际逻辑已重构为 ``split_into_tree`` 纯函数（接收指定输入/输出目录，
不删除正式项目内容），本脚本仅作为旧 CLI 入口的兼容薄壳。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTENT_ROOT = os.path.join(BASE, "content")

sys.path.insert(0, BASE)
from doc_tool.adapters.importer import split_into_tree  # noqa: E402


def split_one(doc_type):
    src_dir = os.path.join(CONTENT_ROOT, doc_type)
    if not os.path.isdir(src_dir):
        print("WARN: 目录不存在:", src_dir)
        return
    stats = split_into_tree(src_dir)
    if stats.dirs == 0 and stats.mds == 0 and stats.indexes == 0:
        print("[%s] 顶层没有大章节 MD(可能已拆分为目录树), 跳过" % doc_type)
        return
    print("[%s] 目录树重建完成: 文件夹=%d, Markdown=%d, _index=%d"
          % (doc_type, stats.dirs, stats.mds, stats.indexes))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    types = ["requirement", "design"] if arg == "all" else [arg]
    for t in types:
        split_one(t)
    print("完成。后续使用 build_docx.py 从目录树生成 Word。")


if __name__ == "__main__":
    main()
