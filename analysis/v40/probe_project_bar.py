import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from doc_tool.ui.project_bar import ProjectBar
from doc_tool.ui.workbench_state import ActionState, WorkbenchState, WorkView
closed = []
bar = ProjectBar(on_close_project=lambda: closed.append(True))
print("fresh: btn hidden", bar._close_btn.isHidden(), "action visible", bar._close_action.isVisible(), "enabled", bar._close_action.isEnabled())
summary = type("FakeSummary", (), {"manifest": None, "project_root": Path("D:/proj")})()
state = WorkbenchState(view=WorkView.IDLE, actions={"validate": ActionState(True, ""), "diag_build": ActionState(True, ""), "merge": ActionState(True, "")}, readiness_text="ready")
bar.render(summary, state)
print("after render: btn hidden", bar._close_btn.isHidden(), "btn visibleTo", bar._close_btn.isVisibleTo(bar), "action visible", bar._close_action.isVisible(), "enabled", bar._close_action.isEnabled())
print("menu pairs", [(a.text(), b.text()) for a, b in bar._overflow.menu_action_pairs])
print("hidden keys", bar._overflow.hidden_keys)
bar.reset()
print("after reset: btn hidden", bar._close_btn.isHidden(), "action visible", bar._close_action.isVisible(), "action enabled", bar._close_action.isEnabled())