with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = """        self._custom_page = _WebPreviewPage(self)
        self._custom_page.anchor_clicked.connect(self.anchorClicked)
        self._custom_page.mermaid_edit_requested.connect(self._on_mermaid_edit_requested)
        self._custom_page.mermaid_view_requested.connect(self._on_mermaid_view_requested)
        self._custom_page.heading_clicked.connect(self._on_heading_clicked)
        self._custom_page.mermaid_locate_requested.connect(self._on_mermaid_locate_requested)
        self._custom_page.render_process_crashed.connect(self._on_render_process_crashed)
        self.setPage(self._custom_page)

        self._web_channel = QWebChannel(self._custom_page)
        self._bridge = _WebPreviewBridge(self)
        self._web_channel.registerObject("previewBridge", self._bridge)
        self._custom_page.setWebChannel(self._web_channel)"""

replacement = """        p = self.page()
        p.renderProcessTerminated.connect(self._on_render_process_terminated)

        self._web_channel = QWebChannel(p)
        self._bridge = _WebPreviewBridge(self)
        self._web_channel.registerObject("previewBridge", self._bridge)
        p.setWebChannel(self._web_channel)"""

assert target in code, "Target not found"
code = code.replace(target, replacement, 1)

# Add _on_render_process_terminated to WebPreviewBrowser if not present
if "def _on_render_process_terminated" not in code:
    handler = """
    def _on_render_process_terminated(self, status, exit_code: int) -> None:
        msg = f"WebEngine 渲染进程异常退出: status={status}, exitCode={exit_code}"
        logger.error(msg)
        self.renderProcessCrashed.emit(msg)
"""
    code = code.replace("    def _on_render_process_crashed", handler + "\n    def _on_render_process_crashed", 1)

with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
    f.write(code)
print("Updated web_preview_browser.py to use default page")
