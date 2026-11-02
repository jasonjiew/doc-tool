with open('doc_tool/ui/content/mermaid_renderer.py', 'r', encoding='utf-8') as f:
    code = f.read()

cleanup_fn = """
def _cleanup_global_renderer():
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
atexit.register(_cleanup_global_renderer)
"""

if "_cleanup_global_renderer" not in code:
    code += cleanup_fn
    with open('doc_tool/ui/content/mermaid_renderer.py', 'w', encoding='utf-8', newline='') as f:
        f.write(code)
    print("Added _cleanup_global_renderer in mermaid_renderer.py")
