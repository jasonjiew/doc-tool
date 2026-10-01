# -*- coding: utf-8 -*-
"""V2.7 27-F：构建前 Lint 阶段与无 Word/取消的安全收尾（6.2、6.5 部分）。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_project_build as T  # noqa: E402

NL = chr(10)


class PrebuildLintStageTests(unittest.TestCase):
    """构建前 Lint 与 CLI/GUI 同源，且不阻断出稿。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v27-lint-stage-")
        self.project_root = T._setup_project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lint_stage_runs_and_does_not_block(self):
        from doc_tool.application.pipeline import STAGE_LINT, run_pipeline

        manifest = T._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        # 写入一个会被 lint 捕获的占位正文。
        chapter = next(paths.content_root.rglob("*.md"))
        chapter.write_text(
            chapter.read_text(encoding="utf-8") + NL + "TODO：待补充" + NL,
            encoding="utf-8",
        )
        result = run_pipeline(manifest, paths, skip_word_refresh=True)
        stage_map = {event.stage: event.status for event in result.events}
        self.assertIn(STAGE_LINT, stage_map, "构建前检查阶段应出现在事件里")
        self.assertEqual(stage_map[STAGE_LINT], "succeeded")
        self.assertTrue(result.success, "默认策略下 lint 发现不得阻断出稿")

    def test_diagnostic_state_marked_for_pending_refresh(self):
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.output_state import read_state

        manifest = T._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        result = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertTrue(result.success)
        state = read_state(result.output_path)
        self.assertIsNotNone(state)
        self.assertTrue(state.diagnostic, "诊断构建必须标记为非正式")
        self.assertFalse(state.formal)


class RefreshFailureTests(unittest.TestCase):
    """刷新失败与取消都不得产生正式产物。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v27-refresh-")
        self.project_root = T._setup_project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refresh_failure_keeps_previous_output(self):
        from unittest import mock

        from doc_tool.application.pipeline import run_pipeline

        manifest = T._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        # 先做一次诊断构建，得到一份可打开产物。
        first = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertTrue(first.success)
        before = Path(first.output_path).read_bytes()

        with mock.patch(
            "doc_tool.adapters.kernel.refresh_with_project",
            return_value=(False, "word_unavailable"),
        ):
            second = run_pipeline(manifest, paths, skip_word_refresh=False)
        self.assertFalse(second.success)
        self.assertEqual(second.error_code, "E3001")
        # 已有正式/诊断产物必须原样保留。
        self.assertEqual(Path(first.output_path).read_bytes(), before)

    def test_cancelled_pipeline_leaves_no_output(self):
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.cancellation import CancellationToken

        manifest = T._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        token = CancellationToken()
        token.request_cancel()
        result = run_pipeline(
            manifest, paths, skip_word_refresh=True, cancel_token=token
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E5003")
        self.assertIsNone(result.pending_output_path)
        pending_dir = paths.output_dir / "待刷新"
        self.assertFalse(pending_dir.exists(), "取消不得留下副本目录")


if __name__ == "__main__":
    unittest.main()