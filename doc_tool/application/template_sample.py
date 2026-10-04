# -*- coding: utf-8 -*-
"""V4.1 41-C：用所选真实模板生成**隔离小样**。

小样是可选动作：默认使用通用示例内容（不含业务正文），写到每轮独立的目录里，
不覆盖当前项目、不写回模板、不污染旧样例。

- `template_summary`：所选底模的真实内容摘要（与映射/版式/示例内容一起参与复用失效）；
- `render_sample`：渲染通用示例 Markdown（标题列表、长表/多行、宽图、代码、已支持字段）；
- `run_sample`：调用既有 `fill_markdown_with_template` 生成 DOCX，并写出 `sample.json`
  记录实际底模、实际/替代参数、可读成果与 Word 待刷新事实；
- `reuse_key`：模板摘要 + 映射 + 版式 + 示例内容 → 同一目录可复用，任一变化生成新轮。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from uuid import uuid4

#: 通用示例内容（**不含业务正文**）；需要业务片段时由调用方显式传入。
GENERIC_SAMPLE = "\n".join([
    "# 1 示例章节",
    "",
    "这是通用示例正文，用于查看模板的实际样式效果。",
    "",
    "## 1.1 标题层级",
    "",
    "### 1.1.1 三级标题",
    "",
    "- 无序列表项 A",
    "- 无序列表项 B",
    "",
    "1. 有序列表项一",
    "2. 有序列表项二",
    "",
    "## 1.2 长表（多行）",
    "",
    "| 列一 | 列二 | 列三 |",
    "| --- | --- | --- |",
] + [
    "| 行 {0} | 值 {0} | 说明 {0} |".format(index) for index in range(1, 21)
] + [
    "",
    "## 1.3 宽图占位",
    "",
    "![宽图占位](images/sample-wide.png)",
    "",
    "## 1.4 代码",
    "",
    "```python",
    "def sample():",
    "    return '模板小样'",
    "```",
    "",
])


def template_summary(path) -> str:
    """所选底模的真实内容摘要（读失败返回空串，不猜）。"""
    target = Path(path)
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return ""


def reuse_key(*, template_hash: str, mapping, layout, sample_text: str) -> str:
    """复用键：模板摘要 + 映射 + 版式 + 示例内容。任一变化即失效。"""
    payload = json.dumps({
        "template": str(template_hash or ""),
        "mapping": {str(k): int(v) for k, v in dict(mapping or {}).items()},
        "layout": dict(layout or {}),
        "sample": hashlib.sha256(str(sample_text or "").encode("utf-8")).hexdigest(),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class SampleOutcome:
    """一次小样的真实结果。"""

    ok: bool = False
    directory: str = ""
    docxPath: str = ""
    htmlPreview: str = ""
    templatePath: str = ""
    templateSummary: str = ""
    appliedLayout: Dict[str, object] = field(default_factory=dict)
    substituted: List[str] = field(default_factory=list)
    unsupported: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    refreshState: str = "normal"
    wordPending: bool = True
    reused: bool = False
    crossProject: bool = False
    reuseKey: str = ""

    def summary_lines(self) -> List[str]:
        lines = []
        if not self.ok:
            lines.append("小样未生成：{0}".format("；".join(self.warnings) or "未知原因"))
            return lines
        lines.append("小样已生成：{0}".format(Path(self.docxPath).name))
        lines.append("实际底模：{0}（摘要 {1}）".format(
            Path(self.templatePath).name if self.templatePath else "未知",
            (self.templateSummary or "")[:12] or "未知",
        ))
        if self.appliedLayout:
            lines.append("已应用版式字段：{0}".format("、".join(sorted(self.appliedLayout))))
        if self.substituted:
            lines.append("替代参数：{0}".format("；".join(self.substituted[:3])))
        if self.unsupported:
            lines.append("未支持声明（保留原文，未生效）：{0}".format("、".join(sorted(self.unsupported))))
        lines.append("HTML 预览：内容预览，版式与 Word 不完全一致")
        lines.append("Word 分页/目录视觉：{0}".format(
            "待刷新（无 Word 或未刷新）" if self.wordPending else "已刷新"
        ))
        if self.reused:
            lines.append("本轮复用了相同模板/映射/版式的既有小样")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok, "directory": self.directory, "docxPath": self.docxPath,
            "htmlPreview": self.htmlPreview, "templatePath": self.templatePath,
            "templateSummary": self.templateSummary, "appliedLayout": dict(self.appliedLayout),
            "substituted": list(self.substituted), "unsupported": dict(self.unsupported),
            "warnings": list(self.warnings), "refreshState": self.refreshState,
            "wordPending": self.wordPending, "reused": self.reused,
            "crossProject": self.crossProject, "reuseKey": self.reuseKey,
        }


def render_sample_markdown(*, business_text: str = "", asset_lines: Sequence[str] = ()) -> str:
    """渲染示例 Markdown；``business_text`` 只在调用方**明确选择**时才传。"""
    parts = []
    if business_text:
        parts.append(str(business_text))
        parts.append("")
    parts.append(GENERIC_SAMPLE)
    for line in asset_lines or ():
        parts.append(str(line))
    text = "\n".join(parts)
    return text if text.endswith("\n") else text + "\n"


def sample_dir(base_dir, *, key: str) -> Path:
    """每轮独立目录：``<base>/<时间戳>-<key8>-<uuid>``。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return Path(base_dir) / "{0}-{1}-{2}".format(stamp, str(key)[:8], uuid4().hex[:8])


