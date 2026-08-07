# -*- coding: utf-8 -*-
"""
Phase 10: 将「大章节 Markdown」重新拆分为「章节目录树」(优化2.md 第二阶段结构重构)
用法:
    python scripts/migration/split_content.py [requirement|design|all]

拆分规则(以原 Word 标题层级为最终依据):
    一级标题  -> 文件夹           第N章 标题/
    二级标题  -> 有三级子节点则文件夹, 否则独立 MD   N.M 标题/ 或 N.M 标题.md
    三级标题  -> 独立 MD          N.M.K 标题.md
    四级及以上-> 保留在所属三级(或二级) MD 内(标题行原样保留)

文件名特殊字符(Windows 不允许 / : * ? " < > |)替换为全角, build_docx.py 生成标题时还原。

正文/图片/表格/复杂表格引用等所有内容逐行迁移, 不丢失、不改变顺序。
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTENT_ROOT = os.path.join(BASE, "content")

# Windows 非法文件名字符 -> 全角替代(可逆, build 时还原为标题文本)
BAD_CHAR_MAP = {
    "/": "\uff0f",   # ／
    ":": "\uff1a",   # ：
    "*": "\uff0a",   # ＊
    "?": "\uff1f",   # ？
    '"': "\u201d",   # "
    "<": "\uff1c",   # ＜
    ">": "\uff1e",   # ＞
    "|": "\uff5c",   # ｜
    "\\": "\uff3c",  # ＼
}


def sanitize(name):
    """文件名特殊字符替换为全角"""
    return "".join(BAD_CHAR_MAP.get(c, c) for c in name)


class Node(object):
    """章节树节点"""

    def __init__(self, depth, title, line_idx):
        self.depth = depth          # 标题层级(1=一级)
        self.title = title          # 标题文本(不含编号)
        self.line_idx = line_idx    # 源文件行号(0-based)
        self.content = []           # 直接内容行(含 depth>=4 的内容标题行)
        self.children = []          # 子节点(depth 递增)
        self.num = []               # 章节编号, 如 [3, 1, 10]

    def is_dir(self):
        """一级标题恒为文件夹; 二级有子节点为文件夹; 三级恒为 MD"""
        if self.depth == 1:
            return True
        if self.depth == 2:
            return len(self.children) > 0
        return False

    def display_name(self):
        """文件夹/文件名(带编号, 不含扩展名)"""
        if self.depth == 1:
            return "第{0}章 {1}".format(self.num[0], self.title)
        return ".".join(str(x) for x in self.num) + " " + self.title

    def full_name(self):
        return sanitize(self.display_name())


def parse_file(path):
    """解析大章节 MD -> 根节点列表(每个一级标题一个节点)"""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    roots = []
    stack = []  # Node 栈, stack[0] 为一级
    for idx, raw in enumerate(lines):
        s = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            depth = len(m.group(1))
            title = m.group(2).strip()
            if depth <= 3:
                node = Node(depth, title, idx)
                while stack and depth <= stack[-1].depth:
                    stack.pop()
                if stack:
                    stack[-1].children.append(node)
                else:
                    roots.append(node)
                stack.append(node)
            else:
                # 四级及以上标题保留在所属 MD 内(原样输出)
                if stack:
                    stack[-1].content.append(raw)
        else:
            if stack:
                stack[-1].content.append(raw)
            elif s and roots:
                # 文件最顶部(一级标题之前)的内容, 挂到第一个一级节点
                roots[0].content.append(raw)
            elif s and not roots:
                print("WARN: 无任何标题, 内容被忽略:", raw[:40])
    return roots


def assign_numbers(roots, chapter_start=0):
    """DFS 分配章节编号; 一级编号从 chapter_start 之后累计(跨大章节文件连续编号)"""
    def walk(nodes, parent_num):
        for j, n in enumerate(nodes, start=1):
            n.num = parent_num + [j]
            walk(n.children, n.num)

    for i, r in enumerate(roots, start=1):
        r.num = [chapter_start + i]
        walk(r.children, r.num)


def first_md_leaf(node):
    """沿第一个子节点下钻, 找到第一个 MD 叶子节点(用于承接文件夹直接内容)"""
    if not node.is_dir():
        return node
    if not node.children:
        return None
    return first_md_leaf(node.children[0])


def emit(node, out_dir, stats):
    """输出节点: 文件夹递归, MD 写文件"""
    name = node.full_name()
    node_path = os.path.join(out_dir, name)
    if node.is_dir():
        os.makedirs(node_path, exist_ok=True)
        stats["dirs"] += 1
        # 文件夹直接内容属于父标题自身，必须放入 _index.md，不能并入
        # 第一个子章节，否则 Word 中的业务上下文会发生错位。
        body = list(node.content)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if body:
            with open(os.path.join(node_path, "_index.md"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(body) + "\n")
            stats["indexes"] += 1
        for c in node.children:
            emit(c, node_path, stats)
    else:
        md_path = node_path + ".md"
        body = node.content
        # 去掉首尾空行(空行是结构分隔, build 会跳过)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
            if body:
                fh.write("\n".join(body) + "\n")
        stats["mds"] += 1


def split_one(doc_type):
    src_dir = os.path.join(CONTENT_ROOT, doc_type)
    if not os.path.isdir(src_dir):
        print("WARN: 目录不存在:", src_dir)
        return
    md_files = sorted(f for f in os.listdir(src_dir) if f.endswith(".md"))
    if not md_files:
        print("[%s] 顶层没有大章节 MD(可能已拆分为目录树), 跳过" % doc_type)
        return
    stats = {"dirs": 0, "mds": 0, "indexes": 0}
    chapter_count = 0
    for f in md_files:
        roots = parse_file(os.path.join(src_dir, f))
        assign_numbers(roots, chapter_count)
        for r in roots:
            emit(r, src_dir, stats)
        chapter_count += len(roots)
    # 删除旧的大章节 MD(内容已迁移进目录树)
    for f in md_files:
        os.remove(os.path.join(src_dir, f))
    print(
        "[%s] 目录树重建完成: 文件夹=%d, Markdown=%d, _index=%d"
        % (doc_type, stats["dirs"], stats["mds"], stats["indexes"])
    )


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    types = ["requirement", "design"] if arg == "all" else [arg]
    for t in types:
        split_one(t)
    print("完成。后续使用 build_docx.py 从目录树生成 Word。")


if __name__ == "__main__":
    main()
