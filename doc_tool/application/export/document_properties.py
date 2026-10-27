# -*- coding: utf-8 -*-
"""Read and apply one export's editable Word document properties to its template copy."""
from __future__ import annotations

import os
import re
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict

from lxml import etree

from doc_tool.domain.ooxml import parse_xml_safe, read_docx_package

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CUSTOM = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
DC = "{http://purl.org/dc/elements/1.1/}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
CORE = {"creator": (DC, "作者", "Author"), "subject": (DC, "主题", "Subject"),
        "description": (DC, "备注", "Comments"), "keywords": (CP, "关键词", "Keywords"),
        "category": (CP, "类别", "Category")}
TEXT_TYPES = {"lpwstr", "lpstr", "bstr"}
INTEGER_TYPES = {"i1": (-128, 127), "i2": (-32768, 32767), "i4": (-2147483648, 2147483647),
                 "int": (-2147483648, 2147483647), "i8": (-(2**63), 2**63-1),
                 "ui1": (0, 255), "ui2": (0, 65535), "ui4": (0, 2**32-1),
                 "uint": (0, 2**32-1), "ui8": (0, 2**64-1)}
SCALAR_TYPES = TEXT_TYPES | set(INTEGER_TYPES) | {"r4", "r8", "decimal", "bool", "date", "filetime"}
RESERVED = {"文档编号", "文件编号", "文件名称", "文档名称", "版本", "版本号"}
_FIELD_RE = re.compile(r'^\s*DOCPROPERTY\s+(?:"([^"]+)"|([^\s\\]+))', re.I)


def _read(path: Path) -> Dict[str, bytes]:
    with read_docx_package(path) as package:
        return package.read_all()


def read_template_reserved_properties(path) -> Dict[str, str]:
    """Read reserved document properties from template (e.g. 文档编号, 文件名称, 版本)."""
    items = _read(Path(path))
    result: Dict[str, str] = {}
    if "docProps/custom.xml" in items:
        root = parse_xml_safe(items["docProps/custom.xml"], "docProps/custom.xml")
        for prop in root.findall(CUSTOM + "property"):
            name = prop.get("name") or ""
            if name in RESERVED and len(prop) == 1:
                result[name] = (prop[0].text or "").strip()
    return result


def inspect_document_properties(path) -> Dict[str, dict]:
    """Return existing scalar properties, with unsupported values marked read-only."""
    items = _read(Path(path))
    result: Dict[str, dict] = {}
    if "docProps/custom.xml" in items:
        root = parse_xml_safe(items["docProps/custom.xml"], "docProps/custom.xml")
        for prop in root.findall(CUSTOM + "property"):
            name = prop.get("name") or ""
            if not name or name in RESERVED or len(prop) != 1:
                continue
            child = prop[0]
            if etree.QName(child).namespace == VT[1:-1]:
                kind = etree.QName(child).localname
                value = (child.text or "") if kind in SCALAR_TYPES else "（复杂属性，原值保留）"
                result["custom:" + name] = {"label": name, "value": value, "type": kind, "editable": kind in SCALAR_TYPES}
    if "docProps/core.xml" in items:
        root = parse_xml_safe(items["docProps/core.xml"], "docProps/core.xml")
        for key, (namespace, label, _field_name) in CORE.items():
            node = root.find(namespace + key)
            result["core:" + key] = {"label": label, "value": (node.text or "") if node is not None else "", "type": "text", "editable": True}
    return result


