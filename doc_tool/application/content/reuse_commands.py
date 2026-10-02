# -*- coding: utf-8 -*-
"""V3.0 正文复用入口适配层（批次 30-F：CLI 与界面共用同一份服务入口）。

本模块**只新增适配**，不改动既有服务实现：

- ``doc_tool/application/content/modules.py``（模块库、提取、导入导出）
- ``doc_tool/application/content/module_refs.py``（固定引用展开、装配、升级、实例）
- ``doc_tool/application/content/variants.py``（产品变体有效内容、独立出稿、展开副本）

CLI 子命令与（可选）界面模块库面板都调用这里的公开函数，因此
「引用解析 / 实例 / 变体」只有一个入口，跨入口拿到的是同一份 ``Resolution``/报告。

关键约束（对齐 design.md D2/D3 与任务 1.3/2.1/2.4/2.5/3.4/4.4/5.2/6.4）：

- 参数只作文本替换、标题偏移只改输出层级、资源按项目相对路径改写，全部复用既有
  resolver；本层不重新实现 Markdown/OOXML。
- 缺模块取「项目固定副本 → 库同版本缓存 → 可读占位」；参数缺项取「声明默认 →
  保留字面值」；循环引用只停止该引用。
- 旧 v1/v2 项目不写 sidecar 时行为不变：``resolve_text`` 返回原文且无 warning。

退出码约定（与 ``project-export``/``assist-*`` 同风格，自带机器报告）::

    0 = 有可用正文
    2 = 参数非法（项目不存在、变体未知、模块不存在、参数格式错、严格模式未达标）
    1 = 完全无可用内容（有效章节为空或全部不可读）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content import module_refs as refs
from doc_tool.application.content import modules as module_lib
from doc_tool.application.content import variants as variants_lib

#: 退出码：有可用正文。
EXIT_OK = 0
#: 退出码：完全无可用内容。
EXIT_EMPTY = 1
#: 退出码：参数非法（未知变体/未知模块/项目缺失）。
EXIT_USAGE = 2

#: 缺省模块库目录名（相对项目根）。
DEFAULT_LIBRARY_RELATIVE = "reuse/library"

#: 人读报告里的状态用语。
STATUS_TEXT = {"ok": "有可用正文", "empty": "无可用内容", "invalid": "参数非法"}


# --------------------------------------------------------------------------
# 项目上下文（同一份扫描/装配/变体输入）
# --------------------------------------------------------------------------


@dataclass
class ProjectReuseContext:
    """一个项目的复用上下文：章节顺序、变量、装配、变体配置与库。"""

    project_root: Path
    document_type: str = "general"
    content_root: Path = field(default_factory=Path)
    asset_root: Path = field(default_factory=Path)
    manifest: object = None
    discovered: List[str] = field(default_factory=list)
    declared: List[str] = field(default_factory=list)
    project_variables: Dict[str, str] = field(default_factory=dict)
    assembly: refs.Assembly = field(default_factory=refs.Assembly)
    config: variants_lib.VariantsConfig = field(default_factory=variants_lib.VariantsConfig)
    instances: refs.InstanceBook = field(default_factory=refs.InstanceBook)
    library: Optional[module_lib.ModuleLibrary] = None
    libraryRoot: str = ""
    warnings: List[str] = field(default_factory=list)

    def chapter_path(self, relative: str) -> Path:
        return self.content_root / str(relative).replace("\\", "/")

    def read_chapter(self, relative: str) -> Optional[str]:
        path = self.chapter_path(relative)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    def variant(self, variant_id: str = "") -> Optional[variants_lib.Variant]:
        if not str(variant_id or "").strip():
            return None
        return self.config.get(str(variant_id))

    def to_dict(self) -> Dict[str, object]:
        return {
            "projectRoot": str(self.project_root),
            "documentType": self.document_type,
            "contentRoot": str(self.content_root),
            "assetRoot": str(self.asset_root),
            "chapters": list(self.discovered),
            "declared": list(self.declared),
            "variables": dict(self.project_variables),
            "assemblySlots": [slot.to_dict() for slot in self.assembly.slots],
            "variants": self.config.ids(),
            "instances": len(self.instances.entries()),
            "library": self.libraryRoot,
            "warnings": list(self.warnings),
        }


def discover_chapters(content_root) -> List[str]:
    """按相对路径扫描章节 Markdown，跳过项目内部文件。

    与 ``effective_snapshot``/``reimport`` 同一口径跳过 ``_revision_record.md``
    这类下划线前缀的内部 Markdown（修订记录不是章节），避免解析报告把内部文件
    当成待解析正文。
    """
    root = Path(content_root)
    if not root.is_dir():
        return []
    found: List[str] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        parts = relative.split("/")
        if any(part.startswith(".") for part in parts):
            continue
        name = parts[-1]
        if name.startswith("_") or name.startswith("~$"):
            continue
        found.append(relative)
    return found


def configured_library(project_root: Path) -> Optional[Path]:
    """从 ``project.yml`` 的可选 ``reuse.library`` 读库目录（字段缺失即没有）。"""
    try:
        import yaml

        manifest_path = Path(project_root) / "project.yml"
        if not manifest_path.is_file():
            return None
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 读不到就当未配置，不阻断
        return None
    if not isinstance(data, dict):
        return None
    section = data.get("reuse")
    if not isinstance(section, dict):
        return None
    value = str(section.get("library") or "").strip()
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (Path(project_root) / candidate)


def library_root_for(project_root, library_root=None) -> Optional[Path]:
    """决定本次使用的库目录：显式 → 项目内固定副本 → 项目配置 → ``reuse/library``。"""
    if library_root:
        return Path(library_root)
    root = Path(project_root)
    project_modules = module_lib.project_module_root(root)
    if project_modules.is_dir():
        return project_modules
    configured = configured_library(root)
    if configured is not None:
        return configured
    fallback = root / DEFAULT_LIBRARY_RELATIVE
    if fallback.is_dir():
        return fallback
    return None


def load_library(project_root, library_root=None) -> Optional[module_lib.ModuleLibrary]:
    """打开模块库；无处可读时返回 None（表示未配置库，不是错误）。"""
    root = library_root_for(project_root, library_root)
    if root is None:
        return None
    return module_lib.ModuleLibrary(root)


def load_context(
    project_root,
    *,
    library_root=None,
) -> ProjectReuseContext:
    """读取项目复用上下文；缺 sidecar 时按「无复用项目」返回空装配/空变体。"""
    from doc_tool.domain.manifest import ProjectManifest

    root = Path(project_root).resolve()
    manifest = ProjectManifest.load(root)
    paths = manifest.resolve_paths(root)
    context = ProjectReuseContext(project_root=root, manifest=manifest)
    context.document_type = str(getattr(manifest, "documentType", "") or "general")
    context.content_root = Path(paths.content_dir(context.document_type))
    context.asset_root = Path(paths.assets_dir(context.document_type))
    context.discovered = discover_chapters(context.content_root)
    context.declared = [
        str(item).replace("\\", "/")
        for item in (getattr(manifest, "chapters", None) or [])
        if str(item or "").strip()
    ]
    context.project_variables = dict(getattr(manifest, "variables", None) or {})
    context.assembly = refs.Assembly.load(root)
    context.config = variants_lib.VariantsConfig.load(root)
    context.instances = refs.InstanceBook.load(root)
    context.library = load_library(root, library_root)
    context.libraryRoot = str(context.library.root) if context.library is not None else ""
    if context.library is not None:
        for issue in context.library.issues:
            context.warnings.append(issue.message)
        if context.library.index_error and context.library.damaged_report:
            context.warnings.append(context.library.damaged_report)
    return context
# --------------------------------------------------------------------------
# 1.3 / 2.1 / 2.4：同一份解析入口（CLI 与界面共用）
# --------------------------------------------------------------------------


def variant_selection(
    context: ProjectReuseContext,
    variant_id: str = "",
) -> Tuple[Optional[variants_lib.Variant], Optional[Dict[str, object]]]:
    """解析变体选择：返回 ``(变体或 None, 失败报告或 None)``。

    明确指定不存在的 variantId 时**不偷偷换型号**，返回失败报告（CLI 退出码 2）。
    """
    variant_id = str(variant_id or "").strip()
    if not variant_id:
        return None, None
    variant = context.config.get(variant_id)
    if variant is not None:
        return variant, None
    if not context.config.variants:
        return None, {
            "ok": False,
            "error": "unknown-variant",
            "message": "项目没有 variants.yml 变体配置；请先添加变体或去掉 --variant。",
            "requested": variant_id,
            "options": [],
        }
    return None, {
        "ok": False,
        "error": "unknown-variant",
        "message": variants_lib.unknown_variant_message(context.config, variant_id),
        "requested": variant_id,
        "options": context.config.ids(),
    }


@dataclass
class ResolutionPlan:
    """解析规划：章节/变量/覆盖 + 范围证据（尚未展开正文）。"""

    context: ProjectReuseContext
    variantId: str = ""
    variant: Optional[variants_lib.Variant] = None
    chapters: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    slot_overrides: Dict[str, Dict[str, object]] = field(default_factory=dict)
    scope: Optional[variants_lib.VariantScope] = None
    warnings: List[str] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    message: str = ""
    options: List[str] = field(default_factory=list)


def plan_project(
    context: ProjectReuseContext,
    *,
    variant_id: str = "",
) -> ResolutionPlan:
    """算出一次解析的全部输入：有效章节、变量、slot 覆盖与范围证据。

    这是 CLI 与界面共用的规划入口；调用它之后才真正展开正文。
    """
    variant, failure = variant_selection(context, variant_id)
    plan = ResolutionPlan(context=context, variantId=str(variant_id or "").strip())
    if failure is not None:
        plan.ok = False
        plan.error = str(failure.get("error") or "unknown-variant")
        plan.message = str(failure.get("message") or "")
        plan.options = [str(item) for item in (failure.get("options") or [])]
        return plan
    plan.variant = variant
    chapters, excluded, chapter_warnings = variants_lib.effective_chapters(
        context.discovered, context.declared, variant
    )
    plan.chapters = chapters
    plan.excluded = excluded
    plan.warnings.extend(chapter_warnings)
    variables, variable_warnings = variants_lib.effective_variables(
        context.project_variables, variant
    )
    plan.variables = variables
    plan.warnings.extend(variable_warnings)
    # 装配里的固定参数是项目级事实：先铺一层，再由变体覆盖（原 Assembly 不被就地修改）。
    baseline = {
        slot.slotId: {"version": slot.version, "params": dict(slot.params)}
        for slot in context.assembly.slots
    }
    variant_overrides, override_warnings = variants_lib.effective_slot_overrides(
        context.assembly, variant
    )
    for slot_id, row in variant_overrides.items():
        current = baseline.setdefault(slot_id, {})
        for key, value in row.items():
            if key == "params" and isinstance(value, dict):
                current["params"] = {**dict(current.get("params") or {}), **value}
            elif value not in (None, "", {}):
                current[key] = value
    plan.slot_overrides = baseline
    plan.warnings.extend(override_warnings)
    if variant is not None:
        scope = variants_lib.variant_scope(
            variant,
            discovered=context.discovered,
            declared=context.declared,
            project_variables=context.project_variables,
            assembly=context.assembly,
        )
        plan.scope = scope
        plan.warnings.extend(scope.warnings)
    return plan


def resolve_text(
    text: str,
    context: ProjectReuseContext,
    *,
    host_path: str = "",
    slot_overrides: Optional[Dict[str, Dict[str, object]]] = None,
    variables: Optional[Dict[str, str]] = None,
    cache: Optional[refs.ResolutionCache] = None,
    strict: bool = False,
) -> refs.Resolution:
    """对单份正文走项目统一解析路径（预览/Word/HTML/检查/CLI 同一入口）。

    这是 ``doc_tool.application.prepared_source.prepare_markdown`` 的上游适配点：
    Mermaid/资源预处理之前先展开固定引用，资源基准与宿主项目保持一致。

    ``slot_overrides`` 为 ``None`` 时沿用装配里的固定参数（项目固定参数是项目级
    事实，任何入口都该一致）；显式传 ``{}`` 表示本次不看装配参数。
    """
    if slot_overrides is None:
        overrides = {
            slot.slotId: {"version": slot.version, "params": dict(slot.params)}
            for slot in context.assembly.slots
        }
    else:
        overrides = slot_overrides
    return refs.resolve_body(
        text,
        project_root=context.project_root,
        library=context.library,
        variables=variables if variables is not None else {},
        host_path=host_path,
        asset_root=context.project_root,
        cache=cache,
        slot_overrides=overrides,
        strict=bool(strict),
    )


@dataclass
class ChapterResolution:
    """一章的展开结果：宿主路径 + Resolution + 来源定位。"""

    hostPath: str
    resolution: refs.Resolution
    sources: List[Dict[str, object]] = field(default_factory=list)
    missing: bool = False
    unreadable: bool = False

    @property
    def text(self) -> str:
        return self.resolution.text

    def to_dict(self, *, withText: bool = False) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "hostPath": self.hostPath,
            "missing": bool(self.missing),
            "unreadable": bool(self.unreadable),
            "changed": bool(self.resolution.changed),
            "degraded": bool(self.resolution.degraded),
            "warnings": list(self.resolution.warnings),
            "errors": list(self.resolution.errors),
            "slots": list(self.resolution.slots),
            "copies": list(self.resolution.copies),
            "dependencies": dict(self.resolution.dependencies),
            "resources": {
                key: str(value) for key, value in self.resolution.resources().items()
            },
            "sources": list(self.sources),
        }
        if withText:
            payload["text"] = self.resolution.text
        return payload


def describe_sources(
    resolution: refs.Resolution,
    *,
    host_path: str = "",
) -> List[Dict[str, object]]:
    """3.4 来源与定位：每个引用的模块/版本/hash/章节相对路径 + 行号。"""
    rows: List[Dict[str, object]] = []
    for segment in resolution.module_segments():
        origin = segment.origin
        rows.append(
            {
                "slotId": segment.slotId,
                "moduleId": segment.moduleId,
                "version": segment.version,
                "identity": "{0}@{1}".format(segment.moduleId, segment.version),
                "moduleDir": str(segment.moduleDir) if segment.moduleDir else "",
                "hostPath": (origin.hostPath if origin is not None else host_path),
                "hostLine": int(origin.hostLine) if origin is not None else 0,
                "moduleLine": int(origin.moduleLine) if origin is not None else 0,
                "params": dict(segment.params),
                "paramsFromDeclared": list(segment.paramsFromDeclared),
                "dependencyHashes": dict(segment.dependencyHashes),
                "resources": {
                    key: str(value) for key, value in segment.resources.items()
                },
                "degraded": bool(segment.degraded),
                "warnings": list(segment.warnings),
            }
        )
    return rows


def resolve_chapter(
    context: ProjectReuseContext,
    host_path: str,
    *,
    plan: Optional[ResolutionPlan] = None,
    cache: Optional[refs.ResolutionCache] = None,
    strict: bool = False,
) -> ChapterResolution:
    """展开一章正文（同一入口）；文件缺失/不可读给可解释标记而不是异常。"""
    if plan is None:
        plan = plan_project(context)
    path = context.chapter_path(host_path)
    text = context.read_chapter(host_path)
    if text is None:
        resolution = refs.Resolution()
        resolution.errors.append("章节不可用：{0}".format(host_path))
        chapter = ChapterResolution(hostPath=host_path, resolution=resolution)
        chapter.missing = not path.exists()
        chapter.unreadable = path.exists()
        return chapter
    resolution = resolve_text(
        text,
        context,
        host_path=host_path,
        slot_overrides=(plan.slot_overrides if plan is not None else None),
        variables=plan.variables,
        cache=cache,
        strict=bool(strict),
    )
    return ChapterResolution(
        hostPath=host_path,
        resolution=resolution,
        sources=describe_sources(resolution, host_path=host_path),
    )


def record_instances(
    context: ProjectReuseContext,
    *,
    variant_id: str = "",
    slot_ids: Optional[Sequence[str]] = None,
    cache: Optional[refs.ResolutionCache] = None,
) -> Dict[str, object]:
    """把**明确纳入追踪**的 slot 条目落盘为实例映射并给出覆盖率（V3.0 4.3）。

    - 默认只登记调用方点名的 slot（``slot_ids``）；不点名时按解析结果里的模块引用登记，
      但分母始终只含“明确纳入”的实例（沿用 ``include_items_in_tracking`` 语义）。
    - 已存在的实例 UUID 复用（``InstanceBook.load``），重复执行幂等。
    """
    plan = plan_project(context, variant_id=variant_id)
    if not plan.ok:
        return {
            "ok": False,
            "error": plan.error,
            "message": plan.message,
            "options": list(plan.options),
            "exitCode": EXIT_USAGE,
        }
    book = refs.InstanceBook.load(context.project_root)
    registered = 0
    for chapter in plan.chapters:
        resolved = resolve_chapter(context, chapter, plan=plan, cache=cache)
        registered += len(refs.include_items_in_tracking(
            book, resolved.resolution, host_path=chapter, slot_ids=slot_ids,
        ))
    # 悬空实例（slot 已不存在）只作证据保留，不进本次写入的映射。
    live_slots = {
        segment.slotId
        for chapter in plan.chapters
        for segment in resolve_chapter(
            context, chapter, plan=plan, cache=cache
        ).resolution.module_segments()
    }
    if live_slots:
        dangling = {item.instanceId for item in book.pruned(live_slots)}
        book = refs.InstanceBook(
            context.project_root,
            instances=[item for item in book.entries() if item.instanceId not in dangling],
        )
    saved = book.save(context.project_root)
    coverage = book.coverage()
    return {
        "ok": True,
        "projectRoot": str(context.project_root),
        "path": str(saved or book.path or ""),
        "registered": registered,
        "instances": len(book.entries()),
        "coverage": coverage.to_dict(),
        "denominator": coverage.denominator,
        "exitCode": EXIT_OK,
    }


#: 内部别名：`resolve_project` 的参数同名，直接调用会被遮蔽。
_record_instances_impl = record_instances


def resolve_project(
    context: ProjectReuseContext,
    *,
    variant_id: str = "",
    strict: bool = False,
    withText: bool = False,
    cache: Optional[refs.ResolutionCache] = None,
    record_instances: bool = False,
    slot_ids: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """对整项目（可选变体）生成解析报告：正文可用性 + 来源定位 + 兜底清单。"""
    plan = plan_project(context, variant_id=variant_id)
    report: Dict[str, object] = {
        "ok": True,
        "projectRoot": str(context.project_root),
        "documentType": context.document_type,
        "variantId": plan.variantId,
        "chapters": list(plan.chapters),
        "excluded": list(plan.excluded),
        "warnings": list(context.warnings) + list(plan.warnings),
        "sources": [],
        "chaptersDetail": [],
        "status": "ok",
        "exitCode": EXIT_OK,
    }
    if not plan.ok:
        report["ok"] = False
        report["error"] = plan.error
        report["message"] = plan.message
        report["options"] = list(plan.options)
        report["status"] = "invalid"
        report["exitCode"] = EXIT_USAGE
        return report

    strict_errors: List[str] = []
    usable = 0
    for chapter in plan.chapters:
        resolved = resolve_chapter(
            context, chapter, plan=plan, cache=cache, strict=bool(strict)
        )
        report["sources"].extend(resolved.sources)
        report["chaptersDetail"].append(resolved.to_dict(withText=withText))
        if not (resolved.missing or resolved.unreadable):
            usable += 1
        strict_errors.extend(resolved.resolution.errors)
    if record_instances:
        instances = _record_instances_impl(
            context, variant_id=variant_id, slot_ids=slot_ids, cache=cache,
        )
        report["instances"] = instances
        report["coverage"] = instances.get("coverage")
        if not instances.get("ok"):
            report["warnings"] = list(report["warnings"]) + [
                "实例登记未完成：{0}".format(instances.get("message") or instances.get("error") or "")
            ]
    if plan.scope is not None:
        report["scope"] = plan.scope.to_dict()
    if plan.variant is not None:
        report["variantName"] = plan.variant.name
        report["variables"] = dict(plan.variables)
    report["degradation"] = [
        warning
        for detail in report["chaptersDetail"]
        for warning in (detail.get("warnings") or [])
    ]
    report["usableChapters"] = usable
    if usable == 0:
        report["status"] = "empty"
        report["exitCode"] = EXIT_EMPTY
    elif strict_errors:
        report["status"] = "invalid"
        report["exitCode"] = EXIT_USAGE
        report["strictErrors"] = strict_errors
    return report


def _short_hash(value) -> str:
    text = str(value or "")
    return text[:12] if text else "（未知）"


def render_resolution_text(report: Dict[str, object]) -> str:
    """人读形式的解析报告（与 JSON 报告同源，不另算一遍）。"""
    lines: List[str] = []
    if report.get("status") == "invalid" and not report.get("chaptersDetail"):
        lines.append("[FAIL] {0}".format(report.get("message") or "参数非法"))
        options = report.get("options") or []
        if options:
            lines.append("可选变体：{0}".format("、".join(str(item) for item in options)))
        return "\n".join(lines)
    lines.append("项目正文解析：{0}".format(report.get("projectRoot", "")))
    variant_id = str(report.get("variantId") or "")
    if variant_id:
        lines.append(
            "变体：{0}（{1}）".format(variant_id, report.get("variantName") or variant_id)
        )
    chapters = report.get("chapters") or []
    lines.append("有效章节（{0}）：".format(len(chapters)))
    for chapter in chapters:
        lines.append("  - {0}".format(chapter))
    excluded = report.get("excluded") or []
    if excluded:
        lines.append("范围外：{0}".format("、".join(str(item) for item in excluded)))
    sources = report.get("sources") or []
    lines.append("引用来源（{0}）：".format(len(sources)))
    for row in sources:
        hashes = row.get("dependencyHashes") or {}
        lines.append(
            "  - slot {0} → {1} [{2}] bodyHash={3} @{4}:{5}".format(
                row.get("slotId") or "（无）",
                row.get("identity") or "",
                row.get("moduleDir") or "（未解析到目录）",
                _short_hash(hashes.get(row.get("identity") or "")),
                row.get("hostPath") or "",
                row.get("hostLine") or 0,
            )
        )
    degradation = report.get("degradation") or []
    lines.append("兜底提示（{0}）：".format(len(degradation)))
    for warning in degradation:
        lines.append("  - {0}".format(warning))
    for warning in report.get("warnings") or []:
        lines.append("  - [项目] {0}".format(warning))
    lines.append(
        "结果：{0}（可用章节 {1}/{2}）".format(
            STATUS_TEXT.get(str(report.get("status")), str(report.get("status"))),
            report.get("usableChapters", 0),
            len(chapters),
        )
    )
    return "\n".join(lines)


def render_report(report: Dict[str, object], output: str = "human") -> str:
    """统一出口：human / json 两种形式（CLI 与界面共用同一份报告）。"""
    if str(output or "human").lower() == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    return render_resolution_text(report)
# --------------------------------------------------------------------------
# 5.2 / 5.3：变体有效范围、独立出稿与展开副本
# --------------------------------------------------------------------------


def variant_evidence(
    context: ProjectReuseContext,
    variant_id: str = "",
) -> Dict[str, object]:
    """查看可用变体与其有效范围（先显示可用内容，再列待完善项）。"""
    plan = plan_project(context, variant_id=variant_id)
    payload: Dict[str, object] = {
        "ok": plan.ok,
        "projectRoot": str(context.project_root),
        "requested": plan.variantId,
        "available": [
            {
                "variantId": item.variantId,
                "name": item.name,
                "include": list(item.include),
                "exclude": list(item.exclude),
                "modules": dict(item.modules),
            }
            for item in context.config.variants
        ],
        "warnings": list(context.warnings) + list(plan.warnings),
    }
    if not plan.ok:
        payload["error"] = plan.error
        payload["message"] = plan.message
        payload["options"] = list(plan.options)
        return payload
    scope = plan.scope.to_dict() if plan.scope is not None else {}
    payload["scope"] = {
        "variantId": scope.get("variantId") or plan.variantId or "default",
        "chapters": list(plan.chapters),
        "excluded": list(plan.excluded),
        "variables": dict(plan.variables),
        "moduleVersions": dict(scope.get("moduleVersions") or {}),
    }
    payload["chapters"] = list(plan.chapters)
    payload["excluded"] = list(plan.excluded)
    return payload


def build_variant_documents(
    context: ProjectReuseContext,
    *,
    variant_ids: Optional[Sequence[str]] = None,
    output_dir=None,
    document_type: str = "",
    cache: Optional[refs.ResolutionCache] = None,
    copy_assets: bool = True,
) -> Dict[str, object]:
    """按 variantId 生成独立输出目录（互不覆盖），并回传机器报告。"""
    selected = [str(item) for item in (variant_ids or []) if str(item or "").strip()]
    for variant_id in selected:
        if context.config.get(variant_id) is None:
            return {
                "ok": False,
                "error": "unknown-variant",
                "message": (
                    variants_lib.unknown_variant_message(context.config, variant_id)
                    if context.config.variants
                    else "项目没有 variants.yml 变体配置；无法按 --variant 构建。"
                ),
                "requested": variant_id,
                "options": context.config.ids(),
                "exitCode": EXIT_USAGE,
            }
    base = Path(output_dir) if output_dir else (context.project_root / "output" / "variants")
    runs, problems = variants_lib.build_variant_outputs(
        context.project_root,
        base,
        discovered=context.discovered,
        document_type=document_type or context.document_type,
        declared=context.declared,
        project_variables=context.project_variables,
        assembly=context.assembly,
        config=context.config,
        variant_ids=selected or None,
        library=context.library,
        cache=cache,
        copy_assets=copy_assets,
    )
    reports = [variants_lib.variant_report(run) for run in runs]
    return {
        "ok": bool(runs),
        "baseDir": str(base),
        "runs": reports,
        "problems": list(problems),
        "exitCode": EXIT_OK if runs else EXIT_EMPTY,
    }


def write_expanded_copy(
    context: ProjectReuseContext,
    target_dir,
    *,
    variant_id: str = "",
    document_type: str = "",
    cache: Optional[refs.ResolutionCache] = None,
    copy_assets: bool = True,
) -> Dict[str, object]:
    """生成展开兼容副本（普通 Markdown + 资源，可整体搬目录打开）。"""
    plan = plan_project(context, variant_id=variant_id)
    if not plan.ok:
        return {
            "ok": False,
            "error": plan.error,
            "message": plan.message,
            "options": list(plan.options),
            "exitCode": EXIT_USAGE,
        }
    run = variants_lib.write_expanded_copy(
        context.project_root,
        target_dir,
        discovered=context.discovered,
        document_type=document_type or context.document_type,
        declared=context.declared,
        project_variables=context.project_variables,
        assembly=context.assembly,
        variant=plan.variant,
        library=context.library,
        cache=cache,
        copy_assets=copy_assets,
    )
    issues = variants_lib.verify_portable_copy(target_dir)
    report = variants_lib.variant_report(run)
    report["ok"] = not issues
    report["portableIssues"] = [
        {"file": item.file, "line": item.line, "target": item.target, "message": item.message}
        for item in issues
    ]
    report["exitCode"] = EXIT_OK if run.chapters else EXIT_EMPTY
    if issues:
        report["exitCode"] = EXIT_USAGE
    return report


# --------------------------------------------------------------------------
# 2.1 / 2.4：提取、导入/导出包
# --------------------------------------------------------------------------


def _resource_roots(context: ProjectReuseContext) -> List[Path]:
    """资源解析基准：内容根 → 资源根（按顺序回退，不改既有实现）。"""
    return [context.content_root, context.asset_root]


def extract_chapter_module(
    context: ProjectReuseContext,
    chapter: str,
    *,
    module_id: str = "",
    version: str = "1.0.0",
    title: str = "",
    tags: Optional[Sequence[str]] = None,
    description: str = "",
    parameters: Optional[Sequence[object]] = None,
    buffer_text: str = "",
    library_root=None,
) -> Dict[str, object]:
    """2.1 从**已保存章节**或**明确传入的缓冲快照**提取模块并发布进库。

    ``buffer_text`` 非空表示调用方提供了明确快照（界面未保存缓冲）；此时不读盘，
    并在来源里记明 ``source.mode=current-buffer``。资源按内容根/资源根解析。
    """
    source_mode = "current-buffer" if str(buffer_text or "").strip() else "saved"
    body = str(buffer_text or "")
    if not body:
        body = context.read_chapter(chapter) or ""
    if not body:
        return {
            "ok": False,
            "error": "chapter-unavailable",
            "message": "章节无可用正文（既无缓冲快照也读不到已保存内容）：{0}".format(chapter),
            "exitCode": EXIT_USAGE,
        }
    module_id = str(module_id or "").strip() or module_lib.default_module_id(body)
    result = module_lib.extract_module(
        body,
        module_id=module_id,
        version=str(version or "1.0.0"),
        title=title,
        tags=tags,
        description=description,
        parameters=parameters,
        resource_roots=_resource_roots(context),
        base_dir=context.project_root,
        source={
            "path": str(chapter or "").replace("\\", "/"),
            "mode": source_mode,
            "projectRoot": str(context.project_root),
        },
    )
    # 发布目标库：显式 ``library_root`` 优先；否则用项目库，最后回退项目内
    # ``reuse/library``。解析用的 ``context.library`` 可能是项目固定副本目录，
    # 不能当作发布目标，否则提取结果会落进固定副本树。
    if library_root:
        publish_root = Path(library_root)
        publish_library = module_lib.ModuleLibrary(publish_root)
    elif context.library is not None and (
        context.library.root != module_lib.project_module_root(context.project_root)
    ):
        publish_library = context.library
        publish_root = context.library.root
    else:
        publish_root = context.project_root / DEFAULT_LIBRARY_RELATIVE
        publish_library = module_lib.ModuleLibrary(publish_root)
    published = publish_library.publish(result.module, resources=result.sourcePaths)
    return {
        "ok": True,
        "moduleId": published.moduleId,
        "version": published.version,
        "candidate": published.candidate or "",
        "directory": str(published.directory),
        "created": bool(published.created),
        "sourceMode": source_mode,
        "bodySha256": module_lib.sha256_text(result.module.body),
        "collected": list(result.collected),
        "missing": list(result.missing),
        "skipped": list(result.skipped),
        "warnings": list(result.warnings) + list(published.warnings),
        "exitCode": EXIT_OK,
    }


def list_modules(
    library: Optional[module_lib.ModuleLibrary],
    *,
    query: str = "",
    tags: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """库列表/检索：名称、标签、正文索引命中，附各模块可选版本。"""
    if library is None:
        return {
            "ok": True,
            "root": "",
            "modules": [],
            "warnings": ["未配置模块库目录（项目内也没有 reuse/modules）"],
            "exitCode": EXIT_OK,
        }
    rows = []
    for module in library.search(query, tags):
        rows.append({
            "moduleId": module.moduleId,
            "version": module.version,
            "identity": module.identity,
            "title": module.title,
            "tags": list(module.tags),
            "description": module.description,
            "parameters": [item.name for item in module.parameters],
            "resources": [item.path for item in module.resources],
            "versions": library.versions(module.moduleId),
            "bodySha256": module_lib.sha256_text(module.body),
        })
    warnings = [issue.message for issue in library.issues]
    if library.index_error and library.damaged_report:
        warnings.append(library.damaged_report)
    return {
        "ok": True,
        "root": str(library.root),
        "query": query,
        "tags": [str(item) for item in (tags or [])],
        "modules": rows,
        "warnings": warnings,
        "exitCode": EXIT_OK,
    }


def show_module(
    library: Optional[module_lib.ModuleLibrary],
    module_id: str,
    version: str = "",
    *,
    params: Optional[Dict[str, str]] = None,
    with_body: bool = False,
) -> Dict[str, object]:
    """查看模块：版本列表、声明参数、预览正文（参数替换同 resolver 规则）。"""
    if library is None:
        return {
            "ok": False,
            "error": "no-library",
            "message": "未配置模块库目录，无法查看模块。",
            "exitCode": EXIT_USAGE,
        }
    versions = library.versions(module_id)
    chosen = str(version or "").strip() or (versions[-1] if versions else "")
    module = library.get(module_id, chosen) if chosen else None
    if module is None:
        return {
            "ok": False,
            "error": "unknown-module",
            "message": "模块不存在：{0}@{1}（可选版本：{2}）".format(
                module_id, chosen or "（未指定）", "、".join(versions) or "（无）"
            ),
            "versions": versions,
            "exitCode": EXIT_USAGE,
        }
    preview = library.preview(module_id, module.version, params or {})
    payload: Dict[str, object] = {
        "ok": True,
        "moduleId": module.moduleId,
        "version": module.version,
        "identity": module.identity,
        "title": module.title,
        "description": module.description,
        "tags": list(module.tags),
        "versions": versions,
        "parameters": [
            {"name": item.name, "default": item.default, "description": item.description}
            for item in module.parameters
        ],
        "resources": [
            {"path": item.path, "sha256": item.sha256} for item in module.resources
        ],
        "bodySha256": module_lib.sha256_text(module.body),
        "preview": preview or "",
        "warnings": [],
        "exitCode": EXIT_OK,
    }
    if with_body:
        payload["body"] = module.body
    return payload


def export_modules(
    library: Optional[module_lib.ModuleLibrary],
    items: Sequence[Tuple[str, str]],
    target_dir,
) -> Dict[str, object]:
    """2.4 导出模块包（Markdown + 元数据 + 资源）；缺资源不阻断导出。"""
    if library is None:
        return {
            "ok": False,
            "error": "no-library",
            "message": "未配置模块库目录，无法导出。",
            "exitCode": EXIT_USAGE,
        }
    target = Path(target_dir)
    exported: List[Dict[str, object]] = []
    problems: List[str] = []
    for module_id, version in items:
        versions = library.versions(module_id)
        chosen = str(version or "").strip() or (versions[-1] if versions else "")
        module = library.get(module_id, chosen) if chosen else None
        if module is None:
            problems.append(
                "模块不存在：{0}@{1}".format(module_id, chosen or "（未指定）")
            )
            continue
        destination = target / module_lib.slugify(module.moduleId) / module.version
        try:
            library.export_module(module.moduleId, module.version, destination)
        except (OSError, FileNotFoundError) as exc:
            problems.append("导出失败 {0}：{1}".format(module.identity, exc))
            continue
        missing = [
            item.path for item in module.resources
            if not (destination / item.path).is_file()
        ]
        exported.append({
            "moduleId": module.moduleId,
            "version": module.version,
            "directory": str(destination),
            "missingResources": missing,
        })
    return {
        "ok": bool(exported),
        "target": str(target),
        "exported": exported,
        "problems": problems,
        "exitCode": EXIT_OK if exported else EXIT_EMPTY,
    }


def import_modules(library_root, sources: Sequence[str]) -> Dict[str, object]:
    """2.4 离线导入模块包：非法附件跳过并报告，原库保留。"""
    library = module_lib.ModuleLibrary(library_root)
    imported: List[Dict[str, object]] = []
    problems: List[str] = []
    for source in sources:
        try:
            published = library.import_module(source)
        except (OSError, ValueError, FileNotFoundError) as exc:
            problems.append("导入失败 {0}：{1}".format(source, exc))
            continue
        imported.append({
            "moduleId": published.moduleId,
            "version": published.version,
            "candidate": published.candidate or "",
            "directory": str(published.directory),
            "created": bool(published.created),
            "warnings": list(published.warnings),
        })
    return {
        "ok": bool(imported),
        "root": str(library.root),
        "imported": imported,
        "problems": problems,
        "exitCode": EXIT_OK if imported else EXIT_EMPTY,
    }


def install_modules(
    context: ProjectReuseContext,
    items: Sequence[Tuple[str, str]],
) -> Dict[str, object]:
    """把库中的模块固定复制进项目（``reuse/modules/<id>/<version>/``）。"""
    if context.library is None:
        return {
            "ok": False,
            "error": "no-library",
            "message": "未配置模块库目录，无法安装固定副本。",
            "exitCode": EXIT_USAGE,
        }
    installed: List[Dict[str, object]] = []
    problems: List[str] = []
    for module_id, version in items:
        versions = context.library.versions(module_id)
        chosen = str(version or "").strip() or (versions[-1] if versions else "")
        if context.library.get(module_id, chosen) is None:
            problems.append(
                "模块不存在：{0}@{1}".format(module_id, chosen or "（未指定）")
            )
            continue
        published = module_lib.install_from_library(
            context.project_root, context.library, module_id, chosen
        )
        installed.append({
            "moduleId": published.moduleId,
            "version": published.version,
            "directory": str(published.directory),
            "created": bool(published.created),
            "warnings": list(published.warnings),
        })
    return {
        "ok": bool(installed),
        "installed": installed,
        "problems": problems,
        "exitCode": EXIT_OK if installed else EXIT_EMPTY,
    }
# --------------------------------------------------------------------------
# 4.4：升级预览与应用
# --------------------------------------------------------------------------


def upgrade_preview(
    context: ProjectReuseContext,
    module_id: str,
    target_version: str = "",
    *,
    slot_ids: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """4.4 查看差异 + 受影响 slot（不写盘）。"""
    library = context.library
    current_version = ""
    for slot in context.assembly.slots:
        if slot.moduleId == module_id:
            current_version = slot.version
            break
    versions = library.versions(module_id) if library is not None else []
    chosen = str(target_version or "").strip() or _newest_version(versions, current_version)
    if library is None:
        return {
            "ok": False,
            "error": "no-library",
            "message": "未配置模块库目录，无法比较版本。",
            "exitCode": EXIT_USAGE,
        }
    if not current_version:
        return {
            "ok": False,
            "error": "not-referenced",
            "message": "项目装配里没有模块 {0} 的固定引用，无需升级。".format(module_id),
            "versions": versions,
            "exitCode": EXIT_USAGE,
        }
    current = library.get(module_id, current_version)
    target = library.get(module_id, chosen) if chosen else None
    if current is None:
        return {
            "ok": False,
            "error": "current-missing",
            "message": "当前固定版本在库中找不到，无法比较：{0}@{1}".format(
                module_id, current_version
            ),
            "versions": versions,
            "exitCode": EXIT_USAGE,
        }
    if target is None:
        return {
            "ok": False,
            "error": "unknown-target",
            "message": "目标版本不存在：{0}@{1}（可选：{2}）".format(
                module_id, chosen or "（未指定）", "、".join(versions) or "（无）"
            ),
            "versions": versions,
            "exitCode": EXIT_USAGE,
        }
    plan = refs.plan_upgrade(
        context.assembly, module_id, current, target, host_slots=slot_ids or None
    )
    payload = plan.to_dict()
    payload.update({
        "ok": True,
        "currentVersion": current_version,
        "targetVersion": target.version,
        "versions": versions,
        "chapterBySlot": {
            slot.slotId: slot.chapter for slot in context.assembly.slots
            if slot.moduleId == module_id
        },
        "exitCode": EXIT_OK,
    })
    return payload


def upgrade_apply(
    context: ProjectReuseContext,
    module_id: str,
    target_version: str = "",
    *,
    slot_ids: Optional[Sequence[str]] = None,
    dry_run: bool = True,
) -> Dict[str, object]:
    """4.4 选择性升级到新版本；``dry_run=False`` 才写回 ``reuse/assembly.yml``。

    只改明确选中的 slot，未选中的保持原版本；``before``/``after`` 一并回传，
    取消或失败时可据此恢复原配置。
    """
    preview = upgrade_preview(context, module_id, target_version, slot_ids=slot_ids)
    if not preview.get("ok"):
        return preview
    plan = refs.plan_upgrade(
        context.assembly,
        module_id,
        context.library.get(module_id, preview["currentVersion"]),
        context.library.get(module_id, preview["targetVersion"]),
        host_slots=slot_ids or None,
    )
    updated_assembly, updated = refs.apply_upgrade(
        context.assembly, plan, slot_ids=slot_ids or None
    )
    changed = updated_assembly.to_dict() != context.assembly.to_dict()
    payload = dict(preview)
    payload.update({
        "dryRun": bool(dry_run),
        "updated": list(updated),
        "changed": bool(changed),
        "before": context.assembly.to_dict(),
        "after": updated_assembly.to_dict(),
    })
    if not dry_run and changed:
        import yaml

        from doc_tool.application.content.writer import atomic_write

        path = context.project_root / refs.ASSEMBLY_RELATIVE
        atomic_write(
            path,
            yaml.safe_dump(updated_assembly.to_dict(), allow_unicode=True, sort_keys=False),
        )
        context.assembly = updated_assembly
        payload["assemblyPath"] = str(path)
    else:
        payload["assemblyPath"] = ""
    if not changed:
        payload["message"] = "没有需要升级的引用（选择为空或版本已一致）。"
    return payload


def _newest_version(versions: Sequence[str], current: str) -> str:
    """取一个和当前版本不同的最新候选（没有别的版本时返回当前版本）。"""
    others = [item for item in versions if item != current]
    if not others:
        return current
    return sorted(others)[-1]


def render_upgrade_text(payload: Dict[str, object]) -> str:
    """升级预览/应用的人读输出。"""
    lines: List[str] = []
    if not payload.get("ok"):
        lines.append("[FAIL] {0}".format(payload.get("message") or "无法比较版本"))
        versions = payload.get("versions") or []
        if versions:
            lines.append("可选版本：{0}".format("、".join(str(item) for item in versions)))
        return "\n".join(lines)
    lines.append(
        "模块 {0}：{1} → {2}".format(
            payload.get("moduleId", ""),
            payload.get("currentVersion", ""),
            payload.get("targetVersion", ""),
        )
    )
    difference = payload.get("difference") or {}
    lines.append("差异：{0}".format(difference.get("summary") or "版本内容无差异"))
    slots = payload.get("slots") or []
    lines.append("受影响引用（{0}）：".format(len(slots)))
    chapter_by_slot = payload.get("chapterBySlot") or {}
    for slot_id in slots:
        lines.append(
            "  - {0} @{1}".format(slot_id, chapter_by_slot.get(slot_id) or "（未记录宿主）")
        )
    for warning in payload.get("warnings") or []:
        lines.append("  - [提示] {0}".format(warning))
    if payload.get("message"):
        lines.append(str(payload["message"]))
    if payload.get("dryRun"):
        lines.append("（预览：未写盘；确认后加 --apply 才更新 reuse/assembly.yml）")
    else:
        lines.append(
            "已应用：{0} 个引用 → {1}".format(
                len(payload.get("updated") or []), payload.get("assemblyPath") or "（无变化）"
            )
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 人读渲染：库/导入导出/变体/副本
# --------------------------------------------------------------------------


def render_payload_text(kind: str, payload: Dict[str, object]) -> str:
    """按命令种类渲染人读结果（机器报告一律用 JSON 原样输出）。"""
    if kind == "resolve":
        return render_resolution_text(payload)
    if kind == "upgrade":
        return render_upgrade_text(payload)
    if kind == "list":
        return _render_list(payload)
    if kind == "show":
        return _render_show(payload)
    if kind in ("import", "export", "install"):
        return _render_transfer(payload, {"import": "导入", "export": "导出", "install": "安装"}[kind])
    if kind == "extract":
        return _render_extract(payload)
    if kind == "variants":
        return _render_variants(payload)
    if kind in ("build", "copy"):
        return _render_runs(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_list(payload: Dict[str, object]) -> str:
    lines = ["模块库：{0}".format(payload.get("root") or "（未配置）")]
    rows = payload.get("modules") or []
    lines.append("条目（{0}）：".format(len(rows)))
    for row in rows:
        lines.append(
            "  - {0}@{1} {2} [{3}] 参数：{4}".format(
                row.get("moduleId", ""), row.get("version", ""), row.get("title", ""),
                "、".join(row.get("tags") or []) or "无标签",
                "、".join(row.get("parameters") or []) or "无",
            )
        )
    for warning in payload.get("warnings") or []:
        lines.append("  - [提示] {0}".format(warning))
    return "\n".join(lines)


def _render_show(payload: Dict[str, object]) -> str:
    if not payload.get("ok"):
        return "[FAIL] {0}".format(payload.get("message") or "模块不可用")
    lines = [
        "{0}@{1} {2}".format(
            payload.get("moduleId", ""), payload.get("version", ""), payload.get("title", "")
        ),
        "可选版本：{0}".format("、".join(payload.get("versions") or []) or "（无）"),
    ]
    parameters = payload.get("parameters") or []
    if parameters:
        lines.append("声明参数：")
        for item in parameters:
            lines.append(
                "  - {0}（默认 {1}）{2}".format(
                    item.get("name", ""), item.get("default", ""), item.get("description", "")
                )
            )
    resources = payload.get("resources") or []
    if resources:
        lines.append("资源（{0}）：".format(len(resources)))
        for item in resources:
            lines.append("  - {0}".format(item.get("path", "")))
    lines.append("---- 预览 ----")
    lines.append(str(payload.get("preview") or ""))
    return "\n".join(lines)


def _render_transfer(payload: Dict[str, object], label: str) -> str:
    lines: List[str] = []
    if not payload.get("ok") and payload.get("message"):
        lines.append("[FAIL] {0}".format(payload["message"]))
    rows = (
        payload.get("imported") or payload.get("exported") or payload.get("installed") or []
    )
    lines.append("{0}成功 {1} 项".format(label, len(rows)))
    for row in rows:
        lines.append(
            "  - {0}@{1} → {2}{3}".format(
                row.get("moduleId", ""), row.get("version", ""), row.get("directory", ""),
                "（候选版本）" if row.get("candidate") else "",
            )
        )
        for warning in row.get("warnings") or []:
            lines.append("      [提示] {0}".format(warning))
        for missing in row.get("missingResources") or []:
            lines.append("      [缺资源] {0}".format(missing))
    for problem in payload.get("problems") or []:
        lines.append("  [跳过] {0}".format(problem))
    return "\n".join(lines)


def _render_extract(payload: Dict[str, object]) -> str:
    if not payload.get("ok"):
        return "[FAIL] {0}".format(payload.get("message") or "提取失败")
    lines = [
        "已提取 {0}@{1}（来源：{2}）".format(
            payload.get("moduleId", ""), payload.get("version", ""),
            "当前缓冲快照" if payload.get("sourceMode") == "current-buffer" else "已保存章节",
        ),
        "目录：{0}".format(payload.get("directory", "")),
        "收集资源：{0}".format("、".join(payload.get("collected") or []) or "（无）"),
    ]
    if payload.get("candidate"):
        lines.append("原版本保留，另存候选版本：{0}".format(payload["candidate"]))
    for target in payload.get("missing") or []:
        lines.append("  [缺资源] {0}".format(target))
    for target in payload.get("skipped") or []:
        lines.append("  [非法路径已跳过] {0}".format(target))
    for warning in payload.get("warnings") or []:
        lines.append("  [提示] {0}".format(warning))
    return "\n".join(lines)


def _render_variants(payload: Dict[str, object]) -> str:
    lines: List[str] = []
    if not payload.get("ok") and payload.get("message"):
        lines.append("[FAIL] {0}".format(payload["message"]))
        options = payload.get("options") or []
        if options:
            lines.append("可选变体：{0}".format("、".join(str(item) for item in options)))
        return "\n".join(lines)
    available = payload.get("available") or []
    lines.append("可用变体（{0}）：".format(len(available)))
    for item in available:
        lines.append(
            "  - {0}（{1}）".format(item.get("variantId", ""), item.get("name", ""))
        )
    requested = payload.get("requested")
    if requested:
        scope = payload.get("scope") or {}
        lines.append("变体 {0} 有效范围：".format(requested))
        for chapter in scope.get("chapters") or []:
            lines.append("  - {0}".format(chapter))
        excluded = scope.get("excluded") or []
        if excluded:
            lines.append("范围外：{0}".format("、".join(str(item) for item in excluded)))
        variables = scope.get("variables") or {}
        if variables:
            lines.append(
                "变量：{0}".format(
                    "、".join("{0}={1}".format(k, v) for k, v in sorted(variables.items()))
                )
            )
    for warning in payload.get("warnings") or []:
        lines.append("  - [提示] {0}".format(warning))
    return "\n".join(lines)


def _render_runs(payload: Dict[str, object]) -> str:
    lines: List[str] = []
    if not payload.get("ok") and payload.get("message"):
        lines.append("[FAIL] {0}".format(payload["message"]))
        options = payload.get("options") or []
        if options:
            lines.append("可选变体：{0}".format("、".join(str(item) for item in options)))
        return "\n".join(lines)
    runs = payload.get("runs") or []
    if not runs and payload.get("outputDir"):
        runs = [payload]
    for run in runs:
        scope = run.get("scope") or {}
        lines.append(
            "{0}（{1}）→ {2}".format(
                run.get("variantId") or "default", run.get("name") or "",
                run.get("outputDir") or "",
            )
        )
        chapters = scope.get("chapters") or run.get("chapters") or []
        lines.append("  章节：{0}".format("、".join(chapters) or "（无）"))
        excluded = scope.get("excluded") or run.get("excluded") or []
        if excluded:
            lines.append("  范围外：{0}".format("、".join(str(item) for item in excluded)))
        versions = scope.get("moduleVersions") or run.get("moduleVersions") or {}
        if versions:
            lines.append(
                "  模块版本：{0}".format(
                    "、".join("{0}={1}".format(k, v) for k, v in sorted(versions.items()))
                )
            )
        assets = run.get("assets") or []
        if assets:
            lines.append("  资源 {0} 个".format(len(assets)))
        for issue in run.get("portableIssues") or []:
            lines.append(
                "  [副本问题] {0}:{1} {2}（{3}）".format(
                    issue.get("file"), issue.get("line"), issue.get("target"), issue.get("message")
                )
            )
        for warning in run.get("warnings") or []:
            lines.append("  - [提示] {0}".format(warning))
    for problem in payload.get("problems") or []:
        lines.append("  [跳过] {0}".format(problem))
    return "\n".join(lines)


__all__ = [
    "EXIT_OK", "EXIT_EMPTY", "EXIT_USAGE", "DEFAULT_LIBRARY_RELATIVE",
    "ProjectReuseContext", "ResolutionPlan", "ChapterResolution",
    "discover_chapters", "configured_library", "library_root_for", "load_library",
    "load_context", "variant_selection", "plan_project", "resolve_text",
    "resolve_chapter", "resolve_project", "describe_sources",
    "render_resolution_text", "render_report", "render_payload_text",
    "render_upgrade_text", "variant_evidence", "build_variant_documents",
    "write_expanded_copy", "extract_chapter_module", "list_modules", "show_module",
    "export_modules", "import_modules", "install_modules",
    "upgrade_preview", "upgrade_apply",
]