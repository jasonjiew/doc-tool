# -*- coding: utf-8 -*-
"""自升级服务：元数据拉取、TTL 缓存、SHA-256 校验与双形态执行。

严格使用 Python 标准库，不引入 PySide6 或 requests，供 CLI 与 GUI 共享。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from doc_tool.domain.branding import PUBLIC_URL
from doc_tool.domain.update import (
    DEFAULT_TTL_SECONDS,
    ReleaseManifest,
    UpdateState,
    detect_install_mode,
    get_update_state_path,
    is_newer_version,
)
from doc_tool.domain.version import APP_VERSION

DEFAULT_CHECK_TIMEOUT = 5.0
DEFAULT_DOWNLOAD_TIMEOUT = 60.0

DEFAULT_LATEST_JSON_URL = (
    f"{PUBLIC_URL.rstrip('/')}/releases/latest/download/latest.json"
)
DEFAULT_GITHUB_API_URL = (
    "https://api.github.com/repos/wangjie0721666-web/doc-tool/releases/latest"
)


class UpdateVerificationError(Exception):
    """升级包校验失败（SHA-256 不匹配或二进制头损坏）。"""


@dataclass
class UpdateCheckResult:
    """更新检查结果。"""

    has_update: bool = False
    current_version: str = ""
    latest_version: str = ""
    manifest: Optional[ReleaseManifest] = None
    install_mode: str = "source"
    is_skipped: bool = False
    error: Optional[str] = None
    from_cache: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hasUpdate": self.has_update,
            "currentVersion": self.current_version,
            "latestVersion": self.latest_version,
            "installMode": self.install_mode,
            "isSkipped": self.is_skipped,
            "error": self.error,
            "fromCache": self.from_cache,
            "manifest": self.manifest.to_dict() if self.manifest else None,
        }


def load_update_state() -> UpdateState:
    """加载本地升级状态缓存，损坏时安全重置。"""
    path = get_update_state_path()
    if not path.is_file():
        return UpdateState()
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return UpdateState.from_dict(data)
    except Exception:
        return UpdateState()


def save_update_state(state: UpdateState) -> None:
    """原子保存本地升级状态。"""
    path = get_update_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if path.exists():
            path.unlink()
        tmp.rename(path)
    except OSError:
        pass


def skip_version(version: str) -> None:
    """设置跳过特定版本。"""
    state = load_update_state()
    state.skipped_version = version.strip()
    save_update_state(state)


def set_auto_check(enabled: bool) -> None:
    """设置是否开启自动检查。"""
    state = load_update_state()
    state.auto_check = bool(enabled)
    save_update_state(state)


def set_custom_endpoint(endpoint: str) -> None:
    """配置自定义升级源 URL。"""
    state = load_update_state()
    state.custom_endpoint = endpoint.strip()
    save_update_state(state)


def _http_get(url: str, timeout: float = DEFAULT_CHECK_TIMEOUT) -> bytes:
    """通过 urllib 发起带有 User-Agent 的 GET 请求。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"DocTool/{APP_VERSION} (Python/{sys.version.split()[0]})",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_from_github_api(
    api_url: str = DEFAULT_GITHUB_API_URL, timeout: float = DEFAULT_CHECK_TIMEOUT
) -> ReleaseManifest:
    """从 GitHub REST API 获取最新版本元数据并组装 ReleaseManifest。"""
    raw = _http_get(api_url, timeout=timeout)
    data = json.loads(raw.decode("utf-8"))

    tag_name = data.get("tag_name", "")
    version = tag_name.lstrip("vV")
    body = data.get("body", "")
    published_at = data.get("published_at", "")
    prerelease = bool(data.get("prerelease", False))
    draft = bool(data.get("draft", False))

    installer_url = ""
    installer_sha256 = ""
    portable_url = ""
    portable_sha256 = ""

    assets = data.get("assets", [])
    sha_map: Dict[str, str] = {}

    # 先提取所有 .sha256 资产
    for a in assets:
        name = a.get("name", "")
        if name.endswith(".sha256") and a.get("browser_download_url"):
            try:
                sha_text = _http_get(a["browser_download_url"], timeout=timeout).decode("utf-8", errors="replace").strip()
                tokens = sha_text.split()
                if tokens:
                    target_name = name[:-7]
                    sha_map[target_name] = tokens[0].lower()
            except Exception:
                pass

    # 匹配安装包与便携包
    for a in assets:
        name = a.get("name", "")
        dl_url = a.get("browser_download_url", "")
        if name.startswith("DocTool-Setup-") and name.endswith(".exe"):
            installer_url = dl_url
            installer_sha256 = sha_map.get(name, "")
        elif name.startswith("DocTool-") and name.endswith("-portable.zip"):
            portable_url = dl_url
            portable_sha256 = sha_map.get(name, "")

    return ReleaseManifest(
        tag_name=tag_name,
        version=version,
        published_at=published_at,
        release_notes=body,
        installer_url=installer_url,
        installer_sha256=installer_sha256,
        portable_url=portable_url,
        portable_sha256=portable_sha256,
        prerelease=prerelease,
        draft=draft,
        raw_assets=assets,
    )


