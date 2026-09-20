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
3. 管线在项目锁内把它同步到 ``ProjectManifest.documentVersion``（封面「版本号」、
   页眉「版次」与输出文件名随之更新），同步时按
   ``paths.normalize_document_version`` 去掉 ``V`` 前缀——表格里历史行惯用
   ``V3.8``，而这三处一律是纯数字 ``3.8``；表格内容本身不被改写；
4. 构建内核 ``build_docx.update_revision_record`` 用该文件的数据行整表覆盖
   Word 模板里的修订记录表。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tool.application.content.changes import ChangeItem
from doc_tool.application.content.writer import atomic_write
from doc_tool.domain.paths import normalize_document_version

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

    该版本号会成为 ``documentVersion``，进而进入封面「版本号」、页眉「版次」
    与输出文件名，因此不能为空，也不能包含换行或 ``|``（那说明表格行被写坏
    了）。版本号的具体格式仍由项目清单的既有校验规则约束；这里只做最小安全
    校验，并按 ``normalize_document_version`` 去掉 ``V`` 前缀——修订记录表里
    历史行惯用 ``V3.8``，而封面/页眉/文件名一律是纯数字 ``3.8``。
    """
    version = str(value).strip()
    if not version:
        raise ValueError("版本号不能为空。")
    if "|" in version or "\n" in version or "\r" in version:
        raise ValueError("版本号不能包含竖线或换行。")
    version = normalize_document_version(version)
    if not version:
        raise ValueError("版本号不能为空。")
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


def _split_markdown_table_row(line: str) -> List[str]:
    r"""将 Markdown 表格行按未转义的管道符 `|` 分割为单元格，保留 `\|` 转义与末尾空列。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells: List[str] = []
    current: List[str] = []
    escaped = False
    for ch in s:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            current.append(ch)
            escaped = True
        elif ch == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


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
        cells = _split_markdown_table_row(line)
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


# ---------------------------------------------------------------------------
# 自动赋值章节文档超链接 (Autolink)
# ---------------------------------------------------------------------------


def safe_markdown_url(rel_path: str, is_dir: bool = False) -> str:
    """把章节相对路径编码为对 Markdown 链接安全的 URL（保留中文表意文字，转义空格与括号）。"""
    posix_path = rel_path.replace("\\", "/")
    if is_dir and not posix_path.endswith("/"):
        posix_path += "/"
    return posix_path.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _normalize_cjk_token(s: str) -> str:
    """归一化 CJK 文本标点与空白，增强全半角斜杠/括号/空格的模糊匹配能力。"""
    s = s.replace("／", "/").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", s)


