# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("doc_tool/resources/web_preview/preview.html")

html_content = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Markdown & Mermaid 实时高保真预览</title>
<script src="markdown-it.min.js"></script>
<script src="mermaid.min.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
:root {
  --bg-color: #ffffff;
  --text-color: #1f2328;
  --border-color: #d0d7de;
  --code-bg: #f6f8fa;
  --card-bg: #ffffff;
  --card-border: #e2e8f0;
  --muted-text: #64748b;
  --link-color: #0969da;
  --table-border: #d0d7de;
  --table-th-bg: #f6f8fa;
  --table-zebra-bg: #f8fafc;
  --badge-bg: #f1f5f9;
  --badge-text: #475569;
  --quote-border: #d0d7de;
  --quote-text: #57606a;
  --alert-note-bg: #eff6ff;
  --alert-note-border: #3b82f6;
  --alert-warn-bg: #fffbeb;
  --alert-warn-border: #f59e0b;
}

body.dark-theme {
  --bg-color: #1e1f26;
  --text-color: #e5e7eb;
  --border-color: #374151;
  --code-bg: #282a36;
  --card-bg: #232530;
  --card-border: #383a48;
  --muted-text: #94a3b8;
  --link-color: #58a6ff;
  --table-border: #3b3d4a;
  --table-th-bg: #282a36;
  --table-zebra-bg: #242632;
  --badge-bg: #334155;
  --badge-text: #cbd5e1;
  --quote-border: #4b5563;
  --quote-text: #9ca3af;
  --alert-note-bg: #1e293b;
  --alert-note-border: #60a5fa;
  --alert-warn-bg: #292524;
  --alert-warn-border: #fbbf24;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", Helvetica, Arial, sans-serif;
  font-size: 14.5px;
  line-height: 1.68;
  color: var(--text-color);
  background-color: var(--bg-color);
  margin: 0;
  padding: 0;
  word-wrap: break-word;
  transition: background-color 0.2s ease, color 0.2s ease;
}

/* 作用域隔离的 Markdown 正文容器，避免样式污染 Mermaid 生成的 SVG 元素（REQ-MD-03） */
.markdown-body {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 28px;
  box-sizing: border-box;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin-top: 24px;
  margin-bottom: 12px;
  font-weight: 600;
  line-height: 1.35;
  cursor: pointer;
  transition: color 0.15s ease;
}
.markdown-body h1:hover,
.markdown-body h2:hover,
.markdown-body h3:hover,
.markdown-body h4:hover,
.markdown-body h5:hover,
.markdown-body h6:hover {
  color: var(--link-color);
}
.markdown-body h1 { font-size: 1.85em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.3em; }
.markdown-body h2 { font-size: 1.5em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.3em; }
.markdown-body h3 { font-size: 1.25em; }
.markdown-body h4 { font-size: 1.1em; }

.markdown-body p,
.markdown-body ul,
.markdown-body ol,
.markdown-body dl {
  margin-top: 0;
  margin-bottom: 14px;
}

/* 嵌套列表层级结构保留（REQ-MD-01） */
.markdown-body ul,
.markdown-body ol {
  padding-left: 2em;
}
.markdown-body ul ul,
.markdown-body ul ol,
.markdown-body ol ul,
.markdown-body ol ol {
  margin-top: 4px;
  margin-bottom: 4px;
}
.markdown-body li {
  margin-top: 2px;
  margin-bottom: 2px;
}
.markdown-body li > p {
  margin-top: 6px;
  margin-bottom: 6px;
}

/* 任务列表（REQ-MD-01） */
.markdown-body .task-list-item {
  list-style-type: none;
  margin-left: -1.5em;
}
.markdown-body .task-list-item-checkbox {
  margin-right: 0.45em;
  vertical-align: middle;
}

