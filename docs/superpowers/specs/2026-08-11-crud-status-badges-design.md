# 章节树 CRUD 状态徽标（补齐新增/删除操作）

- 日期：2026-08-11
- 分支：`feat/ui-interaction-optimization`
- 状态：已批准设计（2026-08-11，可视化 mockup 确认）

## 背景与目标

内容工作区目前只有"改/查"能力成型：编辑保存、全局替换、重命名/重编号、搜索/检查/定位；**缺少"新增章节/文件"和"删除文件"**。团队在批量替换/重命名后无法一眼看出本次会话改了哪些文件，也缺少会话级的变更追踪。

本变更补齐新增与删除操作，并在章节树上以**彩色圆点徽标**自动展示三个常驻会话状态：**新增 / 已修改 / 已删除**。"查"不设独立徽标（搜索/筛选/定位本身即查询能力）。

## 关键决策

- **统一事实源**：扩展既有 `ChangeManifest`（会话改动清单）为唯一变更记录，徽标由清单推导，天然持久化并与回滚联动。
- **删除 = 移入回收站**：`<state_dir>/trash/` 镜像相对结构，文件物理移出 `content_root`，Word 合并/校验管线零改动即天然跳过。
- **生命周期**：徽标随清单持久化到项目 `.state/`；回滚或手动"清除标记"后消失。
- **徽标呈现**：`DecorationRole` 返回运行时生成的彩色圆点图标（绿=新增、琥珀=已修改、红=已删除），不引入图标资源文件。

## 1. 数据模型（`doc_tool/application/content/writer.py`）

新增操作类型常量与回收站目录：

- `OP_CREATE = "create"`
- `OP_DELETE = "delete"`
- `TRASH_DIR_NAME = "trash"`（位于 `state_dir` 下）

`ChangeEntry` 扩展一个可选字段：

- `trash_path: Optional[str] = None` —— delete 条目记录回收站内文件的绝对路径；`to_dict`/`from_dict` 同步。

`record()` 去重键维持 `(operation, rel_path)`；同一文件"新建后又编辑"会存 `create`+`edit` 两条，回滚逆序先恢复 edit 备份再删 create 文件，顺序自然成立，无需改动。

## 2. 写操作（`ContentWriter`）

新增两个方法，沿用既有"越界检查 → 原子写 → 记条目"套路：

```python
def create_file(self, rel_path: str, text: str) -> WriteResult:
    """新建文件（越界检查 → 目标已存在则报错 → atomic_write → 记 OP_CREATE）。"""

def delete_file(self, rel_path: str) -> WriteResult:
    """软删除（越界检查 → 不存在则报错 → 移动到 <state_dir>/trash/<rel_path>
    镜像相对结构 → 记 OP_DELETE，trash_path=移动后绝对路径）。"""
```

`rollback()` / `_rollback_entry()` 扩展两条分支：

- `OP_CREATE`：内容文件若存在则删除。
- `OP_DELETE`：回收站文件若存在则移回 `content_root/rel_path`（自动建父目录）。

现有替换/重命名面板的整份回滚（`replace_panel.py:256` / `refactor_panel.py:203`）会自动带上新增/删除的恢复，行为一致。

## 3. 徽标推导（`writer.py` 纯函数）

```python
def manifest_status_map(entries: List[ChangeEntry]) -> Dict[str, str]:
    """按清单推导每文件会话状态：added | modified | deleted。

    优先级：deleted > added > modified。rename 对"新路径"标 modified，
    旧路径不标；create+edit 同文件 → added。纯函数、无 IO、可独立测试。
    """
```

## 4. 章节树 UI（`doc_tool/ui/content/tree_panel.py`）

- `ChapterTreeModel` 增加 `_status: Dict[str, str]`（rel_path → 状态）：
  - `data()` 的 `DecorationRole`：文件节点命中状态时返回圆点图标（新增绿/已修改琥珀），目录节点不标。
  - 圆点用运行时 `QPixmap` 填充圆生成，按颜色缓存，不引入资源文件。
  - 新增 `set_status(map)`；`set_items` 重置模型后保持已设置的 status，两者互不覆盖。
