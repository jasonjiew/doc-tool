# -*- coding: utf-8 -*-
"""\u4ea4\u4ed8\u94fe\u8def\u7aef\u5230\u7aef\u8bc1\u636e\uff1a\u4ece\u89c4\u8303\u5305\u5efa\u9879 \u2192 check / trace / impact \u5b9e\u8dd1\u3002

\u7528**\u771f\u5b9e\u670d\u52a1\u4e0e\u771f\u5b9e CLI**\uff08\u65e0 mock\uff09\u8dd1\u901a\u4ea4\u4ed8\u94fe\u8def\uff0c\u8bc1\u660e
\u300c\u5efa\u9879\u670d\u52a1\u5c42 + \u4e09\u4e2a CLI \u5165\u53e3\u300d\u5728\u5f53\u524d\u4ee3\u7801\u4e0a\u53ef\u7528\u3002
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

EVIDENCE = ROOT / "docs" / "release" / "evidence"
NL = chr(10)


def main() -> int:
    from doc_tool.application.project_from_pack import create_project_from_pack
    from doc_tool.cli import main as cli_main

    record = {"appVersion": "", "steps": []}
    from doc_tool.domain.version import APP_VERSION, PROJECT_SCHEMA_VERSION

    record["appVersion"] = APP_VERSION
    record["projectSchemaVersion"] = PROJECT_SCHEMA_VERSION

    work = pathlib.Path(tempfile.mkdtemp(prefix="v29-e2e-"))
    try:
        project = work / "requirement"
        result = create_project_from_pack(
            ROOT / "standards" / "generic-requirement",
            project,
            document_name="\u7aef\u5230\u7aef\u6837\u672c",
            document_no="GX-E2E-001",
        )
        record["steps"].append(
            {
                "step": "\u4ece\u89c4\u8303\u5305\u5efa\u9879",
                "ok": bool(result.ok),
                "chapters": len(result.chapters),
                "warnings": list(result.warnings),
                "errors": list(result.errors),
            }
        )
        if not result.ok:
            raise SystemExit("\u5efa\u9879\u5931\u8d25\uff1a{0}".format(result.errors))

        # \u4e3a\u53ef\u8ffd\u6eaf\u573a\u666f\u51c6\u5907\uff1a\u7ed9\u7b2c\u4e00\u7ae0\u52a0\u4e00\u6761\u9700\u6c42\u6761\u76ee\u4e0e\u4e00\u6761\u5173\u7cfb
        content_root = project / "content"
        chapters = sorted(content_root.glob("*.md"))
        if chapters:
            first = chapters[0]
            text = first.read_text(encoding="utf-8")
            from doc_tool.application.content.traceable_items import ItemRef

            ref = ItemRef("GX-E2E-REQ", "req-e2e-0001", "requirement")
            first.write_text(text.rstrip() + NL + NL + "\u7cfb\u7edf\u5e94\u652f\u6301\u7aef\u5230\u7aef\u6837\u672c\u3002 " + ref.render() + NL, encoding="utf-8")

        for command in (
            ["check", "--project", str(project), "--output", "json"],
            ["trace", "--project", str(project), "--format", "json"],
            ["impact", "--project", str(project), "--item", "GX-E2E-REQ/req-e2e-0001", "--format", "json"],
        ):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli_main(command)
            payload = None
            try:
                payload = json.loads(out.getvalue())
            except ValueError:
                payload = None
            record["steps"].append(
                {
                    "step": " ".join(command[:1]),
                    "exitCode": code,
                    "stdoutIsJson": payload is not None,
                    "stderr": err.getvalue().strip()[:200],
                    "summary": _summarise(command[0], payload),
                }
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    target = EVIDENCE / "v29-e2e-chain.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\u5df2\u751f\u6210", target)
    for step in record["steps"]:
        print("  ", step["step"], step.get("exitCode", step.get("ok")), step.get("summary", ""))
    ok = all(
        (step.get("exitCode") in (0, 1)) if "exitCode" in step else step.get("ok")
        for step in record["steps"]
    )
    return 0 if ok else 1


def _summarise(command: str, payload):
    if not isinstance(payload, dict):
        return ""
    if command == "trace":
        return "design={0} test={1}".format(payload.get("designCoverage"), payload.get("testCoverage"))
    if command == "impact":
        return "changed={0} affected={1}".format(len(payload.get("changed", [])), len(payload.get("affected", [])))
    if command == "check":
        return "status={0} issues={1}".format(payload.get("status"), len(payload.get("issues", [])))
    return ""


if __name__ == "__main__":
    raise SystemExit(main())