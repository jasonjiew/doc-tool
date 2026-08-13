# 章节树 CRUD 状态徽标（补齐新增/删除操作）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在章节树上以彩色圆点徽标展示本次会话"新增/已修改/已删除"的文件，并补齐"新增章节/文件"与"删除"（移入回收站可回滚）两项内容操作。

**Architecture:** 扩展 `ChangeManifest` 为唯一变更记录（新增 `create`/`delete` 两种条目），徽标由清单经纯函数 `manifest_status_map` 推导；删除把文件移入 `<state_dir>/trash/`，`ContentWriter` 新增 `create_file`/`delete_file` 并扩展 `rollback`；章节树 `ChapterTreeModel` 按状态返回运行时绘制的圆点 `QIcon`；右键菜单与工具栏操作由 `ContentWorkspace` 接线执行。

**Tech Stack:** Python 3.10+、PySide6（`QTreeView`/`QAbstractItemModel`/`QPixmap`/`QIcon`）、`unittest`（`scripts/tests/test_content_operations.py`，`python scripts/tests/test_content_operations.py` 直接运行）。

**Design spec:** `docs/superpowers/specs/2026-08-11-crud-status-badges-design.md`

## File Structure

| File | 责任 | 改动 |
|---|---|---|
| `doc_tool/application/content/writer.py` | 写安全/改动清单/回滚 | 加 `OP_CREATE`/`OP_DELETE`/`TRASH_DIR_NAME`；`ChangeEntry.trash_path`；`create_file`/`delete_file`；`rollback` 扩展；新增 `manifest_status_map` |
| `doc_tool/application/content/tree.py` | 章节树纯数据推导 | 新增 `next_chapter_rel_path` |
| `doc_tool/ui/content/tree_panel.py` | 章节树 UI | 模型加状态徽标/`index_for_id`/`set_status`；面板加 `set_status_map`、右键"新增/删除"、工具栏"清除标记" |
| `doc_tool/ui/content/tabs_host.py` | 多标签编辑器 | 新增公开 `close_file` |
| `doc_tool/ui/content/workspace.py` | 工作区协调 | 新增 create/delete/clear 处理与 `_apply_status_map`，5 处接线 |
| `scripts/tests/test_content_operations.py` | 自动化测试 | 新增 4 个测试类 + 若干用例 |

测试运行命令（沿用 `run_tests.py` 的直跑方式）：
```bash
python scripts/tests/test_content_operations.py            # 全量
python scripts/tests/test_content_operations.py <类名> -v  # 单类
```

---

### Task 1: writer.py 数据模型扩展（操作常量 + 回收站目录 + trash_path）

**Files:**
- Modify: `doc_tool/application/content/writer.py:30-91`
- Test: `scripts/tests/test_content_operations.py`（新增 `ChangeManifestSerializationTests` 类）

- [ ] **Step 1: 写失败测试**

在 `scripts/tests/test_content_operations.py` 末尾（`if __name__ == "__main__"` 之前）追加：

```python
class ChangeManifestSerializationTests(unittest.TestCase):
    """改动清单条目 JSON 往返（新增 trash_path 字段必须持久化）。"""

    def test_entry_roundtrip_preserves_trash_path(self):
        from doc_tool.application.content.writer import ChangeEntry, OP_DELETE

        entry = ChangeEntry(
            operation=OP_DELETE,
            rel_path="requirement/第1章/1.1 目的.md",
            trash_path="C:/proj/.state/trash/requirement/第1章/1.1 目的.md",
        )
        restored = ChangeEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.operation, OP_DELETE)
        self.assertEqual(
            restored.trash_path,
            "C:/proj/.state/trash/requirement/第1章/1.1 目的.md",
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `python scripts/tests/test_content_operations.py ChangeManifestSerializationTests -v`
Expected: `AttributeError: 'ChangeEntry' object has no attribute 'trash_path'`（FAIL）

- [ ] **Step 3: 实现扩展**

在 `doc_tool/application/content/writer.py`：

1. 第 27 行附近，`OP_RENAME = "rename"` 之后追加：
```python
# 改动操作类型（create 为新增文件；delete 为移入回收站的软删除）。
OP_CREATE = "create"
OP_DELETE = "delete"

