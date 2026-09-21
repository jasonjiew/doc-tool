# -*- coding: utf-8 -*-
"""Safe, chapter-level reimport of an updated source DOCX."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from doc_tool.application.content.index import ContentIndexService
from doc_tool.application.content.references import ReferenceScanner
from doc_tool.application.content.traceability import TraceabilityService
from doc_tool.application.content.writer import ContentWriter, atomic_write
from doc_tool.domain.errors import DocToolError
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_REVISION_RECORD_NAMES = ("_revision_record.md", "_revision_record.markdown")


def _is_revision_record(rel_path: str) -> bool:
    name = Path(rel_path).name
    return name in _REVISION_RECORD_NAMES or name.startswith(".")


def _text_hash(path: Path) -> str:
    """章节内容哈希（sha1，与内容快照基线 ``content_baseline.json`` 同口径）。

    重导入基线（``reimport_base.json`` / 回退到快照基线）都用同一算法，避免
    新旧基线对比口径不一致导致冲突误判。
    """
    return hashlib.sha1(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ChapterChange:
    rel_path: str
    status: str
    conflict: bool = False
    use_new: bool = True


@dataclass
class ReimportResult:
    success: bool
    changes: List[ChapterChange] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    error_code: str = ""
    message: str = ""


def compare_chapters(current_root: Path, incoming_root: Path, base_hashes: Optional[Dict[str, str]] = None) -> List[ChapterChange]:
    """章节级对比：新增/修改/删除/未变 + 冲突判定。

    冲突语义（「不覆盖已有 Markdown 修改」）：
    - 基线缺失（首次重导入无基线）→ 保守判冲突，默认保留本地。
    - 仅源变更、本地未动 → 自动合入。
    - 源未变、本地已改 → 保留本地（不算冲突，也不写回旧源内容）。
    - 双方均变更且不同 → 冲突，默认保留本地。
    - 本地删除（基线有、当前缺、新源有）→ 冲突，默认保留删除。
    """
    base_hashes = base_hashes or {}
    current = {
        path.relative_to(current_root).as_posix(): _text_hash(path)
        for path in Path(current_root).rglob("*.md")
        if path.is_file() and not _is_revision_record(path.name)
    }
    incoming = {
        path.relative_to(incoming_root).as_posix(): _text_hash(path)
        for path in Path(incoming_root).rglob("*.md")
        if path.is_file() and not _is_revision_record(path.name)
    }
    changes: List[ChapterChange] = []
    for rel_path in sorted(set(current) | set(incoming)):
        if rel_path not in current:
            # 基线存在而当前缺失 = 用户本地删除：冲突，默认保留删除。
            in_base = rel_path in base_hashes
            changes.append(ChapterChange(rel_path, "added", in_base, not in_base))
        elif rel_path not in incoming:
            local_modified = rel_path not in base_hashes or current[rel_path] != base_hashes[rel_path]
            changes.append(ChapterChange(rel_path, "deleted", local_modified, not local_modified))
        elif current[rel_path] == incoming[rel_path]:
            changes.append(ChapterChange(rel_path, "unchanged"))
        else:
            base = base_hashes.get(rel_path)
            if base is None:
                conflict, use_new = True, False
            elif incoming[rel_path] == base:
                # 源未变、本地已改：保留本地，避免用旧源内容覆盖本地编辑。
                conflict, use_new = False, False
            elif current[rel_path] == base:
                # 仅源变更、本地未动：自动合入。
                conflict, use_new = False, True
            else:
                conflict, use_new = True, False
            changes.append(ChapterChange(rel_path, "modified", conflict, use_new))
    return changes


class ReimportService:
    def __init__(self, manifest: ProjectManifest, paths: ProjectPaths) -> None:
        self.manifest = manifest
        self.paths = paths
        self.transaction_file = paths.state_dir / "reimport_last.json"

    def source_changed(self) -> bool:
        source = self.paths.resolve(self.manifest.relative_source_docx())
        return not source.is_file() or file_sha256(source) != self.manifest.sourceSha256

    def source_missing(self) -> bool:
        """源文档是否存在（区别于「存在但指纹变化」）。"""
        source = self.paths.resolve(self.manifest.relative_source_docx())
        return not source.is_file()

    def _base_hashes(self) -> Dict[str, str]:
        """重导入基线哈希；缺文件时回退到内容快照基线（sha1 同口径）。

        首次导入已播种 ``reimport_base.json``；旧项目（升级前导入）没有该文件
        时回退 ``content_baseline.json``，保证首次重导入的自动合入仍可用。
        """
        try:
            payload = json.loads((self.paths.state_dir / "reimport_base.json").read_text(encoding="utf-8"))
            files = {rel: h for rel, h in dict(payload.get("files", {})).items() if not _is_revision_record(rel)}
            if files:
                return files
        except (OSError, ValueError, TypeError):
            pass
        try:
            from doc_tool.application.content.snapshot import ContentSnapshot

            snapshot = ContentSnapshot(self.paths.state_dir)
            snapshot.load()
            return {
                rel_path: entry.sha1
                for rel_path, entry in snapshot.entries.items()
            }
        except Exception:
            return {}

    def _writer(self) -> ContentWriter:
        return ContentWriter(
            self.paths.resolve(self.manifest.relative_content_root()),
            self.paths.state_dir,
            self.paths.resolve(self.manifest.relative_asset_root()),
        )

    def _merge_incoming_assets(self, staging_images: Path, staging_tables: Path) -> Dict[str, str]:
        """把暂存图片/复杂表格合并进项目资源目录，返回 ``暂存名 -> 目标引用`` 映射。

        重导入的 ``extract_content`` 把图片写到暂存 ``images/``、复杂表格 XML 写到
        暂存 ``tables/``（编号从 1 重新计数），若不合并进项目 ``assets/<类型>/``，
        新章节里的 ``images/img_NNNN.png`` / ``<!-- TABLE:<n>:tbl_NNNN.xml -->``
        引用会全部悬空。这里按续号分配，避免与既有资源重号：
        - 与项目内同名资源字节一致：沿用原名（映射到自身，引用无需改写）。
        - 内容不同或全新：分配续号新名并映射到新名（合并章节时改写引用）。
        """
        from doc_tool.application.content.asset_manager import next_image_name

        assets_root = self.paths.assets_dir(self.manifest.documentType)
        mapping: Dict[str, str] = {}
        images_root = self.paths.images_dir(self.manifest.documentType)
        images_root.mkdir(parents=True, exist_ok=True)
        if Path(staging_images).is_dir():
            for source in sorted(Path(staging_images).iterdir()):
                if not source.is_file():
                    continue
                existing = images_root / source.name
                if existing.is_file() and existing.read_bytes() == source.read_bytes():
                    mapping[source.name] = "images/{0}".format(source.name)
                    continue
                ext = source.suffix.lstrip(".") or "png"
                new_name = next_image_name(assets_root, self.manifest.documentType, ext)
                shutil.copy2(source, images_root / new_name)
                mapping[source.name] = "images/{0}".format(new_name)
        tables_root = self.paths.tables_dir(self.manifest.documentType)
        tables_root.mkdir(parents=True, exist_ok=True)
        if Path(staging_tables).is_dir():
            for source in sorted(Path(staging_tables).iterdir()):
                if not source.is_file():
                    continue
                existing = tables_root / source.name
                if existing.is_file() and existing.read_bytes() == source.read_bytes():
                    mapping[source.name] = source.name
                    continue
                new_name = self._next_table_name()
                shutil.copy2(source, tables_root / new_name)
                mapping[source.name] = new_name
        return mapping

    def _next_table_name(self) -> str:
        """分配下一个 ``tbl_NNNN.xml``（避开既有复杂表格文件）。"""
        maximum = 0
        try:
            for child in self.paths.tables_dir(self.manifest.documentType).glob("tbl_*.xml"):
                match = re.match(r"^tbl_(\d+)\.xml$", child.name)
                if match is not None:
                    maximum = max(maximum, int(match.group(1)))
        except OSError:
            pass
        return "tbl_{0:04d}.xml".format(maximum + 1)

    @staticmethod
    def _rewrite_incoming_refs(text: str, mapping: Dict[str, str]) -> str:
        """按资源合并映射改写章节 Markdown 里的图片/复杂表格引用。

        图片：``![alt](images/img_0001.png =640x480)``；
        复杂表格：``<!-- TABLE:1:tbl_0001.xml -->``。
        未在映射中的引用原样保留。
        """
        text = re.sub(
            r"!\[([^\]]*)\]\(images/([^\s)]+)((?:\s[^)]*)?)\)",
            lambda m: "![{0}]({1}{2})".format(
                m.group(1),
                mapping.get(m.group(2), "images/" + m.group(2)),
                m.group(3) or "",
            ),
            text,
        )
        return re.sub(
            r"<!--\s*TABLE:(\d+):([^\s>]+)\s*-->",
            lambda m: "<!-- TABLE:{0}:{1} -->".format(
                m.group(1), mapping.get(m.group(2), m.group(2))
            ),
            text,
        )

    def _rebuild_after_merge(self, writer: ContentWriter) -> None:
        """合并后重建索引/引用/追踪并重写重导入基线哈希（与当前内容一致）。"""
        index = ContentIndexService(writer.content_root).build()
        ReferenceScanner(index, writer.assets_root).scan_all()
        TraceabilityService(index, self.paths.state_dir).rebuild()
        hashes = {
            path.relative_to(writer.content_root).as_posix(): _text_hash(path)
            for path in writer.content_root.rglob("*.md")
            if path.is_file() and not _is_revision_record(path.name)
        }
        atomic_write(self.paths.state_dir / "reimport_base.json", json.dumps({"files": hashes}, ensure_ascii=False, indent=2))

    def _rollback_reimport(self, writer: ContentWriter, touched: List[Tuple[str, str]]) -> None:
        """失败回滚：内容、源文件、清单指纹、基线哈希一起恢复。

        回滚为尽力而为：任何一步失败都不能让回滚逻辑自身抛异常，否则会破坏
        ``reimport`` 「失败也返回结构化 ReimportResult」的契约。

        仅当本次重导入确实已把新源替换到源路径（``_source_replaced``）才从备份
        恢复源文件；替换前的失败意味着源文件仍是用户当前版本，绝不能拿上一次
        重导入留存的过期备份覆盖用户对源文档的新编辑，也不能把指纹重置为旧值
        （否则 ``source_changed`` 会因指纹与文件不符而恒为真）。
        """
        try:
            writer.rollback_keys(touched)
        except Exception:
            pass
        if getattr(self, "_source_replaced", False):
            try:
                backup = self.paths.state_dir / "reimport_last_source.docx"
                source = self.paths.resolve(self.manifest.relative_source_docx())
                if backup.is_file():
                    shutil.copy2(backup, source)
                    self.manifest.sourceSha256 = getattr(
                        self, "_rollback_sha", self.manifest.sourceSha256
                    )
                elif not getattr(self, "_source_existed", True):
                    # 源原本不存在且无备份（从未复制成功）：删除新源，
                    # 恢复「无源文档」原状，避免磁盘新 DOCX + 清单旧指纹
                    # 的永久不一致（source_changed 恒为真）。
                    source.unlink(missing_ok=True)
                    self.manifest.sourceSha256 = getattr(
                        self, "_rollback_sha", self.manifest.sourceSha256
                    )
                else:
                    # 源原本存在但备份缺失（复制失败）：无法恢复旧内容，
                    # 至少把指纹更新为新文件真实哈希；保存失败时保持现状。
                    if source.is_file():
                        self.manifest.sourceSha256 = file_sha256(source)
                self.manifest.save(self.paths.root, backup=True)
            except Exception:
                pass
        try:
            self._rebuild_after_merge(writer)
        except Exception:
            pass

    def _heading_style_map(self, new_source: Path) -> Optional[Dict[str, int]]:
        """新源文档的 styleId -> 级别识别映射（清单映射 ∪ 新源自身名称启发式）。

        清单里的 styleId 属于旧源/模板；换源后 Word 可能重编号，仅按清单识别
        会让标题树整章漏掉。并集保证两套 styleId 都能被认出来。仅作识别用途，
        不改变清单里「构建时写哪个 styleId」的决策。
        """
        from doc_tool.domain.ooxml import (
            OOXMLSecurityError,
            parse_heading_styles,
            read_docx_package,
        )

        merged: Dict[str, int] = {}
        try:
            with read_docx_package(new_source) as package:
                merged.update(parse_heading_styles(package.read("word/styles.xml")))
        except (OSError, KeyError, OOXMLSecurityError):
            pass
        for level, style_id in self.manifest.headingStyles.items():
            merged.setdefault(str(style_id), int(level))
        return merged or None

    def reimport(
        self,
        new_source: Path,
        *,
        choices: Optional[Dict[str, bool]] = None,
        extractor: Optional[Callable[[Path, Path], None]] = None,
    ) -> ReimportResult:
        choices = choices or {}
        new_source = Path(new_source)
        staging = Path(tempfile.mkdtemp(prefix="doc-tool-reimport-", dir=str(self.paths.state_dir)))
        incoming = staging / "content"
        incoming.mkdir(parents=True)
        writer = self._writer()
        touched: List[Tuple[str, str]] = []
        old_sha = self.manifest.sourceSha256
        self._rollback_sha = old_sha
        self._source_replaced = False
        source_path = self.paths.resolve(self.manifest.relative_source_docx())
        source_existed = source_path.is_file()
        self._source_existed = source_existed
        source_backup = self.paths.state_dir / "reimport_last_source.docx"
        try:
            if extractor is None:
                from doc_tool.adapters.importer import extract_content, split_into_tree
                from doc_tool.adapters.preflight import preflight

                heading_map = self._heading_style_map(new_source)
                preflight(new_source, heading_style_map=heading_map)
                extract_content(
                    new_source,
                    incoming,
                    staging / "images",
                    staging / "tables",
                    self.manifest.documentType,
                    heading_style_map=heading_map,
                )
                split_into_tree(incoming)
            else:
                extractor(new_source, incoming)
            # 合并暂存图片/复杂表格进项目资源，并取引用改写映射；随后清理
            # extract_content 在重导入暂存路径下误写到 ``.state/assets/`` 的
            # image-map/table-map（状态目录不该有资产，且永不清理）。
            asset_mapping = self._merge_incoming_assets(
                staging / "images", staging / "tables"
            )
            shutil.rmtree(self.paths.state_dir / "assets", ignore_errors=True)
            changes = compare_chapters(writer.content_root, incoming, self._base_hashes())
            conflicts = [item.rel_path for item in changes if item.conflict]
            for item in changes:
                if _is_revision_record(item.rel_path):
                    continue
                use_new = choices.get(item.rel_path, item.use_new)
                if item.status == "unchanged" or not use_new:
                    continue
                if item.status == "added":
                    text = self._rewrite_incoming_refs(
                        (incoming / item.rel_path).read_text(encoding="utf-8"),
                        asset_mapping,
                    )
                    result = writer.create_file(item.rel_path, text)
                    touched.append(("create", item.rel_path))
                elif item.status == "modified":
                    text = self._rewrite_incoming_refs(
                        (incoming / item.rel_path).read_text(encoding="utf-8"),
                        asset_mapping,
                    )
                    result = writer.write_text(item.rel_path, text)
                    touched.append(("edit", item.rel_path))
                else:
                    result = writer.delete_file(item.rel_path)
                    touched.append(("delete", item.rel_path))
                if not result.written:
                    raise OSError(result.error or "章节合并失败")
            # 重建索引/引用/追踪 + 重写基线哈希（不依赖源替换，先做，失败可整体回滚）。
            self._rebuild_after_merge(writer)
            # 先落事务记录，保证 rollback_last 始终可恢复；再做源替换与清单保存。
            atomic_write(self.transaction_file, json.dumps({
                "touched": [list(item) for item in touched],
                "oldSourceSha256": old_sha,
                "sourceBackup": str(source_backup),
                "sourceExisted": source_existed,
            }, ensure_ascii=False, indent=2))
            if source_path.is_file():
                shutil.copy2(source_path, source_backup)
            source_tmp = source_path.with_suffix(".docx.tmp")
            shutil.copy2(new_source, source_tmp)
            try:
                os.replace(str(source_tmp), str(source_path))
            except OSError:
                shutil.move(str(source_tmp), str(source_path))
            self._source_replaced = True
            self.manifest.sourceSha256 = file_sha256(source_path)
            self.manifest.save(self.paths.root, backup=True)
            return ReimportResult(True, changes, conflicts)
        except DocToolError as exc:
            self._rollback_reimport(writer, touched)
            return ReimportResult(False, error_code=exc.code, message=exc.user_message)
        except Exception as exc:
            self._rollback_reimport(writer, touched)
            return ReimportResult(False, error_code="E_REIMPORT", message=str(exc))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            # 源替换临时文件在 os.replace/shutil.move 双失败时残留：
            # 一律清理，避免 .docx.tmp 遗留在项目 original/ 目录。
            try:
                source_path.with_suffix(".docx.tmp").unlink(missing_ok=True)
            except OSError:
                pass

    def rollback_last(self) -> List[str]:
        payload = json.loads(self.transaction_file.read_text(encoding="utf-8"))
        writer = self._writer()
        touched = [tuple(item) for item in payload.get("touched", [])]
        failures = writer.rollback_keys(touched)
        backup = Path(str(payload.get("sourceBackup", "")))
        source = self.paths.resolve(self.manifest.relative_source_docx())
        if backup.is_file():
            shutil.copy2(backup, source)
        elif not payload.get("sourceExisted", True):
            # 源原本不存在且无备份：删除新源，恢复「无源文档」原状。
            source.unlink(missing_ok=True)
        self.manifest.sourceSha256 = str(payload.get("oldSourceSha256", ""))
        self.manifest.save(self.paths.root, backup=True)
        # 回滚后重写基线与索引/追踪，保证下次重导入对比口径与回滚后的内容一致。
        self._rebuild_after_merge(writer)
        return failures
