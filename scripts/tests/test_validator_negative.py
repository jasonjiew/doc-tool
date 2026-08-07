# -*- coding: utf-8 -*-
"""Black-box validator positive/negative regression suite."""

from __future__ import annotations

import copy
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import zipfile
from typing import Callable, Dict

from lxml import etree


TESTS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(TESTS)
BASE = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from docx_common import load_config, normalize_business_text  # noqa: E402
from validate_docx import canonical_xml, paragraph_text, qn  # noqa: E402


REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def package_items(path: str) -> Dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as package:
        return {name: package.read(name) for name in package.namelist()}


def write_package(path: str, items: Dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in items.items():
            package.writestr(name, data)


def heading_map(items: Dict[str, bytes]):
    styles = etree.fromstring(items["word/styles.xml"])
    result = {}
    for style in styles.iter(qn("style")):
        name = style.find(qn("name"))
        if name is None:
            continue
        match = re.match(r"(?i)heading\s*(\d+)", name.get(qn("val")) or "")
        if match:
            result[style.get(qn("styleId"))] = int(match.group(1))
    return result


def paragraph_level(paragraph, levels):
    properties = paragraph.find(qn("pPr"))
    style = properties.find(qn("pStyle")) if properties is not None else None
    return levels.get(style.get(qn("val"))) if style is not None else None


def document_body(items):
    document = etree.fromstring(items["word/document.xml"])
    return document, document.find(qn("body"))


def save_document(items, document):
    items["word/document.xml"] = etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True)


def mutate_empty_body(items, config):
    document, body = document_body(items)
    for element in list(body):
        if element.tag != qn("sectPr"):
            body.remove(element)
    save_document(items, document)


def mutate_delete_h3(items, config):
    document, body = document_body(items)
    levels = heading_map(items)
    victim = next(p for p in body.findall(qn("p")) if paragraph_level(p, levels) == 3)
    body.remove(victim)
    save_document(items, document)


def mutate_swap_headings(items, config):
    document, body = document_body(items)
    levels = heading_map(items)
    indices = [i for i, p in enumerate(body) if p.tag == qn("p") and paragraph_level(p, levels) == 3][:2]
    first, second = copy.deepcopy(body[indices[0]]), copy.deepcopy(body[indices[1]])
    body[indices[0]], body[indices[1]] = second, first
    save_document(items, document)


def mutate_paragraph_text(items, config):
    document, body = document_body(items)
    levels = heading_map(items)
    started = False
    for paragraph in body.findall(qn("p")):
        level = paragraph_level(paragraph, levels)
        started = started or level == 1
        texts = paragraph.findall(".//" + qn("t"))
        if started and not level and texts and paragraph_text(paragraph):
            texts[0].text = (texts[0].text or "") + "[篡改]"
            save_document(items, document)
            return
    raise AssertionError("未找到正文段落")


def mutate_parent_body_position(items, config):
    document, body = document_body(items)
    levels = heading_map(items)
    children = list(body)
    parent_index = next(
        i
        for i, node in enumerate(children)
        if node.tag == qn("p")
        and paragraph_level(node, levels) == 2
        and normalize_business_text(paragraph_text(node)) == "呼吸机接口"
    )
    child_index = next(
        i
        for i in range(parent_index + 1, len(children))
        if children[i].tag == qn("p") and paragraph_level(children[i], levels) == 3
    )
    table = next(node for node in children[parent_index + 1 : child_index] if node.tag == qn("tbl"))
    body.remove(table)
    child = children[child_index]
    body.insert(body.index(child) + 1, table)
    save_document(items, document)


def complex_table_signatures(config):
    result = set()
    for name in os.listdir(config["paths"]["table_root"]):
        if name.lower().endswith(".xml"):
            root = etree.parse(os.path.join(config["paths"]["table_root"], name)).getroot()
            result.add(canonical_xml(root))
    return result


def mutate_normal_table_cell(items, config):
    document, body = document_body(items)
    complex_tables = complex_table_signatures(config)
    levels = heading_map(items)
    started = False
    for table in body:
        if table.tag == qn("p") and paragraph_level(table, levels) == 1:
            started = True
        if not started or table.tag != qn("tbl"):
            continue
        if canonical_xml(table) in complex_tables:
            continue
        text = table.find(".//" + qn("t"))
        if text is not None:
            text.text = (text.text or "") + "[篡改]"
            save_document(items, document)
            return
    raise AssertionError("未找到普通表格")