def run_sample(
    template_path,
    base_dir,
    *,
    mapping: Optional[Dict[str, int]] = None,
    layout: Optional[Dict[str, object]] = None,
    known_style_ids: Sequence[str] = (),
    business_text: str = "",
    asset_lines: Sequence[str] = (),
    existing_key: str = "",
    existing_dir: str = "",
    refresh_fields: bool = False,
    project_root: str = "",
) -> SampleOutcome:
    """生成隔离小样：独立目录、可选复用、不覆盖项目与旧样例。"""
    from doc_tool.application.template_fill import fill_markdown_with_template
    from doc_tool.application.template_fill_presets import (
        collect_layout_fields, validate_layout_fields, validate_style_mapping,
    )

    template = Path(template_path)
    outcome = SampleOutcome(templatePath=str(template))
    if not template.is_file():
        outcome.warnings.append("所选底模不存在：{0}".format(template))
        return outcome
    if template.suffix.lower() != ".docx":
        outcome.warnings.append("底模必须是 .docx：{0}".format(template.name))
        return outcome

    summary = template_summary(template)
    outcome.templateSummary = summary
    mapping_valid, dropped, mapping_summary = validate_style_mapping(mapping, known_style_ids)
    layout_source = dict(layout or {})
    layout_valid, layout_problems = validate_layout_fields(layout_source)
    _supported, unsupported = collect_layout_fields(layout_source)
    outcome.appliedLayout = dict(layout_valid)
    outcome.unsupported = dict(unsupported)
    if mapping_summary:
        outcome.substituted.append(mapping_summary)
    outcome.substituted.extend(layout_problems)

    sample_text = render_sample_markdown(business_text=business_text, asset_lines=asset_lines)
    key = reuse_key(
        template_hash=summary, mapping=mapping_valid, layout=layout_valid, sample_text=sample_text,
    )
    outcome.reuseKey = key
    if existing_key and existing_key == key and existing_dir and Path(existing_dir).is_dir():
        existing = Path(existing_dir)
        docx = existing / "sample.docx"
        if docx.is_file():
            outcome.ok = True
            outcome.reused = True
            outcome.directory = str(existing)
            outcome.docxPath = str(docx)
            outcome.htmlPreview = str(existing / "sample-preview" / "index.html")
            manifest = existing / "sample.json"
            if manifest.is_file():
                try:
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    outcome.refreshState = str(payload.get("refreshState") or "normal")
                    outcome.wordPending = bool(payload.get("wordPending", True))
                except (OSError, ValueError):
                    pass
            return outcome

    directory = sample_dir(base_dir, key=key)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "sample.md"
    source.write_text(sample_text, encoding="utf-8")
    docx = directory / "sample.docx"
    try:
        result = fill_markdown_with_template(
            [source], template, docx, heading_style_map=mapping_valid or None,
            refresh_fields=bool(refresh_fields),
        )
    except Exception as exc:  # noqa: BLE001 - 小样失败保留原项目与旧样例
        shutil.rmtree(directory, ignore_errors=True)
        outcome.warnings.append("小样生成失败：{0}".format(exc))
        return outcome

    outcome.ok = True
    outcome.directory = str(directory)
    outcome.docxPath = str(Path(getattr(result, "output", docx) or docx))
    outcome.refreshState = str(getattr(result, "refresh_state", "normal"))
    outcome.wordPending = outcome.refreshState != "ok"
    for warning in list(getattr(result, "warnings", []) or [])[:5]:
        outcome.warnings.append(str(warning))
    if dropped:
        outcome.substituted.append("{0} 项样式映射在底模中不存在，已自动匹配".format(len(dropped)))

    # HTML 内容预览（可选）：真实写出的只读快照目录
    try:
        from doc_tool.application.export.readonly_html import export_readonly_html

        assets_root = project_root or directory
        snapshot = export_readonly_html(
            directory, assets_root, directory / "preview", "", rel_path="sample.md",
            document_assets=True,
        )
        outcome.htmlPreview = str(Path(snapshot.directory) / "index.html")
    except Exception as exc:  # noqa: BLE001 - 无 HTML 预览不影响小样本身
        outcome.warnings.append("HTML 内容预览未生成：{0}".format(exc))

    manifest = {
        "schemaVersion": 1,
        "kind": "template-sample",
        "templatePath": str(template),
        "templateSummary": summary,
        "appliedLayout": dict(layout_valid),
        "unsupportedLayout": dict(unsupported),
        "mapping": dict(mapping_valid),
        "sampleIsGeneric": not bool(business_text),
        "businessTextIncluded": bool(business_text),
        "reuseKey": key,
        "refreshState": outcome.refreshState,
        "wordPending": outcome.wordPending,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    (directory / "sample.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return outcome


__all__ = [
    "GENERIC_SAMPLE", "SampleOutcome", "template_summary", "reuse_key",
    "render_sample_markdown", "sample_dir", "run_sample",
]

# --- V4.1 41-D：更换模板的差异预览与固定包副本 --------------------------------

#: 视为“保留部件边界”的规范包资源（不在这些范围内的部件不声称保留）。
RETAINED_PART_KEYS = ("template.docx", "variables.yml", "terms.yml", "rules.yml")


@dataclass
class TemplateChangePlan:
    """一次模板更换的差异事实（应用前展示，不改动任何配置）。"""

    ok: bool = False
    oldIdentity: str = ""
    newIdentity: str = ""
    oldSource: str = ""
    newSource: str = ""
    oldSummary: str = ""
    newSummary: str = ""
    newPackRoot: str = ""
    sameContent: bool = False
    appliedMapping: Dict[str, int] = field(default_factory=dict)
    droppedMapping: List[str] = field(default_factory=list)
    mappingSummary: str = ""
    oldLayout: Dict[str, object] = field(default_factory=dict)
    newLayout: Dict[str, object] = field(default_factory=dict)
    layoutChanges: List[str] = field(default_factory=list)
    unsupported: Dict[str, object] = field(default_factory=dict)
    retainedParts: List[str] = field(default_factory=list)
    missingParts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        if not self.ok:
            return ["更换模板未完成：{0}".format("；".join(self.warnings) or "未知原因")]
        lines = [
            "旧模板：{0}（摘要 {1}）".format(
                Path(self.oldSource).name if self.oldSource else "未知",
                (self.oldSummary or "")[:12] or "未知",
            ),
            "新模板：{0}（摘要 {1}）".format(
                Path(self.newSource).name if self.newSource else "未知",
                (self.newSummary or "")[:12] or "未知",
            ),
        ]
        if self.sameContent:
            lines.append("新旧模板内容摘要相同：配置变化但底模字节未变")
        if self.appliedMapping:
            lines.append("继续有效映射 {0} 项".format(len(self.appliedMapping)))
        if self.droppedMapping:
            lines.append("失效映射 {0} 项：{1}".format(
                len(self.droppedMapping), "、".join(self.droppedMapping[:5]),
            ))
        if self.layoutChanges:
            lines.append("受支持版式变化：{0}".format("；".join(self.layoutChanges)))
        if self.unsupported:
            lines.append("未支持声明（保留原文，不声称生效）：{0}".format(
                "、".join(sorted(self.unsupported))
            ))
        if self.retainedParts:
            lines.append("保留部件：{0}".format("、".join(self.retainedParts)))
        if self.missingParts:
            lines.append("新模板缺少的部件：{0}".format("、".join(self.missingParts)))
        lines.append("应用只改变所选模板配置；后续正文需明确生成新轮")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok, "oldIdentity": self.oldIdentity, "newIdentity": self.newIdentity,
            "oldSource": self.oldSource, "newSource": self.newSource,
            "oldSummary": self.oldSummary, "newSummary": self.newSummary,
            "newPackRoot": self.newPackRoot,
            "sameContent": self.sameContent, "appliedMapping": dict(self.appliedMapping),
            "droppedMapping": list(self.droppedMapping), "mappingSummary": self.mappingSummary,
            "oldLayout": dict(self.oldLayout), "newLayout": dict(self.newLayout),
            "layoutChanges": list(self.layoutChanges), "unsupported": dict(self.unsupported),
            "retainedParts": list(self.retainedParts), "missingParts": list(self.missingParts),
            "warnings": list(self.warnings),
        }


def _pack_parts(pack_root) -> Dict[str, str]:
    """规范包内的资源部件 → 真实文件摘要（只列真实存在的文件）。"""
    root = Path(pack_root)
    parts: Dict[str, str] = {}
    if not root.is_dir():
        return parts
    for key in RETAINED_PART_KEYS:
        candidate = root / key
        if candidate.is_file():
            parts[key] = template_summary(candidate)
    skeleton = root / "skeleton"
    if skeleton.is_dir():
        files = sorted(path.name for path in skeleton.glob("*.md") if path.is_file())
        if files:
            parts["skeleton"] = ",".join(files)
    return parts


def plan_template_change(
    *,
    old_source="",
    new_source="",
    new_pack_root="",
    current_mapping=None,
    current_layout=None,
    known_style_ids=(),
    new_layout=None,
) -> TemplateChangePlan:
    """更换模板前的真实差异（不写任何配置、不改动项目）。

    - 旧/新身份 = 来源路径 + 内容摘要（同名不同来源可区分）；
    - 有效/失效映射按**新底模实际枚举的样式 ID** 判定；
    - 受支持版式字段逐项比较；未知声明原样保留；
    - 保留部件按规范包真实文件列举，缺失项单列。
    """
    from doc_tool.application.template_fill_presets import (
        collect_layout_fields, validate_layout_fields, validate_style_mapping,
    )

    plan = TemplateChangePlan()
    new_path = Path(str(new_source)) if new_source else Path()
    if not str(new_source) or not new_path.is_file():
        plan.warnings.append("新模板不存在：{0}".format(new_source or "未选择"))
        return plan
    plan.newSource = str(new_path)
    plan.newPackRoot = str(new_pack_root or "")
    plan.newSummary = template_summary(new_path)
    plan.newIdentity = "{0}#{1}".format(plan.newSource, plan.newSummary[:12])
    if old_source:
        old_path = Path(str(old_source))
        plan.oldSource = str(old_path)
        plan.oldSummary = template_summary(old_path) if old_path.is_file() else ""
        plan.oldIdentity = "{0}#{1}".format(plan.oldSource, plan.oldSummary[:12])
        if not old_path.is_file():
            plan.warnings.append("旧模板已不存在，只能按新模板建立配置：{0}".format(old_source))
    plan.sameContent = bool(plan.oldSummary) and plan.oldSummary == plan.newSummary

    mapping_valid, dropped, mapping_summary = validate_style_mapping(current_mapping, known_style_ids)
    plan.appliedMapping = dict(mapping_valid)
    plan.droppedMapping = list(dropped)
    plan.mappingSummary = mapping_summary

    old_layout_source = dict(current_layout or {})
    old_layout_valid, old_problems = validate_layout_fields(old_layout_source)
    new_layout_source = dict(new_layout) if new_layout is not None else dict(current_layout or {})
    new_layout_valid, new_problems = validate_layout_fields(new_layout_source)
    plan.oldLayout = dict(old_layout_valid)
    plan.newLayout = dict(new_layout_valid)
    _supported, unsupported = collect_layout_fields(old_layout_source)
    plan.unsupported = dict(unsupported)
    for key in sorted(set(old_layout_valid) | set(new_layout_valid)):
        before, after = old_layout_valid.get(key, None), new_layout_valid.get(key, None)
        if before != after:
            plan.layoutChanges.append("{0}：{1} → {2}".format(key, before, after))
    plan.warnings.extend(old_problems)
    plan.warnings.extend(new_problems)

    if new_pack_root:
        new_parts = _pack_parts(new_pack_root)
        plan.retainedParts = sorted(new_parts)
        old_parts = _pack_parts(Path(str(old_source)).parent) if old_source else {}
        plan.missingParts = sorted(set(old_parts) - set(new_parts))
    plan.ok = True
    return plan


def editable_copy(pack_root, drafts_dir, *, name: str = ""):
    """固定包需要编辑时生成**制作副本**（不原地修改历史包）。

    返回 ``(draft, path, error)``：``draft`` 是既有 ``PackDraft``，可继续编辑/冻结。
    """
    from doc_tool.application.pack_authoring import draft_from_pack

    root = Path(pack_root)
    if not root.is_dir():
        return None, "", "规范包目录不存在：{0}".format(root)
    label = str(name or "").strip() or "{0}-副本".format(root.name)
    target = Path(drafts_dir) / label
    if target.exists():
        target = Path(drafts_dir) / "{0}-{1}".format(label, uuid4().hex[:8])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        draft = draft_from_pack(root, target)
    except Exception as exc:  # noqa: BLE001 - 副本失败不得改动原包
        return None, "", "生成制作副本失败：{0}".format(exc)
    return draft, str(target), ""


@dataclass
class TemplateSwitchOutcome:
    """一次模板更换的结果（只改所选配置）。"""

    ok: bool = False
    mapping: Dict[str, int] = field(default_factory=dict)
    layout: Dict[str, object] = field(default_factory=dict)
    template: str = ""
    draftPath: str = ""
    nextStep: str = ""
    warnings: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        if not self.ok:
            return ["更换未完成：{0}".format("；".join(self.warnings) or "未知原因")]
        lines = ["已更换模板配置：{0}".format(Path(self.template).name if self.template else "未知")]
        if self.mapping:
            lines.append("生效映射 {0} 项".format(len(self.mapping)))
        if self.layout:
            lines.append("生效版式字段 {0} 项".format(len(self.layout)))
        if self.draftPath:
            lines.append("已生成可编辑制作副本：{0}".format(self.draftPath))
        if self.nextStep:
            lines.append(self.nextStep)
        return lines


def apply_template_change(plan: TemplateChangePlan, *, fixed_pack=False, drafts_dir="", name="") -> TemplateSwitchOutcome:
    """应用差异：只改所选配置；固定包先取制作副本；后续正文明确新轮。"""
    outcome = TemplateSwitchOutcome()
    if not plan.ok:
        outcome.warnings.extend(plan.warnings or ["差异不可用"])
        return outcome
    outcome.ok = True
    outcome.template = plan.newSource
    outcome.mapping = dict(plan.appliedMapping)
    outcome.layout = dict(plan.newLayout)
    if fixed_pack:
        # 固定包：副本的对象是**规范包目录**（不是底模文件）
        pack_source = plan.newPackRoot or str(Path(plan.newSource).parent)
        draft, path, error = editable_copy(pack_source, drafts_dir, name=name)
        if error:
            outcome.warnings.append(error)
        else:
            outcome.draftPath = path
    outcome.nextStep = "本次只改变模板配置；正文成果需按当前内容明确生成新轮（旧成果保留）"
    return outcome


__all__ = [
    "TemplateChangePlan", "TemplateSwitchOutcome", "plan_template_change",
    "apply_template_change", "editable_copy", "RETAINED_PART_KEYS",
]
