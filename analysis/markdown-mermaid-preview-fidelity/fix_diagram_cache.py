with open('doc_tool/resources/web_preview/preview.html', 'r', encoding='utf-8') as f:
    html = f.read()

target = "window.updateMarkdown = async function(text, dark, baseUrl, version) {"
replacement = """const diagramCache = new Map();

window.updateMarkdown = async function(text, dark, baseUrl, version) {"""

assert target in html, "Target not found in preview.html"
html = html.replace(target, replacement, 1)

with open('doc_tool/resources/web_preview/preview.html', 'w', encoding='utf-8', newline='') as f:
    f.write(html)
print("Added diagramCache definition in preview.html")
