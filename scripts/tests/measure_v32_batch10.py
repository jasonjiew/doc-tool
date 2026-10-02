# -*- coding: utf-8 -*-
"""V3.2 7.2 十成员批次实测：队列响应、总耗时、磁盘体积与失败项续跑。

用法：``$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Get-Location).Path;
python scripts\\tests\\measure_v32_batch10.py``
输出一行 JSON，便于写入台账；只做测量，不做断言。
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests import core_fixtures as fixtures  # noqa: E402


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def main() -> int:
    from doc_tool.application.delivery import gui_tasks
    from doc_tool.application.delivery.queue import DeliveryQueue

    work = fixtures.scratch_dir("v32-batch10")
    metrics = {"members": 10, "brokenMembers": 1}
    try:
        members = work / "members"
        template = fixtures.two_chapter_project(members / "Member01")
        for index in range(2, 11):
            shutil.copytree(str(template), str(members / "Member{0:02d}".format(index)))
        # 第 10 个成员故意损坏清单：用于“失败项续跑”测量
        broken = members / "Member10"
        (broken / "project.yml").write_text("this is: not: valid: yaml\n: :", encoding="utf-8")

        plan = {
            "schemaVersion": 1,
            "batchId": "measure-10",
            "policy": {"execution": "serial", "wordBusy": "waiting-refresh",
                       "onPartial": "keep-useful", "strict": False},
            "defaults": {
                "formats": ["docx"], "destination": str(work / "out"),
                "sourceMode": "saved", "refresh": False,
            },
            "entries": [
                {"id": "m{0:02d}".format(index), "member": "members/Member{0:02d}".format(index),
                 "kind": "project", "formats": ["docx"]}
                for index in range(1, 11)
            ],
        }
        plan_path = work / "batch.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        preview = gui_tasks.plan_preview(plan_path)
        metrics["planExecutable"] = len(preview["executable"])
        metrics["planInvalid"] = len(preview["invalid"])

        store = work / "queue.json"
        started = time.perf_counter()
        result = gui_tasks.run_plan_task(plan_path, store_path=str(store))
        metrics["runSeconds"] = round(time.perf_counter() - started, 2)
        counts = result["queue"]["counts"]
        metrics["counts"] = {key: counts[key] for key in ("total", "completed", "completed-with-warnings",
                                                          "failed", "waiting-refresh", "partial")}
        metrics["usableTargets"] = len(result["openTargets"])
        metrics["averageSecondsPerMember"] = round(metrics["runSeconds"] / max(1, counts["total"]), 2)
        metrics["outputBytes"] = _dir_size(work / "out")
        metrics["queueStoreBytes"] = store.stat().st_size if store.is_file() else 0

        # 失败项续跑：修复坏成员后只补未完成项
        good = members / "Member09"
        shutil.copy2(str(good / "project.yml"), str(broken / "project.yml"))
        started = time.perf_counter()
        retry = gui_tasks.retry_unfinished_task(str(store))
        metrics["resumeSeconds"] = round(time.perf_counter() - started, 2)
        metrics["resumedMembers"] = len(retry.get("ran") or [])
        metrics["afterResumeCounts"] = {
            key: retry["queue"]["counts"][key]
            for key in ("total", "completed", "completed-with-warnings", "failed", "waiting-refresh")
        }
        metrics["afterResumeBytes"] = _dir_size(work / "out")
        queue = DeliveryQueue(str(store))
        metrics["attemptsRecorded"] = sum(len(job.attempts) for job in queue.jobs)
        metrics["ok"] = True
    finally:
        fixtures.cleanup(work)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())