# 回收站目录名（相对项目 .state/ 目录）。
TRASH_DIR_NAME = "trash"
```

2. 把 `ChangeEntry` 改为（新增 `trash_path` 字段，并同步 `to_dict`/`from_dict`）：
```python
@dataclass
class ChangeEntry:
    """改动清单条目。"""

    operation: str  # OP_EDIT | OP_RENAME | OP_CREATE | OP_DELETE
    rel_path: str  # edit 为改动文件；rename 为新路径；delete 为原路径
    backup_path: Optional[str] = None  # .bak 绝对路径（edit 必填，rename 可选）
    original_path: Optional[str] = None  # 原名（仅 rename）
    trash_path: Optional[str] = None  # 回收站内绝对路径（仅 delete）

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "relPath": self.rel_path,
            "backupPath": self.backup_path,
            "originalPath": self.original_path,
            "trashPath": self.trash_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeEntry":
        return cls(
            operation=str(data.get("operation", OP_EDIT)),
            rel_path=str(data.get("relPath", "")),
            backup_path=data.get("backupPath"),
            original_path=data.get("originalPath"),
            trash_path=data.get("trashPath"),
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `python scripts/tests/test_content_operations.py ChangeManifestSerializationTests -v`
Expected: `ok`（1 通过，0 失败）

- [ ] **Step 5: 提交**

```bash
git add doc_tool/application/content/writer.py scripts/tests/test_content_operations.py
git commit -m "$(cat <<'EOF'
feat(content): 改动清单支持 create/delete 条目与回收站路径

新增 OP_CREATE/OP_DELETE 与 TRASH_DIR_NAME，ChangeEntry 增加
trash_path 字段并同步序列化，为新增/删除操作与回滚打底。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 徽标推导纯函数 manifest_status_map

**Files:**
- Modify: `doc_tool/application/content/writer.py`（新增模块函数）
- Test: `scripts/tests/test_content_operations.py`（新增 `ManifestStatusMapTests` 类）

- [ ] **Step 1: 写失败测试**

在 `test_content_operations.py` 末尾追加：

```python
class ManifestStatusMapTests(unittest.TestCase):
    """徽标状态推导：优先级与 rename/create+edit 映射。"""

    def test_status_precedence_and_mapping(self):
        from doc_tool.application.content.writer import (
            ChangeEntry,
            OP_CREATE,
            OP_DELETE,
            OP_EDIT,
            OP_RENAME,
            manifest_status_map,
        )

        entries = [
            ChangeEntry(operation=OP_EDIT, rel_path="a.md", backup_path="x"),
            ChangeEntry(operation=OP_CREATE, rel_path="b.md"),
            ChangeEntry(operation=OP_DELETE, rel_path="c.md", trash_path="t/c.md"),
            ChangeEntry(operation=OP_RENAME, rel_path="d.md", original_path="e.md"),
            # 先 create 后 edit 同一文件 → 仍为 added
            ChangeEntry(operation=OP_CREATE, rel_path="f.md"),
            ChangeEntry(operation=OP_EDIT, rel_path="f.md", backup_path="y"),
            # 先 edit 后 delete 同一文件 → 覆盖为 deleted
            ChangeEntry(operation=OP_EDIT, rel_path="g.md", backup_path="z"),
            ChangeEntry(operation=OP_DELETE, rel_path="g.md", trash_path="t/g.md"),
        ]
        status = manifest_status_map(entries)
        self.assertEqual(status["a.md"], "modified")
        self.assertEqual(status["b.md"], "added")
        self.assertEqual(status["c.md"], "deleted")
        self.assertEqual(status["d.md"], "modified")
        self.assertNotIn("e.md", status)  # rename 旧路径不标（文件已不存在）
        self.assertEqual(status["f.md"], "added")
        self.assertEqual(status["g.md"], "deleted")
```

- [ ] **Step 2: 运行确认失败**

Run: `python scripts/tests/test_content_operations.py ManifestStatusMapTests -v`
Expected: `ImportError: cannot import name 'manifest_status_map'`（FAIL）

- [ ] **Step 3: 实现**

在 `doc_tool/application/content/writer.py` 文件末尾追加：

```python
def manifest_status_map(entries: List[ChangeEntry]) -> Dict[str, str]:
    """按改动清单推导每文件的会话状态：added | modified | deleted。

    优先级 deleted > added > modified：先编辑后删除仍标 deleted；先创建后
    编辑仍标 added。rename 条目只对"新路径"标 modified，旧路径不标（文件
    已不存在）。纯函数、无 IO，供章节树徽标与改动汇总复用。
    """
    status: Dict[str, str] = {}
    for entry in entries:
        if entry.operation == OP_DELETE:
            status[entry.rel_path] = "deleted"
    for entry in entries:
        if entry.operation == OP_CREATE:
            status.setdefault(entry.rel_path, "added")
    for entry in entries:
        if entry.operation in (OP_EDIT, OP_RENAME):
            status.setdefault(entry.rel_path, "modified")
    return status
```

同时把文件顶部 `from typing import List, Optional` 改为 `from typing import Dict, List, Optional`。

- [ ] **Step 4: 运行确认通过**

Run: `python scripts/tests/test_content_operations.py ManifestStatusMapTests -v`
Expected: `ok`

- [ ] **Step 5: 提交**

```bash
git add doc_tool/application/content/writer.py scripts/tests/test_content_operations.py
git commit -m "$(cat <<'EOF'
feat(content): 新增 manifest_status_map 徽标状态推导

按改动清单推导 added/modified/deleted，优先级 deleted>added>modified，
rename 映射到新路径。纯函数，供章节树徽标复用。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: ContentWriter.create_file / delete_file + rollback 扩展

**Files:**
- Modify: `doc_tool/application/content/writer.py:167-308`
- Test: `scripts/tests/test_content_operations.py`（新增 `CreateDeleteTests` 类）

- [ ] **Step 1: 写失败测试**

在 `test_content_operations.py` 末尾追加：

```python
class CreateDeleteTests(unittest.TestCase):
    """任务：新增/删除章节文件 + 回滚恢复。"""

    def setUp(self) -> None:
        self.content_root = make_project(
            {"requirement/第1章 引言/1.1 目的.md": "# 1.1 目的\n原始正文\n"}
        )
        self.project_root = self.content_root.parent
        self.addCleanup(shutil.rmtree, self.content_root, ignore_errors=True)

    def _writer(self):
        from doc_tool.application.content.writer import ContentWriter

        return ContentWriter(
            content_root=self.content_root,
            state_dir=self.project_root / ".state",
        )

    def _read(self, rel):
        return (self.content_root / rel).read_text(encoding="utf-8")

    def test_create_file_writes_and_records(self):
        writer = self._writer()
        result = writer.create_file(
            "requirement/第1章 引言/1.1 新增.md", "# 1.1 新增\n"
        )
        self.assertTrue(result.written)
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 新增.md"), "# 1.1 新增\n"
        )
        writer.manifest.load()
        entry = writer.manifest.entries[-1]
        self.assertEqual(entry.operation, "create")
        self.assertEqual(entry.rel_path, "requirement/第1章 引言/1.1 新增.md")

    def test_create_existing_rejected(self):
        writer = self._writer()
        result = writer.create_file("requirement/第1章 引言/1.1 目的.md", "x")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_create_escape_path_rejected(self):
        writer = self._writer()
        result = writer.create_file("../../evil.md", "x")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_delete_moves_to_trash_and_records(self):
        from pathlib import Path

        writer = self._writer()
        result = writer.delete_file("requirement/第1章 引言/1.1 目的.md")
        self.assertTrue(result.written)
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 目的.md").exists()
        )
        writer.manifest.load()
        entry = writer.manifest.entries[-1]
        self.assertEqual(entry.operation, "delete")
        self.assertIsNotNone(entry.trash_path)
        self.assertTrue(Path(entry.trash_path).exists())
        self.assertTrue(
            Path(entry.trash_path).as_posix().endswith(
                ".state/trash/requirement/第1章 引言/1.1 目的.md"
            )
        )

    def test_delete_missing_rejected(self):
        writer = self._writer()
        result = writer.delete_file("requirement/第1章 引言/不存在.md")
        self.assertFalse(result.written)
        self.assertIsNotNone(result.error)

    def test_rollback_removes_created_file(self):
        writer = self._writer()
        writer.create_file(
            "requirement/第1章 引言/1.1 新增.md", "# 1.1 新增\n"
        )
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 新增.md").exists()
        )
        writer.manifest.load()
        self.assertTrue(writer.manifest.empty)

    def test_rollback_restores_deleted_file(self):
        writer = self._writer()
        writer.delete_file("requirement/第1章 引言/1.1 目的.md")
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertEqual(
            self._read("requirement/第1章 引言/1.1 目的.md"),
            "# 1.1 目的\n原始正文\n",
        )
        writer.manifest.load()
        self.assertTrue(writer.manifest.empty)

    def test_rollback_after_create_then_delete(self):
        """新建→删除同一文件后回滚：文件被恢复为最初不存在状态。"""
        writer = self._writer()
        writer.create_file(
            "requirement/第1章 引言/1.1 新增.md", "# 1.1 新增\n"
        )
        writer.delete_file("requirement/第1章 引言/1.1 新增.md")
        failures = writer.rollback()
        self.assertEqual(failures, [])
        self.assertFalse(
            (self.content_root / "requirement/第1章 引言/1.1 新增.md").exists()
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `python scripts/tests/test_content_operations.py CreateDeleteTests -v`
Expected: `AttributeError: 'ContentWriter' object has no attribute 'create_file'`（FAIL）

- [ ] **Step 3: 实现**

在 `doc_tool/application/content/writer.py`：

1. `ContentWriter.__init__` 增加回收站目录（`_trash_dir`）：
```python
    def __init__(self, content_root: Path, state_dir: Path) -> None:
        self._content_root: Path = Path(content_root).resolve()
        self._manifest = ChangeManifest(state_dir)
        self._trash_dir: Path = Path(state_dir).resolve() / TRASH_DIR_NAME
```

2. 在 `rename` 方法之后、"回滚"段之前，新增两个方法：
```python
    def create_file(self, rel_path: str, text: str) -> WriteResult:
        """新建内容文件（越界/已存在检查 → 原子写 → 记 create 条目）。"""
        try:
            target = _resolve_inside(self._content_root, rel_path)
        except PathOutsideContentError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        if target.exists():
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error="目标已存在：{0}".format(rel_path),
            )
        try:
            atomic_write(target, text)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        self._manifest.record(
            ChangeEntry(operation=OP_CREATE, rel_path=rel_path)
        )
        return WriteResult(
            rel_path=rel_path,
            backup_path=None,
            written=True,
            path=str(target),
        )

    def delete_file(self, rel_path: str) -> WriteResult:
        """软删除：移动文件到 <state_dir>/trash/<rel_path> 并记 delete 条目。

        回收站镜像相对结构防同名冲突；文件移出 contentRoot 后构建/校验
        天然跳过。回滚经 trash_path 恢复。
        """
        try:
            source = _resolve_inside(self._content_root, rel_path)
        except PathOutsideContentError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        if not source.exists():
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error="源文件不存在：{0}".format(rel_path),
            )
        trash_target = self._trash_dir / rel_path
        try:
            trash_target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(trash_target)
        except OSError as exc:
            return WriteResult(
                rel_path=rel_path,
                backup_path=None,
                written=False,
                error=str(exc),
            )
        self._manifest.record(
            ChangeEntry(
                operation=OP_DELETE,
                rel_path=rel_path,
                trash_path=str(trash_target),
            )
        )
        return WriteResult(
            rel_path=rel_path,
            backup_path=None,
            written=True,
            path=str(trash_target),
        )
