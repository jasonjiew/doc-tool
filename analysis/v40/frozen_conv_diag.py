import sys, tempfile, subprocess, os
from pathlib import Path
REPO = Path('.').resolve()
work = Path(tempfile.mkdtemp(prefix='frozen-conv-'))
env = dict(os.environ); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'
CLI = REPO/'dist'/'DocTool'/'doc-tool-cli.exe'
src = work / 'in.md'; src.write_text('# 标题\n\n正文。\n', encoding='utf-8')
dest = work / 'out'; dest.mkdir(parents=True, exist_ok=True)
p = subprocess.run([str(CLI), 'convert', str(src), '--to', 'docx', '--target-dir', str(dest)],
                   capture_output=True, text=True, encoding='utf-8', errors='replace',
                   env=env, timeout=600, cwd=str(work))
print('rc=', p.returncode)
print('STDOUT:', (p.stdout or '')[:900])
print('STDERR:', (p.stderr or '')[-900:])