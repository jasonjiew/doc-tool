# -*- coding: utf-8 -*-
"""V2.7 验收证据：三类样本跑「导入→检查→诊断出稿」（8.2 / A27-1～A27-5）。

用脱敏样本（需求/设计/测试）实际执行构建、严格校验、终审与 ``check``，
并把真实命令、退出码与结果写入 ``docs/release/evidence/``。
本脚本不使用 mock：构建与校验都走真实内核，Word 环节标记为未执行。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

NL = chr(10)
EVIDENCE = ROOT / "docs" / "release" / "evidence"

SAMPLES = {
    "requirement": {
        "title": "需求说明书样本",
        "body": NL.join(
            [
                "## 1.1 功能需求",
                "",
                "系统应支持离线出稿，并在无 Word 环境下给出可打开的诊断产物。",
                "",
                "Table: 需求清单 {#tbl-req}",
                "",
                "| 编号 | 需求 |",
                "| --- | --- |",
                "| R1 | 支持代码块与图表题注 |",
                "| R2 | 支持横向页放置宽表 |",
                "",
                "详见 @tbl-req。",
                "",
                "```mermaid",
                "flowchart TD",
                "  A[导入] --> B[检查]",
                "  B --> C[出稿]",
                "```",
                "",
            ]
        ),
    },
    "design": {
        "title": "详细设计说明书样本",
        "body": NL.join(
            [
                "## 1.1 模块设计",
                "",
                "模块划分与接口约束：代码示例必须保留缩进与空行。",
                "",
                "```python",
                "def build(config):",
                "    if not config:",
                "        return None",
                TAB_RETURN if False else "\treturn 'ok'",
                "",
                "```",
                "",
                "Table: 接口表 {#tbl-api}",
                "",
                "| 接口 | 说明 |",
                "| --- | --- |",
                "| build | 构建产物 |",
                "",
                "<!-- LANDSCAPE -->",
                "",
                "Table: 宽表 {#tbl-wide}",
                "",
                "| 一 | 二 | 三 | 四 | 五 | 六 |",
                "| --- | --- | --- | --- | --- | --- |",
                "| 1 | 2 | 3 | 4 | 5 | 6 |",
                "",
                "<!-- END_LANDSCAPE -->",
                "",
                "横向节之后回到纵向版式。",
                "",
            ]
        ),
    },
    "test": {
        "title": "测试说明书样本",
        "body": NL.join(
            [
                "## 1.1 测试用例",
                "",
                "Table: 用例表 {#tbl-case}",
                "",
                "| 用例 | 预期 |",
                "| --- | --- |",
                "| T1 | 可打开 |",
                "",
                "参见 @tbl-case 与 @tbl-missing。",
                "",
                "<!-- PAGEBREAK -->",
                "",
                "## 1.2 结果",
                "",
                "第二页内容。",
                "",
            ]
        ),
    },
}

TAB_RETURN = "\treturn 'ok'"


#: 样本类型 -> 清单文档类型。清单只接受 general/requirement/design，
#: 「测试说明书」按通用大文档内核出稿（与 V2.6 一致）。
MANIFEST_TYPE = {"requirement": "requirement", "design": "design", "test": "general"}


def _style_map_for(template_path: pathlib.Path) -> dict:
    """从模板 ``styles.xml`` 推导标题/正文样式映射。

    V2.7 样本此前**硬编码**了一套 styleId，但与 ``design-template.docx``
    不一致（实测：级别2 写成 ``3``，而 ``3`` 实为 ``Normal Indent``），
    导致标题渲染成列表项。这里改为**从模板真实样式推导**。
    """
    import re as _re
    import zipfile as _zipfile

    with _zipfile.ZipFile(template_path) as archive:
        styles = archive.read("word/styles.xml").decode("utf-8", errors="replace")
    entries = []
    for match in _re.finditer(r'<w:style [^>]*w:styleId="([^"]+)"[^>]*>(.*?)</w:style>', styles, _re.S):
        style_id, body = match.group(1), match.group(2)
        if 'w:type="paragraph"' not in match.group(0):
            continue
        name = _re.search(r'<w:name w:val="([^"]*)"', body)
        entries.append((style_id, (name.group(1) if name else "").strip()))
    heading = {}
    for style_id, name in entries:
        match = _re.match(r"(?i)heading\s*([1-6])$", name)
        if match and int(match.group(1)) not in heading:
            heading[int(match.group(1))] = style_id
    if not heading:
        heading = {1: "2", 2: "3", 3: "5", 4: "6", 5: "7", 6: "8"}
    body = ""
    for style_id, name in entries:
        if name.casefold() == "body text":
            body = style_id
            break
    if not body:
        body = next((sid for sid, name in entries if name.casefold() == "normal"), "")
    return {"headingStyles": heading, "bodyStyle": body}


def _template_file(name: str) -> pathlib.Path:
    """模板位置：优先仓库 ``templates/``，回退到随包资源。"""
    candidate = ROOT / "templates" / name
    if candidate.is_file():
        return candidate
    return ROOT / "doc_tool" / "resources" / name


STYLE_MAPS = {
    doc_type: _style_map_for(_template_file(name))
    for doc_type, name in (
        ("requirement", "requirement-template.docx"),
        ("design", "design-template.docx"),
        ("test", "generic-template.docx"),
    )
}


def _make_project(root: Path, doc_type: str, sample: dict) -> Path:
    project = root / doc_type
    content = project / "content"
    content.mkdir(parents=True)
    (project / "assets" / "tables").mkdir(parents=True)
    (project / "template").mkdir(parents=True)
    # 每类样本用对应底模：需求/设计用各自模板，测试样本走通用大文档模板。
    template_name = {
        "requirement": "requirement-template.docx",
        "design": "design-template.docx",
        "test": "generic-template.docx",
    }.get(doc_type, "generic-template.docx")
    template_source = ROOT / "templates" / template_name
    if not template_source.is_file():
        template_source = ROOT / "doc_tool" / "resources" / template_name
    shutil.copy2(template_source, project / "template" / "template.docx")
    (content / "1 样本.md").write_text(sample["body"], encoding="utf-8")
    manifest = ProjectManifest(
        documentType=MANIFEST_TYPE.get(doc_type, "general"),
        documentNo="GX-V27-{0}".format(doc_type.upper()[:4]),
        documentName=sample["title"],
        documentVersion="1.0",
        sourceSha256="",
        paths={
            "sourceDocx": "original/source.docx",
            "templateDocx": "template/template.docx",
            "contentRoot": "content",
            "assetRoot": "assets",
            "tableRoot": "assets/tables",
        },
        headingStyles=STYLE_MAPS[doc_type]["headingStyles"],
        bodyStyle=STYLE_MAPS[doc_type]["bodyStyle"],
    )
    manifest.save(str(project))
    return project


def main() -> int:
    results = []
    root = Path(tempfile.mkdtemp(prefix="v27-samples-"))
    try:
        for doc_type, sample in SAMPLES.items():
            project = _make_project(root, doc_type, sample)
            record = {"documentType": doc_type, "project": str(project)}
            from doc_tool.application.pipeline import run_pipeline

            manifest = ProjectManifest.load(str(project))
            paths = manifest.resolve_paths(str(project))
            pipeline = run_pipeline(manifest, paths, skip_word_refresh=True)
            record["pipelineSuccess"] = pipeline.success
            record["pipelineStages"] = [
                {"stage": event.stage, "status": event.status, "detail": event.detail or ""}
                for event in pipeline.events
            ]
            record["outputPath"] = pipeline.output_path
            record["pendingRefreshPath"] = None
            record["wordRefresh"] = "skipped (无 Word 实机验收条件时如实标记)"
            if not pipeline.success:
                record["errorCode"] = pipeline.error_code
                # 失败时把真实校验报告拷到证据目录，避免只有结论没有原因。
                report_path = paths.logs_dir / "{0}-validation.md".format(
                    manifest.documentType
                )
                if report_path.is_file():
                    target_report = EVIDENCE / "v27-sample-{0}-validation.md".format(doc_type)
                    shutil.copy2(str(report_path), str(target_report))
                    record["validationReport"] = str(target_report)
                results.append(record)
                continue

            from doc_tool.application.check import run_check

            report = run_check(project, fail_on="error", strict=False)
            record["checkStatus"] = report.status
            record["checkExitCode"] = report.exit_code
            record["checkIssues"] = [
                {
                    "type": issue.issue_type,
                    "severity": issue.severity,
                    "file": issue.rel_path,
                    "line": issue.line_no,
                    "message": issue.message,
                }
                for issue in report.sorted_issues()
            ]
            record["checkStages"] = [
                {"stage": stage.stage, "status": stage.status} for stage in report.stages
            ]
            results.append(record)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    payload = {
        "appVersion": "2.7.0",
        "note": "无 Word 环境下的诊断出稿；真实 Word 刷新与人工版式为待验收。",
        "samples": results,
    }
    target = EVIDENCE / "v27-samples.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已生成", target)
    for record in results:
        print(
            "  {0}: pipeline={1} check={2} exit={3} issues={4}".format(
                record["documentType"],
                record.get("pipelineSuccess"),
                record.get("checkStatus", "-"),
                record.get("checkExitCode", "-"),
                len(record.get("checkIssues", [])),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
