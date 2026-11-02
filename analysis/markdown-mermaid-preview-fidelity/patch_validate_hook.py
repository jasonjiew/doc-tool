import re

with open('doc_tool/application/content/mermaid.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = """def validate(source: str, kind: Optional[str] = None) -> List[MermaidError]:
    \"\"\"校验 Mermaid 语法（兼容全量 Mermaid 图表格式），错误行相对源码从 1 开始。\"\"\"
        # 优先在 GUI 运行时使用官方 Mermaid 引擎作为语法权威（REQ-MM-01）
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance():
            from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
            official = get_official_mermaid_renderer()
            if official._page_ready:
                return official.validate(source)
    except Exception:
        pass

    lines = (source or \"\").splitlines()"""

replacement = """def validate_official(source: str) -> List[MermaidError]:
    \"\"\"高保真校验：在 GUI 运行时使用官方 Mermaid 引擎作为语法权威（REQ-MM-01）。\"\"\"
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance():
            from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
            official = get_official_mermaid_renderer()
            if official._page_ready:
                return official.validate(source)
    except Exception:
        pass
    return validate(source)


def validate(source: str, kind: Optional[str] = None, *, use_official: bool = False) -> List[MermaidError]:
    \"\"\"校验 Mermaid 语法（兼容全量 Mermaid 图表格式），错误行相对源码从 1 开始。\"\"\"
    if use_official:
        return validate_official(source)

    lines = (source or \"\").splitlines()"""

if target in content:
    content = content.replace(target, replacement, 1)
    with open('doc_tool/application/content/mermaid.py', 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print('Updated validate in mermaid.py successfully')
else:
    print('Target not found in mermaid.py')
