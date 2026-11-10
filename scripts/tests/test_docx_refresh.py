# -*- coding: utf-8 -*-
"""导出稿就地刷新目录/页码的服务层：缺失文件与 supervise 透传。"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.docx_refresh import (  # noqa: E402
    REASON_MISSING,
    refresh_docx_fields,
)


class DocxRefreshTests(unittest.TestCase):
    def test_missing_file_is_rejected_without_starting_word(self) -> None:
        ok, reason = refresh_docx_fields(str(Path(tempfile.gettempdir()) / "no-such.docx"))
        self.assertFalse(ok)
        self.assertEqual(reason, REASON_MISSING)

    def test_delegates_to_supervise_with_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            target.write_bytes(b"PK\x03\x04")

            calls = {}
            fake = types.ModuleType("refresh_fields")

            def supervise(*, output_path, timeout):
                calls["path"] = output_path
                calls["timeout"] = timeout
                return True, "ok"

            fake.supervise = supervise
            with mock.patch.dict(sys.modules, {"refresh_fields": fake}):
                ok, reason = refresh_docx_fields(target, timeout=42)

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(calls["timeout"], 42)
        self.assertEqual(calls["path"], str(target))

    def test_failure_reason_is_passed_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            target.write_bytes(b"PK\x03\x04")
            fake = types.ModuleType("refresh_fields")
            fake.supervise = lambda *, output_path, timeout: (False, "timeout")
            with mock.patch.dict(sys.modules, {"refresh_fields": fake}):
                ok, reason = refresh_docx_fields(target, timeout=5)
        self.assertFalse(ok)
        self.assertEqual(reason, "timeout")


if __name__ == "__main__":
    unittest.main()
