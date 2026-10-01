# -*- coding: utf-8 -*-
"""把文本文件中的 \\uXXXX 转义解码为真实字符（本地辅助工具，非产品代码）。

用法：python tools/decode_escapes.py <file> [...]

就地重写：保留原有换行风格与结尾换行，仅解码 \\uXXXX / \\UXXXXXXXX 转义。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")


def decode(text: str) -> str:
    def replace(match):
        code = match.group(1) or match.group(2)
        return chr(int(code, 16))

    return _ESCAPE_RE.sub(replace, text)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    for name in argv[1:]:
        path = Path(name)
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        trailing = raw.endswith(b"\n")
        text = raw.decode("utf-8")
        text = text.replace("\r\n", "\n")
        decoded = decode(text)
        if crlf:
            decoded = decoded.replace("\n", "\r\n")
        path.write_bytes(decoded.encode("utf-8"))
        print("已解码 {0}".format(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))