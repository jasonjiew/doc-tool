# -*- coding: utf-8 -*-
"""自升级全链路真实模拟与深度漏洞探测脚本。

覆盖真实场景：
1. 正常新版本检测（CLI 与 SDK）
2. 404 静态源回退 GitHub REST API 双通道
3. 24小时 TTL 缓存命中与非法/损坏缓存自愈
4. 用户跳过版本 (skipped_version) 逻辑
5. 离线/网络超时/403 频控静默降级（不弹窗、不崩溃）
6. SHA-256 篡改强拦截与临时垃圾文件清理
7. 便携包解压产物被安全软件改写（文件头损坏）拦截
8. 便携版 PowerShell (apply_update.ps1) 原子替换与启动失败自动回滚
9. GUI 编辑器未保存内容拦截门禁
10. GUI Word 进程占用阻断门禁
11. 源码开发态直接自覆盖拦截
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve()
DOC_TOOL_ROOT = HERE.parents[2]
if str(DOC_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(DOC_TOOL_ROOT))

from doc_tool.application.cli_commands import upgrade_command
from doc_tool.application.content.unsaved import UnsavedChoice
from doc_tool.application.delivery.word_busy import BusyState
from doc_tool.application.updater import (
    UpdateCheckResult,
    UpdateVerificationError,
    check_for_updates,
    download_and_verify,
    load_update_state,
    save_update_state,
    skip_version,
)
from doc_tool.cli import main as cli_main
from doc_tool.domain.update import (
    ReleaseManifest,
    UpdateState,
    detect_install_mode,
    is_newer_version,
    parse_semver,
)
from doc_tool.domain.version import APP_VERSION


class MockServerHandler(BaseHTTPRequestHandler):
    mode = "latest_json"  # latest_json, api_fallback, rate_limit_403, error_500
    manifest_data = {}
    api_data = {}
    sha_text = ""
    download_bytes = b""

    def do_GET(self):
        if self.path.endswith("/latest.json"):
            if self.mode == "latest_json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(self.manifest_data).encode("utf-8"))
            elif self.mode == "api_fallback":
                self.send_response(404)
                self.end_headers()
            elif self.mode == "rate_limit_403":
                self.send_response(403)
                self.end_headers()
            else:
                self.send_response(500)
                self.end_headers()
        elif "/releases/latest" in self.path:
            if self.mode == "api_fallback":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(self.api_data).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path.endswith(".sha256"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(self.sha_text.encode("utf-8"))
        elif "/download/" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(self.download_bytes)))
            self.end_headers()
            self.wfile.write(self.download_bytes)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run_simulation():
    print("=" * 60)
    print(">>> 开始在线自升级全功能模拟与漏洞探测 <<<")
    print(f"当前被测 APP_VERSION: {APP_VERSION}")
    print("=" * 60)

    # 启动本地模拟 HTTP 服务
    server = HTTPServer(("127.0.0.1", 0), MockServerHandler)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    passed_count = 0
    total_count = 0
    issues = []

    def report(scenario_name: str, passed: bool, detail: str = ""):
        nonlocal passed_count, total_count
        total_count += 1
        status = "PASSED" if passed else "FAILED"
        print(f"[{status}] 场景 {total_count}: {scenario_name}")
        if detail:
            print(f"       -> {detail}")
        if passed:
            passed_count += 1
        else:
            issues.append((scenario_name, detail))

    # --- 场景 1: latest.json 发现更高版本 ---
    MockServerHandler.mode = "latest_json"
    MockServerHandler.manifest_data = {
        "version": "3.1.0",
        "tag_name": "v3.1.0",
        "published_at": "2026-10-28T12:00:00Z",
        "release_notes": "1. 增加在线自升级功能\n2. 修复排版缺陷",
        "installer_url": f"{base_url}/download/DocTool-Setup-3.1.0.exe",
        "installer_sha256": "aaaa1111",
        "portable_url": f"{base_url}/download/DocTool-3.1.0-portable.zip",
        "portable_sha256": "bbbb2222",
    }
    res1 = check_for_updates(force=True, custom_url=f"{base_url}/latest.json")
    report(
        "静态 latest.json 正常发现新版本",
        res1.has_update is True and res1.latest_version == "3.1.0" and res1.error is None,
        f"检测结果: hasUpdate={res1.has_update}, latest={res1.latest_version}",
    )

    # --- 场景 2: latest.json 404 时回退 GitHub REST API ---
    MockServerHandler.mode = "api_fallback"
    MockServerHandler.api_data = {
        "tag_name": "v3.2.0",
        "body": "API 回退版本发布说明",
        "published_at": "2026-10-28T13:00:00Z",
        "assets": [
            {
                "name": "DocTool-Setup-3.2.0.exe",
                "browser_download_url": f"{base_url}/download/DocTool-Setup-3.2.0.exe",
            },
            {
                "name": "DocTool-Setup-3.2.0.exe.sha256",
                "browser_download_url": f"{base_url}/download/DocTool-Setup-3.2.0.exe.sha256",
            },
            {
                "name": "DocTool-3.2.0-portable.zip",
                "browser_download_url": f"{base_url}/download/DocTool-3.2.0-portable.zip",
            },
            {
                "name": "DocTool-3.2.0-portable.zip.sha256",
                "browser_download_url": f"{base_url}/download/DocTool-3.2.0-portable.zip.sha256",
            },
        ],
    }
    MockServerHandler.sha_text = "cccc33334444  DocTool-3.2.0-portable.zip"
    from doc_tool.application import updater
    orig_api_url = updater.DEFAULT_GITHUB_API_URL
    updater.DEFAULT_GITHUB_API_URL = f"{base_url}/releases/latest"
    try:
        # 当 URL 为默认 latest 时，404 会回退 API
        orig_latest = updater.DEFAULT_LATEST_JSON_URL
        updater.DEFAULT_LATEST_JSON_URL = f"{base_url}/latest.json"
        res2 = check_for_updates(force=True)
        report(
            "双通道降级：latest.json 404 自动回退 REST API 并组装资产",
            res2.has_update is True and res2.latest_version == "3.2.0",
            f"回退解析成功: version={res2.latest_version}, notes={res2.manifest.release_notes if res2.manifest else ''}",
        )
    finally:
        updater.DEFAULT_GITHUB_API_URL = orig_api_url
        updater.DEFAULT_LATEST_JSON_URL = orig_latest

    # --- 场景 3: 24h TTL 缓存命中与损坏自愈 ---
    temp_dir = tempfile.mkdtemp()
    state_file = Path(temp_dir) / "update_state.json"
    orig_get_path = updater.get_update_state_path
    updater.get_update_state_path = lambda: state_file
    try:
        # 写入有效 1 小时前的缓存
        cached_manifest = ReleaseManifest(version="3.3.0", release_notes="cached").to_dict()
        state = UpdateState(
            last_checked_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            cached_manifest=cached_manifest,
        )
        save_update_state(state)

        res3 = check_for_updates(force=False)
        report(
            "24 小时 TTL 缓存命中，无需网络请求",
            res3.from_cache is True and res3.latest_version == "3.3.0",
            f"from_cache={res3.from_cache}, version={res3.latest_version}",
        )

        # 模拟缓存文件严重损坏（非法 JSON）
        state_file.write_text("{ corrupted invalid json content !!!", encoding="utf-8")
        corrupted_state = load_update_state()
        report(
            "缓存文件损坏时安全降级与自愈",
            corrupted_state.auto_check is True and corrupted_state.cached_manifest is None,
            "损坏 JSON 未引发 Crash，平稳返回初始 UpdateState",
        )
    finally:
        updater.get_update_state_path = orig_get_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    # --- 场景 4: 用户跳过某版本 (skipped_version) ---
    temp_dir2 = tempfile.mkdtemp()
    state_file2 = Path(temp_dir2) / "update_state.json"
    updater.get_update_state_path = lambda: state_file2
    try:
        MockServerHandler.mode = "latest_json"
        MockServerHandler.manifest_data = {"version": "3.1.0"}
        skip_version("3.1.0")
        res4 = check_for_updates(force=True, custom_url=f"{base_url}/latest.json")
        report(
            "用户跳过版本过滤 (skipped_version)",
            res4.is_skipped is True and res4.has_update is False,
            f"已标记 is_skipped={res4.is_skipped}, has_update={res4.has_update}",
        )
    finally:
        updater.get_update_state_path = orig_get_path
        shutil.rmtree(temp_dir2, ignore_errors=True)

    # --- 场景 5: 403 频控与断网静默降级 ---
    MockServerHandler.mode = "rate_limit_403"
    res5_403 = check_for_updates(force=True, custom_url=f"{base_url}/latest.json")
    res5_offline = check_for_updates(force=True, custom_url="http://127.0.0.1:59999/latest.json", timeout=0.3)
    report(
        "HTTP 403 限流与离线断网静默处理",
        res5_403.has_update is False and "403" in str(res5_403.error) and res5_offline.has_update is False,
        f"403 错误信息: {res5_403.error}; 断网错误信息: {res5_offline.error}",
    )

    # --- 场景 6: SHA-256 强校验与篡改拦截 ---
    tampered_bytes = b"malicious or corrupted setup binary"
    MockServerHandler.download_bytes = tampered_bytes
    fake_manifest = ReleaseManifest(
        version="3.1.0",
        installer_url=f"{base_url}/download/DocTool-Setup-3.1.0.exe",
        installer_sha256="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    )
    with tempfile.TemporaryDirectory() as td:
        intercepted = False
        try:
            download_and_verify(manifest=fake_manifest, install_mode="installer", custom_target_dir=Path(td))
        except UpdateVerificationError as e:
            intercepted = True
            leftovers = list(Path(td).glob("*.tmp"))
            report(
                "SHA-256 校验不匹配拦截与临时垃圾文件清理",
                len(leftovers) == 0,
                f"成功拦截篡改并删除临时文件: {e}",
            )
        if not intercepted:
            report("SHA-256 校验不匹配拦截", False, "未能拦截篡改哈希！")

    # --- 场景 7: 便携包二进制头损坏（加密软件改写）拦截 ---
    with tempfile.TemporaryDirectory() as td:
        corrupt_zip = Path(td) / "corrupt.zip"
        with zipfile.ZipFile(corrupt_zip, "w") as zf:
            zf.writestr("DocTool/DocTool.exe", b"XX_CORRUPT_NOT_MZ")
            zf.writestr("DocTool/_internal/base_library.zip", b"PK_DUMMY")
            zf.writestr("DocTool/_internal/python313.dll", b"MZ_DUMMY")

        zip_bytes = corrupt_zip.read_bytes()
        correct_sha = hashlib.sha256(zip_bytes).hexdigest()
        MockServerHandler.download_bytes = zip_bytes

        fake_portable_manifest = ReleaseManifest(
            version="3.1.0",
            portable_url=f"{base_url}/download/DocTool-3.1.0-portable.zip",
            portable_sha256=correct_sha,
        )

        header_intercepted = False
        staging_dir = Path(td) / "portable_target" / ".upgrade_staging"
        try:
            download_and_verify(
                manifest=fake_portable_manifest,
                install_mode="portable",
                custom_target_dir=Path(td) / "portable_target",
            )
        except UpdateVerificationError as e:
            header_intercepted = True
            report(
                "便携包关键二进制文件头损坏阻断（防透明加密/杀软损坏）",
                not staging_dir.exists(),
                f"成功捕获头损坏且清理 staging: {e}",
            )
        if not header_intercepted:
            report("便携包关键二进制文件头损坏阻断", False, "未能识别二进制头损坏！")

    # --- 场景 8: 便携版 PowerShell (apply_update.ps1) 切换与失败自动回滚 ---
    script_path = DOC_TOOL_ROOT / "packaging" / "portable" / "apply_update.ps1"
    with tempfile.TemporaryDirectory() as td:
        target_root = Path(td) / "portable_app"
        target_root.mkdir()

        # 部署旧版本
        old_dir = target_root / "DocTool"
        old_dir.mkdir()
        (old_dir / "app_version.txt").write_text("3.0.1", encoding="utf-8")

        # 部署预检失败脚本（模拟新版存在致命问题）
        bad_preflight = target_root / "preflight.ps1"
        bad_preflight.write_text("exit 1", encoding="utf-8")

        # 部署待更新暂存目录
        stg = target_root / ".upgrade_staging"
        stg_doc = stg / "DocTool"
        stg_doc.mkdir(parents=True)
        (stg_doc / "app_version.txt").write_text("3.1.0-BROKEN", encoding="utf-8")

        # 运行 PowerShell 切换脚本
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-TargetDir",
            str(target_root),
            "-StagingDir",
            str(stg),
            "-PidToWait",
            "999999",
            "-ExeToLaunch",
            "",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk", errors="replace")
        # 预检失败应当触发回滚，退出码 2
        rollback_succeeded = (
            proc.returncode == 2
            and (target_root / "DocTool" / "app_version.txt").is_file()
            and (target_root / "DocTool" / "app_version.txt").read_text(encoding="utf-8") == "3.0.1"
        )
        report(
            "PowerShell 原子切换与失败自动回滚机制",
            rollback_succeeded,
            f"脚本退出码: {proc.returncode}, 旧版是否完好恢复: {rollback_succeeded}",
        )

    # --- 场景 9: 源码开发态拒绝自覆盖 ---
    from unittest.mock import patch
    with patch("doc_tool.domain.update.detect_install_mode", return_value="source"):
        MockServerHandler.mode = "latest_json"
        MockServerHandler.manifest_data = {"version": "3.9.0"}
        cli_res = upgrade_command(check_only=False, auto_confirm=True, custom_url=f"{base_url}/latest.json")
        report(
            "源码开发态（source）拦截二进制自覆盖",
            cli_res["success"] is False and cli_res["actionTaken"] == "refused_source_mode" and "git pull" in cli_res["error"],
            f"正确拦截并提示: {cli_res['error']}",
        )

    # --- 场景 10: CLI upgrade 命令纯净 stdout JSON ---
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(["upgrade", "--check", "--output", "json", "--custom-url", f"{base_url}/latest.json"])
    json_out = buf.getvalue().strip()
    is_valid_json = False
    try:
        parsed = json.loads(json_out)
        is_valid_json = isinstance(parsed, dict) and parsed.get("command") == "upgrade"
    except Exception:
        pass
    report(
        "CLI upgrade --output json 输出绝对纯净（无日志干扰）",
        code == 0 and is_valid_json,
        f"退出码 {code}, JSON 根键: {list(parsed.keys()) if is_valid_json else 'INVALID'}",
    )

    # --- 场景 11: GUI 未保存内容与 Word 忙碌门禁 ---
    from doc_tool.ui.main_window import MainWindow
    from unittest.mock import MagicMock

    mock_win = MagicMock(spec=MainWindow)
    mock_win._confirm_close_with_unsaved.return_value = False

    # 用户在弹窗点击「取消」
    can_proceed = MainWindow._perform_upgrade(mock_win, ReleaseManifest(version="3.1.0"))
    report(
        "GUI 未保存章节用户取消时安全拦截升级退出",
        can_proceed is False,
        "成功拦截，未发生丢稿强退",
    )

    # Word 后台忙碌拦截
    mock_win._confirm_close_with_unsaved.return_value = True
    with patch("doc_tool.application.delivery.word_busy.status", return_value=BusyState(busy=True, pid=1234)):
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_box:
            can_proceed_word = MainWindow._perform_upgrade(mock_win, ReleaseManifest(version="3.1.0"))
            report(
                "GUI 后台 Word 活跃任务冲突拦截",
                can_proceed_word is False and mock_box.called,
                "成功检测 Word 忙碌并弹窗阻断升级",
            )

    print("=" * 60)
    print(f"探测总结: 共执行 {total_count} 个模拟场景，通过 {passed_count} 个，失败 {len(issues)} 个。")
    if issues:
        print("发现以下潜在缺陷：")
        for name, det in issues:
            print(f"  - {name}: {det}")
    else:
        print("未发现任何逻辑漏洞或异常崩溃点，双形态升级闭环与安全门禁均运行正常！")
    print("=" * 60)

    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    run_simulation()