def check_for_updates(
    force: bool = False,
    custom_url: Optional[str] = None,
    timeout: float = DEFAULT_CHECK_TIMEOUT,
    current_version: Optional[str] = None,
    custom_endpoint: Optional[str] = None,
) -> UpdateCheckResult:
    """检查在线更新。

    支持 24 小时 TTL 缓存、跳过版本过滤，以及 latest.json 优先、404 回退 REST API 双通道。
    异常时静默降级，不抛出阻断异常。
    """
    curr_v = current_version or APP_VERSION
    mode = detect_install_mode()
    state = load_update_state()

    # 1. 检查 TTL 缓存（非强制刷新模式）
    if not force and state.last_checked_at and state.cached_manifest:
        try:
            last_dt = datetime.fromisoformat(state.last_checked_at)
            if datetime.now(timezone.utc) - last_dt < timedelta(seconds=DEFAULT_TTL_SECONDS):
                manifest = ReleaseManifest.from_dict(state.cached_manifest)
                newer = is_newer_version(manifest.version, curr_v)
                is_skip = bool(state.skipped_version and manifest.version == state.skipped_version)
                return UpdateCheckResult(
                    has_update=newer and not is_skip,
                    current_version=curr_v,
                    latest_version=manifest.version,
                    manifest=manifest,
                    install_mode=mode,
                    is_skipped=is_skip,
                    from_cache=True,
                )
        except Exception:
            pass

    # 2. 确定检查 URL
    effective_url = custom_url or custom_endpoint
    latest_url = (
        effective_url
        or os.environ.get("DOC_TOOL_UPDATE_URL")
        or state.custom_endpoint
        or DEFAULT_LATEST_JSON_URL
    )

    manifest: Optional[ReleaseManifest] = None
    error_msg: Optional[str] = None

    # 3. 优先拉取 latest.json
    try:
        raw_json = _http_get(latest_url, timeout=timeout)
        data = json.loads(raw_json.decode("utf-8"))
        manifest = ReleaseManifest.from_dict(data)
    except urllib.error.HTTPError as http_err:
        if http_err.code == 404 and latest_url == DEFAULT_LATEST_JSON_URL:
            # 404 时回退 GitHub REST API
            try:
                manifest = _fetch_from_github_api(DEFAULT_GITHUB_API_URL, timeout=timeout)
            except Exception as api_err:
                error_msg = f"GitHub API 请求失败: {api_err}"
        elif http_err.code == 403:
            error_msg = "请求受到速率限制 (HTTP 403 Rate Limit)"
        else:
            error_msg = f"HTTP 请求失败 ({http_err.code}): {http_err.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as net_err:
        error_msg = f"网络不可达或超时: {net_err}"
    except Exception as exc:
        error_msg = f"检查更新异常: {exc}"

    if manifest is None or not manifest.version:
        return UpdateCheckResult(
            has_update=False,
            current_version=curr_v,
            latest_version="",
            manifest=None,
            install_mode=mode,
            error=error_msg,
        )

    # 4. 判断版本高低与跳过状态
    newer = is_newer_version(manifest.version, curr_v)
    is_skip = bool(state.skipped_version and manifest.version == state.skipped_version)

    # 5. 更新本地缓存
    state.last_checked_at = datetime.now(timezone.utc).isoformat()
    state.cached_manifest = manifest.to_dict()
    save_update_state(state)

    return UpdateCheckResult(
        has_update=newer and not is_skip,
        current_version=curr_v,
        latest_version=manifest.version,
        manifest=manifest,
        install_mode=mode,
        is_skipped=is_skip,
        from_cache=False,
    )


