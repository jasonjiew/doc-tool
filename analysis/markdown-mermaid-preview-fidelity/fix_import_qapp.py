with open('doc_tool/ui/content/web_preview_browser.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = "from PySide6.QtWidgets import QWidget"
replacement = "from PySide6.QtWidgets import QApplication, QWidget"

assert target in code, "target not found"
code = code.replace(target, replacement, 1)

with open('doc_tool/ui/content/web_preview_browser.py', 'w', encoding='utf-8', newline='') as f:
    f.write(code)
print("Imported QApplication in web_preview_browser.py")
