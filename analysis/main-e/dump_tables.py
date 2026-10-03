# -*- coding: utf-8 -*-
"""MAIN-E probe: dump built table XML."""
from __future__ import annotations
import shutil, sys, tempfile, zipfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
for c in (str(REPO), str(REPO / "scripts"), str(REPO / "scripts" / "tests")):
    if c not in sys.path:
        sys.path.insert(0, c)
from lxml import etree
import test_project_build as T
from doc_tool.adapters.kernel import build_with_project
from doc_tool.domain.paths import ProjectPaths
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
def q(t): return "{{{0}}}{1}".format(W_NS, t)
tmp = Path(tempfile.mkdtemp(prefix="main-e-dump-"))
root = Path(T._setup_project(str(tmp / "项目")))
content = root / "content" / "requirement"
(content / "1 概述").mkdir(parents=True, exist_ok=True)
rows = chr(10).join("| {0} | 长表第 {0} 行 |".format(i) for i in range(1, 31))
(content / "1 概述" / "_index.md").write_text(
    "## 1.1 表格" + chr(10) + chr(10) + "| 项目 | 值 |" + chr(10) + "| --- | --- |" + chr(10)
    + "| 前导零 | 007 |" + chr(10) + chr(10) + "## 1.2 长表" + chr(10) + chr(10)
    + "| 序号 | 说明 |" + chr(10) + "| --- | --- |" + chr(10) + rows + chr(10),
    encoding="utf-8",
)
manifest = T._make_manifest(str(root))
out = build_with_project(manifest, ProjectPaths(root))
with zipfile.ZipFile(out) as z:
    xml = z.read("word/document.xml")
r = etree.fromstring(xml)
for i, t in enumerate(r.iter(q("tbl"))):
    trs = list(t.iter(q("tr")))
    print("table", i, "rows", len(trs))
    print(etree.tostring(trs[0], pretty_print=True).decode("utf-8")[:600])
shutil.rmtree(tmp, ignore_errors=True)