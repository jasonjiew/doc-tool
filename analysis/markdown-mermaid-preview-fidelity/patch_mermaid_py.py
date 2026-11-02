# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/application/content/mermaid.py")
content = target.read_text(encoding="utf-8")

node_re_start = content.find("_NODE_RE = re.compile(")
edge_re_start = content.find("_EDGE_RE = re.compile(")
assert node_re_start != -1 and edge_re_start != -1

new_node_re = """_NODE_RE = re.compile(
    r"(?P<id>[\\w/.-]+)"
    r"(?:(?:\\*\\*)?\\(\\(\\((?:\\*\\*)?(?P<dblcircle>.*?)(?:\\*\\*)?\\)\\)\\)(?:\\*\\*)?"
    r"|(?:\\*\\*)?\\[\\[(?:\\*\\*)?(?P<sub>.*?)(?:\\*\\*)?\\]\\](?:\\*\\*)?"
    r"|(?:\\*\\*)?\\(\\((?:\\*\\*)?(?P<circle>.*?)(?:\\*\\*)?\\)\\)(?:\\*\\*)?"
    r"|(?:\\*\\*)?\\[\\((?:\\*\\*)?(?P<cyl>.*?)(?:\\*\\*)?\\)\\](?:\\*\\*)?"
    r"|(?:\\*\\*)?\\{\\{(?:\\*\\*)?(?P<hex>.*?)(?:\\*\\*)?\\}\\}(?:\\*\\*)?"
    r"|(?:\\*\\*)?\\[/(?:\\*\\*)?(?P<paraleft>.*?)(?:\\*\\*)?[/\\\\]\\](?:\\*\\*)?"
    r"|(?:\\*\\*)?\\[\\\\(?:\\*\\*)?(?P<pararight>.*?)(?:\\*\\*)?[/\\\\]\\](?:\\*\\*)?"
    r"|(?:\\*\\*)?\\(\\[(?:\\*\\*)?(?P<stadium>.*?)(?:\\*\\*)?\\]\\)(?:\\*\\*)?"
    r"|(?:\\*\\*)?>\\s*(?P<flag>.*?)(?:\\*\\*)?\\](?:\\*\\*)?"
    r"|(?:\\*\\*)?\\[(?:\\*\\*)?(?P<box>.*?)(?:\\*\\*)?\\](?:\\*\\*)?"
    r"|(?:\\*\\*)?\\((?:\\*\\*)?(?P<round>.*?)(?:\\*\\*)?\\)(?:\\*\\*)?"
    r"|(?:\\*\\*)?\\{(?:\\*\\*)?(?P<diamond>.*?)(?:\\*\\*)?\\})?"
)\n"""

content = content[:node_re_start] + new_node_re + content[edge_re_start:]

# 2. validate 增加官方校验
val_idx = content.find("def validate(source: str, kind: Optional[str] = None)")
assert val_idx != -1
body_start = content.find("lines = (source or \"\").splitlines()", val_idx)
assert body_start != -1

injection = """    # 优先在 GUI 运行时使用官方 Mermaid 引擎作为语法权威（REQ-MM-01）
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance():
            from doc_tool.ui.content.mermaid_renderer import get_official_mermaid_renderer
            official = get_official_mermaid_renderer()
            if official._page_ready:
                return official.validate(source)
    except Exception:
        pass

    """

content = content[:body_start] + injection + content[body_start:]

target.write_text(content, encoding="utf-8")
print("mermaid.py patched successfully!")