def mutate_delete_complex_table(items, config):
    document, body = document_body(items)
    signatures = complex_table_signatures(config)
    table = next(table for table in body.findall(qn("tbl")) if canonical_xml(table) in signatures)
    body.remove(table)
    save_document(items, document)


def mutate_missing_image_target(items, config):
    relationships = etree.fromstring(items["word/_rels/document.xml.rels"])
    relationship = next(
        rel for rel in relationships if (rel.get("Type") or "").endswith("/image")
    )
    target = posixpath.normpath(posixpath.join("word", relationship.get("Target"))).lstrip("/")
    if target not in items:
        target = posixpath.normpath(posixpath.join("word", relationship.get("Target").lstrip("/")))
    del items[target]


def mutate_illegal_update_fields(items, config):
    document = etree.fromstring(items["word/document.xml"])
    etree.SubElement(document, qn("updateFields")).set(qn("val"), "true")
    save_document(items, document)


def mutate_duplicate_media(items, config):
    name = next(name for name in items if name.startswith("word/media/"))
    suffix = os.path.splitext(name)[1]
    items["word/media/validator_duplicate" + suffix] = items[name]


def create_mutation(source: str, destination: str, config, mutation: Callable) -> None:
    items = package_items(source)
    mutation(items, config)
    write_package(destination, items)


def validator_exit(document: str, output: str, report: str) -> int:
    command = [
        sys.executable,
        os.path.join(SCRIPTS, "validate_docx.py"),
        document,
        "--output",
        output,
        "--report",
        report,
    ]
    result = subprocess.run(command, cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode


def isolated_build(document: str, output: str) -> bool:
    command = [
        sys.executable,
        os.path.join(SCRIPTS, "build_docx.py"),
        document,
        "--output",
        output,
    ]
    return subprocess.run(
        command, cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    ).returncode == 0


def main() -> int:
    requirement = load_config("requirement", BASE)
    design = load_config("design", BASE)
    failures = []
    with tempfile.TemporaryDirectory(prefix="doc-validator-regression-") as work:
        requirement["paths"]["output"] = os.path.join(work, "requirement-clean.docx")
        design["paths"]["output"] = os.path.join(work, "design-clean.docx")
        if not isolated_build("requirement", requirement["paths"]["output"]) or not isolated_build(
            "design", design["paths"]["output"]
        ):
            print("[FAIL] 无法创建隔离的正向基线输出", file=sys.stderr)
            return 1
        scenarios = [
            ("V01 正确需求文档", "requirement", requirement, None, True),
            ("V02 正确详细设计文档", "design", design, None, True),
            ("V03 空正文", "requirement", requirement, mutate_empty_body, False),
            ("V04 删除 H3", "requirement", requirement, mutate_delete_h3, False),
            ("V05 交换标题顺序", "requirement", requirement, mutate_swap_headings, False),
            ("V06 修改正文文本", "requirement", requirement, mutate_paragraph_text, False),
            ("V07 父正文移动到子标题后", "requirement", requirement, mutate_parent_body_position, False),
            ("V08 修改普通表格单元格", "requirement", requirement, mutate_normal_table_cell, False),
            ("V09 删除复杂表格", "requirement", requirement, mutate_delete_complex_table, False),
            ("V10 图片 relationship 目标缺失", "design", design, mutate_missing_image_target, False),
            ("V11 document.xml 非法 updateFields", "requirement", requirement, mutate_illegal_update_fields, False),
            ("V12 重复媒体文件", "design", design, mutate_duplicate_media, False),
        ]
        for index, (name, document, config, mutation, should_pass) in enumerate(scenarios, start=1):
            output = config["paths"]["output"]
            if mutation is not None:
                output = os.path.join(work, "case-{0}.docx".format(index))
                create_mutation(config["paths"]["output"], output, config, mutation)
            code = validator_exit(document, output, os.path.join(work, "case-{0}.md".format(index)))
            actual_pass = code == 0
            status = "PASS" if actual_pass == should_pass else "FAIL"
            print("[{0}] {1}: validator exit={2}, expected={3}".format(status, name, code, "accept" if should_pass else "reject"))
            if status == "FAIL":
                failures.append(name)
    if failures:
        print("[FAIL] 负向回归未闭环: {0}".format("、".join(failures)), file=sys.stderr)
        return 1
    print("[SUCCESS] Validator 正向/负向回归全部符合预期。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
