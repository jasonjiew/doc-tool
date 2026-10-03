# -*- coding: utf-8 -*-
"""MAIN-A 1.1/1.3 probe: multi-source Markdown resource mapping (post-fix)."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from doc_tool.application.project_from_markdown import create_project_from_markdown  # noqa: E402
from doc_tool.application.content.index import ContentIndexService  # noqa: E402
from doc_tool.application.content.references import ReferenceScanner  # noqa: E402
from doc_tool.domain.manifest import ProjectManifest  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40

tmp = Path(tempfile.mkdtemp(prefix="main-a-"))
src_a = tmp / "srcA"
src_b = tmp / "srcB"
(src_a / "a").mkdir(parents=True)
(src_a / "b").mkdir(parents=True)
src_b.mkdir(parents=True)

(src_a / "a" / "logo.png").write_bytes(PNG + b"A-LOGO")
(src_a / "b" / "logo.png").write_bytes(PNG + b"B-LOGO")
(src_a / "image.png").write_bytes(PNG + b"A-IMAGE")
(src_b / "image.png").write_bytes(PNG + b"B-IMAGE")

(src_a / "1 kai.md").write_text("# kai\n\n![](a/logo.png)\n\n![](b/logo.png)\n\n![](image.png)\n", encoding="utf-8")
(src_b / "2 sheji.md").write_text("# sheji\n\n![](image.png)\n", encoding="utf-8")

project = tmp / "proj"
result = create_project_from_markdown(
    [src_a / "1 kai.md", src_b / "2 sheji.md"],
    project,
    asset_roots=[src_a, src_b],
)

print("ok=", result.ok)
print("copied=", sorted(result.copied_resources))
for item in result.warnings:
    print("   warn:", item)

manifest = ProjectManifest.load(project)
print("assetRoot=", manifest.paths.get("assetRoot"), "tableRoot=", manifest.paths.get("tableRoot"))
print("--- chapter links ---")
for name in result.chapters:
    print("   ", name, "::", (project / "content" / name).read_text(encoding="utf-8").replace(chr(10), " | "))

print("--- reference scan (dangling?) ---")
index = ContentIndexService(project / "content").build()
scanner = ReferenceScanner(index, assets_root=project / "assets")
scanner.scan_all()
for source, refs in sorted(index.references.items()):
    for ref in refs:
        if ref.kind == "image":
            print("   ", source, ref.target, "dangling=", ref.dangling)

print("--- identical content reuse ---")
tmp2 = Path(tempfile.mkdtemp(prefix="main-a2-"))
s1 = tmp2 / "p"
s2 = tmp2 / "q"
s1.mkdir()
s2.mkdir()
(s1 / "pic.png").write_bytes(PNG + b"SAME")
(s2 / "pic.png").write_bytes(PNG + b"SAME")
(s1 / "1.md").write_text("# one\n\n![](pic.png)\n", encoding="utf-8")
(s2 / "2.md").write_text("# two\n\n![](pic.png)\n", encoding="utf-8")
proj2 = tmp2 / "proj"
res2 = create_project_from_markdown([s1 / "1.md", s2 / "2.md"], proj2, asset_roots=[s1, s2])
print("   copied=", sorted(res2.copied_resources))
for name in res2.chapters:
    print("   ", name, "::", (proj2 / "content" / name).read_text(encoding="utf-8").replace(chr(10), " | "))

print("--- project copy readable offline ---")
offline = tmp / "offline-copy"
shutil.copytree(project, offline)
off_index = ContentIndexService(offline / "content").build()
off_scanner = ReferenceScanner(off_index, assets_root=offline / "assets")
off_scanner.scan_all()
dangling = [r.target for refs in off_index.references.values() for r in refs if r.kind == "image" and r.dangling]
print("   offline dangling=", dangling)

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)