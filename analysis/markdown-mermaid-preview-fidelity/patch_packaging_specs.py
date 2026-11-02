# 1. Update packaging/doc_tool.spec
with open('packaging/doc_tool.spec', 'r', encoding='utf-8') as f:
    spec_content = f.read()

webengine_excludes = """        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel",
"""

if webengine_excludes in spec_content:
    spec_content = spec_content.replace(webengine_excludes, "", 1)
    with open('packaging/doc_tool.spec', 'w', encoding='utf-8', newline='') as f:
        f.write(spec_content)
    print("Removed WebEngine excludes from packaging/doc_tool.spec")

# 2. Update packaging/doc_tool_onefile.spec
with open('packaging/doc_tool_onefile.spec', 'r', encoding='utf-8') as f:
    onefile_content = f.read()

if webengine_excludes in onefile_content:
    onefile_content = onefile_content.replace(webengine_excludes, "", 1)
    with open('packaging/doc_tool_onefile.spec', 'w', encoding='utf-8', newline='') as f:
        f.write(onefile_content)
    print("Removed WebEngine excludes from packaging/doc_tool_onefile.spec")

# 3. Update THIRD_PARTY_LICENSES.txt
with open('THIRD_PARTY_LICENSES.txt', 'r', encoding='utf-8') as f:
    licenses_content = f.read()

frontend_licenses = """
前端离线静态资源（离线预览内置）：
-----------------------------------

12. markdown-it 14.1.0
   许可证：MIT License
   用途：离线高保真 Markdown 解析与结构渲染
   https://github.com/markdown-it/markdown-it

13. Mermaid 11.16.1
   许可证：MIT License
   用途：离线官方 Mermaid 矢量渲染与布局生成
   https://github.com/mermaid-js/mermaid
"""

if "markdown-it 14.1.0" not in licenses_content:
    target_marker = "Python 标准库（随 Python 官方发行版提供）："
    if target_marker in licenses_content:
        licenses_content = licenses_content.replace(target_marker, frontend_licenses + "\n" + target_marker, 1)
    else:
        licenses_content += "\n" + frontend_licenses
    with open('THIRD_PARTY_LICENSES.txt', 'w', encoding='utf-8', newline='') as f:
        f.write(licenses_content)
    print("Added markdown-it and Mermaid to THIRD_PARTY_LICENSES.txt")
