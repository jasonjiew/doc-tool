with open('scripts/tests/run_tests.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '"test_reading_continuity_and_sync.py", "test_operation_loading_overlay.py"'
replacement = '"test_reading_continuity_and_sync.py", "test_packaging_and_delivery_fidelity.py", "test_operation_loading_overlay.py"'

assert target in content, "Target not found in run_tests.py"
content = content.replace(target, replacement, 1)

with open('scripts/tests/run_tests.py', 'w', encoding='utf-8', newline='') as f:
    f.write(content)
print("Registered test_packaging_and_delivery_fidelity.py in run_tests.py")
