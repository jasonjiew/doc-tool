# 本地审阅交付物 SHA-256 清单（V2.7～V2.9）

- 生效范围：实现 → 逐文件审查 → 基础设施修复 → 环境根因定位 → 跨版本集成修复（冻结态规范包）→ 最终验证之后的**最终交付物**
- 版本源：2.9.0（project schema 2）
- 测试：scripts/tests/run_tests.py —— **95 套件 = 磁盘全部测试文件**
- 打包：packaging/doc_tool.spec 已随包 ``doc_tool/resources/standards``；打包相关套件 5/5 通过
- 自检：``python tools/check_integrity.py`` 退出码 0
- 隔离产物：tools/patch_v27_build.py.broken（保留可追溯证据，不在产品包内）

| 文件 | SHA-256 |
|------|--------|
| docs/release/v27-acceptance.md | `e4fc820b43bbd20786e1708354a69fa76361fa7f3e083c5b67cf5ebc0ff3c89d` |
| docs/release/v28-acceptance.md | `c040ba20e38f8d5f6c73d527d5256f1493714e2aab81ce1d6479b3dbf92d47cb` |
| docs/release/v29-acceptance.md | `8f58e2e49afb6e9d1baf831899caf65b89455d679c04dbe662d8588e42b991e0` |
| docs/release/v27-v29-code-review.md | `8178ec324bc057adf11c5bfa1cc0bfbebc634cbbb21a239f8d65225ff64a56c9` |
| docs/release/v27-support-matrix.md | `652b5ca143a2dbb09ab74d19dcb48f06c471e7376261d51270dccb2bf0e6f45c` |
| docs/v29-traceability-guide.md | `ff6a7e936c269e0f8252ed5ee78f54ecaa03b3f4f3bf268256e9560d6c5bb2a7` |
| docs/使用说明.md | `f35cb12385f009c4b2c6fa774b98df7c87247798c11b4be35831fd23b6ec2b24` |
| docs/product-plan-execution.md | `d8a294112bffce85c365e98faf0c88984665aa90cd3d870e9881b3ffdfe84d48` |
| scripts/tests/run_tests.py | `d3d76f329d8a20780d51c032013247949e634acca2686fea727821f2118f75c3` |
| packaging/doc_tool.spec | `c7d8f21a54dffc230b2e5187de486ede2b0a43ef0e513eaf0a03fbbdddb4dda1` |
| tools/check_integrity.py | `3dbb108800f8147866c5e52b01e2afe0e5a1c690aa85deed4a234e0d92f72548` |
| tools/list_review_scope.py | `a6f2fa5bd93f7ead3e41b77c356f77e75fed7d923aa7115e4754ba90d1ebfe93` |
| tools/gen_v29_e2e_chain.py | `f36c0beaad4d1bfb594fa69c673a74d6d9782da0e982d48331da1c78839e79ee` |
| doc_tool/domain/version.py | `76a832ec08b9684ac9fa52b614465889be8aafc6c790e02cb46939f5f7e78fa8` |
| doc_tool/domain/ooxml.py | `8c18edeee02243bec477f1c44d1f774cdee251d9956077a45fe3fb8589225321` |
| doc_tool/application/standard_pack.py | `0f300741168a3ebf24b6dab87e4c6a0d9f5a71ad44fc583bec39d069533f7c5f` |
| doc_tool/application/settings.py | `d1ae86442001d5d6dbb5ba090a519309123de64293f1dec806c2f9577e05f206` |
| doc_tool/application/content/chapter_reorder.py | `a855890add69cb3eaee59db1423f02d6fce6c8a34b4c54f4158572eb79afc7f9` |
| doc_tool/application/content/item_actions.py | `2c09bc3edfb0639cc0ee2d4ac7887dc1bebb86f75a462a529d7d079dbaef71bd` |
| doc_tool/application/content/trace_matrix.py | `a0f098561b4256cac1a8ad97112997d16eadb23e193e92ffde045494da71a7ea` |
| doc_tool/application/content/reimport_preview.py | `c348664af4df481c9987c0f8f771697c5729bd7a04d29d10023957369bb92ed2` |
| doc_tool/application/project_from_pack.py | `2bd25d2f94ec95d37cb7b8244a0ebe88040183650fc3931674940757e1e92054` |
| doc_tool/application/project_from_markdown.py | `49ee2eb5a98c200abcc49e3974f29d4caf4dcd493e7f3368ccd3ca0441436328` |
| doc_tool/application/intake_word.py | `3a53cde3e594cdcd658ffccf4aaaf89cd1d76847af8809dc38cf2123138fe3ce` |
| docs/release/evidence/v29-e2e-chain.json | `f7d6fa0ee8437020e45e4245ca2d63debcf8fae1d7f82502b2d1a30f40db1edf` |
| docs/release/evidence/v29-performance.json | `7e6abbc35e34d39437d0e754696e64cd588661be7e70e8b3409a721063fd537a` |
| docs/release/evidence/v29-final-15.xml | `80a5af085d07327fb0b92b7a3764b64e70c98312aea411f0b7ad92f12ad97c00` |
| docs/release/evidence/v29-packaging-2.xml | `e082287d88ea72746b27aa61b737581d061415a6ed71a0dd0a89b28236050859` |

> 可用 Get-FileHash 就地重算核对。
| tools/gen_v29_frozen_upgrade.py | `8d05d3d061d0399afafbf05ce7d93919c8e19404fc03ea4980b4bb7b0a91edec` |
