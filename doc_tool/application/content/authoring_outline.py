"""Current-buffer navigation and explicitly defined text statistics."""
import re
from doc_tool.domain.markdown_structure import markdown_headings, prose_lines, split_table_row, is_separator_row

COUNT_DEFINITION = '原始/选区字符含空白；正文排除围栏代码、HTML 标记与控制注释；CJK 按字符、ASCII 按字母/数字/下划线连续 token；图按引用、表按分隔行计数。'


def buffer_summary(text, selected=''):
    lines = list(prose_lines(text))
    body = '\n'.join(re.sub(r'<[^>]*>', '', line) for _, line in lines)
    return dict(raw=len(text), selection=len(selected), cjk=len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', body)),
                ascii=len(re.findall(r'[A-Za-z0-9_]+', body)), headings=markdown_headings(text),
                images=len(re.findall(r'!\[[^\]]*\]\([^)]+\)', body)),
                tables=sum(is_separator_row(split_table_row(line.strip())) for _, line in lines if line.strip().startswith('|')))
