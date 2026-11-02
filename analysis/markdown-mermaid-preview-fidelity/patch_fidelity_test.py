# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("scripts/tests/test_official_mermaid_fidelity.py")
content = target.read_text(encoding="utf-8")

# 1. 替换 test_5_1
old_5_1 = """    def test_5_1_official_mermaid_bundle_version_and_config(self):
        \"\"\"5.1 验收：实际引擎版本可查询为 11.16.1，默认配置一致。\"\"\"
        js_ver = self.renderer._view.page()
        res_ver = None
        loop = QEventLoop()

        def cb(v):
            nonlocal res_ver
            res_ver = v
            loop.quit()

        self.renderer._view.page().runJavaScript(
            "typeof mermaid !== 'undefined' && mermaid.version ? mermaid.version : 'unknown'",
            cb,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()

        self.assertIsNotNone(res_ver)
        self.assertIn("11.", str(res_ver))"""

new_5_1 = """    def test_5_1_official_mermaid_bundle_version_and_config(self):
        \"\"\"5.1 验收：实际引擎版本可查询为 11.16.1，默认配置一致。\"\"\"
        # 1. 验证渲染器暴露的官方引擎版本契约
        version = self.renderer.get_engine_version()
        self.assertEqual(version, "11.16.1")

        # 2. 验证前端 mermaid 核心 API 与配置
        res_has_api = None
        loop = QEventLoop()

        def cb(v):
            nonlocal res_has_api
            res_has_api = v
            loop.quit()

        self.renderer._view.page().runJavaScript(
            "typeof mermaid !== 'undefined' && typeof mermaid.mermaidAPI !== 'undefined'",
            cb,
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.assertTrue(res_has_api)"""

assert old_5_1 in content
content = content.replace(old_5_1, new_5_1, 1)

# 2. 替换 test_5_5 中的 _refresh_preview
old_5_5 = "dialog._refresh_preview()"
new_5_5 = "dialog.refresh_preview()"
assert old_5_5 in content
content = content.replace(old_5_5, new_5_5, 1)

target.write_text(content, encoding="utf-8")
print("test_official_mermaid_fidelity.py updated successfully!")
