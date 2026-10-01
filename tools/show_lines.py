# -*- coding: utf-8 -*-
"""读取并显示文本文件中的指定行区间（本地辅助脚本）。"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv):
    if len(argv) < 3:
        print("usage: show_lines.py <file> <start> [end]")
        return 2
    path = Path(argv[1])
    start = int(argv[2])
    end = int(argv[3]) if len(argv) > 3 else start
    lines = path.read_text(encoding="utf-8-sig").split("\n")
    for number in range(start, min(end, len(lines)) + 1):
        print("{0:5d}|{1}".format(number, lines[number - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))