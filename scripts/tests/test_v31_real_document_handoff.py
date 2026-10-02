# -*- coding: utf-8 -*-
"""V3.1 6.3 代理试点：用**真实文档**在两棵独立目录树间做作者/评审人交接并记录耗时。

真实团队环境不可得，因此按任务备注“未提供团队环境时单列待验收继续实现”，
把可自动化的部分做实：真实文档内容、两棵独立树（仓库之外，天然无 Git）、
作者改稿 → 导出交接包 → 评审人本地改一章 → 应用（冲突保留、其余应用成功）、
重复导入幂等，并记录各阶段耗时供人工试点对照。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application.content.team_flow import run_team_flow  # noqa: E402
from doc_tool.application.effective_snapshot import discover_chapters  # noqa: E402

REAL_DOCS = (
    REPO_ROOT / "docs" / "product-flow-fallback-policy.md",
    REPO_ROOT / "docs" / "product-v31-usage.md",
)


def _chapter_text(source: Path, title: str, extra: str) -> str:
    body = source.read_text(encoding="utf-8", errors="replace")
    demoted = "\n".join("#" + line if line.startswith("#") else line for line in body.splitlines())
    return "{0}\n\n{1}\n\n{2}\n".format(title, demoted, extra)


class RealDocumentHandoffTests(unittest.TestCase):
    """真实文档 + 两独立目录树（无 Git）的作者/评审人交接试点。"""

    @classmethod
    def setUpClass(cls):
        # 仓库之外的临时目录：天然无 Git，模拟两台机器上的两份工作副本
        cls.root = Path(tempfile.mkdtemp(prefix="doc-tool-team-pilot-"))
        cls.author = fixtures.two_chapter_project(cls.root / "作者工作副本")
        cls.reviewer = cls.root / "评审人工作副本"
        shutil.copytree(str(cls.author), str(cls.reviewer))
        cls.chapters = [rel for rel, _path in discover_chapters(cls.author / "content" / "general")]
        assert len(cls.chapters) >= 2, cls.chapters
        cls.measurements = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.root), ignore_errors=True)

    def _write_chapter(self, project: Path, rel: str, text: str) -> None:
        target = project / "content" / "general" / rel
        target.write_text(text, encoding="utf-8")

    def _read_chapter(self, project: Path, rel: str) -> str:
        return (project / "content" / "general" / rel).read_text(encoding="utf-8")

    def test_real_document_handoff_and_conflict_records(self):
        from doc_tool.application.content.chapter_history import ChapterHistoryService
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.paths import ProjectPaths

        first, second = self.chapters[0], self.chapters[1]
        baseline = {rel: self._read_chapter(self.author, rel) for rel in (first, second)}

        # 作者侧：把两章替换为真实文档正文（模拟真实改稿）
        self._write_chapter(
            self.author, first, _chapter_text(REAL_DOCS[0], "## " + Path(first).stem, "作者补充：兜底顺序为占位→保留原件→可读 DOCX。"),
        )
        self._write_chapter(
            self.author, second, _chapter_text(REAL_DOCS[1], "## " + Path(second).stem, "作者补充：交接为本地文件导出，不自动推送。"),
        )

        # 无 Git 复核（真实团队里常见：共享盘/临时目录）
        manifest = ProjectManifest.load(self.author)
        paths = ProjectPaths(self.author)
        service = ChapterHistoryService(
            self.author, paths.resolve(manifest.relative_content_root()), paths.state_dir,
        )
        self.assertIsNone(service.git_root(), "作者侧应位于 Git 仓库之外")

        started = time.perf_counter()
        exported = run_team_flow(
            self.author, chapters=[first, second],
            handoff_dir=self.root / "交接包", baseline_texts=baseline,
        )
        self.measurements["exportSeconds"] = round(time.perf_counter() - started, 3)
        self.assertTrue(exported.artifacts, exported.summary_lines())
        self.assertFalse(exported.gitAvailable)
        self.measurements["artifacts"] = [str(item) for item in exported.artifacts]

        # 评审人侧：本地改第一章（真实评审意见），第二章保持基准
        self._write_chapter(
            self.reviewer, first, _chapter_text(REAL_DOCS[0], "## " + Path(first).stem, "评审人本地批注：本节需补充回退阈值。"),
        )
        self._write_chapter(self.reviewer, second, baseline[second])

        started = time.perf_counter()
        applied = run_team_flow(self.reviewer, package=exported.artifacts[0])
        self.measurements["applySeconds"] = round(time.perf_counter() - started, 3)
        self.assertFalse(applied.blocked, applied.summary_lines())
        self.assertTrue(any("已应用" in item for item in applied.processed), applied.to_dict())
        self.assertTrue(applied.conflicts or applied.skipped, applied.to_dict())
        self.measurements["processed"] = list(applied.processed)
        self.measurements["conflicts"] = list(applied.conflicts or [])

        # 冲突章保留评审人本地内容；其余章应用作者内容
        self.assertIn("评审人本地批注", self._read_chapter(self.reviewer, first))
        self.assertIn("作者补充：交接为本地文件导出", self._read_chapter(self.reviewer, second))

        # 重复导入幂等
        started = time.perf_counter()
        again = run_team_flow(self.reviewer, package=exported.artifacts[0])
        self.measurements["reapplySeconds"] = round(time.perf_counter() - started, 3)
        self.assertFalse(again.blocked)
        self.assertIn("作者补充：交接为本地文件导出", self._read_chapter(self.reviewer, second))

        print("HANDOFF_JSON:" + json.dumps(self.measurements, ensure_ascii=False, default=str))
        for key in ("exportSeconds", "applySeconds", "reapplySeconds"):
            self.assertLess(self.measurements[key], 30.0, key)


if __name__ == "__main__":
    unittest.main(verbosity=2)