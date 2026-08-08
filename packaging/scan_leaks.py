# -*- coding: utf-8 -*-
"""生产文档泄漏扫描。

任务 9.5：扫描打包产出，发现未允许的 DOCX 或 projects/output/logs 目录时阻断打包。

扫描范围：
1. onedir 产出目录（dist/KonsungDocTool/）
2. Git 仓库工作树（防止生产文档进入源码 Release）

阻断条件：
- 发现 .docx 文件但不在 templates/ 白名单中
- 发现 projects/、output/、logs/ 目录
- 发现 .env、.pem、.pfx、.key 等密钥文件
- 发现 allowlist.txt 之外的未知文件（可选严格模式）

用法：
    python packaging/scan_leaks.py [--strict] [--dist-dir PATH]
    退出码 0 = 通过，1 = 发现泄漏
"""

from __future__ import annotations

import os
import re
import sys
import fnmatch
from pathlib import Path
from typing import List, Set, Tuple

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DIST_DIR = REPO_ROOT / "dist" / "KonsungDocTool"
ALLOWLIST_FILE = HERE / "allowlist.txt"

# 允许的 DOCX 文件（净化模板和测试夹具）
ALLOWED_DOCX_PATTERNS = [
    r".*templates[/\\].*-template\.docx$",
    r".*scripts[/\\]tests[/\\]fixtures[/\\].*\.docx$",
]

# 禁止的目录名
FORBIDDEN_DIRS = {"projects", "output", "logs", ".venv", "venv", "env"}

# 禁止的文件扩展名（密钥和敏感配置）
FORBIDDEN_EXTENSIONS = {".env", ".pem", ".pfx", ".key"}

# 禁止的文件名
FORBIDDEN_FILES = {".env", ".env.local", "secrets.yaml", "credentials.json"}


def scan_docx_leaks(root: Path) -> List[str]:
    """扫描未授权的 DOCX 文件。"""
    leaks = []
    for path in root.rglob("*.docx"):
        rel = str(path.relative_to(root))
        # 检查是否匹配允许模式
        allowed = any(re.match(p, rel, re.IGNORECASE) for p in ALLOWED_DOCX_PATTERNS)
        if not allowed:
            leaks.append("未授权 DOCX: {0}".format(rel))
    return leaks


def scan_forbidden_dirs(root: Path) -> List[str]:
    """扫描禁止的目录。"""
    leaks = []
    for dirpath, dirnames, _ in os.walk(root):
        for name in dirnames:
            if name.lower() in FORBIDDEN_DIRS:
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                leaks.append("禁止目录: {0}".format(rel))
    return leaks


def scan_forbidden_files(root: Path) -> List[str]:
    """扫描禁止的文件（密钥、敏感配置）。"""
    leaks = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        ext = path.suffix.lower()
        rel = str(path.relative_to(root))
        if name in FORBIDDEN_FILES:
            leaks.append("敏感文件: {0}".format(rel))
        elif ext in FORBIDDEN_EXTENSIONS:
            leaks.append("密钥文件: {0}".format(rel))
    return leaks


def load_allowlist(path: Path = ALLOWLIST_FILE) -> List[str]:
    """加载打包文件允许模式。"""
    patterns: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            patterns.append(value.replace("\\", "/"))
    return patterns


def scan_allowlist(root: Path, patterns: List[str] | None = None) -> List[str]:
    """严格扫描 onedir 中不在允许清单内的文件。"""
    allowed_patterns = patterns if patterns is not None else load_allowlist()
    leaks: List[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not any(
            fnmatch.fnmatchcase(rel.lower(), pattern.lower())
            for pattern in allowed_patterns
        ):
            leaks.append("未在打包允许清单中: {0}".format(rel))
    return leaks


def scan_repo_for_secrets(root: Path) -> List[str]:
    """扫描 Git 已跟踪文件中的密钥文件。

    使用 `git ls-files` 获取已跟踪文件列表，避免报告被 .gitignore 忽略的本地文件。
    """
    import subprocess
    leaks = []
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            print("警告: git ls-files 失败，跳过仓库扫描", file=sys.stderr)
            return []
        tracked_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (OSError, subprocess.SubprocessError):
        print("警告: git 不可用，跳过仓库扫描", file=sys.stderr)
        return []

    for rel in tracked_files:
        path = root / rel
        if not path.is_file():
            continue
        name = path.name.lower()
        ext = path.suffix.lower()
        if name in FORBIDDEN_FILES or ext in FORBIDDEN_EXTENSIONS:
            leaks.append("仓库敏感文件（已跟踪）: {0}".format(rel))
        # 检查已跟踪的 DOCX 是否在白名单中
        if ext == ".docx":
            allowed = any(re.match(p, rel, re.IGNORECASE) for p in ALLOWED_DOCX_PATTERNS)
            if not allowed:
                leaks.append("仓库未授权 DOCX（已跟踪）: {0}".format(rel))
    return leaks


def main() -> int:
    strict = "--strict" in sys.argv
    dist_dir = DIST_DIR
    for i, arg in enumerate(sys.argv):
        if arg == "--dist-dir" and i + 1 < len(sys.argv):
            dist_dir = Path(sys.argv[i + 1])

    all_leaks: List[str] = []

    # 1. 扫描 onedir 产出（严格：不允许任何生产文档）
    if dist_dir.exists():
        print("扫描 onedir 产出: {0}".format(dist_dir))
        all_leaks.extend(scan_docx_leaks(dist_dir))
        all_leaks.extend(scan_forbidden_dirs(dist_dir))
        all_leaks.extend(scan_forbidden_files(dist_dir))
        if strict:
            all_leaks.extend(scan_allowlist(dist_dir))
    else:
        print("跳过 onedir 扫描（目录不存在）: {0}".format(dist_dir))

    # 2. 扫描 Git 已跟踪文件（不报告被 .gitignore 忽略的本地文件）
    print("扫描 Git 已跟踪文件: {0}".format(REPO_ROOT))
    all_leaks.extend(scan_repo_for_secrets(REPO_ROOT))

    if all_leaks:
        print("\n[FAIL] 发现 {0} 个泄漏:".format(len(all_leaks)), file=sys.stderr)
        for leak in all_leaks:
            print("  - {0}".format(leak), file=sys.stderr)
        return 1

    print("\n[PASS] 未发现生产文档泄漏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