```

3. `_rollback_entry` 增加两个分支（在 OP_EDIT 分支之后追加）：
```python
        elif entry.operation == OP_CREATE:
            target = _resolve_inside(self._content_root, entry.rel_path)
            if target.exists():
                target.unlink()
        elif entry.operation == OP_DELETE:
            target = _resolve_inside(self._content_root, entry.rel_path)
            if entry.trash_path and Path(entry.trash_path).exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                Path(entry.trash_path).rename(target)
```

- [ ] **Step 4: 运行确认通过**

Run: `python scripts/tests/test_content_operations.py CreateDeleteTests -v`
Expected: 全部 `ok`

- [ ] **Step 5: 提交**

```bash
git add doc_tool/application/content/writer.py scripts/tests/test_content_operations.py
git commit -m "$(cat <<'EOF'
feat(content): ContentWriter 支持新建/软删除并扩展回滚

create_file 原子写并记 create 条目；delete_file 移入 .state/trash/
镜像相对结构并记 trash_path；回滚可删新建文件、从回收站恢复删除文件。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 自动编号纯函数 next_chapter_rel_path

**Files:**
- Modify: `doc_tool/application/content/tree.py`
- Test: `scripts/tests/test_content_operations.py`（在 `ChapterTreeModelTests` 类中追加 3 个用例）

