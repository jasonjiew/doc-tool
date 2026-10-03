# -*- coding: utf-8 -*-
"""RD 研发工作区界面薄适配层（RD-A 1.4）。

只把既有工作区/概览/设置/稳定条目/关系/矩阵/影响/集合服务的返回值转成界面行、
统一来源定位与可执行下一步。本模块只读，不复制覆盖率算法，不新增第二套清单
语义，也不写业务文件；所有写动作仍由既有服务完成。

来源可信原则：身份用 ``projectId + itemId``，编号只负责展示；定位不到时保留
原始记录并给出原因，界面不得按编号猜测位置，也不得把缓冲或捕获内容当作已保存
状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from doc_tool.domain.version import can_read_schema, can_write_schema

#: 来源标签：界面必须区分“已保存内容 / 当前编辑缓冲 / CORE 捕获”。
SOURCE_SAVED = "saved"
SOURCE_BUFFER = "buffer"
SOURCE_CAPTURE = "capture"

SOURCE_LABELS = {
    SOURCE_SAVED: "已保存版本",
    SOURCE_BUFFER: "当前编辑缓冲（未保存）",
    SOURCE_CAPTURE: "CORE 捕获",
}

ROLE_LABELS = {
    "requirement": "需求",
    "design": "设计",
    "test": "测试",
    "other": "其他",
}

KIND_LABELS = {
    "requirement": "需求条目",
    "design": "设计条目",
    "test": "测试条目",
}

#: 与 ``content.relations.RELATION_TYPES`` 保持一致，避免界面出现服务不接受的关系类型。
RELATION_TYPE_LABELS = {
    "satisfies": "满足（设计→需求）",
    "verifies": "验证（测试→需求/设计）",
    "depends_on": "依赖",
}

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_PENDING = "pending"


def role_label(role: str) -> str:
    return ROLE_LABELS.get(str(role or ""), str(role or "未声明角色"))


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(str(kind or ""), str(kind or "条目"))


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(str(source or ""), "未知来源")


def relation_type_label(type_: str) -> str:
    return RELATION_TYPE_LABELS.get(str(type_ or ""), str(type_ or "关系"))


def percent_text(value: Optional[float]) -> str:
    """覆盖率展示：无需求分母时为 N/A，绝不显示虚构的 0% 或 100%。"""
    if value is None:
        return "N/A"
    try:
        return "{0:.1f}%".format(float(value) * 100)
    except (TypeError, ValueError):
        return "N/A"


@dataclass
class SourceLocation:
    """统一来源定位结果（身份是 projectId + itemId，编号只用于展示）。"""

    projectId: str = ""
    itemId: str = ""
    relPath: str = ""
    lineNo: int = 0
    headingNo: str = ""
    memberRole: str = ""
    memberName: str = ""
    memberPath: str = ""
    memberVersion: str = ""
    source: str = SOURCE_SAVED
    ok: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "projectId": self.projectId,
            "itemId": self.itemId,
            "relPath": self.relPath,
            "lineNo": self.lineNo,
            "headingNo": self.headingNo,
            "memberRole": self.memberRole,
            "memberName": self.memberName,
            "memberPath": self.memberPath,
            "memberVersion": self.memberVersion,
            "source": self.source,
            "sourceLabel": source_label(self.source),
            "ok": self.ok,
            "reason": self.reason,
        }

    def describe(self) -> str:
        if not self.ok:
            return "无法定位：{0}".format(self.reason or "来源不可用")
        parts = [self.memberName or self.memberPath or "当前项目"]
        if self.relPath:
            parts.append(self.relPath)
        if self.lineNo:
            parts.append("第 {0} 行".format(self.lineNo))
        if self.headingNo:
            parts.append("章节 {0}".format(self.headingNo))
        parts.append(source_label(self.source))
        return " · ".join(parts)


@dataclass
class SurfaceRow:
    """界面行通用外壳：稳定 key + 状态 + 来源位置 + 可执行动作。"""

    key: str
    label: str
    detail: str = ""
    status: str = STATUS_OK
    source: str = SOURCE_SAVED
    location: Optional[SourceLocation] = None
    actions: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "detail": self.detail,
            "status": self.status,
            "source": self.source,
            "sourceLabel": source_label(self.source),
            "location": self.location.to_dict() if self.location is not None else None,
            "actions": list(self.actions),
        }

# ---------------------------------------------------------------------------
# 工作区与成员
# ---------------------------------------------------------------------------


def _content_root(member_root: Path) -> Optional[Path]:
    """成员项目的正文章节目录；不可读时返回 None（不阻断其他成员）。"""
    try:
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(member_root)
        return member_root / manifest.relative_content_root()
    except Exception:  # noqa: BLE001 - 单个成员不可读不影响其他成员
        return None


def unsaved_chapters(member_root: Path, buffers: Mapping[str, str]) -> List[str]:
    """该成员中带未保存缓冲的章节（按真实文件存在性归属，不猜测）。"""
    if not buffers:
        return []
    root = _content_root(member_root)
    if root is None:
        return []
    found = []
    for rel_path in buffers:
        candidate = root / str(rel_path).replace("\\", "/")
        if candidate.is_file():
            found.append(str(rel_path).replace("\\", "/"))
    return sorted(found)


def member_rows(workspace, *, buffers: Optional[Mapping[str, str]] = None) -> List[dict]:
    """工作区成员行：区分缺失、只读、未保存缓冲与可执行下一步。"""
    buffers = buffers or {}
    error_paths = {issue.relative_path for issue in getattr(workspace, "issues", [])}
    rows: List[dict] = []
    for member in getattr(workspace, "members", []):
        issue = next(
            (item for item in getattr(workspace, "issues", []) if item.relative_path == member.relative_path),
            None,
        )
        root = workspace.member_project_root(member) if hasattr(workspace, "member_project_root") else None
        exists = bool(root is not None and root.is_dir())
        schema = int(getattr(member, "schema_version", 0) or 0)
        writable = can_write_schema(schema) if schema else False
        readable = can_read_schema(schema) if schema else False
        available = exists and member.relative_path not in error_paths
        if not exists:
            status = STATUS_ERROR
            reason = "成员目录不存在（可能已移动或删除）"
            next_action = "重新定位"
        elif member.relative_path in error_paths:
            status = STATUS_ERROR
            reason = issue.reason if issue is not None else "成员不可用"
            next_action = "重新定位"
        elif schema and not writable:
            status = STATUS_WARNING
            reason = "模式版本 v{0} 高于当前可写版本：只读打开，禁止写入".format(schema)
            next_action = "只读打开"
        elif not schema:
            status = STATUS_WARNING
            reason = "未能读取成员模式版本，写入前需重新校验"
            next_action = "打开成员"
        else:
            status = STATUS_OK
            reason = ""
            next_action = "打开成员"
        pending = unsaved_chapters(root, buffers) if root is not None else []
        rows.append({
            "key": member.relative_path,
            "role": member.role,
            "roleLabel": role_label(member.role),
            "name": member.name or Path(member.relative_path).name,
            "path": member.relative_path,
            "projectId": member.project_id,
            "documentVersion": member.document_version,
            "schemaVersion": schema,
            "available": available,
            "readonly": bool(available and schema and not writable),
            "canRead": bool(exists and readable),
            "unsavedChapters": pending,
            "hasUnsaved": bool(pending),
            "status": status,
            "reason": reason,
            "nextAction": next_action,
            "location": SourceLocation(
                projectId=member.project_id, relPath=member.relative_path,
                memberRole=member.role, memberName=member.name,
                memberPath=member.relative_path, memberVersion=member.document_version,
                ok=available, reason=reason,
            ).to_dict(),
        })
    return rows


def workspace_state(workspace) -> dict:
    """工作区头部状态：身份、集合版本、角色分布与覆盖率适用性。"""
    if workspace is None:
        return {
            "loaded": False, "name": "", "workspaceId": "", "collectionVersion": "",
            "roles": {}, "memberCount": 0, "coverage": "N/A", "issues": [],
            "independentOpenAllowed": True,
            "message": "未打开工作区：单文档可直接编辑与出稿。",
        }
    roles = workspace.roles() if hasattr(workspace, "roles") else {}
    has_requirement = workspace.has_requirement() if hasattr(workspace, "has_requirement") else False
    return {
        "loaded": True,
        "name": getattr(workspace, "name", "") or "(未命名)",
        "workspaceId": getattr(workspace, "workspace_id", ""),
        "collectionVersion": getattr(workspace, "collection_version", "1.0"),
        "schemaVersion": getattr(workspace, "schema_version", 1),
        "roles": {role_label(key): value for key, value in roles.items()},
        "memberCount": len(getattr(workspace, "members", [])),
        "coverage": "applicable" if has_requirement else "N/A",
        "hasRequirement": bool(has_requirement),
        "issues": [issue.to_dict() for issue in getattr(workspace, "issues", [])],
        "independentOpenAllowed": True,
        "root": str(getattr(workspace, "root", "") or ""),
        "message": "" if has_requirement else "未包含需求文档：覆盖率以 N/A 呈现，不阻断编辑与出稿。",
    }


def open_workspace(project_root) -> Tuple[Optional[object], str]:
    """读取工作区：``(workspace, message)``；缺失或不可读时返回 ``(None, 原因)``。"""
    from doc_tool.application.workspace import load_workspace

    try:
        return load_workspace(project_root), ""
    except Exception as exc:  # noqa: BLE001 - 无工作区不是错误，只影响工作区视图
        return None, str(exc)


# ---------------------------------------------------------------------------
# 概览与设置
# ---------------------------------------------------------------------------


def overview_view(project_root) -> dict:
    """项目概览：版本、规范来源、结果过期与可执行下一步（服务真值）。"""
    from doc_tool.application.overview import build_overview

    try:
        overview = build_overview(project_root)
    except Exception as exc:  # noqa: BLE001 - 坏项目只影响概览展示
        return {"ok": False, "message": "概览不可用：{0}".format(exc), "sections": [], "nextActions": []}
    payload = overview.to_dict()
    payload["ok"] = True
    payload["blockingCount"] = overview.blocking_count
    payload["pendingReviewCount"] = overview.pending_review_count
    payload["checkStale"] = overview.check_stale
    payload["message"] = ""
    return payload


def settings_groups(model) -> List[dict]:
    """按既有设置字段模型分组，供界面渐进展开（不重写配置结构）。"""
    if model is None:
        return []
    groups = []
    for section, fields in (getattr(model, "sections", {}) or {}).items():
        groups.append({
            "section": section,
            "writable": bool(getattr(model, "writable", False)),
            "fields": [item.to_dict() for item in fields],
        })
    return groups


def settings_field_rows(model, section: str) -> List[dict]:
    """某一分组的字段行；字段错误由保存结果按 key 定位回来。"""
    fields = (getattr(model, "sections", {}) or {}).get(section, [])
    return [item.to_dict() for item in fields]


def settings_group_payload(section: str, values: Mapping[str, object]) -> Dict[str, object]:
    """把界面某一分组的值映射成 ``save_settings`` 的实际载荷。

    只提交当前分组：其他分组的既有配置不进入载荷，因此不会被重写。
    """
    data = dict(values or {})
    if section == "变量":
        return {"variables": {str(key): str(value) for key, value in data.items()}}
    if section == "术语":
        return {"terms": list(data.get("terms") or [])}
    if section == "规则":
        return {"rules": list(data.get("rules") or [])}
    if section == "基本信息":
        return {
            key: data[key]
            for key in ("documentName", "documentNo", "documentVersion", "documentKind")
            if key in data
        }
    if section == "样式":
        return {key: value for key, value in data.items() if key == "bodyStyle" or key.startswith("heading")}
    if section == "门禁":
        return {"qualitySource": data.get("qualitySource", "")}
    return {key: value for key, value in data.items() if key != "schemaVersion"}

# ---------------------------------------------------------------------------
# 稳定条目与关系
# ---------------------------------------------------------------------------


def build_index(documents: Sequence[Tuple[str, str]], *, project_id: str = ""):
    """从 ``(rel_path, text)`` 文档序列建立稳定条目索引（复用既有服务）。"""
    from doc_tool.application.content.traceable_items import build_item_index

    return build_item_index(list(documents or []), project_id=project_id)


def member_lookup(workspace, *, buffers: Optional[Mapping[str, str]] = None) -> Dict[str, dict]:
    """``projectId -> 成员信息``；用于把条目身份翻译成真实文件与角色。"""
    lookup: Dict[str, dict] = {}
    for row in member_rows(workspace, buffers=buffers) if workspace is not None else []:
        if row.get("projectId"):
            lookup[str(row["projectId"])] = row
    return lookup


def item_rows(index, *, project_id: str = "") -> List[dict]:
    """稳定条目行：编号只展示，身份是 projectId + itemId；标明重复与位置。"""
    items = getattr(index, "items", {}) or {}
    locations = getattr(index, "locations", {}) or {}
    duplicates = set()
    try:
        duplicates = {tuple(pair) for pair in index.duplicates()}
    except Exception:  # noqa: BLE001 - 重复检测失败不影响列出条目
        duplicates = set()
    rows: List[dict] = []
    for key, ref in items.items():
        if project_id and ref.project_id != project_id:
            continue
        places = [
            {
                "relPath": place.rel_path,
                "lineNo": place.line_no,
                "headingNo": place.heading_no,
            }
            for place in locations.get(key, [])
        ]
        rows.append({
            "key": "{0}:{1}".format(ref.project_id, ref.item_id),
            "projectId": ref.project_id,
            "itemId": ref.item_id,
            "kind": ref.kind,
            "kindLabel": kind_label(ref.kind),
            "alias": ref.alias,
            "marker": ref.render(),
            "locations": places,
            "duplicate": tuple(key) in duplicates,
            "status": STATUS_WARNING if tuple(key) in duplicates else STATUS_OK,
        })
    rows.sort(key=lambda row: (row["kind"], row["itemId"]))
    return rows


def item_issues(index) -> List[dict]:
    """条目索引问题（重复 ID、标记异常）：保留原始记录供界面定位。"""
    return [issue.to_dict() for issue in getattr(index, "issues", []) or []]


def endpoint_options(index, *, members: Optional[Mapping[str, dict]] = None,
                     source: str = SOURCE_SAVED) -> List[dict]:
    """双端检索候选项：显示成员、章节、摘要与真实来源，不按编号猜测关系。"""
    members = members or {}
    options: List[dict] = []
    for row in item_rows(index):
        member = members.get(row["projectId"], {})
        place = (row["locations"] or [{}])[0]
        options.append({
            "key": row["key"],
            "projectId": row["projectId"],
            "itemId": row["itemId"],
            "kind": row["kind"],
            "kindLabel": row["kindLabel"],
            "alias": row["alias"],
            "marker": row["marker"],
            "memberRole": member.get("role", ""),
            "memberRoleLabel": member.get("roleLabel", ""),
            "memberName": member.get("name", "") or row["projectId"],
            "relPath": place.get("relPath", ""),
            "lineNo": place.get("lineNo", 0),
            "headingNo": place.get("headingNo", ""),
            "source": source,
            "sourceLabel": source_label(source),
            "searchText": " ".join(filter(None, [
                row["itemId"], row["alias"], row["kindLabel"],
                member.get("name", ""), member.get("roleLabel", ""),
                str(place.get("relPath", "")), str(place.get("headingNo", "")),
            ])),
        })
    return options


def relation_type_options() -> List[dict]:
    """关系类型选项：直接来自关系服务的合法类型集合。"""
    from doc_tool.application.content.relations import RELATION_TYPES

    return [
        {"type": name, "label": RELATION_TYPE_LABELS.get(name, name)}
        for name in RELATION_TYPES
    ]


def relation_rows(graph, index=None, *, members: Optional[Mapping[str, dict]] = None) -> List[dict]:
    """关系行：显示真实双端来源与类型；悬空端点在界面标注但不隐藏记录。"""
    members = members or {}
    broken = {
        issue.relation_id
        for issue in getattr(graph, "issues", []) or []
        if getattr(issue, "severity", "") == "error"
    }
    rows: List[dict] = []
    for relation in getattr(graph, "relations", []):
        source = relation.source
        target = relation.target
        rows.append({
            "key": relation.relation_id,
            "relationId": relation.relation_id,
            "type": relation.type,
            "typeLabel": relation_type_label(relation.type),
            "note": relation.note,
            "source": source.to_dict(),
            "target": target.to_dict(),
            "sourceLabel": endpoint_display(source, index, members),
            "targetLabel": endpoint_display(target, index, members),
            "sourceLocation": locate_endpoint(source, index, members, project_id=source.project_id).to_dict(),
            "targetLocation": locate_endpoint(target, index, members, project_id=target.project_id).to_dict(),
            "status": STATUS_ERROR if relation.relation_id in broken else STATUS_OK,
            "reason": "端点缺失或无效" if relation.relation_id in broken else "",
        })
    return rows


def endpoint_from(key) -> object:
    """``(projectId, itemId)`` → 关系端点对象（影响报告使用键元组）。"""
    from doc_tool.application.content.relations import Endpoint

    if hasattr(key, "project_id"):
        return key
    project_id, item_id = (list(key) + ["", ""])[:2]
    return Endpoint(str(project_id or ""), str(item_id or ""))


def endpoint_display(endpoint, index=None, members: Optional[Mapping[str, dict]] = None) -> str:
    """双端展示文本：``成员/角色 · 类型 · 编号（别名）``。"""
    members = members or {}
    member = members.get(endpoint.project_id, {})
    parts = []
    if member:
        parts.append("{0}{1}".format(
            member.get("roleLabel", ""), "·" if member.get("roleLabel") else "",
        ) + str(member.get("name", "")))
    if index is not None:
        ref = index.get(endpoint.project_id, endpoint.item_id)
        if ref is not None:
            parts.append("{0} {1}".format(kind_label(ref.kind), ref.item_id))
            if ref.alias:
                parts.append("（{0}）".format(ref.alias))
            return " ".join(part for part in parts if part)
    if not member:
        parts.append(endpoint.project_id or "(未知项目)")
    parts.append(endpoint.item_id or "(未知条目)")
    return " ".join(part for part in parts if part)


def locate_endpoint(endpoint, index, members: Optional[Mapping[str, dict]] = None,
                    *, project_id: str = "", source: str = SOURCE_SAVED) -> SourceLocation:
    """定位某个关系端点；定位失败保留原因，不猜测位置。"""
    members = members or {}
    member = members.get(endpoint.project_id or project_id, {})
    locations = locate_sources(
        endpoint.item_id, index, project_id=endpoint.project_id or project_id,
        members=members, source=source,
    )
    if not locations:
        return SourceLocation(
            projectId=endpoint.project_id or project_id,
            itemId=endpoint.item_id,
            memberRole=member.get("role", ""),
            memberName=member.get("name", ""),
            memberPath=member.get("path", ""),
            source=source, ok=False,
            reason="条目不在当前索引中（可能只在未保存缓冲或已删除）",
        )
    return locations[0]


def locate_sources(item_id: str, index, *, project_id: str = "",
                   members: Optional[Mapping[str, dict]] = None,
                   source: str = SOURCE_SAVED) -> List[SourceLocation]:
    """按条目 ID 定位真实来源（复用既有 locate_item，不自行匹配编号）。"""
    from doc_tool.application.content.trace_matrix import locate_item

    members = members or {}
    if index is None:
        return []
    found: List[SourceLocation] = []
    for place in locate_item(item_id, index, project_id=project_id):
        member = members.get(place.get("projectId", ""), {})
        found.append(SourceLocation(
            projectId=place.get("projectId", ""),
            itemId=place.get("itemId", item_id),
            relPath=place.get("relPath", ""),
            lineNo=int(place.get("lineNo", 0) or 0),
            headingNo=place.get("headingNo", ""),
            memberRole=member.get("role", ""),
            memberName=member.get("name", ""),
            memberPath=member.get("path", ""),
            memberVersion=member.get("documentVersion", ""),
            source=source,
            ok=True,
        ))
    return found


def endpoints_needing_save(saved_index, source_key: Tuple[str, str],
                           target_key: Tuple[str, str]) -> List[dict]:
    """双端中只存在于未保存缓冲的端点（用于“仅保存相关两端”动作）。

    ``saved_index`` 必须只用**已保存内容**建立：同章节的缓冲修改会让条目在
    磁盘上不存在，因此不能按“章节路径已保存”放行。
    """
    items = getattr(saved_index, "items", {}) or {}
    locations = getattr(saved_index, "locations", {}) or {}
    pending = []
    for key in (tuple(source_key), tuple(target_key)):
        if key not in items or not locations.get(key):
            pending.append({"projectId": key[0], "itemId": key[1]})
    return pending


def item_action_rows(index, *, rel_path: str = "") -> List[dict]:
    """当前文档可执行条目动作（声明/复制/改编号），供界面按钮直接绑定。"""
    rows = []
    for item in item_rows(index):
        places = item.get("locations") or []
        belongs = any(place.get("relPath") == rel_path for place in places) if rel_path else bool(places)
        if not belongs:
            continue
        rows.append({
            "itemId": item["itemId"], "kind": item["kind"], "kindLabel": item["kindLabel"],
            "alias": item["alias"], "lineNo": (places[0].get("lineNo") if places else 0),
            "relPath": (places[0].get("relPath") if places else ""),
            "duplicate": item["duplicate"],
        })
    return rows

# ---------------------------------------------------------------------------
# 矩阵与影响复核
# ---------------------------------------------------------------------------


def matrix_view(items, graph, *, page: int = 1, page_size: int = 20,
                only_uncovered: bool = False,
                pending_review_items=None, confirmed_items=None,
                index=None, members: Optional[Mapping[str, dict]] = None,
                source: str = SOURCE_CAPTURE) -> dict:
    """矩阵/覆盖率视图：显式需求分母、直接/间接覆盖、N/A 与来源定位。"""
    from doc_tool.application.content.trace_matrix import build_coverage, build_matrix_page

    report = build_coverage(
        list(items or []), graph,
        pending_review_items=pending_review_items,
        confirmed_items=confirmed_items,
    )
    page_obj = build_matrix_page(
        report, page=page, page_size=page_size, only_uncovered=only_uncovered,
    )
    rows = []
    for row in page_obj.rows:
        payload = row.to_dict()
        payload["sourceLocation"] = locate_endpoint(
            row.item, index, members, project_id=getattr(row.item, "project_id", ""), source=source,
        ).to_dict() if index is not None else None
        payload["sourceLabel"] = endpoint_display(row.item, index, members)
        rows.append(payload)
    payload = page_obj.to_dict()
    payload["rows"] = rows
    return {
        "ok": True,
        "applicable": report.applicable,
        "totalRequirements": report.total_requirements,
        "linked": report.linked,
        "pendingReview": report.pending_review,
        "coverage": {
            "design": percent_text(report.design_coverage),
            "test": percent_text(report.test_coverage),
            "direct": percent_text(report.direct_coverage),
            "review": percent_text(report.review_coverage),
        },
        "metrics": [
            {"key": "total", "label": "需求条目（显式分母）", "value": str(report.total_requirements)},
            {"key": "design", "label": "设计覆盖", "value": percent_text(report.design_coverage)},
            {"key": "test", "label": "测试覆盖（含间接）", "value": percent_text(report.test_coverage)},
            {"key": "direct", "label": "直接测试覆盖", "value": percent_text(report.direct_coverage)},
            {"key": "review", "label": "已复核覆盖", "value": percent_text(report.review_coverage)},
        ],
        "report": report.to_dict(),
        "page": payload,
        "uncovered": [ref.to_dict() for ref in report.uncovered],
        "uncoveredDesign": [ref.to_dict() for ref in report.uncovered_design],
        "orphans": [ref.to_dict() for ref in list(report.design_orphans) + list(report.test_orphans)],
        "dangling": list(report.dangling),
        "message": "" if report.applicable else "未声明需求条目：覆盖率为 N/A（不显示 0% 或 100%）。",
    }


def matrix_report_text(items, graph, *, fmt: str = "markdown",
                       pending_review_items=None, confirmed_items=None) -> str:
    """与 CLI 同源的矩阵报告文本（用于界面导出/对照）。"""
    from doc_tool.application.content.trace_matrix import build_coverage, export_report

    report = build_coverage(
        list(items or []), graph,
        pending_review_items=pending_review_items, confirmed_items=confirmed_items,
    )
    return export_report(report, fmt)


def impact_view(before, after, graph, *, known_items=None, max_depth: int = 8,
                store=None, hashes: Optional[Mapping] = None,
                spec_before=None, spec_after=None,
                index=None, members: Optional[Mapping[str, dict]] = None,
                source: str = SOURCE_SAVED) -> dict:
    """变化与影响路径：标明已保存或缓冲来源，复核状态沿用既有记录服务。"""
    from doc_tool.application.content.impact import compute_impact, diff_snapshots

    changed, spec_changes = diff_snapshots(
        dict(before or {}), dict(after or {}),
        spec_before=spec_before, spec_after=spec_after,
    )
    report = compute_impact(changed, graph, known_items=known_items, max_depth=max_depth)
    payload = report.to_dict()
    entries = []
    for entry in list(report.direct) + list(report.transitive):
        item = entry.to_dict()
        source_endpoint = endpoint_from(entry.source)
        target_endpoint = endpoint_from(entry.target)
        item["sourceLabel"] = endpoint_display(source_endpoint, index, members)
        item["targetLabel"] = endpoint_display(target_endpoint, index, members)
        item["sourceRef"] = {"projectId": source_endpoint.project_id, "itemId": source_endpoint.item_id}
        item["targetRef"] = {"projectId": target_endpoint.project_id, "itemId": target_endpoint.item_id}
        item["sourceLocation"] = locate_endpoint(
            source_endpoint, index, members, project_id=source_endpoint.project_id, source=source,
        ).to_dict() if index is not None else None
        item["targetLocation"] = locate_endpoint(
            target_endpoint, index, members, project_id=target_endpoint.project_id, source=source,
        ).to_dict() if index is not None else None
        entries.append(item)
    payload["entries"] = entries
    payload["specChanges"] = list(spec_changes or [])
    payload["changed"] = {"{0}:{1}".format(key[0], key[1]): value for key, value in changed.items()}
    # 只有调用方给出真实当前摘要时才判断“已变化待重检”，否则只列记录。
    payload["review"] = review_rows(store, dict(hashes) if hashes is not None else None)
    payload["ok"] = True
    payload["source"] = source
    payload["sourceLabel"] = source_label(source)
    payload["message"] = "" if changed else "当前比较范围内没有内容变化。"
    return payload


def review_rows(store, hashes: Optional[Mapping] = None) -> dict:
    """复核记录：待复核与过期项分开呈现，不自动升级为通过。"""
    if store is None:
        return {"available": False, "records": [], "pending": [], "stale": [],
                "message": "未启用版本化复核记录。"}
    try:
        records = [record.to_dict() for record in store.records()]
        pending = [record.to_dict() for record in store.pending()]
        stale = [record.to_dict() for record in store.stale_relations(dict(hashes or {}))] if hashes is not None else []
    except Exception as exc:  # noqa: BLE001 - 坏记录只影响复核视图
        return {"available": False, "records": [], "pending": [], "stale": [],
                "message": "复核记录不可用：{0}".format(exc)}
    return {
        "available": True,
        "records": records,
        "pending": pending,
        "stale": stale,
        "message": "待复核 {0} 条；已变化待重检 {1} 条。".format(len(pending), len(stale)),
    }


# ---------------------------------------------------------------------------
# 版本集合与成果
# ---------------------------------------------------------------------------


def collection_rows(root) -> dict:
    """版本集合列表：只读清单，不按目录名推断正式成功。"""
    from doc_tool.application.collection_ops import list_baselines

    try:
        baselines = list_baselines(root)
    except Exception as exc:  # noqa: BLE001 - 集合目录缺失只影响集合视图
        return {"ok": False, "rows": [], "message": "集合列表不可用：{0}".format(exc)}
    rows = []
    for summary in baselines:
        payload = summary.to_dict()
        payload["status"] = STATUS_OK if payload.get("complete") else STATUS_WARNING
        payload["statusLabel"] = "完整" if payload.get("complete") else "部分/历史清单"
        rows.append(payload)
    return {
        "ok": True,
        "rows": rows,
        "message": "" if rows else "尚无版本集合：可先对当前工作区执行一次版本集合捕获。",
    }


def collection_detail(root, manifest_path) -> dict:
    """集合详情：分类、缺失、校验问题与可打开成果。"""
    from doc_tool.application.collection_ops import describe_baseline

    try:
        detail = describe_baseline(manifest_path, root=root)
    except Exception as exc:  # noqa: BLE001 - 坏清单只影响详情
        return {"ok": False, "message": "集合详情不可用：{0}".format(exc), "categories": {}, "artifacts": []}
    payload = detail.to_dict()
    payload["ok"] = True
    payload["message"] = ""
    return payload


def collection_compare(left, right) -> dict:
    """两份集合比较：变化分组与来源。"""
    from doc_tool.application.collection_ops import compare_baselines

    try:
        report = compare_baselines(left, right)
    except Exception as exc:  # noqa: BLE001 - 比较失败只影响比较结果
        return {"ok": False, "message": "集合比较不可用：{0}".format(exc), "entries": []}
    payload = report.to_dict()
    payload["ok"] = True
    payload["groups"] = {key: [item.to_dict() for item in value] for key, value in report.by_group().items()}
    payload["message"] = ""
    return payload


def collection_export_package(root, manifest_path, destination) -> dict:
    """导出集合包：``(zip, warnings)`` 转为界面结果。

    ``destination`` 可以是 ZIP 文件路径；若是目录，则按集合版本生成安全文件名。
    """
    from doc_tool.application.collection_ops import export_package

    target = Path(destination)
    if target.is_dir():
        version = ""
        try:
            from doc_tool.application.collection import load_manifest

            version = str(load_manifest(manifest_path).version or "")
        except Exception:  # noqa: BLE001 - 版本不可读时用通用名称
            version = ""
        safe = "".join(char for char in version if char.isalnum() or char in "._-") or "collection"
        target = target / "{0}-collection.zip".format(safe)
    try:
        path, warnings = export_package(root, manifest_path, target)
    except Exception as exc:  # noqa: BLE001 - 导出失败保留原集合
        return {"ok": False, "path": "", "warnings": [str(exc)], "message": "导出包失败：{0}".format(exc)}
    return {
        "ok": bool(path), "path": str(path or ""), "warnings": list(warnings or []),
        "message": "已导出集合包。" if path else "导出包未生成。",
    }


def collection_recover(root, manifest_path, destination, *, overwrite: bool = False) -> dict:
    """恢复为副本：只生成新目录，缺失/校验不符分类返回，不覆盖当前工作区。"""
    from doc_tool.application.collection_ops import recover_baseline

    try:
        result = recover_baseline(root, manifest_path, destination, overwrite=overwrite)
    except Exception as exc:  # noqa: BLE001 - 恢复失败保留原集合
        return {"ok": False, "message": "恢复失败：{0}".format(exc), "recovered": [], "missing": []}
    payload = dict(result or {})
    payload["ok"] = True
    payload.setdefault("message", "已恢复为副本。")
    return payload


def locate_current_chapter(manifest, current_rel_path: str) -> SourceLocation:
    """当前章节的来源位置（单文档主流程与工作区共用同一模型）。"""
    rel = str(current_rel_path or "").replace("\\", "/")
    if not rel:
        return SourceLocation(ok=False, reason="当前没有打开的章节")
    project_id = ""
    try:
        project_id = str(getattr(manifest, "projectId", "") or "")
    except Exception:  # noqa: BLE001 - 清单缺失不影响定位展示
        project_id = ""
    return SourceLocation(projectId=project_id, relPath=rel, source=SOURCE_BUFFER, ok=True)

# ---------------------------------------------------------------------------
# 与 CLI 同源的文档/图/快照收集（RD-D 4.2）
# ---------------------------------------------------------------------------


def project_documents(project_root) -> List[Tuple[str, str]]:
    """项目内全部 Markdown，路径与编辑器一致（相对文档类型目录）。

    CLI ``_project_documents`` 返回相对 ``content`` 的路径；界面/编辑器使用相对
    ``content/<documentType>`` 的路径，这里统一成后者，避免同一章节出现两种身份。
    """
    from doc_tool.cli import _project_documents

    try:
        documents = list(_project_documents(Path(project_root)))
    except Exception:  # noqa: BLE001 - 不可读项目不阻断其他成员
        return []
    prefix = ""
    try:
        from doc_tool.domain.manifest import ProjectManifest

        document_type = str(ProjectManifest.load(Path(project_root)).documentType or "")
        prefix = (document_type + "/") if document_type else ""
    except Exception:  # noqa: BLE001 - 清单不可读时保留原始相对路径
        prefix = ""
    rows: List[Tuple[str, str]] = []
    for rel_path, text in documents:
        key = str(rel_path).replace("\\", "/")
        if prefix and key.startswith(prefix):
            key = key[len(prefix):]
        rows.append((key, text))
    return rows


def snapshot_from_text(rel_path: str, text: str):
    """从 Markdown 提取条目快照（字段级，与 CLI ``_snapshot_from_text`` 同源）。"""
    from doc_tool.cli import _snapshot_from_text

    return _snapshot_from_text(rel_path, text)


def documents_with_buffers(saved: Sequence[Tuple[str, str]],
                           buffers: Optional[Mapping[str, str]] = None):
    """把未保存缓冲覆盖到已保存文档上，并标明每条文档的实际来源。"""
    buffers = buffers or {}
    rows: List[dict] = []
    seen = set()
    for rel_path, text in saved or []:
        key = str(rel_path).replace("\\", "/")
        seen.add(key)
        if key in buffers:
            rows.append({"relPath": key, "text": buffers[key], "source": SOURCE_BUFFER})
        else:
            rows.append({"relPath": key, "text": text, "source": SOURCE_SAVED})
    for key, text in buffers.items():
        norm = str(key).replace("\\", "/")
        if norm not in seen:
            rows.append({"relPath": norm, "text": text, "source": SOURCE_BUFFER})
    return rows


def combined_index(entries: Sequence[Tuple[str, Sequence[Tuple[str, str]]]]):
    """合并多成员索引：身份仍是 ``projectId + itemId``，不去重跨项目同号条目。"""
    from doc_tool.application.content.traceable_items import ItemIndex

    merged = ItemIndex()
    for project_id, documents in entries or []:
        part = build_index(documents, project_id=str(project_id or ""))
        for key, ref in (getattr(part, "items", {}) or {}).items():
            merged.items.setdefault(key, ref)
        for key, places in (getattr(part, "locations", {}) or {}).items():
            merged.locations.setdefault(key, []).extend(places)
        merged.issues.extend(getattr(part, "issues", []) or [])
        for key, heading in (getattr(part, "headings", {}) or {}).items():
            merged.headings.setdefault(key, heading)
    return merged


def collect_graph(root, *, workspace: bool = True):
    """关系图与文档（与 CLI ``_collect_graph`` 同源），用于 GUI/CLI 一致性。"""
    from doc_tool.cli import _collect_graph

    return _collect_graph(Path(root), workspace=bool(workspace))


def empty_graph():
    from doc_tool.application.content.relations import RelationGraph

    return RelationGraph()


def relations_path_for(workspace, root) -> Optional[Path]:
    """工作区关系文件位置（缺省 ``relations.yml``，越界位置不解析）。"""
    rel = str(getattr(workspace, "relations_path", "") or "relations.yml").replace("\\", "/")
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    candidate = Path(root) / rel
    return candidate if candidate.is_file() else None


def snapshots_from_documents(documents: Sequence[dict]) -> Dict[Tuple[str, str], object]:
    """``[{relPath,text,source}]`` → ``{(projectId,itemId): ItemSnapshot}``。"""
    result: Dict[Tuple[str, str], object] = {}
    for row in documents or []:
        snapshot = snapshot_from_text(row.get("relPath", ""), row.get("text", ""))
        if snapshot is None:
            continue
        key, item = snapshot
        result[key] = item
    return result


def document_source_map(documents: Sequence[dict]) -> Dict[str, str]:
    """``relPath -> source``，供列表展示“已保存 / 当前缓冲”。"""
    return {str(row.get("relPath", "")): str(row.get("source", SOURCE_SAVED)) for row in documents or []}
