import sys, tempfile, subprocess, os
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
REPO = Path('.').resolve()
work = Path(tempfile.mkdtemp(prefix='frozen-diag2-'))
proj = fixtures.two_chapter_project(work / 'proj')
out = proj / 'export-out'; out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'
p = subprocess.run([str(REPO/'dist'/'DocTool'/'doc-tool-cli.exe'), 'project-export',
                    '--project', str(proj), '--formats', 'html',
                    '--destination', str(out), '--no-refresh'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace',
                   env=env, timeout=900, cwd=str(work))
print('rc=', p.returncode)
print('=== STDERR (last 1500) ===')
print((p.stderr or '')[-1500:])
print('=== STDOUT (last 500) ===')
print((p.stdout or '')[-500:])