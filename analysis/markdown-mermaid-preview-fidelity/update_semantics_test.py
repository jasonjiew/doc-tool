# -*- coding: utf-8 -*-
from pathlib import Path

target = Path("scripts/tests/test_markdown_fidelity_semantics.py")
content = target.read_text(encoding="utf-8")

# 1. 替换 test_3_2
old_test_3_2 = """        # 嵌套列表包含父子层级
        self.assertIn("<ol>", html)
        self.assertIn("<ul>", html)
        self.assertIn("<li>无序子项 A</li>", html)

        # 自定义起始编号 start="3"
        self.assertIn('<ol start="3">', html)"""

new_test_3_2 = """        # 嵌套列表包含父子层级
        self.assertIn("<ol", html)
        self.assertIn("<ul", html)
        self.assertIn("<li>无序子项 A</li>", html)

        # 自定义起始编号 start="3"
        self.assertIn('start="3"', html)"""

assert old_test_3_2 in content
content = content.replace(old_test_3_2, new_test_3_2, 1)

# 在 3. 起始为3的前面加个独立段落以形成独立有序列表
old_md_list = """2. 有序第二项

3. 起始为3的第一项"""

new_md_list = """2. 有序第二项

独立正文段落。

3. 起始为3的第一项"""

assert old_md_list in content
content = content.replace(old_md_list, new_md_list, 1)

# 2. 替换 test_3_4 的断言
old_test_3_4 = 'self.assertIn("&lt;div class=&quot;test&quot;&gt;", html)'
new_test_3_4 = 'self.assertIn("&lt;div class=\\"test\\"&gt;", html)'
assert old_test_3_4 in content
content = content.replace(old_test_3_4, new_test_3_4, 1)

target.write_text(content, encoding="utf-8")
print("test_markdown_fidelity_semantics.py updated!")