- `ChapterTree` 增加 `set_status_map(map)` 透传。
- 已删除文件物理移出 `content_root`、不在树中，树内只渲染**新增/已修改**两种点；`deleted` 状态保留在 status map，供改动清单/回滚视图展示。

## 5. 右键菜单与工作区接线

`ChapterTree` 不持有 writer/索引，沿用现有 `on_open`/`on_refresh` 回调模式，新增两个回调由 `ContentWorkspace` 接线：

- 目录节点右键 → **新增章节/文件…** → `on_create_file(dir_rel_path)`（目录节点的 `node_id` 即其相对路径前缀，`tree.py:86`）
- 文件节点右键 → **删除**（确认框）→ `on_delete_file(rel_path)`

### `ContentWorkspace`（`doc_tool/ui/content/workspace.py`）

- `on_create_file(dir_rel_path)`：用 `index.all_files()` 与 `next_chapter_rel_path` 算下一个编号 → `writer.create_file` 写 `# 标题` 模板 → `rebuild_file` 刷新索引 → 重建树 → 应用徽标 → `open_file(new_rel_path)` 定位编辑器。
- `on_delete_file(rel_path)`：确认框（提示移入回收站可回滚）→ `writer.delete_file` → `rebuild_file`（文件消失→移除条目，`index.py:134`）→ 重建树 → 应用徽标。
- 新增小助手 `_apply_status_map()`：调用 `tree.set_status_map(manifest_status_map(writer.manifest.entries))`，在**索引就绪、编辑器保存、替换/重命名写回（`_after_write`）、手动刷新（`_rebuild_index`）、增/删操作**共 5 处统一调用，避免散落。
- 树工具栏加 **清除标记** 按钮：确认后 `manifest.clear()`，徽标消失（同时失去本次回滚能力，需在确认文案说明）。

## 6. 自动编号助手（`doc_tool/application/content/tree.py` 纯函数）

```python
def next_chapter_rel_path(dir_rel_path: str, files: List[str], title: str) -> str:
    """返回新章节文件 rel_path：递增最大编号；无兄弟时从目录编号 .1 起；兜底标题。

    1) 取 dir 下兄弟文件名数字前缀 X.Y.Z，取最大 Z 段 +1（如 3.7.3）
    2) 无兄弟且目录名带数字段（3.7 KSOA）→ 3.7.1 起
    3) 兜底：title 直接做文件名
    """
```

## 7. 索引联动

复用 `ContentIndexService.rebuild_file`（`index.py:134`，注释明确"含删除场景：文件消失则移除条目"），新增与删除均无需全量重扫，与现有保存路径一致。

## 8. 测试与验收

### 自动化测试（`scripts/tests/test_content_operations.py`）

- `writer`：create 记 `OP_CREATE`；delete 移入回收站并记 `OP_DELETE`（含 `trash_path`）；回滚能删掉新建文件、能从回收站恢复删除文件。
- `manifest_status_map`：优先级 deleted > added > modified；rename 映射到新路径；create+edit → added；纯 edit → modified。
- `next_chapter_rel_path`：递增最大编号、从目录编号起 .1、兜底标题。
- 树模型 `DecorationRole`：文件节点按状态出圆点，目录节点不出。

### 人工验收清单

1. 编辑保存 → 琥珀点；替换/重命名 → 受影响文件琥珀点；重启项目后徽标仍在。
2. 右键目录「新增章节/文件…」→ 自动编号 → 绿点 → 定位编辑器。
3. 右键文件「删除」→ 移入回收站、树内消失、回滚可恢复。
4. 「清除标记」→ 徽标消失（回滚能力随之清除）。
5. Word 合并/校验天然忽略已删除文件（回收站不在 `content_root`）。

## 影响面

- 主要代码：`writer.py`、`tree.py`、`tree_panel.py`、`workspace.py`。
- 关联：`index.py`（复用 `rebuild_file`）、`replace_panel.py`/`refactor_panel.py`（回滚语义不变）。
- 不改变：文档构建、校验、Word 自动化、项目数据格式、安装位置；不新增运行时依赖。
