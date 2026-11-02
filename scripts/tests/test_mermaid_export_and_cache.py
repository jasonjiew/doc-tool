# -*- coding: utf-8 -*-
"""验证 Mermaid 图形导出、CLI 后端与缓存兼容（Group 6：REQ-MM-04、REQ-MM-05、REQ-MM-06、REQ-MD-04、REQ-MD-07、REQ-MD-08）。"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from doc_tool.application.content.mermaid import (
    BatchConversionResult,
    MermaidBlock,
    RenderResult,
    batch_convert,
    export_png,
    export_svg,
    get_cli_status,
    image_reference,
    next_mermaid_name,
    render,
)
from doc_tool.application.prepared_source import (
    CACHE_FORMAT_VERSION,
    compute_cache_key,
    read_cache,
    write_cache,
)
from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer


class MermaidExportAndCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="doc-tool-export-test-")
        self.assets_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # --- 6.1: 官方 SVG 导出与主题身份保留 ---
    def test_6_1_export_svg_and_theme_identity(self):
        """6.1: SVG 导出保留内容，主题切换产生不同身份，失败不写无效引用。"""
        renderer = get_official_mermaid_renderer()
        source = "flowchart TD\n  Start[开始流程] --> End[结束流程]"

        # 默认主题渲染
        res_default = renderer.render(source, want_png=False, theme="default")
        self.assertTrue(res_default.ok, res_default.error)
        self.assertIsNotNone(res_default.svg)

        # 导出 SVG
        rel_path = export_svg(res_default, self.assets_root, "architecture")
        self.assertTrue(rel_path.startswith("images/mermaid_"))
        self.assertTrue(rel_path.endswith(".svg"))

        disk_file = self.assets_root / "architecture" / rel_path
        self.assertTrue(disk_file.exists())
        self.assertEqual(disk_file.read_bytes(), res_default.svg)

        # 深色主题渲染产生不同 SVG 内容
        res_dark = renderer.render(source, want_png=False, theme="dark")
        self.assertTrue(res_dark.ok)
        self.assertNotEqual(res_default.svg, res_dark.svg)

        # 失败不写图片
        res_fail = RenderResult(ok=False, error="Syntax error")
        with self.assertRaises(ValueError):
            export_svg(res_fail, self.assets_root, "architecture")

    # --- 6.2: 桌面高保真 PNG 导出（无 Node/npm） ---
    def test_6_2_desktop_png_export_without_node(self):
        """6.2: 无 Node/npm 时官方引擎可导出 PNG，支持中文/多行/HTML 标签，尺寸与 DPI 准确。"""
        renderer = get_official_mermaid_renderer()
        source = """flowchart TD
            subgraph 业务子域 [电商交易中心]
                A["用户下单<br/>(含折扣抵扣)"] --> B{"库存校验<br/><b>实时风控</b>"}
                B -- 充足 --> C[扣减库存并生成订单]
                B -- 不足 --> D[提示库存告急]
            end
        """
        result = renderer.render(source, want_png=True, theme="default")
        self.assertTrue(result.ok, result.error)
        self.assertIsNotNone(result.png)
        self.assertTrue(result.png.startswith(b"\x89PNG"))
        self.assertGreater(len(result.png), 300)

        # 逻辑宽高遵循边界
        self.assertGreater(result.width, 100)
        self.assertGreater(result.height, 100)

        # 导出并生成尺寸引用
        rel_png = export_png(result, self.assets_root, "requirements")
        ref = image_reference(rel_png, result)
        self.assertIn(f" ={result.width}x{result.height}", ref)
        self.assertIn("images/mermaid_", ref)

    # --- 6.3: CLI 环境检测与后端报告 ---
    def test_6_3_cli_environment_detection_and_parity(self):
        """6.3: 正确区分 PATH 覆盖、本地 tools、无 CLI 三种环境，内置近似图不宣称高保真一致。"""
        # 1. 模拟 PATH 覆盖环境
        with patch("shutil.which", return_value="C:\\tools\\mmdc.cmd"):
            status_path = get_cli_status()
            self.assertTrue(status_path["available"])
            self.assertEqual(status_path["type"], "path")
            self.assertEqual(status_path["backend_name"], "mermaid-cli")
            self.assertTrue(status_path["claims_desktop_parity"])

        # 2. 模拟无 CLI 环境
        with patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False):
            status_none = get_cli_status()
            self.assertFalse(status_none["available"])
            self.assertEqual(status_none["type"], "none")
            self.assertEqual(status_none["backend_name"], "builtin-approximate")
            self.assertFalse(status_none["claims_desktop_parity"])

        # 3. 验证内置近似渲染结果不声称高保真一致 (claims_fidelity is False)
        builtin_res = render("flowchart TD\n  A --> B", use_cli=False, want_png=False)
        self.assertTrue(builtin_res.ok)
        self.assertFalse(builtin_res.claims_fidelity)
        self.assertEqual(builtin_res.backend, "builtin")

    # --- 6.4: 缓存身份扩展与兼容旧版本缓存 ---
    def test_6_4_cache_identity_and_version_compatibility(self):
        """6.4: 同源码不同主题/字体/布局不误命中，旧版 v1 缓存仍可读取且不被删除。"""
        source = "flowchart TD\n  Node1 --> Node2"

        # 1. 不同主题缓存键不同
        key_default = compute_cache_key(source, "flowchart", theme="default")
        key_dark = compute_cache_key(source, "flowchart", theme="dark")
        self.assertNotEqual(key_default, key_dark)

        # 2. 不同字体/布局缓存键不同
        key_font = compute_cache_key(source, "flowchart", theme="default", font_family="SimSun")
        self.assertNotEqual(key_default, key_font)

        # 3. 写入 v2 缓存
        cache_dir = self.assets_root / "cache"
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest"
        write_cache(
            cache_dir,
            key_default,
            png=dummy_png,
            width=300,
            height=200,
            backend="official-webengine",
            kind="flowchart",
            source=source,
        )
        hit_v2 = read_cache(cache_dir, key_default)
        self.assertIsNotNone(hit_v2)
        self.assertEqual(hit_v2.width, 300)
        self.assertEqual(hit_v2.meta.get("format"), "v2")

        # 4. 模拟已存在的 v1 旧格式缓存
        key_v1 = "legacy_test_key_v1_0001"
        (cache_dir / f"{key_v1}.png").write_bytes(dummy_png)
        import hashlib, json
        meta_v1 = {
            "format": "v1",
            "key": key_v1,
            "kind": "flowchart",
            "backend": "builtin",
            "width": 150,
            "height": 100,
            "sha256": hashlib.sha256(dummy_png).hexdigest(),
        }
        (cache_dir / f"{key_v1}.json").write_text(json.dumps(meta_v1), encoding="utf-8")

        # 验证读取旧版 v1 成功且文件依然完整保留（不被删除）
        hit_v1 = read_cache(cache_dir, key_v1)
        self.assertIsNotNone(hit_v1)
        self.assertEqual(hit_v1.width, 150)
        self.assertEqual(hit_v1.backend, "builtin")
        self.assertTrue((cache_dir / f"{key_v1}.json").exists())

    # --- 6.5: 批量转换、资源命名与部分失败行为 ---
    def test_6_5_batch_convert_naming_and_partial_failure(self):
        """6.5: 命名递增、带尺寸引用、部分失败时保留原源码。"""
        md_text = (
            "# 文档章节\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  OK1[成功节点1] --> OK2[成功节点2]\n"
            "```\n\n"
            "中间段落说明。\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  Broken syntax error {{[\n"
            "```\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "  Second1 --> Second2\n"
            "```\n"
        )

        def exporter(_block, res):
            target = export_png(res, self.assets_root, "architecture")
            return image_reference(target, res)

        res = batch_convert(md_text, exporter, include_fenced=True, use_cli=False)
        self.assertEqual(res.success_count, 2)
        self.assertEqual(len(res.failures), 1)

        # 失败块源码保持不变
        self.assertIn("Broken syntax error {{[", res.text)
        # 成功块被替换为带尺寸引用
        self.assertIn("![图](images/mermaid_0001.png", res.text)
        self.assertIn("![图](images/mermaid_0002.png", res.text)


if __name__ == "__main__":
    unittest.main()
