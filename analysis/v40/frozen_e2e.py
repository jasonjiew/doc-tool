import sys, tempfile, subprocess, shutil, os
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures

REPO = Path('.').resolve()
CLI = REPO / 'dist' / 'DocTool' / 'doc-tool-cli.exe'
work = Path(tempfile.mkdtemp(prefix='frozen-e2e-'))
proj = fixtures.two_chapter_project(work / 'proj')
out = proj / 'export-out'
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'
print('CLI exists:', CLI.is_file(), 'size MB', round(CLI.stat().st_size/1024/1024,1))

runs = []
for args in (
    ['project-export', '--project', str(proj), '--formats', 'docx,html',
     '--destination', str(out), '--no-refresh'],
    ['status', '--project', str(proj)],
):
    p = subprocess.run([str(CLI)] + args, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env, timeout=600)
    runs.append((args[0], p.returncode, (p.stdout or '')[-260:], (p.stderr or '')[-160:]))
    print('---', args[0], 'rc=', p.returncode)
    print((p.stdout or '')[-400:])
    if p.returncode != 0:
        print('STDERR:', (p.stderr or '')[-300:])

print('OUT dir files:', [q.name for q in out.rglob('*') if q.is_file()][:12])