def _get_candidate_temp_dir() -> Path:
    """获取纯 ASCII 临时目录以规避 Windows 中文用户名下安装器崩溃。"""
    try:
        from doc_tool.application.self_heal import _candidate_bases

        bases = _candidate_bases()
        for base in bases:
            p = Path(base) / "doctool_update"
            try:
                p.mkdir(parents=True, exist_ok=True)
                return p
            except OSError:
                continue
    except Exception:
        pass

    # 备选使用系统 tempdir
    td = Path(tempfile.gettempdir()) / "doctool_update"
    td.mkdir(parents=True, exist_ok=True)
    return td


def download_and_verify(
    manifest: ReleaseManifest,
    install_mode: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    custom_target_dir: Optional[Path] = None,
    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT,
) -> Tuple[Path, Optional[Path]]:
    """下载对应分发形态的升级资产并严格校验 SHA-256 与文件头。

    返回值：
      - 安装版 (installer): (setup_exe_path, None)
      - 便携版 (portable): (staging_dir, target_dir)

    异常：
      - UpdateVerificationError: SHA-256 不符或解压后关键二进制文件头损坏。
      - ValueError: 源码态拒绝直接自覆盖。
    """
    mode = install_mode or detect_install_mode()
    if mode == "source":
        raise ValueError("源码开发态禁止下载二进制覆盖当前工作树，请使用 git pull 更新代码。")

    if mode == "installer":
        url = manifest.installer_url
        expected_sha = manifest.installer_sha256.lower().strip()
        filename = f"DocTool-Setup-{manifest.version}.exe"
        if not url:
            raise UpdateVerificationError("Release 元数据中缺少安装版下载链接。")
        temp_dir = custom_target_dir or _get_candidate_temp_dir()
    else:
        # portable
        url = manifest.portable_url
        expected_sha = manifest.portable_sha256.lower().strip()
        filename = f"DocTool-{manifest.version}-portable.zip"
        if not url:
            raise UpdateVerificationError("Release 元数据中缺少便携包下载链接。")

        # 便携版必须在同盘建立 .upgrade_staging\
        if custom_target_dir is not None:
            portable_root = custom_target_dir
        else:
            exe_dir = Path(sys.executable).resolve().parent
            # 如果 exe 在 DocTool/ 目录下，根目录为上一级；否则为 exe_dir
            if exe_dir.name.lower() == "doctool":
                portable_root = exe_dir.parent
            else:
                portable_root = exe_dir
        temp_dir = portable_root

    temp_dir.mkdir(parents=True, exist_ok=True)
    download_file = temp_dir / f"{filename}.download.tmp"

    # 流式下载并边计算 SHA-256
    sha256_calc = hashlib.sha256()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"DocTool/{APP_VERSION} (DownloadWorker)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(download_file, "wb") as out_f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    sha256_calc.update(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total_size)
    except Exception as exc:
        if download_file.exists():
            download_file.unlink()
        raise OSError(f"升级资产下载失败: {exc}") from exc

    actual_sha = sha256_calc.hexdigest().lower()

    # 校验 SHA-256
    if expected_sha and actual_sha != expected_sha:
        if download_file.exists():
            download_file.unlink()
        raise UpdateVerificationError(
            f"SHA-256 校验不匹配: 期望 {expected_sha}, 实际 {actual_sha}。已终止升级并清理临时文件。"
        )

    # 分形态落地处理
    if mode == "installer":
        final_exe = temp_dir / filename
        if final_exe.exists():
            final_exe.unlink()
        download_file.rename(final_exe)
        return (final_exe, None)

    # portable 便携版：解压并校验二进制文件头
    staging_dir = temp_dir / ".upgrade_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(download_file, "r") as zf:
            zf.extractall(staging_dir)
    except Exception as exc:
        if download_file.exists():
            download_file.unlink()
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise UpdateVerificationError(f"解压便携包失败: {exc}") from exc
    finally:
        if download_file.exists():
            download_file.unlink()

    # 校验解压后二进制文件头（MZ / PK）
    doc_dir = staging_dir / "DocTool" if (staging_dir / "DocTool").is_dir() else staging_dir
    check_targets = [
        (doc_dir / "_internal" / "base_library.zip", b"PK"),
        (doc_dir / "_internal" / "python313.dll", b"MZ"),
        (doc_dir / "DocTool.exe", b"MZ"),
    ]

    for target_path, expected_magic in check_targets:
        if target_path.is_file():
            header = b""
            try:
                with open(target_path, "rb") as fh:
                    header = fh.read(2)
            except OSError as read_err:
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise UpdateVerificationError(f"读取文件头失败: {read_err}") from read_err

            if not header.startswith(expected_magic):
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise UpdateVerificationError(
                    f"二进制文件头损坏: {target_path.name} 标识为 {header!r}（期望 {expected_magic!r}）。"
                    "可能受企业终端安全/透明加密软件影响，升级已阻断。请联系管理员将 Doc Tool 加入白名单。"
                )

    return (staging_dir, temp_dir)


