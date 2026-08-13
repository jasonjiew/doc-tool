# -*- coding: utf-8 -*-
"""净化公开源码导出：从 Git 跟踪文件生成不含公司材料的公共源码清单。

任务 8.1/8.7：公共仓库应从一个不含敏感历史的净化导出构建。本脚本：

1. 用 ``git ls-files`` 枚举仓库跟踪文件（不含 .gitignore 忽略的本地文件）。
2. 排除公司专用目录与内部记录：``templates/``、``config/``、``content/``、
   ``assets/``、``analysis/``、``migration/legacy/``、``docs/release/``。
3. 把保留文件按相对路径复制到独立输出目录。
4. 校验输出不包含被排除目录、隐藏文件或未跟踪文件，并可选运行泄漏扫描。

用法：
    python packaging/export_public_source.py --output <dir> [--scan]

退出码：
    0 = 导出并校验通过；1 = 发现被排除内容进入输出或扫描未通过。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

# 被排除的路径前缀（相对仓库根）。与 packaging/scan_vocabulary.txt 的
# [sensitive-path] 保持一致；docs/release/ 为内部发布记录，不入公共仓库；
# scripts/migration/ 为内部一次性迁移脚本（含公司源文件名），不入公共仓库。
EXCLUDED_PREFIXES = (
    "templates/",
    "config/",
    "content/",
    "assets/",
    "analysis/",
    "migration/legacy/",
    "scripts/migration/",
    "docs/release/",
    "openspec/changes/",
    ".claude/",
    ".codex/",
)

# 按文件名排除的仓库根旧品牌/专用构建入口与加密 BAT。
EXCLUDED_ROOT_FILES = (
    "启动康尚文档工具.cmd",
    "全部生成.cmd",
    "生成需求说明书.cmd",
    "生成详细设计说明书.cmd",
    "start-claude.bat",
)

# 输出中必须存在的关键文件（防止误排除核心代码）。
REQUIRED_PATHS = (
    "doc_tool/",
    "packaging/",
    "scripts/",
    "README.md",
    "requirements.txt",
    "requirements-build.txt",
    "THIRD_PARTY_LICENSES.txt",
)


def _tracked_files() -> list[str]:
    """返回 git 跟踪的相对路径列表（关闭 quotepath，避免中文路径被引号包裹）。"""
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_excluded(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    if any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    # 仓库根旧品牌/专用构建入口按文件名排除（仅根目录层）。
    if "/" not in normalized and normalized in EXCLUDED_ROOT_FILES:
        return True
    return False


def export_public_source(output: Path) -> tuple[list[str], list[str]]:
    """把净化源码复制到输出目录。返回 (copied, excluded)。

    Raises:
        RuntimeError: git ls-files 失败或输出目录已存在。
    """
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("输出目录非空，请使用新的空目录：{0}".format(output))
    output.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    excluded: list[str] = []
    for rel in _tracked_files():
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        if _is_excluded(rel):
            excluded.append(rel)
            continue
        dest = output / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(rel)
    return copied, excluded


# 导出中允许的隐藏文件（Git 元数据、CI 配置与 OpenSpec 变更元数据）。
ALLOWED_HIDDEN_FILES = {".gitignore", ".gitattributes", ".gitlab-ci.yml", ".openspec.yaml"}


def validate_export(output: Path) -> list[str]:
    """校验导出：无被排除前缀、无隐藏文件、无 .git、含必需路径。"""
    problems: list[str] = []
    output = output.resolve()
    for root, dirs, files in os.walk(output):
        for name in dirs[:]:
            if name.startswith(".") and name not in ALLOWED_HIDDEN_FILES:
                problems.append("隐藏目录进入导出: {0}".format(
                    os.path.relpath(os.path.join(root, name), output)
                ))
                dirs.remove(name)
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), output).replace("\\", "/")
            if _is_excluded(rel):
                problems.append("被排除内容进入导出: {0}".format(rel))
            if name.startswith(".") and name not in ALLOWED_HIDDEN_FILES:
                problems.append("隐藏文件进入导出: {0}".format(rel))
    for required in REQUIRED_PATHS:
        if not (output / required).exists():
            problems.append("缺少必需路径: {0}".format(required))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="净化公开源码导出")
    parser.add_argument("--output", required=True, help="输出目录（必须是新的空目录）")
    parser.add_argument("--scan", action="store_true", help="导出后运行泄漏/品牌扫描")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    try:
        copied, excluded = export_public_source(output)
    except RuntimeError as exc:
        print("[FAIL] {0}".format(exc), file=sys.stderr)
        return 1

    print("导出文件数: {0}，排除文件数: {1}".format(len(copied), len(excluded)))
    if excluded:
        print("被排除（公司材料/内部记录）:")
        for rel in sorted(excluded):
            print("  - {0}".format(rel))

    problems = validate_export(output)
    if problems:
        print("[FAIL] 导出校验未通过:", file=sys.stderr)
        for problem in problems:
            print("  - {0}".format(problem), file=sys.stderr)
        return 1
    print("[PASS] 导出校验通过：无被排除目录、隐藏或未跟踪文件。")

    if args.scan:
        print("运行泄漏/品牌扫描…")
        code = subprocess.run(
            [sys.executable, str(HERE / "scan_leaks.py"), "--source-root", str(output)],
            check=False,
        ).returncode
        if code != 0:
            print("[FAIL] 净化源码泄漏扫描未通过。", file=sys.stderr)
            return code
        print("[PASS] 净化源码泄漏扫描通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
