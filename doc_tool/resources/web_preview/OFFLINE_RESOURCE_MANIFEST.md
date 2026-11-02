# 离线预览静态资源与第三方许可清单 (Offline Resource Manifest)

本目录为 `doc-tool` 桌面高保真 Markdown 与 Mermaid 预览提供完全自包含的离线静态运行时资源。
应用运行与打包完全基于本地固定文件，**绝对禁止**运行时发起任何外部网络请求或依赖终端全局 npm/Node。

## 资源清单与校验哈希

| 文件名 | 组件与版本 | 来源与构建方式 | 许可证 | SHA-256 哈希值 |
| --- | --- | --- | --- | --- |
| `markdown-it.min.js` | markdown-it v14.1.0 | 官方 npm 独立分发包 (`dist/markdown-it.min.js`) | MIT License | `38c70a1e7ca91ab40e2d9e6e60129851a717ed1c7d4acbbdd41bf9503791cf68` |
| `mermaid.min.js` | Mermaid v11.16.1 | 官方独立浏览器分发 Bundle | MIT License | `18327bef70d96fb505fe7287d9f6a7362ebf07ff6576ddfaffb1a06f3e1a2954` |
| `marked.min.js` | Marked v4.3.0 | 历史集成原型库（保留供特定离线回退对照） | MIT License | `c68075672d976e4777390560baa112194855bd4404b13647da4855aae1f9360c` |
| `preview.html` | 离线宿主页面与样式 | 本工程内置（包含深浅色作用域样式、Task-Lists扩展规则、QWebChannel交互桥梁） | 随工程开源协议 | 动态计算 |

## 支持的方言与语法扩展声明

1. **CommonMark 核心规范**：
   - 段落与连续文本软换行（行尾单换行不分裂独立 `<p>` 标签）
   - 显式硬换行（行尾双空格或反斜杠换行）
   - 嵌套混合列表（有序与无序多层嵌套、保留层级结构不平铺）
   - 有序列表自定义起始编号（例如 `3. 第一项` 输出 `<ol start="3">`）
   - 引用块（单层与多层嵌套引用）
   - 围栏代码块（``` 与 ~~~）与行内代码保护（代码中的链接/图片/HTML/Mermaid 标记不执行）
2. **GFM / 项目扩展**：
   - 表格支持：列对齐（`:---`, `:---:`, `---:`）、单元格内转义竖线 `\|` 不拆列、宽表横向滚动阅读、长表尾行及后续正文完整保留
   - 删除线（`~~text~~`）
   - 任务列表（`- [ ]` 与 `- [x]` 渲染为只读复选框，禁止修改源正文）
   - 项目图片尺寸扩展：`![alt](src){width=300}` 解析为图片宽度元数据并响应阅读区域宽度
   - 构建占位符与提示块保护：在正文中保留呈现，代码块中相似字符串不被误预处理
   - 官方 Mermaid 11.16.1 渲染：支持 flowchart（子图、样式、回边、长中文标签）与 sequenceDiagram（alt/else、opt、loop、par/and、Note、激活条）
