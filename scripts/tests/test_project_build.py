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
from build_docx import _find_revision_record_table, qn  # noqa: E402
from docx_common import (  # noqa: E402
    AutomationError,
    load_config,
    parse_xml_safe,
    read_docx_package,
)
from doc_tool.adapters.kernel import (  # noqa: E402
    build_with_project,
    config_from_project,
    ensure_kernel_importable,
    validate_with_project,
)
from doc_tool.domain.errors import PathEscapeError  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402
from doc_tool.domain.paths import ProjectPaths  # noqa: E402
from extract_revision_record import extract_revision_rows  # noqa: E402
from validate_docx import DocxPackage, validate as validate_docx  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


REQUIREMENT_TEMPLATE = os.path.join(REPO_ROOT, "templates", "requirement-template.docx")

LEGACY_CONFIG_BODY = """\
documentType: requirement
documentNo: GX-TEST-001
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

# 修订记录 Markdown：第 2 行摘要含 ``\|`` 转义，验证构建侧还原成裸竖线。
REVISION_RECORD_MD = r"""<!-- 修订记录（自动提取自模板，可手动编辑） -->

# 修订记录 - requirement

| 版本 | 修订摘要 | 修订时间 | 修订人 |
|------|----------|----------|--------|
| V1.0 | 初始版本 | 2026-01-01 | 张三 |
| V1.1 | 新增模块：3.7产品管理->3.7.9呼吸机应用升级 \| 边界说明 | 2026-08-20 | 李四 |
"""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _header_texts(docx_path: str) -> list:
    """全部页眉部件里的非空文本节点（校验页眉「版次」写成了什么）。"""
    with read_docx_package(docx_path) as package:
        items = package.read_all()
    texts: list = []
    for name in sorted(items):
        if not (name.startswith("word/header") and name.endswith(".xml")):
            continue
        root = parse_xml_safe(items[name], name)
        texts.extend(
            (node.text or "").strip()
            for node in root.iter(qn("t"))
            if (node.text or "").strip()
        )
    return texts


def _revision_table_rows(docx_path: str) -> list:
    """修订记录表的全部 ``w:tr``（前 2 行是表头）。"""
    with read_docx_package(docx_path) as package:
        items = package.read_all()
    root = parse_xml_safe(items["word/document.xml"], "word/document.xml")
    table = _find_revision_record_table(root.find(qn("body")))
    return table.findall(qn("tr")) if table is not None else []


def _row_format_signature(row) -> tuple:
    """行排版签名：行属性 + 每个单元格的宽度/边框/对齐/字符格式。

    模板数据行靠 ``w:trPr`` 的 ``gridBefore``（整行右移一个网格列）、``pct``
    宽度和逐单元格 ``tcBorders`` 定位；重建行必须逐项保持一致，否则在 Word
    里表现为无边框、与表头错开一列、列宽不对。
    """
    row_properties = row.find(qn("trPr"))

    def value_of(parent, *path):
        node = parent
        for name in path:
            if node is None:
                return None
            node = node.find(qn(name))
        return node.get(qn("val")) if node is not None else None

    cells = []
    for cell in row.findall(qn("tc")):
        cell_properties = cell.find(qn("tcPr"))
        width = cell_properties.find(qn("tcW")) if cell_properties is not None else None
        paragraph = cell.find(qn("p"))
        run = paragraph.find(qn("r")) if paragraph is not None else None
        cells.append((
            width.get(qn("w")) if width is not None else None,
            width.get(qn("type")) if width is not None else None,
            cell_properties is not None and cell_properties.find(qn("tcBorders")) is not None,
            value_of(cell_properties, "vAlign"),
            value_of(paragraph, "pPr", "jc"),
            run is not None and run.find(qn("rPr")) is not None,
        ))
    return (
        value_of(row_properties, "gridBefore"),
        value_of(row_properties, "trHeight"),
        row_properties is not None and row_properties.find(qn("cantSplit")) is not None,
        tuple(cells),
    )


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
        documentNo="GX-TEST-001",
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
        legacy_hash = _sha256(legacy_output)
        project_hash = _sha256(project_output)
        if legacy_hash != project_hash:
            # 失败时打印具体差异的 zip 条目，
            # 便于区分环境差异与真实不一致。
            import zipfile
            with zipfile.ZipFile(legacy_output) as za, zipfile.ZipFile(
                project_output
            ) as zb:
                names_a = {i.filename: i.CRC for i in za.infolist()}
                names_b = {i.filename: i.CRC for i in zb.infolist()}
                only_a = sorted(set(names_a) - set(names_b))
                only_b = sorted(set(names_b) - set(names_a))
                differing = sorted(
                    k for k in set(names_a) & set(names_b)
                    if names_a[k] != names_b[k]
                )
            print('legacy_only   =', only_a[:20])
            print('project_only  =', only_b[:20])
            print('crc_differs   =', differing[:20])
            print('legacy_path   =', legacy_output)
            print('project_path  =', project_output)
        self.assertEqual(legacy_hash, project_hash)

    def test_corrupt_template_raises_automation_error(self) -> None:
        """模板不是合法 DOCX 时映射为 AutomationError（统一入口中性异常）。

        回归：read_docx_package 抛 OOXMLSecurityError 时 build 侧契约映射为
        AutomationError，不得泄漏裸异常破坏 CLI 错误消息。
        """
        legacy_config = load_config("requirement", self.project_root)
        with open(legacy_config["paths"]["template"], "wb") as handle:
            handle.write(b"this is not a zip")
        with self.assertRaises(AutomationError):
            build_docx(config=legacy_config)

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
            # 两个入口可能一个产出短路径、一个产出长路径（Windows 8.3），
            # 归一化后比较，避免把等价路径误判为不一致。
            self.assertEqual(
                os.path.realpath(legacy_config["paths"][key]),
                os.path.realpath(project_config["paths"][key]),
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
                documentNo="GX-TEST",
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
        """跳过 Word 刷新的管线返回结构化阶段事件（构建与刷新前校验必须成功）。"""
        from doc_tool.application.pipeline import (
            STAGE_BUILD,
            STAGE_VALIDATE_PRE,
            run_pipeline,
        )

        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)
        result = run_pipeline(manifest, paths, skip_word_refresh=True)

        stage_map = {e.stage: e.status for e in result.events}
        # 构建阶段必须成功
        self.assertEqual(stage_map[STAGE_BUILD], "succeeded")
        # 刷新前校验必须通过并发布：管线临时文件必须是 .docx 扩展名，否则安全
        # 校验入口的扩展名硬校验会让 validate_pre 报「文件扩展名不是 .docx」，
        # 管线永远无法 publish（回归保护，旧实现把成功断言 mock 掉掩盖了该 bug）。
        self.assertEqual(stage_map[STAGE_VALIDATE_PRE], "succeeded")
        self.assertTrue(result.success, "管线应成功发布（临时文件扩展名 bug 回归）")
        self.assertIsNotNone(result.output_path)
        # 每个事件都有阶段名和状态
        for event in result.events:
            self.assertTrue(event.stage)
            self.assertIn(event.status, ("started", "succeeded", "failed", "skipped", "cancelled"))
        history_files = list(paths.state_dir.joinpath("history").glob("*.json"))
        self.assertEqual(len(history_files), 1)
        import json
        history = json.loads(history_files[0].read_text(encoding="utf-8"))
        self.assertTrue(history["diagnostic"])
        self.assertTrue(history["outputSha256"])

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
        self.assertEqual(list(paths.state_dir.joinpath("history").glob("*.json")), [])


class RevisionRecordBuildTests(unittest.TestCase):
    """回归：``_revision_record.md`` 的数据行必须出现在产物 DOCX 的修订记录表里。

    历史缺陷：``update_revision_record`` 自行解析 ``items["word/document.xml"]``
    并写回 ``items``，随后 ``build()`` 末尾又用自己的 ``document_root`` 整份序列化
    覆盖同一个键，修订记录改动被静默丢弃——正式合并写进了 Markdown、构建也报
    成功，但产物里的修订表始终停留在模板原样。原有测试只覆盖 Markdown 侧，
    所以这个缺陷一直没被拦住；本类断言最终 DOCX 的表格内容。

    注意：``paths.revision_record`` 只由新入口 ``config_from_project`` 注入，旧
    入口 ``load_config`` 不提供该键。``_setup_project`` 故意不创建修订记录文件，
    别为了这里的用例给它补上，否则会打破新旧入口字节一致的用例。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="doc-revision-build-")
        self.project_root = _setup_project(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _revision_md_path(self) -> Path:
        return Path(self.project_root) / "content" / "requirement" / "_revision_record.md"

    def test_markdown_rows_reach_output_document(self) -> None:
        """Markdown 表格的数据行原样落到产物修订表（含 ``\\|`` 转义还原）。"""
        self._revision_md_path().write_text(REVISION_RECORD_MD, encoding="utf-8")
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        output = build_with_project(manifest, paths)

        rows = extract_revision_rows(output)
        self.assertEqual([row[0] for row in rows], ["V1.0", "V1.1"])
        self.assertEqual(
            rows[1][1],
            "新增模块：3.7产品管理->3.7.9呼吸机应用升级 | 边界说明",
        )
        self.assertEqual(rows[1][2], "2026-08-20")
        self.assertEqual(rows[1][3], "李四")

    def test_template_rows_are_replaced_not_appended(self) -> None:
        """模板自带的数据行被 Markdown 全量替换，不与新行并存。"""
        template_rows = extract_revision_rows(
            os.path.join(self.project_root, "template", "template.docx")
        )
        self.assertGreater(len(template_rows), 2, "模板应自带多行修订记录")
        self._revision_md_path().write_text(REVISION_RECORD_MD, encoding="utf-8")
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        rows = extract_revision_rows(build_with_project(manifest, paths))

        self.assertEqual(len(rows), 2)
        self.assertNotIn(template_rows[-1][0], [row[0] for row in rows])

    def test_missing_markdown_keeps_template_rows(self) -> None:
        """没有 ``_revision_record.md`` 时保留模板原表，不清空、不报错。"""
        self.assertFalse(self._revision_md_path().exists())
        template_rows = extract_revision_rows(
            os.path.join(self.project_root, "template", "template.docx")
        )
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        rows = extract_revision_rows(build_with_project(manifest, paths))

        self.assertEqual(rows, template_rows)

    def test_rebuilt_rows_keep_template_row_formatting(self) -> None:
        """重建的数据行沿用模板数据行排版（行高/网格偏移/边框/宽度单位/对齐）。

        回归：原实现自建单元格，丢掉 ``w:trPr``（含 ``gridBefore``）与
        ``tcBorders``，并把 ``pct`` 宽度写成 ``dxa``，在 Word 里表现为修订表
        数据行无边框、比表头错开一列、列宽全不对——这就是「模板修订摘要排版
        有问题」的实际成因。新增行（超出模板行数的部分）沿用最后一行排版。
        """
        template_docx = os.path.join(self.project_root, "template", "template.docx")
        template_rows = _revision_table_rows(template_docx)
        self.assertGreater(len(template_rows), 2, "模板应自带数据行作为排版原型")
        expected = _row_format_signature(template_rows[2])
        # 两条数据行：第 1 条对应模板第 1 条数据行，第 2 条也在模板范围内。
        self._revision_md_path().write_text(REVISION_RECORD_MD, encoding="utf-8")
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        output_rows = _revision_table_rows(build_with_project(manifest, paths))

        self.assertEqual(len(output_rows), 4, "2 行表头 + 2 行数据")
        self.assertEqual(_row_format_signature(output_rows[2]), expected)
        # 表头两行必须原样保留。
        self.assertEqual(
            _row_format_signature(output_rows[1]),
            _row_format_signature(template_rows[1]),
        )
        # 排版签名里必须真的带上原实现丢掉的那些属性，否则断言等于什么都没查
        # （自建单元格没有 trPr/tcBorders/rPr）。用户模板另有 gridBefore，
        # 同样由整体签名比对覆盖。
        self.assertIsNotNone(expected[1], "模板数据行应带行高 trHeight")
        self.assertTrue(expected[2], "模板数据行应带 cantSplit")
        self.assertTrue(expected[3][0][2], "模板数据行首列应带 tcBorders")
        self.assertTrue(expected[3][0][5], "模板数据行首列应带字符格式 rPr")

    def test_extra_rows_follow_last_template_row_formatting(self) -> None:
        """Markdown 行数超过模板数据行时，多出来的行沿用模板最后一行排版。"""
        template_docx = os.path.join(self.project_root, "template", "template.docx")
        template_rows = _revision_table_rows(template_docx)
        data_count = len(template_rows) - 2
        expected_last = _row_format_signature(template_rows[-1])
        lines = [
            "| 版本 | 修订摘要 | 修订时间 | 修改人 |",
            "|------|----------|----------|--------|",
        ]
        for index in range(data_count + 2):  # 比模板多两行
            lines.append("| V9.{0} | 摘要{0} | 2026-08-20 | 张三 |".format(index))
        self._revision_md_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        output_rows = _revision_table_rows(build_with_project(manifest, paths))

        self.assertEqual(len(output_rows), 2 + data_count + 2)
        self.assertEqual(_row_format_signature(output_rows[-1]), expected_last)
        self.assertEqual(_row_format_signature(output_rows[-2]), expected_last)

    def test_pipeline_syncs_document_version_from_last_row(self) -> None:
        """管线按修订记录末行版本号定产物版本号，且从不改写该文件。

        ``_revision_record.md`` 是唯一维护点：作者改完就该看到产物文件名与封面
        版本号跟着走。旧实现在合并时自动追加一行并递增清单版本号，现已撤除，
        因此这里同时断言该文件字节不变。
        """
        from doc_tool.application.pipeline import STAGE_REVISION, run_pipeline

        self._revision_md_path().write_text(REVISION_RECORD_MD, encoding="utf-8")
        before = self._revision_md_path().read_text(encoding="utf-8")
        manifest = _make_manifest(self.project_root)  # documentVersion=1.0
        paths = manifest.resolve_paths(self.project_root)

        result = run_pipeline(manifest, paths, skip_word_refresh=True)

        self.assertTrue(
            result.success,
            [(e.stage, e.status, e.detail) for e in result.events],
        )
        self.assertEqual(manifest.documentVersion, "1.1")
        self.assertTrue(
            Path(result.output_path).name.endswith("(1.1).docx"), result.output_path
        )
        details = [
            event.detail
            for event in result.events
            if event.stage == STAGE_REVISION and event.status == "succeeded"
        ]
        self.assertTrue(any("1.0 → 1.1" in text for text in details), details)
        # 工具不再往修订记录里写任何东西
        self.assertEqual(self._revision_md_path().read_text(encoding="utf-8"), before)
        # 产物修订表就是该文件的数据行：表格里作者写的 V1.0/V1.1 原样保留，
        # 只有封面/页眉/文件名这三处「本次文档版本号」去掉 V 前缀。
        self.assertEqual(
            [row[0] for row in extract_revision_rows(result.output_path)],
            ["V1.0", "V1.1"],
        )
        from validate_docx import DocxPackage, cover_values

        cover_text, _cover_fields = cover_values(DocxPackage(result.output_path))
        self.assertEqual(cover_text.get("版本号"), "1.1")
        self.assertIn("1.1", _header_texts(result.output_path))
        self.assertNotIn("V1.1", _header_texts(result.output_path))

    def test_multiline_summary_becomes_line_breaks(self) -> None:
        """摘要里的 ``<br>`` 转成 ``w:br`` 换行，而不是塞进单个 ``w:t``。"""
        self._revision_md_path().write_text(
            "| 版本 | 修订摘要 | 修订时间 | 修改人 |\n"
            "|------|----------|----------|--------|\n"
            "| V1.0 | 第一行<br>第二行 | 2026-08-20 | 张三 |\n",
            encoding="utf-8",
        )
        manifest = _make_manifest(self.project_root)
        paths = manifest.resolve_paths(self.project_root)

        rows = _revision_table_rows(build_with_project(manifest, paths))

        summary_cell = rows[2].findall(qn("tc"))[1]
        self.assertEqual(len(list(summary_cell.iter(qn("br")))), 1)
        texts = [node.text for node in summary_cell.iter(qn("t"))]
        self.assertEqual(texts, ["第一行", "第二行"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
