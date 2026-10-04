# -*- coding: utf-8 -*-
"""MAIN2-C 3.3：所选章节批量复制/移动（复用原服务，逐项结果、取消不写）。

设计要点（不新增第二套章节引擎 / 身份模型）：

- 复制复用 ``refactor.copy_chapter``：新 DOC-ITEM 身份、绝不覆盖、可用活缓冲正文；
- 移动复用 ``refactor.RefactorService.compute_batch_rename_plan``：先在任何文件
  被搬走前算出「章节号 + 链接文件名」引用联动清单，再经原 ``ContentWriter`` 让位
  与落位（可经改动清单回滚），条目身份保持；
- 计划阶段先算出**真实目标**（``旧 → 新``）并在写盘前展示；目标冲突自动改名
  （复制 ``（副本）/（副本N）``、移动 ``（移动）/（移动N）``），绝不覆盖；
- 应用逐项执行：无效项跳过；移动与引用联动作为一份事务，失败时请求整批回滚；
- 计划记录生成时的**操作代次**（``BatchChapterPlan.generation``）：应用时逐项
  核对，代次已前进（项目又写了一轮）时该项标为「已过期」且不写盘，保证为章节 A
  发起的操作不会落到章节 B 上。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.refactor import (
    ChapterCopyResult,
    RefactorService,
    copy_chapter,
)
from doc_tool.application.content.tree import strip_number_prefix

#: 批量操作种类。
BATCH_COPY = "copy"
BATCH_MOVE = "move"
BATCH_KINDS = (BATCH_COPY, BATCH_MOVE)

KIND_LABELS = {BATCH_COPY: "批量复制", BATCH_MOVE: "批量移动"}

#: 自动改名后缀（与手工入口的「（副本）」风格一致）。
COPY_SUFFIX = "（副本）"
MOVE_SUFFIX = "（移动）"

_MAX_SETTLE_PASSES = 8
_MAX_ITEMS = 200


@dataclass
class BatchChapterItem:
    """批量操作的一项：真实来源、目标、结果与可读原因。"""

    source: str
    kind: str = BATCH_COPY
    target: str = ""
    title: str = ""
    ok: bool = False
    message: str = ""
    #: 旧条目 ID -> 新条目 ID（仅复制；证明副本获得独立身份）。
    item_ids: Dict[str, str] = field(default_factory=dict)

    def summary_line(self) -> str:
        if self.ok:
            extra = ""
            if self.kind == BATCH_COPY and self.item_ids:
                extra = "（{0} 个条目新身份）".format(len(self.item_ids))
            if self.message:
                extra += "（{0}）".format(self.message)
            return "{0} → {1}{2}".format(self.source, self.target, extra)
        return "{0}：已跳过（{1}）".format(self.source, self.message or "未知原因")


@dataclass
class BatchChapterPlan:
    """批量计划：真实目标摘要 + 目标目录 + 逐项清单。"""

    kind: str
    dest_dir: str
    items: List[BatchChapterItem] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    #: 生成计划时的操作代次：应用时逐项核对（None 表示不核对）。
    generation: object = None
    #: 计划身份：与调用方代次一起核对，防止晚到请求串章。
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def actionable(self) -> List[BatchChapterItem]:
        return [item for item in self.items if item.ok and item.target]

    @property
    def total(self) -> int:
        return len(self.items)

    def target_lines(self) -> List[str]:
        """写盘前的真实目标摘要：每个所选章节一行 ``旧 → 新``。"""
        lines: List[str] = []
        for item in self.items:
            if item.ok and item.target:
                lines.append("  {0} → {1}".format(item.source, item.target))
            else:
                lines.append(
                    "  {0} → （跳过：{1}）".format(item.source, item.message or "无效项")
                )
        return lines

    def summary_text(self) -> str:
        head = "{0} {1} 个章节到「{2}」".format(
            KIND_LABELS.get(self.kind, self.kind),
            len(self.actionable()),
            self.dest_dir or "（内容根目录）",
        )
        parts = [head, "目标摘要："] + self.target_lines()
        if self.notes:
            parts.append("注意：")
            parts.extend("  " + note for note in self.notes)
        return chr(10).join(parts)

    def result_lines(self) -> List[str]:
        return [item.summary_line() for item in self.items]

    def result_text(self) -> str:
        done = sum(1 for item in self.items if item.ok)
        parts = [
            "{0}完成：{1}/{2} 项成功".format(
                KIND_LABELS.get(self.kind, self.kind), done, self.total
            )
        ]
        parts.extend("  " + line for line in self.result_lines())
        skipped = self.total - done
        if skipped:
            parts.append("跳过 {0} 项（不影响其余项）".format(skipped))
        return chr(10).join(parts)


# --- 路径工具 ---


def _normalized(value: str) -> str:
    return str(value or "").replace(chr(92), "/").strip("/")


def _parent_rel(rel_path: str) -> str:
    parent = Path(_normalized(rel_path)).parent.as_posix()
    return "" if parent == "." else parent


def _join_rel(parent: str, name: str) -> str:
    parent = _normalized(parent)
    return parent + "/" + name if parent else name


def _dir_is_usable(dest_dir: str, files: Sequence[str], content_root=None) -> bool:
    """目标目录必须是内容根或真实存在的目录，杜绝写到内容根之外。"""
    dest = _normalized(dest_dir)
    if not dest:
        return True
    if content_root is not None:
        root = Path(content_root)
        try:
            if not (root / dest).is_dir():
                return False
        except OSError:
            return False
        try:
            (root / dest).resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return False
        return True
    # 无内容根时退化为「既有文件前缀」判定（如空目录尚未建立）。
    prefix = dest + "/"
    return any(rel.startswith(prefix) for rel in files)


def _strip_suffix_marker(stem: str) -> str:
    """去掉 ``（副本）``/``（移动）`` 后缀及其后的递增序号。

    只删除紧跟在标记之后的数字：``Windows 11``、``3.1`` 这类标题自带的数字必须保留。
    """
    for marker in (COPY_SUFFIX, MOVE_SUFFIX):
        index = stem.rfind(marker)
        if index < 0:
            continue
        tail = stem[index + len(marker):]
        if tail.isdigit() or not tail:
            return stem[:index] or stem
    return stem


def _copy_title_of(rel_path: str) -> str:
    """副本正文标题 = 去掉编号段的章节名（编号由原复制服务重新分配）。"""
    stem = Path(rel_path).stem
    return strip_number_prefix(stem) or stem


def _unique_copy_target(dest_dir: str, title: str, occupied: set) -> str:
    """返回复制目标 rel_path：目标已占用时自动改名，绝不覆盖。"""
    candidate = _join_rel(dest_dir, title + ".md")
    step = 0
    while candidate in occupied:
        step += 1
        base = _strip_suffix_marker(title)
        title = "{0}{1}{2}".format(
            base, COPY_SUFFIX, "" if step <= 1 else str(step)
        )
        candidate = _join_rel(dest_dir, title + ".md")
    return candidate


def _unique_move_target(dest_dir: str, name: str, occupied: set, vacated: set) -> str:
    """移动目标：同名占用时自动加「（移动）」，让位链（在本批搬走）不算占用。"""
    candidate = _join_rel(dest_dir, name)
    if candidate not in occupied or candidate in vacated:
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    step = 0
    while candidate in occupied and candidate not in vacated:
        step += 1
        bumped = "{0}{1}{2}{3}".format(
            _strip_suffix_marker(stem) or stem,
            MOVE_SUFFIX,
            "" if step <= 1 else str(step),
            suffix,
        )
        candidate = _join_rel(dest_dir, bumped)
    return candidate


def _index_has(index, rel_path: str) -> bool:
    try:
        return rel_path in index.all_files()
    except Exception:  # noqa: BLE001 - 索引不可读时按不存在处理
        return False


def _index_refresh(index, refresh_index) -> None:
    """让索引读回磁盘现状（跨目录移动后原服务才能算出正确引用联动）。"""
    if refresh_index is not None:
        try:
            refresh_index(index)
            return
        except Exception:  # noqa: BLE001 - 刷新失败退回原索引
            pass
    try:
        service = getattr(index, "service", None)
        if service is not None and hasattr(service, "refresh"):
            service.refresh(index)
    except Exception:  # noqa: BLE001 - 刷新失败不阻断已完成的移动
        pass


# --- 计划 ---


def plan_batch_chapters(
    index,
    sources: Sequence[str],
    kind: str,
    *,
    dest_dir: str = "",
    titles: Optional[Dict[str, str]] = None,
    max_items: int = _MAX_ITEMS,
    content_root=None,
    generation=None,
) -> BatchChapterPlan:
    """生成批量复制/移动计划：真实目标 + 冲突自动改名 + 无效项局部跳过。"""
    kind = str(kind or "").strip().lower()
    if kind not in BATCH_KINDS:
        raise ValueError("不支持的批量章节操作：{0}".format(kind))
    dest_dir = _normalized(dest_dir)
    alias = {_normalized(key): value for key, value in (titles or {}).items()}

    files = list(index.all_files())
    members = set(files)
    occupied = set(files)
    notes: List[str] = []
    if not _dir_is_usable(dest_dir, files, content_root):
        notes.append(
            "目标目录「{0}」不在当前内容范围内，已退回内容根目录".format(dest_dir)
        )
        dest_dir = ""

    wanted = [str(source or "").strip() for source in sources]
    wanted = [source for source in wanted if source]
    limit = max(1, int(max_items))
    if len(wanted) > limit:
        notes.append("一次最多处理 {0} 个章节，其余未纳入本次计划".format(limit))
        wanted = wanted[:limit]

    items: List[BatchChapterItem] = []
    for source in wanted:
        rel = _normalized(source)
        item = BatchChapterItem(source=rel, kind=kind)
        items.append(item)
        if rel not in members:
            item.message = "章节不在当前内容索引中"
            continue
        if kind == BATCH_MOVE:
            if _parent_rel(rel) == dest_dir:
                # 同目录同名是真正的空操作；同目录改名交给下面的目标结算。
                if _unique_move_target(dest_dir, Path(rel).name, occupied, {rel}) == rel:
                    item.message = "已在目标目录中（无需移动）"
                    continue
            if dest_dir == rel or dest_dir.startswith(rel + "/"):
                item.message = "不能移动到自身子目录"
                continue
        item.ok = True

    if kind == BATCH_COPY:
        planned: set = set()
        for item in items:
            if not item.ok:
                continue
            title = str(alias.get(item.source) or "").strip()
            item.title = title or _copy_title_of(item.source)
            item.target = _unique_copy_target(
                dest_dir, _copy_title_of(item.source), occupied | planned
            )
            planned.add(item.target)
    else:
        vacated = {item.source for item in items if item.ok}
        # 结算：同批目标重复时逐轮改名（让位链在本批内搬走不算占用）。
        for _pass in range(_MAX_SETTLE_PASSES):
            planned: set = set()
            for item in items:
                if not item.ok:
                    continue
                item.target = _unique_move_target(
                    dest_dir, Path(item.source).name, occupied | planned, vacated
                )
                planned.add(item.target)
            if len(planned) == sum(1 for item in items if item.ok):
                break
        seen: Dict[str, BatchChapterItem] = {}
        for item in items:
            if not item.ok:
                continue
            if item.target in seen:
                item.ok = False
                item.message = "同批目标重复，已跳过"
                continue
            seen[item.target] = item

    return BatchChapterPlan(
        kind=kind, dest_dir=dest_dir, items=items, notes=notes, generation=generation
    )


# --- 应用 ---


def apply_batch_plan(
    plan: BatchChapterPlan,
    index,
    writer,
    *,
    source_text: Optional[Callable[[str], Optional[str]]] = None,
    generation: Optional[Callable[[], object]] = None,
    on_written: Optional[Callable[[BatchChapterItem], None]] = None,
    refresh_index: Optional[Callable[[object], None]] = None,
) -> List[BatchChapterItem]:
    """应用计划：复制逐项执行；移动与引用联动事务失败时请求整批回滚。

    ``source_text(rel_path)`` 提供当前有效正文（编辑器活缓冲优先），复制时使用；
    ``generation()`` 每项应用前调用，与计划生成时的代次不同则该项标为过期不写。
    """
    if not plan.actionable():
        return []
    # 计划生成时的代次：apply 时逐项核对，晚到请求（代次已前进）一律作废。
    expected_generation = getattr(plan, "generation", None)
    results: List[BatchChapterItem] = []

    def _notify(item) -> None:
        if on_written is not None:
            try:
                on_written(item)
            except Exception:  # noqa: BLE001 - 回调失败不影响已写入结果
                pass

    for item in plan.items:
        if not item.ok or not item.target:
            continue
        if generation is not None and expected_generation is not None:
            if generation() != expected_generation:
                item.ok = False
                item.message = "索引已更新（晚到请求已过期，请重试）"
                results.append(item)
                continue
        if plan.kind == BATCH_COPY:
            _apply_copy(item, index, writer, source_text)
            results.append(item)
            _notify(item)
    if plan.kind == BATCH_MOVE:
        for item in _apply_moves_batch(
            plan, index, writer, refresh_index=refresh_index
        ):
            results.append(item)
            _notify(item)
    return results


def _apply_copy(
    item: BatchChapterItem,
    index,
    writer,
    source_text: Optional[Callable[[str], Optional[str]]],
) -> None:
    body = None
    if source_text is not None:
        try:
            current = source_text(item.source)
            body = None if current is None else str(current)
        except Exception:  # noqa: BLE001 - 缓冲不可读时退回索引内容
            body = None
    try:
        result: ChapterCopyResult = copy_chapter(
            index, item.source, writer, title=item.title, source_text=body
        )
    except Exception as exc:  # noqa: BLE001 - 单项异常不阻断其余项
        item.ok = False
        item.message = "复制失败：{0}".format(exc)
        return
    if not result.ok:
        item.ok = False
        item.message = result.message or "写入失败"
        return
    item.item_ids = dict(result.item_ids)
    # 原复制服务按同目录递增编号落盘；计划目标是用户确认过的真实目标，
    # 不一致时复用原写入服务的改名能力把新章落到该目标（条目身份已重生成）。
    if item.target and item.target != result.target:
        move = _rename_created(writer, result.target, item.target)
        if move:
            item.ok = True
            return
        item.message = "已复制为 {0}（目标 {1} 未能改名）".format(
            result.target, item.target
        )
        item.target = result.target
        item.ok = True
        return
    item.target = result.target
    item.ok = True


def _rename_created(writer, source_rel: str, target_rel: str) -> bool:
    """把刚复制出的新章改名到计划目标；目标不存在时才改名（绝不覆盖）。"""
    if writer.resolve(target_rel).exists():
        return False
    try:
        result = writer.rename(source_rel, target_rel, create_backup=False)
    except Exception:  # noqa: BLE001 - 改名失败保留原复制结果并如实报告
        return False
    return bool(getattr(result, "written", False))


def _apply_moves_batch(
    plan: BatchChapterPlan,
    index,
    writer,
    *,
    refresh_index: Optional[Callable[[object], None]] = None,
) -> List[BatchChapterItem]:
    """复用 RefactorService 的引用改写、让位、落位和失败回滚事务。"""
    items = [item for item in plan.items if item.ok and item.target]
    if not items:
        return []
    # 引用与文件移动复用同一事务；失败时原服务回滚，避免临时文件
    # 或指向失败目标的引用残留。无效项已在计划阶段逐项排除。
    service = RefactorService(index)
    rename_plan = service.compute_batch_rename_plan(
        [(item.source, item.target) for item in items]
    )
    try:
        if rename_plan is None:
            raise ValueError("章节索引已变化，请重新生成计划")
        service.apply_rename_plan(rename_plan, writer)
    except Exception as exc:  # noqa: BLE001 - 保留原章节并报告事务失败
        for item in items:
            item.ok = False
            item.message = "移动事务失败（已请求回滚）：{0}".format(exc)
    _index_refresh(index, refresh_index)
    return items