- [ ] **Step 1: 写失败测试**

在 `test_content_operations.py` 的 `ChapterTreeModelTests` 类内、`test_integration_with_index` 之后追加：

```python
    def test_next_number_increments_sibling_max(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = [
            "requirement/第3章/3.7 GXOA/3.7.1 租户管理.md",
            "requirement/第3章/3.7 GXOA/3.7.2 产品管理.md",
            "requirement/第3章/3.7 GXOA/3.7.10 设备管理.md",
        ]
        result = next_chapter_rel_path("requirement/第3章/3.7 GXOA", files, "权限管理")
        self.assertEqual(
            result, "requirement/第3章/3.7 GXOA/3.7.11 权限管理.md"
        )

    def test_next_from_dir_number_when_no_numeric_siblings(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = ["requirement/第3章/3.7 GXOA/概述.md"]
        result = next_chapter_rel_path("requirement/第3章/3.7 GXOA", files, "权限管理")
        self.assertEqual(
            result, "requirement/第3章/3.7 GXOA/3.7.1 权限管理.md"
        )

    def test_next_fallback_title_when_dir_unnumbered(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = ["requirement/第3章/GXOA/概述.md"]
        result = next_chapter_rel_path("requirement/第3章/GXOA", files, "权限管理")
        self.assertEqual(result, "requirement/第3章/GXOA/权限管理.md")

    def test_next_ignores_subdirectory_files_as_siblings(self):
        from doc_tool.application.content.tree import next_chapter_rel_path

        files = ["requirement/第3章/3.7 GXOA/3.7.1 租户管理/3.7.1.1 详情.md"]
        result = next_chapter_rel_path("requirement/第3章/3.7 GXOA", files, "权限管理")
        self.assertEqual(
            result, "requirement/第3章/3.7 GXOA/3.7.1 权限管理.md"
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `python scripts/tests/test_content_operations.py ChapterTreeModelTests -v`
Expected: `ImportError: cannot import name 'next_chapter_rel_path'`（FAIL）

- [ ] **Step 3: 实现**

在 `doc_tool/application/content/tree.py`：

1. 顶部 import 区，把 `import re` 之后加 `from pathlib import Path`。

2. 文件末尾追加：
```python
_NUM_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _numeric_prefix(name: str) -> Optional[tuple]:
    """提取文件名/目录名开头的数字段（如 3.7.10 → (3, 7, 10)），无则 None。"""
    match = _NUM_PREFIX_RE.match(name)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def next_chapter_rel_path(dir_rel_path: str, files: List[str], title: str) -> str:
    """返回新章节文件 rel_path：递增最大兄弟编号；无编号从目录编号 .1 起；兜底标题。

    1) 只统计 dir 下的直接子文件，取数字前缀最大者的最后一段 +1（3.7.2→3.7.3）。
    2) 无编号兄弟时，用目录名数字段起 .1（3.7 GXOA → 3.7.1）。
    3) 目录名也无数字段时，直接用标题做文件名。
    """
    prefix = dir_rel_path + "/"
    max_num: Optional[tuple] = None
    for rel in files:
        if not rel.startswith(prefix):
            continue
        rest = rel[len(prefix):]
        if "/" in rest:
            continue  # 只考虑直接子文件，忽略更深层
        num = _numeric_prefix(Path(rest).stem)
        if num is not None and (max_num is None or num > max_num):
            max_num = num
    if max_num is not None:
        base = list(max_num)
        base[-1] += 1
        number = ".".join(str(part) for part in base)
    else:
        dir_num = _numeric_prefix(dir_rel_path.rsplit("/", 1)[-1])
        number = (
            ".".join(str(part) for part in dir_num) + ".1"
            if dir_num is not None
            else ""
        )
    head = number + " " if number else ""
    return prefix + head + title + ".md"
