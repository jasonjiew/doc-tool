"""Shared, read-only preflight and immutable-input execution for GUI and CLI."""
import json
import tempfile
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from doc_tool.domain.markdown_structure import markdown_headings, prose_lines, split_table_row, is_separator_row
from doc_tool.application.template_fill_presets import file_hash, fresh_output
from doc_tool.application.template_fill import parse_template_styles, load_last_template, TemplateFillError, OOXMLSecurityError
from doc_tool.domain.errors import TextEncodingError


@dataclass
class FillPlan:
    template: str = ''
    template_hash: str = ''
    output: str = ''
    inputs: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    viable: bool = False
    status: str = '无可行方案'

    def report(self, format='text'):
        if format == 'json': return json.dumps(asdict(self), ensure_ascii=False, indent=2)
        return '\n'.join([self.status, '实际底模：' + self.template, '实际输出：' + self.output] +
            [f'{i+1}. {item["path"]} · 标题 {len(item["outline"])} · 图 {item["images"]} · 表 {item["tables"]}' for i, item in enumerate(self.inputs)] +
            [f'{item["path"]}:{item["line"]} [{item["severity"]}] {item["message"]}；{item["action"]}' for item in self.issues])


def plan_template_fill(sources, template, output, *, mapping=None, strict=False, fallback_templates=None):
    from doc_tool.application.content.preview import _IMAGE_RE
    from doc_tool.application.markdown_word import read_markdown_text
    plan = FillPlan()
    def issue(path, line, message, action='生成后完善', severity='warning'):
        plan.issues.append(dict(path=str(path), line=line, severity=severity, message=message, action=action))
    candidates = [template]
    if fallback_templates is None:
        from doc_tool.resources import resource_root
        # Installed resources use the same root as project creation.
        try: candidates += [load_last_template(), Path(resource_root()) / 'generic-template.docx']
        except (ImportError, TypeError): pass
    else: candidates += list(fallback_templates)
    styles = None
    for candidate in candidates:
        if not candidate: continue
        try:
            styles = parse_template_styles(candidate)
            plan.template = str(Path(candidate))
            plan.template_hash = file_hash(candidate)
            if str(candidate) != str(template): issue(template, 0, '底模不可用，已采用替代底模：' + str(candidate), '可在结果后调整底模')
            break
        except (OSError, ValueError, TemplateFillError, OOXMLSecurityError): continue
    if styles is None: issue(template, 0, '没有可解析底模', '选择可用 DOCX', 'error')
    else:
        known = {s.style_id for s in styles.paragraph_styles}
        plan.mapping = {key: value for key, value in (mapping or {}).items() if key in known and isinstance(value, int) and 1 <= value <= 6}
        from doc_tool.application.template_fill import validate_style_map
        if plan.mapping and validate_style_map(plan.mapping):
            merged = {style: level for level, style in styles.raw_heading_styles.items()}
            for key, value in plan.mapping.items():
                merged = {k: v for k, v in merged.items() if v != value}
                merged[key] = value
            plan.mapping = merged if not validate_style_map(merged) else {}
        if plan.mapping != (mapping or {}): issue(template, 0, '失效样式映射已自动匹配', '可修改样式映射')
        for warning in styles.warnings: issue(template, 0, warning)
    for source in sources:
        path = Path(source)
        try:
            text = read_markdown_text(path)
            if not text.strip(): raise ValueError('输入为空')
        except (OSError, ValueError, TextEncodingError) as exc:
            plan.skipped.append(str(path))
            issue(path, 0, '跳过不可读输入：' + str(exc), '恢复输入后重试')
            continue
        lines = list(prose_lines(text))
        images = 0
        tables = 0
        for number, line in lines:
            if line.strip().startswith('|') and is_separator_row(split_table_row(line.strip())): tables += 1
            for image in _IMAGE_RE.finditer(line):
                images += 1
                target = path.parent / image[2]
                try:
                    target.resolve().relative_to(path.parent.resolve())
                    if not target.is_file(): raise ValueError('缺失')
                except (ValueError, OSError): issue(path, number, '图片缺失/越界：' + image[2], '输出资源说明占位')
        if '```' in text or '~~~' in text: issue(path, 0, '代码/图源码按现有能力降级，不承诺正式 Mermaid 图', '可读源码保留')
        plan.inputs.append(dict(path=str(path), sha256=file_hash(path), outline=markdown_headings(text), images=images, tables=tables))
    if not plan.inputs: issue('', 0, '没有可用输入', '添加可读 Markdown', 'error')
    actual = fresh_output(output, list(sources) + [plan.template])
    plan.output = str(actual)
    if actual != Path(output): issue(output, 0, '输出冲突，已改用新文件', str(actual), 'info')
    plan.viable = bool(styles and plan.inputs and (not strict or not any(i['severity'] in ('warning', 'error') for i in plan.issues)))
    plan.status = ('部分完成' if plan.skipped else '带提醒完成' if plan.issues else '可生成') if plan.viable else '无可行方案/严格检查未通过'
    return plan


