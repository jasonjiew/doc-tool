# -*- coding: utf-8 -*-
"""Read-only, derived main-flow advice. No workflow state, writes, model, or Word calls.

The existing quality report, import ledger and export round remain authoritative.
Action ids are deliberately closed: document/provider text can never become a command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

CHECK_CURRENT = "check-current"
SHOW_ISSUES = "show-issues"
RULE_SETTINGS = "rule-settings"
IMPORT_RESULT = "import-result"
SHOW_RESULTS = "show-results"
RETRY_ROUND = "retry-round"
NEW_EXPORT = "new-export"
REVISION_PREVIEW = "revision-preview"
SHOW_PROGRESS = "show-progress"
OPEN_PROJECT = "open-project"

ACTION_LABELS = {
    CHECK_CURRENT: "检查当前正文", SHOW_ISSUES: "查看并处理问题",
    RULE_SETTINGS: "查看规则设置", IMPORT_RESULT: "查看导入处理结果",
    SHOW_RESULTS: "打开本项目成果", RETRY_ROUND: "补原轮未完成格式",
    NEW_EXPORT: "按当前内容导出新一轮", REVISION_PREVIEW: "预览源 Word 修订",
    SHOW_PROGRESS: "查看正在运行的任务", OPEN_PROJECT: "打开项目",
}
ALLOWED_ACTIONS = frozenset(ACTION_LABELS)


@dataclass(frozen=True)
class QualityFacts:
    """Execution facts, not a second interpretation of quality rules."""
    report: dict = field(default_factory=dict)
    issue_count: int = 0
    stale: bool = False
    scope_text: str = "整份文档"
    scope_kind: str = "document"
    source_mode: str = "unknown"
    checked_at: str = ""
    unavailable: Tuple[str, ...] = ()
    current_configuration: dict = field(default_factory=dict)

    @property
    def state(self) -> str:
        configuration = self.current_configuration or self.report.get("configuration") or {}
        if configuration.get("valid") is False:
            return "configuration-error"
        if self.unavailable:
            return "incomplete"
        if self.stale:
            return "stale"
        if not self.report:
            return "unknown"
        if self.report.get("executedCount") == 0:
            return "not-run"
        if not self.report.get("complete") or configuration.get("valid") is not True:
            return "incomplete"
        return "issues" if self.issue_count else "clean"

    def to_dict(self) -> dict:
        return {
            "state": self.state, "scopeText": self.scope_text,
            "scopeKind": self.scope_kind, "sourceMode": self.source_mode,
            "checkedAt": self.checked_at, "issueCount": self.issue_count,
            "unavailable": list(self.unavailable), "execution": dict(self.report),
            "currentConfiguration": dict(self.current_configuration),
        }


@dataclass(frozen=True)
class FormatFact:
    format: str
    status: str
    usable: bool = False
    path_available: bool = True
    formal: bool = False


@dataclass(frozen=True)
class MainflowFacts:
    project_loaded: bool = True
    running: bool = False
    read_only: bool = False
    source_mode: str = "saved"
    unsaved_chapters: int = 0
    quality: QualityFacts = field(default_factory=QualityFacts)
    import_attention: int = 0
    source_changed: Optional[bool] = None
    formats: Tuple[FormatFact, ...] = ()
    round_id: str = ""
    round_source_mode: str = "unknown"
    round_scope_text: str = "未知范围"


@dataclass(frozen=True)
class NextStep:
    action: str
    reason: str
    priority: int
    scope_text: str = ""
    round_id: str = ""

    def __post_init__(self):
        if self.action not in ALLOWED_ACTIONS:
            raise ValueError("Unsupported mainflow action")

    @property
    def label(self):
        return ACTION_LABELS[self.action]

    def to_dict(self) -> dict:
        return {"action": self.action, "label": self.label, "reason": self.reason,
                "scopeText": self.scope_text, "roundId": self.round_id}


@dataclass(frozen=True)
class MainflowAdvice:
    facts: MainflowFacts
    steps: Tuple[NextStep, ...] = ()

    @property
    def primary(self):
        return self.steps[0] if self.steps else None

    def to_dict(self) -> dict:
        facts = self.facts
        return {
            "schemaVersion": 1, "command": "mainflow-advice", "readOnly": True,
            "sourceMode": facts.source_mode, "unsavedChapters": facts.unsaved_chapters,
            "running": facts.running, "readOnlyProject": facts.read_only,
            "quality": facts.quality.to_dict(), "sourceChanged": facts.source_changed,
            "round": {"roundId": facts.round_id, "sourceMode": facts.round_source_mode,
                      "scopeText": facts.round_scope_text},
            "actions": [step.to_dict() for step in self.steps],
            "primary": self.primary.to_dict() if self.primary else None,
            "notes": ["建议为当前事实的只读派生，不是内容批准；点击动作前重新核对状态。",
                      "普通提醒不新增出稿门禁；补原轮与按当前内容新建轮次是不同操作。"],
        }


def derive_advice(facts: MainflowFacts) -> MainflowAdvice:
    """Stable recommendations from supplied facts only; never performs I/O."""
    steps: List[NextStep] = []

    def add(action, reason, priority, scope="", round_id=""):
        if action not in {item.action for item in steps}:
            steps.append(NextStep(action, reason, priority, scope, round_id))

    if not facts.project_loaded:
        add(OPEN_PROJECT, "尚未打开项目；不会扫描其他目录或猜测当前文档。", 1000)
        return MainflowAdvice(facts, tuple(steps))
    if facts.running:
        add(SHOW_PROGRESS, "已有任务正在运行，先查看真实进度，避免重复启动。", 1000)
        return MainflowAdvice(facts, tuple(steps))

    quality = facts.quality
    state = quality.state
    if state == "configuration-error":
        add(RULE_SETTINGS, "质量配置不可用；旧的空问题列表不能代表检查通过。", 900, quality.scope_text)
        add(CHECK_CURRENT, "修正规则配置后重检，保留原有正文与成果。", 800, quality.scope_text)
    elif state in ("stale", "incomplete", "not-run", "unknown"):
        explanations = {
            "stale": "正文或规则在检查后已变化，旧结果不能代表当前内容。",
            "incomplete": "当前检查未完整执行；请先查看未执行或不可用原因再重检。",
            "not-run": "没有规则实际执行（关闭或不适用），不能称为检查通过。",
            "unknown": "尚无当前范围的执行证据；没有问题记录不等于已检查通过。",
        }
        add(CHECK_CURRENT, explanations[state], 700 if state != "unknown" else 400, quality.scope_text)
    elif state == "issues":
        add(SHOW_ISSUES, "本次实际发现 {0} 项；按已有规则/章节分组并预览修正，不猜测业务语义。".format(
            quality.issue_count), 650, quality.scope_text)
    if quality.scope_kind not in ("document", "project") and state in ("clean", "issues"):
        add(CHECK_CURRENT, "最近仅检查{0}，不能据此声称整份文档通过；可在格式检查中切换整份。".format(
            quality.scope_text), 350, quality.scope_text)
    if facts.import_attention:
        add(IMPORT_RESULT, "导入记录仍有 {0} 项需关注；原件留存与可编辑保留分别处理。".format(
            facts.import_attention), 750)
    if facts.source_changed is True:
        add(REVISION_PREVIEW, "源 Word 已变化：先进入既有差异预览，冲突由作者选择，不能整份覆盖。", 720)

    pending = [item for item in facts.formats if item.status in (
        "failed", "pending-convert", "pending-refresh", "pending-registration")]
    available = [item for item in facts.formats if item.usable and item.path_available]
    missing = [item for item in facts.formats if item.usable and not item.path_available]
    if pending:
        add(RETRY_ROUND, "原轮仍有 {0} 个格式失败或待办；沿用原捕获/原范围，不混入现在的编辑。".format(
            len(pending)), 780, facts.round_scope_text, facts.round_id)
    if available:
        add(SHOW_RESULTS, "有 {0} 个可读成果可先使用；可读不等于正式登记完成。原轮来源：{1}。".format(
            len(available), facts.round_source_mode), 500, facts.round_scope_text, facts.round_id)
    if missing:
        add(SHOW_RESULTS, "{0} 个历史成果路径已失效，应重新定位或明确生成新轮，不能假称可打开。".format(
            len(missing)), 600, facts.round_scope_text, facts.round_id)
    add(NEW_EXPORT, "使用当前内容生成新一轮{0}；不自动保存全部正文，不覆盖旧轮。".format(
        "（含 {0} 章未保存编辑）".format(facts.unsaved_chapters) if facts.unsaved_chapters else ""),
        450 if state == "clean" else 100, "当前导出设置中的范围")
    steps.sort(key=lambda item: (-item.priority, item.action))
    return MainflowAdvice(facts, tuple(steps))


def saved_project_advice(project_root, *, check: bool = True) -> MainflowAdvice:
    """CLI: reuse the existing readonly check, ledger and index; no GUI memory claims."""
    from pathlib import Path
    from doc_tool.application.check import run_check
    from doc_tool.application.import_record import read_import_record
    from doc_tool.application.project_export import read_export_index
    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root)
    manifest = ProjectManifest.load(root)
    paths = manifest.resolve_paths(root)
    quality = QualityFacts(source_mode="saved")
    if check:
        report = run_check(root, build=False)
        quality = QualityFacts(report=dict(report.quality), issue_count=len(report.issues),
                               source_mode="saved", scope_text="整份已保存正文")
    record = read_import_record(root)
    exported = read_export_index(paths.output_dir)
    formats = tuple(FormatFact(item.format, item.status, bool(item.usable),
                               bool(item.path and Path(item.path).is_file()), item.formal)
                    for item in (exported.results if exported else []))
    facts = MainflowFacts(
        source_mode="saved", read_only=not manifest.is_writable(), quality=quality,
        import_attention=record.to_fix_count() if record else 0,
        formats=formats, round_id=exported.roundId if exported else "",
        round_source_mode=exported.sourceMode if exported else "unknown",
        round_scope_text=exported.scope.describe() if exported and exported.scopeKnown else "未知范围",
    )
    return derive_advice(facts)
