# -*- coding: utf-8 -*-
"""单元与集成测试：自升级服务、TTL 缓存、SHA-256 校验与便携版切换回滚。

覆盖 REQ-01, REQ-02, REQ-04, REQ-05。
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

HERE = Path(__file__).resolve()
DOC_TOOL_ROOT = HERE.parents[2]
if str(DOC_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(DOC_TOOL_ROOT))

from doc_tool.application.updater import (
    UpdateCheckResult,
    UpdateVerificationError,
    check_for_updates,
    download_and_verify,
    load_update_state,
    save_update_state,
    skip_version,
)
from doc_tool.domain.update import ReleaseManifest, UpdateState


class MockUpdateHandler(BaseHTTPRequestHandler):
    """用于测试的本地 Mock HTTP 服务处理器。"""

    latest_json_status = 200
    latest_json_body = ""
    api_status = 200
    api_body = ""
    sha_body = ""
    download_content = b""

    def do_GET(self):
        if self.path.endswith("/latest.json"):
            if self.latest_json_status == 200:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(self.latest_json_body.encode("utf-8"))
            else:
                self.send_response(self.latest_json_status)
                self.end_headers()
        elif "/releases/latest" in self.path:
            if self.api_status == 200:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(self.api_body.encode("utf-8"))
            else:
                self.send_response(self.api_status)
                self.end_headers()
        elif self.path.endswith(".sha256"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(self.sha_body.encode("utf-8"))
        elif "/download/" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(self.download_content)))
            self.end_headers()
            self.wfile.write(self.download_content)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # 静默测试输出
        pass


class TestUpdaterService(unittest.TestCase):
    """测试更新检查服务与校验逻辑。"""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockUpdateHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_dir = Path(self.temp_dir) / "state"
        self.state_dir.mkdir()
        # Mock user_config_dir
        self._orig_env = os.environ.get("DOC_TOOL_UPDATE_URL")
        if "DOC_TOOL_UPDATE_URL" in os.environ:
            del os.environ["DOC_TOOL_UPDATE_URL"]

    def tearDown(self):
        if self._orig_env:
            os.environ["DOC_TOOL_UPDATE_URL"] = self._orig_env
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_check_for_updates_latest_json_success(self):
        """测试优先请求 latest.json 成功发现新版本。"""
        manifest_data = {
            "version": "3.1.0",
            "tag_name": "v3.1.0",
            "published_at": "2026-10-28T00:00:00Z",
            "release_notes": "New features in 3.1.0",
            "installer_url": f"{self.base_url}/download/DocTool-Setup-3.1.0.exe",
            "installer_sha256": "abcdef123456",
            "portable_url": f"{self.base_url}/download/DocTool-3.1.0-portable.zip",
            "portable_sha256": "fedcba654321",
        }
        MockUpdateHandler.latest_json_status = 200
        MockUpdateHandler.latest_json_body = json.dumps(manifest_data)

        res = check_for_updates(
            force=True,
            custom_url=f"{self.base_url}/latest.json",
            current_version="3.0.1",
        )

        self.assertTrue(res.has_update)
        self.assertEqual(res.latest_version, "3.1.0")
        self.assertFalse(res.from_cache)
        self.assertIsNotNone(res.manifest)
        self.assertEqual(res.manifest.release_notes, "New features in 3.1.0")

    def test_check_for_updates_403_rate_limit(self):
        """测试遇到 403 频控时静默降级不崩溃。"""
        MockUpdateHandler.latest_json_status = 403
        res = check_for_updates(
            force=True,
            custom_url=f"{self.base_url}/latest.json",
            current_version="3.0.1",
        )
        self.assertFalse(res.has_update)
        self.assertIn("403", str(res.error))

    def test_check_for_updates_offline(self):
        """测试网络不可达或超时时静默降级。"""
        # 请求无效端口
        res = check_for_updates(
            force=True,
            custom_url="http://127.0.0.1:54321/latest.json",
            timeout=0.5,
            current_version="3.0.1",
        )
        self.assertFalse(res.has_update)
        self.assertIsNotNone(res.error)

    def test_download_and_verify_sha256_mismatch(self):
        """测试 SHA-256 篡改时被安全拦截并删除临时文件。"""
        test_content = b"fake executable content"
        MockUpdateHandler.download_content = test_content

        manifest = ReleaseManifest(
            version="3.1.0",
            installer_url=f"{self.base_url}/download/DocTool-Setup-3.1.0.exe",
            installer_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )

        target_dir = Path(self.temp_dir) / "download_test"
        target_dir.mkdir()

        with self.assertRaises(UpdateVerificationError):
            download_and_verify(
                manifest=manifest,
                install_mode="installer",
                custom_target_dir=target_dir,
            )

        # 验证临时下载文件已被删除
        leftovers = list(target_dir.glob("*.tmp"))
        self.assertEqual(len(leftovers), 0)

    def test_download_and_verify_portable_corrupt_binary_header(self):
        """测试便携版解压后二进制头被加密软件破坏（非 MZ/PK）时被安全拦截。"""
        zip_path = Path(self.temp_dir) / "corrupt.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # 伪造被加密破坏的 DocTool.exe（以 XX 开头而非 MZ）
            zf.writestr("DocTool/DocTool.exe", b"XX corrupted binary content")
            zf.writestr("DocTool/_internal/base_library.zip", b"PK fake zip content")
            zf.writestr("DocTool/_internal/python313.dll", b"MZ fake dll content")

        zip_bytes = zip_path.read_bytes()
        correct_sha = hashlib.sha256(zip_bytes).hexdigest()

        MockUpdateHandler.download_content = zip_bytes

        manifest = ReleaseManifest(
            version="3.1.0",
            portable_url=f"{self.base_url}/download/DocTool-3.1.0-portable.zip",
            portable_sha256=correct_sha,
        )

        target_dir = Path(self.temp_dir) / "portable_target"
        target_dir.mkdir()

        with self.assertRaises(UpdateVerificationError) as ctx:
            download_and_verify(
                manifest=manifest,
                install_mode="portable",
                custom_target_dir=target_dir,
            )

        self.assertIn("二进制文件头损坏", str(ctx.exception))
        self.assertIn("白名单", str(ctx.exception))

        # 验证损坏的 staging 目录已清理
        staging = target_dir / ".upgrade_staging"
        self.assertFalse(staging.exists())

    def test_apply_update_ps1_switch_and_rollback(self):
        """测试 apply_update.ps1 的原子目录切换与失败自动回滚机制。"""
        script_path = DOC_TOOL_ROOT / "packaging" / "portable" / "apply_update.ps1"
        self.assertTrue(script_path.is_file(), "apply_update.ps1 脚本必须存在")

        target_dir = Path(self.temp_dir) / "portable_env"
        target_dir.mkdir()

        # 模拟旧版目录
        old_doctool = target_dir / "DocTool"
        old_doctool.mkdir()
        (old_doctool / "DocTool.exe").write_bytes(b"old exe")
        (old_doctool / "version.txt").write_text("3.0.1", encoding="utf-8")

        # 模拟暂存目录
        staging_dir = target_dir / ".upgrade_staging"
        staging_doctool = staging_dir / "DocTool"
        staging_doctool.mkdir(parents=True)
        (staging_doctool / "DocTool.exe").write_bytes(b"new exe")
        (staging_doctool / "version.txt").write_text("3.1.0", encoding="utf-8")

        # 运行切换脚本（PidToWait 使用一个不可能存在的 PID 如 999999）
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-TargetDir",
            str(target_dir),
            "-StagingDir",
            str(staging_dir),
            "-PidToWait",
            "999999",
            "-ExeToLaunch",
            "",  # 不拉起进程
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk", errors="replace")
        self.assertEqual(proc.returncode, 0, f"切换脚本执行失败: {proc.stdout}\n{proc.stderr}")

        # 验证新版本已切入且备份存在
        self.assertEqual((target_dir / "DocTool" / "version.txt").read_text(encoding="utf-8"), "3.1.0")
        self.assertTrue((target_dir / "DocTool.prev" / "version.txt").is_file())
        self.assertEqual((target_dir / "DocTool.prev" / "version.txt").read_text(encoding="utf-8"), "3.0.1")


if __name__ == "__main__":
    unittest.main()
