# 章节树交互增强（键盘 + 右键补齐 + 删除自动重编号）

- 日期：2026-08-12
- 分支：`feat/ui-interaction-optimization`
- 状态：已批准设计（2026-08-12，M1 改动面板之后）

## 背景与目标

M1 已解决「已删除可见/恢复」。本变更提升章节树日常操作效率：

- **键盘**：Enter 打开、F2 重命名、Del 删除（仅文件节点；只读项目隐藏写操作）。
- **右键补齐**：文件加「在外部编辑器打开 / 复制绝对路径 / 复制 Markdown 引用」；目录加「在文件管理器打开」。
- **删除中间编号**：删除后询问是否把后续同级章节递减重编号（联动更新引用与标题），避免手工重编号。

## 关键决策

- **键盘**用 `QTreeView` 子类 `keyPressEvent`，回调复用现有 `on_open` / `on_rename_file` / `on_delete_file`。
- **复制 Markdown 引用** = `[标题](相对路径)`，标题 = 文件名去掉编号前缀（`tree.py` 新增 `strip_number_prefix`）。
- **重编号级联** = 用 `RefactorService` 对同一原始索引逐个 `compute_rename_plan` + `apply_rename_plan`，**按新编号升序**执行：每步的目标号正好是上一步让出的槽位（或已删除的空槽），避免目标冲突；引用与标题联动更新，写回全部经 `ContentWriter` 可回滚。

## 1. `tree.py` 纯函数

```python
def strip_number_prefix(name: str) -> str:
    """去掉开头的编号段（3.7.5 设备管理 → 设备管理）。"""

def renumber_plan_after_delete(deleted_rel_path: str, files: List[str]) -> List[Tuple[str, str]]:
    """删除中间编号后，返回把后续同级直接子文件递减重编号的 (旧, 新) 列表，
    按新编号升序排列。无编号/末尾删除/深层子文件均不产生重编号。"""
```

## 2. `tree_panel.py`

- `_ChapterTreeView(QTreeView)` 子类：`keyPressEvent` 委托给面板 `_handle_tree_key`（Enter/F2/Del，仅文件节点 + 可写）。
- `_show_context_menu` 重构为 `_context_menu(index) -> QMenu`（可测，不 exec）+ `_show_context_menu` 只负责 `exec`。
- 新回调 `on_open_external(rel_path)` / `on_open_directory(dir_rel_path)`。

## 3. `workspace.py`

- `ChapterTree` 构造补 `on_open_external` / `on_open_directory`，接线 `os.startfile(writer.resolve(...))`。
- `_on_delete_file`：删除成功后若 `renumber_plan_after_delete` 非空 → 询问 → 逐个 `RefactorService.compute+apply` → `_after_write()` 刷新。

## 4. 范围控制（本变更不做）

- 目录节点 Enter 展开/折叠、拖拽移动章节、树内分组拖放 → 留后续。

## 5. 测试

- 纯函数：`strip_number_prefix`、`renumber_plan_after_delete`（中间删除/末尾删除/无编号/忽略深层子文件/新编号升序）。
- GUI：键盘 Enter/F2/Del 触发回调；`_context_menu` 动作齐全且「复制 Markdown 引用」写剪贴板；工作区删除中间编号 → 确认 → 后续章节重编号 + 引用更新。
- 全量 121 + 52 回归。

## 6. 人工验收

1. 树选中文件按 Enter → 打开；F2 → 重命名弹窗；Del → 删除确认。
2. 右键文件：打开 / 在外部编辑器打开 / 复制相对路径 / 复制绝对路径 / 复制 Markdown 引用 / 重命名 / 删除。
3. 右键目录：新增章节 / 在文件管理器打开。
4. 删除 `3.7.5`（目录下还有 3.7.6、3.7.7）→ 询问重编号 → 确认后 3.7.6→3.7.5、3.7.7→3.7.6，引用与标题联动更新，改动面板列出全部 rename。
5. 只读项目：F2/Del/删除重编号 均不可用。
