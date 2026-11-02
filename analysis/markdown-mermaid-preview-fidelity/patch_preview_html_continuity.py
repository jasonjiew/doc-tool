with open('doc_tool/resources/web_preview/preview.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add diagramCache definition before window.updateMarkdown
old_header = "window.updateMarkdown = async function(text, isDark, baseUrl, version) {"
new_header = """const diagramCache = new Map();

window.updateMarkdown = async function(text, isDark, baseUrl, version) {"""
if old_header in html and "const diagramCache = new Map();" not in html:
    html = html.replace(old_header, new_header, 1)

# 2. Add scroll preservation
old_render_block = """  // 1. Markdown-it 结构化解析
  let renderedHtml = md.render(text);
  renderedHtml = sanitizeImageAndLinks(renderedHtml);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);
  container.innerHTML = renderedHtml;"""

new_render_block = """  // 1. 保存当前阅读滚动位置（REQ-MD-07：章节中部编辑不跳文首）
  const prevScroll = window.scrollY || document.documentElement.scrollTop || 0;

  // Markdown-it 结构化解析
  let renderedHtml = md.render(text);
  renderedHtml = sanitizeImageAndLinks(renderedHtml);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);
  container.innerHTML = renderedHtml;

  // 恢复阅读位置
  if (prevScroll > 0) {
    window.scrollTo({ top: prevScroll, behavior: 'instant' });
  }"""

if old_render_block in html:
    html = html.replace(old_render_block, new_render_block, 1)

# 3. Add diagramCache lookup and storage
old_render_card = """      const source = rawDiv.textContent.trim();
      const id = 'mmd-' + Date.now().toString(36) + '-' + i;

      try {
        const { svg } = await mermaid.render(id, source);
        if (thisVer !== currentVersion) return;
        viewport.innerHTML = svg;
        setupPanzoom(card, viewport, source, svg);
      } catch (err) {"""

new_render_card = """      const source = rawDiv.textContent.trim();
      const id = 'mmd-' + Date.now().toString(36) + '-' + i;
      const cacheKey = source + '::' + (isDarkTheme ? 'dark' : 'default');

      // 复用未变化图形，消除重复渲染与卡顿（REQ-MD-07）
      if (diagramCache.has(cacheKey)) {
        const cachedSvg = diagramCache.get(cacheKey);
        viewport.innerHTML = cachedSvg;
        setupPanzoom(card, viewport, source, cachedSvg);
        continue;
      }

      try {
        const { svg } = await mermaid.render(id, source);
        if (thisVer !== currentVersion) return;
        diagramCache.set(cacheKey, svg);
        viewport.innerHTML = svg;
        setupPanzoom(card, viewport, source, svg);
      } catch (err) {"""

if old_render_card in html:
    html = html.replace(old_render_card, new_render_card, 1)

# 4. Update click listener to report all block clicks
old_click = """// 全局双向定位（REQ-MD-06）
document.addEventListener('click', function(e) {
  // 1. 标题双向定位
  const heading = e.target.closest('h1, h2, h3, h4, h5, h6');
  if (heading && !e.target.closest('a') && !e.target.closest('button')) {
    const text = heading.textContent.trim();
    if (text) {
      if (bridge && typeof bridge.reportHeadingClick === 'function') {
        bridge.reportHeadingClick(text);
      } else {
        console.log('DOC_TOOL:heading-click:' + encodeURIComponent(text));
      }
    }
    return;
  }"""

new_click = """// 全局双向定位（REQ-MD-06）
document.addEventListener('click', function(e) {
  // 1. 块级定位（段落、列表、表格、代码、图形卡片等任意带有 line-N 的块）
  const block = e.target.closest('[id^="line-"]');
  if (block && !e.target.closest('a') && !e.target.closest('button')) {
    const blockId = block.id;
    if (bridge && typeof bridge.reportBlockClick === 'function') {
      bridge.reportBlockClick(blockId);
    }
  }

  // 标题双向定位兼容
  const heading = e.target.closest('h1, h2, h3, h4, h5, h6');
  if (heading && !e.target.closest('a') && !e.target.closest('button')) {
    const text = heading.textContent.trim();
    if (text) {
      if (bridge && typeof bridge.reportHeadingClick === 'function') {
        bridge.reportHeadingClick(text);
      } else {
        console.log('DOC_TOOL:heading-click:' + encodeURIComponent(text));
      }
    }
    return;
  }"""

if old_click in html:
    html = html.replace(old_click, new_click, 1)

with open('doc_tool/resources/web_preview/preview.html', 'w', encoding='utf-8', newline='') as f:
    f.write(html)
print("Updated preview.html for continuity and sync")
