# -*- coding: utf-8 -*-
"""以 Markdown 为源建项（V2.8 28-E / 5.3，MAIN-A 1.3 资源身份修正）。

与「即时模板填充」的区别：

- 本模块产出的是**可持续维护的项目**（``project.yml`` + ``content/`` + ``assets/``）；
- 即时模板填充（``template_fill``）只从一份文档直接生成 docx，**不建项目**。
两者共享解析与渲染能力，但不互相调用以避免双重实现。

入口：文件清单（按给定顺序）、资源目录、底模与规范包选择。

资源身份（MAIN-A 1.3）：
- 资源按**相对来源目录的路径**判定身份，``a/logo.png`` 与 ``b/logo.png`` 各自保留；
  旧实现按 basename 去重会把后到者丢弃并让引用指向错误的图。
- 目标路径冲突且内容不同时，后到者落 ``<名>-<n>.<扩展名>``，只有引用它的章节被改写；
  内容相同的资源复用同一份文件（同内容复用，不重复复制）。
- 资源根目录统一为 ``assets/<文档类型>/``，与 ``assets_dir()``、资源扫描、图片粘贴
  写入位置一致，保证预览/检查/HTML/DOCX 看到同一份资源。
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

from doc_tool.application.chapter_order import resolve_chapter_order
from doc_tool.domain.errors import ProjectManifestError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.version import APP_VERSION, PROJECT_SCHEMA_VERSION

# Markdown 链接/图片：``![alt](target "title")`` 与 ``[text](target)``。
_LINK_RE = re.compile(r"(!?\[[^\]]*\]\(\s*)(<[^>]*>|[^)\s]+)([^)]*)(\))")
_FENCE_RE = re.compile(r"^(\x60\x60\x60|~~~)")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_SIZE_SUFFIX_RE = re.compile(r"\s+=\s*\d+(?:\s*x\s*\d+)?\s*$")
_NON_RESOURCE_SUFFIXES = (".md", ".markdown")
#: 章节标题行（正文首个非空行）：提出后作为章节名，正文不再重复出现标题。
_H1_RE = re.compile(r"^#\s+(?P<title>\S.*?)\s*$")
#: 已带章节编号的文件名（``1 概述`` / ``3.2 接口``）：保持用户命名不变。
_NUMBERED_STEM_RE = re.compile(r"^\d+(?:[.\-]\d+)*[\s、.]")


def split_chapter_title(text: str) -> Tuple[str, str]:
    """把章节正文开头的 H1 提为章节标题，返回 ``(标题, 正文)``。

    构建内核按**文件名**写章节标题（``第1章 …``/``1.1 …``），章节文件内部再出现
    H1 会被构建前校验判为「内部标题层级不深于文件章节层级」并阻断出稿。因此导入时
    把首个 H1 变成章节名，正文从下一层开始；没有 H1 时原样返回（调用方按字节复制）。
    """
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = _H1_RE.match(line.strip())
        if match is None:
            return "", str(text or "")
        title = match.group("title").strip()
        body = lines[:index] + lines[index + 1:]
        while body and not body[0].strip():
            body.pop(0)
        body_text = "\n".join(body)
        if body_text:
            body_text += "\n"
        return title, body_text
    return "", str(text or "")


def _chapter_file_name(source: Path, order: int, title: str) -> str:
    """章节文件名：已带编号的保持原名，否则按导入顺序补编号（构建按编号排序）。"""
    stem = Path(source).stem
    if _NUMBERED_STEM_RE.match(stem):
        return Path(source).name
    clean = re.sub(r"[\\/:*?\"<>|]+", " ", title or stem).strip() or stem
    return "{0:02d} {1}{2}".format(order, clean, Path(source).suffix or ".md")


@dataclass
class MarkdownProjectResult:
    """以 Markdown 建项结果。"""

    project_root: Optional[Path] = None
    chapters: List[str] = field(default_factory=list)
    copied_resources: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.project_root is not None and not self.errors

    def to_dict(self) -> dict:
        return {
            "projectRoot": str(self.project_root) if self.project_root else "",
            "ok": self.ok,
            "chapters": list(self.chapters),
            "copiedResources": list(self.copied_resources),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class _ResourcePlan:
    """资源复制结果：真正复制出的相对路径 + 需要改写引用的章节。"""

    copied: List[str] = field(default_factory=list)
    #: ``来源绝对路径 -> {原文引用: 新相对路径}``
    rewrites: Dict[str, Dict[str, str]] = field(default_factory=dict)


def _file_digest(path: Path, cache: Dict[str, str]) -> str:
    """文件内容摘要（失败返回空串，调用方须把空串视为「未知」）。"""
    key = str(path)
    if key in cache:
        return cache[key]
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        cache[key] = ""
        return ""
    value = digest.hexdigest()
    cache[key] = value
    return value


def _normalize_dest(target: str) -> str:
    """把引用目标归一成资源目录下的安全相对路径；不该作为资源时返回空串。"""
    text = (target or "").strip().replace("\\", "/")
    if not text:
        return ""
    text = _SIZE_SUFFIX_RE.sub("", text)
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    if not text or text.startswith("#") or _SCHEME_RE.match(text):
        return ""
    text = text.lstrip("/")
    normalized = posixpath.normpath(text)
    while normalized.startswith("../"):
        normalized = normalized[3:]
    if normalized in (".", "", "..") or normalized.startswith("/"):
        return ""
    return normalized


def _is_resource_target(target: str) -> bool:
    """章节 Markdown 链接不算资源；``.md`` 目标整体排除，避免把章节复制进资源目录。"""
    normalized = _normalize_dest(target)
    if not normalized:
        return False
    lowered = normalized.lower()
    return not lowered.endswith(_NON_RESOURCE_SUFFIXES)


def _referenced_targets(text: str) -> List[str]:
    """收集正文（跳过围栏代码块）里的 Markdown 链接/图片目标，按出现顺序去重。"""
    targets: List[str] = []
    seen: set = set()
    in_code = False
    for line in text.splitlines():
        if _FENCE_RE.match(line.lstrip()):
            in_code = not in_code
            continue
        if in_code:
            continue
        for match in _LINK_RE.finditer(line):
            raw = match.group(2).strip()
            if raw.startswith("<") and raw.endswith(">"):
                raw = raw[1:-1].strip()
            if not _is_resource_target(raw) or raw in seen:
                continue
            seen.add(raw)
            targets.append(raw)
    return targets


def _iter_root_files(base: Path) -> Iterator[Tuple[str, Path]]:
    """按稳定顺序遍历目录下的文件，返回 ``(相对路径, 绝对路径)``。"""
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(base).as_posix()
        except ValueError:
            continue
        yield relative, path


def _locate_reference(source: Path, target: str, asset_roots: Sequence[Union[str, Path]]) -> Optional[Path]:
    """按「来源文件同级目录优先、其次显式资源目录」定位被引用资源。"""
    relative = target.replace("\\", "/")
    candidates: List[Path] = [source.parent / relative]
    for item in asset_roots or []:
        candidates.append(Path(item) / relative)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _disambiguate(dest_rel: str, origin: Path, claimed: Dict[str, Path], digests: Dict[str, str]) -> Optional[str]:
    """为同名不同内容的资源分配 ``<名>-<n>.<扩展名>``；同内容则复用既有目标。"""
    stem, suffix = posixpath.splitext(dest_rel)
    index = 2
    origin_digest = _file_digest(origin, digests)
    while True:
        candidate = "{0}-{1}{2}".format(stem, index, suffix)
        other = claimed.get(candidate)
        if other is None:
            claimed[candidate] = origin
            return candidate
        if other.resolve() == origin.resolve():
            return candidate
        other_digest = _file_digest(other, digests)
        if origin_digest and other_digest and origin_digest == other_digest:
            return candidate
        index += 1


def _assign_dest(
    dest_rel: str,
    origin: Path,
    claimed: Dict[str, Path],
    digests: Dict[str, str],
) -> Optional[str]:
    """把来源文件映射到资源目录下的目标相对路径（同内容复用，冲突改名）。"""
    existing = claimed.get(dest_rel)
    if existing is None:
        claimed[dest_rel] = origin
        return dest_rel
    if existing.resolve() == origin.resolve():
        return dest_rel
    left = _file_digest(existing, digests)
    right = _file_digest(origin, digests)
    if left and right and left == right:
        return dest_rel
    return _disambiguate(dest_rel, origin, claimed, digests)


def _copy_resources(
    sources: Sequence[Union[str, Path]],
    asset_roots: Sequence[Union[str, Path]],
    asset_root: Path,
    result: MarkdownProjectResult,
    chapter_sources: Sequence[Path] = (),
) -> _ResourcePlan:
    """把资源复制到 ``assets/<类型>/``，保持来源身份并返回需改写的章节引用。

    两轮处理：

    1. **被引用资源**：每个 Markdown 来源同级目录（及显式资源目录）里被正文引用的
       资源，按来源各自的引用解析，避免两来源 ``image.png`` 串到同一张图；
       目标冲突时改写该章节的引用。
    2. **显式资源目录整体复制**：保持既有契约（选择资源目录即整目录带入），
       但按相对路径判定身份，不再按 basename 丢弃后到者。
    """
    plan = _ResourcePlan()
    claimed: Dict[str, Path] = {}
    digests: Dict[str, str] = {}
    copied_targets: set = set()
    chapter_set = {Path(item).resolve() for item in chapter_sources}

    def _emit(origin: Path, dest_rel: str) -> bool:
        target = asset_root / dest_rel
        key = str(target)
        if key in copied_targets:
            return True
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
        except OSError as exc:
            result.skipped.append("资源复制失败：{0}（{1}）".format(dest_rel, exc))
            return False
        copied_targets.add(key)
        plan.copied.append(dest_rel)
        return True

    # 第一轮：正文真实引用到的资源。
    source_paths = [Path(item) for item in sources or []]
    for source in source_paths:
        if not source.is_file():
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for target in _referenced_targets(text):
            dest_rel = _normalize_dest(target)
            origin = _locate_reference(source, target, asset_roots)
            if origin is None or origin.resolve() in chapter_set:
                continue
            assigned = _assign_dest(dest_rel, origin, claimed, digests)
            if assigned is None:
                continue
            if not _emit(origin, assigned):
                continue
            if assigned != target:
                plan.rewrites.setdefault(source.resolve().as_posix(), {})[target] = assigned

    # 第二轮：显式资源目录整体带入（跳过章节来源自身）。
    for item in asset_roots or []:
        base = Path(item)
        if not base.is_dir():
            result.warnings.append("资源目录不存在，已跳过：{0}".format(item))
            continue
        for relative, path in _iter_root_files(base):
            if path.resolve() in chapter_set:
                continue
            dest_rel = _normalize_dest(relative)
            if not dest_rel:
                continue
            assigned = _assign_dest(dest_rel, path, claimed, digests)
            if assigned is None:
                continue
            _emit(path, assigned)

    return plan


def _rewrite_links(text: str, mapping: Dict[str, str]) -> str:
    """按映射改写正文里的链接/图片目标；围栏代码块内的文本原样保留。"""
    if not mapping:
        return text

    def _replace(match: "re.Match") -> str:
        prefix, raw, suffix, close = match.group(1), match.group(2), match.group(3), match.group(4)
        bracketed = raw.startswith("<") and raw.endswith(">")
        url = raw[1:-1].strip() if bracketed else raw
        new = mapping.get(url)
        if new is None:
            return match.group(0)
        replacement = "<{0}>".format(new) if bracketed or " " in new else new
        return "{0}{1}{2}{3}".format(prefix, replacement, suffix, close)

    out: List[str] = []
    in_code = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        ending = line[len(stripped):]
        if _FENCE_RE.match(stripped.lstrip()):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        out.append(_LINK_RE.sub(_replace, stripped) + ending)
    return "".join(out)


def create_project_from_markdown(
    sources: Sequence[Union[str, Path]],
    project_root: Union[str, Path],
    *,
    asset_roots: Sequence[Union[str, Path]] = (),
    template_path: Optional[Union[str, Path]] = None,
    pack_source: Optional[Union[str, Path]] = None,
    document_name: str = "",
    document_no: str = "",
    document_version: str = "1.0",
    document_type: str = "general",
    chapter_order: Optional[Sequence[str]] = None,
) -> MarkdownProjectResult:
    """把一批 Markdown 变成可持续维护项目。

    - ``sources`` **顺序即章节顺序**；与 ``chapter_order`` 合并后写入显式 ``chapters``；
    - 资源按相对路径身份复制到 ``assets/<文档类型>/``，同名不同内容改名并只改写对应章节；
    - 底模与规范包为**可选**：缺失只警告，不阻断建项（默认兜底）。
    """
    result = MarkdownProjectResult()
    root = Path(project_root)
    if (root / "project.yml").exists():
        result.errors.append("目标目录已存在项目清单，未覆盖。")
        return result

    doc_type = str(document_type or "general") or "general"
    content_root = root / "content"
    asset_root = root / "assets" / doc_type
    table_root = asset_root / "tables"
    template_dir = root / "template"
    for directory in (content_root, table_root, template_dir):
        directory.mkdir(parents=True, exist_ok=True)

    produced: List[str] = []
    chapters: List[Tuple[Path, Path]] = []
    for index, item in enumerate(sources or []):
        source = Path(item)
        if not source.is_file():
            result.skipped.append("源文件不存在：{0}".format(item))
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            result.skipped.append("读取失败：{0}（{1}）".format(source, exc))
            continue
        title, body = split_chapter_title(text)
        name = _chapter_file_name(source, index + 1, title)
        target = content_root / name
        if target.exists():
            suffix_index = index + 1
            while target.exists():
                stem = "{0}-{1}".format(Path(name).stem, suffix_index)
                target = content_root / (stem + source.suffix)
                suffix_index += 1
            result.warnings.append("同名章节已存在，已重命名：{0}".format(target.name))
        try:
            if title:
                # 首个 H1 提为章节名后，正文不再重复标题（构建内核按文件名写章节标题）。
                target.write_text(body, encoding="utf-8", newline="\n")
                result.warnings.append(
                    "章节标题取自正文首个一级标题：{0}".format(target.name)
                )
            else:
                shutil.copy2(source, target)
        except OSError as exc:
            result.skipped.append("复制失败：{0}（{1}）".format(source, exc))
            continue
        produced.append(target.name)
        chapters.append((source, target))

    plan = _copy_resources(
        [source for source, _target in chapters],
        asset_roots,
        asset_root,
        result,
        chapter_sources=[source for source, _target in chapters],
    )
    result.copied_resources = plan.copied

    # 资源同名冲突只改写「引用它的那一章」，原文件与未被冲突影响的章节保持不变。
    for source, target in chapters:
        mapping = plan.rewrites.get(source.resolve().as_posix())
        if not mapping:
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        rewritten = _rewrite_links(text, mapping)
        if rewritten == text:
            continue
        try:
            target.write_text(rewritten, encoding="utf-8")
        except OSError as exc:
            result.warnings.append("引用改写失败：{0}（{1}）".format(target.name, exc))
            continue
        result.warnings.append(
            "同名资源内容不同，已按来源保留：{0}".format(
                "、".join("{0} -> {1}".format(old, new) for old, new in sorted(mapping.items()))
            )
        )

    if template_path is not None:
        template = Path(template_path)
        if template.is_file():
            shutil.copy2(template, template_dir / "template.docx")
        else:
            result.warnings.append("指定底模不存在，已跳过：{0}".format(template_path))
    else:
        result.warnings.append("未指定底模，请在项目内补充 template/template.docx。")

    pack_ref: Dict[str, str] = {}
    document_kind = ""
    if pack_source is not None:
        from doc_tool.application.standard_pack import (
            install_pack,
            pack_fingerprint,
            validate_pack_dir,
        )

        validation = validate_pack_dir(pack_source)
        if validation.ok and validation.pack is not None:
            target, install = install_pack(pack_source, root)
            result.warnings.extend(install.warnings)
            if target is not None:
                pack_ref = {
                    "id": validation.pack.pack_id,
                    "version": validation.pack.version,
                    "hash": pack_fingerprint(validation.pack),
                }
                document_kind = validation.pack.document_kind
                if not (template_dir / "template.docx").is_file():
                    pack_template = validation.pack.entry("template.docx")
                    if pack_template is not None:
                        shutil.copy2(pack_template, template_dir / "template.docx")
        else:
            result.warnings.extend(validation.errors or ["规范包不可用，已跳过。"])

    order = resolve_chapter_order(produced, list(chapter_order or []))
    result.warnings.extend(order.warnings)
    result.chapters = list(order.ordered)

    try:
        manifest = ProjectManifest(
            documentType=doc_type,
            documentNo=document_no or "GX-MD",
            documentName=document_name or root.name,
            documentVersion=document_version,
            sourceSha256="",
            schemaVersion=PROJECT_SCHEMA_VERSION,
            paths={
                "templateDocx": "template/template.docx",
                "contentRoot": "content",
                "assetRoot": "assets/{0}".format(doc_type),
                "tableRoot": "assets/{0}/tables".format(doc_type),
            },
            headingStyles={1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6"},
            bodyStyle="a",
            documentKind=document_kind,
            chapters=result.chapters,
            standardPack=pack_ref,
            qualitySource="pack" if pack_ref else "",
            createdWithVersion=APP_VERSION,
        )
        manifest.save(root)
    except ProjectManifestError as exc:
        result.errors.append("清单校验失败：{0}".format(exc))
        return result
    result.project_root = root
    if not result.chapters:
        result.warnings.append("未收集到章节，项目将以空内容起步。")
    return result


def describe_entry_point() -> Dict[str, str]:
    """说明三条建项路径的差异（供界面与文档复用）。"""
    return {
        "fromPack": "从规范包起步：包提供章节骨架与配置，适合新文档。",
        "fromWord": "接管现有 Word：复用预检/映射/往返门禁，适合已有成文。",
        "fromMarkdown": "以 Markdown 起步：按文件顺序建章节，适合已有 Docs-as-Code 内容。",
        "instantTemplateFill": "即时模板填充：直接从一份文档生成 docx，**不建项目**，不可持续维护。",
    }