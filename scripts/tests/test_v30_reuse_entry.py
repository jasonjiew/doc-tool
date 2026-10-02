# -*- coding: utf-8 -*-
"""V3.0 正文复用**入口与管线接线**测试（批次 30-F，任务 1.3/1.4/2.1/2.4/2.5/3.4/4.4/5.2/5.3/6.4/6.5）。

覆盖：
- CLI ``reuse list|show|extract|import|export|install`` 模块库入口与离线包交换；
- ``reuse resolve`` 统一解析报告：来源/版本/hash/行号定位、同版本缓存兜底、缺参数
  字面值、循环停止、退出码 0/1/2；
- CLI 与 ``reuse_commands`` 服务入口同源（同一份解析路径，跨入口一致）；
- ``prepared_source.prepare_markdown`` 的解析适配点 monkeypatch 后也走同一入口；
- ``reuse upgrade`` 预览与 ``--apply`` 选择性升级（只改选中 slot）；
- ``reuse variants|build|clone`` 变体有效范围、独立输出目录与展开副本可搬目录打开；
- v1/v2 无复用项目回归：旧命令行为不变。

夹具统一用 ``scripts.tests.core_fixtures``（仓库内 ``tmp/core-scratch/``，不用 tempfile），
CLI 一律用 ``subprocess`` 调用 ``doc_tool_cli.py``。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tests.core_fixtures import cleanup, scratch_dir, tiny_png, two_chapter_project  # noqa: E402

from doc_tool.application.content import module_refs as refs  # noqa: E402
from doc_tool.application.content import modules as modules  # noqa: E402
from doc_tool.application.content import reuse_commands as reuse  # noqa: E402
from doc_tool.application.content import variants as variants  # noqa: E402

DOCUMENT_TYPE = "general"
CHAPTER_ONE = "第1章 引言/1.1 目的.md"
CHAPTER_TWO = "第2章 设计/2.1 架构.md"

def _module_body(product: str = "示例产品") -> str:
    return (
        "# 通用术语\n\n"
        "本段说明 {0} 的通用约定，产品名：{{{{module.productName}}}}。\n\n"
        "<!-- DOC-ITEM: REQ-TERM-01 | 术语一致性 -->\n"
        "- 术语以本模块为准。\n"
    ).format(product)

def _iface_body() -> str:
    return (
        "# 接口约定\n\n"
        "![接口示意图](images/img_0001.png)\n\n"
        "统一前缀：{{module.productName}}，版本 {{{{module.apiVersion}}}}。\n\n"
        "<!-- DOC-ITEM: REQ-IFACE-01 | 接口前缀 -->\n"
        "- 接口前缀与产品名一致。\n"
    )

def run_cli(*args, cwd: Path = None):
    """以子进程调用真实 CLI，返回 (退出码, stdout, stderr)。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO_ROOT), env.get("PYTHONPATH", ""))))
    proc = subprocess.run(
        [sys.executable, "doc_tool_cli.py", *[str(item) for item in args]],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""

class ReuseFixture:
    """两章项目 + 三模块库 + 装配 + 两变体（与 30-B/C/E 服务测试同构）。"""

    def __init__(self, prefix: str) -> None:
        self.base = scratch_dir(prefix)
        self.root = two_chapter_project(
            self.base / "proj-{0}".format(prefix), document_type=DOCUMENT_TYPE
        )
        self.content_root = self.root / "content" / DOCUMENT_TYPE
        self.lib_root = self.base / "lib-{0}".format(prefix)
        images = self.root / "assets" / DOCUMENT_TYPE / "images"
        images.mkdir(parents=True, exist_ok=True)
        tiny_png(images / "img_0001.png")

        self.lib = modules.ModuleLibrary(self.lib_root)
        self.lib.publish(modules.Module(
            moduleId="term-standard",
            version="1.0.0",
            title="通用术语",
            body=_module_body(),
            tags=["通用", "术语"],
            description="公共术语与接口约定",
            parameters=[{"name": "productName", "default": "示例产品", "description": "产品名"}],
            source={"path": CHAPTER_ONE},
        ))
        extract = modules.extract_module(
            _iface_body(),
            module_id="iface-spec",
            version="1.0.0",
            tags=["接口"],
            parameters=[{"name": "productName", "default": "示例产品"},
                        {"name": "apiVersion", "default": "v1"}],
            resource_roots=[self.content_root, self.root / "assets" / DOCUMENT_TYPE],
            base_dir=self.root,
            source={"path": CHAPTER_ONE},
        )
        self.lib.publish(extract.module, resources=extract.sourcePaths)

        self.assembly = refs.Assembly(slots=[
            refs.AssemblySlot(slotId="slot-term", moduleId="term-standard", version="1.0.0",
                              chapter=CHAPTER_ONE, params={"productName": "甲型号"}),
            refs.AssemblySlot(slotId="slot-term-two", moduleId="term-standard", version="1.0.0",
                              chapter=CHAPTER_TWO),
            refs.AssemblySlot(slotId="slot-iface", moduleId="iface-spec", version="1.0.0",
                              chapter=CHAPTER_ONE),
        ])
        self.assembly.save(self.root)
        for slot in self.assembly.slots:
            modules.install_from_library(self.root, self.lib, slot.moduleId, slot.version)

        self.write_chapter(
            CHAPTER_ONE,
            "# 目的\n\n本章说明目的。\n\n"
            + refs.canonical_directive("term-standard", "1.0.0", "slot-term")
            + "\n"
            + refs.canonical_directive("iface-spec", "1.0.0", "slot-iface")
            + "\n本章结尾。\n",
        )
        self.write_chapter(
            CHAPTER_TWO,
            "# 架构\n\n"
            + refs.canonical_directive("term-standard", "1.0.0", "slot-term-two")
            + "\n架构正文。\n",
        )
        self.write_variants()

    def chapter(self, relative: str = CHAPTER_ONE) -> Path:
        return self.content_root / relative

    def write_chapter(self, relative: str, text: str) -> None:
        path = self.chapter(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read_chapter(self, relative: str = CHAPTER_ONE) -> str:
        return self.chapter(relative).read_text(encoding="utf-8")

    def write_variants(self) -> None:
        config = variants.VariantsConfig(variants=[
            variants.Variant(
                variantId="model-a",
                name="甲型号",
                include=["第1章 引言"],
                variables={"productName": "甲型号"},
            ),
            variants.Variant(
                variantId="model-b",
                name="乙型号",
                include=["第2章 设计"],
                variables={"productName": "乙型号"},
            ),
        ])
        store = variants.VariantsStore(self.root)
        store.config.variants = list(config.variants)
        store.save(self.root)

    def publish_new_version(self) -> str:
        """发布 term-standard 的 1.1.0（供升级用例）。"""
        self.lib.publish(modules.Module(
            moduleId="term-standard",
            version="1.1.0",
            title="通用术语（V1.1）",
            body=_module_body("示例产品二稿"),
            tags=["通用", "术语"],
            parameters=[{"name": "productName", "default": "示例产品"}],
        ))
        return "1.1.0"

class ProjectContextTests(unittest.TestCase):
    """1.3/1.4：入口上下文 + 旧项目兜底。"""

    def setUp(self) -> None:
        self.case = ReuseFixture("ctx")
        self.addCleanup(cleanup, self.case.base)

    def test_context_reads_assembly_variants_and_library(self):
        context = reuse.load_context(self.case.root)
        self.assertEqual(context.document_type, DOCUMENT_TYPE)
        self.assertEqual(context.content_root, self.case.content_root)
        self.assertEqual(
            sorted(slot.slotId for slot in context.assembly.slots),
            ["slot-iface", "slot-term", "slot-term-two"],
        )
        self.assertEqual(sorted(context.config.ids()), ["model-a", "model-b"])
        self.assertIsNotNone(context.library)
        self.assertEqual(
            sorted(context.discovered), sorted([CHAPTER_ONE, CHAPTER_TWO])
        )
        self.assertTrue(context.libraryRoot.endswith("reuse\\modules")
                        or context.libraryRoot.endswith("reuse/modules"))

    def test_legacy_project_without_sidecar_resolves_unchanged(self):
        base = scratch_dir("legacy")
        self.addCleanup(cleanup, base)
        root = two_chapter_project(base / "proj", document_type=DOCUMENT_TYPE)
        context = reuse.load_context(root)
        self.assertEqual(context.assembly.slots, [])
        self.assertEqual(context.config.variants, [])
        report = reuse.resolve_project(context)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["exitCode"], reuse.EXIT_OK)
        self.assertEqual(report["sources"], [])
        self.assertEqual(report["degradation"], [])
        detail = report["chaptersDetail"][0]
        self.assertFalse(detail["changed"])
        self.assertFalse(detail["degraded"])
        original = (context.content_root / CHAPTER_ONE).read_text(encoding="utf-8")
        resolved = reuse.resolve_chapter(context, CHAPTER_ONE)
        self.assertEqual(resolved.text, original)
        self.assertTrue(resolved.resolution.is_clean())

    def test_cli_and_service_entry_share_one_resolution(self):
        context = reuse.load_context(self.case.root)
        service_report = reuse.resolve_project(context, withText=True)
        code, out, _err = run_cli(
            "reuse", "resolve", "--project", self.case.root, "--with-text", "--output", "json"
        )
        self.assertEqual(code, 0)
        cli_report = json.loads(out)
        self.assertEqual(cli_report["chapters"], service_report["chapters"])
        normalise = lambda rows: sorted(
            (row["slotId"], row["identity"], row["hostPath"], row["hostLine"],
             tuple(sorted(row["paramsFromDeclared"])), tuple(sorted(row["dependencyHashes"].items())))
            for row in rows
        )
        self.assertEqual(normalise(cli_report["sources"]), normalise(service_report["sources"]))
        self.assertEqual(
            [item["text"] for item in cli_report["chaptersDetail"]],
            [item["text"] for item in service_report["chaptersDetail"]],
        )

    def test_prepared_source_adapter_uses_same_resolution_path(self):
        """2.1/2.4：prepared_source 的解析适配点接到同一 resolver（monkeypatch 接入）。"""
        from doc_tool.application import prepared_source

        context = reuse.load_context(self.case.root)
        calls = []

        def fake_prepare(path, **kwargs):
            text = kwargs.get("text")
            if text is None:
                text = Path(path).read_text(encoding="utf-8")
            resolved = reuse.resolve_text(text, context, host_path=str(path))
            prepared = prepared_source.PreparedSource(source_path=str(path))
            prepared.prepared_text = resolved.text
            prepared.prepared_path = str(path)
            calls.append(resolved)
            return prepared

        original = prepared_source.prepare_markdown
        prepared_source.prepare_markdown = fake_prepare
        try:
            prepared = prepared_source.prepare_markdown(
                str(self.case.chapter(CHAPTER_ONE)),
                text=self.case.read_chapter(CHAPTER_ONE),
            )
        finally:
            prepared_source.prepare_markdown = original

        self.assertEqual(len(calls), 1)
        self.assertIn("通用术语", prepared.prepared_text)
        self.assertNotIn("```doc-module", prepared.prepared_text)
        # 与 CLI/服务入口拿到同一份文本（同一 plan → 同一变量/覆盖）
        service = reuse.resolve_chapter(context, CHAPTER_ONE, plan=reuse.plan_project(context))
        self.assertEqual(prepared.prepared_text, service.text)

class ResolveReportTests(unittest.TestCase):
    """2.5/3.4：解析报告（来源、定位、兜底）与退出码。"""

    def setUp(self) -> None:
        self.case = ReuseFixture("res")
        self.addCleanup(cleanup, self.case.base)

    def test_report_locates_module_version_hash_and_line(self):
        context = reuse.load_context(self.case.root)
        plan = reuse.plan_project(context)
        report = reuse.resolve_project(context)
        self.assertEqual(
            plan.slot_overrides["slot-term"],
            {"version": "1.0.0", "params": {"productName": "甲型号"}},
        )
        self.assertEqual(
            reuse.resolve_text("# x", context).text,
            "# x",
            "无引用的正文不因覆盖配置被改写",
        )
        self.assertEqual(report["exitCode"], 0)
        self.assertEqual(report["status"], "ok")
        rows = {row["slotId"]: row for row in report["sources"]}
        self.assertEqual(sorted(rows), ["slot-iface", "slot-term", "slot-term-two"])
        term = rows["slot-term"]
        self.assertEqual(term["identity"], "term-standard@1.0.0")
        self.assertEqual(term["hostPath"], CHAPTER_ONE)
        self.assertEqual(term["hostLine"], 5)
        self.assertTrue(term["moduleDir"].endswith("1.0.0"))
        self.assertTrue(term["dependencyHashes"]["term-standard@1.0.0"])
        # 参数生效：装配固定参数覆盖模块默认值
        self.assertEqual(term["params"].get("productName"), "甲型号")
        iface = rows["slot-iface"]
        self.assertEqual(sorted(iface["resources"]), ["resources/img_0001.png"])
        self.assertTrue(iface["resources"]["resources/img_0001.png"].endswith("img_0001.png"))

    def test_human_report_lists_sources_and_degradation(self):
        code, out, _err = run_cli("reuse", "resolve", "--project", self.case.root)
        self.assertEqual(code, 0)
        self.assertIn("引用来源（3）", out)
        self.assertIn("term-standard@1.0.0", out)
        self.assertIn("{0}:5".format(CHAPTER_ONE), out)
        self.assertIn("结果：有可用正文", out)
        self.assertNotIn("```doc-module", out)

    def test_missing_slot_module_falls_back_to_readable_placeholder(self):
        self.case.write_chapter(
            CHAPTER_ONE,
            "# 目的\n\n"
            + refs.canonical_directive("not-in-project", "9.9.9", "slot-gone")
            + "\n本章结尾。\n",
        )
        context = reuse.load_context(self.case.root)
        report = reuse.resolve_project(context, withText=True)
        self.assertEqual(report["exitCode"], 0)
        self.assertEqual(report["status"], "ok")
        self.assertIn("本章结尾。", report["chaptersDetail"][0]["text"])
        self.assertIn(
            modules.MODULE_MISSING_TEMPLATE.split("{")[0],
            report["chaptersDetail"][0]["text"],
        )
        self.assertTrue(any("未找到固定副本" in item for item in report["degradation"]))

    def test_missing_module_but_library_cache_used(self):
        target = modules.project_module_dir(self.case.root, "iface-spec", "1.0.0")
        import shutil

        shutil.rmtree(str(target))
        context = reuse.load_context(self.case.root, library_root=self.case.lib_root)
        report = reuse.resolve_project(context, withText=True)
        self.assertEqual(report["exitCode"], 0)
        self.assertIn("接口约定", report["chaptersDetail"][0]["text"])
        self.assertTrue(any("库中同版本缓存" in item for item in report["degradation"]))

    def test_cycle_stops_only_that_reference(self):
        # 循环组：loop-a（2.0.0）正文固定引用 loop-b（2.0.0），loop-b 又引用 loop-a。
        self.case.lib.publish(modules.Module(
            moduleId="loop-a", version="2.0.0", title="循环甲",
            body="# 循环甲\n\n" + refs.canonical_directive("loop-b", "2.0.0", "slot-b")
                 + "\n甲正文。\n",
        ))
        self.case.lib.publish(modules.Module(
            moduleId="loop-b", version="2.0.0", title="循环乙",
            body="# 循环乙\n\n" + refs.canonical_directive("loop-a", "2.0.0", "slot-a")
                 + "\n乙正文。\n",
        ))
        for module_id in ("loop-a", "loop-b"):
            modules.install_from_library(self.case.root, self.case.lib, module_id, "2.0.0")
        context = reuse.load_context(self.case.root)
        text = (
            "# 循环\n\n"
            + refs.canonical_directive("loop-a", "2.0.0", "slot-top")
            + "\n收尾正文。\n"
        )
        resolution = reuse.resolve_text(text, context, host_path=CHAPTER_ONE)
        self.assertIn(refs.CYCLE_STOP_TEMPLATE.split("{")[0], resolution.text)
        self.assertTrue(any("循环引用" in item for item in resolution.warnings))
        self.assertIn("收尾正文。", resolution.text)

    def test_undeclared_parameter_keeps_literal(self):
        """未声明键保留字面值；声明键可用，装配固定值优先。"""
        context = reuse.load_context(self.case.root)
        injected = modules.Module(
            moduleId="param-module",
            version="1.0.0",
            title="参数模块",
            body=(
                "# 参数模块\n\n"
                "声明键：{{module.productName}}；未声明键：{{module.notDeclared}}。\n"
            ),
            parameters=[{"name": "productName", "default": "默认产品"}],
        )
        modules.install_module(self.case.root, injected)
        directive = refs.canonical_directive("param-module", "1.0.0", "slot-param")

        # (a) 只给声明键值时：声明键替换，未声明键保留字面值
        loose = reuse.resolve_text(directive, context, host_path=CHAPTER_ONE)
        self.assertIn("默认产品", loose.text)
        self.assertIn("{{module.notDeclared}}", loose.text)

        # (b) 装配里的固定参数生效（同一解析入口）
        assembly = refs.Assembly.load(self.case.root)
        assembly.upsert(refs.AssemblySlot(
            slotId="slot-param", moduleId="param-module", version="1.0.0",
            chapter=CHAPTER_ONE, params={"productName": "固定产品"},
        ))
        assembly.save(self.case.root)
        bound = reuse.resolve_text(
            directive, reuse.load_context(self.case.root), host_path=CHAPTER_ONE
        )
        self.assertIn("固定产品", bound.text)
        self.assertIn("{{module.notDeclared}}", bound.text)
        self.assertNotIn("默认产品", bound.text)

    def test_empty_effective_scope_exits_one(self):
        base = scratch_dir("empty")
        self.addCleanup(cleanup, base)
        root = two_chapter_project(base / "proj", document_type=DOCUMENT_TYPE)
        content = root / "content" / DOCUMENT_TYPE
        for path in sorted(content.rglob("*.md")):
            path.unlink()
        code, out, _err = run_cli("reuse", "resolve", "--project", root, "--output", "json")
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["status"], "empty")
        self.assertEqual(report["usableChapters"], 0)

    def test_unknown_variant_exits_two_without_building_other_model(self):
        code, out, err = run_cli(
            "reuse", "resolve", "--project", self.case.root, "--variant", "nope", "--output", "json"
        )
        self.assertEqual(code, 2)
        report = json.loads(out)
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["error"], "unknown-variant")
        self.assertEqual(report["options"], ["model-a", "model-b"])

    def test_strict_mode_turns_missing_module_into_exit_two(self):
        self.case.write_chapter(
            CHAPTER_ONE,
            "# 目的\n\n"
            + refs.canonical_directive("not-in-project", "9.9.9", "slot-gone")
            + "\n本章结尾。\n",
        )
        loose, _out, _err = run_cli("reuse", "resolve", "--project", self.case.root)
        self.assertEqual(loose, 0)
        strict, out, _err = run_cli(
            "reuse", "resolve", "--project", self.case.root, "--strict", "--output", "json"
        )
        self.assertEqual(strict, 2)
        self.assertEqual(json.loads(out)["status"], "invalid")

    def test_chapter_mode_and_variant_mode_are_exclusive(self):
        code, _out, err = run_cli(
            "reuse", "resolve", "--project", self.case.root,
            "--chapter", CHAPTER_ONE, "--variant", "model-a",
        )
        self.assertEqual(code, 2)
        self.assertIn("不可同时使用", err)

    def test_check_command_reports_warnings_without_writing(self):
        before = self.case.read_chapter(CHAPTER_ONE)
        code, out, _err = run_cli(
            "reuse", "check", "--project", self.case.root, "--output", "json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checkedWarnings"], len(payload["degradation"]))
        self.assertEqual(self.case.read_chapter(CHAPTER_ONE), before)

