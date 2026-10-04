import sys, tempfile, os, json
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
work = Path(tempfile.mkdtemp(prefix='frozen-diag-'))
proj = fixtures.two_chapter_project(work / 'proj')
out = proj / 'export-out'
out.mkdir(parents=True, exist_ok=True)

# 复刻 resolve_export_directory 的探测三步，逐项报告真实异常
steps = []
for label, target in (('preferred', out), ('proj-output', proj / 'output'),
                      ('user-exports', Path.home() / '.doc-tool' / 'exports')):
    rec = {'candidate': str(target)}
    try:
        target.mkdir(parents=True, exist_ok=True)
        rec['mkdir'] = 'ok'
    except OSError as exc:
        rec['mkdir'] = '{0}: {1}'.format(type(exc).__name__, exc)
    probe = target / '.doctool-write-probe'
    try:
        probe.write_text('', encoding='utf-8')
        rec['write'] = 'ok'
    except OSError as exc:
        rec['write'] = '{0}: {1}'.format(type(exc).__name__, exc)
    try:
        probe.unlink()
        rec['unlink'] = 'ok'
    except OSError as exc:
        rec['unlink'] = '{0}: {1}'.format(type(exc).__name__, exc)
    steps.append(rec)
print(json.dumps(steps, ensure_ascii=False, indent=1))