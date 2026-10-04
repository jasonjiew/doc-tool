# -*- coding: utf-8 -*-
"""V4.3 43-D：接收人成果包、补充包用途与副本恢复（复用既有服务）。

不重建打包/恢复引擎：

- ``build_handover_package()`` 调用既有 ``snapshot_package.build_delivery_package``；
- ``package_purpose()`` 只按**包内真实文件**判定用途（可读成果 / 可刷新），
  没有刷新输入就不声称可同源正式化；
- ``recover_to_new_copy()`` 调用既有 ``collection_ops.recover_baseline``，
  只写新副本、冲突换新名、坏项局部跳过。
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: 包用途（来自包内真实内容，不来自调用方声明）。
PURPOSE_READABLE = "readable-results"
PURPOSE_REFRESHABLE = "refreshable"

PURPOSE_LABELS = {
    PURPOSE_READABLE: "可读成果包（没有用于刷新 Word 的原输入，不能声称可同源正式化）",
    PURPOSE_REFRESHABLE: "可刷新包（含原捕获输入，可跨机继续刷新 Word）",
}

#: 判定“含原捕获输入”的真实依据：包内**原捕获目录**（``include_original`` 的产物）。
#: 注意 ``snapshot/`` 本身只是本轮捕获的正文快照，不能单独当作可刷新依据。
REFRESH_INPUT_HINTS = ("snapshot/original/", "original/", "capture/")


@dataclass
class PackageFacts:
    """一个包的真实内容事实（从包内文件读出）。"""

    path: str = ""
    entries: List[str] = field(default_factory=list)
    purpose: str = PURPOSE_READABLE
    offlineEntry: str = ""
    manifestName: str = ""
    refreshInputs: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    broken: List[str] = field(default_factory=list)

    @property
    def purposeLabel(self) -> str:
        return PURPOSE_LABELS.get(self.purpose, self.purpose)

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path, "purpose": self.purpose, "purposeLabel": self.purposeLabel,
            "offlineEntry": self.offlineEntry, "manifestName": self.manifestName,
            "entries": list(self.entries), "refreshInputs": list(self.refreshInputs),
            "missing": list(self.missing), "broken": list(self.broken),
        }


def _iter_zip(path: Path):
    with zipfile.ZipFile(str(path)) as archive:
        for name in archive.namelist():
            yield name


def inspect_package(package) -> PackageFacts:
    """读回包内真实文件清单、离线入口与用途判定依据。"""
    from doc_tool.application.delivery.snapshot_package import (
        PACKAGE_MANIFEST_NAME,
    )

    target = Path(package)
    facts = PackageFacts(path=str(target), manifestName=PACKAGE_MANIFEST_NAME)
    if target.is_dir():
        # 目录形式成果包（``build_delivery_package`` 支持 .zip 或目录）：
        # 必须按真实文件清单读回，按 zip 解析会把完好包判成坏包。
        facts.entries = [
            item.relative_to(target).as_posix()
            for item in sorted(target.rglob("*"))
            if item.is_file()
        ]
    elif target.is_file():
        try:
            facts.entries = list(_iter_zip(target))
        except (OSError, zipfile.BadZipFile) as exc:
            facts.broken.append("包无法读取：{0}".format(exc))
            return facts
    else:
        facts.broken.append("包文件不存在")
        return facts
    for entry in facts.entries:
        if entry.endswith("index.html"):
            facts.offlineEntry = entry
            break
    facts.refreshInputs = [
        entry for entry in facts.entries
        if any(hint in entry for hint in REFRESH_INPUT_HINTS)
    ]
    # 可刷新需要同时有原捕获输入与可正式化的 DOCX；缺任一项按可读成果包标注。
    has_docx = any(entry.startswith("docx/") and entry.endswith(".docx") for entry in facts.entries)
    facts.purpose = (
        PURPOSE_REFRESHABLE if (facts.refreshInputs and has_docx) else PURPOSE_READABLE
    )
    if PACKAGE_MANIFEST_NAME not in facts.entries:
        facts.missing.append(PACKAGE_MANIFEST_NAME)
    if not facts.offlineEntry:
        facts.missing.append("离线入口 index.html")
    return facts


@dataclass
class HandoverOutcome:
    """一次交付包生成的结果。"""

    ok: bool = False
    path: str = ""
    packageId: str = ""
    facts: Optional[PackageFacts] = None
    warnings: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    message: str = ""

    def summary_lines(self) -> List[str]:
        if not self.ok:
            return ["成果包未生成：{0}".format("；".join(self.warnings) or self.message or "未知原因")]
        lines = ["成果包：{0}".format(Path(self.path).name)]
        if self.facts is not None:
            lines.append("用途：{0}".format(self.facts.purposeLabel))
            lines.append("包内文件 {0} 个｜离线入口：{1}".format(
                len(self.facts.entries), self.facts.offlineEntry or "缺失"
            ))
            for item in self.facts.missing:
                lines.append("缺项：{0}".format(item))
        for item in self.skipped:
            lines.append("已跳过：{0}".format(item))
        for item in self.warnings:
            lines.append("提醒：{0}".format(item))
        lines.append("生成本地文件，不自动上传或向他人发送消息")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok, "path": self.path, "packageId": self.packageId,
            "message": self.message, "warnings": list(self.warnings),
            "skipped": list(self.skipped),
            "facts": self.facts.to_dict() if self.facts else None,
        }


def build_handover_package(
    report,
    *,
    destination,
    include_original: bool = False,
    notes: Sequence[str] = (),
    variant_id: str = "",
    offline_source: bool = False,
) -> HandoverOutcome:
    """生成接收人成果包（``offline_source=True`` 时才含源码包内容）。"""
    from doc_tool.application.delivery.snapshot_package import build_delivery_package

    outcome = HandoverOutcome()
    try:
        result = build_delivery_package(
            report, target=destination, variant_id=variant_id,
            include_original=bool(include_original), notes=list(notes or ()),
        )
    except Exception as exc:  # noqa: BLE001 - 打包失败保留原成果
        outcome.warnings.append("打包失败：{0}".format(exc))
        return outcome
    outcome.ok = bool(getattr(result, "ok", False))
    outcome.path = str(getattr(result, "path", "") or "")
    outcome.packageId = str(getattr(result, "packageId", "") or "")
    outcome.message = str(getattr(result, "message", "") or "")
    outcome.warnings.extend(str(item) for item in (getattr(result, "warnings", None) or []))
    outcome.skipped.extend(str(item) for item in (getattr(result, "excluded", None) or []))
    if outcome.ok and outcome.path:
        outcome.facts = inspect_package(outcome.path)
        # 用途只按包内真实内容判定；调用方声明不作为依据。
        if include_original and outcome.facts.purpose != PURPOSE_REFRESHABLE:
            outcome.warnings.append(
                "本次请求包含原捕获，但包内未找到刷新输入：已按可读成果包标注"
            )
    return outcome


@dataclass
class RecoveryOutcome:
    """一次副本恢复的结果。"""

    ok: bool = False
    destination: str = ""
    restored: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    renamed: List[str] = field(default_factory=list)
    message: str = ""

    def summary_lines(self) -> List[str]:
        lines = ["副本恢复：{0}".format(self.destination or "（未生成）")]
        lines.append("已恢复 {0} 项；跳过 {1} 项".format(len(self.restored), len(self.skipped)))
        for item in self.renamed:
            lines.append("冲突换新名：{0}".format(item))
        for item in self.skipped:
            lines.append("跳过：{0}".format(item))
        if not self.ok:
            lines.append(self.message or "恢复未完成")
        return lines

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok, "destination": self.destination,
            "restored": list(self.restored), "skipped": list(self.skipped),
            "renamed": list(self.renamed), "message": self.message,
        }


def _fresh_destination(destination) -> Tuple[Path, bool]:
    target = Path(destination)
    if not target.exists():
        return target, False
    index = 1
    while True:
        candidate = target.with_name("{0}-{1}".format(target.name, index))
        if not candidate.exists():
            return candidate, True
        index += 1


def recover_to_new_copy(root, manifest_path, destination) -> RecoveryOutcome:
    """把所选范围恢复到**新副本**：冲突换新名，坏项跳过，原工程不动。"""
    from doc_tool.application.collection_ops import recover_baseline

    outcome = RecoveryOutcome()
    target, renamed = _fresh_destination(destination)
    outcome.destination = str(target)
    try:
        payload = recover_baseline(root, manifest_path, target, overwrite=False)
    except Exception as exc:  # noqa: BLE001 - 恢复失败保留原工程
        outcome.message = "恢复失败：{0}".format(exc)
        return outcome
    if not isinstance(payload, dict):
        outcome.message = "恢复返回格式不可识别"
        return outcome
    # 既有服务返回 ``restored``/``skipped`` 事实（没有显式 ok 字段）：
    # 有真实恢复项即成功，并保留跳过清单。
    if "ok" in payload or "success" in payload:
        outcome.ok = bool(payload.get("ok", payload.get("success")))
    else:
        outcome.ok = bool(payload.get("restored"))
    for key in ("restored", "written", "copied"):
        value = payload.get(key)
        if isinstance(value, list):
            outcome.restored = [str(item) for item in value]
            break
    for key in ("skipped", "missing", "problems", "broken"):
        value = payload.get(key)
        if isinstance(value, list):
            outcome.skipped.extend(str(item) for item in value)
    if renamed:
        outcome.renamed.append("{0} → {1}".format(Path(destination).name, target.name))
    if not outcome.ok and not outcome.message:
        outcome.message = str(payload.get("error") or payload.get("message") or "恢复未完成")
    return outcome


__all__ = [
    "PURPOSE_READABLE", "PURPOSE_REFRESHABLE", "PURPOSE_LABELS", "REFRESH_INPUT_HINTS",
    "PackageFacts", "HandoverOutcome", "RecoveryOutcome",
    "inspect_package", "build_handover_package", "recover_to_new_copy",
]