# -*- coding: utf-8 -*-
"""V3.2 4.5 / 7.3 实机：交付包真实 Word 补刷新正式化（含等效独立目录的换机场景）。

本用例需要本机 Microsoft Word；无 Word 环境自动跳过并保留兜底结论（可读稿待刷新）。
覆盖：包内原快照正式化 → 正式状态只由既有 OutputState 判定 → 登记写入；
      等价换机（独立目录副本）后仍可正式化；重复正式化幂等；源项目未被改写。
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.delivery.snapshot_package import (  # noqa: E402
    REGISTRY_NAME, build_delivery_package, formalize_package,
)
from doc_tool.application.intake_contract import (  # noqa: E402
    FORMAT_DOCX, FORMAT_HTML, SOURCE_MODE_SAVED, ExportRequest,
)
from doc_tool.application.project_export import run_project_export  # noqa: E402
from doc_tool.domain.output_state import is_formal_success  # noqa: E402


def _word_available() -> bool:
    try:
        from doc_tool.application.word_check import check_word_available

        return bool(check_word_available(dispatch_check=True).available)
    except Exception:  # noqa: BLE001 - 探测失败按不可用处理
        return False


def _tree_state(root: Path) -> dict:
    from doc_tool.application.intake_contract import sha256_file

    state = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            state[path.relative_to(root).as_posix()] = sha256_file(path)
    return state


class RealWordFormalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 实机项：默认跳过，显式开启 V32_REAL_WORD=1 才驱动真实 Word。
        # 原因：本机 Word COM 启动超时不稳定（间歇 10 s 超时→被判不可用），
        # 在默认套件里会拖慢并误报；该项按约定单列实机待验收。
        import os as _os

        if _os.environ.get("V32_REAL_WORD") != "1":
            raise unittest.SkipTest("真实 Word 正式化为实机项：设置 V32_REAL_WORD=1 后执行")
        if not _word_available():
            raise unittest.SkipTest("本机没有可用的 Microsoft Word：真实正式化留待实机验收")
        cls.work = fixtures.scratch_dir("v32-real-word")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        cls.report = run_project_export(
            ExportRequest(
                project_root=str(cls.project), formats=[FORMAT_DOCX, FORMAT_HTML],
                source_mode=SOURCE_MODE_SAVED, destination=str(cls.work / "out"),
            ),
            skip_word_refresh=True,  # 先在“无 Word”语义下得到可读包（待刷新）
        )
        cls.package = cls.work / "delivery.zip"
        outcome = build_delivery_package(cls.report, target=cls.package)
        assert outcome.ok, outcome.message

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(getattr(cls, "work", Path(".")))

    def test_formalize_package_with_real_word_registers_once(self):
        before = _tree_state(self.project)
        destination = self.work / "formalized"
        outcome = formalize_package(self.package, destination=destination)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertIn(outcome.status, ("registered", "already-registered"), outcome.status)
        self.assertTrue(outcome.readableDocx and Path(outcome.readableDocx).is_file())
        self.assertTrue(
            is_formal_success(outcome.readableDocx),
            "正式状态必须由既有 OutputState 判定为正式成功",
        )
        # 正式稿可打开且包含正文
        with zipfile.ZipFile(outcome.readableDocx) as archive:
            document = archive.read("word/document.xml").decode("utf-8", errors="replace")
        self.assertIn("架构正文", document)
        # 登记写入，且原包仍在
        registry = destination / REGISTRY_NAME
        self.assertTrue(registry.is_file(), outcome.summary_lines())
        data = json.loads(registry.read_text(encoding="utf-8"))
        self.assertTrue(data.get("entries"))
        self.assertTrue(self.package.is_file())
        # 源项目未被改写
        self.assertEqual(_tree_state(self.project), before)

    def test_independent_directory_equivalent_machine(self):
        """等效换机：把包复制到另一棵独立目录树后仍可正式化。"""
        other = self.work / "另一台机器"
        other.mkdir(parents=True, exist_ok=True)
        package_copy = other / "delivery.zip"
        shutil.copy2(str(self.package), str(package_copy))
        outcome = formalize_package(package_copy, destination=other / "formalized")
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(Path(outcome.readableDocx).is_file())
        self.assertTrue(is_formal_success(outcome.readableDocx), outcome.summary_lines())
        self.assertNotEqual(Path(outcome.readableDocx).parent, self.package.parent)

    def test_second_formalize_is_idempotent(self):
        destination = self.work / "formalized-idem"
        first = formalize_package(self.package, destination=destination)
        self.assertTrue(first.ok, first.message)
        second = formalize_package(self.package, destination=destination)
        self.assertTrue(second.ok, second.message)
        self.assertEqual(second.status, "already-registered", second.status)
        self.assertEqual(second.registeredPath, first.registeredPath)
        registry = destination / REGISTRY_NAME
        data = json.loads(registry.read_text(encoding="utf-8"))
        keys = [str(item.get("key") or "") for item in data.get("entries") or []]
        self.assertEqual(len(keys), len(set(keys)), "重复正式化不得重复登记")


if __name__ == "__main__":
    unittest.main(verbosity=2)