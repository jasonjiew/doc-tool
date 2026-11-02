import re

# 1. Update doc_tool/application/content/mermaid.py
with open('doc_tool/application/content/mermaid.py', 'r', encoding='utf-8') as f:
    mermaid_code = f.read()

# Update RenderResult
old_render_result = """@dataclass(frozen=True)
class RenderResult:
    ok: bool
    svg: Optional[bytes] = None
    png: Optional[bytes] = None
    width: Optional[int] = None
    height: Optional[int] = None
    backend: str = ""
    error: Optional[str] = None"""

new_render_result = """@dataclass(frozen=True)
class RenderResult:
    ok: bool
    svg: Optional[bytes] = None
    png: Optional[bytes] = None
    width: Optional[int] = None
    height: Optional[int] = None
    backend: str = ""
    error: Optional[str] = None
    claims_fidelity: bool = False"""

if old_render_result in mermaid_code:
    mermaid_code = mermaid_code.replace(old_render_result, new_render_result, 1)

# Add export_svg, get_cli_status and update render, batch_convert
old_render_def = """def render(
    source: str,
    kind: Optional[str] = None,
    *,
    use_cli: bool = True,
    want_png: bool = True,
) -> RenderResult:"""

new_render_def = """def get_cli_status() -> Dict[str, Any]:
    \"\"\"检测当前 CLI 运行环境中的 Mermaid 后端能力（REQ-MM-05、REQ-MM-06、REQ-MD-08）。\"\"\"
    path_mmdc = shutil.which("mmdc")
    if path_mmdc:
        return {
            "available": True,
            "type": "path",
            "path": path_mmdc,
            "backend_name": "mermaid-cli",
            "claims_desktop_parity": True,
        }
    root = _repo_root()
    for candidate in (
        root / "tools" / "mermaid-cli" / "node_modules" / ".bin" / "mmdc.cmd",
        root / "tools" / "mermaid-cli" / "node_modules" / ".bin" / "mmdc",
        root / "node_modules" / ".bin" / "mmdc.cmd",
    ):
        if candidate.is_file():
            return {
                "available": True,
                "type": "local",
                "path": str(candidate),
                "backend_name": "mermaid-cli",
                "claims_desktop_parity": True,
            }
    return {
        "available": False,
        "type": "none",
        "path": None,
        "backend_name": "builtin-approximate",
        "claims_desktop_parity": False,
    }


def export_svg(result: RenderResult, assets_root, doc_type: str) -> str:
    \"\"\"保存成功渲染的 SVG，返回 images/mermaid_NNNN.svg（REQ-MM-04、REQ-MM-05）。\"\"\"
    if not result.ok or not result.svg:
        raise ValueError(result.error or "没有可导出的 SVG")
    folder = Path(assets_root) / doc_type / "images"
    folder.mkdir(parents=True, exist_ok=True)
    name = next_mermaid_name(assets_root, doc_type, ext="svg")
    (folder / name).write_bytes(result.svg)
    return "images/{0}".format(name)


def render(
    source: str,
    kind: Optional[str] = None,
    *,
    use_cli: bool = True,
    want_png: bool = True,
    theme: str = "default",
    engine_version: str = "11.16.1",
    config_hash: str = "",
) -> RenderResult:"""

if old_render_def in mermaid_code:
    mermaid_code = mermaid_code.replace(old_render_def, new_render_def, 1)

old_cache_key = "cache_key = (source.strip(), actual, use_cli, want_png)"
new_cache_key = "cache_key = (source.strip(), actual, use_cli, want_png, theme, engine_version, config_hash)"
if old_cache_key in mermaid_code:
    mermaid_code = mermaid_code.replace(old_cache_key, new_cache_key, 1)