/* 引用块与提示块（REQ-MD-01、REQ-MD-04） */
.markdown-body blockquote {
  margin: 14px 0;
  padding: 6px 16px;
  color: var(--quote-text);
  border-left: 4px solid var(--quote-border);
  background-color: transparent;
}
.markdown-body blockquote blockquote {
  margin: 6px 0;
}
.markdown-body .alert-block {
  margin: 14px 0;
  padding: 10px 16px;
  border-left: 4px solid var(--alert-note-border);
  background-color: var(--alert-note-bg);
  border-radius: 4px;
}
.markdown-body .alert-block.alert-warn {
  border-left-color: var(--alert-warn-border);
  background-color: var(--alert-warn-bg);
}
.markdown-body .alert-title {
  font-weight: 600;
  margin-bottom: 4px;
}

/* 表格结构、三向列对齐与宽表横向滚动（REQ-MD-02） */
.markdown-body .table-wrapper {
  width: 100%;
  overflow-x: auto;
  margin: 16px 0;
  -webkit-overflow-scrolling: touch;
}
.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  display: table;
  border-spacing: 0;
  font-size: 13.5px;
}
.markdown-body table th,
.markdown-body table td {
  padding: 8px 12px;
  border: 1px solid var(--table-border);
}
.markdown-body table th {
  font-weight: 600;
  background-color: var(--table-th-bg);
}
.markdown-body table tr:nth-child(2n) {
  background-color: var(--table-zebra-bg);
}

/* 代码块与行内代码保护（REQ-MD-01、REQ-MD-03） */
.markdown-body code {
  font-family: Consolas, "Cascadia Code", "Courier New", monospace;
  font-size: 88%;
  padding: 0.2em 0.4em;
  margin: 0 2px;
  background-color: var(--code-bg);
  border-radius: 4px;
}
.markdown-body pre {
  margin: 14px 0;
  padding: 14px 16px;
  overflow-x: auto;
  background-color: var(--code-bg);
  border-radius: 6px;
  border: 1px solid var(--border-color);
  line-height: 1.45;
}
.markdown-body pre code {
  padding: 0;
  margin: 0;
  background: transparent;
  font-size: 13px;
  white-space: pre;
}

/* 超链接与图片展示（REQ-MD-04、REQ-MD-05） */
.markdown-body a {
  color: var(--link-color);
  text-decoration: none;
}
.markdown-body a:hover {
  text-decoration: underline;
}
.markdown-body img {
  max-width: 100%;
  box-sizing: border-box;
  border-radius: 4px;
  height: auto;
}

