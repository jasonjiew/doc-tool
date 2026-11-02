with open('scripts/tests/run_tests.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '"test_mermaid_export_and_cache.py", "test_operation_loading_overlay.py"'
replacement = '"test_mermaid_export_and_cache.py", "test_reading_continuity_and_sync.py", "test_operation_loading_overlay.py"'

assert target in content, "Target not found in run_tests.py"
content = content.replace(target, replacement, 1)

with open('scripts/tests/run_tests.py', 'w', encoding='utf-8', newline='') as f:
    f.write(content)
print("Registered test_reading_continuity_and_sync.py in run_tests.py")
