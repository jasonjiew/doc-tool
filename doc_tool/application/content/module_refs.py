# -*- coding: utf-8 -*-
"""V3.0 统一引用展开与追踪实例（批次 30-C / 30-D）。

固定引用与复制编辑的稳定语法（本模块定义，测试固定）：

- **固定引用 slot**：独立正文块，``slotId`` 与宿主章节共同决定实例位置::

      ```doc-module id=term-standard version=1.0.0 slot=<uuid>
      productName=示例产品
      ```

- **复制编辑副本**：展开为普通正文，首行保留来源说明注释，不再随库升级变化::

      ```doc-module-copy slot=<uuid> version=1.0.0 source=<宿主相对路径>
      <复制时的正文>
      ```

设计要点（对齐 design.md D2/D3/D4）：

- 一次 ``resolve_body`` 产出有效文本、来源位置、资源映射、依赖 hash 与 warnings，
  预览/Word/HTML/检查共用同一结果（``ResolutionCache`` 只按输入签名缓存）；
- 参数只作文本替换（``{{module.name}}``），缺项用声明默认值，未声明保留字面值；
- ``headingOffset`` 只改输出层级（1～6 截断），不改源模块；
- 模块内可嵌套固定引用，深度上限 5；循环引用只停止该引用展开，其余正文继续；
- 项目固定副本优先，缺副本时同版本库缓存可用，都没有才输出可读占位；
- 实例身份只由 slotId 决定，明确纳入追踪才写入 ``reuse/instances.yml`` 并计入覆盖率。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from doc_tool.application.content import modules as module_lib
from doc_tool.application.content.writer import atomic_write
from doc_tool.application.intake_contract import sha256_text

#: sidecar schema 版本（assembly / instances）。
SCHEMA_VERSION = 1

#: 模块间固定引用的最大嵌套深度。
MAX_DEPTH = 5

#: 项目内 sidecar 相对路径。
ASSEMBLY_RELATIVE = "reuse/assembly.yml"
INSTANCES_RELATIVE = "reuse/instances.yml"

#: 缺模块占位模板（与模块库共用同一可读形式）。
MISSING_SLOT_TEMPLATE = module_lib.MODULE_MISSING_TEMPLATE
#: 循环引用停止展开时的可读说明。
CYCLE_STOP_TEMPLATE = "【已停止：模块 {module}@{version} 存在循环引用，该引用未展开】"

#: 固定引用块起始行：```doc-module id=... version=... slot=...
MODULE_FENCE_RE = re.compile(
    r"^\s*(?P<fence>`{3,}|~{3,})\s*doc-module\s+(?P<attrs>.*?)\s*$"
)
#: 复制编辑副本块起始行：```doc-module-copy ...
COPY_FENCE_RE = re.compile(
    r"^\s*(?P<fence>`{3,}|~{3,})\s*doc-module-copy\s*(?P<attrs>.*?)\s*$"
)
#: ``name=value`` 属性（value 不含空白）。
_ATTR_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)")
#: 参数行：``name=value``（值可含空格，剔除说明后的剩余部分）。
_PARAM_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^\s]+)")


def _unquote(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def parse_attrs(text: str) -> Dict[str, str]:
    """解析 ``a=1 b="x y"`` 形式的属性串。"""
    values: Dict[str, str] = {}
    for match in _ATTR_RE.finditer(str(text or "")):
        values[match.group(1)] = _unquote(match.group(2))
    return values


def canonical_directive(
    module_id: str,
    version: str,
    slot_id: str,
    params: Optional[Dict[str, str]] = None,
    heading_offset: int = 0,
) -> str:
    """生成一个规范化的固定引用块（供编辑器插入与测试固定语法）。"""
    attrs = "id={0} version={1} slot={2}".format(module_id, version, slot_id)
    if int(heading_offset or 0):
        attrs += " headingOffset={0}".format(int(heading_offset))
    lines = ["```doc-module {0}".format(attrs)]
    for name in sorted((params or {}).keys()):
        lines.append("{0}={1}".format(name, params[name]))
    lines.append("```")
    return "\n".join(lines) + "\n"


def canonical_copy_block(
    body: str,
    *,
    slot_id: str = "",
    version: str = "",
    source: str = "",
) -> str:
    """生成一个复制编辑副本块（展开后即普通正文，含来源说明）。"""
    attrs = []
    if slot_id:
        attrs.append("slot={0}".format(slot_id))
    if version:
        attrs.append("version={0}".format(version))
    if source:
        attrs.append("source={0}".format(str(source).replace("\\", "/")))
    header = "```doc-module-copy" + ((" " + " ".join(attrs)) if attrs else "")
    body_text = str(body or "").rstrip("\n")
    provenance = "<!-- 来源：模块副本，复制编辑内容不随模块升级改变 -->"
    return "\n".join([header, provenance, body_text, "```"]) + "\n"


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


@dataclass
class SlotRef:
    """一处固定引用：块位置 + 模块身份 + 参数。"""

    slotId: str
    moduleId: str
    version: str
    params: Dict[str, str] = field(default_factory=dict)
    headingOffset: int = 0
    startLine: int = 0
    endLine: int = 0
    fence: str = "```"

    @property
    def identity(self) -> str:
        return "{0}@{1}".format(self.moduleId, self.version)

    def with_version(self, version: str, params: Optional[Dict[str, str]] = None) -> "SlotRef":
        return SlotRef(
            slotId=self.slotId,
            moduleId=self.moduleId,
            version=version,
            params=dict(self.params if params is None else params),
            headingOffset=self.headingOffset,
            startLine=self.startLine,
            endLine=self.endLine,
            fence=self.fence,
        )


@dataclass
class CopyBlock:
    """一处复制编辑副本：位置 + 来源信息 + 复制时正文。"""

    slotId: str
    version: str
    source: str
    body: str
    startLine: int = 0
    endLine: int = 0
    fence: str = "```"


@dataclass
class ScanResult:
    slots: List[SlotRef] = field(default_factory=list)
    copies: List[CopyBlock] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_reuse(self) -> bool:
        return bool(self.slots or self.copies)


def scan_directives(text: str) -> ScanResult:
    """扫描正文中的固定引用与复制编辑块（未闭合块给 warning 并跳过）。"""
    result = ScanResult()
    lines = str(text or "").splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        copy_match = COPY_FENCE_RE.match(raw_line)
        if copy_match is not None:
            fence = copy_match.group("fence")
            attrs = parse_attrs(copy_match.group("attrs"))
            body_lines: List[str] = []
            cursor = index + 1
            closed = False
            while cursor < len(lines):
                if lines[cursor].strip().startswith(fence):
                    closed = True
                    break
                body_lines.append(lines[cursor])
                cursor += 1
            if not closed:
                result.warnings.append(
                    "复制编辑块未闭合（第 {0} 行），已按普通正文继续".format(index + 1)
                )
                index += 1
                continue
            result.copies.append(
                CopyBlock(
                    slotId=attrs.get("slot", ""),
                    version=attrs.get("version", ""),
                    source=attrs.get("source", ""),
                    body="\n".join(body_lines),
                    startLine=index + 1,
                    endLine=cursor + 1,
                    fence=fence,
                )
            )
            index = cursor + 1
            continue
        slot_match = MODULE_FENCE_RE.match(raw_line)
        if slot_match is not None:
            fence = slot_match.group("fence")
            attrs = parse_attrs(slot_match.group("attrs"))
            param_lines: List[str] = []
            cursor = index + 1
            closed = False
            while cursor < len(lines):
                if lines[cursor].strip().startswith(fence):
                    closed = True
                    break
                param_lines.append(lines[cursor])
                cursor += 1
            if not closed:
                result.warnings.append(
                    "固定引用块未闭合（第 {0} 行），已按普通正文继续".format(index + 1)
                )
                index += 1
                continue
            module_id = attrs.get("id", "")
            version = attrs.get("version", "")
            if not module_id:
                result.warnings.append(
                    "固定引用缺少 id（第 {0} 行），已按普通正文继续".format(index + 1)
                )
                index = cursor + 1
                continue
            params: Dict[str, str] = {}
            for line in param_lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                for match in _PARAM_RE.finditer(stripped):
                    params[match.group(1)] = _unquote(match.group(2))
            offset = 0
            try:
                offset = int(attrs.get("headingOffset", "0") or 0)
            except ValueError:
                result.warnings.append(
                    "headingOffset 非法（第 {0} 行），已按 0 继续".format(index + 1)
                )
            result.slots.append(
                SlotRef(
                    slotId=attrs.get("slot", ""),
                    moduleId=module_id,
                    version=version,
                    params=params,
                    headingOffset=offset,
                    startLine=index + 1,
                    endLine=cursor + 1,
                    fence=fence,
                )
            )
            index = cursor + 1
            continue
        index += 1
    return result


def strip_directives(text: str) -> str:
    """去掉固定引用/复制编辑块标记，只保留正文（用于来源对照与副本）。"""
    lines = str(text or "").splitlines()
    output: List[str] = []
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        match = COPY_FENCE_RE.match(raw_line) or MODULE_FENCE_RE.match(raw_line)
        if match is None:
            output.append(raw_line)
            index += 1
            continue
        fence = match.group("fence")
        cursor = index + 1
        inner: List[str] = []
        while cursor < len(lines) and not lines[cursor].strip().startswith(fence):
            inner.append(lines[cursor])
            cursor += 1
        if COPY_FENCE_RE.match(raw_line) is not None:
            output.extend(
                line for line in inner if not line.strip().startswith("<!-- 来源：")
            )
        else:
            output.extend(inner)
        index = cursor + 1
    return "\n".join(output)

# --------------------------------------------------------------------------
# assembly / instances 配置（schema 1）
# --------------------------------------------------------------------------


@dataclass
class AssemblySlot:
    """``reuse/assembly.yml`` 中的一个固定引用配置。"""

    slotId: str
    moduleId: str
    version: str
    chapter: str = ""
    params: Dict[str, str] = field(default_factory=dict)
    headingOffset: int = 0

    def __post_init__(self) -> None:
        self.slotId = str(self.slotId or "").strip() or _new_slot_id()
        self.moduleId = str(self.moduleId or "").strip()
        self.version = str(self.version or "").strip()
        self.chapter = str(self.chapter or "").replace("\\", "/").strip()
        self.params = {str(k): ("" if v is None else str(v)) for k, v in (self.params or {}).items()}
        try:
            self.headingOffset = int(self.headingOffset or 0)
        except (TypeError, ValueError):
            self.headingOffset = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "slotId": self.slotId,
            "moduleId": self.moduleId,
            "version": self.version,
            "chapter": self.chapter,
            "params": dict(self.params),
            "headingOffset": self.headingOffset,
        }

    def with_version(self, version: str, params: Optional[Dict[str, str]] = None) -> "AssemblySlot":
        """返回固定到新版本的副本（原配置不被改动，便于取消/回退）。"""
        return AssemblySlot(
            slotId=self.slotId,
            moduleId=self.moduleId,
            version=version,
            chapter=self.chapter,
            params=dict(self.params if params is None else params),
            headingOffset=self.headingOffset,
        )

    def with_version(self, version: str, params: Optional[Dict[str, str]] = None) -> "AssemblySlot":
        """返回固定到新版本的副本（原配置不被改动，便于取消/回退）。"""
        return AssemblySlot(
            slotId=self.slotId,
            moduleId=self.moduleId,
            version=version,
            chapter=self.chapter,
            params=dict(self.params if params is None else params),
            headingOffset=self.headingOffset,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "AssemblySlot":
        return cls(
            slotId=str(data.get("slotId", "")),
            moduleId=str(data.get("moduleId", "")),
            version=str(data.get("version", "")),
            chapter=str(data.get("chapter", "")),
            params=dict(data.get("params") or {}),
            headingOffset=data.get("headingOffset", 0),
        )


def _new_slot_id() -> str:
    return "slot-" + uuid.uuid4().hex[:12]


def new_slot_id() -> str:
    """生成新的 slotId（实例身份只由它决定）。"""
    return _new_slot_id()


@dataclass
class Assembly:
    """项目固定引用装配（schema 1）；无 sidecar 时为空且旧项目行为不变。"""

    slots: List[AssemblySlot] = field(default_factory=list)
    schemaVersion: int = SCHEMA_VERSION

    def get(self, slot_id: str) -> Optional[AssemblySlot]:
        for slot in self.slots:
            if slot.slotId == slot_id:
                return slot
        return None

    def upsert(self, slot: AssemblySlot) -> None:
        for index, existing in enumerate(self.slots):
            if existing.slotId == slot.slotId:
                self.slots[index] = slot
                return
        self.slots.append(slot)

    def to_dict(self) -> Dict[str, object]:
        return {"schemaVersion": self.schemaVersion, "slots": [slot.to_dict() for slot in self.slots]}

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Assembly":
        if not isinstance(data, dict):
            return cls()
        schema = int(data.get("schemaVersion", 0) or 0)
        assembly = cls(schemaVersion=schema or SCHEMA_VERSION)
        version = int(data.get("schemaVersion", 0) or 0)
        if version != SCHEMA_VERSION:
            return cls()
        for row in data.get("slots") or []:
            if isinstance(row, dict):
                assembly.slots.append(AssemblySlot.from_dict(row))
        return assembly

    def save(self, project_root) -> Path:
        import yaml

        path = Path(project_root) / ASSEMBLY_RELATIVE
        atomic_write(path, yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False))
        return path

    @classmethod
    def load(cls, project_root) -> "Assembly":
        """读取项目装配；缺失/损坏回退空装配并继续（不阻断出稿）。"""
        import yaml

        path = Path(project_root) / ASSEMBLY_RELATIVE
        if not path.is_file():
            return cls()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return cls()
        except Exception:  # noqa: BLE001 - YAML 异常类型随版本变化
            return cls()
        return cls.from_dict(data if isinstance(data, dict) else {})


@dataclass
class Instance:
    """追踪实例：slot + 原始条目 → 宿主实例 UUID（仅明确纳入时存在）。"""

    instanceId: str
    slotId: str
    moduleId: str
    version: str
    originItemId: str = ""
    title: str = ""
    chapter: str = ""
    included: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "instanceId": self.instanceId,
            "slotId": self.slotId,
            "moduleId": self.moduleId,
            "version": self.version,
            "originItemId": self.originItemId,
            "title": self.title,
            "chapter": self.chapter,
            "included": bool(self.included),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Instance":
        return cls(
            instanceId=str(data.get("instanceId", "")),
            slotId=str(data.get("slotId", "")),
            moduleId=str(data.get("moduleId", "")),
            version=str(data.get("version", "")),
            originItemId=str(data.get("originItemId", "")),
            title=str(data.get("title", "")),
            chapter=str(data.get("chapter", "")),
            included=bool(data.get("included")),
        )


@dataclass
class Coverage:
    """覆盖率解释：只有明确纳入追踪的实例才进分母。"""

    tracked: List[str] = field(default_factory=list)
    included: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)

    @property
    def denominator(self) -> int:
        return len(self.included)

    @property
    def coverage(self) -> float:
        return 1.0 if self.included else 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "tracked": list(self.tracked),
            "included": list(self.included),
            "excluded": list(self.excluded),
            "denominator": self.denominator,
            "coverage": self.coverage,
        }


class InstanceBook:
    """``reuse/instances.yml``：slot/来源条目到宿主实例 UUID 的持久映射。"""

    def __init__(self, project_root=None, instances: Optional[Sequence[Instance]] = None) -> None:
        self._root = Path(project_root) if project_root is not None else None
        self._instances: List[Instance] = list(instances or [])

    @property
    def path(self) -> Optional[Path]:
        return None if self._root is None else self._root / INSTANCES_RELATIVE

    def entries(self) -> List[Instance]:
        return list(self._instances)

    def by_slot(self, slot_id: str) -> List[Instance]:
        return [item for item in self._instances if item.slotId == slot_id]

    def instance_for(self, slot_id: str, origin_item_id: str) -> Optional[Instance]:
        for item in self._instances:
            if item.slotId == slot_id and item.originItemId == origin_item_id:
                return item
        return None

    def instance_id_for(self, slot_id: str, origin_item_id: str) -> str:
        """同 slot 同来源条目身份稳定；不存在则分配新 UUID。"""
        existing = self.instance_for(slot_id, origin_item_id)
        if existing is not None:
            return existing.instanceId
        return str(uuid.uuid4())

    def register(
        self,
        *,
        slot_id: str,
        module_id: str,
        version: str,
        origin_item_id: str = "",
        title: str = "",
        chapter: str = "",
        included: bool = False,
    ) -> Instance:
        """登记/更新一个实例；已有身份保持不变，位置可刷新。"""
        existing = self.instance_for(slot_id, origin_item_id)
        if existing is not None:
            existing.moduleId = module_id or existing.moduleId
            existing.version = version or existing.version
            existing.title = title or existing.title
            existing.chapter = chapter or existing.chapter
            if included:
                existing.included = True
            return existing
        instance = Instance(
            instanceId=str(uuid.uuid4()),
            slotId=slot_id,
            moduleId=module_id,
            version=version,
            originItemId=origin_item_id,
            title=title,
            chapter=chapter,
            included=bool(included),
        )
        self._instances.append(instance)
        return instance

    def include(self, slot_id: str, origin_item_id: str = "") -> bool:
        """把某个实例明确纳入追踪；不存在时返回 False（不伪造关联）。"""
        existing = self.instance_for(slot_id, origin_item_id)
        if existing is None:
            return False
        existing.included = True
        return True

    def exclude(self, slot_id: str, origin_item_id: str = "") -> bool:
        existing = self.instance_for(slot_id, origin_item_id)
        if existing is None:
            return False
        existing.included = False
        return True

    def refresh_positions(self, positions: Dict[str, str]) -> List[Instance]:
        """按 ``{slotId: 章节}`` 刷新宿主路径；实例身份不变（重排安全）。"""
        kept = []
        for item in self._instances:
            if item.slotId in positions:
                item.chapter = positions[item.slotId]
            kept.append(item)
        return kept

    def items_of(self, slot_id: str) -> List[Instance]:
        return self.by_slot(slot_id)

    def pruned(self, live_slot_ids: Iterable[str]) -> List[Instance]:
        """返回悬空实例（slot 已不存在），保留证据而不删除。"""
        live = {str(item) for item in live_slot_ids}
        return [item for item in self._instances if item.slotId not in live]

    def coverage(self) -> Coverage:
        tracked = [item.instanceId for item in self._instances]
        included = [item.instanceId for item in self._instances if item.included]
        excluded = [item.instanceId for item in self._instances if not item.included]
        return Coverage(tracked=tracked, included=included, excluded=excluded)

    def to_dict(self) -> Dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "instances": [item.to_dict() for item in self._instances],
        }

    def save(self, project_root=None) -> Path:
        import yaml

        root = Path(project_root) if project_root is not None else self._root
        if root is None:
            raise ValueError("缺少项目根，无法保存实例映射")
        path = root / INSTANCES_RELATIVE
        atomic_write(path, yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False))
        return path

    @classmethod
    def load(cls, project_root) -> "InstanceBook":
        """读取实例映射；缺失/损坏回退空映射（身份丢失时不伪造关联）。"""
        import yaml

        path = Path(project_root) / INSTANCES_RELATIVE
        if not path.is_file():
            return cls(project_root)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return cls(project_root)
        except Exception:  # noqa: BLE001
            return cls(project_root)
        if not isinstance(data, dict) or int(data.get("schemaVersion", 0) or 0) != SCHEMA_VERSION:
            return cls(project_root)
        instances = [
            Instance.from_dict(row) for row in (data.get("instances") or []) if isinstance(row, dict)
        ]
        return cls(project_root, instances)

# --------------------------------------------------------------------------
# 展开结果
# --------------------------------------------------------------------------


@dataclass
class SourceLocation:
    """展开内容的来源定位：宿主章节 → 可定位回模块源。"""

    kind: str = "text"
    moduleId: str = ""
    version: str = ""
    slotId: str = ""
    moduleDir: str = ""
    hostLine: int = 0
    moduleLine: int = 0
    hostPath: str = ""

    @property
    def display(self) -> str:
        if self.kind != "module":
            return self.hostPath or "宿主正文"
        origin = "{0}@{1}".format(self.moduleId, self.version)
        if self.hostPath:
            origin = "{0} → {1}".format(origin, self.hostPath)
        return origin


@dataclass
class ResolvedSegment:
    """展开结果的一段：普通正文或模块展开。"""

    text: str
    kind: str = "text"
    origin: Optional[SourceLocation] = None
    moduleId: str = ""
    version: str = ""
    slotId: str = ""
    moduleDir: Optional[Path] = None
    params: Dict[str, str] = field(default_factory=dict)
    paramsFromDeclared: List[str] = field(default_factory=list)
    resources: Dict[str, Path] = field(default_factory=dict)
    dependencyHashes: Dict[str, str] = field(default_factory=dict)
    degraded: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass
class Resolution:
    """一次展开的完整结果（预览/Word/HTML/检查共用）。"""

    segments: List[ResolvedSegment] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    slots: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    copies: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(segment.kind == "module" for segment in self.segments)

    @property
    def degraded(self) -> bool:
        return any(segment.degraded for segment in self.segments)

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)

    def body(self, path: str = "") -> str:
        return self.text

    def module_segments(self) -> List[ResolvedSegment]:
        return [segment for segment in self.segments if segment.kind == "module"]

    def manifest(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        for segment in self.module_segments():
            values[segment.slotId or segment.moduleId] = "{0}@{1}".format(
                segment.moduleId, segment.version
            )
        return values

    def resources(self) -> Dict[str, Path]:
        values: Dict[str, Path] = {}
        for segment in self.module_segments():
            values.update(segment.resources)
        return values

    def slot_ids(self) -> List[str]:
        return [segment.slotId for segment in self.module_segments() if segment.slotId]

    def source_for_slot(self, slot_id: str) -> Optional[SourceLocation]:
        for segment in self.module_segments():
            if segment.slotId == slot_id and segment.origin is not None:
                return segment.origin
        return None

    def locate(self, host_line: int) -> Optional[SourceLocation]:
        """按宿主行号定位展开来源（行号落在模块展开内时返回模块来源）。"""
        cursor = 1
        for segment in self.segments:
            lines = segment.text.count("\n") or 1
            if cursor <= host_line <= cursor + lines:
                return segment.origin
            cursor += lines
        return None

    def issues(self) -> List[str]:
        return list(self.warnings) + list(self.errors)

    def is_clean(self) -> bool:
        return not self.errors


class ResolutionCache:
    """按输入签名缓存展开结果，保证预览/Word/HTML/检查拿到同一份内容。"""

    def __init__(self) -> None:
        self._values: Dict[str, Resolution] = {}

    def __len__(self) -> int:
        return len(self._values)

    def clear(self) -> None:
        self._values.clear()

    def get(self, signature: str) -> Optional[Resolution]:
        return self._values.get(signature)

    def put(self, signature: str, resolution: Resolution) -> Resolution:
        self._values[signature] = resolution
        return resolution

# --------------------------------------------------------------------------
# 展开
# --------------------------------------------------------------------------


def _find_module_directory(
    project_root,
    library,
    module_id: str,
    version: str,
) -> Tuple[Optional[Path], Optional[module_lib.Module], str]:
    """按「项目固定副本 → 同版本库缓存」顺序取模块，返回 (目录, 模块, 来源)。"""
    if project_root is not None:
        directory = module_lib.project_module_dir(project_root, module_id, version)
        if directory.is_dir():
            module = module_lib.ModuleLibrary(module_lib.project_module_root(project_root)).get(
                module_id, version
            )
            if module is not None:
                return directory, module, "project"
            manifest_path = directory / module_lib.MANIFEST_FILE_NAME
            if manifest_path.is_file():
                return directory, None, "project"
    if library is not None:
        directory = library.directory_for(module_id, version)
        if directory is not None:
            module = library.get(module_id, version)
            return directory, module, "library-cache"
    return None, None, ""


def _read_module_body(directory: Path, module: Optional[module_lib.Module]) -> Tuple[str, str]:
    """读取模块正文，返回 ``(正文, 实际正文文件相对路径)``。"""
    if module is not None and module.body:
        return module.body, module.bodyFile
    relative = (module.bodyFile if module is not None else "") or module_lib.BODY_FILE_NAME
    body_path = Path(directory) / relative
    if body_path.is_file():
        try:
            return body_path.read_text(encoding="utf-8"), relative
        except (OSError, UnicodeError):
            return "", relative
    for candidate in sorted(Path(directory).glob("*.md")):
        try:
            return candidate.read_text(encoding="utf-8"), candidate.name
        except (OSError, UnicodeError):
            continue
    return "", relative


def resolve_body(
    text: str,
    *,
    project_root=None,
    library: Optional[module_lib.ModuleLibrary] = None,
    variables: Optional[Dict[str, str]] = None,
    host_path: str = "",
    asset_root=None,
    cache: Optional[ResolutionCache] = None,
    max_depth: int = MAX_DEPTH,
    slot_overrides: Optional[Dict[str, Dict[str, object]]] = None,
    strict: bool = False,
    module_defaults: Optional[Dict[str, str]] = None,
) -> Resolution:
    """展开正文中的固定引用，产出有效内容与来源（复制编辑块按普通正文继续）。

    ``variables`` 同时接受 ``name`` 与 ``module.name`` 两种键位；``asset_root`` 给出
    渲染基准目录，用于把模块资源改写为可用的相对路径（缺省用项目根）。
    ``slot_overrides`` 形如 ``{slotId: {"version": ..., "params": {...}}}``，
    供产品变体在不改动项目装配的前提下覆盖版本与参数。
    """
    signature = ""
    if cache is not None:
        signature = "|".join([
            sha256_text(str(text or "")),
            str(Path(project_root)) if project_root is not None else "-",
            str(getattr(library, "root", "")) if library is not None else "-",
            repr(sorted((variables or {}).items())),
            str(asset_root) if asset_root is not None else "-",
            host_path,
            repr(sorted((slot_overrides or {}).items(), key=lambda item: str(item[0]))),
            str(strict),
            repr(sorted((module_defaults or {}).items())),
        ])
        cached = cache.get(signature)
        if cached is not None:
            return cached
    normalized: Dict[str, str] = {}
    for key, value in (variables or {}).items():
        name = str(key)
        normalized[name] = "" if value is None else str(value)
        if name.startswith("module."):
            normalized.setdefault(name[len("module."):], "" if value is None else str(value))
    resolution = _resolve(
        str(text or ""),
        project_root=project_root,
        library=library,
        variables=normalized,
        host_path=host_path,
        asset_root=asset_root,
        stack=(),
        depth=0,
        max_depth=max_depth,
        slot_overrides=slot_overrides or {},
        strict=strict,
        module_defaults=module_defaults or {},
    )
    if cache is not None:
        cache.put(signature, resolution)
    return resolution


def _resolve(
    text: str,
    *,
    project_root,
    library,
    variables: Dict[str, str],
    host_path: str,
    asset_root,
    stack: Tuple[str, ...],
    depth: int,
    max_depth: int,
    slot_overrides: Dict[str, Dict[str, object]],
    strict: bool,
    module_defaults: Dict[str, str],
) -> Resolution:
    scan = scan_directives(text)
    resolution = Resolution(warnings=list(scan.warnings))
    if strict:
        resolution.errors.extend(scan.warnings)
    if not scan.has_reuse:
        resolution.segments.append(ResolvedSegment(text=text, kind="text"))
        return resolution

    lines = str(text or "").splitlines(keepends=True)
    position = 0
    for block in sorted(
        list(scan.slots) + list(scan.copies),
        key=lambda item: (item.startLine, item.endLine),
    ):
        start_index = block.startLine - 1
        end_index = block.endLine
        if start_index > position:
            resolution.segments.append(
                ResolvedSegment(text="".join(lines[position:start_index]), kind="text")
            )
        if isinstance(block, CopyBlock):
            body_text = block.body
            if body_text and not body_text.endswith("\n"):
                body_text += "\n"
            resolution.segments.append(ResolvedSegment(text=body_text, kind="copy"))
            if block.slotId:
                resolution.copies.append(block.slotId)
            position = end_index
            continue
        segment = _expand_slot(
            block,
            project_root=project_root,
            library=library,
            variables=variables,
            host_path=host_path,
            asset_root=asset_root,
            stack=stack,
            depth=depth,
            max_depth=max_depth,
            slot_overrides=slot_overrides,
            strict=strict,
            module_defaults=module_defaults,
            resolution=resolution,
        )
        resolution.segments.append(segment)
        if block.slotId and segment.kind == "module":
            resolution.slots.append(block.slotId)
        position = end_index
    if position < len(lines):
        resolution.segments.append(ResolvedSegment(text="".join(lines[position:]), kind="text"))
    return resolution

def _expand_slot(
    slot: SlotRef,
    *,
    project_root,
    library,
    variables: Dict[str, str],
    host_path: str,
    asset_root,
    stack: Tuple[str, ...],
    depth: int,
    max_depth: int,
    slot_overrides: Dict[str, Dict[str, object]],
    strict: bool,
    module_defaults: Dict[str, str],
    resolution: Resolution,
) -> ResolvedSegment:
    """展开一个固定引用；任何缺项都降级为可读说明，不阻断其余正文。"""
    override = slot_overrides.get(slot.slotId) or {}
    version = str(override.get("version") or "") or slot.version or "0"
    module_id = str(override.get("moduleId") or "") or slot.moduleId
    params = dict(slot.params)
    params.update({str(k): str(v) for k, v in dict(override.get("params") or {}).items()})
    heading_offset = slot.headingOffset
    if override.get("headingOffset") is not None:
        try:
            heading_offset = int(override.get("headingOffset"))
        except (TypeError, ValueError):
            resolution.warnings.append(
                "slot {0} 的 headingOffset 覆盖值非法，已沿用原值".format(slot.slotId or module_id)
            )

    identity = "{0}@{1}".format(module_id, version)
    if identity in stack:
        text = CYCLE_STOP_TEMPLATE.format(module=module_id, version=version) + "\n"
        message = "检测到循环引用，已停止该引用展开：{0}".format(" → ".join(list(stack) + [identity]))
        resolution.warnings.append(message)
        if strict:
            resolution.errors.append(message)
        return ResolvedSegment(
            text=text,
            kind="module",
            moduleId=module_id,
            version=version,
            slotId=slot.slotId,
            degraded=True,
            warnings=[message],
        )
    if depth >= max_depth:
        text = MISSING_SLOT_TEMPLATE.format(module=module_id, version=version) + "\n"
        message = "模块嵌套超过 {0} 层，已按占位继续：{1}".format(max_depth, identity)
        resolution.warnings.append(message)
        if strict:
            resolution.errors.append(message)
        return ResolvedSegment(
            text=text,
            kind="module",
            moduleId=module_id,
            version=version,
            slotId=slot.slotId,
            degraded=True,
            warnings=[message],
        )

    directory, module, origin = _find_module_directory(project_root, library, module_id, version)
    if directory is None:
        reason = "库中也没有同版本缓存" if library is not None else "未配置模块库"
        text = module_lib.missing_module_placeholder(module_id, version, reason=reason) + "\n"
        message = "模块 {0} 未找到固定副本（{1}）".format(identity, reason)
        resolution.warnings.append(message)
        if strict:
            resolution.errors.append(message)
        return ResolvedSegment(
            text=text,
            kind="module",
            moduleId=module_id,
            version=version,
            slotId=slot.slotId,
            degraded=True,
            warnings=[message],
        )

    warnings: List[str] = []
    if origin == "library-cache":
        message = "项目内无 {0} 固定副本，已用库中同版本缓存继续".format(identity)
        warnings.append(message)
        resolution.warnings.append(message)

    body, _body_file = _read_module_body(directory, module)
    body_hash = sha256_text(body)
    if module is not None and not body:
        message = "模块 {0} 正文为空，已按占位继续".format(identity)
        warnings.append(message)
        resolution.warnings.append(message)
        text = MISSING_SLOT_TEMPLATE.format(module=module_id, version=version) + "\n"
        return ResolvedSegment(
            text=text,
            kind="module",
            moduleId=module_id,
            version=version,
            slotId=slot.slotId,
            moduleDir=directory,
            degraded=True,
            warnings=warnings,
        )

    defaults = dict(module_defaults)
    if module is not None:
        defaults.update(module.parameter_defaults())
    declared_only = set(defaults.keys())
    applied: Dict[str, str] = {}
    for key, value in variables.items():
        if key.startswith("module.") and key[len("module."):] in declared_only:
            applied[key[len("module."):]] = value
    for key, value in variables.items():
        if key in declared_only:
            applied.setdefault(key, value)
    applied.update(params)
    effective_inputs = dict(applied)
    params_from_declared: List[str] = []
    text, undeclared, param_warnings = module_lib.apply_module_parameters(
        body, defaults, effective_inputs
    )
    for warning in param_warnings:
        warnings.append(warning)
    for name in undeclared:
        if name not in params_from_declared:
            params_from_declared.append(name)
    for name in declared_only:
        if name not in effective_inputs:
            params_from_declared.append(name)
    for name in effective_inputs:
        if name in declared_only and name not in params_from_declared:
            params_from_declared.append(name)

    if heading_offset:
        text, heading_warnings = module_lib.shift_headings(text, heading_offset)
        warnings.extend(heading_warnings)

    resources: Dict[str, Path] = {}
    declared_resources: Dict[str, Path] = {}
    if module is not None:
        for resource in module.resources:
            resolved = module_lib.resolve_module_asset(directory, resource.path)
            if resolved is None:
                resolved = module_lib.resolve_module_asset(directory, Path(resource.path).name)
            if resolved is not None and resolved.is_file():
                declared_resources[resource.path] = resolved
                resources[resource.path] = resolved
                continue
            message = "模块资源不可用，已按可读占位继续：{0}".format(resource.path)
            warnings.append(message)
            resolution.warnings.append(message)

    base_dir = Path(asset_root) if asset_root is not None else (
        Path(project_root) if project_root is not None else None
    )

    def _mapper(target: str) -> Optional[str]:
        relative = str(target).replace("\\", "/")
        resolved = declared_resources.get(relative)
        if resolved is None:
            resolved = module_lib.resolve_module_asset(directory, relative)
        if resolved is None:
            return None
        if not resolved.is_file():
            resolution.warnings.append(
                "模块资源缺失：{0}（{1}）".format(relative, identity)
            )
            return None
        resources.setdefault(relative, resolved)
        if base_dir is None:
            return resolved.as_posix()
        return module_lib.relative_asset_display(resolved, base_dir)

    text, unresolved = module_lib.rewrite_resource_paths(text, _mapper)
    for target in unresolved:
        message = "模块资源无法改写为本地可用路径，已保留原引用：{0}".format(target)
        if message not in warnings:
            warnings.append(message)

    nested = _resolve(
        text,
        project_root=project_root,
        library=library,
        variables=variables,
        host_path=host_path,
        asset_root=asset_root,
        stack=tuple(list(stack) + [identity]),
        depth=depth + 1,
        max_depth=max_depth,
        slot_overrides=slot_overrides,
        strict=strict,
        module_defaults=module_defaults,
    )
    for warning in nested.warnings:
        if warning not in warnings:
            warnings.append(warning)
    resolution.warnings.extend(warning for warning in nested.warnings if warning not in resolution.warnings)
    resolution.errors.extend(nested.errors)
    resources.update(nested.resources())
    dependency_hashes = {identity: body_hash}
    dependency_hashes.update(nested.dependencies)

    for warning in warnings:
        if warning not in resolution.warnings:
            resolution.warnings.append(warning)
    origin_location = SourceLocation(
        kind="module",
        moduleId=module_id,
        version=version,
        slotId=slot.slotId,
        moduleDir=str(directory),
        hostLine=slot.startLine,
        moduleLine=1,
        hostPath=host_path,
    )
    return ResolvedSegment(
        text=nested.text,
        kind="module",
        origin=origin_location,
        moduleId=module_id,
        version=version,
        slotId=slot.slotId,
        moduleDir=directory,
        params=effective_inputs,
        paramsFromDeclared=params_from_declared,
        resources=resources,
        dependencyHashes=dependency_hashes,
        degraded=bool(nested.degraded),
        warnings=warnings,
    )

# --------------------------------------------------------------------------
# 升级（只影响明确选定的实例）
# --------------------------------------------------------------------------


@dataclass
class VersionDifference:
    """两个模块版本的差异（正文/资源/参数）。"""

    moduleId: str
    fromVersion: str
    toVersion: str
    bodyChanged: bool = False
    titleChanged: bool = False
    parametersAdded: List[str] = field(default_factory=list)
    parametersRemoved: List[str] = field(default_factory=list)
    resourcesAdded: List[str] = field(default_factory=list)
    resourcesRemoved: List[str] = field(default_factory=list)
    resourcesChanged: List[str] = field(default_factory=list)
    summary: str = ""

    @property
    def changed(self) -> bool:
        return any([
            self.bodyChanged, self.titleChanged, self.parametersAdded, self.parametersRemoved,
            self.resourcesAdded, self.resourcesRemoved, self.resourcesChanged,
        ])

    def to_dict(self) -> Dict[str, object]:
        return {
            "moduleId": self.moduleId,
            "fromVersion": self.fromVersion,
            "toVersion": self.toVersion,
            "bodyChanged": self.bodyChanged,
            "titleChanged": self.titleChanged,
            "parametersAdded": list(self.parametersAdded),
            "parametersRemoved": list(self.parametersRemoved),
            "resourcesAdded": list(self.resourcesAdded),
            "resourcesRemoved": list(self.resourcesRemoved),
            "resourcesChanged": list(self.resourcesChanged),
            "summary": self.summary,
        }


def module_difference(current: module_lib.Module, target: module_lib.Module) -> VersionDifference:
    """比较模块两个版本的正文/资源/参数（复用现有差异字段，不新增渲染器）。"""
    difference = VersionDifference(
        moduleId=current.moduleId,
        fromVersion=current.version,
        toVersion=target.version,
        bodyChanged=current.body != target.body,
        titleChanged=current.title != target.title,
    )
    current_params = set(current.declared_names())
    target_params = set(target.declared_names())
    difference.parametersAdded = sorted(target_params - current_params)
    difference.parametersRemoved = sorted(current_params - target_params)
    current_resources = current.resource_hashes()
    target_resources = target.resource_hashes()
    difference.resourcesAdded = sorted(set(target_resources) - set(current_resources))
    difference.resourcesRemoved = sorted(set(current_resources) - set(target_resources))
    difference.resourcesChanged = sorted(
        name for name in set(current_resources) & set(target_resources)
        if current_resources[name] != target_resources[name]
    )
    parts: List[str] = []
    if difference.bodyChanged:
        parts.append("正文有改动")
    if difference.titleChanged:
        parts.append("标题有改动")
    if difference.parametersAdded:
        parts.append("新增参数 {0}".format("、".join(difference.parametersAdded)))
    if difference.parametersRemoved:
        parts.append("移除参数 {0}".format("、".join(difference.parametersRemoved)))
    if difference.resourcesAdded:
        parts.append("新增资源 {0}".format("、".join(difference.resourcesAdded)))
    if difference.resourcesRemoved:
        parts.append("移除资源 {0}".format("、".join(difference.resourcesRemoved)))
    if difference.resourcesChanged:
        parts.append("资源内容变化 {0}".format("、".join(difference.resourcesChanged)))
    difference.summary = "；".join(parts) if parts else "版本内容无差异"
    return difference


@dataclass
class UpgradePlan:
    """一次升级选择：差异 + 受影响实例（复制编辑正文不在其中）。"""

    moduleId: str
    fromVersion: str
    toVersion: str
    difference: VersionDifference
    slots: List[AssemblySlot] = field(default_factory=list)
    copies: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def affected_slot_ids(self) -> List[str]:
        return [slot.slotId for slot in self.slots]

    def to_dict(self) -> Dict[str, object]:
        return {
            "moduleId": self.moduleId,
            "fromVersion": self.fromVersion,
            "toVersion": self.toVersion,
            "difference": self.difference.to_dict(),
            "slots": [slot.slotId for slot in self.slots],
            "copies": list(self.copies),
            "warnings": list(self.warnings),
        }


def plan_upgrade(
    assembly: Assembly,
    module_id: str,
    current: module_lib.Module,
    target: module_lib.Module,
    *,
    host_slots: Optional[Iterable[str]] = None,
) -> UpgradePlan:
    """列出升级差异与受影响 slot；``host_slots`` 限制只看某些宿主（不传看全部）。"""
    selected = {str(item) for item in (host_slots or [])}
    slots = [
        slot for slot in assembly.slots
        if slot.moduleId == module_id and slot.version == current.version
        and (not selected or slot.slotId in selected)
    ]
    plan = UpgradePlan(
        moduleId=module_id,
        fromVersion=current.version,
        toVersion=target.version,
        difference=module_difference(current, target),
        slots=slots,
    )
    if not plan.difference.changed:
        plan.warnings.append("目标版本与项目固定版本内容一致，无需升级")
    return plan


def apply_upgrade(
    assembly: Assembly,
    plan: UpgradePlan,
    *,
    slot_ids: Optional[Iterable[str]] = None,
) -> Tuple[Assembly, List[str]]:
    """只更新明确选定的引用实例；未选中的保持原版本（返回新装配与已更新 slot）。"""
    wanted = {str(item) for item in (slot_ids or [])} or set(plan.affected_slot_ids())
    updated: List[str] = []
    result = Assembly(schemaVersion=assembly.schemaVersion)
    for slot in assembly.slots:
        if slot.slotId in wanted and slot.moduleId == plan.moduleId and slot.version == plan.fromVersion:
            result.slots.append(slot.with_version(plan.toVersion))
            updated.append(slot.slotId)
        else:
            result.slots.append(
                AssemblySlot(
                    slotId=slot.slotId,
                    moduleId=slot.moduleId,
                    version=slot.version,
                    chapter=slot.chapter,
                    params=dict(slot.params),
                    headingOffset=slot.headingOffset,
                )
            )
    return result, updated


def include_items_in_tracking(
    book: InstanceBook,
    resolution: Resolution,
    *,
    host_path: str = "",
    slot_ids: Optional[Iterable[str]] = None,
) -> List[Instance]:
    """把明确纳入追踪的 slot 条目转成宿主实例 UUID（默认不自动纳入分母）。"""
    wanted = {str(item) for item in (slot_ids or [])}
    registered: List[Instance] = []
    for segment in resolution.module_segments():
        if wanted and segment.slotId not in wanted:
            continue
        items = module_lib.parse_doc_items(segment.text)
        if not items:
            registered.append(
                book.register(
                    slot_id=segment.slotId,
                    module_id=segment.moduleId,
                    version=segment.version,
                    origin_item_id="",
                    chapter=host_path,
                    included=True,
                )
            )
            continue
        for item_id, title in items:
            registered.append(
                book.register(
                    slot_id=segment.slotId,
                    module_id=segment.moduleId,
                    version=segment.version,
                    origin_item_id=item_id,
                    title=title,
                    chapter=host_path,
                    included=True,
                )
            )
    return registered


def tracked_copies(book: InstanceBook, resolution: Resolution) -> List[str]:
    """列出已复制编辑但未纳入追踪的 slot（不计覆盖率，仅做提示）。"""
    return [slot_id for slot_id in resolution.copies if not book.by_slot(slot_id)]


def coverage_of(book: InstanceBook) -> Coverage:
    return book.coverage()


__all__ = [
    "SCHEMA_VERSION", "MAX_DEPTH", "ASSEMBLY_RELATIVE", "INSTANCES_RELATIVE",
    "MISSING_SLOT_TEMPLATE", "CYCLE_STOP_TEMPLATE",
    "MODULE_FENCE_RE", "COPY_FENCE_RE",
    "SlotRef", "CopyBlock", "ScanResult", "scan_directives", "strip_directives",
    "canonical_directive", "canonical_copy_block", "parse_attrs", "new_slot_id",
    "AssemblySlot", "Assembly", "Instance", "Coverage", "InstanceBook",
    "SourceLocation", "ResolvedSegment", "Resolution", "ResolutionCache",
    "resolve_body", "VersionDifference", "module_difference", "UpgradePlan",
    "plan_upgrade", "apply_upgrade", "include_items_in_tracking", "tracked_copies",
    "coverage_of",
]