# -*- coding: utf-8 -*-
"""有效内容快照（CORE-E 5.1-5.4）。

一次捕获固定“这次要出什么内容”：范围（整份/当前章/勾选章）、来源模式
（当前编辑缓冲/已保存版本）、章节顺序、资源与底模/配置哈希。快照把内容复制
到**私有工作目录**，后续构建/HTML/检查都在这份副本上执行，因此：

- 捕获缓冲不写回源文件、不清除脏标记；
- 快照出稿不改写源项目的正文/版本/评审状态；
- 捕获后的编辑不影响本轮结果，结果显示“源已更新”。

与 ``content/snapshot.py`` 的 ``ContentSnapshot``（变更基线）职责不同：本模块
只表示“本轮有效内容”，不参与变更徽标或审核结论。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.intake_contract import (
    SOURCE_MODE_CURRENT_BUFFER,
    SOURCE_MODE_SAVED,
    SOURCE_MODES,
    SCOPE_CHAPTERS,
    SCOPE_CURRENT_CHAPTER,
    SCOPE_PROJECT,
    ExportScope,
    new_capture_id,
    sha256_text,
    utc_now_iso,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths
from doc_tool.domain.version import PROJECT_SCHEMA_VERSION

#: 生成内容快照时忽略的项目内部文件。
#: 生成内容快照时忽略的项目内部文件；``_index.md`` 是章节目录自身的正文，
#: 不单独作为可勾选章节，但会随所属章节一起进入快照。
_IGNORED_FILES = {"_revision_record.md", "_meta.yml", "_index.md"}

#: Markdown 资源引用：``![alt](path)`` / ``[text](path)``。
_RESOURCE_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")

#: 解析/渲染版本：进入缓存 key，解析规则变化时旧缓存自然失效。
SNAPSHOT_PARSE_VERSION = "core-e-1"


@dataclass
class SnapshotChapter:
    """快照中的一个章节。"""

    rel_path: str
    title: str = ""
    contentHash: str = ""
    diskHash: str = ""
    source: str = SOURCE_MODE_SAVED
    location: Optional[Dict[str, object]] = None

    @property
    def fromBuffer(self) -> bool:
        return self.source == SOURCE_MODE_CURRENT_BUFFER

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class EffectiveSnapshot:
    """一轮出稿使用的有效内容快照。"""

    captureId: str = field(default_factory=new_capture_id)
    capturedAt: str = field(default_factory=utc_now_iso)
    scope: ExportScope = field(default_factory=ExportScope)
    sourceMode: str = SOURCE_MODE_CURRENT_BUFFER
    documentType: str = "general"
    projectRoot: str = ""
    workDir: str = ""
    chapters: List[SnapshotChapter] = field(default_factory=list)
    omittedChapters: List[str] = field(default_factory=list)
    textHash: str = ""
    assetHashes: Dict[str, str] = field(default_factory=dict)
    templateHash: str = ""
    configHash: str = ""
    resources: List[str] = field(default_factory=list)
    missingResources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unsavedChapters: List[str] = field(default_factory=list)
    readonlyProject: bool = False
    externalDestination: str = ""
    sourceUpdated: bool = False
    cacheKey: str = ""
    #: V3.2 4.2：本轮出稿使用的产品变体（空=项目当前内容）。
    variantId: str = ""
    #: 变体内容是否真的应用到了快照（未知变体时为 False，按项目当前内容继续）。
    variantApplied: bool = False
    variantWarnings: List[str] = field(default_factory=list)

    # --- 展示 ---

    @property
    def unsavedCount(self) -> int:
        return len(self.unsavedChapters)

    @property
    def orderedChapters(self) -> List[str]:
        return [item.rel_path for item in self.chapters]

    def scope_description(self) -> str:
        return self.scope.describe(len(self.chapters))

    def source_description(self) -> str:
        if self.sourceMode == SOURCE_MODE_CURRENT_BUFFER:
            if self.unsavedCount:
                return "当前编辑内容（包含 {0} 章未保存修改）".format(self.unsavedCount)
            return "当前编辑内容（与已保存版本一致）"
        return "已保存版本（未纳入当前缓冲修改）"

    def summary_lines(self) -> List[str]:
        lines = [
            "本轮内容：{0}".format(self.scope_description()),
            "来源：{0}".format(self.source_description()),
        ]
        if self.omittedChapters:
            lines.append("范围外章节 {0} 个未纳入本次出稿".format(len(self.omittedChapters)))
        if self.missingResources:
            lines.append("{0} 个资源缺失，已保留占位".format(len(self.missingResources)))
        if self.sourceUpdated:
            lines.append("捕获后源内容已更新：本轮结果仍对应捕获时版本，可再次生成新轮")
        for item in self.warnings:
            lines.append("提醒：{0}".format(item))
        return lines

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["scope"] = self.scope.to_dict()
        data["chapters"] = [item.to_dict() for item in self.chapters]
        data["unsavedChapters"] = list(self.unsavedChapters)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "EffectiveSnapshot":
        data = dict(data or {})
        chapters = [
            SnapshotChapter(**{k: v for k, v in item.items() if k in SnapshotChapter.__dataclass_fields__})
            for item in data.pop("chapters", []) or []
            if isinstance(item, dict)
        ]
        scope = ExportScope.from_dict(data.pop("scope", None))
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in data.items() if k in known and k != "scope"}
        snapshot = cls(scope=scope, chapters=chapters, **payload)
        return snapshot


# --- 章节与资源发现 ---


def discover_chapters(content_root: Path) -> List[Tuple[str, Path]]:
    """按项目既有顺序列出章节文件（相对 contentRoot 的 POSIX 路径）。"""
    from doc_tool.application.content.index import ContentIndexService

    service = ContentIndexService(Path(content_root))
    found: List[Tuple[str, Path]] = []
    for rel_path, path in service.discover_files():
        if Path(rel_path).name in _IGNORED_FILES:
            continue
        if Path(rel_path).suffix.lower() != ".md":
            continue
        found.append((rel_path, Path(path)))
    return found


def count_unsaved(content_root: Path, buffer_texts: Dict[str, str]) -> List[str]:
    """返回与磁盘内容不一致的章节相对路径（不写回、不清脏）。"""
    unsaved: List[str] = []
    for rel_path, path in discover_chapters(content_root):
        text = (buffer_texts or {}).get(rel_path)
        if text is None:
            continue
        try:
            disk = path.read_text(encoding="utf-8")
        except OSError:
            disk = ""
        if text != disk:
            unsaved.append(rel_path)
    return unsaved


def collect_resource_paths(texts: Iterable[str]) -> List[str]:
    """从 Markdown 正文收集相对资源路径（去重、保序、忽略外链）。"""
    found: List[str] = []
    for text in texts or ():
        for match in _RESOURCE_RE.finditer(text or ""):
            target = (match.group(1) or "").strip()
            if not target or target.startswith(("http://", "https://", "data:", "#", "mailto:")):
                continue
            target = target.split(" =", 1)[0].strip()
            if target and target not in found:
                found.append(target)
        from doc_tool.domain.blocks import KIND_COMPLEX_TABLE, parse_blocks
        for block in parse_blocks(text or "").blocks:
            if block.kind == KIND_COMPLEX_TABLE and block.filename:
                target = "tables/" + block.filename
                if target not in found:
                    found.append(target)
    return found


# --- 捕获 ---


def _select_chapters(
    chapters: Sequence[Tuple[str, Path]],
    scope: ExportScope,
) -> Tuple[List[Tuple[str, Path]], List[str]]:
    """按范围挑章节；勾选范围按项目顺序（不按点击顺序），并补入祖先结构。"""
    by_rel = {rel: (rel, path) for rel, path in chapters}
    if scope.kind == SCOPE_PROJECT:
        selected = list(chapters)
        return selected, []
    wanted: List[str] = []
    if scope.kind == SCOPE_CURRENT_CHAPTER:
        if scope.current and scope.current in by_rel:
            wanted.append(scope.current)
    else:
        for rel in scope.chapters:
            if rel in by_rel and rel not in wanted:
                wanted.append(rel)
    if not wanted:
        # 范围为空：不给部分结果，回退整份（调用方会展示实际范围）。
        return list(chapters), []
    ordered = [item for item in chapters if item[0] in set(wanted)]
    omitted = [rel for rel, _path in chapters if rel not in set(wanted)]
    return ordered, omitted


def _resolve_resource_file(content_root: Path, rel_chapter: str, target: str) -> Optional[Path]:
    """把 Markdown 中的资源引用解析为项目内绝对路径（越界返回 None）。"""
    cleaned = target.replace("\\", "/")
    if cleaned.startswith("/") or ":" in cleaned.split("/")[0]:
        return None
    base = content_root / Path(rel_chapter).parent
    candidate = (base / cleaned).resolve()
    try:
        candidate.relative_to(content_root.resolve())
    except ValueError:
        return None
    return candidate


def user_snapshot_root() -> Path:
    """用户级快照目录（只读项目/无项目写权限时使用）。"""
    try:
        from doc_tool.application.project_service import _config_dir

        return Path(_config_dir()) / "snapshots"
    except Exception:  # noqa: BLE001 - 配置目录不可用时退回用户主目录
        return Path.home() / ".doctool" / "snapshots"


def _variant_texts(project_root, variant_id: str, snapshot, manifest) -> Dict[str, str]:
    """取变体的有效章节文本；未知变体只记提醒并按项目当前内容继续（不阻断出稿）。"""
    try:
        from doc_tool.application.content import reuse_commands as reuse
        from doc_tool.application.content import variants as variants_lib

        context = reuse.load_context(project_root)
        variant = context.config.get(variant_id) if context.config is not None else None
        if variant is None:
            snapshot.variantApplied = False
            snapshot.variantWarnings.append(
                "未找到变体 {0}：按项目当前内容出稿（可选：{1}）".format(
                    variant_id, "、".join(context.config.ids()) if context.config else "无"
                )
            )
            return {}
        _run, texts = variants_lib.expand_document_variant(
            project_root,
            discovered=context.discovered,
            document_type=context.document_type or manifest.documentType,
            declared=context.declared,
            project_variables=context.project_variables,
            assembly=context.assembly,
            variant=variant,
            library=context.library,
            write=False,
        )
        snapshot.variantApplied = True
        snapshot.warnings.extend(list(getattr(_run, "warnings", []) or [])[:5])
        return {str(key): str(value) for key, value in (texts or {}).items()}
    except Exception as exc:  # noqa: BLE001 - 变体展开失败按当前内容继续并提醒
        snapshot.variantApplied = False
        snapshot.variantWarnings.append("变体展开失败，按项目当前内容出稿：{0}".format(exc))
        return {}


def capture_snapshot(
    project_root,
    *,
    scope: Optional[ExportScope] = None,
    source_mode: str = SOURCE_MODE_CURRENT_BUFFER,
    buffer_texts: Optional[Dict[str, str]] = None,
    current_chapter: str = "",
    work_root=None,
    external_destination: str = "",
    cancel_token=None,
    progress=None,
    cache_root=None,
    variant_id: str = "",
) -> EffectiveSnapshot:
    """捕获一次不可变的有效内容快照，并物化到私有工作目录。

    ``buffer_texts`` 为 ``{相对 contentRoot 的章节路径: 当前编辑器文本}``；
    只有 ``source_mode == current-buffer`` 时才会采用缓冲内容。捕获过程不写回
    项目、不改动编辑器脏状态。``cancel_token`` 在章节边界检查。
    """
    project_root = Path(project_root)
    paths = ProjectPaths(project_root)
    manifest = ProjectManifest.load(project_root)
    content_root = paths.resolve(manifest.relative_content_root())
    effective_mode = source_mode if source_mode in SOURCE_MODES else SOURCE_MODE_SAVED
    effective_scope = scope or ExportScope()
    if current_chapter and not effective_scope.current:
        effective_scope.current = current_chapter

    snapshot = EffectiveSnapshot(
        scope=effective_scope,
        sourceMode=effective_mode,
        documentType=manifest.documentType,
        projectRoot=str(project_root),
        readonlyProject=not manifest.is_writable(),
        externalDestination=str(external_destination or ""),
        variantId=str(variant_id or ""),
    )

    # V3.2 4.2：变体内容在此生效（章节范围 + 变量 + 模块版本），
    # 之后 Word/HTML/检查/交付包都基于同一份变体内容。
    variant_texts: Dict[str, str] = {}
    if variant_id:
        variant_texts = _variant_texts(project_root, variant_id, snapshot, manifest)

    chapters = discover_chapters(content_root)
    selected, omitted = _select_chapters(chapters, effective_scope)
    snapshot.omittedChapters = omitted

    buffers = dict(buffer_texts or {})
    captured_texts: Dict[str, str] = {}
    texts: List[str] = []
    for rel_path, path in selected:
        if cancel_token is not None:
            cancel_token.check_cancel()
        if variant_id and snapshot.variantApplied and rel_path not in variant_texts:
            # 变体未纳入该章：既不出稿也不报缺失
            snapshot.omittedChapters.append(rel_path)
            continue
        try:
            disk_text = path.read_text(encoding="utf-8")
        except OSError:
            disk_text = ""
        disk_hash = sha256_text(disk_text)
        from_buffer = effective_mode == SOURCE_MODE_CURRENT_BUFFER and rel_path in buffers
        text = buffers.get(rel_path, disk_text) if from_buffer else disk_text
        if variant_id and snapshot.variantApplied and rel_path in variant_texts:
            # 变体展开优先（含变量/模块版本）；同章缓冲语义仍然生效
            text = variant_texts[rel_path]
        if from_buffer and text != disk_text:
            snapshot.unsavedChapters.append(rel_path)
        text = _expand_modules(snapshot, rel_path, text)
        captured_texts[rel_path] = text
        snapshot.chapters.append(SnapshotChapter(
            rel_path=rel_path,
            title=_chapter_title(text) or Path(rel_path).stem,
            contentHash=sha256_text(text),
            diskHash=disk_hash,
            source=SOURCE_MODE_CURRENT_BUFFER if from_buffer else SOURCE_MODE_SAVED,
            location={"relPath": rel_path},
        ))
        texts.append(text)
        if progress is not None:
            progress(rel_path)

    snapshot.textHash = sha256_text("".join(texts))
    snapshot.resources = collect_resource_paths(texts)
    snapshot._resolvedResources = dict(getattr(getattr(snapshot, "_reuseResolver", None), "resources", {}))
    # 变体已展开的固定模块引用仍以项目根为基准；复制进快照资源目录保留其引用。
    for target in snapshot.resources:
        if target.startswith(("reuse/modules/", "reuse/library/")):
            try:
                snapshot._resolvedResources[target] = paths.resolve(target)
            except Exception:
                pass
    snapshot.assetHashes, snapshot.missingResources = _hash_resources(
        paths.resolve(manifest.relative_asset_root()), snapshot.chapters, snapshot.resources,
        table_root=paths.resolve(manifest.relative_table_root()),
        resolved_resources=snapshot._resolvedResources,
    )
    for missing in snapshot.missingResources:
        snapshot.warnings.append("资源缺失：{0}（正文保留占位）".format(missing))
    snapshot.templateHash = _file_hash(paths.template_docx)
    snapshot.configHash = _config_hash(manifest, snapshot)
    effective_work_root = work_root
    if effective_work_root is None and not manifest.is_writable():
        # 只读项目：快照与构建产物一律写到用户目录，项目内不新增任何写入。
        effective_work_root = user_snapshot_root() / snapshot.captureId
        snapshot.warnings.append("只读项目：本轮快照与产物写入用户目录，项目内无新增写入")
    snapshot.workDir = _materialize(
        snapshot, paths, manifest, content_root, selected, captured_texts, effective_work_root,
    )
    snapshot.cacheKey = snapshot_cache_key(snapshot)
    return snapshot


def _chapter_title(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped:
            return stripped[:40]
    return ""


def _hash_resources(
    content_root: Path,
    chapters: Sequence[SnapshotChapter],
    resources: Sequence[str],
    *, table_root: Optional[Path] = None, resolved_resources: Optional[Dict[str, Path]] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """固定实际读取到的资源 bytes/hash；缺失项单独记录。"""
    hashes: Dict[str, str] = {}
    missing: List[str] = []
    for target in resources:
        table_resource = table_root is not None and target.startswith("tables/")
        resource_root = table_root if table_resource else content_root
        candidate = (resolved_resources or {}).get(target)
        if candidate is not None:
            if candidate.is_file():
                hashes[target] = _file_hash(candidate)
            else:
                missing.append(target)
            continue
        candidate = _resolve_resource_file(resource_root, "", target[7:] if table_resource else target)
        if candidate is None or not candidate.is_file():
            if target not in missing:
                missing.append(target)
            continue
        key = ("tables/" if table_resource else "") + candidate.relative_to(resource_root.resolve()).as_posix()
        if key not in hashes:
            hashes[key] = _file_hash(candidate)
    return hashes, missing


def _file_hash(path: Path) -> str:
    from doc_tool.application.intake_contract import sha256_file

    return sha256_file(Path(path)) if Path(path).is_file() else ""


def _config_hash(manifest: ProjectManifest, snapshot: EffectiveSnapshot) -> str:
    """配置哈希：映射 + 范围 + 解析版本（缓存 key 的一部分）。"""
    payload = {
        "headingStyles": {str(k): str(v) for k, v in (manifest.headingStyles or {}).items()},
        "bodyStyle": manifest.bodyStyle,
        "variables": dict(manifest.variables or {}),
        "chapters": list(manifest.chapters or []),
        "scope": snapshot.scope.to_dict(),
        "sourceMode": snapshot.sourceMode,
        "parseVersion": SNAPSHOT_PARSE_VERSION,
        "documentType": manifest.documentType,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def snapshot_cache_key(snapshot: EffectiveSnapshot) -> str:
    """缓存 key：源 bytes/hash + 映射 + 范围 + 解析版本 + 渲染配置。"""
    payload = {
        "textHash": snapshot.textHash,
        "templateHash": snapshot.templateHash,
        "configHash": snapshot.configHash,
        "assetHashes": dict(sorted(snapshot.assetHashes.items())),
        "scope": snapshot.scope.to_dict(),
        "sourceMode": snapshot.sourceMode,
        "parseVersion": SNAPSHOT_PARSE_VERSION,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _materialize(
    snapshot: EffectiveSnapshot,
    paths: ProjectPaths,
    manifest: ProjectManifest,
    content_root: Path,
    selected: Sequence[Tuple[str, Path]],
    buffers: Dict[str, str],
    work_root,
) -> str:
    """把选中内容/资源/底模复制到私有工作目录，形成可构建的快照项目。"""
    root = Path(work_root) if work_root is not None else (paths.state_dir / "snapshots" / snapshot.captureId)
    root = root.resolve()
    project_root = paths.root.resolve()
    protected = [content_root.resolve(), paths.resolve(manifest.relative_asset_root()).resolve(),
                 paths.template_dir.resolve(), paths.original_dir.resolve()]
    if root == project_root or root in project_root.parents or any(
        root == source or source in root.parents or root in source.parents for source in protected
    ):
        raise ValueError("快照工作目录不能覆盖项目或源文件目录。")
    if root.exists():
        shutil.rmtree(str(root), ignore_errors=True)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    # 内核按清单校验资源目录存在：快照项目补齐同一套标准目录。
    (root / "assets" / "tables").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "images").mkdir(parents=True, exist_ok=True)
    (root / "template").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)

    copied_index: set = set()
    for chapter in snapshot.chapters:
        text = buffers.get(chapter.rel_path)
        target = root / "content" / chapter.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # 章节自身正文（同目录 _index.md）随章节一起复制，避免丢正文。
        index_source = content_root / Path(chapter.rel_path).parent / "_index.md"
        index_key = index_source.as_posix()
        if index_key not in copied_index and index_source.is_file():
            index_target = root / "content" / Path(chapter.rel_path).parent / "_index.md"
            try:
                shutil.copy2(str(index_source), str(index_target))
                copied_index.add(index_key)
            except OSError:
                pass
        if text is None:
            try:
                read_text = (content_root / chapter.rel_path).read_text(encoding="utf-8")
            except OSError:
                read_text = ""
            resolved = _expand_modules(snapshot, chapter.rel_path, read_text)
            if resolved == read_text:
                # 无模块标记：保持原有复制语义（时间戳/权限与源一致）
                source = content_root / chapter.rel_path
                try:
                    shutil.copy2(str(source), str(target))
                    continue
                except OSError:
                    pass
            text = resolved
        target.write_text(text, encoding="utf-8")

    # 资源：按实际引用复制（保持相对结构），不复制无关资源。
    for rel_key, _digest in snapshot.assetHashes.items():
        resolved_resources = getattr(snapshot, "_resolvedResources", {})
        source = resolved_resources.get(rel_key) or (paths.resolve(manifest.relative_table_root()) / rel_key[7:] if rel_key.startswith("tables/")
                  else paths.resolve(manifest.relative_asset_root()) / rel_key)
        target = root / "assets" / rel_key
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target))
        except OSError:
            continue

    if paths.template_docx.is_file():
        shutil.copy2(str(paths.template_docx), str(root / "template" / "template.docx"))
    try:
        if paths.source_docx.is_file():
            (root / "original").mkdir(parents=True, exist_ok=True)
            os.link(str(paths.source_docx), str(root / "original" / "source.docx"))
    except OSError:
        pass

    # 快照清单：章节顺序固定为本次范围，源项目清单不被修改。
    snapshot_manifest = ProjectManifest(
        documentType=manifest.documentType,
        documentNo=manifest.documentNo,
        documentName=manifest.documentName,
        documentVersion=manifest.documentVersion,
        sourceSha256=manifest.sourceSha256,
        # 快照副本始终用当前可写模式版本：只读源不因此让快照也不可写。
        schemaVersion=PROJECT_SCHEMA_VERSION,
        paths={
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content",
            "assetRoot": "assets",
            "tableRoot": "assets/tables",
        },
        headingStyles=dict(manifest.headingStyles or {}),
        bodyStyle=manifest.bodyStyle,
        documentKind=manifest.documentKind,
        chapters=[item.rel_path for item in snapshot.chapters],
        variables=dict(manifest.variables or {}),
        standardPack=dict(manifest.standardPack or {}),
        qualitySource=manifest.qualitySource,
        createdWithVersion=manifest.createdWithVersion,
        is_headless=manifest.is_headless,
        allow_missing_headings=manifest.allow_missing_headings,
    )
    snapshot_manifest.save(root)
    return str(root)


def _expand_modules(snapshot: EffectiveSnapshot, rel_path: str, text: str) -> str:
    """按项目声明展开嵌入的正文模块（无声明/无标记时原样返回）。

    resolver 懒加载并缓存在快照对象上：同一轮快照内所有章节共用一个解析上下文，
    保证预览、离线 HTML、Word 使用同一份展开内容（V3.0 3.4）。
    """
    resolver = getattr(snapshot, "_reuseResolver", None)
    if resolver is None and not getattr(snapshot, "_reuseResolverChecked", False):
        snapshot._reuseResolverChecked = True  # type: ignore[attr-defined]
        try:
            from doc_tool.application.content.reuse_hook import build_project_resolver

            resolver = build_project_resolver(snapshot.projectRoot)
        except Exception:  # noqa: BLE001 - 复用能力不可用时保持原样
            resolver = None
        snapshot._reuseResolver = resolver  # type: ignore[attr-defined]
    if resolver is None:
        return text
    try:
        resolved = resolver(rel_path, text)
    except Exception as exc:  # noqa: BLE001 - 展开失败保留原文并提醒
        snapshot.warnings.append("正文展开失败（保留原文）：{0}：{1}".format(rel_path, exc))
        return text
    if isinstance(resolved, str) and resolved and resolved != text:
        snapshot.warnings.append("已按项目声明展开正文模块引用：{0}".format(rel_path))
    return resolved if isinstance(resolved, str) and resolved else text


def refresh_assets(snapshot: EffectiveSnapshot, content_root: Path) -> List[str]:
    """资源变化时对该资源重新读一次并记录；持续不可读转占位清单。"""
    changed: List[str] = []
    for rel_key, digest in list(snapshot.assetHashes.items()):
        candidate = Path(content_root) / rel_key
        current = _file_hash(candidate)
        if current and current != digest:
            snapshot.assetHashes[rel_key] = current
            changed.append(rel_key)
        elif not current:
            snapshot.missingResources.append(rel_key)
            snapshot.warnings.append("资源持续不可读：{0}（改用占位）".format(rel_key))
            snapshot.assetHashes.pop(rel_key, None)
    if changed:
        snapshot.cacheKey = snapshot_cache_key(snapshot)
    return changed


def mark_source_updated(snapshot: EffectiveSnapshot) -> bool:
    """判断捕获后源内容是否已变化（按当前磁盘内容与捕获时的磁盘 hash 比较）。

    只读判断，不修改快照内容；``sourceUpdated`` 为 True 时界面提示“本轮结果仍
    对应捕获时版本，可再次生成新轮”。
    """
    try:
        manifest = ProjectManifest.load(snapshot.projectRoot)
        content_root = ProjectPaths(snapshot.projectRoot).resolve(
            manifest.relative_content_root()
        )
    except Exception:  # noqa: BLE001 - 源不可读时按未变化处理
        return False
    updated = False
    for chapter in snapshot.chapters:
        path = Path(content_root) / chapter.rel_path
        try:
            digest = sha256_text(path.read_text(encoding="utf-8"))
        except OSError:
            digest = ""
        if digest and chapter.diskHash and digest != chapter.diskHash:
            updated = True
            break
    snapshot.sourceUpdated = bool(updated)
    return snapshot.sourceUpdated


__all__ = [
    "SNAPSHOT_PARSE_VERSION", "SnapshotChapter", "EffectiveSnapshot",
    "discover_chapters", "count_unsaved", "collect_resource_paths",
    "capture_snapshot", "snapshot_cache_key", "refresh_assets", "mark_source_updated",
]
