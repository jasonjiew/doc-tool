# -*- coding: utf-8 -*-
"""文件级派生索引缓存（V3.6 36-B/36-C）。

缓存是**可丢弃的派生数据**：条目 ID、关系、评审、版本集合等业务记录永不以它
为权威。命中判定使用内容摘要 + 解析器版本 + 影响解析的配置/装配指纹；``mtime``
与 ``size`` 只用于写入与统计，不作为正确性来源。

失效与兜底：

- 内容摘要变化、解析器版本变化、配置/装配指纹变化 → 重新解析；
- 缓存损坏、版本不认识、写入失败 → 直接读取源码重建，并返回可诊断信息；
- 缓存关闭时不读不写，行为与无缓存完全一致。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: 解析器版本：解析逻辑变化时必须递增，使旧缓存自动失效。
PARSER_VERSION = "content-index/2"
#: 缓存文件名与内部版本标记。
CACHE_NAME = "content-index-v1.json"
CACHE_SCHEMA_VERSION = 1
#: 默认容量（超过后按最近使用清理）。
DEFAULT_MAX_ENTRIES = 4000


def content_digest(path) -> str:
    """文件内容摘要（唯一正确性来源；读取失败返回空串）。"""
    target = Path(path)
    try:
        hasher = hashlib.sha256()
        with open(target, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return ""


def text_digest(text: str) -> str:
    """内存文本摘要（未保存缓冲使用，不落磁盘旧内容）。"""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def config_fingerprint(project_root, *, extra: Sequence[str] = ()) -> str:
    """影响解析结果的配置/规范/装配指纹。

    覆盖：清单变量与文档类别、检查策略来源、``quality/`` 术语与规则、
    V3.0 变体与模块槽位声明。任一变化都会使相关派生物失效。
    """
    root = Path(project_root)
    parts: List[str] = list(extra or ())
    manifest = root / "project.yml"
    parts.append(content_digest(manifest))
    for name in (
        "quality/terms.json", "quality/rules.json",
        "variants.yml", "modules.yml", "modules.json",
    ):
        candidate = root / name
        if candidate.is_file():
            parts.append("{0}:{1}".format(name, content_digest(candidate)))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def module_fingerprint(module) -> str:
    """模块内容 + 参数默认值 + 资源摘要的稳定指纹（V3.6 36-C 3.2）。"""
    if module is None:
        return ""
    parts: List[str] = [str(getattr(module, "body", "") or "")]
    for param in getattr(module, "parameters", None) or []:
        parts.append("{0}={1}".format(
            getattr(param, "name", ""), getattr(param, "default", ""),
        ))
    for resource in getattr(module, "resources", None) or []:
        parts.append("{0}:{1}".format(
            getattr(resource, "path", ""), getattr(resource, "sha256", ""),
        ))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def chapter_assembly_fingerprints(project_root, chapters, *, library=None,
                                  extra_variables=None) -> Dict[str, str]:
    """每章装配指纹：只由该章**实际引用**的模块版本/槽位参数决定。

    - 没有模块指令的章节返回 ``""``，因此模块变化不会让它们失效；
    - 有指令的章节把每个槽位的 ``moduleId@version``、该模块内容/资源指纹与
      槽位参数一起哈希，模块或变量变化只失效真正依赖它的章节。
    """
    from doc_tool.application.content import module_refs

    root = Path(project_root)
    if library is None:
        try:
            from doc_tool.application.content.modules import ModuleLibrary, project_module_root

            library = ModuleLibrary(project_module_root(root))
        except Exception:  # noqa: BLE001 - 模块库不可用时只按槽位声明计算指纹
            library = None
    variables = dict(extra_variables or {})
    result: Dict[str, str] = {}
    for rel_path, text in (chapters or {}).items():
        key = str(rel_path).replace("\\", "/")
        try:
            scan = module_refs.scan_directives(str(text or ""))
            slots = list(getattr(scan, "slots", None) or [])
        except Exception:  # noqa: BLE001 - 指令解析失败按“无模块依赖”处理
            slots = []
        if not slots:
            result[key] = ""
            continue
        parts: List[str] = []
        for slot in slots:
            module = None
            if library is not None:
                try:
                    module = library.get(str(getattr(slot, "moduleId", "")), str(getattr(slot, "version", "")))
                except Exception:  # noqa: BLE001 - 单个模块缺失不阻断其它槽位
                    module = None
            params = dict(getattr(slot, "params", None) or {})
            for name in list(params):
                if name in variables:
                    params[name] = variables[name]
            parts.append("|".join([
                str(getattr(slot, "slotId", "")), str(getattr(slot, "moduleId", "")),
                str(getattr(slot, "version", "")), module_fingerprint(module),
                json.dumps(params, sort_keys=True, ensure_ascii=False),
            ]))
        result[key] = hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()
    return result


def default_cache_path(content_root) -> Optional[Path]:
    """项目内缓存位置：``<project>/.state/cache/content-index-v1.json``。"""
    root = Path(content_root)
    if root.parent.name == "content":
        return root.parent.parent / ".state" / "cache" / CACHE_NAME
    if root.is_dir():
        return root / ".state" / "cache" / CACHE_NAME
    return None


@dataclass
class CachedChapter:
    """一个文件的派生解析结果（不含业务身份）。"""

    digest: str = ""
    parser_version: str = PARSER_VERSION
    config_fingerprint: str = ""
    #: V3.6 36-C：缓存条目的捕获身份；同路径不同捕获不得互相复用。
    capture_id: str = ""
    line_count: int = 0
    lines: List[str] = field(default_factory=list)
    headings: List[Tuple[int, int, str, str]] = field(default_factory=list)
    size: int = 0
    mtime: float = 0.0
    used_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "digest": self.digest,
            "parserVersion": self.parser_version,
            "configFingerprint": self.config_fingerprint,
            "captureId": self.capture_id,
            "lineCount": self.line_count,
            "lines": list(self.lines),
            "headings": [list(item) for item in self.headings],
            "size": self.size,
            "mtime": self.mtime,
            "usedAt": self.used_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CachedChapter":
        headings = []
        for item in data.get("headings") or []:
            if isinstance(item, (list, tuple)) and len(item) >= 4:
                headings.append((int(item[0]), int(item[1]), str(item[2]), str(item[3])))
        lines = [str(line) for line in (data.get("lines") or [])]
        return cls(
            digest=str(data.get("digest", "") or ""),
            parser_version=str(data.get("parserVersion", "") or ""),
            config_fingerprint=str(data.get("configFingerprint", "") or ""),
            capture_id=str(data.get("captureId", "") or ""),
            line_count=int(data.get("lineCount", len(lines)) or 0),
            lines=lines,
            headings=headings,
            size=int(data.get("size", 0) or 0),
            mtime=float(data.get("mtime", 0.0) or 0.0),
            used_at=float(data.get("usedAt", 0.0) or 0.0),
        )


class ChapterCache:
    """项目级派生索引缓存（可关闭、可损坏重建、可清理）。"""

    def __init__(self, path=None, *, enabled: bool = True,
                 parser_version: str = PARSER_VERSION,
                 max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self.path = Path(path) if path is not None else None
        self.enabled = bool(enabled)
        self.parser_version = str(parser_version)
        self.max_entries = max(1, int(max_entries))
        self.entries: Dict[str, CachedChapter] = {}
        self.hits = 0
        self.misses = 0
        self.warnings: List[str] = []
        self.loaded = False

    @classmethod
    def for_content_root(cls, content_root, *, enabled: bool = True,
                         max_entries: int = DEFAULT_MAX_ENTRIES) -> "ChapterCache":
        return cls(default_cache_path(content_root), enabled=enabled, max_entries=max_entries)

    # --- 读取 ---

    def load(self) -> dict:
        """读取缓存；损坏、版本不认识或不可读时返回原因并保持空缓存。"""
        self.loaded = True
        if not self.enabled or self.path is None or not Path(self.path).is_file():
            return {"ok": False, "rebuilt": False, "message": "缓存未启用或不存在，将直接读取源码。"}
        try:
            raw = Path(self.path).read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            self.warnings.append("缓存不可读（{0}），已按直接读取重建。".format(exc))
            self.entries = {}
            return {"ok": False, "rebuilt": True, "message": "缓存损坏，已忽略并重建。"}
        if not isinstance(data, dict) or int(data.get("cacheSchemaVersion", 0) or 0) != CACHE_SCHEMA_VERSION:
            self.warnings.append("缓存版本不认识，已忽略并重建。")
            self.entries = {}
            return {"ok": False, "rebuilt": True, "message": "缓存版本不认识，已忽略并重建。"}
        entries: Dict[str, CachedChapter] = {}
        for rel_path, payload in (data.get("entries") or {}).items():
            if not isinstance(payload, dict):
                continue
            entries[str(rel_path)] = CachedChapter.from_dict(payload)
        self.entries = entries
        return {"ok": True, "rebuilt": False, "message": "缓存已加载（{0} 项）。".format(len(entries))}

    # --- 命中 ---

    def get(self, rel_path: str, *, digest: str, config_fp: str,
            capture_id: str = "") -> Optional[CachedChapter]:
        if not self.enabled or not digest:
            self.misses += 1
            return None
        entry = self.entries.get(str(rel_path))
        if entry is None:
            self.misses += 1
            return None
        if (
            entry.digest != digest
            or entry.parser_version != self.parser_version
            or entry.config_fingerprint != config_fp
            or entry.capture_id != str(capture_id or "")
        ):
            self.misses += 1
            return None
        entry.used_at = time.time()
        self.hits += 1
        return entry

    def put(self, rel_path: str, entry: CachedChapter) -> None:
        if not self.enabled:
            return
        entry.parser_version = self.parser_version
        entry.used_at = time.time()
        self.entries[str(rel_path)] = entry

    def drop(self, rel_path: str) -> None:
        self.entries.pop(str(rel_path), None)

    def sync_paths(self, current: Iterable[str]) -> int:
        """删除已不存在文件的缓存项（新增/删除/移动后保持一致）。"""
        known = {str(item) for item in current}
        removed = [key for key in self.entries if key not in known]
        for key in removed:
            self.entries.pop(key, None)
        return len(removed)

    def prune(self) -> int:
        """容量清理：超出上限时按最近使用时间淘汰。"""
        if len(self.entries) <= self.max_entries:
            return 0
        ordered = sorted(self.entries.items(), key=lambda item: item[1].used_at or 0.0)
        removed = 0
        for key, _entry in ordered[: len(self.entries) - self.max_entries]:
            self.entries.pop(key, None)
            removed += 1
        return removed

    # --- 写入 ---

    def save(self) -> dict:
        """原子写缓存；失败只返回诊断，不影响业务结果。"""
        if not self.enabled or self.path is None:
            return {"ok": False, "message": "缓存未启用，未写入。"}
        pruned = self.prune()
        payload = {
            "cacheSchemaVersion": CACHE_SCHEMA_VERSION,
            "parserVersion": self.parser_version,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "entries": {key: entry.to_dict() for key, entry in self.entries.items()},
        }
        target = Path(self.path)
        if target.exists() and target.is_dir():
            message = "缓存写入失败（目标是目录，已忽略）：{0}：继续直接读取源码。".format(target)
            self.warnings.append(message)
            return {"ok": False, "message": message}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            try:
                tmp.replace(target)
            except OSError:
                shutil.move(str(tmp), str(target))
        except OSError as exc:
            message = "缓存写入失败（{0}）：继续直接读取源码。".format(exc)
            self.warnings.append(message)
            return {"ok": False, "message": message, "pruned": pruned}
        return {
            "ok": True, "pruned": pruned, "entries": len(self.entries),
            "message": "缓存已写入（{0} 项{1}）。".format(
                len(self.entries), "，清理 {0} 项".format(pruned) if pruned else "",
            ),
        }

    def clear(self) -> bool:
        """删除缓存文件（用户可随时清理派生数据）。"""
        self.entries = {}
        if self.path is None:
            return False
        try:
            Path(self.path).unlink()
            return True
        except OSError:
            return False

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "path": str(self.path or ""),
            "entries": len(self.entries),
            "hits": self.hits,
            "misses": self.misses,
            "warnings": list(self.warnings),
        }


def capture_index_service(content_root, *, capture_id: str, override_texts=None,
                          project_root=None, max_entries: int = DEFAULT_MAX_ENTRIES,
                          per_file_fingerprint=None):
    """构造“本轮捕获”作用域的内容索引服务（V3.6 36-C 3.1）。

    - 缓存条目按 ``captureId`` 隔离：同路径不同捕获不得互相复用；
    - ``override_texts`` 里的章节（未保存缓冲/变体展开）只用内存文本与真实摘要，
      既不再读磁盘旧内容，也不写入持久缓存；
    - 其余未变章节仍可命中同一捕获下的缓存，避免重复解析。
    """
    from doc_tool.application.content.index import ContentIndexService

    cache_path = default_cache_path(content_root) if project_root is not None else None
    cache = ChapterCache(cache_path, enabled=cache_path is not None, max_entries=max_entries)
    fingerprint = config_fingerprint(project_root) if project_root is not None else ""
    return ContentIndexService(
        content_root, cache=cache, config_fingerprint=fingerprint,
        capture_id=str(capture_id or ""), override_texts=dict(override_texts or {}),
        per_file_fingerprint=per_file_fingerprint,
    )


@dataclass
class CaptureIndex:
    """按 captureId 隔离的内存索引：未保存缓冲使用本轮真实摘要，不混用磁盘旧内容。"""

    capture_id: str = ""
    entries: Dict[str, str] = field(default_factory=dict)  # rel_path -> 文本摘要

    def put(self, rel_path: str, text: str) -> str:
        digest = text_digest(text)
        self.entries[str(rel_path)] = digest
        return digest

    def digest_for(self, rel_path: str) -> str:
        return self.entries.get(str(rel_path), "")

    def to_dict(self) -> dict:
        return {"captureId": self.capture_id, "files": len(self.entries)}
