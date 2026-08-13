# -*- coding: utf-8 -*-
"""Word 正式发布闭环测试。

任务 7.5：增加 Word 缺失、超时、保存失败和后校验失败时保留旧输出的测试。
任务 7.6：在现有 349 页需求文档和 576 页详细设计文档上执行最终实机回归
         与视觉抽检（见文件末尾人工操作清单）。

覆盖范围：
- 7.1 Word 可用性检查（pywin32/交互式会话/DispatchEx 探测）
- 7.3 临时构建→前校验→Word 刷新→后校验→原子发布统一用例
- 7.4 输出状态元数据（formal/diagnostic/failureCode）
- 7.5 Word 缺失：正式模式预检失败，返回 E3001，不获取锁，不修改正式输出
- 7.5 Word 超时/刷新失败：refresh 返回 False，返回 E3001，正式输出保留
- 7.5 Word 保存异常：refresh 抛异常，映射到 E3003，正式输出保留
- 7.5 后校验失败：post-validate 返回 False，返回 E2002，正式输出保留
- 7.5 诊断构建：跳过 Word，发布成功但状态为 diagnostic（非 formal）
- 7.5 失败后状态文件标记 formal=False
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WordCheckTests(unittest.TestCase):
    """任务 7.1：Word 可用性检查。"""

    def test_pywin32_check_returns_bool(self):
        """check_pywin32 返回布尔值，不抛异常。"""
        from doc_tool.application.word_check import check_pywin32

        result = check_pywin32()
        self.assertIsInstance(result, bool)

    def test_interactive_session_check_returns_bool(self):
        """check_interactive_session 返回布尔值，不抛异常。"""
        from doc_tool.application.word_check import check_interactive_session

        result = check_interactive_session()
        self.assertIsInstance(result, bool)

    def test_word_availability_report_structure(self):
        """check_word_available 返回完整报告。"""
        from doc_tool.application.word_check import (
            WordAvailability,
            check_word_available,
        )

        # 静态检查模式（不实际启动 Word）
        report = check_word_available(dispatch_check=False)
        self.assertIsInstance(report, WordAvailability)
        self.assertIsInstance(report.available, bool)
        self.assertIsInstance(report.pywin32_available, bool)
        self.assertIsInstance(report.interactive_session, bool)
        self.assertIsInstance(report.reasons, list)
        # to_dict 可序列化
        data = report.to_dict()
        json.dumps(data, ensure_ascii=False)

    def test_word_availability_to_dict_has_required_fields(self):
        """报告字典包含所有必需字段。"""
        from doc_tool.application.word_check import check_word_available

        report = check_word_available(dispatch_check=False)
        data = report.to_dict()
        for key in (
            "available", "pywin32Available", "interactiveSession",
            "wordDispatchable", "version", "reasons",
        ):
            self.assertIn(key, data)

    def test_non_windows_interactive_session_false(self):
        """非 Windows 平台交互式会话检查返回 False。"""
        from doc_tool.application import word_check

        with patch.object(word_check.os, "name", "posix"):
            result = word_check.check_interactive_session()
            self.assertFalse(result)

    def test_service_profile_detected_as_non_interactive(self):
        """服务账号 profile 被识别为非交互式。"""
        from doc_tool.application import word_check

        with patch.dict(os.environ, {"USERPROFILE": "C:\\Windows\\ServiceProfiles\\LocalService"}):
            with patch.object(word_check.os, "name", "nt"):
                result = word_check.check_interactive_session()
                self.assertFalse(result)

    def test_empty_user_profile_detected_as_non_interactive(self):
        """空 USERPROFILE 被识别为非交互式。"""
        from doc_tool.application import word_check

        # 临时移除 USERPROFILE
        original = os.environ.pop("USERPROFILE", None)
        try:
            with patch.object(word_check.os, "name", "nt"):
                result = word_check.check_interactive_session()
                self.assertFalse(result)
        finally:
            if original is not None:
                os.environ["USERPROFILE"] = original

    def test_session_name_services_detected(self):
        """SESSIONNAME=Services 被识别为非交互式。"""
        from doc_tool.application import word_check

        with patch.dict(os.environ, {
            "USERPROFILE": "C:\\Users\\test",
            "SESSIONNAME": "Services",
        }):
            with patch.object(word_check.os, "name", "nt"):
                result = word_check.check_interactive_session()
                self.assertFalse(result)


class OutputStateTests(unittest.TestCase):
    """任务 7.4：输出状态元数据。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-state-")
        self.output_path = os.path.join(self._tmp, "GX-001 文档(1.0).docx")
        # 写入占位 DOCX
        with open(self.output_path, "wb") as handle:
            handle.write(b"fake docx content for hashing")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_write_and_read_formal_state(self):
        """写入正式成功状态后可读回。"""
        from doc_tool.domain.output_state import (
            is_formal_success,
            read_state,
            write_state,
        )

        write_state(
            self.output_path,
            formal=True,
            diagnostic=False,
            app_version="1.0.0",
            commit="abc123",
            schema_version=1,
            stages=[{"stage": "build", "status": "succeeded"}],
        )
        self.assertTrue(is_formal_success(self.output_path))

        state = read_state(self.output_path)
        self.assertIsNotNone(state)
        self.assertTrue(state.formal)
        self.assertFalse(state.diagnostic)
        self.assertEqual(state.appVersion, "1.0.0")
        self.assertEqual(state.commit, "abc123")
        self.assertEqual(state.schemaVersion, 1)
        self.assertEqual(state.outputFile, "GX-001 文档(1.0).docx")
        # SHA-256 应为完整 64 位指纹
        self.assertEqual(len(state.outputSha256), 64)
        self.assertEqual(state.outputSha256, _sha256(self.output_path))
        self.assertEqual(len(state.stages), 1)

    def test_write_diagnostic_state(self):
        """诊断构建状态 formal=False, diagnostic=True。"""
        from doc_tool.domain.output_state import (
            is_formal_success,
            read_state,
            write_state,
        )

        write_state(
            self.output_path,
            formal=False,
            diagnostic=True,
            app_version="1.0.0",
        )
        self.assertFalse(is_formal_success(self.output_path))

        state = read_state(self.output_path)
        self.assertIsNotNone(state)
        self.assertFalse(state.formal)
        self.assertTrue(state.diagnostic)

    def test_failure_state_records_error_code(self):
        """失败状态记录错误码。"""
        from doc_tool.domain.output_state import read_last_attempt_state, write_state

        write_state(
            self.output_path,
            formal=False,
            diagnostic=False,
            app_version="1.0.0",
            failure_code="E3001",
            compute_hash=False,
        )
        state = read_last_attempt_state(self.output_path)
        self.assertIsNotNone(state)
        self.assertEqual(state.failureCode, "E3001")
        # compute_hash=False 时哈希为空
        self.assertEqual(state.outputSha256, "")

    def test_formal_state_rejected_after_output_is_modified(self):
        from doc_tool.domain.output_state import is_formal_success, write_state

        write_state(self.output_path, formal=True, diagnostic=False)
        self.assertTrue(is_formal_success(self.output_path))
        Path(self.output_path).write_bytes(b"tampered after validation")
        self.assertFalse(is_formal_success(self.output_path))

    def test_string_false_is_not_accepted_as_boolean(self):
        from doc_tool.domain.output_state import read_state, state_file_for

        state_file_for(self.output_path).write_text(
            json.dumps({"formal": "false", "diagnostic": False, "stages": []}),
            encoding="utf-8",
        )
        self.assertIsNone(read_state(self.output_path))

    def test_missing_state_not_formal(self):
        """状态文件不存在时 is_formal_success 返回 False。"""
        from doc_tool.domain.output_state import is_formal_success

        # 状态文件不存在
        self.assertFalse(is_formal_success(self.output_path))

    def test_corrupt_state_returns_none(self):
        """损坏的状态文件返回 None。"""
        from doc_tool.domain.output_state import (
            read_state,
            state_file_for,
        )

        state_path = state_file_for(self.output_path)
        state_path.write_text("not valid json {", encoding="utf-8")
        self.assertIsNone(read_state(self.output_path))

    def test_state_file_naming(self):
        """状态文件名 = 输出文件名 + .state.json。"""
        from doc_tool.domain.output_state import state_file_for

        state_path = state_file_for(self.output_path)
        self.assertEqual(state_path.name, "GX-001 文档(1.0).docx.state.json")
        self.assertEqual(state_path.parent, Path(self.output_path).parent)


