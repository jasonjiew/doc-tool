# -*- coding: utf-8 -*-
"""条目查询、复核状态与稳定迁移计划薄入口服务。"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.impact import ReviewRecordStore, extract_snapshots
from doc_tool.application.content.relations import RELATIONS_NAME, RelationGraph, load_relations
from doc_tool.application.content.traceable_items import (
    ItemIndex,
    ItemKey,
    ItemLocation,
    ItemRef,
    _leading_number,
    _nearest_heading,
    build_item_index,
    extract_table_business_row,
)
from doc_tool.application.review.review_store import ReviewStore
from doc_tool.domain.manifest import ProjectManifest


def _resolve_content_root(manifest: ProjectManifest, project_root: Path) -> Path:
    """优先取 manifest.paths['contentRoot'] 声明的相对路径。"""
    rel = ""
    if isinstance(getattr(manifest, "paths", None), dict):
        rel = manifest.paths.get("contentRoot", "")
    if rel:
        candidate = project_root / rel
        if candidate.is_dir():
            return candidate
    resolved = manifest.resolve_paths(project_root)
    return resolved.content_root


def _collect_project_docs(root: Path) -> List[Tuple[str, str]]:
    """读取单项目内的全部 Markdown（按相对路径）。"""
    if not (root / "project.yml").is_file():
        docs = []
        for path in sorted(root.rglob("*.md")):
            if path.is_file():
                docs.append((path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))
        return docs
    manifest = ProjectManifest.load(root)
    content_root = _resolve_content_root(manifest, root)
    documents = []
    if content_root.is_dir():
        for path in sorted(content_root.rglob("*.md")):
            if path.is_file():
                documents.append(
                    (path.relative_to(content_root).as_posix(), path.read_text(encoding="utf-8"))
                )
    return documents


def _collect_workspace_docs(root: Path) -> Tuple[List[Tuple[str, str]], List[Path], Optional[str]]:
    """读取工作区内各成员文档与关系路径。"""
    from doc_tool.application.workspace import load_workspace

    documents = []
    relation_paths = []
    space = load_workspace(root)
    workspace_id = space.workspace_id if hasattr(space, "workspace_id") else root.name
    member_roots: List[Path] = []
    for member in space.valid_members:
        project_root = space.member_project_root(member)
        if project_root is not None:
            member_roots.append(project_root)
    if not member_roots and not (root / "workspace.yml").is_file():
        from doc_tool.application.baseline_check import _discover_project_roots
        member_roots = _discover_project_roots(root)
    for project_root in member_roots:
        documents.extend(_collect_project_docs(project_root))
        p = project_root / RELATIONS_NAME
        if p.is_file():
            relation_paths.append(p)
    if (root / RELATIONS_NAME).is_file():
        relation_paths.append(root / RELATIONS_NAME)
    return documents, relation_paths, workspace_id


def _populate_table_fallback_items(
    documents: Sequence[Tuple[str, str]],
    target_id: str,
    index: ItemIndex,
    snapshots: Dict[ItemKey, Any],
) -> None:
    """当文档尚未写入 DOC-ITEM 注释时，自动从 Markdown 表格识别 REQ/Function/Design 业务条目。"""
    import re
    from doc_tool.application.content.impact import ItemSnapshot

    proj_id = str(target_id or "default-project")
    for rel_path, text in documents:
        heading_no = ""
        heading_title = ""
        in_code_fence = False
        fence_char = ""
        for line_no, line in enumerate(str(text or "").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                cur_fence = stripped[:3]
                if not in_code_fence:
                    in_code_fence = True
                    fence_char = cur_fence
                    continue
                elif fence_char == cur_fence:
                    in_code_fence = False
                    fence_char = ""
                    continue
            if in_code_fence:
                continue
            h_match = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
            if h_match:
                h_text = h_match.group(1).strip()
                heading_title = h_text
                lead = _leading_number(h_text)
                if lead:
                    heading_no = lead
                continue
            row = extract_table_business_row(line)
            if row is None:
                continue
            biz_id, kind, row_title, row_body = row
            det_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{proj_id}:table:{biz_id}"))
            ref = ItemRef(project_id=proj_id, item_id=det_id, kind=kind, alias=biz_id)
            loc = ItemLocation(rel_path=rel_path, line_no=line_no, heading_no=heading_no)
            index.add(ref, loc)
            if ref.key not in snapshots:
                snapshots[ref.key] = ItemSnapshot(
                    key=ref.key,
                    title=row_title or heading_title or biz_id,
                    body=row_body,
                    resources=(),
                )


def list_items(
    root: Path,
    *,
    workspace: bool = False,
    chapter: Optional[str] = None,
    query: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """查询项目或工作区内的稳定条目，支持章节范围、关键词过滤与分页。"""
    if workspace:
        documents, _rel_paths, target_id = _collect_workspace_docs(root)
    else:
        documents = _collect_project_docs(root)
        target_id = root.name
        if (root / "project.yml").is_file():
            try:
                target_id = ProjectManifest.load(root).projectId
            except Exception:
                pass

    index = build_item_index(documents)
    snapshots = extract_snapshots(documents)
    if index.count() == 0:
        _populate_table_fallback_items(documents, target_id, index, snapshots)

    raw_items = []
    for key, ref in index.items.items():
        locs = index.locations.get(key, [])
        primary_loc = locs[0] if locs else ItemLocation(rel_path="", line_no=0)
        snap = snapshots.get(key)
        title = snap.title if snap else ""
        body = snap.body if snap else ""
        digest = snap.semantic_hash() if snap else ""
        resources = list(snap.resources) if snap else []

        if chapter:
            chap_norm = chapter.replace("\\", "/").strip().lower()
            if not any(chap_norm in loc.rel_path.replace("\\", "/").lower() for loc in locs):
                continue

        if query:
            q = query.strip().lower()
            text_pool = f"{ref.item_id} {ref.alias} {title} {body}".lower()
            if q not in text_pool:
                continue

        raw_items.append({
            "projectId": ref.project_id,
            "itemId": ref.item_id,
            "kind": ref.kind,
            "alias": ref.alias,
            "title": title,
            "relPath": primary_loc.rel_path,
            "lineNo": primary_loc.line_no,
            "headingNo": primary_loc.heading_no,
            "digest": digest,
            "snippet": (body[:100] + "...") if len(body) > 100 else body,
            "resources": resources,
            "locationsCount": len(locs),
        })

    raw_items.sort(key=lambda x: (x["relPath"], x["lineNo"], x["itemId"]))

    total = len(raw_items)
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = raw_items[start : start + page_size]

    issues = [iss.to_dict() for iss in index.issues]
    status = "passed"
    if index.duplicates:
        issues.append({
            "relPath": "",
            "lineNo": 0,
            "reason": f"存在 {len(index.duplicates)} 组重复 DOC-ITEM ID",
            "severity": "error",
        })
        status = "failed"

    from doc_tool.domain.version import get_tool_metadata

    return {
        "schemaVersion": 1,
        "command": "item-list",
        "tool": get_tool_metadata(),
        "targetId": target_id,
        "workspace": workspace,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "items": paged,
        "duplicates": [f"{k[0]}/{k[1]}" for k in index.duplicates],
        "issues": issues,
        "status": status,
    }


def show_item(
    root: Path,
    item_identifier: str,
    *,
    workspace: bool = False,
) -> Dict[str, Any]:
    """查看单个条目的详细内容、原子正文、关联资源与关系。"""
    token = str(item_identifier or "").strip()
    if "/" in token:
        req_project_id, _, req_item_id = token.partition("/")
    else:
        req_project_id, req_item_id = "", token

    if workspace:
        documents, rel_paths, target_id = _collect_workspace_docs(root)
    else:
        documents = _collect_project_docs(root)
        target_id = root.name
        rel_paths = [root / RELATIONS_NAME] if (root / RELATIONS_NAME).is_file() else []

    if (root / "project.yml").is_file() and not workspace:
        try:
            target_id = ProjectManifest.load(root).projectId
        except Exception:
            pass
    index = build_item_index(documents)
    snapshots = extract_snapshots(documents)
    if index.count() == 0:
        _populate_table_fallback_items(documents, target_id, index, snapshots)

    matched_keys = []
    for key, ref in index.items.items():
        proj, i_id = key
        if req_project_id:
            if proj == req_project_id and (i_id == req_item_id or ref.alias == req_item_id):
                matched_keys.append(key)
        else:
            if i_id == req_item_id or ref.alias == req_item_id:
                matched_keys.append(key)

    if not matched_keys:
        from doc_tool.domain.version import get_tool_metadata
        return {
            "schemaVersion": 1,
            "command": "item-show",
            "tool": get_tool_metadata(),
            "found": False,
            "item": None,
            "issues": [f"未在目标范围内找到条目：{item_identifier}"],
            "status": "failed",
        }

    if len(matched_keys) > 1:
        from doc_tool.domain.version import get_tool_metadata
        return {
            "schemaVersion": 1,
            "command": "item-show",
            "tool": get_tool_metadata(),
            "found": False,
            "item": None,
            "issues": [f"条目 ID 存在歧义，在多个项目中存在：{[f'{k[0]}/{k[1]}' for k in matched_keys]}，请指定 projectId/itemId"],
            "status": "failed",
        }

    target_key = matched_keys[0]
    ref = index.items[target_key]
    locs = index.locations.get(target_key, [])
    primary_loc = locs[0] if locs else ItemLocation(rel_path="", line_no=0)
    snap = snapshots.get(target_key)

    item_relations = []
    for p in rel_paths:
        if p.is_file():
            g = load_relations(p)
            for r in g.relations:
                if r.source == target_key or r.target == target_key:
                    item_relations.append({
                        "relationId": r.relation_id,
                        "type": r.type,
                        "source": f"{r.source[0]}/{r.source[1]}" if r.source else "",
                        "target": f"{r.target[0]}/{r.target[1]}" if r.target else "",
                    })

    from doc_tool.domain.version import get_tool_metadata

    return {
        "schemaVersion": 1,
        "command": "item-show",
        "tool": get_tool_metadata(),
        "found": True,
        "item": {
            "projectId": ref.project_id,
            "itemId": ref.item_id,
            "kind": ref.kind,
            "alias": ref.alias,
            "title": snap.title if snap else "",
            "relPath": primary_loc.rel_path,
            "lineNo": primary_loc.line_no,
            "headingNo": primary_loc.heading_no,
            "body": snap.body if snap else "",
            "digest": snap.semantic_hash() if snap else "",
            "resources": list(snap.resources) if snap else [],
            "locations": [loc.to_dict() for loc in locs],
            "relations": item_relations,
        },
        "issues": [],
        "status": "passed",
    }


def review_status(
    root: Path,
    *,
    baseline: Optional[str] = None,
    workspace: bool = False,
) -> Dict[str, Any]:
    """查询指定项目/基线绑定的评审意见、关系复核及签审失效状态。"""
    state_dir = root / ".state"
    if not state_dir.is_dir() and not workspace:
        from doc_tool.domain.version import get_tool_metadata
        return {
            "schemaVersion": 1,
            "command": "review-status",
            "tool": get_tool_metadata(),
            "projectId": root.name,
            "signoffs": [],
            "pendingReviews": [],
            "commentsSummary": {"total": 0, "unresolved": 0, "resolved": 0},
            "status": "passed",
            "issues": [f"项目尚未初始化 .state 目录：{state_dir}"],
        }

    rev_store = ReviewStore(state_dir)
    all_comments = rev_store.comments()
    unresolved_comments = [c for c in all_comments if c.status != "resolved"]

    from doc_tool.application.baseline_check import compute_project_content_hash

    current_docs = _collect_project_docs(root)
    current_content_hash = compute_project_content_hash(current_docs)

    signoff_results = []
    stale_signoffs = 0
    unverified_signoffs = 0
    for s in rev_store.signoffs():
        entry = {
            "signoffId": s.signoff_id,
            "author": s.author,
            "role": s.role,
            "createdAt": s.created_at,
            "note": s.note,
            "baselineId": s.baseline_id,
            "contentHash": s.content_hash,
            "commitId": s.commit_id,
            "status": "valid",
            "staleReason": "",
        }
        if not s.content_hash:
            entry["status"] = "unverified"
            entry["staleReason"] = "无法核实对当前内容的确认（缺少内容指纹绑定）"
            unverified_signoffs += 1
        elif s.content_hash != current_content_hash:
            entry["status"] = "stale"
            entry["staleReason"] = "内容已发生变更，原确认需复核"
            stale_signoffs += 1
        signoff_results.append(entry)

    rel_store = ReviewRecordStore(state_dir)
    pending_records = rel_store.pending()
    pending_list = [r.to_dict() for r in pending_records]

    issues = []
    if unresolved_comments:
        issues.append(f"存在 {len(unresolved_comments)} 条未解决评审意见")
    if pending_records:
        issues.append(f"存在 {len(pending_records)} 条待复核关系")
    if stale_signoffs:
        issues.append(f"存在 {stale_signoffs} 条因内容变更而失效的签审记录")
    if unverified_signoffs:
        issues.append(f"存在 {unverified_signoffs} 条缺少内容指纹绑定的历史签审记录")

    overall_status = "passed"
    if issues:
        overall_status = "pending_review"

    from doc_tool.domain.version import get_tool_metadata

    return {
        "schemaVersion": 1,
        "command": "review-status",
        "tool": get_tool_metadata(),
        "projectId": root.name,
        "baseline": baseline or "",
        "currentContentHash": current_content_hash,
        "signoffs": signoff_results,
        "pendingReviews": pending_list,
        "commentsSummary": {
            "total": len(all_comments),
            "unresolved": len(unresolved_comments),
            "resolved": len(all_comments) - len(unresolved_comments),
        },
        "issues": issues,
        "status": overall_status,
    }


def generate_stable_trace_plan(
    root: Path,
    *,
    workspace: bool = False,
) -> Dict[str, Any]:
    """生成旧编号迁移至 DOC-ITEM 的稳定迁移计划，预览不写正文，支持稳定重跑。"""
    if workspace:
        documents, _rel_paths, target_id = _collect_workspace_docs(root)
    else:
        documents = _collect_project_docs(root)
        target_id = root.name
        if (root / "project.yml").is_file():
            try:
                target_id = ProjectManifest.load(root).projectId
            except Exception:
                pass

    from doc_tool.application.content.traceable_items import DOC_ITEM_RE

    seen: Dict[str, List[Tuple[str, int]]] = {}
    candidates: List[Tuple[str, int, str]] = []

    for rel_path, text in documents:
        heading_no = ""
        in_code_fence = False
        fence_char = ""
        for line_no, line in enumerate(str(text or "").splitlines(), start=1):
            import re
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                current_fence = stripped[:3]
                if not in_code_fence:
                    in_code_fence = True
                    fence_char = current_fence
                    continue
                elif fence_char == current_fence:
                    in_code_fence = False
                    fence_char = ""
                    continue
            if in_code_fence:
                continue
            heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
            if heading_match:
                lead_h = _leading_number(heading_match.group(1))
                if lead_h:
                    heading_no = lead_h
                continue
            if DOC_ITEM_RE.search(line):
                continue
            legacy = _leading_number(line)
            if not legacy:
                table_row = extract_table_business_row(line)
                if table_row is not None:
                    legacy = table_row[0]
            if not legacy:
                continue
            key = f"{heading_no}@{legacy}"
            seen.setdefault(key, []).append((rel_path, line_no))
            candidates.append((rel_path, line_no, legacy))

    confident = []
    ambiguous = []

    for rel_path, line_no, legacy in candidates:
        heading_no = _nearest_heading(documents, rel_path, line_no)
        key = f"{heading_no}@{legacy}"
        places = seen.get(key, [])
        if len(places) > 1:
            ambiguous.append({
                "relPath": rel_path,
                "lineNo": line_no,
                "legacyNo": legacy,
                "proposedId": "",
                "confident": False,
                "reason": f"同一编号在 {len(places)} 处出现，无法唯一确定",
            })
        else:
            stable_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{target_id}:{rel_path}:{line_no}:{legacy}"))
            confident.append({
                "relPath": rel_path,
                "lineNo": line_no,
                "legacyNo": legacy,
                "proposedId": stable_uuid,
                "confident": True,
                "reason": "编号在集合内唯一且定位明确",
            })

    plan_digest = hashlib.sha256(
        f"{target_id}:{len(documents)}:{len(confident)}:{len(ambiguous)}".encode("utf-8")
    ).hexdigest()[:16]

    warnings = []
    if not candidates:
        warnings.append("未发现可迁移的旧编号条目")
    if ambiguous:
        warnings.append(f"有 {len(ambiguous)} 项歧义需人工复核，本次不建议直接写入")
    warnings.append("未标记内容不自动计入覆盖率分母；本命令仅输出预览计划，不修改任何正文")

    from doc_tool.domain.version import get_tool_metadata

    return {
        "schemaVersion": 1,
        "command": "trace-plan",
        "tool": get_tool_metadata(),
        "planId": f"plan-{plan_digest}",
        "projectId": target_id,
        "previewOnly": True,
        "confidentCount": len(confident),
        "ambiguousCount": len(ambiguous),
        "confident": confident,
        "ambiguous": ambiguous,
        "warnings": warnings,
        "status": "passed" if not ambiguous else "has_ambiguities",
    }