def validate_property_value(info: dict, value: str) -> str:
    kind = info.get("type", "text")
    if not info.get("editable", True):
        raise ValueError("该属性类型暂不支持编辑")
    if kind in TEXT_TYPES or kind == "text":
        if any(not (char in "\t\n\r" or "\x20" <= char <= "\ud7ff" or "\ue000" <= char <= "\ufffd" or "\U00010000" <= char <= "\U0010ffff") for char in value):
            raise ValueError("{0} 含有 Word XML 不支持的字符".format(info.get("label", "属性")))
        return value
    value = value.strip()
    try:
        if kind in INTEGER_TYPES:
            if not re.fullmatch(r"[+-]?\d+", value):
                raise ValueError("请输入整数")
            number = int(value)
            low, high = INTEGER_TYPES[kind]
            if not low <= number <= high:
                raise ValueError("超出数值范围")
            value = str(number)
        elif kind in {"r4", "r8", "decimal"}:
            if not Decimal(value).is_finite():
                raise ValueError("数值必须是有限数")
        elif kind == "bool":
            if value.lower() not in {"true", "false", "1", "0"}:
                raise ValueError("布尔值请输入 true 或 false")
            value = "true" if value.lower() in {"true", "1"} else "false"
        elif kind in {"date", "filetime"}:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if kind == "filetime" and parsed.utcoffset() is None:
                raise ValueError("日期时间须带时区，例如 2026-10-27T00:00:00Z")
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("{0} 的值不符合 {1} 类型：{2}".format(info.get("label", "属性"), kind, exc)) from exc
    return value


def _update_field_results(root, values: Dict[str, str]) -> None:
    """Update cached DOCPROPERTY results, retaining fields and run formatting."""
    for field in root.iter(W + "fldSimple"):
        match = _FIELD_RE.match(field.get(W + "instr") or "")
        value = values.get((match.group(1) or match.group(2)).casefold()) if match else None
        if value is not None:
            nodes = list(field.iter(W + "t"))
            if nodes:
                nodes[0].text = value
                nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for node in nodes[1:]:
                    node.text = ""
    stack = []
    for node in root.iter():
        if node.tag == W + "fldChar":
            kind = node.get(W + "fldCharType")
            if kind == "begin":
                stack.append({"instruction": [], "result": False, "written": False})
            elif kind == "separate" and stack:
                stack[-1]["result"] = True
            elif kind == "end" and stack:
                stack.pop()
        elif node.tag == W + "instrText" and stack and not stack[-1]["result"]:
            stack[-1]["instruction"].append(node.text or "")
        elif node.tag == W + "t" and stack and stack[-1]["result"]:
            entry = stack[-1]
            match = _FIELD_RE.match("".join(entry["instruction"]))
            value = values.get((match.group(1) or match.group(2)).casefold()) if match else None
            if value is not None:
                node.text = "" if entry["written"] else value
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                entry["written"] = True


def apply_document_properties(path, overrides: Dict[str, str]) -> None:
    """Apply only explicitly edited properties to a private snapshot template."""
    if not overrides:
        return
    path = Path(path)
    supported = inspect_document_properties(path)
    unknown = {key for key in overrides if key not in supported or not supported[key].get("editable")}
    if unknown:
        raise ValueError("模板文档属性不可编辑或已变化：" + ", ".join(sorted(unknown)))
    overrides = {key: validate_property_value(supported[key], str(value)) for key, value in overrides.items()}
    items = _read(path)
    fields: Dict[str, str] = {}
    for part in ("docProps/custom.xml", "docProps/core.xml"):
        if part not in items:
            continue
        root = parse_xml_safe(items[part], part)
        if part.endswith("custom.xml"):
            for prop in root.findall(CUSTOM + "property"):
                name = prop.get("name") or ""
                key = "custom:" + name
                if key in overrides:
                    prop[0].text = str(overrides[key])
                    fields[name.casefold()] = str(overrides[key])
        else:
            for key, (namespace, label, field_name) in CORE.items():
                override_key = "core:" + key
                if override_key in overrides:
                    node = root.find(namespace + key)
                    if node is None:
                        node = etree.SubElement(root, namespace + key)
                    node.text = str(overrides[override_key])
                    fields[field_name.casefold()] = str(overrides[override_key])
                    fields[label.casefold()] = str(overrides[override_key])
        items[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    for part in list(items):
        if part.startswith("word/") and part.endswith(".xml") and (part == "word/document.xml" or re.match(r"word/(header|footer)\d+\.xml$", part)):
            root = parse_xml_safe(items[part], part)
            _update_field_results(root, fields)
            items[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    fd, temporary = tempfile.mkstemp(prefix=".properties-", suffix=".docx", dir=str(path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(path) as original, zipfile.ZipFile(temporary, "w") as output:
            for info in original.infolist():
                output.writestr(info, items[info.filename])
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
