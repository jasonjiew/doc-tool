# -*- coding: utf-8 -*-
"""导入入口路由：自动识别 Word/Markdown/规范包并真实调用对应建项服务（CORE-A 1.3）。

界面（首页「导入文档」、文件菜单、命令面板）与 CLI 共用本模块，避免出现
「只显示一段说明再转到无关向导」的入口。路由决定可单独查询（不产生副作用），
便于界面在动手之前展示将走哪条服务；真正执行时调用既有服务：

- ``.docx``            -> :func:`doc_tool.application.import_project.import_first_time`
- ``.doc``             -> ``ensure_docx_source`` 后走 DOCX 路径；缺 Word 时标记待转换
- ``.md/.markdown``    -> :func:`doc_tool.application.project_from_markdown.create_project_from_markdown`
- 规范包目录           -> :func:`doc_tool.application.project_from_pack.create_project_from_pack`
- 已打开项目 + DOCX    -> :class:`doc_tool.application.content.reimport.ReimportService`（差异重导入）

普通模式不因内容缺口阻断；只有源不可读/无法形成有效项目才判定该输入失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from doc_tool.application.import_project import (
    ImportRequest,
    ImportResult,
    import_first_time,
)
from doc_tool.application.intake_contract import (
    DEFAULT_ACTIONABLE_LIMIT,
    IntakePlan,
    IntakePolicy,
    PlannedTarget,
    PreservationFinding,
    default_document_name,
    sha256_file,
    unique_directory,
)
from doc_tool.domain.cancellation import CancellationToken

# --- 源类型 ---

KIND_DOCX = "docx"
KIND_DOC = "doc"
KIND_MARKDOWN = "markdown"
KIND_PACK = "pack"
KIND_UNKNOWN = "unknown"

# --- 路由目标（真实服务名） ---

SERVICE_INTAKE_DOCX = "import_first_time"
SERVICE_INTAKE_DOC = "ensure_docx_source+import_first_time"
SERVICE_MARKDOWN = "create_project_from_markdown"
SERVICE_PACK = "create_project_from_pack"
SERVICE_REIMPORT = "ReimportService.reimport"
SERVICE_UNSUPPORTED = ""

ACTION_CREATE = "create-project"
ACTION_REIMPORT = "reimport"
ACTION_PENDING_CONVERT = "pending-convert"
ACTION_UNSUPPORTED = "unsupported"

_MARKDOWN_SUFFIXES = (".md", ".markdown")
_WORD_SUFFIXES = (".docx", ".docm", ".dotx")
_PACK_MARKERS = ("project.yml", "manifest.yml", "pack.yml", "standard.yml")


@dataclass
class EntryRoute:
    """一次导入请求应走哪条真实服务（可先展示，不产生副作用）。"""

    source: str = ""
    kind: str = KIND_UNKNOWN
    action: str = ACTION_UNSUPPORTED
    service: str = ""
    available: bool = False
    reason: str = ""
    suggested_action: str = ""

    def describe(self) -> str:
        if self.action == ACTION_REIMPORT:
            return "接收外部 Word 修改：{0}".format(self.service)
        if self.action == ACTION_CREATE:
            return "创建可维护项目：{0}".format(self.service)
        if self.action == ACTION_PENDING_CONVERT:
            return "待转换：{0}".format(self.reason)
        return self.reason or "无法识别的输入"

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "kind": self.kind,
            "action": self.action,
            "service": self.service,
            "available": self.available,
            "reason": self.reason,
            "suggestedAction": self.suggested_action,
        }


def detect_intake_kind(path: Union[str, Path]) -> str:
    """按后缀/包标记识别源类型；不读取正文。"""
    target = Path(path)
    if target.is_dir():
        for marker in _PACK_MARKERS:
            if (target / marker).is_file():
                return KIND_PACK
        return KIND_UNKNOWN
    suffix = target.suffix.lower()
    if suffix in _WORD_SUFFIXES:
        return KIND_DOCX
    if suffix == ".doc":
        try:
            from doc_tool.adapters.word_convert import is_doc_format

            return KIND_DOC if is_doc_format(target) else KIND_DOCX
        except Exception:  # noqa: BLE001 - 识别失败按后缀处理
            return KIND_DOC
    if suffix in _MARKDOWN_SUFFIXES:
        return KIND_MARKDOWN
    return KIND_UNKNOWN


def route_for(
    path: Union[str, Path],
    *,
    project_open: bool = False,
    word_available: Optional[bool] = None,
) -> EntryRoute:
    """给出该输入对应的真实服务与可用性（不执行建项）。"""
    target = Path(path)
    kind = detect_intake_kind(target)
    route = EntryRoute(source=str(target), kind=kind)
    if kind == KIND_PACK:
        route.action = ACTION_CREATE
        route.service = SERVICE_PACK
        route.available = True
        route.reason = "规范包可作为新项目起步"
        return route
    if kind == KIND_MARKDOWN:
        route.action = ACTION_CREATE
        route.service = SERVICE_MARKDOWN
        route.available = True
        route.reason = "Markdown 依确认顺序建立一份项目"
        return route
    if kind == KIND_DOCX and project_open:
        route.action = ACTION_REIMPORT
        route.service = SERVICE_REIMPORT
        route.available = True
        route.reason = "已打开项目：进入差异重导入，不新建项目"
        route.suggested_action = "查看差异后选择要应用的章节"
        return route
    if kind == KIND_DOCX:
        route.action = ACTION_CREATE
        route.service = SERVICE_INTAKE_DOCX
        route.available = target.is_file()
        route.reason = "接管现有 Word 生成可持续维护项目"
        if not route.available:
            route.suggested_action = "请重新选择存在的 DOCX 文件"
        return route
    if kind == KIND_DOC:
        available = _word_available() if word_available is None else bool(word_available)
        if available:
            route.action = ACTION_CREATE
            route.service = SERVICE_INTAKE_DOC
            route.available = target.is_file()
            route.reason = "旧版 .doc 先转换为 .docx 再接管"
        else:
            route.action = ACTION_PENDING_CONVERT
            route.service = SERVICE_INTAKE_DOC
            route.available = False
            route.reason = "旧版 .doc 需要 Microsoft Word 转换，本机不可用"
            route.suggested_action = "在装有 Word 的电脑另存为 .docx 后重试；原输入已保留"
        return route
    route.reason = "无法识别的输入类型：{0}".format(target.suffix or target.name)
    route.suggested_action = "请选择 DOCX、DOC、Markdown 文件或规范包目录"
    return route


def _word_available() -> bool:
    try:
        from doc_tool.application.word_check import check_word_available

        return bool(check_word_available().available)
    except Exception:  # noqa: BLE001 - 探测失败按不可用处理，走兜底
        return False


def plan_target(
    source: Union[str, Path],
    *,
    parent_dir: Union[str, Path],
    trusted_name: str = "",
    document_no: str = "",
    document_version: str = "1.0",
    target_name: str = "",
) -> PlannedTarget:
    """按默认值规则给出拟建目标：可信名称优先、名称冲突自动后缀、编号可空。"""
    src = Path(source)
    name = default_document_name(src, trusted_name)
    if target_name.strip():
        from doc_tool.application.intake_contract import sanitize_name_part

        cleaned = sanitize_name_part(target_name)
        if cleaned:
            name = cleaned
            name_source = "用户指定"
        else:
            name_source = "可信元数据"
    else:
        name_source = "可信元数据" if trusted_name.strip() else "文件名"
    directory = unique_directory(Path(parent_dir), name)
    return PlannedTarget(
        directory=str(directory),
        document_name=name,
        document_no=str(document_no or ""),
        document_version=str(document_version or ""),
        name_source=name_source,
        directory_source="默认目录" if not target_name.strip() else "用户指定",
    )


@dataclass
class IntakeOutcome:
    """一次导入执行结果：可用项目 + 集中提示 + 待转换项。"""

    ok: bool = False
    route: EntryRoute = field(default_factory=EntryRoute)
    project_root: Optional[Path] = None
    plan: Optional[IntakePlan] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    events: List[object] = field(default_factory=list)
    error_code: str = ""
    suggested_action: str = ""
    diagnostic_log: Optional[Path] = None
    #: CORE R5：本次导入使用的命名映射预设（{presetId,name,mapping,unmatched,warnings}）。
    preset: Dict[str, object] = field(default_factory=dict)
    #: 本次导入保存为预设的名称（为空表示未保存）。
    saved_preset: str = ""

    def summary_lines(self, max_actions: int = DEFAULT_ACTIONABLE_LIMIT) -> List[str]:
        if self.plan is not None:
            lines = self.plan.summary_lines(max_actions=max_actions)
        else:
            lines = []
        if self.ok and self.project_root is not None:
            lines.insert(0, "已生成可编辑项目：{0}".format(Path(self.project_root).name))
        for item in self.pending:
            lines.append("待转换：{0}".format(item))
        for item in self.skipped:
            lines.append("已跳过：{0}".format(item))
        for item in self.warnings:
            lines.append("提醒：{0}".format(item))
        for item in self.errors:
            lines.append("失败：{0}".format(item))
        return lines


def build_docx_request(
    source: Union[str, Path],
    target: PlannedTarget,
    *,
    policy: Optional[IntakePolicy] = None,
    heading_style_map: Optional[Dict[str, int]] = None,
    document_type: str = "general",
    refresh_timeout_seconds: int = 900,
    normalize_heading_levels: bool = True,
    decide_pre_title_body: bool = True,
    pre_title_chapter_title: str = "前言",
    selected_sections: Optional[Sequence[str]] = None,
) -> ImportRequest:
    """把导入计划翻译成既有 ImportRequest（策略经适配，不作为隐藏状态）。

    ``normalize_heading_levels``/``decide_pre_title_body`` 让服务端按同一份大纲
    整理计划压平跳级标题、在明确范围内保留标题前正文（CORE 2.2/2.3）。
    """
    effective = policy or IntakePolicy.normal()
    flags = effective.to_legacy_flags()
    return ImportRequest(
        source_docx=Path(source),
        target_project_root=Path(target.directory),
        document_type=document_type,
        document_no=target.document_no,
        document_name=target.document_name,
        document_version=target.document_version or "1.0",
        refresh_timeout_seconds=refresh_timeout_seconds,
        require_exact_roundtrip=flags["require_exact_roundtrip"],
        heading_style_map=dict(heading_style_map) if heading_style_map else None,
        allow_missing_headings=flags["allow_missing_headings"],
        ignore_roundtrip_block=flags["ignore_roundtrip_block"],
        normalize_heading_levels=bool(normalize_heading_levels),
        decide_pre_title_body=bool(decide_pre_title_body),
        pre_title_chapter_title=pre_title_chapter_title,
        selected_section_titles=[str(item) for item in (selected_sections or [])],
    )


def run_intake(
    source: Union[str, Path],
    *,
    parent_dir: Union[str, Path],
    policy: Optional[IntakePolicy] = None,
    trusted_name: str = "",
    target_name: str = "",
    document_no: str = "",
    document_version: str = "1.0",
    document_type: str = "general",
    heading_style_map: Optional[Dict[str, int]] = None,
    project_root: Optional[Union[str, Path]] = None,
    cancel_token: Optional[CancellationToken] = None,
    on_event=None,
    word_available: Optional[bool] = None,
    markdown_sources: Optional[Sequence[Union[str, Path]]] = None,
    asset_roots: Sequence[Union[str, Path]] = (),
    template_path: Optional[Union[str, Path]] = None,
    pack_source: Optional[Union[str, Path]] = None,
    selected_sections: Optional[Sequence[str]] = None,
    preset_name: str = "",
    save_preset: str = "",
) -> IntakeOutcome:
    """按路由真实调用对应服务并返回统一结果（不抛出业务异常）。"""
    src = Path(source)
    route = route_for(src, project_open=bool(project_root), word_available=word_available)
    outcome = IntakeOutcome(route=route)
    if route.action == ACTION_UNSUPPORTED:
        outcome.errors.append(route.reason)
        outcome.suggested_action = route.suggested_action
        return outcome
    if route.action == ACTION_PENDING_CONVERT:
        outcome.pending.append(route.reason)
        outcome.suggested_action = route.suggested_action
        return outcome
    if route.action == ACTION_REIMPORT:
        outcome.errors.append(
            "目标为已打开项目，请使用「重新导入更新源 Word」入口（差异重导入），不在此新建项目。"
        )
        outcome.suggested_action = route.suggested_action
        return outcome

    target = plan_target(
        src,
        parent_dir=parent_dir,
        trusted_name=trusted_name,
        document_no=document_no,
        document_version=document_version,
        target_name=target_name,
    )
    plan = IntakePlan(
        source=str(src),
        sourceHash=sha256_file(src) if src.is_file() else "",
        sourceKind=route.kind,
        documentType=document_type,
        policy=policy or IntakePolicy.normal(),
        target=target,
    )

    if route.kind == KIND_DOCX:
        # CORE R5：命名映射预设在这里解析成真实映射（未命中项回退自动识别，不阻断导入）
        resolved_preset = None
        if preset_name:
            resolved_preset = _resolve_intake_preset(src, preset_name, outcome)
            if resolved_preset is not None and resolved_preset.mapping and heading_style_map is None:
                heading_style_map = dict(resolved_preset.mapping)
        result = _run_word_intake(
            src, target, plan, outcome,
            policy=policy, heading_style_map=heading_style_map,
            document_type=document_type, cancel_token=cancel_token, on_event=on_event,
            selected_sections=selected_sections,
        )
        if save_preset:
            _save_intake_preset(src, save_preset, result, heading_style_map, outcome)
        return result
    if route.kind == KIND_DOC:
        return _run_word_intake(
            src, target, plan, outcome,
            policy=policy, heading_style_map=heading_style_map,
            document_type=document_type, cancel_token=cancel_token, on_event=on_event,
            selected_sections=selected_sections,
        )
    if route.kind == KIND_MARKDOWN:
        return _run_markdown_intake(
            src, target, plan, outcome,
            markdown_sources=markdown_sources, asset_roots=asset_roots,
            template_path=template_path, document_type=document_type,
        )
    if route.kind == KIND_PACK:
        return _run_pack_intake(src, target, plan, outcome, pack_source=pack_source, document_type=document_type)
    outcome.errors.append(route.reason)
    return outcome


def _preset_style_names(src: Path) -> Dict[str, str]:
    """读取源文档的 ``{styleId: 样式名}``，供预设解析/保存使用（失败返回空）。"""
    try:
        from doc_tool.adapters.docx_parts import read_docx_parts  # type: ignore
    except Exception:  # noqa: BLE001 - 部件读取接口不同版本时退回预检
        read_docx_parts = None
    try:
        if read_docx_parts is not None:
            parts = read_docx_parts(src)
        else:
            import zipfile

            with zipfile.ZipFile(src) as archive:
                parts = {
                    name: archive.read(name) for name in archive.namelist()
                    if name.startswith("word/")
                }
        from doc_tool.adapters.preflight import census_paragraph_styles

        census = census_paragraph_styles(parts)
        return {str(key): str(getattr(value, "name", "") or "") for key, value in census.items()}
    except Exception:  # noqa: BLE001 - 普查失败不阻断导入
        return {}


def _resolve_intake_preset(src: Path, preset_name: str, outcome) -> Optional[object]:
    """把命名预设适配到当前源文档（唯一实现在 intake_presets，这里只把提醒写进 outcome）。"""
    from doc_tool.application.intake_presets import resolve_for_source

    resolved, info, warnings = resolve_for_source(preset_name, src)
    for item in warnings:
        outcome.warnings.append(item)
    if info:
        outcome.preset = dict(info)
    return resolved


def _save_intake_preset(src: Path, name: str, result, heading_style_map, outcome) -> None:
    """把本次导入使用的映射保存为命名预设（唯一实现在 intake_presets）。"""
    if result is None or not getattr(result, "ok", False):
        return
    from doc_tool.application.intake_presets import save_from_import

    mapping = dict(heading_style_map or {})
    if not mapping:
        preset_info = getattr(result, "preset", None) or {}
        if isinstance(preset_info, dict):
            mapping = {str(k): int(v) for k, v in (preset_info.get("mapping") or {}).items()}
    saved, warnings = save_from_import(name, src, mapping)
    for item in warnings:
        outcome.warnings.append(item)
    if saved:
        outcome.saved_preset = saved


def _run_word_intake(
    src: Path,
    target: PlannedTarget,
    plan: IntakePlan,
    outcome: IntakeOutcome,
    *,
    policy: Optional[IntakePolicy],
    heading_style_map: Optional[Dict[str, int]],
    document_type: str,
    cancel_token: Optional[CancellationToken],
    on_event,
    selected_sections: Optional[Sequence[str]] = None,
) -> IntakeOutcome:
    effective_policy = policy or IntakePolicy.normal()
    # 先做一次计划预检：预览内容摘要、章节候选与标题前正文范围，
    # 让界面看到的整理结果与服务端实际采用的决定一致（design D2/D5）。
    outline_plan = _plan_outline(src, target, plan, effective_policy, document_type, outcome)
    if outline_plan is None and not outcome.errors:
        outcome.errors.append("源文档无法解析，未创建项目（源文件未被修改）。")
        return outcome
    request = build_docx_request(
        src, target, policy=effective_policy, heading_style_map=heading_style_map,
        document_type=document_type, selected_sections=selected_sections,
    )
    if selected_sections:
        from doc_tool.application.intake_scope import selection_from_titles

        resolved = selection_from_titles(plan, [str(item) for item in selected_sections])
        plan.warnings.append(
            "范围：纳入 {0} 个章节{1}".format(
                len(resolved.selected_titles),
                "（含 {0} 个上级结构）".format(len(resolved.added_ancestor_ids))
                if resolved.added_ancestor_ids else "",
            )
        )
    result: ImportResult = import_first_time(request, cancel_token=cancel_token, on_event=on_event)
    outcome.events = list(result.events)
    outcome.diagnostic_log = result.diagnostic_log
    outcome.error_code = result.error_code or ""
    outcome.suggested_action = result.suggested_action or ""
    if not result.success or result.project_root is None:
        outcome.errors.append(
            _last_failure_detail(result) or "导入未完成，源文件与已有项目未被修改。"
        )
        return outcome
    outcome.ok = True
    outcome.project_root = Path(result.project_root)
    plan.sourceHash = result.source_sha256 or plan.sourceHash
    plan.target.directory = str(outcome.project_root)
    _merge_intake_record(plan, outcome.project_root)
    outcome.plan = plan
    outcome.warnings.extend(
        str(event.detail) for event in result.events
        if getattr(event, "status", "") == "warning" and getattr(event, "detail", "")
    )
    return outcome


def _plan_outline(
    src: Path,
    target: PlannedTarget,
    plan: IntakePlan,
    policy: IntakePolicy,
    document_type: str,
    outcome: IntakeOutcome,
):
    """用预检结果构造大纲整理计划，并把决定写回 IntakePlan（不产生副作用）。"""
    from doc_tool.adapters.preflight import preflight
    from doc_tool.application.intake_outline import build_plan as build_outline_plan
    from doc_tool.domain.errors import DocToolError

    try:
        preview = preflight(
            str(src),
            allow_missing_headings=bool(policy.allow_missing_headings),
            tolerate_missing_resources=not policy.is_strict,
        )
    except DocToolError as exc:
        outcome.errors.append(exc.user_message)
        outcome.suggested_action = exc.suggested_action
        outcome.error_code = exc.code
        return None
    built, outline = build_outline_plan(
        preview,
        source=src,
        target=target,
        policy=policy,
        document_type=document_type,
        pre_title_blocks=getattr(preview, "pre_title_blocks", []) or [],
    )
    plan.headingDecisions = list(built.headingDecisions)
    plan.sections = list(built.sections)
    plan.policy = built.policy
    plan.warnings.extend(item for item in built.warnings if item not in plan.warnings)
    _merge_ledger_findings(preview, plan)
    for line in outline.preview_lines():
        if line.startswith("层级整理") or line.startswith("未找到可用标题"):
            if line not in plan.warnings:
                plan.warnings.append(line)
    if policy.is_strict:
        blocked, reason = policy.should_block(plan.preservationFindings)
        plan.strictBlocked = blocked
        plan.strictReason = reason
    return outline


def _merge_ledger_findings(preview, plan: IntakePlan) -> None:
    """把预检保真结论并入计划的待完善清单（预览即可看到待完善数量）。"""
    from doc_tool.application.import_record import findings_from_fidelity

    fidelity = getattr(preview, "fidelity", None)
    if fidelity is None:
        return
    merged = findings_from_fidelity(fidelity, retained_path="original/source.docx")
    existing = {(item.feature, item.handling) for item in plan.preservationFindings}
    # 已有“带章节定位的提取事实”的 feature，不再重复文档级统计（CORE 3.2 去重）
    located_features = {
        item.feature for item in plan.preservationFindings if item.target_chapter
    }
    for item in merged:
        if item.feature in located_features and not item.target_chapter:
            continue
        if (item.feature, item.handling) not in existing:
            plan.preservationFindings.append(item)


def _merge_intake_record(plan: IntakePlan, project_root: Path) -> None:
    """成功后用项目内导入记录校正计划：处理事实/对照状态与项目一致。"""
    from doc_tool.application.import_record import read_import_record

    record = read_import_record(Path(project_root))
    if record is None:
        return
    if record.findings:
        plan.preservationFindings = list(record.findings)
    for item in record.unavailableComparisons:
        if item not in plan.unavailableComparisons:
            plan.unavailableComparisons.append(item)
    if record.headingDecisions:
        from doc_tool.application.intake_contract import HeadingDecision

        plan.headingDecisions = [
            HeadingDecision.from_dict(item) for item in record.headingDecisions
            if isinstance(item, dict)
        ]
    if record.actualPolicy == "strict":
        plan.policy = IntakePolicy.strict()


def _last_failure_detail(result: ImportResult) -> str:
    last = result.last_stage
    if last is None:
        return ""
    detail = getattr(last, "detail", "") or ""
    return detail or "阶段 {0} 失败".format(getattr(last, "stage", ""))


def _run_markdown_intake(
    src: Path,
    target: PlannedTarget,
    plan: IntakePlan,
    outcome: IntakeOutcome,
    *,
    markdown_sources: Optional[Sequence[Union[str, Path]]],
    asset_roots: Sequence[Union[str, Path]],
    template_path: Optional[Union[str, Path]],
    document_type: str,
) -> IntakeOutcome:
    from doc_tool.application.project_from_markdown import create_project_from_markdown

    sources: List[Union[str, Path]] = list(markdown_sources or [src])
    if src not in [Path(item) for item in sources]:
        sources.insert(0, src)
    result = create_project_from_markdown(
        sources,
        target.directory,
        asset_roots=asset_roots,
        template_path=template_path,
        document_name=target.document_name,
        document_no=target.document_no,
        document_version=target.document_version or "1.0",
        document_type=document_type,
    )
    outcome.warnings.extend(result.warnings)
    outcome.skipped.extend(result.skipped)
    outcome.errors.extend(result.errors)
    if not result.ok or result.project_root is None:
        if not outcome.errors:
            outcome.errors.append("Markdown 建项未完成，原文件未被修改。")
        return outcome
    outcome.ok = True
    outcome.project_root = Path(result.project_root)
    plan.target.directory = str(outcome.project_root)
    outcome.plan = plan
    return outcome


def _run_pack_intake(
    src: Path,
    target: PlannedTarget,
    plan: IntakePlan,
    outcome: IntakeOutcome,
    *,
    pack_source: Optional[Union[str, Path]],
    document_type: str,
) -> IntakeOutcome:
    from doc_tool.application.project_from_pack import create_project_from_pack

    result = create_project_from_pack(
        pack_source or src,
        target.directory,
        document_name=target.document_name,
        document_no=target.document_no,
        document_version=target.document_version or "1.0",
        document_type=document_type,
    )
    outcome.warnings.extend(result.warnings)
    outcome.errors.extend(result.errors)
    if not result.ok or result.project_root is None:
        if not outcome.errors:
            outcome.errors.append("规范包建项未完成，原包未被修改。")
        return outcome
    outcome.ok = True
    outcome.project_root = Path(result.project_root)
    plan.target.directory = str(outcome.project_root)
    outcome.plan = plan
    return outcome


def default_project_parent() -> Path:
    """首页默认项目父目录（与既有向导默认保持一致）。"""
    try:
        from doc_tool.ui.wizard import get_default_target_parent

        return Path(get_default_target_parent())
    except Exception:  # noqa: BLE001 - 向导不可用时退回用户文档目录
        return Path.home() / "Documents" / "DocToolProjects"


__all__ = [
    "KIND_DOCX", "KIND_DOC", "KIND_MARKDOWN", "KIND_PACK", "KIND_UNKNOWN",
    "ACTION_CREATE", "ACTION_REIMPORT", "ACTION_PENDING_CONVERT", "ACTION_UNSUPPORTED",
    "SERVICE_INTAKE_DOCX", "SERVICE_INTAKE_DOC", "SERVICE_MARKDOWN", "SERVICE_PACK",
    "SERVICE_REIMPORT", "SERVICE_UNSUPPORTED",
    "EntryRoute", "IntakeOutcome", "detect_intake_kind", "route_for",
    "plan_target", "build_docx_request", "run_intake", "default_project_parent",
]