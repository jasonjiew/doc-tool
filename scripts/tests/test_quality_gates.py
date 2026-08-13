# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.tests.fixture_factory import temporary_project
from scripts.tests.run_tests import write_junit


def _load_script(name):
    path = Path(__file__).resolve().parents[2] / "packaging" / name
    spec = importlib.util.spec_from_file_location("doc_tool_gate_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QualityGateTests(unittest.TestCase):
    def test_fixture_is_isolated_complete_and_cleaned(self):
        with temporary_project() as first:
            self.assertTrue((first / "project.yml").is_file())
            self.assertTrue((first / "template" / "template.docx").is_file())
            self.assertTrue(any((first / "content" / "requirement").rglob("*.md")))
            saved = first
            with temporary_project() as second:
                self.assertNotEqual(first, second)
        self.assertFalse(saved.exists())

    def test_junit_writer_is_parseable_and_contains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test-results.xml"
            write_junit(path, [{"name": "x.py", "code": 1, "duration": 0.1, "output": "boom"}])
            root = ET.parse(path).getroot()
            self.assertEqual(root.attrib["failures"], "1")
            self.assertEqual(root.find("./testsuite/testcase/failure").text, "boom")

    def test_sbom_formats_are_parseable_and_cover_both_dependency_files(self):
        generate = _load_script("generate_sbom.py").generate
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.txt"
            build = root / "build.txt"
            runtime.write_text("PyYAML==6.0.3\n", encoding="utf-8")
            build.write_text("coverage==7.10.2\n", encoding="utf-8")
            cyclone_path, spdx_path = root / "bom.json", root / "spdx.json"
            generate([runtime, build], cyclone_path, spdx_path)
            cyclone = json.loads(cyclone_path.read_text(encoding="utf-8"))
            spdx = json.loads(spdx_path.read_text(encoding="utf-8"))
            self.assertEqual({c["name"] for c in cyclone["components"]}, {"PyYAML", "coverage"})
            self.assertEqual(spdx["spdxVersion"], "SPDX-2.3")

    def test_audit_wrapper_propagates_scanner_exit_and_writes_report(self):
        run = _load_script("audit_dependencies.py").run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_audit.py"
            fake.write_text(
                "import pathlib,sys\np=pathlib.Path(sys.argv[sys.argv.index('--output')+1]); p.write_text('[]')\nraise SystemExit(1)\n",
                encoding="utf-8",
            )
            report = root / "audit.json"
            code = run("requirements.txt", str(report), executable=[sys.executable, str(fake)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
