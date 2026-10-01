# -*- coding: utf-8 -*-
"""统一检查入口（V2.7 27-G / 7.1、7.2、7.3）。

只读地收集三类结论并给出统一退出码与机器可读报告：

1. 内容检查（``ContentLinter``，与 GUI 问题面板 / CLI ``lint`` 同一服务）；
2. 可选构建（``--build``，走正式管线，与 GUI 同源）；
3. 可选产物终审（``STAGE_AUDIT`` 的 ``audit_docx``）。

默认策略与 GUI 一致：只要没有 error 就算通过，warning 不阻断；
只有显式 ``--fail-on warning`` 或 ``--strict`` 才提高检查要求。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from doc_tool.application.issues import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    IssueRecord,
)


#: 退出码：0=未达阀值，1=达到检查阀值，2=参数/执行失败。
EXIT_OK = 0
EXIT_THRESHOLD = 1
EXIT_USAGE = 2

_FAIL_ON_CHOICES = ("error", "warning")
_OUTPUT_CHOICES = ("text", "json", "sarif")


@dataclass
class CheckArtifact:
    """检查过程中产生的可打开产物。"""

    path: str
    status: str = ""

    def to_dict(self) -> dict:
        return {"path": self.path, "status": self.status}


@dataclass
class CheckStage:
    """一个阶段的结论（未执行的阶段也如实列出）。"""

    stage: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"stage": self.stage, "status": self.status, "detail": self.detail}


@dataclass
class CheckReport:
    """统一检查报告。"""

    command: str = "check"
    project_id: str = ""
    fail_on: str = "error"
    strict: bool = False
    status: str = "ok"
    issues: List[IssueRecord] = field(default_factory=list)
    stages: List[CheckStage] = field(default_factory=list)
    artifacts: List[CheckArtifact] = field(default_factory=list)
    exit_code: int = EXIT_OK
    message: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == SEVERITY_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == SEVERITY_WARNING)

    def sorted_issues(self) -> List[IssueRecord]:
        """结果顺序确定：按严重级、文件、行号、规则排序。"""
        order = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}
        return sorted(
            self.issues,
            key=lambda issue: (
                order.get(issue.severity, 3),
                issue.rel_path or "",
                issue.line_no if issue.line_no is not None else 0,
                issue.issue_type or "",
                issue.message,
            ),
        )

    def to_dict(self) -> dict:
        return {
            "schemaVersion": 2,
            "command": self.command,
            "projectId": self.project_id,
            "status": self.status,
            "failOn": self.fail_on,
            "strict": self.strict,
            "message": self.message,
            "issues": [issue.to_dict() for issue in self.sorted_issues()],
            "stages": [stage.to_dict() for stage in self.stages],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "exitCode": self.exit_code,
        }


def _status_for(issues: List[IssueRecord], fail_on: str) -> Tuple[str, int]:
    has_error = any(issue.severity == SEVERITY_ERROR for issue in issues)
    has_warning = any(issue.severity == SEVERITY_WARNING for issue in issues)
    if has_error:
        return "failed", EXIT_THRESHOLD
    if fail_on == "warning" and has_warning:
        return "failed", EXIT_THRESHOLD
    if has_warning:
        return "warning", EXIT_OK
    return "ok", EXIT_OK


def build_report(
    issues: List[IssueRecord],
    *,
    project_id: str = "",
    fail_on: str = "error",
    strict: bool = False,
    stages: Optional[List[CheckStage]] = None,
    artifacts: Optional[List[CheckArtifact]] = None,
    message: str = "",
) -> CheckReport:
    """把问题列表汇总成统一报告（退出码在此处决定）。"""
    status, code = _status_for(issues, fail_on)
    return CheckReport(
        project_id=project_id,
        fail_on=fail_on,
        strict=bool(strict),
        status=status,
        issues=list(issues),
        stages=list(stages or []),
        artifacts=list(artifacts or []),
        exit_code=code,
        message=message,
    )


def validate_options(output: str, fail_on: str) -> Optional[str]:
    """校验 CLI 参数；返回错误说明或 None。"""
    if output not in _OUTPUT_CHOICES:
        return "--output 必须是 {0} 之一".format("/".join(_OUTPUT_CHOICES))
    if fail_on not in _FAIL_ON_CHOICES:
        return "--fail-on 必须是 {0} 之一".format("/".join(_FAIL_ON_CHOICES))
    return None
def run_check(
    project_root,
    *,
    fail_on: str = "error",
    strict: bool = False,
    build: bool = False,
    audit: bool = True,
) -> CheckReport:
    """执行统一检查：内容检查 (+ 可选构建 / 终审)。

    任何阶段未执行都在 ``stages`` 里如实标记（skipped），不会被当成通过；
    路径不存在等参数错误由 CLI 层转成退出码 2。
    """
    from pathlib import Path

    from doc_tool.application.issues import issues_from_lint
    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root)
    manifest = ProjectManifest.load(root)
    paths = manifest.resolve_paths(root)
    stages: List[CheckStage] = []
    artifacts: List[CheckArtifact] = []
    issues: List[IssueRecord] = []

    lint_issues = _collect_lint_issues(manifest, paths)
    issues.extend(lint_issues)
    stages.append(
        CheckStage(
            "lint",
            "succeeded" if not lint_issues else "warning",
            "内容检查 {0} 项".format(len(lint_issues)),
        )
    )

    if not build:
        stages.append(CheckStage("build", "skipped", "未请求构建（--build）"))
    else:
        import contextlib
        import sys as _sys

        from doc_tool.application.pipeline import run_pipeline

        # 内核会向 stdout 打印进度（如“校验报告: …”）；机器可读输出
        # 必须保持单一文档，所以构建期间统一改道 stderr。
        with contextlib.redirect_stdout(_sys.stderr):
            pipeline = run_pipeline(manifest, paths, skip_word_refresh=True)
        for event in pipeline.events:
            stages.append(CheckStage(event.stage, event.status, event.detail or ""))
        if pipeline.pending_output_path:
            artifacts.append(
                CheckArtifact(pipeline.pending_output_path, "待刷新")
            )
        if pipeline.output_path:
            artifacts.append(CheckArtifact(pipeline.output_path, "诊断产物"))
            if audit:
                from doc_tool.application.quality_gates import audit_docx, audit_policy

                report = audit_docx(
                    pipeline.output_path,
                    policy=audit_policy(strict),
                    template_path=paths.template_docx,
                )
                issues.extend(report.issues(manifest.documentType))
                stages.append(
                    CheckStage(
                        "audit",
                        report.status,
                        "终审发现 {0} 项".format(len(report.findings)),
                    )
                )
        else:
            stages.append(
                CheckStage(
                    "audit",
                    "skipped" if audit else "skipped",
                    "无可审查产物",
                )
            )

    return build_report(
        issues,
        project_id=str(root),
        fail_on=fail_on,
        strict=strict,
        stages=stages,
        artifacts=artifacts,
        message="" if not issues else "共 {0} 项发现".format(len(issues)),
    )


def _collect_lint_issues(manifest, paths) -> List[IssueRecord]:
    """收集内容检查结果（与 GUI/CLI lint 同一服务）。"""
    from doc_tool.application.content.index import ContentIndexService
    from doc_tool.application.content.lint import ContentLinter, TermStore
    from doc_tool.application.content.quality_rules import QualityRulesConfig
    from doc_tool.application.issues import issues_from_lint

    content_root = paths.resolve(manifest.relative_content_root())
    index = ContentIndexService(content_root).build()
    rules_config = QualityRulesConfig(
        paths.state_dir, manifest.documentType, writable=False
    )
    raw = ContentLinter(index, rules_config).check_all(TermStore(paths.state_dir).load())
    return issues_from_lint(raw, manifest.documentType)


def serialize_check_text(report: CheckReport) -> str:
    """人看的单文档输出（stdout）。"""
    lines = [
        "项目：{0}".format(report.project_id),
        "结论：{0}（exitCode={1}，阀值 fail-on={2}{3}）".format(
            {"ok": "通过", "warning": "带提醒通过", "failed": "未通过"}.get(
                report.status, report.status
            ),
            report.exit_code,
            report.fail_on,
            "，严格模式" if report.strict else "",
        ),
    ]
    if report.issues:
        lines.append("")
        lines.append("问题：")
        for issue in report.sorted_issues():
            where = issue.rel_path or "—"
            if issue.line_no is not None:
                where = "{0}:{1}".format(where, issue.line_no)
            lines.append(
                "  [{0}] {1} {2} — {3}".format(
                    issue.severity, issue.issue_type, where, issue.message
                )
            )
    lines.append("")
    lines.append("阶段：")
    for stage in report.stages:
        lines.append(
            "  {0}: {1}{2}".format(
                stage.stage,
                stage.status,
                "（{0}）".format(stage.detail) if stage.detail else "",
            )
        )
    if report.artifacts:
        lines.append("")
        lines.append("产物：")
        for artifact in report.artifacts:
            lines.append("  {0} [{1}]".format(artifact.path, artifact.status))
    return "\n".join(lines)