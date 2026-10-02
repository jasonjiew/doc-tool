# -*- coding: utf-8 -*-
"""V3.2 批次契约（32-A）：批次计划/成员/快照包/结果索引的最小模型与默认策略。

本模块只定义**契约与默认值**，供 CLI（:mod:`doc_tool.application.delivery.cli_commands`）
与界面服务层（:mod:`doc_tool.application.delivery.gui_hooks`）共用：它不执行出稿、
不写任何持久状态，也不重新定义「正式成功」——正式事实仍只由
:mod:`doc_tool.domain.output_state` 判定，批次状态只是适配视图。

计划文件（schema 1，JSON 或 YAML）示例::

    {
      "schemaVersion": 1,
      "batchId": "batch-demo",
      "policy": {"execution": "serial", "wordBusy": "waiting-refresh",
                 "onPartial": "keep-useful", "strict": false,
                 "autoRetryLimit": 0, "idempotencyScope": "local-common-registry"},
      "defaults": {"formats": ["docx", "html"], "destination": "delivery-out",
                   "refresh": true, "sourceMode": "saved"},
      "entries": [
        {"id": "alpha", "member": "members/Alpha", "kind": "project",
         "variantId": "standard", "formats": ["docx", "pdf"], "outputName": "Alpha"}
      ]
    }

解析规则（任务 1.3）：

- 成员路径缺省相对 ``--base-dir``，未给出时相对计划文件所在目录；绝对路径按原样。
- **成员级问题只影响该项**：写在该项的 ``problems`` 上，``status`` 为
  ``invalid``（不可执行）或 ``warning``（可执行但有提醒），其余成员照常执行。
- **计划级问题**写 ``problems``（schema 不符、根节点非映射、entries 缺失等），
  由调用方按「参数/输入非法」处理。
- 默认值优先级：成员字段 > ``defaults`` 段 > 本模块契约默认。

``policy_overrides`` / :meth:`BatchPlan.apply_overrides` 用于把旧入口标志
（``--strict``、``--no-refresh`` 等）适配到同一模型，见
:func:`policy_from_legacy_flags`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.intake_contract import (
    FORMATS,
    FORMAT_DOCX,
    SCOPE_CURRENT_CHAPTER,
    SCOPE_KINDS,
    SCOPE_PROJECT,
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODES,
    SOURCE_MODE_SAVED,
    ExportScope,
    normalize_formats,
)

#: 批次计划 schema（独立于项目/队列/包 schema，不升级项目模式版本）。
PLAN_SCHEMA_VERSION = 1
PLAN_KIND = "doc-tool-delivery-batch-plan"

#: 成员种类：单个项目目录 / 工作区（展开为其合法成员项目）。
ENTRY_KIND_PROJECT = "project"
ENTRY_KIND_WORKSPACE = "workspace"
ENTRY_KINDS = (ENTRY_KIND_PROJECT, ENTRY_KIND_WORKSPACE)

#: 成员状态：可执行 / 可执行但有提醒 / 不可执行（只影响该项）。
ENTRY_READY = "ready"
ENTRY_WARNING = "warning"
ENTRY_INVALID = "invalid"
ENTRY_STATUSES = (ENTRY_READY, ENTRY_WARNING, ENTRY_INVALID)
EXECUTABLE_ENTRY_STATUSES = (ENTRY_READY, ENTRY_WARNING)

#: 默认策略词（design.md D1/D2/D4）。
EXECUTION_SERIAL = "serial"
WORD_BUSY_WAITING_REFRESH = "waiting-refresh"
ON_PARTIAL_KEEP_USEFUL = "keep-useful"
#: 幂等范围：只承诺「本地共同登记」（packageId + 输入 digest + 目标位置）。
IDEMPOTENCY_SCOPE_LOCAL_REGISTRY = "local-common-registry"

#: 目标格式默认：与既有单项目入口一致，只出 DOCX；需要更多格式在计划里显式列出。
DEFAULT_FORMATS: Tuple[str, ...] = (FORMAT_DOCX,)


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return fallback


def _coerce_int(value: Any, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _text(value: Any) -> str:
    return str(value or "").strip()


# --- 策略与默认值 ---


@dataclass
class BatchPolicy:
    """批次策略：串行执行、Word 忙转待刷新、部分成功保留、本地共同登记幂等。"""

    execution: str = EXECUTION_SERIAL
    wordBusy: str = WORD_BUSY_WAITING_REFRESH
    onPartial: str = ON_PARTIAL_KEEP_USEFUL
    strict: bool = False
    refresh: bool = True
    autoRetryLimit: int = 0
    idempotencyScope: str = IDEMPOTENCY_SCOPE_LOCAL_REGISTRY
    sourceMode: str = SOURCE_MODE_SAVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution": self.execution,
            "wordBusy": self.wordBusy,
            "onPartial": self.onPartial,
            "strict": bool(self.strict),
            "refresh": bool(self.refresh),
            "autoRetryLimit": int(self.autoRetryLimit),
            "idempotencyScope": self.idempotencyScope,
            "sourceMode": self.sourceMode,
        }

    @classmethod
    def from_dict(
        cls, data: Optional[Dict[str, Any]], *, base: Optional["BatchPolicy"] = None,
    ) -> "BatchPolicy":
        base = base or cls()
        if not isinstance(data, dict):
            return cls(**base.__dict__)
        execution = _text(data.get("execution")) or base.execution
        if execution != EXECUTION_SERIAL:
            # 首版只有串行；其它取值不当作已实现能力，退回串行。
            execution = EXECUTION_SERIAL
        source_mode = _text(data.get("sourceMode")) or base.sourceMode
        if source_mode not in SOURCE_MODES:
            source_mode = base.sourceMode
        return cls(
            execution=execution,
            wordBusy=_text(data.get("wordBusy")) or base.wordBusy,
            onPartial=_text(data.get("onPartial")) or base.onPartial,
            strict=_coerce_bool(data.get("strict"), base.strict),
            refresh=_coerce_bool(data.get("refresh"), base.refresh),
            autoRetryLimit=_coerce_int(data.get("autoRetryLimit"), base.autoRetryLimit),
            idempotencyScope=_text(data.get("idempotencyScope")) or base.idempotencyScope,
            sourceMode=source_mode,
        )

    def summary_lines(self) -> List[str]:
        return [
            "策略：{0}｜Word 忙 → {1}｜部分结果 {2}｜严格 {3}｜登记幂等范围 {4}".format(
                self.execution, self.wordBusy, self.onPartial,
                "开" if self.strict else "关", self.idempotencyScope,
            ),
            "自动重试上限：{0} 次（幂等临时故障，0 表示需用户显式重试）".format(self.autoRetryLimit),
        ]


#: 默认策略（测试固定这些默认值）。
DEFAULT_POLICY = BatchPolicy()


def policy_from_legacy_flags(
    *,
    strict: bool = False,
    no_refresh: bool = False,
    source_mode: str = SOURCE_MODE_SAVED,
    auto_retry_limit: Optional[int] = None,
) -> BatchPolicy:
    """旧入口标志 → 批次策略默认值（任务 1.3「正常默认值」的适配口）。

    ``--no-refresh`` 表示本轮不做 Word 刷新：策略 ``refresh=False``，逐项按
    「待刷新」记录（正式事实不提升）；``--strict`` 只影响显式选择严格交付的调用。
    """
    mode = source_mode if source_mode in SOURCE_MODES else SOURCE_MODE_SAVED
    return BatchPolicy(
        strict=bool(strict),
        refresh=not bool(no_refresh),
        autoRetryLimit=(
            DEFAULT_POLICY.autoRetryLimit if auto_retry_limit is None else int(auto_retry_limit)
        ),
        sourceMode=mode,
    )


def legacy_flag_notes(
    *,
    source_mode: str = SOURCE_MODE_SAVED,
    strict: bool = False,
    no_refresh: bool = False,
) -> List[str]:
    """旧标志适配时需要显式说明的限制（不谎称读到了界面缓冲）。"""
    notes: List[str] = []
    if source_mode == SOURCE_MODE_CURRENT_BUFFER:
        notes.append(
            "命令行没有界面缓冲：sourceMode=current-buffer 不可用，已按 saved 处理。"
        )
    elif source_mode not in SOURCE_MODES:
        notes.append("未知 sourceMode（{0}），已按 saved 处理。".format(source_mode))
    if no_refresh:
        notes.append("--no-refresh：逐项不做 Word 刷新，按待刷新记录，可在有 Word 的环境补。")
    if strict:
        notes.append("--strict：严格阈值场景单独返回 1，可读参考产物仍保留。")
    return notes


@dataclass
class BatchDefaults:
    """计划 ``defaults`` 段：成员未给出的字段按此取值。"""

    formats: List[str] = field(default_factory=lambda: list(DEFAULT_FORMATS))
    destination: str = ""
    variantId: str = ""
    outputName: str = ""
    sourceMode: str = SOURCE_MODE_SAVED
    strict: bool = False
    refresh: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formats": list(self.formats),
            "destination": self.destination,
            "variantId": self.variantId,
            "outputName": self.outputName,
            "sourceMode": self.sourceMode,
            "strict": bool(self.strict),
            "refresh": bool(self.refresh),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "BatchDefaults":
        data = data if isinstance(data, dict) else {}
        formats = normalize_formats([str(item) for item in data.get("formats") or []])
        source_mode = _text(data.get("sourceMode")) or SOURCE_MODE_SAVED
        if source_mode not in SOURCE_MODES:
            source_mode = SOURCE_MODE_SAVED
        return cls(
            formats=formats or list(DEFAULT_FORMATS),
            destination=_text(data.get("destination")),
            variantId=_text(data.get("variantId")),
            outputName=_text(data.get("outputName")),
            sourceMode=source_mode,
            strict=_coerce_bool(data.get("strict"), False),
            refresh=_coerce_bool(data.get("refresh"), True),
        )


# --- 计划与成员 ---


@dataclass
class BatchEntry:
    """一个可执行批次成员（工作区会展开成多个成员项）。"""

    entryId: str = ""
    member: str = ""
    kind: str = ENTRY_KIND_PROJECT
    projectRoot: str = ""
    variantId: str = ""
    formats: List[str] = field(default_factory=list)
    destination: str = ""
    outputName: str = ""
    scope: Dict[str, Any] = field(
        default_factory=lambda: {"kind": SCOPE_PROJECT, "chapters": [], "current": ""}
    )
    sourceMode: str = SOURCE_MODE_SAVED
    strict: bool = False
    refresh: bool = True
    requestId: str = ""
    status: str = ENTRY_READY
    problems: List[str] = field(default_factory=list)
    originEntryId: str = ""
    workspaceId: str = ""
    projectId: str = ""
    workspaceRole: str = ""

    # --- 查询 ---

    @property
    def executable(self) -> bool:
        return self.status in EXECUTABLE_ENTRY_STATUSES

    @property
    def memberName(self) -> str:
        return Path(self.projectRoot).name or Path(self.member).name or self.member

    def scope_obj(self) -> ExportScope:
        return ExportScope.from_dict(self.scope)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entryId": self.entryId,
            "originEntryId": self.originEntryId or self.entryId,
            "member": self.member,
            "memberName": self.memberName,
            "kind": self.kind,
            "projectRoot": self.projectRoot,
            "variantId": self.variantId,
            "formats": list(self.formats),
            "destination": self.destination,
            "outputName": self.outputName,
            "scope": dict(self.scope),
            "sourceMode": self.sourceMode,
            "strict": bool(self.strict),
            "refresh": bool(self.refresh),
            "requestId": self.requestId,
            "status": self.status,
            "executable": self.executable,
            "problems": list(self.problems),
            "workspaceId": self.workspaceId,
            "projectId": self.projectId,
            "workspaceRole": self.workspaceRole,
        }

    def summary_line(self) -> str:
        flags = []
        if self.variantId:
            flags.append("变体 {0}".format(self.variantId))
        if self.strict:
            flags.append("严格")
        if not self.refresh:
            flags.append("不刷新")
        tail = "（{0}）".format("；".join(self.problems)) if self.problems else ""
        return "[{0}] {1}｜{2}｜{3}{4}{5}".format(
            self.status, self.memberName, self.projectRoot or self.member,
            "、".join(self.formats), "｜" + "｜".join(flags) if flags else "", tail,
        )


@dataclass
class BatchPlan:
    """schema 1 批次计划（解析结果，不等于执行结果）。"""

    schemaVersion: int = PLAN_SCHEMA_VERSION
    kind: str = PLAN_KIND
    batchId: str = ""
    planPath: str = ""
    planDir: str = ""
    baseDir: str = ""
    policy: BatchPolicy = field(default_factory=BatchPolicy)
    defaults: BatchDefaults = field(default_factory=BatchDefaults)
    entries: List[BatchEntry] = field(default_factory=list)
    skipped: List[BatchEntry] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)

    # --- 查询 ---

    @property
    def ok(self) -> bool:
        """计划级可用：无致命问题且有至少一个成员项。"""
        return not self.problems and bool(self.entries or self.skipped)

    def all_entries(self) -> List[BatchEntry]:
        return list(self.entries) + list(self.skipped)

    def executable_entries(self) -> List[BatchEntry]:
        return [entry for entry in self.entries if entry.executable]

    def invalid_entries(self) -> List[BatchEntry]:
        return [entry for entry in self.all_entries() if entry.status == ENTRY_INVALID]

    def warning_entries(self) -> List[BatchEntry]:
        return [entry for entry in self.all_entries() if entry.status == ENTRY_WARNING]

    def formats(self) -> List[str]:
        """计划声明的全部目标格式（含非法成员声明的格式，便于集中提示）。"""
        seen: List[str] = []
        for entry in self.all_entries():
            for fmt in entry.formats:
                if fmt not in seen:
                    seen.append(fmt)
        return seen

    # --- 适配与调整 ---

    def apply_overrides(
        self,
        *,
        strict: Optional[bool] = None,
        refresh: Optional[bool] = None,
        destination: str = "",
        formats: Optional[Sequence[str]] = None,
        variant_id: str = "",
    ) -> "BatchPlan":
        """按旧入口标志/命令行开关覆盖计划默认（连同不可执行项一起调整）。"""
        normalized = normalize_formats(list(formats or []))
        base = Path(self.baseDir or self.planDir or ".")
        for entry in self.all_entries():
            if strict is not None:
                entry.strict = bool(strict)
            if refresh is not None:
                entry.refresh = bool(refresh)
            if destination:
                raw = Path(destination)
                entry.destination = str(raw if raw.is_absolute() else (base / raw))
            if normalized:
                entry.formats = list(normalized)
                # 目标格式由命令行覆盖后，只清掉格式类问题；成员问题仍需重新核对。
                entry.problems = [
                    item for item in entry.problems
                    if not item.startswith("未知目标格式") and item != "未识别任何目标格式"
                ]
                if entry.status == ENTRY_INVALID and not entry.problems:
                    problem = _project_problem(Path(entry.projectRoot))
                    if problem:
                        entry.problems.append(problem)
                    else:
                        entry.status = ENTRY_READY
            if variant_id:
                entry.variantId = variant_id
        if strict is not None:
            self.policy.strict = bool(strict)
        if refresh is not None:
            self.policy.refresh = bool(refresh)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": PLAN_SCHEMA_VERSION,
            "kind": PLAN_KIND,
            "batchId": self.batchId,
            "planPath": self.planPath,
            "planDir": self.planDir,
            "baseDir": self.baseDir,
            "policy": self.policy.to_dict(),
            "defaults": self.defaults.to_dict(),
            "entryCount": len(self.all_entries()),
            "executableCount": len(self.executable_entries()),
            "invalidCount": len(self.invalid_entries()),
            "warningCount": len(self.warning_entries()),
            "formats": self.formats(),
            "entries": [entry.to_dict() for entry in self.entries],
            "skipped": [entry.to_dict() for entry in self.skipped],
            "problems": list(self.problems),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }

    def summary_lines(self) -> List[str]:
        lines = [
            "批次计划 {0}：{1} 个成员项｜可执行 {2}｜不可执行 {3}".format(
                self.batchId or "（未命名）", len(self.all_entries()),
                len(self.executable_entries()), len(self.invalid_entries()),
            ),
            "计划文件：{0}".format(self.planPath or "（未给出）"),
            "路径基准：{0}".format(self.baseDir or self.planDir or "（当前目录）"),
        ]
        lines.extend(self.policy.summary_lines())
        for entry in self.all_entries():
            lines.append("· " + entry.summary_line())
        for item in self.problems:
            lines.append("计划问题：" + item)
        for item in self.warnings:
            lines.append("提醒：" + item)
        return lines


# --- 解析 ---


def _resolve_path(raw: str, root: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def _variant_problems(project_root: Path, variant_id: str) -> List[str]:
    """变体 ID 校验（只提示，不阻断）：变体展开尚未接入统一出稿请求。"""
    if not variant_id:
        return []
    try:
        from doc_tool.application.content.variants import VariantsConfig

        config = VariantsConfig.load(project_root)
    except Exception as exc:  # noqa: BLE001 - 变体配置不可读只提示
        return ["变体配置不可读（{0}）：变体 {1} 仅登记不展开".format(exc, variant_id)]
    ids = config.ids()
    if not ids:
        return ["项目未配置 variants.yml：变体 {0} 仅登记，出稿按项目当前内容".format(variant_id)]
    if variant_id not in ids:
        return ["未知变体 {0}（可用：{1}）；该项仅登记，出稿按项目当前内容".format(
            variant_id, "、".join(ids),
        )]
    return []


def _scope_problems(scope: ExportScope, scope_raw: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    if scope.kind not in SCOPE_KINDS:
        problems.append("未知范围种类（{0}）".format(scope_raw.get("kind")))
    if scope.kind == SCOPE_CURRENT_CHAPTER and not scope.current:
        problems.append("范围 current-chapter 需要 current 章节；命令行没有界面缓冲")
    if scope.kind not in (SCOPE_PROJECT, SCOPE_CURRENT_CHAPTER) and not scope.chapters:
        problems.append("范围 chapters 未选择任何章节")
    return problems


def _parse_entry(
    raw: Dict[str, Any],
    index: int,
    *,
    defaults: BatchDefaults,
    policy: BatchPolicy,
    root: Path,
) -> Tuple[List[BatchEntry], List[str]]:
    """解析一个计划成员；返回 (展开后的成员项, 计划级提醒)。"""
    warnings: List[str] = []
    kind = _text(raw.get("kind")) or ENTRY_KIND_PROJECT
    entry_id = _text(raw.get("id")) or _text(raw.get("entryId")) or "e{0}".format(index + 1)
    member_raw = _text(raw.get("member") or raw.get("project") or raw.get("workspace"))
    base = BatchEntry(
        entryId=entry_id,
        member=member_raw,
        kind=kind,
        variantId=_text(raw.get("variantId")) or defaults.variantId,
        formats=normalize_formats(
            [str(item) for item in (raw.get("formats") or defaults.formats) if str(item).strip()]
        ),
        destination=_resolve_destination(
            _text(raw.get("destination")) or defaults.destination, root,
        ),
        outputName=_text(raw.get("outputName")) or defaults.outputName,
        scope=ExportScope.from_dict(raw.get("scope") or {"kind": SCOPE_PROJECT}).to_dict(),
        sourceMode=_text(raw.get("sourceMode")) or defaults.sourceMode,
        strict=_coerce_bool(raw.get("strict"), defaults.strict or policy.strict),
        refresh=_coerce_bool(raw.get("refresh"), defaults.refresh and policy.refresh),
        requestId=_text(raw.get("requestId")),
        originEntryId=entry_id,
    )
    raw_scope = raw.get("scope") if isinstance(raw.get("scope"), dict) else {"kind": SCOPE_PROJECT}
    member_path = _resolve_path(member_raw, root) if member_raw else Path("")
    base.projectRoot = str(member_path) if member_raw else ""

    fatal: List[str] = []
    if not member_raw:
        fatal.append("缺少成员路径（member）")
    if kind not in ENTRY_KINDS:
        fatal.append("未知成员种类（{0}）：支持 {1}".format(kind, "、".join(ENTRY_KINDS)))
    if not base.formats:
        fatal.append("未识别任何目标格式")
    unknown_formats = [fmt for fmt in base.formats if fmt not in FORMATS]
    if unknown_formats:
        fatal.append("未知目标格式：{0}（支持 {1}）".format(
            "、".join(unknown_formats), "、".join(FORMATS),
        ))
    if base.sourceMode not in SOURCE_MODES:
        fatal.append("未知 sourceMode（{0}）".format(base.sourceMode))
    elif base.sourceMode == SOURCE_MODE_CURRENT_BUFFER:
        fatal.append("命令行没有界面缓冲：sourceMode=current-buffer 不可用（请用 saved）")
    fatal.extend(_scope_problems(base.scope_obj(), raw_scope))

    if fatal:
        base.status = ENTRY_INVALID
        base.problems.extend(fatal)
        return [base], warnings

    if kind == ENTRY_KIND_PROJECT:
        problem = _project_problem(member_path)
        if problem:
            base.status = ENTRY_INVALID
            base.problems.append(problem)
            return [base], warnings
        base.problems.extend(_variant_problems(member_path, base.variantId))
        base.status = ENTRY_WARNING if base.problems else ENTRY_READY
        return [base], warnings

    # 工作区：展开为合法成员项目，逐个成为成员项（不合法的成员只影响它自己）。
    if not member_path.is_dir():
        base.status = ENTRY_INVALID
        base.problems.append("工作区目录不存在：{0}".format(member_path))
        return [base], warnings
    if not (member_path / "workspace.yml").is_file():
        base.status = ENTRY_INVALID
        base.problems.append("工作区缺少 workspace.yml：{0}".format(member_path))
        return [base], warnings
    try:
        from doc_tool.application.workspace import load_workspace

        workspace = load_workspace(member_path)
    except Exception as exc:  # noqa: BLE001 - 工作区不可读只影响该项
        base.status = ENTRY_INVALID
        base.problems.append("工作区不可读：{0}".format(exc))
        return [base], warnings

    expanded: List[BatchEntry] = []
    for issue in workspace.issues:
        warnings.append("工作区 {0}：{1}（{2}）".format(
            member_path.name, issue.relative_path, issue.reason,
        ))
    for order, item in enumerate(workspace.valid_members):
        child = BatchEntry(
            entryId="{0}:{1}".format(entry_id, order + 1),
            member="{0}/{1}".format(member_raw, item.relative_path),
            kind=ENTRY_KIND_PROJECT,
            projectRoot=str(member_path / item.relative_path),
            variantId=base.variantId,
            formats=list(base.formats),
            destination=base.destination,
            outputName=base.outputName,
            scope=dict(base.scope),
            sourceMode=base.sourceMode,
            strict=base.strict,
            refresh=base.refresh,
            requestId=base.requestId,
            originEntryId=entry_id,
            workspaceId=workspace.workspace_id,
            projectId=item.project_id,
            workspaceRole=item.role,
        )
        problem = _project_problem(Path(child.projectRoot))
        if problem:
            child.status = ENTRY_INVALID
            child.problems.append(problem)
        else:
            child.problems.extend(_variant_problems(Path(child.projectRoot), child.variantId))
            child.status = ENTRY_WARNING if child.problems else ENTRY_READY
        expanded.append(child)
    if not expanded:
        base.status = ENTRY_INVALID
        base.problems.append("工作区没有可用成员项目：{0}".format(member_path))
        return [base], warnings
    return expanded, warnings


def _resolve_destination(raw: str, root: Path) -> str:
    """成员输出目录：相对路径按基准目录解析，绝对路径按原样。"""
    text = _text(raw)
    if not text:
        return ""
    path = Path(text)
    return str(path if path.is_absolute() else (root / path))


def _project_problem(project_root: Path) -> str:
    if not project_root.is_dir():
        return "成员目录不存在：{0}".format(project_root)
    if not (project_root / "project.yml").is_file():
        return "成员目录缺少 project.yml：{0}".format(project_root)
    return ""


def parse_plan(
    data: Any,
    *,
    plan_path: str = "",
    base_dir: str = "",
    policy_overrides: Optional[Dict[str, Any]] = None,
) -> BatchPlan:
    """把计划字典解析为 :class:`BatchPlan`（成员级问题只影响该项）。"""
    plan_path_obj = Path(plan_path) if plan_path else None
    plan_dir = str(plan_path_obj.parent) if plan_path_obj is not None else ""
    root = Path(base_dir) if base_dir else (plan_path_obj.parent if plan_path_obj else Path.cwd())
    plan = BatchPlan(
        planPath=str(plan_path_obj) if plan_path_obj is not None else "",
        planDir=plan_dir,
        baseDir=str(root),
    )
    if not isinstance(data, dict):
        plan.problems.append("计划根节点必须是映射（JSON 对象 / YAML 映射）")
        return plan

    version = _coerce_int(data.get("schemaVersion"), 0)
    if version != PLAN_SCHEMA_VERSION:
        plan.problems.append(
            "不支持的批次计划 schema：{0}（本版只读 schema {1}）".format(
                version, PLAN_SCHEMA_VERSION,
            )
        )
    plan.batchId = _text(data.get("batchId")) or (plan_path_obj.stem if plan_path_obj else "")
    plan.policy = BatchPolicy.from_dict(data.get("policy"))
    overrides = policy_overrides if isinstance(policy_overrides, dict) else {}
    if overrides.get("strict") is not None:
        plan.policy.strict = bool(overrides["strict"])
    if overrides.get("refresh") is not None:
        plan.policy.refresh = bool(overrides["refresh"])
    plan.defaults = BatchDefaults.from_dict(data.get("defaults"))
    if plan.policy.strict:
        plan.defaults.strict = True
    if not plan.policy.refresh:
        plan.defaults.refresh = False

    rows = data.get("entries")
    if not isinstance(rows, list) or not rows:
        plan.problems.append("计划缺少 entries（需要至少一个成员项）")
        return plan

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            plan.skipped.append(BatchEntry(
                entryId="e{0}".format(index + 1), status=ENTRY_INVALID,
                problems=["成员项必须是映射（JSON 对象）"],
            ))
            continue
        expanded, warnings = _parse_entry(
            row, index, defaults=plan.defaults, policy=plan.policy, root=root,
        )
        plan.warnings.extend(warnings)
        for entry in expanded:
            if entry.executable:
                plan.entries.append(entry)
            else:
                plan.skipped.append(entry)
    if not plan.entries and not plan.skipped:
        plan.problems.append("计划没有任何成员项")
    return plan


def parse_plan_text(
    text: str,
    *,
    plan_path: str = "",
    base_dir: str = "",
    policy_overrides: Optional[Dict[str, Any]] = None,
) -> BatchPlan:
    """解析计划文本（按扩展名判断 JSON/YAML；解析失败记计划级问题）。"""
    import json

    suffix = Path(plan_path).suffix.lower() if plan_path else ""
    data: Any = None
    error = ""
    if suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            error = "JSON 解析失败：{0}".format(exc)
    else:
        try:
            import yaml

            data = yaml.safe_load(text)
        except ImportError:
            error = "需要 PyYAML 才能读取 YAML 计划；请改用 .json 计划"
        except Exception as exc:  # noqa: BLE001 - YAML 异常类型随版本变化
            error = "YAML 解析失败：{0}".format(exc)
    if error:
        plan = BatchPlan(
            planPath=plan_path,
            planDir=str(Path(plan_path).parent) if plan_path else "",
            baseDir=base_dir,
        )
        plan.problems.append(error)
        return plan
    return parse_plan(
        data, plan_path=plan_path, base_dir=base_dir, policy_overrides=policy_overrides,
    )


def load_plan_file(
    path,
    *,
    base_dir: str = "",
    policy_overrides: Optional[Dict[str, Any]] = None,
) -> BatchPlan:
    """读取并解析计划文件；文件缺失/不可读记为计划级问题。"""
    target = Path(path)
    if not target.is_file():
        plan = BatchPlan(planPath=str(target), baseDir=base_dir or str(target.parent))
        plan.problems.append("批次计划文件不存在：{0}".format(target))
        return plan
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        plan = BatchPlan(planPath=str(target), baseDir=base_dir or str(target.parent))
        plan.problems.append("批次计划文件不可读：{0}".format(exc))
        return plan
    return parse_plan_text(
        text, plan_path=str(target), base_dir=base_dir, policy_overrides=policy_overrides,
    )


def plan_report(plan: BatchPlan) -> Dict[str, Any]:
    """:class:`BatchPlan` 的机器报告（CLI ``delivery-plan`` 与界面共用同一形状）。"""
    report = plan.to_dict()
    report["command"] = "delivery-plan"
    report["summary"] = plan.summary_lines()
    return report


def entry_matches(entry: BatchEntry, job) -> bool:
    """成员项与已登记任务是否同一范围（用于把执行结果回填到计划视图）。"""
    import os

    def norm(value: object) -> str:
        try:
            return os.path.normcase(str(Path(str(value)).resolve()))
        except OSError:  # pragma: no cover - 极端路径不可解析时退回原文
            return str(value or "")

    return (
        norm(entry.projectRoot) == norm(getattr(job, "projectRoot", ""))
        and (entry.variantId or "") == (getattr(job, "variantId", "") or "")
        and list(entry.formats) == list(getattr(job, "formats", []) or [])
    )


__all__ = [
    "PLAN_SCHEMA_VERSION", "PLAN_KIND",
    "ENTRY_KIND_PROJECT", "ENTRY_KIND_WORKSPACE", "ENTRY_KINDS",
    "ENTRY_READY", "ENTRY_WARNING", "ENTRY_INVALID", "ENTRY_STATUSES",
    "EXECUTABLE_ENTRY_STATUSES",
    "EXECUTION_SERIAL", "WORD_BUSY_WAITING_REFRESH", "ON_PARTIAL_KEEP_USEFUL",
    "IDEMPOTENCY_SCOPE_LOCAL_REGISTRY", "DEFAULT_FORMATS", "DEFAULT_POLICY",
    "BatchPolicy", "BatchDefaults", "BatchEntry", "BatchPlan",
    "policy_from_legacy_flags", "legacy_flag_notes",
    "parse_plan", "parse_plan_text", "load_plan_file", "plan_report", "entry_matches",
]
