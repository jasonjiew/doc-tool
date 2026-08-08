# -*- coding: utf-8 -*-
"""项目化构建回归测试。

任务 2.5：验证新旧入口的事件流、模板语义和最终正文一致。
任务 2.6：增加 Unicode、空格、括号、``&`` 及路径越界的项目化回归测试。

测试策略：
1. 创建临时项目目录，同时包含旧入口的 ``config/requirement.yml`` 和新入口的
   ``project.yml``，两者指向同一套模板/内容/资源。
2. 分别用 ``build_docx.build(config=legacy_config)`` 和
   ``build_with_project(manifest, paths)`` 构建，比较输出 DOCX 的字节哈希。
3. 用 ``validate_docx.validate`` 校验两份输出，确保事件流一致。
4. 在含中文/空格/括号/``&`` 的项目路径上重复构建，验证路径兼容性。
5. 验证 ``ProjectPaths.resolve`` 拒绝 ``..`` 越界和绝对路径。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/tests/ -> scripts/ -> doc-automation/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPTS)

from build_docx import build as build_docx  # noqa: E402
from docx_common import load_config  # noqa: E402
from doc_tool.adapters.kernel import (  # noqa: E402
    build_with_project,
    config_from_project,
    ensure_kernel_importable,
    validate_with_project,
)
from doc_tool.domain.errors import PathEscapeError  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402
from validate_docx import DocxPackage, validate as validate_docx  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


REQUIREMENT_TEMPLATE = os.path.join(REPO_ROOT, "templates", "requirement-template.docx")

LEGACY_CONFIG_BODY = """\
documentType: requirement
documentNo: KF-TEST-001
documentName: 项目化构建测试
documentVersion: "1.0"
template:
  file: ../template/template.docx
contentRoot:
  path: ../content/requirement
assetRoot: ../assets/requirement
tableRoot: ../assets/requirement/tables
headingStyles:
  1: "2"
  2: "3"
  3: "5"
  4: "6"
  5: "7"
  6: "8"
bodyStyle: "4"
output:
  file: "../output/legacy-build.docx"
refresh:
  timeoutSeconds: 900