```

- [ ] **Step 4: 运行确认通过**

Run: `python scripts/tests/test_content_operations.py ChapterTreeModelTests -v`
Expected: 新增 4 个用例全部 `ok`，原有用例仍通过

- [ ] **Step 5: 提交**

```bash
git add doc_tool/application/content/tree.py scripts/tests/test_content_operations.py
git commit -m "$(cat <<'EOF'
feat(content): 新增章节自动编号 next_chapter_rel_path

递增兄弟文件最大数字段，无编号时从目录编号 .1 起，兜底用标题；
只统计直接子文件避免子目录干扰。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 章节树徽标渲染（模型状态 + DecorationRole + 圆点图标）

**Files:**
- Modify: `doc_tool/ui/content/tree_panel.py`
- Test: `scripts/tests/test_content_operations.py`（新增 `ChapterTreeStatusTests` 类）

- [ ] **Step 1: 写失败测试**

在 `test_content_operations.py` 末尾追加：

```python
class ChapterTreeStatusTests(unittest.TestCase):
    """章节树状态徽标渲染（需 PySide6；无显示环境用 offscreen）。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # 自包含：脱离 launcher 环境也能找到 .vendor 里的 PySide6
        vendor = Path(REPO_ROOT) / ".vendor" / "site-packages"
        if vendor.is_dir():
            sys.path.insert(0, str(vendor))
        try:
            from PySide6.QtWidgets import QApplication

            cls._app = QApplication.instance() or QApplication([])
            cls._qt_available = True
        except Exception:
            cls._qt_available = False

    def setUp(self) -> None:
        if not getattr(self, "_qt_available", False):
            self.skipTest("PySide6 不可用")

    def _model(self):
        from doc_tool.application.content.tree import build_tree
        from doc_tool.ui.content.tree_panel import ChapterTreeModel

        items = build_tree(
            [
                "requirement/第3章/3.7 GXOA/3.7.1 租户管理.md",  # added
                "requirement/第3章/3.7 GXOA/3.7.2 产品管理.md",  # modified
                "requirement/第3章/3.7 GXOA/3.7.3 权限管理.md",  # 未标记
            ]
        )
        return ChapterTreeModel(
            items,
            status={
                "requirement/第3章/3.7 GXOA/3.7.1 租户管理.md": "added",
                "requirement/第3章/3.7 GXOA/3.7.2 产品管理.md": "modified",
            },
        )

    def test_decoration_shows_dot_for_marked_files_only(self):
        from PySide6.QtCore import Qt

        model = self._model()
        added = model.index_for_id(
            "requirement/第3章/3.7 GXOA/3.7.1 租户管理.md"
        )
        modified = model.index_for_id(
            "requirement/第3章/3.7 GXOA/3.7.2 产品管理.md"
        )
        unmarked = model.index_for_id(
            "requirement/第3章/3.7 GXOA/3.7.3 权限管理.md"
        )
        self.assertFalse(model.data(added, Qt.ItemDataRole.DecorationRole).isNull())
        self.assertFalse(
            model.data(modified, Qt.ItemDataRole.DecorationRole).isNull()
        )
        self.assertIsNone(
            model.data(unmarked, Qt.ItemDataRole.DecorationRole)
        )

    def test_directory_nodes_have_no_badge(self):
        from PySide6.QtCore import Qt

        model = self._model()
        dir_index = model.index_for_id("requirement/第3章/3.7 GXOA")
        self.assertTrue(dir_index.isValid())
        self.assertIsNone(model.data(dir_index, Qt.ItemDataRole.DecorationRole))
```

- [ ] **Step 2: 运行确认失败**

Run: `python scripts/tests/test_content_operations.py ChapterTreeStatusTests -v`
Expected: `AttributeError: 'ChapterTreeModel' object has no attribute 'index_for_id'`（FAIL）

