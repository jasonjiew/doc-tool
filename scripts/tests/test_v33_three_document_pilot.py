# -*- coding: utf-8 -*-
"""V3.3 6.2 三类真实文档自动化试点：定位耗时、建议采纳/撤销、摘要候选与增强基线。

真实文档取自本仓库（项目说明 / 兜底策略 / 使用指南）三份，逐份驱动同一套辅助服务：
  - `search_evidence`：资料定位耗时（含命中数）
  - `suggest`：确定性建议（规则/术语/引用/复核/变更事实）
  - `adopt` / `undo`：采纳与一次撤销（内容前后对比）
  - `revision_summary_texts`：修订摘要候选（人工摘要修改的输入）
  - `provider_status`：可选模型状态（默认增强未执行，作为基线）

输出一行 JSON（`PILOT_JSON:` 前缀），便于写入台账；人工质量评价与真实文档类型
（方案/报告/说明书）仍需人工试点确认，故本文件只作自动化证据。
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402

REAL_DOCUMENTS = (
    ("项目说明", REPO_ROOT / "README.md", ("交付", "项目")),
    ("兜底策略", REPO_ROOT / "docs" / "product-flow-fallback-policy.md", ("兜底", "失败")),
    ("使用指南", REPO_ROOT / "docs" / "product-v31-usage.md", ("交接", "命令")),
)


def _demote(text: str) -> str:
    """把真实文档的标题整体降一级，作为章节正文嵌入（保持结构合法）。"""
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            lines.append("#" + line)
        else:
            lines.append(line)
    return "\n".join(lines)


class ThreeDocumentPilotTests(unittest.TestCase):
    """三类真实文档的辅助能力试点（自动化部分）。"""

    @classmethod
    def setUpClass(cls):
        from doc_tool.application.assist.service import build_assistant
        from doc_tool.application.effective_snapshot import discover_chapters
        from doc_tool.application.content import reuse_commands as reuse

        cls.work = fixtures.scratch_dir("v33-pilot")
        cls.project = fixtures.two_chapter_project(cls.work / "proj")
        content = cls.project / "content" / "general"
        cls.chapters = [rel for rel, _path in discover_chapters(content)]
        assert len(cls.chapters) >= 2, cls.chapters

        # 三份真实文档：覆盖前两章，并新增一章承载第三份
        cls.records = []
        for index, (label, source, terms) in enumerate(REAL_DOCUMENTS):
            text = source.read_text(encoding="utf-8", errors="replace")
            if index < len(cls.chapters):
                target = content / cls.chapters[index]
            else:
                chapter_dir = content / "第3章 资料"
                chapter_dir.mkdir(parents=True, exist_ok=True)
                target = chapter_dir / "3.1 资料.md"
            # 真实文档正文 + 一条真实草稿常见的 TODO 占位（用于触发“填空”建议，
            # 从而记录建议采纳/撤销；占位本身在试点记录里明示）。
            target.write_text(
                "{0}\n\n{1}\n\n> TODO：本段要点待补充（试点占位）。\n".format(
                    target.stem if target.stem.startswith("#") else "## " + target.stem,
                    _demote(text),
                ),
                encoding="utf-8",
            )
            cls.records.append({"label": label, "rel": str(target.relative_to(content)), "terms": terms})
        # 术语别名映射（真实使用中的“词汇统一”配置）：让建议在真实正文上可采纳。
        cls.assistant = build_assistant(
            cls.project,
            terms=["DocTool", "交付包", "快照"],
            term_aliases={"文档工具": "DocTool"},
        )
        reuse.load_context(cls.project)  # 触发同源上下文（试点环境与真实使用一致）

    @classmethod
    def tearDownClass(cls):
        fixtures.cleanup(cls.work)

    def test_pilot_measurements_and_records(self):
        assistant = self.assistant
        measurements = []
        for record in self.records:
            terms = record["terms"]
            started = time.perf_counter()
            outcome = assistant.search_evidence(query=terms[0], terms=list(terms))
            search_seconds = time.perf_counter() - started
            hits = list(getattr(outcome, "hits", None) or [])
            self.assertTrue(
                hits or getattr(outcome, "fallback_reason", ""),
                "真实文档应能定位到资料：{0}".format(record["label"]),
            )

            from doc_tool.application.assist.models import KIND_FILL, KIND_TERM

            suggestion_set = assistant.suggest(kinds=[KIND_FILL, KIND_TERM])
            items = list(getattr(suggestion_set, "suggestions", None) or [])
            self.assertTrue(items, "应给出确定性建议（规则/术语/引用/复核/变更）")

            adoptable = [item for item in items if bool(getattr(item, "applicable", False))]
            applied = 0
            undone = 0
            if adoptable:
                chosen = adoptable[0]
                before = dict(assistant.current_texts())
                outcome = assistant.adopt(
                    [getattr(chosen, "suggestion_id", "")],
                    suggestions=items, refresh=False,
                )
                after = dict(assistant.current_texts())
                if getattr(outcome, "applied", None) or after != before:
                    applied = len(getattr(outcome, "applied", None) or [1])
                    assistant.undo(outcome)
                    restored = dict(assistant.current_texts())
                    undone = 1 if restored == before else 0
                    self.assertEqual(restored, before, "一次撤销应恢复到采纳前内容")

            from doc_tool.application.content.changes import build_change_items

            summaries = assistant.revision_summary_texts(
                change_items=build_change_items({
                    record["rel"].replace("\\", "/"): "modified",
                }),
            )
            status = assistant.provider_status()
            measurements.append({
                "document": record["label"],
                "relPath": record["rel"],
                "searchSeconds": round(search_seconds, 3),
                "hits": len(hits),
                "searchTotal": int(getattr(outcome, "total", 0) or 0),
                "searchFiles": int(getattr(outcome, "file_count", 0) or 0),
                "searchFallback": str(getattr(outcome, "fallback_reason", "") or ""),
                "suggestions": len(items),
                "adoptable": len(adoptable),
                "applied": applied,
                "undone": undone,
                "adoptKind": str(getattr(chosen, "kind", "") if adoptable else ""),
                "adoptMode": str(getattr(chosen, "apply_mode", "") if adoptable else ""),
                "summaryCandidates": len(list(summaries or [])),
                "provider": {
                    "enhancementRun": bool(status.get("enhancementRun", False)),
                    "configured": bool(status.get("configured", False)),
                    "mode": str(status.get("mode", "") or ""),
                    "requests": len(status.get("requestLog") or []),
                },
            })
        print("PILOT_JSON:" + json.dumps(measurements, ensure_ascii=False))
        self.assertEqual(len(measurements), 3)
        for item in measurements:
            self.assertGreaterEqual(item["hits"], 1)
            self.assertGreaterEqual(item["suggestions"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)