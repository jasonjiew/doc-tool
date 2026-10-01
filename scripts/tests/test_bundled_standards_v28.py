# -*- coding: utf-8 -*-
"""V2.8 5.1/9.4：\u89c4\u8303\u5305\u968f\u5305\u53d1\u5e03\u4e0e\u51bb\u7ed3\u6001\u8d44\u6e90\u5b9a\u4f4d\u3002

\u9a8c\u8bc1\u4e24\u4ef6\u4e8b\uff1a

1. \u8fd0\u884c\u65f6\u80fd\u627e\u5230\u968f\u5e94\u7528\u53d1\u5e03\u7684\u901a\u7528\u89c4\u8303\u5305\uff08\u6e90\u7801\u6001\u4e3a\u4ed3\u5e93 ``standards/``\uff0c
   \u51bb\u7ed3\u6001\u4e3a ``doc_tool/resources/standards``\uff09\uff1b
2. \u6253\u5305\u811a\u672c\u786e\u5b9e\u628a ``standards/`` \u6536\u8fdb\u4ea7\u7269\u7684 ``doc_tool/resources/standards``\u3002
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from doc_tool.application.standard_pack import (  # noqa: E402
    bundled_standards_root,
    list_bundled_packs,
    validate_pack_dir,
)


class BundledStandardsTests(unittest.TestCase):
    def test_bundled_root_resolves_in_source_tree(self):
        root = bundled_standards_root()
        self.assertIsNotNone(root, "源码态应能解析到仓库 standards/ 目录")
        self.assertTrue(root.is_dir())

    def test_bundled_packs_listed_and_valid(self):
        names = list_bundled_packs()
        self.assertEqual(
            sorted(names), ["generic-design", "generic-requirement", "generic-test"]
        )
        root = bundled_standards_root()
        for name in names:
            validation = validate_pack_dir(root / name)
            self.assertTrue(validation.ok, "{0}: {1}".format(name, validation.errors))

    def test_packaging_spec_ships_standards_directory(self):
        spec = (REPO_ROOT / "packaging" / "doc_tool.spec").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn(
            "doc_tool/resources/standards",
            spec,
            "冻结包必须随包发布通用规范包，否则冻结态无法从规范包起步",
        )
        self.assertIn('"standards"', spec)

    def test_missing_bundle_returns_none_without_crash(self):
        """\u4e24\u4e2a\u5019\u9009\u90fd\u4e0d\u5b58\u5728\u65f6\u8fd4\u56de None\uff0c\u4e0d\u5e94\u629b\u5f02\u5e38\u3002"""
        from unittest import mock

        with mock.patch(
            "doc_tool.application.standard_pack.Path.is_dir", return_value=False
        ):
            self.assertIsNone(bundled_standards_root())
            self.assertEqual(list_bundled_packs(), [])


if __name__ == "__main__":
    unittest.main()