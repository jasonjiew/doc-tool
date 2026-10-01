import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from doc_tool.application.template_fill_plan import plan_template_fill, execute_template_fill
from doc_tool.domain.cancellation import CancellationToken
from doc_tool.domain.errors import CancelledError

class FillPlanTests(unittest.TestCase):
    def test_default_strict_missing_inputs_template_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / '章.md'
            source.write_text('# 新章\n中文 ![缺图](missing.png =10x20)\n```\n# 假标题\n```\n', encoding='utf-8')
            missing = root / 'missing.md'
            output = root / 'out.docx'
            output.write_bytes(b'old output')
            plan = plan_template_fill([source, missing], root / 'missing.docx', output, mapping={'gone': 1})
            self.assertTrue(plan.viable, plan.report())
            self.assertEqual(len(plan.inputs[0]['outline']), 1)
            self.assertEqual(plan.inputs[0]['images'], 1)
            self.assertEqual(plan.skipped, [str(missing)])
            self.assertNotEqual(plan.output, str(output))
            self.assertEqual(json.loads(plan.report('json'))['status'], '部分完成')
            self.assertFalse(plan_template_fill([source], 'absent', output, strict=True).viable)
            self.assertFalse(plan_template_fill([], 'absent', output).viable)
            self.assertFalse(plan_template_fill([source], 'absent', output, fallback_templates=[]).viable)
            before = source.read_bytes()
            result = execute_template_fill([source, missing], 'absent', output, refresh_fields=True)
            self.assertTrue(result.output.is_file())
            self.assertEqual(result.status, '部分完成')
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(output.read_bytes(), b'old output')
            token = CancellationToken()
            token.request_cancel()
            with self.assertRaises(CancelledError): execute_template_fill([source], 'absent', output, cancel_token=token)
            self.assertEqual(output.read_bytes(), b'old output')

    def test_cli_json_is_pure_and_changes_refresh(self):
        from doc_tool.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / '章.md'
            source.write_text('# one', encoding='utf-8')
            output = Path(tmp) / 'out.docx'
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                code = main(['template-fill', str(source), '--template', 'absent', '--output', str(output), '--dry-run', '--report-format', 'json'])
            self.assertEqual(code, 0)
            data = json.loads(capture.getvalue())
            self.assertTrue(data['viable'])
            self.assertFalse(output.exists())
            source.write_text('# changed', encoding='utf-8')
            result = execute_template_fill([source], data['template'], output)
            self.assertEqual(result.plan.inputs[0]['outline'][0][1], 'changed')

if __name__ == '__main__': unittest.main()
