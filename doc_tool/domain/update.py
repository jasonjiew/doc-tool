# -*- coding: utf-8 -*-
"""在线自升级领域模型：版本比较、运行形态识别与元数据结构。

不依赖任何 GUI 或网络库，供 CLI 与 GUI 共享。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import glob
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from doc_tool.domain.branding import user_config_dir

DEFAULT_TTL_SECONDS = 86400  # 24 小时检查缓存
UPDATE_STATE_FILE_NAME = "update_state.json"

# SemVer 正则匹配：支持 vX.Y.Z 及预发布后缀 -rc.1, -beta, 等
_SEMVER_RE = re.compile(
    r"^[vV]?(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)


def parse_semver(version_str: str) -> Tuple[int, int, int, str]:
    """解析语义版本字符串。

    返回 (major, minor, patch, prerelease)。
    格式非法时返回 (0, 0, 0, version_str)。
    """
    if not version_str or not isinstance(version_str, str):
        return (0, 0, 0, "")
    match = _SEMVER_RE.match(version_str.strip())
    if not match:
        return (0, 0, 0, version_str.strip())
    major = int(match.group("major"))
    minor = int(match.group("minor") or 0)
    patch = int(match.group("patch") or 0)
    prerelease = match.group("prerelease") or ""
    return (major, minor, patch, prerelease)


def _compare_prerelease(a: str, b: str) -> int:
    """比较预发布标识。

    SemVer 规则：无预发布标识（正式版）高于有预发布标识。
    两者都有时，按段落逐个比较（数字按数值，字母按字典序）。
    a > b 返回 1, a < b 返回 -1, 相等返回 0。
    """
    if not a and not b:
        return 0
    if not a and b:
        return 1
    if a and not b:
        return -1

    parts_a = a.split(".")
    parts_b = b.split(".")
    for pa, pb in zip(parts_a, parts_b):
        if pa == pb:
            continue
        a_is_num = pa.isdigit()
        b_is_num = pb.isdigit()
        if a_is_num and b_is_num:
            return 1 if int(pa) > int(pb) else -1
        if a_is_num and not b_is_num:
            return -1
        if not a_is_num and b_is_num:
            return 1
        return 1 if pa > pb else -1

    if len(parts_a) > len(parts_b):
        return 1
    if len(parts_a) < len(parts_b):
        return -1
    return 0


def is_newer_version(candidate: str, current: str) -> bool:
    """判断 candidate 是否严格高于 current 版本。"""
    cand_parsed = parse_semver(candidate)
    curr_parsed = parse_semver(current)

    # 比较主/次/修订版本
    for c_num, cur_num in zip(cand_parsed[:3], curr_parsed[:3]):
        if c_num > cur_num:
            return True
        if c_num < cur_num:
            return False

    # (major, minor, patch) 均相同，比较 prerelease
    pre_cmp = _compare_prerelease(cand_parsed[3], curr_parsed[3])
    return pre_cmp > 0


def detect_install_mode(
    frozen: Optional[bool] = None,
    executable_path: Optional[str] = None,
) -> str:
    """识别当前运行分发形态。

    返回值：
      - 'source': 源码开发态（sys.frozen == False）
      - 'installer': Inno Setup 安装版（应用目录或 uninst/ 下存在 unins*.exe）
      - 'portable': 免安装便携版（冻结打包但无卸载程序）
    """
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    if not is_frozen:
        return "source"

    exe = executable_path or sys.executable
    app_dir = os.path.dirname(os.path.abspath(exe))

    # Inno Setup 卸载程序通常位于 app_dir 或 app_dir/uninst/
    uninstaller_patterns = [
        os.path.join(app_dir, "unins*.exe"),
        os.path.join(app_dir, "uninst", "unins*.exe"),
    ]
    for pattern in uninstaller_patterns:
        if glob.glob(pattern):
            return "installer"

    return "portable"


def get_update_state_path() -> Path:
    """获取 update_state.json 文件的标准持久化路径。"""
    return Path(user_config_dir()) / UPDATE_STATE_FILE_NAME


@dataclass
class ReleaseManifest:
    """发布版本完整元数据。"""

    tag_name: str = ""
    version: str = ""
    published_at: str = ""
    release_notes: str = ""
    installer_url: str = ""
    installer_sha256: str = ""
    portable_url: str = ""
    portable_sha256: str = ""
    prerelease: bool = False
    draft: bool = False
    raw_assets: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReleaseManifest:
        if not isinstance(data, dict):
            return cls()
        return cls(
            tag_name=str(data.get("tag_name") or ""),
            version=str(data.get("version") or ""),
            published_at=str(data.get("published_at") or ""),
            release_notes=str(data.get("release_notes") or ""),
            installer_url=str(data.get("installer_url") or ""),
            installer_sha256=str(data.get("installer_sha256") or "").lower(),
            portable_url=str(data.get("portable_url") or ""),
            portable_sha256=str(data.get("portable_sha256") or "").lower(),
            prerelease=bool(data.get("prerelease", False)),
            draft=bool(data.get("draft", False)),
            raw_assets=list(data.get("raw_assets") or []),
        )


@dataclass
class UpdateState:
    """本地升级偏好与 TTL 缓存状态。"""

    last_checked_at: str = ""
    skipped_version: str = ""
    auto_check: bool = True
    custom_endpoint: str = ""
    cached_manifest: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UpdateState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            last_checked_at=str(data.get("last_checked_at") or ""),
            skipped_version=str(data.get("skipped_version") or ""),
            auto_check=bool(data.get("auto_check", True)),
            custom_endpoint=str(data.get("custom_endpoint") or ""),
            cached_manifest=data.get("cached_manifest") if isinstance(data.get("cached_manifest"), dict) else None,
        )
