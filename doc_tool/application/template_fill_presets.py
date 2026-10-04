"""Local named recipes and recent jobs; never project build history."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from doc_tool.application.content.writer import atomic_write, atomic_write_bytes


def file_hash(path):
    try: return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError: return ''


def fresh_output(path, sources=()):
    path = Path(path)
    protected = {Path(p).resolve() for p in sources}
    base, number = path, 1
    while path.exists() or path.resolve() in protected:
        path = base.with_name(base.stem + '-' + str(number) + base.suffix)
        number += 1
    return path


class TemplateFillPresets:
    def __init__(self, root=None):
        from doc_tool.application.template_fill import _last_template_file
        self.root = Path(root) if root is not None else _last_template_file().parent
        self.warnings = []
        self.recipes = self._load('template-fill-recipes.json', 'recipes')
        self.jobs = self._load('template-fill-jobs.json', 'jobs')[:20]

    def _load(self, name, key):
        try:
            data = json.loads((self.root / name).read_text(encoding='utf-8'))
            if data.get('schemaVersion') != 1 or not isinstance(data.get(key), list): raise ValueError('schema 1 required')
            if any(not isinstance(item, dict) for item in data[key]): raise ValueError('invalid record')
            for item in data[key]:
                if any(field in item and not isinstance(item[field], str) for field in ('template', 'outputDir', 'outputName')):
                    raise ValueError('invalid settings fields')
                if key == 'recipes':
                    if not isinstance(item.get('recipeId'), str) or not isinstance(item.get('name'), str) or not isinstance(item.get('mapping', {}), dict):
                        raise ValueError('invalid recipe fields')
                elif not isinstance(item.get('time'), str) or not isinstance(item.get('status'), str) or not isinstance(item.get('sources'), list) or any(not isinstance(s, dict) or not isinstance(s.get('path'), str) for s in item['sources']):
                    raise ValueError('invalid job fields')
            return data[key]
        except FileNotFoundError: return []
        except (OSError, ValueError, AttributeError) as exc:
            self.warnings.append(name + ' 配置损坏，保留原文件，使用默认值：' + str(exc))
            return []

    def _save(self, name, key, values):
        path = self.root / name
        if path.exists() and any(warning.startswith(name) for warning in self.warnings):
            atomic_write_bytes(path.with_name(name + '.damaged-' + uuid4().hex), path.read_bytes())
        # Preserve a damaged original before an explicit configuration write.
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding='utf-8'))
                if old.get('schemaVersion') != 1 or not isinstance(old.get(key), list): raise ValueError('schema')
            except (ValueError, AttributeError):
                atomic_write_bytes(path.with_name(name + '.damaged-' + uuid4().hex), path.read_bytes())
        atomic_write(path, json.dumps({'schemaVersion': 1, key: values}, ensure_ascii=False, indent=2))

    def save_recipe(self, name, settings, recipe_id=None, *, known_style_ids=()):
        """保存预设：模板引用 + 有效样式映射 + 受支持版式字段（V4.1 41-B）。

        ``known_style_ids`` 给定时按**实际底模**校验映射（失效项写入替代摘要，
        不进入生效映射）；未知/不支持的版式声明原样保留在详情里但不声称生效。
        """
        if not name.strip(): raise ValueError('预设名称不能为空')
        payload = preset_payload(settings, known_style_ids=known_style_ids)
        recipe = dict(payload, recipeId=recipe_id or uuid4().hex, name=name.strip(),
                      templateHash=file_hash(payload.get('template', '')))
        values = [r for r in self.recipes if r.get('recipeId') != recipe['recipeId']]
        values.append(recipe)
        self._save('template-fill-recipes.json', 'recipes', values)
        self.recipes = values
        return recipe

    def rename_recipe(self, recipe_id, new_name):
        """重命名预设（同一条记录，身份不变）。"""
        new_name = str(new_name or '').strip()
        if not new_name: raise ValueError('预设名称不能为空')
        values = []
        renamed = None
        for item in self.recipes:
            if item.get('recipeId') == recipe_id:
                renamed = dict(item, name=new_name)
                values.append(renamed)
            else:
                values.append(item)
        if renamed is None: raise ValueError('预设不存在：' + str(recipe_id))
        self._save('template-fill-recipes.json', 'recipes', values)
        self.recipes = values
        return renamed

    def get_recipe(self, recipe_id):
        for item in self.recipes:
            if item.get('recipeId') == recipe_id:
                return item
        return None

    def reload(self):
        """从磁盘重新读取预设（外部修改/损坏回退后可重新加载）。"""
        self.warnings = []
        self.recipes = self._load('template-fill-recipes.json', 'recipes')
        self.jobs = self._load('template-fill-jobs.json', 'jobs')[:20]
        return self.recipes

    def delete_recipe(self, recipe_id):
        values = [r for r in self.recipes if r.get('recipeId') != recipe_id]
        self._save('template-fill-recipes.json', 'recipes', values)
        self.recipes = values

    def resolve_recipe(self, recipe, styles):
        values = dict(recipe)
        known = {s.style_id for s in styles.paragraph_styles}
        mapping = recipe.get('mapping') or {}
        if not isinstance(mapping, dict): mapping = {}
        values['mapping'] = {k: v for k, v in mapping.items() if k in known and isinstance(v, int) and 1 <= v <= 6}
        if file_hash(recipe.get('template', '')) != recipe.get('templateHash'):
            self.warnings.append('底模已变化：保留有效映射，其余自动匹配。')
        return values

    def record_job(self, sources, settings, *, status, output='', report='', warnings=()):
        job = dict(settings, jobId=uuid4().hex, time=datetime.now(timezone.utc).isoformat(),
                   sources=[{'path': str(p), 'sha256': file_hash(p)} for p in sources],
                   templateHash=file_hash(settings.get('template', '')), status=status,
                   output=str(output), report=str(report), warnings=list(warnings))
        values = [job] + self.jobs[:19]
        try:
            self._save('template-fill-jobs.json', 'jobs', values)
            self.jobs = values
            return ''
        except OSError as exc:
            return '产物已保留，最近任务记录失败：' + str(exc)


# --- V4.1 41-B：受支持的模板/映射/版式预设 ------------------------------------

#: 真实消费者支持、可写入预设的 LayoutProfile 字段（其余字段不写、不声称生效）。
SUPPORTED_LAYOUT_FIELDS = (
    "mode", "image_width", "table_width", "repeat_header",
    "allow_row_split", "landscape_chapters", "page_break_before_chapter",
)

#: 消费端接受的取值（与 doc_tool/application/export/layout_profile.py 一致）。
_LAYOUT_MODES = ("template", "body-adaptive")
_IMAGE_WIDTHS = ("auto-width", "keep")
_TABLE_WIDTHS = ("equal", "proportional", "keep")

#: 明确**不支持**、只能在详情里保留原文的声明（不加入“已支持”表单）。
UNSUPPORTED_LAYOUT_FIELDS = (
    "fonts", "font", "cover", "header", "footer", "page_numbers", "margins",
)


def collect_layout_fields(layout):
    """挑出受支持的 LayoutProfile 字段；未知字段单独返回（保留不生效）。"""
    data = dict(layout or {})
    supported = {k: data[k] for k in SUPPORTED_LAYOUT_FIELDS if k in data}
    unsupported = {k: v for k, v in data.items() if k not in SUPPORTED_LAYOUT_FIELDS}
    return supported, unsupported


def validate_layout_fields(layout):
    """校验受支持字段；返回 ``(有效字段, 问题说明列表)``。

    无效值被丢弃并给出原因（不静默接受、也不让整份预设失效）。
    """
    supported, _unsupported = collect_layout_fields(layout)
    valid = {}
    problems = []
    for key, value in supported.items():
        if key == "mode":
            if value in _LAYOUT_MODES:
                valid[key] = value
            else:
                problems.append("mode 取值不支持：{0!r}（支持 {1}）".format(value, "/".join(_LAYOUT_MODES)))
        elif key == "image_width":
            if value in _IMAGE_WIDTHS:
                valid[key] = value
            else:
                problems.append("image_width 取值不支持：{0!r}".format(value))
        elif key == "table_width":
            if value in _TABLE_WIDTHS:
                valid[key] = value
            else:
                problems.append("table_width 取值不支持：{0!r}".format(value))
        elif key in ("repeat_header", "allow_row_split", "page_break_before_chapter"):
            if isinstance(value, bool):
                valid[key] = value
            else:
                problems.append("{0} 必须是布尔值：{1!r}".format(key, value))
        elif key == "landscape_chapters":
            if isinstance(value, (list, tuple)):
                valid[key] = [str(item) for item in value]
            else:
                problems.append("landscape_chapters 必须是章节列表：{0!r}".format(value))
    return valid, problems


def validate_style_mapping(mapping, known_style_ids):
    """校验样式映射：保留有效项，返回 ``(有效映射, 失效项, 替代摘要)``。

    ``known_style_ids`` 是**实际底模**里存在的样式 ID 集合（来自真实枚举）。
    失效项不写入生效映射，但会在替代摘要里列出，供用户确认。
    """
    known = {str(item) for item in (known_style_ids or ())}
    valid, dropped = {}, []
    for style_id, level in dict(mapping or {}).items():
        try:
            number = int(level)
        except (TypeError, ValueError):
            dropped.append("{0}（级别不是数字）".format(style_id))
            continue
        if style_id not in known:
            dropped.append("{0}（底模已无此样式）".format(style_id))
            continue
        if not 1 <= number <= 6:
            dropped.append("{0}（级别 {1} 超出 1-6）".format(style_id, number))
            continue
        valid[str(style_id)] = number
    summary = ""
    if dropped:
        summary = "保留 {0} 项有效映射；{1} 项失效将自动匹配标准样式：{2}".format(
            len(valid), len(dropped), "、".join(dropped[:5]),
        )
    return valid, dropped, summary


def preset_payload(settings, *, known_style_ids=(), layout=None):
    """构造一条预设记录：模板引用 + 有效映射 + 受支持版式字段。

    - 未知/不支持声明放入 ``unsupported`` 原样保留，**不进入生效字段**；
    - 正文来源/结构化范围不进预设（由出稿请求承担），避免预设偷偷缩小范围。
    """
    payload = dict(settings or {})
    # 只有拿到**实际底模枚举出的样式 ID** 时才校验映射；否则保持既有行为
    # （不能因为“没有样式清单”就把用户映射全部丢掉）。
    if known_style_ids:
        mapping_valid, mapping_dropped, mapping_summary = validate_style_mapping(
            payload.get("mapping"), known_style_ids,
        )
    else:
        mapping_valid = dict(payload.get("mapping") or {})
        mapping_dropped, mapping_summary = [], ""
    layout_source = layout if layout is not None else payload.get("layout")
    layout_valid, layout_problems = validate_layout_fields(layout_source)
    _supported, unsupported = collect_layout_fields(layout_source)
    payload["mapping"] = mapping_valid
    payload["layout"] = layout_valid
    if unsupported:
        payload["unsupportedLayout"] = unsupported
    if mapping_summary:
        payload["mappingSummary"] = mapping_summary
    if mapping_dropped:
        payload["mappingDropped"] = list(mapping_dropped)
    if layout_problems:
        payload["layoutProblems"] = list(layout_problems)
    # 正文来源/范围与模板预设分开：预设里不得携带 scope/来源模式。
    for key in ("scope", "sourceMode", "source_mode", "captureId", "capture_id"):
        payload.pop(key, None)
    return payload
