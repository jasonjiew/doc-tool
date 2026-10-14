# -*- coding: utf-8 -*-
"""变更报告与 GitLab MR 交付证据整合服务（change-report）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from xml.etree import ElementTree as ET

from doc_tool.application.content.impact import compute_impact
from doc_tool.application.content.relations import RELATIONS_NAME, load_relations
from doc_tool.domain.manifest import ProjectManifest


def parse_junit_xml(path: Path) -> Dict[str, Any]:
    """严格解析单个 JUnit XML 报告文件。

    规则：
    - 空文件或 XML 损坏判定为 blocked；
    - 统计 tests, failures, errors, skipped；
    - skipped 独立列出，绝不算通过；
    - 校验 testsuite 声明总数与实际 testcase 节点数一致性。
    """
    if not path.is_file():
        return {
            "file": path.as_posix(),
            "status": "blocked",
            "error": "JUnit 文件不存在",
            "tests": 0, "failures": 0, "errors": 0, "skipped": 0, "cases": [],
        }

    raw = path.read_bytes()
    if not raw.strip():
        return {
            "file": path.as_posix(),
            "status": "blocked",
            "error": "JUnit 文件为空 (0 字节)",
            "tests": 0, "failures": 0, "errors": 0, "skipped": 0, "cases": [],
        }

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {
            "file": path.as_posix(),
            "status": "blocked",
            "error": f"JUnit XML 解析失败: {exc}",
            "tests": 0, "failures": 0, "errors": 0, "skipped": 0, "cases": [],
        }

    suites = []
    if root.tag == "testsuite":
        suites.append(root)
    elif root.tag == "testsuites":
        suites.extend(root.findall("testsuite"))
    else:
        # 兼容其他包裹结构
        suites.extend(root.findall(".//testsuite"))

    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0
    cases_list = []
    discrepancies = []

    for suite in suites:
        declared_tests = int(suite.attrib.get("tests", 0) or 0)
        declared_failures = int(suite.attrib.get("failures", 0) or 0)
        declared_errors = int(suite.attrib.get("errors", 0) or 0)
        declared_skipped = int(suite.attrib.get("skipped", 0) or 0)

        actual_cases = suite.findall("testcase")
        if declared_tests > 0 and len(actual_cases) > 0 and declared_tests != len(actual_cases):
            discrepancies.append(
                f"Suite '{suite.attrib.get('name')}' 声明 tests={declared_tests} 与实际用例数 {len(actual_cases)} 不一致"
            )

        for case in actual_cases:
            name = case.attrib.get("name", "unknown")
            classname = case.attrib.get("classname", "")
            time_val = float(case.attrib.get("time", 0.0) or 0.0)

            failure_node = case.find("failure")
            error_node = case.find("error")
            skipped_node = case.find("skipped")

            status = "passed"
            msg = ""
            if failure_node is not None:
                status = "failed"
                total_failures += 1
                msg = failure_node.attrib.get("message") or failure_node.text or "failure"
            elif error_node is not None:
                status = "error"
                total_errors += 1
                msg = error_node.attrib.get("message") or error_node.text or "error"
            elif skipped_node is not None:
                status = "skipped"
                total_skipped += 1
                msg = skipped_node.attrib.get("message") or skipped_node.text or "skipped"

            total_tests += 1
            cases_list.append({
                "name": name,
                "classname": classname,
                "time": time_val,
                "status": status,
                "message": (msg.strip()[:200] + "...") if len(msg.strip()) > 200 else msg.strip(),
            })

    # 判定通过状态
    status = "passed"
    if total_failures > 0 or total_errors > 0:
        status = "failed"
    elif total_tests == 0:
        status = "not-run"

    file_hash = hashlib.sha256(raw).hexdigest()

    return {
        "file": path.as_posix(),
        "sha256": file_hash,
        "status": status,
        "tests": total_tests,
        "failures": total_failures,
        "errors": total_errors,
        "skipped": total_skipped,
        "discrepancies": discrepancies,
        "cases": cases_list[:50],  # 截断展示
    }


def parse_manual_evidence(path: Path) -> List[Dict[str, Any]]:
    """解析人工验收记录（JSON/Markdown）。"""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    records = []
    # 尝试 JSON
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return parse_manual_evidence_dict(data)
        if isinstance(data, dict):
            for key in ("records", "manual_acceptance", "items"):
                if key in data and isinstance(data[key], list):
                    return parse_manual_evidence_dict(data[key])
    except Exception:
        pass

    # 尝试 Markdown 表格行匹配
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "状态" in line:
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) >= 3:
            records.append({
                "id": parts[0],
                "description": parts[1],
                "status": parts[2].lower(),
                "author": parts[3] if len(parts) > 3 else "",
                "reason": parts[4] if len(parts) > 4 else "",
            })
    return records


def parse_manual_evidence_dict(items: list) -> List[Dict[str, Any]]:
    records = []
    for item in items:
        if isinstance(item, dict):
            status = str(item.get("status", "not-run")).lower()
            rec_id = str(item.get("id") or item.get("item") or "MANUAL-UNKNOWN")
            desc = str(item.get("description") or item.get("evidence") or "")
            auth = str(item.get("author") or item.get("verifier") or "")
            records.append({
                "id": rec_id,
                "description": desc,
                "author": auth,
                "date": str(item.get("date", "")),
                "status": status,
                "reason": str(item.get("reason", "")),
            })
    return records


def generate_change_report(
    *,
    change_id: str,
    openspec_ref: str = "",
    gitlab_mr_ref: str = "",
    git_evidence_files: Sequence[Path] = (),
    junit_files: Sequence[Path] = (),
    manual_evidence_files: Sequence[Path] = (),
    project_root: Optional[Path] = None,
    baseline: Optional[str] = None,
    affected_items: Sequence[str] = (),
    no_doc_change_reason: str = "",
) -> Dict[str, Any]:
    """整合多仓库 Git 证据、JUnit、人工验收与文档基线影响，生成机器可读报告与 MR 附件。"""
    # 1. 多仓库 Git 证据整合
    git_repos = []
    total_committed_diffs = []
    dirty_repos = []
    for gef in git_evidence_files:
        p = Path(gef)
        if not p.is_file():
            continue
        try:
            raw_ev = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw_ev, dict) and "repositories" in raw_ev and isinstance(raw_ev["repositories"], list):
            ev_list = raw_ev["repositories"]
        elif isinstance(raw_ev, list):
            ev_list = raw_ev
        else:
            ev_list = [raw_ev]
        for ev in ev_list:
            if not isinstance(ev, dict):
                continue
            repo_path = ev.get("repository", "") or ev.get("repo_path", "")
            repo_name = ev.get("repo_name", "") or Path(repo_path).name or repo_path
            head_sha = ev.get("head", "") or ev.get("head_commit", "")
            base_sha = ev.get("base", "") or ev.get("base_commit", "")
            branch = ev.get("branch", "")
            staged = ev.get("staged", [])
            unstaged = ev.get("unstaged", [])
            committed = ev.get("committedBaseToHead", [])
            if not committed and (ev.get("changed_files") or ev.get("changedFiles")):
                committed = ev.get("changed_files") or ev.get("changedFiles", [])
            elif not committed and (ev.get("diff_stat") or ev.get("diffStat")):
                committed = [ev.get("diff_stat") or ev.get("diffStat")]
            is_dirty = bool(staged or unstaged)
            if is_dirty:
                dirty_repos.append(repo_name)

            for diff_line in committed:
                total_committed_diffs.append(f"[{repo_name}] {diff_line}")

            git_repos.append({
                "repository": repo_name,
                "path": repo_path,
                "branch": branch,
                "head": head_sha,
                "base": base_sha,
                "dirty": is_dirty,
                "stagedCount": len(staged),
                "unstagedCount": len(unstaged),
                "committedCount": len(committed),
                "diagnostics": ev.get("diagnostics", []),
            })

    # 2. JUnit 报告整合
    junit_results = []
    all_tests_passed = True
    total_junit_cases = 0
    total_junit_skipped = 0
    total_junit_failed = 0

    for jf in junit_files:
        res = parse_junit_xml(Path(jf))
        junit_results.append(res)
        total_junit_cases += res["tests"]
        total_junit_skipped += res["skipped"]
        total_junit_failed += (res["failures"] + res["errors"])
        if res["status"] != "passed":
            all_tests_passed = False

    # 3. 人工验收记录整合
    manual_results = []
    all_manual_passed = True
    for mf in manual_evidence_files:
        items = parse_manual_evidence(Path(mf))
        for it in items:
            manual_results.append(it)
            if it["status"] not in ("passed", "not-applicable"):
                all_manual_passed = False
            if it["status"] == "not-applicable" and not it.get("reason"):
                all_manual_passed = False

    # 4. 文档基线与变更影响
    doc_report = {
        "projectProvided": project_root is not None,
        "impactedItems": list(affected_items),
        "impactReport": None,
        "noDocChangeReason": no_doc_change_reason,
    }
    if project_root is not None and project_root.is_dir():
        from doc_tool.cli import _detect_changes
        if (project_root / "project.yml").is_file():
            from doc_tool.cli import _collect_graph
            graph, _ = _collect_graph(project_root, workspace=False)
        else:
            from doc_tool.application.content.relations import RelationGraph
            graph = RelationGraph()
        changed_map = {}
        default_proj = project_root.name
        if (project_root / "project.yml").is_file():
            try:
                default_proj = ProjectManifest.load(project_root).projectId
            except Exception:
                pass
        for token in affected_items:
            token_str = str(token).strip()
            if "/" in token_str:
                proj_id, _, item_id = token_str.partition("/")
            else:
                proj_id, item_id = default_proj, token_str
            if proj_id and item_id:
                changed_map[(proj_id, item_id)] = "显式受控变更"
        if not changed_map and baseline:
            changed_map = _detect_changes(project_root, baseline)

        if changed_map:
            impact = compute_impact(changed_map, graph)
            doc_report["impactReport"] = impact.to_dict()

    # 5. 综合判定与已知缺口
    gaps = []
    has_blocked_evidence = False
    for j_res in junit_results:
        if j_res.get("status") == "blocked":
            gaps.append(f"JUnit 报告阻断异常 ({j_res.get('file')}): {j_res.get('error')}")
            has_blocked_evidence = True
        for disc in j_res.get("discrepancies", []):
            gaps.append(f"JUnit 套件总数矛盾 ({j_res.get('file')}): {disc}")
            has_blocked_evidence = True

    if not git_repos:
        gaps.append("未提供有效的 Git 差异证据 JSON")
    if not junit_results and not manual_results:
        gaps.append("未提供任何自动化测试（JUnit）或人工验收证据")
    if total_junit_cases == 0 and not manual_results:
        gaps.append("未实际执行任何自动化测试用例")
    if total_junit_skipped > 0:
        gaps.append(f"存在 {total_junit_skipped} 个跳过的测试用例（skipped 明确不作为通过证据）")
    if dirty_repos:
        gaps.append(f"以下仓库工作树存在未提交改动：{', '.join(dirty_repos)}")
    if not doc_report.get("impactedItems") and not no_doc_change_reason:
        gaps.append("变更未关联受影响文档条目，亦未提供‘无需改文档’的合规理由")

    any_test_failed = (total_junit_failed > 0) or any(r.get("status") == "failed" for r in junit_results) or any(m.get("status") == "failed" for m in manual_results)
    any_blocked = has_blocked_evidence or any(r.get("status") == "blocked" for r in junit_results) or any(r.get("discrepancies") for r in junit_results)

    overall_verdict = "passed"
    exit_code = 0
    if any_test_failed:
        overall_verdict = "failed"
        exit_code = 1
    elif any_blocked or gaps or total_junit_skipped > 0 or not all_manual_passed:
        overall_verdict = "incomplete"
        exit_code = 1

    from doc_tool.domain.version import get_tool_metadata

    report_payload = {
        "schemaVersion": 1,
        "command": "change-report",
        "tool": get_tool_metadata(),
        "changeId": change_id,
        "openSpecRef": openspec_ref,
        "gitlabMrRef": gitlab_mr_ref,
        "verdict": overall_verdict,
        "exitCode": exit_code,
        "summary": {
            "repositories": len(git_repos),
            "totalDiffFiles": len(total_committed_diffs),
            "junitCases": total_junit_cases,
            "junitFailed": total_junit_failed,
            "junitSkipped": total_junit_skipped,
            "manualCases": len(manual_results),
            "gapsCount": len(gaps),
        },
        "repositories": git_repos,
        "committedDiffs": total_committed_diffs[:100],
        "testEvidence": {
            "junit": junit_results,
            "manual": manual_results,
        },
        "documentation": doc_report,
        "gapsAndRisks": gaps,
    }

    # 6. 生成 MR 附件 Markdown
    mr_lines = [
        f"## 变更与交付验证报告：{change_id}",
        "",
        "> [!NOTE] 报告生成说明",
        "> 本报告由 `doc-tool change-report` 依据实际提交与测试产物自动生成，未执行远程 API 或自动提交。",
        f"> **综合结论：`{overall_verdict.upper()}`**（退出码：`{exit_code}`）",
        "",
        "### 1. 变更范围与关联溯源",
        f"- **Change ID**: `{change_id}`",
        f"- **OpenSpec 引用**: `{openspec_ref or '无 / 独立变更'}`",
        f"- **GitLab MR 关联**: `{gitlab_mr_ref or '待确定'}`",
        "",
        "### 2. 多仓库 Git 版本与差异摘要",
        "| 仓库 | 分支 | Base Commit | Head Commit | 工作树状态 |",
        "|------|------|-------------|-------------|------------|",
    ]
    for r in git_repos:
        dirty_str = "脏 (有未暂存/暂存变更)" if r["dirty"] else "干净"
        mr_lines.append(f"| {r['repository']} | {r['branch']} | {r['base'][:10] if r['base'] else 'N/A'} | {r['head'][:10] if r['head'] else 'N/A'} | {dirty_str} |")

    mr_lines.extend([
        "",
        "### 3. 测试与验收证据",
        f"- **自动化 JUnit 测试用例**: 共 {total_junit_cases} 项，通过 {total_junit_cases - total_junit_failed - total_junit_skipped} 项，失败/错误 {total_junit_failed} 项，跳过 {total_junit_skipped} 项（不计入通过）",
        f"- **人工验收用例**: 共 {len(manual_results)} 项",
        "",
    ])

    if manual_results:
        mr_lines.extend([
            "| 验收项 | 说明 | 状态 | 验证人 | 不适用理由 / 依据 |",
            "|--------|------|------|--------|-------------------|",
        ])
        for m in manual_results:
            mr_lines.append(f"| {m['id']} | {m['description']} | {m['status'].upper()} | {m['author'] or 'N/A'} | {m['reason'] or 'N/A'} |")
        mr_lines.append("")

    mr_lines.extend([
        "### 4. 文档基线与需求关联",
    ])
    if no_doc_change_reason:
        mr_lines.append(f"- **无需修改文档理由**: {no_doc_change_reason}")
    elif doc_report.get("impactedItems"):
        mr_lines.append(f"- **受控变更条目**: {', '.join(doc_report['impactedItems'])}")
    else:
        mr_lines.append("- **条目关联**: `N/A (文档未标记 DOC-ITEM 或无变更影响)`")

    if gaps:
        mr_lines.extend([
            "",
            "### 5. 待补齐缺口与交付风险",
        ])
        for g in gaps:
            mr_lines.append(f"- ⚠️ **{g}**")

    report_payload["mrMarkdown"] = "\n".join(mr_lines)
    return report_payload
