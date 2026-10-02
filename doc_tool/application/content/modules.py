# -*- coding: utf-8 -*-
"""V3.0 正文模块库（批次 30-B）：可版本化、带资源的正文模块。

设计要点（对齐 ``openspec/changes/product-v30-content-reuse/design.md`` D1）：

- 模块是**正文 + 所需资源**（图片/表格文件），不内置 Word 底模；
- 元数据是声明式 ``module.yml``（schema 1），含 moduleId/version/参数/来源/资源 hash；
- 版本**不可原地覆盖**：同身份同版本再次发布不同内容时另存候选版本（``1.0.0-2``）；
- 从章节 Markdown 提取时，按引用收集被引用的本地资源并改写为模块内相对路径；
- 项目使用时把模块**固定复制**到 ``reuse/modules/<slug>/<version>/``，出稿不依赖原库绝对路径；
- 库配置损坏/缺失时回退为空索引并提示，仍允许按路径手工选择模块目录。

本模块只做纯文件服务，不依赖 GUI；写入统一走 ``writer.atomic_write``。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.content.writer import atomic_write, atomic_write_bytes
from doc_tool.application.intake_contract import sha256_file, sha256_text

#: 模块/assembly/instances/variants 共用的 sidecar schema 版本。
SCHEMA_VERSION = 1

#: 缺模块时的可读占位（正文继续，不阻断出稿）。
MODULE_MISSING_TEMPLATE = "【待补充：模块 {module}@{version} 未找到固定副本】"
#: 缺资源时的可读占位。
RESOURCE_MISSING_TEMPLATE = "【待补充：模块资源 {target} 不可用】"

#: 模块内正文文件名。
BODY_FILE_NAME = "_body.md"
#: 模块资源目录名（相对模块目录）。
RESOURCES_DIR_NAME = "resources"
#: 模块元数据文件名。
MANIFEST_FILE_NAME = "module.yml"
#: 本地库索引文件名。
INDEX_FILE_NAME = "index.json"

#: 项目内固定模块副本根目录（相对项目根）。
PROJECT_MODULE_ROOT = "reuse/modules"

#: ``{{module.name}}`` 参数占位符。声明键才替换，未声明保留字面值。
MODULE_PARAM_RE = re.compile(r"\{\{\s*module\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: 提取时会被收集的本地资源扩展名。
RESOURCE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp",
    ".docx", ".xlsx", ".csv", ".pdf", ".drawio",
)

#: 内联图片/链接引用：``![alt](target "title")`` / ``[alt](target)``。
_MD_LINK_RE = re.compile(
    r"(!?\[[^\]\n]*\]\()(?P<target>[^)\s]+)(?P<suffix>\s+(?:\"[^\"]*\"|'[^']*'))?(\))"
)
#: 引用式图片定义：``[id]: target``。
_MD_DEF_RE = re.compile(r"^(\s*\[[^\]\n]+\]:\s*)(?P<target>\S+)(\s*)$")
#: 标题行。
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.*?)\s*$")
#: 条目标记 ``<!-- DOC-ITEM: id | 标题 -->``。
ITEM_RE = re.compile(r"<!--\s*DOC-ITEM:\s*(?P<item>[^|\s>][^|>]*?)\s*(?:\|\s*(?P<title>[^>]*?)\s*)?-->")
#: 模块身份合法字符（slug 化前校验，避免路径注入）。
MODULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
#: 版本号合法字符。
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def is_external_target(target: str) -> bool:
    """外链/锚点/绝对 URL 不参与资源收集与改写。"""
    value = str(target or "").strip()
    if not value:
        return True
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "data:", "#", "ftp://")):
        return True
    if value.startswith("//"):
        return True
    return False


def slugify(value: str) -> str:
    """把 moduleId/版本号转为安全目录名；非法字符折叠为 ``-``。"""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("-.")
    return cleaned or "module"
def _safe_relative(value: str) -> Optional[Path]:
    """把相对路径规范化为不含越界项的 ``Path``；非法返回 None。"""
    text = str(value or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ":" in text.split("/")[0]:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return Path(*parts)


def _declared_relative(value: str) -> Optional[str]:
    """把**声明**的资源路径规范化为 POSIX 字符串；非法（空/绝对/越界）返回 None。

    与 ``_safe_relative`` 的区别：只读的声明路径不能因为一个坏项就让整个模块
    元数据不可用——坏附件由导入/发布阶段按「跳过并报告」处理（任务 2.4）。
    """
    text = str(value or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ":" in text.split("/")[0]:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _validate_identifier(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not MODULE_ID_RE.match(text):
        raise ValueError("{0} 非法：{1!r}".format(label, value))
    return text


def _validate_version(value: str) -> str:
    text = str(value or "").strip()
    if not VERSION_RE.match(text):
        raise ValueError("模块版本非法：{0!r}".format(value))
    return text


def module_version_dir(root, module_id: str, version: str) -> Path:
    """模块在库/项目固定副本中的目录：``<root>/<slug(id)>/<version>``。"""
    return Path(root) / slugify(module_id) / _validate_version(version)


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleParameter:
    """模块声明的文本参数（只有声明键可填写，不做表达式求值）。"""

    name: str
    default: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise ValueError("模块参数名非法：{0!r}".format(self.name))
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "default", "" if self.default is None else str(self.default))
        object.__setattr__(self, "description", str(self.description or ""))

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "default": self.default, "description": self.description}


@dataclass(frozen=True)
class ModuleResource:
    """模块所需资源：模块内相对路径 + 内容 hash。

    声明路径非法（越界/绝对/为空）时**不抛异常**：保留原文字面值并标记
    ``invalidPath``，由导入/发布/展开阶段按「跳过并定位」处理，避免一个坏附件
    让整个模块元数据不可读（对齐 design.md「合法项可用」）。
    """

    path: str
    sha256: str = ""

    def __post_init__(self) -> None:
        raw = str(self.path or "").replace("\\", "/").strip()
        safe = _declared_relative(raw)
        object.__setattr__(self, "path", safe if safe is not None else raw)
        object.__setattr__(self, "sha256", str(self.sha256 or ""))
        object.__setattr__(self, "invalidPath", safe is None)

    @property
    def isSafe(self) -> bool:
        """路径是否可安全解析到模块目录内（越界/绝对为 False）。"""
        return _declared_relative(self.path) is not None

    def to_dict(self) -> Dict[str, str]:
        data = {"path": self.path, "sha256": self.sha256}
        if not self.isSafe:
            data["invalidPath"] = "true"
        return data


@dataclass
class Module:
    """一个正文模块的具体版本。"""

    moduleId: str
    version: str
    title: str
    body: str
    bodyFile: str = BODY_FILE_NAME
    tags: List[str] = field(default_factory=list)
    description: str = ""
    parameters: List[ModuleParameter] = field(default_factory=list)
    resources: List[ModuleResource] = field(default_factory=list)
    source: Dict[str, str] = field(default_factory=dict)
    schemaVersion: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.moduleId = _validate_identifier(self.moduleId, "moduleId")
        self.version = _validate_version(self.version)
        self.title = str(self.title or self.moduleId)
        self.body = str(self.body or "")
        body_file = _safe_relative(self.bodyFile) or Path(BODY_FILE_NAME)
        self.bodyFile = body_file.as_posix()
        self.tags = [str(item) for item in (self.tags or []) if str(item or "").strip()]
        self.description = str(self.description or "")
        self.parameters = [
            item if isinstance(item, ModuleParameter) else ModuleParameter(**dict(item))
            for item in (self.parameters or [])
        ]
        self.resources = [
            item if isinstance(item, ModuleResource) else ModuleResource(**dict(item))
            for item in (self.resources or [])
        ]
        self.source = {str(key): str(value) for key, value in (self.source or {}).items()}
    # --- 序列化 ---

    @property
    def identity(self) -> str:
        return "{0}@{1}".format(self.moduleId, self.version)

    def to_dict(self) -> Dict[str, object]:
        return {
            "schemaVersion": self.schemaVersion,
            "moduleId": self.moduleId,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "bodyFile": self.bodyFile,
            "bodySha256": sha256_text(self.body),
            "parameters": [item.to_dict() for item in self.parameters],
            "resources": [item.to_dict() for item in self.resources],
            "source": dict(self.source),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object], body: Optional[str] = None) -> "Module":
        if not isinstance(data, dict):
            raise ValueError("模块元数据必须是映射")
        schema = int(data.get("schemaVersion", 0) or 0)
        if schema != SCHEMA_VERSION:
            raise ValueError("模块元数据必须是 schemaVersion {0}".format(SCHEMA_VERSION))
        return cls(
            moduleId=str(data.get("moduleId", "")),
            version=str(data.get("version", "")),
            title=str(data.get("title", "")),
            body=str(body if body is not None else data.get("body", "")),
            bodyFile=str(data.get("bodyFile") or BODY_FILE_NAME),
            tags=list(data.get("tags") or []),
            description=str(data.get("description", "")),
            parameters=list(data.get("parameters") or []),
            resources=list(data.get("resources") or []),
            source=dict(data.get("source") or {}),
            schemaVersion=schema,
        )

    # --- 查询 ---

    def parameter_defaults(self) -> Dict[str, str]:
        return {item.name: item.default for item in self.parameters}

    def declared_names(self) -> List[str]:
        return [item.name for item in self.parameters]

    def resource_hashes(self) -> Dict[str, str]:
        return {item.path: item.sha256 for item in self.resources}


@dataclass
class PublishedModule:
    """一次 ``publish``/``install`` 的结果：固定目录、是否新建、候选版本、提示。"""

    moduleId: str
    version: str
    directory: Path
    bodyPath: Path
    created: bool
    candidate: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def identity(self) -> str:
        return "{0}@{1}".format(self.moduleId, self.version)


@dataclass
class ModuleIssue:
    """库索引中的一条跳过/损坏提示。"""

    identity: str
    message: str


# --------------------------------------------------------------------------
# 提取
# --------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """从章节正文提取模块的结果。"""

    module: Module
    collected: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    #: ``{模块内相对路径: 原资源文件}``，供 publish 复制资源时使用。
    sourcePaths: Dict[str, Path] = field(default_factory=dict)


def _iter_targets(text: str) -> Iterable[Tuple[int, str]]:
    """按行产出 ``(行号, 引用目标)``，覆盖内联与引用式两种写法。"""
    for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
        for match in _MD_LINK_RE.finditer(raw_line):
            yield line_no, match.group("target")
        definition = _MD_DEF_RE.match(raw_line)
        if definition is not None:
            yield line_no, definition.group("target")


def is_resource_target(target: str) -> bool:
    """目标是否是本模块需要收集的资源（按扩展名判断，外链不算）。"""
    if is_external_target(target):
        return False
    cleaned = str(target).split("#", 1)[0].split("?", 1)[0].strip()
    if not cleaned:
        return False
    return Path(cleaned).suffix.lower() in RESOURCE_SUFFIXES


def collect_resources(text: str) -> List[str]:
    """收集正文引用的资源相对路径（去重保序）。"""
    found: List[str] = []
    seen = set()
    for _line_no, target in _iter_targets(text):
        if not is_resource_target(target):
            continue
        cleaned = str(target).split("#", 1)[0].split("?", 1)[0].strip().replace("\\", "/")
        relative = _safe_relative(cleaned)
        if relative is None:
            continue
        key = relative.as_posix()
        if key in seen:
            continue
        seen.add(key)
        found.append(key)
    return found

def _rewrite_resource_targets(text: str, mapping: Dict[str, str]) -> str:
    """把正文中的资源目标按 ``mapping`` 改写为模块内相对路径。"""
    if not mapping:
        return text

    def _inline(match: re.Match) -> str:
        target = match.group("target")
        replacement = mapping.get(str(target).replace("\\", "/"))
        if replacement is None:
            return match.group(0)
        return "{0}{1}{2}{3}".format(
            match.group(1), replacement, match.group("suffix") or "", match.group(4)
        )

    lines: List[str] = []
    for raw_line in str(text).splitlines(keepends=True):
        line = _MD_LINK_RE.sub(_inline, raw_line)
        stripped = line.rstrip("\r\n")
        definition = _MD_DEF_RE.match(stripped)
        if definition is not None:
            replacement = mapping.get(definition.group("target").replace("\\", "/"))
            if replacement is not None:
                ending = line[len(stripped):]
                line = "{0}{1}{2}".format(definition.group(1), replacement, ending or definition.group(3))
        lines.append(line)
    return "".join(lines)


def module_title_from(body: str, fallback: str = "") -> str:
    """取正文首个标题作为模块标题；无标题时用 fallback。"""
    for raw_line in str(body or "").splitlines():
        match = _HEADING_RE.match(raw_line.strip())
        if match is not None:
            title = match.group("title").strip()
            if title:
                return title
    return str(fallback or "").strip()


def default_module_id(body: str, fallback: str = "module") -> str:
    """从标题/来源名生成稳定 moduleId（小写、去空格）。"""
    title = module_title_from(body, fallback) or fallback
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(title).strip().lower()).strip("-.")
    if not slug or not re.match(r"^[A-Za-z0-9]", slug):
        slug = "module-" + sha256_text(str(title))[:8]
    return slug


def _root_for(path: Path, roots: Sequence[Path], base: Optional[Path]) -> Path:
    """给出一个文件应记录为相对路径的基准目录（内容根/资源根/项目根）。"""
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(path)
    if base is not None:
        try:
            resolved.relative_to(Path(base).resolve())
            return Path(base)
        except (ValueError, OSError):
            pass
    for root in sorted(roots, key=lambda item: len(str(item)), reverse=True):
        try:
            resolved.relative_to(Path(root).resolve())
            return Path(root)
        except (ValueError, OSError):
            continue
    return Path(path).parent


def _locate_resource(
    roots: Sequence[Path],
    relative: Path,
    *,
    recurse: bool = True,
) -> Optional[Path]:
    """在给定基准目录下查找资源；都找不到时按文件名在基准目录内递归查找。"""
    for root in roots:
        candidate = Path(root) / relative
        if candidate.is_file():
            return candidate
    if recurse:
        for root in roots:
            try:
                for candidate in Path(root).rglob(relative.name):
                    if candidate.is_file():
                        return candidate
            except OSError:
                continue
    return None


def module_resource_relative(backed: str) -> bool:
    """记录的相对路径是否已在模块资源目录内（是则模块可自包含）。"""
    text = str(backed or "").replace("\\", "/").strip("/")
    return text.startswith(RESOURCES_DIR_NAME + "/")


def extract_module(
    body: str,
    *,
    module_id: str,
    version: str,
    title: str = "",
    tags: Optional[Sequence[str]] = None,
    description: str = "",
    parameters: Optional[Sequence[object]] = None,
    source: Optional[Dict[str, str]] = None,
    resource_root=None,
    resource_roots: Optional[Sequence[object]] = None,
    base_dir=None,
    resource_sources: Optional[Dict[str, object]] = None,
    recurse: bool = True,
) -> ExtractionResult:
    """从章节正文提取模块：收集被引用资源、改写为模块内相对路径并算 hash。

    ``resource_root``/``resource_roots`` 是引用目标的解析基准目录（内容根与资源根）；
    ``base_dir`` 给出一并记录进项目的相对基准（通常是项目根）；``resource_sources``
    可显式给出 ``{引用目标: 源文件路径}``。找不到的资源记入 ``missing`` 并按原样保留
    引用，不阻断提取（兜底原则）。
    """
    module_id = _validate_identifier(module_id, "moduleId")
    version = _validate_version(version)
    body_text = str(body or "")
    declared = [
        item if isinstance(item, ModuleParameter) else ModuleParameter(**dict(item))
        for item in (parameters or [])
    ]

    targets = collect_resources(body_text)
    explicit = {
        str(key).replace("\\", "/"): Path(value)
        for key, value in (resource_sources or {}).items()
    }
    roots: List[Path] = []
    for value in list(resource_roots or []):
        if value is not None:
            roots.append(Path(value))
    if resource_root is not None:
        roots.append(Path(resource_root))
    base = Path(base_dir) if base_dir is not None else (roots[0] if roots else None)

    mapping: Dict[str, str] = {}
    resources: List[ModuleResource] = []
    collected: List[str] = []
    missing: List[str] = []
    warnings: List[str] = []
    skipped: List[str] = []
    source_paths: Dict[str, Path] = {}
    used_names = set()
    for target in targets:
        relative = _safe_relative(target)
        if relative is None:
            skipped.append(target)
            warnings.append("非法资源路径已跳过：{0}".format(target))
            continue
        source_path = explicit.get(target)
        if source_path is None:
            source_path = _locate_resource(roots, relative, recurse=recurse)
        if source_path is None or not Path(source_path).is_file():
            missing.append(target)
            warnings.append("模块资源缺失，已保留原引用：{0}".format(target))
            continue
        found = Path(source_path)
        root = _root_for(found, roots, base)
        backed = relative_asset_display(found, root)
        module_relative = ""
        if module_resource_relative(backed):
            module_relative = backed
        else:
            name = relative.name
            if name in used_names:
                name = "{0}-{1}{2}".format(relative.stem, sha256_text(target)[:6], relative.suffix)
            used_names.add(name)
            module_relative = (Path(RESOURCES_DIR_NAME) / name).as_posix()
        resources.append(ModuleResource(path=module_relative, sha256=sha256_file(found)))
        mapping[target] = module_relative
        source_paths[module_relative] = found
        collected.append(target)
    module = Module(
        moduleId=module_id,
        version=version,
        title=str(title or "").strip() or module_title_from(body_text, module_id),
        body=_rewrite_resource_targets(body_text, mapping),
        tags=list(tags or []),
        description=str(description or ""),
        parameters=declared,
        resources=resources,
        source=dict(source or {}),
    )
    return ExtractionResult(
        module=module,
        collected=collected,
        missing=missing,
        skipped=skipped,
        warnings=warnings,
        sourcePaths=source_paths,
    )

# --------------------------------------------------------------------------
# 本地库
# --------------------------------------------------------------------------


@dataclass
class ModuleSearchHit:
    module: Module
    directory: Path


class ModuleLibrary:
    """本地模块库：``<root>/<slug>/<version>/`` 只读索引 + 不可变发布。"""

    def __init__(self, root) -> None:
        self._root = Path(root)
        self._issues: List[ModuleIssue] = []
        self._index: List[ModuleSearchHit] = []
        self._index_error = False
        self._damaged_report: Optional[str] = None
        self.refresh()

    # --- 属性 ---

    @property
    def root(self) -> Path:
        return self._root

    @property
    def issues(self) -> List[ModuleIssue]:
        return list(self._issues)

    @property
    def index_error(self) -> bool:
        return self._index_error

    @property
    def damaged_report(self) -> Optional[str]:
        return self._damaged_report

    # --- 索引 ---

    def refresh(self) -> None:
        """重建内存索引；库缺失/索引损坏时回退空索引并记录提示。"""
        self._issues = []
        self._index = []
        self._index_error = False
        self._damaged_report = None
        if not self._root.is_dir():
            self._issues.append(
                ModuleIssue("-", "模块库目录不存在，已按空库继续：{0}".format(self._root))
            )
            return
        index_path = self._root / INDEX_FILE_NAME
        if index_path.is_file():
            try:
                import json

                data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                self._index_error = True
                self._damaged_report = "索引不可解析，已按目录重建索引"
            else:
                if not isinstance(data, dict) or int(data.get("schemaVersion", 0) or 0) != SCHEMA_VERSION:
                    self._index_error = True
                    self._damaged_report = "索引 schema 不兼容，已按目录重建索引"
        self._scan_directories()

    def _scan_directories(self) -> None:
        try:
            children = sorted(path for path in self._root.iterdir() if path.is_dir())
        except OSError as exc:
            self._issues.append(ModuleIssue("-", "模块库目录不可读：{0}".format(exc)))
            return
        for module_dir in children:
            try:
                version_dirs = sorted(path for path in module_dir.iterdir() if path.is_dir())
            except OSError:
                continue
            for version_dir in version_dirs:
                manifest_path = version_dir / MANIFEST_FILE_NAME
                if not manifest_path.is_file():
                    self._issues.append(
                        ModuleIssue(
                            version_dir.name,
                            "缺少 {0}，已跳过：{1}".format(MANIFEST_FILE_NAME, version_dir),
                        )
                    )
                    continue
                module = self.load_module(version_dir)
                if module is None:
                    self._issues.append(
                        ModuleIssue(version_dir.name, "模块元数据不可用，已跳过：{0}".format(version_dir))
                    )
                    continue
                self._index.append(ModuleSearchHit(module=module, directory=version_dir))

    def entries(self) -> List[ModuleSearchHit]:
        return list(self._index)

    def modules(self) -> List[Module]:
        return [hit.module for hit in self._index]

    # --- 读取 ---

    def load_module(self, directory) -> Optional[Module]:
        """读取单个模块目录；缺元数据/损坏返回 None（不抛异常，供手工选择回退）。"""
        directory = Path(directory)
        manifest_path = directory / MANIFEST_FILE_NAME
        if not directory.is_dir() or not manifest_path.is_file():
            return None
        try:
            import yaml

            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        except Exception:  # noqa: BLE001 - YAML 解析异常类型随版本变化
            return None
        if not isinstance(data, dict):
            return None
        relative = _safe_relative(str(data.get("bodyFile") or BODY_FILE_NAME))
        if relative is None:
            return None
        body_path = directory / relative
        body = ""
        if body_path.is_file():
            try:
                body = body_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                body = ""
        try:
            return Module.from_dict(data, body=body)
        except ValueError:
            return None
        except (TypeError, AttributeError):
            return None

    def get(self, module_id: str, version: str) -> Optional[Module]:
        for hit in self._index:
            if hit.module.moduleId == module_id and hit.module.version == version:
                return hit.module
        return None

    def directory_for(self, module_id: str, version: str) -> Optional[Path]:
        for hit in self._index:
            if hit.module.moduleId == module_id and hit.module.version == version:
                return hit.directory
        return None

    def versions(self, module_id: str) -> List[str]:
        values = [hit.module.version for hit in self._index if hit.module.moduleId == module_id]
        return sorted(set(values))

    def search(self, query: str = "", tags: Optional[Sequence[str]] = None) -> List[Module]:
        """按名称/标签/正文/描述检索（大小写不敏感，全空返回全部）。"""
        needle = str(query or "").strip().casefold()
        wanted = {str(item).strip().casefold() for item in (tags or []) if str(item).strip()}
        hits: List[Module] = []
        for hit in self._index:
            module = hit.module
            if wanted and not wanted.issubset({tag.casefold() for tag in module.tags}):
                continue
            if needle:
                haystack = "\n".join([
                    module.moduleId, module.version, module.title, module.description,
                    " ".join(module.tags), module.body,
                ]).casefold()
                if needle not in haystack:
                    continue
            hits.append(module)
        return hits

    def preview(
        self, module_id: str, version: str, params: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """返回按参数（缺省用声明默认）替换后的正文预览；无此版本返回 None。"""
        module = self.get(module_id, version)
        if module is None:
            return None
        text, _undeclared, _warnings = apply_module_parameters(
            module.body, module.parameter_defaults(), params or {}
        )
        return text
    # --- 写入 ---

    def _write_index(self) -> None:
        import json

        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "modules": [
                {
                    "moduleId": hit.module.moduleId,
                    "version": hit.module.version,
                    "title": hit.module.title,
                    "tags": list(hit.module.tags),
                    "directory": hit.directory.relative_to(self._root).as_posix(),
                    "bodySha256": sha256_text(hit.module.body),
                }
                for hit in self._index
            ],
            "issues": [
                {"identity": issue.identity, "message": issue.message} for issue in self._issues
            ],
        }
        try:
            atomic_write(self._root / INDEX_FILE_NAME, json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError:
            pass

    def publish(self, module: Module, *, resources: Optional[Dict[str, object]] = None) -> PublishedModule:
        """写入模块的固定版本；同身份同版本不同内容时另存候选版本，绝不覆盖。

        ``resources`` 是 ``{模块内相对路径: 源文件路径}``；缺项按占位继续并提示。
        """
        import yaml

        if not isinstance(module, Module):
            raise TypeError("publish 需要 Module 实例")
        target_dir = module_version_dir(self._root, module.moduleId, module.version)
        candidate: Optional[str] = None
        warnings: List[str] = []
        if target_dir.exists():
            existing = self.load_module(target_dir)
            if existing is not None and existing.body == module.body:
                warnings.append("版本 {0} 内容相同，未重复写入".format(module.version))
                self.refresh()
                return PublishedModule(
                    moduleId=module.moduleId,
                    version=module.version,
                    directory=target_dir,
                    bodyPath=target_dir / module.bodyFile,
                    created=False,
                    warnings=warnings,
                )
            if existing is not None:
                candidate = self.next_version(module.moduleId, module.version)
                warnings.append(
                    "版本 {0} 已存在且内容不同，原版本保留，已另存候选版本 {1}".format(
                        module.version, candidate
                    )
                )
                module = Module(
                    moduleId=module.moduleId,
                    version=candidate,
                    title=module.title,
                    body=module.body,
                    bodyFile=module.bodyFile,
                    tags=module.tags,
                    description=module.description,
                    parameters=module.parameters,
                    resources=module.resources,
                    source=module.source,
                )
                target_dir = module_version_dir(self._root, module.moduleId, module.version)

        body_path = target_dir / module.bodyFile
        atomic_write(body_path, module.body)
        provided = {
            str(key).replace("\\", "/"): Path(value) for key, value in (resources or {}).items()
        }
        unresolved: List[str] = []
        safe_resources = []
        for resource in module.resources:
            if not resource.isSafe:
                warnings.append("非法附件路径已跳过，不读取：{0}".format(resource.path))
                continue
            safe_resources.append(resource)
            source_path = provided.get(resource.path)
            if source_path is None or not Path(source_path).is_file():
                source_path = _find_resource_fallback(target_dir.parent, resource.path)
            if source_path is None:
                unresolved.append(resource.path)
                warnings.append("资源缺失，已占位提示：{0}".format(resource.path))
                continue
            data = Path(source_path).read_bytes()
            atomic_write_bytes(target_dir / resource.path, data)
            actual = _sha256_bytes(data)
            if resource.sha256 and resource.sha256 != actual:
                warnings.append(
                    "资源 hash 与元数据不一致，已按实际内容记录：{0}".format(resource.path)
                )
        manifest_data = module.to_dict()
        if unresolved:
            manifest_data["unresolvedResources"] = list(unresolved)
        atomic_write(
            target_dir / MANIFEST_FILE_NAME,
            yaml.safe_dump(manifest_data, allow_unicode=True, sort_keys=False),
        )
        self.refresh()
        self._write_index()
        return PublishedModule(
            moduleId=module.moduleId,
            version=module.version,
            directory=target_dir,
            bodyPath=body_path,
            created=True,
            candidate=candidate,
            warnings=warnings,
        )

    def next_version(self, module_id: str, version: str) -> str:
        """为已占用版本取候选新版本号：``1.0.0`` → ``1.0.0-2``、``-3``…"""
        existing = set(self.versions(module_id))
        index = 2
        while True:
            candidate = "{0}-{1}".format(version, index)
            if candidate not in existing:
                return candidate
            index += 1

    def save_examples(self, modules: Sequence[Module]) -> List[PublishedModule]:
        """写入若干公开示例模块（按需显式调用，不自动创建库）。"""
        return [self.publish(module) for module in modules]

    def export_module(self, module_id: str, version: str, target) -> Path:
        """导出一个模块目录（Markdown + 元数据 + 资源）到目标目录。"""
        directory = self.directory_for(module_id, version)
        if directory is None:
            raise FileNotFoundError("模块不存在：{0}@{1}".format(module_id, version))
        target = Path(target)
        if target.exists():
            shutil.rmtree(str(target))
        shutil.copytree(str(directory), str(target))
        return target
    def import_module(self, source) -> PublishedModule:
        """从模块目录导入：非法附件路径跳过并报告，原库保留。"""
        source = Path(source)
        module = self.load_module(source)
        if module is None:
            raise FileNotFoundError(
                "模块目录不可用（缺 {0}）：{1}".format(MANIFEST_FILE_NAME, source)
            )
        warnings: List[str] = []
        resources: Dict[str, object] = {}
        kept: List[ModuleResource] = []
        base = source.resolve()
        for resource in module.resources:
            source_path = source / resource.path
            try:
                source_path.resolve().relative_to(base)
            except ValueError:
                warnings.append("非法附件路径已跳过：{0}".format(resource.path))
                continue
            if not source_path.is_file():
                warnings.append("附件缺失，已占位提示：{0}".format(resource.path))
                continue
            resources[resource.path] = source_path
            kept.append(resource)
        if len(kept) != len(module.resources):
            module = Module(
                moduleId=module.moduleId,
                version=module.version,
                title=module.title,
                body=module.body,
                bodyFile=module.bodyFile,
                tags=module.tags,
                description=module.description,
                parameters=module.parameters,
                resources=kept,
                source=module.source,
            )
        published = self.publish(module, resources=resources)
        published.warnings = warnings + list(published.warnings)
        return published


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _find_resource_fallback(module_root: Path, relative: str) -> Optional[Path]:
    """在模块目录邻近位置查找同名资源（用于从库内复制时补全缺失附件）。"""
    name = Path(relative).name
    try:
        candidates = list(module_root.rglob(name))
    except OSError:
        return None
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------
# 参数与标题偏移（供 resolver 复用；与 V2.8 变量规则一致）
# --------------------------------------------------------------------------


def apply_module_parameters(
    text: str,
    defaults: Dict[str, str],
    values: Dict[str, str],
) -> Tuple[str, List[str], List[str]]:
    """替换 ``{{module.name}}``：调用方值 → 声明默认值 → 保留字面值。

    返回 ``(文本, 未声明键列表, warnings)``。代码围栏内不替换，资源路径行不替换；
    只做文本替换，不做表达式求值。
    """
    declared = {
        str(key): ("" if value is None else str(value)) for key, value in (defaults or {}).items()
    }
    raw = {
        str(key): ("" if value is None else str(value)) for key, value in (values or {}).items()
    }
    #: 只有声明键可填写；未声明键保留字面值并提示（不做表达式求值）。
    provided = {key: value for key, value in raw.items() if key in declared}
    undeclared: List[str] = []
    warnings: List[str] = []

    for key in raw:
        if key not in declared:
            undeclared.append(key)
            warnings.append("模块未声明参数 {0}，已保留字面值".format(key))

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name in raw and name not in declared:
            warnings.append("模块参数 {0} 未声明，已保留字面值".format(name))
            return match.group(0)
        if name in provided:
            return provided[name]
        if name in declared:
            warnings.append("模块参数 {0} 未提供，已用声明默认值".format(name))
            return declared[name]
        warnings.append("模块参数 {0} 未声明，已保留字面值".format(name))
        return match.group(0)

    lines: List[str] = []
    in_fence = False
    fence_marker = ""
    for raw_line in str(text or "").splitlines(keepends=True):
        stripped = raw_line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            lines.append(raw_line)
            continue
        if in_fence or not raw_line.strip():
            lines.append(raw_line)
            continue
        lines.append(MODULE_PARAM_RE.sub(_replace, raw_line))
    return "".join(lines), undeclared, warnings


def shift_headings(text: str, offset: int) -> Tuple[str, List[str]]:
    """按 ``offset`` 调整标题层级（1～6 截断），返回 ``(文本, warnings)``。

    只改正文标题行；代码围栏内不处理；越界时给提示但仍输出被截断的层级。
    """
    try:
        offset_value = int(offset)
    except (TypeError, ValueError):
        offset_value = 0
    warnings: List[str] = []
    if offset_value == 0:
        return text, warnings
    label = "+{0}".format(offset_value) if offset_value > 0 else str(offset_value)
    warnings.append("标题偏移 {0}（源模块未改动）".format(label))
    clipped = False
    lines: List[str] = []
    in_fence = False
    fence_marker = ""
    for raw_line in str(text or "").splitlines(keepends=True):
        stripped = raw_line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            lines.append(raw_line)
            continue
        if in_fence:
            lines.append(raw_line)
            continue
        rstrip_line = raw_line.rstrip("\r\n")
        match = re.match(r"^(?P<indent>\s*)(?P<hashes>#{1,6})(?P<rest>\s+.*)$", rstrip_line)
        if match is None:
            lines.append(raw_line)
            continue
        level = len(match.group("hashes"))
        target = level + offset_value
        if target < 1:
            target = 1
            clipped = True
        elif target > 6:
            target = 6
            clipped = True
        ending = raw_line[len(rstrip_line):]
        lines.append(
            "{0}{1}{2}{3}".format(match.group("indent"), "#" * target, match.group("rest"), ending)
        )
    if clipped:
        warnings.append("标题层级超出 1～6，已按支持范围截断（源模块未改动）")
    return "".join(lines), warnings

# --------------------------------------------------------------------------
# 项目内固定副本
# --------------------------------------------------------------------------


def project_module_root(project_root) -> Path:
    """项目内固定模块副本根：``<project>/reuse/modules``。"""
    return Path(project_root) / PROJECT_MODULE_ROOT


def project_module_dir(project_root, module_id: str, version: str) -> Path:
    return module_version_dir(project_module_root(project_root), module_id, version)


def install_module(
    project_root,
    module: Module,
    *,
    resources: Optional[Dict[str, object]] = None,
    overwrite: bool = False,
) -> PublishedModule:
    """把模块固定复制进项目：``reuse/modules/<slug>/<version>/``。

    默认不覆盖已有固定副本（项目快照稳定）；``overwrite=True`` 用于显式修复。
    """
    target_dir = project_module_dir(project_root, module.moduleId, module.version)
    warnings: List[str] = []
    if target_dir.exists() and not overwrite:
        library = ModuleLibrary(project_module_root(project_root))
        existing = library.get(module.moduleId, module.version)
        if existing is not None and existing.body == module.body:
            return PublishedModule(
                moduleId=module.moduleId,
                version=module.version,
                directory=target_dir,
                bodyPath=target_dir / module.bodyFile,
                created=False,
                warnings=warnings,
            )
        warnings.append("项目已存在同版本固定副本，未覆盖：{0}".format(target_dir))
        return PublishedModule(
            moduleId=module.moduleId,
            version=module.version,
            directory=target_dir,
            bodyPath=target_dir / module.bodyFile,
            created=False,
            warnings=warnings,
        )
    published = ModuleLibrary(project_module_root(project_root)).publish(module, resources=resources)
    published.warnings = warnings + list(published.warnings)
    return published


def install_from_library(
    project_root,
    library: ModuleLibrary,
    module_id: str,
    version: str,
) -> PublishedModule:
    """从库把模块固定复制进项目（资源一并复制，出稿不再依赖库目录）。"""
    module = library.get(module_id, version)
    directory = library.directory_for(module_id, version)
    if module is None or directory is None:
        raise FileNotFoundError("模块不存在：{0}@{1}".format(module_id, version))
    resources = {
        resource.path: directory / resource.path
        for resource in module.resources
        if (directory / resource.path).is_file()
    }
    return install_module(project_root, module, resources=resources)


# --------------------------------------------------------------------------
# 路径改写与资源占位
# --------------------------------------------------------------------------


def module_asset_root(module_dir) -> Path:
    """模块目录内资源根（``resources/``）。"""
    return Path(module_dir) / RESOURCES_DIR_NAME


def resolve_module_asset(module_dir, target: str) -> Optional[Path]:
    """把模块内资源相对路径解析为绝对路径；越界/非法返回 None。"""
    relative = _safe_relative(target)
    if relative is None:
        return None
    base = Path(module_dir)
    candidate = base / relative
    try:
        candidate.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return candidate


def rewrite_resource_paths(text: str, mapper) -> Tuple[str, List[str]]:
    """按 ``mapper(旧目标) -> 新目标|None`` 改写正文资源引用。

    返回 ``(文本, 未解析的资源目标列表)``；``mapper`` 返回 None 时原样保留。
    """
    unresolved: List[str] = []

    def _inline(match: re.Match) -> str:
        target = match.group("target")
        if is_external_target(target):
            return match.group(0)
        replacement = mapper(target)
        if replacement is None:
            if is_resource_target(target):
                unresolved.append(target)
            return match.group(0)
        return "{0}{1}{2}{3}".format(
            match.group(1), replacement, match.group("suffix") or "", match.group(4)
        )

    lines: List[str] = []
    for raw_line in str(text or "").splitlines(keepends=True):
        line = _MD_LINK_RE.sub(_inline, raw_line)
        stripped = line.rstrip("\r\n")
        definition = _MD_DEF_RE.match(stripped)
        if definition is not None and not is_external_target(definition.group("target")):
            replacement = mapper(definition.group("target"))
            if replacement is not None:
                ending = line[len(stripped):]
                line = "{0}{1}{2}".format(
                    definition.group(1), replacement, ending or definition.group(3)
                )
        lines.append(line)
    return "".join(lines), unresolved


def relative_asset_display(target, base_dir) -> str:
    """给出相对 ``base_dir`` 的展示路径；失败退回 POSIX 路径。"""
    if base_dir is None:
        return Path(target).as_posix()
    try:
        return Path(target).resolve().relative_to(Path(base_dir).resolve()).as_posix()
    except (ValueError, OSError):
        try:
            import os

            return Path(
                os.path.relpath(str(Path(target).resolve()), str(Path(base_dir).resolve()))
            ).as_posix()
        except (ValueError, OSError):
            return Path(target).as_posix()


def parse_doc_items(text: str) -> List[Tuple[str, str]]:
    """解析 ``<!-- DOC-ITEM: id | 标题 -->``，返回 ``[(itemId, title)]``（去重保序）。"""
    items: List[Tuple[str, str]] = []
    seen = set()
    for match in ITEM_RE.finditer(str(text or "")):
        item_id = match.group("item").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        items.append((item_id, (match.group("title") or "").strip()))
    return items


def missing_module_placeholder(module_id: str, version: str, *, reason: str = "") -> str:
    """缺模块时的可读占位（带定位说明，正文继续）。"""
    text = MODULE_MISSING_TEMPLATE.format(module=module_id, version=version or "-")
    if reason:
        text += "（{0}）".format(reason)
    return text


def missing_resource_placeholder(target: str) -> str:
    return RESOURCE_MISSING_TEMPLATE.format(target=target)


__all__ = [
    "SCHEMA_VERSION", "MODULE_MISSING_TEMPLATE", "RESOURCE_MISSING_TEMPLATE",
    "BODY_FILE_NAME", "RESOURCES_DIR_NAME", "MANIFEST_FILE_NAME", "INDEX_FILE_NAME",
    "PROJECT_MODULE_ROOT", "MODULE_PARAM_RE", "RESOURCE_SUFFIXES", "ITEM_RE",
    "ModuleParameter", "ModuleResource", "Module", "PublishedModule", "ModuleIssue",
    "ExtractionResult", "ModuleSearchHit", "ModuleLibrary",
    "is_external_target", "is_resource_target", "slugify", "module_version_dir",
    "module_title_from", "default_module_id", "collect_resources", "extract_module",
    "apply_module_parameters", "shift_headings",
    "project_module_root", "project_module_dir", "install_module", "install_from_library",
    "module_asset_root", "resolve_module_asset", "rewrite_resource_paths",
    "relative_asset_display", "parse_doc_items",
    "missing_module_placeholder", "missing_resource_placeholder",
]