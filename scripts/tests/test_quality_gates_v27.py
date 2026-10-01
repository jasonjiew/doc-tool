# -*- coding: utf-8 -*-
"""发布质量门禁与产物终审（V2.7 27-F / 6.1、6.3、6.4、6.6）。

覆盖：默认策略不拦截、严格策略才拦截、真实域错误与代码示例区分、
占位/超宽表发现、终审只读且不改变产物。
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from doc_tool.application.quality_gates import (  # noqa: E402
    RULE_BODY_PLACEHOLDER,
    RULE_FIELD_ERROR,
    RULE_TABLE_OVERWIDE,
    audit_docx,
    audit_policy,
)

TEMPLATE = REPO_ROOT / "templates" / "requirement-template.docx"
NL = chr(10)


def _build_project(root: Path, markdown: str) -> Path:
    """构造最小项目并构建，返回产物路径。"""
    from build_docx import build

    project = root / "project"
    (project / "content").mkdir(parents=True)
    (project / "assets" / "tables").mkdir(parents=True)
    (project / "template").mkdir(parents=True)
    shutil.copy2(TEMPLATE, project / "template" / "template.docx")
    (project / "content" / "1 内容.md").write_text(markdown, encoding="utf-8")
    config = {
        "documentType": "general",
        "documentNo": "GX-AUDIT-001",
        "documentName": "终审契约",
        "documentVersion": "1.0",
        "paths": {
            "template": str(project / "template" / "template.docx"),
            "content_root": str(project / "content"),
            "asset_root": str(project / "assets"),
            "table_root": str(project / "assets" / "tables"),
            "output": str(project / "output" / "终审(1.0).docx"),
        },
        "headingStyles": {1: "1", 2: "2", 3: "3"},
        "bodyStyle": "a",
    }
    output = Path(build(config=config))
    _LAST_TEMPLATE[0] = config["paths"]["template"]
    return output


#: 最近一次`_build_project` 使用的模板路径（供审查过滤模板自带元素）。
_LAST_TEMPLATE = [""]


def _audit(output, **kwargs):
    """对产物执行终审，默认传入模板路径以排除模板自带元素。"""
    from doc_tool.application.quality_gates import audit_docx

    kwargs.setdefault("template_path", _LAST_TEMPLATE[0] or None)
    return audit_docx(output, **kwargs)


class AuditPolicyTests(unittest.TestCase):
    """策略：默认带提醒继续，严格交付才拦截。"""

    def test_default_policy_never_blocks(self):
        for rule in (RULE_FIELD_ERROR, RULE_BODY_PLACEHOLDER, RULE_TABLE_OVERWIDE):
            self.assertFalse(audit_policy(False).blocks(rule))
            self.assertTrue(audit_policy(True).blocks(rule))

    def test_report_status_reflects_worst_severity(self):
        from doc_tool.application.quality_gates import AuditFinding, AuditReport

        default = AuditReport(
            findings=[
                AuditFinding(rule=RULE_FIELD_ERROR, message="x", severity="warning")
            ],
            policy=audit_policy(False),
        )
        self.assertEqual(default.status, "warning")
        self.assertFalse(default.blocked)
        strict = AuditReport(
            findings=[
                AuditFinding(rule=RULE_FIELD_ERROR, message="x", severity="error")
            ],
            policy=audit_policy(True),
        )
        self.assertEqual(strict.status, "blocked")
        self.assertTrue(strict.blocked)

    def test_findings_map_to_issue_records(self):
        from doc_tool.application.quality_gates import AuditFinding, AuditReport

        report = AuditReport(
            findings=[
                AuditFinding(
                    rule=RULE_BODY_PLACEHOLDER,
                    message="正文仍有占位",
                    severity="warning",
                    location="body[7]",
                )
            ],
            policy=audit_policy(False),
        )
        records = report.issues(document_type="general")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].severity, "warning")
        self.assertIn(RULE_BODY_PLACEHOLDER, records[0].issue_type)
        self.assertIn("占位", records[0].message)


class DocxAuditTests(unittest.TestCase):
    """STAGE_AUDIT 对真实产物的检查。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v27-audit-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_clean_document_has_no_findings(self):
        output = _build_project(
            self.root,
            NL.join(["## 1.1 正文", "", "正常段落。", ""]),
        )
        report = _audit(output)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.status, "ok")
        self.assertIn("未发现问题", report.markdown_text())

    def test_body_placeholder_reported_but_code_example_ignored(self):
        output = _build_project(
            self.root,
            NL.join(
                [
                    "## 1.1 占位",
                    "",
                    "本章待补充。",
                    "",
                    "```python",
                    "# TODO: 代码示例里的占位不算作者遗留",
                    "print('TODO')",
                    "```",
                    "",
                ]
            ),
        )
        report = _audit(output)
        placeholder = [f for f in report.findings if f.rule == RULE_BODY_PLACEHOLDER]
        self.assertEqual(len(placeholder), 1, [f.to_dict() for f in report.findings])
        self.assertIn("待补充", placeholder[0].message)

    def test_field_error_detected_but_not_from_code_literal(self):
        """真实域错误被捕获；代码示例里的同名字符串不算。"""
        from doc_tool.adapters.word_convert import _apply_word_layout  # noqa: F401  (仅确认常量源)

        output = _build_project(
            self.root,
            NL.join(
                [
                    "## 1.1 域",
                    "",
                    "```text",
                    "Error! 未定义书签。",
                    "```",
                    "",
                ]
            ),
        )
        clean = _audit(output)
        self.assertEqual(
            [f for f in clean.findings if f.rule == RULE_FIELD_ERROR],
            [],
            "代码示例里的字符串不得被当成真实域错误",
        )

        # 手工注入一个域缓存结果为错误文本的段落，模拟 Word 刷新后的真实错误。
        corrupted = self.root / "corrupted.docx"
        _inject_field_error(output, corrupted)
        report = audit_docx(corrupted)
        self.assertTrue(
            any(f.rule == RULE_FIELD_ERROR for f in report.findings),
            [f.to_dict() for f in report.findings],
        )

    def test_overwide_table_reported(self):
        """列数过多导致每列被压到不可读时应报超宽。

        构建内核会把超宽表按版心缩放，因此这里构造的是“缩完也读不清”
        的极窄多列表（逐列宽度取自元数据，不依赖默认 2400）。
        """
        count = 40
        columns = " | ".join("C{0}".format(i) for i in range(1, count + 1))
        separator = " | ".join("---" for _ in range(count))
        values = " | ".join("1" for _ in range(count))
        width = ",".join(["1000"] * count)
        meta = "<!-- TBL:style= type=dxa tw={0} cols={1} -->".format(
            1000 * count, width
        )
        output = _build_project(
            self.root,
            NL.join(
                [
                    "## 1.1 宽表",
                    "",
                    meta,
                    "| " + columns + " |",
                    "| " + separator + " |",
                    "| " + values + " |",
                    "",
                ]
            ),
        )
        report = _audit(output)
        self.assertTrue(
            any(f.rule == RULE_TABLE_OVERWIDE for f in report.findings),
            [f.to_dict() for f in report.findings],
        )

    def test_audit_is_read_only(self):
        output = _build_project(
            self.root,
            NL.join(["## 1.1 正文", "", "正常。", ""]),
        )
        before = hashlib.sha256(output.read_bytes()).hexdigest()
        _audit(output, policy=audit_policy(True))
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before)

    def test_report_serializes_for_machine_output(self):
        output = _build_project(
            self.root,
            NL.join(["## 1.1 正文", "", "TODO：补充", ""]),
        )
        report = _audit(output)
        data = report.to_dict()
        self.assertEqual(data["status"], "warning")
        self.assertIn("counts", data)
        self.assertTrue(data["findings"])


def _inject_field_error(source: Path, target: Path) -> None:
    """把产物里第一个非空段落的文本换成“错误！未定义书签”。"""
    import zipfile

    from docx_common import parse_xml_safe
    from lxml import etree

    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(source) as package:
        names = package.namelist()
        payload = {name: package.read(name) for name in names}
    document = parse_xml_safe(payload["word/document.xml"], "word/document.xml")
    body = document.find(w + "body")
    injected = False
    for paragraph in body.findall(w + "p"):
        texts = [node for node in paragraph.iter(w + "t")]
        if not texts:
            continue
        if not injected:
            # 只保留第一个非空段落的错误文本，
            # 其余段落清空，避免模板自带的页眉/目录文本引入噪声。
            texts[0].text = "Error! 未定义书签。"
            for extra in texts[1:]:
                extra.text = ""
            injected = True
            continue
        for node in texts:
            node.text = ""
        for run in paragraph.findall(w + "r"):
            paragraph.remove(run)
    payload["word/document.xml"] = etree.tostring(
        document, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in payload.items():
            package.writestr(name, data)


if __name__ == "__main__":
    unittest.main()