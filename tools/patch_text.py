# -*- coding: utf-8 -*-
"""精确文本替换辅助（供本地批量修改使用，非产品代码）。

用法：
    python tools/patch_text.py <file> <old-file> <new-file> [--count N]

以 ``old-file`` 的完整内容作为待替换文本、``new-file`` 的完整内容作为替换
文本，在 ``file`` 中做替换；默认要求唯一匹配，匹配次数不符时退出码 2 并
报告实际次数，避免误改。自动适配 CRLF/LF 行尾并保留原文件的行尾风格。
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv):
    args = [item for item in argv[1:] if not item.startswith("--")]
    expected = 1
    for item in argv[1:]:
        if item.startswith("--count="):
            expected = int(item.split("=", 1)[1])
    if len(args) != 3:
        print(__doc__)
        return 2
    target = Path(args[0])
    old = Path(args[1]).read_text(encoding="utf-8")
    new = Path(args[2]).read_text(encoding="utf-8")
    raw = target.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8-sig")
    old = old.replace("\r\n", "\n")
    new = new.replace("\r\n", "\n")
    text = text.replace("\r\n", "\n")
    count = text.count(old)
    if count != expected:
        print("匹配次数={0}（期望 {1}），未修改".format(count, expected))
        return 2
    updated = text.replace(old, new)
    if crlf:
        updated = updated.replace("\n", "\r\n")
    target.write_bytes(updated.encode("utf-8"))
    print("已修改 {0}".format(target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))