class PipelineWordReleaseTests(unittest.TestCase):
    """任务 7.5：Word 缺失/超时/保存失败/后校验失败保留旧输出。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-word-rel-")
        self.project_root = self._tmp
        from test_project_build import _setup_project, _make_manifest
        _setup_project(self.project_root)
        self._make_manifest = _make_manifest

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _formal_output_path(self, manifest, paths):
        output_name = "{0} {1}({2}).docx".format(
            manifest.documentNo, manifest.documentName, manifest.documentVersion
        )
        return paths.output_dir / output_name

    def test_formal_pipeline_blocked_when_word_unavailable(self):
        """正式模式在 Word 不可用时返回 E3001，不获取锁，不修改正式输出。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.project_lock import inspect_lock

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        # 预先创建一个「旧正式输出」，验证它不被修改
        formal = self._formal_output_path(manifest, paths)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        formal.write_bytes(b"previous formal output")
        previous_hash = _sha256(str(formal))

        # 模拟 Word 不可用
        fake_report = word_check.WordAvailability(available=False)
        with patch.object(word_check, "check_word_available", return_value=fake_report):
            result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E3001")
        # 不应获取锁（预检失败前就返回）
        self.assertIsNone(inspect_lock(paths))
        # 正式输出未被修改
        self.assertTrue(formal.exists())
        self.assertEqual(_sha256(str(formal)), previous_hash)

    def test_word_refresh_failure_preserves_previous_output(self):
        """Word 刷新失败（refresh 返回 False）时保留旧正式输出。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.adapters import kernel

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        # 预先创建旧正式输出
        formal = self._formal_output_path(manifest, paths)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        formal.write_bytes(b"previous formal output")
        previous_hash = _sha256(str(formal))
        from doc_tool.domain.output_state import write_state
        write_state(str(formal), formal=True, diagnostic=False)

        # Word 可用但刷新返回 False（模拟超时/失败）
        # 同时 mock 前校验为 True，确保管线到达 Word 刷新阶段
        fake_report = word_check.WordAvailability(available=True)
        with patch.object(word_check, "check_word_available", return_value=fake_report):
            with patch.object(kernel, "refresh_with_project", return_value=False):
                with patch.object(kernel, "validate_with_project", return_value=True):
                    result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E3001")
        # 正式输出未被修改
        self.assertTrue(formal.exists())
        self.assertEqual(_sha256(str(formal)), previous_hash)
        # 临时文件应被清理
        temp_file = paths.output_dir / ("." + formal.name + ".tmp")
        self.assertFalse(temp_file.exists())
        # 上一次正式状态保持不变，失败尝试写入独立状态文件
        from doc_tool.domain.output_state import read_last_attempt_state, read_state
        state = read_state(str(formal))
        self.assertIsNotNone(state)
        self.assertTrue(state.formal)
        attempt = read_last_attempt_state(str(formal))
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.failureCode, "E3001")

    def test_word_save_exception_preserves_previous_output(self):
        """Word 保存异常时映射到错误码，保留旧正式输出。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.adapters import kernel
        from docx_common import AutomationError

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        formal = self._formal_output_path(manifest, paths)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        formal.write_bytes(b"previous formal output")
        previous_hash = _sha256(str(formal))

        # Word 可用但刷新抛出保存异常
        fake_report = word_check.WordAvailability(available=True)

        def raising_refresh(*args, **kwargs):
            raise AutomationError("Word 保存失败：磁盘空间不足")

        with patch.object(word_check, "check_word_available", return_value=fake_report):
            with patch.object(kernel, "refresh_with_project", side_effect=raising_refresh):
                with patch.object(kernel, "validate_with_project", return_value=True):
                    result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertFalse(result.success)
        # 保存异常应映射到 E3003（WordSaveFailedError）
        self.assertEqual(result.error_code, "E3003")
        self.assertTrue(formal.exists())
        self.assertEqual(_sha256(str(formal)), previous_hash)
        # 临时文件应被清理
        temp_file = paths.output_dir / ("." + formal.name + ".tmp")
        self.assertFalse(temp_file.exists())

    def test_word_timeout_preserves_previous_output(self):
        """Word 超时（异常消息含超时）映射到 E3002，保留旧正式输出。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.adapters import kernel
        from docx_common import AutomationError

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        formal = self._formal_output_path(manifest, paths)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        formal.write_bytes(b"previous formal output")
        previous_hash = _sha256(str(formal))

        fake_report = word_check.WordAvailability(available=True)

        def timeout_refresh(*args, **kwargs):
            raise AutomationError("Word 刷新超过 900 秒")

        with patch.object(word_check, "check_word_available", return_value=fake_report):
            with patch.object(kernel, "refresh_with_project", side_effect=timeout_refresh):
                with patch.object(kernel, "validate_with_project", return_value=True):
                    result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E3002")
        self.assertTrue(formal.exists())
        self.assertEqual(_sha256(str(formal)), previous_hash)

    def test_post_validate_failure_preserves_previous_output(self):
        """后校验失败时返回 E2002，保留旧正式输出。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.adapters import kernel

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        formal = self._formal_output_path(manifest, paths)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        formal.write_bytes(b"previous formal output")
        previous_hash = _sha256(str(formal))
        from doc_tool.domain.output_state import write_state
        write_state(str(formal), formal=True, diagnostic=False)

        fake_report = word_check.WordAvailability(available=True)

        # 构建成功 + 前校验通过 + Word 刷新成功 + 后校验失败
        # 前校验返回 True（避免测试夹具模板的孤立关系影响），
        # 后校验（require_refreshed=True）返回 False
        def selective_validate(manifest, paths, output_override=None, baseline=False,
                               require_refreshed=False, report_override=None):
            return not require_refreshed  # 前校验 True，后校验 False

        with patch.object(word_check, "check_word_available", return_value=fake_report):
            with patch.object(kernel, "refresh_with_project", return_value=True):
                with patch.object(kernel, "validate_with_project", side_effect=selective_validate):
                    result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "E2002")
        # 正式输出未被修改
        self.assertTrue(formal.exists())
        self.assertEqual(_sha256(str(formal)), previous_hash)
        # 临时文件应被清理
        temp_file = paths.output_dir / ("." + formal.name + ".tmp")
        self.assertFalse(temp_file.exists())
        # 上次正式状态仍与旧输出匹配；本次失败另记 attempt 状态
        from doc_tool.domain.output_state import read_last_attempt_state, read_state
        state = read_state(str(formal))
        self.assertIsNotNone(state)
        self.assertTrue(state.formal)
        attempt = read_last_attempt_state(str(formal))
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt.failureCode, "E2002")

    def test_diagnostic_build_publishes_but_marked_non_formal(self):
        """诊断构建（skip_word_refresh=True）发布成功但标记为非正式。"""
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.output_state import is_formal_success, read_state

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        # mock 前校验通过（测试夹具模板有孤立关系会导致真实校验失败）
        with patch.object(kernel, "validate_with_project", return_value=True):
            result = run_pipeline(manifest, paths, skip_word_refresh=True)

        # 诊断构建应成功发布
        self.assertTrue(result.success)
        self.assertIsNotNone(result.output_path)
        formal = self._formal_output_path(manifest, paths)
        self.assertTrue(formal.exists())

        # 但状态元数据标记为非正式
        self.assertFalse(is_formal_success(str(formal)))
        state = read_state(str(formal))
        self.assertIsNotNone(state)
        self.assertFalse(state.formal)
        self.assertTrue(state.diagnostic)
        self.assertEqual(state.failureCode, "")

    def test_build_failure_writes_failure_state(self):
        """构建失败时写入失败状态文件。"""
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.output_state import read_last_attempt_state, read_state

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        # 删除模板制造构建失败
        os.remove(str(paths.template_docx))

        result = run_pipeline(manifest, paths, skip_word_refresh=True)

        self.assertFalse(result.success)
        formal = self._formal_output_path(manifest, paths)
        # 正式输出不存在（构建失败，从未发布）
        self.assertFalse(formal.exists())
        # 未发布产物没有成功状态；失败尝试写入独立状态文件
        self.assertIsNone(read_state(str(formal)))
        state = read_last_attempt_state(str(formal))
        self.assertIsNotNone(state)
        self.assertNotEqual(state.failureCode, "")

    def test_formal_success_writes_formal_state(self):
        """正式成功（mock Word 可用 + 刷新成功 + 后校验通过）写入 formal=True。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.adapters import kernel
        from doc_tool.domain.output_state import is_formal_success, read_state

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        fake_report = word_check.WordAvailability(available=True)

        with patch.object(word_check, "check_word_available", return_value=fake_report):
            with patch.object(kernel, "refresh_with_project", return_value=True):
                # 使用真实 validate，但 require_refreshed=True 时也返回 True
                # （测试夹具的模板可能让后校验失败，所以强制 mock）
                with patch.object(kernel, "validate_with_project", return_value=True):
                    result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertTrue(result.success)
        formal = self._formal_output_path(manifest, paths)
        self.assertTrue(formal.exists())
        # 状态元数据标记为正式
        self.assertTrue(is_formal_success(str(formal)))
        state = read_state(str(formal))
        self.assertIsNotNone(state)
        self.assertTrue(state.formal)
        self.assertFalse(state.diagnostic)
        self.assertEqual(state.failureCode, "")
        # SHA-256 完整指纹
        self.assertEqual(len(state.outputSha256), 64)
        self.assertEqual(state.outputSha256, _sha256(str(formal)))
        # 阶段摘要包含所有阶段
        stage_names = [s["stage"] for s in state.stages]
        for stage in ("build", "validate_pre", "word_refresh", "validate_post", "publish"):
            self.assertIn(stage, stage_names)

    def test_atomic_publish_no_partial_output_on_failure(self):
        """失败时正式输出目录中不残留临时文件。"""
        from doc_tool.application import word_check
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.adapters import kernel

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        fake_report = word_check.WordAvailability(available=True)
        with patch.object(word_check, "check_word_available", return_value=fake_report):
            with patch.object(kernel, "refresh_with_project", return_value=False):
                result = run_pipeline(manifest, paths, skip_word_refresh=False)

        self.assertFalse(result.success)
        # 输出目录中无 .tmp 文件残留
        temp_files = list(paths.output_dir.glob(".*.tmp"))
        self.assertEqual(len(temp_files), 0)


class PipelineAtomicPublishTests(unittest.TestCase):
    """任务 7.3：原子发布与状态元数据集成。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="doc-atomic-")
        self.project_root = self._tmp
        from test_project_build import _setup_project, _make_manifest
        _setup_project(self.project_root)
        self._make_manifest = _make_manifest

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_publish_stage_emitted_on_success(self):
        """成功时事件流包含 publish 阶段。"""
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import (
            STAGE_PUBLISH,
            run_pipeline,
        )

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        # mock 前校验通过
        with patch.object(kernel, "validate_with_project", return_value=True):
            result = run_pipeline(manifest, paths, skip_word_refresh=True)

        stages = [e.stage for e in result.events]
        self.assertIn(STAGE_PUBLISH, stages)
        # publish 阶段成功
        publish_events = [e for e in result.events if e.stage == STAGE_PUBLISH]
        self.assertTrue(any(e.status == "succeeded" for e in publish_events))

    def test_output_path_returns_formal_not_temp(self):
        """返回的 output_path 是正式路径，不是临时文件。"""
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import run_pipeline

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        with patch.object(kernel, "validate_with_project", return_value=True):
            result = run_pipeline(manifest, paths, skip_word_refresh=True)

        self.assertIsNotNone(result.output_path)
        # 不含 .tmp 后缀
        self.assertFalse(result.output_path.endswith(".tmp"))
        # 不以 . 开头（临时文件以 . 开头）
        basename = os.path.basename(result.output_path)
        self.assertFalse(basename.startswith("."))

    def test_repeated_pipeline_overwrites_formal_atomically(self):
        """重复执行管线时正式输出被原子覆盖，无残留临时文件。"""
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import run_pipeline

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        with patch.object(kernel, "validate_with_project", return_value=True):
            result1 = run_pipeline(manifest, paths, skip_word_refresh=True)
            result2 = run_pipeline(manifest, paths, skip_word_refresh=True)

        self.assertTrue(result1.success)
        self.assertTrue(result2.success)
        # 正式输出存在
        formal = Path(result1.output_path)
        self.assertTrue(formal.exists())
        # 无临时文件残留
        temp_files = list(paths.output_dir.glob(".*.tmp"))
        self.assertEqual(len(temp_files), 0)
        # 状态文件存在
        from doc_tool.domain.output_state import state_file_for
        self.assertTrue(state_file_for(str(formal)).exists())

    def test_state_write_failure_rolls_back_docx_and_state(self):
        """DOCX 替换后状态写入失败时恢复上一版完整发布。"""
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.output_state import state_file_for

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        with patch.object(kernel, "validate_with_project", return_value=True):
            first = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertTrue(first.success)
        formal = Path(first.output_path)
        state_path = state_file_for(formal)
        old_doc_hash = _sha256(str(formal))
        old_state = state_path.read_bytes()
        md_file = next(paths.content_dir(manifest.documentType).rglob("*.md"))
        md_file.write_text(
            md_file.read_text(encoding="utf-8") + "\n回滚测试新增内容。\n",
            encoding="utf-8",
        )

        with patch.object(kernel, "validate_with_project", return_value=True):
            with patch(
                "doc_tool.domain.output_state.write_state",
                side_effect=OSError("state disk failure"),
            ):
                second = run_pipeline(manifest, paths, skip_word_refresh=True)

        self.assertFalse(second.success)
        self.assertEqual(_sha256(str(formal)), old_doc_hash)
        self.assertEqual(state_path.read_bytes(), old_state)

    def test_successful_pipeline_persists_last_build_version(self):
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.manifest import ProjectManifest
        from doc_tool.domain.version import APP_VERSION

        manifest = self._make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        with patch.object(kernel, "validate_with_project", return_value=True):
            result = run_pipeline(manifest, paths, skip_word_refresh=True)
        self.assertTrue(result.success)
        loaded = ProjectManifest.load(self.project_root)
        self.assertEqual(loaded.lastSuccessfulBuildVersion, APP_VERSION)


# === 任务 7.6 人工操作清单 ===
# 在现有 349 页需求文档和 576 页详细设计文档上执行最终实机回归与视觉抽检。
# 完整清单见 analysis/manual-checklist.md 第 3 节「任务 7.6 实机回归与视觉抽检清单」。
#
# 覆盖范围：
# 1. 正式合并端到端（build/validate_pre/word_refresh/validate_post/publish）
# 2. 视觉抽检（TOC/NUMPAGES/章节编号/图片/表格/封面）
# 3. Word 缺失场景（E3001，不获取锁，不修改正式输出）
# 4. 诊断构建（formal=false, diagnostic=true）
# 5. 用户 Word 隔离（专用 DispatchEx 进程，不影响用户 Word）
# 6. 失败恢复（E2002，保留旧输出，修正后恢复）
# 7. 大文档性能（576 页，界面响应，超时内完成）


if __name__ == "__main__":
    unittest.main(verbosity=2)