- [ ] **Step 3: 实现**

在 `doc_tool/ui/content/tree_panel.py`：

1. import 区，把 `from PySide6.QtGui import QAction, QCursor` 改为：
```python
from PySide6.QtGui import QAction, QCursor, QColor, QIcon, QPainter, QPixmap
```
并新增 `from functools import lru_cache`。

2. 在 `ChapterTreeModel` 类之前（`_ROOT = ""` 附近之上）加模块级图标工厂：
```python
_STATUS_COLORS = {"added": "#1a9c5b", "modified": "#c98a12"}


@lru_cache(maxsize=None)
def status_icon(status: str) -> QIcon:
    """生成指定状态的彩色圆点图标（运行时绘制，不依赖资源文件）。"""
    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_STATUS_COLORS[status]))
    painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    return QIcon(pix)
```

3. `ChapterTreeModel`：
   - `__init__` 签名改为 `def __init__(self, items, parent=None, *, status=None):`，内部 `self.set_items(items, status)`。
   - `set_items` 改为接受 `status`：
```python
    def set_items(self, items: List[TreeItem], status: Optional[Dict[str, str]] = None) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._status = dict(status) if status else {}
        self._by_id: Dict[str, TreeItem] = {
            item.node_id: item for item in self._items
        }
        self._children: Dict[str, List[str]] = defaultdict(list)
        for item in self._items:
            self._children[item.parent_id or self._ROOT].append(item.node_id)
        self._root = self._ROOT
        self.endResetModel()
```
   - `data()` 的 `DecorationRole` 分支改为：
```python
        if role == Qt.ItemDataRole.DecorationRole:
            if item.is_file:
                state = self._status.get(item.rel_path)
                if state in ("added", "modified"):
                    return status_icon(state)
            return None
```
   - 在"辅助"段新增两个方法：
```python
    def index_for_id(self, node_id: str) -> QModelIndex:
        """按 node_id 深度优先构造模型索引；不存在返回无效索引。"""
        return self._find_index(QModelIndex(), node_id)

    def _find_index(self, parent: QModelIndex, node_id: str) -> QModelIndex:
        parent_id = self._node_id(parent)
        for row, child_id in enumerate(self._children.get(parent_id, [])):
            index = self.createIndex(row, 0, child_id)
            if child_id == node_id:
                return index
            if self.rowCount(index) > 0:
                found = self._find_index(index, node_id)
                if found.isValid():
                    return found
        return QModelIndex()

    def set_status(self, status: Dict[str, str]) -> None:
        """更新徽标状态并重绘受影响文件节点（不重置模型/不折叠展开）。"""
        self._status = dict(status)
        for item in self._items:
            if not item.is_file:
                continue
            index = self.index_for_id(item.node_id)
            if index.isValid():
                self.dataChanged.emit(
                    index, index, [Qt.ItemDataRole.DecorationRole]
                )
```

4. `ChapterTree`：新增 `_status_map` 字段与 `set_status_map`，`_apply_filter` 透传 status：
   - `__init__` 中 `self._visible_items: List[TreeItem] = []` 之后加 `self._status_map: Dict[str, str] = {}`
   - `set_items` 不变（仍 `self._apply_filter(...)`）
   - `_apply_filter` 的模型调用改为：
```python
        self._model.set_items(self._visible_items, status=self._status_map)
```
   - 新增：
```python
    def set_status_map(self, status_map: Dict[str, str]) -> None:
        """设置徽标状态映射并重建可见节点（配合 set_items 使用）。"""
        self._status_map = dict(status_map)
        self._apply_filter(self._filter_entry.text())
```

- [ ] **Step 4: 运行确认通过**

Run: `python scripts/tests/test_content_operations.py ChapterTreeStatusTests -v`
Expected: 2 个用例 `ok`

- [ ] **Step 5: 提交**

