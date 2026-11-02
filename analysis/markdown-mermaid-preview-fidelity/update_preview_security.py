# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/resources/web_preview/preview.html")
text = target.read_text(encoding="utf-8")

# 在 CSS 中添加 missing-image-placeholder 与 blocked-remote-resource 样式
css_to_add = """
.missing-image-placeholder {
  border: 1px dashed var(--border-color);
  padding: 10px 14px;
  background: var(--code-bg);
  color: var(--muted-text);
  font-size: 12px;
  border-radius: 4px;
  margin: 6px 0;
  display: block;
}
.blocked-remote-resource {
  border: 1px solid #f87171;
  background: #fef2f2;
  color: #b91c1c;
  padding: 8px 12px;
  font-size: 12px;
  border-radius: 4px;
  margin: 6px 0;
}
body.dark-theme .blocked-remote-resource {
  background: #3b1d1d;
  border-color: #7f1d1d;
  color: #fca5a5;
}
"""

text = text.replace("</style>", css_to_add + "\n</style>", 1)

# 在 JavaScript 中添加安全清洗函数与图片错误监听器
js_security = """
// 7. 正文图片与链接安全边界清洗（REQ-MD-05）
function sanitizeImageAndLinks(html) {
  // 拦截伪协议链接
  html = html.replace(/href\\s*=\\s*["']\\s*(javascript|vbscript|data):[^"']*["']/gi, 'href="#blocked-executable-url"');
  // 拦截远程图片与多级上级逃逸
  html = html.replace(/<img\\s+([^>]*?)src="([^"]+)"([^>]*?)>/gi, function(match, p1, src, p2) {
    if (/^(https?:|\\/\\/|ftp:)/i.test(src)) {
      return `<div class="blocked-remote-resource">🛡️ 远程资源已阻断: <code>${src}</code> (离线安全保护)</div>`;
    }
    if (src.includes('..') && (src.includes('../../') || src.startsWith('/') || src.includes('..\\\\..\\\\'))) {
      return `<div class="blocked-remote-resource">🛡️ 越界资源已阻断: <code>${src}</code> (禁止路径逃逸)</div>`;
    }
    return match;
  });
  return html;
}

// 缺失图片捕获并展示占位提示（REQ-MD-05）
document.addEventListener('error', function(e) {
  if (e.target && e.target.tagName === 'IMG') {
    const img = e.target;
    if (!img.dataset.failed) {
      img.dataset.failed = 'true';
      const src = img.getAttribute('src') || '';
      const alt = img.getAttribute('alt') || '无描述';
      const placeholder = document.createElement('div');
      placeholder.className = 'missing-image-placeholder';
      placeholder.innerHTML = `⚠️ 缺失图片: <code>${src}</code> (说明: ${alt})`;
      img.replaceWith(placeholder);
    }
  }
}, true);
"""

text = text.replace("window.updateMarkdown = async function", js_security + "\nwindow.updateMarkdown = async function", 1)

# 在 updateMarkdown 中调用 sanitizeImageAndLinks
old_render_call = """  let renderedHtml = md.render(text);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);"""

new_render_call = """  let renderedHtml = md.render(text);
  renderedHtml = sanitizeImageAndLinks(renderedHtml);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);"""

assert old_render_call in text
text = text.replace(old_render_call, new_render_call, 1)

target.write_text(text, encoding="utf-8")
print("preview.html updated with resource boundary protection!")
