with open('scripts/tests/run_tests.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '"test_official_mermaid_fidelity.py", "test_operation_loading_overlay.py"'
replacement = '"test_official_mermaid_fidelity.py", "test_mermaid_export_and_cache.py", "test_operation_loading_overlay.py"'

assert target in content, "Target not found in run_tests.py"
content = content.replace(target, replacement, 1)

with open('scripts/tests/run_tests.py', 'w', encoding='utf-8', newline='') as f:
    f.write(content)
print("Registered test_mermaid_export_and_cache.py in run_tests.py")
