# -*- coding: utf-8 -*-
"""V2.8 9.2 \u9a8c\u6536\u8bc1\u636e\uff1a\u4e09\u7c7b\u89c4\u8303\u5305 + \u65e7 v1 \u9879\u76ee\u8dd1\u300c\u5efa\u9879\u2192\u7f16\u8f91\u2192\u68c0\u67e5\u2192\u8bc4\u5ba1\u2192\u4ea4\u4ed8\u300d\u3002

\u5b9e\u9645\u6267\u884c\u771f\u5b9e\u670d\u52a1\uff08\u4e0d\u7528 mock\uff09\uff1a\u89c4\u8303\u5305\u9a8c\u8bc1\u4e0e\u56fa\u5b9a\u3001schema \u8fc1\u79fb\u9884\u89c8/\u5e94\u7528\u3001
\u7ae0\u8282\u987a\u5e8f\u89e3\u6790\u3001\u53d8\u91cf\u89e3\u6790\uff08\u542b\u574f\u914d\u7f6e\u4e0e\u7f3a\u53d8\u91cf\uff09\u3001\u8bc4\u5ba1\u95e8\u7981\u9ed8\u8ba4\u4e0e\u4e25\u683c\u3001\u8bca\u65ad\u6784\u5efa\u4e0e\u7ec8\u5ba1\u3002
Word \u4eba\u5de5\u7248\u5f0f\u4e0e\u56e2\u961f\u8bd5\u70b9\u4f9d\u8d56\u5b9e\u673a\u6761\u4ef6\uff0c\u5982\u5b9e\u6807\u8bb0\u4e3a\u5f85\u9a8c\u6536\u3002
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

NL = chr(10)
EVIDENCE = ROOT / "docs" / "release" / "evidence"
PACKS = ROOT / "standards"


def _chapter_text(title: str, variables: dict) -> str:
    lines = [
        "## {0}".format(title),
        "",
        "| \u9879 | \u5185\u5bb9 |",
        "| --- | --- |",
        "| \u4ea7\u54c1 | {{{{productName}}}} |",
        "| \u7248\u672c | {{{{docVersion}}}} |",
        "",
        "\u672c\u7ae0\u8bf4\u660e\u3002",
        "",
    ]
    del variables
    return NL.join(lines)


def main() -> int:
    from doc_tool.application.chapter_order import resolve_chapter_order, resolve_variables
    from doc_tool.application.migrate_schema_v2 import migrate_project
    from doc_tool.application.quality_location import load_terms_with_fallback
    from doc_tool.application.review.review_store import ReviewStore
    from doc_tool.application.review.versioned_review import ReviewGatePolicy
    from doc_tool.application.standard_pack import (
        install_pack,
        load_project_pack,
        pack_fingerprint,
        validate_pack_dir,
    )
    from doc_tool.domain.manifest import ProjectManifest

    record = {"appVersion": "2.8.0", "packs": [], "legacyV1": {}, "notes": []}
    root = Path(tempfile.mkdtemp(prefix="v28-accept-"))
    try:
        for name in ("generic-requirement", "generic-design", "generic-test"):
            pack_dir = PACKS / name
            validation = validate_pack_dir(pack_dir)
            entry = {
                "pack": name,
                "valid": validation.ok,
                "errors": validation.errors,
                "warnings": validation.warnings,
            }
            project = root / name
            (project / "content").mkdir(parents=True)
            (project / "assets" / "tables").mkdir(parents=True)
            (project / "template").mkdir(parents=True)
            target, install = install_pack(pack_dir, project)
            entry["installed"] = bool(target)
            entry["installErrors"] = install.errors
            if target:
                (project / "template" / "template.docx").write_bytes(
                    (target / "template.docx").read_bytes()
                    if (target / "template.docx").is_file()
                    else b"PK\x03\x04placeholder"
                )
                manifest = ProjectManifest(
                    documentType="general",
                    documentNo="GX-V28-{0}".format(name[-4:].upper()),
                    documentName="{0} \u9a8c\u6536".format(name),
                    documentVersion="1.0",
                    sourceSha256="",
                    schemaVersion=2,
                    paths={
                        "templateDocx": "template/template.docx",
                        "contentRoot": "content",
                        "assetRoot": "assets",
                        "tableRoot": "assets/tables",
                    },
                    headingStyles={1: "1", 2: "2", 3: "3"},
                    bodyStyle="a",
                    standardPack={
                        "id": name,
                        "version": "1.0.0",
                        "hash": pack_fingerprint(validation.pack),
                    },
                    chapters=["1 \u6982\u8ff0.md", "2 \u8bbe\u8ba1.md"],
                )
                manifest.save(str(project))
                loaded_pack, warnings = load_project_pack(
                    project, manifest.standardPack
                )
                entry["reloaded"] = loaded_pack is not None
                entry["reloadWarnings"] = warnings

                # \u7ae0\u8282\u987a\u5e8f\uff1a\u58f0\u660e\u4f18\u5148 + \u672a\u5217\u5165\u8ffd\u52a0
                (project / "content" / "1 \u6982\u8ff0.md").write_text(
                    _chapter_text("1 \u6982\u8ff0", manifest.variables), encoding="utf-8"
                )
                (project / "content" / "2 \u8bbe\u8ba1.md").write_text(
                    _chapter_text("2 \u8bbe\u8ba1", manifest.variables), encoding="utf-8"
                )
                (project / "content" / "3 \u9644\u5f55.md").write_text(
                    _chapter_text("3 \u9644\u5f55", manifest.variables), encoding="utf-8"
                )
                order = resolve_chapter_order(
                    ["1 \u6982\u8ff0.md", "2 \u8bbe\u8ba1.md", "3 \u9644\u5f55.md"], manifest.chapters
                )
                entry["chapterOrder"] = order.ordered
                entry["unlisted"] = order.unlisted

                # \u53d8\u91cf\uff1a\u5df2\u5b9a\u4e49 + \u672a\u5b9a\u4e49\u53ef\u8bfb\u5360\u4f4d
                resolution = resolve_variables(
                    "\u4ea7\u54c1 {{{{productName}}}}\uff0c\u8d1f\u8d23\u4eba {{{{owner}}}}",
                    manifest.variables,
                )
                entry["variableText"] = resolution.text
                entry["undefinedVariables"] = resolution.undefined

                # \u8bc4\u5ba1\u95e8\u7981\uff1a\u9ed8\u8ba4\u5e26\u63d0\u9192\u3001\u4e25\u683c\u62e6\u622a
                store = ReviewStore(project / ".state")
                store.add_comment("\u9700\u786e\u8ba4", "reviewer", "content/1 \u6982\u8ff0.md", 3)
                default_allowed, default_reasons = ReviewGatePolicy(strict=False).evaluate(store)
                strict_allowed, _ = ReviewGatePolicy(strict=True).evaluate(store)
                entry["reviewGate"] = {
                    "defaultAllowed": default_allowed,
                    "defaultReasons": default_reasons,
                    "strictAllowed": strict_allowed,
                }

                # \u574f\u914d\u7f6e\u4e0e\u672f\u8bed\u56de\u9000
                quality = project / "quality"
                quality.mkdir(parents=True, exist_ok=True)
                (quality / "terms.json").write_text("{ broken", encoding="utf-8")
                terms, term_warnings = load_terms_with_fallback(project)
                entry["termsFallback"] = {"terms": terms, "warnings": term_warnings}

                # \u8bca\u65ad\u6784\u5efa\u4e0e\u7ec8\u5ba1
                try:
                    from doc_tool.application.check import run_check

                    report = run_check(project, fail_on="error", strict=False, build=True)
                    entry["checkStatus"] = report.status
                    entry["checkExitCode"] = report.exit_code
                    entry["checkStages"] = [
                        {"stage": stage.stage, "status": stage.status} for stage in report.stages
                    ]
                except Exception as exc:  # noqa: BLE001 - \u5982\u5b9e\u8bb0\u5f55\u5931\u8d25\u539f\u56e0
                    entry["checkError"] = str(exc)

                # v1 \u2192 v2 \u8fc1\u79fb\u9884\u89c8\u4e0e\u5e94\u7528
                migrated = ProjectManifest.load(str(project))
                migrated.schemaVersion = 1
                migrated.save(str(project))
                preview = migrate_project(project, apply=False)
                applied = migrate_project(project, apply=True)
                entry["migration"] = {
                    "fromSchema": preview.from_schema,
                    "toSchema": preview.to_schema,
                    "applied": applied.success,
                    "backup": bool(applied.backup_path),
                    "finalSchema": ProjectManifest.load(str(project)).schemaVersion,
                }
            record["packs"].append(entry)

        # \u65e7 v1 \u9879\u76ee\u4e0d\u5347\u7ea7\u4e5f\u5fc5\u987b\u53ef\u8bfb\u53ef\u5199
        legacy = root / "legacy-v1"
        (legacy / "content").mkdir(parents=True)
        legacy_manifest = ProjectManifest(
            documentType="general",
            documentNo="GX-V28-LEG",
            documentName="\u65e7 v1 \u9879\u76ee",
            documentVersion="1.0",
            sourceSha256="",
            schemaVersion=1,
            paths={"contentRoot": "content"},
            headingStyles={1: "1"},
            bodyStyle="a",
        )
        legacy_manifest.save(str(legacy))
        reloaded = ProjectManifest.load(str(legacy))
        record["legacyV1"] = {
            "schemaVersion": reloaded.schemaVersion,
            "writable": reloaded.is_writable(),
            "chaptersDeclared": bool(reloaded.chapters),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    target = EVIDENCE / "v28-team-samples.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\u5df2\u751f\u6210", target)
    for entry in record["packs"]:
        print(
            "  {0}: valid={1} installed={2} reloaded={3} check={4} migration={5}".format(
                entry["pack"],
                entry.get("valid"),
                entry.get("installed"),
                entry.get("reloaded"),
                entry.get("checkStatus"),
                entry.get("migration", {}).get("finalSchema"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())