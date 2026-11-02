import sys
sys.path.insert(0, ".")

import unittest
from PySide6.QtWidgets import QApplication

from doc_tool.ui.content.web_preview_browser import _ACTIVE_BROWSERS
from scripts.tests import test_main_d_lint_scope

print("Browsers before:", len(_ACTIVE_BROWSERS))
suite = unittest.defaultTestLoader.loadTestsFromModule(test_main_d_lint_scope)
unittest.TextTestRunner().run(suite)
print("Browsers after:", len(_ACTIVE_BROWSERS))

for b in list(_ACTIVE_BROWSERS):
    print("Cleaning up browser:", b)
    b.cleanup()
    b.deleteLater()

app = QApplication.instance()
if app:
    app.sendPostedEvents()
    app.processEvents()

print("End of script")
