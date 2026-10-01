# -*- coding: utf-8 -*-
"""V2.7 8.3：真实 Word 环现下的正式出稿与域刷新验收（A27-6 自动部分）。

实际调用本机 Word（DispatchEx）刷新域，记录真实结果；人工视觉版式仍需人工复核，
本脚本不代替人工结论。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("gen_samples", ROOT / "tools" / "gen_v27_samples.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

from doc_tool.application.pipeline import run_pipeline  # noqa: E402
from doc_tool.application.word_check import check_word_available  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402


def _post_refresh_failures(manifest, paths, result) -> list:
    """从**项目内验收报告**取刷新后失败明细。

    不在这里重跑 ``validate_with_project``：流水线失败时会回滚并删除临时产物，
    重跑只会得到“DOCX 不存在”这种**误导性**结果，而报告里已经有逐条原因。
    """
    report = paths.logs_dir / "general-validation.md"
    if not report.is_file():
        report = paths.logs_dir / "{0}-validation.md".format(manifest.documentType)
    if not report.is_file():
        candidates = sorted(paths.logs_dir.glob("*-validation.md"))
        report = candidates[0] if candidates else None
    details = []
    if report is not None and report.is_file():
        text = report.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip().startswith("- [FAIL]"):
                details.append({"report": line.strip()[:400]})
    if details:
        return details
    for event in result.events:
        if event.stage == "validate_post":
            details.append({"stage": event.status, "detail": (event.detail or "")[:400]})
    return details or [{"stage": "unknown", "detail": "刷新后校验未通过，报告未找到"}]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="V2.7 真实 Word 刷新证据")
    parser.add_argument("--keep", action="store_true", help="保留临时目录以便排查")
    parser.add_argument("--only", default="", help="只跑指定类型（requirement/design/test）")
    args = parser.parse_args()
    availability = check_word_available(dispatch_check=True)
    record = {
        "wordAvailable": availability.available,
        "wordDispatchable": availability.word_dispatchable,
        "reasons": list(availability.reasons),
        "samples": [],
    }
    root = pathlib.Path(tempfile.mkdtemp(prefix="v27-word-"))
    try:
        types = (args.only,) if args.only else ("requirement", "design", "test")
        for doc_type in types:
            sample = mod.SAMPLES[doc_type]
            project = mod._make_project(root, doc_type, sample)
            manifest = ProjectManifest.load(str(project))
            paths = manifest.resolve_paths(str(project))
            if not availability.available:
                record["samples"].append(
                    {
                        "documentType": doc_type,
                        "executed": False,
                        "reason": "本机 Word 不可用",
                    }
                )
                continue
            result = run_pipeline(manifest, paths, skip_word_refresh=False)
            from doc_tool.domain.output_state import read_state

            state = read_state(result.output_path) if result.output_path else None
            failures = _post_refresh_failures(manifest, paths, result)
            record["samples"].append(
                {
                    "documentType": doc_type,
                    "executed": True,
                    "success": result.success,
                    "errorCode": result.error_code,
                    "outputPath": result.output_path,
                    "formal": bool(state.formal) if state else None,
                    "diagnostic": bool(state.diagnostic) if state else None,
                    "postRefreshFailures": failures,
                    "stages": [
                        {"stage": event.stage, "status": event.status, "detail": (event.detail or "")[:160]}
                        for event in result.events
                    ],
                }
            )
    finally:
        if args.keep:
            print("临时目录保留于", root)
        else:
            shutil.rmtree(root, ignore_errors=True)
    target = ROOT / "docs" / "release" / "evidence" / "v27-word-refresh.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已生成", target)
    for item in record["samples"]:
        print(
            "  {0}: executed={1} success={2} formal={3}".format(
                item["documentType"], item.get("executed"), item.get("success"), item.get("formal")
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())