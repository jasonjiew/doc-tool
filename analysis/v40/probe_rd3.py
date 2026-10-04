import sys, tempfile, inspect
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
from doc_tool.application import rd_surface as s
import doc_tool.application.workspace as w

work = Path(tempfile.mkdtemp(prefix='probe-rd3-'))
ws_root = work / 'ws'; ws_root.mkdir(parents=True)
ws = w.create_workspace(ws_root, name='三成员')
for name in ('Alpha','Beta','Gamma'):
    proj = fixtures.two_chapter_project(ws_root / name)
    member, copied = w.add_project(ws, proj, role='requirement')
    print(name, 'member', getattr(member,'relative_path',None), 'copied', copied)
ws.save()
print('workspace.yml:', (ws_root/'workspace.yml').is_file())
loaded, msg = s.open_workspace(str(ws_root))
print('open_workspace:', loaded is not None, (msg or '')[:50])
g = s.collect_graph(ws_root, workspace=True)
print('graph nodes/edges:', len(getattr(g,'nodes',{}) or {}), len(getattr(g,'edges',[]) or []))
rows = s.member_rows(loaded)
print('member_rows:', [(r.get('path'), r.get('available')) for r in rows])
print('state:', s.workspace_state(loaded))