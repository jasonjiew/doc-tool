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

    def save_recipe(self, name, settings, recipe_id=None):
        if not name.strip(): raise ValueError('预设名称不能为空')
        recipe = dict(settings, recipeId=recipe_id or uuid4().hex, name=name.strip(),
                      templateHash=file_hash(settings.get('template', '')))
        values = [r for r in self.recipes if r.get('recipeId') != recipe['recipeId']]
        values.append(recipe)
        self._save('template-fill-recipes.json', 'recipes', values)
        self.recipes = values
        return recipe

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
