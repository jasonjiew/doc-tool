# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/resources/web_preview/preview.html")
text = target.read_text(encoding="utf-8")

old_fn = """function applyAlertBlocks(html) {
  return html.replace(/<blockquote>\\s*<p>\\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\\](?:\\s*<br>|\\s+)([\\s\\S]*?)<\\/p>\\s*<\\/blockquote>/gi, function(match, type, content) {
    const t = type.toUpperCase();
    const isWarn = t === 'WARNING' || t === 'CAUTION';
    const cls = isWarn ? 'alert-block alert-warn' : 'alert-block';
    return `<div class="${cls}"><div class="alert-title">${t}</div><p>${content}</p></div>`;
  });
}"""

new_fn = """function applyAlertBlocks(html) {
  return html.replace(/<blockquote[^>]*>\\s*<p[^>]*>\\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\\](?:\\s*<br>|\\s+)([\\s\\S]*?)<\\/p>\\s*<\\/blockquote>/gi, function(match, type, content) {
    const t = type.toUpperCase();
    const isWarn = t === 'WARNING' || t === 'CAUTION';
    const cls = isWarn ? 'alert-block alert-warn' : 'alert-block';
    return `<div class="${cls}"><div class="alert-title">${t}</div><p>${content}</p></div>`;
  });
}"""

assert old_fn in text
text = text.replace(old_fn, new_fn, 1)
target.write_text(text, encoding="utf-8")
print("preview.html alert regex fixed!")
