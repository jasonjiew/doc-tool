import sys
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
from pathlib import Path
import shutil, tempfile
from scripts.tests import core_fixtures as fixtures
work = Path(tempfile.mkdtemp(prefix="probe-main2c-"))
proj = fixtures.two_chapter_project(work / "proj")
print("project", proj)
for p in sorted(proj.rglob("*")):
    print("  ", p.relative_to(proj).as_posix())
shutil.rmtree(work, ignore_errors=True)