/* Mermaid 容器卡片 */
.mermaid-card {
  margin: 20px 0;
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.mermaid-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--code-bg);
  border-bottom: 1px solid var(--card-border);
  font-size: 12px;
}
.mermaid-header-title {
  font-weight: 600;
  color: var(--muted-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.mermaid-header-actions {
  display: flex;
  gap: 6px;
}
.mermaid-btn {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  color: var(--text-color);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.mermaid-btn:hover {
  background: var(--border-color);
}
.mermaid-viewport {
  position: relative;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  overflow: hidden;
  background: var(--card-bg);
  cursor: grab;
}
.mermaid-viewport.grabbing {
  cursor: grabbing;
}
.mermaid-viewport svg {
  max-width: 100%;
  height: auto;
  transition: transform 0.05s ease-out;
  transform-origin: center center;
}
.mermaid-error-box {
  padding: 14px;
  color: #ef4444;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  font-family: Consolas, monospace;
}
body.dark-theme .mermaid-error-box {
  background: #2b1d1d;
  border-color: #4c1d1d;
  color: #fca5a5;
}
</style>
</head>
<body>
<div class="markdown-body" id="preview-container">
  <div style="color: var(--muted-text); text-align: center; padding: 40px;">正在加载高保真阅读预览...</div>
</div>

<script>
let currentVersion = 0;
let isDarkTheme = false;
let bridge = null;

// 初始化 QWebChannel 安全桥梁（REQ-MD-05、REQ-MD-06）
if (typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined') {
  new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.previewBridge;
    if (bridge && typeof bridge.reportReady === 'function') {
      bridge.reportReady();
    }
  });
}

// 初始化 markdown-it 实例并配置安全参数（REQ-MD-01、REQ-MD-05）
const md = window.markdownit({
  html: false,        // 严格拦截正文中的任意活动 HTML（REQ-MD-05）
  xhtmlOut: false,
  breaks: false,      // CommonMark 规范：同一段落内连续行不拆为新段落
  langPrefix: 'language-',
  linkify: true,
  typographer: false
});

// 1. 扩展任务列表语法（- [ ] 与 - [x]）（REQ-MD-01）
md.core.ruler.after('inline', 'task-lists', function(state) {
  const tokens = state.tokens;
  for (let i = 2; i < tokens.length; i++) {
    if (tokens[i].type === 'inline' && tokens[i - 1].type === 'paragraph_open' && tokens[i - 2].type === 'list_item_open') {
      const text = tokens[i].content;
      if (/^\[[ xX]\][ \t]/.test(text)) {
        const checked = text[1] === 'x' || text[1] === 'X';
        tokens[i].content = text.slice(4);
        if (tokens[i].children && tokens[i].children.length > 0 && tokens[i].children[0].type === 'text') {
          tokens[i].children[0].content = tokens[i].children[0].content.replace(/^\[[ xX]\][ \t]/, '');
        }
        tokens[i - 2].attrJoin('class', 'task-list-item');
        const checkboxToken = new state.Token('html_inline', '', 0);
        checkboxToken.content = `<input type="checkbox" class="task-list-item-checkbox" ${checked ? 'checked' : ''} disabled /> `;
        tokens[i].children.unshift(checkboxToken);
      }
    }
  }
});

// 2. 注入行号锚点映射（REQ-MD-06）
const defaultRender = (tokens, idx, options, env, self) => self.renderToken(tokens, idx, options);
['paragraph_open', 'heading_open', 'blockquote_open', 'bullet_list_open', 'ordered_list_open'].forEach(type => {
  const orig = md.renderer.rules[type] || defaultRender;
  md.renderer.rules[type] = function(tokens, idx, options, env, self) {
    const token = tokens[idx];
    if (token.map && token.map.length >= 1) {
      const line = token.map[0] + 1;
      token.attrSet('id', `line-${line}`);
      token.attrSet('data-line', String(line));
    }
    return orig(tokens, idx, options, env, self);
  };
});

// 3. 表格包裹层，保障宽表横向滚动阅读（REQ-MD-02）
const origTableOpen = md.renderer.rules.table_open || defaultRender;
md.renderer.rules.table_open = function(tokens, idx, options, env, self) {
  const token = tokens[idx];
  let lineAttr = '';
  if (token.map && token.map.length >= 1) {
    const line = token.map[0] + 1;
    lineAttr = ` id="line-${line}" data-line="${line}"`;
  }
  return `<div class="table-wrapper"${lineAttr}>` + origTableOpen(tokens, idx, options, env, self);
};
const origTableClose = md.renderer.rules.table_close || defaultRender;
md.renderer.rules.table_close = function(tokens, idx, options, env, self) {
  return origTableClose(tokens, idx, options, env, self) + '</div>';
};

// 4. 围栏代码块拦截 Mermaid 与普通代码保护（REQ-MD-01、REQ-MM-01）
const origFence = md.renderer.rules.fence || defaultRender;
md.renderer.rules.fence = function(tokens, idx, options, env, self) {
  const token = tokens[idx];
  const lang = (token.info || '').trim();
  const line = token.map && token.map.length >= 1 ? token.map[0] + 1 : 1;

  if (lang === 'mermaid') {
    const rawCode = token.content;
    const escapedCode = rawCode.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `
    <div class="mermaid-card" id="line-${line}" data-line="${line}">
      <div class="mermaid-header">
        <span class="mermaid-header-title">📊 Mermaid 架构图</span>
        <div class="mermaid-header-actions">
          <button class="mermaid-btn btn-reset">100%</button>
          <button class="mermaid-btn btn-edit" title="在 Mermaid 工作台中编辑">编辑</button>
          <button class="mermaid-btn btn-view" title="放大并自由缩放探索">大图</button>
        </div>
      </div>
      <div class="mermaid-viewport" data-line="${line}">
        <div class="mermaid-loading" style="color:var(--muted-text); font-size:12px;">正在渲染官方图表...</div>
      </div>
      <pre class="mermaid-raw" style="display:none;">${escapedCode}</pre>
    </div>`;
  }

  if (token.map && token.map.length >= 1) {
    token.attrSet('id', `line-${line}`);
    token.attrSet('data-line', String(line));
  }
  return origFence(tokens, idx, options, env, self);
};

// 5. 项目图片尺寸扩展处理（REQ-MD-04）
function applyCustomImageSizes(html) {
  // 匹配形如 <img src="..." alt="...">\{width=300\} 或 \{width=300px height=200px\}
  return html.replace(/<img\s+([^>]*?)src="([^"]+)"([^>]*?)>\{width=(\d+)(?:px)?(?:\s+height=(\d+)(?:px)?)?\}/g, function(match, p1, src, p2, w, h) {
    let style = `max-width: ${w}px; width: 100%;`;
    if (h) style += ` height: ${h}px;`;
    return `<img ${p1}src="${src}"${p2} style="${style}">`;
  });
}

