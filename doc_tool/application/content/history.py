# -*- coding: utf-8 -*-
"""Successful build history, artifact diffs, and reversible restore."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from xml.etree import ElementTree as ET

from doc_tool.application.content.changes import render_unified_diff
from doc_tool.application.content.writer import ContentWriter, atomic_write
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.output_state import compute_sha256, read_state


def _sha1_bytes(data: bytes) -> str:
    """内容快照哈希（sha1，与 ``snapshot.py`` / spec 的 sha1 契约一致）。"""
    return hashlib.sha1(data).hexdigest()


def _directory_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not Path(root).exists():
        return ""
    for path in sorted(item for item in Path(root).rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class HistoryEntry:
    history_id: str
    completed_at: str
    document_version: str
    diagnostic: bool
    output_file: str
    output_exists: bool
    data: dict
    formal: bool = False


class BuildHistoryStore:
    def __init__(self, state_dir: Path) -> None:
        self.root = Path(state_dir) / "history"

    def archive(
        self,
        manifest: ProjectManifest,
        content_root: Path,
        template_path: Path,
        assets_root: Path,
        output_path: Path,
        *,
        diagnostic: bool,
    ) -> Path:
        now = datetime.now(timezone.utc)
        history_id = now.strftime("%Y%m%dT%H%M%S%fZ")
        snapshot = self.root / history_id / "content"
        files: Dict[str, str] = {}
        for source in sorted(Path(content_root).rglob("*.md")):
            if not source.is_file():
                continue
            rel_path = source.relative_to(content_root).as_posix()
            data = source.read_bytes()
            files[rel_path] = _sha1_bytes(data)
            destination = snapshot / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        state = read_state(output_path)
        payload = {
            "historyId": history_id,
            "completedAt": now.isoformat(timespec="seconds"),
            "appVersion": manifest.lastSuccessfulBuildVersion or "",
            "documentVersion": manifest.documentVersion,
            "diagnostic": bool(diagnostic),
            "formal": bool(state.formal) if state is not None else bool(not diagnostic),
            "stages": list(state.stages) if state is not None else [],
            "publishNotes": manifest.publishNotes,
            "contentFiles": files,
            "templateSha256": compute_sha256(template_path) if Path(template_path).is_file() else "",
            "assetsSha256": _directory_hash(assets_root),
            "outputFile": Path(output_path).name,
            "outputPath": str(Path(output_path)),
            "outputSha256": compute_sha256(output_path),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        metadata = self.root / (history_id + ".json")
        atomic_write(metadata, json.dumps(payload, ensure_ascii=False, indent=2))
        # 归档完整性校验：回读元数据并与本次内存快照比对，写入截断/损坏即刻暴露。
        try:
            reread = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OSError("历史归档写入校验失败：{0}".format(history_id)) from exc
        if reread.get("contentFiles") != files:
            raise OSError("历史归档校验失败：快照记录不一致：{0}".format(history_id))
        return metadata

    def list_entries(self) -> List[HistoryEntry]:
        entries: List[HistoryEntry] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                output_path = Path(str(data.get("outputPath", "")))
                entries.append(
                    HistoryEntry(
                        history_id=str(data.get("historyId", path.stem)),
                        completed_at=str(data.get("completedAt", "")),
                        document_version=str(data.get("documentVersion", "")),
                        diagnostic=bool(data.get("diagnostic", False)),
                        output_file=str(data.get("outputFile", "")),
                        output_exists=output_path.is_file(),
                        data=data,
                        formal=bool(data.get("formal", False)),
                    )
                )
            except (OSError, ValueError, TypeError):
                continue
        return sorted(
            entries,
            key=lambda entry: (entry.completed_at, entry.history_id),
            reverse=True,
        )

    def get(self, history_id: str) -> HistoryEntry:
        for entry in self.list_entries():
            if entry.history_id == history_id:
                return entry
        raise FileNotFoundError("历史版本不存在：{0}".format(history_id))

    def diff(self, older_id: str, newer_id: str) -> dict:
        older = self.get(older_id).data.get("contentFiles", {})
        newer = self.get(newer_id).data.get("contentFiles", {})
        old_keys, new_keys = set(older), set(newer)
        return {
            "added": sorted(new_keys - old_keys),
            "deleted": sorted(old_keys - new_keys),
            "modified": sorted(path for path in old_keys & new_keys if older[path] != newer[path]),
        }

    def text_diff(self, older_id: str, newer_id: str, rel_path: str) -> str:
        old_path = self.root / older_id / "content" / rel_path
        new_path = self.root / newer_id / "content" / rel_path
        old_text = old_path.read_text(encoding="utf-8") if old_path.is_file() else ""
        new_text = new_path.read_text(encoding="utf-8") if new_path.is_file() else ""
        return render_unified_diff(old_text, new_text)

    def restore(
        self,
        history_id: str,
        writer: ContentWriter,
        *,
        confirmed: bool,
        rebuild: Optional[Callable[[], object]] = None,
    ) -> List[str]:
        if not confirmed:
            return []
        entry = self.get(history_id)
        snapshot = self.root / history_id / "content"
        expected = dict(entry.data.get("contentFiles", {}))
        if not snapshot.is_dir() or not expected:
            raise FileNotFoundError(
                "历史快照缺失，已拒绝恢复：{0}".format(history_id)
            )
        # 快照文件集合与记录哈希必须一致：快照不完整/损坏时拒绝恢复，
        # 避免把「current - expected」误当删除而静默移走用户当前文件。
        actual_files = {
            path.relative_to(snapshot).as_posix()
            for path in snapshot.rglob("*.md") if path.is_file()
        }
        if set(expected) != actual_files:
            raise FileNotFoundError(
                "历史快照不完整，已拒绝恢复：{0}".format(history_id)
            )
        for rel_path, recorded in expected.items():
            source = snapshot / rel_path
            if not source.is_file() or _sha1_bytes(source.read_bytes()) != recorded:
                raise FileNotFoundError(
                    "历史快照内容与记录不一致，已拒绝恢复：{0}".format(rel_path)
                )
        changed: List[str] = []
        # 事务化：先捕获清单条目数作为回滚起点；任一步写入失败即回滚本次
        # 恢复已落盘的改动，避免出现「部分文件已恢复、部分还是旧版」的半状态。
        checkpoint = writer.manifest.entry_count()
        try:
            for rel_path in sorted(expected):
                source = snapshot / rel_path
                result = writer.write_text(rel_path, source.read_text(encoding="utf-8"))
                if not result.written:
                    raise OSError(result.error or "历史恢复失败")
                changed.append(rel_path)
            current = {
                path.relative_to(writer.content_root).as_posix()
                for path in writer.content_root.rglob("*.md") if path.is_file()
            }
            for rel_path in sorted(current - set(expected)):
                result = writer.delete_file(rel_path)
                if not result.written:
                    raise OSError(result.error or "历史恢复删除失败")
                changed.append(rel_path)
        except OSError as exc:
            rollback_failures = writer.rollback(since=checkpoint)
            if rollback_failures:
                raise OSError(
                    "{0}；恢复已回滚但部分文件回滚失败：{1}".format(
                        exc, "、".join(rollback_failures)
                    )
                ) from exc
            raise
        if rebuild is not None:
            rebuild()
        return changed


def extract_docx_text(path: Path) -> str:
    """Extract visible Word text for semantic artifact comparison."""
    with zipfile.ZipFile(path) as package:
        root = ET.fromstring(package.read("word/document.xml"))
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(namespace + "p"):
        paragraphs.append("".join(node.text or "" for node in paragraph.iter(namespace + "t")))
    return "\n".join(paragraphs)


def diff_docx_text(older: Path, newer: Path) -> str:
    try:
        return render_unified_diff(extract_docx_text(older), extract_docx_text(newer))
    except (KeyError, ET.ParseError, zipfile.BadZipFile, OSError) as exc:
        # 产物缺失/损坏时给出可读提示而非抛栈（历史面板对比入口容错）。
        return "无法提取 Word 文本进行对比：{0}".format(exc)
