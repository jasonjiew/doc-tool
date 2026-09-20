# -*- coding: utf-8 -*-
"""自动为修订记录表摘要补充章节文档超链接。

用法示例：
    # 为指定项目的 _revision_record.md 全量自动赋值超链接
    python scripts/autolink_revision_record.py --project "D:/path/to/project"

    # 仅为最新一条（正式初稿）赋值超链接
    python scripts/autolink_revision_record.py --project "D:/path/to/project" --latest-only

    # 预览模式（不写盘）
    python scripts/autolink_revision_record.py --project "D:/path/to/project" --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

# 确保 doc_tool 模块可导入
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

def _force_utf8_stdio() -> None:
    """Windows 下非 UTF-8 控制台强制使用 UTF-8 避免打印帮助信息崩溃。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_force_utf8_stdio()

from doc_tool.application.content.revision_record import (
    autolink_revision_record,
)
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths


def autolink_project(
    project_dir: Path | str,
    target_version: Optional[str] = None,
    dry_run: bool = False,
) -> tuple[bool, str, int, int]:
    """为项目目录下的 _revision_record.md 自动赋超链接。

    Returns:
        (success, message, updated_rows, total_links)
    """
    project_root = Path(project_dir).resolve()
    manifest_path = project_root / "project.yml"
    if not manifest_path.is_file():
        return False, f"未找到 project.yml: {project_root}", 0, 0

    try:
        manifest = ProjectManifest.load(project_root)
        paths = ProjectPaths(project_root)
        content_root = paths.resolve(manifest.relative_content_root())
        rev_path = content_root / "_revision_record.md"

        if not rev_path.is_file():
            return False, f"未找到修订记录文件: {rev_path}", 0, 0

        updated_rows, total_links, _ = autolink_revision_record(
            rev_path,
            content_root=content_root,
            target_version=target_version,
            dry_run=dry_run,
        )
        mode_str = " [预览]" if dry_run else ""
        msg = f"[{manifest.documentName}]{mode_str} 修订记录: {updated_rows} 行已更新，新增 {total_links} 个文档超链接 -> {rev_path}"
        return True, msg, updated_rows, total_links
    except Exception as exc:
        return False, f"处理失败: {exc}", 0, 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="根据章节目录结构为 _revision_record.md 自动赋值文档超链接"
    )
    parser.add_argument(
        "--project",
        "-p",
        default=".",
        help="文档工程根目录路径（默认当前目录）",
    )
    parser.add_argument(
        "--file",
        "-f",
        help="直接指定 _revision_record.md 文件路径",
    )
    parser.add_argument(
        "--content-root",
        "-c",
        help="内容根目录（配合 --file 使用，默认文件所在父目录）",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="仅为末尾最新一条（正式初稿/当前发版行）赋值超链接",
    )
    parser.add_argument(
        "--version",
        "-v",
        dest="target_version",
        help="指定仅为特定版本（如 V2.6）赋值超链接",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览处理结果，不写入磁盘",
    )
    args = parser.parse_args(argv)

    target_ver = "latest" if args.latest_only else args.target_version

    if args.file:
        file_path = Path(args.file).resolve()
        content_root = Path(args.content_root).resolve() if args.content_root else file_path.parent
        try:
            upd, links, _ = autolink_revision_record(
                file_path,
                content_root=content_root,
                target_version=target_ver,
                dry_run=args.dry_run,
            )
            mode_str = " [预览]" if args.dry_run else ""
            print(f"[OK]{mode_str} 更新 {upd} 行，新增 {links} 个超链接: {file_path}")
            return 0
        except Exception as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1

    success, msg, _, _ = autolink_project(
        args.project,
        target_version=target_ver,
        dry_run=args.dry_run,
    )
    if success:
        print(f"[OK] {msg}")
        return 0
    else:
        print(f"[FAIL] {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
