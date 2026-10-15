# -*- coding: utf-8 -*-
"""按明确范围检查模块章节和表型；复用构建端 Markdown 词法契约。"""
from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import List

from doc_tool.domain.markdown_structure import (
    StructureFinding, is_separator_row, markdown_headings, prose_lines, split_table_row,
)

CONTRACT_RULE_IDS = frozenset(("module_sections", "table_schema"))


def matches_paths(path: str, params: dict) -> bool:
    """只选择已进入索引的相对路径，不据 glob 读取文件系统。"""
    value = path.replace("\\", "/")
    def matches(pattern):
        pattern = pattern.replace("\\", "/")
        return fnmatch.fnmatchcase(value, pattern) or (
            pattern.startswith("**/") and fnmatch.fnmatchcase(value, pattern[3:])
        )
    return any(matches(p) for p in params.get("paths", [])) and not any(
        matches(p) for p in params.get("exclude_paths", [])
    )


def _strings(value, name, errors, *, nonempty=True):
    if not isinstance(value, list) or (nonempty and not value) or any(
        not isinstance(x, str) or not x.strip() for x in value
    ):
        errors.append(name + " 应为非空字符串列表" if nonempty else name + " 应为字符串列表")
        return False
    if len(set(value)) != len(value):
        errors.append(name + " 不可重复")
    return True


def validate_contract_params(rule_id: str, params: dict) -> List[str]:
    errors = []
    if _strings(params.get("paths"), "paths", errors):
        for path in params["paths"]:
            normalized = path.replace("\\", "/")
            if normalized.startswith("/") or ":" in normalized or ".." in PurePosixPath(normalized).parts:
                errors.append("paths 必须相对 contentRoot，不可越界")
    if "exclude_paths" in params:
        _strings(params["exclude_paths"], "exclude_paths", errors, nonempty=False)
    if rule_id == "module_sections":
        _strings(params.get("sections"), "sections", errors)
        mode = params.get("mode", "file")
        if mode not in ("file", "heading"):
            errors.append("mode 只能为 file/heading")
        level = params.get("module_level", 3)
        section = params.get("section_level", level + 1 if mode == "heading" and type(level) is int else 4)
        if type(section) is not int or not 1 <= section <= 6:
            errors.append("section_level 应为 1～6 的整数")
        if mode == "heading" and (type(level) is not int or not 1 <= level < 6 or type(section) is not int or section <= level):
            errors.append("heading 模式要求 module_level 为 1～5，section_level 大于模块级别")
        for key in ("ordered", "allow_extra"):
            if key in params and type(params[key]) is not bool:
                errors.append(key + " 应为布尔值")
    else:
        schemas = params.get("schemas")
        if not isinstance(schemas, list) or not schemas:
            errors.append("schemas 应为非空表型列表")
            return errors
        for i, schema in enumerate(schemas):
            label = "schemas[{0}]".format(i)
            if not isinstance(schema, dict):
                errors.append(label + " 应为对象")
                continue
            _strings(schema.get("required_headers"), label + ".required_headers", errors)
            for key in ("match_headers", "required_cells"):
                if key in schema:
                    _strings(schema[key], label + "." + key, errors, nonempty=False)
            aliases = schema.get("aliases", {})
            if not isinstance(aliases, dict):
                errors.append(label + ".aliases 应为列名到别名列表的映射")
            else:
                for key, values in aliases.items():
                    if not isinstance(key, str) or not key.strip():
                        errors.append(label + ".aliases 的列名应为非空字符串")
                    _strings(values, label + ".aliases." + str(key), errors, nonempty=False)
            headers = schema.get("required_headers")
            cells = schema.get("required_cells", headers)
            if isinstance(headers, list) and isinstance(cells, list) and all(isinstance(x, str) for x in headers + cells):
                if any(name not in headers for name in cells):
                    errors.append(label + ".required_cells 必须引用 required_headers 中的列")
            if isinstance(headers, list) and all(isinstance(x, str) for x in headers) and isinstance(aliases, dict):
                owners = {}
                for header in headers:
                    values = aliases.get(header, [])
                    if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
                        continue
                    for value in [header] + values:
                        token = _normal_header(value)
                        if token in owners and owners[token] != header:
                            errors.append(label + ".aliases 在不同必需列之间存在歧义：" + value)
                        owners[token] = header
            count = schema.get("min_rows", 1)
            if type(count) is not int or count < 0:
                errors.append(label + ".min_rows 应为非负整数")
        if "require_table" in params and type(params["require_table"]) is not bool:
            errors.append("require_table 应为布尔值")
    return errors


