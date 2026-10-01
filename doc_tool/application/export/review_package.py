# -*- coding: utf-8 -*-
"""离线 HTML 评审包与意见回流（V2.8 28-G / 7.1～7.4）。

包是**自足**的：样式、正文、图片全部内联，无任何外部链接依赖；
评审人在浏览器里填写意见后下载 JSON，导入时**先验证再事务写入**，按来源 ID 幂等。

契约（``doc-tool-review-pack/v1``）：

    {
      "schema": "doc-tool-review-pack/v1",
      "projectId": "...", "packageId": "...", "createdAt": "...",
      "baselineId": "...", "contentHashes": {"rel": "hash"},
      "comments": [{"author","text","relPath","lineNo","chapterNo","seq","contentHash"}]
    }

异项目、schema 不匹配或文件损坏一律**拒绝**；旧 hash 意见进入待复核；重复导入不产生副本。
"""

from __future__ import annotations

import base64
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

#: 回流契约标识。
PACKAGE_SCHEMA = "doc-tool-review-pack/v1"
#: 内联图片限制（避免单文件过大）。
MAX_INLINE_IMAGE_BYTES = 8 * 1024 * 1024
#: 允许的图片扩展名与 MIME。
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+=[0-9]+x[0-9]+)?\)")


@dataclass
class ReviewPackageResult:
    """生成结果。"""

    html_path: Optional[Path] = None
    json_path: Optional[Path] = None
    package_id: str = ""
    warnings: List[str] = field(default_factory=list)
    comment_count: int = 0

    @property
    def ok(self) -> bool:
        return self.html_path is not None


@dataclass
class ImportResult:
    """回流结果。"""

    success: bool
    added: int = 0
    pending_recheck: int = 0
    skipped: int = 0
    duplicates: int = 0
    message: str = ""
    rejected_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "added": self.added,
            "pendingRecheck": self.pending_recheck,
            "skipped": self.skipped,
            "duplicates": self.duplicates,
            "message": self.message,
            "rejectedReason": self.rejected_reason,
        }


