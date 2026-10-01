# -*- coding: utf-8 -*-
"""检查 patch 步骤在目标文件中的匹配次数（本地辅助工具）。"""

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
    steps = Path(argv[1])
    text_cache = {}
    for line in steps.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        target = ROOT / fields[0]
        if target not in text_cache:
            text_cache[target] = target.read_text(encoding="utf-8-sig")
        old = read_chunk(ROOT / fields[1])
        count = text_cache[target].count(old)
        print("{0}\t{1}\told={2}\tcount={3}".format(fields[0], fields[1], len(old), count))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))