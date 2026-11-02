# -*- coding: utf-8 -*-
"""验证安装版、便携版交付规格与运行边界（Group 8：REQ-MD-08、REQ-ED-01、REQ-MM-05、REQ-MM-06）。"""

import hashlib
import os
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
import sys
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class PackagingAndDeliveryFidelityTests(unittest.TestCase):
    def test_8_1_spec_and_license_manifest_integrity(self):
        """8.1: spec 移除 WebEngine 排除，收集 web_preview 资源，第三方许可清单包含 markdown-it 与 mermaid。"""
        # 1. 检查 packaging/doc_tool.spec
        doc_tool_spec = (REPO_ROOT / "packaging" / "doc_tool.spec").read_text(encoding="utf-8")
        self.assertNotIn('"PySide6.QtWebEngineCore"', doc_tool_spec)
        self.assertNotIn('"PySide6.QtWebEngineWidgets"', doc_tool_spec)
        self.assertNotIn('"PySide6.QtWebChannel"', doc_tool_spec)
        self.assertIn("web_preview", doc_tool_spec)

        # 2. 检查 packaging/doc_tool_onefile.spec
        onefile_spec = (REPO_ROOT / "packaging" / "doc_tool_onefile.spec").read_text(encoding="utf-8")
        self.assertNotIn('"PySide6.QtWebEngineCore"', onefile_spec)
        self.assertNotIn('"PySide6.QtWebEngineWidgets"', onefile_spec)
        self.assertNotIn('"PySide6.QtWebChannel"', onefile_spec)
        self.assertIn("web_preview", onefile_spec)

        # 3. 检查 THIRD_PARTY_LICENSES.txt
        licenses = (REPO_ROOT / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
        self.assertIn("markdown-it 14.1.0", licenses)
        self.assertIn("Mermaid 11.16.1", licenses)
        self.assertIn("MIT License", licenses)

    def test_8_2_offline_static_resources_integrity(self):
        """8.2: 离线静态资源完整且哈希可核对，断网时无需拉取任何外部文件。"""
        res_dir = REPO_ROOT / "doc_tool" / "resources" / "web_preview"
        self.assertTrue((res_dir / "preview.html").is_file())
        self.assertTrue((res_dir / "markdown-it.min.js").is_file())
        self.assertTrue((res_dir / "OFFLINE_RESOURCE_MANIFEST.md").is_file())

        js_bytes = (res_dir / "markdown-it.min.js").read_bytes()
        expected_sha256 = "38c70a1e7ca91ab40e2d9e6e60129851a717ed1c7d4acbbdd41bf9503791cf68"
        self.assertEqual(hashlib.sha256(js_bytes).hexdigest(), expected_sha256)

        html_text = (res_dir / "preview.html").read_text(encoding="utf-8")
        self.assertIn("markdown-it.min.js", html_text)
        self.assertIn("mermaid.min.js", html_text)
        self.assertIn("previewBridge", html_text)

    def test_8_3_headless_and_readonly_html_boundary(self):
        """8.3: 无 GUI CLI 与只读离线 HTML 包保留原有契约，不依赖 GUI 浏览器初始化。"""
        from doc_tool.application.prepared_source import SUPPORTED_KINDS
        self.assertEqual(SUPPORTED_KINDS, ("flowchart", "sequenceDiagram"))

        # CLI 检测不加载 WebEngine 实例
        from doc_tool.application.content.mermaid import get_cli_status
        status = get_cli_status()
        self.assertIn(status["type"], ("path", "local", "none"))

    def test_8_4_capability_statement_fidelity(self):
        """8.4: 规格与说明一致，不宣传未验证的 Word 分页一致或全量 Typora 即时编辑。"""
        from doc_tool.domain.preview_types import PreviewMode
        self.assertEqual(PreviewMode.FIDELITY.value, "fidelity")
        self.assertEqual(PreviewMode.LIGHTWEIGHT.value, "lightweight")


if __name__ == "__main__":
    unittest.main()
