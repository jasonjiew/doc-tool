# -*- coding: utf-8 -*-
"""生成可审计的最新版本元数据索引 (latest.json)。

发布流水线在打包签名完成后调用，产物随 Release 资产一同发布，
供客户端一键检查时以轻量静态文件形式优先拉取，规避 GitHub REST API 频控。

用法：
    python packaging/generate_latest_json.py --output packaging/Output/latest.json
    [--version 3.0.1]
    [--setup-exe packaging/Output/DocTool-Setup-3.0.1.exe]
    [--setup-sha256 packaging/Output/DocTool-Setup-3.0.1.exe.sha256]
    [--portable-zip packaging/Output/DocTool-3.0.1-portable.zip]
    [--portable-sha256 packaging/Output/DocTool-3.0.1-portable.zip.sha256]
    [--release-notes packaging/Output/release-notes.md]
    [--repo-url https://github.com/wangjie0721666-web/doc-tool]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))


def _calc_sha256(path: Path) -> str:
    """计算文件 SHA-256 小写十六进制。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _read_sha256(path_or_str: Optional[str], fallback_file: Optional[Path]) -> str:
    """从 .sha256 文件、纯字符串或原二进制文件提取 SHA-256。"""
    if path_or_str:
        p = Path(path_or_str)
        if p.is_file():
            content = p.read_text(encoding="utf-8", errors="replace").strip()
            # 常见格式: "<hash>  <filename>" 或纯 "<hash>"
            parts = content.split()
            if parts:
                return parts[0].strip().lower()
        elif len(path_or_str.strip()) == 64:
            return path_or_str.strip().lower()

    if fallback_file and fallback_file.is_file():
        return _calc_sha256(fallback_file)
    return ""


def generate_latest_json(
    output_path: Path,
    version: Optional[str] = None,
    setup_exe: Optional[Path] = None,
    setup_sha256: Optional[str] = None,
    portable_zip: Optional[Path] = None,
    portable_sha256: Optional[str] = None,
    release_notes: Optional[Path] = None,
    repo_url: Optional[str] = None,
    prerelease: bool = False,
) -> dict:
    """生成 latest.json 数据结构并写出到目标路径。"""
    from doc_tool.domain.branding import PUBLIC_URL
    from doc_tool.domain.version import APP_VERSION

    v = (version or APP_VERSION).strip()
    clean_version = v[1:] if v.startswith(("v", "V")) else v
    tag_name = f"v{clean_version}"
    base_url = (repo_url or PUBLIC_URL).rstrip("/")

    # 计算/读取校验值
    installer_hash = _read_sha256(setup_sha256, setup_exe)
    portable_hash = _read_sha256(portable_sha256, portable_zip)

    # 资产文件名与下载链接
    installer_name = f"DocTool-Setup-{clean_version}.exe"
    portable_name = f"DocTool-{clean_version}-portable.zip"
    installer_url = f"{base_url}/releases/download/{tag_name}/{installer_name}"
    portable_url = f"{base_url}/releases/download/{tag_name}/{portable_name}"

    notes_text = ""
    if release_notes and Path(release_notes).is_file():
        notes_text = Path(release_notes).read_text(encoding="utf-8", errors="replace").strip()

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = {
        "schemaVersion": 1,
        "tag_name": tag_name,
        "version": clean_version,
        "published_at": now_iso,
        "release_notes": notes_text,
        "installer_url": installer_url,
        "installer_sha256": installer_hash,
        "portable_url": portable_url,
        "portable_sha256": portable_hash,
        "prerelease": prerelease,
        "installer": {
            "name": installer_name,
            "url": installer_url,
            "sha256": installer_hash,
        },
        "portable": {
            "name": portable_name,
            "url": portable_url,
            "sha256": portable_hash,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 latest.json 版本元数据索引")
    parser.add_argument("--output", required=True, help="输出 latest.json 路径")
    parser.add_argument("--version", default=None, help="版本号，缺省读取 APP_VERSION")
    parser.add_argument("--setup-exe", default=None, help="安装程序 exe 路径")
    parser.add_argument("--setup-sha256", default=None, help="安装程序 sha256 文件或十六进制")
    parser.add_argument("--portable-zip", default=None, help="便携包 zip 路径")
    parser.add_argument("--portable-sha256", default=None, help="便携包 sha256 文件或十六进制")
    parser.add_argument("--release-notes", default=None, help="release-notes.md 路径")
    parser.add_argument("--repo-url", default=None, help="GitHub 仓库 URL")
    parser.add_argument("--prerelease", action="store_true", help="是否为预发布版本")

    args = parser.parse_args()
    generate_latest_json(
        output_path=Path(args.output),
        version=args.version,
        setup_exe=Path(args.setup_exe) if args.setup_exe else None,
        setup_sha256=args.setup_sha256,
        portable_zip=Path(args.portable_zip) if args.portable_zip else None,
        portable_sha256=args.portable_sha256,
        release_notes=Path(args.release_notes) if args.release_notes else None,
        repo_url=args.repo_url,
        prerelease=args.prerelease,
    )
    print(f"latest.json 已生成: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
