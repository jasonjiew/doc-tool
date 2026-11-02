# 1. Update doc_tool/ui/content/web_preview_browser.py
with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    browser_code = f.read()

# Update _on_block_clicked
old_block_click = """    def _on_block_clicked(self, block_id: str) -> None:
        if self._block_registry:
            loc = self._block_registry.find_by_id(block_id)
            if loc and self._editor_panel and hasattr(self._editor_panel, "highlight_line"):
                self._editor_panel.highlight_line(loc.start_line)
                if hasattr(self._editor_panel, "_flash_line"):
                    self._editor_panel._flash_line(loc.start_line)
                return
        if block_id.startswith("line-"):
            clean = block_id[len("line-"):]
            if clean.isdigit():
                self.anchorClicked.emit(QUrl(f"line-{clean}"))"""

new_block_click = """    def _on_block_clicked(self, block_id: str) -> None:
        if self._block_registry:
            loc = self._block_registry.find_by_id(block_id)
            if loc and self._editor_panel and hasattr(self._editor_panel, "highlight_line"):
                self._editor_panel.highlight_line(loc.start_line)
                if hasattr(self._editor_panel, "_flash_line"):
                    self._editor_panel._flash_line(loc.start_line)
                return
        if block_id.startswith("line-"):
            clean = block_id[len("line-"):]
            if clean.isdigit():
                line_no = int(clean)
                if self._editor_panel and hasattr(self._editor_panel, "highlight_line"):
                    self._editor_panel.highlight_line(line_no)
                    if hasattr(self._editor_panel, "_flash_line"):
                        self._editor_panel._flash_line(line_no)
                self.anchorClicked.emit(QUrl(f"line-{clean}"))"""

if old_block_click in browser_code:
    browser_code = browser_code.replace(old_block_click, new_block_click, 1)

# In set_markdown, add snapshot version check
old_set_md = """    def set_markdown(
        self,
        text: str,
        base_url: str = "",
        snapshot: Optional[PreviewSnapshot] = None,
    ) -> None:
        self._last_heading = None
        if snapshot is not None:
            self._current_snapshot = snapshot
            if snapshot.block_registry:
                self._block_registry = snapshot.block_registry"""

new_set_md = """    def set_markdown(
        self,
        text: str,
        base_url: str = "",
        snapshot: Optional[PreviewSnapshot] = None,
    ) -> None:
        self._last_heading = None
        if snapshot is not None:
            # 校验会话与版本：若已有较新版本，丢弃乱序返回的旧版本（REQ-MD-07）
            if self._current_snapshot is not None:
                if (
                    snapshot.session_id == self._current_snapshot.session_id
                    and snapshot.chapter_id == self._current_snapshot.chapter_id
                    and snapshot.buffer_version < self._current_snapshot.buffer_version
                ):
                    logger.info("Discarded stale preview render result: ver %s < current %s",
                                snapshot.buffer_version, self._current_snapshot.buffer_version)
                    return
            self._current_snapshot = snapshot
            if snapshot.block_registry:
                self._block_registry = snapshot.block_registry"""

if old_set_md in browser_code:
    browser_code = browser_code.replace(old_set_md, new_set_md, 1)

# Add scroll_to_line and cleanup methods to WebPreviewBrowser
extra_methods = """
    def scroll_to_line(self, line_no: int) -> None:
        \"\"\"根据源码行号将预览区平滑滚动到对应的块（REQ-MD-06）。\"\"\"
        if not self._page_ready:
            return
        js_code = f\"\"\"
        (() => {{
            let target = document.getElementById('line-{line_no}') || document.querySelector('[data-line="{line_no}"]');
            if (!target) {{
                for (let l = {line_no} - 1; l >= Math.max(1, {line_no} - 10); l--) {{
                    target = document.getElementById('line-' + l) || document.querySelector('[data-line="' + l + '"]');
                    if (target) break;
                }}
            }}
            if (target) {{
                target.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}
        }})();
        \"\"\"
        self.page().runJavaScript(js_code)

    def cleanup(self) -> None:
        \"\"\"安全释放页面与信道资源，避免多窗口内存泄漏（REQ-MD-07）。\"\"\"
        self._pending_update = None
        self._current_snapshot = None
        self._block_registry = None
        try:
            self.stop()
            self.setPage(None)
        except Exception:
            pass
"""

if "def scroll_to_line" not in browser_code:
    browser_code += extra_methods
    with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
        f.write(browser_code)
    print("Updated web_preview_browser.py")

# 2. Update doc_tool/ui/content/preview_adapter.py
with open('doc_tool/ui/content/preview_adapter.py', 'r', encoding='utf-8') as f:
    adapter_code = f.read()

# Add scroll_to_line and cleanup in PreviewAdapter
adapter_methods = """
    def scroll_to_line(self, line_no: int) -> None:
        \"\"\"双向滚动联动（REQ-MD-06）。\"\"\"
        if self._mode == PreviewMode.FIDELITY and hasattr(self._active_browser, "scroll_to_line"):
            self._active_browser.scroll_to_line(line_no)
        elif self._mode == PreviewMode.LIGHTWEIGHT and hasattr(self._active_browser, "scrollToAnchor"):
            self._active_browser.scrollToAnchor(f"line-{line_no}")

    def cleanup(self) -> None:
        \"\"\"安全释放适配器与底层浏览器资源（REQ-MD-07）。\"\"\"
        self._pending_buffer = None
        self._latest_snapshot = None
        if hasattr(self._web_browser, "cleanup"):
            self._web_browser.cleanup()
"""

if "def scroll_to_line" not in adapter_code:
    # insert before class or at end of PreviewAdapter
    adapter_code += adapter_methods
    with open('doc_tool/ui/content/preview_adapter.py', 'w', encoding='utf-8', newline='') as f:
        f.write(adapter_code)
    print("Updated preview_adapter.py")