```bash
git add doc_tool/ui/content/tree_panel.py scripts/tests/test_content_operations.py
git commit -m "$(cat <<'EOF'
feat(ui): 章节树按会话状态渲染彩色圆点徽标

ChapterTreeModel 接受 status 映射并在 DecorationRole 返回运行时绘制
的圆点图标；新增 index_for_id/set_status；ChapterTree 透传 set_status_map。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 章节树右键"新增/删除" + 工具栏"清除标记"

**Files:**
- Modify: `doc_tool/ui/content/tree_panel.py`

- [ ] **Step 1: 实现（无独立服务测试，交互经回调由 Task 7 覆盖）**

1. `ChapterTree.__init__` 签名改为：
```python
    def __init__(
        self,
        *,
        on_open: Optional[Callable[[str], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_create_file: Optional[Callable[[str], None]] = None,
        on_delete_file: Optional[Callable[[str], None]] = None,
        on_clear_markers: Optional[Callable[[], None]] = None,
        writable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
```
并在 `self._on_refresh = on_refresh` 之后新增：
```python
        self._on_create_file = on_create_file
        self._on_delete_file = on_delete_file
        self._on_clear_markers = on_clear_markers
```

2. 工具栏加"清除标记"按钮（在 `toolbar.addStretch(1)` 之后、"刷新"按钮创建之前插入）：
```python
        self._clear_btn = QPushButton("清除标记", self)
        self._clear_btn.setProperty("btnRole", "compact")
        self._clear_btn.clicked.connect(
            lambda: self._on_clear_markers and self._on_clear_markers()
        )
        toolbar.addWidget(self._clear_btn)
```

3. `set_writable` 改为同时控制清除按钮显隐：
```python
    def set_writable(self, writable: bool) -> None:
        self._writable = writable
        self._clear_btn.setVisible(writable)
```

4. 重写 `_show_context_menu`（目录节点出"新增"，文件节点出"打开/复制/删除"，写操作仅在可写时显示）：
```python
    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        node_id = index.internalPointer()
        item = self._model.item_for(node_id)
        if item is None:
            return
        menu = QMenu(self)
        if item.is_file:
            rel_path = item.rel_path
            open_action = QAction("打开", menu)
            open_action.triggered.connect(
                lambda: self._on_open and self._on_open(rel_path)
            )
            menu.addAction(open_action)
            copy_action = QAction("复制相对路径", menu)
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(rel_path)
            )
            menu.addAction(copy_action)
            if self._writable:
                menu.addSeparator()
                delete_action = QAction("删除", menu)
                delete_action.triggered.connect(
                    lambda: self._on_delete_file and self._on_delete_file(rel_path)
                )
                menu.addAction(delete_action)
        elif self._writable and item.parent_id is not None:
            # 目录节点（非类型根）→ 新增章节/文件
            create_action = QAction("新增章节/文件…", menu)
            create_action.triggered.connect(
                lambda: self._on_create_file and self._on_create_file(item.node_id)
            )
            menu.addAction(create_action)
        menu.exec(QCursor.pos())
```

- [ ] **Step 2: 冒烟运行确认导入无错**

Run: `PYTHONPATH=.vendor/site-packages python -c "from doc_tool.ui.content import tree_panel"`
Expected: 无输出（导入成功，无语法/导入错误）

- [ ] **Step 3: 提交**

```bash
git add doc_tool/ui/content/tree_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): 章节树右键新增/删除与工具栏清除标记

目录节点右键「新增章节/文件…」，文件节点右键「删除」；工具栏新增
「清除标记」；写操作仅在可写时显示，经回调由工作区执行。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 工作区接线（create/delete/clear + _apply_status_map + TabsHost.close_file）

**Files:**
- Modify: `doc_tool/ui/content/workspace.py`
- Modify: `doc_tool/ui/content/tabs_host.py`

- [ ] **Step 1: 实现 TabsHost.close_file**

在 `doc_tool/ui/content/tabs_host.py` 的 `close_all` 方法后新增公开方法：
```python
    def close_file(self, rel_path: str) -> None:
        """关闭指定文件的标签（删除文件时清理已打开标签）。"""
        self._close_tab_by_path(rel_path)
```

- [ ] **Step 2: 实现 workspace 接线**

在 `doc_tool/ui/content/workspace.py`：

1. `ChapterTree` 构造处（`self._tree = ChapterTree(...)`）补充回调：
```python
        self._tree = ChapterTree(
            on_open=self._on_tree_open,
            on_refresh=self._rebuild_index,
            on_create_file=self._on_create_file,
            on_delete_file=self._on_delete_file,
            on_clear_markers=self._on_clear_markers,
            writable=self._writable,
        )
```

2. 新增徽标刷新助手（放 `_rebuild_index` 附近）：
```python
    def _apply_status_map(self) -> None:
        """从改动清单重推会话状态并应用到章节树徽标。"""
        from doc_tool.application.content.writer import manifest_status_map

        self._writer.manifest.load()
        self._tree.set_status_map(
            manifest_status_map(self._writer.manifest.entries)
        )
```

3. 在 5 处写/刷后调用 `_apply_status_map()`：
   - `_populate_panels`：`self._tree.set_items(items)` 之后加 `self._apply_status_map()`
   - `_on_file_saved`：`rebuild_file` 之后加 `self._apply_status_map()`
   - `_after_write`：`self._tree.set_items(items)` 之后加 `self._apply_status_map()`
   - `_rebuild_index`：`self._tree.set_items(items)` 之后加 `self._apply_status_map()`

4. 新增三个操作处理（放在"写后联动"段，`_after_write` 之前）：
```python
    # --- 新增/删除/清除标记 ---

    def _on_create_file(self, dir_rel_path: str) -> None:
        """在指定目录自动编号新建章节文件并定位到编辑器。"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from doc_tool.application.content.tree import next_chapter_rel_path

        if self._index is None:
            return
        title, ok = QInputDialog.getText(self, "新增章节/文件", "章节标题：")
        if not ok or not title.strip():
            return
        title = title.strip()
        rel_path = next_chapter_rel_path(
            dir_rel_path, self._index.all_files(), title
        )
        result = self._writer.create_file(rel_path, "# {0}\n".format(title))
        if not result.written:
            QMessageBox.warning(
                self, "新增失败", result.error or "写入失败"
            )
            return
        self._index_service.rebuild_file(self._index, rel_path)
        items = build_tree(self._index.all_files())
        self._tree.set_items(items)
        self._apply_status_map()
        self.open_file(rel_path)

    def _on_delete_file(self, rel_path: str) -> None:
        """确认后把文件移入回收站并刷新树与索引。"""
        from PySide6.QtWidgets import QMessageBox

        if self._index is None:
            return
        answer = QMessageBox.question(
            self,
            "删除文件",
            "将删除并移入回收站（可回滚）：\n{0}\n\n确认？".format(rel_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self._writer.delete_file(rel_path)
        if not result.written:
            QMessageBox.warning(
                self, "删除失败", result.error or "删除失败"
            )
            return
        self.tabs_host.close_file(rel_path)
        self._index_service.rebuild_file(self._index, rel_path)
        items = build_tree(self._index.all_files())
        self._tree.set_items(items)
        self._apply_status_map()

    def _on_clear_markers(self) -> None:
        """清除全部会话改动标记（同时失去本次回滚能力）。"""
        from PySide6.QtWidgets import QMessageBox

        self._writer.manifest.load()
        if self._writer.manifest.empty:
            return
        answer = QMessageBox.question(
            self,
            "清除标记",
            "清除全部会话改动标记？\n（同时失去本次回滚能力，改动内容保留）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._writer.manifest.clear()
        self._apply_status_map()
```

- [ ] **Step 3: 冒烟运行确认导入无错**

Run: `cd doc-tool && python -c "from doc_tool.ui.content import workspace, tabs_host"`
Expected: 无输出（导入成功）

- [ ] **Step 4: 提交**

```bash
git add doc_tool/ui/content/workspace.py doc_tool/ui/content/tabs_host.py
git commit -m "$(cat <<'EOF'
feat(ui): 工作区接线新增/删除/清除标记并统一刷新徽标

ContentWorkspace 处理 create/delete/clear 回调，经 ContentWriter +
索引重建后由 _apply_status_map 统一重推徽标；TabsHost 增加 close_file。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 全量回归与人工验收

**Files:**
- 无新增改动（仅运行）

- [ ] **Step 1: 运行内容操作全量测试**

Run: `python scripts/tests/test_content_operations.py`
Expected: 全部通过（原有 + 新增用例），`OK` 结尾，0 失败

- [ ] **Step 2: 运行 GUI 服务回归（确认工作区改动无回归）**

Run: `python scripts/tests/test_gui_services.py`
Expected: 全部通过

- [ ] **Step 3: 人工验收清单（在真实项目 `python -m doc_tool.app` 验证）**

1. 编辑保存 → 该文件琥珀点；替换/重命名 → 受影响文件琥珀点；重启项目后徽标仍在。
2. 右键目录「新增章节/文件…」→ 自动编号 → 绿点 → 自动定位到编辑器（内容为 `# 标题`）。
3. 右键文件「删除」→ 确认 → 树内消失、文件进入 `<state_dir>/trash/`；「回滚本次替换/重命名」可恢复。
4. 删除当前正打开的文件 → 对应标签被关闭，无残留。
5. 工具栏「清除标记」→ 确认后徽标全部消失（再次操作「回滚」无内容可回滚）。
6. 只读项目：右键无「新增/删除」、工具栏无「清除标记」。
7. Word 合并/校验忽略已删除文件（回收站不在 content_root）。

- [ ] **Step 4: 提交遗留未提交内容（如验收发现修复）**

如有修复，单独提交并注明；无则跳过。

---

## Self-Review

**Spec coverage:**
- 数据模型（spec §1）→ Task 1
- 写操作 create/delete/rollback（spec §2）→ Task 3
- 徽标推导 manifest_status_map（spec §3）→ Task 2
- 树 UI 徽标（spec §4）→ Task 5
- 右键菜单与工作区接线（spec §5）→ Task 6、7
- 自动编号 next_chapter_rel_path（spec §6）→ Task 4
- 索引联动 rebuild_file（spec §7）→ Task 7（`_on_create_file`/`_on_delete_file` 用 `rebuild_file`）
- 自动化测试（spec §8）→ Task 1-5 各含测试；人工验收 → Task 8
- `TabsHost.close_file` 是 spec 未显式列出的补充（删除打开文件时清理标签），已在 Task 7 实现。

**Placeholder scan:** 无 TBD/TODO；每个代码步骤都含完整可粘贴代码与运行命令。

**Type consistency:** `status_icon(state)`、`set_status(map)`、`set_status_map(map)`、`set_items(items, status=None)`、`ChapterTreeModel(items, status=...)`、`index_for_id`、`manifest_status_map(entries)`、`next_chapter_rel_path(dir, files, title)`、`create_file`/`delete_file` 在各任务间签名一致。`_status_colors` 键与 `data()` 判定（`added`/`modified`）一致。
