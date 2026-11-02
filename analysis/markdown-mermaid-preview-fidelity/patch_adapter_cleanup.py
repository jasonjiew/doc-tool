# 1. Update doc_tool/ui/content/preview_adapter.py
with open('doc_tool/ui/content/preview_adapter.py', 'r', encoding='utf-8') as f:
    adapter_code = f.read()

target = "    def viewport(self) -> QWidget:"
replacement = """    def toPlainText(self) -> str:
        if self._light_browser:
            return self._light_browser.toPlainText()
        if self._fidelity_browser and getattr(self._fidelity_browser, "_compat_doc", None):
            return self._fidelity_browser._compat_doc.toPlainText()
        return ""

    def viewport(self) -> QWidget:"""

if target in adapter_code and "def toPlainText" not in adapter_code:
    adapter_code = adapter_code.replace(target, replacement, 1)

# Update cleanup and closeEvent in PreviewAdapter
old_cleanup = """    def cleanup(self) -> None:
        \"\"\"安全释放适配器与底层浏览器资源（REQ-MD-07）。\"\"\"
        self._pending_buffer = None
        self._latest_snapshot = None
        if hasattr(self._web_browser, "cleanup"):
            self._web_browser.cleanup()"""

new_cleanup = """    def cleanup(self) -> None:
        \"\"\"安全释放适配器与底层浏览器资源（REQ-MD-07）。\"\"\"
        self._current_text = ""
        self._current_snapshot = None
        if self._fidelity_browser and hasattr(self._fidelity_browser, "cleanup"):
            self._fidelity_browser.cleanup()

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)"""

if old_cleanup in adapter_code:
    adapter_code = adapter_code.replace(old_cleanup, new_cleanup, 1)

with open('doc_tool/ui/content/preview_adapter.py', 'w', encoding='utf-8', newline='') as f:
    f.write(adapter_code)
print("Updated preview_adapter.py with toPlainText and cleanup")

# 2. Update doc_tool/ui/content/web_preview_browser.py
with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    browser_code = f.read()

old_b_cleanup = """    def cleanup(self) -> None:
        \"\"\"安全释放页面与信道资源，避免多窗口内存泄漏（REQ-MD-07）。\"\"\"
        self._pending_update = None
        self._current_snapshot = None
        self._block_registry = None
        try:
            self.stop()
            self.setPage(None)
        except Exception:
            pass"""

new_b_cleanup = """    def cleanup(self) -> None:
        \"\"\"安全释放页面与信道资源，避免多窗口内存泄漏（REQ-MD-07）。\"\"\"
        self._pending_update = None
        self._current_snapshot = None
        self._block_registry = None
        try:
            self.stop()
            p = self.page()
            if p is not None:
                self.setPage(None)
                p.deleteLater()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)"""

if old_b_cleanup in browser_code:
    browser_code = browser_code.replace(old_b_cleanup, new_b_cleanup, 1)
    with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
        f.write(browser_code)
    print("Updated web_preview_browser.py with cleanup and closeEvent")
