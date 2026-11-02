# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/ui/content/mermaid_renderer.py")
content = target.read_text(encoding="utf-8")

old_def = "class OfficialMermaidRenderer:"
new_def = """class OfficialMermaidRenderer:
    MERMAID_VERSION = "11.16.1"

    def get_engine_version(self) -> str:
        return self.MERMAID_VERSION
"""

assert old_def in content
content = content.replace(old_def, new_def, 1)
target.write_text(content, encoding="utf-8")
print("mermaid_renderer.py updated with get_engine_version!")
