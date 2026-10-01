# -*- coding: utf-8 -*-
"""按 patch 文件对目标源码做精确替换（本地一次性补丁工具，非产品代码）。

用法：python tools/apply_patch.py <steps 文件>

steps 文件每行（制表符分隔）：

    <目标文件>\t<old 文件>\t<new 文件>[\t<期望匹配次数>]

old/new 文件中，独立成行的 ``<<<SEP>>>`` 用于分隔多个片段，片段按顺序用
空行拼接。先校验全部步骤的匹配次数，再统一写盘；任何一步不匹配即整体失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEPARATOR = "\n<<<SEP>>>\n"


def read_chunk(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if SEPARATOR in text:
        return "".join(part.strip("\n") + "\n" for part in text.split(SEPARATOR))
    return text


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    steps = Path(argv[1])
    if not steps.is_absolute():
        steps = ROOT / steps
    plan = []
    for line in steps.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            print("步骤格式错误: {0}".format(line))
            return 2
        expected = int(fields[3]) if len(fields) > 3 else 1
        plan.append((ROOT / fields[0], read_chunk(ROOT / fields[1]), read_chunk(ROOT / fields[2]), expected))

    texts = {}
    for target, old, new, expected in plan:
        if target not in texts:
            texts[target] = target.read_text(encoding="utf-8-sig")
        count = texts[target].count(old)
        if count != expected:
            print("{0}: 匹配次数={1}（期望 {2}）".format(target, count, expected))
            return 2

    for target, old, new, expected in plan:
        texts[target] = texts[target].replace(old, new)
    for target in sorted(set(item[0] for item in plan), key=str):
        raw = target.read_bytes()
        crlf = b"\r\n" in raw
        text = texts[target]
        if crlf:
            text = text.replace("\n", "\r\n")
        target.write_bytes(text.encode("utf-8"))
        print("已修改 {0}".format(target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))