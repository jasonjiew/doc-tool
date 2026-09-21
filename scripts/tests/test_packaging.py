# -*- coding: utf-8 -*-
"""打包与资源定位测试。

任务 8.2：验证 resource_root() 在开发态与冻结态（PyInstaller）资源定位一致。
任务 8.7：验证旧应用拒写更高模式项目（can_write_schema）。

覆盖范围：
- resource_root() 开发态返回 doc_tool/resources/ 目录
- resource_root() 冻结态（模拟 sys._MEIPASS）返回 _MEIPASS/doc_tool/resources
- resource_path() 正确拼接子路径
- 默认配置文件 default_project.yml 在开发态可访问
- can_read_schema / can_write_schema 的向前/向后兼容语义
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class ResourceRootTests(unittest.TestCase):
    """任务 8.2：resource_root() 开发态与冻结态定位。"""

    def test_dev_mode_returns_resources_dir(self):
        """开发态：resource_root() 返回 doc_tool/resources/ 目录。"""
        from doc_tool.resources import resource_root

        root = resource_root()
        self.assertTrue(os.path.isdir(root))
        # 必须包含 default_project.yml
        self.assertTrue(os.path.isfile(os.path.join(root, "default_project.yml")))

    def test_dev_mode_resource_path(self):
        """resource_path() 正确拼接子路径。"""
        from doc_tool.resources import resource_path

        p = resource_path("default_project.yml")
        self.assertTrue(os.path.isfile(p))

    def test_frozen_mode_returns_meipass_resources(self):
        """冻结态：模拟 sys._MEIPASS，resource_root() 返回 _MEIPASS/doc_tool/resources。"""
        from doc_tool.resources import resource_root

        with tempfile.TemporaryDirectory(prefix="doc-meipass-") as tmp:
            # 模拟 PyInstaller 冻结环境
            fake_resources = os.path.join(tmp, "doc_tool", "resources")
            os.makedirs(fake_resources)
            # 放入一个标记文件
            marker = os.path.join(fake_resources, "default_project.yml")
            with open(marker, "w", encoding="utf-8") as f:
                f.write("# frozen marker")

            with patch.object(sys, "_MEIPASS", tmp, create=True):
                root = resource_root()
                self.assertEqual(os.path.normpath(root), os.path.normpath(fake_resources))
                self.assertTrue(os.path.isfile(os.path.join(root, "default_project.yml")))

    def test_frozen_mode_resource_path(self):
        """冻结态：resource_path() 在 _MEIPASS 下定位资源。"""
        from doc_tool.resources import resource_path

        with tempfile.TemporaryDirectory(prefix="doc-meipass-") as tmp:
            fake_resources = os.path.join(tmp, "doc_tool", "resources")
            os.makedirs(fake_resources)
            marker = os.path.join(fake_resources, "test.yml")
            with open(marker, "w", encoding="utf-8") as f:
                f.write("# test")

            with patch.object(sys, "_MEIPASS", tmp, create=True):
                p = resource_path("test.yml")
                self.assertTrue(os.path.isfile(p))

    def test_default_project_yml_loadable(self):
        """默认项目清单在开发态可被 yaml 加载。"""
        import yaml

        from doc_tool.resources import resource_path

        p = resource_path("default_project.yml")
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)
        self.assertIn("schemaVersion", data)
        self.assertEqual(data["schemaVersion"], 1)


class SchemaCompatibilityTests(unittest.TestCase):
    """任务 8.7：旧应用拒写更高模式项目。"""

    def test_can_write_current_schema(self):
        """当前应用可写当前模式版本。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_write_schema

        self.assertTrue(can_write_schema(PROJECT_SCHEMA_VERSION))

    def test_reject_write_higher_schema(self):
        """旧应用拒绝写入更高模式版本（避免破坏性降级）。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_write_schema

        future = PROJECT_SCHEMA_VERSION + 1
        self.assertFalse(can_write_schema(future))

    def test_can_read_higher_schema(self):
        """当前应用可只读打开更高模式版本（向前兼容展示）。"""
        from doc_tool.domain.version import PROJECT_SCHEMA_VERSION, can_read_schema

        future = PROJECT_SCHEMA_VERSION + 1
        self.assertTrue(can_read_schema(future))

    def test_reject_read_unknown_lower_schema(self):
        """未知的历史低版本不可读（无降级迁移）。"""
        from doc_tool.domain.version import can_read_schema

        # 假设的 v0（不存在于 SUPPORTED_PROJECT_SCHEMA_VERSIONS）
        self.assertFalse(can_read_schema(0))


class PackageAllowlistTests(unittest.TestCase):
    def test_strict_allowlist_rejects_unknown_file(self):
        import importlib.util

        module_path = Path(REPO_ROOT) / "packaging" / "scan_leaks.py"
        spec = importlib.util.spec_from_file_location("doc_tool_scan_leaks", module_path)
        scan_leaks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scan_leaks)

        with tempfile.TemporaryDirectory(prefix="doc-allowlist-") as tmp:
            root = Path(tmp)
            (root / "DocTool.exe").write_bytes(b"exe")
            (root / "customer-data.txt").write_text("secret", encoding="utf-8")
            leaks = scan_leaks.scan_allowlist(root)
            self.assertTrue(any("customer-data.txt" in item for item in leaks))
            self.assertFalse(any("DocTool.exe" in item for item in leaks))


class ReleasePipelineTests(unittest.TestCase):
    def test_hash_is_generated_after_all_signing_steps(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        self.assertGreater(
            package_block.rfind("Get-FileHash"),
            package_block.rfind("signtool.Source sign"),
        )
        self.assertIn("signtool.Source verify", package_block)

    def test_release_gate_blocks_public_until_decisions_resolved(self):
        """任务 9.3：未决发布决策阻断公共正式发布，允许内部测试产物。

        用临时决策表驱动门禁机制，避免随真实决策表进入已决状态后本测试失效。
        """
        import importlib.util

        module_path = Path(REPO_ROOT) / "packaging" / "release_gate.py"
        spec = importlib.util.spec_from_file_location("doc_tool_release_gate", module_path)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)

        with tempfile.TemporaryDirectory(prefix="doc-gate-") as tmp:
            decisions = Path(tmp) / "decisions.md"
            decisions.write_text(
                "| 决策项 | 占位值 | 责任人 | 状态 | 备注 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 品牌/许可证 | — | 权利人 | UNRESOLVED | 未定 |\n",
                encoding="utf-8",
            )
            old_decisions = gate.DECISIONS_FILE
            old_checklist = gate.CHECKLIST_FILE
            gate.DECISIONS_FILE = decisions
            gate.CHECKLIST_FILE = Path(tmp) / "absent-checklist.md"
            try:
                blockers = gate.check_public_gate()
                self.assertTrue(any("品牌/许可证" in b for b in blockers))
                # 未决决策应同时出现在 unresolved_items 中
                self.assertEqual(
                    gate.unresolved_items(decisions), ["品牌/许可证"]
                )
            finally:
                gate.DECISIONS_FILE = old_decisions
                gate.CHECKLIST_FILE = old_checklist

    def test_public_source_export_wired_into_ci(self):
        """任务 9.4：净化源码导出+扫描已接入公共 CI。"""
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertIn("export_public_source.py", ci)
        self.assertIn("release_gate.py --public", ci)

    def test_frozen_build_installs_runtime_and_build_requirements(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        build_block = ci[ci.index("build-onedir:"):ci.index("package-installer:")]
        self.assertIn("-r requirements.txt -r requirements-build.txt", build_block)

    def test_install_level_smoke_runs_before_installer_signing(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        smoke_pos = package_block.index("test_installer_smoke.ps1")
        installer_sign_pos = package_block.index(
            "$signtool.Source sign", package_block.index('$exe = "packaging')
        )
        self.assertLess(smoke_pos, installer_sign_pos)
        self.assertTrue(
            (Path(REPO_ROOT) / "scripts" / "tests" / "test_installer_smoke.ps1").is_file()
        )

    def test_release_requires_clean_tree_and_uses_generated_notes(self):
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertIn("git status --porcelain --untracked-files=all", ci)
        self.assertIn('description: "packaging/Output/release-notes.md"', ci)
        self.assertIn("CI_COMMIT_SHA", ci)


class PortablePackageTests(unittest.TestCase):
    """团队分发便携包：启动脚本入库且可复现打包。

    1.4.4 起产物全量代码签名，启动脚本原地启动已签名 exe，不再复制到 %TEMP%
    （透明加密客户端如亿赛通 DocGuard 会加密复制出的 .pyd，导致启动失败）。
    脚本此前只存在于 gitignore 的 dist\\ 下、手工维护，清一次 dist 就没了——
    必须入库并由构建脚本产出。
    """

    LAUNCHER = Path(REPO_ROOT) / "packaging" / "portable" / "启动DocTool.cmd"

    def test_launcher_is_tracked_in_repo(self):
        self.assertTrue(self.LAUNCHER.is_file(), "便携包启动脚本必须入库")

    def test_launcher_is_ascii_only(self):
        """cmd.exe 按系统 ANSI 代码页解析批处理，非 ASCII 字节会破坏解析。"""
        raw = self.LAUNCHER.read_bytes()
        offenders = [
            (index, byte) for index, byte in enumerate(raw) if byte > 0x7F
        ]
        self.assertEqual(offenders, [], "启动脚本出现非 ASCII 字节")

    def test_launcher_starts_in_place_without_temp_copy(self):
        """1.4.4：原地启动已签名 exe，不再复制到 %TEMP%（透明加密客户端会加密 .pyd）。"""
        text = self.LAUNCHER.read_text(encoding="ascii")
        # 相对自身定位 DocTool\，解压到任意路径都能用。
        self.assertIn("%~dp0DocTool", text)
        # 原地启动：不再复制、不再引用 dt_run_ / robocopy / Copy-Item / %TGT%。
        self.assertIn('start "" "%SRC%\\DocTool.exe"', text)
        self.assertNotIn("dt_run_", text)
        self.assertNotIn("robocopy", text)
        self.assertNotIn("Copy-Item", text)
        self.assertNotIn("%TGT%", text)

    def test_launcher_reports_start_failure(self):
        """1.4.5：preflight 启动并监视应用，快速失败时启动器给出可见报错。"""
        text = self.LAUNCHER.read_text(encoding="ascii")
        self.assertIn("STARTFAIL", text)
        self.assertIn("NOTSTARTED", text)
        self.assertIn("dt_startfail_reason.txt", text)
        # 兜底直启（preflight 未运行/未能启动时）仍在。
        self.assertIn('start "" "%SRC%\\DocTool.exe"', text)
        preflight = (
            Path(REPO_ROOT) / "packaging" / "portable" / "preflight.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Start-Process", preflight)
        self.assertIn("WaitForExit", preflight)
        self.assertIn("STARTFAIL", preflight)
        installed = (
            Path(REPO_ROOT) / "packaging" / "installed" / "启动DocTool.cmd"
        ).read_text(encoding="ascii")
        self.assertIn("STARTFAIL", installed)
        self.assertIn("NOTSTARTED", installed)

    def test_preflight_script_is_ascii_only(self):
        """preflight.ps1 与启动器一样必须 ASCII-only（PS 5.1 无 BOM 按 ANSI 解析）。"""
        raw = (
            Path(REPO_ROOT) / "packaging" / "portable" / "preflight.ps1"
        ).read_bytes()
        offenders = [
            (index, byte) for index, byte in enumerate(raw) if byte > 0x7F
        ]
        self.assertEqual(offenders, [], "preflight.ps1 出现非 ASCII 字节")

    def test_build_script_exposes_portable_switch(self):
        script = (Path(REPO_ROOT) / "build_exe.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Portable", script)
        # 装配逻辑统一委托给 packaging/make_portable.ps1（与 CI 同源）。
        self.assertIn("make_portable.ps1", script)
        make_portable = (
            Path(REPO_ROOT) / "packaging" / "make_portable.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Compress-Archive", make_portable)
        self.assertIn("DocTool-$Version-portable.zip", make_portable)
        # zip 里同时包含应用目录、启动脚本与诊断脚本。
        self.assertIn("启动DocTool.cmd", make_portable)
        self.assertIn("diagnose.cmd", make_portable)

    def test_dist_staging_script_shared(self):
        """stage_dist.ps1 除低了启动/诊断脚本的复处漂移与基线过期。"""
        stage = (Path(REPO_ROOT) / "packaging" / "stage_dist.ps1").read_text(encoding="utf-8")
        self.assertIn("EXP_BL_SIZE", stage)
        self.assertIn("Get-FileHash", stage)
        self.assertIn("diagnose.cmd", stage)
        build_installer = (Path(REPO_ROOT) / "packaging" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("stage_dist.ps1", build_installer)

    def test_ci_publishes_portable_package(self):
        """tag 流水线除安装器外还产出便携包，并挂进 Release 资产。"""
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        self.assertIn("DocTool-$env:APP_VERSION-portable.zip", package_block)
        self.assertIn("make_portable.ps1", package_block)
        # 便携包也要有校验值，且发布说明与资产链接都要带上。
        self.assertIn('"$portable.sha256"', package_block)
        release_block = ci[ci.index("release-upload:"):]
        self.assertIn("DocTool-$APP_VERSION-portable.zip", release_block)
        self.assertIn("portable.zip.sha256", release_block)
        self.assertIn("启动DocTool.cmd", release_block)

    def test_ci_zips_portable_after_app_signing(self):
        """便携包必须在应用签名之后打，否则包里是未签名 exe（照样被拦）。"""
        ci = (Path(REPO_ROOT) / ".gitlab-ci.yml").read_text(encoding="utf-8")
        package_block = ci[ci.index("package-installer:"):ci.index("release-upload:")]
        sign_pos = package_block.index("$signtool.Source sign")
        zip_pos = package_block.index("make_portable.ps1")
        self.assertLess(sign_pos, zip_pos)


    def test_installer_ships_diagnose_cmd(self):
        """安装器随带诊断脚本，成员双击运行后回传 DocTool-diagnose.txt。"""
        iss = (Path(REPO_ROOT) / "packaging" / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("diagnose.cmd", iss)
        self.assertTrue(
            (Path(REPO_ROOT) / "packaging" / "portable" / "diagnose.cmd").is_file(),
            "诊断脚本必须入库",
        )

    def test_gui_entry_has_self_heal_fallback(self):
        """GUI 入口冻结态下 PySide6 导入失败走 self_heal 自愈，其余启动异常可见化。"""
        app_src = (Path(REPO_ROOT) / "doc_tool" / "app.py").read_text(encoding="utf-8")
        self.assertIn("self_heal.handle_blocked_import", app_src)
        self.assertIn("self_heal.report_startup_failure", app_src)
        heal = (
            Path(REPO_ROOT) / "doc_tool" / "application" / "self_heal.py"
        ).read_text(encoding="utf-8")
        # 1.4.4: 不再复制到 %TEMP%（透明加密客户端会加密 .pyd），故不再有迁移标记
        self.assertNotIn("DOCTOOL_RELOCATED", heal)
        self.assertIn("MessageBoxW", heal)



class PublishReleaseTests(unittest.TestCase):
    """验证 packaging/publish_release.py 环境变量动态解析、防呆门禁与 API 包装行为。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        publish_py = Path(REPO_ROOT) / "packaging" / "publish_release.py"
        spec = importlib.util.spec_from_file_location("packaging.publish_release", publish_py)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_get_token_from_env(self):
        with patch.dict(os.environ, {"GITLAB_TOKEN": "token_abc"}, clear=False):
            self.assertEqual(self.mod.get_token(), "token_abc")

    def test_get_token_from_argv(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["publish_release.py", "token_xyz"]):
            self.assertEqual(self.mod.get_token(), "token_xyz")

    def test_get_token_missing_raises_runtime_error(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "argv", ["publish_release.py"]):
            with self.assertRaises(RuntimeError) as ctx:
                self.mod.get_token()
            self.assertIn("GITLAB_TOKEN", str(ctx.exception))

    def test_get_gitlab_base_valid(self):
        with patch.dict(os.environ, {"GITLAB_BASE": "http://gitlab.example.internal:8080/"}, clear=False):
            self.assertEqual(self.mod.get_gitlab_base(), "http://gitlab.example.internal:8080")

    def test_get_gitlab_base_missing_raises(self):
        with patch.dict(os.environ, {"GITLAB_BASE": ""}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                self.mod.get_gitlab_base()
            self.assertIn("GITLAB_BASE", str(ctx.exception))

    def test_get_project_id_valid(self):
        with patch.dict(os.environ, {"GITLAB_PROJECT_ID": "42"}, clear=False):
            self.assertEqual(self.mod.get_project_id(), 42)

    def test_get_project_id_missing_raises(self):
        with patch.dict(os.environ, {"GITLAB_PROJECT_ID": ""}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                self.mod.get_project_id()
            self.assertIn("GITLAB_PROJECT_ID", str(ctx.exception))

    def test_get_project_id_invalid_type_raises(self):
        with patch.dict(os.environ, {"GITLAB_PROJECT_ID": "not_an_int"}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                self.mod.get_project_id()
            self.assertIn("无效", str(ctx.exception))

    def test_get_project_path_valid(self):
        with patch.dict(os.environ, {"GITLAB_PROJECT_PATH": "/mygroup/myproject/"}, clear=False):
            self.assertEqual(self.mod.get_project_path(), "mygroup/myproject")

    def test_get_project_path_missing_raises(self):
        with patch.dict(os.environ, {"GITLAB_PROJECT_PATH": ""}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                self.mod.get_project_path()
            self.assertIn("GITLAB_PROJECT_PATH", str(ctx.exception))

    def test_calc_sha256(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"DocTool release package test content")
            tmp_path = f.name
        try:
            import hashlib
            expected = hashlib.sha256(b"DocTool release package test content").hexdigest().upper()
            self.assertEqual(self.mod.calc_sha256(tmp_path), expected)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_upload_file_puts_to_correct_url(self):
        from unittest.mock import MagicMock
        with patch.dict(os.environ, {
            "GITLAB_BASE": "http://gitlab.test",
            "GITLAB_PROJECT_ID": "99",
        }, clear=False):
            with tempfile.NamedTemporaryFile("wb", delete=False) as f:
                f.write(b"binary payload")
                tmp_path = f.name
            try:
                mock_resp = MagicMock()
                mock_resp.status = 201
                mock_resp.__enter__.return_value = mock_resp
                mock_resp.__exit__.return_value = None

                captured_req = []
                def fake_urlopen(req):
                    captured_req.append(req)
                    return mock_resp

                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    self.mod.upload_file("test-token", "package.zip", tmp_path)

                self.assertEqual(len(captured_req), 1)
                req = captured_req[0]
                self.assertIn(f"http://gitlab.test/api/v4/projects/99/packages/generic/DocTool/{self.mod.VERSION}/package.zip", req.full_url)
                self.assertEqual(req.get_header("Private-token"), "test-token")
                self.assertEqual(req.get_method(), "PUT")
                self.assertEqual(req.data, b"binary payload")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)


    def test_get_package_files_success(self):
        import json
        from unittest.mock import MagicMock
        with patch.dict(os.environ, {"GITLAB_BASE": "http://gitlab.test", "GITLAB_PROJECT_ID": "99"}):
            mock_resp_pkgs = MagicMock()
            mock_resp_pkgs.read.return_value = json.dumps([{"name": "DocTool", "version": self.mod.VERSION, "id": 888}]).encode("utf-8")
            mock_resp_pkgs.__enter__.return_value = mock_resp_pkgs
            mock_resp_pkgs.__exit__.return_value = None

            mock_resp_files = MagicMock()
            mock_resp_files.read.return_value = json.dumps([{"file_name": f"DocTool-Setup-{self.mod.VERSION}.exe", "id": 1001}]).encode("utf-8")
            mock_resp_files.__enter__.return_value = mock_resp_files
            mock_resp_files.__exit__.return_value = None

            with patch("urllib.request.urlopen", side_effect=[mock_resp_pkgs, mock_resp_files]):
                files = self.mod.get_package_files("token")
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["id"], 1001)

    def test_get_package_files_missing_package_raises(self):
        import json
        from unittest.mock import MagicMock
        with patch.dict(os.environ, {"GITLAB_BASE": "http://gitlab.test", "GITLAB_PROJECT_ID": "99"}):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps([]).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = None

            with patch("urllib.request.urlopen", return_value=mock_resp):
                with self.assertRaises(RuntimeError) as ctx:
                    self.mod.get_package_files("token")
                self.assertIn("未找到 Package", str(ctx.exception))

    def test_create_or_update_release_creates_when_not_exists(self):
        import json
        import urllib.error
        from unittest.mock import MagicMock
        with patch.dict(os.environ, {"GITLAB_BASE": "http://gitlab.test", "GITLAB_PROJECT_ID": "99"}):
            err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
            mock_post_resp = MagicMock()
            mock_post_resp.read.return_value = json.dumps({"tag_name": self.mod.TAG_NAME, "status": "created"}).encode("utf-8")
            mock_post_resp.__enter__.return_value = mock_post_resp
            mock_post_resp.__exit__.return_value = None

            calls = []
            def fake_urlopen(req):
                calls.append(req)
                if len(calls) == 1:
                    raise err
                return mock_post_resp

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = self.mod.create_or_update_release("token", "desc", [])

            self.assertEqual(result["status"], "created")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1].get_method(), "POST")

    def test_create_or_update_release_updates_when_exists(self):
        import json
        from unittest.mock import MagicMock
        with patch.dict(os.environ, {"GITLAB_BASE": "http://gitlab.test", "GITLAB_PROJECT_ID": "99"}):
            mock_check_resp = MagicMock()
            mock_check_resp.status = 200
            mock_check_resp.__enter__.return_value = mock_check_resp
            mock_check_resp.__exit__.return_value = None

            mock_put_resp = MagicMock()
            mock_put_resp.read.return_value = json.dumps({"tag_name": self.mod.TAG_NAME, "status": "updated"}).encode("utf-8")
            mock_put_resp.__enter__.return_value = mock_put_resp
            mock_put_resp.__exit__.return_value = None

            calls = []
            def fake_urlopen(req):
                calls.append(req)
                if len(calls) == 1:
                    return mock_check_resp
                return mock_put_resp

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = self.mod.create_or_update_release("token", "new_desc", [])

            self.assertEqual(result["status"], "updated")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1].get_method(), "PUT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
