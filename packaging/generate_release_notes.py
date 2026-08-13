# -*- coding: utf-8 -*-
"""生成可审计的公共 Release 说明。

任务 9.5：包含版本、提交、校验和、SBOM、已知限制和升级说明的可审计发布说明。

用法：
    python packaging/generate_release_notes.py --output packaging/Output/release-notes.md
    [--setup-exe packaging/Output/DocTool-Setup-X.Y.Z.exe]
    [--sbom packaging/Output/DocTool-X.Y.Z-sbom.txt]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def _checksum(path: Path) -> str:
    """返回文件 SHA-256（小写十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _commit_id() -> str:
    """返回当前短提交标识；无法确定时返回 dev。"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "dev"


def generate_release_notes(
    output: Path,
    setup_exe: Path | None = None,
    sbom: Path | None = None,
) -> str:
    """生成并写出发布说明，返回内容。"""
    from doc_tool.domain.branding import APP_DISPLAY_NAME
    from doc_tool.domain.version import APP_VERSION, get_build_info

    build = get_build_info()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# {0} v{1}".format(APP_DISPLAY_NAME, APP_VERSION),
        "",
        "## 构建来源",
        "- 版本: {0}".format(APP_VERSION),
        "- 提交: {0}".format(build["commit"] or _commit_id()),
        "- 生成时间: {0}".format(now),
        "- 平台: {0} ({1})".format(build["platform"], build["machine"]),
        "",
        "## 安装",
        "- 下载安装包（见 Release 资产），双击运行，按提示安装。",
        "- 默认安装到 %LOCALAPPDATA%\\DocTool（无需管理员权限）。",
        "- 与内部旧版本可并存安装，首次启动会自动迁移窗口/最近项目等偏好。",
        "",
    ]

    if setup_exe is not None and setup_exe.is_file():
        lines.extend([
            "## 校验和",
            "- 安装包 SHA-256: {0}".format(_checksum(setup_exe)),
            "",
        ])

    if sbom is not None and sbom.is_file():
        lines.extend([
            "## 依赖清单（SBOM）",
            "- 见 Release 资产中的 CycloneDX（.cdx.json）与 SPDX（.spdx.json）文件。",
            "- 摘要文本: {0}".format(sbom.name),
            "",
        ])

    lines.extend([
        "## 本版变更",
        "- 大型 Word 文档 → Markdown 章节项目，可编辑、校验并可靠重建为 Word。",
        "- 自包含桌面应用与事务化项目导入；受保护的校验、Word 刷新与原子发布管线。",
        "- 按用户安装、升级与非破坏性卸载。",
        "",
        "## 已知限制",
        "- 正式合并需要交互式 Windows 会话与 Microsoft Word（诊断构建无需 Word）。",
        "- 旧版专用（需求/详细设计）项目可读取与构建，并提供迁移为通用项目的能力。",
        "",
        "## 升级与回滚",
        "- 升级使用相同 AppId 与安装目录，自动关闭旧进程后覆盖。",
        "- 公共版与内部旧版使用不同 AppId/目录，可并存、独立卸载。",
        "- 旧设置（窗口几何、最近项目）在首次启动时只读迁移，旧值保留便于回滚。",
        "",
    ])

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可审计发布说明")
    parser.add_argument("--output", required=True)
    parser.add_argument("--setup-exe", default=None)
    parser.add_argument("--sbom", default=None)
    args = parser.parse_args()
    generate_release_notes(
        Path(args.output),
        Path(args.setup_exe) if args.setup_exe else None,
        Path(args.sbom) if args.sbom else None,
    )
    print("发布说明已生成: {0}".format(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
