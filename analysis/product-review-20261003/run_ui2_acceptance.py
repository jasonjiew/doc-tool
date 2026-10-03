"""Run existing acceptance checks with new, isolated evidence destinations."""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WITH_FONTS = os.environ.get("PRODUCT_REVIEW_LOAD_FONTS") == "1"
font_evidence = {}
if WITH_FONTS:
    from PySide6.QtGui import QFont, QFontDatabase, QRawFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    loaded = []
    for name in ("msyh.ttc", "msyhbd.ttc", "consola.ttf", "seguiemj.ttf"):
        font_path = Path("C:/Windows/Fonts") / name
        if font_path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            loaded.append({"path": str(font_path), "families": list(
                QFontDatabase.applicationFontFamilies(font_id)
            )})
    font = QFont("Microsoft YaHei", 10)
    raw = QRawFont.fromFont(font)
    supports_chinese = raw.isValid() and raw.supportsCharacter(ord("章"))
    if not supports_chinese:
        raise RuntimeError("Review font has no Chinese glyphs")
    app.setFont(font)
    font_evidence = {"loaded": loaded, "requested": font.family(),
                     "resolved": raw.familyName(), "supportsChineseGlyph": True,
                     "platform": "Qt offscreen", "realDpiImeWordTrial": False}

from scripts.tests import test_ui2_acceptance as acceptance

acceptance.EVIDENCE_DIR = Path(__file__).resolve().parent / (
    "ui2-acceptance-with-fonts" if WITH_FONTS else "ui2-acceptance"
)
acceptance.GEOMETRY_FILE = acceptance.EVIDENCE_DIR / "ui2-geometry.json"
acceptance.LOOP_FILE = acceptance.EVIDENCE_DIR / "ui2-closed-loop.json"
if WITH_FONTS:
    acceptance.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (acceptance.EVIDENCE_DIR / "font-environment.json").write_text(
        json.dumps(font_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )

if __name__ == "__main__":
    unittest.main(module=acceptance, verbosity=2)
