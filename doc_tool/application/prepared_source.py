# -*- coding: utf-8 -*-
"""构建期内容预处理（V2.7 任务 3.1～3.3 / 设计 D2）。

`PreparedSource` 是构建管线的 ``STAGE_PREPARE``：把 Markdown 里的
Mermaid 围栏在**任务临时目录**里离线渲染成图片引用，并把缓存与来源记录
带回构建阶段。

三条硬约束：

1. 预处理只写任务临时目录与用户缓存目录，绝不改写源 Markdown、用户资产
   或模板。
2. 每个生成图都记录来源 ``SourceLocation``（原 ``.md`` 文件 + 行号）与缓存
   命中情况，报告里定位到原文件而不是临时路径。
3. 渲染失败/超时/取消都走兜底：默认用同源码有效缓存，其次输出源码说明
   继续出稿并 warning；只有用户显式取消才结束本任务。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.domain.blocks import (
    KIND_CODE,
    CodeBlock,
    ParsedDocument,
    SourceLocation,
    parse_blocks,
)

#: 正文展开失败事实（V3.0 3.4）：供调用方在报告中说明，不改变既有返回结构。
_RESOLVE_FAILURES: List[Dict[str, str]] = []


#: 缓存格式版本；渲染参数或输出结构变化时必须递增，避免复用旧语义结果。
CACHE_FORMAT_VERSION = "v1"

#: 单图渲染超时（秒）；超时走缓存/源码兜底。
RENDER_TIMEOUT_SECONDS = 120

#: 渲染参数（与 mermaid.render 的图语义相关）：尺寸/主题/背景。
RENDER_PARAMS = {
    "scale": 3.0,
    "background": "white",
    "theme": "default",
}

#: 本版承诺支持的图种子集；其余图种即使本机 mmdc 可用也不自动承诺支持。
SUPPORTED_KINDS = ("flowchart", "sequenceDiagram")

#: 不支持的图种说明（默认兜底：输出源码 + 说明，继续出稿）。
UNSUPPORTED_HINT = (
    "本版正式稿只承诺 flowchart / sequenceDiagram 的支持子集；"
    "该图已按源码说明输出，可在编辑器 Mermaid 工作台单独导出后手工替换。"
)


class CancelledError(RuntimeError):
    """用户显式取消当前任务。"""


@dataclass
class GeneratedAsset:
    """一个由预处理生成的图片资产。"""

    location: SourceLocation
    kind: str
    source_text: str
    cache_key: str
    image_path: str = ""
    relative_path: str = ""
    width_px: int = 0
    height_px: int = 0
    backend: str = ""
    from_cache: bool = False
    fallback: str = ""
    message: str = ""

    def to_report(self) -> Dict[str, object]:
        return {
            "path": self.location.path,
            "line": self.location.start_line,
            "kind": self.kind,
            "cacheKey": self.cache_key,
            "relativePath": self.relative_path,
            "backend": self.backend,
            "fromCache": self.from_cache,
            "fallback": self.fallback,
            "message": self.message,
        }


@dataclass
class PreparedSource:
    """一份 Markdown 的预处理结果。

    ``prepared_path`` 是预处理后的临时文件（没有图时等于
    源文件路径），``asset_root`` 是生成图所在的临时资源目录。
    源文件始终只读，不会被改写。
    """

    source_path: str
    prepared_path: str = ""
    asset_root: str = ""
    temp_dir: str = ""
    prepared_text: str = ""
    assets: List[GeneratedAsset] = field(default_factory=list)
    warnings: List[Dict[str, object]] = field(default_factory=list)
    parse_warnings: List[Dict[str, object]] = field(default_factory=list)
    skipped: List[Dict[str, object]] = field(default_factory=list)
    cancelled: bool = False
    owns_temp_dir: bool = True

    @property
    def images(self) -> int:
        return sum(1 for asset in self.assets if asset.image_path)

    def cleanup(self) -> None:
        """删除任务临时目录；用户缓存目录不在这里清理。"""
        if self.owns_temp_dir and self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __enter__(self) -> "PreparedSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def read_prepared_text(self) -> str:
        """读取预处理后的文本；不可读时回退到已保存的文本。"""
        if self.prepared_path and self.prepared_path != self.source_path:
            try:
                with open(self.prepared_path, encoding="utf-8") as handle:
                    return handle.read()
            except (OSError, UnicodeError):
                return self.prepared_text
        return self.prepared_text

    def to_report(self) -> Dict[str, object]:
        return {
            "source": self.source_path,
            "assets": [asset.to_report() for asset in self.assets],
            "warnings": list(self.warnings),
            "parseWarnings": list(self.parse_warnings),
            "skipped": list(self.skipped),
            "cancelled": self.cancelled,
        }


def default_cache_root() -> Path:
    """用户缓存根目录（可用 DOC_TOOL_CACHE_DIR 覆盖，便于测试与便携包）。"""
    override = os.environ.get("DOC_TOOL_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".doctool" / "cache" / "mermaid"


def compute_cache_key(
    source: str,
    kind: str,
    *,
    renderer_version: str = "",
    params: Optional[Dict[str, object]] = None,
) -> str:
    """SHA-256 缓存键：源码 + 图种 + 渲染器版本 + 尺寸/主题参数。"""
    payload = {
        "format": CACHE_FORMAT_VERSION,
        "source": source.replace("\r\n", "\n").strip(),
        "kind": kind,
        "rendererVersion": renderer_version,
        "params": dict(params or RENDER_PARAMS),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _renderer_version() -> str:
    """渲染器版本：内置渲染器固定标识，CLI 存在时附加 mmdc 版本标识。"""
    try:
        from doc_tool.application.content import mermaid

        if mermaid.cli_available():
            return "builtin+cli"
    except Exception:  # noqa: BLE001 - 版本探测失败不能阻断预处理
        return "builtin"
    return "builtin"


def _detect_kind(source: str) -> str:
    try:
        from doc_tool.application.content.mermaid import detect_kind

        return detect_kind(source) or ""
    except Exception:  # noqa: BLE001
        lowered = source.strip().splitlines()
        if not lowered:
            return ""
        head = lowered[0].strip().lower()
        if head.startswith("sequencediagram"):
            return "sequenceDiagram"
        if head.startswith("flowchart") or head.startswith("graph"):
            return "flowchart"
        return ""


@dataclass
class _CacheHit:
    png: bytes
    width: int
    height: int
    backend: str
    meta: Dict[str, object]


def read_cache(cache_root: Path, cache_key: str) -> Optional[_CacheHit]:
    """读取一个有效缓存项；缺失/损坏都返回 None（不抛异常）。"""
    png_path = cache_root / (cache_key + ".png")
    meta_path = cache_root / (cache_key + ".json")
    if not png_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return None
        if meta.get("format") != CACHE_FORMAT_VERSION:
            return None
        data = png_path.read_bytes()
        if not data:
            return None
        if meta.get("sha256") and hashlib.sha256(data).hexdigest() != meta["sha256"]:
            return None
        width = int(meta.get("width") or 0)
        height = int(meta.get("height") or 0)
        if width <= 0 or height <= 0:
            return None
        return _CacheHit(
            png=data,
            width=width,
            height=height,
            backend=str(meta.get("backend") or "builtin"),
            meta=meta,
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return None


def write_cache(
    cache_root: Path,
    cache_key: str,
    *,
    png: bytes,
    width: int,
    height: int,
    backend: str,
    kind: str,
    source: str,
    params: Optional[Dict[str, object]] = None,
) -> None:
    """写入缓存；失败只影响复用效率，不阻断构建。"""
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / (cache_key + ".png")).write_bytes(png)
        meta = {
            "format": CACHE_FORMAT_VERSION,
            "key": cache_key,
            "kind": kind,
            "backend": backend,
            "width": width,
            "height": height,
            "params": dict(params or RENDER_PARAMS),
            "rendererVersion": _renderer_version(),
            "sha256": hashlib.sha256(png).hexdigest(),
            "sourceHint": source.strip().splitlines()[0][:120] if source.strip() else "",
        }
        (cache_root / (cache_key + ".json")).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return


#: 子进程标记：设为 1 时在当前进程内直接渲染（避免无限套开子进程）。
_RENDER_WORKER_ENV = "DOC_TOOL_MERMAID_WORKER"


def _qt_main_thread_available() -> bool:
    """当前线程能否安全创建/使用 Qt GUI 对象。

    已有 ``QGuiApplication`` 实例时，任何线程都可以做 QtSvg 栅格化；
    实例尚未创建时只能在主线程创建（否则原生崩溃）。
    """
    if os.environ.get(_RENDER_WORKER_ENV):
        return True
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception:  # noqa: BLE001 - 无 Qt 环境时走内置 SVG 回退
        return True
    if QGuiApplication.instance() is not None:
        return True
    import threading

    return threading.current_thread() is threading.main_thread()


def _render_in_worker_process(source: str, kind: str):
    """在专用子进程里渲染（子进程主线程拥有 Qt），超时后清理进程树。"""
    import json as _json
    import subprocess as _subprocess

    payload = _json.dumps({"source": source, "kind": kind}, ensure_ascii=False)
    env = os.environ.copy()
    env[_RENDER_WORKER_ENV] = "1"
    command = [sys.executable, "-c", _WORKER_CODE]
    try:
        completed = _subprocess.run(
            command,
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=RENDER_TIMEOUT_SECONDS,
            check=False,
        )
    except _subprocess.TimeoutExpired:
        # 超时由 run 结束子进程；子进程内部只做纯计算，不残留外部进程。
        return _WorkerFailure("Mermaid 渲染超时（{0} 秒）".format(RENDER_TIMEOUT_SECONDS))
    except (OSError, ValueError) as exc:
        return _WorkerFailure("无法启动渲染子进程：{0}".format(exc))
    try:
        data = _json.loads(completed.stdout or "{}")
    except ValueError:
        return _WorkerFailure(
            "渲染子进程未返回可读结果：{0}".format(
                (completed.stderr or "").strip()[-200:]
            )
        )
    if not data.get("ok"):
        return _WorkerFailure(str(data.get("error") or "渲染子进程失败"))
    return _WorkerSuccess(
        png=bytes.fromhex(data["png"]),
        width=int(data.get("width") or 0),
        height=int(data.get("height") or 0),
        backend=str(data.get("backend") or "worker"),
    )


class _WorkerFailure:
    def __init__(self, error: str) -> None:
        self.error = error


class _WorkerSuccess:
    def __init__(self, png: bytes, width: int, height: int, backend: str) -> None:
        self.png = png
        self.width = width
        self.height = height
        self.backend = backend
        self.ok = True


_WORKER_CODE = """
import json, sys
payload = json.loads(sys.stdin.read() or "{}")
from doc_tool.application.content.mermaid import render
result = render(payload.get("source", ""), payload.get("kind", ""), use_cli=True, want_png=True)
out = {"ok": bool(getattr(result, "ok", False))}
if out["ok"] and getattr(result, "png", None):
    out["png"] = result.png.hex()
    out["width"] = int(getattr(result, "width", 0) or 0)
    out["height"] = int(getattr(result, "height", 0) or 0)
    out["backend"] = str(getattr(result, "backend", "") or "worker")
