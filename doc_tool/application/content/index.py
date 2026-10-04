# -*- coding: utf-8 -*-
"""内容索引构建与增量维护服务。

一次扫描 ``content_root``（即 ``content/<类型>`` 的父目录）下全部 .md，
构建行索引、标题清单与文档类型集合。引用索引（``FileReference``）由
``doc_tool.application.content.references`` 在上层填充。

索引键统一为相对 contentRoot 的 POSIX 风格 rel_path。

增量维护：写路径（编辑器保存/全局替换/重命名联动）在改动后调用
``ContentIndex.invalidate(rel_path)``；搜索/引用/术语操作前调用
``refresh_dirty`` 重建失效文件，避免展示过期内容。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

from doc_tool.application.content import incremental_index as incremental
from doc_tool.domain.content_index import ContentIndex, FileEntry, HeadingEntry
from doc_tool.domain.cancellation import CancellationToken

# 识别为内容文件的扩展名。
MD_SUFFIXES = (".md", ".markdown")

# 内容索引收录的文档类型目录（contentRoot 直接子目录）。
KNOWN_DOCUMENT_TYPES = ("requirement", "design", "general")

# 标题行匹配：行首 1-6 个 # 后跟空白。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# 锚点 slug 中允许保留的字符：ASCII 字母数字与 CJK 统一表意文字。
_KEEP_RE = re.compile(r"[^\w\s一-鿿]+", re.UNICODE)
_SPACES_RE = re.compile(r"\s+")


def slugify_heading(text: str) -> str:
    """标题文本生成 GitHub 风格锚点 id（CJK 保留、标点丢弃、空白折叠为连字符）。

    生成与匹配使用同一函数，保证工具内锚点链接自洽；不追求与
    GitHub/Word 完全一致的 slug（精确渲染属于 build 产物范畴）。
    """
    lowered = text.lower()
    kept = _KEEP_RE.sub("", lowered)
    slug = _SPACES_RE.sub("-", kept).strip("-")
    return slug or "section"


def infer_document_type(rel_path: str) -> str:
    """从 rel_path 首段推断文档类型；无法识别时回退 general。"""
    first = rel_path.split("/", 1)[0]
    if first in ("requirement", "design", "general"):
        return first
    return "general"


class ContentIndexService:
    """内容索引服务：构建、增量重建、失效刷新。"""

    def __init__(self, content_root: Path, *, cache=None, config_fingerprint: str = "",
                 capture_id: str = "", override_texts=None,
                 per_file_fingerprint=None) -> None:
        """``cache`` 为可选派生缓存（V3.6）：不传时行为与无缓存完全一致。

        V3.6 36-C 3.1：``capture_id`` 让缓存条目按捕获隔离；``override_texts``
        提供本轮捕获的内存文本（未保存缓冲/变体展开），这些章节只用内存真实摘要，
        既不再读磁盘、也不写持久缓存。
        """
        self._content_root: Path = Path(content_root).resolve()
        self._cache = cache
        self._config_fingerprint = str(config_fingerprint or "")
        self._capture_id = str(capture_id or "")
        self._override_texts = {str(key).replace("\\", "/"): str(value) for key, value in (override_texts or {}).items()}
        #: V3.6 36-C 3.2：按文件装配指纹（模块/变量依赖），未给出的文件用全局配置指纹。
        self._per_file_fingerprint = {
            str(key).replace("\\", "/"): str(value)
            for key, value in (per_file_fingerprint or {}).items()
        }
        self.capture_paths: set = set()
        #: 本次服务实例中「真正解析」与「缓存/摘要命中」的文件次数（性能观测用）。
        self.parse_count = 0
        self.reuse_count = 0
        self._digests: dict = {}
        self._cache_loaded = False
        # 布局 B（content_root 本身就是文档类型目录，如 content/requirement）时，
        # 用目录名作为默认文档类型；布局 A（父目录含类型子目录）由首段推断。
        self._default_doc_type = (
            self._content_root.name
            if self._content_root.name in KNOWN_DOCUMENT_TYPES
            else "general"
        )

    @property
    def content_root(self) -> Path:
        return self._content_root

    # --- 发现与读取 ---

    def discover_files(self) -> List[Tuple[str, Path]]:
        """返回 [(rel_path, absolute_path)]，稳定排序。

        兼容两种内容布局：
        - A：contentRoot 下是文档类型子目录（content/ 含 requirement/design/general），
          仅收录类型子目录内的 .md，避免 assets 等非内容目录误入。
        - B：contentRoot 本身就是文档类型目录（content/requirement 直接含章节），
          直接递归收录其下所有 .md（章节目录自然形成树层级）。
        """
        result: List[Tuple[str, Path]] = []
        if not self._content_root.exists():
            return result
        type_dirs = sorted(
            child
            for child in self._content_root.iterdir()
            if child.is_dir() and child.name in KNOWN_DOCUMENT_TYPES
        )
        # 布局 A 以类型子目录为根；布局 B 以 content_root 自身为根。
        roots = type_dirs if type_dirs else [self._content_root]
        # V4.2 42-B 实测：改成 `rglob("*")` + Python 侧筛后缀反而更慢
        # （1000 章 cold discover 149ms → 244ms，因为对每个目录项都做了一次
        # Python 层判断），因此保留“按后缀 rglob”这一由解释器 C 层过滤的实现。
        # 结论来自 analysis/v42/measure-staged.json，不凭直觉优化。
        for base in roots:
            for suffix in MD_SUFFIXES:
                for file_path in base.rglob("*" + suffix):
                    rel_parts = file_path.relative_to(base).parts[:-1]
                    if any(p.startswith(".") or p in ("node_modules", "output", "logs") for p in rel_parts):
                        continue
                    rel = file_path.relative_to(self._content_root).as_posix()
                    result.append((rel, file_path))
        result.sort(key=lambda item: item[0])
        return result

    def _doc_type_of(self, rel_path: str) -> str:
        """推断文档类型：优先取 rel_path 首段（布局 A），否则用类型目录名（布局 B）。"""
        first = rel_path.split("/", 1)[0]
        if first in KNOWN_DOCUMENT_TYPES:
            return first
        return self._default_doc_type

    def read_lines(self, file_path: Path) -> List[str]:
        """读取 .md 为行列表；读取失败视为空（由调用方决定是否保留索引）。"""
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return []
        return text.splitlines()

    # --- 构建 ---

    def build(
        self,
        cancel_token: Optional[CancellationToken] = None,
        *,
        save_cache: bool = True,
        on_progress=None,
        progress_every: int = 25,
    ) -> ContentIndex:
        """全量扫描 contentRoot 构建索引。可传入取消令牌在文件边界安全中断。

        V3.6 36-B：启用派生缓存时，内容摘要 + 解析器版本 + 配置指纹一致的文件
        直接复用之前解析出的行与标题，不再重复解析；缓存不可用时行为不变。

        V3.6 36-D：``on_progress(scanned, total)`` 按 ``progress_every`` 个文件回报
        进度（只含计数），供界面在扫描中显示“已解析 N/M 章节”而不是假总数。
        """
        index = ContentIndex()
        files = self.discover_files()
        self._ensure_cache_loaded()
        if self._cache is not None:
            self._cache.sync_paths(rel for rel, _path in files)
        total = len(files)
        interval = max(1, int(progress_every))
        for position, (rel_path, file_path) in enumerate(files, start=1):
            if cancel_token is not None:
                cancel_token.check_cancel()
            self._index_file(index, rel_path, file_path)
            if on_progress is not None and (position % interval == 0 or position >= total):
                on_progress(position, total)
        index.document_types = {
            self._doc_type_of(rel) for rel in index.files.keys()
        }
        if save_cache and self._cache is not None:
            self._cache_result = self._cache.save()
        return index

    def _ensure_cache_loaded(self) -> None:
        if self._cache is None or self._cache_loaded:
            return
        self._cache.load()
        self._cache_loaded = True

    def stats(self) -> dict:
        """性能观测：解析/复用次数与缓存统计（不含正文）。"""
        payload = {
            "parseCount": self.parse_count,
            "reuseCount": self.reuse_count,
            "files": len(self._digests),
            "captureId": self._capture_id,
            "captureFiles": len(self.capture_paths),
        }
        if self._cache is not None:
            payload["cache"] = self._cache.stats()
        return payload

    def rebuild_file(self, index: ContentIndex, rel_path: str) -> None:
        """重建单个文件索引（含删除场景：文件消失则移除条目）。"""
        file_path = self._resolve(rel_path)
        if not file_path or not file_path.exists():
            index.files.pop(rel_path, None)
            index.lines.pop(rel_path, None)
            index.headings.pop(rel_path, None)
            index.references.pop(rel_path, None)
        else:
            self._index_file(index, rel_path, file_path)
        index.refresh(rel_path)

    def refresh_dirty(self, index: ContentIndex) -> None:
        """重建全部失效文件；无效文件被移除条目。"""
        for rel_path in sorted(index.invalid_files):
            self.rebuild_file(index, rel_path)

    def refresh(self, index: ContentIndex) -> int:
        """增量重扫：新增/删除/变更文件，重建内容条目并返回文件总数。

        V3.6 36-B：**先按内容摘要确认是否真的变化**（mtime/size 只作初筛提示，
        正确性来自摘要），未变化的文件不再重复解析；摘要缺失时按变化处理，
        保证正确性优先于命中率。非破坏性：不影响引用索引（由调用方重扫）。
        """
        current = dict(self.discover_files())
        removed = [rel for rel in list(index.files.keys()) if rel not in current]
        for rel_path in removed:
            index.files.pop(rel_path, None)
            index.lines.pop(rel_path, None)
            index.headings.pop(rel_path, None)
            index.references.pop(rel_path, None)
            index.refresh(rel_path)
            self._digests.pop(rel_path, None)
            if self._cache is not None:
                self._cache.drop(rel_path)
        self._ensure_cache_loaded()
        if self._cache is not None:
            self._cache.sync_paths(current.keys())
        for rel_path, file_path in current.items():
            digest = incremental.content_digest(file_path)
            known = self._digests.get(rel_path, "")
            if index.files.get(rel_path) is not None and digest and digest == known:
                self.reuse_count += 1
                continue
            self._index_file(index, rel_path, file_path, digest=digest)
        index.document_types = {
            self._doc_type_of(rel) for rel in index.files.keys()
        }
        if self._cache is not None:
            self._cache.save()
        return len(index.files)

    def _resolve(self, rel_path: str) -> Optional[Path]:
        """把 rel_path 解析为绝对路径；越出 contentRoot 返回 None。"""
        target = (self._content_root / rel_path).resolve()
        try:
            target.relative_to(self._content_root)
        except ValueError:
            return None
        return target

    def _fingerprint_for(self, rel_path: str) -> str:
        """该文件的失效键：有装配指纹时用它，否则用全局配置指纹。"""
        if not self._per_file_fingerprint:
            return self._config_fingerprint
        specific = self._per_file_fingerprint.get(str(rel_path).replace("\\", "/"), "")
        if specific:
            return "{0}+{1}".format(self._config_fingerprint, specific)
        return self._config_fingerprint

    def _index_lines(self, index: ContentIndex, rel_path: str, lines) -> None:
        """用给定行内容建立 FileEntry + lines + headings（不读盘）。"""
        line_list = list(lines)
        entry = FileEntry(
            rel_path=rel_path,
            document_type=self._doc_type_of(rel_path),
            line_count=len(line_list),
        )
        headings: List[HeadingEntry] = []
        for line_no, line in enumerate(line_list, start=1):
            match = _HEADING_RE.match(line)
            if match is None:
                continue
            text = match.group(2)
            headings.append(HeadingEntry(
                rel_path=rel_path, line_no=line_no, level=len(match.group(1)),
                text=text, anchor_id=slugify_heading(text),
            ))
        index.files[rel_path] = entry
        index.lines[rel_path] = line_list
        index.headings[rel_path] = headings
        index.refresh(rel_path)
        index.document_types.add(entry.document_type)

    def _index_file(self, index: ContentIndex, rel_path: str, file_path: Path,
                    *, digest: str = "") -> None:
        """为单个文件构建 FileEntry + lines + headings，并入索引。

        命中派生缓存时直接复用行与标题（内容摘要一致），否则真实解析。
        """
        override = self._override_texts.get(str(rel_path).replace("\\", "/"))
        if override is not None:
            # 本轮捕获的内存文本：摘要是真实内容的摘要，不读盘、不命中/写入缓存。
            self.capture_paths.add(str(rel_path))
            self.parse_count += 1
            self._index_lines(index, rel_path, override.splitlines())
            self._digests[rel_path] = incremental.text_digest(override)
            return
        resolved_digest = digest or incremental.content_digest(file_path)
        cached = None
        if self._cache is not None:
            self._ensure_cache_loaded()
            cached = self._cache.get(
                rel_path, digest=resolved_digest,
                config_fp=self._fingerprint_for(rel_path),
                capture_id=self._capture_id,
            )
        if cached is not None:
            self.reuse_count += 1
            entry = FileEntry(
                rel_path=rel_path,
                document_type=self._doc_type_of(rel_path),
                line_count=cached.line_count,
            )
            headings = [
                HeadingEntry(
                    rel_path=rel_path, line_no=line_no, level=level,
                    text=text, anchor_id=anchor,
                )
                for line_no, level, text, anchor in cached.headings
            ]
            index.files[rel_path] = entry
            index.lines[rel_path] = list(cached.lines)
            index.headings[rel_path] = headings
            index.refresh(rel_path)
            index.document_types.add(entry.document_type)
            self._digests[rel_path] = resolved_digest
            return
        self.parse_count += 1
        lines = self.read_lines(file_path)
        entry = FileEntry(
            rel_path=rel_path,
            document_type=self._doc_type_of(rel_path),
            line_count=len(lines),
        )
        headings: List[HeadingEntry] = []
        for line_no, line in enumerate(lines, start=1):
            match = _HEADING_RE.match(line)
            if match is None:
                continue
            level = len(match.group(1))
            text = match.group(2)
            headings.append(
                HeadingEntry(
                    rel_path=rel_path,
                    line_no=line_no,
                    level=level,
                    text=text,
                    anchor_id=slugify_heading(text),
                )
            )
        index.files[rel_path] = entry
        index.lines[rel_path] = lines
        index.headings[rel_path] = headings
        index.refresh(rel_path)
        index.document_types.add(entry.document_type)
        self._digests[rel_path] = resolved_digest
        if self._cache is not None:
            try:
                stat = file_path.stat()
            except OSError:
                stat = None
            self._cache.put(rel_path, incremental.CachedChapter(
                digest=resolved_digest,
                config_fingerprint=self._fingerprint_for(rel_path),
                capture_id=self._capture_id,
                line_count=len(lines),
                lines=list(lines),
                headings=[
                    (item.line_no, item.level, item.text, item.anchor_id) for item in headings
                ],
                size=int(stat.st_size) if stat is not None else 0,
                mtime=float(stat.st_mtime) if stat is not None else 0.0,
            ))
