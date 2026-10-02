"""Self-contained, saved-content HTML snapshots using the existing renderer."""
import hashlib
import html
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from doc_tool.application.content.index import ContentIndexService, infer_document_type
from doc_tool.application.content.writer import _resolve_inside, atomic_write
from doc_tool.application.content.preview import _IMAGE_RE
from doc_tool.domain.markdown_structure import prose_lines
from doc_tool.application.export.pdf_html import export_html
from doc_tool.domain.version import APP_VERSION


@dataclass
class HtmlSnapshot:
    directory: Path
    status: str
    warnings: list


def export_readonly_html(content_root, assets_root, output_dir, version='', *, rel_path=None,
                         omitted_unsaved=(), cancel_token=None, text_resolver=None,
                         document_assets=False):
    content_root, assets_root = Path(content_root), Path(assets_root)
    preview_root = _resolve_inside(Path(output_dir), 'preview')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    destination = _resolve_inside(preview_root, stamp)
    staging = _resolve_inside(preview_root, '.tmp-' + stamp)
    chapters, sources, warnings = [], [], []
    files = [(rel_path, _resolve_inside(content_root, rel_path))] if rel_path else ContentIndexService(content_root).discover_files()
    try:
        for rel, path in files:
            if cancel_token: cancel_token.check_cancel()
            try:
                path = _resolve_inside(content_root, rel)
                raw = path.read_bytes()
                text = raw.decode('utf-8')
                if text_resolver is not None:
                    # V3.0 3.4：只读 HTML 与出稿同源——先展开固定模块引用再渲染。
                    try:
                        resolved = text_resolver(rel, text)
                    except Exception as exc:  # noqa: BLE001 - 展开失败保留原文并提醒
                        resolved = text
                        warnings.append(dict(path=rel, line=0, message='模块展开失败，保留原文：' + str(exc)))
                    if isinstance(resolved, str) and resolved:
                        text = resolved
            except (OSError, ValueError) as exc:
                warnings.append(dict(path=rel, line=0, message='跳过不可读章节：' + str(exc)))
                continue
            sources.append(dict(path=rel, sha256=hashlib.sha256(raw).hexdigest()))
            allowed = {n for n, _ in prose_lines(text)}
            new_lines = []
            for number, line in enumerate(text.splitlines(keepends=True), 1):
                if number not in allowed:
                    new_lines.append(line)
                    continue
                for match in reversed(list(_IMAGE_RE.finditer(line))):
                    target = match[2]
                    try:
                        base = assets_root if document_assets else _resolve_inside(assets_root, infer_document_type(rel))
                        image = _resolve_inside(base, target)
                        if image.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'):
                            raise ValueError('资源格式不支持静态安全复制')
                        data = image.read_bytes()
                        name = hashlib.sha256(data).hexdigest() + image.suffix.lower()
                        copied = _resolve_inside(staging, 'assets/' + name)
                        copied.parent.mkdir(parents=True, exist_ok=True)
                        copied.write_bytes(data)
                        line = line[:match.start(2)] + 'assets/' + name + line[match.end(2):]
                    except (OSError, ValueError):
                        warnings.append(dict(path=rel, line=number, message='图片缺失/越界或不支持：' + target))
                        # Match excludes closing parenthesis; replace only the resource target
                        # with an inert missing marker, then render a plain explanatory label.
                        end = line.find(')', match.end())
                        end = end + 1 if end >= 0 else match.end()
                        line = line[:match.start()] + '【图片待补：' + match[1] + '】' + line[end:]
                new_lines.append(line)
            chapters.append((rel, ''.join(new_lines)))
        if not chapters: raise ValueError('没有可导出的已保存章节')
        for rel in omitted_unsaved:
            warnings.append(dict(path=rel, line=0, message='导出使用已保存版本，未包含未保存编辑'))
        staging.mkdir(parents=True, exist_ok=True)
        generated = export_html(chapters, staging, 'preview', use_cli=False)
        generated.replace(staging / 'index.html')
        generated.parent.rmdir()
        status = '部分完成' if len(sources) < len(files) else '带提醒完成' if warnings else '完成'
        manifest = dict(schemaVersion=1, kind='readonly-html', appVersion=APP_VERSION,
            documentVersion=version, time=datetime.now(timezone.utc).isoformat(), sources=sources,
            warnings=warnings, status=status, savedContent=True)
        atomic_write(staging / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        doc = (staging / 'index.html').read_text(encoding='utf-8')
        banner = '<p>只读 HTML 内容快照 · 已保存版本 · ' + html.escape(status) + ' · 非正式 Word 发布</p>'
        atomic_write(staging / 'index.html', doc.replace('<main>', '<main>' + banner))
        if cancel_token: cancel_token.check_cancel()
        staging.rename(destination)
        return HtmlSnapshot(destination, status, warnings)
    except BaseException:
        if staging.exists():
            staging.resolve().relative_to(preview_root.resolve())
            shutil.rmtree(staging)
        raise