def _chinese_to_int(s: str):
    """将中文数字（一至九百九十九）或纯阿拉伯数字字符串解析为整数。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    cn_digits = {
        "零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3,
        "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
        "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
    }
    val = 0
    temp = 0
    for ch in s:
        if ch in cn_digits:
            temp = cn_digits[ch]
        elif ch in ("百", "佰"):
            val += (temp if temp != 0 else 1) * 100
            temp = 0
        elif ch in ("十", "拾"):
            val += (temp if temp != 0 else 1) * 10
            temp = 0
        else:
            return None
    val += temp
    return val if (val > 0 or s == "零") else None


class SectionCatalog:
    """章节与文档目录树快速检索索引。

    扫描 content_root 下全部文档及子目录，构建全名、章节编号、去空格标题的多级索引，
    供修订记录自动赋值超链接时进行稳定定位。
    """

    def __init__(self, content_root: Path) -> None:
        self.root = Path(content_root).resolve()
        self.exact_map: Dict[str, str] = {}
        self.num_map: Dict[str, str] = {}
        self.num_entry_map: Dict[str, Tuple[str, str, str]] = {}
        self.chap_map: Dict[str, str] = {}
        self.title_map: Dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        import os

        if not self.root.is_dir():
            return
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = Path(dirpath).relative_to(self.root)
            for d in dirnames:
                if d.startswith("."):
                    continue
                rel_d = (rel_dir / d).as_posix()
                index_cand = None
                for idx_name in ("_index.md", "_index.markdown"):
                    if (Path(dirpath) / d / idx_name).is_file():
                        index_cand = idx_name
                        break
                if index_cand:
                    d_url = safe_markdown_url(rel_d + "/" + index_cand, is_dir=False)
                else:
                    d_url = safe_markdown_url(rel_d, is_dir=True)
                self.exact_map[d] = d_url
                self.exact_map[d.replace(" ", "")] = d_url
                self.exact_map[_normalize_cjk_token(d)] = d_url
                if index_cand:
                    self.exact_map[safe_markdown_url(rel_d, is_dir=True)] = d_url
                m_ch = re.match(r"^(第?\s*([0-9一二三四五六七八九十百]+)\s*[章节])(?:\s+(.+))?", d)
                if m_ch:
                    cn_val = _chinese_to_int(m_ch.group(2))
                    if cn_val is not None:
                        ch_num = str(cn_val)
                        ch_key = "第{0}章".format(ch_num)
                        self.chap_map[ch_key] = d_url
                        self.chap_map[ch_num] = d_url
                        self.chap_map[d] = d_url
                        self.chap_map[d.replace(" ", "")] = d_url
                        self.num_map.setdefault(ch_num, d_url)
                        self.num_entry_map.setdefault(ch_num, (m_ch.group(3) or "", d_url, d))
                        if m_ch.group(3):
                            ch_title = m_ch.group(3)
                            self.exact_map[ch_title] = d_url
                            self.exact_map[ch_title.replace(" ", "")] = d_url
                            self.exact_map[_normalize_cjk_token(ch_title)] = d_url
                            self.title_map[_normalize_cjk_token(ch_title)] = d_url
                            full_k1 = "{0} {1}".format(ch_key, ch_title)
                            self.chap_map[full_k1] = d_url
                            self.chap_map[full_k1.replace(" ", "")] = d_url
                            raw_k = "{0} {1}".format(m_ch.group(1), ch_title)
                            self.chap_map[raw_k] = d_url
                            self.chap_map[raw_k.replace(" ", "")] = d_url
                else:
                    m_top = re.match(r"^(\d+)(?:\s+(.+))?$", d)
                    if m_top:
                        ch_num = str(int(m_top.group(1)))
                        ch_key = "第{0}章".format(ch_num)
                        ch_title = m_top.group(2) or ""
                        self.chap_map[ch_key] = d_url
                        self.chap_map[ch_num] = d_url
                        self.chap_map[d] = d_url
                        self.chap_map[d.replace(" ", "")] = d_url
                        self.num_map.setdefault(ch_num, d_url)
                        self.num_entry_map.setdefault(ch_num, (ch_title, d_url, d))
                        if ch_title:
                            self.exact_map[ch_title] = d_url
                            self.exact_map[ch_title.replace(" ", "")] = d_url
                            self.exact_map[_normalize_cjk_token(ch_title)] = d_url
                            self.title_map[_normalize_cjk_token(ch_title)] = d_url
                            full_k2 = "{0} {1}".format(ch_key, ch_title)
                            self.chap_map[full_k2] = d_url
                            self.chap_map[full_k2.replace(" ", "")] = d_url
                m_num = re.match(r"^(\d+(?:\.\d+)+)(?:\s+(.+))?", d)
                if m_num:
                    num = m_num.group(1)
                    title = m_num.group(2) or ""
                    self.num_map[num] = d_url
                    self.num_entry_map[num] = (title, d_url, d)
                    if title:
                        self.exact_map[title] = d_url
                        self.exact_map[title.replace(" ", "")] = d_url
                        self.exact_map[_normalize_cjk_token(title)] = d_url
                        self.title_map[_normalize_cjk_token(title)] = d_url

            for f in filenames:
                if not f.endswith(_MD_SUFFIXES) or Path(f).name in _REVISION_RECORD_NAMES:
                    continue
                rel_f = (rel_dir / f).as_posix()
                f_url = safe_markdown_url(rel_f, is_dir=False)
                stem = Path(f).stem
                self.exact_map[stem] = f_url
                self.exact_map[stem.replace(" ", "")] = f_url
                self.exact_map[_normalize_cjk_token(stem)] = f_url
                m_ch_f = re.match(r"^(第?\s*([0-9一二三四五六七八九十百]+)\s*章)(?:\s+(.+))?", stem)
                if m_ch_f:
                    cn_val = _chinese_to_int(m_ch_f.group(2))
                    if cn_val is not None:
                        ch_num = str(cn_val)
                        ch_key = "第{0}章".format(ch_num)
                        self.chap_map.setdefault(ch_key, f_url)
                        self.chap_map.setdefault(ch_num, f_url)
                        self.num_map.setdefault(ch_num, f_url)
                        self.num_entry_map.setdefault(ch_num, (m_ch_f.group(3) or "", f_url, stem))
                else:
                    m_top_f = re.match(r"^(\d+)(?:\s+(.+))?$", stem)
                    if m_top_f:
                        ch_num = str(int(m_top_f.group(1)))
                        ch_key = "第{0}章".format(ch_num)
                        self.chap_map.setdefault(ch_key, f_url)
                        self.chap_map.setdefault(ch_num, f_url)
                        self.num_map.setdefault(ch_num, f_url)
                        self.num_entry_map.setdefault(ch_num, (m_top_f.group(2) or "", f_url, stem))
                m_num = re.match(r"^(\d+(?:\.\d+)+)(?:\s+(.+))?", stem)
                if m_num:
                    num = m_num.group(1)
                    title = m_num.group(2) or ""
                    self.num_map[num] = f_url
                    self.num_entry_map[num] = (title, f_url, stem)
                    if title:
                        self.exact_map[title] = f_url
                        self.exact_map[title.replace(" ", "")] = f_url
                        self.exact_map[_normalize_cjk_token(title)] = f_url
                        self.title_map[_normalize_cjk_token(title)] = f_url

                # 解析 markdown 文件内部定义的子标题（如 ## 3.4.1 蓝牙交互）
                full_f_path = Path(dirpath) / f
                try:
                    with open(full_f_path, "r", encoding="utf-8", errors="ignore") as md_f:
                        for md_line in md_f:
                            m_h = re.match(r"^#{1,6}\s+(.+)$", md_line.strip())
                            if m_h:
                                h_text = m_h.group(1).strip()
                                m_hnum = re.match(r"^(\d+(?:\.\d+)+)(?:\s+(.+))?", h_text)
                                if m_hnum:
                                    h_num = m_hnum.group(1)
                                    h_title = m_hnum.group(2) or ""
                                    frag_url = f_url + "#" + safe_markdown_url(h_text)
                                    self.num_map.setdefault(h_num, frag_url)
                                    self.num_entry_map.setdefault(h_num, (h_title, frag_url, h_text))
                                    if h_title:
                                        self.exact_map.setdefault(h_title, frag_url)
                                        self.title_map.setdefault(_normalize_cjk_token(h_title), frag_url)
                                m_hch = re.match(r"^(第?\s*([0-9一二三四五六七八九十百]+)\s*[章节])(?:\s+(.+))?", h_text)
                                if m_hch:
                                    ch_val = _chinese_to_int(m_hch.group(2))
                                    if ch_val is not None:
                                        ch_k = "第{0}章".format(ch_val)
                                        frag_url = f_url + "#" + safe_markdown_url(h_text)
                                        self.chap_map.setdefault(ch_k, frag_url)
                                        self.chap_map.setdefault(str(ch_val), frag_url)
                                        self.num_map.setdefault(str(ch_val), frag_url)
                                        self.num_entry_map.setdefault(str(ch_val), (m_hch.group(3) or "", frag_url, h_text))
                except Exception:
                    pass

    def find_num_entry(self, num: str) -> Tuple[Optional[str], Optional[Tuple[str, str, str]]]:
        """精确或按最长前缀查找编号对应的章节条目。

        例如输入 4.1.6.4 时，若该小节没有独立 md 文件，则回退查找父小节 4.1.6
        （对应 4.1.6 设备管理.md），保证细化逻辑可跳转到所属上级文档。
        """
        if num in self.num_entry_map:
            return num, self.num_entry_map[num]
        parts = num.split(".")
        if len(parts) == 2 and parts[1] == "0" and parts[0] in self.num_entry_map:
            return parts[0], self.num_entry_map[parts[0]]
        while len(parts) > 1:
            parts.pop()
            p_num = ".".join(parts)
            if p_num in self.num_entry_map:
                return p_num, self.num_entry_map[p_num]
        return None, None

    def resolve(self, token: str) -> Optional[str]:
        t = token.strip()
        if not t:
            return None
        if t in self.exact_map:
            return self.exact_map[t]
        t_nosp = t.replace(" ", "")
        if t_nosp in self.exact_map:
            return self.exact_map[t_nosp]
        norm_t = _normalize_cjk_token(t)
        if norm_t in self.exact_map:
            return self.exact_map[norm_t]
        m_num = re.match(r"^(\d+(?:\.\d+)+)", t)
        if m_num:
            _, entry = self.find_num_entry(m_num.group(1))
            if entry:
                return entry[1]
        m_ch = re.match(r"^(第?\s*([0-9一二三四五六七八九十百]+)\s*[章节])", t)
        if m_ch:
            cn_val = _chinese_to_int(m_ch.group(2))
            ch_k = "第{0}章".format(cn_val) if cn_val is not None else m_ch.group(1).replace(" ", "")
            if ch_k in self.chap_map:
                return self.chap_map[ch_k]
            if cn_val is not None and str(cn_val) in self.chap_map:
                return self.chap_map[str(cn_val)]
        if norm_t in self.title_map:
            return self.title_map[norm_t]
        return None


_STOP_WORDS = frozenset(["等", "各", "及", "和", "与", "包含", "新增", "修改", "删除", "模块", "子模块"])


def link_revision_summary(text: str, catalog: SectionCatalog) -> str:
    """在修订摘要文本中识别章节/小节标题或编号，自动替换为 Markdown 超链接（严格幂等）。"""
    saved_links: List[str] = []

    def _save_link(m: re.Match) -> str:
        saved_links.append(m.group(0))
        return "\x00MDLINK_{0}\x00".format(len(saved_links) - 1)

    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", _save_link, text)

    pattern = re.compile(
        r"(第?\s*[0-9一二三四五六七八九十百]+\s*[章节](?:\s+[^\s\n（\(\)\）\[\]【】<>{}:：，,;；“”\"\'->→。!！?？~]+)?|"
        r"(?<![0-9a-zA-Z\.])\d+(?:\.\d+)+)"
    )

    out: List[str] = []
    pos = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start < pos:
            continue
        out.append(text[pos:start])
        matched_str = match.group(0)

        # 1. 检查是否为章级标题（如 "第4章 WEB端功能设计" 或 "第三章"）
        m_chap = re.match(r"^(第?\s*([0-9一二三四五六七八九十百]+)\s*[章节])(?:\s+(.+))?$", matched_str)
        if m_chap:
            raw_chap = m_chap.group(1)
            cn_digits = m_chap.group(2)
            raw_title = m_chap.group(3)
            num_val = _chinese_to_int(cn_digits)
            ch_k = "第{0}章".format(num_val) if num_val is not None else raw_chap.replace(" ", "")
            if raw_title:
                full_k = raw_chap + " " + raw_title
                url = (
                    catalog.chap_map.get(full_k)
                    or catalog.exact_map.get(_normalize_cjk_token(full_k))
                    or catalog.chap_map.get(ch_k)
                )
                if url:
                    out.append("[{0}]({1})".format(full_k, url))
                    pos = end
                    continue
            url = catalog.chap_map.get(ch_k) or (catalog.chap_map.get(str(num_val)) if num_val is not None else None)
            if url:
                if raw_title:
                    out.append("[{0}]({1}) {2}".format(raw_chap, url, raw_title))
                else:
                    out.append("[{0}]({1})".format(raw_chap, url))
                pos = end
                continue
            out.append(matched_str)
            pos = end
            continue

        # 2. 编号小节匹配（如 4.8.5、10.1、15.1.6、4.1.6.4）
        num = matched_str
        rest_text = text[end:]
        _, entry = catalog.find_num_entry(num)

        if entry:
            known_title, url, stem = entry
            lead_spaces = len(rest_text) - len(rest_text.lstrip(" \t"))
            rest_no_lead = rest_text[lead_spaces:]

            matched_len = 0
            if known_title:
                norm_kt = _normalize_cjk_token(known_title)
                cur_norm = ""
                for i, char in enumerate(rest_no_lead):
                    if char in "\r\n<>[【】":
                        break
                    cur_norm += _normalize_cjk_token(char)
                    if cur_norm == norm_kt:
                        matched_len = lead_spaces + i + 1
                        break
                    elif not norm_kt.startswith(cur_norm):
                        break

            if matched_len > 0:
                full_label = text[start : end + matched_len]
                out.append("[{0}]({1})".format(full_label, url))
                pos = end + matched_len
                continue

            # 别名/短标题前缀匹配（如 3.1呼吸机结果集上传，或 16.16 波形数据Protobuf上传）
            m_chunk = re.match(
                r"^[ \t]*([^\s\n（\(\)\）\[\]【】<>{}:：，,;；“”\"\'->→。!！?？~]+)", rest_text
            )
            if m_chunk:
                chunk = m_chunk.group(1)
                chunk_len = len(m_chunk.group(0))
                if chunk not in _STOP_WORDS and not any(chunk.startswith(sw) for sw in ("各", "等")):
                    norm_c = _normalize_cjk_token(chunk)
                    norm_k = _normalize_cjk_token(known_title)
                    if known_title and (
                        norm_c in norm_k or norm_k in norm_c or (len(norm_c) >= 2 and norm_c[:2] in norm_k)
                    ):
                        full_label = text[start : end + chunk_len]
                        out.append("[{0}]({1})".format(full_label, url))
                        pos = end + chunk_len
                        continue

            out.append("[{0}]({1})".format(num, url))
            pos = end
            continue

        # 3. 容错：若编号未命中（如手写错 4.14证书管理），尝试按紧随其后的标题反查
        m_chunk = re.match(
            r"^[ \t]*([^\s\n（\(\)\）\[\]【】<>{}:：，,;；“”\"\'->→。!！?？~]+)", rest_text
        )
        if m_chunk:
            chunk = m_chunk.group(1)
            chunk_len = len(m_chunk.group(0))
            norm_c = _normalize_cjk_token(chunk)
            if norm_c in catalog.title_map:
                url = catalog.title_map[norm_c]
                full_label = text[start : end + chunk_len]
                out.append("[{0}]({1})".format(full_label, url))
                pos = end + chunk_len
                continue

        out.append(num)
        pos = end

    out.append(text[pos:])
    linked = "".join(out)

    for i, orig in enumerate(saved_links):
        linked = linked.replace("\x00MDLINK_{0}\x00".format(i), orig)
    return linked


def autolink_revision_record_text(
    markdown_text: str,
    content_root: Path,
    target_version: Optional[str] = None,
) -> Tuple[str, int, int]:
    """解析修订记录 Markdown 表格，为修改摘要列自动赋超链接。

    Args:
        markdown_text: 原始修订记录 Markdown 文本
        content_root: 内容根目录（用于建立章节索引）
        target_version: 目标版本号；若为 "latest" 则仅处理末尾最新一行；None 则处理所有数据行。

    Returns:
        (new_markdown_text, updated_rows_count, total_links_count)
    """
    cat = SectionCatalog(content_root)
    lines = markdown_text.splitlines()
    new_lines: List[str] = []
    header_seen = False
    updated_rows = 0
    total_links = 0

    latest_row_idx = None
    if target_version == "latest":
        header_passed = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("|"):
                if re.match(r"^\|[\s\-:|]+\|$", stripped):
                    header_passed = True
                    continue
                if header_passed:
                    cells = _split_markdown_table_row(line)
                    if len(cells) >= 2 and cells[0]:
                        latest_row_idx = idx
            elif header_passed:
                break

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                header_seen = True
                new_lines.append(line)
                continue
            cells = _split_markdown_table_row(line)
            if not header_seen:
                header_seen = True
                new_lines.append(line)
                continue

            if header_seen and len(cells) >= 2:
                ver = cells[0]
                summary = cells[1]

                should_process = True
                if target_version == "latest":
                    should_process = (idx == latest_row_idx)
                elif target_version:
                    norm_ver = ver.strip().lstrip("vV")
                    norm_target = str(target_version).strip().lstrip("vV")
                    should_process = (norm_ver == norm_target)

                if should_process:
                    linked_summary = link_revision_summary(summary, cat)
                    links_in_row = len(re.findall(r"\[[^\]]+\]\([^\)]+\)", linked_summary)) - len(
                        re.findall(r"\[[^\]]+\]\([^\)]+\)", summary)
                    )
                    if linked_summary != summary:
                        updated_rows += 1
                        total_links += max(0, links_in_row)
                        cells[1] = linked_summary
                        new_lines.append("| " + " | ".join(cells) + " |")
                        continue

            new_lines.append(line)
        else:
            new_lines.append(line)

    result_text = "\n".join(new_lines)
    if markdown_text.endswith("\n") and not result_text.endswith("\n"):
        result_text += "\n"
    return result_text, updated_rows, total_links


def autolink_revision_record(
    md_path: Path,
    content_root: Optional[Path] = None,
    target_version: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[int, int, str]:
    """读取文件并为修订记录赋超链接；返回 (更新行数, 新增超链接数, 处理后的全文)。"""
    md_path = Path(md_path).resolve()
    if not md_path.is_file():
        raise FileNotFoundError("修订记录文件不存在: {0}".format(md_path))
    if content_root is None:
        content_root = md_path.parent
    else:
        content_root = Path(content_root).resolve()

    original_text = md_path.read_text(encoding="utf-8")
    new_text, updated_rows, total_links = autolink_revision_record_text(
        original_text, content_root, target_version=target_version
    )
    if updated_rows > 0 and not dry_run:
        atomic_write(md_path, new_text)
    return updated_rows, total_links, new_text
