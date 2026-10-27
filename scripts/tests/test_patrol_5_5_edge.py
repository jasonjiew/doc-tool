# -*- coding: utf-8 -*-
"""Regression tests for Patrol 5.5: CLI 全子命令契约、参数组合与退出码巡检."""

import io
import json
import sys
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from doc_tool.cli import main


class TestPatrol55CliContractsAndExitCodes:
    def test_cli_invalid_project_path_returns_code_2_clean_stderr(self):
        """测试用例：对不存在的项目执行 export 或 build，返回码为 2 且输出清晰的中文提示，无裸 Traceback。"""
        fake_proj = "non_existent_project_dir_xyz_123"

        # 1. export 命令
        err_buf = io.StringIO()
        out_buf = io.StringIO()
        with redirect_stderr(err_buf), redirect_stdout(out_buf):
            code = main(["export", "--project", fake_proj])
        assert code == 2
        assert "缺少 project.yml" in err_buf.getvalue()

        # 2. build 命令
        err_buf2 = io.StringIO()
        out_buf2 = io.StringIO()
        with redirect_stderr(err_buf2), redirect_stdout(out_buf2):
            code2 = main(["build", "--project", fake_proj])
        assert code2 == 2
        assert "无法加载项目清单" in err_buf2.getvalue()

    def test_cli_invalid_property_format_returns_code_2(self, tmp_path):
        """测试用例：传入格式非法的 --property（缺少等号），返回非零退出码并提示正确用法。"""
        # 创建一个空项目目录结构
        proj = tmp_path / "valid_proj"
        proj.mkdir()
        (proj / "project.yml").write_text("""schemaVersion: 2
documentType: general
documentName: 测试项目
documentVersion: 1.0
paths:
  content: content
  output: output
  template: template/template.docx
""", encoding="utf-8")

        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = main(["export", "--project", str(proj), "-D", "INVALID_KEY_NO_EQUALS"])
        assert code == 2
        assert "属性参数格式非法" in err_buf.getvalue()

    def test_cli_json_mode_stdout_is_pure_json(self, tmp_path):
        """测试用例：在 --json 模式下，stdout 100% 为纯净合法的 JSON 字符串，无任何进度或日志污染。"""
        proj = tmp_path / "json_proj"
        proj.mkdir()
        (proj / "project.yml").write_text("""schemaVersion: 2
documentType: general
documentName: JSON测试项目
documentVersion: 1.0
documentNo: DOC-JSON-001
paths:
  content: content
  output: output
  template: template/template.docx
""", encoding="utf-8")

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = main(["export", "--project", str(proj), "--inspect-properties", "--json"])
        assert code == 0

        # 断言 stdout 能够被 json.loads 且包含预期字段
        raw_out = out_buf.getvalue().strip()
        data = json.loads(raw_out)
        assert data["documentName"] == "JSON测试项目"
        assert data["documentNo"] == "DOC-JSON-001"
        assert data["documentType"] == "general"
