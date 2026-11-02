with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = "logger = logging.getLogger(__name__)"
replacement = """logger = logging.getLogger(__name__)

_ACTIVE_BROWSERS = set()

def _cleanup_all_active_browsers():
    for b in list(_ACTIVE_BROWSERS):
        try:
            b.cleanup()
        except Exception:
            pass
    _ACTIVE_BROWSERS.clear()
"""

if "_cleanup_all_active_browsers" not in code:
    code = code.replace(target, replacement, 1)

init_target = "        self._load_template()"
init_replacement = """        self._load_template()
        _ACTIVE_BROWSERS.add(self)
        app = QApplication.instance()
        if app:
            try:
                app.aboutToQuit.connect(_cleanup_all_active_browsers)
            except Exception:
                pass"""

if init_target in code and "_ACTIVE_BROWSERS.add(self)" not in code:
    code = code.replace(init_target, init_replacement, 1)

cleanup_target = "    def cleanup(self) -> None:"
cleanup_replacement = """    def cleanup(self) -> None:
        _ACTIVE_BROWSERS.discard(self)"""

if cleanup_target in code and "_ACTIVE_BROWSERS.discard(self)" not in code:
    code = code.replace(cleanup_target, cleanup_replacement, 1)

with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
    f.write(code)
print("Updated web_preview_browser.py with aboutToQuit cleanup")
