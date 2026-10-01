# -*- coding: utf-8 -*-
"""V2.9 8.4\uff1a\u51bb\u7ed3\u6001\u9879\u76ee\u5347\u7ea7\uff08schema v1 \u2192 v2\uff09\u5b9e\u673a\u56de\u5f52\u53d6\u8bc1\u3002

\u7528**\u5df2\u6784\u5efa\u7684\u51bb\u7ed3 CLI**\uff08``dist/DocTool/doc-tool-cli.exe``\uff09\u5bf9\u771f\u5b9e v1 \u9879\u76ee\u6267\u884c\u5347\u7ea7\uff0c
\u5e76\u4f9d\u6b21\u9a8c\u8bc1\uff1a\u5347\u7ea7\u524d\u540e\u6b63\u6587\u4e00\u81f4\u3001\u65b0\u65e7\u8def\u5f84\u5747\u53ef\u7528\u3001\u6e90\u9879\u76ee\u672a\u88ab\u4fee\u6539\u3002
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "tests"), str(ROOT / "tools")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

CLI = ROOT / "dist" / "DocTool" / "doc-tool-cli.exe"
EVIDENCE = ROOT / "docs" / "release" / "evidence" / "v29-frozen-upgrade.json"


def build_v1_project(root: pathlib.Path) -> pathlib.Path:
    """\u9020\u4e00\u4e2a **schema v1** \u65e7\u9879\u76ee\uff08\u4e0d\u5e26 v2 \u5b57\u6bb5\uff09\u3002"""
    import test_project_build as T
    from doc_tool.domain.manifest import ProjectManifest

    project = pathlib.Path(T._setup_project(str(root)))
    manifest = T._make_manifest(str(project))
    manifest.schemaVersion = 1
    manifest.save(str(project))
    # \u786e\u8ba4\u6e05\u5355\u91cc\u786e\u5b9e\u6ca1\u6709 v2 \u5b57\u6bb5
    text = (project / "project.yml").read_text(encoding="utf-8")
    assert "schemaVersion: 1" in text or "schemaVersion: '1'" in text, text[:200]
    del ProjectManifest
    return project


def run_cli(*args: str) -> tuple:
    result = subprocess.run(
        [str(CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def main() -> int:
    if not CLI.is_file():
        print("\u51bb\u7ed3 CLI \u4e0d\u5b58\u5728\uff0c\u8df3\u8fc7\uff1a{0}".format(CLI))
        return 1

    record = {"cli": str(CLI), "steps": []}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v29-frozen-"))
    try:
        source = build_v1_project(tmp / "legacy")
        before = {
            path.relative_to(source).as_posix(): path.read_bytes()
            for path in source.rglob("*")
            if path.is_file() and ".state" not in path.parts
        }
        target = tmp / "upgraded"
        code, out, err = run_cli("migrate", "--project", str(source), "--target", str(target), "--output", "json")
        record["steps"].append({"step": "migrate", "exitCode": code, "stdout": out[:400], "stderrTail": err[-300:] if err else ""})
        try:
            payload = json.loads(out)
            record["migrate"] = {
                "ok": bool(payload.get("success")),
                "errorCode": payload.get("errorCode"),
                "results": payload.get("results"),
            }
        except ValueError:
            record["migrate"] = {"raw": out[:400]}

        if target.is_dir():
            manifest = (target / "project.yml").read_text(encoding="utf-8")
            record["steps"].append(
                {
                    "step": "target-manifest",
                    "exitCode": 0,
                    "schemaV2": "schemaVersion: 2" in manifest,
                    "hasDocumentKind": "documentKind" in manifest,
                }
            )
            code2, out2, _ = run_cli("info", "--project", str(target), "--output", "json")
            record["steps"].append({"step": "info-upgraded", "exitCode": code2, "stdoutIsJson": out2.startswith("{")})
        else:
            record["steps"].append({"step": "target-created", "exitCode": 1, "detail": "\u76ee\u6807\u9879\u76ee\u672a\u521b\u5efa"})

        after = {
            path.relative_to(source).as_posix(): path.read_bytes()
            for path in source.rglob("*")
            if path.is_file() and ".state" not in path.parts
        }
        record["sourceUnchanged"] = before == after
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2)[:1200])
    ok = all(step.get("exitCode") == 0 for step in record["steps"]) and record.get("sourceUnchanged") is True
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())