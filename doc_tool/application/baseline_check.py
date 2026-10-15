# -*- coding: utf-8 -*-
"""基线核对与版本冲突判定服务（baseline-check）。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.baselines import BaselineStore
from doc_tool.application.review.review_store import ReviewStore
from doc_tool.domain.manifest import ProjectManifest


def compute_project_content_hash(documents: Sequence[Tuple[str, str]]) -> str:
    """计算跨 Windows/Linux CRLF 一致的项目 Markdown 正文内容摘要。"""
    digest = hashlib.sha256()
    for rel_path, text in sorted(documents):
        norm_path = rel_path.replace("\\", "/")
        norm_text = "\n".join(line.rstrip() for line in str(text or "").splitlines())
        digest.update(norm_path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(norm_text.encode("utf-8"))
        digest.update(b"\x01")
    return digest.hexdigest()


def _normalize_ver(v: str) -> str:
    """归一化版本字符串，如 'V3.8' -> '3.8', 'v2.5' -> '2.5'。"""
    cleaned = str(v or "").strip()
    if cleaned.startswith(("V", "v")):
        cleaned = cleaned[1:].strip()
    return cleaned


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


def _extract_revision_record_version(revision_file: Path) -> Tuple[Optional[str], Optional[str]]:
    """从 _revision_record.md 提取最后一行修订记录的版本与整行内容。"""
    if not revision_file.is_file():
        return None, None
    try:
        text = revision_file.read_text(encoding="utf-8")
    except Exception:
        return None, None

    last_ver = None
    last_line = None
    for line in text.splitlines():
        line_str = line.strip()
        if not line_str.startswith("|"):
            continue
        parts = [p.strip() for p in line_str.split("|")[1:-1]]
        if not parts:
            continue
        first_col = parts[0]
        # 跳过表头与分隔线
        if "版本" in first_col or "---" in first_col or not first_col:
            continue
        ver_match = re.search(r"[vV]?\d+(?:\.\d+)*", first_col)
        if ver_match:
            last_ver = ver_match.group(0)
            last_line = line_str

    return _normalize_ver(last_ver) if last_ver else None, last_line


def _scan_declared_version(
    declare_file: Path,
    document_no: str,
    document_name: str,
) -> List[Dict[str, Any]]:
    """在声明文件（如 README.md）中检索该文档编号或名称声明的版本。"""
    if not declare_file.is_file():
        return []
    try:
        text = declare_file.read_text(encoding="utf-8")
    except Exception:
        return []

    found = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if document_no and document_no in line:
            # 常见 Markdown 表格：| document_no | document_name | version | ...
            m = re.search(r"\|\s*" + re.escape(document_no) + r"\s*\|[^|]*\|\s*([vV]?\d+(?:\.\d+)*)\s*\|", line)
            if m:
                found.append({
                    "file": declare_file.as_posix(),
                    "lineNo": idx,
                    "declaredVersion": _normalize_ver(m.group(1)),
                    "matchedText": line.strip(),
                    "source": "table_row_by_doc_no",
                })
                continue
            m2 = re.search(re.escape(document_no) + r"[^\d\n\r]*([vV]?\d+(?:\.\d+)+)", line)
            if m2:
                found.append({
                    "file": declare_file.as_posix(),
                    "lineNo": idx,
                    "declaredVersion": _normalize_ver(m2.group(1)),
                    "matchedText": line.strip(),
                    "source": "text_pattern_by_doc_no",
                })
        elif document_name and document_name in line:
            m = re.search(r"\|\s*" + re.escape(document_name) + r"\s*\|[^|]*\|\s*([vV]?\d+(?:\.\d+)*)\s*\|", line)
            if m:
                found.append({
                    "file": declare_file.as_posix(),
                    "lineNo": idx,
                    "declaredVersion": _normalize_ver(m.group(1)),
                    "matchedText": line.strip(),
                    "source": "table_row_by_name",
                })
                continue
            m2 = re.search(re.escape(document_name) + r"[^\d\n\r]*([vV]?\d+(?:\.\d+)+)", line)
            if m2:
                found.append({
                    "file": declare_file.as_posix(),
                    "lineNo": idx,
                    "declaredVersion": _normalize_ver(m2.group(1)),
                    "matchedText": line.strip(),
                    "source": "text_pattern_by_name",
                })
    return found


def check_project_baseline(
    project_root: Path,
    *,
    declare_files: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    """对单个文档项目执行清单版本、修订记录、声明文件与冻结基线核对。"""
    manifest_path = project_root / "project.yml"
    if not manifest_path.is_file():
        return {
            "projectId": project_root.name,
            "projectRoot": project_root.as_posix(),
            "status": "error",
            "issues": [f"项目目录缺失 project.yml：{project_root}"],
            "conflict": False,
        }

    try:
        manifest = ProjectManifest.load(project_root)
    except Exception as exc:
        return {
            "projectId": project_root.name,
            "projectRoot": project_root.as_posix(),
            "documentNo": "",
            "documentName": project_root.name,
            "manifestVersion": "",
            "revisionRecordVersion": None,
            "revisionRecordLine": None,
            "declaredVersions": [],
            "frozenBaseline": {"exists": False, "version": "", "corrupted": [], "frozenAt": ""},
            "currentContentHash": "",
            "signoffs": [],
            "status": "error",
            "issues": [f"清单文件解析失败（{project_root / 'project.yml'}）：{exc}"],
            "conflict": False,
        }
    content_root = _resolve_content_root(manifest, project_root)
    manifest_ver = _normalize_ver(manifest.documentVersion)
    document_no = getattr(manifest, "documentNo", "")
    document_name = getattr(manifest, "documentName", "")

    # 1. 修订记录末行版本
    rev_file = content_root / "_revision_record.md"
    if not rev_file.is_file():
        # 尝试递归查找
        found_revs = list(project_root.rglob("_revision_record.md"))
        if found_revs:
            rev_file = found_revs[0]

    rev_ver, rev_line = _extract_revision_record_version(rev_file)

    # 2. 外部声明文件中的版本
    declared_matches = []
    for df in declare_files or ():
        matches = _scan_declared_version(Path(df), document_no, document_name)
        declared_matches.extend(matches)

    # 3. 冲突比对
    conflicts = []
    if rev_ver and rev_ver != manifest_ver:
        conflicts.append(
            f"清单 documentVersion ({manifest_ver}) 与修订记录末行版本 ({rev_ver}) 不一致"
        )
    for dm in declared_matches:
        d_ver = dm["declaredVersion"]
        if d_ver != manifest_ver:
            conflicts.append(
                f"清单版本 ({manifest_ver}) 与外部声明文件 {dm['file']} (第 {dm['lineNo']} 行) 声明版本 ({d_ver}) 冲突。当前批准基线需团队确认，不能自动选择较大版本"
            )

    # 4. 冻结基线检查
    state_dir = project_root / ".state"
    b_store = BaselineStore(state_dir)
    frozen_exists = False
    frozen_corrupted = []
    frozen_metadata = None
    try:
        loaded = b_store.load(manifest_ver)
        frozen_exists = True
        frozen_metadata = loaded
        snapshot_content_dir = state_dir / "baselines" / manifest_ver / "content"
        if not snapshot_content_dir.is_dir():
            frozen_corrupted.append(f"基线快照目录不存在：{snapshot_content_dir}")
        else:
            for rel_p, exp_hash in loaded.get("files", {}).items():
                target_f = snapshot_content_dir / rel_p
                if not target_f.is_file():
                    frozen_corrupted.append(f"快照文件缺失：{rel_p}")
                else:
                    cur_h = hashlib.sha256(target_f.read_bytes()).hexdigest()
                    if cur_h != exp_hash:
                        frozen_corrupted.append(f"快照文件哈希不匹配：{rel_p}")
    except Exception:
        frozen_exists = False

    # 计算项目当前文档内容摘要（CRLF 归一化）
    current_docs = []
    if content_root.is_dir():
        for p in sorted(content_root.rglob("*.md")):
            if p.is_file() and ".state" not in p.parts:
                current_docs.append((p.relative_to(content_root).as_posix(), p.read_text(encoding="utf-8")))
    current_content_hash = compute_project_content_hash(current_docs)

    # 5. 签审确认绑定核查
    r_store = ReviewStore(state_dir)
    signoff_checks = []
    signoff_issues = []
    for s in r_store.signoffs():
        entry = {
            "signoffId": s.signoff_id,
            "author": s.author,
            "role": s.role,
            "createdAt": s.created_at,
            "contentHash": s.content_hash,
            "baselineId": s.baseline_id,
            "status": "valid",
            "reason": "",
        }
        if not s.content_hash:
            entry["status"] = "unverified"
            entry["reason"] = "缺少内容指纹绑定，无法核实对当前内容的确认"
            signoff_issues.append(f"签审确认未满足：{s.author} ({s.role}) - 缺少内容指纹绑定")
        elif s.content_hash != current_content_hash:
            entry["status"] = "stale"
            entry["reason"] = "内容已发生变更，原确认需复核"
            signoff_issues.append(f"签审确认已失效：{s.author} ({s.role}) - 内容已发生变更，原确认需复核")
        signoff_checks.append(entry)

    issues = list(conflicts) + signoff_issues
    if not rev_ver:
        issues.append(f"修订记录文件不存在或未找到有效数据行：{rev_file}")
    if not frozen_exists:
        issues.append(f"版本 {manifest_ver} 未找到本地冻结基线（.state/baselines/{manifest_ver}.json）")
    if frozen_corrupted:
        issues.extend(frozen_corrupted)

    has_conflict = len(conflicts) > 0
    status = "passed"
    if has_conflict:
        status = "conflict"
    elif issues:
        status = "incomplete"

    return {
        "projectId": manifest.projectId,
        "projectRoot": project_root.as_posix(),
        "documentNo": document_no,
        "documentName": document_name,
        "manifestVersion": manifest_ver,
        "revisionRecordVersion": rev_ver,
        "revisionRecordLine": rev_line,
        "declaredVersions": declared_matches,
        "frozenBaseline": {
            "exists": frozen_exists,
            "version": manifest_ver if frozen_exists else "",
            "corrupted": frozen_corrupted,
            "frozenAt": frozen_metadata.get("frozenAt", "") if frozen_metadata else "",
        },
        "currentContentHash": current_content_hash,
        "signoffs": signoff_checks,
        "conflict": has_conflict,
        "issues": issues,
        "status": status,
    }


_SKIP_DISCOVERY_DIRS = {
    ".git", ".state", "output", "tmp", "node_modules", "__pycache__", ".venv", ".pytest_cache"
}


def _discover_project_roots(root: Path, max_depth: int = 3) -> List[Path]:
    """在指定目录下递归发现包含 project.yml 的文档工程目录（最多向下 max_depth 层）。"""
    if (root / "project.yml").is_file():
        return [root]
    found: List[Path] = []

    def _walk(cur: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(cur.iterdir())
        except OSError:
            return
        for sub in children:
            if not sub.is_dir() or sub.name in _SKIP_DISCOVERY_DIRS or sub.name.startswith("."):
                continue
            if (sub / "project.yml").is_file():
                found.append(sub)
            else:
                _walk(sub, depth + 1)

    _walk(root, 1)
    return found


def check_baselines(
    root: Path,
    *,
    declare_files: Optional[Sequence[Path]] = None,
    workspace: bool = False,
) -> Dict[str, Any]:
    """统一基线核对服务，支持单项目、多级目录集合或工作区成员批量核对。"""
    projects_to_check = []
    if workspace:
        if (root / "workspace.yml").is_file():
            from doc_tool.application.workspace import load_workspace

            space = load_workspace(root)
            for member in space.valid_members:
                p_root = space.member_project_root(member)
                if p_root is not None and (p_root / "project.yml").is_file():
                    projects_to_check.append(p_root)
        else:
            projects_to_check.extend(_discover_project_roots(root))
    else:
        projects_to_check.extend(_discover_project_roots(root))

    if not projects_to_check:
        from doc_tool.domain.version import get_tool_metadata
        return {
            "schemaVersion": 1,
            "command": "baseline-check",
            "tool": get_tool_metadata(),
            "root": root.as_posix(),
            "projects": [],
            "conflict": False,
            "issues": [f"在指定路径下未找到有效的文档项目（缺少 project.yml）：{root}"],
            "status": "error",
            "exitCode": 2,
        }

    results = []
    any_conflict = False
    all_passed = True

    for p in projects_to_check:
        res = check_project_baseline(p, declare_files=declare_files)
        results.append(res)
        if res.get("conflict"):
            any_conflict = True
        if res.get("status") != "passed":
            all_passed = False

    overall_status = "passed"
    exit_code = 0
    if any_conflict:
        overall_status = "conflict"
        exit_code = 1
    elif not all_passed:
        overall_status = "incomplete"
        exit_code = 1

    from doc_tool.domain.version import get_tool_metadata

    return {
        "schemaVersion": 1,
        "command": "baseline-check",
        "tool": get_tool_metadata(),
        "root": root.as_posix(),
        "workspace": workspace,
        "projects": results,
        "conflict": any_conflict,
        "allPassed": all_passed,
        "status": overall_status,
        "exitCode": exit_code,
    }
