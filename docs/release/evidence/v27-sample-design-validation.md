# design 严格校验报告

- 输出: `C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\output\.tmp-GX-V27-DESI 详细设计说明书样本(2.2).docx`

## 校验结果

- [PASS] DOCX ZIP 与全部 XML 可解析
- [PASS] Relationship Target 与引用完整
- [PASS] 章节编号、层级与必需资源预检 — 章节条目 1
- [FAIL] 目录/Markdown 与 Word 元素顺序、上下文严格一致 — #2 内容/位置不一致: expected P='模块划分与接口约束：代码示例必须保留缩进与空行。' (C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\content\1 样本.md:3); actual H=(2, '模块划分与接口约束：代码示例必须保留缩进与空行。') (body[318])；#8 内容/位置不一致: expected P='横向节之后回到纵向版式。' (C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\content\1 样本.md:29); actual H=(2, '横向节之后回到纵向版式。') (body[326])
- [FAIL] Heading 数量、文本、层级、顺序一致 — #2 内容/位置不一致: expected P='模块划分与接口约束：代码示例必须保留缩进与空行。' (C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\content\1 样本.md:3); actual H=(2, '模块划分与接口约束：代码示例必须保留缩进与空行。') (body[318])；#8 内容/位置不一致: expected P='横向节之后回到纵向版式。' (C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\content\1 样本.md:29); actual H=(2, '横向节之后回到纵向版式。') (body[326])
- [FAIL] 正文文本与位置一致 — #2 内容/位置不一致: expected P='模块划分与接口约束：代码示例必须保留缩进与空行。' (C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\content\1 样本.md:3); actual H=(2, '模块划分与接口约束：代码示例必须保留缩进与空行。') (body[318])；#8 内容/位置不一致: expected P='横向节之后回到纵向版式。' (C:\Users\18098\AppData\Local\Temp\v27-samples-e2flg9_i\design\content\1 样本.md:29); actual H=(2, '横向节之后回到纵向版式。') (body[326])
- [PASS] 普通表格文本一致
- [PASS] 复杂表格 OOXML 一致 — 复杂表格 0
- [PASS] 图片对象、内容哈希与位置一致
- [PASS] 媒体无重复打包 — media=180, duplicateFiles=0, duplicateBytes=0
- [PASS] document.xml 根节点结构合法
- [PASS] updateFields 仅位于 settings.xml
- [PASS] Styles/Font/Theme 保持模板体系
- [PASS] Numbering 保持模板体系
- [PASS] Section/方向/页边距 保持模板体系
- [PASS] Header 保持模板体系
- [PASS] Footer 保持模板体系
- [PASS] settings.xml 保持模板体系
- [PASS] 封面编号、版本与 NUMPAGES 字段正确 — {'文件编号': 'GX-V27-DESI', '版本号': '2.2', '页数': '0'}
- [PASS] TOC 域存在

## 关键指标

- Markdown: 2
- Heading: 4
- 正文段落(非空): 2
- 普通表格: 3
- 复杂表格: 0
- Word 顶层表格: 3
- 图片: 0
- 媒体部件: 180
- 重复媒体: 0
- DOCX 大小(字节): 10900250

## 总结

- PASS: 17
- FAIL: 3
- 结论: **失败**
