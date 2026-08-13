# -*- coding: utf-8 -*-
"""公共发行泄漏扫描（品牌、内网、凭据、未登记资源、OOXML 内容）。

任务 9.1：扩展扫描覆盖 Git 跟踪文件、打包输入、``dist``、安装器与 Release 目录。
任务 8.5：对 DOCX/OOXML ZIP 内部 XML、关系、文档属性、图片元数据和文件名执行内容扫描。

扫描目标：
1. onedir 产出目录（dist/DocTool/）：严格 allowlist + 未登记 DOCX/图片/资源。
2. 净化公开源码导出（``--source-root``）：品牌词表、内网地址、凭据模式、OOXML 内容。
3. Git 仓库跟踪文件：密钥/敏感文件（内部仓库）。

禁止词表来自 ``packaging/scan_vocabulary.txt``（任务 1.4），命中阻断项返回非零。

用法：
    python packaging/scan_leaks.py [--strict] [--dist-dir PATH] [--source-root PATH]
    退出码 0 = 通过，1 = 发现泄漏
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DIST_DIR = REPO_ROOT / "dist" / "DocTool"
ALLOWLIST_FILE = HERE / "allowlist.txt"
VOCAB_FILE = HERE / "scan_vocabulary.txt"

# 允许的 DOCX 文件（净化模板和测试夹具）
ALLOWED_DOCX_PATTERNS = [
    r".*scripts[/\\]tests[/\\]fixtures[/\\].*\.docx$",
]

# 禁止的目录名
FORBIDDEN_DIRS = {"projects", "output", "logs", ".venv", "venv", "env"}

# 禁止的文件扩展名（密钥和敏感配置）
FORBIDDEN_EXTENSIONS = {".env", ".pem", ".pfx", ".key"}

# 禁止的文件名
FORBIDDEN_FILES = {".env", ".env.local", "secrets.yaml", "credentials.json"}


# --- 扫描词表加载与文本扫描 ---


def load_vocabulary(path: Path = VOCAB_FILE) -> Dict[str, List[str]]:
    """加载禁止内容扫描词表，按类别分组。"""
    categories: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            categories.setdefault(current, [])
        elif current is not None:
            categories[current].append(line)
    return categories


_RFC1918_PREFIX_RE = re.compile(r"^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)")


def _is_rfc1918_ip(text: str) -> bool:
    """判断一段文本是否为私有网段 IP（形如 10.x.x.x / 172.16-31.x.x / 192.168.x.x）。"""
    candidate = text.strip()
    return bool(_RFC1918_PREFIX_RE.match(candidate))


_IP_TOKEN_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def scan_text_for_terms(text: str, categories: Dict[str, List[str]], source: str) -> List[str]:
    """扫描文本中的禁止词条（品牌/编号/产品/域名/内网地址）。

    返回 ``source: term (category)`` 命中列表；RFC1918 按完整 IP 判定。
    """
    hits: List[str] = []
    lowered = text.lower()

    def _add(term: str, category: str) -> None:
        hits.append("{0}: {1} ({2})".format(source, term, category))

    for category, terms in categories.items():
        if category == "rfc1918":
            # 从文本中提取完整 IP，再按前缀判定是否内网地址。
            for token in _IP_TOKEN_RE.findall(text):
                if _is_rfc1918_ip(token):
                    _add(token, category)
            continue
        if category == "sensitive-path":
            continue  # 路径类别由路径扫描处理
        for term in terms:
            if term.lower() in lowered:
                _add(term, category)
    return hits


def scan_path_for_terms(rel_path: str, categories: Dict[str, List[str]]) -> List[str]:
    """扫描相对路径是否命中敏感路径前缀或品牌词条。"""
    hits: List[str] = []
    normalized = rel_path.replace("\\", "/").lower()
    for prefix in categories.get("sensitive-path", []):
        if normalized.startswith(prefix.lower().lstrip("/")):
            hits.append("{0}: {1} (sensitive-path)".format(rel_path, prefix))
    for category, terms in categories.items():
        if category in ("sensitive-path", "rfc1918"):
            continue
        lowered = normalized
        for term in terms:
            if term.lower() in lowered:
                hits.append("{0}: {1} ({2})".format(rel_path, term, category))
    return hits


# --- OOXML / DOCX 内容扫描（任务 8.5） ---


def _scan_png_text_chunks(data: bytes, categories: Dict[str, List[str]], source: str) -> List[str]:
    """提取 PNG tEXt/iTXt/zTXt 文本块并扫描禁止词条。"""
    hits: List[str] = []
    pos = 8  # PNG signature
    try:
        while pos + 8 <= len(data):
            length = int.from_bytes(data[pos:pos + 4], "big")
            chunk_type = data[pos + 4:pos + 8]
            chunk_data = data[pos + 8:pos + 8 + length]
            if chunk_type in (b"tEXt", b"iTXt", b"zTXt"):
                try:
                    text = chunk_data.decode("utf-8", errors="replace")
                except UnicodeDecodeError:
                    text = ""
                hits.extend(scan_text_for_terms(text, categories, source))
            pos += 12 + length
            if chunk_type == b"IEND":
                break
    except (IndexError, ValueError):
        pass
    return hits


def scan_ooxml_content(docx_path: Path, categories: Dict[str, List[str]]) -> List[str]:
    """扫描 DOCX/OOXML ZIP 内部：文件名、XML/关系、文档属性、图片元数据。

    返回命中列表；每个命中标注 ``<zip 条目>: <词条> (<类别>)``。
    """
    hits: List[str] = []
    try:
        with zipfile.ZipFile(docx_path) as zf:
            for name in zf.namelist():
                hits.extend(scan_path_for_terms(name, categories))
                lower = name.lower()
                if lower.endswith((".xml", ".rels", ".json", ".txt")):
                    try:
                        text = zf.read(name).decode("utf-8", errors="replace")
                    except (RuntimeError, zipfile.BadZipFile):
                        continue
                    hits.extend(scan_text_for_terms(text, categories, name))
                elif lower.endswith((".png", ".jpg", ".jpeg")):
                    hits.extend(_scan_png_text_chunks(zf.read(name), categories, name))
    except (zipfile.BadZipFile, OSError) as exc:
        hits.append("{0}: 无法读取 DOCX ({1})".format(docx_path.name, exc))
    return hits


# --- 目录/文件扫描 ---


def scan_docx_leaks(root: Path) -> List[str]:
    """扫描未授权的 DOCX 文件。"""
    leaks = []
    for path in root.rglob("*.docx"):
        rel = str(path.relative_to(root))
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


def scan_source_terms(root: Path, categories: Dict[str, List[str]]) -> List[str]:
    """扫描目录（净化源码导出）中的品牌词条、内网地址与 OOXML 内容。"""
    leaks: List[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # 词表文件本身列出禁止词条，是扫描规则而非泄漏内容。
        if path.name in ("scan_vocabulary.txt", "allowlist.txt"):
            continue
        rel = path.relative_to(root).as_posix()
        # 路径命中敏感路径前缀
        leaks.extend(scan_path_for_terms(rel, categories))
        suffix = path.suffix.lower()
        if suffix == ".docx":
            leaks.extend(scan_ooxml_content(path, categories))
        elif suffix in (".py", ".txt", ".md", ".yml", ".yaml", ".json", ".cmd",
                        ".ps1", ".iss", ".spec", ".cfg", ".toml"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            leaks.extend(scan_text_for_terms(text, categories, rel))
    return leaks


def scan_repo_for_secrets(root: Path) -> List[str]:
    """扫描 Git 已跟踪文件中的密钥文件。"""
    import subprocess
    leaks = []
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files"],
            cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False,
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
        if ext == ".docx":
            allowed = any(re.match(p, rel, re.IGNORECASE) for p in ALLOWED_DOCX_PATTERNS)
            if not allowed:
                leaks.append("仓库未授权 DOCX（已跟踪）: {0}".format(rel))
    return leaks


def main() -> int:
    strict = "--strict" in sys.argv
    dist_dir = DIST_DIR
    source_root: Optional[Path] = None
    for i, arg in enumerate(sys.argv):
        if arg == "--dist-dir" and i + 1 < len(sys.argv):
            dist_dir = Path(sys.argv[i + 1])
        if arg == "--source-root" and i + 1 < len(sys.argv):
            source_root = Path(sys.argv[i + 1])

    vocab = load_vocabulary()
    all_leaks: List[str] = []

    # 1. 扫描 onedir 产出（严格：不允许任何生产文档/未登记资源）
    if dist_dir.exists():
        print("扫描 onedir 产出: {0}".format(dist_dir))
        all_leaks.extend(scan_docx_leaks(dist_dir))
        all_leaks.extend(scan_forbidden_dirs(dist_dir))
        all_leaks.extend(scan_forbidden_files(dist_dir))
        all_leaks.extend(scan_source_terms(dist_dir, vocab))
        if strict:
            all_leaks.extend(scan_allowlist(dist_dir))
    else:
        print("跳过 onedir 扫描（目录不存在）: {0}".format(dist_dir))

    # 2. 扫描净化公开源码导出（--source-root）
    if source_root is not None:
        if not source_root.is_dir():
            print("[FAIL] --source-root 目录不存在: {0}".format(source_root), file=sys.stderr)
            return 1
        print("扫描净化源码: {0}".format(source_root))
        all_leaks.extend(scan_source_terms(source_root, vocab))
        all_leaks.extend(scan_forbidden_dirs(source_root))
        all_leaks.extend(scan_forbidden_files(source_root))
    else:
        print("跳过源码词表扫描（未指定 --source-root）")

    # 3. 扫描 Git 已跟踪文件（内部仓库密钥）
    print("扫描 Git 已跟踪文件: {0}".format(REPO_ROOT))
    all_leaks.extend(scan_repo_for_secrets(REPO_ROOT))

    if all_leaks:
        print("\n[FAIL] 发现 {0} 个泄漏:".format(len(all_leaks)), file=sys.stderr)
        for leak in all_leaks:
            print("  - {0}".format(leak), file=sys.stderr)
        return 1

    print("\n[PASS] 未发现生产文档/品牌/内网泄漏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
