# -*- coding: utf-8 -*-
"""Named checkpoints and immutable project baselines."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from doc_tool.application.content.writer import ContentWriter, atomic_write
from doc_tool.domain.manifest import ProjectManifest


def _safe_name(name: str) -> str:
    value = str(name).strip()
    if not value or value in (".", "..") or re.search(r'[<>:"/\\|?*]', value):
        raise ValueError("名称不能为空且不能包含文件名非法字符。")
    return value


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_files(content_root: Path) -> List[Path]:
    return sorted(path for path in Path(content_root).rglob("*.md") if path.is_file())


class CheckpointStore:
    def __init__(self, state_dir: Path) -> None:
        self.root = Path(state_dir) / "checkpoints"

    def create(
        self,
        name: str,
        manifest_path: Path,
        content_root: Path,
        validation_report: Optional[Path] = None,
    ) -> Path:
        target = self.root / _safe_name(name)
        if target.exists():
            raise FileExistsError("检查点名称已存在：{0}".format(name))
        (target / "content").mkdir(parents=True)
        shutil.copy2(manifest_path, target / "project.yml")
        for source in _content_files(content_root):
            destination = target / "content" / source.relative_to(content_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if validation_report is not None and Path(validation_report).is_file():
            shutil.copy2(validation_report, target / "validation.md")
        return target


class BaselineStore:
    def __init__(self, state_dir: Path) -> None:
        self.root = Path(state_dir) / "baselines"

    def freeze(self, manifest: ProjectManifest, content_root: Path) -> Path:
        version = _safe_name(manifest.documentVersion)
        metadata = self.root / (version + ".json")
        snapshot_root = self.root / version / "content"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        files = {}
        for source in _content_files(content_root):
            rel_path = source.relative_to(content_root).as_posix()
            destination = snapshot_root / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            files[rel_path] = _hash(source)
        payload = {
            "version": manifest.documentVersion,
            "frozenAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "manifest": manifest.to_dict(),
            "files": files,
        }
        atomic_write(metadata, json.dumps(payload, ensure_ascii=False, indent=2))
        return metadata

    def load(self, version: str) -> dict:
        return json.loads((self.root / (_safe_name(version) + ".json")).read_text(encoding="utf-8"))

    def restore(
        self,
        version: str,
        writer: ContentWriter,
        *,
        confirmed: bool,
    ) -> List[str]:
        if not confirmed:
            return []
        payload = self.load(version)
        version_name = _safe_name(version)
        snapshot_root = self.root / version_name / "content"
        expected = set(payload.get("files", {}))
        # 恢复前校验快照完整：目录存在、文件集齐全、内容与冻结时哈希一致。
        # 缺失/损坏时直接失败，绝不"成功"地删掉当前内容——那是数据丢失。
        if not snapshot_root.is_dir():
            raise OSError(
                "基线快照目录缺失，无法恢复：{0}".format(snapshot_root)
            )
        snapshot_files = {
            path.relative_to(snapshot_root).as_posix()
            for path in _content_files(snapshot_root)
        }
        missing = expected - snapshot_files
        if missing:
            raise OSError(
                "基线快照文件缺失，无法恢复：{0}".format("、".join(sorted(missing)))
            )
        corrupted = [
            rel_path
            for rel_path in expected
            if _hash(snapshot_root / rel_path) != payload["files"][rel_path]
        ]
        if corrupted:
            raise OSError(
                "基线快照内容已变化（可能被冻结后修改），拒绝恢复：{0}".format(
                    "、".join(sorted(corrupted))
                )
            )
        restored: List[str] = []
        # 1) 先恢复全部基线文件（写失败即中止，不触碰任何当前文件）。
        for rel_path in sorted(expected):
            result = writer.write_text(
                rel_path,
                (snapshot_root / rel_path).read_text(encoding="utf-8"),
            )
            if not result.written:
                raise OSError(result.error or "恢复基线失败")
            restored.append(rel_path)
        # 2) 全部基线文件写回成功后，才删除基线外的当前文件。
        current = {
            path.relative_to(writer.content_root).as_posix()
            for path in _content_files(writer.content_root)
        }
        for rel_path in sorted(current - expected):
            result = writer.delete_file(rel_path)
            if not result.written:
                raise OSError(result.error or "删除基线外文件失败")
            restored.append(rel_path)
        return restored


@dataclass(frozen=True)
class CheckItem:
    check_id: str
    passed: bool
    message: str


def _version_tuple(value: str) -> tuple:
    parts = str(value).strip().split(".")
    if not parts or any(not item.isdigit() for item in parts):
        return (-1,)
    return tuple(int(item) for item in parts) + (0,) * (3 - len(parts))


def pre_publish_checks(
    *,
    quality_errors: int,
    unresolved_reviews: int,
    current_version: str,
    baseline_version: Optional[str],
    pending_changes: int,
) -> List[CheckItem]:
    version_ok = baseline_version is None or _version_tuple(current_version) >= _version_tuple(baseline_version)
    return [
        CheckItem("quality", quality_errors == 0, "质量规则无 error"),
        CheckItem("reviews", unresolved_reviews == 0, "无未解决评审意见"),
        CheckItem("version", version_ok, "当前版本不低于冻结基线"),
        CheckItem("changes", pending_changes == 0, "无未完成改动"),
    ]