class LibraryCliTests(unittest.TestCase):
    """5.2/6.4：reuse list|show|extract|import|export|install 与离线包。"""

    def setUp(self) -> None:
        self.case = ReuseFixture("lib")
        self.addCleanup(cleanup, self.case.base)

    def test_list_and_query_show_library_entries(self):
        code, out, _err = run_cli(
            "reuse", "list", "--project", self.case.root, "--library", self.case.lib_root
        )
        self.assertEqual(code, 0)
        self.assertIn("term-standard@1.0.0", out)
        self.assertIn("iface-spec@1.0.0", out)
        code, out, _err = run_cli(
            "reuse", "list", "--project", self.case.root, "--library", self.case.lib_root,
            "--query", "接口约定", "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(
            [row["moduleId"] for row in payload["modules"]], ["iface-spec", "term-standard"]
        )
        iface = next(row for row in payload["modules"] if row["moduleId"] == "iface-spec")
        self.assertEqual(iface["resources"], ["resources/img_0001.png"])
        # 标签检索只命中带该标签的模块
        code, out, _err = run_cli(
            "reuse", "list", "--project", self.case.root, "--library", self.case.lib_root,
            "--tag", "术语", "--output", "json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            [row["moduleId"] for row in json.loads(out)["modules"]], ["term-standard"]
        )

    def test_show_previews_with_parameter_override(self):
        code, out, _err = run_cli(
            "reuse", "show", "--project", self.case.root, "--library", self.case.lib_root,
            "--module", "term-standard@1.0.0", "--param", "productName=乙型号", "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("乙型号", payload["preview"])
        self.assertEqual(payload["parameters"][0]["name"], "productName")
        code, out, _err = run_cli(
            "reuse", "show", "--project", self.case.root, "--library", self.case.lib_root,
            "--module", "no-such-module",
        )
        self.assertEqual(code, 2)
        self.assertIn("模块不存在", out)

    def test_extract_from_saved_chapter_records_source_and_resources(self):
        code, out, _err = run_cli(
            "reuse", "extract", "--project", self.case.root, "--chapter", CHAPTER_ONE,
            "--module-id", "chapter-one", "--module-version", "0.9.0",
            "--parameter", "productName=示例产品:产品名", "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["sourceMode"], "saved")
        self.assertEqual(payload["moduleId"], "chapter-one")
        self.assertEqual(payload["version"], "0.9.0")
        self.assertIn("chapter-one", payload["directory"])
        module = modules.ModuleLibrary(self.case.root / "reuse" / "library").get(
            "chapter-one", "0.9.0"
        )
        self.assertIsNotNone(module)
        self.assertEqual([item.name for item in module.parameters], ["productName"])
        # 提取不写回源章节
        self.assertIn("```doc-module", self.case.read_chapter(CHAPTER_ONE))

    def test_extract_from_explicit_buffer_snapshot_does_not_read_disk(self):
        buffer_file = self.case.base / "buffer.md"
        buffer_file.write_text(
            "# 缓冲正文\n\n<!-- DOC-ITEM: REQ-BUF-01 | 缓冲条目 -->\n- 来自未保存缓冲。\n",
            encoding="utf-8",
        )
        saved_before = self.case.read_chapter(CHAPTER_ONE)
        code, out, _err = run_cli(
            "reuse", "extract", "--project", self.case.root, "--chapter", CHAPTER_ONE,
            "--module-id", "buffer-module", "--current-buffer", buffer_file, "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["sourceMode"], "current-buffer")
        module = modules.ModuleLibrary(self.case.root / "reuse" / "library").get(
            "buffer-module", "1.0.0"
        )
        self.assertIsNotNone(module)
        self.assertIn("来自未保存缓冲", module.body)
        self.assertNotIn("本章说明目的", module.body)
        self.assertEqual(self.case.read_chapter(CHAPTER_ONE), saved_before)

    def test_export_and_import_round_trip_keeps_library_and_skips_missing(self):
        target = self.case.base / "package"
        code, out, _err = run_cli(
            "reuse", "export", "--project", self.case.root, "--library", self.case.lib_root,
            "--target", target, "--module", "iface-spec@1.0.0", "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["exported"][0]["missingResources"], [])
        exported_dir = Path(payload["exported"][0]["directory"])
        self.assertTrue((exported_dir / modules.MANIFEST_FILE_NAME).is_file())
        self.assertTrue((exported_dir / "resources" / "img_0001.png").is_file())

        # 缺资源：删掉包内图片后导入仍成功，缺项进报告，原库保留
        (exported_dir / "resources" / "img_0001.png").unlink()
        other_root = self.case.base / "lib-other"
        code, out, _err = run_cli(
            "reuse", "import", str(exported_dir), "--library", other_root, "--output", "json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["imported"][0]["warnings"])
        self.assertTrue(any("附件缺失" in item for item in payload["imported"][0]["warnings"]))
        self.assertIsNotNone(modules.ModuleLibrary(other_root).get("iface-spec", "1.0.0"))
        self.assertIsNotNone(self.case.lib.get("term-standard", "1.0.0"))

    def test_import_reports_illegal_attachment_without_reading_it(self):
        source = self.case.base / "bad-package"
        module_dir = source / "evil"
        module_dir.mkdir(parents=True)
        (module_dir / modules.BODY_FILE_NAME).write_text("# 坏包\n", encoding="utf-8")
        (module_dir / modules.MANIFEST_FILE_NAME).write_text(
            "schemaVersion: 1\n"
            "moduleId: evil\nversion: 1.0.0\ntitle: 坏包\n"
            "bodyFile: {0}\n"
            "resources:\n- path: ../../outside.txt\n  sha256: ''\n".format(modules.BODY_FILE_NAME),
            encoding="utf-8",
        )
        library_root = self.case.base / "lib-bad"
        library_root.mkdir(parents=True, exist_ok=True)
        code, out, _err = run_cli(
            "reuse", "import", str(module_dir), "--library", library_root, "--output", "json"
        )
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        warnings = payload["imported"][0]["warnings"]
        self.assertTrue(any("非法附件路径已跳过" in item for item in warnings))
        self.assertIsNotNone(modules.ModuleLibrary(library_root).get("evil", "1.0.0"))

    def test_install_copies_module_into_project_offline(self):
        fresh = self.case.base / "proj-fresh"
        fresh.mkdir(parents=True, exist_ok=True)
        target_project = two_chapter_project(fresh / "p2", document_type=DOCUMENT_TYPE)
        code, out, _err = run_cli(
            "reuse", "install", "--project", target_project, "--library", self.case.lib_root,
            "--module", "iface-spec@1.0.0", "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["installed"][0]["moduleId"], "iface-spec")
        installed = modules.project_module_dir(target_project, "iface-spec", "1.0.0")
        self.assertTrue((installed / "resources" / "img_0001.png").is_file())
        # 原库搬走后项目固定副本仍可用
        moved = self.case.lib_root.with_name(self.case.lib_root.name + "-moved")
        self.case.lib_root.rename(moved)
        try:
            context = reuse.load_context(target_project)
            resolution = reuse.resolve_text(
                refs.canonical_directive("iface-spec", "1.0.0", "slot-x"),
                context,
                host_path=CHAPTER_ONE,
            )
            self.assertIn("接口约定", resolution.text)
        finally:
            moved.rename(self.case.lib_root)

class UpgradeCliTests(unittest.TestCase):
    """4.4：升级差异预览与选择性升级（默认只预览）。"""

    def setUp(self) -> None:
        self.case = ReuseFixture("upg")
        self.addCleanup(cleanup, self.case.base)
        self.new_version = self.case.publish_new_version()

    def _assembly_versions(self) -> dict:
        assembly = refs.Assembly.load(self.case.root)
        return {slot.slotId: slot.version for slot in assembly.slots}

    def test_preview_lists_difference_and_affected_slots_without_writing(self):
        before = self._assembly_versions()
        code, out, _err = run_cli(
            "reuse", "upgrade", "--project", self.case.root, "--library", self.case.lib_root,
            "--module", "term-standard", "--to", self.new_version, "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["dryRun"])
        self.assertEqual(payload["currentVersion"], "1.0.0")
        self.assertEqual(payload["targetVersion"], self.new_version)
        self.assertEqual(sorted(payload["slots"]), ["slot-term", "slot-term-two"])
        self.assertTrue(payload["difference"]["bodyChanged"])
        self.assertEqual(payload["assemblyPath"], "")
        self.assertEqual(self._assembly_versions(), before)
        self.assertIn("正文有改动", payload["difference"]["summary"])

    def test_apply_updates_only_selected_slot(self):
        code, out, _err = run_cli(
            "reuse", "upgrade", "--project", self.case.root, "--library", self.case.lib_root,
            "--module", "term-standard", "--to", self.new_version, "--slot", "slot-term",
            "--apply", "--output", "json",
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["updated"], ["slot-term"])
        versions = self._assembly_versions()
        self.assertEqual(versions["slot-term"], self.new_version)
        self.assertEqual(versions["slot-term-two"], "1.0.0")
        self.assertTrue(Path(payload["assemblyPath"]).is_file())

        # 升级后正文按新固定版本展开，未选中的仍是旧版本
        from doc_tool.application.content import modules as module_lib

        module_lib.install_from_library(
            self.case.root, self.case.lib, "term-standard", self.new_version
        )
        self.assertTrue(
            module_lib.project_module_dir(
                self.case.root, "term-standard", self.new_version
            ).is_dir()
        )
        context = reuse.load_context(self.case.root, library_root=self.case.lib_root)
        report = reuse.resolve_project(context)
        rows = {row["slotId"]: row for row in report["sources"]}
        self.assertEqual(rows["slot-term"]["identity"], "term-standard@{0}".format(self.new_version))
        self.assertEqual(rows["slot-term-two"]["identity"], "term-standard@1.0.0")
        # 只改配置，不改正文
        self.assertNotIn("示例产品二稿", self.case.read_chapter(CHAPTER_ONE))

    def test_unknown_target_version_exits_two(self):
        code, out, _err = run_cli(
            "reuse", "upgrade", "--project", self.case.root, "--library", self.case.lib_root,
            "--module", "term-standard", "--to", "9.9.9", "--output", "json",
        )
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"], "unknown-target")
        self.assertIn("1.1.0", payload["versions"])

    def test_module_without_reference_reports_clear_reason(self):
        self.case.lib.publish(modules.Module(
            moduleId="unused-module", version="1.0.0", title="未引用", body="# 未引用\n",
        ))
        code, out, _err = run_cli(
            "reuse", "upgrade", "--project", self.case.root, "--library", self.case.lib_root,
            "--module", "unused-module", "--output", "json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"], "not-referenced")

class VariantCliTests(unittest.TestCase):
    """5.2/5.3：变体可选范围、独立输出目录与范围证据。"""

    def setUp(self) -> None:
        self.case = ReuseFixture("var")
        self.addCleanup(cleanup, self.case.base)

    def test_variants_command_lists_available_and_scope(self):
        code, out, _err = run_cli(
            "reuse", "variants", "--project", self.case.root, "--variant", "model-a",
            "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual([item["variantId"] for item in payload["available"]], ["model-a", "model-b"])
        self.assertIn(CHAPTER_ONE, payload["scope"]["chapters"])
        self.assertEqual(payload["scope"]["excluded"], [CHAPTER_TWO])
        self.assertEqual(payload["scope"]["variables"]["productName"], "甲型号")

    def test_unknown_variant_exits_two_and_lists_options(self):
        code, out, _err = run_cli(
            "reuse", "variants", "--project", self.case.root, "--variant", "no-such",
            "--output", "json",
        )
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["options"], ["model-a", "model-b"])

    def test_build_two_variants_into_separate_directories(self):
        destination = self.case.base / "out"
        code, out, _err = run_cli(
            "reuse", "build", "--project", self.case.root, "--library", self.case.lib_root,
            "--variant", "model-a", "--variant", "model-b",
            "--destination", destination, "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual([run["variantId"] for run in payload["runs"]], ["model-a", "model-b"])
        first, second = payload["runs"]
        self.assertNotEqual(first["outputDir"], second["outputDir"])
        self.assertIn(CHAPTER_ONE, first["scope"]["chapters"])
        self.assertTrue(all(item.startswith("第1章 引言/") for item in first["scope"]["chapters"]))
        self.assertIn(CHAPTER_TWO, second["scope"]["chapters"])
        self.assertTrue(all(item.startswith("第2章 设计/") for item in second["scope"]["chapters"]))
        self.assertIn(CHAPTER_ONE, second["scope"]["excluded"])
        self.assertEqual(
            first["scope"]["moduleVersions"]["slot-term"], "term-standard@1.0.0"
        )
        for run in payload["runs"]:
            body = list((Path(run["outputDir"]) / "content" / DOCUMENT_TYPE).rglob("*.md"))
            self.assertTrue(body)
            text = "\n".join(path.read_text(encoding="utf-8") for path in body)
            self.assertNotIn("```doc-module", text)
        first_text = (
            Path(first["outputDir"]) / "content" / DOCUMENT_TYPE / CHAPTER_ONE
        ).read_text(encoding="utf-8")
        second_text = (
            Path(second["outputDir"]) / "content" / DOCUMENT_TYPE / CHAPTER_TWO
        ).read_text(encoding="utf-8")
        self.assertIn("甲型号", first_text)
        self.assertIn("乙型号", second_text)
        # 源项目与公共模块未被改写
        self.assertIn("```doc-module", self.case.read_chapter(CHAPTER_ONE))

    def test_build_unknown_variant_exits_two(self):
        code, out, _err = run_cli(
            "reuse", "build", "--project", self.case.root, "--library", self.case.lib_root,
            "--variant", "ghost", "--output", "json",
        )
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["error"], "unknown-variant")

    def test_build_reports_unknown_variant_even_without_config(self):
        base = scratch_dir("novar")
        self.addCleanup(cleanup, base)
        root = two_chapter_project(base / "proj", document_type=DOCUMENT_TYPE)
        code, out, _err = run_cli(
            "reuse", "build", "--project", root, "--variant", "ghost", "--output", "json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"], "unknown-variant")

class ExpandedCopyCliTests(unittest.TestCase):
    """6.3/6.5：展开副本 CLI 入口与可搬目录自检。"""

    def setUp(self) -> None:
        self.case = ReuseFixture("cpy")
        self.addCleanup(cleanup, self.case.base)

    def test_clone_writes_plain_markdown_and_verifies_portable(self):
        target = self.case.base / "copy-model-a"
        code, out, _err = run_cli(
            "reuse", "clone", "--project", self.case.root, "--library", self.case.lib_root,
            "--variant", "model-a", "--target", target, "--output", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["portableIssues"], [])
        body_path = target / "content" / DOCUMENT_TYPE / CHAPTER_ONE
        text = body_path.read_text(encoding="utf-8")
        self.assertNotIn("```doc-module", text)
        self.assertIn("通用术语", text)
        self.assertTrue((target / variants_lib_index_name()).is_file())
        self.assertTrue((target / "README-展开副本.md").is_file())

    def test_clone_refuses_non_empty_target(self):
        target = self.case.base / "occupied"
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("不要覆盖", encoding="utf-8")
        code, _out, err = run_cli(
            "reuse", "clone", "--project", self.case.root, "--target", target
        )
        self.assertEqual(code, 2)
        self.assertIn("未覆盖", err)
        self.assertTrue((target / "keep.txt").is_file())

    def test_clone_plain_project_moves_and_reopens(self):
        """6.5：副本可搬目录打开——搬到另一路径后仍能逐条打开引用。"""
        target = self.case.base / "copy-move"
        code, _out, _err = run_cli(
            "reuse", "clone", "--project", self.case.root, "--library", self.case.lib_root,
            "--target", target,
        )
        self.assertEqual(code, 0)
        moved = self.case.base / "another-place" / "copy-moved"
        moved.parent.mkdir(parents=True, exist_ok=True)
        target.rename(moved)
        issues = variants.verify_portable_copy(moved)
        self.assertEqual([(item.file, item.target) for item in issues], [])
        text = (moved / "content" / DOCUMENT_TYPE / CHAPTER_ONE).read_text(encoding="utf-8")
        self.assertIn("本章结尾。", text)

    def test_clone_creates_copy_without_new_markers(self):
        """1.4：旧应用读取展开副本时不需识别新标记。"""
        target = self.case.base / "copy-second"
        code, _out, _err = run_cli(
            "reuse", "clone", "--project", self.case.root, "--library", self.case.lib_root,
            "--variant", "model-b", "--target", target,
        )
        self.assertEqual(code, 0)
        content = target / "content" / DOCUMENT_TYPE
        checked = 0
        for path in sorted(content.rglob("*.md")):
            checked += 1
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("```doc-module", text)
            self.assertNotIn("doc-module-copy", text)
        self.assertTrue(checked)

def variants_lib_index_name() -> str:
    return variants.COPY_INDEX_NAME

class LegacyCliRegressionTests(unittest.TestCase):
    """1.4/6.5：旧命令与无复用项目行为不变。"""

    def setUp(self) -> None:
        base = scratch_dir("ovl")
        self.addCleanup(cleanup, base)
        self.root = two_chapter_project(base / "proj", document_type=DOCUMENT_TYPE)

    def test_project_export_keeps_current_buffer_refusal(self):
        code, _out, err = run_cli(
            "project-export", "--project", self.root, "--source-mode", "current-buffer"
        )
        self.assertEqual(code, 2)
        self.assertIn("current-buffer", err)

    def test_top_level_help_still_lists_existing_commands(self):
        code, out, _err = run_cli("--help")
        self.assertEqual(code, 0)
        for name in ("project-export", "assist-search", "assist-provider", "reuse", "check"):
            self.assertIn(name, out)

    def test_reuse_subcommand_help_is_available(self):
        code, out, _err = run_cli("reuse", "--help")
        self.assertEqual(code, 0)
        for name in ("list", "show", "extract", "import", "export", "install",
                     "resolve", "upgrade", "variants", "build", "check", "clone"):
            self.assertIn(name, out)

    def test_reuse_without_subcommand_exits_two(self):
        code, _out, err = run_cli("reuse")
        self.assertEqual(code, 2)
        self.assertIn("请指定 reuse 子命令", err)

    def test_missing_project_yml_exits_two(self):
        code, _out, err = run_cli("reuse", "resolve", "--project", self.root / "not-there")
        self.assertEqual(code, 2)
        self.assertIn("project.yml", err)

if __name__ == "__main__":
    unittest.main(verbosity=2)