else:
    out["error"] = str(getattr(result, "error", "") or "renderer failed")
sys.stdout.write(json.dumps(out))
"""


def _default_renderer(source: str, kind: str):
    from doc_tool.application.content.mermaid import render

    return render(source, kind, use_cli=True, want_png=True)


def prepare_markdown(
    path: str,
    *,
    temp_root: Optional[str] = None,
    cache_root: Optional[Path] = None,
    renderer: Optional[Callable[[str, str], object]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    text: Optional[str] = None,
    asset_subdir: str = "assets",
    resolver: Optional[Callable[[str, str], str]] = None,
) -> PreparedSource:
    """把一份 Markdown 预处理成可构建的临时文件。

    Args:
        path: 源 Markdown 路径（只读，绝不改写）。
        temp_root: 临时目录父目录；为空时使用系统临时目录。
        cache_root: Mermaid 缓存根目录；为空时用 ``default_cache_root()``。
        renderer: 可注入的渲染函数（测试用），默认复用 ``mermaid.render``。
        cancel_check: 返回 True 表示用户已取消当前任务。
        text: 已读取的 Markdown 文本；为空时从 ``path`` 读取。
        resolver: 可选正文展开器 ``(path, text) -> text``（V3.0 固定模块引用）。
            在 Mermaid/资源预处理**之前**调用，保证预览/检查/Word/HTML 使用同一
            份展开内容；没有模块标记时实现方应原样返回，避免额外开销。
    """
    cache_dir = Path(cache_root) if cache_root else default_cache_root()
    if text is None:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeError) as exc:
            prepared = PreparedSource(source_path=path)
            prepared.warnings.append(
                {
                    "path": path,
                    "line": 0,
                    "rule": "markdown_unreadable",
                    "message": "Markdown 无法读取：{0}".format(exc),
                }
            )
            return prepared

    if resolver is not None:
        try:
            resolved_text = resolver(path, text)
        except Exception as exc:  # noqa: BLE001 - 展开失败保留原文，不阻断构建
            resolved_text = text
            _RESOLVE_FAILURES.append(
                {"path": path, "message": str(exc) or type(exc).__name__}
            )
        if isinstance(resolved_text, str) and resolved_text:
            text = resolved_text
    document = parse_blocks(text, path)
    prepared = PreparedSource(source_path=path)
    prepared.parse_warnings = [warning.to_dict() for warning in document.warnings]
    prepared.warnings.extend(prepared.parse_warnings)

    code_blocks = [block for block in document.blocks if block.kind == KIND_CODE and block.is_mermaid]
    if not code_blocks:
        # 没有需要预处理的图：保持原文，不建临时目录。
        prepared.prepared_text = text
        prepared.prepared_path = path
        prepared.asset_root = ""
        prepared.owns_temp_dir = False
        return prepared

    temp_dir = tempfile.mkdtemp(prefix="doc-tool-prepare-", dir=temp_root)
    prepared.temp_dir = temp_dir
    prepared.asset_root = str(Path(temp_dir) / asset_subdir)
    Path(prepared.asset_root).mkdir(parents=True, exist_ok=True)

    lines = text.split("\n")
    # 从后往前替换，保持前面块的行号不受影响。
    replacements: List[Tuple[int, int, List[str]]] = []
    for block in code_blocks:
        if cancel_check is not None and cancel_check():
            prepared.cancelled = True
            prepared.prepared_text = text
            prepared.prepared_path = path
            prepared.warnings.append(
                {
                    "path": path,
                    "line": block.location.start_line,
                    "rule": "prepare_cancelled",
                    "message": "用户取消：Mermaid 预处理已停止，保留原输入。",
                }
            )
            return prepared
        asset = _prepare_one(
            block,
            prepared,
            cache_dir=cache_dir,
            renderer=renderer or _default_renderer,
            asset_root=prepared.asset_root,
        )
        if asset is None:
            continue
        start = max(0, block.location.start_line - 1)
        end = block.location.end_line
        reference = _image_markdown(asset)
        replacements.append((start, end, reference))

    prepared_text = text
    for start, end, reference in sorted(replacements, key=lambda item: item[0], reverse=True):
        prepared_text = "\n".join(lines[:start] + reference + lines[end:])
        lines = prepared_text.split("\n")

    prepared.prepared_text = prepared_text
    prepared_path = Path(temp_dir) / (Path(path).stem + ".prepared.md")
    prepared_path.write_text(prepared_text, encoding="utf-8")
    prepared.prepared_path = str(prepared_path)
    return prepared


def _image_markdown(asset: GeneratedAsset) -> List[str]:
    """生成替换行：图片引用（相对 asset_root）+ 题注行。"""
    if not asset.image_path:
        # 兜底：把源码包成代码块 + 说明，保证内容可读且不被静默丢弃。
        lines = ["```mermaid"]
        lines.extend(asset.source_text.split("\n"))
        lines.append("```")
        if asset.message:
            lines.append("")
            lines.append("> {0}".format(asset.message))
        return lines
    reference = "![{0}]({1})".format(
        asset.kind or "图", asset.relative_path.replace("\\", "/")
    )
    if asset.width_px and asset.height_px:
        reference = "{0} ={1}x{2}".format(reference, asset.width_px, asset.height_px)
    return [reference]


def _prepare_one(
    block: CodeBlock,
    prepared: PreparedSource,
    *,
    cache_dir: Path,
    renderer: Callable[[str, str], object],
    asset_root: str,
) -> Optional[GeneratedAsset]:
    source = block.text
    kind = _detect_kind(source) or "flowchart"
    key = compute_cache_key(
        source, kind, renderer_version=_renderer_version(), params=RENDER_PARAMS
    )
    asset = GeneratedAsset(
        location=block.location,
        kind=kind,
        source_text=source,
        cache_key=key,
    )
    prepared.assets.append(asset)

    if kind not in SUPPORTED_KINDS:
        # 既不在声明支持子集内，也没有同源码有效缓存（缓存只按支持图种建立）：
        # 输出源码说明，其他章节继续。
        cached = read_cache(cache_dir, key)
        if cached is None:
            asset.fallback = "unsupported"
            asset.message = UNSUPPORTED_HINT
            prepared.warnings.append(
                {
                    "path": block.location.path,
                    "line": block.location.start_line,
                    "rule": "mermaid_unsupported_kind",
                    "message": "Mermaid 图种 {0} 不在本版支持子集内，已输出源码说明。".format(kind),
                    "hint": UNSUPPORTED_HINT,
                }
            )
            return asset
        return _store_asset(asset, cached, asset_root, prepared)

    render_error = ""
    result = None
    try:
        if renderer is _default_renderer and not _qt_main_thread_available():
            # CLI/后台线程：栅格化放到拥有 Qt 主线程的专用子进程，
            # 避免在不允许的线程创建 QPixmap/QGuiApplication。
            worker = _render_in_worker_process(source, kind)
            if isinstance(worker, _WorkerSuccess):
                result = worker
            else:
                render_error = str(worker.error)
        else:
            result = renderer(source, kind)
    except Exception as exc:  # noqa: BLE001 - 渲染器异常一律走兜底
        result = None
        render_error = str(exc)

    ok = bool(getattr(result, "ok", False))
    png = getattr(result, "png", None) if ok else None
    if ok and png:
        cached = _CacheHit(
            png=png,
            width=int(getattr(result, "width", 0) or 0),
            height=int(getattr(result, "height", 0) or 0),
            backend=str(getattr(result, "backend", "") or "builtin"),
            meta={},
        )
        write_cache(
            cache_dir,
            key,
            png=png,
            width=cached.width,
            height=cached.height,
            backend=cached.backend,
            kind=kind,
            source=source,
        )
        return _store_asset(asset, cached, asset_root, prepared, from_cache=False)

    # 失败/超时：先找同源码有效缓存（绝不用其它源码的图），否则输出源码说明。
    cached = read_cache(cache_dir, key)
    if cached is not None:
        asset.message = "渲染失败，已复用同源码有效缓存。"
        prepared.warnings.append(
            {
                "path": block.location.path,
                "line": block.location.start_line,
                "rule": "mermaid_render_failed",
                "message": "Mermaid 渲染失败（{0}），已复用同源码有效缓存。".format(
                    render_error or getattr(result, "error", "") or "未知原因"
                ),
            }
        )
        return _store_asset(asset, cached, asset_root, prepared, from_cache=True)

    asset.fallback = "source"
    asset.message = "Mermaid 渲染不可用：{0}".format(
        render_error or getattr(result, "error", "") or "渲染器未返回结果"
    )
    prepared.warnings.append(
        {
            "path": block.location.path,
            "line": block.location.start_line,
            "rule": "mermaid_render_unavailable",
            "message": asset.message + "；已输出源码和说明继续出稿。",
            "hint": "可在编辑器 Mermaid 工作台单独渲染后替换为图片引用。",
        }
    )
    return asset


def _store_asset(
    asset: GeneratedAsset,
    cached: _CacheHit,
    asset_root: str,
    prepared: PreparedSource,
    *,
    from_cache: bool = True,
) -> GeneratedAsset:
    name = "{0}-{1}.png".format("mermaid", asset.cache_key[:16])
    target = Path(asset_root) / name
    try:
        target.write_bytes(cached.png)
    except OSError as exc:
        asset.fallback = "source"
        asset.message = "生成图写入临时目录失败：{0}".format(exc)
        prepared.warnings.append(
            {
                "path": asset.location.path,
                "line": asset.location.start_line,
                "rule": "mermaid_asset_write_failed",
                "message": asset.message,
            }
        )
        return asset
    asset.image_path = str(target)
    asset.relative_path = name
    asset.width_px = cached.width
    asset.height_px = cached.height
    asset.backend = cached.backend
    asset.from_cache = from_cache
    return asset


def prepare_documents(
    paths: Sequence[str],
    *,
    temp_root: Optional[str] = None,
    cache_root: Optional[Path] = None,
    renderer: Optional[Callable[[str, str], object]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    resolver: Optional[Callable[[str, str], str]] = None,
) -> Tuple[List[PreparedSource], Optional[str]]:
    """批量预处理多份 Markdown，共用一个临时目录。

    Returns:
        ``(预处理结果列表, 共用临时目录)``；没有任何图时临时目录为 None。
    """
    shared = tempfile.mkdtemp(prefix="doc-tool-prepare-", dir=temp_root)
    results: List[PreparedSource] = []
    used = False
    for path in paths:
        prepared = prepare_markdown(
            path,
            temp_root=shared,
            cache_root=cache_root,
            renderer=renderer,
            cancel_check=cancel_check,
            resolver=resolver,
        )
        if prepared.temp_dir:
            # 子目录已挂到共享目录下，交给共享目录统一清理。
            prepared.owns_temp_dir = False
            used = True
        results.append(prepared)
    if not used:
        shutil.rmtree(shared, ignore_errors=True)
        return results, None
    return results, shared