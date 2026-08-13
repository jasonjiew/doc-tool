# -*- coding: utf-8 -*-
"""CLI 命令应用层：只返回结构化结果，不负责打印。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from doc_tool.application.issues import IssueRecord, issues_from_validation_report
from doc_tool.domain.errors import DocToolError


@dataclass
class ProjectCommandResult:
    project: str
    success: bool
    error_code: str = ""
    suggested_action: str = ""
    data: Any = None
    issues: List[IssueRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "success": self.success,
            "errorCode": self.error_code or None,
            "suggestedAction": self.suggested_action,
            "data": to_json_value(self.data),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class CommandResult:
    command: str
    results: List[ProjectCommandResult]

    @property
    def success(self) -> bool:
        return bool(self.results) and all(item.success for item in self.results)

    @property
    def exit_code(self) -> int:
        succeeded = sum(1 for item in self.results if item.success)
        failed = len(self.results) - succeeded
        if failed == 0:
            return 0
        if succeeded and failed:
            return 3
        return 1

    def to_dict(self) -> dict:
        error_codes = [item.error_code for item in self.results if item.error_code]
        return {
            "schemaVersion": 1,
            "command": self.command,
            "success": self.success,
            "errorCode": error_codes[0] if len(set(error_codes)) == 1 else None,
            "results": [item.to_dict() for item in self.results],
        }


def to_json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_value(item) for item in value]
    return value


def _failure(project: str, exc: Exception) -> ProjectCommandResult:
    if isinstance(exc, DocToolError):
        return ProjectCommandResult(
            project=project,
            success=False,
            error_code=exc.code,
            suggested_action=exc.suggested_action,
            data={"message": exc.user_message, "details": exc.details},
        )
    return ProjectCommandResult(
        project=project,
        success=False,
        error_code="E9000",
        suggested_action="请查看 stderr 与运行日志。",
        data={"message": str(exc) or type(exc).__name__},
    )


def run_per_project(
    command: str, projects: Iterable[str], operation: Callable[[Path], ProjectCommandResult]
) -> CommandResult:
    results = []
    for raw_project in projects:
        project = str(Path(raw_project).resolve())
        try:
            results.append(operation(Path(project)))
        except Exception as exc:  # noqa: BLE001 - command boundary
            results.append(_failure(project, exc))
    return CommandResult(command, results)


def preflight_command(docx: str) -> CommandResult:
    from doc_tool.adapters.preflight import preflight

    label = str(Path(docx).resolve())
    try:
        preview = preflight(label)
        result = ProjectCommandResult(label, True, data=preview)
    except Exception as exc:  # noqa: BLE001
        result = _failure(label, exc)
    return CommandResult("preflight", [result])


def import_command(args) -> CommandResult:
    from doc_tool.application.import_project import ImportRequest, import_first_time

    target = Path(args.target_dir).resolve() / args.name
    request = ImportRequest(
        source_docx=Path(args.docx),
        target_project_root=target,
        document_type=args.document_type,
        document_no=args.document_no,
        document_name=args.document_name or args.name,
        document_version=args.document_version,
    )
    result = import_first_time(request)
    item = ProjectCommandResult(
        project=str(target),
        success=result.success,
        error_code=result.error_code or "",
        suggested_action="请查看导入诊断日志并修正源文档。" if not result.success else "",
        data={
            "projectRoot": str(result.project_root) if result.project_root else None,
            "sourceSha256": result.source_sha256,
            "events": [to_json_value(event) for event in result.events],
            "diagnosticLog": str(result.diagnostic_log) if result.diagnostic_log else None,
        },
    )
    return CommandResult("import", [item])


def migrate_command(args) -> CommandResult:
    """把旧版专用项目迁移为通用项目（复制到新目录 + 验证后原子发布）。"""
    from doc_tool.application.migrate_project import migrate_legacy_project

    source = str(Path(args.project).resolve())
    target = str((Path(args.target)).resolve())
    result = migrate_legacy_project(source, target)
    item = ProjectCommandResult(
        project=source,
        success=result.success,
        error_code=result.error_code or "",
        suggested_action="请查看迁移报告并修正源项目内容后重试。" if not result.success else "",
        data={
            "target": str(result.target),
            "report": str(result.report_path) if result.report_path else None,
            "events": [to_json_value(event) for event in result.events],
        },
    )
    return CommandResult("migrate", [item])


def validate_command(projects: Iterable[str]) -> CommandResult:
    def operation(root: Path) -> ProjectCommandResult:
        from doc_tool.adapters.kernel import validate_with_project
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(root)
        paths = manifest.resolve_paths(root)
        passed = validate_with_project(manifest, paths)
        report = paths.logs_dir / (manifest.documentType + "-validation.md")
        issues = issues_from_validation_report(report, manifest.documentType)
        return ProjectCommandResult(
            str(root), passed, "" if passed else "E2002",
            "" if passed else "请根据校验报告修正对应章节或资源后重试。",
            data={"documentType": manifest.documentType, "report": str(report)},
            issues=issues,
        )

    return run_per_project("validate", projects, operation)


def lint_command(projects: Iterable[str]) -> CommandResult:
    def operation(root: Path) -> ProjectCommandResult:
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.lint import ContentLinter, TermStore
        from doc_tool.application.content.quality_rules import QualityRulesConfig
        from doc_tool.application.issues import issues_from_lint
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(root)
        paths = manifest.resolve_paths(root)
        content_root = paths.resolve(manifest.relative_content_root())
        index = ContentIndexService(content_root).build()
        config = QualityRulesConfig(paths.state_dir, manifest.documentType, writable=False)
        raw = ContentLinter(index, config).check_all(TermStore(paths.state_dir).load())
        issues = issues_from_lint(raw, manifest.documentType)
        return ProjectCommandResult(
            str(root), not issues, "" if not issues else "E2002",
            "" if not issues else "请修正 lint 发现后重试。",
            data={"documentType": manifest.documentType, "issueCount": len(issues)},
            issues=issues,
        )

    return run_per_project("lint", projects, operation)


def search_command(projects: Iterable[str], query: str, args) -> CommandResult:
    def operation(root: Path) -> ProjectCommandResult:
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.search import SearchOptions, SearchService
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(root)
        paths = manifest.resolve_paths(root)
        content_root = paths.resolve(manifest.relative_content_root())
        result = SearchService(ContentIndexService(content_root).build()).search(
            SearchOptions(
                query=query,
                regex=args.regex,
                case_sensitive=args.case_sensitive,
                whole_word=args.whole_word,
                limit=args.limit,
            )
        )
        return ProjectCommandResult(str(root), True, data=result)

    return run_per_project("search", projects, operation)


def status_command(projects: Iterable[str]) -> CommandResult:
    def operation(root: Path) -> ProjectCommandResult:
        from doc_tool.application.project_service import open_project

        summary = open_project(str(root))
        return ProjectCommandResult(str(root), True, data={
            "documentType": summary.manifest.documentType,
            "documentNo": summary.manifest.documentNo,
            "documentName": summary.manifest.documentName,
            "documentVersion": summary.manifest.documentVersion,
            "writable": summary.is_writable,
            "sourceExists": summary.source_exists,
            "templateExists": summary.template_exists,
            "contentExists": summary.content_exists,
            "outputExists": summary.output_exists,
            "lock": summary.lock_info,
        })

    return run_per_project("status", projects, operation)
