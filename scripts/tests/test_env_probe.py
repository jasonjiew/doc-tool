# -*- coding: utf-8 -*-
"""环境自检补测：写拒绝、密文读取、目标已存在、CLI 退出码。"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


class EnvProbeTests(unittest.TestCase):
    def setUp(self):
        self.work = fixtures.scratch_dir("env-probe")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_healthy_directory_and_docx(self):
        from doc_tool.application.env_probe import diagnose_environment

        docx = fixtures.build_docx(self.work / "ok.docx", [("h1", "第1章"), ("p", "正文")])
        result = diagnose_environment(directory=self.work, docx=docx)
        self.assertTrue(result.ok, result.to_dict())
        kinds = {item["kind"] for item in result.checks}
        self.assertEqual(kinds, {"write", "docx-read"})

    def test_write_denied_is_reported_with_advice(self):
        from doc_tool.application.env_probe import ADVICE_WRITE_DENIED, probe_write

        with patch("tempfile.mkstemp", side_effect=PermissionError(13, "Permission denied")):
            result = probe_write(self.work)
        self.assertFalse(result.ok)
        self.assertEqual(result.checks[-1]["kind"], "write")
        self.assertIn("PermissionError", result.checks[-1]["detail"])
        self.assertIn(ADVICE_WRITE_DENIED, result.advice)

    def test_ciphertext_docx_is_detected(self):
        """密文（非 ZIP 签名）必须被识别为环境问题。

        用受控的文件对象模拟：本机加密客户端会让真实文件写入后立刻读回失败
        （PermissionError），那是另一条被覆盖的路径。
        """
        import io

        from doc_tool.application.env_probe import ADVICE_READ_ENCRYPTED, probe_docx_read

        encrypted = self.work / "cipher.docx"
        encrypted.write_bytes(b"PK\x03\x04placeholder")
        cipher = b"\xe0\xa8\x91\xe7\xd8\xf2\x05\xac\x00\x02\x00\x00\x00\x10\x00\x00"
        with patch("pathlib.Path.open", return_value=io.BytesIO(cipher)):
            result = probe_docx_read(encrypted)
        self.assertFalse(result.ok)
        self.assertIn("疑似被透明加密", result.checks[-1]["detail"])
        self.assertIn(ADVICE_READ_ENCRYPTED, result.advice)

    def test_unreadable_docx_is_reported_as_environment_issue(self):
        from doc_tool.application.env_probe import ADVICE_READ_ENCRYPTED, probe_docx_read

        target = self.work / "blocked.docx"
        target.write_bytes(b"PK\x03\x04x")
        with patch("pathlib.Path.open", side_effect=PermissionError(13, "Permission denied")):
            result = probe_docx_read(target)
        self.assertFalse(result.ok)
        self.assertIn("PermissionError", result.checks[-1]["detail"])
        self.assertIn(ADVICE_READ_ENCRYPTED, result.advice)

    def test_existing_target_is_reported(self):
        from doc_tool.application.env_probe import ADVICE_TARGET_EXISTS, diagnose_environment

        target = self.work / "已有项目"
        target.mkdir(parents=True, exist_ok=True)
        result = diagnose_environment(directory=self.work, target_exists=target)
        self.assertFalse(result.ok)
        self.assertIn(ADVICE_TARGET_EXISTS, result.advice)


class CiphertextDocxMessageTests(unittest.TestCase):
    """密文 docx 的错误信息必须带环境建议（不是“请重新另存 docx”）。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("env-probe-msg")

    def tearDown(self):
        fixtures.cleanup(self.work)

    def test_ciphertext_docx_error_carries_environment_advice(self):
        import io

        from doc_tool.application.env_probe import ADVICE_READ_ENCRYPTED
        from doc_tool.domain.ooxml import OOXMLSecurityError, read_docx_package

        cipher = self.work / "cipher.docx"
        cipher.write_bytes(b"PK\x03\x04placeholder")
        payload = b"\xe0\xa8\x91\xe7\xd8\xf2\x05\xac\x00\x02\x00\x00\x00\x10\x00\x00"
        # ooxml 用内建 open 读头部，探测用 Path.open：两处都要看到密文
        with patch("builtins.open", return_value=io.BytesIO(payload)), patch(
            "pathlib.Path.open", return_value=io.BytesIO(payload)
        ), patch("zipfile.ZipFile", side_effect=__import__("zipfile").BadZipFile("bad")):
            with self.assertRaises(OOXMLSecurityError) as ctx:
                read_docx_package(cipher)
        message = str(ctx.exception)
        self.assertIn("ZIP", message)
        self.assertIn(ADVICE_READ_ENCRYPTED, message)


class EnvCheckCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = fixtures.scratch_dir("env-check-cli")

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "doc_tool.cli", *args],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )

    def test_env_check_healthy_exit_zero(self):
        docx = fixtures.build_docx(self.work / "ok.docx", [("h1", "第1章")])
        proc = self._cli("env-check", "--json", "--dir", str(self.work), "--docx", str(docx))
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["checks"]), 2)

    def test_env_check_reports_encrypted_docx_with_exit_three(self):
        cipher = self.work / "cipher.docx"
        cipher.write_bytes(b"\xe0\xa8\x91\xe7\xd8\xf2\x05\xac")
        proc = self._cli("env-check", "--json", "--dir", str(self.work), "--docx", str(cipher))
        self.assertEqual(proc.returncode, 3, proc.stdout[-300:])
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["advice"])

    def test_env_check_reports_existing_target(self):
        target = self.work / "已有"
        target.mkdir(parents=True, exist_ok=True)
        proc = self._cli("env-check", "--json", "--dir", str(self.work), "--target", str(target))
        self.assertEqual(proc.returncode, 3, proc.stdout[-300:])
        payload = json.loads(proc.stdout)
        self.assertTrue(any("已存在" in item["detail"] for item in payload["checks"]))

    def test_import_failure_carries_environment_advice(self):
        """受限环境下导入失败要带上可执行建议（不只是“联系支持”）。"""
        from doc_tool.application.import_project import ImportRequest, import_first_time

        docx = fixtures.build_docx(self.work / "ok2.docx", [("h1", "第1章")])
        request = ImportRequest(
            source_docx=docx, target_project_root=self.work / "out" / "P",
            document_type="general", document_no="", document_name="P", document_version="1.0",
        )
        from doc_tool.application.env_probe import ADVICE_WRITE_DENIED, EnvProbeResult

        failing = EnvProbeResult()
        failing.add("write", False, "PermissionError: Permission denied", ADVICE_WRITE_DENIED)
        with patch(
            "doc_tool.application.import_project.preflight",
            side_effect=PermissionError(13, "Permission denied"),
        ), patch(
            "doc_tool.application.env_probe.diagnose_environment", return_value=failing,
        ):
            result = import_first_time(request)
        self.assertFalse(result.success)
        self.assertTrue(
            any("信任" in item or "写入" in item for item in result.warnings),
            result.warnings,
        )
        self.assertEqual(
            result.suggested_action, ADVICE_WRITE_DENIED,
            "环境自检建议应优先于笼统的“联系支持”",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)