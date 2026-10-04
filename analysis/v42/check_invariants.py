import inspect
import sys

sys.path.insert(0, ".")
import doc_tool.application.content.index as I
import doc_tool.application.content.lint as L

src = inspect.getsource(I.ContentIndexService.discover_files)
print("lint deps:", len(L.RULE_DEPENDENCIES), "parser:", L.LINT_PARSER_VERSION)
print("per-suffix rglob restored:", "for suffix in MD_SUFFIXES" in src)
print("single-pass reverted:", 'rglob("*")' not in src)