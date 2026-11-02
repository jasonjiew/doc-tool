# 1. Update doc_tool/ui/content/web_preview_browser.py
with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    browser_code = f.read()

cleanup_fn = """import atexit

_ACTIVE_BROWSERS = set()

def _cleanup_all_active_browsers():
    app = QApplication.instance()
    for b in list(_ACTIVE_BROWSERS):
        try:
            b.cleanup()
        except Exception:
            pass
    _ACTIVE_BROWSERS.clear()
    if app:
        try:
            app.sendPostedEvents()
            app.processEvents()
        except Exception:
            pass

atexit.register(_cleanup_all_active_browsers)
"""

old_block = """_ACTIVE_BROWSERS = set()

def _cleanup_all_active_browsers():
    for b in list(_ACTIVE_BROWSERS):
        try:
            b.cleanup()
        except Exception:
            pass
    _ACTIVE_BROWSERS.clear()"""

if old_block in browser_code:
    browser_code = browser_code.replace(old_block, cleanup_fn, 1)

old_cleanup = """    def cleanup(self) -> None:
        _ACTIVE_BROWSERS.discard(self)
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
            pass"""

new_cleanup = """    def cleanup(self) -> None:
        _ACTIVE_BROWSERS.discard(self)
        self._pending_update = None
        self._current_snapshot = None
        self._block_registry = None
        try:
            self.stop()
            p = getattr(self, "_custom_page", None) or self.page()
            self._custom_page = None
            if p is not None:
                self.setPage(None)
                p.deleteLater()
                app = QApplication.instance()
                if app:
                    app.sendPostedEvents()
                    app.processEvents()
        except Exception:
            pass"""

if old_cleanup in browser_code:
    browser_code = browser_code.replace(old_cleanup, new_cleanup, 1)

with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
    f.write(browser_code)
print("Updated web_preview_browser.py with robust teardown")

# 2. Update doc_tool/ui/content/mermaid_renderer.py
with open('doc_tool/ui/content/mermaid_renderer.py', 'r', encoding='utf-8') as f:
    m_code = f.read()

old_m_cleanup = """def _cleanup_global_renderer():
    global _GLOBAL_RENDERER
    if _GLOBAL_RENDERER is not None:
        try:
            r = _GLOBAL_RENDERER
            _GLOBAL_RENDERER = None
            if hasattr(r, "_view") and r._view:
                p = r._view.page()
                r._view.setPage(None)
                if p:
                    p.deleteLater()
                r._view.deleteLater()
        except Exception:
            pass

import atexit
atexit.register(_cleanup_global_renderer)"""

new_m_cleanup = """def _cleanup_global_renderer():
    global _GLOBAL_RENDERER
    if _GLOBAL_RENDERER is not None:
        try:
            r = _GLOBAL_RENDERER
            _GLOBAL_RENDERER = None
            if hasattr(r, "_view") and r._view:
                p = r._view.page()
                r._view.setPage(None)
                if p:
                    p.deleteLater()
                r._view.deleteLater()
                app = QApplication.instance()
                if app:
                    app.sendPostedEvents()
                    app.processEvents()
        except Exception:
            pass

import atexit
atexit.register(_cleanup_global_renderer)"""

if old_m_cleanup in m_code:
    m_code = m_code.replace(old_m_cleanup, new_m_cleanup, 1)
    with open('doc_tool/ui/content/mermaid_renderer.py', 'w', encoding='utf-8', newline='') as f:
        f.write(m_code)
    print("Updated mermaid_renderer.py with robust teardown")
