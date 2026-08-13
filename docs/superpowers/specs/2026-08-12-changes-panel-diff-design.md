# 改动汇总面板 + 差异视图（Changes Panel & Diff）

- 日期：2026-08-12
- 分支：`feat/ui-interaction-optimization`
- 状态：已批准设计（2026-08-12，基线内容副本方案确认）

## 背景与目标

章节树已有会话改动徽标（新增绿/已修改琥珀），但：
- **已删除文件直接消失**——删完树里就没了，本次删了啥、能否恢复都看不见。
- **徽标只有"有没有"，没有"改了什么"**——没有差异视图，无法对比基线。
- **回滚入口分散且语义误导**——重命名面板的「回滚本次联动」实际 `writer.rollback()` 回滚全部。

本变更新增底部工具面板第 5 个 Tab「改动」，作为会话改动的**单一入口**：按状态分组的文件清单 + 每文件「基线 vs 当前」diff + 每文件恢复/撤销 + 统一回滚。

## 关键决策

- **基线内容副本**：`ContentSnapshot.take()` 打基线时把每个 `.md` 复制到 `<state_dir>/baseline/<rel_path>`。代价是 `.md` 在 `.state/` 多一份副本（纯文本，一般几 MB 内），换来 VCS-free 的准确 diff。
- **已删除从快照 diff 的 deleted 键列出**：恢复走 `ChangeManifest` delete 条目的 `trash_path` 移回。
- **rename 标记为 modified**：diff 基线取旧路径内容；不提供单文件恢复（提示走全局回滚）。
- **「回滚全部会话改动」**：确认后调 `writer.rollback()`，刷新清单；重命名面板「回滚本次联动」文案改指向改动面板。

## 1. 数据层：基线内容副本（`doc_tool/application/content/snapshot.py`）

```python
BASELINE_CONTENT_DIR_NAME = "baseline"  # 相对 <state_dir>/

class ContentSnapshot:
    def take(self, content_root, files) -> None:
        """打基线：记录 size/mtime/sha1 元数据（现状）+ 复制内容到 baseline 目录。"""

    def content_of(self, rel_path) -> Optional[str]:
        """读基线内容副本；缺失（升级前项目/复制失败）返回 None。"""

    def ensure_baseline_content(self, content_root, files) -> None:
        """升级兜底：元数据存在但内容副本缺失的文件补拷（旧项目打开时调用）。"""
```

- 复制失败**不阻断**打基线（跳过，diff 显示「基线内容不可用」）。
- 内容副本与元数据 JSON 一起持久化在项目 `.state/`。

## 2. 纯函数（新模块 `doc_tool/application/content/changes.py`）

无 IO、可单测，与 `tree.py` 同风格：

```python
@dataclass(frozen=True)
class ChangeItem:
    rel_path: str            # 当前路径（rename 后为新路径）
    status: str              # added | modified | deleted
    baseline_rel_path: str   # diff 基线路径（rename 为旧路径，其它同 rel_path）
    trash_path: Optional[str]  # 仅 deleted

def build_change_items(status_map, rename_map, trash_map) -> List[ChangeItem]:
    """status_map 来自 snapshot.diff + overlay_rename_status；rename_map 把
    新路径→旧路径；trash_map 把 deleted 路径→回收站绝对路径。输出按
    (状态序, 自然排序) 稳定排列。"""

def render_unified_diff(old_text, new_text) -> str:
    """difflib.unified_diff(lineterm='\n', n=1)，返回文本；无差异返回空串。"""
```

## 3. 恢复操作（`doc_tool/application/content/writer.py`）

在 `ContentWriter` 上新增（复用既有清单操作）：

```python
def restore_file(self, item, baseline_text=None) -> WriteResult:
    """按 ChangeItem 恢复单个文件：
    - added   → 删除文件 + drop(OP_CREATE, rel_path)
    - deleted → 从 trash_path 移回 + drop(OP_DELETE, rel_path)
    - modified→ 写回 baseline_text + drop(OP_EDIT, rel_path) + 清理 .bak
    （rename 的 modified 不接受 restore_file，调用方走全局回滚）"""
```

`WriteResult.written` 保持既有语义；失败返回 error 文本。

## 4. UI 层（新 `doc_tool/ui/content/changes_panel.py`）

- 顶部：计数行（新增 N · 已修改 N · 已删除 N）+「刷新」+「回滚全部会话改动」（确认弹窗）。
- 中部：`QTreeWidget` 或 `QListWidget` 按状态分组列出文件（复用 `status_icon` 彩色圆点）。
- 右侧：只读 diff 视图（`QPlainTextEdit` + `difflib`），选中已修改项时展示「基线 vs 当前」。
- 底部上下文按钮：撤销新增 / 恢复删除 / 恢复到基线（按所选项状态启用）。
- 接线：`ContentWorkspace._populate_panels` 加第 5 个 Tab「改动」（`Ctrl+5`，主窗口 `_select_content_tab` 名字列表同步）；`_after_write`/`_on_file_saved`/`_on_create_file`/`_on_delete_file`/`_on_clear_markers` 后刷新面板。
- `set_writable` 语义：只读项目隐藏写操作按钮，diff 只读仍可看。

## 5. 范围控制（本变更不做）

- 状态栏/项目条改动计数、任务历史、产物 diff、git 集成——留待后续。
- 「回滚本次联动」文案调整单列（`refactor_panel.py`），不改其行为。

## 6. 测试

- 纯函数（`test_content_operations.py` 追加 `ChangeItemsTests`）：
  - `build_change_items`：added/deleted/rename 映射、排序、trash_path 透传。
  - `render_unified_diff`：有差异输出、无差异空串。
  - `restore_file`：撤销新增删文件、恢复删除移回、恢复修改写回基线并清理条目。
- 基线内容（`test_content_operations.py` 追加 `SnapshotContentTests`）：`take` 复制、`content_of` 读取、缺失返回 None、`ensure_baseline_content` 补拷。
- GUI（`test_gui_services.py` 追加 `ChangesPanelTests`，offscreen）：面板列出改动、点击触发 diff 文本、恢复按钮触发回调。

## 7. 人工验收

1. 编辑并保存 → 改动面板「已修改」计数 +1；选中可见 diff（基线 vs 当前）。
2. 右键新增章节 → 「新增」分组出现；「撤销新增」后文件消失、徽标清空。
3. 删除文件 → 「已删除」分组列出；「恢复删除」后文件回位、徽标清空。
4. 重命名 → 标 modified，diff 基线为旧路径内容。
5. 「回滚全部会话改动」确认后全部清空、回滚能力释放。
6. 只读项目：隐藏写操作按钮，diff 可看。