"""

MINIMAL_CONTENT = {
    "1 概述/_index.md": "本文档用于验证项目化构建与旧入口一致。\n",
    "1 概述/1.1 背景.md": "测试背景描述。\n\n| 字段 | 值 |\n| --- | --- |\n| 名称 | 测试 |\n",
    "1 概述/1.2 目标.md": "验证新旧入口输出一致。\n",
    "2 详细设计/_index.md": "详细设计概述。\n",
    "2 详细设计/2.1 架构.md": "系统架构说明。\n",
}


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _setup_project(root: str) -> str:
    """在 ``root`` 下创建自包含项目（同时支持旧入口和新入口）。"""
    # 模板
    template_dir = os.path.join(root, "template")
    os.makedirs(template_dir, exist_ok=True)
    shutil.copy2(REQUIREMENT_TEMPLATE, os.path.join(template_dir, "template.docx"))
    # 内容
    content_dir = os.path.join(root, "content", "requirement")
    for relative, body in MINIMAL_CONTENT.items():
        path = os.path.join(content_dir, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    # 资源目录
    for sub in ("images", "tables"):
        os.makedirs(os.path.join(root, "assets", "requirement", sub), exist_ok=True)
    # 输出目录
    os.makedirs(os.path.join(root, "output"), exist_ok=True)
    # 旧入口配置
    config_dir = os.path.join(root, "config")
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "requirement.yml"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(LEGACY_CONFIG_BODY)
    return root


def _make_manifest(project_root: str) -> ProjectManifest:
    """为临时项目构造清单。"""
    return ProjectManifest(
        documentType="requirement",
        documentNo="KF-TEST-001",
        documentName="项目化构建测试",
        documentVersion="1.0",
        sourceSha256="",
        paths={
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content/requirement",
            "assetRoot": "assets/requirement",
            "tableRoot": "assets/requirement/tables",
        },
        headingStyles={1: "2", 2: "3", 3: "5", 4: "6", 5: "7", 6: "8"},
        bodyStyle="4",
    )


class LegacyProjectConsistencyTests(unittest.TestCase):
    """任务 2.5：新旧入口产出一致。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="doc-project-build-")
        self.project_root = _setup_project(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_build_outputs_are_byte_identical(self) -> None:
        """同一模板/内容/资源下，新旧入口构建的 DOCX 字节哈希一致。"""
        # 旧入口：load_config + build(config=...)
        legacy_config = load_config("requirement", self.project_root)
        legacy_output = build_docx(config=legacy_config)

        # 新入口：ProjectManifest + build_with_project
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        project_output = build_with_project(manifest, paths)

        # 比较字节哈希
        self.assertEqual(_sha256(legacy_output), _sha256(project_output))

    def test_validate_events_are_identical(self) -> None:
        """新旧入口的校验事件流（Heading/正文/表格）一致。"""
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        # 构建两份输出
        legacy_config = load_config("requirement", self.project_root)
        legacy_output = build_docx(config=legacy_config)
        project_output = build_with_project(manifest, paths)

        # 提取事件流
        legacy_events = DocxPackage(legacy_output).body_events()
        project_events = DocxPackage(project_output).body_events()

        def signature(event):
            return ("T" if event.kind in ("T", "C") else event.kind, event.value)

        self.assertEqual(
            [signature(e) for e in legacy_events],
            [signature(e) for e in project_events],
        )

    def test_project_validate_matches_legacy(self) -> None:
        """新旧入口的校验结果一致（同时通过或同时失败）。"""
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        legacy_config = load_config("requirement", self.project_root)
        legacy_output = build_docx(config=legacy_config)
        project_output = build_with_project(manifest, paths)

        legacy_ok = validate_docx(
            doc_type="requirement",
            output_override=legacy_output,
            config=legacy_config,
            report_override=os.path.join(self._tmp, "legacy-report.md"),
        )
        project_ok = validate_with_project(
            manifest, paths, report_override=os.path.join(self._tmp, "project-report.md")
        )
        # 两入口校验结果必须一致（模板已有孤立关系时同时失败，内容完整时同时通过）。
        self.assertEqual(legacy_ok, project_ok)

    def test_config_from_project_matches_legacy(self) -> None:
        """config_from_project 产出的路径与 load_config 一致。"""
        legacy_config = load_config("requirement", self.project_root)
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        project_config = config_from_project(manifest, paths)

        for key in ("template", "content_root", "asset_root", "table_root"):
            self.assertEqual(
                os.path.normpath(legacy_config["paths"][key]),
                os.path.normpath(project_config["paths"][key]),
                "路径 {0} 不一致".format(key),
            )
        self.assertEqual(
            legacy_config["headingStyles"],
            project_config["headingStyles"],
        )
        self.assertEqual(legacy_config["bodyStyle"], project_config["bodyStyle"])


class SpecialPathRegressionTests(unittest.TestCase):
    """任务 2.6：中文/空格/括号/``&`` 路径与路径越界回归。"""

    def test_build_with_chinese_space_bracket_ampersand_path(self) -> None:
        """在含中文、空格、括号、& 的项目路径下构建成功。"""
        special_name = "测试 项目(1.0) & 验证"
        tmp = tempfile.mkdtemp(prefix="doc-special-path-")
        try:
            project_root = os.path.join(tmp, special_name)
            _setup_project(project_root)
            manifest = _make_manifest(project_root)
            paths = manifest.resolve_paths(project_root)
            output = build_with_project(manifest, paths)
            self.assertTrue(os.path.isfile(output))
            # 路径中包含特殊字符
            self.assertIn(special_name, output)
            # 与旧入口产出一致
            legacy_config = load_config("requirement", project_root)
            legacy_output = build_docx(config=legacy_config)
            self.assertEqual(_sha256(output), _sha256(legacy_output))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_manifest_roundtrip_with_special_path(self) -> None:
        """清单在特殊路径下保存/加载后路径仍正确。"""
        special_name = "路径 & 测试(2.5)"
        tmp = tempfile.mkdtemp(prefix="doc-manifest-rt-")
        try:
            project_root = os.path.join(tmp, special_name)
            os.makedirs(project_root)
            manifest = _make_manifest(project_root)
            manifest.save(project_root, backup=False)
            loaded = ProjectManifest.load(project_root)
            self.assertEqual(loaded.documentNo, manifest.documentNo)
            self.assertEqual(loaded.headingStyles, manifest.headingStyles)
            self.assertEqual(loaded.bodyStyle, manifest.bodyStyle)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_path_escape_rejected_in_resource(self) -> None:
        """资源路径越界（..）被 ProjectPaths 拒绝。"""
        paths = ProjectPaths(tempfile.mkdtemp(prefix="doc-escape-"))
        with self.assertRaises(PathEscapeError):
            paths.resolve("../../../etc/passwd")

    def test_absolute_path_rejected(self) -> None:
        """绝对路径作为项目内资源被拒绝。"""
        paths = ProjectPaths(tempfile.mkdtemp(prefix="doc-abs-"))
        with self.assertRaises(PathEscapeError):
            paths.resolve("C:/Windows/System32")

    def test_config_from_project_rejects_escape_in_manifest(self) -> None:
        """清单中 templateDocx 越界时 resolve_paths 抛出 PathEscapeError。"""
        tmp = tempfile.mkdtemp(prefix="doc-manifest-escape-")
        try:
            manifest = ProjectManifest(
                documentType="requirement",
                documentNo="KF-TEST",
                documentName="测试",
                documentVersion="1.0",
                sourceSha256="",
                paths={"templateDocx": "../../escape.docx"},
                headingStyles={1: "2"},
                bodyStyle="4",
            )
            with self.assertRaises(PathEscapeError):
                manifest.resolve_paths(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PipelineServiceTests(unittest.TestCase):
    """任务 2.4：结构化管线服务返回阶段事件和错误码。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="doc-pipeline-")
        self.project_root = _setup_project(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_skip_word_refresh_pipeline_returns_structured_events(self) -> None:
        """跳过 Word 刷新的管线返回结构化阶段事件（构建阶段必须成功）。"""
        from doc_tool.application.pipeline import (
            STAGE_BUILD,
            STAGE_VALIDATE_PRE,
            run_pipeline,
        )

        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        result = run_pipeline(manifest, paths, skip_word_refresh=True)

        stages = [(e.stage, e.status) for e in result.events]
        # 构建阶段必须成功
        self.assertIn((STAGE_BUILD, "succeeded"), stages)
        # 刷新前校验阶段必须执行（可能因模板已有孤立关系而失败）
        self.assertIn(STAGE_VALIDATE_PRE, [s for s, _ in stages])
        self.assertIsNotNone(result.output_path)
        # 每个事件都有阶段名和状态
        for event in result.events:
            self.assertTrue(event.stage)
            self.assertIn(event.status, ("started", "succeeded", "failed", "skipped", "cancelled"))

    def test_build_failure_returns_error_code(self) -> None:
        """构建失败时返回结构化错误码。"""
        from doc_tool.application.pipeline import run_pipeline

        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        # 删除模板，制造构建失败
        os.remove(str(paths.template_docx))
        result = run_pipeline(manifest, paths, skip_word_refresh=True)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_code)
        self.assertTrue(len(result.events) > 0)
        self.assertEqual(result.events[-1].status, "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
