# -*- coding: utf-8 -*-
"""V3.2 7.3 强化：**独立进程**（模拟另一台机器）按包补刷新正式化。

现有证据是“同进程 + 独立目录树”；真实换机还要求不依赖任何进程内状态。本用例把包
放到独立目录，用子进程 `python -m doc_tool.cli delivery-promote --json` 完成补刷新，
并核对退出码、机器报告状态与正式状态（`OutputState`）——即换机等价验证的进程级版本。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery.snapshot_package import build_delivery_package  # noqa: E402
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, SOURCE_MODE_SAVED, ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402
from doc_tool.domain.output_state import is_formal_success  # noqa: E402


def _extract_json(text: str) -> dict:
    """从 CLI 输出里取出 JSON 对象（内核日志可能混在 stdout）。"""
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        pass
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except ValueError:
            return {}
    return {}


def _word_available() -> bool:
    """本机 Word 启动可能 2.6~17.6 s：用更长超时探测，避免把可用 Word 误判为不可用。"""
    try:
        from doc_tool.application.word_check import check_word_available

        return bool(
            check_word_available(dispatch_check=True, dispatch_timeout_seconds=60.0).available
        )
    except Exception:  # noqa: BLE001
        return False


class CrossProcessPromoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 实机项：默认跳过；显式 V32_REAL_WORD=1 时执行（Word COM 在本机可能间歇超时）。
        if os.environ.get("V32_REAL_WORD") != "1":
            raise unittest.SkipTest("换机正式化为实机项：设置 V32_REAL_WORD=1 后执行")
        if not _word_available():
            raise unittest.SkipTest("本机当前没有可用的 Microsoft Word：换机正式化留待实机")
        cls.work = fixtures.scratch_dir("v32-cross-process")
        project = fixtures.two_chapter_project(cls.work / "proj")
        report = run_project_export(
            ExportRequest(
                project_root=str(project), formats=[FORMAT_DOCX],
                source_mode=SOURCE_MODE_SAVED, destination=str(cls.work / "out"),
            ),
            skip_word_refresh=True,
        )
        package = cls.work / "待刷新包.zip"
        outcome = build_delivery_package(report, target=package)
        assert outcome.ok, outcome.message
        # “另一台机器”：独立目录 + 独立用户配置目录（不共享任何进程内/用户级状态）
        cls.machine = cls.work / "另一台机器"
        cls.machine.mkdir(parents=True, exist_ok=True)
        cls.package = cls.machine / package.name
        shutil.copy2(str(package), str(cls.package))
        cls.home = cls.machine / "user-home"
        cls.home.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(getattr(cls, "work", Path(".")))

    def test_child_process_formalizes_package(self):
        env = dict(os.environ)
        # 只隔离工具自身的配置/缓存目录；不改 USERPROFILE/LOCALAPPDATA，
        # 否则 Word COM 拿不到真实用户配置而无法启动（本机实测）。
        env.update({
            "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", "")))),
            "DOC_TOOL_ASSIST_CACHE": str(self.home / "assist-cache"),
            "DOC_TOOL_ASSIST_CONFIG": str(self.home / "assist-config"),
        })
        destination = self.machine / "正式稿"
        proc = subprocess.run(
            [sys.executable, "-m", "doc_tool.cli", "delivery-promote",
             str(self.package), "--destination", str(destination),
             "--word-available", "yes", "--json"],
            cwd=str(self.machine), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
        self.assertEqual(proc.returncode, 0, (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:])
        payload = _extract_json(proc.stdout)
        self.assertTrue(payload, "子进程应输出可解析 JSON：{0}".format((proc.stdout or "")[-500:]))
        status = str(payload.get("status") or (payload.get("formalize") or {}).get("status") or "")
        self.assertIn(status, ("registered", "already-registered"), payload)
        formal_docx = payload.get("docxPath") or (payload.get("formalize") or {}).get("readableDocx") or ""
        self.assertTrue(formal_docx and Path(formal_docx).is_file(), payload)
        self.assertTrue(
            is_formal_success(formal_docx),
            "子进程正式化后，正式状态仍须由既有 OutputState 判定为真",
        )
        registry = destination / "delivery-registry.json"
        self.assertTrue(registry.is_file(), destination)
        data = json.loads(registry.read_text(encoding="utf-8"))
        self.assertTrue(data.get("entries"))

    def test_child_process_is_idempotent_on_second_run(self):
        env = dict(os.environ)
        env.update({"PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", ""))))})
        destination = self.machine / "正式稿二次"
        args = [sys.executable, "-m", "doc_tool.cli", "delivery-promote",
                str(self.package), "--destination", str(destination),
                "--word-available", "yes", "--json"]
        first = subprocess.run(args, cwd=str(self.machine), env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=600)
        second = subprocess.run(args, cwd=str(self.machine), env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=600)
        self.assertEqual(first.returncode, 0, (first.stderr or "")[-400:])
        self.assertEqual(second.returncode, 0, (second.stderr or "")[-400:])
        payload = _extract_json(second.stdout)
        self.assertTrue(payload, "子进程应输出可解析 JSON：{0}".format((second.stdout or "")[-500:]))
        status = str(payload.get("status") or (payload.get("formalize") or {}).get("status") or "")
        self.assertEqual(status, "already-registered", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