def check_module_sections(text: str, params: dict) -> List[StructureFinding]:
    from doc_tool.application.content.tree import strip_number_prefix
    # DOC-ITEM/TBL 等行内标记不应让其前后的真实正文消失，行号保持不变。
    text = re.sub(r"<!--[^\n]*?-->", "", text)
    headings = [(level, strip_number_prefix(title), line) for level, title, line in markdown_headings(text)]
    required = [strip_number_prefix(name.strip()) for name in params["sections"]]
    mode = params.get("mode", "file")
    module_level = params.get("module_level", 3)
    section_level = params.get("section_level", module_level + 1 if mode == "heading" else 4)
    modules = [(1, len(text.splitlines()) + 1, "本模块")]
    if mode == "heading":
        modules = []
        for i, (level, title, start) in enumerate(headings):
            if level != module_level:
                continue
            end = next((h[2] for h in headings[i + 1:] if h[0] <= module_level), len(text.splitlines()) + 1)
            modules.append((start, end, title))
        if not modules:
            return [StructureFinding(1, "module_sections", "未发现配置级别的模块标题，本文件的模块规范未完成检查。")]
    findings = []
    for start, end, title in modules:
        sections = [(name, line) for level, name, line in headings if level == section_level and start <= line < end]
        names = [name for name, _ in sections]
        missing = [name for name in required if name not in names]
        if missing:
            findings.append(StructureFinding(start, "module_sections", "模块「{0}」缺少：{1}。".format(title, "、".join(missing))))
        seen = set()
        for name, line in sections:
            if name in seen:
                findings.append(StructureFinding(line, "module_sections", "模块「{0}」章节「{1}」重复。".format(title, name)))
            seen.add(name)
            if name not in required and not params.get("allow_extra", False):
                findings.append(StructureFinding(line, "module_sections", "模块「{0}」存在规范外的同级章节「{1}」。".format(title, name)))
        known = [name for name in names if name in required]
        ranks = [required.index(name) for name in known]
        if params.get("ordered", True) and ranks != sorted(ranks):
            line = next((line for name, line in sections if name in required), start)
            findings.append(StructureFinding(line, "module_sections", "模块「{0}」章节顺序应为：{1}。".format(title, " → ".join(required))))
    return findings


def _normal_header(value):
    import re
    return re.sub(r"\s+", "", value.strip().strip("`*_ ")).casefold()


def _tables(text):
    text = re.sub(r"<!--[^\n]*?-->", "", text)
    block = []
    previous = 0
    for number, line in prose_lines(text):
        if line.lstrip().startswith("|"):
            if block and number != previous + 1:
                yield block
                block = []
            block.append((number, split_table_row(line)))
            previous = number
        elif block:
            yield block
            block = []
    if block:
        yield block


def check_table_schema(text: str, params: dict) -> List[StructureFinding]:
    findings = []
    selected = 0
    for block in _tables(text):
        header_line, header = block[0]
        normalized = [_normal_header(x) for x in header]
        candidates = []
        for schema in params["schemas"]:
            aliases = schema.get("aliases", {})
            def alternatives(name):
                return {_normal_header(x) for x in [name] + aliases.get(name, [])}
            matchers = schema.get("match_headers") or schema["required_headers"]
            score = sum(bool(alternatives(name).intersection(normalized)) for name in matchers)
            if score:
                candidates.append((score, schema))
        if not candidates:
            continue  # 模块头/功能概览等无关表不被强行套入需求明细表型。
        selected += 1
        score = max(x[0] for x in candidates)
        best = [schema for value, schema in candidates if value == score]
        if len(best) != 1:
            findings.append(StructureFinding(header_line, "table_schema", "表型匹配不唯一，请配置更明确的 match_headers；本表未执行字段检查。"))
            continue
        schema = best[0]
        aliases = schema.get("aliases", {})
        positions = {}
        for name in schema["required_headers"]:
            alternatives = {_normal_header(x) for x in [name] + aliases.get(name, [])}
            hits = [i for i, value in enumerate(normalized) if value in alternatives]
            if not hits:
                findings.append(StructureFinding(header_line, "table_schema", "表格缺少必需列「{0}」。".format(name)))
            elif len(hits) > 1:
                findings.append(StructureFinding(header_line, "table_schema", "列「{0}」重复或别名冲突。".format(name)))
            else:
                positions[name] = hits[0]
        rows = [(number, cells) for number, cells in block[1:] if not is_separator_row(cells)]
        if len(rows) < schema.get("min_rows", 1):
            findings.append(StructureFinding(header_line, "table_schema", "需求明细表数据行不足，至少需要 {0} 行。".format(schema.get("min_rows", 1))))
        for number, cells in rows:
            for name in schema.get("required_cells", schema["required_headers"]):
                index = positions.get(name)
                if index is not None and (index >= len(cells) or not cells[index].strip()):
                    findings.append(StructureFinding(number, "table_schema", "必填字段「{0}」为空。".format(name)))
    if not selected and params.get("require_table", True):
        findings.append(StructureFinding(1, "table_schema", "未发现匹配的需求明细表，本文件的表型规范未完成检查。"))
    return findings