def execute_template_fill(sources, template, output, *, heading_style_map=None, strict=False,
                          refresh_fields=False, clean_body_from_first_heading=False, on_warning=None,
                          refresh_timeout_seconds=300, cancel_token=None, progress=None, on_event=None):
    from doc_tool.application.template_fill import fill_markdown_with_template
    def stage(name, detail=''):
        if on_event:
            from types import SimpleNamespace
            on_event(SimpleNamespace(stage=name, status='running', detail=detail))
    stage('解析底模/预检')
    plan = plan_template_fill(sources, template, output, mapping=heading_style_map, strict=strict)
    if not plan.viable: raise TemplateFillError(user_message=plan.report())
    if cancel_token: cancel_token.check_cancel()
    # Freeze the bytes actually read; shared image resolver still uses original source directories.
    from doc_tool.application.markdown_word import read_markdown_text
    with tempfile.TemporaryDirectory(prefix='template-fill-snapshot-') as tmp:
        frozen_template = Path(tmp) / 'template.docx'
        shutil.copyfile(plan.template, frozen_template)
        from doc_tool.application.content.preview import _IMAGE_RE
        frozen_inputs = []
        for n, item in enumerate(plan.inputs):
            if cancel_token: cancel_token.check_cancel()
            source = Path(item['path'])
            raw = source.read_bytes()
            import hashlib
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash != item['sha256']:
                plan.issues.append(dict(path=str(source), line=0, severity='info', message='输入已变化，使用本次快照', action='查看实际输出'))
            item['sha256'] = actual_hash
            folder = Path(tmp) / ('input-' + str(n))
            folder.mkdir()
            frozen = folder / source.name
            frozen.write_bytes(raw)
            text = read_markdown_text(frozen)
            item['outline'] = markdown_headings(text)
            for _, line in prose_lines(text):
                for image in _IMAGE_RE.finditer(line):
                    candidate = source.parent / image[2]
                    try:
                        candidate.resolve().relative_to(source.parent.resolve())
                        if candidate.is_file():
                            dest = folder / image[2]
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(candidate, dest)
                    except (OSError, ValueError): pass
            frozen_inputs.append(frozen)
            if progress: progress('扫描输入', f'{n+1}/{len(plan.inputs)} {source.name}')
            stage('扫描输入', f'{n+1}/{len(plan.inputs)} {source.name}')
        if cancel_token: cancel_token.check_cancel()
        # Assemble to a task-local path so cancellation cannot replace any output.
        assembled = Path(tmp) / 'assembled.docx'
        stage('装配 / 可选 Word 刷新')
        result = fill_markdown_with_template(frozen_inputs, frozen_template, assembled,
            heading_style_map=plan.mapping or None, refresh_fields=refresh_fields,
            refresh_timeout_seconds=refresh_timeout_seconds, clean_body_from_first_heading=clean_body_from_first_heading,
            on_warning=on_warning)
        if cancel_token: cancel_token.check_cancel()
        from doc_tool.application.content.writer import atomic_write_bytes
        final = fresh_output(plan.output, sources + [template] if isinstance(sources, list) else list(sources) + [template])
        atomic_write_bytes(final, assembled.read_bytes())
        result.output = final
        plan.output = str(final)
        stage('完成', str(final))
    result.warnings.extend(i['message'] for i in plan.issues)
    result.plan = plan
    result.status = '部分完成' if plan.skipped else '待刷新' if result.refresh_state != 'ok' else '带提醒完成' if result.warnings else '完成'
    return result
