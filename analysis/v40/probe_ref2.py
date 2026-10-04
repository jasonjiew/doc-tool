import sys, tempfile
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from scripts.tests import core_fixtures as fixtures
from doc_tool.application.content.index import ContentIndexService
from doc_tool.domain.manifest import ProjectManifest
from doc_tool.domain.paths import ProjectPaths

work = Path(tempfile.mkdtemp(prefix="probe-ref2-"))
proj = fixtures.two_chapter_project(work / "p")
paths = ProjectPaths(proj); m = ProjectManifest.load(proj)
content = paths.resolve(m.relative_content_root())
t = content / "第2章 设计" / "2.1 架构.md"
t.write_text("# 2.1 架构\n\n链接 [目的](../第1章 引言/1.1 目的.md)。\n", encoding="utf-8")
svc = ContentIndexService(content); idx = svc.build()
print("files:", sorted(idx.files))
for src, refs in idx.references.items():
    for r in refs:
        print("REF", src, r.source_line, r.kind, "->", r.target_rel_path, "|", repr(r.source_text)[:60])