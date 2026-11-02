# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("scripts/tests/run_tests.py")
text = target.read_text(encoding="utf-8")
old_item = '"test_style_and_resource_boundaries.py",'
new_item = '"test_style_and_resource_boundaries.py", "test_official_mermaid_fidelity.py",'
assert old_item in text
text = text.replace(old_item, new_item, 1)
target.write_text(text, encoding="utf-8")
print("run_tests.py updated with test_official_mermaid_fidelity.py!")
