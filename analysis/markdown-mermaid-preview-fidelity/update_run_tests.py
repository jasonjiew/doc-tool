# -*- coding: utf-8 -*-
from pathlib import Path

target_file = Path("scripts/tests/run_tests.py")
text = target_file.read_text(encoding="utf-8")
old_item = '"test_diagram_viewer_interaction.py", "test_operation_loading_overlay.py",'
new_item = '"test_diagram_viewer_interaction.py", "test_preview_fidelity_adapter.py", "test_operation_loading_overlay.py",'
assert old_item in text
text = text.replace(old_item, new_item, 1)
target_file.write_text(text, encoding="utf-8")
print("run_tests.py updated successfully!")
