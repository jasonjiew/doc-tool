"""Explicit image-reference plans and rollback of only this application."""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from doc_tool.application.content.preview import _IMAGE_RE
from doc_tool.domain.markdown_structure import prose_lines
from doc_tool.application.content.writer import _resolve_inside, atomic_write_bytes


@dataclass
class ReferenceEdit:
    source: str
    line: int
    start: int
    end: int
    old: str
    replacement: str
    source_hash: str
    selected: bool = True


class AssetBatchService:
    def __init__(self, writer, index, *, is_dirty=None):
        self.writer, self.index = writer, index
        self.is_dirty = is_dirty or (lambda _: False)

    def plan(self, missing_target, replacement):
        edits = []
        for rel in self.index.files:
            path = self.writer.resolve(rel)
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            offset = 0
            allowed = {n for n, _ in prose_lines(text)}
            for number, line in enumerate(text.splitlines(keepends=True), 1):
                if number in allowed:
                    for ref in _IMAGE_RE.finditer(line):
                        if ref[2] == missing_target:
                            edits.append(ReferenceEdit(rel, number, offset + ref.start(2), offset + ref.end(2),
                                missing_target, replacement, hashlib.sha256(raw).hexdigest()))
                offset += len(line)
        return edits

    def asset_path(self, source, replacement):
        doc_type = self.index.files[source].document_type
        root = _resolve_inside(self.writer.assets_root, doc_type)
        return _resolve_inside(root, replacement)

    def apply(self, edits, *, confirmed=False, imported=None):
        result = dict(applied=[], skipped=[], refreshed=[], warnings=[])
        if not confirmed: return result
        if not self.writer._writable: raise PermissionError('只读项目不能应用图片修复')
        groups = {}
        for edit in edits:
            if edit.selected: groups.setdefault(edit.source, []).append(edit)
        before = {}
        updated = {}
        for rel, rows in groups.items():
            path = self.writer.resolve(rel)
            raw = path.read_bytes()
            if self.is_dirty(rel) or any(hashlib.sha256(raw).hexdigest() != row.source_hash for row in rows):
                result['skipped'].append(rel)
                for row in rows:
                    result['refreshed'].extend(e for e in self.plan(row.old, row.replacement) if e.source == rel)
                continue
            text = raw.decode('utf-8')
            try:
                for row in rows:
                    target = self.asset_path(rel, row.replacement)
                    if not target.is_file() and (not imported or target not in imported): raise ValueError('选择的资源不存在')
                    if text[row.start:row.end] != row.old: raise ValueError('引用范围已变化')
            except (ValueError, OSError) as exc:
                result['skipped'].append(rel)
                result['warnings'].append(str(exc))
                continue
            before[rel] = raw
            for row in sorted(rows, key=lambda r: r.start, reverse=True):
                text = text[:row.start] + row.replacement + text[row.end:]
            updated[rel] = text
        manifest_path = self.writer.manifest.file
        manifest_before = manifest_path.read_bytes() if manifest_path.exists() else None
        created = []
        written = []
        try:
            needed = {self.asset_path(rel, row.replacement) for rel in updated for row in groups[rel]}
            for target, raw in (imported or {}).items():
                root = self.writer.assets_root
                target_path = Path(target)
                try:
                    relative = str(target_path.relative_to(root))
                except ValueError:
                    # 8.3 短名与长名可能指向同一目录：归一化后再取相对路径；
                    # target 仍按原写法构造，以免与 asset_path() 产出的形态不一致。
                    relative = str(
                        target_path.resolve().relative_to(Path(root).resolve())
                    )
                target = _resolve_inside(root, relative)
                if target not in needed: continue
                if target.exists(): raise ValueError('导入目标已出现，刷新计划后重试')
                from io import BytesIO
                from PIL import Image
                with Image.open(BytesIO(raw)) as image: image.load()
                atomic_write_bytes(target, raw)
                created.append(target)
            for rel, text in updated.items():
                write = self.writer.write_text(rel, text, operation='asset-reference')
                if not write.written: raise OSError(write.error)
                written.append(rel)
                result['warnings'].extend(write.warnings)
        except (OSError, ValueError):
            failures = []
            for rel in reversed(written):
                try: atomic_write_bytes(self.writer.resolve(rel), before[rel])
                except OSError: failures.append(rel)
            if not failures:
                for target in created: target.unlink(missing_ok=True)
                if manifest_before is not None: atomic_write_bytes(manifest_path, manifest_before)
                elif manifest_path.exists(): manifest_path.unlink()
                self.writer.manifest.load()
            if failures: raise OSError('正文回滚未完成，历史恢复点/新增资源已保留：' + ', '.join(failures))
            raise
        result['applied'] = written
        return result


def asset_inventory(assets_root, index):
    from PIL import Image
    inventory = []
    root = Path(assets_root)
    for path in root.rglob('*'):
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg') or not path.is_file(): continue
        try:
            path.resolve().relative_to(root.resolve())
            raw = path.read_bytes()
            try:
                with Image.open(path) as image: dimensions = str(image.width) + '×' + str(image.height)
            except (OSError, ValueError): dimensions = '未识别'
            rel = path.relative_to(root).as_posix()
            sources = []
            for source, refs in index.references.items():
                doc_type = index.files[source].document_type
                for ref in refs:
                    if ref.kind == 'image' and rel == doc_type + '/' + ref.target.split()[0]:
                        sources.append((source, ref.source_line))
            inventory.append(dict(path=rel, bytes=len(raw), dimensions=dimensions, sha256=hashlib.sha256(raw).hexdigest(), references=sources))
        except (OSError, ValueError): continue
    for row in inventory:
        row['duplicates'] = [r['path'] for r in inventory if r['sha256'] == row['sha256'] and r['path'] != row['path']]
    return inventory
