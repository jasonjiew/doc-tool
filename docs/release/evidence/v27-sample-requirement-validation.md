# requirement 严格校验报告

- 输出: `C:\Users\18098\AppData\Local\Temp\v27-samples-88oenrh7\requirement\output\.tmp-GX-V27-REQU 需求说明书样本(3.8).docx`

## 校验结果

- [PASS] DOCX ZIP 与全部 XML 可解析
- [PASS] Relationship Target 与引用完整
- [PASS] 章节编号、层级与必需资源预检 — 章节条目 1
- [FAIL] 目录/Markdown 与 Word 元素顺序、上下文严格一致 — #6 内容/位置不一致: expected T=(('flowchart TD\nA[导入] --> B[检查]\nB --> C[出稿]',),) (C:\Users\18098\AppData\Local\Temp\v27-samples-88oenrh7\requirement\content\1 样本.md:14); actual I=('4f50badcecc367ca490d29cc24a67b565fda2d5c2107f1412bf2fce34359e35e',) (body[50])
- [PASS] Heading 数量、文本、层级、顺序一致
- [PASS] 正文文本与位置一致
- [FAIL] 普通表格文本一致
- [PASS] 复杂表格 OOXML 一致 — 复杂表格 0
- [FAIL] 图片对象、内容哈希与位置一致
- [PASS] 媒体无重复打包 — media=4, duplicateFiles=0, duplicateBytes=0
- [PASS] document.xml 根节点结构合法
- [PASS] updateFields 仅位于 settings.xml
- [PASS] Styles/Font/Theme 保持模板体系
- [PASS] Numbering 保持模板体系
- [PASS] Section/方向/页边距 保持模板体系
- [PASS] Header 保持模板体系
- [PASS] Footer 保持模板体系
- [PASS] settings.xml 保持模板体系
- [PASS] 封面编号、版本与 NUMPAGES 字段正确 — {'文件编号': 'GX-V27-REQU', '版本号': '3.8', '页数': '0'}
- [PASS] TOC 域存在

## 关键指标

- Markdown: 2
- Heading: 2
- 正文段落(非空): 3
- 普通表格: 2
- 复杂表格: 0
- Word 顶层表格: 1
- 图片: 1
- 媒体部件: 4
- 重复媒体: 0
- DOCX 大小(字节): 207516

## 总结

- PASS: 17
- FAIL: 3
- 结论: **失败**
