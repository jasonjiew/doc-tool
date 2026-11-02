with open('doc_tool/ui/content/editor_panel.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = """        # 批量转换所有 Mermaid 源码（包含裸源码与围栏块）为图片。批量优先
        # mermaid-cli（若已安装，单块约 1~3s）；未安装 mmdc 时自动回退内置渲染器。
        converted = batch_convert(
            self._editor.toPlainText(), exporter, include_fenced=True, use_cli=True
        )"""

replacement = """        # 优先使用官方桌面渲染器（无 Node/npm 依赖，高保真生成 PNG，REQ-MM-05）
        try:
            from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
            official = get_official_mermaid_renderer()
            def desktop_renderer(source: str, kind=None):
                res = official.render(source, want_png=True)
                if res and res.ok:
                    return res
                from doc_tool.application.content.mermaid import render as app_render
                return app_render(source, kind=kind, use_cli=True)
        except Exception:
            desktop_renderer = None

        converted = batch_convert(
            self._editor.toPlainText(),
            exporter,
            include_fenced=True,
            use_cli=True,
            renderer=desktop_renderer,
        )"""

assert target in code, "Target not found in editor_panel.py"
code = code.replace(target, replacement, 1)

with open('doc_tool/ui/content/editor_panel.py', 'w', encoding='utf-8', newline='') as f:
    f.write(code)
print("Updated batch_convert_mermaid in editor_panel.py")