// 6. 提示块处理（> [!NOTE]、> [!WARNING] 等）（REQ-MD-04）
function applyAlertBlocks(html) {
  return html.replace(/<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:\s*<br>|\s+)([\s\S]*?)<\/p>\s*<\/blockquote>/gi, function(match, type, content) {
    const t = type.toUpperCase();
    const isWarn = t === 'WARNING' || t === 'CAUTION';
    const cls = isWarn ? 'alert-block alert-warn' : 'alert-block';
    return `<div class="${cls}"><div class="alert-title">${t}</div><p>${content}</p></div>`;
  });
}

/**
 * 核心渲染调度函数：供 Python 端直接调用更新正文
 */
window.updateMarkdown = async function(text, dark, baseUrl, version) {
  if (typeof dark === 'boolean') {
    isDarkTheme = dark;
    if (dark) {
      document.body.classList.add('dark-theme');
    } else {
      document.body.classList.remove('dark-theme');
    }
  }

  if (typeof version === 'number') {
    currentVersion = version;
  }

  if (text === undefined || text === null) return;

  const container = document.getElementById('preview-container');
  if (!container) return;

  // 1. Markdown-it 结构化解析
  let renderedHtml = md.render(text);
  renderedHtml = applyCustomImageSizes(renderedHtml);
  renderedHtml = applyAlertBlocks(renderedHtml);
  container.innerHTML = renderedHtml;

  // 2. 异步渲染官方 Mermaid 图表
  const cards = container.querySelectorAll('.mermaid-card');
  if (cards.length > 0 && typeof mermaid !== 'undefined') {
    mermaid.initialize({
      startOnLoad: false,
      theme: isDarkTheme ? 'dark' : 'default',
      securityLevel: 'loose',
      htmlLabels: true
    });

    const thisVer = currentVersion;
    for (let i = 0; i < cards.length; i++) {
      if (thisVer !== currentVersion) return; // 过期丢弃
      const card = cards[i];
      const rawDiv = card.querySelector('.mermaid-raw');
      const viewport = card.querySelector('.mermaid-viewport');
      if (!rawDiv || !viewport) continue;

      const source = rawDiv.textContent.trim();
      const id = 'mmd-' + Date.now().toString(36) + '-' + i;

      try {
        const { svg } = await mermaid.render(id, source);
        if (thisVer !== currentVersion) return;
        viewport.innerHTML = svg;
        setupPanzoom(card, viewport, source, svg);
      } catch (err) {
        if (thisVer !== currentVersion) return;
        const tmp = document.getElementById('d' + id) || document.getElementById(id);
        if (tmp && tmp.parentElement) tmp.parentElement.removeChild(tmp);
        const errMsg = String(err && err.message ? err.message : err);
        viewport.innerHTML = `<div class="mermaid-error-box">⚠️ Mermaid 语法提示：\\n${errMsg}</div>`;
      }
    }
  }

  // 3. 通知就绪与完成统计
  if (bridge && typeof bridge.reportRendered === 'function') {
    bridge.reportRendered(currentVersion, cards.length);
  }
};

