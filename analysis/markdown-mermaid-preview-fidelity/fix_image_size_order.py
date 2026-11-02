with open('doc_tool/resources/web_preview/preview.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update updateMarkdown order
old_order = """  // Markdown-it 结构化解析
  let renderedHtml = md.render(text);
  renderedHtml = sanitizeImageAndLinks(renderedHtml);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);"""

new_order = """  // Markdown-it 结构化解析
  let renderedHtml = md.render(text);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = sanitizeImageAndLinks(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);"""

if old_order in html:
    html = html.replace(old_order, new_order, 1)

# 2. Update image error handler to preserve style on placeholder
old_err_handler = """      const placeholder = document.createElement('div');
      placeholder.className = 'missing-image-placeholder';
      placeholder.innerHTML = `⚠️ 缺失图片: <code>${src}</code> (说明: ${alt})`;
      img.replaceWith(placeholder);"""

new_err_handler = """      const placeholder = document.createElement('div');
      placeholder.className = 'missing-image-placeholder';
      if (img.getAttribute('style')) {
        placeholder.setAttribute('style', img.getAttribute('style'));
      }
      placeholder.innerHTML = `⚠️ 缺失图片: <code>${src}</code> (说明: ${alt})`;
      img.replaceWith(placeholder);"""

if old_err_handler in html:
    html = html.replace(old_err_handler, new_err_handler, 1)

with open('doc_tool/resources/web_preview/preview.html', 'w', encoding='utf-8', newline='') as f:
    f.write(html)
print("Updated image size order and error placeholder style in preview.html")
