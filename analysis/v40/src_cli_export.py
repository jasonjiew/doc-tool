import sys, tempfile, subprocess, os
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
REPO = Path('.').resolve()
work = Path(tempfile.mkdtemp(prefix='srccli-'))
proj = fixtures.two_chapter_project(work / 'proj')
out = proj / 'export-out'
env = dict(os.environ); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'
p = subprocess.run([sys.executable, str(REPO/'doc_tool_cli.py'), 'project-export',
                    '--project', str(proj), '--formats', 'html',
                    '--destination', str(out), '--no-refresh'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=600)
print('SOURCE CLI rc=', p.returncode)
print('STDOUT:', (p.stdout or '')[-400:])
print('STDERR:', (p.stderr or '')[-400:])
print('out files:', [q.name for q in out.rglob('*') if q.is_file()][:8])