/**
 * 平滑缩放平移交互
 */
function setupPanzoom(card, viewport, source, svgContent) {
  let scale = 1.0;
  let translateX = 0;
  let translateY = 0;
  let isDragging = false;
  let startX = 0;
  let startY = 0;

  const btnReset = card.querySelector('.btn-reset');
  const btnEdit = card.querySelector('.btn-edit');
  const btnView = card.querySelector('.btn-view');

  function updateTransform() {
    const svg = viewport.querySelector('svg');
    if (svg) {
      svg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      if (btnReset) btnReset.textContent = Math.round(scale * 100) + '%';
    }
  }

  if (btnReset) {
    btnReset.addEventListener('click', () => {
      scale = 1.0;
      translateX = 0;
      translateY = 0;
      updateTransform();
    });
  }

  if (btnEdit) {
    btnEdit.addEventListener('click', () => {
      if (bridge && typeof bridge.reportMermaidAction === 'function') {
        bridge.reportMermaidAction('edit', source, '');
      } else {
        console.log('DOC_TOOL:mermaid-edit:' + encodeURIComponent(source));
      }
    });
  }

  if (btnView) {
    btnView.addEventListener('click', () => {
      const payload = JSON.stringify({ source: source, svg: svgContent });
      if (bridge && typeof bridge.reportMermaidAction === 'function') {
        bridge.reportMermaidAction('view', source, payload);
      } else {
        console.log('DOC_TOOL:mermaid-view:' + encodeURIComponent(payload));
      }
    });
  }

  viewport.addEventListener('wheel', (e) => {
    if (e.ctrlKey || e.metaKey || isDragging) {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1.15 : 0.87;
      scale = Math.min(Math.max(0.15, scale * delta), 6.0);
      updateTransform();
    }
  }, { passive: false });

  viewport.addEventListener('mousedown', (e) => {
    if (e.button === 0) {
      isDragging = true;
      startX = e.clientX - translateX;
      startY = e.clientY - translateY;
      viewport.classList.add('grabbing');

      const onMouseMove = (ev) => {
        if (!isDragging) return;
        translateX = ev.clientX - startX;
        translateY = ev.clientY - startY;
        updateTransform();
      };

      const onMouseUp = () => {
        if (isDragging) {
          isDragging = false;
          viewport.classList.remove('grabbing');
        }
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      };

      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    }
  });
}

// 全局超链接与标题双向定位（REQ-MD-06）
document.addEventListener('click', function(e) {
  // 1. 标题点击双向联动
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
  }

  // 2. 超链接与行号锚点跳转
  const link = e.target.closest('a');
  if (link && link.href) {
    const href = link.getAttribute('href') || '';
    if (href.startsWith('#line-') || href.startsWith('line-')) {
      e.preventDefault();
      const lineNo = href.replace(/^#?line-/, '');
      if (bridge && typeof bridge.reportAnchorClick === 'function') {
        bridge.reportAnchorClick(`line-${lineNo}`);
      } else {
        console.log('DOC_TOOL:anchor:' + lineNo);
      }
    } else if (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('mailto:')) {
      e.preventDefault();
      console.log('DOC_TOOL:external:' + href);
    } else if (href.startsWith('#')) {
      e.preventDefault();
      const targetId = decodeURIComponent(href.slice(1));
      const el = document.getElementById(targetId) || document.querySelector(`[name="${targetId}"]`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
});
</script>
</body>
</html>
'''

target.write_text(html_content, encoding="utf-8")
print(f"Updated {target} successfully!")
