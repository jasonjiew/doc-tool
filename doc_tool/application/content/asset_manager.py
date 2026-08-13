# -*- coding: utf-8 -*-
"""图片资源管理纯服务：命名、导入、未使用扫描与缺失清单。

图片资产位于 ``assets/<类型>/images/``，命名延续导入链路既有 ``img_NNNN.ext``
序列（见 ``doc_tool.adapters.importer``）。本模块提供：

- ``next_image_name``：按类型独立分配下一个 ``img_NNNN.ext``，扫描 images
  目录与 ``image-map.yml`` 计数器，保证不覆盖既有资源。
- ``import_image_data``：写入图片文件并用 PIL 校验/读尺寸，返回插入引用
  所需的 ``images/<名>`` 相对路径与像素尺寸。
- ``scan_unused``：复用 ``ReferenceScanner`` 的引用差集，列出未被任何
  Markdown 引用的图片（供清理面板）。
- ``list_missing``：列出引用存在但文件不存在的悬空图片引用。

写入侧不负责"安全删除/回滚"——清理走 ``ContentWriter.delete_file`` 的回收站
语义（见 ``assets/`` 路径白名单处理）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# 既有 img_NNNN 命名（导入链路生成的资源）。
_IMG_NAME_RE = re.compile(r"^img_(\d+)\.[A-Za-z0-9]+$")
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


@dataclass(frozen=True)
class MissingImage:
    """一条悬空图片引用：源文件 + 行号 + 缺失文件名。"""

    source: str  # 引用来源文件（相对 contentRoot）
    line: int  # 1-based
    text: str  # 引用所在行原文
    target: str  # 引用目标（如 images/img_0001.png）


def images_dir(assets_root, doc_type: str) -> Path:
    """``assets/<类型>/images/`` 目录。"""
    return Path(assets_root) / doc_type / "images"


def _max_sequence_in_dir(images: Path) -> int:
    """扫描目录内 img_NNNN 文件的最大序号；无则 0。"""
    maximum = 0
    try:
        for child in images.iterdir():
            match = _IMG_NAME_RE.match(child.name)
            if match is not None:
                maximum = max(maximum, int(match.group(1)))
    except OSError:
        pass
    return maximum


def _max_sequence_in_map(assets_root, doc_type: str) -> int:
    """解析 ``image-map.yml`` 的 images 列表取最大序号。"""
    import yaml

    map_path = Path(assets_root) / doc_type / "image-map.yml"
    maximum = 0
    try:
        data = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return maximum
    if not isinstance(data, dict):
        return maximum
    for entry in data.get("images", []) or []:
        if not isinstance(entry, dict):
            continue
        match = _IMG_NAME_RE.match(Path(str(entry.get("file", ""))).name)
        if match is not None:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def next_image_name(
    assets_root, doc_type: str, ext: str = "png"
) -> str:
    """返回下一个 ``img_NNNN.<ext>``（不覆盖既有资源，按类型独立计数）。

    ``ext`` 不带点；目录扫描与 image-map.yml 计数器取较大者作为当前序号，
    递增后若仍与既有文件冲突则继续自增。
    """
    extension = (ext or "png").lstrip(".")
    images = images_dir(assets_root, doc_type)
    sequence = max(
        _max_sequence_in_dir(images),
        _max_sequence_in_map(assets_root, doc_type),
    )
    candidate = sequence
    while True:
        candidate += 1
        name = "img_{0:04d}.{1}".format(candidate, extension)
        if not (images / name).exists():
            return name


def import_image_data(
    data: bytes,
    assets_root,
    doc_type: str,
    ext: str = "png",
) -> Tuple[str, Optional[int], Optional[int]]:
    """把图片字节写入资源目录，PIL 校验并读像素尺寸。

    返回 ``(rel_target, width_px, height_px)``；``rel_target`` 形如
    ``images/img_NNNN.png``（供插入 Markdown 引用）。无法从 PIL 获得有效
    尺寸时 ``width_px/height_px`` 为 None（引用省略尺寸后缀）。
    """
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    name = next_image_name(assets_root, doc_type, ext)
    images = images_dir(assets_root, doc_type)
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    try:
        # 先在内存中完整解码，避免损坏/伪装图片在资源目录留下半写入文件。
        with Image.open(BytesIO(data)) as image:
            image.load()
            width_px, height_px = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("无效图片数据") from exc

    images.mkdir(parents=True, exist_ok=True)
    target = images / name
    target.write_bytes(data)
    rel_target = "images/{0}".format(name)
    return rel_target, width_px, height_px


def _referenced_image_paths(index) -> set:
    """收集 ``(文档类型, Markdown 图片目标)``，避免跨类型同名串扰。"""
    referenced: set = set()
    for source, refs in index.references.items():
        entry = index.files.get(source)
        doc_type = entry.document_type if entry is not None else "general"
        for ref in refs:
            if ref.kind == "image":
                referenced.add((doc_type, ref.target.split()[0]))
    return referenced


def scan_unused(assets_root, index) -> List[Tuple[str, int]]:
    """列出未被任何 Markdown 引用的图片：``[(rel_target, size_bytes)]``。

    ``rel_target`` 形如 ``requirement/images/img_NNNN.png``（相对 assets/）。
    被引用项不在清单中，避免误删。
    """
    referenced = _referenced_image_paths(index)
    unused: List[Tuple[str, int]] = []
    for doc_type in sorted(index.document_types):
        images = images_dir(assets_root, doc_type)
        if not images.is_dir():
            continue
        try:
            children = sorted(images.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_file() or child.suffix.lower() not in _IMAGE_EXTENSIONS:
                continue
            # 引用侧同时支持 ``images/<name>`` 与裸名 ``<name>`` 两种形态
            # （``_resolve_image`` 两种都解析），扫描侧须两种都比对，否则
            # 裸名引用的图片会被误判未使用而从清理面板误删。
            target = "images/{0}".format(child.name)
            if (doc_type, target) in referenced or (doc_type, child.name) in referenced:
                continue
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            unused.append(("{0}/{1}".format(doc_type, target), size))
    return unused


def list_missing(index, assets_root) -> List[MissingImage]:
    """列出引用存在但文件缺失的图片（复用引用悬空检测）。"""
    missing: List[MissingImage] = []
    for refs in index.references.values():
        for ref in refs:
            if ref.kind == "image" and ref.dangling:
                missing.append(
                    MissingImage(
                        source=ref.source,
                        line=ref.source_line,
                        text=ref.source_text,
                        target=ref.target,
                    )
                )
    return missing


def resolve_asset_path(assets_root, doc_type: str, target: str) -> Path:
    """把 Markdown 引用目标（images/xxx.png）解析为 assets 下绝对路径。

    优先 ``assets/<类型>/<target>``；目标不合法（含 .. 越界）时返回空 Path。
    """
    base = (Path(assets_root) / doc_type).resolve()
    candidate = (base / target).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return Path("")
    return candidate