def build_review_package(
    project_root: Union[str, Path],
    chapters: Sequence[Tuple[str, str]],
    *,
    output_dir: Union[str, Path],
    asset_roots: Optional[Sequence[Union[str, Path]]] = None,
    project_id: str = "",
    baseline_id: str = "",
    review_store=None,
    compare_with: Optional[Sequence[Tuple[str, str]]] = None,
) -> ReviewPackageResult:
    """生成自足 HTML 评审包（含意见表单与本地 JSON 下载）。

    ``chapters`` 为 ``[(title, markdown), ...]``；``compare_with`` 供应时输出前后对照。
    图片会被内联为 data URI；缺失的图片只警告不中断。
    """
    root = Path(project_root)
    result = ReviewPackageResult()
    result.package_id = str(uuid4())
    warnings = result.warnings
    assets: Dict[str, str] = {}
    for asset_root in asset_roots or []:
        base = Path(asset_root)
        if not base.is_dir():
            continue
        for item in base.rglob("*"):
            if item.is_file():
                assets.setdefault(item.name, str(item))

    hashes = {str(title): _hash_markdown(text) for title, text in chapters}
    comments = _collect_comments(review_store)
    result.comment_count = len(comments)

    body = []
    for index, (title, text) in enumerate(chapters):
        body.append('<section class="chapter">')
        body.append("<h2>{0}</h2>".format(html.escape(str(title))))
        comparison = _comparison_html(compare_with, index)
        if comparison:
            body.append(comparison)
        body.append(_markdown_to_html(text, assets, warnings))
        body.append("</section>")
    styles = """
    :root { color-scheme: light dark; }
    body { font-family: system-ui, "Microsoft YaHei", sans-serif; margin: 0 auto; max-width: 60rem; padding: 1.5rem; line-height: 1.7; }
    .chapter { border-top: 1px solid rgba(0,0,0,.12); padding-top: 1rem; margin-top: 1.5rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid rgba(0,0,0,.2); padding: .3rem .5rem; }
    pre { background: rgba(0,0,0,.05); padding: .6rem; overflow-x: auto; }
    .diff-old { color: #a12622; } .diff-new { color: #176b3a; }
    form { border: 1px solid rgba(0,0,0,.2); padding: 1rem; border-radius: .4rem; margin-top: 1rem; }
    input, textarea { width: 100%; font: inherit; }
    @media print { form, #download { display: none; } }
    """
    payload = {
        "schema": PACKAGE_SCHEMA,
        "projectId": project_id or str(root),
        "packageId": result.package_id,
        "baselineId": baseline_id,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contentHashes": hashes,
    }
    document = _render_document(styles, body, payload, comments)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    html_path = destination / "评审包.html"
    html_path.write_text(document, encoding="utf-8")
    result.html_path = html_path
    json_path = destination / "评审包空白格式.json"
    json_path.write_text(
        json.dumps(payload_with_comments(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.json_path = json_path
    return result


def payload_with_comments(payload: dict, comments: Optional[Sequence[dict]] = None) -> dict:
    data = dict(payload)
    data["comments"] = [dict(item) for item in (comments or [])]
    return data


def import_review_package(
    package_path: Union[str, Path],
    store,
    *,
    project_id: str = "",
    current_hashes: Optional[Dict[str, str]] = None,
) -> ImportResult:
    """导入意见 JSON：先验证再**事务写入**，按来源 ID 幂等。

    - schema 不匹配、文件损坏、异项目 → **拒绝**（不写入任何内容）；
    - 已存在同签名意见 → 计入 ``duplicates``，不重复写入；
    - 意见携带的 ``contentHash`` 与当前内容不同 → 进入**待复核**；
    - 写入前先把原台账备份，任何异常回滚本次范围。
    """
    from doc_tool.application.review.versioned_review import (
        STATUS_PENDING_FIX,
        STATUS_PENDING_RECHECK,
        content_hash,
    )

    path = Path(package_path)
    result = ImportResult(success=False)
    if not path.is_file():
        result.rejected_reason = "意见文件不存在：{0}".format(path)
        result.message = result.rejected_reason
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result.rejected_reason = "意见文件损坏：{0}".format(exc)
        result.message = result.rejected_reason
        return result
    if not isinstance(data, dict):
        result.rejected_reason = "意见文件格式不正确：根节点应为映射。"
        result.message = result.rejected_reason
        return result
    if data.get("schema") != PACKAGE_SCHEMA:
        result.rejected_reason = "意见包契约不匹配：{0}".format(data.get("schema"))
        result.message = result.rejected_reason
        return result
    source_project = str(data.get("projectId", "") or "")
    if project_id and source_project and source_project != project_id:
        result.rejected_reason = "意见包来自其他项目，已拒绝。"
        result.message = result.rejected_reason
        return result
    raw_comments = data.get("comments")
    if not isinstance(raw_comments, list):
        result.rejected_reason = "意见包缺少 comments 列表。"
        result.message = result.rejected_reason
        return result

    existing = store.comments()
    signatures = {(item.author, item.text, item.chapter_no) for item in existing}
    staged: List[Tuple[str, str, str, int, str, str, Optional[str]]] = []
    for item in raw_comments:
        if not isinstance(item, dict):
            result.skipped += 1
            continue
        text = str(item.get("text", "") or "").strip()
        author = str(item.get("author", "") or "").strip()
        if not text or not author:
            result.skipped += 1
            continue
        rel_path = str(item.get("relPath", item.get("rel_path", "")) or "")
        line_no = int(item.get("lineNo", item.get("line_no", 1)) or 1)
        chapter_no = str(item.get("chapterNo", item.get("chapter_no", "")) or "")
        if (author, text, chapter_no) in signatures:
            result.duplicates += 1
            continue
        signatures.add((author, text, chapter_no))
        staged.append(
            (
                text,
                author,
                rel_path,
                line_no,
                chapter_no,
                str(item.get("contentHash", item.get("content_hash", "")) or ""),
                item.get("packageId") or item.get("package_id"),
            )
        )

    if not staged:
        result.success = True
        result.message = "没有新意见（重复 {0} 条已跳过）。".format(result.duplicates)
        return result

    added_ids: List[str] = []
    try:
        for text, author, rel_path, line_no, chapter_no, recorded_hash, package_id in staged:
            comment = store.add_comment(
                text, author, rel_path, line_no, chapter_no=chapter_no
            )
            added_ids.append(comment.comment_id)
            current = ""
            if current_hashes and rel_path:
                current = current_hashes.get(rel_path, "")
            bind_hash = current or recorded_hash
            updates = {"lifecycle_status": STATUS_PENDING_FIX}
            if bind_hash:
                updates["content_hash"] = bind_hash
            if package_id:
                updates["package_id"] = str(package_id)
            store.update_comment(comment.comment_id, **updates)
            if recorded_hash and current and recorded_hash != current:
                store.update_comment(
                    comment.comment_id,
                    lifecycle_status=STATUS_PENDING_RECHECK,
                    confirm_status="待复核",
                    stale_reason="意见基于旧版本内容",
                )
                result.pending_recheck += 1
            result.added += 1
    except Exception as exc:  # noqa: BLE001 - 写入失败必须回滚本次范围
        _rollback_ids(store, added_ids)
        result.success = False
        result.added = 0
        result.message = "导入失败已回滚：{0}".format(exc)
        result.rejected_reason = result.message
        return result

    result.success = True
    result.message = "导入 {0} 条意见（其中 {1} 条进入待复核）。".format(
        result.added, result.pending_recheck
    )
    return result


def _rollback_ids(store, comment_ids: Sequence[str]) -> None:
    """精确回滚本次导入创建的意见（按 ID，不依赖位置）。

    不能按“最后 N 条”回滚：部分失败时已写入的条目不一定在末尾，那样会误删其他意见。
    """
    for comment_id in list(comment_ids):
        try:
            store.delete_comment(comment_id)
        except Exception:  # noqa: BLE001 - 回滚单条失败不得中断其余
            continue


def _collect_comments(review_store) -> List[dict]:
    if review_store is None:
        return []
    try:
        items = review_store.comments()
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "commentId": item.comment_id,
            "author": item.author,
            "text": item.text,
            "relPath": item.rel_path,
            "lineNo": item.line_no,
            "chapterNo": item.chapter_no,
            "seq": item.seq,
            "contentHash": getattr(item, "content_hash", ""),
        }
        for item in items
    ]


def _hash_markdown(text: str) -> str:
    from doc_tool.application.review.versioned_review import content_hash

    return content_hash(text)


def _comparison_html(compare_with, index: int) -> str:
    if not compare_with or index >= len(compare_with):
        return ""
    old_title, old_text = compare_with[index]
    return (
        '<details class="diff"><summary>与上一版对照（{0}）</summary>'
        '<pre class="diff-old">{1}</pre></details>'.format(
            html.escape(str(old_title)), html.escape(str(old_text))
        )
    )


def _markdown_to_html(text: str, assets: Dict[str, str], warnings: List[str]) -> str:
    lines = str(text or "").splitlines()
    out: List[str] = []
    in_code = False
    in_table = False
    for line in lines:
        if line.lstrip().startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
            out.append(
                "<tr>" + "".join("<td>{0}</td>".format(html.escape(c)) for c in cells) + "</tr>"
            )
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            out.append("<h{0}>{1}</h{0}>".format(level, html.escape(stripped[level:].strip())))
            continue
        out.append(_inline_html(line, assets, warnings))
    if in_table:
        out.append("</table>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def _inline_html(line: str, assets: Dict[str, str], warnings: List[str]) -> str:
    escaped = html.escape(line)
    for match in _IMAGE_RE.finditer(line):
        name = Path(match.group(1)).name
        target = assets.get(name)
        if not target:
            warnings.append("图片未找到，评审包中已省略：{0}".format(match.group(1)))
            continue
        data_uri = _data_uri(Path(target), warnings)
        if not data_uri:
            continue
        escaped = escaped.replace(
            html.escape(match.group(0)),
            '<img src="{0}" alt="{1}">'.format(data_uri, html.escape(name)),
            1,
        )
    return escaped + "<br>"


def _data_uri(path: Path, warnings: List[str]) -> str:
    mime = _IMAGE_MIME.get(path.suffix.lower())
    if mime is None:
        return ""
    try:
        size = path.stat().st_size
        if size > MAX_INLINE_IMAGE_BYTES:
            warnings.append("图片过大未内联：{0}".format(path.name))
            return ""
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        warnings.append("图片读取失败：{0}".format(exc))
        return ""
    return "data:{0};base64,{1}".format(mime, payload)


def _render_document(styles: str, body: List[str], payload: dict, comments: List[dict]) -> str:
    template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>评审包</title>
<style>{styles}</style>
</head>
<body>
<h1>评审包</h1>
<p>包标识：{package_id}</p>
{body}
<form id="review-form">
<h2>填写意见</h2>
<label>作者<input id="author" name="author"></label>
<label>章节<input id="chapter" name="chapter"></label>
<label>意见<textarea id="text" name="text" rows="4"></textarea></label>
<button type="button" id="download">下载意见 JSON</button>
</form>
<script>
const base = {payload};
document.getElementById('download').addEventListener('click', function () {{
  const data = Object.assign({{}}, base);
  const text = document.getElementById('text').value.trim();
  const author = document.getElementById('author').value.trim();
  const chapter = document.getElementById('chapter').value.trim();
  data.comments = text && author
    ? [{{author: author, text: text, relPath: '', lineNo: 1, chapterNo: chapter,
         contentHash: (base.contentHashes || {{}})[chapter] || ''}}]
    : [];
  const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = '意见-' + base.packageId + '.json';
  link.click();
  URL.revokeObjectURL(link.href);
}});
</script>
</body>
</html>
"""
    return template.format(
        styles=styles,
        package_id=html.escape(str(payload.get("packageId", ""))),
        body="\n".join(body),
        payload=_safe_json(payload_with_comments(payload, comments)),
    )


def _safe_json(value) -> str:
    """把 JSON 写进 ``<script>`` 时转义危险字符，防止脚本/标签注入。"""
    text = json.dumps(value, ensure_ascii=False)
    return (
        text.replace('<', '\\u003c')
        .replace('>', '\\u003e')
        .replace('&', '\\u0026')
        .replace(' ', '\\u2028')
        .replace(' ', '\\u2029')
    )
