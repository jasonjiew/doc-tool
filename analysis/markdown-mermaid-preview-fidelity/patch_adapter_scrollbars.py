with open('doc_tool/ui/content/preview_adapter.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = "    def viewport(self) -> QWidget:"
replacement = """    def horizontalScrollBar(self):
        if self._mode == PreviewMode.LIGHTWEIGHT or not self._fidelity_browser:
            return self._light_browser.horizontalScrollBar()
        if hasattr(self._fidelity_browser, "horizontalScrollBar"):
            return self._fidelity_browser.horizontalScrollBar()
        return self._light_browser.horizontalScrollBar()

    def verticalScrollBar(self):
        if self._mode == PreviewMode.LIGHTWEIGHT or not self._fidelity_browser:
            return self._light_browser.verticalScrollBar()
        if hasattr(self._fidelity_browser, "verticalScrollBar"):
            return self._fidelity_browser.verticalScrollBar()
        return self._light_browser.verticalScrollBar()

    def viewport(self) -> QWidget:"""

assert target in code, "Target not found"
code = code.replace(target, replacement, 1)

with open('doc_tool/ui/content/preview_adapter.py', 'w', encoding='utf-8', newline='') as f:
    f.write(code)
print("Added scrollbar methods to preview_adapter.py successfully")
