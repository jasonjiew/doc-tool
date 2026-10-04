import sys
sys.path.insert(0, ".")
from doc_tool.application.intake_contract import FORMAT_DOCX, ExportRequest, SCOPE_PROJECT
from doc_tool.application.export.layout_profile import LayoutProfile
req = ExportRequest(project_root="x", formats=[FORMAT_DOCX], source_mode="saved", destination="out")
print("layout_profile attr:", repr(getattr(req, "layout_profile", None)))
print("layout dict:", getattr(req, "layout", None))
p = LayoutProfile.from_dict(getattr(req, "layout", {}) or {})
print("profile.is_template:", p.is_template, "landscape:", p.landscape_chapters, "pagebreak:", p.page_break_before_chapter)
print("image_width:", p.image_width, "table_width:", p.table_width)