def apply_installer_update(setup_exe_path: Path, silent: bool = True) -> subprocess.Popen:
    """脱离当前进程组启动 Inno Setup 安装包。"""
    cmd = [str(setup_exe_path)]
    if silent:
        cmd.extend(["/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    return subprocess.Popen(
        cmd,
        creationflags=creation_flags,
        close_fds=True,
    )


def apply_portable_update(
    staging_dir: Path,
    target_dir: Optional[Path] = None,
    custom_script: Optional[Path] = None,
) -> subprocess.Popen:
    """脱离当前进程组启动 apply_update.ps1 完成便携版切换。"""
    t_dir = target_dir or staging_dir.parent

    # 寻找 apply_update.ps1 脚本
    candidates = [
        custom_script,
        staging_dir / "apply_update.ps1",
        staging_dir / "DocTool" / "apply_update.ps1",
        t_dir / "apply_update.ps1",
        t_dir / "DocTool" / "apply_update.ps1",
        Path(__file__).resolve().parents[2] / "packaging" / "portable" / "apply_update.ps1",
    ]
    script = next((c for c in candidates if c and Path(c).is_file()), None)
    if not script:
        raise FileNotFoundError("未找到便携版更新切换脚本 apply_update.ps1")

    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-TargetDir",
        str(t_dir),
        "-StagingDir",
        str(staging_dir),
        "-PidToWait",
        str(os.getpid()),
    ]

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    return subprocess.Popen(
        cmd,
        creationflags=creation_flags,
        close_fds=True,
    )


def run_update_check_async(
    on_result: Callable[[UpdateCheckResult], None],
    force: bool = False,
    custom_endpoint: Optional[str] = None,
    custom_url: Optional[str] = None,
) -> threading.Thread:
    """在后台线程执行更新检查，并在结束时调用 on_result。"""
    effective_url = custom_url or custom_endpoint

    def _worker() -> None:
        try:
            res = check_for_updates(force=force, custom_url=effective_url)
        except Exception as exc:
            res = UpdateCheckResult(error=str(exc))
        try:
            on_result(res)
        except Exception:
            pass

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    return th
