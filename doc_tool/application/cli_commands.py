# -*- coding: utf-8 -*-
"""CLI 命令应用层：只返回结构化结果，不负责打印。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Tuple

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
        if not self.results:
            return 2  # 无项目可执行：视为用法/输入错误，不得静默成功
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

    # 项目名必须是单层目录名：含 / \ .. 或盘符会逃逸 target_dir 之外。
    name = (args.name or "").strip()
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        or ":" in name
    ):
        return CommandResult("import", [
            ProjectCommandResult(
                str(Path(args.target_dir).resolve()),
                False, "E5001",
                "项目名必须是单层目录名（不能含路径分隔符、盘符或 ..）。",
                data={"message": "非法项目名：{0!r}".format(args.name)},
            )
        ])
    target = Path(args.target_dir).resolve() / name
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
    # 失败时迁移报告不会写出（report_path 为 None），真实原因在最后一条事件明细中；
    # 把它透出到 message 供 human 序列化显示，避免只给一个指向不存在报告的笼统建议。
    failure_detail = ""
    if not result.success and result.last_event is not None:
        failure_detail = result.last_event.detail
    item = ProjectCommandResult(
        project=source,
        success=result.success,
        error_code=result.error_code or "",
        suggested_action=(
            "" if result.success else
            "请修正源项目内容后重试。"
        ),
        data={
            "target": str(result.target),
            "report": str(result.report_path) if result.report_path else None,
            "events": [to_json_value(event) for event in result.events],
            "message": failure_detail or None,
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


def renumber_command(args) -> CommandResult:
    """一键重编号：把章节目录下已编号子节点重排为连续编号。

    缺省仅 dry-run 预览（不写盘）；``--apply`` 才经 RefactorService 联动
    更新引用与标题后写盘。``--dir`` 限定时只扫描该内容相对目录（相对
    contentRoot，如 ``第4章 WEB端功能设计/4.7 示例模块``），否则扫描整个
    内容根下全部带编号的章节目录。
    """

    def operation(root: Path) -> ProjectCommandResult:
        from doc_tool.application.content.index import ContentIndexService
        from doc_tool.application.content.refactor import RefactorService
        from doc_tool.application.content.tree import (
            ChapterMoveError,
            renumber_plan,
        )
        from doc_tool.application.content.writer import ContentWriter
        from doc_tool.domain.manifest import ProjectManifest

        manifest = ProjectManifest.load(root)
        paths = manifest.resolve_paths(root)
        content_root = paths.resolve(manifest.relative_content_root())
        index = ContentIndexService(content_root).build()
        service = RefactorService(index)
        target = (getattr(args, "dir", "") or "").strip().replace("\\", "/").strip("/")
        if target:
            directories = [target]
        else:
            directories = sorted(
                {str(Path(rel).parent.as_posix()) for rel in index.files}
            )
        renamed: List[Tuple[str, str]] = []
        for directory in directories:
            if not directory or directory == ".":
                continue
            try:
                renamed.extend(renumber_plan(directory, index.files))
            except ChapterMoveError as exc:
                return ProjectCommandResult(
                    str(root), False, "E2003",
                    "重编号计划冲突：{0}".format(exc),
                    data={"message": str(exc)},
                )
        preview = [{"old": old, "new": new} for old, new in renamed]
        if not renamed:
            if target:
                # 用户显式指定 --dir 却无任何命中：静默成功会让脚本误以为已重排。
                return ProjectCommandResult(
                    str(root), False, "E2003",
                    "指定目录下未找到需要重编号的章节。",
                    data={
                        "message": "指定目录下未找到需要重编号的章节",
                        "renamed": 0, "preview": [], "applied": False,
                        "directories": [],
                    },
                )
            return ProjectCommandResult(
                str(root), True,
                data={
                    "renamed": 0, "preview": [], "applied": False,
                    "directories": [],
                },
            )
        batch = service.compute_batch_rename_plan(renamed)
        if batch is None:
            return ProjectCommandResult(
                str(root), False, "E2003",
                "内容索引与文件不一致，请刷新后重试。",
                data={"message": "无法生成重命名计划", "preview": preview},
            )
        if batch.conflicts:
            return ProjectCommandResult(
                str(root), False, "E2003",
                "重编号计划存在冲突，请检查目标路径占用。",
                data={"message": "；".join(batch.conflicts), "preview": preview},
            )
        directories = sorted(
            {str(Path(old).parent.as_posix()) for old, _new in renamed}
        )
        if not args.apply:
            return ProjectCommandResult(
                str(root), True,
                data={
                    "renamed": len(renamed), "preview": preview,
                    "applied": False, "directories": directories,
                },
            )
        writer = ContentWriter(content_root, paths.state_dir)
        try:
            results = service.apply_rename_plan(batch, writer)
        except (OSError, ValueError) as exc:
            # apply_rename_plan 内部已事务回滚；把失败映射为 E2003 而非通用
            # E9000，便于调用方按重编号语义处理。
            return ProjectCommandResult(
                str(root), False, "E2003",
                "重编号写回失败，本次改动已回滚。",
                data={"message": str(exc), "preview": preview},
            )
        if not all(r.written for r in results):
            failures = [r.error or r.rel_path for r in results if not r.written]
            return ProjectCommandResult(
                str(root), False, "E2003",
                "部分重编号写回失败，请查看备份与改动清单。",
                data={"message": "；".join(failures), "preview": preview},
            )
        return ProjectCommandResult(
            str(root), True,
            data={
                "renamed": len(renamed), "preview": preview,
                "applied": True, "directories": directories,
            },
        )

    return run_per_project("renumber", [args.project], operation)
