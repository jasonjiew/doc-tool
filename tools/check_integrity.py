# -*- coding: utf-8 -*-
"""\u4ea7\u54c1\u5b8c\u6574\u6027\u68c0\u67e5\uff08\u6700\u7ec8\u4ea4\u4ed8\u524d\u53ef\u91cd\u590d\u6267\u884c\uff09\u3002

\u4f9d\u6b21\u68c0\u67e5\uff1a
1. ``doc_tool`` / ``scripts`` / ``packaging`` / ``tools`` \u4e0b\u6240\u6709 ``.py`` \u7684 BOM \u4e0e\u8bed\u6cd5\uff1b
2. \u6d4b\u8bd5\u6e05\u5355\u5b8c\u6574\u6027\uff08\u78c1\u76d8\u4e0a\u7684 ``test_*.py`` \u5168\u90e8\u5df2\u767b\u8bb0\uff09\uff1b
3. \u5173\u952e\u670d\u52a1\u6a21\u5757\u53ef\u5bfc\u5165\uff1b
4. \u7248\u672c\u6e90\u4e0e schema \u4e00\u81f4\u6027\uff1b
5. \u9694\u79bb\u7684\u635f\u574f\u4ea7\u7269\u6e05\u5355\uff08\u4f9b\u8ffd\u6eaf\uff09\u3002

\u9000\u51fa\u7801\uff1a0 = \u5168\u90e8\u901a\u8fc7\uff1b1 = \u6709\u95ee\u9898\uff08\u9010\u6761\u5217\u51fa\uff09\u3002
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KEY_MODULES = (
    "doc_tool.application.settings",
    "doc_tool.application.chapter_order",
    "doc_tool.application.check",
    "doc_tool.application.collection",
    "doc_tool.application.collection_ops",
    "doc_tool.application.intake_word",
    "doc_tool.application.migrate_schema_v2",
    "doc_tool.application.overview",
    "doc_tool.application.prepared_source",
    "doc_tool.application.project_from_markdown",
    "doc_tool.application.project_from_pack",
    "doc_tool.application.quality_gates",
    "doc_tool.application.quality_location",
    "doc_tool.application.standard_pack",
    "doc_tool.application.workspace",
    "doc_tool.application.content.chapter_reorder",
    "doc_tool.application.content.impact",
    "doc_tool.application.content.item_actions",
    "doc_tool.application.content.reimport_plan",
    "doc_tool.application.content.reimport_preview",
    "doc_tool.application.content.relations",
    "doc_tool.application.content.trace_matrix",
    "doc_tool.application.content.traceable_items",
    "doc_tool.application.export.review_package",
    "doc_tool.application.review.versioned_review",
    "doc_tool.domain.blocks",
    "doc_tool.domain.captions",
)


def check_syntax() -> list:
    problems = []
    for name in ("doc_tool", "scripts", "packaging", "tools"):
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                source = path.read_bytes()
            except OSError as exc:
                problems.append("{0}: \u8bfb\u53d6\u5931\u8d25 {1}".format(path, exc))
                continue
            if source.startswith(b"\xef\xbb\xbf"):
                problems.append("{0}: \u5e26 BOM".format(path))
                continue
            try:
                ast.parse(source.decode("utf-8"))
            except SyntaxError as exc:
                problems.append("{0}: \u8bed\u6cd5\u9519\u8bef\u7b2c {1} \u884c {2}".format(path, exc.lineno, exc.msg))
            except UnicodeDecodeError:
                problems.append("{0}: \u7f16\u7801\u65e0\u6cd5\u89e3\u6790".format(path))
    return problems


def check_suite_registration() -> list:
    runner = ROOT / "scripts" / "tests" / "run_tests.py"
    text = runner.read_text(encoding="utf-8")
    listed = set(re.findall(r'"([a-z0-9_]+[.]py)"', text))
    on_disk = {path.name for path in (ROOT / "scripts" / "tests").glob("test_*.py")}
    problems = []
    for name in sorted(on_disk - listed):
        problems.append("\u672a\u767b\u8bb0\u7684\u6d4b\u8bd5\u5957\u4ef6\uff1a{0}".format(name))
    for name in sorted(listed - on_disk):
        problems.append("\u6e05\u5355\u4e2d\u4e0d\u5b58\u5728\u7684\u5957\u4ef6\uff1a{0}".format(name))
    return problems


def check_imports() -> list:
    problems = []
    for name in KEY_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - \u5b8c\u6574\u6027\u68c0\u67e5\u9700\u8981\u5982\u5b9e\u62a5\u544a
            problems.append("{0}: \u5bfc\u5165\u5931\u8d25 {1}".format(name, exc))
    return problems


def check_version() -> list:
    from doc_tool.domain.version import APP_VERSION, PROJECT_SCHEMA_VERSION

    problems = []
    if not APP_VERSION.startswith("2.9."):
        problems.append("\u7248\u672c\u6e90\u4e0d\u662f 2.9.x\uff1a{0}".format(APP_VERSION))
    if int(PROJECT_SCHEMA_VERSION) != 2:
        problems.append("schema \u7248\u672c\u4e0d\u662f 2\uff1a{0}".format(PROJECT_SCHEMA_VERSION))
    return problems


def main() -> int:
    sections = (
        ("\u8bed\u6cd5\u4e0e\u7f16\u7801", check_syntax()),
        ("\u6d4b\u8bd5\u6e05\u5355", check_suite_registration()),
        ("\u5173\u952e\u6a21\u5757\u5bfc\u5165", check_imports()),
        ("\u7248\u672c\u6e90", check_version()),
    )
    failed = False
    for title, problems in sections:
        status = "\u901a\u8fc7" if not problems else "\u53d1\u73b0 {0} \u9879".format(len(problems))
        print("[{0}] {1}".format(title, status))
        for item in problems:
            print("   -", item)
        failed = failed or bool(problems)
    quarantined = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tools").glob("*.broken"))
    print("[\u9694\u79bb\u4ea7\u7269] {0}".format("\u3001".join(quarantined) if quarantined else "\u65e0"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())