old_batch_def = """def batch_convert(
    md_text: str,
    exporter: Callable[[MermaidBlock, RenderResult], str],
    *,
    include_fenced: bool = False,
    use_cli: bool = True,
) -> BatchConversionResult:
    \"\"\"逐个渲染并替换 Mermaid 源码；exporter 返回完整 Markdown 引用。\"\"\"
    blocks = [block for block in extract_blocks(md_text) if include_fenced or not block.fenced]
    lines = md_text.splitlines(keepends=True)
    replacements = []
    failures: List[BatchFailure] = []
    for block in blocks:
        result = render(block.source, block.kind, use_cli=use_cli)"""

new_batch_def = """def batch_convert(
    md_text: str,
    exporter: Callable[[MermaidBlock, RenderResult], str],
    *,
    include_fenced: bool = False,
    use_cli: bool = True,
    renderer: Optional[Callable[[str, Optional[str]], RenderResult]] = None,
) -> BatchConversionResult:
    \"\"\"逐个渲染并替换 Mermaid 源码；exporter 返回完整 Markdown 引用。\"\"\"
    blocks = [block for block in extract_blocks(md_text) if include_fenced or not block.fenced]
    lines = md_text.splitlines(keepends=True)
    replacements = []
    failures: List[BatchFailure] = []
    for block in blocks:
        if renderer is not None:
            result = renderer(block.source, block.kind)
        else:
            result = render(block.source, block.kind, use_cli=use_cli)"""

if old_batch_def in mermaid_code:
    mermaid_code = mermaid_code.replace(old_batch_def, new_batch_def, 1)

with open('doc_tool/application/content/mermaid.py', 'w', encoding='utf-8', newline='') as f:
    f.write(mermaid_code)
print('Updated mermaid.py')

# 2. Update doc_tool/application/prepared_source.py
with open('doc_tool/application/prepared_source.py', 'r', encoding='utf-8') as f:
    prep_code = f.read()

# Update CACHE_FORMAT_VERSION and read_cache
prep_code = prep_code.replace('CACHE_FORMAT_VERSION = "v1"', 'CACHE_FORMAT_VERSION = "v2"', 1)
old_read = """        if meta.get("format") != CACHE_FORMAT_VERSION:
            return None"""
new_read = """        format_version = meta.get("format")
        if format_version not in ("v1", "v2"):
            return None"""
if old_read in prep_code:
    prep_code = prep_code.replace(old_read, new_read, 1)

old_compute_key = """def compute_cache_key(
    source: str,
    kind: str,
    *,
    renderer_version: str = "",
    params: Optional[Dict[str, object]] = None,
) -> str:
    \"\"\"SHA-256 缓存键：源码 + 图种 + 渲染器版本 + 尺寸/主题参数。\"\"\"
    payload = {
        "format": CACHE_FORMAT_VERSION,
        "source": source.replace("\\r\\n", "\\n").strip(),
        "kind": kind,
        "rendererVersion": renderer_version,
        "params": dict(params or RENDER_PARAMS),
    }"""

new_compute_key = """def compute_cache_key(
    source: str,
    kind: str,
    *,
    renderer_version: str = "",
    theme: str = "default",
    font_family: str = "",
    layout: str = "",
    params: Optional[Dict[str, object]] = None,
) -> str:
    \"\"\"SHA-256 缓存键：源码 + 图种 + 渲染器版本 + 主题 + 字体 + 布局 + 尺寸参数（REQ-MM-04、REQ-MD-07）。\"\"\"
    payload = {
        "format": CACHE_FORMAT_VERSION,
        "source": source.replace("\\r\\n", "\\n").strip(),
        "kind": kind,
        "rendererVersion": renderer_version,
        "theme": theme,
        "fontFamily": font_family,
        "layout": layout,
        "params": dict(params or RENDER_PARAMS),
    }"""

if old_compute_key in prep_code:
    prep_code = prep_code.replace(old_compute_key, new_compute_key, 1)

with open('doc_tool/application/prepared_source.py', 'w', encoding='utf-8', newline='') as f:
    f.write(prep_code)
print('Updated prepared_source.py')
