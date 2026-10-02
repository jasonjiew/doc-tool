# -*- coding: utf-8 -*-
"""汇总全量回归 JUnit 结果（失败文件与用例、计数）。"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def summarize(xml_path) -> dict:
    path = Path(xml_path)
    if not path.is_file():
        return {"ok": False, "message": "JUnit 文件不存在：{0}".format(path)}
    tree = ET.parse(path)
    suites = list(tree.getroot().iter("testsuite"))
    tests = failures = errors = 0
    failed_cases = []
    for suite in suites:
        tests += int(suite.get("tests", 0) or 0)
        failures += int(suite.get("failures", 0) or 0)
        errors += int(suite.get("errors", 0) or 0)
        for case in suite.iter("testcase"):
            node = case.find("failure")
            kind = "failure"
            if node is None:
                node = case.find("error")
                kind = "error"
            if node is not None:
                failed_cases.append({
                    "kind": kind,
                    "name": case.get("name", ""),
                    "message": (node.get("message") or "")[:160],
                })
    return {
        "ok": True,
        "files": len(suites),
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "failedCases": failed_cases,
    }


def main() -> int:
    import json

    xml = sys.argv[1] if len(sys.argv) > 1 else str(REPO_ROOT / "test-results-full-v3-r23.xml")
    payload = summarize(xml)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())