# -*- coding: utf-8 -*-
"""生成可公开分发的通用规范包（V2.8 28-C / 3.4）。

三个包都是声明式文件集合，不包含任何公司专属底模：
底模用仓库内的脱敏模板（若存在），否则只生成骨架与声明文件。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NL = chr(10)

PACKS = {
    "generic-requirement": {
        "kind": "requirement",
        "description": "通用需求说明书规范包（可公开分发）",
        "template": "requirement-template.docx",
        "chapters": [
            ("1 引言", ["1.1 目的", "1.2 范围", "1.3 术语与缩写"]),
            ("2 需求描述", ["2.1 功能需求", "2.2 非功能需求"]),
        ],
        "variables": {"productName": "待填写产品名", "docVersion": "1.0"},
        "terms": {"terms": [{"canonical": "需求", "aliases": ["需求项"]}]},
        "rules": {"rules": [{"ruleId": "todo_residual", "severity": "warning", "enabled": True}]},
    },
    "generic-design": {
        "kind": "design",
        "description": "通用详细设计说明书规范包（可公开分发）",
        "template": "design-template.docx",
        "chapters": [
            ("1 引言", ["1.1 编写目的", "1.2 范围"]),
            ("2 设计说明", ["2.1 模块划分", "2.2 接口设计"]),
        ],
        "variables": {"productName": "待填写产品名", "docVersion": "1.0"},
        "terms": {"terms": [{"canonical": "模块", "aliases": ["组件"]}]},
        "rules": {"rules": [{"ruleId": "duplicate_title", "severity": "warning", "enabled": True}]},
    },
    "generic-test": {
        "kind": "general",
        "description": "通用测试说明书规范包（可公开分发）",
        "template": "generic-template.docx",
        "chapters": [
            ("1 概述", ["1.1 测试目标", "1.2 测试范围"]),
            ("2 测试用例", ["2.1 功能用例", "2.2 异常场景"]),
        ],
        "variables": {"productName": "待填写产品名", "docVersion": "1.0"},
        "terms": {"terms": [{"canonical": "用例", "aliases": ["测试用例"]}]},
        "rules": {"rules": [{"ruleId": "field_completeness", "severity": "warning", "enabled": True}]},
    },
}


def _skeleton_text(kind: str, title: str, sections) -> str:
    lines = [
        "Table: 文档信息 {#tbl-doc}",
        "",
        "| 项 | 内容 |",
        "| --- | --- |",
        "| 文档名称 | {{productName}} |",
        "| 版本 | {{docVersion}} |",
        "",
    ]
    for heading, children in sections:
        lines.append("## {0}".format(heading))
        lines.append("")
        lines.append("请在此填写{0}。".format(heading))
        lines.append("")
        for child in children:
            lines.append("### {0}".format(child))
            lines.append("")
            lines.append("请在此填写{0}。".format(child))
            lines.append("")
    return NL.join(lines)


def build_pack(name: str, spec: dict, destination: Path) -> dict:
    pack_dir = destination / name
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    (pack_dir / "skeleton").mkdir(parents=True)
    files = {}

    for index, (heading, children) in enumerate(spec["chapters"], start=1):
        file_name = "skeleton/{0}.md".format(heading)
        text = _skeleton_text(spec["kind"], heading, [(heading, children)])
        (pack_dir / file_name).write_text(text, encoding="utf-8")
        files[file_name] = _sha256(pack_dir / file_name)

    variables_path = pack_dir / "variables.yml"
    import yaml

    variables_path.write_text(
        yaml.safe_dump(spec["variables"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    files["variables.yml"] = _sha256(variables_path)

    terms_path = pack_dir / "terms.yml"
    terms_path.write_text(
        yaml.safe_dump(spec["terms"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    files["terms.yml"] = _sha256(terms_path)

    rules_path = pack_dir / "rules.yml"
    rules_path.write_text(
        yaml.safe_dump(spec["rules"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    files["rules.yml"] = _sha256(rules_path)

    template_source = ROOT / "templates" / spec["template"]
    if template_source.is_file():
        shutil.copy2(template_source, pack_dir / "template.docx")
        files["template.docx"] = _sha256(pack_dir / "template.docx")

    pack_meta = {
        "schemaVersion": 1,
        "packId": name,
        "version": "1.0.0",
        "documentKind": spec["kind"],
        "description": spec["description"],
        "files": files,
    }
    (pack_dir / "pack.yml").write_text(
        yaml.safe_dump(pack_meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return pack_meta


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    destination = ROOT / "standards"
    destination.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, spec in PACKS.items():
        summary[name] = build_pack(name, spec, destination)
    (destination / "index.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("已生成 {0} 个通用规范包到 {1}".format(len(summary), destination))
    for name, meta in summary.items():
        print("  {0} v{1} ({2} 个文件)".format(name, meta["version"], len(meta["files"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())