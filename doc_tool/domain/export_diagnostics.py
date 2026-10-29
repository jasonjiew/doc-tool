# -*- coding: utf-8 -*-
"""Export diagnostics data structures, Markdown projection, desensitization and persistence.

Complies with the export-diagnostics specification:
- Tracks stages, failed stage, error code, locations, resources, and execution identity.
- Generates human-readable, desensitized Markdown for UI viewing and copying.
- Atomic file persistence into stable export logs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def new_execution_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    rand = os.urandom(4).hex()
    return "exec-{0}-{1}".format(now, rand)


def desensitize_path(path_str: str, project_root: str = "") -> str:
    """脱敏文件路径，移除用户敏感目录（如 C:\\Users\\username）并尽量使用项目相对路径。"""
    if not path_str:
        return ""
    norm = os.path.normpath(path_str)
    if project_root:
        norm_proj = os.path.normpath(project_root)
        try:
            rel = os.path.relpath(norm, norm_proj)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except ValueError:
            pass
    # 脱敏常见 Windows / Unix 用户主目录
    clean = re.sub(r"^[A-Za-z]:[\\/]Users[\\/][^\\/]+", "~", norm)
    clean = re.sub(r"^/home/[^/]+", "~", clean)
    return clean.replace("\\", "/")


def sanitize_text(text: str) -> str:
    """过滤敏感 Token、密码、认证头与异常堆栈局部变量。"""
    if not text:
        return ""
    clean = str(text)
    clean = re.sub(r"(token|secret|password|api[_-]?key|credential)[:=]\s*[\w\.\-]+", r"\1: [REDACTED]", clean, flags=re.IGNORECASE)
    clean = re.sub(r"Bearer\s+[\w\.\-]+", "Bearer [REDACTED]", clean, flags=re.IGNORECASE)
    return clean


@dataclass
class DiagnosticLocation:
    path: str = ""
    line: int = 0
    snippet: str = ""
    verifiable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiagnosticResource:
    reference: str = ""
    source_kind: str = ""  # 'captured', 'module', 'generated'
    resolved_path: str = ""
    sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExportDiagnostics:
    schemaVersion: int = 1
    executionId: str = field(default_factory=new_execution_id)
    roundId: str = ""
    captureId: str = ""  # 捕获未建立时明确为空字符串
    createdAt: str = ""
    stages: List[Dict[str, Any]] = field(default_factory=list)
    failedStage: str = ""
    errorCode: str = ""
    message: str = ""
    locations: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    logRefs: List[str] = field(default_factory=list)
    reportRefs: List[str] = field(default_factory=list)
    saved: bool = False
    savedPath: str = ""
    markdownPath: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["ExportDiagnostics"]:
        if not data or not isinstance(data, dict):
            return None
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        for list_field in ("stages", "locations", "resources", "logRefs", "reportRefs"):
            if list_field in filtered and filtered[list_field] is None:
                filtered[list_field] = []
        return cls(**filtered)

    def desensitize(self, project_root: str = "") -> "ExportDiagnostics":
        """返回一份经过白名单脱敏的诊断副本。"""
        new_diag = ExportDiagnostics.from_dict(self.to_dict()) or ExportDiagnostics()
        new_diag.message = sanitize_text(new_diag.message)
        clean_locations = []
        for loc in new_diag.locations:
            clean_loc = dict(loc)
            clean_loc["path"] = desensitize_path(str(loc.get("path") or ""), project_root)
            clean_loc["snippet"] = sanitize_text(str(loc.get("snippet") or ""))
            clean_locations.append(clean_loc)
        new_diag.locations = clean_locations

        clean_resources = []
        for res in new_diag.resources:
            clean_res = dict(res)
            clean_res["resolved_path"] = desensitize_path(str(res.get("resolved_path") or ""), project_root)
            clean_resources.append(clean_res)
        new_diag.resources = clean_resources

        new_diag.logRefs = [desensitize_path(ref, project_root) for ref in new_diag.logRefs]
        new_diag.reportRefs = [desensitize_path(ref, project_root) for ref in new_diag.reportRefs]
        return new_diag

    def to_markdown(self, project_root: str = "") -> str:
        """生成脱敏且可直接阅读的同源 Markdown 诊断投影。"""
        diag = self.desensitize(project_root)
        lines = [
            "# 导出诊断报告",
            "",
            "- **执行标识**：`{0}`".format(diag.executionId or "未知"),
            "- **导出轮次**：`{0}`".format(diag.roundId or "未知"),
            "- **捕获标识**：`{0}`".format(diag.captureId if diag.captureId else "（未建立捕获快照）"),
            "- **最终结论**：{0}".format(diag.message or "无详细说明"),
            "- **失败阶段**：`{0}`".format(diag.failedStage if diag.failedStage else "无"),
            "- **错误代码**：`{0}`".format(diag.errorCode if diag.errorCode else "无"),
            "- **持久保存**：{0}".format("已保存" if diag.saved else "未持久保存（内存可复制）"),
            "",
            "## 阶段执行事实",
            "",
            "| 阶段 | 状态 | 详细说明 | 错误码 |",
            "| :--- | :--- | :--- | :--- |",
        ]
        if diag.stages:
            for st in diag.stages:
                lines.append(
                    "| {0} | {1} | {2} | {3} |".format(
                        st.get("stage", "-"),
                        st.get("status", "-"),
                        sanitize_text(str(st.get("message") or st.get("detail") or "-")),
                        st.get("errorCode") or st.get("error_code") or "-",
                    )
                )
        else:
            lines.append("| - | 未记录 | 无阶段事件记录 | - |")

        lines.extend([
            "",
            "## 问题源定位",
            "",
        ])
        if diag.locations:
            for idx, loc in enumerate(diag.locations, 1):
                p = loc.get("path") or "未知文件"
                line = loc.get("line") or 0
                snippet = loc.get("snippet") or ""
                verifiable = loc.get("verifiable", True)
                lines.append("{0}. **文件位置**：`{1}:{2}`（{3}）".format(
                    idx, p, line, "位置已核实" if verifiable else "未知/陈旧位置"
                ))
                if snippet:
                    lines.append("   > {0}".format(snippet))
        else:
            lines.append("无具体内容位置问题（可能为全局设置、环境工具或外部 Word 进程异常）。")

        if diag.resources:
            lines.extend([
                "",
                "## 关联资源身份",
                "",
                "| 逻辑引用 | 来源类型 | 解析路径 | 校验哈希 |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for res in diag.resources:
                lines.append(
                    "| `{0}` | {1} | `{2}` | `{3}` |".format(
                        res.get("reference") or "-",
                        res.get("source_kind") or "-",
                        res.get("resolved_path") or "-",
                        (res.get("sha256") or "")[:12] if res.get("sha256") else "-",
                    )
                )

        if diag.logRefs or diag.reportRefs:
            lines.extend([
                "",
                "## 关联日志与报告",
                "",
            ])
            for ref in diag.logRefs:
                lines.append("- 本次日志：`{0}`".format(ref))
            for ref in diag.reportRefs:
                lines.append("- 校验报告：`{0}`".format(ref))

        lines.append("")
        return "\n".join(lines)

    def save(self, target_dir: Path) -> bool:
        """安全原子落盘：写入 diagnostics.json 与 diagnostics.md。"""
        try:
            target_dir = Path(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            json_file = target_dir / "diagnostics.json"
            md_file = target_dir / "diagnostics.md"

            # 写入临时文件再替换
            json_tmp = json_file.with_name("diagnostics.json.tmp")
            md_tmp = md_file.with_name("diagnostics.md.tmp")

            json_tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            md_tmp.write_text(self.to_markdown(), encoding="utf-8")

            try:
                os.replace(str(json_tmp), str(json_file))
            except OSError:
                shutil.move(str(json_tmp), str(json_file))

            try:
                os.replace(str(md_tmp), str(md_file))
            except OSError:
                shutil.move(str(md_tmp), str(md_file))

            self.saved = True
            self.savedPath = str(json_file)
            self.markdownPath = str(md_file)
            return True
        except (OSError, UnicodeError):
            self.saved = False
            self.savedPath = ""
            self.markdownPath = ""
            return False
