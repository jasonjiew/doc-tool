# -*- coding: utf-8 -*-
"""Word can renumber styles to IDs previously used by other styles."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_word_compatibility_audit import _make_minimal_docx, W_NS
from validate_docx import DocxPackage


class RefreshedStyleMappingTests(unittest.TestCase):
    def test_renumbering_preserves_heading_levels_and_body_style(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def styles(body_id, heading_id, custom_id):
                return f'''<w:styles xmlns:w="{W_NS}">
                    <w:style w:type="paragraph" w:styleId="{body_id}"><w:name w:val="Normal"/></w:style>
                    <w:style w:type="paragraph" w:styleId="{heading_id}"><w:name w:val="heading 1"/></w:style>
                    <w:style w:type="paragraph" w:styleId="{custom_id}"><w:name w:val="Custom chapter"/></w:style>
                </w:styles>'''

            template = _make_minimal_docx(root / "template.docx", "", styles("1", "2", "3"))
            body = '''<w:p><w:pPr><w:pStyle w:val="1"/></w:pPr><w:r><w:t>Chapter</w:t></w:r></w:p>
                <w:p><w:pPr><w:pStyle w:val="n"/></w:pPr><w:r><w:t>Body</w:t></w:r></w:p>
                <w:p><w:pPr><w:pStyle w:val="2"/></w:pPr><w:r><w:t>Custom</w:t></w:r></w:p>'''
            output = _make_minimal_docx(root / "output.docx", body, styles("n", "1", "2"))
            package = DocxPackage(str(output))
            package.remap_template_styles(DocxPackage(str(template)), {1: "2", 2: "3"}, "1")
            self.assertEqual([(event.kind, event.value) for event in package.body_events()], [
                ("H", (1, "Chapter")), ("P", "Body"), ("H", (2, "Custom")),
            ])


class FormalTocTests(unittest.TestCase):
    def test_formal_build_defers_cache_but_diagnostic_keeps_policy(self):
        import test_project_build as fixtures
        from doc_tool.adapters import kernel
        from doc_tool.application.pipeline import run_pipeline
        from doc_tool.domain.merge_policy import MergePolicy

        with tempfile.TemporaryDirectory() as directory:
            root = fixtures._setup_project(directory)
            manifest = fixtures._make_manifest(root)
            paths = manifest.resolve_paths(root)
            policy = MergePolicy(synthesize_static_fields=True, auto_shift_inline_headings=True)
            with mock.patch.object(kernel, "build_with_project", wraps=kernel.build_with_project) as build:
                result = run_pipeline(manifest, paths, skip_word_refresh=True, merge_policy=policy)
                self.assertTrue(result.success)
                self.assertIs(build.call_args.kwargs["merge_policy"], policy)
            with mock.patch.object(kernel, "build_with_project", wraps=kernel.build_with_project) as build:
                with mock.patch.object(kernel, "refresh_with_project", return_value=(False, "word_unavailable")):
                    result = run_pipeline(manifest, paths, word_available=True, merge_policy=policy)
                self.assertFalse(result.success)
                applied = build.call_args.kwargs["merge_policy"]
                self.assertFalse(applied.synthesize_static_fields)
                self.assertTrue(applied.auto_shift_inline_headings)
                self.assertTrue(policy.synthesize_static_fields)

    def test_legacy_formal_pipeline_defers_cache_only_when_refreshing(self):
        import run_pipeline as legacy

        for diagnostic in (False, True):
            with self.subTest(diagnostic=diagnostic):
                with mock.patch.object(legacy, "run_step", return_value=True) as step:
                    self.assertTrue(legacy.pipeline("requirement", diagnostic))
                build_args = step.call_args_list[0].args[1]
                self.assertEqual("--defer-static-toc" in build_args, not diagnostic)


if __name__ == "__main__":
    unittest.main()
