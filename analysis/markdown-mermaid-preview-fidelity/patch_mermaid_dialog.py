# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/ui/content/mermaid_dialog.py")
content = target.read_text(encoding="utf-8")

# 1. 替换 _refresh_preview 中的 render 调用
old_preview_render = """        actual = detect_kind(source)
        # 实时预览：flowchart/sequenceDiagram 内置快速渲染；其它类型若有 CLI 则走 CLI
        if actual in ("flowchart", "sequenceDiagram"):
            result = render(source, use_cli=False)
        else:
            result = render(source, use_cli=True)"""

new_preview_render = """        actual = detect_kind(source)
        # 优先使用桌面官方 Mermaid 引擎（REQ-MM-04，与阅读区/大图保持同一契约）
        try:
            from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
            official_renderer = get_official_mermaid_renderer()
            result = official_renderer.render(source, want_png=True)
        except Exception:
            result = None

        if result is None or not result.ok:
            # 官方渲染不可用或失败时，降级使用内置近似模式
            if actual in ("flowchart", "sequenceDiagram"):
                result = render(source, use_cli=False)
            else:
                result = render(source, use_cli=True)"""

assert old_preview_render in content, "未找到 _refresh_preview 中的 render 逻辑"
content = content.replace(old_preview_render, new_preview_render, 1)

# 2. 替换 _finish 中的 export render 调用
old_finish_render = """        # 实时预览用内置渲染器（快），导出用 mermaid-cli 官方渲染；未安装时自动回退。
        result = render(source, use_cli=True)
        if not result.ok or not result.png:
            self.status.setText("渲染失败：{0}".format(result.error or "未知原因"))
            return
        self.render_result = result
        if result.backend == "mermaid-cli":
            self.status.setText("已用 mermaid-cli 渲染，可插入 Word")
        else:
            self.status.setText("未检测到 mermaid-cli，已用内置渲染器（近似效果）；安装 mermaid-cli 后导出自动升级为官方渲染")"""

new_finish_render = """        # 优先使用桌面官方 Mermaid 引擎生成高保真 PNG（无 Node/npm 依赖，REQ-MM-05）
        try:
            from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
            official_renderer = get_official_mermaid_renderer()
            result = official_renderer.render(source, want_png=True)
        except Exception:
            result = None

        if result is None or not result.ok or not result.png:
            result = render(source, use_cli=True)

        if not result.ok or not result.png:
            self.status.setText("渲染失败：{0}".format(result.error or "未知原因"))
            return
        self.render_result = result
        if result.backend in ("official-webengine", "mermaid-cli"):
            self.status.setText("已使用官方 Mermaid 引擎渲染，可直接插入 Word")
        else:
            self.status.setText("已使用内置渲染器（近似效果）")"""

assert old_finish_render in content, "未找到 _finish 中的 export render 逻辑"
content = content.replace(old_finish_render, new_finish_render, 1)

target.write_text(content, encoding="utf-8")
print("mermaid_dialog.py patched successfully!")
