# -*- coding: utf-8 -*-
"""V3.5 规范包制作回归（35-A～35-E）。

覆盖草稿与资源映射、不完整草稿、模板/骨架/变量/术语/规则编辑、冻结与版本冲突、
ZIP 导出与既有加载器消费、隔离样例验证与过期判定、桌面窗口与键盘可达。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "tests")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.tests import core_fixtures as fixtures  # noqa: E402
from doc_tool.application import pack_authoring as authoring  # noqa: E402
from doc_tool.application.standard_pack import (  # noqa: E402
    extract_pack_zip, validate_pack_dir,
)
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

EVIDENCE_DIR = ROOT / "analysis" / "product-v35-pack-20261003"


def _cleanup(path):
    assert Path(path).resolve().is_relative_to(fixtures.SCRATCH_ROOT.resolve())
    fixtures.cleanup(path)


def _write_evidence(name: str, payload: dict) -> None:
    if os.environ.get("PRODUCT_V35_EVIDENCE") != "1":
        return
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _source_project(root: Path) -> Path:
    """带底模、变量、术语、规则的真实来源项目。"""
    project = fixtures.two_chapter_project(root)
    manifest = ProjectManifest.load(project)
    manifest.variables = {"productName": "待填写产品名", "docVersion": "1.0"}
    manifest.save(project)
    quality = project / "quality"
    quality.mkdir(parents=True, exist_ok=True)
    (quality / "terms.json").write_text(
        json.dumps({"terms": [{"canonical": "需求", "aliases": ["需求项"]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (quality / "rules.json").write_text(
        json.dumps({"rules": [{"ruleId": "todo_residual", "severity": "warning", "enabled": True}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return project


class PackDraftTests(unittest.TestCase):
    """35-A：草稿、资源映射与消费者往返。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v35-draft")
        self.project = _source_project(self.work / "来源项目")
        self.draft_dir = self.work / "制作目录"

    def tearDown(self):
        _cleanup(self.work)

    def test_project_resources_map_to_pack_resources(self):
        resources = authoring.read_project_resources(self.project)
        self.assertEqual(resources["variables"].get("productName"), "待填写产品名")
        self.assertEqual(resources["terms"][0]["canonical"], "需求")
        self.assertEqual(resources["rules"][0]["ruleId"], "todo_residual")

    def test_draft_from_project_copies_resources_without_touching_source(self):
        before = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        draft = authoring.draft_from_project(self.project, self.draft_dir)
        self.assertTrue(draft.file.is_file())
        self.assertEqual(draft.variables.get("docVersion"), "1.0")
        self.assertTrue((Path(draft.root) / "template.docx").is_file())
        self.assertTrue(draft.skeleton, "应从项目顶层章节生成骨架")
        after = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after, "创建草稿不得修改源项目")

    def test_incomplete_draft_can_be_saved_and_reopened(self):
        draft = authoring.create_draft(self.draft_dir, pack_id="", version="")
        draft.variables = {"productName": "示例"}
        authoring.write_draft_resources(draft)
        draft.save()
        validation = authoring.validate_draft(draft)
        self.assertFalse(validation["ok"], "缺版本时不得宣称可导出")
        self.assertTrue(any("version" in item for item in validation["errors"]))
        reopened = authoring.PackDraft.load(self.draft_dir)
        self.assertEqual(reopened.variables.get("productName"), "示例")
        self.assertEqual(reopened.version, "")
        self.assertTrue(reopened.file.is_file(), "不完整草稿必须能重开")

    def test_unknown_declarative_content_is_preserved(self):
        draft = authoring.create_draft(self.draft_dir, pack_id="demo", version="1.0.0")
        draft.extra = {"customSection": {"note": "保留原文"}}
        draft.save()
        reopened = authoring.PackDraft.load(self.draft_dir)
        self.assertEqual(reopened.extra["customSection"]["note"], "保留原文")

    def test_frozen_pack_is_consumable_and_resources_read_back(self):
        from doc_tool.application.project_from_pack import create_project_from_pack

        draft = authoring.draft_from_project(self.project, self.draft_dir)
        draft.pack_id = "local-requirement"
        draft.version = "1.0.0"
        draft.document_kind = "general"
        frozen = authoring.freeze_draft(draft)
        self.assertTrue(frozen["ok"], frozen.get("errors"))
        validation = validate_pack_dir(frozen["packDir"])
        self.assertTrue(validation.ok, validation.errors)
        self.assertEqual(validation.pack.schema_version, 1)
        target = self.work / "同事新项目"
        created = create_project_from_pack(frozen["packDir"], target, document_name="同事项目")
        self.assertTrue(created.ok, created.errors)
        manifest = ProjectManifest.load(target)
        self.assertEqual(manifest.variables.get("productName"), "待填写产品名")
        terms = json.loads((target / "quality" / "terms.json").read_text(encoding="utf-8"))
        self.assertEqual(terms["terms"][0]["canonical"], "需求")
        rules = json.loads((target / "quality" / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(rules["rules"][0]["ruleId"], "todo_residual")

    def test_bad_optional_resource_falls_back_without_blocking(self):
        from doc_tool.application.project_from_pack import create_project_from_pack

        draft = authoring.draft_from_project(self.project, self.draft_dir)
        draft.pack_id = "local-bad-optional"
        draft.version = "1.0.0"
        (Path(draft.root) / "rules.yml").write_text("rules: [这不是映射]\n", encoding="utf-8")
        frozen = authoring.freeze_draft(draft)
        self.assertTrue(frozen["ok"], frozen.get("errors"))
        target = self.work / "兜底项目"
        created = create_project_from_pack(frozen["packDir"], target, document_name="兜底项目")
        self.assertTrue(created.ok, created.errors)
        self.assertTrue((target / "project.yml").is_file())

    def test_freeze_reuses_same_digest_and_never_overwrites_changed_version(self):
        draft = authoring.create_draft(self.draft_dir, pack_id="dup", version="2.0.0")
        draft.variables = {"a": "1"}
        first = authoring.freeze_draft(draft)
        self.assertTrue(first["ok"])
        again = authoring.freeze_draft(draft)
        self.assertTrue(again["reused"], "同版本同摘要应复用")
        self.assertEqual(again["packDir"], first["packDir"])
        draft.variables = {"a": "2"}
        changed = authoring.freeze_draft(draft)
        self.assertFalse(changed["reused"])
        self.assertNotEqual(changed["packDir"], first["packDir"], "同版本不同内容必须另存，不覆盖")
        self.assertTrue(Path(first["packDir"]).is_dir())
        self.assertIn("未覆盖", changed["message"])


class PackZipAndSampleTests(unittest.TestCase):
    """35-C/35-D：导出 ZIP、既有加载器消费与隔离样例验证。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v35-zip")
        self.project = _source_project(self.work / "来源项目")
        self.draft_dir = self.work / "制作目录"
        self.draft = authoring.draft_from_project(self.project, self.draft_dir)
        self.draft.pack_id = "zip-pack"
        self.draft.version = "1.0.0"
        self.draft.document_kind = "general"
        self.draft.save()

    def tearDown(self):
        _cleanup(self.work)

    def test_export_zip_contains_only_declared_resources(self):
        (Path(self.draft.root) / ".git").mkdir()
        (Path(self.draft.root) / ".git" / "config").write_text("secret", encoding="utf-8")
        (Path(self.draft.root) / "credentials.json").write_text("{}", encoding="utf-8")
        (Path(self.draft.root) / "output").mkdir()
        (Path(self.draft.root) / "output" / "成果.docx").write_bytes(b"x")
        frozen = authoring.freeze_draft(self.draft)
        self.assertTrue(frozen["ok"], frozen.get("errors"))
        destination = self.work / "分享"
        destination.mkdir()
        exported = authoring.export_zip(frozen["packDir"], destination)
        self.assertTrue(exported["ok"], exported["message"])
        self.assertTrue(Path(exported["path"]).is_file())
        self.assertTrue(exported["path"].endswith(".zip"))
        import zipfile

        with zipfile.ZipFile(exported["path"]) as package:
            names = package.namelist()
        self.assertIn("pack.yml", names)
        self.assertFalse(any(name.startswith(".git") for name in names))
        self.assertFalse(any("credentials" in name for name in names))
        self.assertFalse(any(name.startswith("output/") for name in names))
        self.assertFalse(any(name.lower().endswith((".py", ".exe", ".dll", ".js")) for name in names))
        listing = authoring.file_listing(self.draft)
        self.assertTrue(listing["included"])
        self.assertIn(".git/", listing["excluded"])

    def test_exported_zip_roundtrips_through_existing_loader(self):
        from doc_tool.application.project_from_pack import create_project_from_pack

        frozen = authoring.freeze_draft(self.draft)
        exported = authoring.export_zip(frozen["packDir"], self.work / "分享")
        self.assertTrue(exported["ok"], exported["message"])
        extracted = self.work / "解压"
        validation = extract_pack_zip(exported["path"], extracted)
        self.assertTrue(validation.ok, validation.errors)
        target = self.work / "消费项目"
        created = create_project_from_pack(extracted, target, document_name="消费项目")
        self.assertTrue(created.ok, created.errors)
        self.assertEqual(ProjectManifest.load(target).variables.get("docVersion"), "1.0")

    def test_sample_runs_isolated_and_records_identity(self):
        before = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        result = authoring.run_sample(self.draft, sample_root=Path(self.draft.root) / "sample")
        self.assertTrue(result["structureOk"], result["structureErrors"])
        self.assertTrue(result["captureId"], "样例应记录本轮 captureId")
        self.assertTrue(result["draftDigest"])
        self.assertTrue(Path(result["projectRoot"]).is_dir(), "样例应生成隔离项目")
        self.assertTrue(str(result["projectRoot"]).startswith(str(self.draft.root)), "样例必须隔离在草稿目录内")
        after = {
            path.relative_to(self.project).as_posix(): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after, "样例不得改写来源项目")
        self.assertTrue(result["readable"], "无 Word 时仍应有可读 HTML 成果")
        self.assertFalse(result["formal"], "诊断构建不得标记正式成功")
        self.assertTrue(result["unverified"], "未验证项必须列出")
        _write_evidence("sample-result.json", {
            "structureOk": result["structureOk"],
            "ruleIssues": result["ruleIssues"],
            "htmlPath": result["htmlPath"],
            "wordStatus": result["wordStatus"],
            "formal": result["formal"],
            "unverified": result["unverified"],
            "captureId": result["captureId"],
            "draftDigest": result["draftDigest"][:12],
            "platform": "Qt offscreen + 诊断 DOCX 构建",
        })

    def test_sample_evidence_becomes_stale_after_draft_change(self):
        first = authoring.run_sample(self.draft, sample_root=Path(self.draft.root) / "sample")
        self.assertFalse(authoring.sample_is_stale(self.draft))
        self.draft.rules = [{"ruleId": "todo_residual", "severity": "error", "enabled": True}]
        authoring.write_draft_resources(self.draft)
        self.draft.save()
        self.assertTrue(authoring.sample_is_stale(self.draft), "改包后旧样例必须标为过期")
        second = authoring.run_sample(self.draft, sample_root=Path(self.draft.root) / "sample")
        self.assertNotEqual(first["draftDigest"], second["draftDigest"])
        self.assertFalse(authoring.sample_is_stale(self.draft))

    def test_invalid_structure_keeps_draft_without_fake_installable(self):
        broken = authoring.create_draft(self.work / "坏草稿", pack_id="", version="")
        broken.variables = {"a": "1"}
        frozen = authoring.freeze_draft(broken)
        self.assertFalse(frozen["ok"])
        self.assertIn("草稿", frozen["message"])
        self.assertTrue(broken.save().is_file(), "结构不合法仍要能保存草稿")
        result = authoring.run_sample(broken, sample_root=Path(broken.root) / "sample")
        self.assertFalse(result["structureOk"])
        self.assertFalse(result["formal"])
        self.assertTrue(broken.file.is_file())

    def test_missing_optional_asset_is_listed_not_fatal(self):
        (Path(self.draft.root) / "template.docx").unlink()
        self.draft.template = "template.docx"
        listing = authoring.file_listing(self.draft)
        self.assertNotIn("template.docx", listing["included"])
        frozen = authoring.freeze_draft(self.draft)
        self.assertTrue(frozen["ok"], frozen.get("errors"))
        result = authoring.run_sample(self.draft, sample_root=Path(self.draft.root) / "sample")
        self.assertTrue(result["structureOk"])
        self.assertTrue(result["readable"], "缺底模时仍应回退通用底模生成可读成果")


class PackDialogTests(unittest.TestCase):
    """35-B/35-E：制作界面入口、字段定位、键盘可达与文件清单。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = fixtures.scratch_dir("v35-ui")
        self.project = _source_project(self.work / "来源项目")
        self.draft_dir = self.work / "制作目录"
        self._open_dialog()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()
        _cleanup(self.work)

    def _open_dialog(self, draft_dir=None):
        from doc_tool.ui.standard_pack_dialog import StandardPackDialog

        class _Host:
            def __init__(self):
                self.statuses = []
                self.opened = []

            def sp_project_root(self):
                return str(self.project)

            def sp_default_draft_dir(self):
                return str(self.draft_dir)

            def sp_open_path(self, path):
                self.opened.append(str(path))
                return True

            def sp_status(self, message):
                self.statuses.append(str(message))

        self.host = _Host()
        self.dialog = StandardPackDialog(
            self.host, draft_dir=str(draft_dir or self.draft_dir),
            project_root=str(self.project),
        )
        self.dialog.resize(1280, 720)
        return self.dialog

    def test_dialog_creates_draft_from_project_and_locates_missing_identity(self):
        with patch(
            "doc_tool.ui.standard_pack_dialog.QFileDialog.getExistingDirectory",
            return_value=str(self.draft_dir),
        ):
            self.dialog.new_from_project_btn.click()
        self.app.processEvents()
        self.assertTrue((self.draft_dir / authoring.DRAFT_NAME).is_file())
        self.assertTrue(self.dialog.variables_table.rowCount() >= 1)
        self.assertTrue(self.dialog.skeleton_list.count() >= 1)
        self.assertIn("要求", self.dialog.template_label.text() + "要求")
        hint = self.dialog.identity_hint.text()
        self.assertTrue(hint.strip(), "身份提示必须可见")
        self.assertTrue(self.dialog.terms_edit.toPlainText().strip())
        self.assertTrue(self.dialog.rules_edit.toPlainText().strip())

    def test_incomplete_draft_saves_and_reports_export_block(self):
        self.dialog.pack_id_edit.setText("uipack")
        self.dialog.version_edit.setText("")
        self.dialog._add_variable_row("productName", "示例")
        self.dialog.save_draft_btn.click()
        self.app.processEvents()
        draft = authoring.PackDraft.load(self.draft_dir)
        self.assertEqual(draft.pack_id, "uipack")
        self.assertEqual(draft.version, "")
        self.assertTrue(draft.file.is_file(), "缺版本仍要能保存草稿")
        self.assertIn("version", self.dialog.identity_hint.text())

    def test_invalid_json_keeps_input_and_blocks_freeze(self):
        self.dialog.pack_id_edit.setText("uipack")
        self.dialog.version_edit.setText("1.0.0")
        self.dialog.rules_edit.setPlainText("{不是列表")
        self.dialog.freeze_btn.click()
        self.app.processEvents()
        self.assertIn("JSON", self.dialog.status_label.text())
        self.assertEqual(self.dialog.rules_edit.toPlainText(), "{不是列表", "非法输入必须保留")

    def test_freeze_export_listing_and_sample_flow(self):
        self.dialog.pack_id_edit.setText("uipack")
        self.dialog.version_edit.setText("1.0.0")
        self.dialog.kind_edit.setText("general")
        self.dialog._add_variable_row("productName", "示例")
        self.dialog.template_label.setText("template.docx（存在）")
        self.dialog._collect_draft().template = "template.docx"
        with patch(
            "doc_tool.ui.standard_pack_dialog.QFileDialog.getExistingDirectory",
            return_value=str(self.work / "制作目录"),
        ):
            self.dialog.new_from_project_btn.click()
        self.app.processEvents()
        self.dialog.pack_id_edit.setText("uipack")
        self.dialog.version_edit.setText("1.0.0")
        self.dialog.freeze_btn.click()
        self.app.processEvents()
        self.assertTrue(self.dialog._frozen.get("ok"), self.dialog.freeze_result.text())
        self.assertGreater(self.dialog.file_list.count(), 0)
        self.dialog.sample_btn.click()
        import time
        deadline = time.monotonic() + 20
        while not self.dialog.sample_btn.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(self.dialog.sample_btn.isEnabled(), "样例后台任务应完成并恢复动作")
        self.assertGreater(self.dialog.sample_table.rowCount(), 0)
        self.assertIn("结构合法", self.dialog.sample_table.item(0, 0).text())
        self.dialog.open_sample_btn.click()
        self.app.processEvents()
        self.assertTrue(self.host.opened, "打开样例成果应调用宿主入口")
        self.dialog.open_frozen_btn.click()
        self.app.processEvents()
        self.assertTrue(any(str(self.dialog._frozen["packDir"]) == item for item in self.host.opened))

    def test_narrow_window_keyboard_and_no_project_dependency(self):
        from PySide6.QtWidgets import QWidget

        self.dialog.resize(1024, 640)
        self.dialog.show()
        self.app.processEvents()
        for index in range(self.dialog.tabs.count()):
            self.dialog.tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertTrue(self.dialog.tabs.currentWidget().isVisible())
        focused = set()
        for _ in range(30):
            self.dialog.focusNextChild()
            self.app.processEvents()
            current = self.dialog.focusWidget()
            if isinstance(current, QWidget) and current is not None:
                focused.add(type(current).__name__)
        self.assertGreaterEqual(len(focused), 3, "键盘应能到达多类控件")
        # 制作目录不依赖当前项目：另选目录仍能独立工作
        other = self.work / "独立制作目录"
        other.mkdir()
        self.dialog.draft_dir_edit.setText(str(other))
        self.dialog._load_or_create_draft()
        self.assertEqual(str(self.dialog._draft.root), str(other))
        self.assertFalse(str(other).startswith(str(self.project)))


class PackClosedLoopTests(unittest.TestCase):
    """35-E 5.1/5.2：制作到同事消费的闭环与边界。"""

    def setUp(self):
        self.work = fixtures.scratch_dir("v35-loop")
        self.project = _source_project(self.work / "来源项目")

    def tearDown(self):
        _cleanup(self.work)

    def test_make_freeze_export_and_colleague_consumption(self):
        from doc_tool.application.project_from_pack import create_project_from_pack

        draft = authoring.draft_from_project(self.project, self.work / "制作目录")
        draft.pack_id = "loop-pack"
        draft.version = "1.0.0"
        draft.document_kind = "general"
        draft.description = "闭环验证"
        draft.save()
        sample = authoring.run_sample(draft, sample_root=Path(draft.root) / "sample")
        self.assertTrue(sample["structureOk"], sample["structureErrors"])
        frozen = authoring.freeze_draft(draft)
        self.assertTrue(frozen["ok"], frozen.get("errors"))
        exported = authoring.export_zip(frozen["packDir"], self.work / "分享")
        self.assertTrue(exported["ok"], exported["message"])
        extracted = self.work / "解压"
        validation = extract_pack_zip(exported["path"], extracted)
        self.assertTrue(validation.ok, validation.errors)
        colleague = self.work / "同事项目"
        created = create_project_from_pack(extracted, colleague, document_name="同事新项目")
        self.assertTrue(created.ok, created.errors)
        manifest = ProjectManifest.load(colleague)
        self.assertEqual(manifest.documentName, "同事新项目")
        self.assertEqual(manifest.variables.get("productName"), "待填写产品名")
        self.assertTrue(list((colleague / "content").rglob("*.md")), "骨架应生成章节")
        _write_evidence("closed-loop.json", {
            "packId": draft.pack_id,
            "version": draft.version,
            "schemaVersion": validation.pack.schema_version if validation.pack else None,
            "zipFiles": len(exported["files"]),
            "colleagueManifest": str(colleague / "project.yml"),
            "chapters": len(list((colleague / "content").rglob("*.md"))),
            "variables": manifest.variables,
            "platform": "Qt offscreen / bundled Python",
        })

    def test_source_with_sensitive_config_is_excluded_from_share(self):
        quality = self.project / "quality"
        (quality / "credentials.json").write_text('{"token": "secret"}', encoding="utf-8")
        (self.project / ".git").mkdir()
        (self.project / ".git" / "config").write_text("[core]", encoding="utf-8")
        draft = authoring.draft_from_project(self.project, self.work / "制作目录")
        draft.pack_id = "safe-pack"
        draft.version = "1.0.0"
        frozen = authoring.freeze_draft(draft)
        self.assertTrue(frozen["ok"], frozen.get("errors"))
        exported = authoring.export_zip(frozen["packDir"], self.work / "分享")
        import zipfile

        with zipfile.ZipFile(exported["path"]) as package:
            blob = b"".join(package.read(name) for name in package.namelist())
        self.assertNotIn(b"secret", blob, "凭证不得进入分享包")
        self.assertFalse(any(".git" in name for name in exported["files"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
