import sys, tempfile, inspect
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
from doc_tool.application import rd_surface as s
import doc_tool.application.workspace as w

work = Path(tempfile.mkdtemp(prefix='probe-rd2-'))
ws_root = work / 'ws'; ws_root.mkdir(parents=True)
for name in ('Alpha','Beta','Gamma'):
    fixtures.two_chapter_project(ws_root / name)
ws = w.create_workspace(ws_root, name='三成员')
print('created:', ws.workspace_id, 'members', len(getattr(ws,'members',[]) or []), 'file', (ws_root/'workspace.yml').is_file())
print('add_project sig:', inspect.signature(w.add_project))
loaded, msg = s.open_workspace(str(ws_root))
print('open_workspace:', loaded is not None, msg[:60] if msg else '')
g = s.collect_graph(ws_root, workspace=True)
print('graph:', type(g).__name__, 'nodes', len(getattr(g,'nodes',{}) or {}), 'edges', len(getattr(g,'edges',[]) or []))
rows = s.member_rows(loaded)
print('member_rows:', [(r.get('path'), r.get('available')) for r in rows])
print('workspace_state:', s.workspace_state(loaded))