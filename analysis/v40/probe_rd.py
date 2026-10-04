import sys, tempfile
from pathlib import Path
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from scripts.tests import core_fixtures as fixtures
from doc_tool.application import rd_surface as s

work = Path(tempfile.mkdtemp(prefix='probe-rd-'))
ws_root = work / 'ws'; ws_root.mkdir(parents=True)
members = {}
for name in ('Alpha','Beta','Gamma'):
    members[name] = fixtures.two_chapter_project(ws_root / name)
idx = s.build_index([("第1章 引言/1.1 目的.md", "# 目的\n"), ], project_id='pid-Alpha')
print('index items:', len(getattr(idx, 'items', {}) or {}))
graph = s.empty_graph()
print('graph type:', type(graph).__name__, 'edges:', len(getattr(graph, 'edges', []) or []))
g2 = s.collect_graph(ws_root, workspace=True)
print('collect_graph:', type(g2).__name__)
ci = s.combined_index([('pid-Alpha', idx)])
print('combined_index:', type(ci).__name__)
print('item_rows:', len(s.item_rows(ci)))
print('matrix_view ok:', bool(s.matrix_view([], graph)))
print('impact_view ok:', bool(s.impact_view(None, None, graph)))