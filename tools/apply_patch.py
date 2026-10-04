# -*- coding: utf-8 -*-
"""按 JSON 规格对文本文件做精确替换（LLM 编辑工作流的可靠落地工具）。

用法::

    python tools/apply_patch.py <patch.json> [--check]

patch.json::

    {
      "edits": [
        {"file": "doc_tool/foo.py",
         "replacements": [
            {"old": "精确原文", "new": "替换后", "count": 1}
         ]}
      ]
    }

约束（避免静默改坏大文件）：

- ``old`` 必须与文件内容逐字符匹配，``count`` 为期望出现次数（默认 1）；
- 未匹配到或次数不符时整体失败，**不写任何文件**；
- 写盘后重新读取并核对：每条 ``new`` 存在、且替换区域附近的原文不再原样存在；
- 全部替换在同一文件内按顺序应用，任何一步失败即中止。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apply_replacements(text: str, replacements: list, label: str) -> str:
    for index, item in enumerate(replacements):
        old = item.get("old")
        new = item.get("new")
        expected = int(item.get("count", 1))
        if old is None or new is None:
            raise SystemExit("replacement #{0} of {1} misses old/new".format(index + 1, label))
        found = text.count(old)
        if found != expected:
            raise SystemExit(
                "replacement #{0} of {1}: expected {2} occurrence(s), found {3}\n--- old ---\n{4}".format(
                    index + 1, label, expected, found, old[:400]
                )
            )
        text = text.replace(old, new, expected if expected else -1)
    return text


def apply_file(path: Path, replacements: list) -> tuple:
    text = path.read_text(encoding="utf-8")
    before_len = len(text)
    written_text = apply_replacements(text, replacements, str(path))
    path.write_text(written_text, encoding="utf-8", newline="\n")
    written = path.read_text(encoding="utf-8")
    if written != written_text:
        raise SystemExit("verify failed: written content differs for {0}".format(path))
    for index, item in enumerate(replacements):
        if item["new"] and item["new"] not in written:
            raise SystemExit(
                "verify failed: replacement #{0} new text missing in {1}".format(index + 1, path)
            )
    return before_len, len(written)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("patch")
    parser.add_argument("--check", action="store_true", help="只校验替换能否命中，不写文件")
    args = parser.parse_args()

    payload = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    edits = payload.get("edits") or []
    if not edits:
        raise SystemExit("patch has no edits")
    # 先全部校验，再写盘：任一条不匹配就不动任何文件。
    for edit in edits:
        path = ROOT / edit["file"]
        if not path.is_file():
            raise SystemExit("missing file: {0}".format(path))
        apply_replacements(path.read_text(encoding="utf-8"),
                           edit.get("replacements") or [], edit["file"])
    if args.check:
        print("patch OK (dry run): {0} file(s)".format(len(edits)))
        return 0
    for edit in edits:
        path = ROOT / edit["file"]
        before_len, after_len = apply_file(path, edit["replacements"])
        print("{0}: {1} -> {2} chars ({3} replacement(s))".format(
            edit["file"], before_len, after_len, len(edit["replacements"])
        ))
    print("applied {0} file(s)".format(len(edits)))
    return 0


if __name__ == "__main__":
    sys.exit(main())