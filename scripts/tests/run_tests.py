# -*- coding: utf-8 -*-
"""自定义测试运行器：隔离运行测试文件并生成 JUnit/coverage 产物。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DEFAULT_TESTS = [
    "test_docx_common.py", "test_ooxml_security.py", "test_validator_negative.py",
    "test_iteration_scenarios.py", "test_project_model.py", "test_import_preflight.py",
    "test_fidelity.py", "test_project_build.py", "test_import_project.py",
    "test_roundtrip.py", "test_style_mapping.py", "test_authoring_services.py",
    "test_issues.py", "test_cli_machine.py", "test_quality_gates.py", "test_quality_traceability.py",
    "test_gui_services.py", "test_content_operations.py", "test_safety_recovery.py",
    "test_lock_log_cancel.py", "test_word_release.py", "test_packaging.py",
    "test_installer.py", "test_brand_consistency.py",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", default=str(ROOT / "test-results.xml"))
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--coverage-min", type=float, default=0.0)
    parser.add_argument("--coverage-xml", default=str(ROOT / "coverage.xml"))
    parser.add_argument("--coverage-json", default=str(ROOT / "coverage.json"))
    parser.add_argument("tests", nargs="*")
    return parser.parse_args()


def run_one(name: str, coverage: bool) -> dict:
    print("\n== {0} ==".format(name), flush=True)
    command = [sys.executable]
    if coverage:
        command.extend(["-m", "coverage", "run", "--parallel-mode", "--source=doc_tool,scripts"])
    command.append(str(HERE / name))
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", check=False,
    )
    duration = time.monotonic() - started
    print(completed.stdout, end="", flush=True)
    return {"name": name, "code": completed.returncode, "duration": duration, "output": completed.stdout}


def write_junit(path: Path, results: list[dict]) -> None:
    suite = ET.Element("testsuite", {
        "name": "doc-tool", "tests": str(len(results)),
        "failures": str(sum(1 for result in results if result["code"] != 0)),
        "time": "{0:.3f}".format(sum(result["duration"] for result in results)),
    })
    for result in results:
        case = ET.SubElement(suite, "testcase", {
            "name": result["name"], "classname": "scripts.tests",
            "time": "{0:.3f}".format(result["duration"]),
        })
        if result["code"] != 0:
            failure = ET.SubElement(case, "failure", {
                "message": "exit code {0}".format(result["code"]), "type": "TestFailure",
            })
            failure.text = result["output"][-12000:]
        output = ET.SubElement(case, "system-out")
        output.text = result["output"][-12000:]
    root = ET.Element("testsuites", {
        "tests": suite.attrib["tests"], "failures": suite.attrib["failures"],
        "time": suite.attrib["time"],
    })
    root.append(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def finish_coverage(args) -> int:
    subprocess.run([sys.executable, "-m", "coverage", "combine"], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, "-m", "coverage", "xml", "-o", args.coverage_xml], cwd=str(ROOT), check=True)
    subprocess.run([sys.executable, "-m", "coverage", "json", "-o", args.coverage_json], cwd=str(ROOT), check=True)
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "report", "--fail-under", str(args.coverage_min)],
        cwd=str(ROOT), check=False,
    )
    return report.returncode


def main() -> int:
    args = parse_args()
    tests = args.tests or DEFAULT_TESTS
    results = [run_one(name, args.coverage) for name in tests]
    write_junit(Path(args.junit), results)
    test_code = 1 if any(result["code"] != 0 for result in results) else 0
    coverage_code = finish_coverage(args) if args.coverage else 0
    return test_code or coverage_code


if __name__ == "__main__":
    sys.exit(main())
