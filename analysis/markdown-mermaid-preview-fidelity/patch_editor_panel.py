# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/ui/content/editor_panel.py")
content = target.read_text(encoding="utf-8")

# 1. 替换 _ImageHitInfo 和 _PreviewBrowser 定义
old_def = """@dataclass
class _ImageHitInfo:
    img_format: QTextFormat
    pixmap: QPixmap
    line_no: Optional[int]
    is_mermaid: bool


class _PreviewBrowser(QTextBrowser):"""

start_idx = content.find(old_def)
end_marker = "class EditorPanel(QWidget):"
end_idx = content.find(end_marker)
assert start_idx != -1 and end_idx != -1

replacement_block = """from doc_tool.ui.content.preview_adapter import (
    PreviewAdapter,
    _PreviewBrowser,
    _ImageHitInfo,
)


"""

content = content[:start_idx] + replacement_block + content[end_idx:]

# 2. 替换 self._preview = _PreviewBrowser(...)
old_inst = "self._preview = _PreviewBrowser(preview_frame, editor_panel=self)"
new_inst = "self._preview = PreviewAdapter(preview_frame, editor_panel=self)"
assert old_inst in content, "未找到 self._preview 实例化"
content = content.replace(old_inst, new_inst, 1)

# 连接额外信号
old_connect = "self._preview.anchorClicked.connect(self._on_preview_anchor_clicked)"
new_connect = """self._preview.anchorClicked.connect(self._on_preview_anchor_clicked)
        if hasattr(self._preview, "headingClicked"):
            self._preview.headingClicked.connect(self.jump_to_heading)
        if hasattr(self._preview, "mermaidEditRequested"):
            self._preview.mermaidEditRequested.connect(self.open_mermaid_workbench)
        if hasattr(self._preview, "mermaidLocateRequested"):
            self._preview.mermaidLocateRequested.connect(self.locate_mermaid_source)"""
assert old_connect in content, "未找到 anchorClicked connect"
content = content.replace(old_connect, new_connect, 1)

# 3. 替换 _refresh_preview
old_refresh = """    def _refresh_preview(self, text: str) -> None:
        text = self._resolved_preview_text(text)
        document = self._preview.document()
        if hasattr(document, "setBaseUrl"):
            document.setBaseUrl(self._preview_base_url())
        if hasattr(document, "setHtml"):
            document.setHtml(render_markdown_html(text, dark=self._dark))
        if hasattr(self._preview, "adjust_images"):
            self._preview.adjust_images()
        if hasattr(self._preview, "moveCursor"):
            self._preview.moveCursor(QTextCursor.MoveOperation.Start)"""

new_refresh = """    def _refresh_preview(self, text: str) -> None:
        text = self._resolved_preview_text(text)
        if hasattr(self._preview, "update_content"):
            self._preview.update_content(text, self._preview_base_url())
        else:
            document = self._preview.document()
            if hasattr(document, "setBaseUrl"):
                document.setBaseUrl(self._preview_base_url())
            if hasattr(document, "setHtml"):
                document.setHtml(render_markdown_html(text, dark=self._dark))
            if hasattr(self._preview, "adjust_images"):
                self._preview.adjust_images()
            if hasattr(self._preview, "moveCursor"):
                self._preview.moveCursor(QTextCursor.MoveOperation.Start)"""

assert old_refresh in content, "未找到 _refresh_preview 方法"
content = content.replace(old_refresh, new_refresh, 1)

# 4. set_dark 联动
old_dark_block = """        if self._dark != dark:
            self._dark = dark
            self._refresh_preview(self._editor.toPlainText())"""

new_dark_block = """        if self._dark != dark:
            self._dark = dark
            if hasattr(self._preview, "set_dark"):
                self._preview.set_dark(dark)
            self._refresh_preview(self._editor.toPlainText())"""

assert old_dark_block in content, "未找到 set_dark block"
content = content.replace(old_dark_block, new_dark_block, 1)

target.write_text(content, encoding="utf-8")
print("editor_panel.py patched successfully!")
