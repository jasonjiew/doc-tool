import sys, tempfile, subprocess, os
from pathlib import Path
REPO = Path('.').resolve()
work = Path(tempfile.mkdtemp(prefix='frozen-w-'))
env = dict(os.environ); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'
CLI = REPO/'dist'/'DocTool'/'doc-tool-cli.exe'
# 用 convert 让冻结程序往指定目录写文件（不涉及项目/导出目录解析）
src = work / 'in.md'; src.write_text('# 标题\n\n正文。\n', encoding='utf-8')
for label, dest in (('temp-dir', work / 'out-temp'), ('repo-dir', REPO / 'tmp' / 'frozen-out')):
    dest.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([str(CLI), 'convert', str(src), '--to', 'docx',
                        '--target-dir', str(dest)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=env, timeout=600, cwd=str(work))
    print('---', label, 'rc=', p.returncode)
    print((p.stdout or '')[-200:].replace(chr(10),' '))
    print('ERR:', (p.stderr or '')[-260:].replace(chr(10),' '))
    print('files:', [q.name for q in dest.rglob('*') if q.is_file()][:4])