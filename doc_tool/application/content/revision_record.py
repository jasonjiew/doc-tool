# -*- coding: utf-8 -*-
"""修订记录：``_revision_record.md`` 是唯一维护点。

纯函数、无 Qt。本模块只做两件事：

- ``build_revision_record``：把改动清单转成「章节 -> 小节」定位清单，供改动
  面板「生成修订记录」弹窗复制，作者据此到 ``_revision_record.md`` 里补写本次
  改了什么。
- 合并期读取：``ensure_revision_record`` 为旧项目从模板初始化该文件，
  ``document_version_from_record`` 取表格末行版本号作为本次文档版本号。

章节/小节标签约定（对齐用户模板，如 ``3.7产品管理->3.7.9呼吸机应用升级``）：
- 小节：文件名去扩展名并去掉所有空格（``3.7.9 呼吸机应用升级`` → ``3.7.9呼吸机应用升级``）。
- 章节：文件所在目录段去空格（``3.7 产品管理`` → ``3.7产品管理``）；``_index.md``
  （父章节自身正文）用目录段同时作章节与小节。

设计取舍：本模块**不再**生成修订记录内容，也不再往该文件写行。机器猜不出
「改了什么」（表格行级启发式推断依赖脆弱的表格解析，产出的又多是「修改列表」
这类零信息量描述，却直接进了正式文档），更不该替作者决定摘要与版本号。合并
前的确认弹窗与自动追加行因此一并撤除：作者手工维护 ``_revision_record.md``
一处，合并只按该文件为准。

合并流程（``_revision_record.md`` 单向流向 Word）：
1. 作者在 ``_revision_record.md`` 表格末尾手工加一行（版本/摘要/日期/修改人）；
2. ``pipeline._prepare_revision_sync`` 只读地取末行版本号；
3. 管线在项目锁内把它同步到 ``ProjectManifest.documentVersion``（封面「版本号」
   与输出文件名随之更新）；
4. 构建内核 ``build_docx.update_revision_record`` 用该文件的数据行整表覆盖
   Word 模板里的修订记录表。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.changes import ChangeItem
from doc_tool.application.content.writer import atomic_write

# 修订记录分组顺序与中文标签（与改动面板 _ITEM_LABELS 一致）。
_STATUS_GROUPS = (
    ("added", "新增"),
    ("modified", "修改"),
    ("deleted", "删除"),
)

_MD_SUFFIXES = (".md", ".markdown")

# 修订记录元数据文件名：不是章节正文，不参与改动摘要。
_REVISION_RECORD_NAMES = ("_revision_record.md", "_revision_record.markdown")

_SEP_CELL_RE = re.compile(r":?-{1,}:?")


# ---------------------------------------------------------------------------
# 路径 → 章节/小节
# ---------------------------------------------------------------------------


def section_labels(rel_path: str) -> Tuple[str, str]:
    """从内容相对路径推导「章节 -> 小节」标签。

    - ``requirement/第3章 功能需求/3.7 产品管理/3.7.9 呼吸机应用升级.md``
      → ``("3.7产品管理", "3.7.9呼吸机应用升级")``
    - ``requirement/第3章 功能需求/3.7 产品管理/_index.md``
      → ``("3.7产品管理", "3.7产品管理")``（父章节自身正文）
    """
    parts = rel_path.split("/")
    stem = Path(parts[-1]).stem
    parent = parts[-2] if len(parts) >= 2 else ""
    label = parent.replace(" ", "")
    if stem == "_index":
        return label, label
    return label, stem.replace(" ", "")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_revision_record(items: Sequence[ChangeItem]) -> str:
    """把改动项列表转成「章节 -> 小节」定位清单（按新增/修改/删除分组）。

    只回答「哪些小节动了」，不猜「改了什么」——语义由作者补写（模块文档已述）。
    非 Markdown 条目（资源、project.yml 等）与修订记录元数据文件不进入清单。
    同一小节重复出现时去重（改名可能同时命中新增/删除组，属预期）。
    """
    groups: Dict[str, List[str]] = {"added": [], "modified": [], "deleted": []}
    for item in items:
        if not item.rel_path.endswith(_MD_SUFFIXES):
            continue
        if Path(item.rel_path).name in _REVISION_RECORD_NAMES:
            continue
        if item.status not in groups:
            continue
        chapter, section = section_labels(item.rel_path)
        head = "{0}->{1}".format(chapter, section)
        if head not in groups[item.status]:
            groups[item.status].append(head)

    lines: List[str] = []
    for status, label in _STATUS_GROUPS:
        entries = groups[status]
        if not entries:
            continue
        lines.append("{0}：".format(label))
        lines.extend(entries)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 版本号校验 / 修订记录文件读写
# ---------------------------------------------------------------------------


def normalize_revision_version(value: str) -> str:
    """校验并规范化修订记录表里的版本号。

    该版本号会成为 ``documentVersion``，进而进入封面「版本号」与输出文件名，
    因此不能为空，也不能包含换行或 ``|``（那说明表格行被写坏了）。版本号的
    具体格式仍由项目清单的既有校验规则约束；这里只做最小安全校验。
    """
    version = str(value).strip()
    if not version:
        raise ValueError("版本号不能为空。")
    if "|" in version or "\n" in version or "\r" in version:
        raise ValueError("版本号不能包含竖线或换行。")
    return version


def ensure_revision_record(
    *,
    md_path: Path,
    template_path: Path,
    document_type: str,
) -> bool:
    """为未迁移的旧项目从模板初始化修订记录 Markdown 文件。

    修订记录是项目元数据，不属于章节正文，因此只在目标文件缺失时创建，
    不覆盖用户已有内容。模板解析复用内核脚本，保证 Markdown 初始表格与
    构建侧 ``update_revision_record`` 使用同一套表格识别规则。
    """
    md_path = Path(md_path)
    template_path = Path(template_path)
    if md_path.exists() or not template_path.is_file():
        return False
    try:
        from doc_tool.adapters.kernel import ensure_kernel_importable

        ensure_kernel_importable()
        from extract_revision_record import extract_revision_rows, rows_to_markdown

        rows = extract_revision_rows(str(template_path))
        if not rows:
            return False
        atomic_write(md_path, rows_to_markdown(rows, document_type))
        return md_path.is_file()
    except Exception:  # noqa: BLE001
        # 旧模板可能没有修订表，初始化失败不能阻断正常合并；调用方会
        # 继续按“修订记录不可用”降级，并保留原有构建能力。
        return False


def _revision_table_rows(md_path: Path) -> Optional[List[List[str]]]:
    """修订记录表的非分隔行单元格矩阵；文件不存在或无 ``|`` 块返回 None。

    表定义与构建侧 ``build_docx._parse_revision_markdown`` 一致：文件中第一个
    连续的 ``|`` 行块。返回值区分「没有表」（None）与「表里还没有数据行」
    （只含表头的列表）——后者说明作者还没写过任何一条修订记录。
    """
    try:
        lines = Path(md_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    table_lines: List[str] = []
    in_table = False
    for line in lines:
        if line.strip().startswith("|"):
            in_table = True
            table_lines.append(line)
        elif in_table:
            break
    if not table_lines:
        return None
    rows: List[List[str]] = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(_SEP_CELL_RE.fullmatch(cell) for cell in cells):
            continue  # 分隔行
        rows.append(cells)
    return rows


def has_revision_table(md_path: Path) -> bool:
    """``_revision_record.md`` 中是否存在修订记录表（允许 0 条数据行）。"""
    return _revision_table_rows(md_path) is not None


def last_revision_version(md_path: Path) -> Optional[str]:
    """修订记录表最后一条数据行的版本列；无表或只有表头返回 None。"""
    rows = _revision_table_rows(md_path)
    if rows is None or len(rows) < 2:
        return None
    return rows[-1][0] if rows[-1] else None


def document_version_from_record(md_path: Path) -> Optional[str]:
    """``_revision_record.md`` 末行版本号，作为本次构建的文档版本号。

    修订记录由作者手工维护，末行即「本次要发布的版本」。返回 None 表示无从
    取值、沿用项目清单里的现有版本号：文件缺失、没有修订记录表、表里还没有
    数据行，或末行版本号为空/含竖线换行（行被写坏）。只读，绝不抛异常——
    版本号取不到不该拦住合并。
    """
    try:
        version = last_revision_version(md_path)
        if version is None:
            return None
        return normalize_revision_version(version)
    except Exception:  # noqa: BLE001
        return None
