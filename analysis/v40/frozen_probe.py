import sys, tempfile, subprocess, os, json
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
REPO = Path('.').resolve()
work = Path(tempfile.mkdtemp(prefix='frozen-probe-'))
proj = fixtures.two_chapter_project(work / 'proj')
out = proj / 'export-out'
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'
CLI = REPO/'dist'/'DocTool'/'doc-tool-cli.exe'
for label, dest in (('abs', str(out)), ('missing-abs', str(proj/'nope')), ('proj-output', '')):
    args = [str(CLI), 'project-export', '--project', str(proj), '--formats', 'html', '--no-refresh']
    if dest:
        args += ['--destination', dest]
    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=env, timeout=600, cwd=str(work))
    mark = 'OK' if p.returncode == 0 else 'FAIL'
    print('---', label, mark, 'rc=', p.returncode)
    tail = ((p.stdout or '') + '|' + (p.stderr or '')).strip()
    print(tail[-260:].replace(chr(10), ' '))